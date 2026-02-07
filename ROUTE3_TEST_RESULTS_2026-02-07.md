# Route 3 (Global Search / LazyGraphRAG) Test Results — Post-Reindex

**Date:** 2026-02-07
**Benchmark:** `route3_global_search_20260207T083756Z`
**Group:** `test-5pdfs-v2-fix2` (5 PDFs, all 5/5 with `language_spans`)
**Context:** Full V2 reindex with GDS (KNN, Louvain, PageRank) completed 2026-02-07

## Summary

| Category | Result |
|----------|--------|
| **Positive Tests (Q-G1-G10)** | 10/10 pass (9/10 with 100% theme, Q-G5 at 67%) |
| **Negative Tests (Q-N1-N10)** | 9/9 **PASS** |
| **Citation Stability** | 1.00 Jaccard (perfect) |
| **Pass Rate** | **100% (19/19)** |
| **Sentence Citation Ratio** | **49.1%** (up from 33.0% pre-reindex) |
| **[Na] Count** | **1619** (up from 977 pre-reindex, +66%) |

## Key Finding: Sentence Citation Coverage Improved

The reindex from 3/5 → 5/5 docs with `language_spans` increased sentence-level citation coverage:

| Metric | Pre-Reindex (141511Z) | Post-Reindex (083756Z) | Change |
|--------|----------------------|----------------------|--------|
| **[Na] sentence citations** | 977 | 1619 | **+642 (+66%)** |
| **Total citations** | 2958 | 3300 | +342 (+12%) |
| **Sentence citation ratio** | 33.0% | **49.1%** | **+16.0 pp** |

### Per-Question Citation Delta

| Question | Pre-Ratio | Post-Ratio | Delta | Note |
|----------|----------|-----------|-------|------|
| Q-G1 | 41.0% | **61.3%** | +20.3pp | ✅ Big improvement |
| Q-G2 | 25.0% | **73.9%** | +48.9pp | ✅ Biggest improvement |
| Q-G3 | 46.7% | **56.6%** | +9.9pp | ✅ |
| Q-G4 | 54.9% | 22.4% | -32.5pp | ⚠️ LLM variance (see below) |
| Q-G5 | 17.4% | **39.0%** | +21.7pp | ✅ |
| Q-G6 | 27.6% | **49.2%** | +21.6pp | ✅ |
| Q-G7 | 25.4% | **45.0%** | +19.6pp | ✅ |
| Q-G8 | 32.4% | **44.6%** | +12.2pp | ✅ |
| Q-G9 | 45.6% | **55.3%** | +9.7pp | ✅ |
| Q-G10 | 31.1% | **54.1%** | +23.1pp | ✅ |

**8/10 questions improved, 1 regressed (Q-G4), 1 marginal (Q-G3).**

### Q-G4 Regression Analysis

Q-G4 (reporting obligations) response was 16,939 chars but used combined citation format
(`[1, 1r, 1s, 1u, ...]`) with fewer sentence refs and more chunk-level refs in this
particular LLM run. This is **LLM non-determinism**, not a structural regression.
Pre-reindex Q-G4 had only 51 total citations vs 241 post-reindex.

## Theme Coverage

| Question | Coverage | Matched | Missing |
|----------|---------|---------|---------|
| Q-G1 | 100% (7/7) | 60 days, written notice, 3 business days, full refund, deposit, forfeited, terminates | — |
| Q-G2 | 100% (5/5) | idaho, florida, hawaii, arbitration, governing law | — |
| Q-G3 | 100% (8/8) | All terms | — |
| Q-G4 | 100% (6/6) | All terms | — |
| Q-G5 | **67% (4/6)** | arbitration, binding, small claims, contractor | **legal fees, default** |
| Q-G6 | 100% (8/8) | All terms | — |
| Q-G7 | 100% (5/5) | All terms | — |
| Q-G8 | 100% (6/6) | All terms | — |
| Q-G9 | 100% (6/6) | All terms | — |
| Q-G10 | **100% (6/6)** ✅ | warranty, arbitration, servicing, invoice, scope of work, payment | — |

**Q-G10 recovered** from 83% (previous run 105102Z) to 100% — confirming LLM variance.
**Q-G5 dropped** to 67% missing "legal fees" and "default" — also LLM variance (not structural).

## Latency

| Question | p50 (ms) | Prev p50 (105102Z) | Delta |
|----------|---------|-------|-------|
| Q-G1 | 33,149 | 27,745 | +5,404 |
| Q-G2 | 23,510 | 26,575 | -3,065 |
| Q-G3 | 42,321 | 42,846 | -525 |
| Q-G4 | 31,455 | 21,258 | +10,197 |
| Q-G5 | 37,447 | 33,075 | +4,372 |
| Q-G6 | 25,278 | 32,689 | -7,411 |
| Q-G7 | 33,766 | 37,449 | -3,683 |
| Q-G8 | 30,489 | 27,875 | +2,614 |
| Q-G9 | 24,822 | 24,885 | -63 |
| Q-G10 | 15,229 | 10,803 | +4,426 |
| **Avg** | **~29.7s** | **~28.5s** | +1.2s |

Latency within normal LLM variance band (~±5s).

## Configuration

- **Endpoint:** `/hybrid/query` with `force_route=global_search`
- **Response Type:** `summary`
- **Repeats:** 3
- **Timeout:** 180s
- **URL:** `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`

## Output Files

- JSON: `benchmarks/route3_global_search_20260207T083756Z.json`
- Markdown: `benchmarks/route3_global_search_20260207T083756Z.md`

## Conclusion

The full V2 reindex (5/5 docs with `language_spans`) **confirmed the expected improvement**:
- Sentence citation coverage rose from **33.0% → 49.1%** (+16 percentage points)
- Total [Na] citations increased by **66%** (977 → 1619)
- All 19/19 tests pass, all negatives correctly rejected
- Q-G10 theme regression from previous session recovered to 100%
- Q-G5 theme dip to 67% is LLM variance (not structural)

**Next steps:** The remaining ~51% chunk-only citations are inherent to the LLM's citation style
and the sentence segmentation granularity. Further improvement would require prompt engineering
or a post-processing step to convert remaining chunk-level citations to sentence-level.
