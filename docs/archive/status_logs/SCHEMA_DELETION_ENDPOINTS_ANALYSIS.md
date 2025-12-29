# Schema Deletion Endpoints Analysis

## Date: October 10, 2025

## Question: Why do we have 2 kinds of deletion endpoints?

**Answer:** We have **TWO DIFFERENT deletion endpoints** for **DIFFERENT use cases**:

1. **Single Schema Deletion** - For deleting one schema at a time
2. **Bulk Schema Deletion** - For deleting multiple schemas concurrently

---

## Endpoint Details

### 1. Single Schema Deletion (Individual Delete)

**Endpoint:** `DELETE /pro-mode/schemas/{schema_id}`  
**Function:** `delete_pro_schema()`  
**Location:** `proMode.py` line 3108  
**Used by Frontend:** ✅ YES

#### Frontend Usage:
```typescript
// schemaService.ts line 364
async deleteSchema(schemaId: string): Promise<void> {
  await httpUtility.delete(`${SCHEMA_ENDPOINTS.DELETE}/${schemaId}`);
}

// SchemaTab.tsx line 849
await schemaService.deleteSchema(selectedSchema.id);
```

#### Use Case:
- User clicks "Delete" button on a single schema
- Delete dialog for one schema
- Quick single-item deletion

#### Features:
- ✅ Deletes from Cosmos DB
- ✅ Deletes from Azure Blob Storage
- ✅ Query parameter: `cleanup_blob` (default: `true`)
- ✅ Returns detailed status for single schema
- ✅ Graceful error handling

#### Request:
```http
DELETE /pro-mode/schemas/abc-123-def?cleanup_blob=true
```

#### Response:
```json
{
  "status": "deleted",
  "message": "Schema 'INVOICE_SCHEMA' deleted successfully",
  "schemaId": "abc-123-def",
  "cleanup": {
    "cosmosDb": "deleted",
    "azureStorage": "deleted"
  }
}
```

---

### 2. Bulk Schema Deletion (Multiple Delete)

**Endpoint:** `POST /pro-mode/schemas/bulk-delete`  
**Function:** `bulk_delete_schemas()`  
**Location:** `proMode.py` line 8825  
**Used by Frontend:** ✅ YES (available but may not be actively used in UI)

#### Frontend Service:
```typescript
// schemaService.ts line 383
async bulkDeleteSchemas(schemaIds: string[]): Promise<void> {
  await httpUtility.post(SCHEMA_ENDPOINTS.BULK_DELETE, { schemaIds });
}
```

#### Use Case:
- Delete multiple schemas at once
- Batch cleanup operations
- Administrative bulk operations
- Future feature: Multi-select delete in UI

#### Features:
- ✅ Deletes from Cosmos DB (all schemas)
- ✅ Deletes from Azure Blob Storage (all blobs)
- ✅ Request body parameter: `cleanupBlobs` (default: `true`)
- ✅ Concurrent processing (ThreadPoolExecutor, max 10 workers)
- ✅ Per-schema status tracking
- ✅ Rate limiting: Max 50 schemas per request
- ✅ Continues even if individual deletions fail

#### Request:
```http
POST /pro-mode/schemas/bulk-delete
Content-Type: application/json

{
  "schemaIds": ["id1", "id2", "id3"],
  "cleanupBlobs": true
}
```

#### Response:
```json
{
  "message": "Bulk deletion completed: 2 successful, 1 failed",
  "deletedCount": 2,
  "dualStorageCleanup": true,
  "results": {
    "total": 3,
    "successful": 2,
    "failed": 1,
    "successDetails": [
      {
        "id": "id1",
        "cosmosDb": "deleted",
        "azureStorage": "deleted"
      },
      {
        "id": "id2",
        "cosmosDb": "deleted",
        "azureStorage": "no_blob"
      }
    ],
    "failures": [
      {
        "id": "id3",
        "error": "Schema not found"
      }
    ]
  }
}
```

---

## Comparison Table

| Feature | Single Delete | Bulk Delete |
|---------|--------------|-------------|
| **Endpoint** | `DELETE /pro-mode/schemas/{id}` | `POST /pro-mode/schemas/bulk-delete` |
| **HTTP Method** | DELETE | POST |
| **Schema ID** | Path parameter | Request body array |
| **Max Schemas** | 1 | 50 |
| **Concurrent Processing** | N/A | Yes (10 workers) |
| **Cosmos DB Cleanup** | ✅ Yes | ✅ Yes |
| **Blob Storage Cleanup** | ✅ Yes | ✅ Yes |
| **Configurable Cleanup** | `cleanup_blob` param | `cleanupBlobs` body |
| **Error Handling** | Fail-fast | Continues on error |
| **Response Detail** | Single status | Per-schema status |
| **Rate Limiting** | None | Max 50 schemas |
| **Used in UI** | ✅ Yes (active) | ⚠️ Available (not in UI yet) |

---

## Should We Delete One?

### ❌ **NO - Both Endpoints Are Needed**

**Reasons to keep both:**

### 1. **Different REST Semantics**
- **Single Delete**: RESTful `DELETE /resource/{id}` pattern
- **Bulk Delete**: Batch operation requiring `POST` with body

### 2. **Different Use Cases**
- **Single Delete**: User interaction (delete button on one schema)
- **Bulk Delete**: Administrative operations, future multi-select feature

### 3. **Different Performance Characteristics**
- **Single Delete**: Fast, synchronous, immediate response
- **Bulk Delete**: Concurrent, asynchronous, detailed status tracking

### 4. **Frontend Already Uses Single Delete**
```typescript
// SchemaTab.tsx line 849
await schemaService.deleteSchema(selectedSchema.id);
```

### 5. **Both Have Dual Storage Cleanup**
- Both properly delete from Cosmos DB and Azure Blob Storage
- Both have configurable blob cleanup
- Both handle errors gracefully

### 6. **Bulk Delete Is Future-Proof**
The bulk delete endpoint enables future features like:
- Multi-select checkbox in schema list
- "Delete All" functionality
- Cleanup scripts for administrators
- Automated maintenance tasks

---

## Current Frontend Usage

### Active Usage:
```typescript
// SchemaTab.tsx - Single Delete Flow
const handleDeleteSchemas = useCallback(async () => {
  if (selectedSchema) {
    await schemaService.deleteSchema(selectedSchema.id); // ← Uses single delete
    
    // Update UI
    updateUiState({ showDeleteDialog: false, schemasToDelete: [] });
    
    // Refresh schema list
    const updatedSchemas = await schemaService.getSchemas();
    dispatch(setSchemas(updatedSchemas));
  }
}, [selectedSchema]);
```

### Available But Not Used:
```typescript
// schemaService.ts - Bulk Delete Available
async bulkDeleteSchemas(schemaIds: string[]): Promise<void> {
  await httpUtility.post(SCHEMA_ENDPOINTS.BULK_DELETE, { schemaIds });
}
// ⚠️ Not currently called from UI
```

---

## Recommendations

### ✅ **Keep Both Endpoints**

**Single Delete (`DELETE /pro-mode/schemas/{id}`):**
- ✅ Keep - Currently used in UI
- ✅ RESTful pattern
- ✅ User-facing feature

**Bulk Delete (`POST /pro-mode/schemas/bulk-delete`):**
- ✅ Keep - Future-proof for multi-select
- ✅ Administrative operations
- ✅ Better performance for multiple deletions

### 💡 **Future Enhancement: Add Multi-Select UI**

Consider adding multi-select functionality to SchemaTab:

```typescript
// Future enhancement example
const handleBulkDelete = async () => {
  const selectedIds = schemas
    .filter(s => s.selected)
    .map(s => s.id);
  
  if (selectedIds.length > 0) {
    await schemaService.bulkDeleteSchemas(selectedIds); // ← Use bulk endpoint
    // Refresh list
  }
};
```

### 📋 **Endpoint Naming Clarity**

Both endpoints are clearly named:
- `DELETE /pro-mode/schemas/{schema_id}` - Obvious single delete
- `POST /pro-mode/schemas/bulk-delete` - Obvious bulk delete

No confusion or ambiguity.

---

## Architecture Consistency

Both endpoints follow the same dual storage cleanup pattern:

```python
# Single Delete
def delete_pro_schema(schema_id: str, cleanup_blob: bool = True):
    # 1. Delete from Cosmos DB
    collection.delete_one({"id": schema_id})
    
    # 2. Delete from Azure Storage
    if cleanup_blob and blob_url:
        blob_helper.delete_schema_blob(blob_url)

# Bulk Delete
def bulk_delete_schemas(request: Dict):
    for schema_id in schema_ids:
        # 1. Delete from Cosmos DB
        collection.delete_one({"id": schema_id})
        
        # 2. Delete from Azure Storage
        if cleanup_blobs and blob_url:
            blob_helper.delete_schema_blob(blob_url)
```

✅ **Consistent dual storage cleanup across both endpoints**

---

## Testing Both Endpoints

### Test Single Delete:
```bash
# Test single schema deletion
curl -X DELETE "http://localhost:8000/pro-mode/schemas/abc-123" \
  -H "Authorization: Bearer $TOKEN"
```

### Test Bulk Delete:
```bash
# Test bulk schema deletion
curl -X POST "http://localhost:8000/pro-mode/schemas/bulk-delete" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "schemaIds": ["id1", "id2", "id3"],
    "cleanupBlobs": true
  }'
```

---

## Conclusion

### ✅ **Both Deletion Endpoints Are Valid and Necessary**

| Endpoint | Purpose | Status | Action |
|----------|---------|--------|--------|
| Single Delete | User-facing one-at-a-time deletion | ✅ Active in UI | **Keep** |
| Bulk Delete | Batch operations, future multi-select | ⚠️ Available but not used | **Keep for future** |

**Recommendation:** 
- ✅ **Keep both endpoints**
- ✅ Both properly handle dual storage cleanup
- ✅ No duplication or conflict
- ✅ Serves different use cases
- ✅ Future-proof for multi-select feature

---

**Status:** ✅ Analysis complete - Both endpoints are necessary  
**Action Required:** None - Keep both endpoints as-is  
**Future Enhancement:** Consider adding multi-select UI to utilize bulk delete
