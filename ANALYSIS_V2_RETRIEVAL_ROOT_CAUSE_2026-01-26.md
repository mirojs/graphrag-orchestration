# V2 Retrieval Root Cause Analysis - 2026-01-26

## Problem Statement

V2 (Voyage embeddings) achieved 83% theme coverage on Q-G10 vs V1 (OpenAI) at 100%, specifically missing the "scope of work" theme from purchase_contract.pdf EXHIBIT A chunks (1 and 3).

## Investigation Summary

### Initial Hypothesis (INCORRECT)
"Voyage embeddings rank EXHIBIT A chunks lower for generic summary queries compared to explicit queries."

This was unconvincing because:
- Explicit "EXHIBIT A" query successfully retrieved all 4 chunks (0,1,2,3)
- But document summary query only retrieved chunks 0,2
- Same embedding model should show consistent behavior

### Root Cause (CORRECT)

**The V2 group was indexed with V1 pipeline that stored OpenAI 3072D embeddings in `embedding` property, not Voyage 2048D embeddings in `embedding_v2` property.**

#### How It Happened

1. **V2 Group Creation**: `test-5pdfs-v2-1769440005` was indexed via `/hybrid/index/documents` API endpoint

2. **V1 Pipeline Used**: The endpoint called:
   ```python
   from app.hybrid.indexing.lazygraphrag_indexing_pipeline import (
       get_lazygraphrag_indexing_pipeline,  # V1 factory
   )
   pipeline = get_lazygraphrag_indexing_pipeline()
   ```

3. **V1 Factory Default**: The V1 factory creates pipeline with:
   - `embedder=llm_service.embed_model` → OpenAI text-embedding-3-large (3072D)
   - `use_v2_embedding_property=False` (default) → stores in `embedding` property
   - Creates `chunk_embedding` index (V1)

4. **Query-Time Mismatch**: When V2 queries executed:
   ```python
   # Query embedding
   query_embedding = get_query_embedding(query)  # Returns Voyage 2048D
   
   # Index selection
   index_name = get_vector_index_name()  # Returns "chunk_embeddings_v2"
   
   # Vector search
   db.index.vector.queryNodes(index_name, k, query_embedding)  # Searches embedding_v2 property
   ```

5. **The Problem**:
   - Chunks have: `embedding` = OpenAI 3072D
   - Chunks missing: `embedding_v2` = Voyage 2048D
   - Query searches: `chunk_embeddings_v2` index for `embedding_v2` property
   - **Result**: Vector search returns no results or wrong results due to dimension/property mismatch

#### Why Explicit EXHIBIT A Query Worked

The explicit query "What is in EXHIBIT A?" likely succeeded due to BM25 text matching:
- BM25 component matched "EXHIBIT A" text directly in chunks 1 and 3
- Vector component may have failed silently or contributed less
- RRF fusion combined results, giving good coverage

For the document summary query:
- Generic query "Summarize each document's main purpose" 
- BM25 matched general terms in longer narrative chunks (0, 2)
- Vector component failed to find EXHIBIT A chunks due to missing `embedding_v2`
- Result: Only chunks 0, 2 retrieved, missing 1, 3

## The Fix

Changed `/hybrid/index/documents` endpoint to use V2 pipeline:

```python
from app.hybrid_v2.indexing.lazygraphrag_indexing_pipeline import (
    get_lazygraphrag_indexing_pipeline_v2,  # V2 factory
)
pipeline = get_lazygraphrag_indexing_pipeline_v2()
```

V2 factory (`get_lazygraphrag_indexing_pipeline_v2`):
- Checks `is_voyage_v2_enabled()` → uses Voyage embeddings when true
- Sets `use_v2_embedding_property=True` → stores in `embedding_v2` property
- Uses `VOYAGE_EMBEDDING_DIM=2048` dimensions
- Creates `chunk_embeddings_v2` index

## Impact

After fix and re-indexing:
- V2 chunks will have `embedding_v2` with Voyage 2048D embeddings
- V2 queries will find chunks via proper vector search
- Should achieve 100% theme coverage matching V1 performance

## Files Changed

- `app/routers/hybrid.py`: Import and use `get_lazygraphrag_indexing_pipeline_v2()`

## Commit

```
commit 8217cd1
fix: Use V2 indexing pipeline in hybrid router when V2 enabled
```

## Verification Steps

1. Deploy fix ✓ (in progress)
2. Re-index V2 group with correct pipeline
3. Run Route 3 benchmark
4. Verify 100% theme coverage on Q-G10

## Lessons Learned

1. **Always verify end-to-end consistency**: Query embeddings must match indexed embeddings
2. **Don't accept "expected behavior" without investigation**: The user was right to challenge
3. **Check factory functions carefully**: Subtle differences in pipeline creation can cause major issues
4. **Use property naming conventions**: `embedding_v2` makes parallel V1/V2 operation possible
5. **Vector search fails silently**: Missing properties don't always throw errors, just return no results

## Related Documents

- `VOYAGE_V2_IMPLEMENTATION_PLAN_2026-01-25.md`: V2 architecture design
- `app/hybrid_v2/indexing/lazygraphrag_pipeline.py`: Pipeline with `use_v2_embedding_property` flag
- `app/hybrid_v2/orchestrator.py`: V2-aware `get_query_embedding()` and `get_vector_index_name()`
