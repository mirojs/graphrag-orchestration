# Storage Migration Diagnosis

## Problem Statement
After migrating to group-first container pattern:
- ✅ **Input files**: Present in `group-{id}/input-files/` ← WORKING
- ❌ **Schemas**: NOT in `group-{id}/schemas/` ← MISSING
- ❌ **Analysis results**: NOT in `group-{id}/analysis-results/` ← MISSING
- ⚠️ **Analysis got results "through fallback"** ← Using old storage locations

## Expected Storage Structure
```
group-{sanitized_group_id}/
├── input-files/
│   └── {process_id}_{filename}.pdf
├── reference-files/
│   └── {process_id}_{filename}.pdf
├── schemas/
│   └── {schema_id}/
│       └── schema_{timestamp}.json
├── analyzers/
│   └── analyzer_{analyzer_id}_{timestamp}.json
└── analysis-results/
    ├── analysis_result_{analyzer_id}_{timestamp}.json
    └── analysis_summary_{analyzer_id}_{timestamp}.json
```

## Root Cause Analysis

### Issue 1: Code vs Deployment Mismatch
The code in the repository HAS been updated to use the new pattern:
- ✅ `get_group_container_name()` - Returns `group-{id}`
- ✅ `get_resource_blob_path()` - Returns subdirectory paths
- ✅ ProModeSchemaBlob uses group container
- ✅ Analysis results save uses group container

**BUT** the deployed Docker image may still contain OLD CODE.

### Issue 2: Docker Image Not Rebuilt
After code changes, you need to:
1. Rebuild the Docker images
2. Push to Azure Container Registry  
3. Redeploy to Azure Container Apps

### Issue 3: Container Apps May Be Caching
Azure Container Apps might be running old container revisions.

## Diagnostic Steps

### Step 1: Check Azure Storage Account Structure
Navigate to Azure Portal → Storage Account → Containers

Expected to see:
- `group-{your-group-id}` ← ONE container
  - `input-files/` ← Should have files
  - `schemas/` ← Should have schemas
  - `analysis-results/` ← Should have results
  
Currently seeing:
- `group-{your-group-id}` 
  - `input-files/` ← Only this exists

Old containers that might still exist:
- `pro-schemas-{config}` ← OLD PATTERN
- `analysis-results-{group_id}` ← OLD PATTERN
- `analyzers-{group_id}` ← OLD PATTERN

### Step 2: Check Backend Logs
Look for these log messages in Container Apps logs:

**For Schema Saves:**
```
[ProModeSchemaBlob] Initialized for group: {group_id}, container: group-{sanitized}
[upload_schema_blob] Group: {group_id}, Blob: schemas/{schema_id}/...
```

**For Analysis Results:**
```
[AnalysisResults] 🔐 GROUP ISOLATION: Saving to container 'group-{id}' (group: {id})
[AnalysisResults] 💾 Complete results saved to Storage Account blob: analysis-results/...
```

If you DON'T see these messages, the deployed code is OLD.

### Step 3: Check Container App Revision
```bash
az containerapp revision list \
  --name ca-{solution-prefix}-api \
  --resource-group {resource-group} \
  --query "[].{name:name,active:properties.active,created:properties.createdTime,image:properties.template.containers[0].image}"
```

Check if the image timestamp matches your last build.

## Resolution Steps

### Option 1: Full Rebuild and Redeploy (RECOMMENDED)
```bash
# Navigate to scripts directory
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/infra/scripts

# Rebuild Docker images with latest code
./docker-build.sh

# Redeploy everything
azd up
```

This will:
1. Build new Docker images with updated code
2. Push to Azure Container Registry
3. Deploy new container revisions
4. Run post-deployment scripts

### Option 2: Quick Container Restart (Testing Only)
```bash
az containerapp revision restart \
  --name ca-{solution-prefix}-api \
  --resource-group {resource-group} \
  --revision {revision-name}
```

**Note**: This only works if the image in ACR is already updated.

### Option 3: Manual Image Check
```bash
# Check what's in Azure Container Registry
az acr repository show-tags \
  --name {acr-name} \
  --repository contentprocessorapi \
  --orderby time_desc \
  --output table
```

Look for recent timestamps.

## Verification After Deployment

### 1. Check Storage Structure
After redeployment, upload a schema and run analysis:
1. Upload schema → Check `group-{id}/schemas/` exists
2. Run analysis → Check `group-{id}/analysis-results/` exists

### 2. Check Backend Logs
Filter logs for these patterns:
- `[ProModeSchemaBlob]` → Should show group container
- `[AnalysisResults] 🔐 GROUP ISOLATION` → Should show group container
- `[AnalyzeContent]` → Should show finding files in `input-files/` subdirectory

### 3. Verify No Fallback
If analysis works **without** creating new containers like `analysis-results-{id}`, then the new pattern is working.

## Expected vs Actual Behavior

| Component | Expected Location | Actual Location | Status |
|-----------|------------------|-----------------|--------|
| Input Files | `group-{id}/input-files/` | `group-{id}/input-files/` | ✅ Working |
| Reference Files | `group-{id}/reference-files/` | ??? | ❓ Unknown |
| Schemas | `group-{id}/schemas/{id}/` | `pro-schemas-{config}/` ? | ❌ Old Pattern |
| Analyzers | `group-{id}/analyzers/` | `analyzers-{id}/` ? | ❌ Old Pattern |
| Analysis Results | `group-{id}/analysis-results/` | `analysis-results-{id}/` ? | ❌ Old Pattern |

## Code Verification Checklist

These functions should all be using the NEW pattern:

- ✅ `get_group_container_name()` → Returns `group-{sanitized_id}`
- ✅ `get_resource_blob_path()` → Returns `{type}-files/` or `{type}/`
- ✅ `ProModeSchemaBlob.__init__()` → Uses `get_group_container_name()`
- ✅ `ProModeSchemaBlob.upload_schema_blob()` → Uses `get_resource_blob_path("schema", ...)`
- ✅ Analysis results save (line ~9078) → Uses `get_group_container_name()` + `get_resource_blob_path("analysis_result", ...)`
- ✅ File resolution (line ~6744) → Searches with `{file_type}-files/{blob_id}` prefix

All code checks pass ✅ → **Problem is in deployment, not code**

## Next Steps

1. **Rebuild Docker images** with latest code
2. **Redeploy to Azure** via `azd up`
3. **Test end-to-end**:
   - Upload input files
   - Create/upload schema
   - Run analysis
   - Check all files land in group container subdirectories

## Rollback Plan (If Needed)

If new pattern causes issues, the old containers still exist:
- Schemas: Check `pro-schemas-{config}/`
- Analysis results: Check `analysis-results-{group_id}/`
- Analyzers: Check `analyzers-{group_id}/`

Data is not lost - it's just in the old locations.
