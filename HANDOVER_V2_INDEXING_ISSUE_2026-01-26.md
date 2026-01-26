# V2 Indexing Issue - Handover Document
**Date:** January 26, 2026  
**Status:** Root cause identified, fix deployed, re-indexing required  
**Team:** Ready for continuation on January 27, 2026

---

## Executive Summary

**Problem:** V2 achieved only 83% theme coverage on Q-G10 (missing "scope of work" from EXHIBIT A chunks) vs V1's 100%.

**Root Cause:** The V2 group `test-5pdfs-v2-1769440005` was indexed via the `/hybrid/index/documents` API endpoint, which called the **V1 factory** (`get_lazygraphrag_indexing_pipeline()`) instead of the V2 factory. This resulted in:
- OpenAI 3072D embeddings stored in `embedding` property (not `embedding_v2`)
- V1 index `chunk_embedding` created (not `chunk_embeddings_v2`)
- Query-time dimension mismatch: Voyage 2048D query vs OpenAI 3072D index

**Fix Status:** 
- ✅ Code fix deployed (commit `2c8e8d6`): `/hybrid/index/documents` now uses V2 factory when V2 enabled
- ✅ Deployment completed to Sweden Central Container Apps
- ⏳ V2 group needs re-indexing with correct pipeline

---

## Technical Deep Dive

### The Investigation Trail

1. **Initial Symptoms** (Jan 26, 09:00-15:00):
   - Route 3 queries incorrectly falling back to Route 4 (DRIFT) due to enum type mismatch
   - Fixed enum bug by importing all V2 modules consistently
   - Route 3 working, but Q-G10 showed 83% coverage (5/6 themes) - missing "scope of work"

2. **Embedding Dimension Discovery** (Jan 26, 15:00-16:00):
   - Routes 1, 3, 4 were using `llm_service.embed_model.get_text_embedding()` → OpenAI 3072D
   - V2 indexes store Voyage 2048D embeddings
   - Fixed all routes to use `get_query_embedding()` which returns correct dimensions based on V2 mode

3. **Partial Success** (Jan 26, 16:00-17:00):
   - Deployed embedding fix with VOYAGE_V2_ENABLED=true in Azure
   - Fixed ACR permission issue (managed identity lost AcrPull role)
   - Explicit "EXHIBIT A" query retrieved all 4 chunks ✅
   - Document summary query still only retrieved chunks 0,2 ❌

4. **Root Cause Discovery** (Jan 26, 17:00-18:30):
   - Investigated V2 indexing pipeline configuration
   - Found `/hybrid/index/documents` endpoint calls V1 factory `get_lazygraphrag_indexing_pipeline()`
   - V1 factory defaults `use_v2_embedding_property=False`
   - **Result**: V2 group has OpenAI embeddings in `embedding` property, NOT Voyage embeddings in `embedding_v2`

### The Mismatch Explained

**During Indexing (V1 Factory - WRONG):**
```python
# /hybrid/index/documents endpoint (OLD CODE)
pipeline = get_lazygraphrag_indexing_pipeline(...)
# ↓
# V1 factory in app/hybrid/indexing/lazygraphrag_indexing_pipeline.py
pipeline = LazyGraphRAGIndexingPipeline(
    embedder=OpenAIEmbedService(...),  # OpenAI 3072D
    use_v2_embedding_property=False,    # Stores in 'embedding' property
    ...
)
# ↓
# Creates chunks with:
#   - embedding: [3072-dim OpenAI vector]
#   - embedding_v2: NULL
# Creates index:
#   - chunk_embedding (1536 or 3072 dim)
```

**During Query (V2 Mode - EXPECTED):**
```python
# Route 3 query flow
query_embedding = get_query_embedding(query_text)  # Returns Voyage 2048D
index_name = get_vector_index_name()               # Returns "chunk_embeddings_v2"
# ↓
# Cypher vector search
CALL db.index.vector.queryNodes(
    "chunk_embeddings_v2",  # ← Looking for this index (doesn't exist!)
    20,
    $query_embedding        # ← 2048D Voyage vector
)
YIELD node, score
WHERE node.embedding_v2 IS NOT NULL  # ← Looking for this property (is NULL!)
```

**Outcome:** Vector search returns 0 results, query falls back to BM25-only retrieval, missing semantically-relevant chunks.

### The Fix

**File Modified:** `graphrag-orchestration/app/routers/hybrid.py`

**Change:** Line 220 in `/hybrid/index/documents` endpoint:
```python
# BEFORE (V1 factory - WRONG)
pipeline = get_lazygraphrag_indexing_pipeline(...)

# AFTER (V2-aware factory - CORRECT)
if settings.VOYAGE_V2_ENABLED:
    pipeline = get_lazygraphrag_indexing_pipeline_v2(...)
else:
    pipeline = get_lazygraphrag_indexing_pipeline(...)
```

**What This Changes:**
- V2 factory uses `VoyageEmbedService(model="voyage-context-3", output_dim=2048)`
- Sets `use_v2_embedding_property=True`
- Stores embeddings in `embedding_v2` property (2048D Voyage vectors)
- Creates/uses `chunk_embeddings_v2` index
- Query-time vector search now matches: 2048D query → 2048D index ✅

---

## Current Status

### ✅ Completed

1. **Enum Bug Fix** (Commit `9ef3106`):
   - Fixed Route 3 → Route 4 fallback issue
   - All V2 modules now use consistent `from app.hybrid_v2.orchestrator import QueryRoute`

2. **Embedding Dimension Fix** (Commit `40490c5`, `606feff`, `db424e6`):
   - Routes 1, 3, 4 now use `get_query_embedding()` instead of `llm_service.embed_model.get_text_embedding()`
   - Correctly returns Voyage 2048D when V2 enabled, OpenAI 3072D otherwise

3. **Azure Environment** (Commit `ab4d570`, `8e79ce3`):
   - VOYAGE_V2_ENABLED=true
   - VOYAGE_API_KEY (secret reference)
   - VOYAGE_EMBEDDING_MODEL=voyage-context-3
   - VOYAGE_EMBEDDING_DIM=2048

4. **ACR Permissions**:
   - Restored AcrPull role for managed identity `28972c71-7386-4bee-8a5e-35f06f966848`

5. **Indexing Endpoint Fix** (Commit `2c8e8d6`):
   - `/hybrid/index/documents` now uses V2 factory when `VOYAGE_V2_ENABLED=true`
   - Deployed to Sweden Central Container Apps

### ⏳ Pending (Next Steps)

1. **Re-index V2 Group** (HIGH PRIORITY):
   ```bash
   # Delete old V2 group (has wrong embeddings)
   # Option A: Via API
   curl -X DELETE "https://graphrag-sweden-lazy-hippo.azurewebsites.net/groups/test-5pdfs-v2-1769440005" \
     -H "Content-Type: application/json"
   
   # Option B: Via Neo4j (more thorough)
   MATCH (n {group_id: 'test-5pdfs-v2-1769440005'})
   DETACH DELETE n
   
   # Re-index with V2 pipeline
   python3 scripts/index_5pdfs_v2_cloud.py
   # This will create new group: test-5pdfs-v2-<timestamp>
   ```

2. **Verify V2 Index Creation**:
   ```bash
   # Check that embedding_v2 property exists
   python3 scripts/index_5pdfs_v2_local.py --verify-only test-5pdfs-v2-<new-timestamp>
   
   # Expected output:
   #   Total chunks: ~140-150
   #   With embedding_v2: 100%
   #   V2 embedding dimension: 2048 (correct)
   ```

3. **Run Route 3 Benchmark**:
   ```bash
   cd graphrag-orchestration
   python3 scripts/run_benchmark.py \
     --group-id test-5pdfs-v2-<new-timestamp> \
     --route 3 \
     --output ../bench_route3_v2_correct_embeddings_<timestamp>.txt
   ```

4. **Validate Results**:
   - Q-G10 should achieve 100% theme coverage (6/6 themes including "scope of work")
   - All EXHIBIT A chunks (1 and 3) should be retrieved for document summary query
   - Compare with V1 baseline for parity

5. **Update Architecture Documentation**:
   - Document the indexing endpoint fix
   - Add warning about V1/V2 factory distinction
   - Update recommended indexing flow

---

## Key Learnings

### 1. **Factory Pattern Complexity**
- Multiple factory functions (`get_lazygraphrag_indexing_pipeline()` vs `get_lazygraphrag_indexing_pipeline_v2()`) create confusion
- API endpoints must explicitly choose the correct factory based on V2 mode
- Consider consolidating into single factory with V2-awareness built in

### 2. **Embedding Property Naming**
- Having both `embedding` and `embedding_v2` properties on same nodes is error-prone
- Query-time code must match indexing-time configuration
- Consider enforcing this via schema validation

### 3. **Index Name Consistency**
- `get_vector_index_name()` returns correct index name based on V2 mode
- But if index doesn't exist (because V1 factory was used), vector search silently fails
- Consider adding index existence check with clear error message

### 4. **V2 Mode Configuration**
- Must be consistent across:
  1. Environment variables (VOYAGE_V2_ENABLED)
  2. Factory selection (V2 factory vs V1 factory)
  3. Query-time helpers (get_query_embedding, get_vector_index_name)
- Currently #2 was out of sync with #1 and #3

### 5. **Testing Strategy**
- Need integration test that verifies end-to-end V2 flow:
  1. Index documents via API with V2 enabled
  2. Verify `embedding_v2` property exists
  3. Verify `chunk_embeddings_v2` index exists
  4. Query via API and verify vector results
- Would have caught this issue before deployment

---

## Files Modified (Full Change History)

### Commits (Jan 26, 2026)

1. **9ef3106** - Fix Route 3 enum type mismatch
   - `app/hybrid_v2/routes/route_3_global.py`
   - `app/hybrid_v2/orchestrator.py`

2. **40490c5** - Fix Routes 1, 3, 4 embedding dimension mismatch
   - `app/hybrid_v2/routes/route_1_vector.py`
   - `app/hybrid_v2/routes/route_3_global.py`
   - `app/hybrid_v2/routes/route_4_drift.py`

3. **606feff** - Add VOYAGE env vars to bicep
   - `infra/main.bicep`

4. **db424e6** - Fix bicep conditional secrets syntax
   - `infra/main.bicep`

5. **ab4d570** - Fix ACR managed identity permissions
   - Azure Portal (manual fix)

6. **8e79ce3** - Deploy with VOYAGE_V2_ENABLED=true
   - Azure deployment (via `azd up`)

7. **2c8e8d6** - Fix /hybrid/index/documents to use V2 factory
   - `graphrag-orchestration/app/routers/hybrid.py`

---

## Environment Configuration

### Required .env Variables (V2 Mode)

```bash
# V2 Voyage Configuration
VOYAGE_V2_ENABLED=true
VOYAGE_API_KEY=pa-xxx...vULX
VOYAGE_MODEL_NAME=voyage-context-3
VOYAGE_EMBEDDING_DIM=2048
VOYAGE_V2_SIMILARITY_THRESHOLD=0.87

# Neo4j (same for V1 and V2)
NEO4J_URI=neo4j+s://cec7cfcd.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=xxx
NEO4J_DATABASE=neo4j

# Azure OpenAI (still used for LLM, entity extraction)
AZURE_OPENAI_ENDPOINT=https://graphrag-sweden.openai.azure.com/
AZURE_OPENAI_KEY=xxx
AZURE_OPENAI_DEPLOYMENT=gpt-4o-2024-08-06-sweden
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

### Azure Container Apps Environment Variables

Verified via Azure Portal → Container App → Configuration:

```bash
VOYAGE_V2_ENABLED=true
VOYAGE_API_KEY=<secret reference: voyage-api-key>
VOYAGE_EMBEDDING_MODEL=voyage-context-3
VOYAGE_EMBEDDING_DIM=2048
```

---

## Quick Reference

### Test Groups

- **V1 Group (OpenAI):** `test-5pdfs-1769071711867955961` - 100% coverage baseline
- **V2 Group (Wrong):** `test-5pdfs-v2-1769440005` - 83% coverage (wrong embeddings)
- **V2 Group (Correct):** TBD after re-indexing

### API Endpoints

- **Production:** `https://graphrag-sweden-lazy-hippo.azurewebsites.net`
- **Index Documents:** `POST /hybrid/index/documents`
- **Query:** `POST /query`
- **Delete Group:** `DELETE /groups/{group_id}`

### Key Scripts

- **V2 Indexing (Cloud):** `scripts/index_5pdfs_v2_cloud.py`
- **V2 Indexing (Local):** `scripts/index_5pdfs_v2_local.py`
- **V2 Verification:** `scripts/index_5pdfs_v2_local.py --verify-only <group_id>`
- **Benchmark:** `scripts/run_benchmark.py --group-id <group_id> --route 3`
- **Graph Check:** `check_edges.py <group_id>`

### Useful Cypher Queries

```cypher
// Check embedding properties on V2 group
MATCH (c:TextChunk {group_id: 'test-5pdfs-v2-1769440005'})
RETURN 
  count(c) AS total_chunks,
  count(c.embedding) AS with_v1_embedding,
  count(c.embedding_v2) AS with_v2_embedding
LIMIT 1;

// Check embedding dimensions
MATCH (c:TextChunk {group_id: 'test-5pdfs-v2-1769440005'})
WHERE c.embedding_v2 IS NOT NULL
RETURN size(c.embedding_v2) AS v2_dimension
LIMIT 1;

// List all vector indexes
SHOW INDEXES
YIELD name, type
WHERE type = 'VECTOR'
RETURN name, type;

// Delete V2 group (CAUTION!)
MATCH (n {group_id: 'test-5pdfs-v2-1769440005'})
DETACH DELETE n;
```

---

## TODO List (Priority Order)

### 🔥 Critical (Do First)

- [ ] **Re-index V2 group with correct pipeline**
  - Delete `test-5pdfs-v2-1769440005` from Neo4j
  - Run `python3 scripts/index_5pdfs_v2_cloud.py` 
  - Verify `embedding_v2` property exists (use `--verify-only`)
  - Update `last_test_group_id.txt` with new group ID

- [ ] **Run Route 3 benchmark on new V2 group**
  - Target: 100% theme coverage on Q-G10
  - Verify EXHIBIT A chunks (1 and 3) are retrieved
  - Compare latency with V1 baseline

### ⚡ High Priority

- [ ] **Add integration test for V2 indexing**
  - Test: Index via API with V2 enabled → verify `embedding_v2` exists
  - Test: Query via API with V2 enabled → verify vector results returned
  - Prevents regression of this bug

- [ ] **Consolidate factory functions**
  - Consider single `get_lazygraphrag_indexing_pipeline()` with auto-detection
  - Or rename to make V1/V2 distinction more obvious
  - Add docstring warnings about V2 mode

- [ ] **Add index existence check**
  - Before vector search, verify `chunk_embeddings_v2` index exists
  - Provide clear error message if missing
  - Guide user to re-index with correct pipeline

### 📋 Medium Priority

- [ ] **Update architecture documentation**
  - Document the V1/V2 factory distinction
  - Add section on "Common Pitfalls"
  - Update recommended indexing flow diagram

- [ ] **Create deployment checklist**
  - Verify VOYAGE_V2_ENABLED matches factory selection
  - Verify embedding dimensions match index dimensions
  - Run smoke test after deployment

- [ ] **Add Prometheus metrics**
  - Track vector_search_results_count (should be >0 for vector queries)
  - Track embedding_dimension_mismatches (should be 0)
  - Alert on anomalies

### 🔧 Nice to Have

- [ ] **Migrate to single embedding property**
  - Instead of `embedding` and `embedding_v2`, use `embedding` for both
  - Store dimension in separate property: `embedding_dim`
  - Reduces confusion and storage overhead

- [ ] **Add V2 mode visual indicator**
  - In query response, include `"v2_mode": true/false`
  - In logs, prefix with `[V2]` or `[V1]`
  - Makes debugging easier

- [ ] **Create V2 migration script**
  - Converts existing V1 group to V2
  - Re-embeds all chunks with Voyage
  - Updates indexes
  - Useful for production data migration

---

## Contact & Escalation

- **Primary:** Continue on January 27, 2026
- **Deployment:** Sweden Central Container Apps (`graphrag-sweden-lazy-hippo`)
- **Database:** Neo4j Aura (`cec7cfcd.databases.neo4j.io`)
- **Monitoring:** Check Container App logs for errors

**Key Decision Makers:**
- Architecture changes: Team lead
- Database modifications: DBA approval for production
- Deployment timing: DevOps coordination

---

## Appendix: Benchmark Results

### Route 3 - V2 with Wrong Embeddings (83% Coverage)

File: `bench_route3_v2_enum_fix_20260126_171612.txt`

**Q-G10 Results:**
- ✅ legal obligations and responsibilities (4 sources)
- ✅ services provided (6 sources)
- ✅ warranty conditions (4 sources)
- ✅ payment terms (5 sources)
- ✅ duration and termination (4 sources)
- ❌ **scope of work** (MISSING - should be in purchase_contract.pdf EXHIBIT A chunks 1 and 3)

**Chunks Retrieved for purchase_contract.pdf:**
- Chunk 0 (long narrative) ✅
- Chunk 1 (EXHIBIT A - 740 chars) ❌ MISSING
- Chunk 2 (long narrative) ✅
- Chunk 3 (EXHIBIT A - 740 chars) ❌ MISSING

**Root Cause:** Vector search failed due to dimension mismatch (2048D query vs 3072D index stored in wrong property)

### Route 3 - V1 Baseline (100% Coverage)

Previous benchmarks show V1 achieves 100% theme coverage including "scope of work" from EXHIBIT A chunks.

**Expected V2 Results (After Fix):**
- 100% theme coverage (6/6 themes)
- All 4 purchase_contract chunks retrieved
- Comparable or better latency than V1 (Voyage is faster API)

---

**Document Version:** 1.0  
**Last Updated:** January 26, 2026 18:45 UTC  
**Next Review:** January 27, 2026 (after re-indexing and benchmark)
