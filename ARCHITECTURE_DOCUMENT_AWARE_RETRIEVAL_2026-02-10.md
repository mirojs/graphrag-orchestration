# Architecture: Document-Aware Retrieval — Three-Layer Structural Design

**Date:** 2026-02-10  
**Status:** Design RFC  
**Problem:** Cross-document contamination causes 67% of retrieval context to be noise  
**Proposal:** Wire the existing (but dormant) structural graph layer into retrieval  

---

## 1. The Three-Layer Retrieval Model

The user proposed treating `document_id`, `section_id`, and DI layout positions as
first-class structural dimensions alongside semantic/entity dimensions:

| Layer | What it captures | Existing infrastructure | Used for retrieval? |
|---|---|---|---|
| **Embedding space** | Vector similarity | `embedding_v2` on Entity/Section, `SEMANTICALLY_SIMILAR` edges | ✅ Yes (PPR Path 3) |
| **Graph space** | Entity relationships | `RELATED_TO`, `MENTIONS`, PPR traversal | ✅ Yes (PPR Paths 1-2) |
| **Structural space** | Document, section, position | `Document`, `Section` nodes; `IN_DOCUMENT`, `IN_SECTION`, `APPEARS_IN_SECTION`, `APPEARS_IN_DOCUMENT` edges | ❌ **No — dormant** |

**Key insight:** The structural layer is already fully materialized in the graph.
It is not "virtual" — it exists as real nodes and edges. It is simply **never consulted
during retrieval filtering**. It is only used downstream for output formatting
(document grouping in `_build_cited_context`).

---

## 2. What Already Exists in the Graph

### 2.1 Structural Nodes

```
Document (5 nodes)
  properties: id, title, source, date, metadata, primary_language,
              detected_languages, language_spans, group_id

Section (9 sections across 5 docs)
  properties: id, path_key, title, depth, doc_id, embedding, group_id
```

### 2.2 Structural Edges (all materialized, all unused for retrieval)

```
Document -[HAS_SECTION]→ Section          (9 edges)
TextChunk -[IN_DOCUMENT]→ Document        (18 edges — every chunk)
TextChunk -[IN_SECTION]→ Section          (18 edges — every chunk)
Entity -[APPEARS_IN_DOCUMENT]→ Document   (4,522 edges — every entity to every doc it appears in)
Entity -[APPEARS_IN_SECTION]→ Section     (221 edges — entities to their sections)
Section -[SUBSECTION_OF]→ Section         (section hierarchy)
Section -[SHARES_ENTITY]→ Section         (cross-doc bridges — used by PPR but document-blindly)
```

### 2.3 Structural Properties on Existing Nodes

```
TextChunk.document_id   → links chunk to its source document
TextChunk.chunk_index   → position within document
Section.doc_id          → which document owns this section
Section.depth           → hierarchy depth (for section-level scoping)
```

### 2.4 Entity Scope Analysis

| Scope | Count | % | Description |
|---|---|---|---|
| Single-document | 127 | 96.2% | Entity appears in only 1 document |
| Multi-document | 5 | 3.8% | Super-connector entities |

The 5 super-connectors that cause 67% contamination:

| Entity | Docs | Role |
|---|---|---|
| Fabrikam Inc. | 4 | Contractual party in all contracts |
| Contoso Ltd. | 4 | Contractual party in all contracts |
| Contoso Lifts LLC | 2 | Invoice/purchase subject |
| P.O. Box 123567 Key West | 2 | Shared address |
| 61 S 34th Street, Dayton | 2 | Shared address |

---

## 3. Where Contamination Enters — The Document-Blind Pipeline

### Current data flow (zero structural awareness):

```
Query → Entity Extraction → PPR Expansion → Chunk Retrieval → Denoising → LLM

                              ❌ PPR crosses     ❌ Cypher has    ❌ Denoising
                              documents freely    no WHERE on     never checks
                              via RELATED_TO,     document_id     document_id
                              SHARES_ENTITY
```

### Specific code gaps:

| Stage | File | Line | Gap |
|---|---|---|---|
| **PPR query** | `async_neo4j_service.py` | L771-873 | 5 path types, ALL traverse freely across documents. Path 4 (SHARES_ENTITY) is explicitly cross-doc by design. |
| **Chunk retrieval Cypher** | `text_store.py` | L265-278 | `MATCH (c:TextChunk)-[:MENTIONS]->(e)` — no `WHERE c.document_id IN $target_docs`. `OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d)` is for metadata only. |
| **Document cap** | `text_store.py` | L368-375 | `max_per_document=6` per entity. But 3 irrelevant entities × 6 chunks each = 18 noise chunks vs 6 relevant. Cap is per-entity, not aggregate. |
| **Denoising** | `synthesis.py` | L960-1195 | 6 passes (community, score-gap, score-weighted, hash-dedup, semantic-dedup, noise-filter). **None check document_id.** |
| **PPR call** | `tracing.py` | L296-309 | No `document_ids` parameter. `folder_id` exists on class but is never passed through. |
| **Context builder** | `synthesis.py` | L1455-1463 | Groups by `document_id` — **but only for display formatting**, not for filtering. |

---

## 4. Architecture: Document-Scoped Retrieval

### 4.1 Core Algorithm: Target Document Resolution

Before any retrieval, determine which document(s) the query is about.

```
Input:  seed_entities = ["Fabrikam Inc.", "123 Mockup Lane, Washburn",
                         "Waste Hauling Services"]

Step 1: For each seed entity, get APPEARS_IN_DOCUMENT → doc_ids
  "Fabrikam Inc."          → [doc_A, doc_B, doc_C, doc_D]    (super-connector)
  "123 Mockup Lane"        → [doc_C]                         (single-doc)
  "Waste Hauling Services" → [doc_C]                         (single-doc)

Step 2: Score documents by seed entity overlap
  doc_A: 1 entity  (Fabrikam only — super-connector)
  doc_B: 1 entity  (Fabrikam only — super-connector)
  doc_C: 3 entities  ← ALL seeds appear here
  doc_D: 1 entity  (Fabrikam only — super-connector)

Step 3: Select target documents
  - doc_C is the clear winner (3/3 seed coverage)
  - Super-connector penalty: Fabrikam's vote counts 1/4 (it spans 4 docs)
  - Weighted scores: doc_C = 2 + 0.25 = 2.25, others ≤ 0.25

Target: doc_C (HOLDING TANK SERVICING CONTRACT)
```

**Entity Vote Weighting Formula:**

$$w(e, d) = \frac{1}{|\text{docs}(e)|}$$

Where $\text{docs}(e)$ is the set of documents entity $e$ appears in.
A single-doc entity's vote = 1.0. A 4-doc super-connector's vote = 0.25.

**Document score:**

$$\text{score}(d) = \sum_{e \in \text{seeds}} w(e, d) \cdot \mathbb{1}[e \in d]$$

**Target selection:** Documents with $\text{score}(d) \geq \theta$ where $\theta$ is
configurable (default: at least 2 non-super-connector seeds, or top-1 by score).

### 4.2 Where to Inject: Three Injection Points

```
Query → Entity Extraction → [A] Target Doc Resolution
                                       ↓
                           → PPR Expansion ← [B] Document-Scoped PPR
                                       ↓
                           → Chunk Retrieval ← [C] Document-Filtered Cypher
                                       ↓
                           → Denoising ← [D] Document-Coherence Pass
                                       ↓
                           → LLM
```

#### [A] Target Document Resolution (NEW — in `synthesis.py`)

**Location:** `_retrieve_text_chunks()` between entity extraction (L950) and PPR call (L960).

**Implementation:** Single Cypher query via `async_neo4j_service.py`:

```cypher
UNWIND $entity_names AS ename
MATCH (e)-[:APPEARS_IN_DOCUMENT]->(d:Document {group_id: $group_id})
WHERE (e:Entity OR e:`__Entity__`) AND e.group_id = $group_id
  AND (toLower(e.name) = toLower(ename)
       OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(ename)))
WITH d.id AS doc_id, d.title AS doc_title,
     collect(DISTINCT ename) AS matching_seeds,
     count(DISTINCT ename) AS seed_coverage
RETURN doc_id, doc_title, matching_seeds, seed_coverage
ORDER BY seed_coverage DESC
```

Then weight by the IDF-like formula above.

**Complexity:** O(1) Cypher query. No additional API calls. ~5ms on this graph.

#### [B] Document-Scoped PPR (SOFT boost — in `async_neo4j_service.py`)

Two approaches, from least to most invasive:

**B1 — Post-PPR re-scoring (recommended):**
After PPR returns ranked entities, multiply each entity's score by a document affinity factor:

$$\text{score}'(e) = \text{score}(e) \times \begin{cases} 1.0 & \text{if } e \in \text{target\_docs} \\ \alpha & \text{if } e \notin \text{target\_docs} \end{cases}$$

where $\alpha = 0.3$ (configurable, env var `DOC_SCOPE_PENALTY`).

**Location:** New function in `synthesis.py`, called between PPR return and entity selection.

**B2 — PPR path weight modulation:**
When target documents are known, set `weight_shares=0.1` to dampen cross-doc traversal.
This uses the existing `PPR_WEIGHT_SHARES` mechanism. Zero code change needed — just
pass a reduced weight when document scope is narrow.

#### [C] Document-Filtered Chunk Retrieval (HARD filter — in `text_store.py`)

The highest-impact single change. Modify `_get_chunks_for_entities_batch_sync`:

**Current Cypher (L265-278):**
```cypher
MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
```

**Proposed Cypher (when target_docs is provided):**
```cypher
MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
WHERE d.id IN $target_document_ids
```

When `target_document_ids` is `None` (cross-doc question or low-confidence scoping),
fall back to the current document-blind query.

#### [D] Document-Coherence Denoising (SAFETY NET — in `synthesis.py`)

New 7th denoising pass in `_retrieve_text_chunks`, after semantic dedup:

```python
# Pass 7: Document coherence scoring
if target_document_ids and denoise_document_coherence:
    for chunk in deduped_chunks:
        doc_id = chunk.get("metadata", {}).get("document_id", "")
        if doc_id not in target_document_ids:
            chunk["_ppr_score"] *= DOC_COHERENCE_PENALTY  # 0.3
    # Re-sort by score, truncate
```

This is the safety net — even if PPR and chunk retrieval let some cross-doc noise through,
document coherence scoring will push it to the bottom of the ranked list.

### 4.3 Cross-Document Question Handling

**Critical edge case:** "Compare the warranty terms in the Builders warranty and the
Property Management Agreement."

Detection heuristic (in intent.py entity extraction):
- If seed entities span multiple documents AND no single document covers most seeds
  → multi-document query → skip document scoping (or scope to the relevant subset)
- If the user's query contains comparative language ("compare", "between", "vs")
  → multi-document query

**Algorithm:**
```
if max_doc_score / total_seeds < 0.5:
    # No dominant document — cross-doc question
    target_document_ids = None  # Disable scoping
elif max_doc_score == second_doc_score:
    # Two equally-relevant documents — include both
    target_document_ids = [top_doc, second_doc]
else:
    # Single dominant document
    target_document_ids = [top_doc]
```

---

## 5. Expected Impact

### 5.1 Noise Reduction Projection

Taking Q-L6 (worst case: 6.9% relevant, 93.1% noise):
- **Current:** Seed "Fabrikam Inc." pulls chunks from 4 docs. Only 1/4 is relevant.
- **With doc scoping:** Target document correctly identified. Chunk retrieval scoped.
- **Projected:** ~85-95% relevant context (up from 6.9%)

| Question | Current relevant % | Projected relevant % | Improvement |
|---|---|---|---|
| Q-L6 | 6.9% | ~90% | **13× more signal** |
| Q-L7 | 6.9% | ~90% | **13× more signal** |
| Q-L4 | 25.2% | ~85% | **3.4× more signal** |
| Q-L2 | 25.5% | ~85% | **3.3× more signal** |
| Q-L1 | 30.6% | ~90% | **2.9× more signal** |

### 5.2 Token Savings

Current average context size: 7,800 tokens (94-97% of prompt).
With document scoping: expect ~2,500-3,500 tokens (60-70% reduction) while
carrying MORE relevant information.

### 5.3 Expected F1 Impact

v1_concise + gpt-5-mini already achieves F1=0.591 with 67% noise context.
With 90% relevant context, we project F1 ≥ 0.70-0.80 based on the established
relationship between context quality and answer precision.

---

## 6. Implementation Plan

### Phase 1: Target Document Resolution — `async_neo4j_service.py` + `synthesis.py`

**Goal:** Given seed entity names, return ranked document IDs with confidence scores.

**Step 1a — New Cypher method in `async_neo4j_service.py`:**
```python
async def get_entity_document_coverage(
    self, group_id: str, entity_names: List[str]
) -> List[Dict[str, Any]]:
```
Cypher query:
```cypher
UNWIND $entity_names AS ename
MATCH (e)-[:APPEARS_IN_DOCUMENT]->(d:Document {group_id: $group_id})
WHERE (e:Entity OR e:`__Entity__`) AND e.group_id = $group_id
  AND (toLower(e.name) = toLower(ename)
       OR ANY(alias IN coalesce(e.aliases, [])
              WHERE toLower(alias) = toLower(ename)))
WITH d.id AS doc_id, d.title AS doc_title,
     collect(DISTINCT ename) AS matching_seeds,
     count(DISTINCT ename) AS seed_coverage
RETURN doc_id, doc_title, matching_seeds, seed_coverage
ORDER BY seed_coverage DESC
```
Returns: `[{doc_id, doc_title, matching_seeds, seed_coverage}]`

**Step 1b — IDF-weighted scoring in `synthesis.py`:**
```python
def _resolve_target_documents(
    self,
    seed_entities: List[str],
    entity_doc_coverage: List[Dict],
    entity_doc_counts: Dict[str, int],  # how many docs each entity appears in
) -> Optional[List[str]]:
```
Algorithm:
1. For each doc, sum `1/|docs(e)|` for each seed entity present
2. If top score < threshold → return `None` (cross-doc, skip scoping)
3. If top score ≫ second score → return `[top_doc_id]`
4. If top ≈ second → return `[top_doc_id, second_doc_id]`

**Env vars:** `DOC_SCOPE_ENABLED` (default=1), `DOC_SCOPE_MIN_SCORE` (default=1.5)

**Files touched:** `async_neo4j_service.py` (~30 lines), `synthesis.py` (~50 lines)

---

### Phase 2: Document-Filtered Chunk Retrieval — `text_store.py`

**Goal:** When target docs are resolved, only retrieve chunks from those docs.

**Step 2a — Add parameter to `_get_chunks_for_entities_batch_sync`:**
```python
def _get_chunks_for_entities_batch_sync(
    self,
    entity_names: List[str],
    max_per_section: int = 3,
    max_per_document: int = 6,
    target_document_ids: Optional[List[str]] = None,  # NEW
) -> Dict[str, List[Dict[str, Any]]]:
```

**Step 2b — Conditional Cypher modification (L265-278):**
When `target_document_ids` is provided:
```cypher
MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
WHERE d.id IN $target_document_ids          // ← NEW LINE
```
When `None`, keep current `OPTIONAL MATCH` behavior (backward-compatible).

**Step 2c — Thread through `synthesis.py` `_retrieve_text_chunks`:**
Pass `target_document_ids` from Phase 1 result into `text_store.get_chunks_for_entities()`.

**Files touched:** `text_store.py` (~15 lines changed), `synthesis.py` (~5 lines)

---

### Phase 3: Section Scoping — `async_neo4j_service.py` + `text_store.py`

**Goal:** Within the target document, narrow to the most relevant section(s).

**Step 3a — New Cypher method for section coverage:**
```python
async def get_entity_section_coverage(
    self, group_id: str, entity_names: List[str],
    target_document_ids: List[str]
) -> List[Dict[str, Any]]:
```
```cypher
UNWIND $entity_names AS ename
MATCH (e)-[:APPEARS_IN_SECTION]->(s:Section {group_id: $group_id})
WHERE (e:Entity OR e:`__Entity__`) AND e.group_id = $group_id
  AND s.doc_id IN $target_document_ids
  AND (toLower(e.name) = toLower(ename)
       OR ANY(alias IN coalesce(e.aliases, [])
              WHERE toLower(alias) = toLower(ename)))
WITH s.id AS section_id, s.path_key AS section_key, s.doc_id AS doc_id,
     collect(DISTINCT ename) AS matching_seeds,
     count(DISTINCT ename) AS seed_coverage
RETURN section_id, section_key, doc_id, matching_seeds, seed_coverage
ORDER BY seed_coverage DESC
```

**Step 3b — Optional: query↔section embedding similarity:**
Embed the query, fetch section embeddings from Neo4j, compute cosine similarity.
Combine: `combined_score = α * entity_vote_score + (1-α) * cosine_sim` (α=0.6).

**Step 3c — Thread `target_section_ids` into chunk retrieval Cypher:**
```cypher
MATCH (c)-[:IN_SECTION]->(s:Section)
WHERE s.id IN $target_section_ids
```

**Env vars:** `SECTION_SCOPE_ENABLED` (default=0 initially, opt-in),
`SECTION_SCOPE_EMBED_WEIGHT` (default=0.4)

**Files touched:** `async_neo4j_service.py` (~30 lines), `text_store.py` (~10 lines),
`synthesis.py` (~40 lines)

---

### Phase 4: Post-PPR Document Affinity Re-scoring — `synthesis.py`

**Goal:** Even if PPR expands to cross-doc entities, penalize their score.

**Step 4a — After PPR returns ranked entities, before entity selection:**
```python
def _apply_document_affinity(
    self,
    ranked_entities: List[Dict],
    target_document_ids: List[str],
    penalty: float = 0.3,
) -> List[Dict]:
    """Multiply off-document entities' scores by penalty factor."""
    for entity in ranked_entities:
        entity_docs = entity.get("document_ids", [])
        if not any(d in target_document_ids for d in entity_docs):
            entity["score"] *= penalty
    return sorted(ranked_entities, key=lambda e: e["score"], reverse=True)
```

**Requires:** Entity → document mapping. Fetch in the same Cypher as Phase 1
or add to PPR result metadata.

**Env var:** `DOC_SCOPE_PPR_PENALTY` (default=0.3)

**Files touched:** `synthesis.py` (~25 lines)

---

### Phase 5: Document-Coherence Denoising Pass — `synthesis.py`

**Goal:** Safety net — even after all upstream scoping, catch any remaining cross-doc noise.

**Step 5a — New 7th denoising pass in `_retrieve_text_chunks` (~L1195):**
```python
# Pass 7: Document coherence — penalize off-target-document chunks
if target_document_ids and denoise_doc_coherence:
    for chunk in deduped_chunks:
        doc_id = chunk.get("metadata", {}).get("document_id", "")
        if doc_id and doc_id not in target_document_ids:
            chunk["_ppr_score"] *= DOC_COHERENCE_PENALTY
    deduped_chunks.sort(key=lambda c: c.get("_ppr_score", 0), reverse=True)
```

**Env var:** `DENOISE_DOC_COHERENCE` (default=1), `DOC_COHERENCE_PENALTY` (default=0.2)

**Files touched:** `synthesis.py` (~15 lines)

---

### Phase 6: Benchmark & Validation

**Step 6a — Context quality benchmark:**
- Re-run 2-phase benchmark with doc-scoped retrieval enabled
- Measure: relevant doc % per question (target: 90%+ up from 33%)
- Measure: total context tokens (target: <3,000 down from 7,800)

**Step 6b — F1 benchmark:**
- Replay captured contexts through v1_concise + gpt-5-mini
- Compare against baseline F1=0.591 (target: 0.70+)

**Step 6c — Cross-document negative control:**
- Add 2-3 benchmark questions that are genuinely cross-document
- Verify doc scoping gracefully falls back to `None`

**Step 6d — Ablation:**
- Phase 2 alone (chunk filter only)
- Phase 2 + Phase 3 (chunk filter + section scoping)
- Phase 2 + Phase 4 (chunk filter + PPR re-scoring)
- Full stack (all phases)

**Files touched:** benchmark script (~50 lines)

---

## 6.1 Implementation Complexity Assessment

| Phase | New code | Files touched | Risk | Dependency |
|---|---|---|---|---|
| **1: Target doc resolution** | ~80 lines | 2 (neo4j_svc, synthesis) | Low — pure add, no existing change | None |
| **2: Doc-filtered chunks** | ~20 lines | 2 (text_store, synthesis) | Low — conditional Cypher swap | Phase 1 |
| **3: Section scoping** | ~80 lines | 3 (neo4j_svc, text_store, synthesis) | Medium — embed call + scoring | Phase 1+2 |
| **4: PPR re-scoring** | ~25 lines | 1 (synthesis) | Low — post-processing only | Phase 1 |
| **5: Doc-coherence denoise** | ~15 lines | 1 (synthesis) | Low — extra denoising pass | Phase 1 |
| **6: Benchmark** | ~50 lines | 1 (benchmark script) | Low | Phase 1+2 |
| **Total** | **~270 lines** | **4 files** | | |

### Verdict: Straightforward — Phase 1+2 can ship same day

**Phases 1+2 alone give 80% of the benefit** (document scoping + filtered chunk retrieval).
These require:
- 1 new Cypher query (~15 lines)
- 1 new Python function (~50 lines)
- 1 conditional Cypher clause (~5 lines)
- Threading 1 parameter through 2 function calls

No model changes, no schema changes, no new dependencies. All env-var gated
with backward-compatible fallback. The graph edges already exist.

**Phase 3 (section scoping)** is the only phase with medium complexity —
the embedding similarity call requires async coordination. But it's optional
and can ship independently.

**Phases 4+5** are simple post-processing additions (soft scoring adjustments).

### Recommended Implementation Order

```
Day 1:  Phase 1 + Phase 2 + Phase 5 + Phase 6a
        → Document scoping + chunk filter + safety denoising + benchmark
        → Expected: 33% relevant → 85%+ relevant

Day 2:  Phase 4 + Phase 6b
        → PPR re-scoring + F1 benchmark
        → Expected: F1 0.591 → 0.70+

Later:  Phase 3 + Phase 6d
        → Section scoping (opt-in) + ablation study
        → Expected: 85% relevant → 95%+ relevant
```

---

## 7. Conceptual Model: The Three Retrieval Layers

```
┌─────────────────────────────────────────────────────────────┐
│                    Query Understanding                       │
│  "What are the waste hauling service terms?"                │
│          ↓ entity extraction                                │
│  seeds: [Fabrikam Inc., 123 Mockup Lane, Waste Hauling]     │
└─────────────────────┬───────────────────────────────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
┌─────────────┐ ┌─────────────┐ ┌──────────────────┐
│  LAYER 1    │ │  LAYER 2    │ │  LAYER 3         │
│  Embedding  │ │  Graph      │ │  Structural      │
│             │ │             │ │                  │
│  "What is   │ │ Entity →    │ │ Seed entities →  │
│   similar    │ │ RELATED_TO  │ │ APPEARS_IN_DOC   │
│   to these   │ │ → Entity    │ │ → Document vote  │
│   entities?" │ │             │ │ → Target doc(s)  │
│             │ │ PPR expands │ │                  │
│  Similarity │ │ relationship│ │ Answers: WHERE   │
│  search for │ │ paths       │ │ is the question  │
│  fallback   │ │             │ │ about?           │
│  entities   │ │ Answers:    │ │                  │
│             │ │ WHAT is     │ │ Constrains L1+L2 │
│  Answers:   │ │ connected?  │ │ to target scope  │
│  WHO ELSE   │ │             │ │                  │
│  is relevant?│ │             │ │                  │
└──────┬──────┘ └──────┬──────┘ └────────┬─────────┘
       │               │                 │
       └───────────────┼─────────────────┘
                       ▼
              ┌─────────────────┐
              │  Chunk Retrieval │ ← scoped to target doc(s)
              │  + Denoising     │ ← document coherence pass
              ├─────────────────┤
              │  ~90% relevant   │  (was 33%)
              │  ~2,500 tokens   │  (was 7,800)
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  Synthesis LLM   │
              │  v1_concise +    │
              │  gpt-5-mini      │
              └─────────────────┘
```

### Layer Roles Summary

| Layer | Question it answers | Used for | Existing? |
|---|---|---|---|
| **Embedding** | "Who else is semantically similar to these entities?" | Fallback entity discovery (PPR Path 3) | ✅ Active |
| **Graph** | "What is connected to these entities?" | Relationship traversal (PPR Paths 1-2, 4-5) | ✅ Active |
| **Structural** | "WHERE in the corpus is the question about?" | Document/section scoping | ⚠️ **Exists but dormant** |

---

## 8. Design Principles

1. **Soft over hard:** Document scoping should boost/penalize, not hard-block, unless
   confidence is very high. This preserves cross-document question support.

2. **Existing edges only:** No new graph construction needed. `APPEARS_IN_DOCUMENT`,
   `IN_DOCUMENT`, `IN_SECTION`, `APPEARS_IN_SECTION` all already exist.

3. **IDF-weighted voting:** Super-connector entities (appearing in many docs) get
   proportionally less voting power. Single-doc entities are strong signals.

4. **Env-var controlled:** All thresholds are env vars, deployable without code change.
   `DOC_SCOPE_ENABLED`, `DOC_SCOPE_PENALTY`, `DOC_SCOPE_MIN_SEEDS`.

5. **Backward compatible:** When document scoping is disabled or inconclusive,
   the pipeline falls back to exactly the current behavior.

---

---

## 9. Section-Level Scoping — The Precision Layer

### 9.1 The Opportunity

Document scoping answers "WHICH document?" — that alone cuts 67% noise to ~10%.
But within a long document that has multiple sections, there's a second question:
**"WHICH section?"**

Sections carry semantic meaning (titles like "EXHIBIT A — SCOPE OF WORK" or
"2. Term."), have 2048-dim embeddings, and already link to both entities and chunks.
This is the dormant precision layer.

### 9.2 What Section Infrastructure Exists

**Section nodes** — 12 across 5 documents, with hierarchy:

| Document | Sections (depth=0) | Sub-sections (depth=1) | Chunks |
|---|---|---|---|
| Builders Limited Warranty | 3 (main, "1. Builder's Warranty", "2. Term") | 2 sub-sections | 5 |
| Purchase Contract | 2 (contract, Exhibit A) | 0 | 4 |
| Property Management | 2 (agreement header, terms) | 1 sub-section | 2 |
| Holding Tank Contract | 1 | 0 | 1 |
| Contoso Invoice | 1 | 0 | 2 |

**Section properties:**
- `title` — semantic heading ("1. Builder's Limited Warranty.", "EXHIBIT A - SCOPE OF WORK")
- `path_key` — hierarchical path (e.g., "BUILDERS LIMITED WARRANTY WITH ARBITRATION > 2. Term.")
- `depth` — 0 (top-level) or 1 (sub-section)
- `doc_id` — which document owns the section
- `embedding` — 2048-dim vector (query-matchable)

**Section edges:**
- `Entity -[APPEARS_IN_SECTION]→ Section` (221 edges)
- `TextChunk -[IN_SECTION]→ Section` (18 edges — every chunk in exactly 1 section)
- `Section -[SUBSECTION_OF]→ Section` (3 edges)
- `Document -[HAS_SECTION]→ Section` (9 edges)

### 9.3 Entity Section Locality

| Scope | Doc scope | Count | % | Avg sections |
|---|---|---|---|---|
| **1 section only** | single-doc | 73 | 55.3% | 1.0 |
| 2–3 sections | single-doc | 53 | 40.2% | 2.3 |
| 4+ sections | single-doc | 1 | 0.8% | 5.0 |
| 2–3 sections | multi-doc | 3 | 2.3% | 2.0 |
| **4+ sections** | **multi-doc** | **2** | **1.5%** | **8.5** |

**55% of entities are single-section.** These are the strongest section-scoping signals.
Compare with document level: 96% single-doc. The pattern is the same — most entities
are local; a few super-connectors span everything.

### 9.4 How Section Scoping Works

Two complementary mechanisms:

#### A. Section-Entity Voting (structural — like document voting)

Same IDF-weighted formula, but at section granularity:

$$w_s(e, s) = \frac{1}{|\text{sections}(e)|}$$

Seed entities vote for sections. A single-section entity votes 1.0;
a 5-section entity votes 0.2. Target section = highest-scoring section within
the target document.

**Concrete trace for Q-L6:**

```
Seeds:  Fabrikam Inc.              → 9 sections (4 docs)  → vote = 0.11 each
        Walt Flood Realty          → 3 sections (1 doc)   → vote = 0.33 each
        123 Mockup Lane, Washburn  → 1 section  (1 doc)   → vote = 1.00

After document scoping → target doc = Holding Tank Contract (doc_8ad...)

Within target doc, sections:
  "HOLDING TANK SERVICING CONTRACT":
    Fabrikam Inc.    = 0.11
    123 Mockup Lane  = 1.00
    (Walt Flood Realty appears in Property Mgmt, not here)
    Score = 1.11

→ Target: the single section of Holding Tank Contract
→ Chunks scoped to that section's chunks only
```

For multi-section documents, this becomes critical. The Builders Warranty has
3 sections. A question about "arbitration terms" should route to section
"BUILDERS LIMITED WARRANTY WITH ARBITRATION", not "1. Builder's Limited Warranty."

#### B. Section-Embedding Similarity (semantic — query-to-section matching)

Sections have 2048-dim embeddings. At query time:

1. Embed the query with the same model
2. Compute cosine similarity between query embedding and each section embedding
   within the target document
3. Boost chunks from high-similarity sections

$$\text{score}_{\text{section}}(q, s) = \cos(\vec{q}, \vec{s})$$

This is particularly powerful because section titles capture the **topic** of the
section ("EXHIBIT A - SCOPE OF WORK", "2. Term.", "PROPERTY MANAGEMENT AGREEMENT:").
A query about "warranty term duration" will have high similarity with "2. Term."
and low similarity with "EXHIBIT A - SCOPE OF WORK".

### 9.5 Two-Level Scoping: Document → Section

The complete scoping cascade:

```
Query
  ↓
Layer 3a: Document Scoping
  Seed entity → APPEARS_IN_DOCUMENT → Document vote (IDF-weighted)
  → Target document(s)
  ↓
Layer 3b: Section Scoping (within target document)
  Two signals combined:
    (1) Seed entity → APPEARS_IN_SECTION → Section vote (IDF-weighted)
    (2) Query embedding ↔ Section embedding (cosine similarity)
  → Target section(s) within document
  ↓
Chunk retrieval: WHERE d.id IN $target_docs AND s.id IN $target_sections
```

### 9.6 The Scoping Hierarchy

| Level | Question answered | Signal type | Resolution |
|---|---|---|---|
| **Document** | "Which document?" | Entity-doc voting | Corpus → 1–2 documents |
| **Section** | "Which section?" | Entity-section voting + embedding sim | Document → 1–3 sections |
| **Chunk** | "Which text span?" | Entity-chunk scoring | Section → 1–6 chunks |

Each level narrows the funnel. A corpus of 18 chunks across 5 documents:
- No scoping: 18 chunks considered → 6 relevant = 33%
- Document scoping: ~4 chunks from target doc → ~3 relevant = 75%
- Section scoping: ~2 chunks from target section → ~2 relevant = 95%

### 9.7 Cross-Cutting Concern: Section Spanning

Some questions span sections within a document (e.g., "What are all the warranty terms
and arbitration rules?"). Detection:

- If top 2 sections in the target doc have similar votes → include both
- If the query embedding has high similarity with 2+ sections → include both
- Conservative: always include the top-scoring section + any subsections (via SUBSECTION_OF)

### 9.8 Implementation Notes

**No new graph construction needed.** All of these already exist:
- `APPEARS_IN_SECTION` (221 edges)
- `IN_SECTION` (18 edges, every chunk in exactly 1 section)
- Section `embedding` (2048-dim on every section)
- `HAS_SECTION` (document → section)
- `SUBSECTION_OF` (section hierarchy)

The only new code:
1. A `resolve_target_sections()` function (one Cypher query)
2. Optional: embed the query and do cosine sim vs section embeddings
3. Thread `target_section_ids` into the chunk retrieval Cypher

**Chunk retrieval Cypher with full scoping:**
```cypher
MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
WHERE d.id IN $target_document_ids
// Optional section scoping (when target sections resolved)
MATCH (c)-[:IN_SECTION]->(s:Section)
WHERE s.id IN $target_section_ids
```

---

## 10. The Complete Four-Layer Retrieval Model

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Query Understanding                            │
│  "What is the warranty term duration under the builder's warranty?"   │
│           ↓ entity extraction                                        │
│  seeds: [Builder's Limited Warranty, Fabrikam Inc., 2010-06-15]      │
└───────────────────────────┬────────────────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌─────────────────────────────────┐
│  LAYER 1     │  │  LAYER 2     │  │  LAYER 3: Structural Space      │
│  Embedding   │  │  Graph       │  │                                 │
│              │  │              │  │  3a: Document scoping           │
│  "who else   │  │  Entity →    │  │    IDF-vote → BUILDERS WARRANTY │
│   is similar │  │  RELATED_TO  │  │                                 │
│   to these?" │  │  → expand    │  │  3b: Section scoping            │
│              │  │              │  │    IDF-vote + embed sim          │
│              │  │              │  │    → "2. Term." section          │
│              │  │              │  │                                 │
│              │  │              │  │  3c: Position (future)          │
│              │  │              │  │    chunk_index ordering          │
└──────┬───────┘  └──────┬───────┘  └──────────────┬──────────────────┘
       │                 │                         │
       └─────────────────┼─────────────────────────┘
                         ▼
            ┌──────────────────────┐
            │  Chunk Retrieval     │ ← scoped to doc + section
            │  WHERE d.id IN [..]  │
            │  AND s.id IN [..]    │
            ├──────────────────────┤
            │  ~95% relevant       │  (was 33%)
            │  ~1,500 tokens       │  (was 7,800)
            └──────────┬───────────┘
                       ▼
            ┌──────────────────────┐
            │  Synthesis LLM       │ ← less noise = more precise
            │  v1_concise          │
            │  + gpt-5-mini        │
            └──────────────────────┘
```

### Layer 3 Sub-Dimensions

| Sub-layer | Signal | Data source | Complexity |
|---|---|---|---|
| **3a: Document** | Entity-doc IDF voting | `APPEARS_IN_DOCUMENT` edges | O(1) Cypher |
| **3b: Section** | Entity-section IDF voting + query↔section cosine sim | `APPEARS_IN_SECTION` edges + section `embedding` | O(1) Cypher + 1 embed call |
| **3c: Position** | Chunk ordering within section | `chunk_index` property | Free (already have it) |

Layer 3c (position/chunk_index) is a future possibility — using chunk ordering to
prefer contiguous spans and drop isolated fragments. This ties to the fragment citation
problem (25-60% of citations are <25 chars).

---

## 11. One-Line Summary

> The graph already knows which document AND which section each entity belongs to
> (4,522 + 221 structural edges). Sections even have embeddings for semantic matching.
> We just never ask. Wire it into retrieval: 67% noise → ~5% noise, 7,800 tokens → ~1,500 tokens.
