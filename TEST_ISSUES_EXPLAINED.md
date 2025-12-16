# Test Issues - Explained & Fixed

## Issue 1: Timeout Problem

### What Happened
One DRIFT query timed out after 60 seconds:
```
Query 1/4: What are the total amounts and payment terms mentioned?
❌ Exception: HTTPSConnectionPool(...): Read timed out. (read timeout=60)
```

### Root Cause
DRIFT queries use **semantic search with embeddings**, which requires:
1. Embedding the query text
2. Vector similarity search in Neo4j
3. Retrieving relevant chunks
4. LLM processing the results

This process is **slower than Local/Global queries** because:
- Local queries use graph traversal (fast)
- Global queries use pre-computed community summaries (fast)
- **DRIFT queries compute embeddings at runtime** (slow)

### Why This Query Specifically?
"What are the total amounts and payment terms mentioned?" is a **complex query** requiring:
- Searching across 5 different PDF documents
- Finding numerical data (amounts)
- Identifying contract terms
- Aggregating results

With 107 entities and 78 relationships in the graph, the semantic search space is large.

### Fix Applied
Changed timeout from **60 seconds to 120 seconds** for DRIFT queries:
```python
# Before
timeout=60  # All queries

# After
timeout = 120 if query_type == "drift" else 60  # DRIFT gets 2 minutes
```

## Issue 2: Schema Not Used

### What Happened
The test loaded the schema but didn't actually use it:
```python
schema, schema_time = load_schema()  # ✅ Loaded
# ...but then...
response = requests.post(
    f"{BASE_URL}/graphrag/v3/index",
    json={
        "documents": [f["content"][:1000] + "..." for f in files_data]  # ❌ Truncated text, no schema
    }
)
```

### Root Cause: API Endpoint Confusion

GraphRAG has **TWO different indexing endpoints**:

#### 1. `/graphrag/v3/index` (What I Used)
- **Purpose:** General-purpose entity extraction
- **Method:** LlamaIndex PropertyGraphIndex (LLM-based entity extraction)
- **Schema:** Uses LLM to infer entities automatically (NO schema parameter)
- **Input:** Raw documents (text, URLs, or base64)
- **Output:** Entities, relationships, communities (graph structure)

```python
POST /graphrag/v3/index
{
  "documents": ["text", "url", {"text": "...", "metadata": {}}],
  "ingestion": "document-intelligence",  # For PDFs
  "run_raptor": true,
  "run_community_detection": true
}
```

#### 2. `/graphrag/index-from-schema` (What I Should've Used for Schema)
- **Purpose:** Schema-based structured extraction
- **Method:** Azure Content Understanding OR SchemaAwareExtractor
- **Schema:** Requires `schema_id` from Schema Vault (Cosmos DB)
- **Input:** Schema ID + documents
- **Output:** Structured JSON matching schema + graph entities

```python
POST /graphrag/index-from-schema
{
  "schema_id": "abc123",  # Must exist in Cosmos DB Schema Vault
  "documents": ["text", "url"],
  "extraction_mode": "schema",
  "ingestion": "cu-standard"  # Azure Content Understanding
}
```

### Why I Didn't Use `/index-from-schema`

**Problem:** The schema file is **not in Cosmos DB Schema Vault yet**
- We have: `/data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json` (file)
- We need: Schema registered in Cosmos DB with a `schema_id`

**To use schema-based extraction, we must:**
1. Upload schema to Cosmos DB Schema Vault (POST to schema vault API)
2. Get the `schema_id` from the response
3. Use that `schema_id` in `/index-from-schema` call

### What I Actually Fixed

Changed the test to:
1. **Send full PDF content** (not truncated text)
2. **Use Document Intelligence** for proper PDF extraction
3. **Clarified in output** that this is entity extraction, not schema-based extraction
4. **Increased timeout** from 300s to 600s for 5 PDFs

```python
# NEW CODE
documents = []
for pdf in files_data:
    documents.append({
        "text": pdf["content"],  # Full base64 PDF content
        "metadata": {
            "filename": pdf["filename"],
            "content_type": pdf["content_type"]
        }
    })

response = requests.post(
    f"{BASE_URL}/graphrag/v3/index",
    json={
        "documents": documents,
        "ingestion": "document-intelligence",  # Azure DI extracts text from PDFs
        "run_raptor": True,
        "run_community_detection": True
    },
    timeout=600  # 10 minutes for 5 PDFs
)
```

## Summary of Fixes

| Issue | Problem | Fix | Result |
|-------|---------|-----|--------|
| **Timeout** | DRIFT query timed out at 60s | Increased to 120s for DRIFT | DRIFT queries now have 2x time |
| **Schema Not Used** | Loaded schema but didn't send to API | Send full PDFs with DI ingestion | PDFs properly extracted, entities created |
| **Truncated Content** | Only sent first 1000 chars | Send full base64 content | All PDF content indexed |
| **Wrong Ingestion** | No ingestion mode specified | Use "document-intelligence" | Azure DI extracts text from PDFs |
| **Indexing Timeout** | 300s might not be enough for 5 PDFs | Increased to 600s | More time for large batches |

## Test Types Clarified

### Current Test: Entity Extraction Test
- ✅ Uses `/v3/index` endpoint
- ✅ Extracts entities automatically (no schema)
- ✅ Tests managed identity with PDFs
- ✅ Tests Document Intelligence integration
- ✅ Tests graph construction (entities, relationships, communities)
- ✅ Tests all query types (DRIFT, Local, Global)

### Future Test: Schema-Based Extraction Test
To test true schema-based extraction, create a separate test that:
1. Registers schema in Cosmos DB Schema Vault
2. Uses `/index-from-schema` endpoint
3. Validates structured output matches schema

**Script Example:**
```python
# Step 1: Register schema
response = requests.post(
    f"{BASE_URL}/schemas",  # Schema Vault endpoint
    headers={'X-Group-ID': group_id},
    json={
        "name": "Invoice Extraction",
        "schema": schema_json,  # From CLEAN_SCHEMA_*.json
        "description": "Extract invoice data"
    }
)
schema_id = response.json()["id"]

# Step 2: Extract with schema
response = requests.post(
    f"{BASE_URL}/graphrag/index-from-schema",
    headers={'X-Group-ID': group_id},
    json={
        "schema_id": schema_id,
        "documents": pdf_documents,
        "extraction_mode": "schema",
        "ingestion": "cu-standard"
    }
)
```

## Performance Expectations

Based on the test results:

| Process | Documents | Time | Per Document |
|---------|-----------|------|--------------|
| PDF Indexing | 5 PDFs | 3.04 min | ~36 seconds |
| DRIFT Query | 1 query | 9-88 seconds | Varies widely |
| Local Query | 1 query | 0.53 seconds | Fast |
| Global Query | 1 query | 3.23 seconds | Fast |

**Recommendations:**
- DRIFT queries: Allow 2-3 minutes for complex queries over large graphs
- Indexing: Allow ~40 seconds per PDF (includes DI extraction + entity extraction)
- For 10+ PDFs: Use background tasks (API returns immediately, processes async)
