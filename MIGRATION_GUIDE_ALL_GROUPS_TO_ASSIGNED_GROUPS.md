# 🔒 Migration Guide: All Groups → Assigned Groups Only

## 📋 **Overview**

This guide provides step-by-step instructions for migrating from **Option A (All Security Groups)** to **Option B (Assigned Groups Only)** with **zero code changes** and **zero downtime**.

**Migration Type:** Azure Portal Configuration Only  
**Code Changes Required:** None ✅  
**Estimated Time:** 30-60 minutes  
**Rollback Time:** 5 minutes  
**Risk Level:** Low (if steps followed correctly)

---

## 🎯 **Migration Goals**

### **From: Option A (All Security Groups - Current State)**
```
Configuration: "Security groups" in token configuration
Behavior: ALL Azure AD security groups appear in JWT tokens
Access: Any user in any security group can access the app
Management: Groups work automatically, no registration needed
```

### **To: Option B (Assigned Groups Only - Target State)**
```
Configuration: "Groups assigned to the application" in token configuration
Behavior: ONLY assigned groups appear in JWT tokens
Access: Only users in assigned groups can access the app
Management: New groups must be explicitly assigned to enterprise application
```

### **Why Migrate?**
- 🔒 **Enhanced Security**: Explicit control over which groups can access
- 📋 **Compliance**: Meet requirements for explicit access grants
- 🎯 **Access Control**: Prevent unauthorized group access
- 📊 **Audit Trail**: Clear record of approved groups

---

## ⚠️ **Pre-Migration Checklist**

### **Required Roles:**
- [ ] **Application Administrator** or **Global Administrator** (for token configuration)
- [ ] **Application Administrator** (for group assignments)
- [ ] **Groups Administrator** (optional, for group verification)

### **Required Information:**
- [ ] List of all groups currently using the application
- [ ] List of users in each group (for testing)
- [ ] Test user credentials from each group
- [ ] Application Client ID and Tenant ID
- [ ] Enterprise Application name

### **Prerequisites:**
- [ ] Application is deployed and working
- [ ] Users can currently access the app
- [ ] Groups are visible in group selector
- [ ] No active deployments or maintenance

### **Preparation:**
- [ ] Schedule migration window (recommend: low-usage time)
- [ ] Notify users of upcoming change
- [ ] Identify support personnel for day of migration
- [ ] Prepare rollback plan communication

---

## 📊 **Phase 1: Discovery & Documentation**

### **Step 1.1: Identify Current Groups**

**Method 1: Check Azure AD Groups**
```bash
# Azure CLI
az ad group list --query "[].{Name:displayName, ID:id}" -o table

# Or use Azure Portal:
1. Azure Portal → Azure Active Directory → Groups
2. Filter: Groups with members
3. Export list to Excel/CSV
```

**Method 2: Check Application Logs**
```bash
# If you have logging enabled
1. Check backend logs for group_id values
2. Look for X-Group-ID header values
3. Query Cosmos DB for unique group_id values:
   SELECT DISTINCT c.group_id FROM c WHERE c.group_id != null
```

**Method 3: Check JWT Tokens**
```bash
# Have users from different teams test:
1. User logs into app
2. User goes to: https://jwt.ms
3. Paste their token
4. Look at "groups" claim
5. Document all group IDs
```

**Document in spreadsheet:**
```
| Group Name          | Group ID              | Member Count | Priority | Notes           |
|---------------------|----------------------|--------------|----------|-----------------|
| Marketing Team      | a1b2c3d4-e5f6-...   | 12           | High     | Active users    |
| Sales Team          | b2c3d4e5-f6g7-...   | 8            | High     | Active users    |
| Engineering Team    | c3d4e5f6-g7h8-...   | 25           | High     | Active users    |
| Finance Team        | d4e5f6g7-h8i9-...   | 5            | Medium   | Occasional use  |
| Contractors         | e5f6g7h8-i9j0-...   | 3            | Low      | Rarely used     |
```

---

### **Step 1.2: Verify Current Configuration**

**Check Token Configuration:**
```bash
1. Azure Portal → App Registrations
2. Find: Your API application (e.g., "content-processor-api")
3. Click: Token configuration
4. Look for: "groups" claim
5. Check "Group types" column
6. Current should show: "Security groups"
```

**Document current state:**
```
✅ Current Configuration:
   - Claim: groups
   - Group types: Security groups
   - Emit as: Group IDs
   - Tokens: ID, Access
```

---

### **Step 1.3: Identify Test Users**

**Select test users (at least 2 per group):**
```
| Group Name          | Test User 1        | Test User 2        | Status |
|---------------------|--------------------|--------------------|--------|
| Marketing Team      | alice@yourorg.com  | bob@yourorg.com    | Ready  |
| Sales Team          | carol@yourorg.com  | dave@yourorg.com   | Ready  |
| Engineering Team    | eve@yourorg.com    | frank@yourorg.com  | Ready  |
```

**Provide test instructions:**
```markdown
Test Script for Users:
1. Log into the application
2. Check that you can see your group in the dropdown
3. Select your group
4. Upload a test file
5. Verify you can see the file
6. Report: Success or Error
```

---

## 🔧 **Phase 2: Pre-Migration Setup**

### **Step 2.1: Assign Groups to Enterprise Application**

**⚠️ CRITICAL: Do this BEFORE changing token configuration!**

**For EACH group identified in Phase 1:**

#### **Process A: Using Azure Portal**
```bash
1. Navigate to Enterprise Applications
   Azure Portal → Azure Active Directory → Enterprise applications
   
2. Find your application
   Search: "content-processor" or your app name
   Click: Your application
   
3. Go to Users and groups
   Left menu → Users and groups
   
4. Add group assignment
   Click: + Add user/group
   
5. Select the group
   Click: None Selected (under Users and groups)
   Search: "Marketing Team"
   Select: The group
   Click: Select
   
6. Assign role (if applicable)
   Role: Default Access (or custom role if defined)
   Click: Assign
   
7. Verify assignment
   You should see the group listed
   Note the assignment date/time
   
8. Repeat for each group
   Do NOT skip any active groups!
```

#### **Process B: Using Azure CLI**
```bash
# Get Enterprise Application Object ID
APP_ID=$(az ad sp list --display-name "content-processor-api" --query "[0].id" -o tsv)

# Get Group Object ID
GROUP_ID=$(az ad group show --group "Marketing Team" --query "id" -o tsv)

# Assign group to application
az ad app-role-assignment create \
  --assignee-object-id $GROUP_ID \
  --app-role-id 00000000-0000-0000-0000-000000000000 \
  --resource-id $APP_ID

# Repeat for each group
```

#### **Process C: Bulk Assignment Script**
```bash
#!/bin/bash
# bulk_assign_groups.sh

APP_NAME="content-processor-api"
GROUPS=("Marketing Team" "Sales Team" "Engineering Team" "Finance Team")

# Get application service principal ID
APP_ID=$(az ad sp list --display-name "$APP_NAME" --query "[0].id" -o tsv)

if [ -z "$APP_ID" ]; then
    echo "❌ Application not found: $APP_NAME"
    exit 1
fi

echo "✅ Found application: $APP_NAME (ID: $APP_ID)"
echo ""

# Assign each group
for GROUP_NAME in "${GROUPS[@]}"; do
    echo "📋 Processing: $GROUP_NAME"
    
    # Get group ID
    GROUP_ID=$(az ad group show --group "$GROUP_NAME" --query "id" -o tsv 2>/dev/null)
    
    if [ -z "$GROUP_ID" ]; then
        echo "   ⚠️  Group not found: $GROUP_NAME"
        continue
    fi
    
    # Assign to application
    az ad app-role-assignment create \
        --assignee-object-id "$GROUP_ID" \
        --app-role-id 00000000-0000-0000-0000-000000000000 \
        --resource-id "$APP_ID" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        echo "   ✅ Assigned: $GROUP_NAME"
    else
        echo "   ⚠️  Already assigned or error: $GROUP_NAME"
    fi
    echo ""
done

echo "🎉 Bulk assignment complete!"
```

**Usage:**
```bash
chmod +x bulk_assign_groups.sh
./bulk_assign_groups.sh
```

---

### **Step 2.2: Verify All Assignments**

**Check in Azure Portal:**
```bash
1. Azure Portal → Enterprise Applications → [Your App]
2. Users and groups
3. Verify ALL groups from Step 1.1 are listed
4. Check assignment dates (should be recent)
```

**Expected output:**
```
Users and groups (7)
- Marketing Team          Group    [Date]    Default Access
- Sales Team              Group    [Date]    Default Access
- Engineering Team        Group    [Date]    Default Access
- Finance Team            Group    [Date]    Default Access
- alice@yourorg.com       User     [Date]    Default Access
- bob@yourorg.com         User     [Date]    Default Access
...
```

**Verification checklist:**
- [ ] All groups from Phase 1 are assigned
- [ ] Assignment count matches expected count
- [ ] No errors shown in portal
- [ ] Assignment dates are today

---

### **Step 2.3: Test with Current Configuration**

**Before changing anything, verify app still works:**

```bash
Test Plan:
1. Have test users log out completely
2. Clear browser cache
3. Log back in
4. Verify groups appear in dropdown
5. Verify can upload/download files
6. Verify can switch between groups

Expected Result: Everything works normally ✅
```

**Document baseline:**
```
✅ Pre-Migration Test Results (Option A still active):
   - User can log in: Yes
   - Groups visible: Yes (all groups)
   - Can upload files: Yes
   - Can download files: Yes
   - Can switch groups: Yes
   - Errors: None
```

---

## 🚀 **Phase 3: Execute Migration**

### **Step 3.1: Change Token Configuration**

**⚠️ This is the critical step - users must log out after this**

#### **Using Azure Portal:**
```bash
1. Navigate to App Registrations
   Azure Portal → App Registrations → [Your API App]
   
2. Go to Token configuration
   Left menu → Token configuration
   
3. Edit groups claim
   Find: "groups" claim
   Click: Edit
   
4. Change configuration
   Current: ✅ Security groups
   New: ✅ Groups assigned to the application
   
   Keep checked:
   ✅ Emit groups as group IDs (not names)
   ✅ ID (ID tokens)
   ✅ Access (Access tokens)
   
5. Save changes
   Click: Save
   
6. Note the time
   Document: Configuration changed at [timestamp]
```

#### **Verify the change:**
```bash
1. Refresh the Token configuration page
2. Verify "groups" claim shows:
   Group types: "Groups assigned to the application"
```

---

### **Step 3.2: Force Token Refresh**

**Users must get new tokens for change to take effect:**

#### **Option A: User Log Out (Recommended)**
```bash
Communication to users:
"Please log out and log back in to continue using the application.
This is required for a security update."

Instructions:
1. Click your profile icon
2. Click "Sign out"
3. Close browser tab
4. Reopen application
5. Log in again
```

#### **Option B: Wait for Token Expiration**
```bash
Tokens expire automatically after 1 hour
Groups will update automatically on next login
Monitor for 1 hour for automatic transition
```

#### **Option C: Session Invalidation (Advanced)**
```bash
Azure Portal → Users → [User] → Revoke sessions
This forces immediate re-authentication
Only needed if urgent
```

---

### **Step 3.3: Immediate Verification**

**Test within 5 minutes of configuration change:**

```bash
Test User Checklist:

For each test user:
1. ✅ User logs out
2. ✅ User logs back in
3. ✅ User sees group dropdown
4. ✅ Only assigned groups appear
5. ✅ Can select group
6. ✅ Can upload file
7. ✅ File appears in correct container
8. ✅ No errors in browser console

Document results:
- Marketing test user: ✅ Success
- Sales test user: ✅ Success
- Engineering test user: ✅ Success
```

**Check JWT tokens:**
```bash
1. User logs in
2. Go to https://jwt.ms
3. Paste token
4. Verify "groups" claim only contains assigned group IDs
5. Verify non-assigned groups are NOT in token
```

**Expected token (after migration):**
```json
{
  "groups": [
    "a1b2c3d4-e5f6-...",  // Only assigned groups!
    "b2c3d4e5-f6g7-..."   // Non-assigned groups missing
  ]
}
```

---

## 📊 **Phase 4: Post-Migration Validation**

### **Step 4.1: Monitor Application Logs**

**Check for errors:**
```bash
# Azure Portal → Container App → Log stream
# Look for:
- 403 Forbidden errors (indicates user lost access)
- "No access to group" messages
- Authentication failures

# Expected: No new errors
# If errors appear, check if user/group assignment missing
```

**Common issues and fixes:**
```bash
Issue: User gets 403 error
Fix: Check if their group is assigned to enterprise app

Issue: Group doesn't appear in dropdown
Fix: Verify group is assigned, user may need to log out/in

Issue: Old groups still visible
Fix: User needs to clear browser cache and re-login
```

---

### **Step 4.2: Test All Groups**

**Comprehensive testing plan:**

```bash
For EACH assigned group:

1. Test with 2 different users from that group
2. Verify both can:
   - Log in successfully
   - See the group in dropdown
   - Select the group
   - Upload a file
   - Download a file
   - List files in their group
   
3. Verify they CANNOT:
   - See files from other groups
   - Access containers of non-assigned groups

Document results:
| Group          | User 1 | User 2 | Upload | Download | Isolation | Status |
|----------------|--------|--------|--------|----------|-----------|--------|
| Marketing      | ✅     | ✅     | ✅     | ✅       | ✅        | Pass   |
| Sales          | ✅     | ✅     | ✅     | ✅       | ✅        | Pass   |
| Engineering    | ✅     | ✅     | ✅     | ✅       | ✅        | Pass   |
```

---

### **Step 4.3: Verify Non-Assigned Groups**

**If you have test groups that were NOT assigned:**

```bash
Test Plan:
1. Create a test security group (not assigned to app)
2. Add a test user to this group
3. User logs in
4. Expected: Test group does NOT appear in dropdown
5. Expected: User can only see assigned groups

Result: ✅ Confirms restriction is working
```

---

### **Step 4.4: Check Blob Storage**

**Verify container isolation:**
```bash
1. Azure Portal → Storage Account → Containers
2. Check that group-specific containers exist:
   - pro-input-files-group-a1b2c3d4/  (Marketing)
   - pro-input-files-group-b2c3d4e5/  (Sales)
   - pro-input-files-group-c3d4e5f6/  (Engineering)
3. Verify files in each container
4. Confirm no cross-contamination
```

---

### **Step 4.5: Check Cosmos DB**

**Verify data filtering:**
```bash
# Query for each group
Azure Portal → Cosmos DB → Data Explorer

Query 1: Check Marketing data
SELECT * FROM c WHERE c.group_id = 'a1b2c3d4-e5f6-...'

Query 2: Check Sales data
SELECT * FROM c WHERE c.group_id = 'b2c3d4e5-f6g7-...'

Expected: Each query returns only that group's data
```

---

## 📋 **Phase 5: Documentation Updates**

### **Step 5.1: Update Internal Documentation**

**Update these documents:**

#### **Document 1: AZURE_PORTAL_ONLY_GROUP_MANAGEMENT.md**
```markdown
Add prominent notice at top:

> ⚠️ **CURRENT CONFIGURATION: Assigned Groups Only (Option B)**
> 
> New groups must be explicitly assigned to the enterprise application
> before they will work. See Step 3 below for assignment procedure.
```

#### **Document 2: Create New Group Procedure**
```markdown
# How to Add New Group to Content Processor

## Prerequisites
- Groups Administrator role
- Application Administrator role

## Steps

### 1. Create Security Group (Groups Administrator)
1. Azure Portal → Azure AD → Groups → New group
2. Group type: Security
3. Group name: [Team Name]
4. Add members

### 2. Assign Group to Application (Application Administrator)
⚠️ **REQUIRED STEP** - Group will not work without this!

1. Azure Portal → Enterprise Applications
2. Search: "content-processor"
3. Users and groups → Add user/group
4. Select: The new group
5. Assign

### 3. Verify (Any User)
1. User from new group logs in
2. Logs out and logs back in (refresh token)
3. Should see new group in dropdown
4. Can upload files to new group

## Troubleshooting
- Group not visible? → Check assignment in Step 2
- Still not visible? → User needs to log out/in
```

---

### **Step 5.2: Update User Documentation**

**Create user-facing guide:**

```markdown
# Content Processor Group Access - User Guide

## How Group Access Works

Your access to the Content Processor is based on your Azure AD group membership.

### Which Groups Can I See?

You can only see and access groups that:
1. You are a member of in Azure AD
2. Have been approved for use with Content Processor

### How to Request Access to New Group

If you need access to a group that isn't visible:
1. Contact your Groups Administrator
2. Request to be added to the desired group
3. If the group is new to the app, IT must approve it first
4. After approval, log out and log back in

### Troubleshooting

**Problem:** I don't see my group in the dropdown
**Solution:** 
- Verify you're a member of the group (check with Groups Administrator)
- Try logging out and logging back in
- Contact IT if still not visible

**Problem:** I get "Access Denied" error
**Solution:**
- You may not have permission for that group
- Contact your manager to request group access
```

---

### **Step 5.3: Update Runbooks**

**Create operational runbook:**

```markdown
# Runbook: Add New Group to Content Processor

## Frequency
As needed (when new teams/departments need access)

## Roles Required
- Groups Administrator (or Group Owner)
- Application Administrator

## Estimated Time
10 minutes

## Steps

### 1. Create Group (Groups Administrator)
- Azure Portal → Azure AD → Groups → New group
- Type: Security
- Name: [Descriptive name]
- Add initial members

### 2. Assign to Enterprise Application (Application Administrator)
- Azure Portal → Enterprise Applications → "content-processor-api"
- Users and groups → Add user/group
- Select the new group → Assign

### 3. Test
- Have test user from group log in
- Verify group appears in dropdown
- Verify can upload/download files

### 4. Notify
- Inform team members they can now access the app
- Provide link to user documentation

## Verification
- Group appears in Enterprise Application assignments
- Users can see group in application dropdown
- Files upload to correct container: pro-input-files-group-[id]

## Rollback
To remove group access:
- Enterprise Applications → Users and groups
- Select group → Remove
- Users will lose access on next login
```

---

## 🔄 **Rollback Plan**

### **If Issues Occur, Rollback is Simple:**

#### **Immediate Rollback (5 minutes)**

```bash
1. Azure Portal → App Registrations → [Your API App]
2. Token configuration → Edit "groups" claim
3. Change from: "Groups assigned to the application"
   Back to: "Security groups"
4. Save
5. Users log out and log back in
6. All groups work again

Result: Back to Option A (all groups accessible)
```

#### **When to Rollback:**

```bash
Trigger rollback if:
- ❌ Multiple users report access issues
- ❌ Critical groups were not assigned
- ❌ Business operations impacted
- ❌ More than 10% of users affected

Do NOT rollback if:
- ✅ Only a few users affected (assign their groups instead)
- ✅ Issue is with non-critical test group
- ✅ Can be fixed by group assignment
```

#### **Post-Rollback Actions:**

```bash
1. Document what went wrong
2. Identify missed group assignments
3. Schedule new migration attempt
4. Assign ALL groups before retry
5. Test more thoroughly
```

---

## 📊 **Success Criteria**

### **Migration is successful when:**

- ✅ All assigned groups work correctly
- ✅ Users can log in and see their groups
- ✅ File upload/download works for all groups
- ✅ No 403 errors in application logs
- ✅ Non-assigned groups do NOT appear (if any)
- ✅ No user complaints after 24 hours
- ✅ Blob containers created correctly per group
- ✅ Cosmos DB filtering works correctly
- ✅ Documentation updated
- ✅ Support team trained

---

## 📝 **Post-Migration Checklist**

### **Day 1 (Migration Day):**
- [ ] Configuration changed successfully
- [ ] All test users verified working
- [ ] No critical errors in logs
- [ ] Support team on standby
- [ ] Documentation updated

### **Day 2-7 (Monitoring Period):**
- [ ] Monitor logs daily for access errors
- [ ] Respond to user reports within 1 hour
- [ ] Track any missed group assignments
- [ ] Document any issues encountered
- [ ] Adjust process documentation based on learnings

### **Week 2 (Stabilization):**
- [ ] All issues resolved
- [ ] User complaints < 1%
- [ ] Process documented and published
- [ ] Training materials updated
- [ ] Declare migration complete

---

## 🎓 **Training Materials**

### **For Groups Administrators:**

```markdown
# Training: Managing Groups After Migration

## What Changed?
Before: Groups automatically worked in Content Processor
After: Groups must be explicitly assigned by Application Administrator

## Your New Workflow:
1. Create security group (same as before)
2. Add users (same as before)  
3. **NEW**: Request Application Administrator to assign group to app
4. Verify group works (test with user)

## When to Contact Application Administrator:
- Creating new group for Content Processor
- Existing group not working
- Need to revoke group access
```

### **For Application Administrators:**

```markdown
# Training: Assigning Groups to Content Processor

## New Responsibility:
You must assign new groups to the enterprise application

## Frequency:
As needed (when Groups Administrator creates new groups)

## Process:
1. Receive request from Groups Administrator
2. Verify group exists and has members
3. Assign to enterprise application (5 minutes)
4. Test with user from that group
5. Confirm to Groups Administrator

## SLA:
- Standard requests: Within 1 business day
- Urgent requests: Within 4 hours
```

---

## 📞 **Support Plan**

### **Day 1 Support (Migration Day):**

```bash
Support Team Availability:
- Application Administrator: On call 8am-6pm
- Groups Administrator: On call 8am-6pm
- Technical Lead: On call 8am-6pm

Escalation Path:
1. User reports issue → Help desk
2. Help desk cannot resolve → Groups Administrator
3. Groups Admin cannot resolve → Application Administrator
4. App Admin cannot resolve → Technical Lead
5. Technical Lead decision: Fix or Rollback
```

### **Common Support Scenarios:**

```bash
Scenario 1: User can't see their group
Resolution:
1. Verify user is member of group (Azure AD)
2. Verify group is assigned to app (Enterprise Applications)
3. If yes to both → User needs to log out/in
4. If no to #2 → Assign group to app

Scenario 2: User gets 403 error
Resolution:
1. Check application logs for specific error
2. Verify group_id in error message
3. Verify group assignment
4. Verify user group membership

Scenario 3: Group assignment not working
Resolution:
1. Check Enterprise Applications → Users and groups
2. Verify group appears in list
3. Verify assignment date is recent
4. Try removing and re-adding assignment
5. Check token at jwt.ms (groups claim)
```

---

## 📈 **Metrics to Track**

### **Before Migration:**
```bash
- Total number of groups: [X]
- Total number of users: [Y]
- Average groups per user: [Z]
- Support tickets (baseline): [N per week]
```

### **During Migration:**
```bash
- Groups assigned: [X / Total]
- Test results: [Passed / Total]
- Errors encountered: [Count]
- Rollback performed: [Yes/No]
```

### **After Migration:**
```bash
- Successfully migrated groups: [X / Total]
- User satisfaction: [Survey results]
- Support tickets: [N per week] (compare to baseline)
- Time to assign new group: [Average minutes]
```

---

## ✅ **Migration Complete!**

### **Congratulations! You've successfully migrated to assigned groups only.**

**Benefits achieved:**
- 🔒 Enhanced security with explicit group approval
- 📋 Better compliance and audit trail
- 🎯 Controlled access to application
- 📊 Clear record of which groups have access

**Remember:**
- ✅ No code changes were required
- ✅ Application continues to work exactly the same
- ✅ Only token configuration changed
- ✅ New groups now require explicit assignment

**Next steps:**
- Monitor for 2 weeks
- Gather user feedback
- Adjust documentation as needed
- Train new administrators on process
- Schedule periodic access reviews

---

## 📚 **Related Documentation**

| Document | Purpose |
|----------|---------|
| `GROUP_REGISTRATION_DECISION_TREE.md` | Understand Option A vs Option B |
| `AZURE_PORTAL_ONLY_GROUP_MANAGEMENT.md` | Complete group management guide |
| `AZURE_AD_ROLES_QUICK_REFERENCE.md` | Required roles and permissions |
| `DEPLOYMENT_GROUP_ISOLATION_FAQ.md` | Architecture and deployment info |

---

**Document Version:** 1.0  
**Last Updated:** October 20, 2025  
**Next Review:** After first migration execution
