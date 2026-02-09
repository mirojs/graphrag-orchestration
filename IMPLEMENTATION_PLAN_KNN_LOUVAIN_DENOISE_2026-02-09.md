# Implementation Plan: KNN + Louvain + Context De-noising

**Date:** 2026-02-09  
**Status:** In Progress  
**Architecture:** HippoRAG 2 (PPR entity graph) + LazyGraphRAG (community summarization) — preserved and enhanced  
**Scope:** Routes 2/3/4 — improve signal-to-noise ratio of context fed to synthesis LLM  

---

## 0. Executive Summary

Three complementary improvements share one goal: **reduce noise and improve relevance of context chunks sent to the synthesis LLM**. They compose naturally within the existing HippoRAG 2 + LazyGraphRAG dual architecture, which remains the backbone — no architectural rewrites.

| # | Work Item | Status | Impact |
|---|-----------|--------|--------|
| A | **Louvain Community Materialization (Step 9)** | ✅ DONE | Route 3 theme coverage 69.8% → 100% |
| B | **KNN Embedding Score Propagation** | 🔲 TODO | Routes 2/3/4 — PPR scores surfaced to synthesis, score-ranked context |
| C | **Context De-noising Pipeline** | 🔲 TODO | Routes 2/3/4 — dedup, token budget, noise filtering |

**Architectural principle:** HippoRAG 2 PPR remains the retrieval backbone (5-path entity graph traversal). LazyGraphRAG community matching remains Route 3's entry point. Both systems are **enhanced, not replaced** — GDS KNN feeds PPR Path 3, Louvain communities feed CommunityMatcher.

---

## A. Louvain Community Materialization — ✅ COMPLETE

**Commits:** `8271e404`, `9062b2c1`, `b42b3352`, `c662a6bb`, `1d78ec26`, `4c54bc60`  
**Design doc:** `DESIGN_LOUVAIN_COMMUNITY_SUMMARIZATION_2026-02-09.md` (741 lines)  
**Deployed:** Image `1d78ec26-05` on `graphrag-api` + `graphrag-worker`

### What was done

- **Step 9** added to `lazygraphrag_pipeline.py`: GDS Louvain `community_id` → `:Community` nodes + `:BELONGS_TO` edges + LLM summaries + Voyage embeddings
- **CommunityMatcher** upgraded: loads communities from Neo4j (Louvain-backed) with semantic matching; falls back to ad-hoc 4-level cascade if none exist
- **Neo4j store** extended: `update_community_summary()`, `update_community_embedding()` methods
- **25 unit tests** passing, all committed
- **Benchmark:** `test-5pdfs-v2-fix2` — 6 communities, 105 BELONGS_TO edges, theme coverage 100%, +41% citations, 10/10 pass rate
- **`min_community_size`** lowered from 3 to 2 to capture small but meaningful clusters

### How it fits the architecture

```
LazyGraphRAG Community Layer (Route 3 entry point):
  Query → CommunityMatcher → semantic match against Louvain community summaries
       → top-3 communities → hub entity extraction → PPR → synthesis

HippoRAG 2 PPR Layer (Routes 2/3/4 backbone):
  Seed entities → 5-path PPR traversal (unchanged) → evidence entities → chunks → synthesis
```

Louvain defines **structural boundaries** (graph topology). LazyGraphRAG provides **semantic bridge** (LLM summaries + Voyage embeddings for matching). Neither replaces the other.

---

## B. KNN Embedding Score Propagation — TODO

### B.1 Problem Statement

GDS KNN creates `SEMANTICALLY_SIMILAR` edges at index time (Step 8a) with cosine similarity scores. These edges are traversed by PPR Path 3, contributing to per-entity scores. However, the PPR scores are **discarded before synthesis**:

```python
# synthesis.py line 754 — SCORE EXPLICITLY DISCARDED
for name, _score in evidence_nodes:
    cleaned = _clean_entity_name(name)
    ...
```

**Current score flow:**
```
GDS KNN → SEMANTICALLY_SIMILAR edges (score: 0.60–1.0)
    ↓
PPR 5-path query → combined score per entity (sum of 5 path contributions)
    ↓
evidence_nodes: List[(name, score)]  ← scores computed correctly
    ↓
┌─ get_ppr_evidence_chunks(): scores USED for chunk ranking ✓
│
└─ synthesis._retrieve_text_chunks(): scores DISCARDED ✗
   └─ _build_cited_context(): chunks grouped by document, NO score ordering
      └─ LLM prompt: NO score signal visible to LLM
```

**Consequence:** The synthesis LLM receives an unbounded, unranked bag of chunks. High-relevance and low-relevance chunks are treated equally. The expensive PPR computation is wasted at the final step.

### B.2 Root Cause Detail

| Location | Issue | Line |
|----------|-------|------|
| `synthesis.py` `_retrieve_text_chunks()` | Score variable named `_score` — intentionally ignored | L754 |
| `synthesis.py` `_build_cited_context()` | Chunks grouped by document, not by PPR rank | L800+ |
| `synthesis.py` `synthesize()` | `evidence_path` extracts names only: `[node for node, _ in evidence_nodes]` | L291 |
| Routes 2 PPR | Always traverses SEMANTICALLY_SIMILAR (no knn_config filter) | Path 3 always on |
| Route 4 beam search | Conditionally traverses SEMANTICALLY_SIMILAR (via knn_config) | Asymmetric |

### B.3 Planned Changes

#### B.3.1 Propagate PPR scores to chunk selection

**File:** `src/worker/hybrid_v2/pipeline/synthesis.py`

```python
# BEFORE (current):
for name, _score in evidence_nodes:
    cleaned = _clean_entity_name(name)

# AFTER:
entity_scores = {_clean_entity_name(name): score for name, score in evidence_nodes}
for name in entity_scores:
    ...
```

Pass `entity_scores` dict through to `_build_cited_context()` so chunks can be ranked by the PPR score of their source entity.

#### B.3.2 Score-ranked context assembly

**File:** `src/worker/hybrid_v2/pipeline/synthesis.py` → `_build_cited_context()`

Sort chunks by their entity's PPR score before assembling context. Higher-scored chunks appear first in the LLM prompt (recency bias in LLMs means earlier context gets more attention).

#### B.3.3 Token budget enforcement

When assembling context, stop when cumulative token count reaches a configurable budget (e.g., 32K tokens for a 128K model). This naturally drops the lowest-scored chunks.

#### B.3.4 Consistent knn_config across routes

Route 2 PPR Path 3 always traverses SEMANTICALLY_SIMILAR regardless of `knn_config`. Route 4 beam search conditionally includes them. Normalize: either both respect `knn_config` or both always include KNN edges (recommended — KNN edges are valuable and already quality-filtered by `similarity_cutoff=0.60`).

### B.4 Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `pipeline/synthesis.py` | Propagate scores, add score-ranked assembly, add token budget |
| 2 | `pipeline/synthesis.py` | Chunk dedup by content hash before assembly |
| 3 | `services/async_neo4j_service.py` | (Optional) Add knn_config filter to PPR Path 3 for consistency |

### B.5 Expected Impact

- PPR scores become **actionable** — highest-relevance chunks appear first in context
- Token budget prevents unbounded context (currently 49K–100K+ tokens observed)
- KNN Path 3 contribution becomes meaningful (currently diluted by noise)

### B.6 Metrics

| Metric | Current | Target |
|--------|---------|--------|
| PPR scores used in synthesis | No (discarded) | Yes |
| Context ordered by relevance | No (by document) | Yes |
| Token budget enforced | No (unbounded) | Yes (configurable) |
| KNN edges in Route 2 vs 4 | Asymmetric | Consistent |

---

## C. Context De-noising Pipeline — TODO

### C.1 Problem Statement (from Feb 8 analysis)

From `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` and `ANALYSIS_CONTEXT_QUALITY_AND_DEDUP_2026-02-08.md`:

| Issue | Severity | Detail |
|-------|----------|--------|
| **56.5% duplicate chunks** | P0 | Same chunk retrieved via multiple entities, sent to LLM 2-3× |
| **No token budget** | P0 | Route 2: 49K tokens, Route 3: 100K+ tokens, Route 4: 55K+ tokens |
| **PPR scores discarded** | P0 | Covered in Section B above |
| **Form-label noise** | P1 | `Pumper's Name:____`, `Date:____` — structurally useless chunks |
| **Bare heading chunks** | P1 | `"4. Customer Default"` — heading-only chunks with no substantive text |
| **No cross-entity dedup** | P0 | If entities A and B both `MENTIONS` chunk X, it appears twice |

### C.2 Three-Phase Plan

#### Phase 1: Chunk Dedup + Token Budget (immediate, with B.3)

**Goal:** Eliminate the 56.5% duplicate chunks and enforce a token ceiling.

1. **Content-hash dedup** in `_retrieve_text_chunks()`: Before assembly, hash each chunk's text content and keep only the first occurrence. O(n) compute, eliminates ~half the context.
2. **Token budget** in `_build_cited_context()`: Accumulate tokens (tiktoken encoding) as chunks are added. Stop at budget limit (default 32K). Since chunks are now score-ranked (from B.3.2), the dropped chunks are the least relevant.
3. **Cross-entity dedup**: When multiple entities reference the same chunk, keep the chunk but associate it with the highest-scored entity.

**Files:** `synthesis.py` (same changes as B.3, combined implementation)

#### Phase 2: Noise Filtering (after Phase 1 validated)

**Goal:** Remove structurally useless chunks before they consume token budget.

1. **Form-label filter**: Detect chunks that are predominantly form field labels (pattern: `Name:____`, `Signature:____`, `Date:____`). Score them at 0 or skip.
2. **Bare heading filter**: Detect chunks with <20 substantive characters after stripping heading markers. These are section headings with no body text.
3. **Minimum content threshold**: Chunks with <50 tokens of actual content (excluding whitespace, form labels, headings) are deprioritized.

**Files:** New `pipeline/chunk_filters.py` + integration in `synthesis.py`

#### Phase 3: PPR Weight Tuning (after Phase 1+2 validated)

**Goal:** Optimize the 5 PPR path weights for best chunk quality.

1. **Path contribution analysis**: Log which paths contribute most to each evidence entity's final score. Identify if any paths are noise-dominant.
2. **Weight tuning**: Adjust `damping`, `sim_weight`, `hub_weight` parameters based on analysis.
3. **KNN similarity cutoff tuning**: Current cutoff=0.60 may be too permissive. Test 0.65, 0.70 on benchmark suite.
4. **Community-aware PPR seeding**: After CommunityMatcher selects top-3 communities (from Section A), bias PPR seeds toward entities in those communities. This connects the Louvain investment to PPR scoring.

**Files:** `services/async_neo4j_service.py` (PPR query), `lazygraphrag_pipeline.py` (KNN params)

### C.3 Dependency Chain

```
Phase 1 (Dedup + Budget) ← depends on B.3 (score propagation)
Phase 2 (Noise Filters) ← independent, can parallel with Phase 1
Phase 3 (PPR Tuning) ← depends on Phase 1+2 validation
```

### C.4 Expected Impact

| Metric | Current (Feb 8) | After Phase 1 | After Phase 2 | After Phase 3 |
|--------|-----------------|---------------|---------------|---------------|
| Duplicate chunks | 56.5% | ~0% | ~0% | ~0% |
| Context tokens (Route 2) | ~49K | ≤32K | ≤32K | ≤32K |
| Context tokens (Route 3) | ~100K+ | ≤32K | ≤32K | ≤32K |
| Form-label noise | Present | Present | Filtered | Filtered |
| PPR scores in synthesis | Discarded | Used | Used | Tuned |
| Theme coverage (Route 3) | 100% (after A) | 100% | 100%+ | 100%+ |

---

## D. Architecture Preservation Principles

The following principles guide all three work items. They reflect the design of the HippoRAG 2 + LazyGraphRAG hybrid system and must not be violated:

### D.1 HippoRAG 2 Is the Retrieval Backbone

- **PPR 5-path traversal** remains the core retrieval algorithm for Routes 2/3/4
- Entity graph structure (extracted entities + relationships) is the primary knowledge representation
- GDS algorithms (KNN, Louvain, PageRank) **enrich** the entity graph — they don't replace it
- `SEMANTICALLY_SIMILAR` edges from GDS KNN are **one of five PPR paths**, not the primary signal

### D.2 LazyGraphRAG Is the Community Layer

- **Community-based thematic matching** is Route 3's entry point (via CommunityMatcher)
- Louvain communities (now materialized as Step 9) provide structural clustering
- LLM summaries provide semantic bridge between user queries and community content
- The ad-hoc 4-level cascade remains as fallback for corpora without communities

### D.3 GDS KNN and Louvain Work Together

```
GDS KNN (Step 8a):
  Entity embeddings → SEMANTICALLY_SIMILAR edges → PPR Path 3 traversal
  Purpose: Cross-document entity linking by embedding similarity

GDS Louvain (Step 8b):
  Entity graph → community_id assignment → Community nodes (Step 9)
  Purpose: Topological clustering for thematic grouping

Together:
  KNN creates semantic bridges between distant entities
  Louvain identifies dense subgraphs (communities) in the enriched graph
  Both inform PPR scoring (KNN via Path 3, Louvain via community hub entities)
```

### D.4 Synthesis LLM Receives Ranked, Bounded, De-duplicated Context

This is the **target state** after all three work items are complete:
- Chunks sorted by PPR score (highest relevance first)
- Token budget enforced (no unbounded context)
- Duplicate chunks eliminated (content-hash dedup)
- Noise chunks filtered (form labels, bare headings)
- Citation metadata preserved (document source, page, section)

### D.5 Backward Compatibility

- If GDS is unavailable: KNN edges don't exist, PPR Path 3 returns 0, other paths compensate
- If Louvain communities don't exist: CommunityMatcher falls back to ad-hoc cascade
- If token budget is not set: existing behavior (no truncation) preserved
- All changes are additive — no existing method signatures are broken

---

## E. Implementation Order

| Step | Work | Depends On | Est. Effort |
|------|------|------------|-------------|
| 1 | ~~Louvain community materialization~~ | — | ✅ DONE |
| 2 | PPR score propagation to synthesis | Step 1 ✅ | 2-3 hours |
| 3 | Chunk dedup (content-hash) | — | 1-2 hours |
| 4 | Token budget in context assembly | Steps 2+3 | 1-2 hours |
| 5 | Score-ranked context ordering | Step 2 | 1 hour |
| 6 | Noise filters (form-label, bare heading) | — | 2-3 hours |
| 7 | KNN config consistency (Route 2 vs 4) | — | 1 hour |
| 8 | Benchmark regression (all routes) | Steps 2-5 | 2 hours |
| 9 | PPR weight tuning | Step 8 results | 3-4 hours |
| 10 | Community-aware PPR seeding | Steps 1+9 | 2-3 hours |

**Logical grouping:**
- **Sprint 1 (next):** Steps 2-5 — Score propagation + dedup + budget (combined implementation in synthesis.py)
- **Sprint 2:** Steps 6-7 — Noise filters + KNN consistency
- **Sprint 3:** Steps 8-10 — Benchmark + PPR tuning + community-PPR integration

---

## F. Reference Documents

| Document | Content |
|----------|---------|
| `DESIGN_LOUVAIN_COMMUNITY_SUMMARIZATION_2026-02-09.md` | Detailed design for Step 9 (Louvain → communities) |
| `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` | 6 gaps + 3-phase optimization plan |
| `ANALYSIS_CONTEXT_QUALITY_AND_DEDUP_2026-02-08.md` | 56.5% duplicate chunks analysis |
| `ARCHITECTURE_CORRECTIONS_2026-02-08.md` | 13 corrections to architecture doc (pending) |
| `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` | Main architecture doc (Section 23 updated) |

---

## G. Key Code Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| GDS KNN edge creation | `indexing/lazygraphrag_pipeline.py` | `_run_gds_graph_algorithms()` L1660-1862 |
| GDS Louvain + Step 9 | `indexing/lazygraphrag_pipeline.py` | `_materialize_louvain_communities()` L1930+ |
| PPR 5-path query | `services/async_neo4j_service.py` | `_build_ppr_query_with_section_graph()` L708-950 |
| PPR Path 3 (KNN) | `services/async_neo4j_service.py` | L790-800 |
| Score discarding | `pipeline/synthesis.py` | `_retrieve_text_chunks()` L754 |
| Context assembly | `pipeline/synthesis.py` | `_build_cited_context()` L800+ |
| CommunityMatcher | `pipeline/community_matcher.py` | `_load_from_neo4j()`, `_semantic_match()` |
| Route 4 beam search | `services/async_neo4j_service.py` | `semantic_multihop_beam()` L1187 |
| KNN config in orchestrator | `orchestrator.py` | `query()` L337, `force_route()` L2175 |
