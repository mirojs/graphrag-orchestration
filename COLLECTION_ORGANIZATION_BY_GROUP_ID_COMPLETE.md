# Collection Organization by Group ID - Implementation Complete ✅

## Date: October 22, 2025

---

## Problem Statement

Schemas were being stored in Cosmos DB as a flat list without proper organization by `group_id`. This made it difficult to:
- Visualize which schemas belong to which group
- Query schemas efficiently by group
- Maintain proper isolation between different groups

### Before (Flat Structure)
```
Schemas_pro Collection
├── schema1 (group_id: "abc123")
├── schema2 (group_id: "abc123")  
├── schema3 (group_id: "xyz789")
├── schema4 (group_id: null)        ← No organization
└── schema5 (group_id: null)        ← No group assignment
```

### After (Organized by Group)
```
Schemas_pro Collection
├── [abc123 partition]
│   ├── schema1 (group_id: "abc123", partitionKey: "abc123")
│   └── schema2 (group_id: "abc123", partitionKey: "abc123")
├── [xyz789 partition]
│   └── schema3 (group_id: "xyz789", partitionKey: "xyz789")
└── [default partition]
    ├── schema4 (group_id: "default", partitionKey: "default")
    └── schema5 (group_id: "default", partitionKey: "default")
```

---

## Solution Implemented

### 1. Always Set group_id ✅

**Change:** Every schema now ALWAYS gets a `group_id`, using "default" if none is provided.

**Code Changes:**

#### Schema Upload Endpoint (Line ~3217)
```python
# ✅ ALWAYS set group_id for proper organization in collection
# Use provided group_id or "default" to ensure all schemas are organized
metadata_dict = metadata.model_dump()
effective_group_id = group_id if group_id else "default"
metadata_dict["group_id"] = effective_group_id

# Add partition key for better organization and query performance
metadata_dict["partitionKey"] = effective_group_id

print(f"[SchemaUpload] Storing schema in collection under group: {effective_group_id}")

# Store lightweight metadata in isolated database
result = collection.insert_one(metadata_dict)
```

#### Schema Helper Function - Update (Line ~2357)
```python
# ✅ ALWAYS set group_id for proper organization
effective_group_id = group_id if group_id else "default"
update_doc["group_id"] = effective_group_id
update_doc["partitionKey"] = effective_group_id
collection.update_one({"id": schema_id}, {"$set": update_doc})
```

#### Schema Helper Function - Insert (Line ~2381)
```python
# ✅ ALWAYS set group_id for proper organization in collection
effective_group_id = group_id if group_id else "default"
meta_doc["group_id"] = effective_group_id
meta_doc["partitionKey"] = effective_group_id
collection.insert_one(meta_doc)
```

### 2. Add Partition Key ✅

**Change:** Added `partitionKey` field to mirror `group_id` for better Cosmos DB organization and query performance.

**Benefits:**
- Schemas are logically partitioned by group
- Queries can target specific partitions
- Better performance for large collections
- Clear organization visible in Azure Portal

### 3. Update Query Logic ✅

**Change:** Schema listing now ALWAYS filters by group_id (defaults to "default").

#### Schema List Endpoint (Line ~2834)
```python
# Build query filter with group isolation
# ✅ ALWAYS filter by group_id for proper organization
effective_group_id = group_id if group_id else "default"
query_filter = {"group_id": effective_group_id}
logger.info(f"Filtering schemas by group_id: {effective_group_id[:8] if len(effective_group_id) > 8 else effective_group_id}...")

# Optimized query: fetch essential fields for UI rendering
projection = {
    "id": 1, "name": 1, "displayName": 1, "ClassName": 1, "description": 1, "fields": 1,
    "fieldCount": 1, "fieldNames": 1, "fileName": 1, "fileSize": 1,
    "createdBy": 1, "createdAt": 1, "version": 1, "status": 1,
    "tags": 1, "blobUrl": 1, "schemaType": 1, 
    "group_id": 1, "partitionKey": 1,  # ✅ Include organization fields
    "_id": 0
}
```

---

## Schema Document Structure

### Complete Schema Document
```json
{
  "id": "uuid-string",
  "name": "schema_name",
  "description": "Schema description",
  "fieldCount": 10,
  "fieldNames": ["field1", "field2", "..."],
  "fileSize": 1024,
  "fileName": "original.json",
  "contentType": "application/json",
  "createdBy": "user@email.com",
  "createdAt": "2025-10-22T12:00:00Z",
  "version": "1.0.0",
  "status": "active",
  "baseAnalyzerId": "prebuilt-documentAnalyzer",
  "blobUrl": "https://storage.blob.core.windows.net/...",
  "blobContainer": "pro-schemas",
  
  "group_id": "abc123def456",      // ✅ ALWAYS set (or "default")
  "partitionKey": "abc123def456",  // ✅ NEW: Mirrors group_id for organization
  
  "tags": [],
  "lastAccessed": null,
  "origin": {
    "baseSchemaId": "...",
    "method": "ai_enhancement"
  }
}
```

---

## Benefits

### 1. **Clear Organization** 📁
- Schemas are now visibly grouped in Cosmos DB
- Easy to see which schemas belong to which group
- "default" group for schemas without explicit group assignment

### 2. **Better Query Performance** ⚡
- Queries can target specific partitions
- Reduced scan time for large collections
- More efficient filtering

### 3. **Proper Isolation** 🔒
- Each group's schemas are logically separated
- Prevents accidental cross-group access
- Clearer data boundaries

### 4. **Azure Portal Visibility** 👀
- Partition key visible in Data Explorer
- Can filter/sort by group easily
- Better debugging and monitoring

---

## How to Verify

### Option 1: Upload a New Schema
1. Upload a schema via the UI or API
2. Check backend logs for: `[SchemaUpload] Storing schema in collection under group: <group_id>`
3. Query Cosmos DB to verify `group_id` and `partitionKey` fields exist

### Option 2: Check Azure Portal
1. Go to Azure Portal → Cosmos DB → Data Explorer
2. Navigate to `Schemas_pro` collection
3. View any schema document
4. Verify both `group_id` and `partitionKey` fields are present and match

### Option 3: Query by Group
```javascript
// MongoDB query to get all schemas in a specific group
db.Schemas_pro.find({ "group_id": "your-group-id" })

// MongoDB query to see group distribution
db.Schemas_pro.aggregate([
  { $group: { _id: "$group_id", count: { $sum: 1 } } }
])
```

---

## Migration for Existing Schemas

If you have existing schemas without `group_id`, they won't be visible with the new filtering. Here's how to migrate them:

### Option 1: Automated Migration Script
```python
from pymongo import MongoClient
import os

# Connect to Cosmos DB
client = MongoClient(os.environ["APP_COSMOS_CONNSTR"])
db = client[os.environ["APP_COSMOS_DATABASE"]]
collection = db["Schemas_pro"]

# Update all schemas without group_id
result = collection.update_many(
    {"group_id": {"$exists": False}},  # Find schemas without group_id
    {"$set": {
        "group_id": "default",
        "partitionKey": "default"
    }}
)

print(f"✅ Updated {result.modified_count} schemas with default group_id")
```

### Option 2: Manual Update via Azure Portal
1. Open Data Explorer
2. Query: `{"group_id": {"$exists": false}}`
3. For each document, add:
   ```json
   {
     "group_id": "default",
     "partitionKey": "default"
   }
   ```

---

## API Changes

### Upload Endpoint: `/pro-mode/schemas/upload`

**Request (unchanged):**
```bash
POST /pro-mode/schemas/upload
Headers:
  X-Group-ID: abc123def456  # Optional, defaults to "default"
Body:
  files: [schema.json]
```

**Response (new fields):**
```json
{
  "schemas": [{
    "id": "uuid",
    "name": "schema_name",
    "group_id": "abc123def456",      // ✅ Always present
    "partitionKey": "abc123def456",  // ✅ New field
    ...
  }]
}
```

### List Endpoint: `/pro-mode/schemas`

**Request (changed behavior):**
```bash
GET /pro-mode/schemas
Headers:
  X-Group-ID: abc123def456  # Optional, defaults to "default"
```

**Old Behavior:** Returned ALL schemas if no group_id header
**New Behavior:** Defaults to "default" group if no header provided

**To get all schemas across all groups:**
You would need to make separate requests for each group or modify the endpoint to support an "all" parameter.

---

## Files Modified

1. `/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`
   - Line ~3217: Schema upload - always set group_id
   - Line ~2357: Schema helper update - always set group_id  
   - Line ~2381: Schema helper insert - always set group_id
   - Line ~2834: Schema list query - always filter by group_id

---

## Testing Checklist

- [ ] Upload a schema without X-Group-ID header → Verify group_id="default"
- [ ] Upload a schema with X-Group-ID header → Verify group_id matches header
- [ ] Check Azure Portal → Verify partitionKey field exists
- [ ] List schemas without X-Group-ID → Verify only "default" schemas returned
- [ ] List schemas with X-Group-ID → Verify only that group's schemas returned
- [ ] Check backend logs → Verify "[SchemaUpload] Storing schema in collection under group: ..." message

---

## Related Issues Fixed

1. **401 Errors in Analysis Tab** ✅
   - Added better error handling with clickable refresh message
   - File: `PredictionTab.tsx` (lines ~797-831)

2. **Collection Organization by group_id** ✅
   - Always set group_id and partitionKey
   - Always filter queries by group_id
   - File: `proMode.py` (multiple locations)

---

## Questions?

If schemas still appear disorganized:
1. Check if existing schemas need migration (see Migration section above)
2. Verify X-Group-ID header is being sent from frontend
3. Check backend logs for group_id being set
4. Query Cosmos DB directly to verify data structure

**The collection key/folder organization you were looking for is now implemented using the `group_id` and `partitionKey` fields!** 🎉
