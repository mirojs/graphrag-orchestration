# Data Lake Gen2 Configuration Guide

## Overview

The storage account can be deployed with **Hierarchical Namespace (HNS)** enabled, which upgrades it to Azure Data Lake Gen2. This is controlled by the `enableHierarchicalNamespace` parameter.

## Default Behavior

- **Default:** `false` (Standard Blob Storage)
- **Reason:** HNS cannot be enabled on existing storage accounts (read-only property)
- **Safe for:** Testing virtual folder patterns without infrastructure changes

## When to Enable Data Lake Gen2

Enable HNS (`enableHierarchicalNamespace: true`) when:

✅ Creating a **new storage account** (new environment/region)  
✅ Need true folder hierarchy (not just virtual folders via prefixes)  
✅ Need POSIX-compliant ACLs on directories  
✅ Working with big data workloads (Spark, Databricks, HDInsight)  
✅ Want better performance for hierarchical operations

## How to Enable for Different Scenarios

### Scenario 1: New Environment (Recommended)

Create a new environment with Data Lake Gen2 from the start:

```bash
# Create new environment (e.g., for West US)
cd code/content-processing-solution-accelerator
azd env new westus-env

# Set location
azd env set AZURE_LOCATION westus

# Enable Data Lake Gen2 for this environment
azd env set AZURE_ENV_ENABLE_HNS true

# Provision (creates new storage with HNS enabled)
azd provision
```

### Scenario 2: Environment-Specific Config File

Edit `.azure/<environment>/config.json`:

```json
{
  "infra": {
    "parameters": {
      "aiDeploymentsLocation": "westus",
      "enablePrivateNetworking": false,
      "gptDeploymentCapacity": 100,
      "enableHierarchicalNamespace": true
    }
  }
}
```

### Scenario 3: One-Time Deployment Override

```bash
# Deploy with HNS enabled without saving to environment
azd provision --parameter enableHierarchicalNamespace=true
```

## Testing Strategy (Incremental)

### Phase 1: Test Virtual Folders with Standard Blob Storage ✅
**Current East US 2 environment** (HNS disabled)

1. Update backend to use virtual folder pattern: `{container}/{group_id}/{filename}`
2. Add X-Group-ID header to frontend
3. Test file uploads with group isolation
4. Verify Cosmos DB partition key queries work

**Why:** Virtual folders work with both standard and Gen2 storage. Test the code changes first.

### Phase 2: Deploy Data Lake Gen2 in New Region ✅
**New West US environment** (HNS enabled)

1. Create westus-env with `AZURE_ENV_ENABLE_HNS=true`
2. Deploy complete stack with Gen2 storage
3. Verify same virtual folder code works with Gen2
4. Compare performance and features

**Why:** Clean deployment, no risk to existing environment, easy rollback.

## Current Environment Status

| Environment | Location | HNS Enabled | Purpose |
|-------------|----------|-------------|---------|
| contentaccelerator | eastus2 | ❌ No | Test virtual folders with existing storage |
| westus-env (future) | westus | ✅ Yes | Test Data Lake Gen2 features |

## Important Notes

⚠️ **Cannot change HNS on existing storage accounts**  
- Once a storage account is created, `isHnsEnabled` is read-only
- Attempting to change it will fail deployment
- Must create new storage account to enable HNS

✅ **Virtual folder pattern works with both**  
- Code using `{group_id}/{filename}` paths works on both storage types
- No code changes needed when migrating from Blob to Gen2
- Safe to test incrementally

✅ **Parameter defaults to `false` for safety**  
- Existing deployments won't accidentally try to enable HNS
- Must explicitly opt-in for new deployments

## Verification Commands

Check if HNS is enabled on a storage account:

```bash
# Get storage account name from environment
STORAGE_ACCOUNT=$(azd env get-value STORAGE_ACCOUNT_NAME 2>/dev/null || echo "stcpsxh5lwkfq3vfm")

# Check HNS status
az storage account show \
  --name "$STORAGE_ACCOUNT" \
  --query "{name:name, isHnsEnabled:isHnsEnabled, kind:kind}" \
  -o table
```

Expected output:
- **Standard Blob Storage:** `isHnsEnabled: false`
- **Data Lake Gen2:** `isHnsEnabled: true`

## Migration Path (When Ready)

When you want to fully migrate to Data Lake Gen2:

1. Test virtual folder code in East US 2 (HNS disabled) ✅
2. Create West US environment with HNS enabled ✅
3. Verify functionality in West US
4. Migrate data if needed (or start fresh)
5. Delete East US 2 deployment
6. Use West US as primary (or create new East US with HNS)

## Related Files

- `infra/main.bicep` - Parameter definition and storage module
- `infra/main.parameters.json` - Default parameter values
- `.azure/<env>/config.json` - Environment-specific overrides
- `infra/scripts/post_deployment.sh` - Automated permission setup
