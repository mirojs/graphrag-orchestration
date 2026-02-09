# KNN + Louvain + Context De-noising: Implementation Plan

**Date:** 2026-02-09  
**Status:** In Progress  
**Architecture:** HippoRAG 2 (PPR entity graph) + LazyGraphRAG (community summarization)  
**Scope:** Routes 2/3/4  

---

## 1. Issues

### 1.1 The Synthesis LLM Receives Noisy, Unbounded, Unranked Context

Routes 2, 3, and 4 all follow the same final step: collect text chunks from the knowledge graph and send them to a synthesis LLM to generate a cited answer. Benchmarking on Feb 8, 2026 revealed that **the quality of the context fed to the LLM is the primary bottleneck** — not the LLM itself, not the graph structure, not the retrieval algorithm.

| Symptom | Measured Value | Route(s) |
|---------|---------------|----------|
| **Duplicate chunks** — same chunk retrieved via multiple entities, sent to LLM 2-3× | **56.5%** of all chunks are exact duplicates | All routes |
| **Unbounded context** — no token limit on context window | Route 2: **49K tokens**, Route 3: **100K+**, Route 4: **55K-460K** | All routes |
| **PPR scores discarded** — expensive graph traversal scores computed then thrown away | `for name, _score in evidence_nodes` — score explicitly ignored | All routes |
| **Form-label noise** — structurally useless chunks consume token budget | `Pumper's Name:____`, `Date:____`, `Signature:____` | Routes 2, 3 |
| **Bare heading chunks** — heading-only chunks with no substantive text | `"4. Customer Default"` — present but carries zero information | Route 3 |
| **Theme coverage gaps** — thematic queries miss known topics | Average **69.8%** theme coverage (10 questions, Feb 8 benchmark) | Route 3 |

### 1.2 Two Powerful GDS Tools Sit Underutilized

The indexing pipeline (Step 8) computes two graph-structural signals via Neo4j GDS, but neither is fully exploited at query time:

| Tool | Indexed? | Used at Query Time? | What's Wasted |
|------|----------|---------------------|---------------|
| **GDS KNN** — `SEMANTICALLY_SIMILAR` edges between entities by embedding cosine similarity | ✅ Yes (Step 8a) | ⚠️ Partial — PPR Path 3 traverses them, but resulting PPR scores are **discarded before synthesis** | The entire PPR score computation. KNN improves which entities PPR finds, but downstream code throws away the scores. |
| **GDS Louvain** — `community_id` integer on every entity based on graph topology | ✅ Yes (Step 8b) | ❌ No — `CommunityMatcher` never reads `community_id`. It generates ad-hoc entity clusters per query via a fragile 4-level fallback cascade. | Topological clustering. Entities that co-occur in the same clauses form Louvain clusters, but Route 3 can't see them. |

---

## 2. Issue Analysis

### 2.1 The Problem is Two-Layered

These issues exist at two different layers, and **both need fixing — they are complementary, not competing**:

| Layer | What's Broken | Tools That Fix It |
|-------|---------------|-------------------|
| **Retrieval quality** — which entities/chunks make it into the candidate set | Louvain communities unused, KNN edges partially wasted | GDS Louvain composition, GDS KNN score propagation, GDS structural embeddings (FastRP) |
| **Context assembly quality** — how the candidate set is filtered and presented to the LLM | No dedup, no token budget, no score ranking, no noise filtering | Chunk dedup, token budget, PPR score-weighted allocation, noise filters |

With KNN improvements but no token budget → better entities but still 49K tokens of noise.  
With token budget but no KNN → capped context but may cap it with noise entities from structural paths alone.

### 2.2 PPR Score Flow — Where It Breaks

HippoRAG 2's PPR algorithm computes per-entity relevance scores via 5 traversal paths:

| Path | Traversal | What It Captures |
|------|-----------|------------------|
| **Path 1** | Seed entity → graph edges → neighbor entities | Direct co-occurrence relationships |
| **Path 2** | Seed → mentions → chunks → sections → similar sections → chunks → entities | Cross-section topical similarity |
| **Path 3** | Seed → `SEMANTICALLY_SIMILAR` → neighbor entities (**KNN edges**) | Cross-document entity linking by embedding similarity |
| **Path 4** | Seed → section → shared-entity sections → hub entities | Hub entity discovery via section co-membership |
| **Path 5** | Seed → section → hub entities (direct) | High-mention-count entity discovery |

Final entity score = sum of all 5 path contributions. Scores are correct and meaningful. But then:

```python
# synthesis.py L754 — THE BREAK POINT
for name, _score in evidence_nodes:    # ← score DISCARDED here
    cleaned = _clean_entity_name(name)
    ...
```

```
PPR 5-path traversal → evidence_nodes: List[(name, score)]
                                ↓
    ┌─ get_ppr_evidence_chunks(): scores USED for ranking ✓ (Route 3 fast_mode only)
    │
    └─ synthesis._retrieve_text_chunks(): scores DISCARDED ✗
       └─ _build_cited_context(): chunks grouped by document, NO score ordering
          └─ LLM prompt: unbounded, unranked bag of chunks
```

### 2.3 Route 3 Community Matching — Why It Misses Themes

Route 3's `CommunityMatcher` generates ad-hoc entity clusters per query via a **4-level fallback cascade**:

```
Level 1: Embedding similarity search on entity nodes (threshold > 0.35)
Level 2: Keyword matching on entity names/descriptions
Level 3: Multi-document sampling (top entities per document)
Level 4: Degree-based fallback (highest-connected entities)
```

Three fundamental weaknesses:

| Weakness | Effect | Example |
|----------|--------|---------|
| **No topological awareness** | Clusters formed by text similarity, not graph structure | `Pumper`, `Holding Tank Owner`, `pumping equipment` share dense contract edges but names don't match "key parties" |
| **No semantic summaries** | Dynamic "community" gets placeholder summary: `"Dynamically generated..."` | Hub entity selection is blind to what the cluster represents |
| **Non-deterministic** | Same query can produce different clusters depending on which fallback triggers | Violates the architecture's determinism principle |

Meanwhile, GDS Louvain already assigns `community_id` based on graph topology — exactly the signal CommunityMatcher needs but never reads.

### 2.4 KNN Embedding Gap — Text vs Structural

KNN currently uses **Voyage AI text embeddings** (`embedding_v2`). This captures entity name/description similarity but NOT graph topology:

| Embedding Type | Encodes | "AGENT'S FEES" is similar to... |
|---------------|---------|----------------------------------|
| **Text (Voyage)** — current | Textual semantics of entity name + description | "FEES", "AGENCY CHARGES", "BROKER'S FEES" (name-similar) |
| **Structural (FastRP)** — future | Graph neighborhood: shared edges, sections, documents | "MANAGEMENT FEE", "COMMISSION RATE", "PAYMENT TERMS" (graph-position-similar) |

The original insight: *"KNN embedding will enhance the LLM embedding from graph relationships"* — this requires GDS structural embeddings (FastRP or node2vec), not yet implemented.

### 2.5 KNN Impact by Route

| Route | Impact | Why |
|-------|--------|-----|
| **Route 2** (Local) | **MEDIUM** | PPR Path 3 adds semantic gravity (reach `MANAGEMENT FEE` from `AGENT'S FEES`). But real noise problem is downstream — scores discarded at synthesis. Complementary to score-weighted allocation. |
| **Route 3** (Global) | **MINIMAL** | CommunityMatcher doesn't use PPR Path 3. Chunks collected before PPR runs. Near-zero impact — Louvain communities are what transforms Route 3. |
| **Route 4** (DRIFT) | **MEDIUM-HIGH** | Biggest beneficiary. 3-5 PPR passes compound KNN benefit. Better sub-question entity discovery. Most valuable combined with score-weighted allocation. |

### 2.6 Asymmetric KNN Config

Route 2 PPR Path 3 **always** traverses `SEMANTICALLY_SIMILAR` edges (no `knn_config` filter). Route 4 beam search **conditionally** includes them based on `knn_config`. Inconsistent behavior for the same edges.

---

## 3. Proposed Solutions

### 3.1 Solution A: Louvain → LazyGraphRAG Community Composition — ✅ DONE

**Core idea:** Use GDS Louvain to define community boundaries (structural), then use LazyGraphRAG to summarize each community (semantic). Each tool does what it's best at.

| Concern | Tool | Strength |
|---------|------|----------|
| **Which entities belong together?** (structure) | GDS Louvain | Fast, deterministic, captures graph topology |
| **What does this group mean?** (semantics) | LazyGraphRAG LLM summarization | Human-readable descriptions for semantic matching |

**Neither alone solves the problem:**
- Louvain without summaries → communities can't be matched to queries (no semantic bridge)
- Summaries without Louvain → summaries describe ad-hoc clusters that don't reflect real graph structure

**Together:** Louvain defines subgraph boundaries → LazyGraphRAG summarizes each subgraph → CommunityMatcher matches queries to summaries.

```
INDEX TIME:
  Step 8b: GDS Louvain → community_id on entities          [EXISTING]
  Step 9a: Group entities by community_id                    [NEW]
  Step 9b: Create :Community nodes + :BELONGS_TO edges       [NEW]
  Step 9c: LLM summary per community                        [NEW]
  Step 9d: Voyage embedding per community summary            [NEW]

QUERY TIME (Route 3):
  CommunityMatcher → semantic match against community embeddings
  → top-3 communities → hub entities → PPR → synthesis
```

**LazyGraphRAG "lazy" principle — tension and resolution:**

Pre-computing summaries at index time could violate LazyGraphRAG's "lazy" principle. Resolved because:
- Louvain runs in seconds (not expensive like Microsoft GraphRAG)
- LLM summaries are per-community (~10-30), not per-entity (~hundreds)
- Total added indexing: ~30-60s — negligible vs entity extraction (~60-120s)
- **Option A (eager, at index time) chosen** over Option B (lazy, first-query triggers) — indexing already takes minutes, every query benefits from day one

This is NOT Microsoft GraphRAG's heavy community pipeline. It's LazyGraphRAG's lightweight "just enough" approach on Louvain's structural output.

**Route 3 impact — transformative:**

| Question | Before (ad-hoc cascade) | After (Louvain composition) |
|----------|------------------------|---------------------------|
| Q-G6 "key parties" | `pumper` missed — 26 form-label occurrences | Louvain clusters `Pumper`, `Holding Tank Owner`, `pumping equipment` → summary mentions pumper-owner relation → matched |
| Q-G5 "dispute resolution" | `default` missed — bare heading only | Louvain clusters `Customer Default`, `Payment Terms`, `Legal Fees` → summary mentions "default remedies" |
| Q-G4 "financial terms" | `expenses`/`income` missed by 2/5 models | Financial entities form Louvain cluster → summary describes income/expense terms |

**Status:** ✅ Implemented, tested (25/25 unit tests), benchmarked (69.8% → 100% theme coverage, +41% citations), deployed (`1d78ec26-05`).  
**Commits:** `8271e404`, `9062b2c1`, `b42b3352`, `c662a6bb`, `1d78ec26`, `4c54bc60`  
**Design doc:** `DESIGN_LOUVAIN_COMMUNITY_SUMMARIZATION_2026-02-09.md`

---

### 3.2 Solution B: KNN Score Propagation + GDS Structural Embeddings

**Phase B.1 (immediate): Propagate PPR scores through to synthesis**

Stop discarding PPR scores. Use them to rank chunks and enforce a token budget:

```python
# BEFORE — scores discarded:
for name, _score in evidence_nodes:
    cleaned = _clean_entity_name(name)

# AFTER — scores propagated:
entity_scores = {_clean_entity_name(name): score for name, score in evidence_nodes}
```

Changes:
1. Pass `entity_scores` dict through to `_build_cited_context()` — chunks ranked by source entity's PPR score
2. Score-ranked assembly — higher-scored chunks earlier in LLM prompt (LLM attention bias toward early context)
3. Token budget — stop adding chunks at configurable limit (e.g., 32K tokens)
4. Normalize `knn_config` — both Route 2 and 4 always include KNN edges (already quality-filtered by `similarity_cutoff=0.60`)

**Phase B.2 (future): GDS Structural Embeddings (FastRP)**

Add FastRP to `_run_gds_graph_algorithms()` — generate embeddings encoding **graph neighborhood structure**:
- Store as `embedding_structural` property → re-run KNN on combined embeddings
- `SEMANTICALLY_SIMILAR` edges then encode textual AND topological similarity
- Effort: HIGH (new algorithm, new property, KNN recalculation, benchmarking)

**Files to modify:**

| # | File | Change |
|---|------|--------|
| 1 | `pipeline/synthesis.py` | Propagate scores, score-ranked assembly, token budget, chunk dedup |
| 2 | `services/async_neo4j_service.py` | (Optional) Normalize knn_config in PPR Path 3 |
| 3 | `indexing/lazygraphrag_pipeline.py` | (Future) Add FastRP to GDS pipeline |

---

### 3.3 Solution C: Context De-noising Pipeline

Three phases, each building on the previous:

**Phase 1: Chunk Dedup + Token Budget** (combined with B.1)

| Fix | Method | Impact |
|-----|--------|--------|
| Content-hash dedup | Hash chunk text → keep first occurrence → eliminate 56.5% duplicates | Halves context volume |
| Cross-entity dedup | When entities A and B both reference chunk X, keep chunk associated with highest-scored entity | Removes redundant citations |
| Token budget | Accumulate tokens, stop at limit (32K default). Strict score-ranked → dropped chunks are least relevant. | Bounded, relevant context |

**Design note — strict score-ranking in Phase 1:** The token budget uses pure score-ranked truncation with no document-grouping logic. This means a high-scoring chunk from Document A may appear adjacent to a high-scoring chunk from Document B, potentially without their surrounding context. This is *intentional* for Phase 1: simplicity first, benchmark, then refine. Document-integrity grouping ("if we accept one chunk from a section, prefer its neighbors") is deferred to Phase 2 — it adds complexity and may not be needed if score-ranking alone produces coherent context.

**Phase 2: Noise Filtering** (after Phase 1 validated)

| Fix | Method | Impact |
|-----|--------|--------|
| Form-label filter | Detect chunks predominantly form fields (`Name:____`, `Date:____`) → deprioritize | Removes structural noise |
| Bare heading filter | Chunks with <20 substantive characters → deprioritize | Removes empty headings |
| Minimum content threshold | Chunks with <50 tokens of actual content → deprioritize | Budget spent on useful text |
| Document-integrity grouping | If a chunk is accepted, prefer its same-section neighbors (within budget) over distant lower-scored chunks | Reduces cross-document fragmentation |

**Phase 2 files:** New `pipeline/chunk_filters.py` + integration in `synthesis.py`

**Phase 3: PPR Weight Tuning** (after Phase 1+2 validated)

| Fix | Method | Impact |
|-----|--------|--------|
| Path contribution analysis | Log which of 5 PPR paths contributes most per entity | Identifies noise-dominant paths |
| Weight tuning | Adjust `damping`, `sim_weight`, `hub_weight` | Better signal balance |
| KNN cutoff tuning | Test 0.65, 0.70 (current 0.60 may be too permissive) | Tighter semantic edges |
| Community-aware PPR seeding | Bias PPR seeds toward entities in CommunityMatcher's top-3 communities | Connects Louvain to PPR |

**Dependency chain:**
```
Phase 1 (Dedup + Budget) ← combined with B.1 (score propagation)
Phase 2 (Noise Filters) ← independent, can parallel with Phase 1
Phase 3 (PPR Tuning) ← depends on Phase 1+2 benchmarks
```

---

## 4. Architecture Alignment

All changes must preserve the HippoRAG 2 + LazyGraphRAG dual architecture.

### 4.1 Framework Alignment Check

| Proposed Change | LazyGraphRAG | HippoRAG 2 | Verdict |
|----------------|-------------|------------|----------|
| KNN edge activation | Neutral (index-time edges feed PPR) | **Enhances** Path 3 | ✅ Safe |
| PPR score-weighted allocation | Neutral (post-retrieval) | **Fulfills** design intent | ✅ Safe |
| Chunk dedup + token budget | Neutral (post-retrieval) | Neutral | ✅ Safe |
| Louvain summaries replacing CommunityMatcher | **Violates** lazy principle | Neutral | ⚠️ Rejected |
| Louvain → LazyGraphRAG composition (Step 9) | **Compatible** (lazy-scale cost) | Neutral | ✅ Adopted |
| GDS structural embeddings (FastRP) | Neutral (index-time enrichment) | Enhances KNN quality | ✅ Safe (future) |

**Key tension resolved:** Directly replacing CommunityMatcher's lazy clustering with pre-computed Louvain summaries would regress toward Microsoft GraphRAG's expensive indexing. The composition pattern resolves this: Louvain provides structural boundaries (seconds), LazyGraphRAG provides semantic summaries (per-community, not per-entity). Total ~30-60s index time — orders of magnitude cheaper than Microsoft GraphRAG.

### 4.2 Principles

| Principle | How Preserved |
|-----------|--------------|
| **HippoRAG 2 PPR backbone** | PPR 5-path traversal unchanged. GDS algorithms enrich the graph, don't replace it. `SEMANTICALLY_SIMILAR` is one of five PPR paths, not the primary signal. |
| **LazyGraphRAG community layer** | CommunityMatcher remains Route 3's entry point. Louvain communities (Step 9) feed it with structural clustering. Ad-hoc cascade remains as fallback. |
| **KNN + Louvain synergy** | KNN creates semantic bridges between distant entities. Louvain identifies dense subgraphs in the enriched graph. Both inform PPR scoring — KNN via Path 3, Louvain via community hub entities. |
| **Determinism** | Louvain is deterministic. Summaries generated once at index time. KNN edges deterministic. Token budget truncation deterministic (score-ranked, fixed budget). |
| **Backward compatibility** | No GDS → Path 3 returns 0, others compensate. No communities → ad-hoc cascade. No budget → no truncation. All changes additive. |

### 4.3 Target State

After all solutions, the synthesis LLM receives:
- Chunks **sorted by PPR score** (highest relevance first)
- **Token budget enforced** (no unbounded context)
- **Duplicates eliminated** (content-hash dedup)
- **Noise filtered** (form labels, bare headings)
- **Citation metadata preserved** (document source, page, section)

---

## 5. Implementation Plan

### 5.1 Expected Impact

| Metric | Current (Feb 8) | After A (done) | After B+C Phase 1 | After C Phase 2 | After C Phase 3 + B.2 |
|--------|-----------------|----------------|--------------------|-----------------|-----------------------|
| Theme coverage (Route 3) | 69.8% | **100%** | 100% | 100%+ | 100%+ |
| Duplicate chunks | 56.5% | 56.5% | **~0%** | ~0% | ~0% |
| Context tokens (Route 2) | ~49K | ~49K | **≤32K** | ≤32K | ≤32K |
| Context tokens (Route 3) | ~100K+ | ~100K+ | **≤32K** | ≤32K | ≤32K |
| Context tokens (Route 4) | ~55K-460K | ~55K-460K | **≤32K** | ≤32K | ≤32K |
| PPR scores in synthesis | Discarded | Discarded | **Used** | Used | Tuned |
| Form-label noise | Present | Present | Present | **Filtered** | Filtered |
| KNN embedding type | Text only | Text only | Text only | Text only | **Text + Structural** |

### 5.2 Weekly Schedule

#### Week 1 — Verify KNN + Phase 1 Pipeline Fixes (immediate relief)

| Step | Work | Depends On | Est. Effort |
|------|------|------------|-------------|
| 1 | ~~Louvain → LazyGraphRAG composition (Step 9)~~ | — | ✅ DONE |
| 2 | Verify `test-5pdfs-v2-fix2` has `SEMANTICALLY_SIMILAR` edges | — | 15 min |
| 3 | If not, reindex with `knn_enabled=True` or run maintenance recompute | Step 2 | 30 min |

> **Audit traceability (February 9, 2026):** Steps 2-3 are justified by the **graph completeness audit** documented in `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` (Feb 6 updates): `test-5pdfs-v2-fix2` was found to have **Entity KNN SEMANTICALLY_SIMILAR = 0** (only KVP↔KVP KNN edges present, 540 total). GDS properties (`community_id`, `pagerank`) were also 0 on all nodes. A reindex with deployed fixes is expected to resolve all issues.

| 4 | Chunk dedup (content-hash) in `_retrieve_text_chunks()` | — | 1-2 hours |
| 5 | Token budget in `_build_cited_context()` | — | 1-2 hours |

#### Week 2 — PPR Score Propagation + Benchmarking

| Step | Work | Depends On | Est. Effort |
|------|------|------------|-------------|
| 6 | PPR score propagation to synthesis | Steps 4-5 | 2-3 hours |
| 7 | Score-ranked context ordering | Step 6 | 1 hour |
| 8 | KNN config consistency (Route 2 vs 4) | — | 1 hour |
| 9 | Benchmark regression (all routes, 10-question suite) | Steps 4-7 | 2 hours |

#### Week 3 — Noise Filters + PPR Tuning

| Step | Work | Depends On | Est. Effort |
|------|------|------------|-------------|
| 10 | Noise filters (form-label, bare heading) | — | 2-3 hours |
| 11 | PPR weight tuning (damping, sim_weight, hub_weight) | Step 9 results | 3-4 hours |
| 12 | Community-aware PPR seeding (bias toward matched communities) | Steps 1+11 | 2-3 hours |

#### Documentation Updates (keep architecture aligned)

| Step | Work | Depends On | Est. Effort |
|------|------|------------|-------------|
| D1 | ~~Apply corrections from `ARCHITECTURE_CORRECTIONS_2026-02-08.md` into `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` (route numbering, Stage 2.2 engine, add Stage 2.2.5)~~ | — | ✅ DONE |
| D2 | ~~Add audit traceability note for Steps 2/3~~ | — | ✅ DONE |

#### Future — GDS Structural Embeddings

| Step | Work | Depends On | Est. Effort |
|------|------|------------|-------------|
| 13 | Add FastRP to `_run_gds_graph_algorithms()` | Steps 9-12 validated | 4-6 hours |
| 14 | Re-run KNN on structural embeddings | Step 13 | 1 hour (reindex) |
| 15 | Benchmark: text-only KNN vs text+structural KNN | Step 14 | 2-3 hours |
| 16 | Route 4 sub-question community routing | Steps 1+12 | 3-4 hours |

---

## 6. Reference

### 6.1 Documents

| Document | Content |
|----------|---------|
| `DESIGN_LOUVAIN_COMMUNITY_SUMMARIZATION_2026-02-09.md` | Detailed design for Step 9 (Louvain → communities) |
| `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` | 6 gaps + 3-phase optimization plan |
| `ANALYSIS_CONTEXT_QUALITY_AND_DEDUP_2026-02-08.md` | 56.5% duplicate chunks analysis |
| `ARCHITECTURE_CORRECTIONS_2026-02-08.md` | 13 corrections to architecture doc (pending) |
| `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` | Main architecture doc (Section 23 updated) |

### 6.2 Key Code Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| GDS KNN edge creation | `indexing/lazygraphrag_pipeline.py` | `_run_gds_graph_algorithms()` L1660-1862 |
| GDS Louvain + Step 9 | `indexing/lazygraphrag_pipeline.py` | `_materialize_louvain_communities()` L1930+ |
| PPR 5-path query | `services/async_neo4j_service.py` | `_build_ppr_query_with_section_graph()` L708-950 |
| PPR Path 3 (KNN edges) | `services/async_neo4j_service.py` | L790-800 |
| Score discarding (break point) | `pipeline/synthesis.py` | `_retrieve_text_chunks()` L754 |
| Context assembly | `pipeline/synthesis.py` | `_build_cited_context()` L800+ |
| CommunityMatcher | `pipeline/community_matcher.py` | `_load_from_neo4j()`, `_semantic_match()` |
| Route 4 beam search | `services/async_neo4j_service.py` | `semantic_multihop_beam()` L1187 |
| KNN config in orchestrator | `orchestrator.py` | `query()` L337, `force_route()` L2175 |