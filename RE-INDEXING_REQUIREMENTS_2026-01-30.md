# Re-indexing Requirements After Embedding V2 Fix

**Date:** January 30, 2026

## Executive Summary

**✅ INDEXING PIPELINE IS CORRECT** - No code bugs found. The pipeline properly uses `embedding_v2` property when `use_v2_embedding_property=True`.

**❌ RE-INDEXING REQUIRED FOR V2 ONLY** - Documents indexed with `VOYAGE_V2_ENABLED=true` before today need re-indexing to populate `embedding_v2` property on Entity nodes.

**✅ V1 DOCUMENTS ARE FINE** - Documents indexed with `VOYAGE_V2_ENABLED=false` (default) do not need re-indexing.

---

## Technical Analysis

### What Was Fixed Today (January 30, 2026)

1. **Entity Dataclass**: Added `embedding_v2: Optional[List[float]]` property
   - File: `app/hybrid_v2/services/neo4j_store.py`
   - Before: Entity only had `embedding` property
   - After: Entity has both `embedding` (V1/OpenAI) and `embedding_v2` (V2/Voyage)

2. **Vector Index**: Created `entity_embedding_v2` index for 2048-dimensional Voyage embeddings
   - Index name: `entity_embedding_v2`
   - Dimension: 2048 (Voyage voyage-context-3)
   - Property: `embedding_v2`
   - Before: Only `entity_embedding` index existed (3072d for OpenAI)

3. **Strategy 6 Integration**: Vector similarity now matches embedding dimensions
   - Auto-detects query embedding dimension (2048d vs 3072d)
   - Selects correct index (`entity_embedding_v2` vs `entity_embedding`)
   - Enables semantic fallback when exact/alias/substring matching fails

### Indexing Pipeline Verification

**API Endpoint:** `/hybrid/index/documents`

**Code Path:**
```
app/routers/hybrid.py::hybrid_index_documents()
  ↓
app/routers/hybrid.py::_run_indexing_job()
  ↓
app/hybrid_v2/indexing/pipeline_factory.py::get_lazygraphrag_indexing_pipeline_v2()
  ↓
app/hybrid_v2/indexing/lazygraphrag_pipeline.py::LazyGraphRAGIndexingPipeline(
    use_v2_embedding_property=True  ✅ CORRECT
)
```

**Factory Code (Line 121 of pipeline_factory.py):**
```python
_indexing_pipeline_v2 = LazyGraphRAGIndexingPipeline(
    neo4j_store=store,
    llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
    embedder=embedder,
    config=config,
    use_v2_embedding_property=True,  # ✅ This is CORRECT
)
```

**Chunk Embeddings (Line 547 of lazygraphrag_pipeline.py):**
```python
if self.use_v2_embedding_property:
    chunk.embedding_v2 = emb  # ✅ CORRECT
else:
    chunk.embedding = emb
```

**Entity Embeddings - LlamaIndex Extractor (Line 716):**
```python
if self.use_v2_embedding_property:
    ent.embedding_v2 = emb  # ✅ CORRECT
else:
    ent.embedding = emb
```

**Entity Embeddings - Native Extractor (Line 987):**
```python
if self.use_v2_embedding_property:
    ent.embedding_v2 = emb  # ✅ CORRECT
else:
    ent.embedding = emb
```

**Verdict:** ✅ All code paths correctly use `embedding_v2` when V2 flag is set.

---

## What Needs Re-indexing?

### Scenario 1: Documents Indexed with V1 (Default)
**Environment:** `VOYAGE_V2_ENABLED=false` or unset (default)
**Embedder:** OpenAI `text-embedding-3-large` (3072d)
**Storage:**
- TextChunk: `embedding` property (3072d)
- Entity: `embedding` property (3072d)
- Index: `chunk_embedding` (3072d), `entity_embedding` (3072d)

**Re-indexing Required?** ❌ **NO**
- Reason: V1 pipeline stores in `embedding` property (correct behavior)
- Strategy 6: Auto-selects `entity_embedding` index (3072d matches 3072d query)
- Status: Working correctly

### Scenario 2: Documents Indexed with V2 BEFORE Today's Fix
**Environment:** `VOYAGE_V2_ENABLED=true`
**Embedder:** Voyage `voyage-context-3` (2048d)
**Storage (BEFORE fix):**
- TextChunk: `embedding` property (2048d) ❌ WRONG PROPERTY
- Entity: `embedding` property (2048d) ❌ WRONG PROPERTY
- Problem: 2048d embeddings stored in 3072d index

**Re-indexing Required?** ✅ **YES**
- Reason: Embeddings stored in wrong property before dataclass fix
- Impact: Strategy 6 vector similarity fails (dimension mismatch)
- Solution: Re-index to populate `embedding_v2` property

### Scenario 3: Documents Indexed with V2 AFTER Today's Fix
**Environment:** `VOYAGE_V2_ENABLED=true`
**Embedder:** Voyage `voyage-context-3` (2048d)
**Storage (AFTER fix):**
- TextChunk: `embedding_v2` property (2048d) ✅ CORRECT
- Entity: `embedding_v2` property (2048d) ✅ CORRECT
- Index: `chunk_embedding_v2` (2048d), `entity_embedding_v2` (2048d)

**Re-indexing Required?** ❌ **NO**
- Reason: Pipeline now stores in correct property
- Strategy 6: Auto-selects `entity_embedding_v2` index (2048d matches 2048d query)
- Status: Working correctly

---

## Re-indexing Decision Matrix

| Scenario | `VOYAGE_V2_ENABLED` | Indexed When? | Re-index? | Why? |
|:---------|:-------------------|:--------------|:----------|:-----|
| **1. V1 Production** | `false` (default) | Anytime | ❌ NO | V1 pipeline always correct |
| **2. V2 Test (before fix)** | `true` | Before Jan 30 | ✅ YES | Entity embeddings in wrong property |
| **3. V2 Test (after fix)** | `true` | After Jan 30 | ❌ NO | Fixed pipeline stores correctly |
| **4. V1 → V2 Migration** | Changing to `true` | N/A | ✅ YES | Must re-index with V2 pipeline |

---

## Re-indexing Commands

### Check If Re-indexing Is Needed

```cypher
// Check Entity embedding coverage
MATCH (e:Entity {group_id: $group_id})
RETURN 
  count(e) as total_entities,
  count(e.embedding) as has_v1_embedding,
  count(e.embedding_v2) as has_v2_embedding,
  size([x IN collect(e.embedding) WHERE x IS NOT NULL | 1]) as v1_count,
  size([x IN collect(e.embedding_v2) WHERE x IS NOT NULL | 1]) as v2_count
```

**Interpretation:**
- If `v2_count = 0` and `VOYAGE_V2_ENABLED=true` → **RE-INDEX REQUIRED**
- If `v2_count > 0` and `VOYAGE_V2_ENABLED=true` → **Already fixed (indexed after fix)**
- If `v1_count > 0` and `VOYAGE_V2_ENABLED=false` → **No action needed**

### Re-index via API

```bash
# Set V2 mode in .env
export VOYAGE_V2_ENABLED=true
export VOYAGE_API_KEY=your_key_here

# Call indexing API with reindex=true
curl -X POST "http://localhost:8000/hybrid/index/documents" \
  -H "X-Group-ID: your_tenant_id" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": ["https://example.com/doc.pdf"],
    "reindex": true,
    "ingestion": "document-intelligence",
    "run_community_detection": false,
    "run_raptor": false
  }'

# Poll status
curl "http://localhost:8000/hybrid/index/status/{job_id}"
```

### Re-index via Script

```bash
# Use the test indexing script
cd /afh/projects/graphrag-orchestration/scripts

# Ensure .env has V2 enabled
# VOYAGE_V2_ENABLED=true
# VOYAGE_API_KEY=pa-xxx

python index_5pdfs_v2_local.py --reindex
```

---

## Validation After Re-indexing

### 1. Check Entity Embedding Coverage

```cypher
MATCH (e:Entity {group_id: $group_id})
WHERE e.embedding_v2 IS NOT NULL
RETURN count(e) as entities_with_v2_embedding
```

**Expected:** Should match total entity count (100% coverage)

### 2. Test Vector Similarity (Strategy 6)

```python
from app.services.async_neo4j_service import AsyncNeo4jService

neo4j_service = AsyncNeo4jService(...)
await neo4j_service.initialize()

# Get query embedding (Voyage 2048d)
query_embedding = get_query_embedding("Invoice")  # Returns 2048d vector

# Test vector similarity
entities = await neo4j_service.get_entities_by_vector_similarity(
    query_embedding=query_embedding,
    group_id="test_tenant",
    top_k=10,
    # index_name auto-detected as "entity_embedding_v2" based on dim=2048
)

print(f"Found {len(entities)} entities via vector similarity")
# Expected: > 0 entities with cosine similarity >= 0.7
```

### 3. Test Route 4 DRIFT End-to-End

```bash
# Query that requires vector fallback
curl -X POST "http://localhost:8000/hybrid/query" \
  -H "X-Group-ID: your_tenant_id" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Find inconsistencies between invoice details and contract terms",
    "route": "drift"
  }'
```

**Success Indicators:**
- Seed entities resolved: > 0 (check logs for "Strategy 6" success)
- Evidence chunks: > 0 (PPR traversal succeeded)
- Citations: Multiple documents cited
- No hallucination (LLM doesn't make up facts)

---

## Timeline & Rollout

### Phase 1: Test Environment Re-indexing (Immediate)
- [ ] Re-index test documents with V2 pipeline
- [ ] Validate entity `embedding_v2` coverage (100%)
- [ ] Test Strategy 6 vector similarity
- [ ] Test Route 4 DRIFT with generic query terms

### Phase 2: Production V1 Validation (No Action)
- [ ] Verify V1 production documents have correct `embedding` property
- [ ] Confirm `entity_embedding` index working (3072d)
- [ ] No re-indexing required for V1 environments

### Phase 3: V2 Production Rollout (Future)
- [ ] Set `VOYAGE_V2_ENABLED=true` in production
- [ ] Re-index all documents with V2 pipeline
- [ ] Validate `embedding_v2` coverage
- [ ] Monitor query quality (should improve with Strategy 6)

---

## Cost Analysis

### Re-indexing Costs (V2 Voyage Embeddings)

**Assumptions:**
- 1000 documents
- Average 10 chunks per document = 10,000 chunks
- Average 50 entities per document = 50,000 entities

**Voyage API Costs:**
- Chunk embeddings: 10,000 × $0.00012/token × 500 tokens = **$0.60**
- Entity embeddings: 50,000 × $0.00012/token × 50 tokens = **$3.00**
- **Total:** ~$3.60 per 1000 documents

**Azure DI Costs (if using document-intelligence ingestion):**
- Layout extraction: 1000 pages × $0.01/page = **$10.00**
- Total: ~$13.60 per 1000 pages

**Time Estimate:**
- Indexing throughput: ~20-30 documents/minute
- 1000 documents: ~30-50 minutes

---

## Conclusion

**✅ No Code Bugs Found**
- Indexing pipeline correctly uses `embedding_v2` when `use_v2_embedding_property=True`
- Both chunk and entity embeddings store in correct property
- All 3 extraction paths verified: chunks, LlamaIndex entities, native entities

**📋 Action Items**

1. **V1 Users (Default)**: ❌ No action required
2. **V2 Test Users (before fix)**: ✅ Re-index with `VOYAGE_V2_ENABLED=true`
3. **V2 Test Users (after fix)**: ✅ Verify `embedding_v2` coverage, no re-indexing needed
4. **V2 Production Rollout**: 📅 Plan re-indexing during next maintenance window

**🎯 Priority**: **Medium** - Only affects V2 test environments. V1 production unaffected.

---

## Related Documents

- `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` - Section 8.1 (6-Strategy Seed Resolution)
- `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` - Section 8.2 (Semantic Beam Search)
- `VOYAGE_V2_IMPLEMENTATION_PLAN_2026-01-25.md` - V2 migration plan
- Commit: `fix(V2): Entity embeddings now properly use embedding_v2 property`
- Commit: `feat(Route4): Use semantic beam search for query-aligned traversal`
- Commit: `docs: Update architecture with semantic beam search and 6-strategy seed resolution`
