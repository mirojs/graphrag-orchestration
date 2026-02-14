# Route 2 Latency Investigation & Improvement Plan

**Date:** 2026-02-14  
**Objective:** Investigate the Route 2 latency regression (reported 10.2s avg in HANDOVER_2026-02-12, target ≤5s), identify root causes, and plan improvements.  
**Benchmark:** `route2_local_search_20260214T065835Z.json`  
**Group:** `test-5pdfs-v2-fix2`

---

## 1. Current Latency Profile (Feb 14 Benchmark)

| Metric | Value |
|---|---|
| **Positive avg (Q-L1–Q-L10)** | **7,295 ms** |
| Positive avg excl. Q-L1 cold start | **6,096 ms** |
| Positive min | 4,606 ms (Q-L5) |
| Positive max | 18,078 ms (Q-L1, cold start) |
| Negative avg (Q-N1–Q-N10) | 3,880 ms |
| All questions avg | 5,677 ms |
| **Target** | **≤5,000 ms** |
| **Gap** | **+1,096 ms** (excl. cold start) |

### Per-Question Breakdown

| QID | Latency | Seeds | Evidence | Chunks | Skeleton | Ctx Tokens | Notes |
|---|---|---|---|---|---|---|---|
| Q-L1 | 18,078 ms | 2 | 15 | 5 | 24 | 4,792 | **Cold start outlier** |
| Q-L4 | 9,367 ms | 5 | 15 | 4 | 18 | 4,658 | Most seeds (5) |
| Q-L9 | 6,982 ms | 2 | 15 | 15 | 24 | 4,173 | Most chunks (15) |
| Q-L3 | 6,509 ms | 2 | 15 | 4 | 25 | 4,658 | |
| Q-L2 | 6,020 ms | 2 | 15 | 4 | 24 | 4,658 | |
| Q-L7 | 5,702 ms | 5 | 15 | 3 | 14 | 1,810 | 5 seeds, fewest ctx tokens |
| Q-L8 | 5,689 ms | 3 | 15 | 5 | 18 | 6,189 | Most ctx tokens |
| Q-L6 | 5,025 ms | 3 | 15 | 4 | 14 | 2,505 | |
| Q-L10 | 4,968 ms | 1 | 15 | 17 | 21 | 4,405 | 1 seed, most chunks but fast |
| Q-L5 | 4,606 ms | 1 | 15 | 4 | 18 | 4,658 | **Fastest** (1 seed) |

### Negative Questions (typically faster — many short-circuit on 0 seeds)

| QID | Latency | Seeds | Evidence | Notes |
|---|---|---|---|---|
| Q-N5 | 1,196 ms | 0 | 0 | No seeds → skeleton-only → fast |
| Q-N1 | 1,302 ms | 0 | 0 | No seeds → skeleton-only → fast |
| Q-N2 | 2,259 ms | 0 | 0 | No seeds → skeleton-only |
| Q-N10 | 3,597 ms | 1 | 0 | 1 seed resolved but 0 evidence |
| Q-N7 | 4,058 ms | 1 | 15 | Full pipeline |
| Q-N3 | 4,065 ms | 1 | 15 | Full pipeline |
| Q-N8 | 4,696 ms | 1 | 15 | Full pipeline |
| Q-N9 | 6,761 ms | 5 | 15 | 5 seeds → full pipeline |
| Q-N6 | 6,984 ms | 5 | 15 | 5 seeds → full pipeline |

---

## 2. Historical Latency Trend

| Period | Pos Avg | Max | Key Change |
|---|---|---|---|
| Jan 4 (baseline, pre-V2) | 2,996–4,968 ms | 4,678 ms* | Original pipeline, fewer stages |
| Jan 19 (Voyage migration) | 24,144–25,902 ms | 56,240 ms | Voyage V2 cold start / API issues |
| Jan 21–23 (stabilized) | 4,092–6,587 ms | 20,874 ms | Cold start resolved |
| Feb 5–8 (pre-denoising) | 10,191–43,604 ms | 75,590 ms | Full synthesis → gpt-5.1 |
| Feb 9 (denoising deployed) | 5,920–8,306 ms | 13,439 ms | **Denoising cut tokens 50%+** |
| Feb 10 (ablation experiments) | 5,718–8,744 ms | 20,629 ms | Various toggles tested |
| Feb 12 (regression report) | 6,572–10,224 ms | 19,668 ms | **Regression noted** |
| Feb 13 (latest pre-today) | 6,207–9,326 ms | 12,921 ms | Partial recovery |
| **Feb 14 (current)** | **7,295 ms** | **18,078 ms** | Today's measurement |

*\*Excluding cold-start outliers where noted.*

The "10.2s regression" from the handover doc corresponds to the Feb 12 18:40 benchmark (`route2_local_search_20260212T184042Z.json`). It was a **single-run measurement** with a high cold-start max (19,668ms on Q-L1). The positive average excluding Q-L1 was likely ~9s.

**Key insight:** The regression is **not** a sudden cliff. Latency has been gradually increasing since the denoising baseline (5.9s → 6.2–7.3s) due to added pipeline stages, primarily skeleton enrichment (Stage 2.2.6) which adds a Voyage embedding + Neo4j vector query on every request.

---

## 3. Root Cause Analysis

### 3.1 Architecture: Fully Serial Pipeline (No Parallelism)

The Route 2 pipeline in `route_2_local.py` executes **all stages serially** with zero `asyncio.gather`:

```
Query ──→ [2.1 NER] ──→ [2.2 PPR] ──→ [2.2.5 Chunks+Spans] ──→ [2.2.6 Skeleton] ──→ [2.3 Synthesis]
          (serial)      (serial)      (serial)                  (serial)              (serial)
```

**Independent operations that could be parallelized:**
- NER (Stage 2.1) and query embedding for skeleton (part of 2.2.6) both only need the query
- Skeleton retrieval (2.2.6) and chunk pre-fetch (2.2.5) — skeleton depends only on the query, chunks depend on PPR

### 3.2 Estimated Per-Stage Latency (Without Instrumentation)

Since the deployed container doesn't have per-stage timing yet, these are estimates based on component analysis:

| Stage | Component | Est. Duration | % of ~6s | I/O Type |
|---|---|---|---|---|
| **2.1** | NER entity extraction (`gpt-5.1`) | ~800–1,200 ms | ~15–20% | **LLM call** |
| **2.2** | PPR graph traversal (6-strategy seed resolution + 5-path PPR) | ~400–800 ms | ~8–12% | Neo4j async |
| **2.2.5** | Chunk pre-fetch + language spans | ~300–600 ms | ~5–10% | Neo4j batch |
| **2.2.6** | Skeleton enrichment (Voyage embed + Neo4j vector search) | ~300–500 ms | ~5–8% | **API call** + Neo4j |
| **2.3** | Synthesis (chunk retrieval + denoising + LLM) | ~2,500–3,500 ms | ~45–55% | **LLM call** + Neo4j |
| | **Total** | **~4,300–6,600 ms** | | |

### 3.3 Model Configuration

| Model Slot | Model | Usage | Notes |
|---|---|---|---|
| `HYBRID_NER_MODEL` | **gpt-5.1** | NER entity extraction (Stage 2.1) | Heavy model for NER |
| `HYBRID_SYNTHESIS_MODEL` | gpt-5.1 | Synthesis fallback | Only used when skeleton fails |
| `SKELETON_SYNTHESIS_MODEL` | **gpt-4.1-mini** | Synthesis (Stage 2.3) — **active path** | Lighter model, active |
| Router | gpt-4o-mini | Query classification | Runs before Route 2 |

The NER stage uses `gpt-5.1`, which is the heaviest model, for a task (entity extraction) that could likely work with a lighter model.

### 3.4 Cold Start (Q-L1 Outlier)

Q-L1 consistently shows 2–3× higher latency than subsequent questions:
- **Today:** 18,078 ms (vs 6,096 ms avg for Q-L2–L10)
- This is a container-level cold start: connection pool initialization, model warm-up, Neo4j driver first-connect

The cold start penalty is ~12s, which inflates the average by ~1.2s.

### 3.5 Seed Count → NER Latency Correlation

Questions with more seeds (5) tend to be slower, likely because:
- More seed resolution queries in Stage 2.2 (6 strategies × N seeds)
- More entities in PPR expand the traversal scope

| Seeds | Questions | Avg Latency (excl. Q-L1) |
|---|---|---|
| 1 | Q-L5, Q-L10 | 4,787 ms |
| 2 | Q-L2, Q-L3, Q-L9 | 6,504 ms |
| 3 | Q-L6, Q-L8 | 5,357 ms |
| 5 | Q-L4, Q-L7 | 7,535 ms |

Correlation exists but is not perfectly linear — other factors (context tokens, skeleton count) also contribute.

---

## 4. What Changed Since the 5.9s Baseline (Feb 9)?

The baseline measurement (5,920 ms avg, `20260209T162951Z`) was taken **before** skeleton enrichment was deployed. Changes since then:

| Change | Impact on Latency | When |
|---|---|---|
| **Skeleton enrichment (Strategy B)** | **+300–500 ms** per request (Voyage API + Neo4j vector query) | Feb 10 |
| Score-gap pruning (`DENOISE_SCORE_GAP=1`) | −200 ms (fewer chunks → faster synthesis) | Feb 10 |
| Semantic near-dedup (`DENOISE_SEMANTIC_DEDUP=1`) | +100 ms (Jaccard computation) | Feb 10 |
| Graph traversal Strategy B (vs flat A) | +100–200 ms (more complex Cypher) | Feb 11 |
| **Net effect** | **+300–500 ms** | |

This accounts for most of the increase from 5.9s → 6.1–6.5s. The remainder (~500ms) is likely API/network variance between runs.

---

## 5. Improvement Plan

### 5.1 Quick Wins (Low Effort, Deploy Without Rebuild)

| # | Improvement | Est. Savings | Risk |
|---|---|---|---|
| **P1** | **Parallelize NER + query embedding** — `asyncio.gather(disambiguate(), _get_query_embedding())` | 300–500 ms | Low — independent ops |
| **P2** | **Parallelize skeleton + chunk pre-fetch** — After PPR, run 2.2.5 and 2.2.6 concurrently | 300 ms | Low — independent after PPR |
| **Combined P1+P2** | | **500–800 ms** | |

### 5.2 Medium Effort

| # | Improvement | Est. Savings | Risk |
|---|---|---|---|
| **M1** | **Downgrade NER model** — `gpt-5.1` → `gpt-4.1-mini` for entity extraction | 500–800 ms | Medium — needs accuracy validation |
| **M2** | **Cache Voyage embeddings** — Same query re-embedding on skeleton is wasteful | 100–200 ms | Low |
| **M3** | **Warm container keep-alive** — Eliminate Q-L1 cold start via periodic health pings | ~12s for first request | Low |

### 5.3 Requires Investigation

| # | Improvement | Est. Savings | Risk |
|---|---|---|---|
| **I1** | **Per-stage timing instrumentation** — Deploy timing code (already added to `route_2_local.py`) to get real measurements | Observability | None |
| **I2** | **Profile Strategy B Cypher** — The graph traversal query is complex; may benefit from index hints or simplification | 100–300 ms | Medium |
| **I3** | **Reduce PPR top_k from 15** — Every entity generates chunk fetches; reducing to 10 may help | 100–200 ms | Medium — accuracy impact |

### 5.4 Projected Latency After Improvements

| State | Positive Avg (excl. cold start) |
|---|---|
| Current (Feb 14) | 6,096 ms |
| After P1+P2 (parallelization) | ~5,300–5,600 ms |
| After P1+P2+M1 (+ NER model) | ~4,800–5,100 ms |
| After all quick wins | **~4,500–5,000 ms** ← meets target |

---

## 6. Instrumentation Added

Per-stage `time.perf_counter()` timing has been added to `src/worker/hybrid_v2/routes/route_2_local.py`:

- `stage_2.1_ner_ms` — NER entity extraction
- `stage_2.2_ppr_ms` — PPR graph traversal
- `stage_2.2.5_chunks_spans_ms` — Chunk pre-fetch + language spans
- `stage_2.2.6_skeleton_ms` — Skeleton enrichment (Voyage + Neo4j)
- `stage_2.3_synthesis_ms` — Full synthesis (retrieval + denoising + LLM)
- `total_ms` — End-to-end handler time

Controlled by `ROUTE2_RETURN_TIMINGS=1` (default ON). Timings are returned in `metadata.timings_ms` in the API response.

**Next step:** Deploy container with timing instrumentation, re-run benchmark, and replace the estimated breakdown in Section 3.2 with real measurements.

---

## 7. Benchmark Reference

**File:** `benchmarks/route2_local_search_20260214T065835Z.json`

**Accuracy (unchanged by latency investigation):**
- Containment: 6/10 positive (Q-L1, L5, L7, L8 fail — existing accuracy issue, not latency-related)
- Negative test: 9/9 pass
- Avg F1: 0.528

**Configuration at time of benchmark:**
- `SKELETON_ENRICHMENT_ENABLED=True`
- `SKELETON_GRAPH_TRAVERSAL_ENABLED=True` (Strategy B)
- `SKELETON_SYNTHESIS_MODEL=gpt-4.1-mini`
- `HYBRID_NER_MODEL=gpt-5.1`
- `DENOISE_SCORE_WEIGHTED=1`, `DENOISE_COMMUNITY_FILTER=1`, `DENOISE_SCORE_GAP=1`, `DENOISE_SEMANTIC_DEDUP=1`
