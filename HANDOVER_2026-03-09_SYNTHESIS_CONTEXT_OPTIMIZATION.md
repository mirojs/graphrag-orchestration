# Handover: Synthesis Context Optimization

**Date:** 2026-03-09  
**Score:** 55/57 (56/57 previous session → prompt fix for Q-D10 applied, LLM non-determinism)

## What Was Done

### 1. Q-D10 Root Cause Fully Traced

Q-D10: *"List the three risk allocation statements (risk of loss, liability limitations, non-transferability)"*

**Pipeline trace results:**
- **DPR:** Found warranty non-transferability at rank #3 (score 0.6404) and auto-termination at rank #6 (score 0.6289) ✅
- **PPR:** Both sentences in top-30 output (positions #22 and #25, scores 0.99/0.96) ✅
- **Synthesis LLM:** Received the correct evidence but picked the wrong passage — cited "Neither party may assign this contract" (purchase contract assignment clause) instead of "is not transferable" (warranty) for the non-transferability bullet ❌

**Root cause:** Synthesis error, not retrieval gap. The LLM conflated "non-assignability" with "non-transferability."

### 2. Prompt Fix Applied

Added instruction #11 to both `v3_keypoints` and `v0` synthesis prompts in `synthesis.py`:

> **Prefer exact lexical matches over semantic paraphrases.** If the question asks about "non-transferability" and the evidence contains a clause saying something "is not transferable", cite THAT clause rather than a loosely related clause (e.g. "may not assign"). Match the question's specific terminology to the evidence's wording.

**Result:** Manual testing shows 2/3 runs now correctly cite the warranty clause. But LLM non-determinism means the benchmark first-run scored 1/3 on Q-D10 (unlucky first run).

**Commit:** `e395e3d2` — pushed to `fix/git-flow-cleanup`

### 3. Benchmark Notes

- The benchmark evaluator (`evaluate_route4_reasoning.py`) only judges `runs[0]` (first run). The 3 repeats are for latency measurement only.
- The previous 56/57 vs current 55/57 difference is purely due to which Run 1 the LLM happened to produce for Q-D10.

---

## Immediate TODOs

### TODO 1: Sentence Window Expansion (3-Sentence Context)

**Problem:** Our synthesis sends individual sentences (1-sentence granularity) to the LLM. HippoRAG 2 upstream uses paragraph-level passages (much bigger chunks). Single sentences lack context, making it harder for the LLM to assess relevance.

**Example:** The LLM sees:
```
[2] This limited warranty is extended to the Buyer/Owner as the first purchaser of the home and is not transferable.
```
But without surrounding context, it's hard to judge this as a "risk allocation" statement. With a 3-sentence window:
```
[2] The Builder warrants labor for ninety (90) days. This limited warranty is extended to the Buyer/Owner as the first purchaser of the home and is not transferable. In the event the first purchaser sells the home or moves out of it, this limited warranty automatically terminates.
```
The non-transferability + termination context makes it obviously a risk allocation clause.

**Proposed approach:**
- In `_fetch_sentences_by_ids()` (~L1481), after fetching target sentences, also fetch ±1 adjacent sentences (by `index_in_doc`) from the same document
- Expand each sentence's `text` field to include prev + current + next (3-sentence window)
- This is different from the existing `_MAX_MERGE = 2` which only merges when multiple PPR-ranked sentences happen to be adjacent
- The existing `_extract_sentence_context()` helper (~L1070) already does ±1 windowing for entity contexts — reuse that pattern

**Key consideration:** This increases token usage per passage. Need to measure:
- Current avg sentence length vs 3-sentence window length
- Whether the reranker (Step 4.5) scores better with more context
- Whether to reduce `ppr_passage_top_k` from 50 to compensate for larger passages

### TODO 2: Optimal Passage Count Experiment

**Problem:** We send ~23-30 passages to synthesis (after PPR top-50 → rerank top-30). Upstream HippoRAG 2 sends only top-5 passages to its QA reader. More context = more distraction for the LLM.

**Experiment plan:**
1. Sweep `ROUTE7_RERANK_TOP_K` from 5 → 10 → 15 → 20 → 30 (current)
2. With and without 3-sentence windowing
3. Measure: (a) Q-D10 consistency across 5 runs, (b) overall score stability, (c) token usage

**Hypothesis:** Fewer but richer passages (e.g., 10-15 passages × 3-sentence window) may outperform many thin passages (30 × 1-sentence).

### TODO 3: Benchmark Evaluator — Best-of-N Scoring

**Problem:** The evaluator only judges `runs[0]`. For non-deterministic LLM outputs, this makes the score noisy.

**Options:**
- (a) Judge all N runs, report best-of-N score (optimistic)
- (b) Judge all N runs, report worst-of-N score (pessimistic)
- (c) Judge all N runs, report majority vote (realistic)
- Recommended: (c) majority — score each run independently, take the median

**File:** `scripts/evaluate_route4_reasoning.py` line 262: `actual_answer = runs[0].get("text", "")`

---

## Medium-Priority TODOs

### TODO 4: Entity-Doc Map for Q-D10

The `graph_structural_header` (entity-doc map) is only enabled for exhaustive enumeration queries. Q-D10 is a cross-document enumeration ("across the set"). Check if enabling the entity-doc map for Q-D10 helps the LLM map each risk category to the correct document.

**Config:** `ROUTE7_ENTITY_DOC_MAP` env var, detection logic at ~L629 in route_7_hipporag2.py.

### TODO 5: Dashboard Zero-Data Investigation

Query counter shows 0 on dashboard. Diagnostic endpoint deployed at `/dashboard/diag/query-recording`. Still needs investigation.

### TODO 6: Deploy Updated Prompt to Cloud

The synthesis prompt fix (`e395e3d2`) needs to be deployed to Azure Container Apps. The cloud endpoint was rate-limiting (429) during benchmark — the cloud deployment still has the old prompt.

---

## Current State

| Component | Status |
|---|---|
| Embedding renames (Phase A/B) | ✅ Complete |
| Two-tier group isolation | ✅ Complete (18 files, `build_group_ids()`) |
| `__global__` reindex | ✅ Complete (5 docs, 210 sent, 425 ent, 2137 triples) |
| Q-D10 retrieval trace | ✅ Complete — retrieval works, synthesis issue |
| Synthesis prompt fix | ✅ Committed (`e395e3d2`) |
| Benchmark | 55/57 (Q-D10 non-deterministic, 2/3 runs correct) |
| Sentence windowing | 🔲 Not started |
| Passage count sweep | 🔲 Not started |

## Key Files

- `src/worker/hybrid_v2/pipeline/synthesis.py` — Synthesis prompts (v3_keypoints L2554, v0 L2594)
- `src/worker/hybrid_v2/routes/route_7_hipporag2.py` — Route 7 pipeline
  - `_fetch_sentences_by_ids()` L1481 — where sentence windowing would go
  - `_extract_sentence_context()` L1070 — existing ±1 window helper
  - Step 4.5 reranker L633 — takes `ppr_passage_top_k` candidates
- `scripts/evaluate_route4_reasoning.py` L262 — evaluator runs[0] only
- `benchmarks/route7_hipporag2_r4questions_20260309T174132Z.json` — latest benchmark
- `benchmarks/route7_hipporag2_r4questions_20260309T174132Z.eval.md` — 55/57

## .env Overrides (verified)

```
ROUTE7_DPR_TOP_K=50
ROUTE7_PPR_PASSAGE_TOP_K=50       # code default: 30
ROUTE7_RERANK=1
ROUTE7_RERANK_TOP_K=30
ROUTE7_TRIPLE_RERANK=1
ROUTE7_TRIPLE_CANDIDATES_K=500
ROUTE7_SYNONYM_THRESHOLD=0.70     # code default: 0.65
ROUTE7_SEMANTIC_PASSAGE_SEEDS=1
ROUTE7_SEMANTIC_SEED_TOP_K=20
ROUTE7_SEMANTIC_SEED_WEIGHT=0.05
```
