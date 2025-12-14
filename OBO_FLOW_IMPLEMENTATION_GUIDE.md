# OBO Flow Implementation - Environment Variable Configuration

## Overview
This document describes the environment variables required for the On-Behalf-Of (OBO) authentication flow implementation.

## Implementation Details
We've implemented Microsoft's battle-tested OBO flow from [azure-search-openai-demo](https://github.com/Azure-Samples/azure-search-openai-demo) to fix the group name display issue.

**Root Cause**: User's frontend token has `aud: "api://your-app-id"` but Graph API requires `aud: "https://graph.microsoft.com"`.

**Solution**: Backend uses OBO flow to exchange the user's API token for a Graph API token.

## Required Environment Variables

Add these three environment variables to your Azure Container App configuration:

### 1. AZURE_SERVER_APP_ID
- **Description**: The Application (Client) ID of your backend API app registration
- **Where to find it**: Azure Portal → App registrations → [Your API App] → Overview → Application (client) ID
- **Example value**: `12345678-1234-1234-1234-123456789012`

### 2. AZURE_SERVER_APP_SECRET
- **Description**: Client secret for the backend API app registration
- **Where to find it**: 
  - Azure Portal → App registrations → [Your API App] → Certificates & secrets → Client secrets
  - If you don't have one, click "New client secret"
- **Example value**: `abc~DEF123456789_ghi.JKL.mnopq`
- **Security**: This is a sensitive value. Keep it secure and rotate regularly.

### 3. AZURE_TENANT_ID
- **Description**: Your Azure AD (Entra ID) tenant ID
- **Where to find it**: Azure Portal → Azure Active Directory → Overview → Tenant ID
- **Example value**: `87654321-4321-4321-4321-210987654321`

## Configuration Steps

### Option 1: Azure Portal
1. Navigate to your Container App: `ca-cps-gw6br2ms6mxy-api`
2. Go to Settings → Environment variables
3. Add each variable:
   - Click "+ Add"
   - Name: `AZURE_SERVER_APP_ID`
   - Value: [Your app ID]
   - Repeat for the other two variables
4. Click "Save"
5. Restart the container app

### Option 2: Azure CLI
```bash
# Get your resource group and container app name
RESOURCE_GROUP="your-resource-group"
CONTAINER_APP="ca-cps-gw6br2ms6mxy-api"

# Set environment variables
az containerapp update \
  --name $CONTAINER_APP \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars \
    AZURE_SERVER_APP_ID="your-server-app-id" \
    AZURE_SERVER_APP_SECRET="your-server-app-secret" \
    AZURE_TENANT_ID="your-tenant-id"
```

## Required Azure AD Permissions

After setting environment variables, an Azure AD admin must grant consent for:

### User.Read Delegated Permission
This is the ONLY permission needed for the backend OBO flow (not Group.Read.All).

**Grant consent steps**:
1. Azure Portal → App registrations → [Your API App]
2. API permissions → Add a permission
3. Microsoft Graph → Delegated permissions
4. Search for "User.Read" and check it
5. Click "Grant admin consent for [Your Organization]"

## Frontend Configuration
The frontend (msaConfig.ts) is already correctly configured with:
- `loginRequest.scopes` includes `"Group.Read.All"` (for direct Graph calls if needed)
- `tokenRequest.scopes` includes the backend API scope

No frontend changes needed.

## Code Changes Summary

### Files Modified
1. **src/ContentProcessorAPI/app/auth/authentication.py** (NEW)
   - Complete OBO flow implementation from Microsoft's azure-search-openai-demo
   - ~360 lines of battle-tested production code
   - Handles token validation, OBO exchange, group claims, overage scenarios

2. **src/ContentProcessorAPI/app/routers/groups.py** (MODIFIED)
   - Changed from passing user token directly → using OBO flow
   - Now exchanges user's API token for Graph API token before calling Graph
   - Maintains same API contract (no frontend changes needed)

## Testing
After deployment with environment variables configured:
1. Log in to the web app
2. Navigate to a page with the "Active Group" dropdown
3. Verify that real group names display (e.g., "Sales Team") instead of "Group abc12345..."
4. Check backend logs for OBO flow success messages:
   ```
   [GROUPS] ✅ OBO flow successful. User OID: xxx, Groups in token: N
   [GROUPS] ✅ Successfully acquired Graph API token via OBO
   [GROUPS] ✅ Resolved {group-id} to '{group-name}' (from displayName field)
   ```

## Troubleshooting

### Error: "Authentication not configured. Missing environment variables."
- **Cause**: One or more required environment variables are missing
- **Fix**: Add all three environment variables as described above

### Error: "OBO token exchange failed"
- **Cause**: Incorrect app ID/secret, or missing permissions
- **Fix**: 
  1. Verify AZURE_SERVER_APP_ID matches your API app registration
  2. Verify AZURE_SERVER_APP_SECRET is valid and not expired
  3. Grant User.Read delegated permission with admin consent

### Error: "Invalid audience"
- **Cause**: Token audience mismatch
- **Fix**: Verify the frontend is requesting tokens with the correct scope (backend API scope)

## Security Benefits
- **User-scoped access**: Users can only see groups they belong to (vs tenant-wide access with app-only tokens)
- **Audit trail**: All Graph API calls are associated with the user's identity
- **Least privilege**: Only requires User.Read permission (not Group.Read.All for backend)
- **Token security**: Backend tokens never leave the server

## Reference
- **Microsoft's Implementation**: https://github.com/Azure-Samples/azure-search-openai-demo
- **OBO Flow Documentation**: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
- **Previous Documentation**: MICROSOFT_AUTH_ALIGNMENT_COMPLETE.md (documented delegated approach)
