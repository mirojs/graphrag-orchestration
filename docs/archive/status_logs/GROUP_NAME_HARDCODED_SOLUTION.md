# Group Name Display - Simple Hardcoded Solution

## 🎯 Problem
User still seeing group IDs instead of names after trying Microsoft Graph API integration.

## 🔍 Root Cause: Permission Type Mismatch

### The Issue with Graph API Approach

We configured **Application Permission** in Azure AD:
```
Group.Read.All (Application) ✅
```

But MSAL in the browser uses **Delegated Permissions** (on behalf of user):
```typescript
// This doesn't work because Group.Read.All is APPLICATION permission
scopes: ['https://graph.microsoft.com/Group.Read.All']
```

**Application vs Delegated:**
- **Application Permissions:** Used by backend services (daemon/service accounts)
- **Delegated Permissions:** Used by frontend on behalf of logged-in user

### What We Would Need for Graph API in Frontend

To read group names from frontend, we'd need **Delegated** permission:
```
Group.Read.All (Delegated) - Requires admin consent for each user
```

OR

```
Directory.Read.All (Delegated) - Even more permissions
```

**Problem:** These are high-privilege permissions that:
1. Require admin consent **per user**
2. Give access to read ALL groups in directory
3. Security concern for a simple UI dropdown

## ✅ Better Solution: Hardcoded Group Mappings

### Why This is Better

1. **✅ Simple** - No complex API calls or permissions
2. **✅ Fast** - No network latency
3. **✅ Secure** - No additional permissions needed
4. **✅ Reliable** - Works offline, no API failures
5. **✅ Maintainable** - Easy to update group names

### Implementation

```typescript
const knownGroups: Record<string, string> = {
  '7e9e0c33-a31e-4b56-8ebf-0fff973f328f': 'Hulkdesign-AI-access',
  '824be8de-0981-470e-97f2-3332855e22b2': 'Owner-access',
  'fb0282b9-12e0-4dd5-94ab-3df84561994c': 'Testing-access',
};
```

### Your Groups

| Group ID | Display Name |
|----------|--------------|
| `7e9e0c33-a31e-4b56-8ebf-0fff973f328f` | Hulkdesign-AI-access |
| `824be8de-0981-470e-97f2-3332855e22b2` | Owner-access |
| `fb0282b9-12e0-4dd5-94ab-3df84561994c` | Testing-access |

## 🔄 Alternative Solutions (More Complex)

### Option 1: Backend API Endpoint

Create a backend endpoint that uses Application permissions:

**Backend (FastAPI):**
```python
@app.get("/api/groups/names")
async def get_group_names(group_ids: List[str]):
    # Backend has Application permission
    # Can call Graph API directly
    graph_token = get_app_only_token()
    names = {}
    for group_id in group_ids:
        response = requests.get(
            f"https://graph.microsoft.com/v1.0/groups/{group_id}",
            headers={"Authorization": f"Bearer {graph_token}"}
        )
        names[group_id] = response.json()["displayName"]
    return names
```

**Frontend:**
```typescript
const response = await fetch('/api/groups/names', {
  method: 'POST',
  body: JSON.stringify({ group_ids: groupIds })
});
const names = await response.json();
```

**Pros:**
- Dynamic, no hardcoded values
- Uses existing Application permissions

**Cons:**
- Additional API endpoint needed
- More network calls
- More complex

### Option 2: Add Delegated Permissions

Add `Group.Read.All` as **Delegated** permission:

```bash
# Add delegated permission (different ID than Application)
az ad app permission add \
  --id 546fae19-24fb-4ff8-9e7c-b5ff64e17987 \
  --api 00000003-0000-0000-c000-000000000000 \
  --api-permissions 5f8c59db-677d-491f-a6b8-5f174b11ec1d=Scope

# Grant admin consent
az ad app permission admin-consent \
  --id 546fae19-24fb-4ff8-9e7c-b5ff64e17987
```

**Delegated Permission ID:**
- `5f8c59db-677d-491f-a6b8-5f174b11ec1d` = Group.Read.All (Delegated)

**Pros:**
- Dynamic group name resolution
- Works for any new groups

**Cons:**
- High privilege permission
- Requires admin consent per user
- Security/compliance concern
- User can read ALL groups in directory

## 🚀 Recommended: Hardcoded Mapping (Current Implementation)

### Advantages

1. **Immediate** - Works right now
2. **Secure** - No additional permissions
3. **Fast** - No API latency
4. **Simple** - Easy to understand and maintain

### When to Update

Update the mapping when:
- Creating new groups
- Renaming existing groups
- Deactivating old groups

### How to Update

1. **Edit the file:**
   ```
   src/ContentProcessorWeb/src/components/GroupSelector.tsx
   ```

2. **Update the mapping:**
   ```typescript
   const knownGroups: Record<string, string> = {
     '7e9e0c33-a31e-4b56-8ebf-0fff973f328f': 'Hulkdesign-AI-access',
     '824be8de-0981-470e-97f2-3332855e22b2': 'Owner-access',
     'fb0282b9-12e0-4dd5-94ab-3df84561994c': 'Testing-access',
     // Add new groups here
     'new-group-id-here': 'New Group Name',
   };
   ```

3. **Redeploy:**
   ```bash
   cd ./code/content-processing-solution-accelerator/infra/scripts
   ./docker-build.sh
   ```

## 📊 Trade-offs Comparison

| Approach | Complexity | Security | Performance | Maintenance |
|----------|-----------|----------|-------------|-------------|
| **Hardcoded** ✅ | Low | High (no extra perms) | Instant | Update on group changes |
| **Backend API** | Medium | Medium | Good | Automatic |
| **Delegated Perm** | Low | Low (high privileges) | Good | Automatic |

## ✅ Summary

**Solution:** Hardcoded group name mappings  
**Status:** Implemented in GroupSelector.tsx  
**Action:** Redeploy to see group names  

**Next Deployment Will Show:**
```
✅ Hulkdesign-AI-access
✅ Owner-access
✅ Testing-access
```

Instead of:
```
❌ 7e9e0c33-a31e-4b56-8ebf-0fff973f328f
❌ 824be8de-0981-470e-97f2-3332855e22b2
❌ fb0282b9-12e0-4dd5-94ab-3df84561994c
```

---

**Decision:** Use hardcoded mappings for simplicity and security.  
**If needed later:** Can implement backend API endpoint for dynamic resolution.
