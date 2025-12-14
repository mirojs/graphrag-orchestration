# RAPTOR Vector Indexing Architecture Issue

**Date:** December 13, 2025  
**Status:** Critical Issue Identified - Needs Architecture Decision  
**Impact:** DRIFT multi-step reasoning and detailed document comparison queries not working

---

## Problem Summary

RAPTOR nodes are successfully created and stored in Neo4j with text content, but they **lack vector embeddings** for similarity search. This breaks the detailed document comparison workflow that requires RAPTOR content for multi-step reasoning.

### Current State

```
✅ Document Intelligence → Text extraction working
✅ RAPTOR hierarchical summaries → Created (14 nodes)
✅ RAPTOR text → Stored in Neo4j
❌ RAPTOR embeddings → NOT indexed (neither Neo4j nor Azure AI Search)
❌ RAPTOR vector search → Fails with "Index query" error
❌ DRIFT with RAPTOR → Cannot access detailed content
```

### Test Results (5 PDFs: invoices + contracts)

| Component | Status | Details |
|-----------|--------|---------|
| Entities extracted | ✅ Working | 194 entities in Neo4j |
| Relationships | ✅ Working | 192 relationships |
| Communities | ✅ Working | 15 communities with summaries |
| Text chunks | ✅ Working | 11 chunks in Neo4j |
| RAPTOR nodes created | ✅ Working | 14 nodes in Neo4j |
| RAPTOR embeddings | ❌ **MISSING** | No embeddings in Neo4j or Azure AI Search |
| Global search | ⚠️ Limited | Uses community summaries (loses detail) |
| Local search | ⚠️ Limited | Uses entities only (no document text) |
| DRIFT search | ❌ Broken | Embedding compatibility error |
| RAPTOR query | ❌ Broken | Vector index query fails |

---

## Root Cause Analysis

### Issue 1: Missing VECTOR_STORE_TYPE Configuration

**Current Configuration:**
```bash
AZURE_SEARCH_ENDPOINT=https://graphrag-search.search.windows.net
AZURE_SEARCH_INDEX_NAME=graphrag-raptor
# MISSING: VECTOR_STORE_TYPE environment variable
```

**Code Check:**
```python
# File: app/v3/services/indexing_pipeline.py:281
if settings.VECTOR_STORE_TYPE == "azure_search" and settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_API_KEY:
    self.vector_store_provider = AzureAISearchProvider(...)
    # This block NEVER executes because VECTOR_STORE_TYPE is not set
```

**Result:** RAPTOR nodes are created in Neo4j but NOT indexed to Azure AI Search.

### Issue 2: Neo4j Vector Index Created but No Embeddings

**Schema Definition:**
```cypher
CREATE VECTOR INDEX raptor_embedding IF NOT EXISTS
FOR (r:RaptorNode)
ON (r.embedding)
OPTIONS {indexConfig: {
    `vector.dimensions`: 3072,
    `vector.similarity_function`: 'cosine'
}}
```

**Data Check:**
```cypher
MATCH (r:RaptorNode {group_id: "test-5pdfs-1765652467"})
RETURN r.text IS NOT NULL, r.embedding IS NOT NULL
// Result: text=true, embedding=NULL
```

**Root Cause:** During indexing, RAPTOR nodes are stored with text but embeddings are either:
1. Not generated for RAPTOR nodes
2. Only sent to Azure AI Search (which isn't configured)
3. Not stored in Neo4j `embedding` property

### Issue 3: Architecture Document vs Implementation Mismatch

**Architecture Document Says:**
```
Azure AI Search Strategy:
- Indexing Time: Index RAPTOR nodes into BOTH Neo4j and Azure AI Search
- Query Time: Use Neo4j ONLY
```

**Actual Implementation:**
- RAPTOR text → Neo4j ✅
- RAPTOR embeddings → Neo4j ❌
- RAPTOR embeddings → Azure AI Search ❌ (VECTOR_STORE_TYPE not set)

---

## Impact on Use Cases

### Use Case: Invoice/Contract Verification

**Requirement:** Compare 5 PDFs (invoices + contracts) to find ALL inconsistencies in:
- Payment amounts
- Payment terms  
- Line item quantities
- Unit prices
- Delivery dates
- Specific numerical values

**Expected Flow:**
```
1. Document Intelligence extracts detailed text
2. RAPTOR creates hierarchical summaries with all details
3. DRIFT multi-step reasoning queries RAPTOR nodes
4. LLM compares specific values across documents
5. Returns comprehensive list of inconsistencies
```

**Actual Flow:**
```
1. Document Intelligence extracts detailed text ✅
2. RAPTOR creates hierarchical summaries ✅
3. DRIFT tries to query RAPTOR nodes ❌ (no embeddings)
4. Falls back to community summaries ⚠️ (loses detail)
5. Returns only 5 high-level inconsistencies ❌ (should be 20+)
```

**Result:** System correctly identifies themes but misses specific numerical discrepancies because RAPTOR detailed content is inaccessible.

---

## Technical Details

### Modified Code (Today)

1. **Added RAPTOR query endpoint** (`/v3/query/raptor`)
   - Purpose: Direct query of RAPTOR nodes for detailed content
   - Status: ❌ Broken - vector index fails

2. **Modified DRIFT to include RAPTOR nodes**
   ```python
   # File: app/v3/services/drift_adapter.py
   def load_text_units_with_raptor_as_graphrag_models(self, group_id: str):
       """Load BOTH text chunks AND RAPTOR nodes for richer DRIFT context."""
       chunks_df = self.load_text_chunks(group_id)  # 11 chunks
       raptor_df = self.load_raptor_nodes(group_id)  # 14 nodes
       # Combine into 25 text units for DRIFT
   ```
   - Purpose: Give DRIFT access to hierarchical summaries
   - Status: ❌ Broken - DRIFT has embedding compatibility error

3. **Deployed new image** (`raptor-drift`)
   - Changes: RAPTOR integration into DRIFT
   - Status: Deployed but not functional due to missing embeddings

### Error Messages

**RAPTOR Query Endpoint:**
```
{code: Neo.ClientError.Procedure.ProcedureCallFailed} 
{message: Failed to invoke procedure `db.index.vector.queryNodes`: 
Caused by: java.lang.IllegalArgumentException: Index query vector is not compatible}
```

**DRIFT Search:**
```
DRIFT search failed: Query and document embeddings are not compatible. 
Please ensure that the embeddings are of the same type and length.
```

Both errors indicate: **RAPTOR nodes exist but have no embeddings**.

---

## Architecture Decision Required

We need to decide on ONE of the following approaches:

### Option 1: Neo4j-Only Vector Storage (Simpler)

**Implementation:**
1. Modify indexing pipeline to generate embeddings for RAPTOR nodes
2. Store embeddings in Neo4j `RaptorNode.embedding` property
3. Use existing `raptor_embedding` vector index for queries
4. Remove Azure AI Search dependency

**Pros:**
- Single source of truth (Neo4j)
- No external dependencies
- Faster queries (one hop)
- Simpler deployment

**Cons:**
- Diverges from architecture doc (which specifies Azure AI Search)
- No backup/legacy compatibility layer

**Code Changes:**
```python
# File: app/v3/services/indexing_pipeline.py
# In _run_raptor() method after creating RAPTOR nodes:

for node in raptor_nodes:
    # Generate embedding for RAPTOR text
    embedding = await self.llm_service.embed_model.aget_text_embedding(node.text)
    node.embedding = embedding  # Store in RaptorNode object
    
    # Save to Neo4j with embedding
    self.neo4j_store.upsert_raptor_node(group_id, node)
```

**Deployment:**
- No environment variable changes needed
- Re-index existing data: `DELETE (r:RaptorNode) WHERE r.group_id = $group_id`
- Run indexing again to create RAPTOR nodes with embeddings

---

### Option 2: Dual Storage (Azure AI Search + Neo4j) - Per Architecture Doc

**Implementation:**
1. Set `VECTOR_STORE_TYPE=azure_search` environment variable
2. Configure Azure AI Search credentials (managed identity already set up)
3. Index RAPTOR embeddings to Azure AI Search
4. Store RAPTOR text in Neo4j (as currently done)
5. Query: Search Azure AI Search → Get IDs → Fetch text from Neo4j

**Pros:**
- Matches architecture document exactly
- Backup/redundancy (data in two places)
- Can switch between vector stores if needed
- Azure Semantic Ranker available (future)

**Cons:**
- More complex (two systems to manage)
- Slower queries (two hops: Azure AI Search → Neo4j)
- Higher cost (Azure AI Search usage)
- Data consistency challenges

**Code Changes:**
```bash
# Environment variable
VECTOR_STORE_TYPE=azure_search

# Existing code already handles this:
# app/v3/services/indexing_pipeline.py:281-531
# Just need to set the env var and re-index
```

**Deployment:**
1. Update container app env vars
2. Re-index data to populate Azure AI Search
3. Modify query endpoints to use Azure AI Search for RAPTOR retrieval

---

### Option 3: Hybrid Approach (Recommended for Testing)

**Short-term (This Week):**
- Use Option 1 (Neo4j-only) for immediate testing
- Store RAPTOR embeddings in Neo4j
- Validate that DRIFT + detailed queries work

**Long-term (Next Sprint):**
- Implement Option 2 (Dual storage) per architecture doc
- Add toggle to switch between Neo4j vectors and Azure AI Search
- Performance test both approaches with larger datasets

**Benefits:**
- Unblocks testing immediately
- Validates architecture with real data
- Allows performance comparison before committing

---

## Recommended Next Steps

1. **Tomorrow Morning (30 min):**
   - Decide: Option 1, 2, or 3
   - If Option 1: Modify indexing pipeline to store RAPTOR embeddings in Neo4j
   - If Option 2: Set VECTOR_STORE_TYPE=azure_search

2. **Re-index Test Data (1 hour):**
   ```bash
   # Delete current RAPTOR nodes (no embeddings)
   DELETE (r:RaptorNode {group_id: "test-5pdfs-1765652467"})
   
   # Re-run indexing with new configuration
   curl -X POST .../v3/index -d '{"documents": [...]}'
   ```

3. **Validate (30 min):**
   - Test RAPTOR query endpoint
   - Test DRIFT with detailed comparison query
   - Verify 20+ inconsistencies are found (not just 5)

4. **Update Architecture Doc (15 min):**
   - Document the chosen approach
   - Update query flow diagrams
   - Add troubleshooting section

---

## Test Query for Validation

Once embeddings are working, test with:

```bash
curl -X POST https://.../v3/query/drift \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-1765652467" \
  -d '{
    "query": "Compare ALL invoices against ALL contracts. For each comparison, identify specific inconsistencies in: payment terms, payment amounts, line items, quantities, unit prices, total amounts, delivery dates. List every difference with specific values from each document.",
    "max_iterations": 10,
    "convergence_threshold": 0.7
  }'
```

**Expected Output:**
- 15-25 specific inconsistencies
- Exact values from documents (e.g., "Invoice shows $10,950, contract shows $12,000")
- Document names and page references
- Categorized by inconsistency type

**Current Output:**
- Error: "Query and document embeddings are not compatible"

---

## Files Modified Today

| File | Changes | Status |
|------|---------|--------|
| `app/v3/routers/graphrag_v3.py` | Added `/query/raptor` endpoint | Deployed (non-functional) |
| `app/v3/services/drift_adapter.py` | Added `load_raptor_nodes()` | Deployed (unused) |
| `app/v3/services/drift_adapter.py` | Added `load_text_units_with_raptor_as_graphrag_models()` | Deployed (breaks DRIFT) |
| `app/v3/services/drift_adapter.py` | Modified `drift_search()` to use RAPTOR | Deployed (breaks DRIFT) |

**Docker Image:** `graphragacr12153.azurecr.io/graphrag-orchestration:raptor-drift`  
**Container Revision:** graphrag-orchestration--0000012 (latest)

---

## References

- Architecture Document: `docs/GRAPHRAG_V3_ARCHITECTURE_DECISIONS.md`
- Indexing Pipeline: `app/v3/services/indexing_pipeline.py`
- Neo4j Store: `app/v3/services/neo4j_store.py`
- DRIFT Adapter: `app/v3/services/drift_adapter.py`
- Azure AI Search Config: Environment variables `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_INDEX_NAME`

---

## Decision Log

**Date:** December 13, 2025  
**Participants:** TBD  
**Decision:** Pending - To be discussed tomorrow  
**Action Items:** TBD
