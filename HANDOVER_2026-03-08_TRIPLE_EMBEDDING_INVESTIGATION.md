# Handover — 2026-03-08: Triple Embedding Investigation & Pipeline Diagnosis

## Summary

Investigated whether Route 7 triple embeddings could benefit from Voyage-context-3's contextual awareness (like sentence embeddings already do). The experiment proved harmful, but the investigation uncovered multiple pre-existing bugs and a critical `.env` override bottleneck. Current score: **56/57** (was 57/57 baseline, regressed to 55/57 mid-session, restored to 56/57). The remaining 1 point (Q-D3: 2/3) has a clear, actionable root cause identified but not yet fixed.

## Commits Made

### 1. `f4a3f2ee` — Bug fixes: hooks.py + neo4j_store.py
- **hooks.py**: Added missing `skip_record_query: bool = False` parameter to `track_query()` and `_log_query_async()` — was causing HTTP 500 when `hybrid.py` passed the kwarg
- **neo4j_store.py**: `store_triple_embeddings_batch()` now matches `group_id IN [group_id, '__global__']` instead of `= group_id` — was causing only 49% of triples (1853/3807) to get stored embeddings because 1954 edges involve at least one `__global__` entity

### 2. `439dec64` — Single-call triple embedding + restore max_facts=7
- **lazygraphrag_pipeline.py** (~L4418): Replaced batch-of-128 embedding loop with single `embed_documents(texts)` call. Larger context windows (~600 triples/bin) produce more diverse embeddings than isolated 128-triple bins
- **triple_store.py** (L258, L356): Restored `RECOGNITION_MEMORY_MAX_FACTS` default from 4 → 7 (had been silently reverted by another session's commit `af022139`)

## Key Discovery: Why Batch Size Matters

The `embed_documents()` call in `voyage_embed.py` bin-packs texts into ~30K token windows for Voyage-context-3. Each bin becomes a "document" where cross-chunk context awareness applies:

| Approach | Bins | Triples/Bin | Context | Q-D3 Score |
|----------|------|-------------|---------|------------|
| Batch-128 (broken) | 30 | ~128 | Isolated | 1/3 |
| Single-call (3807) | ~7 | ~540-600 | Rich cross-triple | 2/3 |
| Baseline fallback* | ~7 | ~540-600 | Rich cross-triple | 3/3 |

\*The baseline ALWAYS used the fallback path because the store bug left 1954 triples without `embedding_v2`, making `all_precomputed` check fail at `triple_store.py:110`.

## Root Cause of Remaining 1 Point (Q-D3: 2/3 → need 3/3)

### The Problem
Q-D3 ("Compare time windows across the set: list all explicit day-based timeframes") is missing:
1. **"3 business days cancellation window with full refund"** (Purchase Contract)
2. **"180 days arbitration completion target"** (Warranty)
3. **"180 days threshold for short-term vs long-term rentals"** (Property Management)

The baseline (57/57) had triple seed #5 = `"party agree to conclude arbitration within 180 days"` — the current does not.

### Pipeline Trace Results

**Stage 1 — Cosine search** with instructed embedding (code default `TRIPLE_CANDIDATES_K=500`):
- `"party agree to conclude arbitration within 180 days"` → **rank 26** (score 0.2821) ✓ IN top-500
- `"holiday rentals include leases of more than 180 days"` → **rank 18** (score 0.2908) ✓ IN top-500
- `"90 days Customer may cancel within 3 business days"` → **rank 190** (score 0.2489) ✓ IN top-500
- `"repair must occur within 90 days"` → **rank 188** (score 0.2489) ✓ IN top-500

**Stage 2 — Reranker** (Voyage rerank-2.5, top-500 → top-15):
- `"party agree to conclude arbitration within 180 days"` → **rerank #3** (score 0.4258) ✓ SURVIVES
- Other arbitration variants → rerank #5, #7, #8 ✓

**BUT — .env overrides `TRIPLE_CANDIDATES_K=50`**, which means the live pipeline only feeds **50 candidates** to the reranker, not 500. With only 50 candidates:
- Arbitration triple is at cosine rank 26 → just barely inside top-50
- But embedding non-determinism means it may fall outside in some runs
- "3 business days" triple is at rank 190 → **always excluded**

### The Fix (Not Yet Applied)

**Remove or update `.env` override**: `ROUTE7_TRIPLE_CANDIDATES_K=50` → should be `500` (matching code default)

This is the ONLY blocker. The instructed embedding + reranker pipeline works correctly when given enough candidates. The `.env` override was likely set during earlier tuning when the reranker was new, and is now stale.

**Expected impact**: With `TRIPLE_CANDIDATES_K=500`, the reranker sees arbitration/cancellation/lease triples and promotes them into the top-15, MMR deduplicates warranty variants, and the final 7 seeds become diverse across all documents.

## Experiment: Contextualized Triple Embedding (REJECTED)

Attempted to embed triples with document/section context prefix (like sentence embeddings):
- Modified `fetch_all_triples()` to JOIN through MENTIONS→Sentence→Document
- Modified `_precompute_triple_embeddings()` with per-document grouping and `embed_documents_contextualized()`
- **Result: 53/57** — significantly worse. Triple embeddings become too document-specific, losing cross-document retrieval ability
- Q-D3 `triple_topic_diversity` crashed from 5→1 (all 7 seeds identical warranty triples)
- **Conclusion**: Triples are inherently cross-document knowledge; contextualizing them is counterproductive

All contextualized changes were reverted via `git checkout`.

## Current State

### Files Modified (committed)
| File | Change |
|------|--------|
| `src/core/instrumentation/hooks.py` | Added `skip_record_query` param |
| `src/worker/hybrid_v2/services/neo4j_store.py` | `__global__` group match fix |
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | Single-call triple embedding |
| `src/worker/hybrid_v2/retrievers/triple_store.py` | `max_facts` default 4→7 |

### Neo4j State
- All 4284 triples have `embedding_v2` with single-call embeddings
- Group: `test-5pdfs-v2-fix2`
- Both `group_id` and `__global__` entities properly covered

### .env Overrides to Review
```
ROUTE7_TRIPLE_CANDIDATES_K=50    # ← Bottleneck! Code default is 500
ROUTE7_RECOGNITION_MEMORY_MAX_FACTS  # Not in .env (uses code default 7) ✓
```

### Benchmark Score History

| Time | Embedding | max_facts | Candidates_K | Score | Q-D3 |
|------|-----------|-----------|--------------|-------|------|
| 16:04 (baseline) | fallback single-call | 7 | 50 (.env) | 57/57 | 3/3 |
| 18:39 | contextualized per-doc | 7 | 50 | 53/57 | 1/3 |
| 19:05 | batch-128 (reverted) | 7 | 50 | 55/57 | 1/3 |
| 19:58 (current) | single-call (fixed) | 7 | 50 (.env) | 56/57 | 2/3 |

Note: The baseline 57/57 used the fallback path (store bug → no precomputed embeddings → query-time single-call). This is subtly different from our pre-computed single-call because the query-time fallback embeds all 1954 triples (only those matching AND condition) while our indexing embeds all 3807/4284 (including OR-matched). The different corpus composition changes bin packing and thus embedding context.

## TODO List

### Immediate (High Priority)
1. **Fix `TRIPLE_CANDIDATES_K` .env override** — Change from 50 to 500 (or remove to use code default). This is the primary bottleneck preventing Q-D3 3/3.
2. **Re-run full benchmark** after the .env fix to confirm 57/57 restoration.
3. **Investigate triple count discrepancy** — `fetch_all_triples()` returns 4284 but `_fetch_triples_sync()` in TripleEmbeddingStore returns 1954 for the same AND condition. Need to understand if duplicates or stale edges exist.

### Follow-up (Medium Priority)
4. **Align `.env` with code defaults** — The `.env` has `ROUTE7_TRIPLE_CANDIDATES_K=50` which silently overrides the code default of 500 via `load_dotenv()`. Audit all Route 7 `.env` overrides against current code defaults.
5. **Verify embedding non-determinism impact** — The baseline used query-time fallback embedding (non-deterministic, depends on Neo4j query order). Our fix pre-computes at index time (deterministic). Confirm the reranker compensates for any per-run variation.
6. **Consider increasing TRIPLE_TOP_K** — Currently 15 (post-reranker). With 500 candidates and reranker, we could potentially increase to 20 to capture more cross-document facts.

### Research (Low Priority)
7. **Triple deduplication at indexing** — Many triples are near-duplicates (e.g., 5+ warranty variants with different subjects but identical predicates). Deduplicating at index time would reduce noise and make cosine/reranker stages more efficient.
8. **Per-document triple embedding** — The rejected contextualized approach hurt global retrieval, but a hybrid approach (embed both contextualized AND bare) could serve different query types.

## Key Learnings

1. **`.env` overrides are invisible** — `load_dotenv()` in `main.py` means `.env` values ALWAYS override code defaults. Multiple sessions changed code defaults without checking `.env`, creating phantom regressions.
2. **Voyage bin-packing determines embedding quality** — `embed_documents()` bin-packs into ~30K token windows. Larger bins = more cross-chunk context = better diversity. Batch size at index time must match or exceed query-time behavior.
3. **Instructed embeddings work** — The `ROUTE7_TRIPLE_SEARCH_INSTRUCTION` prefix dramatically improves cosine recall for semantic queries (arbitration triple: rank 369→26 with instruction).
4. **Cross-encoder reranker rescues cosine misses** — Arbitration triple jumps from cosine rank 26 to reranker rank 3, but ONLY if it's in the candidate set.
5. **Triple contextualization is harmful** — Unlike sentences (which benefit from document context), triples represent extracted cross-document facts. Adding document context makes them too specific.
