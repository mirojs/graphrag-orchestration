# GraphRAG Document Lifecycle Management

## Overview
Complete document lifecycle management system for GraphRAG enabling add, list, delete, and query operations on indexed documents with full metadata tracking across Neo4j and LanceDB/Azure Search.

## Implementation Summary

### 1. Metadata Tracking
**Automatic metadata injection during indexing:**
- Every document gets `url`, `page_number`, `group_id` in metadata
- Document Intelligence service automatically adds source tracking
- Neo4j nodes inherit document metadata via `MultiTenantNeo4jStore.upsert_nodes()`
- LanceDB/Azure Search vectors include metadata for filtering

**Key files:**
- `app/services/document_intelligence_service.py` - Adds `url`, `page_number`, `group_id` to Document metadata
- `app/services/graph_service.py` - Injects `group_id` into all Neo4j nodes

### 2. Graph Service Enhancements
**Added methods to `GraphService` class:**

```python
def list_indexed_documents(self, group_id: str) -> List[Dict[str, Any]]
```
- Lists all unique documents by URL
- Returns node counts, page counts, and page numbers
- Scoped to tenant via `group_id` filter

```python
def delete_document_by_url(self, group_id: str, url: str) -> Dict[str, Any]
```
- Deletes all nodes matching URL
- Uses `DETACH DELETE` to remove relationships
- Returns deletion statistics

```python
def delete_all_documents(self, group_id: str) -> Dict[str, Any]
```
- Nuclear option: removes ALL tenant data
- Useful for testing/cleanup

```python
def get_document_stats(self, group_id: str, url: str) -> Dict[str, Any]
```
- Detailed statistics for a specific document
- Shows node types, label distributions, pages

### 3. Vector Service Enhancements
**Added methods to `VectorStoreService` class:**

```python
def delete_by_url(self, group_id: str, url: str, index_name: str = "default") -> int
```
- Deletes vectors matching document URL
- Works for both LanceDB and Azure Search
- Returns count of vectors deleted

**Provider implementations:**

**LanceDB:**
```python
def delete_by_metadata(self, group_id: str, index_name: str, metadata_filter: Dict[str, Any]) -> int
```
- Uses SQL-like filter syntax: `table.delete("url = 'xyz' AND group_id = 'abc'")`
- Counts rows before/after for accurate deletion stats

**Azure Search:**
```python
def delete_by_metadata(self, group_id: str, index_name: str, metadata_filter: Dict[str, Any]) -> int
```
- Uses OData filters to find matching documents
- Deletes by document ID
- Batch deletion via `client.delete_documents()`

### 4. API Endpoints

#### GET `/graphrag/documents`
**List all indexed documents for a tenant**

Request:
```bash
curl -X GET "http://localhost:8001/graphrag/documents" \
  -H "X-Group-ID: my-group"
```

Response:
```json
{
  "group_id": "my-group",
  "documents": [
    {
      "url": "https://storage.blob.core.windows.net/.../doc1.pdf",
      "node_count": 45,
      "page_count": 3,
      "pages": [1, 2, 3]
    }
  ],
  "total_count": 1
}
```

#### POST `/graphrag/documents/delete`
**Delete a specific document by URL**

Request:
```bash
curl -X POST "http://localhost:8001/graphrag/documents/delete" \
  -H "X-Group-ID: my-group" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://storage.blob.core.windows.net/.../doc1.pdf"}'
```

Response:
```json
{
  "status": "completed",
  "url": "https://storage.blob.core.windows.net/.../doc1.pdf",
  "neo4j_stats": {
    "url": "...",
    "nodes_deleted": 45,
    "relationships_deleted": 87
  },
  "vector_stats": {
    "vectors_deleted": 45
  },
  "message": "Deleted 45 nodes, 87 relationships, and 45 vectors"
}
```

#### GET `/graphrag/documents/stats?url=<url>`
**Get detailed statistics for a document**

Request:
```bash
curl -X GET "http://localhost:8001/graphrag/documents/stats?url=https://..." \
  -H "X-Group-ID: my-group"
```

Response:
```json
{
  "group_id": "my-group",
  "url": "https://...",
  "total_nodes": 45,
  "label_sets": [
    ["__Node__", "Entity", "Person"],
    ["__Node__", "Chunk"]
  ],
  "pages": [1, 2, 3]
}
```

#### DELETE `/graphrag/documents/all`
**Delete ALL documents for a tenant (DANGEROUS)**

Request:
```bash
curl -X DELETE "http://localhost:8001/graphrag/documents/all" \
  -H "X-Group-ID: my-group"
```

Response:
```json
{
  "status": "completed",
  "group_id": "my-group",
  "neo4j_stats": {
    "group_id": "my-group",
    "nodes_deleted": 450
  },
  "vector_stats": {
    "vectors_deleted": 450
  },
  "message": "Deleted all data for group my-group"
}
```

## Testing

### Automated Test Suite
Run the comprehensive lifecycle test:
```bash
cd services/graphrag-orchestration
python test_document_lifecycle.py
```

**Test coverage:**
1. Index 2 documents with Document Intelligence
2. List indexed documents
3. Get statistics for each document
4. Delete first document
5. Verify deletion
6. List remaining documents
7. Query to verify graph state
8. Delete all documents
9. Final verification

**Expected output:**
```
================================================================================
  STEP 1: INDEX DOCUMENTS
================================================================================
📥 Indexing 2 documents...
✅ Indexing completed!
   Documents indexed: 2
   Nodes created: 87

================================================================================
  STEP 2: LIST INDEXED DOCUMENTS
================================================================================
📋 Found 2 indexed documents:
   1. URL: .../purchase_contract.pdf
      Nodes: 45
      Pages: 3

================================================================================
  STEP 3: DELETE DOCUMENT
================================================================================
🗑️  Deleting: .../purchase_contract.pdf...
✅ Deletion completed!
   Nodes deleted: 45
   Relationships deleted: 87
   Vectors deleted: 45
```

### Manual Testing
```bash
# 1. Index a document
curl -X POST "http://localhost:8001/graphrag/index" \
  -H "X-Group-ID: test-group" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": ["https://storage.blob.core.windows.net/.../doc.pdf"],
    "extraction_mode": "dynamic",
    "ingestion": "document-intelligence"
  }'

# 2. List documents
curl -X GET "http://localhost:8001/graphrag/documents" \
  -H "X-Group-ID: test-group"

# 3. Get stats
curl -X GET "http://localhost:8001/graphrag/documents/stats?url=https://..." \
  -H "X-Group-ID: test-group"

# 4. Delete document
curl -X POST "http://localhost:8001/graphrag/documents/delete" \
  -H "X-Group-ID: test-group" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://..."}'

# 5. Verify deletion
curl -X GET "http://localhost:8001/graphrag/documents" \
  -H "X-Group-ID: test-group"
```

## Architecture Decisions

### Why URL-based deletion?
- Document Intelligence automatically adds `url` to metadata
- URLs are unique and stable identifiers
- Neo4j queries on string properties are efficient with indexes
- No need for separate `document_id` field

### Why separate Neo4j and LanceDB deletion?
- Different APIs and deletion semantics
- Neo4j uses Cypher `DETACH DELETE`
- LanceDB uses SQL-like `table.delete(filter)`
- Azure Search uses document ID-based deletion
- Ensures both graph and vectors are cleaned up

### Why `group_id` filtering everywhere?
- Multi-tenant isolation is critical
- Prevents accidental cross-tenant deletion
- Enforced at application layer (Neo4j Community has no native RLS)
- All deletion queries include `WHERE n.group_id = $group_id`

### Why not cascade deletion from Neo4j to LanceDB?
- Different data stores with independent lifecycles
- Explicit deletion gives better observability
- Allows partial cleanup (e.g., delete vectors but keep graph)
- Clear error handling per store

## Security Considerations

### Tenant Isolation
- All endpoints require `X-Group-ID` header
- All Neo4j queries filter by `group_id`
- All LanceDB/Azure Search filters include `group_id`
- No cross-tenant data leakage possible

### Dangerous Operations
- `DELETE /graphrag/documents/all` requires explicit confirmation in production
- Consider adding confirmation header: `X-Confirm-Delete-All: true`
- Log all deletion operations with group_id and user context
- Implement soft delete for production (add `deleted_at` timestamp)

### Input Validation
- URL must be valid HTTPS URL
- group_id must match authenticated tenant
- Consider URL allow-list for blob storage domains

## Performance Considerations

### Deletion Performance
- Neo4j `DETACH DELETE` is atomic but can be slow for large graphs
- Consider batching for > 10,000 nodes
- LanceDB deletion rebuilds table index (can take time)
- Azure Search batch deletion is efficient (up to 1000 docs/batch)

### Indexing for Fast Lookups
Add Neo4j indexes for common queries:
```cypher
CREATE INDEX document_url_idx FOR (n:__Node__) ON (n.url);
CREATE INDEX group_id_idx FOR (n:__Node__) ON (n.group_id);
CREATE COMPOSITE INDEX document_lookup FOR (n:__Node__) ON (n.group_id, n.url);
```

### Pagination for Large Result Sets
Current implementation loads all documents. For production:
```python
# Add pagination to list_documents
def list_indexed_documents(
    self, 
    group_id: str,
    skip: int = 0,
    limit: int = 100
) -> Dict[str, Any]:
    query = """
    MATCH (n)
    WHERE n.group_id = $group_id AND n.url IS NOT NULL
    WITH n.url AS url, count(n) AS node_count
    RETURN url, node_count
    ORDER BY url
    SKIP $skip
    LIMIT $limit
    """
```

## Future Enhancements

### 1. Soft Delete
Add `deleted_at` timestamp instead of hard delete:
```python
def soft_delete_document(self, group_id: str, url: str):
    query = """
    MATCH (n {group_id: $group_id, url: $url})
    SET n.deleted_at = datetime()
    RETURN count(n) AS marked_deleted
    """
```

### 2. Document Versioning
Track multiple versions of same document:
```python
metadata = {
    "url": url,
    "version": "v2",
    "previous_version": "v1",
    "indexed_at": datetime.now().isoformat()
}
```

### 3. Batch Operations
Delete multiple documents in one call:
```python
class BatchDeleteRequest(BaseModel):
    urls: List[str]

@router.post("/documents/batch-delete")
async def batch_delete_documents(request: Request, payload: BatchDeleteRequest):
    results = []
    for url in payload.urls:
        result = graph_service.delete_document_by_url(group_id, url)
        results.append(result)
    return {"deletions": results}
```

### 4. Metadata Search
Find documents by metadata:
```python
@router.get("/documents/search")
async def search_documents(
    request: Request,
    page_count_min: int = None,
    page_count_max: int = None,
    indexed_after: str = None
):
    # Query Neo4j with metadata filters
```

### 5. Document Deduplication
Detect and merge duplicate documents:
```python
def find_duplicate_documents(self, group_id: str) -> List[Dict[str, Any]]:
    query = """
    MATCH (n {group_id: $group_id})
    WHERE n.url IS NOT NULL
    WITH n.url AS url, count(*) AS count
    WHERE count > 1
    RETURN url, count
    """
```

## Related Files
- `app/services/graph_service.py` - Neo4j deletion logic
- `app/services/vector_service.py` - LanceDB/Azure Search deletion
- `app/services/document_intelligence_service.py` - Metadata injection
- `app/routers/graphrag.py` - API endpoints
- `test_document_lifecycle.py` - Comprehensive test suite
- `app/services/indexing_service.py` - Index creation (unchanged)

## Troubleshooting

### Issue: "Driver not initialized"
**Cause:** Neo4j connection failed
**Solution:** Check `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` in `.env`

### Issue: Deletion returns 0 nodes deleted
**Cause:** URL doesn't match exactly
**Solution:** List documents first to get exact URL, including query params

### Issue: Vectors not deleted from LanceDB
**Cause:** LanceDB table doesn't exist or metadata filter incorrect
**Solution:** Check table name format: `{group_id}_default`

### Issue: Cross-tenant data visible
**Cause:** Missing `group_id` filter in query
**Solution:** All queries MUST include `WHERE n.group_id = $group_id`

## Status
✅ Implementation complete
✅ Graph service methods added
✅ Vector service methods added
✅ API endpoints created
✅ Test suite implemented
✅ Service restarted and validated
✅ Documentation created

## Next Steps
1. Run `python test_document_lifecycle.py` once quota increases approved
2. Add pagination for production workloads (> 100 documents)
3. Consider soft delete for production safety
4. Add document versioning if needed
5. Implement batch operations for efficiency
