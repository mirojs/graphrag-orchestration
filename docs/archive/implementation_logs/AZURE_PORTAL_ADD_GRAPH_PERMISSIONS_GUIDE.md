# 🔐 Adding Microsoft Graph API Permissions - Azure Portal Guide

## 📋 Overview

This guide shows you how to **manually add Microsoft Graph API permissions** through the Azure Portal to enable your application to read group information.

**What You're Adding:**
- **Permission:** `Group.Read.All`
- **Type:** Application Permission
- **Purpose:** Allows your app to read group names and memberships

**Time Required:** 5-10 minutes per app

---

## 🎯 Prerequisites

Before starting, ensure you have:
- [ ] Azure Portal access (https://portal.azure.com)
- [ ] Permissions to modify app registrations
- [ ] Admin rights to grant consent (or access to an admin)

---

## 📖 Step-by-Step Instructions

### **Part 1: Add Permission to API App**

#### **Step 1: Navigate to App Registrations**

1. Open **Azure Portal** (https://portal.azure.com)
2. In the search bar at the top, type: `App registrations`
3. Click on **App registrations** from the results

![Navigation: Search for App registrations in top search bar]

---

#### **Step 2: Select Your API App**

1. In the **App registrations** page, you'll see a list of all your apps
2. Find and click on your **API app**: `ca-cps-xh5lwkfq3vfm-api`
   - Or search for it using the search box at the top of the list
   - You can identify it by the **Application (client) ID**: `9f9b5bce-42a9-4eb0-b1dd-c7e5d454a2f5`

![App Registrations List showing ca-cps-xh5lwkfq3vfm-api]

---

#### **Step 3: Open API Permissions**

1. In the left sidebar, click on **API permissions**
2. You'll see the current permissions for your app
3. Existing permissions should include:
   - Microsoft Graph → User.Read (Delegated)

![Left sidebar showing API permissions option]

---

#### **Step 4: Add a Permission**

1. Click the **"+ Add a permission"** button at the top
2. A panel will slide out from the right side: **"Request API permissions"**

![Add a permission button at top of API permissions page]

---

#### **Step 5: Select Microsoft Graph**

1. In the **"Request API permissions"** panel, you'll see two sections:
   - **Microsoft APIs** (commonly used)
   - **APIs my organization uses**
2. Under **Microsoft APIs**, click on **Microsoft Graph**
   - This is usually the first option in the list

![Request API permissions panel showing Microsoft Graph option]

---

#### **Step 6: Choose Application Permissions**

1. You'll see two tabs:
   - **Delegated permissions** (user context)
   - **Application permissions** (app context)
2. Click on **Application permissions** tab
   - This allows your app to work without a signed-in user

![Two tabs showing Delegated permissions and Application permissions]

**Important:** Choose **Application permissions**, not Delegated permissions!

---

#### **Step 7: Search for Group Permissions**

1. In the search box, type: `Group`
2. The list will filter to show only group-related permissions
3. Expand the **Group** section if it's collapsed
4. You'll see several options:
   - Group.Create
   - Group.Read.All
   - Group.ReadWrite.All
   - etc.

![Search box with "Group" entered, showing filtered results]

---

#### **Step 8: Select Group.Read.All**

1. Find **Group.Read.All** in the list
2. Check the checkbox next to it
   - Description: "Read all groups"
   - Type: Application
3. Review the permission description to confirm it's correct

![Group.Read.All checkbox selected with description visible]

**Alternative:** You can also use **Directory.Read.All** (gives broader read access to directory)

---

#### **Step 9: Add the Permission**

1. Scroll to the bottom of the panel
2. Click the **"Add permissions"** button
3. The panel will close
4. You'll return to the **API permissions** page

![Add permissions button at bottom of panel]

---

#### **Step 10: Verify Permission Added**

1. Back on the **API permissions** page, you should now see:
   - Microsoft Graph → User.Read (Delegated)
   - Microsoft Graph → Group.Read.All (Application) ✅ **NEW!**

2. You'll notice the status shows:
   - **Status:** "Not granted for [your tenant]" (yellow warning icon)
   - This is expected - we need to grant admin consent next

![API permissions list showing new Group.Read.All permission with "Not granted" status]

---

#### **Step 11: Grant Admin Consent** (CRITICAL!)

1. At the top of the **API permissions** page, locate the button:
   - **"Grant admin consent for [your tenant name]"**
   - Example: "Grant admin consent for Default Directory"

2. Click the button
3. A confirmation dialog will appear:
   - **"Grant admin consent confirmation"**
   - Message: "The requested permissions will be granted..."
4. Click **"Yes"** to confirm

![Grant admin consent button highlighted]

**Important:** This step requires admin privileges. If you don't see this button or get an error, ask your Azure AD admin to complete this step.

---

#### **Step 12: Verify Admin Consent Granted**

1. After granting consent, the page will refresh
2. Check the **Status** column for Group.Read.All:
   - Should now show: **"Granted for [your tenant]"** with a green checkmark ✅
3. The permission is now active and ready to use!

![API permissions showing Group.Read.All with green checkmark and "Granted" status]

---

### **Part 2: Add Permission to Web App**

Repeat the exact same steps for your **Web app**:

#### **Quick Steps:**

1. Navigate to **App registrations**
2. Select: `ca-cps-xh5lwkfq3vfm-web` (Client ID: `546fae19-24fb-4ff8-9e7c-b5ff64e17987`)
3. Click **API permissions** in left sidebar
4. Click **"+ Add a permission"**
5. Select **Microsoft Graph**
6. Select **Application permissions** tab
7. Search for `Group`
8. Check **Group.Read.All**
9. Click **"Add permissions"**
10. Click **"Grant admin consent for [tenant]"**
11. Confirm by clicking **"Yes"**
12. Verify green checkmark appears ✅

---

## ✅ Verification Checklist

After completing both apps, verify:

### **API App (`ca-cps-xh5lwkfq3vfm-api`):**
- [ ] API permissions page shows:
  - Microsoft Graph → User.Read (Delegated) - Status: Granted ✅
  - Microsoft Graph → Group.Read.All (Application) - Status: Granted ✅
- [ ] Green checkmark visible for Group.Read.All
- [ ] Status shows "Granted for [your tenant]"

### **Web App (`ca-cps-xh5lwkfq3vfm-web`):**
- [ ] API permissions page shows:
  - Microsoft Graph → User.Read (Delegated) - Status: Granted ✅
  - Microsoft Graph → Group.Read.All (Application) - Status: Granted ✅
- [ ] Green checkmark visible for Group.Read.All
- [ ] Status shows "Granted for [your tenant]"

---

## 🔍 Troubleshooting

### **Issue: "Grant admin consent" button is grayed out**

**Cause:** You don't have admin privileges

**Solution:**
1. Ask your Azure AD administrator to grant consent
2. Or request "Application Administrator" or "Cloud Application Administrator" role
3. Alternative: Use Azure CLI (if you have CLI admin access):
   ```bash
   az ad app permission admin-consent --id <CLIENT_ID>
   ```

---

### **Issue: "Insufficient privileges to complete the operation"**

**Cause:** Missing required Azure AD role

**Required Roles (any one of):**
- Global Administrator
- Privileged Role Administrator
- Application Administrator
- Cloud Application Administrator

**Solution:**
1. Contact your Azure AD admin
2. Request one of the above roles
3. Or ask admin to grant consent for you

---

### **Issue: Permission shows "Not granted" after clicking grant consent**

**Cause:** Browser cache or delayed propagation

**Solution:**
1. Wait 2-3 minutes and refresh the page
2. Clear browser cache and reload
3. Try in a different browser or incognito mode
4. Check Azure AD audit logs for consent events

---

### **Issue: Can't find Group.Read.All in the list**

**Cause:** Searching in wrong permission type

**Solution:**
1. Make sure you're in **Application permissions** tab (not Delegated)
2. Clear the search box and search again
3. Type exactly: `Group.Read.All`
4. Alternative: Use `Directory.Read.All` (gives broader access)

---

## 📊 What These Permissions Enable

### **Group.Read.All Permission:**

**Allows your application to:**
- ✅ Read all groups in the tenant
- ✅ Read group properties (name, description, etc.)
- ✅ Read group memberships
- ✅ Resolve group Object IDs to friendly names

**Does NOT allow:**
- ❌ Create or modify groups
- ❌ Add/remove members
- ❌ Delete groups
- ❌ Change group ownership

### **In Your Application:**

**Backend (API):**
```python
# Can now call Microsoft Graph API
from azure.identity import ManagedIdentityCredential
from msgraph.core import GraphClient

credential = ManagedIdentityCredential()
client = GraphClient(credential=credential)

# Get group details
group = client.get(f"/groups/{group_id}")
print(group["displayName"])  # "Hulkdesign-AI-access"
```

**Frontend (Web):**
```typescript
// Can resolve group IDs to names
const groupName = await resolveGroupName(groupId);
// Shows: "Hulkdesign-AI-access" instead of "7e9e0c33-a31e-4b56-8ebf-0fff973f328f"
```

---

## 🎯 Alternative: Directory.Read.All

If you need broader read access to Azure AD:

### **Instead of Group.Read.All, use Directory.Read.All:**

**Advantages:**
- Reads all directory data (users, groups, apps, etc.)
- Single permission covers multiple needs
- Useful if you need user info later

**Disadvantages:**
- More powerful (may raise security concerns)
- Requires more justification for approval

**To use Directory.Read.All:**
- Follow same steps as above
- In Step 7, search for: `Directory`
- Select: `Directory.Read.All`
- Continue with Steps 8-12

---

## 📚 Related Documentation

### **Microsoft Official Docs:**
- [Microsoft Graph permissions reference](https://docs.microsoft.com/en-us/graph/permissions-reference)
- [Group.Read.All permission details](https://docs.microsoft.com/en-us/graph/permissions-reference#groupreadall)
- [App-only access (Application permissions)](https://docs.microsoft.com/en-us/graph/auth-v2-service)

### **Your Project Docs:**
- `AZURE_AD_CONFIGURATION_COMPLETE.md` - Full configuration summary
- `PRE_DEPLOYMENT_GROUP_ISOLATION_VALIDATION.md` - Testing guide
- `AZURE_PORTAL_ONLY_GROUP_MANAGEMENT.md` - Group management procedures

---

## ✅ Success Indicators

**You've successfully completed this when:**

1. ✅ Both apps (API + Web) show Group.Read.All permission
2. ✅ Admin consent granted (green checkmark)
3. ✅ Status shows "Granted for [your tenant]"
4. ✅ No yellow warning icons
5. ✅ Can call Microsoft Graph API to read groups (test in code)

---

## 🧪 Testing the Permission

After adding the permission, test it works:

### **Test 1: Using Azure CLI**
```bash
# Get access token for Microsoft Graph
TOKEN=$(az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv)

# Test reading a group
curl -H "Authorization: Bearer $TOKEN" \
  https://graph.microsoft.com/v1.0/groups/7e9e0c33-a31e-4b56-8ebf-0fff973f328f

# Expected: JSON response with group details
```

### **Test 2: In Your Application**
```python
# Backend test
from azure.identity import DefaultAzureCredential
from msgraph.core import GraphClient

credential = DefaultAzureCredential()
client = GraphClient(credential=credential)

# Try to read a group
group_id = "7e9e0c33-a31e-4b56-8ebf-0fff973f328f"
response = client.get(f"/groups/{group_id}")

if response.status_code == 200:
    print("✅ Permission working!")
    print(f"Group name: {response.json()['displayName']}")
else:
    print(f"❌ Error: {response.status_code}")
```

### **Expected Results:**
- ✅ API call succeeds (200 OK)
- ✅ Returns group details with displayName
- ✅ No "Insufficient privileges" errors

---

## 🔐 Security Best Practices

### **1. Principle of Least Privilege**
- Use Group.Read.All (not ReadWrite) if you only need to read
- Don't request broader permissions than needed
- Document why each permission is required

### **2. Regular Audits**
- Review permissions quarterly
- Remove unused permissions
- Check Azure AD audit logs for API calls

### **3. Monitor Usage**
- Set up alerts for permission changes
- Track API calls to Microsoft Graph
- Review consent events in audit logs

---

## 🎉 Completion

**Congratulations!** You've successfully added Microsoft Graph API permissions to your applications.

**Your apps can now:**
- ✅ Read security groups from Azure AD
- ✅ Resolve group Object IDs to friendly names
- ✅ Display user-friendly group names in the UI
- ✅ Support group-based data isolation

**Next Steps:**
1. Test the permissions work (see Testing section above)
2. Update your application code to use Graph API
3. Deploy group isolation features
4. Test with real users

---

**Last Updated:** 2025-10-20  
**App Registrations:**
- API: `ca-cps-xh5lwkfq3vfm-api` (9f9b5bce-42a9-4eb0-b1dd-c7e5d454a2f5)
- Web: `ca-cps-xh5lwkfq3vfm-web` (546fae19-24fb-4ff8-9e7c-b5ff64e17987)

**Status:** ✅ **Permissions Configured and Granted**
