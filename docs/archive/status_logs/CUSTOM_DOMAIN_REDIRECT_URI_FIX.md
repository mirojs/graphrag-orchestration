# Custom Domain Redirect URI Configuration Fix

## Issue Summary

**Error Message:**
```
AADSTS50011: The redirect URI 'https://test.hulkdesign.com/' specified in the request does not match the redirect URIs configured for the application 'b4aa58e1-8b31-445d-9fc9-1a1b6a044deb'.
```

**Root Cause:**
When using custom domains with Azure Container Apps, the app registrations must include **both** the default Azure Container Apps FQDN **and** the custom domain in their redirect URI configurations.

For MSAL.js (client-side authentication), the **SPA redirect URIs** are used, not the Web redirect URIs.

## Solution Applied (2025-11-26)

### rg-knowledgegraph (test.hulkdesign.com)

**App Registration ID:** `b4aa58e1-8b31-445d-9fc9-1a1b6a044deb`

**Updated Configuration:**
```json
{
  "spa": {
    "redirectUris": [
      "https://ca-cps-gw6br2ms6mxy-web.kindbush-ab1ad332.westus.azurecontainerapps.io",
      "https://test.hulkdesign.com"
    ]
  },
  "web": {
    "redirectUris": [
      "https://ca-cps-gw6br2ms6mxy-web.kindbush-ab1ad332.westus.azurecontainerapps.io/.auth/login/aad/callback",
      "https://test.hulkdesign.com/.auth/login/aad/callback"
    ]
  }
}
```

### rg-knowledgemap (map.hulkdesign.com)

**App Registration ID:** `8556f0c7-7a22-431f-a349-3b9df865f416`

**Updated Configuration:**
```json
{
  "spa": {
    "redirectUris": [
      "https://ca-cps-y22yd4amoxqu-web.whitepebble-0e537b84.swedencentral.azurecontainerapps.io",
      "https://map.hulkdesign.com"
    ]
  },
  "web": {
    "redirectUris": [
      "https://ca-cps-y22yd4amoxqu-web.whitepebble-0e537b84.swedencentral.azurecontainerapps.io/.auth/login/aad/callback",
      "https://map.hulkdesign.com/.auth/login/aad/callback"
    ]
  }
}
```

## Commands Used

### Update SPA Redirect URIs
```bash
az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/applications/$(az ad app show --id <APP_ID> --query id -o tsv)" \
  --headers "Content-Type=application/json" \
  --body '{
    "spa": {
      "redirectUris": [
        "https://<DEFAULT_FQDN>",
        "https://<CUSTOM_DOMAIN>"
      ]
    }
  }'
```

### Update Both SPA and Web Redirect URIs
```bash
az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/applications/$(az ad app show --id <APP_ID> --query id -o tsv)" \
  --headers "Content-Type=application/json" \
  --body '{
    "spa": {
      "redirectUris": [
        "https://<DEFAULT_FQDN>",
        "https://<CUSTOM_DOMAIN>"
      ]
    },
    "web": {
      "redirectUris": [
        "https://<DEFAULT_FQDN>/.auth/login/aad/callback",
        "https://<CUSTOM_DOMAIN>/.auth/login/aad/callback"
      ]
    }
  }'
```

### Verify Configuration
```bash
az ad app show --id <APP_ID> --query "{displayName:displayName, web:web.redirectUris, spa:spa.redirectUris}" --output json
```

## Understanding Redirect URI Types

### SPA Redirect URIs
- **Used by:** Client-side JavaScript apps using MSAL.js
- **Format:** `https://your-domain.com` (no path)
- **Purpose:** Where MSAL.js redirects after authentication
- **Critical for:** React/Angular/Vue apps with MSAL Browser library

### Web Redirect URIs
- **Used by:** Server-side web apps and Easy Auth
- **Format:** `https://your-domain.com/.auth/login/aad/callback`
- **Purpose:** OAuth callback endpoint for authorization code flow
- **Critical for:** Container Apps Easy Auth integration

## When to Configure Custom Domain Redirect URIs

You must update app registrations when:

1. **Adding a custom domain** to a Container App
2. **Changing the custom domain** name
3. **Deploying to a new environment** with different custom domain

## Troubleshooting

### Error: AADSTS50011 (Redirect URI Mismatch)

**Symptoms:**
- Authentication fails with redirect URI error
- User sees error page instead of login

**Check:**
```bash
# 1. Get the custom domain from Container App
az containerapp show --name <APP_NAME> --resource-group <RG> \
  --query "properties.configuration.ingress.customDomains[0].name" -o tsv

# 2. Check app registration redirect URIs
az ad app show --id <APP_ID> \
  --query "{spa:spa.redirectUris, web:web.redirectUris}" --output json

# 3. Verify they match
```

**Fix:**
- Ensure custom domain is in **SPA redirect URIs** (not just Web)
- Include both default FQDN and custom domain
- Don't add trailing slashes to SPA URIs
- Do include `/.auth/login/aad/callback` for Web URIs

### Error: AADSTS700016 (Application Not Found)

**Symptoms:**
- Authentication fails saying app doesn't exist
- Wrong tenant ID in error message

**Check:**
```bash
# Verify APP_WEB_CLIENT_ID matches app registration
az containerapp show --name <WEB_APP_NAME> --resource-group <RG> \
  --query "properties.template.containers[0].env[?name=='APP_WEB_CLIENT_ID'].value" -o tsv

az ad app show --id <EXPECTED_APP_ID> --query appId -o tsv
```

**Fix:**
- Update environment variable `APP_WEB_CLIENT_ID` to correct app registration ID
- Ensure app registration exists in correct tenant

## Future Deployments

When deploying to new environments with custom domains:

1. **Deploy infrastructure** (azd up)
2. **Configure custom domain** on Container App
3. **Get app registration IDs:**
   ```bash
   WEB_APP_ID=$(az containerapp show --name <WEB_APP_NAME> --resource-group <RG> \
     --query "properties.template.containers[0].env[?name=='APP_WEB_CLIENT_ID'].value" -o tsv)
   ```
4. **Update redirect URIs** using commands above
5. **Test authentication** on custom domain

## Portal Alternative

You can also update redirect URIs via Azure Portal:

1. Go to **Azure Portal** → **Microsoft Entra ID** → **App registrations**
2. Find your app (e.g., `ca-cps-gw6br2ms6mxy-web`)
3. Click **Authentication** in left menu
4. Under **Single-page application**:
   - Add `https://your-custom-domain.com`
5. Under **Web**:
   - Add `https://your-custom-domain.com/.auth/login/aad/callback`
6. Click **Save**

## Related Documentation

- [Azure AD Redirect URI Mismatch](https://aka.ms/redirectUriMismatchError)
- [MSAL.js Configuration](https://learn.microsoft.com/entra/identity-platform/msal-js-initializing-client-applications)
- [Container Apps Custom Domains](https://learn.microsoft.com/azure/container-apps/custom-domains-managed-certificates)
- [App Registration Redirect URI Types](https://learn.microsoft.com/entra/identity-platform/reply-url)

## Testing Checklist

After updating redirect URIs:

- [ ] Clear browser cache (Ctrl+Shift+R)
- [ ] Navigate to custom domain (e.g., https://test.hulkdesign.com)
- [ ] Click login or wait for redirect
- [ ] Should redirect to Microsoft login page
- [ ] After login, should redirect back to custom domain
- [ ] Check browser console for MSAL errors
- [ ] Verify token acquisition succeeds
- [ ] Test API calls with Authorization header
