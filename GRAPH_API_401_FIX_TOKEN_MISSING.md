# Graph API 401 Error Fix - Missing Authorization Header

## Problem Diagnosis

**Issue**: `/api/groups/resolve-names` endpoint returns 401 Unauthorized, and group IDs are displayed instead of names.

**Root Cause**: Frontend code was making direct `fetch()` calls WITHOUT including the Authorization header with the user's token.

## Microsoft's Pattern (from azure-search-openai-demo)

### Backend Pattern ✅ (Already Correct)
```python
# app/backend/routes/groups.py - Uses user's token directly
headers = {"Authorization": request.headers.get("Authorization")}
response = requests.get(url, headers=headers)
```

### Frontend Pattern 🔴 (Was Missing)
```typescript
// Microsoft's api.ts - ALWAYS uses getHeaders() helper
export async function getHeaders(idToken: string | undefined): Promise<Record<string, string>> {
    if (useLogin && !isUsingAppServicesLogin) {
        if (idToken) {
            return { Authorization: `Bearer ${idToken}` };
        }
    }
    return {};
}

// All API calls use this pattern:
const headers = await getHeaders(idToken);
const response = await fetch("/endpoint", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data)
});
```

## Our Implementation Status

### ✅ What Was Already Correct
1. **Backend**: `groups.py` correctly passes through user's Authorization header
2. **httpUtility**: `Services/httpUtility.ts` already adds Authorization header automatically
3. **msalConfig.ts**: Frontend requests `Group.Read.All` scope
4. **Admin Consent**: Granted successfully in Azure Portal
5. **Bicep**: No Graph-specific configuration needed (we use delegated permissions)

### 🔴 What Was Broken
**PredictionTab.tsx** - Direct fetch() call without Authorization:
```typescript
// ❌ BEFORE - No auth header
const response = await fetch(`${process.env.REACT_APP_API_BASE_URL}/api/groups/resolve-names`, {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json'  // ← Missing Authorization!
    },
    body: JSON.stringify([currentCase.group_id])
});
```

**GroupSelector.tsx** - Already correct (uses httpUtility) ✅

## Fix Applied

### Updated PredictionTab.tsx (Lines 226-236)
```typescript
// ✅ AFTER - Uses httpUtility which includes Authorization header
const response = await httpUtility.post<Record<string, string>>(
    '/api/groups/resolve-names',
    [currentCase.group_id]
);
if (response.status === 200 && response.data) {
    const name = response.data[currentCase.group_id];
    if (name) {
        console.log('[PredictionTab] Resolved case group name:', name);
        setCaseGroupName(name);
    }
}
```

### Added Import (Line 21)
```typescript
import httpUtility from '../Services/httpUtility';
```

## Token Flow (Delegated Permissions Pattern)

```
┌─────────────┐
│   User      │ Logs in with MSAL
│   Browser   │ Requests scopes: ["user.read", "api://...", "Group.Read.All"]
└─────┬───────┘
      │ Token includes all scopes
      ▼
┌─────────────────────────────────────────────────────────┐
│  httpUtility.ts (Automatic Auth)                        │
│  - Gets token from localStorage                         │
│  - Adds header: Authorization: Bearer <token>           │
│  - Includes Group.Read.All permission in token          │
└─────┬───────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  Backend: groups.py (/api/groups/resolve-names)        │
│  headers = {"Authorization": request.headers["Auth"]}  │
└─────┬───────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  Microsoft Graph API                                    │
│  GET https://graph.microsoft.com/v1.0/groups/{id}     │
│  Authorization: Bearer <user-token-with-Group.Read>    │
└─────────────────────────────────────────────────────────┘
```

## Key Differences: Microsoft vs Our Implementation

| Aspect | Microsoft (azure-search-openai-demo) | Ours (Simpler) |
|--------|-------------------------------------|----------------|
| **Token Strategy** | On-Behalf-Of Flow (exchanges tokens) | Direct pass-through |
| **Backend Secrets** | Requires client secrets in Bicep | No secrets needed |
| **Token Acquisition** | Backend acquires new Graph token | Reuses user's token |
| **Complexity** | Higher (MSAL confidential client) | Lower (just forward header) |
| **Result** | Both work with delegated permissions! | Both work with delegated permissions! |

## Why This Works

1. **User logs in** → MSAL acquires token with scopes: `["user.read", "api://app-id", "Group.Read.All"]`
2. **Admin consent granted** → User's token includes Group.Read.All permission
3. **Frontend sends token** → httpUtility adds `Authorization: Bearer <token>` header
4. **Backend forwards token** → No processing, just passes it to Graph API
5. **Graph API validates** → Sees delegated Group.Read.All permission, allows access
6. **Returns group name** → Backend forwards to frontend

## Testing Checklist

After deployment:
- [ ] Clear browser cache/cookies
- [ ] Login fresh to get new token with Group.Read.All scope
- [ ] Check browser console: Should see `[httpUtility] Using stored authentication token`
- [ ] Check Network tab: `/api/groups/resolve-names` should have `Authorization: Bearer ...` header
- [ ] Verify: Group names display as "Sales Team" instead of "Group abc12345..."
- [ ] Verify: No 401 errors in console

## Files Modified

1. `src/ContentProcessorWeb/src/ProModeComponents/PredictionTab.tsx`
   - Line 21: Added `import httpUtility from '../Services/httpUtility';`
   - Lines 226-236: Changed direct fetch() to httpUtility.post()

## Deployment Command

```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/infra/scripts
./docker-build.sh
```

## Expected Result

✅ Group names resolve correctly (e.g., "Sales Team")  
✅ No 401 errors on `/api/groups/resolve-names`  
✅ Case management shows proper group names  
✅ Group selector displays names instead of IDs
