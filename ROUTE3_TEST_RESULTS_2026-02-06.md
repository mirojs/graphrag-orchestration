# Route 3 (Global Search / LazyGraphRAG) Test Results

**Date:** 2026-02-06
**Latest Benchmark:** `route3_global_search_20260206T105102Z` (with sentence citations deployed)
**Group:** `test-5pdfs-v2-fix2` (5 PDFs indexed)

## Summary

| Category | Result |
|----------|--------|
| **Positive Tests (Q-G1-G10)** | 10/10 pass (9/10 with 100% theme, Q-G10 at 83%) |
| **Negative Tests (Q-N1-N10)** | 9/9 **PASS** |
| **Citation Stability** | 1.00 Jaccard (perfect repeatability) |
| **Pass Rate** | **100%** (19/19 questions) |
| **Note** | Q-G10 theme coverage regression: 83% (5/6) vs 100% in previous runs |

## Configuration

- **Endpoint:** `/hybrid/query` with `force_route=global_search`
- **Response Type:** `summary`
- **Repeats:** 3
- **Timeout:** 180s
- **URL:** `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`

## Three Feb 6 Runs Timeline

| Run | Time (UTC) | Code Version | Theme Coverage |
|-----|-----------|--------------|----------------|
| **063218Z** | 06:32:18 | Pre-sentence-citation | 10/10 at 100% |
| **093824Z** | 09:38:24 | Pre-sentence-citation (local) | 10/10 at 100% |
| **105102Z** | 10:51:02 | **With sentence citations** (deployed) | 9/10 at 100%, Q-G10 at 83% |

**Note:** All three runs tested the same indexed data. The 105102Z run is the first to test with the sentence citation feature deployed (commit `f3002c8d`).

## Output Files

**Latest Run (105102Z with sentence citations):**
- JSON: `benchmarks/route3_global_search_20260206T105102Z.json`
- Markdown: `benchmarks/route3_global_search_20260206T105102Z.md`

**Previous Runs:**
- 093824Z: `benchmarks/route3_global_search_20260206T093824Z.{json,md}`
- 063218Z: `benchmarks/route3_global_search_20260206T063218Z.{json,md}`

## Three-Way Comparison: Feb 6 Runs

**Summary:** All runs achieved 100% pass rate (19/19) with perfect negative detection. Theme coverage remained stable across runs except Q-G10 in the latest run (83% vs 100%). Latency variance is expected due to LLM non-determinism and Azure server load.

### Positive Tests (p50 Latency Comparison)

| Question | 063218Z | 093824Z | 105102Z | Δ (latest) | Theme (latest) |
|----------|---------|---------|---------|------------|----------------|
| Q-G1 | 27505 | 29608 | 27745 | -1863 | 100% (7/7) ✅ |
| Q-G2 | 20337 | 24280 | 26575 | +2295 | 100% (5/5) ✅ |
| Q-G3 | 34766 | 35107 | 42846 | +7739 | 100% (8/8) ✅ |
| Q-G4 | 15735 | 22795 | 21258 | -1537 | 100% (6/6) ✅ |
| Q-G5 | 35762 | 34839 | 33075 | -1764 | 100% (6/6) ✅ |
| Q-G6 | 28837 | 34831 | 32689 | -2142 | 100% (8/8) ✅ |
| Q-G7 | 35217 | 51011 | 37449 | -13562 | 100% (5/5) ✅ |
| Q-G8 | 27038 | 25740 | 27875 | +2135 | 100% (6/6) ✅ |
| Q-G9 | 23797 | 23166 | 24885 | +1719 | 100% (6/6) ✅ |
| Q-G10 | 9416 | 10199 | 10803 | +604 | **83% (5/6)** ⚠️ |

**Observations:**
- **Q-G10 Regression:** Theme coverage dropped from 100% (6/6) to 83% (5/6) in the latest run
- **Q-G7 Improvement:** Latency improved significantly (-13.6s) after spike in 093824Z
- **Average latency:** ~28.5s (latest) vs ~29.1s (093824Z) - slight improvement
- **Citation stability:** Perfect 1.00 Jaccard across all runs

### Negative Tests (p50 Latency Comparison)

| Question | 063218Z | 093824Z | 105102Z | Δ (latest) | Status |
|----------|---------|---------|---------|------------|--------|
| Q-N1 | 4506 | 4528 | 4256 | -272 | PASS ✅ |
| Q-N2 | 4233 | 4523 | 4627 | +104 | PASS ✅ |
| Q-N3 | 4274 | 4198 | 4689 | +491 | PASS ✅ |
| Q-N5 | 3940 | 4104 | 6705 | +2601 | PASS ✅ |
| Q-N6 | 6190 | 5175 | 4149 | -1026 | PASS ✅ |
| Q-N7 | 4085 | 3436 | 3318 | -118 | PASS ✅ |
| Q-N8 | 5160 | 4690 | 4969 | +279 | PASS ✅ |
| Q-N9 | 3452 | 4416 | 4768 | +352 | PASS ✅ |
| Q-N10 | 4970 | 4383 | 4881 | +498 | PASS ✅ |

**Observations:**
- **Q-N5 Spike:** Latency increased by 2.6s (still fast at 6.7s)
- All negative tests maintained perfect repeatability (exact=1.00)
- Average latency: ~4.7s (latest) vs ~4.3s (093824Z)

## Detailed Results (Latest Run: 105102Z)

### Positive Tests (Q-G1 to Q-G10)

9 of 10 positive tests achieved **100% theme coverage** (Q-G10 at 83%):

| Question | Theme Coverage | p50 Latency (ms) | Containment | Citation Jaccard |
|----------|---------------|------------------|-------------|------------------|
| Q-G1 | 100% (7/7) | 27745 | 0.93 | 1.00 |
| Q-G2 | 100% (5/5) | 26575 | 0.71 | 1.00 |
| Q-G3 | 100% (8/8) | 42846 | - | 1.00 |
| Q-G4 | 100% (6/6) | 21258 | 0.76 | 1.00 |
| Q-G5 | 100% (6/6) | 33075 | 0.75 | 1.00 |
| Q-G6 | 100% (8/8) | 32689 | 0.82 | 1.00 |
| Q-G7 | 100% (5/5) | 37449 | 0.88 | 1.00 |
| Q-G8 | 100% (6/6) | 27875 | 0.68 | 1.00 |
| Q-G9 | 100% (6/6) | 24885 | 0.87 | 1.00 |
| Q-G10 | **83% (5/6)** ⚠️ | 10803 | - | 1.00 |

### Negative Tests (Q-N1 to Q-N10)

All negative tests correctly returned "not found" responses:

| Question | Result | p50 Latency (ms) | Repeatability |
|----------|--------|------------------|---------------|
| Q-N1 | PASS | 4256 | exact=1.00 |
| Q-N2 | PASS | 4627 | exact=1.00 |
| Q-N3 | PASS | 4689 | exact=1.00 |
| Q-N5 | PASS | 6705 | exact=1.00 |
| Q-N6 | PASS | 4149 | exact=1.00 |
| Q-N7 | PASS | 3318 | exact=1.00 |
| Q-N8 | PASS | 4969 | exact=1.00 |
| Q-N9 | PASS | 4768 | exact=1.00 |
| Q-N10 | PASS | 4881 | exact=1.00 |

**Negative Detection:** All 9 negative queries achieved perfect repeatability (exact=1.00).
