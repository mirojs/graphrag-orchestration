# Architecture: EasyAuth Token Refresh on Azure Container Apps

**Date:** 2026-03-04  
**Status:** Implemented & Live  
**Affects:** `graphrag-api` (B2B), `graphrag-api-b2c` (CIAM), Frontend SPA

---

## Problem

Users experienced session expiration after ~60 minutes, resulting in 401 errors and blank pages. The root cause was incomplete EasyAuth configuration across both B2B and B2C Container App deployments.

## Key Difference: App Service vs Container Apps

On **Azure App Service**, the token store uses built-in file storage (`D:\home`). Tokens persist automatically, and `.auth/refresh` works out of the box once a client secret is configured.

On **Azure Container Apps**, there is **no built-in persistent filesystem**. The token store requires an **external Azure Blob Storage** container with a SAS URL. Without it, EasyAuth cannot persist refresh tokens and `.auth/refresh` returns 401.

## Key Difference: B2B (Entra ID) vs B2C (CIAM / Entra External ID)

### ⚠️ CRITICAL: CIAM Does NOT Support Nonce Validation

Standard Entra ID (B2B) supports the full EasyAuth feature set:
- `offline_access` scope → Azure AD issues a refresh token
- `response_type=code` → authorization code flow
- Nonce validation → replay attack protection
- `.auth/refresh` endpoint → silent token renewal

**CIAM (Entra External ID) does NOT support:**
- Nonce validation (`validateNonce: true`) — CIAM does not include a `nonce` claim in id_tokens

**CIAM DOES support (confirmed via OIDC discovery `scopes_supported`):**
- `offline_access` scope — **required** for EasyAuth to get a refresh token
- `response_type=code` — supported but optional (EasyAuth auto-selects when client secret is present)
- Token store with blob storage
- `.auth/refresh` endpoint (when a refresh token exists)

### AADSTS900144 Root Cause (Fixed 2026-03-04)

After initial implementation, B2C users saw `AADSTS900144: missing client_id` ~60 minutes after login. Root cause: we initially added `offline_access` + `nonce` together, both broke login, so we removed both. But only `nonce` was the culprit. Without `offline_access`, CIAM never issued a refresh token. When EasyAuth tried to refresh after the access token expired (~60 min), the malformed request to the CIAM token endpoint failed with AADSTS900144.

**Fix:** Add `offline_access` back WITHOUT nonce validation.

### What CIAM Supports

| Setting | B2B (Entra ID) | B2C (CIAM) |
|---|---|---|
| `clientSecretSettingName` | ✅ Required | ✅ Required |
| `offline_access` scope | ✅ Required | ✅ Required |
| `response_type=code` | ✅ Used | ⚠️ Optional (auto from client secret) |
| `nonce.validateNonce` | ✅ Recommended | ❌ Breaks login (no nonce in id_token) |
| `tokenStore` with blob storage | ✅ Required | ✅ Required |
| `tokenRefreshExtensionHours` | ✅ Recommended (72h) | ✅ Safe to set |
| `cookieExpiration` (FixedTime) | ✅ Recommended (8h) | ✅ Safe to set |
| `.auth/refresh` endpoint | ✅ Works | ✅ Works (with offline_access) |

## Architecture: Six Fixes Applied

### 1. Backend Bicep: `container-app.bicep`

Added conditional EasyAuth settings based on `authType`:
- **B2B only:** `response_type=code`, `nonce` validation
- **B2B + B2C:** `offline_access` scope in `loginParameters`
- **Both:** `clientSecretSettingName`, blob token store, `cookieExpiration`, `tokenRefreshExtensionHours`

### 2. Frontend Bicep: `container-apps-auth.bicep`

Added `tokenRefreshExtensionHours: 72`, `cookieExpiration` (8h FixedTime), and `nonce` validation to the frontend Container App's EasyAuth config.

### 3. Infrastructure: `main.bicep` + `main.parameters.json`

Wired `authClientSecret` (B2B) and `b2cClientSecret` as Container App secrets. Added `tokenStoreSasSecretName` parameter to pass the blob storage SAS URL secret name to both B2B and B2C modules.

### 4. Frontend: 401 Auto-Retry (`api.ts`)

Added `fetchWithAuthRetry()` wrapper that:
1. Catches 401 responses
2. Calls `.auth/refresh` to renew the token
3. Retries the original request once
4. Falls back to login redirect if refresh fails

Applied to all authenticated API calls (chat, upload, file operations, history).

### 5. Frontend: Proactive Token Refresh (`authConfig.ts`)

Added a background timer that calls `.auth/refresh` **5 minutes before token expiry**, preventing users from ever hitting a 401. Re-schedules itself after each successful refresh.

### 6. Backend: JWT Expiry Verification (`auth.py`)

Enabled `verify_exp: True` in `pyjwt.decode()`. Previously, expired tokens were accepted because `verify_signature: False` also disabled expiry checks. This adds defense-in-depth.

## Infrastructure: Blob Storage Token Store

Both Container Apps use `neo4jstorage21224` (in `rg-graphrag-feature`) with:
- **Container:** `easyauth-tokens`
- **Access:** SAS URL stored as Container App secret `token-store-sas`
- **Identity:** System-assigned managed identity with `Storage Blob Data Contributor` role

## Files Changed

| File | Change |
|---|---|
| `infra/core/host/container-app.bicep` | Conditional B2B/B2C EasyAuth, blob token store, session management |
| `infra/main.bicep` | Wired `authClientSecret`, `tokenStoreSasSecretName` |
| `infra/main.parameters.json` | Added `authClientSecret` parameter |
| `frontend/infra/core/host/container-apps-auth.bicep` | Added session management settings |
| `frontend/app/frontend/src/api/api.ts` | `fetchWithAuthRetry()` wrapper |
| `frontend/app/frontend/src/authConfig.ts` | Proactive background refresh timer |
| `src/api_gateway/middleware/auth.py` | `verify_exp: True` in JWT decode |

## Debugging Checklist

If token expiration issues return:

1. **Check EasyAuth config:** `az containerapp auth show -n <app> -g rg-graphrag-feature`
   - B2B: must have `clientSecretSettingName`, `offline_access`, `nonce`, blob storage
   - B2C: must have `clientSecretSettingName`, `offline_access`, blob storage. Must NOT have `nonce`
2. **Check secrets exist:** `az containerapp secret list -n <app> -g rg-graphrag-feature`
   - B2B: `aad-client-secret`, `token-store-sas`
   - B2C: `microsoft-provider-authentication-secret`, `token-store-sas`
3. **Check blob storage:** `az storage container list --account-name neo4jstorage21224 --auth-mode login`
   - Container `easyauth-tokens` must exist
4. **Check SAS URL expiry:** SAS URLs expire — regenerate if needed
5. **Check managed identity role:** Both container apps need `Storage Blob Data Contributor` on `neo4jstorage21224`
6. **Check client secret expiry:** `az ad app show --id <client-id> --query "passwordCredentials[].endDateTime"`
