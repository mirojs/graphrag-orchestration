# Route 1 NLP Enhancement Summary

**Date:** 2026-01-03  
**Status:** Implemented, Ready for Testing

## Problem Statement

Route 1 (Vector RAG) exhibited hallucination on negative questions:
- Q-N4: Hallucinated payment portal URL `https://ww.contosolifts.com/portal/pay`
- Q-N6: Incorrectly stated documents are governed by California law

**Root Cause:** LLM synthesis step (after retrieval) was making inferences from keyword matches instead of strictly following the "Not specified" instruction.

## Solution: NLP-First Hybrid Approach

Implemented a two-tier synthesis strategy in Route 1:

### Tier 1: NLP Pattern Extraction (Fast, Deterministic, No Hallucination)
- Tries deterministic regex patterns first
- Optimized for invoice/contract factual extraction
- Patterns cover:
  - Invoice/PO/Registration numbers
  - Currency amounts (total, price)
  - Dates (MM/DD/YYYY, YYYY-MM-DD, Month DD, YYYY)
  - Names (salesperson, vendor, agent)
  - Durations (warranty period, term)
  - Payment terms

### Tier 2: LLM Synthesis with temperature=0 (Fallback)
- Only invoked when NLP patterns don't match
- **temperature=0** for deterministic, conservative outputs
- Reduced hallucination risk significantly

## Changes Made

### File: `graphrag-orchestration/app/hybrid/orchestrator.py`

1. **Modified synthesis logic** (lines ~315-330):
   - Added `nlp_answer = self._extract_with_nlp(query, results)`
   - Falls back to LLM only if NLP returns None
   - Added `temperature=0.0` to `llm.complete()` call

2. **Added `_extract_with_nlp()` method** (lines ~363-480):
   - 6 pattern categories optimized for Route 1's use case
   - Returns `None` when no pattern matches (triggers LLM fallback)
   - Fully deterministic (same input → same output)

## Expected Benefits

1. **Faster**: ~50-80% of Route 1 queries can skip LLM call
2. **Cheaper**: Reduced LLM token usage on simple extractions
3. **More Accurate**: No hallucination on pattern-matched queries
4. **Deterministic**: Same query always returns same answer (when NLP matches)
5. **Robust**: LLM fallback handles edge cases

## Testing Plan

1. **Re-run Route 1 benchmark** against cloud endpoint:
   ```bash
   python3 scripts/benchmark_route1_vector_rag.py \
     --group-id test-5pdfs-1767453722 \
     --repeats 1
   ```

2. **Expected improvements**:
   - Positive questions: Similar or better (some may be exact matches now)
   - Negative questions: 10/10 instead of 8/10 (no hallucination)
   - Latency: 10-30% faster on average (NLP is instant)

3. **Validation metrics**:
   - Exact match rate (should improve)
   - F1 score (should maintain or improve)
   - Negative test pass rate (should reach 10/10)
   - Latency P50/P95 (should decrease)

## Design Rationale

### Why NLP for Route 1 Synthesis?

Route 1 receives queries after routing logic filters out:
- ❌ Entity-focused queries (→ Route 2)
- ❌ Thematic summaries (→ Route 3)
- ❌ Multi-hop reasoning (→ Route 4)

**What remains are simple factual lookups**, which are perfect for NLP:
- "What is the invoice total?" → extract currency
- "What is the due date?" → extract date
- "Who is the salesperson?" → extract name after label

### Why Not NLP for Routes 2/3/4?

Routes 2/3/4 need:
- Context understanding (entity relationships, themes)
- Synthesis across multiple sources
- Inference and reasoning
- Natural language generation

NLP cannot do these—LLM is necessary. But Route 1 is specifically for **extraction**, where NLP excels.

### Borrowed from Route 3

Route 3 already uses a similar approach via `ExtractionService`:
- `nlp_audit` mode: Pure NLP extraction
- `nlp_connected` mode: NLP + LLM rephrasing at temperature=0

Route 1 adapts this concept but with simpler, more targeted patterns since Route 1 chunks are smaller and more focused.

## Next Steps

1. **Deploy to cloud** (commit + push + redeploy)
2. **Run benchmark test** to validate improvements
3. **Monitor production** for regression
4. **Tune patterns** if needed based on real queries

## References

- Benchmark test: `scripts/benchmark_route1_vector_rag.py`
- Previous results: `benchmarks/route1_vector_rag_20260103T165348Z.md`
- Extraction service (Route 3): `app/v3/services/extraction_service.py`
- Synthesis pipeline (Route 3): `app/hybrid/pipeline/synthesis.py`
