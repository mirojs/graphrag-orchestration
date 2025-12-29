# Security Group Access Issue Analysis

## Problem Summary

**Symptom**: Users in the `Testing-access` security group get 500 errors when clicking Quick Start button and schema upload, while users in `test-users` group work fine.

**Reported Issues**:
1. Quick Start button - 500 error for Testing-access group
2. Schema upload - 500 error for Testing-access group
3. No special role assignments found for either group

---

## CORRECTED Root Cause Analysis

### ⚠️ INITIAL ANALYSIS WAS WRONG - Here's Why

**My First Theory (INCORRECT):** The issue was about container creation permissions - that `test-users` works because their container exists, while `Testing-access` fails because their container needs to be created.

**Why This Was Wrong:** 
The application uses a **VIRTUAL FOLDER PATTERN**, not separate containers per group. Both groups use the **SAME containers** (`pro-input-files`, `pro-reference-files`, etc.) with group IDs as blob path prefixes.

```python
# ACTUAL IMPLEMENTATION (Virtual Folder Pattern)
container_name = "pro-input-files"  # Same for all groups
blob_prefix = f"{group_id}/" if group_id else ""
blob_name = f"{blob_prefix}{process_id}_{file.filename}"
# Result: pro-input-files/{group-id}/file.pdf
```

Since both groups use the **same Container App instance** accessing the **same containers**, container creation permissions cannot explain why one group works and another doesn't.

---

## Actual Root Causes to Investigate

Since the "container creation" theory is debunked, here are the real possibilities:

### 1. **Group ID Format/Encoding Issues**

**Hypothesis**: The `Testing-access` group ID might contain characters that break blob path creation.

**Evidence to check**:
```bash
# Get the actual group IDs
test-users group ID: ?
Testing-access group ID: fb0282b9-12e0-4dd5-94ab-3df84561994c
```

**Potential issues**:
- Special characters in group name that break path sanitization
- Group ID encoding problems (hyphens in GUIDs are fine, but display name might have issues)
- Path prefix concatenation errors

### 2. **Group Name Resolution Failures**

```python
def get_group_container_name(group_id: str, use_display_name: bool = True) -> str:
  # Resolves group ID to display name via MS Graph
  if use_display_name:
    group_identifier = get_group_display_name(group_id)  # ← Might fail here
```

**Hypothesis**: Microsoft Graph API call to resolve `Testing-access` group name fails, causing 500 error.

**Possible causes**:
- Graph API permissions missing
- Rate limiting
- Group ID not found in Azure AD
- Network timeout calling Graph API

### 3. **JWT Token Issues**

**Hypothesis**: Users in `Testing-access` group have different token structure.

**Check**:
- Do `Testing-access` users' tokens contain the `groups` claim?
- Is the group ID in their token exactly `fb0282b9-12e0-4dd5-94ab-3df84561994c`?
- Token size limits (Azure AD has 200 group limit in tokens)

### 4. **Backend Error Handling**

The code has lazy container creation but swallows errors:
```python
def _ensure_container_exists(self, container_name: str):
  try:
    if not container_client.exists():
      container_client.create_container()
  except Exception as e:
    print(f"Warning: Could not ensure container {container_name} exists: {e}")
    # ⚠️ Doesn't raise - continues execution
```

**But the actual error might be**:
- Blob path creation failing with group ID prefix
- Permission denied on blob write (not container)
- Storage account firewall rules blocking specific users

### 5. **Storage Account Network/Firewall Rules**

**Hypothesis**: Storage account has network rules that block requests for certain users.

**Check Azure Portal**:
- Storage Account → Networking
- Are there IP restrictions?
- Are there virtual network rules?
- Is managed identity explicitly allowed?

---

## Verification Steps

## Diagnostic Steps (Do These First!)

### Step 1: Check Backend Logs During 500 Error

```bash
CONTAINER_APP_NAME="ca-cps-xh5lwkfq3vfm-api"
RESOURCE_GROUP="<your-resource-group>"

# Tail logs in real-time
az containerapp logs show \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --follow

# Have a Testing-access user click Quick Start
# Look for error messages in the log output
```

**What to look for**:
- Graph API failures
- Group ID validation errors
- Blob path creation errors
- Storage access denied messages
- Group name resolution failures

### Step 2: Compare JWT Tokens

Ask users from both groups to:

1. Log into the app
2. Open browser DevTools → Application → Cookies
3. Find the auth token
4. Decode at https://jwt.ms
5. Compare the tokens:

```json
{
  "groups": [
    "fb0282b9-12e0-4dd5-94ab-3df84561994c"  // Is this present?
  ],
  "oid": "user-object-id",
  "tid": "tenant-id"
}
```

**Check**:
- Is `groups` claim present in both tokens?
- Is the group ID exactly `fb0282b9-12e0-4dd5-94ab-3df84561994c`?
- Are there any differences in token structure?

### Step 3: Test Group Name Resolution

```bash
# Test if backend can resolve the group name
GROUP_ID="fb0282b9-12e0-4dd5-94ab-3df84561994c"

# Check if Graph API can read this group
az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/groups/${GROUP_ID}" \
  --query "{id: id, displayName: displayName}"
```

**Expected**: Should return group details
**If fails**: Graph API permissions issue

### Step 4: Check Storage Account Network Rules

```bash
STORAGE_ACCOUNT="<your-storage-account>"
RESOURCE_GROUP="<your-resource-group>"

az storage account show \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query "{networkRules: networkRuleSet, publicAccess: publicNetworkAccess}"
```

**Look for**:
- Firewall rules that might block certain requests
- Virtual network restrictions
- IP allowlist/denylist

### Step 5: Test Blob Operations Directly

Create a test script to simulate what the backend does:

```python
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# Same container both groups should use
container_name = "pro-input-files"
group_id = "fb0282b9-12e0-4dd5-94ab-3df84561994c"

credential = DefaultAzureCredential()
blob_service = BlobServiceClient(
    account_url="https://<account>.blob.core.windows.net",
    credential=credential
)

# Test virtual folder pattern
container_client = blob_service.get_container_client(container_name)
blob_name = f"{group_id}/test-file.txt"

try:
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(b"test content", overwrite=True)
    print("✅ Upload succeeded")
except Exception as e:
    print(f"❌ Upload failed: {e}")
```

### Step 6: Check Quick Start Endpoint Specifically

The Quick Start button likely calls a specific endpoint. Find and test it:

```bash
# Find the quick start endpoint (search codebase)
grep -r "quick.*start" --include="*.py" ./code/

# Test directly with curl
curl -X POST "https://<api-url>/api/quick-start" \
  -H "Authorization: Bearer <token-from-testing-access-user>" \
  -H "X-Group-ID: fb0282b9-12e0-4dd5-94ab-3df84561994c" \
  -v
```

---

## Summary

## CORRECTED Summary & Next Steps

**Problem**: Users in `Testing-access` group get 500 errors while `test-users` group works fine, despite using the same Container App.

**Why My Initial Analysis Was Wrong**: I assumed separate containers per group, but the app uses virtual folder pattern (same containers for all groups).

**Your Question Was Right**: Since both groups use the same Container App and same containers, container creation permissions cannot be the differentiator.

**Real Diagnostic Needed**:
1. **Check backend logs** during a 500 error from Testing-access user
2. **Compare JWT tokens** between working and failing users
3. **Test Graph API** ability to resolve `Testing-access` group name
4. **Verify blob path creation** works with that specific group ID
5. **Check network rules** on storage account

**Most Likely Culprits** (in order):

1. **Graph API Permission Issue**: Backend can't resolve `Testing-access` group name
  - Quick check: Does your app have `Group.Read.All` with admin consent?
   
2. **Group Name Sanitization**: The name "Testing-access" might create invalid blob paths
  - The hyphen in the name could break path logic
  - Compare with "test-users" - different character pattern

3. **Token Groups Claim**: Testing-access group ID might not be in users' tokens
  - Azure AD has 200 group limit in tokens
  - Overage claim might require special handling

4. **Quick Start Endpoint Logic**: Might have hardcoded logic expecting specific groups
  - Search for "quick start" or "quickstart" in backend code
  - Check if it validates against a whitelist

**What to Provide for Further Help**:
- Backend logs showing the exact error
- JWT token from a Testing-access user (groups claim)
- Result of Graph API query for that group
- Output of the diagnostic scripts above

---

## Why This Investigation Matters

Your question revealed a critical flaw in my reasoning - it's easy to jump to "permissions" as the cause of 500 errors, but the architecture needs to be understood first. 

Since **both groups use the same infrastructure** (same Container App, same managed identity, same containers), any difference must be in:
- **The data** (group IDs, names, tokens)
- **Application logic** (how it handles different groups)
- **External service calls** (Graph API, Azure AD)

Not in Azure RBAC or container permissions.
