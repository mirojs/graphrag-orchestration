# Storage Architecture Analysis: Group-First vs Resource-First

**Date**: October 23, 2025  
**Context**: Evaluating whether to restructure storage to group-first pattern

## Current Architecture (Resource-First)

### Cosmos DB Structure
```
Database: ContentProcessorDB
├── Collections (by resource type):
│   ├── cases_pro
│   │   └── Partition Key: group_id
│   ├── schemas_pro  
│   │   └── Partition Key: group_id
│   └── analyzers_pro
│       └── Partition Key: group_id
```

**Pattern**: One collection per resource type, partitioned by `group_id`

### Blob Storage Structure
```
Storage Account
├── Containers (mixed patterns):
│   ├── pro-input-files (SHARED, uses virtual folders)
│   ├── pro-reference-files (SHARED, uses virtual folders)
│   ├── pro-schemas-{config} (SHARED, uses schema_id folders)
│   ├── analysis-results-{group_id} (PER GROUP)
│   └── analyzers-{group_id} (PER GROUP)
```

**Pattern**: Mixed approach
- Input/reference files: Shared container with virtual folders (`{group_id}/blob_name`)
- Analysis results/analyzers: Separate container per group
- Schemas: Shared container with schema_id folders (no group isolation in container name)

## Proposed Architecture (Group-First)

### Cosmos DB Structure
```
Database: ContentProcessorDB
├── Collections (by group):
│   ├── group-{sanitized_group_id}
│   │   └── Partition Key: resource_type
│   │       ├── "case"
│   │       ├── "schema"
│   │       └── "analyzer"
│   └── group-default
│       └── Partition Key: resource_type
```

**Pattern**: One collection per group, partitioned by `resource_type`

### Blob Storage Structure
```
Storage Account
├── Containers (by group):
│   ├── group-{sanitized_group_id}
│   │   ├── input-files/
│   │   ├── reference-files/
│   │   ├── schemas/{schema_id}/
│   │   ├── analyzers/{analyzer_id}/
│   │   └── analysis-results/{analysis_id}/
│   └── group-default
│       ├── input-files/
│       ├── reference-files/
│       └── schemas/
```

**Pattern**: One container per group with subdirectories for resource types

---

## Comparison Matrix

| Aspect | **Current (Resource-First)** | **Proposed (Group-First)** |
|--------|------------------------------|----------------------------|
| **Cosmos DB Collections** | 3 fixed (cases_pro, schemas_pro, analyzers_pro) | N collections (1 per group) |
| **Cosmos Partition Key** | `group_id` (perfect for group queries) | `resource_type` (less ideal for group queries) |
| **Blob Containers** | Mixed: Shared + per-group | N containers (1 per group) |
| **Cross-group queries** | Easy (partition key = group_id) | Harder (need to query multiple collections) |
| **List all schemas** | Easy (1 collection) | Harder (query all group collections) |
| **Group deletion** | Delete docs in 3 collections | Delete 1 collection + 1 container |
| **Runtime container creation** | ❌ Not needed for Cosmos (fixed 3)<br>✅ Needed for some blob containers | ✅ Required for both Cosmos & Blob |
| **Cosmos scalability** | ✅ Excellent (partition key = group_id) | ⚠️ Less optimal (partition key = resource_type) |
| **Blob organization** | ⚠️ Inconsistent (mixed patterns) | ✅ Consistent (all in group container) |
| **Group isolation** | ✅ Strong (partition key + some containers) | ✅ Very strong (collection + container per group) |
| **Initial setup** | Simple (3 collections pre-created) | Complex (collections created on-demand) |
| **Migration complexity** | N/A (current state) | 🔴 Very high |

---

## Deep Dive: Cosmos DB Partition Key Impact

### Current: Partition Key = `group_id`

**✅ Advantages:**
```javascript
// Fast: Queries one partition
collection.find({ group_id: "test-group" })  

// Fast: Cross-resource query within a group
collection.find({ 
  group_id: "test-group",
  resource_type: { $in: ["schema", "analyzer"] }
})
```

**❌ Disadvantages:**
- Each resource type needs its own collection (can't mix)
- More collections to manage (3 vs potentially hundreds)

### Proposed: Partition Key = `resource_type`

**✅ Advantages:**
- All group data in one collection
- Easier group deletion (drop collection)
- Cleaner conceptual model ("one group = one collection")

**❌ Disadvantages:**
```javascript
// INEFFICIENT: Queries ALL partitions (schema, analyzer, case)
collection.find({ group_id: "test-group" })

// Better but still queries across partitions
collection.find({ 
  group_id: "test-group",
  resource_type: "schema"  // At least limits to 1 partition
})
```

**⚠️ Performance Impact:**
- Cosmos DB optimizes for queries WITHIN a partition
- Queries across partitions (e.g., "get all resources for group X") are slower and more expensive
- RU (Request Unit) cost increases significantly for cross-partition queries

---

## Deep Dive: Runtime Collection/Container Creation

### Current State

**Cosmos DB:**
- ✅ Collections are PRE-CREATED: `cases_pro`, `schemas_pro`, `analyzers_pro`
- ❌ No runtime creation needed

**Blob Storage:**
- ✅ Some containers are PRE-CREATED: `pro-input-files`, `pro-reference-files`, `pro-schemas-{config}`
- ✅ Some containers are CREATED AT RUNTIME: `analysis-results-{group_id}`, `analyzers-{group_id}`

**Current Code for Runtime Container Creation:**
```python
# In proMode.py ~line 8938 (analysis results)
container_name = f"analysis-results-{safe_group}"
storage_helper = StorageBlobHelper(app_config.app_storage_blob_url, container_name)
storage_helper.upload_blob(blob_name, result_bytes)  # Auto-creates container if missing

# In proMode.py ~line 9117 (analyzers)
analyzer_container = f"analyzers-{safe_group}"
storage_helper = StorageBlobHelper(app_config.app_storage_blob_url, analyzer_container)
storage_helper.upload_blob(blob_name, analyzer_json_bytes)  # Auto-creates container
```

**How it works:**
- `StorageBlobHelper.upload_blob()` likely has auto-create logic
- Or Azure Blob Storage auto-creates containers on first write (if permissions allow)

### Proposed State (Group-First)

**Cosmos DB:**
- ❌ Collections are NOT PRE-CREATED
- ✅ **MUST CREATE AT RUNTIME** when first group resource is saved

**Required Code:**
```python
def ensure_group_collection(db, group_id: str) -> Collection:
    """Create group collection if it doesn't exist."""
    collection_name = f"group-{sanitize_group_id(group_id)}"
    
    # Check if collection exists
    if collection_name not in db.list_collection_names():
        # Create with partition key = resource_type
        db.create_collection(
            collection_name,
            partition_key_definition={
                "paths": ["/resource_type"],
                "kind": "Hash"
            }
        )
        print(f"[CosmosDB] Created collection: {collection_name}")
    
    return db[collection_name]

# Usage in every endpoint:
collection = ensure_group_collection(db, effective_group_id)
collection.insert_one({
    "resource_type": "schema",  # Partition key
    "group_id": effective_group_id,
    "name": "PurchaseOrder",
    # ... rest of schema
})
```

**Blob Storage:**
- Same as current: Auto-create on first upload or explicit check

```python
def ensure_group_container(storage_helper, group_id: str) -> str:
    """Create group container if it doesn't exist."""
    container_name = f"group-{sanitize_group_id(group_id)}"
    
    # StorageBlobHelper likely handles this, but explicit:
    container_client = storage_helper._get_container_client()
    if not container_client.exists():
        container_client.create_container()
        print(f"[BlobStorage] Created container: {container_name}")
    
    return container_name
```

---

## Migration Complexity

### If We Switch to Group-First

**Cosmos DB Migration:**
1. For each existing collection (cases_pro, schemas_pro, analyzers_pro):
   - Query all documents
   - Group by `group_id`
   - For each group:
     - Create new collection: `group-{group_id}`
     - Insert documents with `resource_type` field
2. Update all code references to use new collection pattern
3. Drop old collections (after verification)

**Estimated Documents to Migrate:** Potentially thousands (depending on usage)

**Blob Storage Migration:**
1. **Input/Reference Files:**
   ```
   FROM: pro-input-files/{group_id}/{blob}
   TO:   group-{group_id}/input-files/{blob}
   ```
   - Need to iterate all blobs, parse group_id from path, move to new container

2. **Analysis Results:**
   ```
   FROM: analysis-results-{group_id}/{blob}
   TO:   group-{group_id}/analysis-results/{blob}
   ```
   - Rename containers (if possible) or copy blobs

3. **Analyzers:**
   ```
   FROM: analyzers-{group_id}/{blob}
   TO:   group-{group_id}/analyzers/{blob}
   ```
   - Same: rename or copy

4. **Schemas:**
   ```
   FROM: pro-schemas-{config}/{schema_id}/{blob}
   TO:   group-{group_id}/schemas/{schema_id}/{blob}
   ```
   - ⚠️ **PROBLEM**: No group_id in current schema path! 
   - Would need to query Cosmos to map schema_id → group_id
   - Very complex

**Estimated Blobs to Migrate:** Potentially tens of thousands

**Downtime Required:** Yes, significant (hours to days depending on data volume)

---

## Code Changes Required

### Group-First Architecture Needs

**1. Dynamic Collection/Container Management**

Every endpoint that writes to Cosmos or Blob needs:
```python
# Before EVERY operation
collection = ensure_group_collection(db, group_id)
container = ensure_group_container(storage, group_id)
```

Impacted endpoints: ~40+ in proMode.py

**2. Cross-Group Queries**

Current (easy):
```python
# List all schemas
collection = db["schemas_pro"]
schemas = collection.find({ "group_id": group_id })  # Single partition query
```

Proposed (harder):
```python
# List all schemas - must query EVERY group collection!
all_groups = get_all_group_ids()  # How do we even get this list?
all_schemas = []
for group_id in all_groups:
    collection = db[f"group-{group_id}"]
    schemas = collection.find({ "resource_type": "schema" })  # Cross-partition query!
    all_schemas.extend(schemas)
```

**3. Group Discovery**

New problem: How to list all groups?
- Current: Query `group_id` field in any collection
- Proposed: List all Cosmos collections? (expensive, not designed for this)
- Solution: Need a METADATA collection to track groups

```python
# New collection needed
db.groups_metadata.insert_one({
    "group_id": "test-group",
    "created_at": datetime.now(),
    "collection_name": "group-testgroup",
    "container_name": "group-testgroup"
})
```

**4. Container Name Conflicts**

Azure Blob container names: 3-63 characters, lowercase, alphanumeric + hyphens

```python
# Current sanitization
safe_group = re.sub(r'[^a-z0-9-]', '', group_id.lower())[:24]
container = f"analyzers-{safe_group}"  # Prefix makes it unique

# Proposed problem
container = f"group-{safe_group}"  # ALL groups share same prefix pattern
```

Need robust collision detection!

---

## Recommendations

### 🟢 Keep Current Architecture (Resource-First)

**Reasoning:**

1. **Cosmos DB Partition Key is Optimal**
   - `group_id` as partition key = best performance for group queries
   - Changing to `resource_type` partition key = worse performance, higher costs

2. **No Migration Complexity**
   - Current system works
   - Proven in production
   - No downtime needed

3. **Collections Already Created**
   - No runtime collection creation complexity
   - Easier infrastructure management
   - Predictable costs

4. **Simpler Code**
   - Fixed collection names
   - No dynamic creation logic
   - Fewer error cases

5. **Better Cross-Group Analytics**
   - Easy to query "all schemas" or "all analyzers"
   - Single collection = simpler aggregations

### 🟡 Improve Blob Storage Consistency (Minor Refactor)

**What to Fix:**
Current blob storage is inconsistent. Standardize to ONE pattern:

**Option A: All Shared Containers with Virtual Folders (Recommended)**
```
pro-input-files/{group_id}/{blob}
pro-reference-files/{group_id}/{blob}
pro-schemas/{group_id}/{schema_id}/{blob}
pro-analyzers/{group_id}/{analyzer_id}/{blob}
pro-analysis-results/{group_id}/{analysis_id}/{blob}
```

**Benefits:**
- ✅ Consistent pattern everywhere
- ✅ No runtime container creation needed
- ✅ Easier to pre-create containers in infrastructure
- ✅ Better container-level access control (e.g., reference files public, analyzers private)
- ✅ Easier monitoring (fixed set of containers)

**Option B: All Per-Group Containers**
```
schemas-{group_id}/{schema_id}/{blob}
analyzers-{group_id}/{analyzer_id}/{blob}
analysis-results-{group_id}/{analysis_id}/{blob}
input-files-{group_id}/{blob}
reference-files-{group_id}/{blob}
```

**Benefits:**
- ✅ Strongest group isolation (container level)
- ✅ Easy group deletion (drop all group containers)
- ⚠️ Need runtime creation for ALL containers
- ⚠️ More containers to manage (5 x N groups)

**Recommendation:** **Option A** (shared containers with virtual folders)

---

## Implementation: Blob Storage Standardization (Option A)

### Changes Needed

**1. Update Input/Reference Files (Already Using Virtual Folders)**
- ✅ No changes needed! Already using pattern: `{group_id}/blob_name`

**2. Update Schemas (Currently: `pro-schemas-{config}/{schema_id}/blob`)**

Change from:
```python
container = f"pro-schemas-{app_config.app_cps_configuration}"
blob_name = f"{schema_id}/{filename}"
```

To:
```python
container = "pro-schemas"  # Fixed container
blob_name = f"{group_id}/{schema_id}/{filename}"
```

**3. Update Analyzers (Currently: `analyzers-{group_id}/blob`)**

Change from:
```python
container = f"analyzers-{group_id}"
blob_name = f"analyzer_{analyzer_id}_{timestamp}.json"
```

To:
```python
container = "pro-analyzers"  # Fixed container
blob_name = f"{group_id}/analyzer_{analyzer_id}_{timestamp}.json"
```

**4. Update Analysis Results (Currently: `analysis-results-{group_id}/blob`)**

Change from:
```python
container = f"analysis-results-{group_id}"
blob_name = f"analysis_result_{analyzer_id}_{timestamp}.json"
```

To:
```python
container = "pro-analysis-results"  # Fixed container
blob_name = f"{group_id}/analysis_result_{analyzer_id}_{timestamp}.json"
```

### Migration Script (Blob Standardization)

```python
# migrate_blob_containers_to_virtual_folders.py

from azure.storage.blob import BlobServiceClient
import re

MIGRATIONS = [
    {
        "from_pattern": "analyzers-{group_id}",
        "to_container": "pro-analyzers",
        "to_path": "{group_id}/{blob_name}"
    },
    {
        "from_pattern": "analysis-results-{group_id}",
        "to_container": "pro-analysis-results",
        "to_path": "{group_id}/{blob_name}"
    },
    {
        "from_pattern": "pro-schemas-{config}",  # Need to map schema → group
        "to_container": "pro-schemas",
        "to_path": "{group_id}/{schema_id}/{blob_name}"
    }
]

def migrate_containers(blob_service_client):
    # List all containers
    containers = blob_service_client.list_containers()
    
    for container in containers:
        for migration in MIGRATIONS:
            # Check if container matches pattern
            pattern = migration["from_pattern"]
            # ... migration logic
```

**Complexity:** Medium (need to handle schema group mapping)

---

## Final Recommendation

### ✅ DO THIS:

1. **Keep Cosmos DB as-is (Resource-First with group_id partition)**
   - Optimal performance
   - No migration
   - Proven pattern

2. **Standardize Blob Storage to Virtual Folders**
   - Migrate to: All shared containers with `{group_id}/` prefixes
   - More consistent
   - Easier management
   - Moderate migration effort

### ❌ DON'T DO THIS:

1. **Don't switch to Group-First Cosmos DB**
   - Worse performance (wrong partition key)
   - High migration complexity
   - Adds runtime collection creation complexity
   - Harder cross-group queries

---

## Summary

Your instinct about putting `group_id` as the container/collection name is interesting for **conceptual clarity** (one group = one place), but in practice:

**Cosmos DB:**
- **Current `group_id` as partition key** = ✅ Perfect for performance
- **Proposed `group_id` as collection name** = ❌ Worse performance (wrong partition key)

**Blob Storage:**
- **Current mixed pattern** = ⚠️ Inconsistent
- **Proposed group containers** = ✅ Clean but complex
- **Better: Virtual folders in shared containers** = ✅ Best of both worlds

The current architecture is actually **mostly correct** for Cosmos DB! The only thing to improve is **blob storage consistency** by standardizing to virtual folders.

Would you like me to implement the blob storage standardization (Option A)?
