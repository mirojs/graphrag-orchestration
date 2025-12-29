# Grant Managed Identity Graph API Permissions

## 🎯 What We Need

Your Container App's **Managed Identity** needs **Group.Read.All** permission to call Microsoft Graph API and resolve group names.

**Container App:** `ca-cps-xh5lwkfq3vfm-api`  
**Managed Identity Principal ID:** `6178b5f1-25e8-4dfc-80f3-d894f9970071`

---

## ✅ Method 1: Grant Permission via Azure Portal (Recommended for New Deployments)

### Step-by-Step Guide

1. **Navigate to Azure Portal** → [https://portal.azure.com](https://portal.azure.com)

2. **Go to Microsoft Entra ID** (formerly Azure Active Directory)
   - Search for "Microsoft Entra ID" in the top search bar
   - Click on **Microsoft Entra ID**

3. **Open Enterprise Applications**
   - In the left menu, click **Enterprise applications**
   - In the search box, enter your managed identity principal ID: `6178b5f1-25e8-4dfc-80f3-d894f9970071`
   - Or search by name: `ca-cps-xh5lwkfq3vfm-api`
   - Click on the managed identity when it appears

4. **Navigate to Permissions**
   - In the left menu, click **Permissions**
   - Click **+ Add permission**

5. **Select Microsoft Graph**
   - Click **Microsoft Graph**
   - Click **Application permissions** (NOT Delegated permissions)

6. **Add Group.Read.All Permission**
   - In the search box, type `Group.Read`
   - Expand the **Group** section
   - Check the box for **Group.Read.All**
   - Click **Add permissions** at the bottom

7. **Grant Admin Consent** ⚠️ **CRITICAL STEP**
   - Back on the Permissions page, you'll see the new permission listed
   - Click **Grant admin consent for [Your Organization]**
   - Click **Yes** to confirm
   - Wait for the status to show a green checkmark ✅

8. **Verify Permission**
   - Refresh the page
   - You should see **Group.Read.All** with status **Granted for [Your Organization]**

### 📸 Visual Guide

```
Azure Portal
  └─ Microsoft Entra ID
      └─ Enterprise applications
          └─ Search: "ca-cps-xh5lwkfq3vfm-api"
              └─ Permissions
                  └─ Add permission
                      └─ Microsoft Graph
                          └─ Application permissions
                              └─ Group.Read.All ✓
                                  └─ Grant admin consent ✓
```

---

## ✅ Method 2: Grant Permission via Azure CLI (Scripting/Automation)

Run these commands to grant the Managed Identity permission to read groups:

```bash
# 1. Get the Microsoft Graph Service Principal ID
GRAPH_SP_ID=$(az ad sp list --filter "appId eq '00000003-0000-0000-c000-000000000000'" --query "[0].id" -o tsv)

echo "Microsoft Graph Service Principal ID: $GRAPH_SP_ID"

# 2. Get your Container App's Managed Identity Principal ID
API_PRINCIPAL_ID="6178b5f1-25e8-4dfc-80f3-d894f9970071"

echo "API Managed Identity Principal ID: $API_PRINCIPAL_ID"

# 3. Grant Group.Read.All permission (App Role Assignment)
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$API_PRINCIPAL_ID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{
    \"principalId\": \"$API_PRINCIPAL_ID\",
    \"resourceId\": \"$GRAPH_SP_ID\",
    \"appRoleId\": \"5b567255-7703-4780-807c-7be8301ae99b\"
  }"
```

**Permission ID Reference:**
- `5b567255-7703-4780-807c-7be8301ae99b` = **Group.Read.All** (Application)

---

## 🔑 Common Microsoft Graph Permission IDs

For future reference, here are common Graph API permission IDs you might need:

| Permission | Type | App Role ID | Description |
|------------|------|-------------|-------------|
| **Group.Read.All** | Application | `5b567255-7703-4780-807c-7be8301ae99b` | Read all groups |
| **User.Read.All** | Application | `df021288-bdef-4463-88db-98f22de89214` | Read all users |
| **Directory.Read.All** | Application | `7ab1d382-f21e-4acd-a863-ba3e13f7da61` | Read directory data |
| **Files.Read.All** | Application | `01d4889c-1287-42c6-ac1f-5d1e02578ef6` | Read all files |
| **Mail.Read** | Application | `810c84a8-4a9e-49e6-bf7d-12d183f40d01` | Read mail in all mailboxes |

💡 **Tip:** To find other permission IDs, use this Azure CLI command:
```bash
az ad sp show --id 00000003-0000-0000-c000-000000000000 \
  --query "appRoles[?value=='Permission.Name.Here'].id" -o tsv
```

---

## 🔍 Verify Permission Granted

```bash
# Check assigned permissions
az rest --method GET \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/6178b5f1-25e8-4dfc-80f3-d894f9970071/appRoleAssignments" \
  --query "value[?resourceId=='$GRAPH_SP_ID'].appRoleId" -o table
```

**Expected Output:** Should include `5b567255-7703-4780-807c-7be8301ae99b`

---

## 🚀 After Granting Permission

Once the permission is granted:

1. **No code changes needed** - Managed Identity is already configured
2. **No secrets needed** - Azure handles authentication automatically
3. **Deploy the updated code:**
   ```bash
   cd ./code/content-processing-solution-accelerator/infra/scripts
   ./docker-build.sh
   ```

4. **Test the endpoint:**
   ```bash
   curl -X POST https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/api/groups/resolve-names \
     -H "Content-Type: application/json" \
     -d '["7e9e0c33-a31e-4b56-8ebf-0fff973f328f"]'
   ```

   **Expected Response:**
   ```json
   {
     "7e9e0c33-a31e-4b56-8ebf-0fff973f328f": "Hulkdesign-AI-access"
   }
   ```

---

## 📊 Architecture (Simplified - Managed Identity Only)

```
Container App (ca-cps-xh5lwkfq3vfm-api)
    ↓
  System-Assigned Managed Identity
  (Principal ID: 6178b5f1-25e8-4dfc-80f3-d894f9970071)
    ↓
  DefaultAzureCredential() ← No secrets!
    ↓
  Acquires token from Azure AD automatically
    ↓
  Calls Microsoft Graph API
  GET /v1.0/groups/{id}
    ↓
  Returns group displayName
```

**No secrets, no environment variables, just works!** ✨

---

## ✅ Benefits of This Approach

| Benefit | Description |
|---------|-------------|
| **No Secrets** | Zero credentials to manage or rotate |
| **Auto-Managed** | Azure handles identity lifecycle |
| **More Secure** | Credentials never leave Azure platform |
| **Simpler Code** | Only ~10 lines instead of 40+ |
| **Zero Config** | No environment variables needed |
| **Compliance** | No secrets in logs or config files |

---

## 🔧 Troubleshooting

### Error: "Failed to acquire token via managed identity"

**Possible Causes:**
1. Managed Identity not enabled (but yours is!)
2. Permission not granted yet (run the az rest command above)
3. Container not running in Azure (local won't work)

**Check Container App has Managed Identity:**
```bash
az containerapp show \
  --name ca-cps-xh5lwkfq3vfm-api \
  --resource-group rg-contentaccelerator \
  --query "identity"
```

**Expected:** Should show `"type": "SystemAssigned"` with principalId

---

## 📝 Summary

**What changed:**
- ✅ Removed client credentials code (simpler)
- ✅ Only using Managed Identity (more secure)
- ✅ No environment variables needed (zero config)

**What you need to do:**
1. Grant Managed Identity permission (run az rest command above)
2. Deploy updated code (`./docker-build.sh`)
3. Test and enjoy! 🎉

---

**Status:** Code simplified to use only Managed Identity  
**Next Step:** Grant permission then deploy
