# Group Name Resolution Fix

## 🐛 Issue
User sees **group IDs** instead of **group names** in the dropdown.

Example:
```
7e9e0c33-a31e-4b56-8ebf-0fff973f328f
```

Instead of:
```
Hulkdesign-AI-access
```

## 🔍 Root Causes Identified

### 1. ❌ Wrong Permission Scope
**Before:**
```typescript
scopes: ['https://graph.microsoft.com/Directory.Read.All']
```

**After:**
```typescript
scopes: ['https://graph.microsoft.com/Group.Read.All']
```

The code was requesting `Directory.Read.All` but Azure AD was configured with `Group.Read.All`.

### 2. 🔍 Insufficient Error Logging
The original code had minimal logging, making it hard to debug why group names weren't loading.

## ✅ Fixes Applied

### 1. Corrected Permission Scope
Changed to match the Azure AD configured permission: `Group.Read.All`

### 2. Enhanced Error Logging
```typescript
// Before fetch
console.log(`Fetching group name for: ${groupId}`);

// After successful fetch
console.log(`Group ${groupId} name:`, group.displayName);

// On error
console.error(`Failed to fetch group ${groupId}. Status: ${graphResponse.status}, Error:`, errorText);

// On exception
console.error(`Exception fetching name for group ${groupId}:`, error);
```

### 3. Account Validation
```typescript
if (!account) {
  console.warn('No active account found');
  return;
}
```

### 4. Token Acquisition Logging
```typescript
console.log('Requesting Graph API token with Group.Read.All scope...');
const response = await msalInstance.acquireTokenSilent(graphRequest);
console.log('Successfully acquired Graph API token');
```

## 🧪 Testing After Redeployment

### Step 1: Check Browser Console
Open Developer Tools (F12) and look for these logs:

**Success:**
```
Requesting Graph API token with Group.Read.All scope...
Successfully acquired Graph API token
Fetching group name for: 7e9e0c33-a31e-4b56-8ebf-0fff973f328f
Group 7e9e0c33-a31e-4b56-8ebf-0fff973f328f name: Hulkdesign-AI-access
```

**Failure (Permission Denied):**
```
Failed to fetch group 7e9e0c33-a31e-4b56-8ebf-0fff973f328f. Status: 403, Error: {"error":{"code":"Authorization_RequestDenied"...}}
```

**Failure (Token Issue):**
```
Failed to load group names: Error: consent_required
```

### Step 2: Expected Behavior

**Before Fix:**
- Dropdown shows: `7e9e0c33-a31e-4b56-8ebf-0fff973f328f`
- Single group shows: `Active: 7e9e0c33-a31e-4b56-8ebf-0fff973f328f`

**After Fix:**
- Dropdown shows: `Hulkdesign-AI-access`
- Single group shows: `Active: Hulkdesign-AI-access`

## 🔧 Troubleshooting Guide

### Issue: Still seeing group IDs

**Check 1: Permission Granted?**
```bash
az ad app permission list \
  --id 546fae19-24fb-4ff8-9e7c-b5ff64e17987 \
  --query "[?resourceAppId=='00000003-0000-0000-c000-000000000000'].resourceAccess[].id" \
  -o json
```

Expected: Should include `5b567255-7703-4780-807c-7be8301ae99b` (Group.Read.All)

**Check 2: Admin Consent Given?**
```bash
az ad app permission list-grants \
  --id 546fae19-24fb-4ff8-9e7c-b5ff64e17987
```

Expected: `consentType: AllPrincipals` and scope includes `Group.Read.All`

**Check 3: Browser Console Errors?**
Look for:
- `consent_required` → Need to re-login or grant consent
- `403 Authorization_RequestDenied` → Permission not granted
- `401 Unauthorized` → Token issue

**Check 4: Token Contains Groups?**
In browser console after login:
```javascript
// Check if token has groups
const account = await msalInstance.getActiveAccount();
console.log('ID Token Claims:', account.idTokenClaims);
// Should see: groups: ["7e9e0c33-...", "824be8de-..."]
```

## 🚀 Deployment Commands

### Rebuild and Deploy
```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

### Check Logs After Deployment
```bash
# Web container logs
az containerapp logs show \
  --name ca-cps-xh5lwkfq3vfm-web \
  --resource-group rg-contentaccelerator \
  --follow
```

## 📊 Alternative: Use JWT Token Group Names

If Microsoft Graph API continues to have permission issues, we could alternatively parse group names from the JWT token itself (if Azure AD includes them in the token).

**Code modification would be:**
```typescript
// Instead of Graph API call, use token claims
const account = msalInstance.getActiveAccount();
if (account?.idTokenClaims?.groups) {
  // Extract group info from token if available
  const groupInfo = account.idTokenClaims.groups;
  // Map to display names
}
```

**However**, this requires Azure AD to include group names in the token, which is not default behavior (only IDs are included).

## ✅ Expected Resolution

After redeployment with these fixes:
1. ✅ Code requests correct permission scope (`Group.Read.All`)
2. ✅ Detailed logging shows what's happening
3. ✅ Group names should display instead of IDs
4. ✅ If still issues, logs will show exactly why

## 🔄 Next Steps

1. **Rebuild:** Run `./docker-build.sh`
2. **Test:** Login to the web app
3. **Check:** Browser console for logs
4. **Verify:** Group names appear in dropdown
5. **Report:** Share console logs if still seeing IDs

---

**Status:** Fix Applied, Awaiting Redeployment  
**Files Changed:** `GroupSelector.tsx`  
**Changes:** Permission scope + Enhanced logging
