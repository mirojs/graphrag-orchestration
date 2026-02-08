# Architecture Design Document — Corrections & Findings (February 8, 2026)

**Date:** 2026-02-08  
**Source:** `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` (as of Feb 6, 2026)  
**Related:** `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md`

This document lists factual inaccuracies, missing information, and numbering inconsistencies discovered in the architecture design file during the over-retrieval root cause investigation. It is intended as a correction guide — the architecture design file itself has NOT been modified.

---

## 1. Numbering Inconsistency: 3-Route vs 4-Route Scheme

The architecture doc uses **two different numbering schemes** that create confusion:

| Section | Numbering | Route 1 | Route 2 | Route 3 | Route 4 |
|---------|-----------|---------|---------|---------|---------|
| **Overview (L475-560)** | 3-route | Local Search (Entity-Focused) | Global Search (Thematic) | DRIFT Multi-Hop (Complex) | — |
| **Component Breakdown (L563+)** | 4-route | Vector RAG (Fast Lane) | Local Search (LazyGraphRAG Only) | Global Search (LazyGraphRAG + HippoRAG 2) | DRIFT (Multi-Hop Iterative) |
| **Actual Code** | 4-route | `_execute_route_1_vector_rag()` | `_execute_route_2_local_search()` | `_execute_route_3_global_search()` | `_execute_route_4_drift()` |

**The mapping between overview and code:**

| Overview Label | Code Route | Component Section |
|---------------|------------|-------------------|
| Route 1: Local Search | Route 2 in code | Route 2: Local Search Equivalent |
| Route 2: Global Search | Route 3 in code | Route 3: Global Search Equivalent |
| Route 3: DRIFT Multi-Hop | Route 4 in code | Route 4: DRIFT Equivalent |
| *(not in overview)* | Route 1 in code | Route 1: Vector RAG (Fast Lane) |

**Impact:** Any edit to the overview section must map to the correct code route. E.g., updating "Route 1" in the overview affects **code Route 2** (local search), not code Route 1 (vector RAG).

**Recommendation:** Update the overview to use the actual 4-route scheme matching the code so both sections are consistent.

---

## 2. Route 2 Stage 2.2 — Wrong Engine Description

**Location:** L603-611 (Component Breakdown → Route 2)

**Current text (WRONG):**
```
### Route 2: Local Search Equivalent (LazyGraphRAG Only)
...
#### Stage 2.2: LazyGraphRAG Iterative Deepening
*   **Engine:** LazyGraphRAG
*   **What:** Start from extracted entities, iteratively explore neighbors
*   **Why:** Entities are explicit → LazyGraphRAG can navigate from clear starting points
*   **Output:** Rich context from entity neighborhoods
```

**Actual code behavior:**
```
### Route 2: Local Search Equivalent (HippoRAG PPR)
...
#### Stage 2.2: HippoRAG PPR Tracing
*   **Engine:** HippoRAG 2 (Personalized PageRank) via `tracer.trace()`
*   **What:** Run PPR from extracted entities as seeds to find structurally connected evidence nodes
*   **Parameters:** top_k=15 → produces ~13 budgeted entities (after 0.8 relevance budget)
*   **Output:** List[Tuple[str, float]] — ranked (entity_name, ppr_score) pairs
```

**Code reference:** `orchestrator.py` L415-L460 → `tracing.py` → `async_neo4j_service.py` `personalized_pagerank_native()`

Route 2 does NOT use "LazyGraphRAG Iterative Deepening." It uses HippoRAG PPR traversal, the same engine used in Routes 3 (conditional) and 4. The title "LazyGraphRAG Only" in the section header is also incorrect — HippoRAG PPR is the core retrieval engine.

---

## 3. Route 2 Stage 2.1 — Incomplete Engine Description

**Location:** L598-601

**Current text:**
```
#### Stage 2.1: Entity Extraction
*   **Engine:** NER / Embedding Match (deterministic)
```

**Actual code behavior:**
```
#### Stage 2.1: Entity Extraction (NER)
*   **Engine:** NER via LLM (gpt-4o) — extracts entity names from query
```

The entity extraction is done via LLM-based NER (gpt-4o), not "deterministic NER / Embedding Match." The word "deterministic" is misleading — this is an LLM call.

---

## 4. Route 2 — Missing Stage 2.2.5 (Text Chunk Retrieval)

**Location:** Between Stage 2.2 and Stage 2.3

The architecture doc jumps from PPR (Stage 2.2) directly to Synthesis (Stage 2.3), skipping the critical chunk retrieval step.

**Missing stage:**
```
#### Stage 2.2.5: Text Chunk Retrieval
*   **Engine:** synthesis.py → _retrieve_text_chunks()
*   **What:** For each evidence entity, fetch TextChunks via MENTIONS edges from Neo4j
*   **Parameters:** limit_per_entity=12, max_per_section=3, max_per_document=6
    (via text_store.get_chunks_for_entities())
*   **Known Issue:** No cross-entity chunk deduplication — same chunk can appear 
    multiple times when it MENTIONS multiple entities. Uses chunks.extend() 
    without checking chunk_id uniqueness.
*   **Output:** Flat list of text chunks (PPR scores not passed through)
```

---

## 5. Route 2 Stage 2.3 — Missing Context Budget Warning

**Location:** L612-616

**Current text:**
```
#### Stage 2.3: Synthesis with Citations
*   **Engine:** LLM (or deterministic extraction if response_type="nlp_audit")
*   **What:** Generate cited response from collected context
```

**Missing critical information:**
- Engine is specifically: `synthesizer.synthesize()` → `_build_cited_context()` → `_generate_response()`
- **No token budget** on context assembly. Each chunk's full text (~1,150 tokens avg) is appended verbatim.
- With 42 chunks → ~49K tokens for a simple factual lookup (Q-L7).
- No re-ranking by query relevance.
- Code reference: `synthesis.py` L145 (`synthesize()`), L802 (`_build_cited_context()`)

See `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` Gaps 2-3 for full details.

---

## 6. Route 3 Stage 3.4 — PPR Scores Never Used for Retrieval

**Location:** L708-712

**Current text:**
```
#### Stage 3.4: HippoRAG PPR Tracing (DETAIL RECOVERY)
*   **Engine:** HippoRAG 2 (Personalized PageRank)
*   **What:** Mathematical graph traversal from hub entities
*   **Why:** Finds ALL structurally connected nodes (even "boring" ones LLM might skip)
*   **Output:** Ranked evidence nodes with PPR scores
```

**Missing critical information:**

1. **PPR is CONDITIONAL, not always-on.** In `fast_mode` (default ON), PPR is SKIPPED unless query has relationship indicators ("between", "impact on", "connected to") or 2+ proper nouns. For simple thematic queries, PPR never runs.

2. **PPR scores are NEVER used for chunk retrieval in Route 3.** Chunks are already collected in `graph_context.source_chunks` from Stages 3.3 + 3.3.5 BEFORE PPR runs. The `evidence_nodes` output is passed to `synthesize_with_graph_context()` but only stored as `evidence_path` metadata — it has **zero influence** on which chunks the LLM sees.

3. This is fundamentally different from Routes 2/4, where PPR output at least determines the entity list for chunk fetching (even though scores are discarded there too).

**Corrected title should be:** `Stage 3.4: HippoRAG PPR Tracing (CONDITIONAL — DETAIL RECOVERY)`

**Code reference:** `orchestrator.py` L1007-L1057

See `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` Section 3.3.2 for full analysis.

---

## 7. Route 3 Stage 3.5 — Wrong Synthesis Path Documented

**Location:** L741-749

**Current text:**
```
#### Stage 3.5: Raw Text Chunk Fetching
*   **Engine:** Storage backend (Neo4j / Parquet)
*   **What:** Fetch raw text chunks for all evidence nodes
...

#### Stage 3.5: Synthesis with Citations
*   **Engine:** LLM (or deterministic extraction if response_type="nlp_audit")
*   **What:** Generate comprehensive response from raw chunks
```

**Issues:**
1. Two stages are both numbered "3.5" — the raw text chunk fetching stage is a duplicate/leftover.
2. Route 3 does NOT use the same synthesis path as Routes 2/4. It uses `synthesize_with_graph_context()` (synthesis.py L297), NOT `synthesize()` (L145).
3. Route 3 does NOT call `_retrieve_text_chunks()` at all — chunks are already in `graph_context.source_chunks` from Stages 3.3 + 3.3.5.

**Corrected description:**
```
#### Stage 3.5: Synthesis with Citations (DIFFERENT CODE PATH from Routes 2/4)
*   **Engine:** LLM via synthesizer.synthesize_with_graph_context() — NOT synthesize()
*   **What:** Build context from graph_context.source_chunks (already collected in 
    Stages 3.3 + 3.3.5), group by document, add relationship context + entity 
    descriptions, then send to LLM.
*   **Architecture Note:** Route 3 uses a completely separate synthesis code path:
    - Routes 2/4: synthesize() → _retrieve_text_chunks() → _build_cited_context()
    - Route 3: synthesize_with_graph_context() → builds context from 
      graph_context.source_chunks → _generate_graph_response()
*   **Known Issue:** No token budget on context assembly. Full chunk text appended 
    verbatim. With ~40-60 chunks, context can reach 57K-80K+ tokens.
*   **Code:** synthesis.py L297 (synthesize_with_graph_context())
```

---

## 8. Route 4 Stage 4.5 — Missing Context Budget Warning & PPR Score Waste

**Location:** L1107-1113

**Current text:**
```
#### Stage 4.5: Multi-Source Synthesis
*   **Engine:** LLM with DRIFT-style aggregation (or deterministic extraction...)
*   **What:** Synthesize findings from all sub-questions into coherent report
*   **Output:** Executive summary + detailed evidence trail
```

**Missing critical information:**
- Engine is specifically: `synthesizer.synthesize()` → `_retrieve_text_chunks()` → `_build_cited_context()` (same code path as Route 2)
- Route 4 runs up to **3 PPR passes** (Stages 4.2, 4.3, 4.3.5) producing ranked `(entity, score)` tuples, but `_retrieve_text_chunks()` **discards all scores** — every entity gets uniform `limit_per_entity=12`.
- Combined with sub-question iteration and coverage gap-fill, Route 4 can send **100K+ tokens** to the LLM.
- Code reference: same as Route 2 — `synthesis.py` L145 (`synthesize()`)

See `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` Sections 3.4 and Gap 6.

---

## 9. Section 2.3 "Where HippoRAG 2 Is Used" — Incomplete

**Location:** L552-558

**Current text:**

| Route | HippoRAG 2 Used? | Entity Aliases? | Why |
|:------|:-----------------|:----------------|:----|
| Route 1 (Local Search) | ✅ Yes | ✅ Yes | PPR from extracted entities |
| Route 2 (Global Search) | ✅ Optional | ✅ Yes | PPR from hub entities (full mode) or skip (fast mode) |
| Route 3 (DRIFT) | ✅ Yes | ✅ Yes | PPR after query decomposition |

**Missing column: PPR Score Used for Retrieval?**

| Route | HippoRAG 2 Used? | Entity Aliases? | PPR Score Used for Retrieval? | Why |
|:------|:-----------------|:----------------|:------------------------------|:----|
| Route 1 (Vector RAG) | ❌ No | ✅ Yes | N/A | Pure BM25+Vector hybrid |
| Route 2 (Local Search) | ✅ Yes (always) | ✅ Yes | ⚠️ Discarded | PPR from NER entities (top_k=15) |
| Route 3 (Thematic) | ✅ Conditional | ✅ Yes | ❌ Never used | Scores stored as metadata only |
| Route 4 (DRIFT) | ✅ Yes (up to 3 passes) | ✅ Yes | ⚠️ Discarded | PPR after query decomposition |

> **February 8, 2026 Finding:** PPR scores are computed but never used to weight chunk allocation in ANY route. See `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` Gap 6 for the planned fix.

---

## 10. Section 2.2 "Division of Labor" — Outdated

**Location:** L547-551

**Current text:**

| Component | Role | Analogy |
|:----------|:-----|:--------|
| **LazyGraphRAG** | Librarian + Editor | Finds the right shelf, writes the report |
| **HippoRAG 2** | Researcher | Finds every relevant page on that shelf |
| **Synthesis LLM** | Writer | Generates human-readable output |

**Issue:** The table is missing BM25+Vector RRF (a core retrieval component in Routes 1 and 3) and query decomposition (Route 4 only). Also, "LazyGraphRAG" as a named component is misleading — the code uses HippoRAG PPR directly, not a separate "LazyGraphRAG" module.

**Updated version:**

| Component | Role | Used In | Analogy |
|:----------|:-----|:--------|:--------|
| **HippoRAG 2 PPR** | Entity-focused graph traversal | Routes 2, 3 (conditional), 4 | Researcher — finds every relevant page |
| **BM25+Vector RRF** | Lexical + semantic chunk retrieval | Routes 1, 3 | Keyword + meaning search |
| **Synthesis LLM** | Generates human-readable output | All routes | Writer |
| **Query Decomposition** | Break complex queries into sub-questions | Route 4 only | Editor — splits ambiguous questions |

---

## 11. Overview Section Routes — Incorrect Engine Descriptions

**Location:** L505-510

**Current text for Route 1 (Overview — maps to code Route 2):**
```
*   **Engines:** Entity Extraction → LazyGraphRAG Iterative Deepening → LLM Synthesis
```

**Corrected:**
```
*   **Engines:** NER (gpt-4o) → HippoRAG PPR (top_k=15) → _retrieve_text_chunks() 
    → _build_cited_context() → LLM Synthesis
```

**Current text for Route 2 (Overview — maps to code Route 3):**
```
*   **Engines (Full Mode):** Entity Embedding Search → Hub Entities → Graph Evidence 
    → BM25+Vector RRF → Section Boost → Keyword Boost → HippoRAG 2 PPR → Synthesis
```

**Corrected:**
```
*   **Engines (Full Mode):** Community Matching → Hub Entities → Enhanced Graph Context 
    → BM25+Vector RRF → [PPR if complex] → Coverage Fill 
    → synthesize_with_graph_context()
```

---

## 12. Stage 3.5.1 Context Distillation — Scope Too Narrow

**Location:** If present (planned section, references nonexistent Section 23)

Stage 3.5.1 was added as a Route 3-only context deduplication step. However, the unbounded context problem affects **all routes**:

| Route | Context Issue | Tokens (typical) |
|-------|--------------|-------------------|
| Route 2 | PPR scores discarded, no token budget | ~49K |
| Route 3 | Different synthesis path, no token budget | ~57K-80K |
| Route 4 | Up to 3 PPR passes + coverage gap-fill, no token budget | ~100K+ |

The optimization plan in `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` covers all three routes with:
- Phase 1: Chunk dedup + token budget (all routes)
- Phase 2: PPR score-weighted allocation (Routes 2/4) + RRF score ranking (Route 3)
- Phase 3: Semantic re-ranking + adaptive budgets (all routes)

Any future Section 23 should cover the cross-route context budget architecture, not just Route 3 dedup.

---

## 13. Section 18.3 "Future Optimization Opportunities" — Overlap with Current Plan

**Location:** ~L5440-5490

Section 18.3 lists "Smarter context pruning" and "Adaptive context window" as future ideas. These directly overlap with the optimization plan in `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md` which provides concrete implementation details. The future optimization section should cross-reference the analysis doc and note that Phase 1-2 require zero additional API calls.

---

## Summary of Required Updates

| # | Section | Issue | Severity |
|---|---------|-------|----------|
| 1 | Overview vs Components | 3-route vs 4-route numbering inconsistency | High (confusing) |
| 2 | Route 2 Stage 2.2 | Wrong engine: "LazyGraphRAG" → HippoRAG PPR | **Critical** (factually wrong) |
| 3 | Route 2 Stage 2.1 | "Deterministic NER" → LLM-based NER (gpt-4o) | Medium |
| 4 | Route 2 (between 2.2-2.3) | Missing Stage 2.2.5 (text chunk retrieval) | High |
| 5 | Route 2 Stage 2.3 | Missing unbounded context warning | High |
| 6 | Route 3 Stage 3.4 | PPR is conditional + scores never used for retrieval | **Critical** |
| 7 | Route 3 Stage 3.5 | Wrong synthesis path documented + duplicate numbering | **Critical** |
| 8 | Route 4 Stage 4.5 | Missing context budget warning + PPR score waste | High |
| 9 | Section 2.3 | Missing "PPR Score Used?" column | Medium |
| 10 | Section 2.2 | Missing components (BM25/RRF, Query Decomposition) | Medium |
| 11 | Overview routes | Wrong engine descriptions | High |
| 12 | Stage 3.5.1 | Scope should be cross-route, not Route 3 only | Medium |
| 13 | Section 18.3 | Overlaps with concrete optimization plan | Low |
