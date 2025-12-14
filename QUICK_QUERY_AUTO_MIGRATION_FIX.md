# Quick Query Migration Fix - Auto-Upgrade Old Schemas

**Date**: January 11, 2025  
**Issue**: Update-prompt endpoint failing for schemas created before unified interface  
**Error**: "Blob URL not found in schema metadata"  
**Status**: ✅ FIXED

## Problem Analysis

### Error Message
```
HTTP 500: Failed to update schema in blob storage: Blob URL not found in schema metadata
```

### Root Cause

The update-prompt endpoint was **too strict** - it required the `blobUrl` field to exist in metadata, but schemas created **before the unified interface fix** don't have this field:

```python
# ❌ BROKEN CODE
blob_url = existing_metadata.get("blobUrl")

if not blob_url:
    print(f"[QuickQuery] Warning: No blob URL found in metadata")
    raise Exception("Blob URL not found in schema metadata")  # ❌ Hard failure!
```

### Why This Happened

Timeline of Quick Query schema evolution:

1. **Version 1** (Initial implementation):
   - Schema created with ad-hoc fields
   - No `blobUrl` field
   - No unified interface

2. **Version 2** (Unified interface fix - THIS SESSION):
   - New schemas use ProSchemaMetadata
   - Include `blobUrl` field
   - BUT old schemas still in database don't have it

3. **Version 3** (This fix - Migration support):
   - Update-prompt auto-upgrades old schemas
   - Creates blob storage if missing
   - Updates metadata with blobUrl

## The Solution: Auto-Migration

Instead of failing when `blobUrl` is missing, the update-prompt endpoint now **auto-upgrades** old schemas:

### Fixed Code

**File**: `proMode.py`, lines ~12387-12430

```python
try:
    blob_helper = get_pro_mode_blob_helper(app_config)
    old_blob_url = existing_metadata.get("blobUrl")
    
    # ✅ FIX: Don't fail if blobUrl missing - auto-migrate instead
    if not old_blob_url:
        print(f"[QuickQuery] Warning: Old schema doesn't have blobUrl (created before unified interface)")
        print(f"[QuickQuery] Will create blob storage and update metadata")
    
    # Reconstruct the complete schema data for blob storage
    complete_schema_data = {
        "id": QUICK_QUERY_MASTER_SCHEMA_ID,
        "name": "Quick Query Master Schema",
        "description": prompt,  # Updated prompt
        "fieldSchema": {
            "fields": {
                "QueryResult": {
                    "type": "string",
                    "description": prompt,
                    "method": "generate"
                }
            }
        },
        "version": existing_metadata.get("version", "1.0.0"),
        "baseAnalyzerId": existing_metadata.get("baseAnalyzerId", "prebuilt-documentAnalyzer"),
        "createdBy": existing_metadata.get("createdBy", "quick-query-system"),
        "tags": existing_metadata.get("tags", ["quick-query", "master-schema", "phase-1-mvp"])
    }
    
    # ✅ Upload complete schema (creates blob if doesn't exist)
    blob_url = blob_helper.upload_schema_blob(
        schema_id=QUICK_QUERY_MASTER_SCHEMA_ID,
        schema_data=complete_schema_data,
        filename=f"{QUICK_QUERY_MASTER_SCHEMA_ID}.json"
    )
    print(f"[QuickQuery] Updated blob storage with new prompt: {blob_url}")
    
    # ✅ FIX: If first time creating blob, update metadata
    if not old_blob_url:
        print(f"[QuickQuery] Updating metadata with new blobUrl (migration from old schema)")
        collection.update_one(
            {"id": QUICK_QUERY_MASTER_SCHEMA_ID},
            {
                "$set": {
                    "blobUrl": blob_url,
                    "blobContainer": blob_helper.container_name
                }
            }
        )
        
except Exception as blob_error:
    print(f"[QuickQuery] Error: Failed to update blob storage: {blob_error}")
    import traceback
    print(f"[QuickQuery] Traceback: {traceback.format_exc()}")
    raise HTTPException(
        status_code=500,
        detail=f"Failed to update schema in blob storage: {str(blob_error)}"
    )
```

## How Auto-Migration Works

### Scenario 1: Old Schema (No blobUrl)

**Initial State** (Cosmos DB):
```json
{
    "id": "quick_query_master",
    "name": "Quick Query Master Schema",
    "description": "Old description",
    "fieldSchema": {...}
    // ❌ Missing: blobUrl, blobContainer
}
```

**What Happens on First Update-Prompt Call**:

1. **Detects old schema**: `old_blob_url = None`
2. **Logs migration**: "Old schema doesn't have blobUrl (created before unified interface)"
3. **Creates blob storage**: Uploads complete schema to Azure Blob Storage
4. **Gets blob URL**: `https://...blob.core.windows.net/.../quick_query_master.json`
5. **Updates metadata**: Adds `blobUrl` and `blobContainer` fields
6. **Returns success**: Prompt updated + schema migrated

**Final State** (Cosmos DB):
```json
{
    "id": "quick_query_master",
    "name": "Quick Query Master Schema",
    "description": "Updated prompt",
    // ✅ Added during migration:
    "blobUrl": "https://...blob.core.windows.net/.../quick_query_master.json",
    "blobContainer": "pro-schemas-dev"
}
```

**Final State** (Blob Storage):
```json
// File: quick_query_master.json
{
    "id": "quick_query_master",
    "name": "Quick Query Master Schema",
    "description": "Updated prompt",
    "fieldSchema": {
        "fields": {
            "QueryResult": {
                "type": "string",
                "description": "Updated prompt",
                "method": "generate"
            }
        }
    },
    "version": "1.0.0",
    "baseAnalyzerId": "prebuilt-documentAnalyzer",
    "createdBy": "quick-query-system",
    "tags": ["quick-query", "master-schema", "phase-1-mvp"]
}
```

### Scenario 2: New Schema (Has blobUrl)

**Initial State** (Cosmos DB):
```json
{
    "id": "quick_query_master",
    "name": "Quick Query Master Schema",
    "description": "Old prompt",
    "blobUrl": "https://...blob.core.windows.net/.../quick_query_master.json",  // ✅ Exists
    "blobContainer": "pro-schemas-dev"
}
```

**What Happens on Update-Prompt Call**:

1. **Detects new schema**: `old_blob_url` is not None
2. **Skips migration**: No log about old schema
3. **Updates blob storage**: Overwrites existing blob with updated schema
4. **Skips metadata update**: blobUrl already exists
5. **Returns success**: Prompt updated

## Benefits of Auto-Migration

### 1. Zero Downtime

Users don't need to:
- Delete old schemas manually
- Run migration scripts
- Restart services
- Re-initialize schemas

### 2. Transparent Upgrade

The migration happens **automatically** on first use:
```
User executes Quick Query
    ↓
Backend detects old schema
    ↓
Auto-migrates to new structure
    ↓
Query executes successfully
    ↓
All future queries use new structure
```

### 3. Backwards Compatible

Works with:
- ✅ Schemas created before unified interface (Version 1)
- ✅ Schemas created with unified interface but before blobUrl (Version 2)
- ✅ Schemas created with complete unified interface (Version 3)

### 4. Self-Healing

Even if blob storage gets deleted:
- Next update-prompt recreates it
- Metadata gets updated with new blobUrl
- System recovers automatically

## Impact Analysis

### Before Fix

1. ❌ **Hard failure**: Old schemas cannot be updated
2. ❌ **Manual intervention**: User must delete and recreate
3. ❌ **Lost history**: Old query history gone
4. ❌ **Poor UX**: Confusing error messages

### After Fix

1. ✅ **Automatic migration**: Old schemas upgraded on first use
2. ✅ **No manual steps**: Works out of the box
3. ✅ **Preserves history**: Old schemas retain their data
4. ✅ **Better UX**: Transparent to users

## Verification Steps

### Test 1: Old Schema Migration

**Setup**:
1. Find an old schema in Cosmos DB without `blobUrl`:
   ```javascript
   db.pro_mode_schemas.findOne({
       id: "quick_query_master",
       blobUrl: {$exists: false}
   })
   ```

**Test**:
1. Execute Quick Query with any prompt
2. Watch backend logs

**Expected Logs**:
```
[QuickQuery] Warning: Old schema doesn't have blobUrl (created before unified interface)
[QuickQuery] Will create blob storage and update metadata
[QuickQuery] Updated blob storage with new prompt: https://...
[QuickQuery] Updating metadata with new blobUrl (migration from old schema)
```

**Verify**:
1. Check Cosmos DB - schema now has `blobUrl` field
2. Check Blob Storage - file exists with complete schema
3. Execute another query - no migration logs (already upgraded)

### Test 2: New Schema (No Migration)

**Setup**:
1. Schema already has `blobUrl` field

**Test**:
1. Execute Quick Query

**Expected Logs**:
```
[QuickQuery] Updated blob storage with new prompt: https://...
```

**Verify**:
- No migration logs
- Blob storage updated
- No metadata changes (blobUrl unchanged)

### Test 3: Error Handling

**Setup**:
1. Temporarily disable blob storage access

**Test**:
1. Execute Quick Query

**Expected**:
- HTTP 500 error
- Detailed traceback in logs
- Clear error message to user

**Logs**:
```
[QuickQuery] Error: Failed to update blob storage: <error details>
[QuickQuery] Traceback: <full traceback>
```

## Console Output Examples

### Successful Migration
```
[QuickQuery] Executing query: Extract invoice number
[QuickQuery] Updating master schema with prompt: Extract invoice number
[QuickQuery] Warning: Old schema doesn't have blobUrl (created before unified interface)
[QuickQuery] Will create blob storage and update metadata
[QuickQuery] Updated blob storage with new prompt: https://stproschemadev.blob.core.windows.net/pro-schemas-dev/quick_query_master.json
[QuickQuery] Updating metadata with new blobUrl (migration from old schema)
[QuickQuery] Prompt updated successfully
```

### Successful Update (Already Migrated)
```
[QuickQuery] Executing query: Extract total amount
[QuickQuery] Updating master schema with prompt: Extract total amount
[QuickQuery] Updated blob storage with new prompt: https://stproschemadev.blob.core.windows.net/pro-schemas-dev/quick_query_master.json
[QuickQuery] Prompt updated successfully
```

## Files Modified

### proMode.py

**Line ~12387-12430**: Update-prompt endpoint

**Changes**:
1. Made `blobUrl` check **informational** instead of **error**
2. Added auto-creation of blob storage if missing
3. Added metadata update with `blobUrl` and `blobContainer` after creation
4. Added better error logging with traceback

## Deployment Notes

### Before Deploying

- ✅ No breaking changes
- ✅ Works with both old and new schemas
- ✅ Auto-migrates on first use

### After Deploying

1. **First user executes Quick Query**: Auto-migration happens
2. **Monitor logs**: Look for migration messages
3. **Verify**: Check Cosmos DB for `blobUrl` field
4. **Test**: Execute another query (should not migrate again)

### Rollback Plan

If issues occur:
- Revert this commit
- Old behavior returns (hard failure on missing blobUrl)
- No data loss

## Future Improvements

### 1. Add Migration Status Field

**Problem**: Can't tell if schema has been migrated without checking blobUrl.

**Solution**:
```python
collection.update_one(
    {"id": QUICK_QUERY_MASTER_SCHEMA_ID},
    {
        "$set": {
            "blobUrl": blob_url,
            "blobContainer": blob_helper.container_name,
            "migrationVersion": "unified-interface-v3",  # Track migration
            "migratedAt": datetime.utcnow()
        }
    }
)
```

### 2. Add Bulk Migration Endpoint

**Problem**: Want to migrate all schemas proactively instead of on-demand.

**Solution**:
```python
@router.post("/pro-mode/schemas/migrate-all")
async def migrate_all_schemas():
    """Migrate all old schemas to unified interface."""
    schemas = collection.find({"blobUrl": {"$exists": False}})
    migrated_count = 0
    
    for schema in schemas:
        # Migrate each schema...
        migrated_count += 1
    
    return {"migrated": migrated_count}
```

### 3. Add Migration Health Check

**Problem**: Want to know if any schemas still need migration.

**Solution**:
```python
@router.get("/pro-mode/schemas/migration-status")
async def get_migration_status():
    """Check how many schemas need migration."""
    total = collection.count_documents({})
    migrated = collection.count_documents({"blobUrl": {"$exists": True}})
    
    return {
        "total": total,
        "migrated": migrated,
        "pending": total - migrated,
        "percentComplete": (migrated / total * 100) if total > 0 else 100
    }
```

## Lessons Learned

1. **Graceful degradation**: Don't fail hard on missing fields - auto-migrate
2. **Backwards compatibility**: Always support old data formats
3. **Self-healing systems**: Auto-upgrade instead of requiring manual intervention
4. **Clear logging**: Make migration visible in logs for debugging
5. **Progressive enhancement**: Old schemas work, new schemas are better

## Success Criteria

✅ **Fix is successful when**:
- Old schemas without blobUrl auto-migrate on first update
- Migration logs appear in backend
- Cosmos DB updated with blobUrl field
- Blob storage created with complete schema
- Second update doesn't trigger migration (already done)
- New schemas update without migration
- No breaking changes or data loss

---

**Fix completed**: January 11, 2025  
**Ready for deployment**: ✅ YES  
**Breaking changes**: None  
**Backwards compatible**: ✅ YES - Auto-migrates old schemas  
**Manual intervention**: ❌ NOT REQUIRED - Fully automatic
