# Handover: Route 7 Gap 1 — PPR Top-K=100, MENTIONS Edge Weight Fix, Upstream Comparison — 2026-03-01

**Date:** 2026-03-01  
**Status:** MENTIONS edge weight bug found and fixed (uncommitted). Full upstream code comparison identified 5 critical deviations (P0: entity seed IDF + mean-norm, P1: DPR min-max norm, P2: entity top-K=5 filter). Gap 1 (all-passage DPR seeding) does NOT improve scores. Baseline DPR_TOP_K=20 + edge fix = 54–55/57. Continue tomorrow with commit + P0/P1/P2 fixes.  
**Previous handover:** `HANDOVER_2026-02-28_SENTENCE_SOURCE_TAGGING.md`  
**Companion analysis:** `ANALYSIS_ROUTE7_VS_UPSTREAM_HIPPORAG2_2026-03-01.md` — Full 12-deviation code comparison with architecture diagrams, pseudocode diffs, and priority recommendations (P0–P3).  
**Baseline (pre-changes):** 56/57 (98.2%) — `route7_hipporag2_r4questions_20260226T222346Z` (v7.2, rerank_top_k=30, PPR_TOP_K=20)  
**Current HEAD:** `25659557 Clarify signature detection costs for both DI and CU`

---

## 1. What Was Done Today

### 1.1 Route 7 Architecture Iterations (committed)

Several architecture experiments were committed to main today:

| Commit | Change | Notes |
|--------|--------|-------|
| `5b87dd60` | Replace reranker with semantic search for passage seeding | Experiment |
| `f3382d9c` | Merge PPR + semantic search scores instead of replacing | Experiment |
| `4f34f0ac` | Increase semantic search top_k 30→100 | Broader coverage |
| `45d65c9d` | Remove step 4.7 PPR override — semantic search for seeding only | Cleanup |
| **`6505b212`** | **Route 7 v7.4: DPR seeding + PPR + reranker on PPR output** | **Restore original HippoRAG2 architecture** |

### 1.2 Gap 1 Fix — DPR Seeds ALL Passages (uncommitted)

**Uncommitted changes** in `route_7_hipporag2.py` implement upstream Gap 1 alignment:
- `ROUTE7_DPR_TOP_K` default changed from `20` → `0` (0 = all passages)
- `ROUTE7_DPR_SENTENCE_TOP_K` default changed from `120` → `0` (0 = all)
- `ROUTE7_PPR_PASSAGE_TOP_K` default changed from `20` → `100`
- When `top_k=0`, dynamically queries corpus size via `COUNT(s:Sentence)` to seed every passage into PPR

### 1.3 **CRITICAL FIX: MENTIONS Edge Weight Bug** (uncommitted)

**File:** `src/worker/hybrid_v2/retrievers/hipporag2_ppr.py` line 257

**Bug:** MENTIONS (passage-entity) edges in the PPR graph were weighted `passage_node_weight` (0.05) instead of 1.0.

**In upstream HippoRAG 2** (`add_passage_edges()`): passage-entity edges have weight **1.0**. The `passage_node_weight=0.05` is only used for **passage seed weights** in the PPR personalization vector, NOT for graph edge weights.

**Impact:** With 0.05 edge weight, PPR random walks were 20× less likely to step from an entity to a passage node compared to stepping to another entity. This trapped the walk in entity-space and prevented cross-document bridging via Entity→Passage→Entity paths.

**Fix:** Changed `self._add_edge(src_idx, tgt_idx, passage_node_weight)` → `self._add_edge(src_idx, tgt_idx, 1.0)` at line 257.

### 1.4 Upstream HippoRAG 2 — Full Comparison (updated EOD)

Comprehensive code-level review of [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) `src/hipporag/HippoRAG.py` identified **12 parameters** — 7 match, 5 have critical deviations.

#### ✅ What Matches (7 parameters)

| Aspect | Upstream | Route 7 | Status |
|--------|----------|---------|--------|
| Damping | 0.5 | 0.5 | ✅ Match |
| `passage_node_weight` (seed only) | 0.05 | 0.05 | ✅ Match |
| `triple_top_k` / `linking_top_k` | 5 | 5 | ✅ Match |
| Synonym threshold | 0.8 | 0.8 | ✅ Match |
| Undirected graph | Yes | Yes | ✅ Match |
| Entity-entity edge weight source | co-occurrence / weight | `r.weight` | ✅ ~Match |
| **Passage-entity edge weight** | **1.0** | **1.0** | ✅ **Fixed today** |

#### ❌ Critical Deviations (5 items)

| # | Deviation | Upstream | Route 7 | Impact | Priority |
|---|-----------|----------|---------|--------|----------|
| 1 | **Entity seed: missing IDF + mean-norm** | `fact_score / entity_doc_freq`, then `÷ num_facts` | raw `fact_score` sum | Entity:passage seed ratio ~95:5 instead of ~30:70. Over-weights entities in PPR personalization vector. | **P0** |
| 2 | **No entity seed top-K filter** | Zeros out all but top-5 entities | Seeds ALL matched entities | Disperses PPR mass across too many entities | **P2** |
| 3 | **DPR scores not min-max normalized** | Min-max normalize passage scores to [0,1] | Raw cosine scores | Less differentiation between passage seeds | **P1** |
| 5 | **Recognition memory prompt** | DSPy few-shot optimized prompt | Zero-shot numbered list | Lower filtering precision | P3 |
| 6 | **Post-PPR reranker (Route 7 addition)** | None | voyage-rerank-2.5 cross-encoder | Changes ranking paradigm; generally improves quality | N/A (addition) |
| 7 | **Sentence↔Sentence KNN edges (Route 7 addition)** | Not present | Direct cross-doc bridges | Creates shortcuts not in upstream graph | N/A (addition) |

**Entity seed weighting (Deviation #1) is the most impactful** — it controls how much PPR mass starts on entities vs passages. Without IDF and mean-normalization, entities dominate the personalization vector.

### 1.5 Benchmark Results

#### Phase 1: Gap 1 + PPR_TOP_K=100 (reranker ON, MENTIONS=0.05)

| Run Timestamp | Score | Failures |
|---------------|-------|----------|
| `123740Z` | 51/57 | Q-D8 |
| `165355Z` | 52/57 | Q-D3, Q-N9 |
| `170938Z` | 54/57 | Q-D3 |
| `172016Z` | 54/57 | Q-D3 |
| `172912Z` | 51/57 | Q-D3, Q-D9, Q-D10 |
| `174313Z` | 51/57 | Q-D3, Q-D7, Q-D10 |
| `180715Z` | 51/57 | Q-D3, Q-N9 |
| `181247Z` | 52/57 | Q-D3, Q-N9 |
| `183846Z` | 53/57 | Q-D3, Q-D10 |
| `184616Z` | 53/57 | Q-D3, Q-D10 |
| `190309Z` | 52/57 | Q-D3, Q-D10 |
**Median: ~52/57 (91.2%)** — regression from 56/57

#### Phase 2: Gap 1 + PPR_TOP_K=100 + MENTIONS edge=1.0 (reranker OFF)

| Run Timestamp | Score | Failures |
|---------------|-------|----------|
| `195414Z` | 51/57 | Q-D3 (1/3), Q-N9 (0/3) |
| `200007Z` | 53/57 | Q-N9 (0/3) |
| `200543Z` | 52/57 | Q-D3 (1/3), Q-N9 (0/3) |
**Median: ~52/57** — similar, all-passage seeding still dilutes

#### Phase 3: Baseline DPR_TOP_K=20 + MENTIONS edge=1.0 (reranker ON) ← **Best config**

| Run Timestamp | Score | Failures |
|---------------|-------|----------|
| `201110Z` | **55/57** | Q-D3 (1/3) |
| `201549Z` | **54/57** | Q-D3 (1/3) |
| `201924Z` | **55/57** | Q-D3 (1/3) |
**Median: 55/57 (96.5%)** — nearly matches 56/57 baseline. Q-D3 improved from 0/3 to 1/3.

---

## 2. Root Cause Analysis — Q-D3

### PPR Entity Seed Narrowness

**Query:** `Compare "time windows" across the set: list all explicit day-based timeframes.`

**Problem:** `_query_to_triple_linking()` returns only 3 surviving triples, ALL about warranty 60-day period. Entity seeds: "sixty (60) day warranty period", "windows", "doors (including hardware)", "standards of construction". PPR walks from these 4 warranty entities.

**Triples exist but don't match:** The graph has 1320 triples including "3 business day cancellation period", "ten (10) business days", "Contractor labor warranty for 90 days", "five (5) business days". But `triple_top_k=5` + cosine matching only returns warranty triples for this query.

**This matches upstream behavior** — upstream also uses `linking_top_k=5`. The difference is:
1. **MENTIONS edge fix** (now applied) helps PPR walk from entity-space to passage-space
2. Upstream sends **200 PPR passages** to synthesis (vs Route 7's 20-30), increasing odds of capturing sparse timeframe mentions
3. Q-D3 is a **cross-document aggregate query** — not the typical multi-hop reasoning HippoRAG was designed for

### Reranker Gate Bug (separate issue, not yet fixed)

Line 494 of `route_7_hipporag2.py`: `passage_scores[:rerank_top_k]` (top 30 from PPR) → reranker → **replaces** `passage_scores` with 30 items → `passage_scores[:ppr_passage_top_k]` at line 519 can only return 30 even if `ppr_passage_top_k=100`. **PPR_PASSAGE_TOP_K>30 is effectively ignored when reranker is enabled.**

---

## 3. Current State

### Uncommitted Changes
```
src/worker/hybrid_v2/routes/route_7_hipporag2.py   (+31, -8)
  - Gap 1: DPR_TOP_K=0, DPR_SENTENCE_TOP_K=0, PPR_PASSAGE_TOP_K=100
  - Debug logging at lines ~468-480 (temporary, remove before commit)

src/worker/hybrid_v2/retrievers/hipporag2_ppr.py   (+4, -2)
  - MENTIONS edge weight: 0.05 → 1.0 (the critical fix)
```

### Recommended Commit Strategy
1. **Commit the MENTIONS edge fix** (`hipporag2_ppr.py`) — this is correct and improves scores.
2. **Revert Gap 1 changes** in `route_7_hipporag2.py` — all-passage seeding doesn't help small corpus. Keep DPR_TOP_K=20 baseline.
3. **Remove debug logging** from `route_7_hipporag2.py` before committing.
4. **Fix the reranker gate bug** (line 494) — separate commit, use `passage_scores[:ppr_passage_top_k]` not `[:rerank_top_k]`.

---

## 4. TODO List

### Immediate — Commit & Deploy

- [ ] **Commit MENTIONS edge weight fix** — `hipporag2_ppr.py` line 257: weight 1.0. This is the upstream-aligned fix.
- [ ] **Revert Gap 1 changes** in `route_7_hipporag2.py` — restore DPR_TOP_K=20, DPR_SENTENCE_TOP_K=120, PPR_PASSAGE_TOP_K=20.
- [ ] **Remove debug logging** — lines ~468-480 in `route_7_hipporag2.py`.
- [ ] **Fix reranker gate bug** — line 494: `passage_scores[:ppr_passage_top_k]` instead of `[:rerank_top_k]`.
- [ ] **Run 5+ benchmarks with final config** — Confirm stable 55-56/57.
- [ ] **Deploy to cloud** — Push to main triggers CI/CD.

### Upstream Alignment Fixes — Priority Order (next session)

- [ ] **P0: Entity seed IDF + mean-normalization** — Lines 396-398 of `route_7_hipporag2.py`. Upstream divides each entity's seed weight by `entity_doc_frequency` (IDF) then divides by `num_facts` (mean-normalization). This changes entity:passage seed ratio from ~95:5 to ~30:70. **This is the highest-impact remaining deviation.**
- [ ] **P1: Min-max normalize DPR passage scores** — Before passage seeding, normalize DPR cosine scores to [0,1] range using `(s - min) / (max - min)`. Upstream does this for better differentiation.
- [ ] **P2: Entity seed top-K=5 filter** — After computing entity seeds, zero out all but the top-5 highest-weighted entities. Upstream does this to concentrate PPR mass.
- [ ] **Increase retrieval_top_k** — Try PPR_PASSAGE_TOP_K=50 or 100 WITH the reranker gate fix (so reranker sees more candidates).
- [ ] **Triple diversity exploration** — Increase `triple_top_k` from 5 to 10-20 for broad aggregate queries.
- [ ] **Query decomposition** — Break "list all timeframes across documents" into per-document sub-queries.

### Carried Over from 2026-02-28 — Unfinished Tasks

#### Route 7 Benchmark on 197-Sentence Index (from §4 of previous handover)
- [ ] **Run Route 7 benchmark on cloud (197-sentence index)** — Today's runs were all local. Need to verify cloud deployment matches. Previous handover said to run:
  ```bash
  python3 scripts/benchmark_route7_hipporag2.py \
    --url https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
    --group-id test-5pdfs-v2-fix2 --repeats 1
  ```
- [ ] **Deploy v7.4 + edge fix to cloud** — Current HEAD has v7.4 committed but edge fix is uncommitted.

#### Route 7 Upstream Alignment (carried from 2026-02-28 §4 / 2026-02-26)
- [ ] **OpenIE triple extraction at indexing time** — Dedicated `subject predicate object` extraction. Stub: `_extract_triples()` in `dual_index.py`.
- [ ] **Sentence window expansion (±1 neighbors)** — When a sentence is retrieved, also fetch adjacent sentences.
- [ ] **Damping factor ablation** — Sweep {0.5, 0.7, 0.85} for small corpus optimization.

#### Sentence Extraction Thresholds (carried from 2026-02-28 §4)
- [ ] **Lower `SKELETON_MIN_SENTENCE_CHARS` 30→20** — Rescue short legal sentences.
- [ ] **Tighten ALL_CAPS word threshold 10→6** — Preserve binding legal statements.
- [ ] **`_is_kvp_label` word threshold 8→10** — Prevent false positives on long KVP sentences.
- [ ] **`numeric_only` alpha threshold 10→6** — Recover "Invoice #1256003", "Total: $29,900".
- [ ] **Whitespace-normalize dedup key** — `re.sub(r'\s+', ' ', text).strip().lower()`.

#### CU vs DI Migration (carried from 2026-02-28 §4)
- [ ] **Test CU page-level extraction** — CU is deployed; test paragraph/sentence quality.
- [ ] **Compare CU signature block** — Single polygon vs multiple.
- [ ] **Evaluate CU sentence splitting** — May need wtpsplit.

#### Infrastructure (carried from 2026-02-28 §4)
- [ ] **Investigate GDS Aura connectivity** — 0 communities and 0 KNN edges on cloud reindexes.
- [ ] **Cloud query 500 error investigation** — Intermittent.

---

## 5. How to Resume

```bash
# 1. Check uncommitted changes
cd /workspaces/graphrag-orchestration
git diff --stat

# 2. Commit the edge fix (after reverting Gap 1 and removing debug logs)
git checkout -- src/worker/hybrid_v2/routes/route_7_hipporag2.py  # revert Gap 1
# Then manually apply only the reranker gate fix if desired
git add src/worker/hybrid_v2/retrievers/hipporag2_ppr.py
git commit -m "fix: MENTIONS edge weight 0.05→1.0 to match upstream HippoRAG 2

passage_node_weight was incorrectly used for both PPR seed weights AND
graph edge weights. Upstream uses weight=1.0 for passage-entity edges
in the PPR graph; passage_node_weight (0.05) is only for seeding.

With 0.05 edge weight, PPR walks were 20x less likely to reach passages
from entities, trapping walks in entity-space. Fixes cross-document
retrieval for broad aggregate queries.

Benchmark: 54-55/57 (up from 51-52/57 with edge+Gap1, baseline 56/57)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

# 3. Start local API
PYTHONPATH=. python -m uvicorn src.api_gateway.main:app --host 0.0.0.0 --port 8000 &

# 4. Run benchmark
PYTHONPATH=. python3 scripts/benchmark_route7_hipporag2.py \
  --url http://localhost:8000 \
  --group-id test-5pdfs-v2-fix2 --repeats 3 --no-auth

# 5. Run LLM eval
PYTHONPATH=. python3 scripts/evaluate_route4_reasoning.py benchmarks/route7_hipporag2_r4questions_<timestamp>.json
```

---

## 6. Benchmark History (Route 7)

| Date | Config | Score | Notes |
|------|--------|-------|-------|
| Feb 24 | v7.0, 18 chunks | 55/57 | Pre-reranker best |
| Feb 26 | v7.2, rerank_top_k=20 | 55/57 | Reranker baseline |
| **Feb 26** | **v7.2, rerank_top_k=30** | **56/57** | **All-time best** |
| Mar 1 | v7.4, PPR_TOP_K=100, MENTIONS=0.05 | 51–54/57 | Gap 1 regression |
| Mar 1 | v7.4, PPR_TOP_K=100, MENTIONS=1.0, reranker OFF | 51–53/57 | Edge fix + all-passage dilutes |
| **Mar 1** | **v7.4, DPR_TOP_K=20, MENTIONS=1.0, reranker ON** | **54–55/57** | **Edge fix only — best new config** |
