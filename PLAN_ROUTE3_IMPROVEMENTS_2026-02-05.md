# Route 3 Improvement Plan

**Date:** February 5, 2026  
**Status:** Ready for Implementation  
**Risk Level:** Low (proven patterns from Route 4)

---

## Summary

Port Route 4's enhanced coverage gap fill logic to Route 3 (Global Search). Expected outcome: slight latency reduction via early exit optimization, improved robustness for cross-document queries.

---

## Changes

### 1. Enhanced Coverage Gap Fill

**File:** `src/worker/hybrid/routes/route_3_global.py` (lines 571-592)

**Current Implementation:**
- Fixed `max_total=10`
- Deduplicates by `chunk_id` only
- No early exit when full coverage achieved

**New Implementation (from Route 4 pattern):**
- Add `existing_docs` set for document-level tracking
- Dynamic sizing: `min(max(total_docs * 2, 10), 200)` for comprehensive queries
- Early exit when `len(existing_docs) >= total_docs`
- Comprehensive query detection ("list all", "summarize across", etc.)

### 2. Comprehensive Query Detection

Add helper function `_is_comprehensive_query()` to detect enumeration patterns and scale retrieval accordingly.

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Semantic beam search | Route 3 already at 100% accuracy; unnecessary complexity |
| comprehensive_sentence mode | Route 4 specialty for invoice analysis; not needed for thematic queries |
| Evaluation tooling overhaul | Deferred to separate milestone; current benchmarks sufficient |

---

## Verification

1. Run Route 3 benchmark:
   ```bash
   python scripts/benchmark_route3_global_search.py \
     --url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
     --group-id phase1-5docs-1766595043
   ```

2. Confirm Q-G3 ("Summarize who pays what") still passes (100%)

3. Check logs for optimization:
   - `coverage_gap_fill_skipped` when already full coverage
   - `coverage_gap_fill_applied` with document count when triggered

---

## Latency Impact

| Optimization | Effect |
|--------------|--------|
| Early exit | **Reduces** latency when all docs already covered |
| Document-level dedup | **Neutral** (O(1) set operations) |
| Dynamic sizing | **Neutral to slight reduction** (prevents over-fetching) |

**Net effect:** Slight reduction in average latency.

---

## Related Work

- Route 4 implementation: `src/worker/hybrid/routes/route_4_drift.py` (lines 539-700)
- Route 3 Fast Mode: `ROUTE3_FAST_MODE_IMPLEMENTATION_2026-01-24.md`
- Coverage gap analysis: `ANALYSIS_ROUTE3_COVERAGE_GAP_INVESTIGATION_2026-01-25.md`

---

## Future Backlog (Separate Milestone)

- [ ] Expanded test corpus (20+ documents)
- [ ] Latency threshold assertions in CI
- [ ] Negative test audit (Q-N* coverage)
