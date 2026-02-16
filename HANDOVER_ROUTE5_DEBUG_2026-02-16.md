# Route 5 (Unified Search) — Debug Handover

**Date:** 2026-02-16  
**Branch:** `main`  
**Latest commit:** `19b1e924` — *Fix Route 5 sentence search: move group_id filter to post-search WHERE*  
**Git state:** Clean (no uncommitted changes)

---

## 1. What Was Done Today

### Route 5 Implementation (commits `d27dcb31` → `19b1e924`)
- Closed gaps in Route 5: removed lazy community fallback, added `_ensure_embeddings()`, wired router weight profiles
- Added `UNIFIED_SEARCH` to `RouteEnum` in `src/api_gateway/routers/hybrid.py`
- Added `--force-route` CLI arg to `scripts/benchmark_route3_global_search.py`
- Ran Route 3 vs Route 5 benchmark with Q-G questions

### Cypher Bug Found & Fixed (`19b1e924`)
**Root cause:** The `sentence_embeddings_v2` Neo4j vector index has NO additional filterable properties.
The Cypher SEARCH clause had `group_id` as an inline WHERE filter, which requires it to be an indexed additional property. This caused `Neo.ClientError.Statement.PropertyNotFound`, silently caught by the try/except returning empty results.

**File:** `src/worker/hybrid_v2/routes/route_5_unified.py` (lines ~539-541)

```cypher
-- BEFORE (broken):
SEARCH sent IN (VECTOR INDEX sentence_embeddings_v2 FOR $embedding WHERE sent.group_id = $group_id LIMIT $top_k)
SCORE AS score
WHERE score >= $threshold

-- AFTER (fixed):
SEARCH sent IN (VECTOR INDEX sentence_embeddings_v2 FOR $embedding LIMIT $top_k)
SCORE AS score
WHERE sent.group_id = $group_id AND score >= $threshold
```

### Deployment
- **Worker** deployed: revision `azd-1771251841` (but worker is NOT used for queries)
- **API Gateway** deployed: revision `azd-1771253499` (Healthy, 100% traffic)
- ACR image `azd-deploy-1771251838` verified to contain the fix via `az acr run` grep
- `GROUP_ID_OVERRIDE=test-5pdfs-v2-fix2` is set on API container

### Test Results
- **Unit tests:** 160 pass, 27 skipped
- **Settings fix:** Added `ROUTE3_SENTENCE_RERANK` and `ROUTE4_WORKFLOW` to `app/core/config.py` to prevent Pydantic validation errors from `.env`

---

## 2. Current Status — Two Unresolved Bugs

### Bug A: Benchmark vs Direct API Discrepancy (Critical)

**Symptom:** Direct `curl`/Python API calls return real Route 5 answers, but the benchmark script returns "not found" for the same queries on the same endpoint.

| Test Method | Q-G6 Result | Latency |
|---|---|---|
| Direct `curl` POST to API | **Real answer** (property management agreement details) | ~12.2 s |
| Benchmark script (`benchmark_route3_global_search.py --force-route unified_search`) | "not found" | ~1.8 s |

**Key observations:**
- Same API endpoint, same group_id (GROUP_ID_OVERRIDE), same single replica, same revision
- Benchmark latencies are suspiciously fast (1.8-2.0 s) vs direct test (12-20 s). A real Route 5 query involves NER + sentence search + community match + PPR + synthesis — impossible in 1.8 s
- Q-G6 benchmark: run0=2081ms, run1=1834ms, run2=1840ms — ALL fail. Not just subsequent runs
- Direct test uses `group_id` in body (ignored by Pydantic) + `Authorization` header
- Benchmark uses `X-Group-ID` header + `Authorization` header, `force_route` in JSON body

**Hypothesis:** The `X-Group-ID` header might be interfering despite `GROUP_ID_OVERRIDE`, OR auth middleware might be routing to a different code path. The fast latency strongly suggests the request is being short-circuited before reaching Route 5 `execute()`.

**Investigation state — what was checked:**
1. `force_route()` in `orchestrator.py` line 2192 — READ ✅. Code path is clean: `QueryRoute.UNIFIED_SEARCH` is in `_route_handlers`, handler's `execute()` is called correctly
2. `_get_or_create_pipeline()` in `hybrid.py` — READ ✅. Pipeline cache keyed by `{group_id}:{profile}`
3. Single revision confirmed: `graphrag-api--azd-1771253499` with 100% traffic
4. No response caching found (only pipeline instance cache, not query result cache)

**Next steps for Bug A:**
- **Test locally** — run the API server with `.env.local` and hit it with both direct curl and the benchmark script to reproduce
- Check if the benchmark's `X-Group-ID` header fights with `GROUP_ID_OVERRIDE` causing a different pipeline cache key
- Add debug logging or print the actual `group_id` and `route` that the endpoint handler receives from the benchmark
- Check if the 1.8 s latency means the request is hitting a 410 (deprecated route) or exception path. Check `stderr`/response body from the benchmark more carefully

### Bug B: Q-G3 Returns "Not Found" Even in Direct Test

**Symptom:** Q-G3 ("What is the total purchase price and how is it broken down?") returns "not found" even via direct API call (20 s latency — so Route 5 IS executing, just finding no evidence).

**Q-G3 expected terms:** `["29900", "25%", "10%", "installment", "commission", "$75", "$50", "tax"]`

**Hypothesis:** This may be a legitimate retrieval gap — the query is about purchase price breakdowns which might not produce enough NER entities or community matches to seed PPR effectively. Could also be:
- Sentence search finds results but all below threshold (`ROUTE5_SENTENCE_THRESHOLD=0.2`)
- PPR seeds resolve to zero entities
- Negative detection fires: `not ppr_evidence and not sentence_evidence` (line ~310)

**Next steps for Bug B:**
- Run locally with `ROUTE5_RETURN_TIMINGS=1` and verbose logging to see which step produces zero results
- Test if lowering `ROUTE5_SENTENCE_THRESHOLD` helps
- Compare Route 3 output for Q-G3 (Route 3 gets 40% theme coverage baseline)

---

## 3. Files Modified This Session

| File | Change |
|---|---|
| `src/worker/hybrid_v2/routes/route_5_unified.py` | Cypher fix: moved `group_id` from inline SEARCH WHERE to post-search WHERE |
| `graphrag-orchestration/app/core/config.py` | Added `ROUTE3_SENTENCE_RERANK` and `ROUTE4_WORKFLOW` fields |
| `tests/unit/test_community_materialization.py` | Fixed async mock + missing attributes (5 test fixes) |
| `scripts/benchmark_route3_global_search.py` | Added `--force-route` flag with `unified_search` option |
| `scripts/benchmark_route3_thematic.py` | Added `--force-route` flag |
| `src/api_gateway/routers/hybrid.py` | Added `UNIFIED_SEARCH` to `RouteEnum` |

---

## 4. How to Test Locally

### Start the API server
```bash
cd /afh/projects/graphrag-orchestration

# Load local env (has Neo4j, OpenAI, Voyage credentials)
set -a && source .env.local && set +a

# Add group_id override
export GROUP_ID_OVERRIDE=test-5pdfs-v2-fix2

# Enable Route 5 timing diagnostics
export ROUTE5_RETURN_TIMINGS=1

# Start FastAPI server
uvicorn src.api_gateway.main:app --host 0.0.0.0 --port 8000
```

### Direct query test (should work)
```bash
curl -s -X POST http://localhost:8000/hybrid/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the roles and responsibilities of each party involved in the property management agreement?",
    "force_route": "unified_search",
    "response_type": "summary"
  }' | python3 -m json.tool
```

### Benchmark test (reproduces Bug A)
```bash
python3 scripts/benchmark_route3_global_search.py \
  --url http://localhost:8000 \
  --force-route unified_search \
  --repeats 1 \
  --max-questions 3
```

### Compare: are the payloads identical?
The benchmark sends:
```json
{
  "query": "...",
  "force_route": "unified_search",
  "response_type": "summary"
}
```
With headers: `Content-Type: application/json`, `X-Group-ID: test-5pdfs-v2-fix2`, `Authorization: Bearer <jwt>`

The direct test sends the same payload (no `X-Group-ID` header, no auth when local `AUTH_TYPE=none`).

**Key difference when deployed:** Auth middleware extracts `group_id` from JWT `groups[0]`, which might differ from `GROUP_ID_OVERRIDE` pipeline cache key.

---

## 5. Architecture Context

### Request Flow
```
Client → API Gateway (FastAPI, in-process) → /hybrid/query endpoint
  → force_route handler (hybrid.py:489-510)
    → _get_or_create_pipeline(group_id) → pipeline cache
    → pipeline.force_route(query, QueryRoute.UNIFIED_SEARCH)
      → _route_handlers[UNIFIED_SEARCH] → UnifiedSearchHandler.execute()
        → Parallel: NER + Sentence search + Community match
        → Seed resolution → Weighted PPR → Synthesis
```

### Key env vars for Route 5
| Variable | Default | Purpose |
|---|---|---|
| `ROUTE5_SENTENCE_TOP_K` | 30 | Max sentence vector search results |
| `ROUTE5_PPR_TOP_K` | 30 | Max PPR evidence nodes |
| `ROUTE5_SENTENCE_THRESHOLD` | 0.2 | Min cosine similarity for sentence hits |
| `ROUTE5_WEIGHT_PROFILE` | balanced | Seed weighting profile |
| `ROUTE5_RETURN_TIMINGS` | 0 | Include step timings in response metadata |
| `ROUTE5_SENTENCE_RERANK` | 1 | Enable Voyage reranking of sentences |
| `ROUTE5_RERANK_TOP_K` | 15 | Top-K after reranking |
| `ROUTE5_PPR_PER_SEED_LIMIT` | 50 | Max nodes per PPR seed |
| `ROUTE5_PPR_PER_NEIGHBOR_LIMIT` | 20 | Max neighbors per PPR node |

---

## 6. Deployment Info

| Resource | Value |
|---|---|
| Resource Group | `rg-graphrag-feature` |
| Region | Sweden Central |
| Subscription | `3adfbe7c-9922-40ed-b461-ec798989a3fa` |
| ACR | `graphragacr12153` |
| API Container App | `graphrag-api` |
| Worker Container App | `graphrag-worker` |
| API URL | `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io` |
| Token Scope | `api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default` |
| Active API Revision | `graphrag-api--azd-1771253499` |
| Group ID Override | `test-5pdfs-v2-fix2` |

---

## 7. TODO for Next Session

### Priority 1: Reproduce & Fix Bug A (Benchmark Discrepancy)
- [ ] Run API locally with `.env.local` + `GROUP_ID_OVERRIDE` + `AUTH_TYPE=none`
- [ ] Test direct curl to `localhost:8000/hybrid/query` with `force_route=unified_search` — expect real answer
- [ ] Run benchmark script against `localhost:8000` — expect same "not found" bug
- [ ] Add debug print/logging in `hybrid.py` endpoint handler to log exact `group_id`, `body.force_route`, and pipeline cache key
- [ ] Check if `X-Group-ID` header creates a different group_id than `GROUP_ID_OVERRIDE` (middleware order issue?)
- [ ] Check if the 1.8 s response indicates an exception being caught and returned as "not found"
- [ ] Read the `except Exception` block at end of `/hybrid/query` endpoint — does it return a dict with `response` key or just error?

### Priority 2: Fix Bug B (Q-G3 No Evidence)
- [ ] Run Q-G3 locally with `ROUTE5_RETURN_TIMINGS=1` — check which step returns zero results
- [ ] Check sentence search results for Q-G3 query (are there any above threshold?)
- [ ] Check NER output for Q-G3 — what entities are extracted?
- [ ] If sentence search returns 0 hits, try lowering `ROUTE5_SENTENCE_THRESHOLD` from 0.2 to 0.1
- [ ] Compare Route 3 output for Q-G3 to understand what evidence Route 3 finds that Route 5 misses

### Priority 3: Re-run Benchmark After Fixes
- [ ] Run full Route 5 benchmark locally first (all Q-G questions)
- [ ] Compare Route 5 vs Route 3 theme coverage
- [ ] If local passes, redeploy to Azure and run remote benchmark
- [ ] Commit and push any fixes

---

## 8. Benchmark Results So Far

| Scenario | Avg Theme Coverage | Failing Queries | Notes |
|---|---|---|---|
| Route 3 baseline | 40% | None | All 10 Q-G questions answered |
| Route 5 (pre-fix) | 42% | Q-G3, Q-G6, Q-G10 ("not found") | Cypher bug: inline WHERE on unindexed property |
| Route 5 (post-fix, direct API test) | Working for Q-G6 (12s), Q-G10 (20s) | Q-G3 still "not found" | Cypher fix confirmed |
| Route 5 (post-fix, benchmark) | Same as pre-fix | Q-G3, Q-G6, Q-G10 still "not found" | Bug A — benchmark discrepancy |

Benchmark result files in `benchmarks/`:
- Route 3 baseline: `route3_global_search_20260216T125815Z.json`
- Route 5 runs: `route5_global_search_20260216T130120Z.json` through `...T151646Z.json` (multiple attempts, all same failure)
