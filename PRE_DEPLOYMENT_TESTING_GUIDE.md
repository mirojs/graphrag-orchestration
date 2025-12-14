# 🧪 Pre-Deployment Testing Guide

## 📋 **Overview**

This guide provides comprehensive testing procedures to validate your group-based isolation implementation **before** deploying to production.

**Testing Goals:**
- ✅ Verify Azure AD configuration is correct
- ✅ Validate group-based authentication works
- ✅ Test container isolation in blob storage
- ✅ Verify Cosmos DB filtering by group_id
- ✅ Ensure frontend group selection works
- ✅ Validate Microsoft Graph API integration
- ✅ Test all critical user workflows

**Estimated Time:** 2-4 hours  
**Required:** Test Azure environment or dev/staging environment  
**Prerequisites:** All Azure resources deployed to test environment

---

## 🎯 **Phase 1: Azure AD Configuration Tests**

### **Test 1.1: Verify Tenant and App Registration**

#### **Objective:** Ensure Azure AD is properly configured

**Steps:**
```bash
# Using Azure CLI
az account show --query "{Subscription:name, TenantId:tenantId}" -o table

# Verify app registration exists
az ad app list --display-name "content-processor-api" --query "[].{Name:displayName, ClientId:appId}" -o table

# Expected output:
DisplayName              ClientId
-----------------------  ------------------------------------
content-processor-api    12345678-abcd-1234-abcd-123456789abc
```

**Validation Checklist:**
- [ ] Tenant ID matches environment variable `AZURE_AD_TENANT_ID`
- [ ] App registration exists with correct name
- [ ] Client ID matches environment variable `AZURE_AD_CLIENT_ID`
- [ ] App registration type is "Single tenant"

---

### **Test 1.2: Verify Groups Claim Configuration**

#### **Objective:** Ensure JWT tokens will contain groups

**Steps:**
```bash
1. Azure Portal → App Registrations → [Your API App]
2. Token configuration → Check "groups" claim exists
3. Verify configuration:
   - Group types: "Security groups" OR "Groups assigned to the application"
   - Emit groups as: "Group IDs" (not names)
   - Token types: ID, Access (both checked)
```

**Validation Checklist:**
- [ ] Groups claim exists in token configuration
- [ ] Configured to emit as Group IDs
- [ ] Both ID and Access tokens selected
- [ ] Configuration matches chosen option (A or B)

---

### **Test 1.3: Verify Microsoft Graph API Permissions**

#### **Objective:** Ensure app can read group names from Graph API

**Steps:**
```bash
# Using Azure CLI
az ad app permission list --id <CLIENT_ID> --query "[].{API:resourceAccess[0].id, Type:resourceAccess[0].type}" -o table

# Or via Azure Portal:
1. App Registrations → [Your API App]
2. API permissions → Check for:
   - Microsoft Graph
   - Directory.Read.All OR Group.Read.All
   - Status: "Granted for [tenant]" (green checkmark)
```

**Validation Checklist:**
- [ ] Microsoft Graph permissions added
- [ ] Either Directory.Read.All or Group.Read.All present
- [ ] Admin consent granted (green checkmark)
- [ ] Status shows "Granted for [your tenant]"

---

### **Test 1.4: Create Test Security Groups**

#### **Objective:** Set up test groups for validation

**Steps:**
```bash
# Create 3 test groups
az ad group create --display-name "Test-Marketing" --mail-nickname "test-marketing"
az ad group create --display-name "Test-Sales" --mail-nickname "test-sales"
az ad group create --display-name "Test-Engineering" --mail-nickname "test-engineering"

# Get group IDs
az ad group list --query "[?displayName=='Test-Marketing'].{Name:displayName, ID:id}" -o table
```

**Create via Azure Portal:**
```bash
1. Azure AD → Groups → New group
2. Group type: Security
3. Group name: Test-Marketing
4. Description: Test group for Content Processor
5. Create
6. Repeat for Test-Sales and Test-Engineering
```

**Validation Checklist:**
- [ ] 3 test groups created
- [ ] All are Security groups (not Microsoft 365)
- [ ] Group IDs documented
- [ ] Groups visible in Azure AD

---

### **Test 1.5: Add Test Users to Groups**

#### **Objective:** Assign test users to groups for testing

**Required Test Users:**
- User A: Member of Test-Marketing only
- User B: Member of Test-Sales only
- User C: Member of both Test-Marketing and Test-Sales
- User D: Not member of any test group

**Steps:**
```bash
# Add user to group
az ad group member add --group "Test-Marketing" --member-id <USER_OBJECT_ID>

# Or via Azure Portal:
1. Azure AD → Groups → Test-Marketing
2. Members → Add members
3. Search and select user
4. Add
```

**Validation Checklist:**
- [ ] User A in Test-Marketing only
- [ ] User B in Test-Sales only
- [ ] User C in both Test-Marketing and Test-Sales
- [ ] User D in no test groups
- [ ] Memberships verified in Azure AD

---

### **Test 1.6: Verify JWT Token Contains Groups**

#### **Objective:** Ensure groups appear in authentication tokens

**Steps:**
```bash
# Method 1: Manual token inspection
1. Deploy app to test environment
2. Log in as User A (Test-Marketing member)
3. Open browser DevTools → Application → Session Storage
4. Find MSAL token
5. Copy token value
6. Go to https://jwt.ms
7. Paste token
8. Look for "groups" claim

# Expected token structure:
{
  "aud": "12345678-...",
  "iss": "https://login.microsoftonline.com/.../v2.0",
  "iat": 1234567890,
  "groups": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890"  // Test-Marketing group ID
  ],
  "name": "Test User A",
  "preferred_username": "usera@yourorg.com"
}
```

**Method 2: Using test script**
```python
# test_jwt_token.py
import requests
import jwt
from msal import PublicClientApplication

# Configuration
tenant_id = "YOUR_TENANT_ID"
client_id = "YOUR_CLIENT_ID"
authority = f"https://login.microsoftonline.com/{tenant_id}"
scopes = [f"api://{client_id}/user_impersonation"]

# Initialize MSAL
app = PublicClientApplication(client_id, authority=authority)

# Interactive login
result = app.acquire_token_interactive(scopes=scopes)

if "access_token" in result:
    token = result["access_token"]
    
    # Decode without verification (just to inspect)
    decoded = jwt.decode(token, options={"verify_signature": False})
    
    print("✅ Token acquired successfully!")
    print(f"User: {decoded.get('name')}")
    print(f"Email: {decoded.get('preferred_username')}")
    print(f"Groups: {decoded.get('groups', [])}")
    
    if decoded.get('groups'):
        print(f"✅ Groups claim present with {len(decoded['groups'])} group(s)")
    else:
        print("❌ No groups claim in token!")
else:
    print(f"❌ Error: {result.get('error_description')}")
```

**Run test:**
```bash
pip install msal pyjwt
python test_jwt_token.py
```

**Validation Checklist:**
- [ ] User A token contains Test-Marketing group ID
- [ ] User B token contains Test-Sales group ID
- [ ] User C token contains both group IDs
- [ ] User D token has empty groups array or no groups claim
- [ ] Group IDs match Azure AD group Object IDs

---

## 🎨 **Phase 2: Frontend Tests**

### **Test 2.1: Group Selector Visibility**

#### **Objective:** Verify group dropdown appears and shows correct groups

**Test Script:**
```bash
Test Case: Group Selector Appears
1. Deploy frontend to test environment
2. Navigate to application URL
3. Log in as User A (Test-Marketing member)
4. Expected: Group selector visible in header/navigation
5. Click group selector
6. Expected: Dropdown shows "Test-Marketing"
7. Verify: Only groups user is member of appear
```

**Validation Checklist:**
- [ ] Group selector component renders
- [ ] Dropdown is clickable
- [ ] Shows groups from JWT token
- [ ] Does not show groups user is not member of

---

### **Test 2.2: Microsoft Graph API Integration**

#### **Objective:** Verify friendly group names load from Graph API

**Test Script:**
```bash
Test Case: Group Names Load from Graph API
1. Log in as User A
2. Open browser DevTools → Network tab
3. Filter: XHR/Fetch requests
4. Look for request to: graph.microsoft.com/v1.0/groups
5. Expected: Request succeeds with 200 status
6. Response contains: displayName for each group
7. Group selector shows: "Test-Marketing" (not the GUID)
```

**Check Network Request:**
```javascript
// Expected request
GET https://graph.microsoft.com/v1.0/groups/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer <access_token>

// Expected response
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "displayName": "Test-Marketing",
  "description": "Test group for Content Processor"
}
```

**Validation Checklist:**
- [ ] Graph API request succeeds
- [ ] Response contains displayName
- [ ] Group selector shows friendly names (not GUIDs)
- [ ] Fallback to short ID works if Graph API fails

---

### **Test 2.3: Group Selection and Persistence**

#### **Objective:** Verify selected group persists across page refreshes

**Test Script:**
```bash
Test Case: Group Selection Persists
1. Log in as User C (member of 2 groups)
2. Select "Test-Marketing" from dropdown
3. Verify: Selected group displayed in UI
4. Check: localStorage contains selectedGroup
5. Refresh page (F5)
6. Expected: "Test-Marketing" still selected
7. Select "Test-Sales"
8. Refresh page again
9. Expected: "Test-Sales" now selected
```

**Check Browser Storage:**
```javascript
// Open browser console
localStorage.getItem('selectedGroup')
// Expected: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

**Validation Checklist:**
- [ ] Selected group stored in localStorage
- [ ] Selection persists after page refresh
- [ ] Changing selection updates localStorage
- [ ] Default selection on first login works

---

### **Test 2.4: X-Group-ID Header Injection**

#### **Objective:** Verify API requests include group header

**Test Script:**
```bash
Test Case: Group Header Sent to Backend
1. Log in and select "Test-Marketing"
2. Open DevTools → Network tab
3. Navigate to any feature (upload file, create schema)
4. Inspect API request to backend
5. Check headers for: X-Group-ID
6. Expected value: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Check Request Headers:**
```javascript
// Expected headers in API requests
Authorization: Bearer <jwt_token>
X-Group-ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
Content-Type: application/json
```

**Validation Checklist:**
- [ ] X-Group-ID header present in all API calls
- [ ] Header value matches selected group
- [ ] Changing groups updates header in subsequent requests
- [ ] No header sent if no group selected

---

## 🔧 **Phase 3: Backend Tests**

### **Test 3.1: Authentication Middleware**

#### **Objective:** Verify backend extracts user context from JWT

**Create Test Script:**
```python
# test_authentication.py
import requests
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")
TEST_TOKEN = "YOUR_TEST_JWT_TOKEN"  # From Test 1.6

def test_authentication():
    """Test that backend validates JWT and extracts user context"""
    
    headers = {
        "Authorization": f"Bearer {TEST_TOKEN}",
        "X-Group-ID": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
    
    # Test endpoint that requires authentication
    response = requests.get(f"{API_URL}/api/pro-mode/schemas", headers=headers)
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        print("✅ Authentication successful")
        print(f"Response: {response.json()}")
    elif response.status_code == 401:
        print("❌ Authentication failed - check JWT token")
    elif response.status_code == 403:
        print("❌ Authorization failed - check group access")
    else:
        print(f"❌ Unexpected status: {response.status_code}")
        print(f"Response: {response.text}")

if __name__ == "__main__":
    test_authentication()
```

**Run Test:**
```bash
python test_authentication.py
```

**Validation Checklist:**
- [ ] Backend accepts valid JWT token
- [ ] Returns 401 for invalid/missing token
- [ ] Extracts user_id, email, name from token
- [ ] Extracts groups from token claims

---

### **Test 3.2: Group Access Validation**

#### **Objective:** Verify backend validates group membership

**Test Script:**
```python
# test_group_validation.py
import requests
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")

def test_group_access_validation():
    """Test group access validation"""
    
    # User A is in Test-Marketing group
    user_a_token = "USER_A_JWT_TOKEN"
    marketing_group_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    sales_group_id = "b2c3d4e5-f6g7-8901-bcde-f23456789012"
    
    # Test 1: Valid access (user in group)
    headers = {
        "Authorization": f"Bearer {user_a_token}",
        "X-Group-ID": marketing_group_id
    }
    response = requests.get(f"{API_URL}/api/pro-mode/schemas", headers=headers)
    assert response.status_code == 200, "User should access their own group"
    print("✅ Test 1 passed: User can access their group")
    
    # Test 2: Invalid access (user not in group)
    headers["X-Group-ID"] = sales_group_id
    response = requests.get(f"{API_URL}/api/pro-mode/schemas", headers=headers)
    assert response.status_code == 403, "User should NOT access other group"
    print("✅ Test 2 passed: User blocked from other group")
    
    # Test 3: No group specified (backward compatible)
    del headers["X-Group-ID"]
    response = requests.get(f"{API_URL}/api/pro-mode/schemas", headers=headers)
    assert response.status_code == 200, "Should work without group_id"
    print("✅ Test 3 passed: Backward compatible (no group)")
    
    print("\n🎉 All group validation tests passed!")

if __name__ == "__main__":
    test_group_access_validation()
```

**Run Test:**
```bash
python test_group_validation.py
```

**Validation Checklist:**
- [ ] User can access groups they're member of
- [ ] User blocked from groups they're NOT member of
- [ ] Returns 403 for unauthorized group access
- [ ] Backward compatible when no group_id provided

---

### **Test 3.3: Container Naming**

#### **Objective:** Verify group-specific blob container names

**Test Script:**
```python
# test_container_naming.py
import requests
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")

def test_container_naming():
    """Test that containers use group-specific naming"""
    
    user_a_token = "USER_A_JWT_TOKEN"
    group_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    
    headers = {
        "Authorization": f"Bearer {user_a_token}",
        "X-Group-ID": group_id,
        "Content-Type": "multipart/form-data"
    }
    
    # Upload a test file
    files = {'file': ('test.txt', b'test content', 'text/plain')}
    response = requests.post(
        f"{API_URL}/api/pro-mode/input-files/upload",
        headers=headers,
        files=files
    )
    
    if response.status_code == 200:
        result = response.json()
        container = result.get('container')
        
        # Verify container name includes group ID
        expected_container = f"pro-input-files-group-{group_id[:8]}"
        
        if container == expected_container:
            print(f"✅ Container naming correct: {container}")
        else:
            print(f"❌ Container naming wrong!")
            print(f"   Expected: {expected_container}")
            print(f"   Got: {container}")
    else:
        print(f"❌ Upload failed: {response.status_code}")
        print(f"   Response: {response.text}")

if __name__ == "__main__":
    test_container_naming()
```

**Validation Checklist:**
- [ ] Container name includes "group-{group_id[:8]}"
- [ ] Different groups use different containers
- [ ] Container creation succeeds
- [ ] Files stored in correct group container

---

## 📦 **Phase 4: Storage Isolation Tests**

### **Test 4.1: Blob Storage Container Isolation**

#### **Objective:** Verify files are isolated between groups

**Manual Test Procedure:**
```bash
Test Case: File Upload Isolation
1. Log in as User A (Test-Marketing)
2. Select Test-Marketing group
3. Upload file: "marketing-doc.pdf"
4. Note container: pro-input-files-group-a1b2c3d4
5. Verify file appears in list

6. Log out
7. Log in as User B (Test-Sales)
8. Select Test-Sales group
9. List files
10. Expected: marketing-doc.pdf NOT visible
11. Upload file: "sales-doc.pdf"
12. Note container: pro-input-files-group-b2c3d4e5
13. Expected: Only sales-doc.pdf visible

14. Check Azure Portal:
    - Storage Account → Containers
    - Verify two separate containers exist
    - pro-input-files-group-a1b2c3d4/ contains marketing-doc.pdf
    - pro-input-files-group-b2c3d4e5/ contains sales-doc.pdf
```

**Automated Test:**
```python
# test_blob_isolation.py
import requests
import os

API_URL = os.getenv("API_URL")

def test_blob_isolation():
    """Test blob storage isolation between groups"""
    
    # Upload file to Group A
    headers_a = {
        "Authorization": f"Bearer {USER_A_TOKEN}",
        "X-Group-ID": GROUP_A_ID
    }
    files = {'file': ('group-a-file.txt', b'Group A content', 'text/plain')}
    upload_resp = requests.post(
        f"{API_URL}/api/pro-mode/input-files/upload",
        headers=headers_a,
        files=files
    )
    assert upload_resp.status_code == 200
    print("✅ File uploaded to Group A")
    
    # List files from Group A
    list_resp_a = requests.get(
        f"{API_URL}/api/pro-mode/input-files",
        headers=headers_a
    )
    files_a = list_resp_a.json().get('files', [])
    assert any(f['filename'] == 'group-a-file.txt' for f in files_a)
    print("✅ Group A can see their file")
    
    # List files from Group B
    headers_b = {
        "Authorization": f"Bearer {USER_B_TOKEN}",
        "X-Group-ID": GROUP_B_ID
    }
    list_resp_b = requests.get(
        f"{API_URL}/api/pro-mode/input-files",
        headers=headers_b
    )
    files_b = list_resp_b.json().get('files', [])
    assert not any(f['filename'] == 'group-a-file.txt' for f in files_b)
    print("✅ Group B cannot see Group A's file")
    
    print("\n🎉 Blob isolation test passed!")

if __name__ == "__main__":
    test_blob_isolation()
```

**Validation Checklist:**
- [ ] Files uploaded to group-specific containers
- [ ] Group A cannot see Group B's files
- [ ] Group B cannot see Group A's files
- [ ] Container names include group ID prefix

---

### **Test 4.2: Cosmos DB Filtering**

#### **Objective:** Verify database queries filter by group_id

**Test Script:**
```python
# test_cosmos_filtering.py
import requests
import os

API_URL = os.getenv("API_URL")

def test_cosmos_filtering():
    """Test Cosmos DB filtering by group_id"""
    
    # Create schema in Group A
    headers_a = {
        "Authorization": f"Bearer {USER_A_TOKEN}",
        "X-Group-ID": GROUP_A_ID,
        "Content-Type": "application/json"
    }
    
    schema_data = {
        "name": "Group A Schema",
        "fields": [
            {"name": "field1", "type": "string"}
        ]
    }
    
    create_resp = requests.post(
        f"{API_URL}/api/pro-mode/schemas/save-extracted",
        headers=headers_a,
        json=schema_data
    )
    assert create_resp.status_code == 200
    schema_id = create_resp.json().get('id')
    print(f"✅ Schema created in Group A: {schema_id}")
    
    # List schemas from Group A
    list_resp_a = requests.get(
        f"{API_URL}/api/pro-mode/schemas",
        headers=headers_a
    )
    schemas_a = list_resp_a.json().get('schemas', [])
    assert any(s['id'] == schema_id for s in schemas_a)
    print("✅ Group A can see their schema")
    
    # List schemas from Group B
    headers_b = {
        "Authorization": f"Bearer {USER_B_TOKEN}",
        "X-Group-ID": GROUP_B_ID
    }
    list_resp_b = requests.get(
        f"{API_URL}/api/pro-mode/schemas",
        headers=headers_b
    )
    schemas_b = list_resp_b.json().get('schemas', [])
    assert not any(s['id'] == schema_id for s in schemas_b)
    print("✅ Group B cannot see Group A's schema")
    
    print("\n🎉 Cosmos DB filtering test passed!")

if __name__ == "__main__":
    test_cosmos_filtering()
```

**Manual Verification in Azure Portal:**
```bash
1. Azure Portal → Cosmos DB → Data Explorer
2. Select database → schema container
3. Run query:
   SELECT * FROM c WHERE c.group_id = 'a1b2c3d4-...'
4. Verify: Only Group A's schemas returned
5. Run query:
   SELECT * FROM c WHERE c.group_id = 'b2c3d4e5-...'
6. Verify: Only Group B's schemas returned
```

**Validation Checklist:**
- [ ] Schemas saved with group_id field
- [ ] Queries filter by group_id automatically
- [ ] Group A cannot query Group B's data
- [ ] group_id field present in all documents

---

## 🔄 **Phase 5: End-to-End Workflow Tests**

### **Test 5.1: Complete File Upload Workflow**

**Test Procedure:**
```bash
Test Case: Upload → Process → Download
1. Log in as User A (Test-Marketing)
2. Select Test-Marketing group
3. Upload document: test-invoice.pdf
4. Expected: Success message
5. Expected: File appears in file list
6. Expected: Container: pro-input-files-group-a1b2c3d4
7. Click on file to preview/download
8. Expected: File downloads successfully
9. Verify: Downloaded file matches uploaded file
10. Delete file
11. Expected: File removed from list
12. Check Azure Storage: File deleted from container
```

**Validation Checklist:**
- [ ] Upload succeeds
- [ ] File stored in correct group container
- [ ] File visible in group's file list
- [ ] Download works correctly
- [ ] Delete removes file from storage
- [ ] All operations isolated to user's group

---

### **Test 5.2: Schema Creation and Management**

**Test Procedure:**
```bash
Test Case: Create → Save → List → Edit → Delete Schema
1. Log in as User A (Test-Marketing)
2. Select Test-Marketing group
3. Create new schema:
   - Name: "Invoice Schema"
   - Add fields: vendor, amount, date
4. Save schema
5. Expected: Success, schema appears in list
6. Verify: Schema has group_id field in Cosmos DB
7. Edit schema (add field)
8. Save changes
9. Expected: Updates reflected
10. List all schemas
11. Expected: Only schemas from Test-Marketing visible
12. Delete schema
13. Expected: Schema removed from list
```

**Validation Checklist:**
- [ ] Schema creation includes group_id
- [ ] Schema saved to Cosmos DB
- [ ] Schema list filtered by group_id
- [ ] Edits preserve group_id
- [ ] Delete removes from correct group only

---

### **Test 5.3: Cross-Group Switching (User C)**

**Test Procedure:**
```bash
Test Case: User with Multiple Groups
1. Log in as User C (Test-Marketing + Test-Sales)
2. Group dropdown shows both groups
3. Select Test-Marketing
4. Upload file: marketing-file.pdf
5. Verify: File visible in list
6. Switch to Test-Sales group
7. Expected: File list refreshes
8. Expected: marketing-file.pdf NOT visible
9. Upload file: sales-file.pdf
10. Verify: sales-file.pdf visible
11. Switch back to Test-Marketing
12. Expected: marketing-file.pdf visible
13. Expected: sales-file.pdf NOT visible
```

**Validation Checklist:**
- [ ] User sees all groups they're member of
- [ ] Switching groups updates UI
- [ ] File lists isolated per group
- [ ] Selection persists after page refresh
- [ ] X-Group-ID header updates when switching

---

### **Test 5.4: Analysis Run with Group Isolation**

**Test Procedure:**
```bash
Test Case: Full Analysis Workflow
1. Log in as User A (Test-Marketing)
2. Select Test-Marketing group
3. Upload document for analysis
4. Create/select schema
5. Run analysis
6. Expected: Analysis runs successfully
7. View results
8. Expected: Results visible
9. Check Cosmos DB:
   - analysisRuns collection
   - Verify run has group_id field
   - Value matches Test-Marketing group ID
10. Check Blob Storage:
    - predictions container or predictions-group-{id}
    - Verify results file exists
11. Log in as User B (Test-Sales)
12. List analysis runs
13. Expected: User A's analysis NOT visible
```

**Validation Checklist:**
- [ ] Analysis run includes group_id
- [ ] Results stored in group-specific location
- [ ] Results visible to group members only
- [ ] Other groups cannot access analysis results
- [ ] All related data has matching group_id

---

## 🚨 **Phase 6: Security and Error Handling Tests**

### **Test 6.1: Unauthorized Group Access**

**Test Script:**
```python
# test_unauthorized_access.py
import requests

def test_unauthorized_access():
    """Test that users cannot access groups they're not member of"""
    
    # User A tries to access Group B's data
    headers = {
        "Authorization": f"Bearer {USER_A_TOKEN}",
        "X-Group-ID": GROUP_B_ID  # User A not in Group B
    }
    
    # Test various endpoints
    endpoints = [
        "/api/pro-mode/schemas",
        "/api/pro-mode/input-files",
        "/api/pro-mode/analysis-runs"
    ]
    
    for endpoint in endpoints:
        response = requests.get(f"{API_URL}{endpoint}", headers=headers)
        assert response.status_code == 403, f"Expected 403 for {endpoint}"
        print(f"✅ Access denied for {endpoint}")
    
    print("\n🎉 Unauthorized access properly blocked!")

if __name__ == "__main__":
    test_unauthorized_access()
```

**Validation Checklist:**
- [ ] Returns 403 for unauthorized group access
- [ ] Error message explains access denied
- [ ] User cannot guess/brute-force group IDs
- [ ] Logs show attempted unauthorized access

---

### **Test 6.2: Invalid Group ID**

**Test Cases:**
```bash
Test: Non-existent Group ID
- X-Group-ID: "00000000-0000-0000-0000-000000000000"
- Expected: 403 Forbidden

Test: Malformed Group ID
- X-Group-ID: "invalid-group-id"
- Expected: 400 Bad Request

Test: Empty Group ID
- X-Group-ID: ""
- Expected: Works (backward compatible) OR 400 Bad Request

Test: Missing Group ID Header
- No X-Group-ID header
- Expected: Works (backward compatible)
```

**Validation Checklist:**
- [ ] Invalid group IDs rejected
- [ ] Appropriate error codes returned
- [ ] Error messages are helpful
- [ ] No sensitive information in errors

---

### **Test 6.3: Token Expiration**

**Test Procedure:**
```bash
Test Case: Expired JWT Token
1. Get JWT token
2. Wait for token to expire (1 hour)
3. Attempt API call with expired token
4. Expected: 401 Unauthorized
5. User redirected to login
6. After re-login, operations work again
```

**Validation Checklist:**
- [ ] Expired tokens rejected
- [ ] User prompted to re-authenticate
- [ ] Re-authentication refreshes groups
- [ ] Session continues after re-auth

---

## 📊 **Phase 7: Performance Tests**

### **Test 7.1: Load Test with Multiple Groups**

**Load Test Script:**
```python
# load_test.py
import asyncio
import aiohttp
import time

async def upload_file(session, user_token, group_id, file_num):
    """Upload a file for load testing"""
    headers = {
        "Authorization": f"Bearer {user_token}",
        "X-Group-ID": group_id
    }
    
    data = aiohttp.FormData()
    data.add_field('file',
                   f'test-file-{file_num}.txt',
                   filename=f'test-file-{file_num}.txt',
                   content_type='text/plain')
    
    async with session.post(
        f"{API_URL}/api/pro-mode/input-files/upload",
        headers=headers,
        data=data
    ) as response:
        return response.status

async def run_load_test():
    """Simulate multiple users uploading files"""
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        
        # 10 users from Group A
        for i in range(10):
            task = upload_file(session, USER_A_TOKEN, GROUP_A_ID, i)
            tasks.append(task)
        
        # 10 users from Group B
        for i in range(10):
            task = upload_file(session, USER_B_TOKEN, GROUP_B_ID, i)
            tasks.append(task)
        
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        duration = time.time() - start_time
        
        success_count = sum(1 for r in results if r == 200)
        print(f"✅ Completed {success_count}/20 uploads in {duration:.2f}s")

if __name__ == "__main__":
    asyncio.run(run_load_test())
```

**Validation Checklist:**
- [ ] Concurrent uploads from different groups work
- [ ] No cross-group data contamination
- [ ] Response times acceptable (<5s per upload)
- [ ] No memory leaks or resource exhaustion

---

## ✅ **Pre-Deployment Checklist**

### **Azure AD Configuration:**
- [ ] Tenant ID configured correctly
- [ ] App registration exists
- [ ] Groups claim in token configuration
- [ ] Microsoft Graph API permissions granted
- [ ] Admin consent given
- [ ] Test groups created
- [ ] Test users assigned to groups
- [ ] JWT tokens contain groups claim

### **Backend Configuration:**
- [ ] Environment variables set
- [ ] Authentication middleware working
- [ ] Group validation functioning
- [ ] Container naming correct
- [ ] Cosmos DB filtering by group_id
- [ ] Blob storage isolation working
- [ ] All endpoints include group validation

### **Frontend Configuration:**
- [ ] Group selector renders
- [ ] Microsoft Graph integration works
- [ ] Group names display correctly
- [ ] X-Group-ID header sent
- [ ] Group selection persists
- [ ] Multi-group switching works

### **Security Tests:**
- [ ] Unauthorized access blocked (403)
- [ ] Invalid group IDs rejected
- [ ] Token expiration handled
- [ ] Error messages appropriate
- [ ] No sensitive data leaked

### **Integration Tests:**
- [ ] End-to-end workflows complete
- [ ] File upload/download isolated
- [ ] Schema management isolated
- [ ] Analysis runs isolated
- [ ] Cross-group switching works

### **Performance Tests:**
- [ ] Load testing passed
- [ ] No performance degradation
- [ ] Resource usage acceptable
- [ ] No data contamination under load

---

## 🎯 **Test Results Summary Template**

```markdown
# Pre-Deployment Test Results

**Date:** [Date]
**Tested By:** [Name]
**Environment:** [Dev/Staging]
**Duration:** [Hours]

## Azure AD Tests
- [✅/❌] Tenant configuration
- [✅/❌] Groups claim
- [✅/❌] Graph API permissions
- [✅/❌] Test groups created
- [✅/❌] JWT tokens valid

## Frontend Tests
- [✅/❌] Group selector
- [✅/❌] Graph API integration
- [✅/❌] Group persistence
- [✅/❌] Header injection

## Backend Tests
- [✅/❌] Authentication
- [✅/❌] Group validation
- [✅/❌] Container naming
- [✅/❌] Error handling

## Storage Tests
- [✅/❌] Blob isolation
- [✅/❌] Cosmos filtering
- [✅/❌] Cross-group protection

## Integration Tests
- [✅/❌] File workflow
- [✅/❌] Schema management
- [✅/❌] Analysis runs
- [✅/❌] Group switching

## Security Tests
- [✅/❌] Unauthorized access blocked
- [✅/❌] Invalid inputs rejected
- [✅/❌] Token validation

## Performance Tests
- [✅/❌] Load test passed
- [✅/❌] Response times acceptable
- [✅/❌] No data contamination

## Issues Found
[List any issues discovered during testing]

## Recommendations
[Any recommendations before production deployment]

## Sign-off
- [ ] All critical tests passed
- [ ] All blockers resolved
- [ ] Ready for production deployment

**Approved by:** [Name]
**Date:** [Date]
```

---

## 📚 **Related Documentation**

| Document | Purpose |
|----------|---------|
| `DEPLOYMENT_GROUP_ISOLATION_FAQ.md` | Deployment requirements and FAQs |
| `AZURE_PORTAL_ONLY_GROUP_MANAGEMENT.md` | Group management procedures |
| `GROUP_REGISTRATION_DECISION_TREE.md` | Group registration options |
| `AZURE_AD_ROLES_QUICK_REFERENCE.md` | Required Azure AD roles |

---

**Remember:** Thorough pre-deployment testing prevents production issues! 🛡️
