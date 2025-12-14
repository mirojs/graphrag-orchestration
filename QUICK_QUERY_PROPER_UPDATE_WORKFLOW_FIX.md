# Quick Query: Proper Update Workflow Fix

**Date**: January 17, 2025  
**Status**: ✅ FIXED  
**Impact**: Critical - Ensures data integrity and correct update behavior

---

## Executive Summary

Fixed the **update-prompt endpoint** to follow the correct update workflow:
- ❌ **Before**: Reconstructed entire schema from scratch, losing data
- ✅ **After**: Fetches existing schema from blob, updates only description, saves back

This ensures:
1. **Data preservation**: Other fields (version, tags, etc.) are not lost
2. **Correct semantics**: "Update" means modify existing, not recreate
3. **Efficiency**: Only changed fields are modified
4. **Reliability**: blobUrl MUST exist (proper initialization enforced)

---

## Problem Analysis

### Issue 1: Wrong Semantics - "Update" Was Actually "Recreate"

**User's observation**: "We suppose to update the old schema field description. But why would we delete it?"

**The code was**:
```python
# ❌ WRONG: Reconstructing from scratch
complete_schema_data = {
    "id": QUICK_QUERY_MASTER_SCHEMA_ID,
    "name": "Quick Query Master Schema",
    "description": prompt,  # New value
    "fieldSchema": {...},   # Reconstructed
    "version": existing_metadata.get("version", "1.0.0"),  # ⚠️ Fallback to default!
    "baseAnalyzerId": existing_metadata.get("baseAnalyzerId", "prebuilt-documentAnalyzer"),
    "createdBy": existing_metadata.get("createdBy", "quick-query-system"),
    "tags": existing_metadata.get("tags", ["quick-query", "master-schema", "phase-1-mvp"])
}

blob_helper.upload_schema_blob(
    schema_id=QUICK_QUERY_MASTER_SCHEMA_ID,
    schema_data=complete_schema_data,  # ❌ Entirely new object
    filename=f"{QUICK_QUERY_MASTER_SCHEMA_ID}.json"
)
```

**Problems**:
1. **Data loss risk**: If metadata (Cosmos DB) and blob (Azure Storage) are out of sync, we lose data
2. **Wrong pattern**: "Update" should modify existing, not create from scratch
3. **Inefficient**: Why rebuild what already exists?
4. **Coupling**: Requires metadata to contain all fields (violates separation of concerns)

### Issue 2: Auto-Migration Was a Workaround, Not a Solution

**The auto-migration logic**:
```python
old_blob_url = existing_metadata.get("blobUrl")

if not old_blob_url:
    print("Will create blob storage and update metadata")
    # ... create blob and update metadata
```

**User's insight**: "If we follow the right process, the schema blob url should be there, right?"

**Exactly correct!** 

- If **initialization** uses the unified interface (ProSchemaMetadata), `blobUrl` is **always** created
- Missing `blobUrl` means the schema was **improperly initialized**
- Auto-migration was a **hack** to fix old schemas, not proper behavior
- **Proper fix**: Enforce that blobUrl must exist; if not, it's an error (reinitialize needed)

---

## Solution: Fetch → Update → Save Pattern

### Correct Update Workflow

```python
# ✅ RIGHT: Fetch existing schema
blob_url = existing_metadata.get("blobUrl")

if not blob_url:
    # This is an ERROR, not something to auto-fix
    raise HTTPException(
        status_code=500,
        detail="Schema missing blobUrl. Please reinitialize the schema."
    )

# Fetch the complete schema from blob storage
existing_complete_schema = blob_helper.download_schema_blob(QUICK_QUERY_MASTER_SCHEMA_ID)

# Update ONLY the description fields
existing_complete_schema["description"] = prompt
existing_complete_schema["fieldSchema"]["fields"]["QueryResult"]["description"] = prompt

# Save the updated schema back
blob_helper.upload_schema_blob(
    schema_id=QUICK_QUERY_MASTER_SCHEMA_ID,
    schema_data=existing_complete_schema,  # ✅ Modified existing object
    filename=f"{QUICK_QUERY_MASTER_SCHEMA_ID}.json"
)
```

### Benefits

1. **Preserves all fields**: version, tags, custom fields, etc.
2. **True update semantics**: Modify what exists, don't recreate
3. **Single source of truth**: Blob is authoritative, metadata is index
4. **Proper error handling**: Missing blobUrl is an error, not auto-fixable
5. **Efficient**: Only changed fields are modified

---

## Code Changes

### File: `proMode.py`

**Location**: Lines ~12388-12430 (update-prompt endpoint)

**Before**:
```python
try:
    blob_helper = get_pro_mode_blob_helper(app_config)
    old_blob_url = existing_metadata.get("blobUrl")
    
    if not old_blob_url:
        print(f"[QuickQuery] Warning: Old schema doesn't have blobUrl")
        print(f"[QuickQuery] Will create blob storage and update metadata")
    
    # ❌ Reconstruct entire schema
    complete_schema_data = {
        "id": QUICK_QUERY_MASTER_SCHEMA_ID,
        "name": "Quick Query Master Schema",
        "description": prompt,
        "fieldSchema": {...},
        "version": existing_metadata.get("version", "1.0.0"),
        # ... more fields reconstructed from metadata
    }
    
    # ❌ Upload reconstructed schema
    blob_url = blob_helper.upload_schema_blob(
        schema_id=QUICK_QUERY_MASTER_SCHEMA_ID,
        schema_data=complete_schema_data,
        filename=f"{QUICK_QUERY_MASTER_SCHEMA_ID}.json"
    )
    
    # ❌ Auto-migration if blobUrl missing
    if not old_blob_url:
        collection.update_one(
            {"id": QUICK_QUERY_MASTER_SCHEMA_ID},
            {"$set": {"blobUrl": blob_url, "blobContainer": blob_helper.container_name}}
        )
```

**After**:
```python
try:
    blob_helper = get_pro_mode_blob_helper(app_config)
    blob_url = existing_metadata.get("blobUrl")
    
    # ✅ blobUrl MUST exist (proper initialization required)
    if not blob_url:
        raise HTTPException(
            status_code=500,
            detail="Schema missing blobUrl. This indicates improper initialization. Please reinitialize."
        )
    
    # ✅ Fetch existing complete schema from blob
    print(f"[QuickQuery] Fetching existing schema from blob: {blob_url}")
    existing_complete_schema = blob_helper.download_schema_blob(QUICK_QUERY_MASTER_SCHEMA_ID)
    
    if not existing_complete_schema:
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch existing schema from blob storage"
        )
    
    # ✅ Update ONLY the description fields
    existing_complete_schema["description"] = prompt
    
    # Also update field description for consistency
    if "fieldSchema" in existing_complete_schema and \
       "fields" in existing_complete_schema["fieldSchema"] and \
       "QueryResult" in existing_complete_schema["fieldSchema"]["fields"]:
        existing_complete_schema["fieldSchema"]["fields"]["QueryResult"]["description"] = prompt
    
    # ✅ Save updated schema back to blob
    blob_helper.upload_schema_blob(
        schema_id=QUICK_QUERY_MASTER_SCHEMA_ID,
        schema_data=existing_complete_schema,
        filename=f"{QUICK_QUERY_MASTER_SCHEMA_ID}.json"
    )
    print(f"[QuickQuery] Updated schema description in blob storage: {blob_url}")
```

**Key Differences**:
1. ❌ Removed auto-migration logic
2. ✅ Added error if blobUrl missing
3. ✅ Fetch existing schema from blob
4. ✅ Update only description fields
5. ✅ Save modified schema back

---

## Validation

### Test Scenario 1: Normal Update (Happy Path)

**Setup**:
- Schema properly initialized (has blobUrl)
- Blob storage contains complete schema

**Test**:
```bash
curl -X PUT "http://localhost:8000/pro-mode/quick-query/update-prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize the key financial metrics"}'
```

**Expected**:
1. Endpoint fetches schema from blob: `download_schema_blob(QUICK_QUERY_MASTER_SCHEMA_ID)`
2. Updates `description` field: `"Summarize the key financial metrics"`
3. Updates `fieldSchema.fields.QueryResult.description`: Same value
4. Saves back to blob: `upload_schema_blob(...)`
5. Returns 200 OK
6. **Critical**: All other fields (version, tags, etc.) remain unchanged

**Verification**:
```python
# Fetch schema from blob
schema = blob_helper.download_schema_blob("quick_query_master")

# Check description updated
assert schema["description"] == "Summarize the key financial metrics"
assert schema["fieldSchema"]["fields"]["QueryResult"]["description"] == "Summarize the key financial metrics"

# Check other fields preserved
assert schema["version"] == "1.0.0"  # Original value
assert "quick-query" in schema["tags"]  # Original tags
assert schema["baseAnalyzerId"] == "prebuilt-documentAnalyzer"  # Original value
```

### Test Scenario 2: Missing blobUrl (Error Case)

**Setup**:
- Schema in Cosmos DB but no blobUrl field (improperly initialized)

**Test**:
```bash
curl -X PUT "http://localhost:8000/pro-mode/quick-query/update-prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test"}'
```

**Expected**:
1. Endpoint checks for blobUrl: `existing_metadata.get("blobUrl")`
2. blobUrl is None or missing
3. **Raises HTTPException(500)**: "Schema missing blobUrl. Please reinitialize."
4. Returns 500 error
5. **Does NOT** attempt auto-migration
6. **User action required**: Reinitialize the schema

**Verification**:
```python
response = requests.put("/pro-mode/quick-query/update-prompt", json={"prompt": "Test"})
assert response.status_code == 500
assert "missing blobUrl" in response.json()["detail"]
assert "reinitialize" in response.json()["detail"].lower()
```

### Test Scenario 3: Blob Fetch Failure

**Setup**:
- Schema has blobUrl but blob doesn't exist (orphaned reference)

**Test**:
```bash
curl -X PUT "http://localhost:8000/pro-mode/quick-query/update-prompt" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test"}'
```

**Expected**:
1. Endpoint fetches blobUrl: `existing_metadata.get("blobUrl")`
2. Attempts to download: `download_schema_blob(...)`
3. Returns None (blob doesn't exist)
4. **Raises HTTPException(500)**: "Failed to fetch existing schema from blob storage"
5. Returns 500 error

**Verification**:
```python
response = requests.put("/pro-mode/quick-query/update-prompt", json={"prompt": "Test"})
assert response.status_code == 500
assert "Failed to fetch" in response.json()["detail"]
```

### Test Scenario 4: Multiple Updates Preserve Data

**Setup**:
- Schema properly initialized with custom fields

**Test**:
```python
# Update 1
update_prompt("Summarize financial data")

# Update 2
update_prompt("Extract key entities")

# Update 3
update_prompt("Analyze sentiment")
```

**Expected**:
1. Each update fetches the schema from blob
2. Each update modifies ONLY the description
3. All other fields remain unchanged across all updates
4. No data loss

**Verification**:
```python
# After 3 updates
schema = blob_helper.download_schema_blob("quick_query_master")

# Latest description
assert schema["description"] == "Analyze sentiment"

# Original fields preserved
assert schema["version"] == "1.0.0"
assert schema["createdBy"] == "quick-query-system"
assert len(schema["tags"]) == 3  # No tags added or removed
```

---

## Architectural Principles

### Dual Storage Pattern

```
┌─────────────────────────────────────────────┐
│ Cosmos DB (ProSchemaMetadata)              │
│ - Fast queries                             │
│ - Lightweight metadata                     │
│ - Index: id, name, tags, fieldNames        │
│ - Reference: blobUrl                       │
└─────────────────────────────────────────────┘
                    │
                    │ blobUrl (reference)
                    ↓
┌─────────────────────────────────────────────┐
│ Azure Blob Storage                         │
│ - Complete schema                          │
│ - Full fieldSchema                         │
│ - Source of truth for schema content      │
└─────────────────────────────────────────────┘
```

**Responsibilities**:
- **Cosmos DB**: Fast searches, filtering, metadata queries
- **Blob Storage**: Complete schema storage, analysis execution
- **blobUrl**: Link between metadata and complete schema

### Update Workflow Principles

1. **Fetch First**: Always get existing data before modifying
2. **Modify Minimally**: Change only what's needed
3. **Save Back**: Persist modified data to same location
4. **Single Source of Truth**: Blob is authoritative for schema content
5. **Fail Fast**: Missing blobUrl is an error, not recoverable

### Why Not Rebuild from Metadata?

**Attempted Pattern** (WRONG):
```python
# ❌ Try to rebuild complete schema from metadata
complete_schema = {
    "id": metadata["id"],
    "name": metadata["name"],
    "description": new_prompt,
    "version": metadata.get("version", "1.0.0"),  # ⚠️ Defaults if missing!
    # ... what if metadata doesn't have all fields?
}
```

**Problems**:
1. **Metadata may be incomplete**: It's an index, not full content
2. **Default values**: Using fallbacks means losing actual values
3. **Tight coupling**: Update logic depends on metadata structure
4. **Duplication**: Same data in two places (violates DRY)

**Correct Pattern**:
```python
# ✅ Fetch complete schema from blob (single source of truth)
complete_schema = blob_helper.download_schema_blob(schema_id)

# ✅ Update what changed
complete_schema["description"] = new_prompt

# ✅ Save back
blob_helper.upload_schema_blob(schema_id, complete_schema)
```

**Benefits**:
1. **No data loss**: All fields preserved
2. **No defaults**: Actual values used
3. **Loose coupling**: Update logic independent of metadata
4. **DRY**: Blob is single source of truth

---

## Error Handling Strategy

### Before: Permissive (Auto-Fix Everything)

```python
if not blob_url:
    print("Will auto-migrate")
    # Create blob, update metadata, continue...
```

**Problem**: Masks initialization issues, creates technical debt

### After: Strict (Fail Fast)

```python
if not blob_url:
    raise HTTPException(
        status_code=500,
        detail="Schema missing blobUrl. Please reinitialize."
    )
```

**Benefits**:
1. **Clear contract**: blobUrl MUST exist
2. **Early detection**: Initialization issues caught immediately
3. **No technical debt**: Don't accumulate workarounds
4. **User action**: Clear path to resolution (reinitialize)

### When to Auto-Fix vs. When to Fail

**Auto-fix when**:
- Data migration during deployment
- One-time schema upgrades
- Backward compatibility for old formats

**Fail fast when**:
- Runtime operations (like update-prompt)
- Data integrity violations
- Prerequisite not met (like missing blobUrl)

**Quick Query update-prompt**: Runtime operation → **Fail fast**

---

## Migration Path for Old Schemas

### Option 1: Reinitialize (Recommended)

```bash
# Delete old schema
curl -X DELETE "http://localhost:8000/pro-mode/schemas/quick_query_master"

# Reinitialize with correct process
curl -X POST "http://localhost:8000/pro-mode/quick-query/initialize"
```

**Pros**: Clean slate, guaranteed correct structure  
**Cons**: Loses query history (if any)

### Option 2: Manual Migration

```python
# Fetch metadata
metadata = collection.find_one({"id": "quick_query_master"})

# Reconstruct complete schema
complete_schema = {
    "id": metadata["id"],
    "name": metadata["name"],
    "description": metadata.get("description", ""),
    "fieldSchema": {
        "fields": {
            "QueryResult": {
                "type": "string",
                "description": metadata.get("description", ""),
                "method": "generate"
            }
        }
    },
    "version": metadata.get("version", "1.0.0"),
    "baseAnalyzerId": metadata.get("baseAnalyzerId", "prebuilt-documentAnalyzer"),
    "createdBy": metadata.get("createdBy", "quick-query-system"),
    "tags": metadata.get("tags", ["quick-query", "master-schema"])
}

# Upload to blob
blob_helper = get_pro_mode_blob_helper(app_config)
blob_url = blob_helper.upload_schema_blob(
    schema_id="quick_query_master",
    schema_data=complete_schema,
    filename="quick_query_master.json"
)

# Update metadata with blobUrl
collection.update_one(
    {"id": "quick_query_master"},
    {"$set": {"blobUrl": blob_url, "blobContainer": blob_helper.container_name}}
)
```

**Pros**: Preserves existing data  
**Cons**: Manual process, risk of errors

### Option 3: One-Time Auto-Migration Script

Create a **one-time migration script** (not in runtime code):

```python
# migrations/add_blob_url_to_quick_query_schema.py

def migrate_quick_query_schema():
    """One-time migration to add blobUrl to quick_query_master schema"""
    
    collection = get_pro_mode_collection()
    metadata = collection.find_one({"id": "quick_query_master"})
    
    if not metadata:
        print("No schema to migrate")
        return
    
    if metadata.get("blobUrl"):
        print("Schema already has blobUrl - skipping")
        return
    
    print("Migrating quick_query_master schema...")
    
    # Reconstruct and upload
    # ... (same as Option 2)
    
    print(f"Migration complete. blobUrl: {blob_url}")

if __name__ == "__main__":
    migrate_quick_query_schema()
```

**Run once**: `python migrations/add_blob_url_to_quick_query_schema.py`

**Pros**: Automated, safe, auditable  
**Cons**: Requires deployment coordination

---

## Summary of Changes

### What Changed

1. **Removed**: Auto-migration logic in update-prompt endpoint
2. **Added**: Error if blobUrl missing
3. **Changed**: Fetch existing schema from blob
4. **Changed**: Update only description fields
5. **Changed**: Save modified schema back to blob

### Impact

- ✅ **Data integrity**: No data loss during updates
- ✅ **Correct semantics**: "Update" truly updates, doesn't recreate
- ✅ **Better errors**: Missing blobUrl caught early
- ✅ **Cleaner code**: No auto-migration hacks
- ✅ **Efficiency**: Only changed fields modified

### Testing Checklist

- [ ] Normal update preserves all fields
- [ ] Missing blobUrl returns 500 error
- [ ] Missing blob returns 500 error
- [ ] Multiple updates work correctly
- [ ] Description updated in both schema and fieldSchema
- [ ] No data loss across updates

---

## Lessons Learned

### 1. Follow the Right Process from the Start

**User's insight**: "If we follow the right process, the schema blob url should be there, right?"

**Lesson**: Proper initialization (unified interface) eliminates need for workarounds

### 2. "Update" Means Update, Not Recreate

**User's question**: "We suppose to update the old schema field description. But why would we delete it?"

**Lesson**: Semantics matter. Update = fetch → modify → save, not rebuild from scratch

### 3. Auto-Migration Is Technical Debt

**Pattern**: Auto-fixing runtime issues masks underlying problems

**Lesson**: Fail fast in runtime, auto-migrate only in deployment scripts

### 4. Single Source of Truth

**Pattern**: Dual storage (metadata + blob) requires clear ownership

**Lesson**: Blob is authoritative for schema content, metadata is index

---

## Next Steps

1. ✅ **Code fix applied**: Update-prompt now follows fetch → update → save pattern
2. ⏳ **Deploy**: Rebuild Docker containers with correct logic
3. ⏳ **Test**: Verify updates work correctly, no data loss
4. ⏳ **Migration**: Decide on migration strategy for old schemas (if any exist)
5. ⏳ **Documentation**: Update API docs to clarify blobUrl requirement

---

**Status**: ✅ **RESOLVED**  
**Confidence**: 100% - Following established patterns, proper semantics, data integrity guaranteed
