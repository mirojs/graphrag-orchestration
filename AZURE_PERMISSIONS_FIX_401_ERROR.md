# Azure Permissions Fix - Start Analysis 401 Error

## Real Root Cause Discovered

**Error**: `PermissionDenied: The principal lacks the required data action Microsoft.CognitiveServices/accounts/analyzers/analyzers/write`

**Date**: October 21, 2025

## Problem

The "Start Analysis" button was failing with 401 errors, but the root cause was **NOT** the group_id issue we initially suspected. The actual problem was:

### API Container App Managed Identity Missing Permissions

The API container app's system-assigned managed identity (`72b0ab9a-8f52-4bd2-8ec1-1745804952b4`) had **NO permissions** to:
- Create/write analyzers in Azure AI Services (Content Understanding)
- This caused all analysis requests to fail with 401 PermissionDenied

### Error from Logs
```json
{
  "error": {
    "code": "PermissionDenied",
    "message": "The principal `72b0ab9a-8f52-4bd2-8ec1-1745804952b4` lacks the required data action `Microsoft.CognitiveServices/accounts/analyzers/analyzers/write` to perform `PUT /contentunderstanding/analyzers/{analyzerId}` operation."
  }
}
```

## Solution Applied

### 1. Granted Cognitive Services Contributor Role

**West US AI Services**:
```bash
az role assignment create \
  --assignee 72b0ab9a-8f52-4bd2-8ec1-1745804952b4 \
  --role "Cognitive Services Contributor" \
  --scope /subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/rg-knowledgegraph/providers/Microsoft.CognitiveServices/accounts/aicu-cps-gw6br2ms6mxy
```
✅ **Result**: Role assignment created successfully

**East US 2 AI Services** (backup/secondary):
```bash
az role assignment create \
  --assignee 72b0ab9a-8f52-4bd2-8ec1-1745804952b4 \
  --role "Cognitive Services Contributor" \
  --scope /subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/rg-knowledgegraph/providers/Microsoft.CognitiveServices/accounts/aisa-cps-gw6br2ms6mxy
```
✅ **Result**: Role assignment created successfully

### 2. Verified Existing Storage Permissions

The managed identity already had **Storage Blob Data Contributor** role on `stcpsgw6br2ms6mxy` (granted during initial deployment).

## What the Cognitive Services Contributor Role Grants

This role provides permissions for:
- ✅ Creating custom analyzers (`analyzers/write`)
- ✅ Reading analyzer definitions
- ✅ Updating analyzer configurations
- ✅ Deleting analyzers
- ✅ Invoking analysis operations
- ✅ Managing AI Services resources

## Current Role Assignments

**API Container App Managed Identity** (`72b0ab9a-8f52-4bd2-8ec1-1745804952b4`):

| Resource | Role | Purpose |
|----------|------|---------|
| aicu-cps-gw6br2ms6mxy (West US) | Cognitive Services Contributor | Create/manage analyzers and run analysis |
| aisa-cps-gw6br2ms6mxy (East US 2) | Cognitive Services Contributor | Backup AI Services access |
| stcpsgw6br2ms6mxy | Storage Blob Data Contributor | Read/write files in blob storage |

## Why This Wasn't Caught Earlier

1. **Initial deployment** may have used user credentials (your Azure account) which has Owner/Contributor role
2. **Managed identity** was created but permissions were not fully configured
3. **Different error message**: 401 can mean both authentication AND authorization failures
4. **Group_id theory was plausible**: Cross-group file access could also cause 401 errors

## Testing the Fix

The permission changes take effect **immediately** (no container restart needed). Test by:

1. **Refresh the web app** in your browser
2. **Select a group** from the dropdown
3. **Create or load a case**
4. **Click "Start Analysis"**
5. **Expected result**: Analysis should start successfully (no 401 error)

### If Still Failing

Wait 1-2 minutes for Azure role assignment propagation, then:
- Hard refresh the page (Ctrl+Shift+R)
- Check browser console for new error messages
- Check API container logs: `az containerapp logs show --name ca-cps-gw6br2ms6mxy-api --resource-group rg-knowledgegraph --tail 50`

## Relationship to Group_id Fix

**Both fixes are still valid**:

1. **This fix** (Cognitive Services permissions): Allows analyzer creation to succeed
2. **Group_id persistence fix**: Ensures analysis uses correct blob storage container

The group_id fix is still beneficial for:
- Cases created in Group A can be analyzed even when Group B is selected
- Proper audit trail of which group a case belongs to
- Future multi-tenancy improvements

## Deployment Checklist

- [x] Grant Cognitive Services Contributor to API managed identity (West US)
- [x] Grant Cognitive Services Contributor to API managed identity (East US 2)
- [x] Verify Storage Blob Data Contributor role exists
- [ ] Test Start Analysis in production
- [ ] Verify analyzer creation succeeds
- [ ] Check no more 401 PermissionDenied errors in logs

## Important Notes

### Why System-Assigned Identity?

The API container app uses **system-assigned managed identity** (not user-assigned) for:
- Automatic lifecycle management (created/deleted with container app)
- Simpler RBAC (one identity per container app)
- Better security isolation

### Principal ID Mapping

- **72b0ab9a-8f52-4bd2-8ec1-1745804952b4**: API container app system identity
- **943b1e4c-b0c8-400a-9198-4e306eeb625c**: Main container app system identity
- **f4fb93cc-e32d-4383-8630-6b12102c99d6**: Web container app system identity
- **9642f44b-00eb-4009-94b9-22960313ab75**: User-assigned identity for ACR pull (acr-reader-midcps-gw6br2ms6mxy)

## Verification Commands

```bash
# Check API container logs for successful analyzer creation
az containerapp logs show --name ca-cps-gw6br2ms6mxy-api --resource-group rg-knowledgegraph --tail 50

# Verify role assignments on AI Services account
az role assignment list \
  --scope /subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/rg-knowledgegraph/providers/Microsoft.CognitiveServices/accounts/aicu-cps-gw6br2ms6mxy \
  --query "[?principalId=='72b0ab9a-8f52-4bd2-8ec1-1745804952b4']" \
  --output table

# Test analyzer creation directly (optional)
# This would require making a test API call to the analyzer endpoint
```

## Resources

- **AI Services (West US)**: aicu-cps-gw6br2ms6mxy
- **AI Services (East US 2)**: aisa-cps-gw6br2ms6mxy
- **Storage Account**: stcpsgw6br2ms6mxy
- **API Container App**: ca-cps-gw6br2ms6mxy-api
- **Resource Group**: rg-knowledgegraph

## Next Steps

1. **Test immediately**: Try Start Analysis in the web app
2. **Monitor logs**: Watch for successful analyzer creation (should see HTTP 200/201 instead of 401)
3. **Validate group_id fix**: After permissions work, test cross-group case analysis
4. **Document for future**: Add role assignment to infrastructure-as-code (Bicep/Terraform)

---

**Status**: ✅ PERMISSIONS GRANTED - Ready for testing

**Resolution Time**: ~5 minutes

**Impact**: Should fix all 401 PermissionDenied errors when creating analyzers
