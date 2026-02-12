# Route 4 Architecture Assessment & Improvement Recommendations

**Date:** 2026-02-12  
**Scope:** Route 4 DRIFT Multi-Hop — architectural soundness, HippoRAG 2 alignment, actionable improvements  
**Source:** Code review of `route_4_drift.py`, `tracing.py`, `async_neo4j_service.py`, `synthesis.py`, plus `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` and `ARCHITECTURE_CORRECTIONS_2026-02-08.md`

---

## 1. What Route 4 Actually Is

The architecture doc calls it "DRIFT Equivalent enhanced with HippoRAG 2 PPR." The actual hot path is:

```
Query → LLM decomposition (4.1) → LLM NER per sub-question (4.2)
      → 6-layer seed resolution → semantic beam graph traversal (4.3)
      → confidence loop (4.3.5) → coverage gap fill (4.3.6)
      → sentence-level synthesis (4.4)
```

**Honest name:** DRIFT decomposition + semantic beam search + sentence-level synthesis.

Route 4 borrows *concepts* from HippoRAG 2 (knowledge graph + PPR) and DRIFT (query decomposition), but the active traversal algorithm — `trace_semantic_beam()` — is a custom algorithm that exists in neither paper. Standard PPR (`trace()`) is never invoked by Route 4.

---

## 2. What's Architecturally Sound

### 2.1 Semantic Beam Search (Stage 4.3) — Genuine Improvement Over Vanilla PPR

HippoRAG 2's PPR propagates probability mass along all edges equally, causing **topic drift after 2–3 hops.** `trace_semantic_beam()` re-scores candidates at each hop using `vector.similarity.cosine(entity.embedding, query_embedding)`, keeping only the top `beam_width` most query-aligned entities.

This is well-motivated and solves a known PPR limitation. The implementation in `async_neo4j_service.py` (L1286–L1510) uses native Neo4j vector similarity — no GDS dependency.

| Metric | Pure PPR | Semantic Beam |
|--------|----------|---------------|
| Hop 1 Precision | High | High |
| Hop 3 Precision | Medium-Low (drift) | High (query-aligned) |
| Coverage | Higher (explores all edges) | Lower (filtered frontier) |
| Use Case | Exploratory | Precision-critical |

**Configuration (from `route_4_drift.py`):**

| Stage | beam_width | max_hops | Purpose |
|-------|-----------|----------|---------|
| 4.3 Main Traversal | 30 | 3 | Primary evidence collection |
| 4.3.5 Confidence Loop | 15 | 2 | Refinement from new seeds |
| 4.2 Discovery Pass | 5 | 2 | Quick context per sub-question |

### 2.2 Seed Resolution — Should Collapse to 2 Layers

The current 6-layer cascade (exact → alias → KVP key → substring → token overlap → vector similarity)
was designed to compensate for a noisy entity graph where exact matching frequently failed.

With Phase B (sentence-based entity extraction, classifier, no generic aliases), layers 3–5 become
both **unnecessary** and **harmful**:

| Layer | Purpose | Post-Phase B Status |
|-------|---------|--------------------|
| 1. Exact match | Deterministic, indexed | **Keep** — always valid |
| 2. Alias match | Same query as L1 | **Keep** — always valid |
| 3. KVP key match | Structured data entities had weird names | **Remove** — compensating for chunk-level noise |
| 4. Substring match | "Contract Date" should match "Date" | **Remove** — primary source of false-positive seeds |
| 5. Token overlap | Jaccard-like fuzzy match | **Remove** — compensating for fragmented entities |
| 6. Vector similarity | Semantic fallback | **Promote** — the correct approach for non-exact matches |

**Recommended: 2-layer resolution**

- **Layer 1: Exact + Alias** (current Layers 1-2, single indexed Cypher — sub-ms)
- **Layer 2: Vector similarity** (current Layer 6 via ANN index — ~2-5ms)

Route 2 proved that semantic search + sentence extension is sufficient — no BM25, no PPR, no
fuzzy string matching needed. The beam search already does semantic pruning at every hop; having
seed resolution also be semantic-first makes the entire pipeline semantically coherent.

**Why this matters for Route 4 specifically:**
The current failure mode: Layer 4 (substring) matches "Name" to "Pumper's Name", which becomes a
beam seed, which expands to 10 neighbors at hop 1, 100 at hop 2 — all completely irrelevant.
With vector similarity, "Name" would match something like "Contract Party Name" which is at least
semantically adjacent.

**Latency:** Route 4 already computes `query_embedding` for beam search (`_get_query_embedding(sub_q)`
in `route_4_drift.py`). Reuse it for vector seed resolution — zero additional embedding calls.
ANN index query is ~2-5ms vs current cascade of 4-5 sequential Cypher queries at ~5ms each = 20-25ms.
Vector-first is actually **faster**.

**Implementation:** Collapse `get_entities_by_names()` in `async_neo4j_service.py` to accept
`query_embedding` parameter. If exact+alias misses, use `get_entities_by_vector_similarity()`.
Remove Strategies 3-5 entirely. Update both callers in `tracing.py` (`trace()` and
`trace_semantic_beam()`) to pass their query embeddings.

**Code:** `async_neo4j_service.py` L186–L395, callers at `tracing.py` L190, L363

### 2.3 Confidence Loop (Stage 4.3.5) — Well-Motivated

Detects two real failure modes:
- **Sparse subgraphs:** Not enough evidence per sub-question
- **Entity concentration:** One entity dominates (e.g., "Contract" appears in every sub-question)

Re-decomposes only the "thin" questions, avoiding full recomputation.

**Code:** `route_4_drift.py` L540–L600 (`_compute_subgraph_confidence()`)

### 2.4 Community-Aware Seed Augmentation — Sound

Adds top-degree peers from the same Louvain community to bias PPR toward the topological neighborhood. Non-fatal on failure. Controlled via `PPR_COMMUNITY_SEED_AUGMENT` env var (default: 5).

**Code:** `tracing.py` L270–L291

### 2.5 `comprehensive_sentence` Mode — Highest Performing Path

Bypasses entity disambiguation entirely, retrieves ALL documents with Azure DI sentence boundaries, passes to a single LLM call. **100% accuracy (14/14)** on 5-PDF cross-document benchmark vs 62–93% for graph-based mode.

**Code:** `synthesis.py` `_comprehensive_sentence_level_extract()`

---

## 3. Architectural Issues (Ranked by Severity)

### 3.1 CRITICAL: PPR Scores Are Discarded in Chunk Retrieval

**All routes** compute PPR/beam scores but `_retrieve_text_chunks()` gives every entity uniform `limit_per_entity=12` regardless of rank. The mathematical ranking — the entire point of PPR — is thrown away.

**Impact:** A PPR-top entity (score 0.95) and a marginal entity (score 0.12) each get 12 chunks. No score-proportional budgeting.

**Location:** `synthesis.py` `_retrieve_text_chunks()` (PPR scores → discarded)

**Fix (planned, Solution B.1):** Budget chunks proportionally to PPR score. Top entities get 12, bottom get 2–3.

### 3.2 CRITICAL: 56.5% Duplicate Chunks (No Cross-Entity Dedup)

When a chunk MENTIONS multiple entities, it appears once per entity in the context. `_retrieve_text_chunks()` uses `chunks.extend()` without checking `chunk_id` uniqueness.

**Impact:** ~49K tokens for a simple factual lookup that should need ~25K.

**Fix:** 5-line change — add `seen_chunk_ids: set` to `_retrieve_text_chunks()`.

### 3.3 HIGH: No Token Budget on Context Assembly

Each chunk's full text (~1,150 tokens avg) is appended verbatim. Route 4 with 3 PPR passes + coverage gap fill can send **100K+ tokens** to the LLM with no re-ranking or truncation.

**Location:** `synthesis.py` `_build_cited_context()` (no limit)

**Fix (planned, Phase 1):** Token budget cap with priority ordering by PPR score.

### 3.4 HIGH: Coverage Gap Fill Is Compensating for Weak Entity Extraction

Stage 4.3.6 exists because entity-based retrieval misses entire documents. The hybrid keyword/semantic reranking (`0.7 * keyword + 0.3 * semantic`) is ad-hoc. This is a 200-line band-aid for a root cause that should be fixed at indexing time (sentence-based entity extraction — see Phase B of denoising plan).

**Impact:** Injects potentially irrelevant content for specific queries. Necessary only for "list all" corpus-level queries.

### 3.5 MEDIUM: Double Graph Traversal in Discovery + Main Trace

Stage 4.2 runs `trace_semantic_beam(beam_width=5, max_hops=2)` per sub-question for confidence counting only. Stage 4.3 re-runs `trace_semantic_beam(beam_width=30, max_hops=3)` with all seeds consolidated. The discovery traces aren't reused as evidence.

**Impact:** ~2× graph queries needed. For 3 sub-questions: 3 discovery traces + 1 main trace = 4 beam searches.

**Fix:** Use discovery traces as preliminary evidence, then augment in Stage 4.3 rather than re-tracing.

### 3.6 MEDIUM: Hop 0 Vector Expansion Dilutes Graph Signal

Before any graph traversal, `semantic_multihop_beam` runs a standalone `db.index.vector.queryNodes()` and injects results into the beam at 0.9× score. Entities with **zero graph connectivity** can enter the beam purely via embedding similarity.

**Impact:** Pragmatically useful (catches isolated entities like Exhibit A details), but means the system is a **hybrid vector+graph** approach, not graph-first. The structural guarantee of HippoRAG 2 is diluted.

**Location:** `async_neo4j_service.py` L1428–L1450

### 3.7 LOW: Standard PPR Code Is Dead in Route 4

`DeterministicTracer.trace()` (the standard PPR path) is never called by Route 4. Route 4 exclusively uses `trace_semantic_beam()`. The PPR code in `_trace_with_async_neo4j()` is used by Routes 2/3 but is dead weight in Route 4's execution path.

### 3.8 LOW: Query Decomposition Has No Structural Validation

`_drift_decompose()` is pure prompt engineering. There's no check that sub-questions are well-formed, collectively cover the original query, or avoid overlap. The "preserve ALL constraints" instruction is good but unenforceable.

---

## 4. Does Route 4 Need Communities?

**Short answer: No. Route 4 does not use communities in any meaningful way today.**

### Current Community Usage by Route

| Route | Uses CommunityMatcher? | Uses community_id on entities? | Uses Community nodes? |
|-------|----------------------|-------------------------------|----------------------|
| Route 3 (Global) | **Yes** — Step 1, primary entry point | No | **Yes** — summaries for MAP phase |
| Route 4 (DRIFT) | **No** | Indirectly (seed augmentation) | **No** |
| Route 2 (Local) | **No** | No | No |

### What Route 4 Actually Uses from Communities

The **only** community-related code touching Route 4 is `community_seed_augment` in `tracing.py` L270–L291. This looks up `community_id` on resolved seed entities and adds top-degree peers from the same community. It's:

- A **seed augmentation** heuristic, not community matching
- Controlled by `PPR_COMMUNITY_SEED_AUGMENT` env var (default: 5, set to 0 to disable)
- Non-fatal — if `get_community_peers()` fails, Route 4 proceeds normally
- Applied inside `_trace_with_async_neo4j()` (the PPR path), but **NOT** inside `trace_semantic_beam()` (the active Route 4 path)

**Wait — this means Route 4 doesn't even use community augmentation in its active code path.**

`trace_semantic_beam()` (L324–L396 in `tracing.py`) resolves seeds via `get_entities_by_names()` and calls `semantic_multihop_beam()` directly. It never calls `_trace_with_async_neo4j()` where the community augmentation lives.

### Does Route 4 Need Pre-Computed Community Artifacts?

**No.** The pre-computed community pipeline consists of:

1. **GDS Louvain community detection** — assigns `community_id` to Entity nodes
   (`lazygraphrag_pipeline.py` L2423–L2440)
2. **Community materialization** — creates `Community` nodes with LLM-generated summaries
   (`_materialize_louvain_communities()`, L2491+)
3. **PART_OF_COMMUNITY edges** — links entities to their community nodes
4. **Community embeddings** — vectorized summaries for `CommunityMatcher`

Route 3 uses all four: `CommunityMatcher` selects relevant communities by embedding similarity,
then the MAP phase uses community summaries as context for LLM analysis.

Route 4 uses **none of them** in its active code path. The community seed augmentation code
(`tracing.py` L270–291) only reads `community_id` from Entity nodes (artifact #1), not Community
nodes or summaries. And even that code lives in `_trace_with_async_neo4j()` which Route 4 never calls.

### Recommendation

**Route 4 does not need `Community` nodes, `CommunityMatcher`, or pre-computed community summaries.**
Communities are a Route 3 concept (thematic grouping for map-reduce). Route 4's
decompose-discover-trace architecture gets its topological context from the entity graph +
semantic beam traversal, not from pre-computed community summaries.

The `community_id` property on Entity nodes (from Louvain) is used by `synthesis.py`'s
community-aware entity scoring (L1153+) for de-noising, but this is a retrieval filter,
not a Route 4-specific dependency — it applies equally to all routes.

If community-aware seed augmentation proves valuable, it should be moved into
`trace_semantic_beam()` rather than living in the dead PPR path. But given Route 4's current
benchmark results, this is low priority.

---

## 5. The `comprehensive_sentence` Insight — Implications for Architecture

The Feb 4 finding deserves architectural weight:

| Mode | Accuracy | Graph Used? | LLM Calls | Latency |
|------|----------|-------------|-----------|---------|
| Route 4 graph traversal | 62–93% (config-dependent) | Yes | Multiple | ~8s |
| `comprehensive_sentence` (bypass graph) | **100%** | No | 1 | ~45s |

**Architectural implication:** For corpora that fit in the LLM context window (≤20 documents), graph-based retrieval adds complexity without accuracy benefit. The graph's value increases with corpus size, where you *can't* send everything to the LLM.

### Recommended Threshold Strategy

```python
if total_documents <= 20:
    # All sentences fit in context — use comprehensive_sentence
    return await self._comprehensive_sentence_level_extract(query, ...)
else:
    # Graph-based selection necessary — use DRIFT + semantic beam
    return await self._drift_multi_hop(query, ...)
```

This lets you honestly claim:
- **Small corpora:** 100% accuracy via exhaustive sentence-level analysis
- **Large corpora:** Graph-guided selection with sentence-level citations

---

## 6. Prioritized Improvement Roadmap

### Phase 1: Quick Wins (1–2 days, no re-index)

| # | Fix | Impact | LOC | File |
|---|-----|--------|-----|------|
| 1 | Chunk deduplication (`seen_chunk_ids` set) | -50% context tokens | ~5 | `synthesis.py` |
| 2 | PPR score-proportional chunk budgeting | Correct retrieval ranking | ~30 | `synthesis.py` |
| 3 | Auto-select `comprehensive_sentence` for ≤20 docs | 100% accuracy on small corpora | ~15 | `route_4_drift.py` |

### Phase 2: Structural Fixes (1 week, no re-index)

| # | Fix | Impact | LOC | File |
|---|-----|--------|-----|------|
| 4 | Token budget cap on context assembly | Prevent 100K+ token blowup | ~40 | `synthesis.py` |
| 5 | Reuse discovery traces as evidence (eliminate double-trace) | -50% graph queries | ~30 | `route_4_drift.py` |
| 6 | Gate hop-0 vector expansion behind flag | Honest graph-first vs hybrid | ~5 | `async_neo4j_service.py` |
| 7 | Unify synthesis code paths (Route 3 vs Routes 2/4) | Single place for budget/dedup fixes | ~100 | `synthesis.py` |

### Phase 3: Source Denoising (1 week, requires re-index)

| # | Fix | Impact | LOC | File |
|---|-----|--------|-----|------|
| 8 | Sentence-based entity extraction (Phase B of denoising plan) | Clean entity graph at source | ~300 | `lazygraphrag_pipeline.py` |
| 9 | Remove `_generate_generic_aliases()` | Eliminate compensating code | -50 | `lazygraphrag_pipeline.py` |
| 10 | Move community augmentation into `trace_semantic_beam()` or remove | Fix dead code path | ~20 | `tracing.py` |
| 11 | Collapse 6-layer seed resolution to 2-layer (exact+alias → vector) | Eliminate false-positive seeds | ~-120 | `async_neo4j_service.py` |

### Phase 4: Naming & Documentation Honesty (ongoing)

| # | Fix | Impact |
|---|-----|--------|
| 12 | Rename "HippoRAG 2 PPR" references to "semantic beam search" in Route 4 | Architectural clarity |
| 13 | Document `comprehensive_sentence` as the default for small corpora | Honest positioning |
| 14 | Update architecture doc per `ARCHITECTURE_CORRECTIONS_2026-02-08.md` | Consistency |

---

## 7. Summary

**Route 4 is architecturally sound at the macro level.** The decompose → discover → traverse → synthesize pattern is a valid multi-hop RAG architecture. The semantic beam search is a genuine improvement over vanilla HippoRAG 2 PPR for intent-aligned retrieval.

**However:**
1. The system works primarily because of LLM synthesis quality and Azure DI sentence-level integration, not because of graph traversal sophistication
2. The best-performing mode (`comprehensive_sentence`, 100% accuracy) bypasses the graph entirely
3. Three critical implementation bugs (PPR scores discarded, 56.5% chunk duplication, no token budget) undermine retrieval quality
4. Route 4 does **not** need communities — that's a Route 3 concept
5. The "HippoRAG 2" framing is aspirational; the active path is semantic beam search

**Recommended narrative:** Position the architecture as an **adaptive system** — exhaustive sentence-level analysis for small corpora, graph-guided semantic beam search for large corpora — rather than claiming graph-based retrieval is always the active path.
