# Route 2 Architecture Deep Dive — Sequential Improvement Experiment

**Date:** 2026-02-10  
**Objective:** Systematically analyze and improve Route 2 (Local Search) noise sources, one improvement at a time, with evaluation after each change.  
**Baseline Build:** commit `b7a299c0` (post-denoising Feb 9, Steps 4–12)  
**Test Group:** `test-5pdfs-v2-fix2`  
**Benchmark:** 10 positive (Q-L1–Q-L10) + 9 negative (Q-N1–Q-N10) questions

---

## 1. Architecture Overview: LazyGraphRAG + HippoRAG 2 Hybrid

The system combines two complementary retrieval paradigms:

| Component | Strength | Weakness (compensated by the other) |
|---|---|---|
| **LazyGraphRAG** | Structural topic clustering (GDS Louvain communities), eager index-time LLM summaries, semantic community matching | Can't do entity-level precision retrieval — returns thematic clusters, not specific facts |
| **HippoRAG 2** | Entity-focused PPR traversal — deterministic graph pathfinding from seed entities; traverses KNN `SEMANTICALLY_SIMILAR` edges | Cold-start problem with ambiguous queries (needs clear entity seeds to start PPR) |

### How They Work Together in Route 2

Route 2 is **primarily HippoRAG 2**, with LazyGraphRAG providing supporting infrastructure:

| LazyGraphRAG contribution to Route 2 | HippoRAG 2 contribution to Route 2 |
|---|---|
| GDS Louvain `community_id` property on Entity nodes → used for PPR seed augmentation (adds top-degree community peers) | Core retrieval engine: PPR from NER entities through 5 graph paths |
| `:Community` nodes with LLM summaries + Voyage embeddings → injected into NER prompt as context so gpt-4o can extract entity names that exist in the graph | Entity→TextChunk traversal via MENTIONS edges |
| Community-aware seed augmentation (+5 peers from same Louvain cluster) | KNN entity↔entity edges traversed in PPR Path 3 (similarity ≥ 0.60) |
| | KNN section↔section edges traversed in PPR Path 2 (similarity ≥ 0.50) |

### Two Louvain Implementations (Same Partition, Two Access Patterns)

| Step | What it produces | Query-time usage in Route 2 |
|---|---|---|
| **Step 8** — GDS Louvain (`_run_gds_graph_algorithms()`) | `community_id` integer property on each Entity node | PPR seed augmentation: `get_community_peers()` queries `seed.community_id` to find top-degree peers |
| **Step 9** — Materialization (`_materialize_louvain_communities()`) | Reads Step 8 `community_id` → creates `:Community` nodes with LLM summaries + Voyage embeddings + `BELONGS_TO` edges | NER prompt grounding: community titles+summaries injected into gpt-4o NER prompt |

Both derive from the same GDS Louvain run. Step 9 is a materialization layer on top of Step 8.

---

## 2. Route 2 Pipeline — Step-by-Step with Noise Analysis

```
Query
  │
  ▼
Step 1: NER Entity Extraction (gpt-4o)       [intent.py]
  │  ~5 seed entity names
  ▼
Step 2: Seed Resolution (6-strategy cascade)  [tracing.py]
  │  resolved Neo4j node IDs
  ▼
Step 3: PPR Graph Traversal (HippoRAG 2)     [async_neo4j_service.py]
  │  ~13 entities (top_k=15, budget=0.8)
  ▼
Step 4: Text Chunk Retrieval + Denoising      [synthesis.py → _retrieve_text_chunks()]
  │  ~40 raw → ~10 deduped chunks
  ▼
Step 5: Context Building (token budget)       [synthesis.py → _build_cited_context()]
  │  ~11.6K tokens (32K budget at 36% utilization)
  ▼
Step 6: LLM Synthesis (gpt-5.1)              [synthesis.py → _generate_response()]
  │  cited response
  ▼
Post: Negative detection (0 chunks → "not found")
```

### PPR 5-Path Traversal (Step 3)

| Path | Edge Types | Weight Env Var | Default |
|---|---|---|---|
| Path 1: Entity-to-Entity | All edges except MENTIONS, SIMILAR_TO, APPEARS_IN_SECTION | `PPR_WEIGHT_ENTITY` | 1.0 |
| Path 2: Section thematic hops | MENTIONS → IN_SECTION → **SEMANTICALLY_SIMILAR** (Section↔Section) → IN_SECTION → MENTIONS | `PPR_WEIGHT_SECTION` | 1.0 |
| Path 3: Entity KNN similarity | **SEMANTICALLY_SIMILAR** or **SIMILAR_TO** (Entity↔Entity) | `PPR_WEIGHT_SIMILAR` | 1.0 |
| Path 4: Cross-document | APPEARS_IN_SECTION → **SHARES_ENTITY** → HAS_HUB_ENTITY | `PPR_WEIGHT_SHARES` | 1.0 |
| Path 5: Hub entities | APPEARS_IN_SECTION → **HAS_HUB_ENTITY** | `PPR_WEIGHT_HUB` | 1.0 |

All weights default to 1.0 — no tuning has been done.

---

## 3. Noise Source Attribution

| # | Source | Pipeline Step | Mechanism | Current Mitigation | Residual Gap |
|---|---|---|---|---|---|
| **N1** | Broad NER entities | Step 1 | "PROPERTY MANAGEMENT AGREEMENT" pulls in everything from that doc | Generic seed blocklist | No query-intent filtering |
| **N2** | PPR graph expansion | Step 3 | Fee question reaches Warranty, Disclaimers via document-level edges | Relevance budget 0.8 (keeps 13/15) | Budget too generous; no score-gap pruning |
| **N3** | PPR scores discarded | Step 4 | Every entity gets uniform `limit_per_entity=12` regardless of PPR score | MD5 dedup collapses duplicates using highest score | Score-weighted allocation not implemented |
| **N4** | Multi-entity chunk duplication | Step 4 | Same chunk via multiple entities → 75% duplicates | **MD5 content-hash dedup** (dominant fix, +67% F1) | Near-duplicate detection not implemented |
| **N5** | Cross-document copies | Index-time | Same doc indexed as 5+ copies → 20× redundancy | MD5 dedup catches content-identical copies | Semantic near-dedup not implemented |

---

## 4. Baseline Metrics (Post-Feb 9 Denoising)

| Metric | Value |
|---|---|
| Containment (positive) | 10/10 |
| F1 (avg) | 0.261 |
| Chunks to LLM (avg) | 9.9 |
| Context tokens (avg) | 11,597 |
| Latency (avg) | 5,920 ms |
| Negative pass | 9/9 |
| Raw chunks before dedup (avg) | 40.0 |
| Dedup ratio (avg) | 75.3% |
| Noise filters triggered | 0 |
| Token budget utilization | 36% |

Source: `route2_local_search_20260209T162951Z.json` (baseline, all measures ON)

---

## 5. Improvement Queue

| # | Improvement | Target Noise Source | Env Toggle | Expected Impact | Status |
|---|---|---|---|---|---|
| **1** | PPR score-weighted chunk allocation | N3 (scores discarded) | `DENOISE_SCORE_WEIGHTED=1` (enable) | Raw chunks ~40→~20; F1 ↑ | 🔧 Implementing |
| **1.5** | Community-aware PPR entity filtering | N2 (graph expansion) | `DENOISE_COMMUNITY_FILTER=1` (enable) | Cross-community noise entities penalized | ⏳ Queued |
| **2** | PPR score-gap pruning | N2 (graph expansion) | `DENOISE_SCORE_GAP=1` (enable) | Entity count ~13→~6-8 | ⏳ Queued |
| **3** | Query-intent NER prompt | N1 (broad NER) | Prompt change only | Seed count ~5→~2-3 targeted | ⏳ Queued |
| **4** | Semantic near-dedup (embedding cosine) | N5 (cross-doc copies) | `DENOISE_SEMANTIC_DEDUP=1` (enable) | Catches formatting-variant duplicates | ⏳ Queued |
| **5** | Vector chunk safety net | N/A (coverage gap) | `DENOISE_VECTOR_FALLBACK=1` (enable) | Insurance for NER misses | ⏳ Queued |

---

## 6. Experiment Results

### 6.1 Improvement #1: PPR Score-Weighted Chunk Allocation

**Hypothesis:** Allocating chunks proportional to PPR score instead of uniform `limit_per_entity=12` will reduce raw chunk count and improve context focus. High-PPR entities get more chunks; low-PPR entities get fewer (min 1).

**Implementation:**
- Modified `_retrieve_text_chunks()` in `synthesis.py`
- Formula: `entity_budget = max(1, round(score / max_score × limit_per_entity))`
- Top-scoring entity gets full 12 chunks; noise entity with 1/50th the score gets 1 chunk
- Toggle: `DENOISE_SCORE_WEIGHTED=1` to enable (off by default for safe rollout)
- Fallback: if all scores are 0 or equal, reverts to uniform allocation

**Results:**

| Metric | Baseline (all ON) | + Score-Weighted | Delta |
|---|---|---|---|
| Containment | 10/10 | | |
| F1 (avg) | 0.261 | | |
| Chunks to LLM (avg) | 9.9 | | |
| Raw chunks (pre-dedup) | 40.0 | | |
| Latency (avg) | 5,920 ms | | |
| Negative pass | 9/9 | | |

**Per-question detail:**

| QID | Baseline F1 | + Score-Weighted F1 | Baseline chunks | + Score-Weighted chunks |
|---|---|---|---|---|
| Q-L1 | 0.304 | | 10 | |
| Q-L2 | 0.062 | | 10 | |
| Q-L3 | 0.412 | | 10 | |
| Q-L4 | 0.133 | | 9 | |
| Q-L5 | 0.222 | | 8 | |
| Q-L6 | 0.291 | | 10 | |
| Q-L7 | 0.197 | | 8 | |
| Q-L8 | 0.275 | | 10 | |
| Q-L9 | 0.432 | | 12 | |
| Q-L10 | 0.286 | | 12 | |

**Verdict:** *(pending evaluation)*

---

### 6.2 Improvement #1.5: Community-Aware PPR Entity Filtering

*(Pending — will be filled after #1 evaluation)*

---

### 6.3 Improvement #2: PPR Score-Gap Pruning

*(Pending)*

---

### 6.4 Improvement #3: Query-Intent NER Prompt

*(Pending)*

---

### 6.5 Improvement #4: Semantic Near-Dedup

*(Pending)*

---

### 6.6 Improvement #5: Vector Chunk Safety Net

*(Pending)*

---

## 7. Cumulative Results Summary

| Improvement | Containment | F1 (avg) | Chunks (avg) | Raw Chunks | Latency | Neg Pass | Verdict |
|---|---|---|---|---|---|---|---|
| Baseline (Feb 9) | 10/10 | 0.261 | 9.9 | 40.0 | 5,920 ms | 9/9 | — |
| + #1 Score-weighted | | | | | | | |
| + #1.5 Community filter | | | | | | | |
| + #2 Score-gap pruning | | | | | | | |
| + #3 NER intent prompt | | | | | | | |
| + #4 Semantic dedup | | | | | | | |
| + #5 Vector safety net | | | | | | | |

---

## 8. Conclusions & Recommendations

*(Will be written after all experiments complete)*
