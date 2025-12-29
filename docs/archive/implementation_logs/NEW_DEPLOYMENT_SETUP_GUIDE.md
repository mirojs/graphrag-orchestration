# New Deployment Setup Guide

## 🎯 Overview

This guide walks through the complete setup process for deploying the Content Processing Solution Accelerator to a **new Azure environment**. Follow these steps in order.

---

## 📋 Prerequisites

- Azure subscription with appropriate permissions
- Azure CLI installed and logged in (`az login`)
- Docker installed locally (for docker-build.sh)
- Owner or Contributor role on the Azure subscription
- Global Administrator or Privileged Role Administrator role in Microsoft Entra ID (for granting Graph API permissions)

---

## 🚀 Step-by-Step Deployment

### Phase 1: Initial Infrastructure Deployment

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd content-processing-solution-accelerator
   ```

2. **Navigate to infrastructure scripts**
   ```bash
   cd infra/scripts
   ```

3. **Run initial deployment**
   ```bash
   ./docker-build.sh
   ```
   
   This will:
   - Create Azure resources (Container Apps, Storage, etc.)
   - Build and push Docker images
   - Deploy the application

4. **Note the Container App names** (output from deployment)
   - Backend API: `ca-cps-xxxxxxxxxx-api`
   - Frontend Web: `ca-cps-xxxxxxxxxx-web`

---

### Phase 2: Enable Managed Identity

The managed identity should be automatically enabled during deployment, but verify:

```bash
# Replace with your actual resource group and container app name
az containerapp show \
  --name ca-cps-xxxxxxxxxx-api \
  --resource-group rg-contentaccelerator \
  --query "identity" -o json
```

**Expected output:**
```json
{
  "type": "SystemAssigned",
  "principalId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

**Save the `principalId`** - you'll need it in the next step!

If managed identity is NOT enabled, enable it:
```bash
az containerapp identity assign \
  --name ca-cps-xxxxxxxxxx-api \
  --resource-group rg-contentaccelerator \
  --system-assigned
```

---

### Phase 3: Grant Microsoft Graph API Permissions

The backend API needs permission to read Azure AD groups to resolve group names.

#### Option A: Azure Portal (Recommended - Easier for first-time setup)

1. **Go to Azure Portal** → [portal.azure.com](https://portal.azure.com)

2. **Navigate to Microsoft Entra ID**
   - Search "Microsoft Entra ID" in the top search bar
   - Click **Microsoft Entra ID**

3. **Find your Container App's Managed Identity**
   - Click **Enterprise applications** in the left menu
   - Change the **Application type** filter to **Managed Identities**
   - Search for: `ca-cps-xxxxxxxxxx-api` (your backend container app name)
   - Click on it when it appears

4. **Add Microsoft Graph Permissions**
   - Click **Permissions** in the left menu
   - Click **+ Add permission**
   - Click **Microsoft Graph**
   - Click **Application permissions** (NOT Delegated!)
   - Search for and expand **Group**
   - Check ✅ **Group.Read.All**
   - Click **Add permissions**

5. **Grant Admin Consent** ⚠️ **CRITICAL**
   - Click **Grant admin consent for [Your Organization]**
   - Click **Yes** to confirm
   - Verify the status shows a green checkmark ✅

6. **Verify**
   - The permission should show as "Granted for [Your Organization]"
   - Status should be green ✅

#### Option B: Azure CLI (Recommended - For automation/scripting)

```bash
# 1. Get the Microsoft Graph Service Principal ID
GRAPH_SP_ID=$(az ad sp list --filter "appId eq '00000003-0000-0000-c000-000000000000'" --query "[0].id" -o tsv)

# 2. Set your Container App's Managed Identity Principal ID (from Phase 2)
API_PRINCIPAL_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # Replace with your principalId

# 3. Grant Group.Read.All permission
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$API_PRINCIPAL_ID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{
    \"principalId\": \"$API_PRINCIPAL_ID\",
    \"resourceId\": \"$GRAPH_SP_ID\",
    \"appRoleId\": \"5b567255-7703-4780-807c-7be8301ae99b\"
  }"

# 4. Verify the permission was granted
az rest --method GET \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$API_PRINCIPAL_ID/appRoleAssignments" \
  --query "value[].{Permission:appRoleId, Resource:resourceDisplayName}" -o table
```

**Expected output:**
```
Permission                              Resource
5b567255-7703-4780-807c-7be8301ae99b   Microsoft Graph
```

---

### Phase 4: Configure Environment Variables (If Needed)

Most configuration is automatic, but you may need to set:

1. **Storage Connection String** (usually auto-configured)
2. **Document Intelligence Endpoint** (for AI extraction)
3. **Any custom configuration**

Check your Container App's environment variables:
```bash
az containerapp show \
  --name ca-cps-xxxxxxxxxx-api \
  --resource-group rg-contentaccelerator \
  --query "properties.template.containers[0].env" -o table
```

---

### Phase 5: Test the Deployment

#### Test Backend API

```bash
# Get your backend URL
BACKEND_URL=$(az containerapp show \
  --name ca-cps-xxxxxxxxxx-api \
  --resource-group rg-contentaccelerator \
  --query "properties.configuration.ingress.fqdn" -o tsv)

# Test the groups endpoint (replace with an actual group ID from your Azure AD)
curl -X POST https://$BACKEND_URL/api/groups/resolve-names \
  -H "Content-Type: application/json" \
  -d '["xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"]'
```

**Expected Response:**
```json
{
  "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx": "Your Group Name"
}
```

#### Test Frontend Web App

```bash
# Get your frontend URL
FRONTEND_URL=$(az containerapp show \
  --name ca-cps-xxxxxxxxxx-web \
  --resource-group rg-contentaccelerator \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo "Frontend URL: https://$FRONTEND_URL"
```

Open the URL in your browser and:
1. Login with your Azure AD account
2. Navigate to the group selector
3. Verify you see **group names** (not GUIDs) in the dropdown

---

## 🔧 Troubleshooting Common Issues

### Issue: Groups showing as GUIDs instead of names

**Cause:** Graph API permission not granted or admin consent not completed

**Fix:** 
- Repeat Phase 3 and ensure you clicked "Grant admin consent"
- Wait 5-10 minutes for permission propagation
- Restart the container app:
  ```bash
  az containerapp revision restart \
    --name ca-cps-xxxxxxxxxx-api \
    --resource-group rg-contentaccelerator
  ```

### Issue: "Failed to acquire token via managed identity"

**Cause:** Managed Identity not enabled

**Fix:**
```bash
az containerapp identity assign \
  --name ca-cps-xxxxxxxxxx-api \
  --resource-group rg-contentaccelerator \
  --system-assigned
```

Then redeploy:
```bash
cd infra/scripts
./docker-build.sh
```

### Issue: 403 Forbidden when calling Graph API

**Cause:** Permission granted but admin consent missing

**Fix:** Go to Azure Portal → Microsoft Entra ID → Enterprise Applications → Your Managed Identity → Permissions → Click "Grant admin consent"

---

## 📊 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Azure Container Apps                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────┐         ┌─────────────────────┐    │
│  │   Frontend (Web)   │────────▶│   Backend (API)     │    │
│  │  React + Fluent UI │         │   FastAPI + Python  │    │
│  └────────────────────┘         └─────────────────────┘    │
│                                           │                  │
│                                           │ Uses             │
│                                           ▼                  │
│                              ┌─────────────────────────┐    │
│                              │   Managed Identity      │    │
│                              │  (No secrets!)          │    │
│                              └─────────────────────────┘    │
│                                           │                  │
└───────────────────────────────────────────┼──────────────────┘
                                            │
                                            │ Group.Read.All
                                            ▼
                              ┌─────────────────────────┐
                              │  Microsoft Graph API    │
                              │  /v1.0/groups/{id}      │
                              └─────────────────────────┘
```

---

## ✅ Required Permissions Summary

| Permission | Type | Purpose | Grant Via |
|------------|------|---------|-----------|
| **Group.Read.All** | Application | Resolve group IDs to names | Portal or CLI |

**App Role ID:** `5b567255-7703-4780-807c-7be8301ae99b`

---

## 🔑 Additional Permissions (For Future Features)

If you need to add more Graph API permissions later:

| Permission | App Role ID | Purpose |
|------------|-------------|---------|
| **User.Read.All** | `df021288-bdef-4463-88db-98f22de89214` | Read user profiles |
| **Directory.Read.All** | `7ab1d382-f21e-4acd-a863-ba3e13f7da61` | Read all directory data |
| **Files.Read.All** | `01d4889c-1287-42c6-ac1f-5d1e02578ef6` | Read SharePoint files |

**To find permission IDs:**
```bash
az ad sp show --id 00000003-0000-0000-c000-000000000000 \
  --query "appRoles[?value=='Group.Read.All']" -o json
```

---

## 📝 Deployment Checklist

- [ ] Phase 1: Run `./docker-build.sh` - Initial deployment
- [ ] Phase 2: Verify managed identity is enabled
- [ ] Phase 2: Save the `principalId` for next step
- [ ] Phase 3: Grant Graph API permissions (Portal or CLI)
- [ ] Phase 3: **Grant admin consent** (CRITICAL!)
- [ ] Phase 3: Verify permission shows as "Granted"
- [ ] Phase 4: Configure any custom environment variables
- [ ] Phase 5: Test backend API endpoint
- [ ] Phase 5: Test frontend web application
- [ ] Phase 5: Verify group names appear (not GUIDs)

---

## 🎉 Success Criteria

Your deployment is successful when:

1. ✅ Backend API responds to `/api/groups/resolve-names`
2. ✅ Response contains group **names**, not IDs
3. ✅ Frontend displays group names in dropdown
4. ✅ No errors in browser console
5. ✅ No authentication errors in backend logs

---

## 📞 Support

If you encounter issues:

1. Check the [Troubleshooting section](#troubleshooting-common-issues) above
2. Review container logs:
   ```bash
   az containerapp logs show \
     --name ca-cps-xxxxxxxxxx-api \
     --resource-group rg-contentaccelerator \
     --tail 50
   ```
3. Verify all permissions are granted with green checkmarks
4. Wait 5-10 minutes for Azure AD changes to propagate

---

**Last Updated:** 2025-01-20  
**Version:** 1.0 - Managed Identity with Graph API Permissions
