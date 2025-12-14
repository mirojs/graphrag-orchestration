# Group Switcher Debug Status - October 21, 2025

## Current Issue
**Problem:** Group Switcher is not visible in the header despite authentication working and no errors showing.

## What We've Confirmed ✅

### 1. Deployment Status
- **Repository:** Reset to commit `af6bd3e9` (Centralized Group Change Handling)
- **Deployed Revision:** `ca-cps-gw6br2ms6mxy-web--0000009` (latest)
- **Location:** West US
- **Auth Working:** No 401 errors, authentication is functional

### 2. Code Status
- `.env` file: `REACT_APP_AUTH_ENABLED = true` (hardcoded, correct)
- GroupSelector component: Properly imported in `Header.tsx` at line 32
- GroupSelector usage: Conditionally rendered at line 158-159 based on `authEnabled` flag
- Component export: Correctly exported from `GroupSelector.tsx`

### 3. Browser Investigation Results
**Element exists but empty:**
```javascript
document.querySelector('.headerGroupSelector')  // ✅ Returns element
el.innerHTML  // ❌ Returns '' (empty!)
el.getBoundingClientRect()  // {width: 0, height: 0} - no content
el.querySelector('button')  // null - no dropdown rendered
window.getComputedStyle(el).display  // 'block' ✅
window.getComputedStyle(el).visibility  // 'visible' ✅
```

**Conclusion:** The `<div class="headerGroupSelector">` wrapper IS rendering, but the `<GroupSelector />` component inside is returning `null` or empty content.

## Root Cause Identified 🎯

### GroupSelector.tsx Logic
Located at: `src/ContentProcessorWeb/src/Components/GroupSelector.tsx`

**The component returns `null` when:**
```typescript
if (loading || userGroups.length === 0) {
  return null;  // ← Nothing renders!
}
```

**This means one of two things:**
1. **`loading === true`** - Still fetching groups
2. **`userGroups.length === 0`** - No groups available (most likely)

## What Needs Investigation 🔍

### 1. GroupContext Data Source
**File:** `src/ContentProcessorWeb/src/contexts/GroupContext.tsx`

**Questions to answer:**
- How does `GroupContext` fetch user groups?
- What API endpoint does it call?
- Is it using Microsoft Graph API or a custom backend endpoint?
- What authentication token is it using?

### 2. Backend API Logs
**Container:** `ca-cps-gw6br2ms6mxy-api`

**Check for:**
- 401/403 errors when fetching groups
- Microsoft Graph API permission errors
- Managed Identity authentication failures
- Endpoint: `/api/groups/*` or similar

### 3. Microsoft Graph Permissions
**Post-deployment script:** `infra/scripts/post_deployment.sh` (lines 46-83)

**Configured permission:**
- `Group.Read.All` (App Role ID: `5b567255-7703-4780-807c-7be8301ae99b`)
- Assigned to: API container app's managed identity

**Verify:**
- Was `post_deployment.sh` run after deployment?
- Does the managed identity actually have Graph permissions?
- Run: `az rest --method GET --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$API_PRINCIPAL_ID/appRoleAssignments"`

## Next Steps - Quick Fix Checklist 📋

### Option 1: Run Graph Permissions Script
```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/infra/scripts
./post_deployment.sh
```

### Option 2: Manual Graph Permission Assignment
```bash
# 1. Get API principal ID
API_PRINCIPAL_ID=$(az containerapp show \
  --name ca-cps-gw6br2ms6mxy-api \
  --resource-group rg-knowledgegraph \
  --query "identity.principalId" -o tsv)

# 2. Get Graph service principal ID
GRAPH_SP_ID=$(az ad sp list --filter "appId eq '00000003-0000-0000-c000-000000000000'" --query "[0].id" -o tsv)

# 3. Assign Group.Read.All permission
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$API_PRINCIPAL_ID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{\"principalId\":\"$API_PRINCIPAL_ID\",\"resourceId\":\"$GRAPH_SP_ID\",\"appRoleId\":\"5b567255-7703-4780-807c-7be8301ae99b\"}"
```

### Option 3: Check API Logs
```bash
az containerapp logs show \
  --name ca-cps-gw6br2ms6mxy-api \
  --resource-group rg-knowledgegraph \
  --tail 100 \
  --follow false
```
Look for: Graph API errors, 401s, permission errors

### Option 4: Debug Frontend GroupContext
1. Open browser DevTools Console
2. Add breakpoint in `GroupContext.tsx` where groups are fetched
3. Check Network tab for group API calls
4. Verify response data

## Files to Review When You Return

### Frontend
- `src/ContentProcessorWeb/src/contexts/GroupContext.tsx` - How groups are loaded
- `src/ContentProcessorWeb/src/Components/GroupSelector.tsx` - Line ~92: `if (loading || userGroups.length === 0) return null`
- `src/ContentProcessorWeb/src/Components/Header/Header.tsx` - Lines 75-78: authEnabled logic

### Backend
- Check if backend has a `/groups` or `/user/groups` endpoint
- Verify it uses managed identity to call Microsoft Graph
- Check `src/ContentProcessorAPI/` for group-related code

### Infrastructure
- `infra/scripts/post_deployment.sh` - Lines 46-83: Graph permission assignment
- Container app managed identity: `ca-cps-gw6br2ms6mxy-api`

## Quick Test Commands

### Browser Console (test group loading)
```javascript
// Check if GroupContext has any data
// This requires React DevTools or logging from the component
```

### Check Managed Identity Permissions
```bash
# Get API managed identity principal ID
az containerapp show \
  --name ca-cps-gw6br2ms6mxy-api \
  --resource-group rg-knowledgegraph \
  --query "identity.principalId" -o tsv

# Check its Graph permissions (replace $PRINCIPAL_ID)
az rest --method GET \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$PRINCIPAL_ID/appRoleAssignments"
```

## Environment Details

### Container Apps
- **Web:** `ca-cps-gw6br2ms6mxy-web` (revision --0000009)
  - URL: https://ca-cps-gw6br2ms6mxy-web.kindbush-ab1ad332.westus.azurecontainerapps.io
- **API:** `ca-cps-gw6br2ms6mxy-api` (revision --0000006)
  - URL: https://ca-cps-gw6br2ms6mxy-api.kindbush-ab1ad332.westus.azurecontainerapps.io
- **Resource Group:** `rg-knowledgegraph`
- **Location:** West US

### Environment Variables (Web Container)
- `APP_API_BASE_URL` = https://ca-cps-gw6br2ms6mxy-api.kindbush-ab1ad332.westus.azurecontainerapps.io
- `APP_WEB_CLIENT_ID` = b4aa58e1-8b31-445d-9fc9-1a1b6a044deb
- `APP_WEB_AUTHORITY` = https://login.microsoftonline.com//ecaa729a-f04c-4558-a31a-ab714740ee8b
- `APP_WEB_SCOPE` = api://b4aa58e1-8b31-445d-9fc9-1a1b6a044deb/user_impersonation
- `APP_API_SCOPE` = api://519dd9e8-25b9-494b-ac7f-e90b4f4dd284/user_impersonation
- `APP_CONSOLE_LOG_ENABLED` = true
- `REACT_APP_AUTH_ENABLED` = (set but not used - build-time value is `true`)
- `APP_AUTH_ENABLED` = true

## Most Likely Cause

**The backend API is likely failing to fetch groups from Microsoft Graph** because:
1. The managed identity doesn't have Graph API permissions yet
2. The `post_deployment.sh` script wasn't run after the latest deployment
3. Or there's an issue with the Graph API call itself

**Expected behavior:**
- Backend should call Microsoft Graph API with managed identity
- Should return list of user's groups
- Frontend GroupContext should populate `userGroups` array
- GroupSelector should render dropdown with groups

**Current behavior:**
- `userGroups.length === 0` (empty)
- GroupSelector returns `null`
- Empty div renders in header

## Resume Work By

1. **First:** Run `./post_deployment.sh` to assign Graph permissions
2. **Second:** Check API logs for any Graph/permission errors
3. **Third:** Test in browser - group switcher should appear
4. **Fourth:** If still not working, read `GroupContext.tsx` to understand the exact fetch logic

---

**Status:** Debugging in progress - Group switcher component exists and auth works, but no groups are loading (likely Graph API permissions issue).

**Last Updated:** October 21, 2025 03:15 UTC
**Current Commit:** af6bd3e9 (Centralized Group Change Handling)
**Deployed Revision:** web--0000009, api--0000006
