# Handover — 2026-03-15: Hallucination Guard Revert & Benchmark

## Summary

Over the past 3-4 days we investigated making Route 7 (HippoRAG 2) handle Route 6 benchmark questions — particularly community-dominant queries like Q-D3 ("list all explicit day-based timeframes"). We discovered an NER hallucination ("90 days" instead of "ten (10) business days"), built and tested a hallucination guard, found the real root cause was entity dedup merging time-period entities, built a numeric dedup guard, tuned PPR top_k and dynamic reranking, and ultimately **reverted the hallucination guard** after proving it was net-negative.

## Final Benchmark: 54/57 (94.7%)

| Question | Score | Notes |
|----------|-------|-------|
| Q-D1 | 3/3 | ✅ |
| Q-D2 | 3/3 | ✅ |
| Q-D3 | 3/3 | ✅ Was our primary target — all 13 timeframes listed |
| Q-D4 | 3/3 | ✅ |
| Q-D5 | 3/3 | ✅ |
| Q-D6 | 3/3 | ✅ |
| Q-D7 | 3/3 | ✅ |
| Q-D8 | 3/3 | ✅ |
| Q-D9 | 2/3 | LLM synthesis too concise — omits fixed fees, tax, credit card deductions |
| Q-D10 | 1/3 | LLM synthesis incomplete — omits liability/indemnity language |
| Q-N1–N10 | 3/3 each | ✅ All 9 negative tests pass |

**Judge model:** GPT-5.1 · **Group ID:** test-5pdfs-v2-fix2 · **Benchmark file:** `benchmarks/route7_hipporag2_r4questions_20260315T000304Z.json`

## What We Shipped (commits on `fix/git-flow-cleanup`)

### 1. Numeric Dedup Guard — `1f83aa43`
- **File:** `src/worker/hybrid_v2/services/entity_deduplication.py`
- `_has_conflicting_numbers()` prevents merging entities with different numeric values
- Handles both digit ("90") and word-form numbers ("sixty", "ten")
- Result: embedding merges 251→193, entities 460→488 post-dedup
- "90 days" no longer absorbs "ten (10) business days", "sixty (60) days", etc.

### 2. PPR top_k 50→100 + Dynamic Rerank — `603d6d85`
- **Files:** `route_7_hipporag2.py`, `.env`, `infra/main.bicep`
- `ppr_passage_top_k` default 50→100 (catches entities at PPR rank 50-100)
- `rerank_dynamic_cutoff` default True (0.15 threshold trims irrelevant passages)
- Bicep and .env synced

### 3. Rerank Keyword Args + Community Matcher — `1f83aa43`
- Fixed 3 rerank_with_retry calls missing keyword args
- Dynamic cutoff `request_k` fix
- Adaptive `relative_threshold` in community_matcher.py

### 4. user_id Fix — `1f83aa43` (kept in `e95b7906`)
- `_prepare_documents()` now accepts `user_id` parameter
- Both call sites pass `user_id=user_id`
- Was a silent bug caught by DI retry loop

### 5. Hallucination Guard REVERTED — `e95b7906`
- Guard was too aggressive: strict substring matching false-positived on valid paraphrased entities
- Net effect: 175 fewer relationships (3559→3384), no benchmark improvement
- Removed: `_NER_FIX_PROMPT`, `_TRIPLE_FIX_PROMPT`, checkpoint logic, helper functions

## Root Cause Analysis

### Why Q-D3 was failing before
1. **NER hallucination**: LLM extracted "90 days" from text containing "ten (10) business days"
2. **Entity dedup**: cosine similarity >0.8 between all time-period entities → union-find merged them into "90 days" (shortest name wins)
3. **PPR ranking**: "ten 10 business days" entity had degree=1, ranked #67/419 — outside old top_k=50

### Why hallucination guard was net-negative
- Strict substring match (`entity in sentence_text`) rejects valid paraphrased entities
- Re-extraction LLM calls often produce entities that also fail the check
- The "90 days" mega-hub was accidentally helping retrieval (more edges = higher PPR)
- Real fix was numeric dedup guard + wider PPR window

## Current State

- **Index:** `test-5pdfs-v2-fix2` — clean re-index without hallucination guard
- **Server:** running on port 8000
- **Branch:** `fix/git-flow-cleanup`
- **All changes committed** — no uncommitted work

## TODO List (continue later)

### High Priority
- [ ] **Fix Q-D9 / Q-D10 LLM synthesis** — both are retrieval-complete but synthesis-incomplete
  - Q-D9: LLM omits fixed monthly fees, tax rate, credit card deductions from Property Management
  - Q-D10: LLM omits liability limitation/indemnity language, warranty exclusions
  - Root cause: synthesis prompt favors conciseness over exhaustiveness
  - Approach: when question says "list" or "compare", prompt should instruct exhaustive coverage
  - File: `src/worker/hybrid_v2/routes/route_7_hipporag2.py` (synthesis prompt section)

### Medium Priority
- [ ] **Verify retrieval context for Q-D9/Q-D10** — confirm all needed sentences are in the reranked context before blaming synthesis
  - Use `response_type=detailed_report` or add debug logging to check reranked passages
- [ ] **Deploy to cloud** — current changes are local only
  - Bicep already updated (`infra/main.bicep`), need `azd up` or pipeline trigger
- [ ] **Test with production data** — benchmark is on 5 test PDFs; validate on real customer documents

### Low Priority
- [ ] **Evaluate running Route 7 for Route 6 questions end-to-end** — the original goal
  - Community-dominant questions: proven ✅ (Q-D3 perfect)
  - Cross-document comparison questions: need synthesis improvement (Q-D9, Q-D10)
  - Negative detection: all pass ✅
- [ ] **Consider prompt variant for "list all" questions** — detect enumerate-style queries and use a more exhaustive synthesis template
- [ ] **Monitor entity dedup in production** — numeric guard may need tuning for edge cases (e.g., "10-day" vs "10 business days" should still merge)

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | Indexing pipeline (guard reverted, user_id fix kept) |
| `src/worker/hybrid_v2/services/entity_deduplication.py` | Entity dedup with numeric guard |
| `src/worker/hybrid_v2/routes/route_7_hipporag2.py` | Route 7 query handler (PPR/rerank defaults) |
| `src/worker/hybrid_v2/pipeline/community_matcher.py` | Adaptive community matching |
| `scripts/index_5pdfs_v2_local.py` | Local re-index script |
| `scripts/benchmark_route7_hipporag2.py` | Benchmark runner |
| `scripts/evaluate_route4_reasoning.py` | LLM judge evaluator |
