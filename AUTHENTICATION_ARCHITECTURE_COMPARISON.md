# Authentication Architecture Comparison: rg-knowledgemap vs rg-knowledgegraph

## Executive Summary

**Both environments use the SAME hybrid authentication pattern** (Easy Auth + MSAL-based Entra ID), but rg-knowledgegraph has additional environment variables that explicitly enable the MSAL authentication flow in the React frontend. The core architecture is identical across both deployments.

## Environment Configurations

### rg-knowledgemap (swedencentral)
- **Resource Group:** rg-knowledgemap
- **Container Apps:** ca-cps-y22yd4amoxqu-api, ca-cps-y22yd4amoxqu-web
- **App Registrations:** 2 (API + Web, both with identifierUris)
- **Easy Auth Status:** ✅ Enabled
- **MSAL Environment Variables:** ✅ Present (APP_WEB_CLIENT_ID, APP_WEB_AUTHORITY, APP_WEB_SCOPE, APP_API_SCOPE)
- **Additional Auth Flags:** ❌ Missing (REACT_APP_AUTH_ENABLED, APP_AUTH_ENABLED)

### rg-knowledgegraph (westus)
- **Resource Group:** rg-knowledgegraph
- **Container Apps:** ca-cps-gw6br2ms6mxy-api, ca-cps-gw6br2ms6mxy-web
- **App Registrations:** 2 (API + Web, both with identifierUris)
- **Easy Auth Status:** ✅ Enabled
- **MSAL Environment Variables:** ✅ Present (APP_WEB_CLIENT_ID, APP_WEB_AUTHORITY, APP_WEB_SCOPE, APP_API_SCOPE)
- **Additional Auth Flags:** ✅ Present (REACT_APP_AUTH_ENABLED=true, APP_AUTH_ENABLED=true)

## App Registrations Details

### rg-knowledgemap App Registrations

**API App Registration:**
```json
{
  "appId": "89cf18d0-6a50-42ea-825f-fbc8f655c725",
  "displayName": "ca-cps-y22yd4amoxqu-api",
  "identifierUris": ["api://89cf18d0-6a50-42ea-825f-fbc8f655c725"],
  "signInAudience": "AzureADMyOrg",
  "web.redirectUris": [
    "https://ca-cps-y22yd4amoxqu-api.whitepebble-0e537b84.swedencentral.azurecontainerapps.io/.auth/login/aad/callback"
  ]
}
```

**Web App Registration:**
```json
{
  "appId": "8556f0c7-7a22-431f-a349-3b9df865f416",
  "displayName": "ca-cps-y22yd4amoxqu-web",
  "identifierUris": ["api://8556f0c7-7a22-431f-a349-3b9df865f416"],
  "signInAudience": "AzureADMyOrg",
  "spa.redirectUris": [
    "https://ca-cps-y22yd4amoxqu-web.whitepebble-0e537b84.swedencentral.azurecontainerapps.io"
  ]
}
```

**Note:** Web app has different client IDs in environment:
- Environment variable `APP_WEB_CLIENT_ID=8b0cba30-011d-4522-a1c0-b0663ae659c0`
- Different from app registration ID `8556f0c7-7a22-431f-a349-3b9df865f416`
- This mismatch may indicate manual configuration changes

### rg-knowledgegraph App Registrations

**API App Registration:**
```json
{
  "appId": "519dd9e8-25b9-494b-ac7f-e90b4f4dd284",
  "displayName": "ca-cps-gw6br2ms6mxy-api",
  "identifierUris": ["api://519dd9e8-25b9-494b-ac7f-e90b4f4dd284"],
  "signInAudience": "AzureADMyOrg",
  "web.redirectUris": [
    "https://ca-cps-gw6br2ms6mxy-api.kindbush-ab1ad332.westus.azurecontainerapps.io/.auth/login/aad/callback"
  ]
}
```

**Web App Registration:**
```json
{
  "appId": "b4aa58e1-8b31-445d-9fc9-1a1b6a044deb",
  "displayName": "ca-cps-gw6br2ms6mxy-web",
  "identifierUris": ["api://b4aa58e1-8b31-445d-9fc9-1a1b6a044deb"],
  "signInAudience": "AzureADMyOrg",
  "spa.redirectUris": [
    "https://ca-cps-gw6br2ms6mxy-web.kindbush-ab1ad332.westus.azurecontainerapps.io"
  ]
}
```

**Correct configuration:** Environment variables match app registration IDs

## Environment Variables Comparison

### rg-knowledgemap Web Container
```bash
APP_API_BASE_URL=https://ca-cps-y22yd4amoxqu-api.whitepebble-0e537b84.swedencentral.azurecontainerapps.io
APP_WEB_CLIENT_ID=8b0cba30-011d-4522-a1c0-b0663ae659c0
APP_WEB_AUTHORITY=https://login.microsoftonline.com//ecaa729a-f04c-4558-a31a-ab714740ee8b
APP_WEB_SCOPE=api://ab68a9c3-584a-42bf-b883-a15c1000f71b/user_impersonation
APP_API_SCOPE=api://ab68a9c3-584a-42bf-b883-a15c1000f71b/user_impersonation
APP_CONSOLE_LOG_ENABLED=false
```

### rg-knowledgegraph Web Container
```bash
APP_API_BASE_URL=https://ca-cps-gw6br2ms6mxy-api.kindbush-ab1ad332.westus.azurecontainerapps.io
APP_WEB_CLIENT_ID=b4aa58e1-8b31-445d-9fc9-1a1b6a044deb
APP_WEB_AUTHORITY=https://login.microsoftonline.com//ecaa729a-f04c-4558-a31a-ab714740ee8b
APP_WEB_SCOPE=api://b4aa58e1-8b31-445d-9fc9-1a1b6a044deb/user_impersonation
APP_API_SCOPE=api://519dd9e8-25b9-494b-ac7f-e90b4f4dd284/user_impersonation
APP_CONSOLE_LOG_ENABLED=true
REACT_APP_AUTH_ENABLED=true  # ← ADDITIONAL
APP_AUTH_ENABLED=true         # ← ADDITIONAL
REACT_APP_CONSOLE_LOG_ENABLED=true
```

## Authentication Flow Pattern (azure-search-openai-demo Reference)

Both environments follow the **dual authentication pattern** from the reference architecture:

### 1. **Container Apps Easy Auth (Platform-Level)**
- **Purpose:** Protects the ingress endpoint with Azure AD authentication
- **Configuration:** `platform.enabled=true`, `unauthenticatedClientAction=RedirectToLoginPage`
- **How it works:**
  - All HTTP requests hit Easy Auth middleware first
  - Unauthenticated users redirected to `/.auth/login/aad/callback`
  - Sets `X-MS-TOKEN-AAD-ID-TOKEN` and other auth headers
  - Token stored in Container Apps token store (see `microsoft-provider-authentication-secret`)

### 2. **MSAL.js Client-Side Authentication (Application-Level)**
- **Purpose:** Acquire tokens for API calls with custom scopes (group isolation)
- **Configuration:** Environment variables (`APP_WEB_CLIENT_ID`, `APP_WEB_AUTHORITY`, `APP_WEB_SCOPE`)
- **How it works:**
  - React app uses `@azure/msal-browser` to authenticate users
  - Acquires access tokens with scope `api://{API_APP_ID}/user_impersonation`
  - Includes tokens in `Authorization: Bearer {token}` headers
  - Backend validates tokens and extracts group claims

### Why Both Are Needed?

**Easy Auth alone is insufficient for group isolation** because:
1. Easy Auth validates the user is authenticated (any valid tenant user)
2. But it doesn't enforce custom scopes or extract group membership claims
3. Group-based data isolation requires custom scopes like `api://xxx/user_impersonation`

**MSAL provides the application-level control:**
1. Frontend can request specific scopes during token acquisition
2. Backend can validate tokens contain required scopes and group claims
3. Enables fine-grained authorization beyond basic authentication

## Key Differences Explained

### The Missing Environment Variables in rg-knowledgemap

The **only meaningful difference** is:
```bash
# rg-knowledgegraph has these, rg-knowledgemap doesn't:
REACT_APP_AUTH_ENABLED=true
APP_AUTH_ENABLED=true
```

**Impact Analysis:**

1. **Frontend Behavior (`REACT_APP_AUTH_ENABLED`)**
   - When `true`: React app enables MSAL authentication flow, shows login UI, acquires tokens
   - When `false` or missing: React app may skip MSAL initialization, rely solely on Easy Auth cookies
   - **Risk for rg-knowledgemap:** May not be acquiring proper access tokens for API calls with group scopes

2. **Backend Behavior (`APP_AUTH_ENABLED`)**
   - When `true`: Backend validates `Authorization` header tokens using MSAL
   - When `false` or missing: Backend may only check Easy Auth headers (`X-MS-TOKEN-AAD-ID-TOKEN`)
   - **Risk for rg-knowledgemap:** Group isolation may not be enforced if backend doesn't validate group claims

### Why Both Environments "Work"

Both environments appear functional because:

1. **Easy Auth provides baseline protection** - both environments block unauthenticated access
2. **MSAL configuration is still present** in both environments (APP_WEB_CLIENT_ID, etc.)
3. **Code may have fallback logic** - If `REACT_APP_AUTH_ENABLED` is undefined, code might default to `true`

### Potential Issues with rg-knowledgemap

Without explicit `REACT_APP_AUTH_ENABLED=true`:

1. **Group isolation may be bypassed:**
   - Frontend might not include proper `Authorization: Bearer` tokens
   - Backend might accept requests with only Easy Auth headers
   - Users from different groups could potentially access each other's data

2. **Token scope issues:**
   - API calls might use Easy Auth cookie authentication instead of OAuth tokens
   - Missing required scopes like `user_impersonation` in requests

3. **Audit trail gaps:**
   - Backend logging might not capture user group membership correctly
   - Compliance requirements for data isolation not met

## Client ID Mismatch in rg-knowledgemap

**Critical Finding:**
```bash
# Environment variable points to:
APP_WEB_CLIENT_ID=8b0cba30-011d-4522-a1c0-b0663ae659c0

# But app registration is:
Web App Registration ID: 8556f0c7-7a22-431f-a349-3b9df865f416
```

**Implications:**
- Frontend MSAL configuration references a **different app registration** (`8b0cba30...`) than what exists (`8556f0c7...`)
- This could be:
  - **Scenario A:** An old/deleted app registration still referenced in environment
  - **Scenario B:** A manually created app registration not visible in current query results
  - **Scenario C:** A copy-paste error from another environment

**Recommendation:** Verify which client ID is correct and update environment variable to match

## API Scope Configuration Analysis

### rg-knowledgemap
```bash
APP_WEB_SCOPE=api://ab68a9c3-584a-42bf-b883-a15c1000f71b/user_impersonation
APP_API_SCOPE=api://ab68a9c3-584a-42bf-b883-a15c1000f71b/user_impersonation
```
- Both scopes point to `ab68a9c3...` (not matching current app registrations)
- **Issue:** This app ID doesn't match either the API app (`89cf18d0...`) or Web app (`8556f0c7...`)

### rg-knowledgegraph
```bash
APP_WEB_SCOPE=api://b4aa58e1-8b31-445d-9fc9-1a1b6a044deb/user_impersonation
APP_API_SCOPE=api://519dd9e8-25b9-494b-ac7f-e90b4f4dd284/user_impersonation
```
- Scopes match actual app registration IDs
- `APP_WEB_SCOPE` = Web App ID (`b4aa58e1...`)
- `APP_API_SCOPE` = API App ID (`519dd9e8...`)
- **Correct configuration**

## Recommendations

### Immediate Actions for rg-knowledgemap

1. **Add missing environment variables:**
   ```bash
   az containerapp update \
     --name ca-cps-y22yd4amoxqu-web \
     --resource-group rg-knowledgemap \
     --set-env-vars \
       "REACT_APP_AUTH_ENABLED=true" \
       "APP_AUTH_ENABLED=true" \
       "REACT_APP_CONSOLE_LOG_ENABLED=true"
   ```

2. **Fix client ID mismatch:**
   - Verify the correct Web App client ID (check Azure Portal app registrations)
   - Update to match actual app registration:
   ```bash
   az containerapp update \
     --name ca-cps-y22yd4amoxqu-web \
     --resource-group rg-knowledgemap \
     --set-env-vars \
       "APP_WEB_CLIENT_ID=8556f0c7-7a22-431f-a349-3b9df865f416"
   ```

3. **Fix API scope configuration:**
   - Update scopes to match current app registrations:
   ```bash
   az containerapp update \
     --name ca-cps-y22yd4amoxqu-web \
     --resource-group rg-knowledgemap \
     --set-env-vars \
       "APP_WEB_SCOPE=api://8556f0c7-7a22-431f-a349-3b9df865f416/user_impersonation" \
       "APP_API_SCOPE=api://89cf18d0-6a50-42ea-825f-fbc8f655c725/user_impersonation"
   ```

4. **Test group isolation:**
   - Create test users in different groups
   - Upload documents with group-specific access
   - Verify users cannot access other groups' data
   - Run `python test_database_isolation.py` if available

### Long-Term Standardization

1. **Document the authentication pattern** in deployment guides
2. **Update IaC templates** (Bicep/ARM) to include all required environment variables
3. **Add deployment validation** to check for required auth variables
4. **Implement end-to-end tests** for group isolation before production deployments

## Reference Architecture Comparison

Based on `azure-search-openai-demo` pattern:

| Component | azure-search-openai-demo | rg-knowledgegraph | rg-knowledgemap |
|-----------|-------------------------|-------------------|-----------------|
| App Registrations | Server + Client | API + Web (2) | API + Web (2) |
| Easy Auth | Optional (can disable with `AZURE_DISABLE_APP_SERVICES_AUTHENTICATION`) | Enabled | Enabled |
| MSAL.js Frontend | Required for group isolation | Configured | Configured (but flag missing) |
| MSAL Backend | Required for token validation | Configured | Configured (but flag missing) |
| Group Claims | Via custom scopes | Via `user_impersonation` scope | Via `user_impersonation` scope |
| Environment Variables | `AZURE_USE_AUTHENTICATION`, `AZURE_ENFORCE_ACCESS_CONTROL` | `APP_AUTH_ENABLED`, `REACT_APP_AUTH_ENABLED` | Missing auth flags |

**Key Insight:** Both your environments follow the reference architecture's **hybrid pattern** (Easy Auth + MSAL), but rg-knowledgemap may have incomplete configuration due to missing environment variables and client ID mismatches.

## Testing Checklist

To verify both environments are truly equivalent:

- [ ] Check frontend MSAL initialization logs (look for "MSAL initialized" in browser console)
- [ ] Verify `Authorization: Bearer` headers in API requests (Network tab → Headers)
- [ ] Test group isolation:
  - [ ] User A uploads document in Group 1
  - [ ] User B (Group 2) should NOT see document
  - [ ] User C (Group 1) SHOULD see document
- [ ] Check backend token validation logs (search for "token validation" or "group_id" in API logs)
- [ ] Verify Cosmos DB partition key enforcement (all queries include `partition_key=group_id`)

## Conclusion

**Your observation was partially correct** - there are configuration differences between the two environments, but **both have 2 app registrations**. The real issues are:

1. **rg-knowledgemap is missing explicit auth enablement flags** (`REACT_APP_AUTH_ENABLED`, `APP_AUTH_ENABLED`)
2. **rg-knowledgemap has client ID mismatches** between environment variables and actual app registrations
3. **Both environments use the same hybrid authentication pattern** (Easy Auth + MSAL)

The environments may both "work" currently because:
- Easy Auth provides baseline protection for both
- Code might have sensible defaults when auth flags are missing
- But **group isolation may not be properly enforced** in rg-knowledgemap

**Recommended Action:** Follow the "Immediate Actions" steps above to bring rg-knowledgemap into alignment with rg-knowledgegraph's correct configuration.
