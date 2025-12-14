# Quick Query: Enforce UUID for All Schemas

**Date**: January 17, 2025  
**Status**: ✅ IMPLEMENTED  
**Impact**: Critical - Ensures consistency across all schemas, enables proper versioning

---

## Executive Summary

Changed Quick Query master schema to use **UUID as schema ID** (consistent with all other schemas) instead of hardcoded `"quick_query_master"` string. Added `schemaType` field for easy lookup.

**Before**:
```
Schema ID: "quick_query_master" (hardcoded string)
Blob path: quick_query_master/quick_query_master.json
Lookup: By ID
```

**After**:
```
Schema ID: "8f3a4b2c-1234-..." (UUID, generated)
Blob path: 8f3a4b2c-1234-.../8f3a4b2c-1234-....json
Lookup: By schemaType="quick_query_master"
```

---

## Why This Change?

### Problem with Hardcoded ID

1. **Inconsistency**: All other schemas use UUID, Quick Query used string
2. **Versioning impossible**: Can't create multiple versions with same ID
3. **Migration issues**: Different ID format complicates data migration
4. **Deletion confusion**: Special-case logic needed for non-UUID schemas

### Benefits of UUID

1. ✅ **Consistency**: All schemas follow same pattern
2. ✅ **Versioning ready**: Can create schema versions in future
3. ✅ **Standard tooling**: All CRUD operations work uniformly
4. ✅ **No special cases**: Deletion, update, retrieval all use same logic
5. ✅ **Future-proof**: Supports schema evolution

---

## Implementation Details

### Backend Changes

#### 1. Constants (proMode.py, line ~12213)

**Before**:
```python
QUICK_QUERY_MASTER_SCHEMA_ID = "quick_query_master"
```

**After**:
```python
# Using special identifier for lookup - actual schema ID will be UUID
QUICK_QUERY_MASTER_IDENTIFIER = "quick_query_master"  # Used in schemaType field
```

#### 2. Initialization Endpoint (proMode.py, line ~12220)

**Before**:
```python
# Check if exists
existing_schema = collection.find_one({"id": QUICK_QUERY_MASTER_SCHEMA_ID})

# Create with hardcoded ID
complete_schema_data = {
    "id": QUICK_QUERY_MASTER_SCHEMA_ID,  # "quick_query_master"
    # ...
}

blob_url = blob_helper.upload_schema_blob(
    schema_id=QUICK_QUERY_MASTER_SCHEMA_ID,  # "quick_query_master"
    # ...
)
```

**After**:
```python
# Check if exists by schemaType (not by ID)
existing_schema = collection.find_one({"schemaType": QUICK_QUERY_MASTER_IDENTIFIER})

if existing_schema:
    schema_id = existing_schema.get("id")  # Get existing UUID
    return existing

# Generate new UUID
schema_id = str(uuid.uuid4())  # e.g., "8f3a4b2c-1234-..."

# Create with UUID
complete_schema_data = {
    "id": schema_id,  # UUID!
    "schemaType": QUICK_QUERY_MASTER_IDENTIFIER,  # "quick_query_master"
    # ...
}

blob_url = blob_helper.upload_schema_blob(
    schema_id=schema_id,  # UUID!
    filename=f"{schema_id}.json"  # UUID!
)

# Add schemaType to metadata for lookup
metadata_dict = metadata.model_dump()
metadata_dict["schemaType"] = QUICK_QUERY_MASTER_IDENTIFIER

collection.insert_one(metadata_dict)
```

#### 3. Update-Prompt Endpoint (proMode.py, line ~12375)

**Before**:
```python
# Find by hardcoded ID
existing_metadata = collection.find_one({"id": QUICK_QUERY_MASTER_SCHEMA_ID})

# Update by hardcoded ID
collection.update_one(
    {"id": QUICK_QUERY_MASTER_SCHEMA_ID},
    {"$set": {"description": prompt}}
)

# Save blob with hardcoded ID
blob_helper.upload_schema_blob(
    schema_id=QUICK_QUERY_MASTER_SCHEMA_ID,
    filename=f"{QUICK_QUERY_MASTER_SCHEMA_ID}.json"
)

return {"schemaId": QUICK_QUERY_MASTER_SCHEMA_ID}
```

**After**:
```python
# Find by schemaType (not by ID)
existing_metadata = collection.find_one({"schemaType": QUICK_QUERY_MASTER_IDENTIFIER})

# Get actual UUID
schema_id = existing_metadata.get("id")
print(f"Found master schema with ID: {schema_id}")

# Update by schemaType
collection.update_one(
    {"schemaType": QUICK_QUERY_MASTER_IDENTIFIER},
    {"$set": {"description": prompt}}
)

# Save blob with UUID
blob_helper.upload_schema_blob(
    schema_id=schema_id,  # UUID!
    filename=f"{schema_id}.json"  # UUID!
)

return {"schemaId": schema_id}  # Return UUID
```

### Frontend Changes

#### PredictionTab.tsx (line ~172)

**Before**:
```typescript
// Find by hardcoded ID
const quickQueryMasterSchema = allSchemas.find((s: any) => s.id === 'quick_query_master');
```

**After**:
```typescript
// Find by schemaType field
const quickQueryMasterSchema = allSchemas.find((s: any) => s.schemaType === 'quick_query_master');
```

---

## Database Schema

### Cosmos DB Document Structure

**Before**:
```json
{
  "id": "quick_query_master",
  "name": "Quick Query Master Schema",
  "description": "...",
  "blobUrl": "https://.../quick_query_master/quick_query_master.json",
  // ... other fields
}
```

**After**:
```json
{
  "id": "8f3a4b2c-1234-5678-9abc-def012345678",
  "schemaType": "quick_query_master",  // NEW: Used for lookup
  "name": "Quick Query Master Schema",
  "description": "...",
  "blobUrl": "https://.../8f3a4b2c-1234-.../8f3a4b2c-1234-....json",
  // ... other fields
}
```

### Blob Storage Structure

**Before**:
```
pro-schemas-dev/
  quick_query_master/
    quick_query_master.json
```

**After**:
```
pro-schemas-dev/
  8f3a4b2c-1234-5678-9abc-def012345678/
    8f3a4b2c-1234-5678-9abc-def012345678.json
```

---

## Migration Path

### For New Deployments

1. Initialize Quick Query → Creates with UUID automatically
2. No migration needed

### For Existing Deployments

**Option 1: Delete and Reinitialize (Recommended)**
```
1. Delete old schema from UI (Schema tab)
2. Refresh Prediction tab
3. Quick Query auto-initializes with UUID
```

**Option 2: Manual Migration Script**
```python
# Find old schema
old_schema = collection.find_one({"id": "quick_query_master"})

if old_schema:
    # Generate new UUID
    new_id = str(uuid.uuid4())
    
    # Add schemaType field
    old_schema["schemaType"] = "quick_query_master"
    old_schema["id"] = new_id
    
    # Upload to blob with UUID path
    blob_url = blob_helper.upload_schema_blob(
        schema_id=new_id,
        schema_data=old_schema,
        filename=f"{new_id}.json"
    )
    
    # Update blobUrl
    old_schema["blobUrl"] = blob_url
    
    # Delete old
    collection.delete_one({"id": "quick_query_master"})
    
    # Insert new
    collection.insert_one(old_schema)
```

---

## Testing

### Test 1: Initialization Creates UUID

**Action**: Call `/pro-mode/quick-query/initialize`

**Expected**:
```json
{
  "schemaId": "8f3a4b2c-1234-5678-9abc-def012345678",  // UUID!
  "status": "created",
  "message": "Master schema initialized successfully"
}
```

**Verify**:
- Schema ID is UUID format
- Cosmos DB has `schemaType: "quick_query_master"`
- Blob path uses UUID: `8f3a4b2c-.../8f3a4b2c-....json`

### Test 2: Update Works with UUID

**Action**: Execute a query: "Summarize the documents"

**Expected**:
```
[QuickQuery] Found master schema with ID: 8f3a4b2c-1234-...
[QuickQuery] Updated field description (AI prompt): Summarize the documents
PUT /pro-mode/quick-query/update-prompt 200 OK
```

**Verify**:
- Backend logs show UUID
- Blob updated at UUID path
- Cosmos DB description updated

### Test 3: Frontend Finds Schema by schemaType

**Action**: Open Prediction tab, view Quick Query section

**Expected**:
```
[PredictionTab] Quick Query: Found master schema in Redux: {
  id: "8f3a4b2c-1234-...",
  schemaType: "quick_query_master",
  name: "Quick Query Master Schema"
}
```

**Verify**:
- Schema found by `schemaType` field
- UI shows schema correctly
- Query execution works

### Test 4: Deletion Works with UUID

**Action**: Delete Quick Query schema from Schema tab

**Expected**:
```
DELETE /pro-mode/schemas/8f3a4b2c-1234-...
[DeleteSchema] Deleting schema: 8f3a4b2c-1234-...
[DeleteSchema] ✅ Deleted from Cosmos DB
[DeleteSchema] ✅ Deleted blob from Azure Storage
```

**Verify**:
- Schema deleted from Cosmos DB
- Blob deleted from storage (UUID folder removed)
- No orphaned data

### Test 5: Reinitialize After Deletion

**Action**: Refresh Prediction tab after deletion

**Expected**:
```
[QuickQuery] Initializing master schema
[QuickQuery] Creating new master schema with UUID: 9a2b3c4d-...  // NEW UUID!
[QuickQuery] Successfully created
```

**Verify**:
- New UUID generated
- `schemaType` field set
- Everything works normally

---

## Consistency Verification

### All Schemas Now Use UUID

```python
# Regular schema creation
schema_id = str(uuid.uuid4())  # ✅

# AI-enhanced schema creation
schema_id = str(uuid.uuid4())  # ✅

# Quick Query schema creation
schema_id = str(uuid.uuid4())  # ✅ NOW CONSISTENT!
```

### All Blob Paths Use UUID

```
pro-schemas-dev/
  8f3a4b2c-1234-5678.../schema.json       # Regular schema
  9a2b3c4d-5678-9abc.../updated_FOO.json  # Enhanced schema
  1b2c3d4e-5678-9def.../1b2c3d4e-....json  # Quick Query ✅
```

### All Lookups Consistent

```python
# Regular schemas
collection.find_one({"id": schema_id})  # By UUID

# Quick Query schema
collection.find_one({"schemaType": "quick_query_master"})  # By type
# Then: schema_id = result.get("id")  # Get UUID

# All deletions
DELETE /pro-mode/schemas/{uuid}  # All use UUID!
```

---

## Benefits Realized

### 1. Versioning Support (Future)

```python
# Can now create versions of Quick Query schema
v1 = create_schema(schemaType="quick_query_master", version="1.0")
v2 = create_schema(schemaType="quick_query_master", version="2.0")

# Query specific version
latest = collection.find_one({
    "schemaType": "quick_query_master",
    "version": {"$exists": True}
}).sort("version", -1).limit(1)
```

### 2. Uniform CRUD Operations

```python
# All schemas (including Quick Query) use same patterns
create → Generate UUID
read → Query by UUID or schemaType
update → Update by UUID or schemaType
delete → Delete by UUID
```

### 3. No Special Cases

```python
# Before: Special handling for Quick Query
if schema_id == "quick_query_master":
    # Special blob path logic
    # Special deletion logic
    # Special update logic

# After: All schemas treated uniformly ✅
blob_path = f"{schema_id}/{filename}"
```

### 4. Migration-Ready

```python
# Can now migrate schemas between environments
export_schema(schema_id="8f3a4b2c-...")
import_schema(data, generate_new_id=True)  # New UUID in target env
```

---

## Breaking Changes

### ⚠️ API Response Changes

**Initialize endpoint**:
```diff
{
- "schemaId": "quick_query_master",
+ "schemaId": "8f3a4b2c-1234-5678-9abc-def012345678",
  "status": "created"
}
```

**Update-prompt endpoint**:
```diff
{
- "schemaId": "quick_query_master",
+ "schemaId": "8f3a4b2c-1234-5678-9abc-def012345678",
  "status": "updated"
}
```

### ⚠️ Frontend Code

Must update any hardcoded references:

```diff
- const schema = schemas.find(s => s.id === 'quick_query_master');
+ const schema = schemas.find(s => s.schemaType === 'quick_query_master');
```

### ⚠️ Database Queries

External tools/scripts must update:

```diff
- db.ProModeSchemas.find({"id": "quick_query_master"})
+ db.ProModeSchemas.find({"schemaType": "quick_query_master"})
```

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Schema ID** | `"quick_query_master"` | `"8f3a4b2c-..."` (UUID) |
| **Blob Path** | `quick_query_master/quick_query_master.json` | `8f3a4b2c-.../8f3a4b2c-....json` |
| **Lookup Method** | By hardcoded ID | By `schemaType` field |
| **Consistency** | ❌ Different from other schemas | ✅ Same as all schemas |
| **Versioning** | ❌ Not possible | ✅ Supported |
| **Deletion** | ✅ Works (special case) | ✅ Works (uniform) |

---

## Files Modified

1. **proMode.py** (Backend):
   - Line ~12213: Changed constant to `QUICK_QUERY_MASTER_IDENTIFIER`
   - Line ~12232: Generate UUID, query by schemaType
   - Line ~12257: Add schemaType to complete schema
   - Line ~12301: Add schemaType to metadata
   - Line ~12377: Find by schemaType, use UUID for updates

2. **PredictionTab.tsx** (Frontend):
   - Line ~169: Find schema by `schemaType` instead of hardcoded `id`

---

**Status**: ✅ **IMPLEMENTED**  
**Breaking**: Yes - API responses return UUID instead of string  
**Migration**: Delete old schema and reinitialize  
**Ready for deployment**: YES

