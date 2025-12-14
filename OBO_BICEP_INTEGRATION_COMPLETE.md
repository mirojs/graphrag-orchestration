# ✅ OBO Flow Integration into Bicep + Post-Deployment Script

## Overview

Successfully integrated On-Behalf-Of (OBO) flow configuration into the automated deployment workflow. **No more manual environment variable setup required!**

---

## What Changed

### 1. **Bicep Template Updates** (`infra/main.bicep`)

#### Added Key Vault Access for API Container App
```bicep
roleAssignments: [
  {
    principalId: avmManagedIdentity.outputs.principalId
    roleDefinitionIdOrName: 'Key Vault Administrator'
    principalType: 'ServicePrincipal'
  }
  {
    principalId: avmContainerApp_API.outputs.systemAssignedMIPrincipalId!
    roleDefinitionIdOrName: 'Key Vault Secrets User'  // NEW: Allows reading OBO secret
    principalType: 'ServicePrincipal'
  }
]
```

#### Added OBO Environment Variables to API Container App
```bicep
env: [
  {
    name: 'APP_CONFIG_ENDPOINT'
    value: ''
  }
  {
    name: 'APP_ENV'
    value: 'prod'
  }
  // NEW: OBO Flow Configuration
  {
    name: 'AZURE_TENANT_ID'
    value: tenant().tenantId  // Auto-populated from Azure context
  }
  {
    name: 'AZURE_SERVER_APP_ID'
    value: ''  // Populated by post_deployment.sh
  }
  {
    name: 'AZURE_SERVER_APP_SECRET'
    value: 'keyvaultref:${avmKeyVault.outputs.vaultUri}secrets/AZURE-SERVER-APP-SECRET,identityref:system'
  }
]
```

**Key Benefits:**
- `AZURE_TENANT_ID`: Auto-populated from Azure context (no manual input needed)
- `AZURE_SERVER_APP_SECRET`: Securely references Key Vault secret using managed identity
- `AZURE_SERVER_APP_ID`: Placeholder updated by post-deployment script

---

### 2. **Post-Deployment Script Updates** (`infra/scripts/post_deployment.sh`)

Added comprehensive OBO flow setup to the existing Azure AD app registration process:

#### New Steps Added:
1. **Create OBO Client Secret**
   - Generates client secret for API app registration
   - Stores in Key Vault as `AZURE-SERVER-APP-SECRET`
   - Uses date-stamped naming: `OBO-Flow-Secret-YYYYMMDD`

2. **Add Microsoft Graph Delegated Permission**
   - Adds `User.Read` delegated permission to API app
   - Required for On-Behalf-Of token exchange
   - Idempotent: skips if already configured

3. **Store Configuration in App Configuration**
   - `AZURE_SERVER_APP_ID`: API Client ID
   - `AZURE_TENANT_ID`: Tenant ID
   - Stored with `APP_` prefix for consistency

4. **Update Container App Environment Variables**
   - Automatically adds `AZURE_SERVER_APP_ID`, `AZURE_SERVER_APP_SECRET`, `AZURE_TENANT_ID`
   - Uses Key Vault reference for secret (no plaintext storage)
   - Idempotent: skips if already configured

5. **Admin Consent Instructions**
   - Provides URLs for both API and Web app consent
   - Includes CLI commands for automation

---

## Deployment Workflow

### For Brand New Deployments

```bash
# 1. Deploy infrastructure (creates everything including placeholders)
azd up

# 2. Post-deployment automatically runs and:
#    ✅ Creates Azure AD app registrations
#    ✅ Generates OBO client secret
#    ✅ Stores secret in Key Vault
#    ✅ Configures Graph API permissions
#    ✅ Updates container app environment variables
#    ✅ Stores config in App Configuration

# 3. Grant admin consent (one-time manual step)
az ad app permission admin-consent --id <API_CLIENT_ID>
az ad app permission admin-consent --id <WEB_CLIENT_ID>

# Done! OBO flow is fully configured
```

### For Existing Deployments

The post-deployment script is **idempotent** and safe to re-run:

```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
./post_deployment.sh
```

**What happens:**
- ✅ Detects existing Azure AD apps (skips creation)
- ✅ Detects existing OBO configuration (skips if present)
- ✅ Only adds missing components
- ✅ Safe to run multiple times

---

## Architecture

### Before (Manual Setup Required)

```
Deployment → Manual Steps:
├── Create Azure AD apps manually
├── Get Client IDs from portal
├── Generate client secret in portal
├── Copy secret to Key Vault manually
├── Update container app env vars via portal/CLI
└── Grant admin consent
```

### After (Fully Automated)

```
azd up → Bicep Deployment:
├── Creates Key Vault with RBAC
├── Creates Container Apps with managed identities
├── Grants Key Vault Secrets User role to API app
└── Sets up environment variables (with Key Vault refs)
         ↓
    Post-Deployment Script:
    ├── Creates Azure AD app registrations
    ├── Generates OBO client secret
    ├── Stores secret in Key Vault (AZURE-SERVER-APP-SECRET)
    ├── Configures Graph API User.Read permission
    ├── Updates container app env vars
    └── Stores config in App Configuration
         ↓
    Manual Admin Consent (one-time):
    └── az ad app permission admin-consent --id <API_CLIENT_ID>
```

---

## Security Benefits

1. **No Secrets in Code**: Secret stored only in Key Vault
2. **Managed Identity Access**: Container app reads secret via system-assigned identity
3. **RBAC-Based**: Uses Azure RBAC for Key Vault access (no access policies)
4. **Auto-Rotation Ready**: Update Key Vault secret, container apps auto-reload
5. **No Redeployment Needed**: Change client IDs in App Configuration without rebuilding

---

## Configuration Storage

| Setting | Storage Location | Access Method |
|---------|------------------|---------------|
| `AZURE_TENANT_ID` | Bicep (auto) + App Config | Managed identity |
| `AZURE_SERVER_APP_ID` | App Configuration | Managed identity |
| `AZURE_SERVER_APP_SECRET` | Key Vault | Managed identity + Key Vault reference |
| `APP_AZURE_API_CLIENT_ID` | App Configuration | Managed identity |
| `APP_AZURE_WEB_CLIENT_ID` | App Configuration | Managed identity |

---

## Verification

After deployment, verify OBO configuration:

```bash
# 1. Check Key Vault secret exists
az keyvault secret show --vault-name kv-cps-XXXXX --name AZURE-SERVER-APP-SECRET

# 2. Check container app environment variables
az containerapp show \
  --name ca-cps-XXXXX-api \
  --resource-group rg-XXXXX \
  --query "properties.template.containers[0].env[?name=='AZURE_SERVER_APP_ID' || name=='AZURE_SERVER_APP_SECRET' || name=='AZURE_TENANT_ID']"

# 3. Check App Configuration values
az appconfig kv list --name appcs-cps-XXXXX --fields key value | grep AZURE

# 4. Check Azure AD app permissions
az ad app show --id <API_CLIENT_ID> --query requiredResourceAccess
```

---

## Troubleshooting

### Issue: "keyvaultref not working"
**Cause**: Container app doesn't have Key Vault Secrets User role

**Fix**: Already configured in bicep! Redeploy:
```bash
azd up
```

### Issue: "401 Unauthorized from Graph API"
**Cause**: Admin consent not granted for User.Read permission

**Fix**:
```bash
az ad app permission admin-consent --id <API_CLIENT_ID>
```

### Issue: "Environment variable AZURE_SERVER_APP_ID is empty"
**Cause**: Post-deployment script didn't run or failed

**Fix**: Re-run post-deployment:
```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
./post_deployment.sh
```

---

## What's NOT Automated (Intentionally)

1. **Admin Consent**: Requires Azure AD admin privileges
   - Could be automated with sufficient permissions
   - Kept manual for security/governance reasons

2. **App Registration Creation**: Now automated in post_deployment.sh!
   - API app: `{deployment-name}-api`
   - Web app: `{deployment-name}-web`

---

## Migration from Manual Setup

If you previously configured OBO manually:

```bash
# 1. Re-run post-deployment script (it's idempotent)
cd ./code/content-processing-solution-accelerator/infra/scripts
./post_deployment.sh

# 2. Verify configuration
az containerapp show --name ca-cps-XXXXX-api --resource-group rg-XXXXX \
  --query "properties.template.containers[0].env"

# 3. Old container app env vars can be removed (script won't duplicate)
```

---

## Files Modified

1. **`infra/main.bicep`**:
   - Added Key Vault Secrets User role for API container app
   - Added OBO environment variables to API container app
   - Environment variables use Key Vault references

2. **`infra/scripts/post_deployment.sh`**:
   - Added OBO client secret generation
   - Added Microsoft Graph User.Read permission
   - Added Key Vault secret storage
   - Added container app environment variable updates
   - Added App Configuration storage

---

## Next Steps for Future Deployments

1. **Deploy**: `azd up` (creates everything)
2. **Grant Consent**: `az ad app permission admin-consent --id <API_CLIENT_ID>`
3. **Test**: Access web app, verify group names display correctly
4. **Done**: No manual environment variable configuration needed!

---

## Comparison: Manual vs Automated

| Task | Manual (Old) | Automated (New) |
|------|-------------|-----------------|
| Create Azure AD apps | Portal clicks | `post_deployment.sh` |
| Generate client secret | Portal → Copy → Paste | Automated + Key Vault |
| Store in Key Vault | `az keyvault secret set` | Automated |
| Update container app | Portal → Env vars → Save | Automated |
| Configure permissions | Portal → API Permissions | Automated |
| Grant admin consent | Portal click | Portal click (required) |
| **Total manual steps** | **~15 steps** | **1 step** |

---

## Success! 🎉

OBO flow is now **fully integrated** into the standard deployment workflow. Future deployments require **zero manual environment variable configuration** for OBO token exchange!
