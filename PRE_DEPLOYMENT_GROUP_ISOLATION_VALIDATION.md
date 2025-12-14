# 🧪 Pre-Deployment Group Isolation Validation

## 📊 **Your Current Status**
- ✅ Application deployed to Azure (without group isolation)
- ✅ Azure AD configured (App registrations, Tenant ID, Client IDs)
- ❌ Group isolation code NOT deployed yet
- 🎯 **Objective:** Validate Azure AD setup BEFORE deploying group isolation features

---

## 🎯 **Testing Strategy: 2-Phase Approach**

### **Phase 1: Azure AD Readiness Tests** ⏱️ 30 minutes
Validate Azure AD configuration is ready for group isolation

### **Phase 2: Local Development Tests** ⏱️ 45 minutes  
Test group isolation code locally before deployment

---

## 📋 **PHASE 1: Azure AD Readiness Tests**

### **Test 1.1: Verify App Registrations**

**What to check:**
```bash
1. Azure Portal → Azure Active Directory → App registrations
2. Find your two app registrations:
   - API App Registration
   - Web App Registration
3. Note down the Application (client) IDs
```

**Validation:**
- [ ] API App Registration exists
- [ ] Web App Registration exists
- [ ] Both have valid Client IDs
- [ ] You can access both app registrations

**Expected Output:**
```
API App:
  - Name: content-processor-api (or similar)
  - Client ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  - Status: Active

Web App:
  - Name: content-processor-web (or similar)
  - Client ID: yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
  - Status: Active
```

---

### **Test 1.2: Verify Tenant Configuration**

**Steps:**
```bash
1. Azure Portal → Azure Active Directory
2. Click "Overview" in left sidebar
3. Look for "Tenant ID" in the overview section
```

**Validation:**
- [ ] Tenant ID visible and can be copied
- [ ] Tenant type is "Azure Active Directory" (not B2C)
- [ ] You have sufficient permissions to view tenant

**Document Your Tenant ID:**
```
Tenant ID: ________________________________________
Tenant Type: Single Tenant / Multi-Tenant
```

---

### **Test 1.3: Check Security Groups**

**Current State Check:**
```bash
1. Azure Portal → Azure Active Directory → Groups
2. Check if any security groups exist
3. If yes, note them down
4. If no, we'll create test groups
```

**What You Need:**
- [ ] At least 2-3 test security groups
- [ ] Groups are type "Security" (not Microsoft 365)
- [ ] You have permission to create groups if needed

**Action: Create Test Groups (If None Exist)**

Run this script or create manually:

```bash
#!/bin/bash
# create_test_groups.sh

echo "Creating test security groups for group isolation testing..."

# Method 1: Using Azure CLI
az ad group create \
  --display-name "Test-Marketing" \
  --mail-nickname "test-marketing" \
  --description "Test group for Content Processor - Marketing team"

az ad group create \
  --display-name "Test-Sales" \
  --mail-nickname "test-sales" \
  --description "Test group for Content Processor - Sales team"

az ad group create \
  --display-name "Test-Engineering" \
  --mail-nickname "test-engineering" \
  --description "Test group for Content Processor - Engineering team"

# Get group IDs
echo ""
echo "✅ Groups created! Getting Group IDs..."
az ad group list --query "[?displayName=='Test-Marketing'].{Name:displayName, ID:id}" -o table
az ad group list --query "[?displayName=='Test-Sales'].{Name:displayName, ID:id}" -o table
az ad group list --query "[?displayName=='Test-Engineering'].{Name:displayName, ID:id}" -o table
```

**Or create via Azure Portal:**
```
1. Azure AD → Groups → New group
2. Group type: Security
3. Group name: Test-Marketing
4. Group description: Test group for Content Processor
5. Click "Create"
6. Repeat for Test-Sales and Test-Engineering
```

**Document Your Groups:**
```
Group 1:
  - Name: _______________________
  - Object ID: ___________________________________

Group 2:
  - Name: _______________________
  - Object ID: ___________________________________

Group 3:
  - Name: _______________________
  - Object ID: ___________________________________
```

---

### **Test 1.4: Assign Test Users to Groups**

**You Need:**
- At least 2-3 test user accounts
- Users can be your own account + colleagues

**Recommended Test User Matrix:**
```
User A: Member of Test-Marketing only
User B: Member of Test-Sales only
User C: Member of BOTH Test-Marketing and Test-Sales (multi-group testing)
User D: Not member of any group (access denial testing)
```

**Assign Users:**
```bash
# Via Azure Portal:
1. Azure AD → Groups → Test-Marketing
2. Members → Add members
3. Search for user email
4. Select user and click "Select"
5. Repeat for other groups/users

# Via Azure CLI:
az ad group member add \
  --group "Test-Marketing" \
  --member-id $(az ad user show --id "usera@yourorg.com" --query id -o tsv)
```

**Document User Assignments:**
```
User A: ____________________ | Groups: [ Test-Marketing ]
User B: ____________________ | Groups: [ Test-Sales ]
User C: ____________________ | Groups: [ Test-Marketing, Test-Sales ]
User D: ____________________ | Groups: [ ]
```

---

### **Test 1.5: Configure Token Claims (CRITICAL)**

**This is THE most important pre-deployment test!**

#### **Step 1: Add Groups Claim to API App**

```bash
1. Azure Portal → App Registrations → [Your API App]
2. Token configuration (left sidebar)
3. Click "+ Add groups claim"
4. Select: ✅ Security groups
5. Customize token properties:
   - ID: ✅ Check
   - Access: ✅ Check
   - SAML: Leave unchecked
6. Advanced options:
   - Emit groups as group IDs: ✅ Select this
7. Click "Add"
```

**Validation:**
- [ ] Groups claim added to token configuration
- [ ] Configured for Security groups
- [ ] Emits as Group IDs (not names)
- [ ] Applied to both ID and Access tokens

#### **Step 2: Add Groups Claim to Web App**

```bash
1. Azure Portal → App Registrations → [Your Web App]
2. Token configuration (left sidebar)
3. Click "+ Add groups claim"
4. Select: ✅ Security groups
5. Same settings as API app
6. Click "Add"
```

**Validation:**
- [ ] Groups claim added to Web app
- [ ] Same configuration as API app
- [ ] Both ID and Access tokens selected

---

### **Test 1.6: Add Microsoft Graph API Permissions**

**Why:** Your app needs to read group names from Microsoft Graph API

#### **Step 1: Add API Permissions**

```bash
1. Azure Portal → App Registrations → [Your API App]
2. API permissions (left sidebar)
3. Click "+ Add a permission"
4. Select "Microsoft Graph"
5. Select "Application permissions"
6. Search for "Group.Read.All" or "Directory.Read.All"
7. Check the permission
8. Click "Add permissions"
```

#### **Step 2: Grant Admin Consent**

```bash
1. Still in API permissions page
2. Click "Grant admin consent for [your tenant]"
3. Click "Yes" to confirm
4. Wait for green checkmark
```

**Validation:**
- [ ] Microsoft Graph permission added
- [ ] Either Group.Read.All OR Directory.Read.All
- [ ] Admin consent granted (green checkmark)
- [ ] Status shows "Granted for [your tenant]"

**Repeat for Web App Registration**

---

### **Test 1.7: Verify JWT Token Contains Groups**

**This validates everything is working!**

#### **Method 1: Use jwt.ms (Recommended)**

```bash
1. Open a new browser in Incognito/Private mode
2. Navigate to your deployed app URL
3. Log in as User A (Test-Marketing member)
4. Open browser DevTools (F12)
5. Go to Application tab → Session Storage
6. Find MSAL token (look for keys containing "accesstoken")
7. Copy the token value (long string starting with "eyJ...")
8. Go to https://jwt.ms
9. Paste the token
10. Look for "groups" claim in the decoded token
```

**Expected Token Payload:**
```json
{
  "aud": "api://your-client-id",
  "iss": "https://login.microsoftonline.com/your-tenant-id/v2.0",
  "iat": 1234567890,
  "nbf": 1234567890,
  "exp": 1234567890,
  "oid": "user-object-id",
  "sub": "user-subject-id",
  "name": "Test User A",
  "preferred_username": "usera@yourorg.com",
  "groups": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890"  ← Test-Marketing group ID
  ],
  "tid": "your-tenant-id",
  "ver": "2.0"
}
```

**Validation:**
- [ ] Token has "groups" claim
- [ ] "groups" is an array
- [ ] Array contains group Object IDs (GUIDs)
- [ ] Group IDs match the groups in Azure AD

**Test All Users:**
- [ ] User A token: Contains Test-Marketing group ID
- [ ] User B token: Contains Test-Sales group ID
- [ ] User C token: Contains BOTH group IDs
- [ ] User D token: Empty groups array or no groups claim

#### **Method 2: Automated Script**

Save this as `test_token_groups.py`:

```python
#!/usr/bin/env python3
"""
Test Azure AD JWT tokens contain groups claim
"""
import jwt
import json
import sys

def decode_token(token_string):
    """Decode JWT token without verification (testing only)"""
    try:
        # Decode without verification (for testing)
        decoded = jwt.decode(token_string, options={"verify_signature": False})
        return decoded
    except Exception as e:
        print(f"❌ Error decoding token: {e}")
        return None

def validate_groups_claim(decoded_token):
    """Validate groups claim in token"""
    print("\n🔍 Token Claims Analysis")
    print("=" * 60)
    
    # Check user identification
    user_id = decoded_token.get('oid') or decoded_token.get('sub')
    print(f"✅ User ID: {user_id}")
    
    user_email = decoded_token.get('preferred_username') or decoded_token.get('upn')
    print(f"✅ Email: {user_email}")
    
    user_name = decoded_token.get('name')
    print(f"✅ Name: {user_name}")
    
    # Check groups claim
    print("\n🔍 Groups Claim Analysis")
    print("-" * 60)
    
    if 'groups' not in decoded_token:
        print("❌ FAIL: No 'groups' claim in token")
        print("\n⚠️  This means token configuration is not complete!")
        print("   → Go to App Registration → Token configuration")
        print("   → Add 'groups' claim")
        return False
    
    groups = decoded_token.get('groups', [])
    
    if not isinstance(groups, list):
        print(f"❌ FAIL: 'groups' is not an array, it's: {type(groups)}")
        return False
    
    if len(groups) == 0:
        print("⚠️  WARNING: 'groups' array is empty")
        print("   → This user is not member of any groups")
        print("   → OR groups were not assigned to the application")
        return True  # Not a failure, user just has no groups
    
    print(f"✅ PASS: Found {len(groups)} group(s)")
    print("\nGroup IDs in token:")
    for i, group_id in enumerate(groups, 1):
        print(f"  {i}. {group_id}")
    
    return True

def main():
    """Main test function"""
    print("🧪 Azure AD Token Groups Claim Validator")
    print("=" * 60)
    
    if len(sys.argv) < 2:
        print("\n❌ Usage: python test_token_groups.py <JWT_TOKEN>")
        print("\nHow to get token:")
        print("1. Login to your app")
        print("2. Open browser DevTools → Application → Session Storage")
        print("3. Find MSAL token")
        print("4. Copy the token value")
        print("5. Run: python test_token_groups.py 'your-token-here'")
        sys.exit(1)
    
    token = sys.argv[1]
    
    decoded = decode_token(token)
    if not decoded:
        sys.exit(1)
    
    print("\n📋 Full Token Payload:")
    print(json.dumps(decoded, indent=2))
    
    success = validate_groups_claim(decoded)
    
    print("\n" + "=" * 60)
    if success:
        print("✅ VALIDATION PASSED - Token is ready for group isolation!")
    else:
        print("❌ VALIDATION FAILED - Fix token configuration before deployment")
    print("=" * 60)
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
```

**Run the test:**
```bash
python test_token_groups.py "eyJhbGciOiJSUzI1NiIsImtpZCI6IjFMVE16YWtpaG..."
```

---

## ✅ **Phase 1 Completion Checklist**

Before proceeding to Phase 2, ensure:

### **Azure AD Configuration:**
- [ ] App Registrations verified (API + Web)
- [ ] Tenant ID documented
- [ ] Security groups created (at least 2-3)
- [ ] Test users assigned to groups
- [ ] Groups claim added to token configuration (API + Web)
- [ ] Microsoft Graph API permissions granted
- [ ] Admin consent completed
- [ ] JWT tokens contain groups claim (verified)

### **Documentation Complete:**
- [ ] All group Object IDs documented
- [ ] All test user assignments documented
- [ ] Token validation test passed
- [ ] Screenshots saved (optional but recommended)

**If all checked:** ✅ **READY for Phase 2 - Local Development Testing**

**If issues found:** ❌ **Fix issues before proceeding**

---

## 🚀 **PHASE 2: Local Development Tests**

**Prerequisite:** Phase 1 must be 100% complete

### **Test 2.1: Set Up Local Test Environment**

#### **Step 1: Clone/Update Code**

```bash
# Ensure you have latest group isolation code
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939
git pull origin main  # Or your branch with group isolation code
```

#### **Step 2: Configure Environment Variables**

Create/update `.env` file:

```bash
# API Backend .env
cd code/content-processing-solution-accelerator/src/ContentProcessorAPI/app

# Create .env.dev for local testing
cat > .env.dev <<EOF
# Azure AD Configuration
AZURE_AD_TENANT_ID=your-tenant-id-here
AZURE_AD_CLIENT_ID=your-api-client-id-here

# Development Mode
APP_ENV=dev

# Database (use test database)
COSMOS_CONNECTION_STRING=your-cosmos-connection-string
COSMOS_DATABASE=test_content_processor

# Storage (use test storage)
AZURE_STORAGE_CONNECTION_STRING=your-storage-connection-string

# Feature Flags
GROUP_ISOLATION_ENABLED=true
EOF
```

#### **Step 3: Update Frontend .env**

```bash
cd ../../../ContentProcessorWeb

cat > .env.local <<EOF
# Azure AD Configuration
REACT_APP_WEB_CLIENT_ID=your-web-client-id
REACT_APP_WEB_AUTHORITY=https://login.microsoftonline.com/your-tenant-id
REACT_APP_API_SCOPE=api://your-api-client-id/user_impersonation

# API URL
REACT_APP_API_BASE_URL=http://localhost:8000

# Feature Flags
REACT_APP_FEATURE_PRO_MODE=true
REACT_APP_AUTH_ENABLED=true
EOF
```

---

### **Test 2.2: Start Backend API Locally**

```bash
cd code/content-processing-solution-accelerator/src/ContentProcessorAPI

# Install dependencies
pip install -r requirements.txt

# Start API server
uvicorn app.main:app --reload --port 8000 --env-file app/.env.dev
```

**Validation:**
- [ ] Server starts without errors
- [ ] Can access http://localhost:8000/docs
- [ ] No authentication errors in logs
- [ ] Swagger UI loads

---

### **Test 2.3: Start Frontend Locally**

```bash
cd code/content-processing-solution-accelerator/src/ContentProcessorWeb

# Install dependencies
npm install

# Start dev server
npm start
```

**Validation:**
- [ ] Frontend starts on http://localhost:3000
- [ ] No build errors
- [ ] MSAL authentication initializes
- [ ] Can see login button/prompt

---

### **Test 2.4: Test Authentication Flow**

```bash
1. Navigate to http://localhost:3000
2. Click login
3. Sign in with User A (Test-Marketing member)
4. Should redirect back to app
5. Open DevTools → Console
6. Look for authentication success messages
```

**Expected Console Output:**
```
[MSAL] Login successful
[MSAL] Token acquired
[Auth] User authenticated: usera@yourorg.com
[Auth] Groups: ["a1b2c3d4-..."]
```

**Validation:**
- [ ] Login succeeds
- [ ] Token acquired
- [ ] Groups extracted from token
- [ ] No authentication errors

---

### **Test 2.5: Test Group Selector**

**If group isolation UI is implemented:**

```bash
1. After login, look for group selector in header/navigation
2. Should show: "Test-Marketing" (or the short ID if Graph API not configured)
3. Click dropdown
4. Should only show groups user belongs to
```

**Validation:**
- [ ] Group selector visible
- [ ] Shows correct group(s) for user
- [ ] Can select group
- [ ] Selection persists after page refresh

---

### **Test 2.6: Test API Calls with Group Header**

**Open browser DevTools → Network tab:**

```bash
1. Navigate to any feature (Schema tab, File upload, etc.)
2. Trigger an API call
3. Inspect the request headers
4. Look for: X-Group-ID header
```

**Expected Headers:**
```
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
X-Group-ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
Content-Type: application/json
```

**Validation:**
- [ ] X-Group-ID header present in requests
- [ ] Header value matches selected group
- [ ] Authorization header also present
- [ ] API calls succeed (200 status)

---

### **Test 2.7: Test Group Isolation (Critical Test)**

**Test Scenario:** Different users should NOT see each other's data

#### **Test 2.7.1: Upload File as User A**

```bash
1. Login as User A (Test-Marketing)
2. Select Test-Marketing group
3. Upload a file: "marketing-document.pdf"
4. Verify file appears in file list
5. Note the file name
```

#### **Test 2.7.2: Switch to User B**

```bash
1. Logout
2. Login as User B (Test-Sales)
3. Select Test-Sales group
4. Check file list
5. Verify: "marketing-document.pdf" should NOT be visible
```

**Validation:**
- [ ] User A can see their file
- [ ] User B cannot see User A's file
- [ ] Files are isolated by group
- [ ] No cross-group data leakage

#### **Test 2.7.3: Multi-Group User (User C)**

```bash
1. Login as User C (member of both groups)
2. Select Test-Marketing group
3. Should see: marketing-document.pdf
4. Switch to Test-Sales group
5. Should NOT see: marketing-document.pdf
6. Upload different file in Test-Sales
7. Switch back to Test-Marketing
8. Should NOT see: Sales file
```

**Validation:**
- [ ] User C sees correct files per group
- [ ] Switching groups updates data
- [ ] No mixing of data between groups

---

### **Test 2.8: Test Backend API Directly (Optional)**

**Use curl or Postman to test API endpoints:**

```bash
# Get real JWT token from browser
TOKEN="eyJhbGciOiJSUzI1NiIs..."
GROUP_ID="a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# Test 1: Get schemas (with group)
curl -X GET http://localhost:8000/api/pro-mode/schemas \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Group-ID: $GROUP_ID"

# Expected: 200 OK, schemas for that group

# Test 2: Try different group (should fail if user not member)
WRONG_GROUP="different-group-id-here"
curl -X GET http://localhost:8000/api/pro-mode/schemas \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Group-ID: $WRONG_GROUP"

# Expected: 403 Forbidden

# Test 3: Upload file with group isolation
curl -X POST http://localhost:8000/api/pro-mode/input-files/upload \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Group-ID: $GROUP_ID" \
  -F "file=@test-document.pdf"

# Expected: 200 OK, file uploaded to group-specific container
```

**Validation:**
- [ ] Authorized group access succeeds (200)
- [ ] Unauthorized group access fails (403)
- [ ] Files go to group-specific containers
- [ ] API enforces group validation

---

## ✅ **Phase 2 Completion Checklist**

### **Local Environment:**
- [ ] Backend API running locally
- [ ] Frontend running locally
- [ ] Authentication working
- [ ] Group selector functional (if implemented)

### **Functional Tests:**
- [ ] Login/logout working
- [ ] Groups extracted from token
- [ ] X-Group-ID header sent in requests
- [ ] File upload works with group isolation
- [ ] Data isolated between groups
- [ ] Multi-group users can switch groups

### **Security Tests:**
- [ ] Cross-group access blocked (403)
- [ ] Invalid group IDs rejected
- [ ] Unauthorized users blocked
- [ ] No data leakage between groups

**If all checked:** ✅ **READY FOR DEPLOYMENT**

**If issues found:** ❌ **Fix issues before deployment**

---

## 🚀 **Post-Validation: Deployment Preparation**

### **Deployment Checklist**

#### **1. Environment Variables for Production**

**API Container App:**
```bash
AZURE_AD_TENANT_ID=<your-tenant-id>
AZURE_AD_CLIENT_ID=<your-api-client-id>
GROUP_ISOLATION_ENABLED=true
APP_ENV=prod
```

**Web Container App:**
```bash
REACT_APP_WEB_CLIENT_ID=<your-web-client-id>
REACT_APP_WEB_AUTHORITY=https://login.microsoftonline.com/<your-tenant-id>
REACT_APP_API_SCOPE=api://<your-api-client-id>/user_impersonation
REACT_APP_AUTH_ENABLED=true
REACT_APP_FEATURE_PRO_MODE=true
```

#### **2. Azure Resources Verification**

- [ ] Storage Account: System-assigned managed identity has "Storage Blob Data Contributor"
- [ ] Cosmos DB: Managed identity has "Cosmos DB Built-in Data Contributor"
- [ ] Container App: System-assigned managed identity enabled
- [ ] Microsoft Graph: App registration has permissions (verified in Phase 1)

#### **3. Deployment Strategy**

**Option A: Blue-Green Deployment (Recommended)**
```bash
1. Deploy new version to staging slot
2. Test in staging with real users
3. Swap staging → production when validated
4. Rollback available if issues
```

**Option B: Direct Deployment**
```bash
1. Deploy directly to production
2. Monitor logs closely
3. Have rollback plan ready
```

#### **4. Post-Deployment Validation**

**Immediately after deployment:**
```bash
1. Check container app logs for errors
2. Login as test user
3. Verify groups appear in token (jwt.ms)
4. Verify group selector works
5. Test file upload with group isolation
6. Verify cross-group access blocked
7. Test with multiple users
```

---

## 📊 **Test Results Documentation Template**

Save this for your records:

```markdown
# Group Isolation Pre-Deployment Test Results

**Date:** [DATE]
**Tester:** [YOUR NAME]
**Environment:** Local Development

---

## Phase 1: Azure AD Configuration

### App Registrations
- [ ] API App: [CLIENT_ID] - Status: ✅/❌
- [ ] Web App: [CLIENT_ID] - Status: ✅/❌

### Tenant Configuration
- Tenant ID: [TENANT_ID]
- Tenant Type: Single Tenant
- Status: ✅/❌

### Security Groups
- Group 1: [NAME] - [OBJECT_ID] - Status: ✅/❌
- Group 2: [NAME] - [OBJECT_ID] - Status: ✅/❌
- Group 3: [NAME] - [OBJECT_ID] - Status: ✅/❌

### Test Users
- User A: [EMAIL] - Groups: [LIST] - Status: ✅/❌
- User B: [EMAIL] - Groups: [LIST] - Status: ✅/❌
- User C: [EMAIL] - Groups: [LIST] - Status: ✅/❌
- User D: [EMAIL] - Groups: [] - Status: ✅/❌

### Token Configuration
- API App groups claim: ✅/❌
- Web App groups claim: ✅/❌
- Graph API permissions: ✅/❌
- Admin consent: ✅/❌

### Token Validation
- User A token contains groups: ✅/❌
- User B token contains groups: ✅/❌
- User C token contains groups: ✅/❌
- User D token (no groups): ✅/❌

**Phase 1 Result:** ✅ PASS / ❌ FAIL

---

## Phase 2: Local Development Tests

### Environment Setup
- Backend API running: ✅/❌
- Frontend running: ✅/❌
- Environment variables configured: ✅/❌

### Authentication
- Login successful: ✅/❌
- Token acquired: ✅/❌
- Groups extracted: ✅/❌

### Group Isolation
- File upload (User A): ✅/❌
- File isolation (User B can't see): ✅/❌
- Multi-group switching (User C): ✅/❌
- Unauthorized access blocked: ✅/❌

### API Validation
- X-Group-ID header sent: ✅/❌
- Group validation working: ✅/❌
- 403 for unauthorized groups: ✅/❌

**Phase 2 Result:** ✅ PASS / ❌ FAIL

---

## Issues Found

[List any issues discovered during testing]

1. Issue: [DESCRIPTION]
   - Severity: High/Medium/Low
   - Status: Open/Fixed
   
2. Issue: [DESCRIPTION]
   - Severity: High/Medium/Low
   - Status: Open/Fixed

---

## Deployment Recommendation

- [ ] ✅ APPROVED for deployment - All tests passed
- [ ] ❌ NOT READY - Issues must be fixed first
- [ ] ⚠️  CONDITIONAL - Deploy with monitoring

**Approver:** [NAME]
**Date:** [DATE]
```

---

## 🎯 **Next Steps After Validation**

### **If All Tests Pass:**
1. ✅ Document test results
2. ✅ Update deployment scripts with env variables
3. ✅ Create deployment runbook
4. ✅ Schedule deployment window
5. ✅ Prepare rollback plan
6. ✅ Deploy to production!

### **If Tests Fail:**
1. ❌ Document failures
2. ❌ Fix issues in code
3. ❌ Re-run failed tests
4. ❌ Repeat until all pass
5. ❌ Then proceed to deployment

---

## 📚 **Related Documentation**

- `PRE_DEPLOYMENT_TESTING_GUIDE.md` - Full testing procedures
- `AZURE_PORTAL_ONLY_GROUP_MANAGEMENT.md` - Group management guide
- `DEPLOYMENT_GROUP_ISOLATION_FAQ.md` - Deployment FAQs
- `MIGRATION_GUIDE_ALL_GROUPS_TO_ASSIGNED_GROUPS.md` - Migration procedures

---

**Ready to start testing?** Begin with Phase 1, Test 1.1! 🚀
