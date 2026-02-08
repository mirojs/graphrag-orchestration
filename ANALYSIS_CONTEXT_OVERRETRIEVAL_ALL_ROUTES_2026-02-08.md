# Analysis: Context Over-Retrieval Across Routes 2/3/4

**Date:** 2026-02-08  
**Status:** Investigation Complete → Optimization Plan Ready  
**Severity:** Medium — causes intermittent synthesis failures on capable models  
**Affects:** Route 2 (Local Search), Route 3 (Global/Thematic), Route 4 (DRIFT Multi-Hop)

---

## 1. Discovery

During the Route 2 synthesis model comparison benchmark (2026-02-08), **gpt-5.1 failed Q-L7** ("What is the Agent fee/commission for long-term leases >180 days?") across all 3 runs, while **gpt-4.1 answered correctly** every time. Both models received identical context from the same deterministic retrieval pipeline.

| Model | Q-L7 Result | Answer Given |
|-------|-------------|-------------|
| gpt-4.1 | **PASS** (3/3 runs) | "ten percent (10%) of the gross revenues" |
| gpt-5.1 | **FAIL** (3/3 runs) | "information not found... text is truncated" |
| gpt-4.1-mini | PASS (3/3) | Correct |

gpt-5.1 consistently claimed the long-term lease fee text was "truncated" or "incomplete," even though the data was fully present. Run 1 even acknowledged "10% of gross revenues" existed but misclassified it as "for management services generally" rather than for long-term leases specifically.

---

## 2. Root Cause Investigation

### 2.1 Neo4j Data Verification

Connected to Neo4j Aura and verified the source data. The relevant chunk text in doc_591d (and all document copies) is **perfectly clear and complete**:

```
(b) A fee/commission of twenty five percent (25%) of the gross revenues for management
services for short term and/or vacation rentals (reservations of less than 180 days).

(c) A fee/commission of ten percent (10%) of the gross revenues for management services
for long term leases (leases of more than 180 days).

(d) A pro-ration charge for advertising for short-term (vacation rentals), at $75.
```

**The data is not truncated.** The answer "ten percent (10%)" sits immediately before "for long term leases" in a cleanly structured paragraph.

### 2.2 Retrieval Pipeline Trace

The Route 2 pipeline for Q-L7 proceeds as follows:

| Stage | Output | Detail |
|-------|--------|--------|
| **NER** (gpt-4o) | 5 seed entities | PROPERTY MANAGEMENT AGREEMENT, Walt Flood Realty, AGENT'S FEES, Pacific View Retreat, 456 Palm Tree Avenue |
| **PPR** (top_k=15) | 15 evidence entities | Seeds + Warranty, AGENCY START-UP FEE, DISCLAIMER OF GUARANTEES, AGENCY, RESPONSIBILITIES OF AGENT, RESPONSIBILITIES OF OWNER, warranty period, TERM, limited warranty term, other features of home |
| **Budget filter** (0.8) | 13 entities | First 13 of 15 |
| **Chunk retrieval** | 42 unique chunks | Via TextChunk→MENTIONS→Entity, with 12/entity + 3/section + 6/doc caps |
| **Context assembly** | ~49,042 tokens | Full chunk text, no truncation, no re-ranking |

### 2.3 Entity Relevance Breakdown

Of the 15 PPR entities, only **2-3 are actually relevant** to the fee question:

| Entity | Relevance to Q-L7 | Chunks Retrieved | Chunks with Answer |
|--------|-------------------|------------------|--------------------|
| **AGENT'S FEES** | **HIGH** — directly about fees | ~12 | ~12 (all) |
| **PROPERTY MANAGEMENT AGREEMENT** | Medium — parent doc entity | ~12 | ~8 |
| Warranty | **NONE** — about home warranty | ~12 | 0 |
| DISCLAIMER OF GUARANTEES | **NONE** | ~3 | 0 |
| TERM | Low — about lease term, not fees | ~6 | ~2 |
| AGENCY START-UP FEE | Low — about startup fee, not commission | ~3 | 0 |
| Walt Flood Realty | Low — agent name, broad | ~6 | ~3 |
| RESPONSIBILITIES OF AGENT | **NONE** | ~3 | 0 |
| RESPONSIBILITIES OF OWNER | **NONE** | ~3 | 0 |
| Other entities | Low–None | remaining | few |

**~22 of 42 chunks are completely irrelevant** to the fee question, pulled in by noise entities from PPR graph expansion.

### 2.4 Cross-Document Duplication

The same Property Management Agreement exists as **5+ document copies** in the graph:

- doc_591d5a607cca... (the primary)
- doc_c10729...
- doc_83de43...
- doc_9c7df6...
- doc_8f697a...
- doc_937e6d...

Each has its own TextChunks. Of the 20 chunks containing "ten percent," they are **near-identical paragraphs** from different document copies. The same answer appears ~20 times in the context — massive redundancy.

### 2.5 Pre-Diversification Scale

Before the section/doc caps (12/entity, 3/section, 6/doc), the raw query returns:

| Metric | Value |
|--------|-------|
| Total rows (entity × chunk) | **737** |
| Unique chunks | **276** |
| Total chars | **1,094,748** |
| Estimated tokens | **~273,687** |
| Rows with "ten percent" | **513 / 737** (70%) |

The caps reduce this from 276 → 42 chunks, but **42 chunks at ~49K tokens is still far too large** for a simple factual extraction question.

### 2.6 Why gpt-5.1 Failed

gpt-5.1's behavior across all 3 runs was consistent:
- **Saw the 25% short-term fee** clearly and cited it correctly
- **Claimed the 10% long-term fee text was "truncated"** — a hallucination
- Run 1 even acknowledged "10% of gross revenues" but misclassified it as "for management services generally"

**Hypothesis:** With ~49K tokens of context, the same fee paragraph repeated ~20 times across document copies, and ~22 completely irrelevant chunks, gpt-5.1's attention mechanism couldn't reliably discriminate between the 25% (short-term) and 10% (long-term) clauses. It found the 25% easily (it appears first in the text) but "lost" the 10% in the noise. gpt-4.1, having a more robust information extraction capability at high context lengths, succeeded.

---

## 3. Architecture Across Routes 2/3/4

**All three routes face the same over-retrieval problem** — unbounded context sent to the LLM — but they reach it through **different pipelines**. Routes 2 & 4 share a common synthesis path (`synthesize()` → `_retrieve_text_chunks()` → `_build_cited_context()`). Route 3 uses a completely separate path (`synthesize_with_graph_context()`) that collects chunks differently and never calls `_retrieve_text_chunks()`.

### 3.1 Pipeline Flows

**Routes 2 & 4** share the same synthesis path:
```
NER (gpt-4o) → Seed Entities
    → PPR (personalized_pagerank_native) → Evidence Entities (with scores)
        → _retrieve_text_chunks() → TextChunk list  (scores DISCARDED here)
            → _build_cited_context() → Context string (UNBOUNDED)
                → LLM Synthesis call (synthesize())
```

**Route 3** uses a completely different path:
```
Community Matching → Hub Entities (up to 30)
    → get_full_context() → graph_context.source_chunks (Batch 1)
        + BM25/Vector RRF → graph_context.source_chunks (Batch 2, merged)
            → PPR (CONDITIONAL, fast_mode may skip) → evidence_nodes
                (scores used ONLY for metadata, NOT for retrieval)
            → synthesize_with_graph_context() → Context string (UNBOUNDED)
                → LLM Synthesis call
```

### 3.2 Route Parameters

| Parameter | Route 2 | Route 3 | Route 4 |
|-----------|---------|---------|---------|
| PPR top_k | **15** | **20** (conditional, often skipped) | **20** (+ sub-questions at 30) |
| Chunk retrieval method | `_retrieve_text_chunks()` | `get_full_context()` + BM25/RRF (**different path**) | `_retrieve_text_chunks()` |
| Synthesis method | `synthesize()` | `synthesize_with_graph_context()` (**different**) | `synthesize()` |
| Relevance budget | 0.8 | N/A (no entity budget) | 0.8 |
| Budgeted entities | ~13 | N/A | ~17 (per question) |
| limit_per_entity | 12 | 3 (max_chunks_per_entity) | 12 |
| Section diversification | max_per_section=3, max_per_document=6 | max_per_section=3, max_per_document=6 | max_per_section=3, max_per_document=6 |
| Max graph chunks (theoretical) | 13 × 12 = 156 | 30 entities × 3 = 90 (pre-diversification) | 17 × 12 × N_subQ |
| Additional sources | — | BM25/RRF (+20) + coverage gap-fill | Sub-question iteration + coverage gap-fill |
| PPR scores used? | **Discarded** at `_retrieve_text_chunks()` | **Never used** for retrieval (only metadata) | **Discarded** at `_retrieve_text_chunks()` |
| **Token budget** | **NONE** | **NONE** | **NONE** |
| **Cross-entity dedup** | **NONE** | Partial (BM25 merge dedup by chunk_id) | **NONE** |
| **Re-ranking by query** | **NONE** | **NONE** | **NONE** |
| **PPR score threshold** | **NONE** (score > 0) | **NONE** | **NONE** |

### 3.3 Route 3 Deep Dive — A Completely Different Pipeline

Route 3 is the global/thematic search route. It uses a **fundamentally different architecture** from Routes 2/4 — it does NOT call `_retrieve_text_chunks()` at all. Instead, chunks are collected from two separate sources before synthesis, and PPR scores (when computed) are **never used for chunk retrieval**.

#### 3.3.1 Route 3 Full Pipeline Trace

```
┌──────────────────────────────────────────────────────────────────┐
│ ROUTE 3 — Global/Thematic Search                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Stage 3.1: Community Matching                                   │
│  ┌─────────────────────────────────────────────────┐             │
│  │ community_matcher.match_communities(query,      │             │
│  │   top_k=3)                                      │             │
│  │ → 3 community IDs                               │             │
│  └─────────────────────────────────────────────────┘             │
│                        ↓                                         │
│  Stage 3.2: Hub Entity Extraction                                │
│  ┌─────────────────────────────────────────────────┐             │
│  │ hub_extractor.extract_hub_entities(communities,  │             │
│  │   top_k_per_community=10)                       │             │
│  │ → up to 30 hub entities                         │             │
│  └─────────────────────────────────────────────────┘             │
│                        ↓                                         │
│  Stage 3.3: Enhanced Graph Context ← CHUNK SOURCE #1            │
│  ┌─────────────────────────────────────────────────┐             │
│  │ enhanced_retriever.get_full_context(             │             │
│  │   hub_entities,                                  │             │
│  │   max_chunks_per_entity=3,     ← 3 per entity   │             │
│  │   max_relationships=30,                          │             │
│  │   section_diversify=True,                        │             │
│  │   max_per_section=3,                             │             │
│  │   max_per_document=6)                            │             │
│  │ → graph_context.source_chunks (Batch 1)         │             │
│  │ → graph_context.relationships (up to 30)        │             │
│  │ → graph_context.entity_descriptions             │             │
│  └─────────────────────────────────────────────────┘             │
│                        ↓                                         │
│  Stage 3.3.5: BM25 + Vector RRF Hybrid ← CHUNK SOURCE #2       │
│  ┌─────────────────────────────────────────────────┐             │
│  │ Cypher25 hybrid search:                          │             │
│  │   bm25_k=30, vector_k=30, rrf_k=60, top_k=20  │             │
│  │ BM25 doc diversity:                              │             │
│  │   merge_top_k=20, max_per_doc=2, min_docs=3    │             │
│  │ → Merged INTO graph_context.source_chunks       │             │
│  │   (deduped by chunk_id)                         │             │
│  └─────────────────────────────────────────────────┘             │
│                        ↓                                         │
│  Stage 3.4: PPR (CONDITIONAL) ← SCORES WASTED                   │
│  ┌─────────────────────────────────────────────────┐             │
│  │ IF fast_mode (default ON):                       │             │
│  │   SKIPPED unless query has relationship         │             │
│  │   indicators or 2+ proper nouns                 │             │
│  │ WHEN ENABLED:                                    │             │
│  │   seeds = hub_entities + related_entities[:10]  │             │
│  │   tracer.trace(query, seeds, top_k=20)          │             │
│  │   → evidence_nodes with scores                  │             │
│  │   BUT: used ONLY for evidence_path metadata     │             │
│  │   NOT used for chunk retrieval at all!           │             │
│  └─────────────────────────────────────────────────┘             │
│                        ↓                                         │
│  Stage 3.4.1: Coverage Gap-Fill                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │ For coverage_mode queries:                       │             │
│  │ get_document_lead_chunks() for missing docs     │             │
│  │ → 1 chunk per missing document added            │             │
│  └─────────────────────────────────────────────────┘             │
│                        ↓                                         │
│  Stage 3.5: Synthesis ← DIFFERENT ENTRY POINT                   │
│  ┌─────────────────────────────────────────────────┐             │
│  │ synthesizer.synthesize_with_graph_context(       │             │
│  │   query, evidence_nodes, graph_context,         │             │
│  │   response_type)                                │             │
│  │ Context built from graph_context.source_chunks: │             │
│  │   - Groups chunks by doc_id                     │             │
│  │   - Full chunk text, NO truncation              │             │
│  │   - Sentence-level citations from Azure DI      │             │
│  │   - Relationship context (up to 30)             │             │
│  │   - Entity descriptions (top 10)                │             │
│  │   - NO token budget anywhere                    │             │
│  │   → _generate_graph_response(full_context)      │             │
│  └─────────────────────────────────────────────────┘             │
│                                                                  │
│  Code: orchestrator.py L486-L1200                                │
│  Synthesis: synthesis.py L297 (synthesize_with_graph_context)    │
│  Chunk retrieval: enhanced_graph_retriever.py L711               │
└──────────────────────────────────────────────────────────────────┘
```

#### 3.3.2 Route 3's Unique Architecture Problem

Route 3 is architecturally different from Routes 2/4 in three critical ways:

**1. PPR scores are not just discarded — they're never used for retrieval at all.**

In Routes 2/4, PPR produces `evidence_nodes` → `_retrieve_text_chunks()` fetches chunks for those entities (ignoring scores, but at least using the entity list). In Route 3, chunks are already collected **before PPR runs** (Stages 3.3 + 3.3.5). The PPR output (`evidence_nodes`) is passed to `synthesize_with_graph_context()`, but that method only uses `evidence_nodes` to populate the `evidence_path` metadata field — never for retrieval.

```python
# orchestrator.py L1158 — evidence_nodes passed but NOT used for chunks:
result = await self.synthesizer.synthesize_with_graph_context(
    query=query,
    evidence_nodes=evidence_nodes,   # ← only used for evidence_path
    graph_context=graph_context,     # ← source_chunks already here
    response_type=response_type,
)

# synthesis.py L297 — synthesize_with_graph_context():
# Builds context entirely from graph_context.source_chunks
# evidence_nodes only stored as metadata, never drives chunk selection
```

**2. Route 3 uses `synthesize_with_graph_context()` (L297), NOT `synthesize()` (L145).**

This is a completely separate code path that does NOT call `_retrieve_text_chunks()` or `_build_cited_context()`. It builds its own context string from `graph_context.source_chunks` grouped by document, adding relationship context and entity descriptions on top. Like Route 2/4's path, it has **no token budget**, but the lack of PPR-score-based filtering is even more pronounced because PPR doesn't even influence which chunks are in the set.

**3. PPR is often SKIPPED entirely.**

In `fast_mode` (default ON), Route 3 skips PPR unless the query meets specific criteria (relationship indicators like "between", "impact on", or 2+ capitalized proper nouns). For simple thematic queries like "What are the key terms?", PPR never runs — the chunk set is determined entirely by hub entity expansion (Stage 3.3) + BM25/Vector search (Stage 3.3.5).

#### 3.3.3 Chunk Source Analysis

Route 3 collects chunks from two independent sources:

| Source | Mechanism | Max Chunks | Controls |
|--------|-----------|------------|----------|
| **Stage 3.3:** Enhanced graph context | `get_full_context()` via MENTIONS edges | 30 entities × 3/entity = **90** pre-diversification | max_chunks_per_entity=3, section_diversify=True, max_per_section=3, max_per_document=6 |
| **Stage 3.3.5:** BM25 + Vector RRF | Cypher25 hybrid search | **20** (merge_top_k=20) | max_per_doc=2, min_docs=3, dedup by chunk_id |
| **Stage 3.4.1:** Coverage gap-fill | `get_document_lead_chunks()` | 1 per missing doc | Only for coverage_mode queries |

**Post-diversification estimate for Stage 3.3:**
- 30 hub entities × 3 chunks/entity = 90 raw chunks
- Section diversification (max_per_section=3, max_per_document=6) reduces this significantly
- With ~5 documents × 6 chunks/doc = ~30 chunks survive diversification
- But: entity overlap means many entities share chunks → actual unique chunks likely ~20-40

**Combined worst case:** ~40 (graph) + 20 (BM25/RRF) + coverage gap-fill = **50-70 chunks**
At ~1,150 tokens/chunk → **57K-80K tokens** before entity/relationship context is added.

#### 3.3.4 Context Assembly in `synthesize_with_graph_context()` (synthesis.py L297-600)

The context is built with NO budget controls:

```python
# synthesis.py — context building for Route 3:

# 1. Group source_chunks by doc_id
for chunk in graph_context.source_chunks:
    doc_groups[chunk.document_id].append(chunk)

# 2. Build chunk context — FULL TEXT, no truncation
for doc_id, chunks in doc_groups.items():
    context_parts.append(f"=== DOCUMENT: {title} ===")
    for i, chunk in enumerate(chunks, 1):
        citation_key = f"[{global_idx}]"
        entry = f"{citation_key}"
        if chunk.section_path:
            entry += f" [Section: {' > '.join(chunk.section_path)}]"
        if chunk.entity_name:
            entry += f" [Entity: {chunk.entity_name}]"
        entry += f"\n{chunk.text}"           # ← FULL chunk text
        context_parts.append(entry)

# 3. Add relationship context ON TOP (up to 30 relationships)
for rel in graph_context.relationships[:30]:
    rel_parts.append(f"- {rel.source_entity} → {rel.relationship_type} → {rel.target_entity}")

# 4. Add entity descriptions ON TOP (top 10)
for entity, desc in list(graph_context.entity_descriptions.items())[:10]:
    entity_parts.append(f"- {entity}: {desc}")

# 5. Concatenate everything — no budget, no truncation
full_context = entity_context + "\n\n" + relationship_context + "\n\n" + chunk_context
```

#### 3.3.5 Route 3-Specific Optimization Notes

For Route 3, the Phase 2 fix (PPR score-weighted chunk allocation) **cannot apply directly** because:
- Route 3 doesn't use `_retrieve_text_chunks()` at all
- Chunks come from enhanced graph context + BM25/RRF, not from PPR entities
- PPR often doesn't even run (fast_mode skips it)

The optimization strategy for Route 3 must be different:

| Phase | Routes 2/4 Fix | Route 3 Equivalent |
|-------|----------------|---------------------|
| **1a** Chunk dedup | Dedup in `_retrieve_text_chunks()` | Dedup already exists in BM25 merge (by chunk_id), but Stage 3.3 + 3.3.5 chunks can still overlap → need dedup at `synthesize_with_graph_context()` entry |
| **1b** Token budget | Cap in `_build_cited_context()` | Cap in `synthesize_with_graph_context()` before `_generate_graph_response()` |
| **2a** PPR score-weighted allocation | Scale limit_per_entity by PPR score | N/A — Route 3 doesn't use PPR for chunk retrieval. Instead: use RRF scores from Stage 3.3.5 + relevance_score from Stage 3.3 to **re-rank** the combined chunk set before token budget truncation |
| **2b** PPR score threshold | Filter low-scoring entities from PPR | Can apply IF PPR runs (non-fast_mode). For fast_mode: not applicable |
| **3a** Semantic re-ranking | Re-rank chunks by query similarity | Same approach — but more impactful here since no PPR scores exist to leverage |

**Key Route 3 fix: Token budget in `synthesize_with_graph_context()`**

The most impactful single change for Route 3 is adding a token budget to `synthesize_with_graph_context()`, identical in concept to Phase 1b but applied to the Route 3 context assembly loop. This is the ONLY code path Route 3 uses, and it currently has zero truncation.

### 3.4 Route 4 Deep Dive — The Worst Case

Route 4 is the most complex pipeline in the system. It runs **multiple PPR passes** across decomposed sub-questions, a confidence loop that may trigger additional passes, and a coverage gap-fill stage. Here is the complete flow with code references:

#### 3.4.1 Route 4 Full Pipeline Trace

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4.0: Deterministic date metadata check (optional early exit)     │
│   orchestrator.py L1453-L1498                                          │
│   → If query is "which doc has latest date?", answer from Document     │
│     .date property without LLM. No over-retrieval here.                │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ (not a date query)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4.1: Query Decomposition (LLM)                                   │
│   orchestrator.py L1501-L1503                                          │
│   → _drift_decompose(query) → typically 3-5 sub-questions              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4.2: Iterative Entity Discovery (per sub-question)               │
│   orchestrator.py L1506-L1510 → _drift_execute_discovery_pass()        │
│   For EACH sub-question:                                               │
│     1. NER: disambiguator.disambiguate(sub_q) → entities               │
│     2. PPR: tracer.trace(sub_q, seeds, top_k=5) → partial evidence     │
│   Collects: all_seeds (deduplicated), intermediate_results             │
│   → With 4 sub-questions: ~20 seeds, 4 × PPR calls                    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4.3: Consolidated Tracing (MAIN PPR)                             │
│   orchestrator.py L1514-L1519                                          │
│   tracer.trace(query, all_seeds, top_k=30)                             │
│   → Returns complete_evidence: List[(entity_name, ppr_score)]          │
│   → Up to 30 entities WITH SCORES                                     │
│   ⚠ PPR scores are computed but DISCARDED downstream                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4.3.5: Confidence Loop (conditional)                             │
│   orchestrator.py L1521-L1616                                          │
│   If confidence < 0.5 OR entity_diversity < 0.3:                       │
│     1. Re-decompose thin questions                                     │
│     2. _drift_execute_discovery_pass(refined_questions)                 │
│        → More NER + PPR(top_k=5) per refined question                  │
│     3. tracer.trace(query, additional_seeds, top_k=15) ← ANOTHER PPR   │
│     4. Merge into complete_evidence (deduped by entity name)           │
│   → Can add 15+ more entities to complete_evidence                     │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4.3.6: Coverage Gap Fill                                         │
│   orchestrator.py L1620-L1873                                          │
│   If is_comprehensive_query ("list all", "compare", etc.):             │
│     → get_all_sections_chunks(max_per_section=None)  ← ENTIRE CORPUS   │
│     → ALL chunks from ALL sections added to coverage_chunks            │
│   Else:                                                                │
│     → 1 chunk per missing document (semantic or early-chunk)           │
│   → coverage_chunks_for_synthesis passed to synthesizer                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Stage 4.4: Synthesis                                                   │
│   orchestrator.py L1876-L1883                                          │
│   synthesizer.synthesize(                                              │
│     evidence_nodes=complete_evidence,     ← [(name, score), ...]       │
│     coverage_chunks=coverage_chunks       ← already-fetched chunks     │
│   )                                                                    │
│                                                                        │
│   INSIDE synthesize() (synthesis.py L177):                             │
│     _retrieve_text_chunks(evidence_nodes)                              │
│       → Takes entity NAMES, IGNORES scores                             │
│       → Budget: int(len(entities) * 0.8) + 1                           │
│       → For each entity: Cypher UNWIND → 12/entity, 3/section, 6/doc  │
│       → chunks.extend() with NO cross-entity dedup                     │
│     text_chunks.extend(coverage_chunks)   ← adds coverage on top       │
│     _build_cited_context(all_chunks)                                   │
│       → Full text, NO token budget, NO re-ranking                      │
│     LLM call with unbounded context                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 3.4.2 PPR Score Waste — The Core Design Flaw

Route 4 runs **up to 3 PPR passes** (Stage 4.2 per-sub-question, Stage 4.3 consolidated, Stage 4.3.5 confidence loop). Each produces ranked `(entity_name, ppr_score)` tuples. But at Stage 4.4, `_retrieve_text_chunks()` **strips the scores** and treats every entity name identically:

```python
# synthesis.py _retrieve_text_chunks() L752-L766:
for name, _score in evidence_nodes:   # ← _score DISCARDED
    cleaned = _clean_entity_name(name)
    ...
    entity_names.append(cleaned)

# All entities get the same limit_per_entity=12 regardless of PPR score
entity_chunks_map = await self.text_store.get_chunks_for_entities(selected_entities)
for entity_name in selected_entities:
    chunks.extend(entity_chunks_map.get(entity_name, []))  # 12 each, uniform
```

This means an entity with PPR score 5.0 (directly connected to query seeds) retrieves the **same 12 chunks** as an entity with score 0.01 (barely reachable via 3-hop graph traversal). The PPR ranking work is wasted.

#### 3.4.3 Worst-Case Context Size Estimate (Route 4)

| Component | Entities | Chunks per entity | Total chunks | Est. tokens |
|-----------|----------|-------------------|--------------|-------------|
| Stage 4.3 PPR (top_k=30) | 30 | 12 (cap) | 360 | ~414,000 |
| Budget filter (0.8) | 25 | 12 | 300 | ~345,000 |
| After section/doc caps | 25 | ~4-6 avg | ~125 | ~143,750 |
| + Confidence loop (+15 entities) | 40 | ~4-6 avg | ~200 | ~230,000 |
| + Coverage gap-fill (comprehensive) | +ALL sections | variable | +50-200 | +57K-230K |
| **Total worst case** | — | — | **200-400** | **230K-460K** |

Even the **moderate** case (no confidence loop, non-comprehensive query) produces ~125 chunks / ~144K tokens. That's **3× worse than Route 2's already-problematic 42 chunks / 49K tokens.**

#### 3.4.4 Coverage Gap-Fill Amplification

For comprehensive queries (`"list all"`, `"compare the"`, `"across all documents"`), Stage 4.3.6 calls:

```python
# orchestrator.py L1761:
coverage_source_chunks = await self.enhanced_retriever.get_all_sections_chunks(
    max_per_section=None,  # ← Get ALL chunks from ALL sections
)
```

This retrieves **the entire corpus** as coverage chunks, which are then appended to the chunks from `_retrieve_text_chunks()`. The coverage chunks bypass the per-entity caps entirely since they're passed as `coverage_chunks` and simply `.extend()`ed:

```python
# synthesis.py L180:
if coverage_chunks:
    text_chunks.extend(coverage_chunks)  # ← Unbounded addition
```

#### 3.4.5 Route 4 Does NOT Need Another PPR Before Synthesis

The question arises: if we add re-ranking, are we "doing PPR again"? **No.** PPR ranks **entities** in the graph. What's missing is ranking **chunks** by their relevance to the query. These are different:

| PPR (entity-level) | Chunk-level ranking (missing) |
|---|---|
| Operates on Entity graph nodes | Operates on TextChunk text content |
| Uses graph topology (edges, hops) | Uses semantic similarity to query |
| Answers: "Which entities are structurally related to the seeds?" | Answers: "Which text passages actually contain information relevant to the question?" |
| Already done ✓ (Stages 4.2, 4.3, 4.3.5) | Never done ✗ |

However, we **already have PPR scores** that encode entity importance. The simplest and most efficient fix is to **use those scores to weight chunk allocation** rather than ignoring them. A high-PPR entity should get more chunks; a low-PPR entity should get fewer or zero. This requires zero additional API calls — just arithmetic on data we already have.

---

## 4. Six Gaps Identified

### Gap 1: No Cross-Entity Chunk Deduplication

**Location:** `synthesis.py` `_retrieve_text_chunks()` (line 731)

Currently, `chunks.extend(batch_chunks)` appends all chunks from each entity without checking if a chunk was already added from a different entity. The same chunk can appear multiple times when it MENTIONS multiple entities (e.g., a chunk mentioning both `AGENT'S FEES` and `PROPERTY MANAGEMENT AGREEMENT`).

```python
# Current code (line 786-791):
for entity_name in selected_entities:
    entity_chunks = entity_chunks_map.get(entity_name, [])
    if entity_chunks:
        chunks.extend(entity_chunks)  # ← No dedup check
```

### Gap 2: No Semantic Re-Ranking by Query Relevance

**Location:** `synthesis.py` `_build_cited_context()` (line 802)

Chunks are ordered by `chunk_index` (document order) within each entity group, then assembled in entity-appearance order. A chunk from noise entity "Warranty" about home appliance coverage has equal priority as a chunk from `AGENT'S FEES` about the exact commission percentage.

There is **no step** that scores chunks by their semantic similarity to the original user query.

### Gap 3: No Token Budget on Context Assembly

**Location:** `synthesis.py` `_build_cited_context()` (line 802)

The context string grows without any limit. Each chunk's **full text** (averaging ~4,600 chars / ~1,150 tokens) is appended verbatim. With 42 chunks, the context reaches ~49K tokens. With Route 3/4, it could be 100K+.

There are truncation safeguards in specialized code paths (`_comprehensive_sentence_level_extract` truncates to 1500 chars, `_build_graph_aware_comparison_context` truncates >3000 char chunks), but **the main `summary`/`detailed_report` synthesis path has zero truncation**.

```python
# _build_cited_context() (line 866-870):
for chunk in group:
    text = chunk.get("text", "")
    # ... citation marker logic ...
    cited_sections.append(f"[{idx}] {text}")  # ← Full text, no limit
```

### Gap 4: No PPR Score Thresholding

**Location:** `async_neo4j_service.py` `personalized_pagerank_native()` (line 569)

The final PPR Cypher returns all entities with `WHERE score > 0 ORDER BY score DESC LIMIT $top_k`. An entity with a score of 0.001 (barely connected) is treated the same as one with score 5.0 (directly relevant). This is how noise entities like "Warranty" and "DISCLAIMER OF GUARANTEES" make it into the evidence set.

### Gap 5: No Cross-Document Text Deduplication

When 5+ copies of the same document exist in the graph (common for versioned contracts), each produces its own set of chunks with near-identical text. The same paragraph appears ~20 times in the context. There is no logic to detect and merge duplicate text across document copies.

### Gap 6: PPR Scores Computed Then Discarded (Routes 2/4) or Never Used (Route 3)

**Location (Routes 2/4):** `synthesis.py` `_retrieve_text_chunks()` (line 752)

Route 4 runs up to 3 PPR passes (Stages 4.2, 4.3, 4.3.5), producing ranked `(entity_name, ppr_score)` tuples. But `_retrieve_text_chunks()` iterates with `for name, _score in evidence_nodes` — the score is explicitly ignored via the `_` convention. Every entity then gets the same `limit_per_entity=12` regardless of its PPR importance.

**Location (Route 3):** `orchestrator.py` L1158 + `synthesis.py` L297

Route 3's situation is **even worse**: PPR (when it runs at all — fast_mode often skips it) produces `evidence_nodes`, but `synthesize_with_graph_context()` only stores them as metadata in `evidence_path`. The chunks are already in `graph_context.source_chunks` from Stages 3.3 + 3.3.5, collected **before PPR ran**. PPR output has zero influence on which chunks the LLM sees.

This is the most wasteful gap: we spend significant compute (multiple Neo4j PPR traversals) to produce a ranking signal, then throw it away at the most critical juncture — deciding **how many chunks** each entity contributes to the LLM context.

```python
# Routes 2/4 — Current code (synthesis.py L752-L766):
for name, _score in evidence_nodes:  # ← _score DISCARDED
    cleaned = _clean_entity_name(name)
    ...
    entity_names.append(cleaned)

# Budget slices entities by position, not score:
selected_entities = entity_names[:budget_limit]  # first N, not top-scoring N

# All selected entities get same 12 chunks:
entity_chunks_map = await self.text_store.get_chunks_for_entities(selected_entities)
```

```python
# Route 3 — PPR output ignored entirely (orchestrator.py L1158):
result = await self.synthesizer.synthesize_with_graph_context(
    query=query,
    evidence_nodes=evidence_nodes,   # ← only stored as metadata
    graph_context=graph_context,     # ← chunks already here from Stages 3.3+3.3.5
    response_type=response_type,
)
# synthesize_with_graph_context() builds context from graph_context.source_chunks
# evidence_nodes NEVER influence chunk selection
```

**Note:** The `entity_names[:budget_limit]` preserves insertion order from `evidence_nodes`, which IS PPR-score-descending (the tracer returns sorted results). So the budget filter does implicitly drop the lowest-scoring entities. But among the **selected** entities, a score-5.0 entity and a score-0.5 entity both get 12 chunks.

---

## 5. Optimization Plan

### Phase 1: Quick Wins (Low Risk, High Impact)

#### 1a. Cross-Entity Chunk Deduplication

**File (Routes 2/4):** `src/worker/hybrid_v2/pipeline/synthesis.py` → `_retrieve_text_chunks()`

```python
# Add seen_chunk_ids set before the entity loop
seen_chunk_ids: set = set()
for entity_name in selected_entities:
    entity_chunks = entity_chunks_map.get(entity_name, [])
    for chunk in entity_chunks:
        cid = chunk.get("id", chunk.get("chunk_id", ""))
        if cid and cid not in seen_chunk_ids:
            seen_chunk_ids.add(cid)
            chunks.append(chunk)
```

**File (Route 3):** `src/worker/hybrid_v2/pipeline/synthesis.py` → `synthesize_with_graph_context()`

Route 3 already has partial dedup: BM25/RRF merge (Stage 3.3.5) deduplicates by `chunk_id` when merging into `graph_context.source_chunks`. However, chunks from Stage 3.3 (enhanced graph context) may overlap with Stage 3.3.5 (BM25/RRF) chunks. A dedup pass at the start of `synthesize_with_graph_context()` would catch these:

```python
# At start of synthesize_with_graph_context():
seen_ids = set()
deduped_chunks = []
for chunk in graph_context.source_chunks:
    if chunk.chunk_id not in seen_ids:
        seen_ids.add(chunk.chunk_id)
        deduped_chunks.append(chunk)
graph_context.source_chunks = deduped_chunks
```

- **Effort:** ~10 lines per path (~20 total)
- **Risk:** Zero — purely additive guard
- **Expected impact:** ~10-20% chunk reduction (overlap between entities like AGENT'S FEES ↔ PROPERTY MANAGEMENT AGREEMENT)

#### 1b. Token Budget Cap on Context Assembly

**File (Routes 2/4):** `src/worker/hybrid_v2/pipeline/synthesis.py` → `_build_cited_context()`
**File (Route 3):** `src/worker/hybrid_v2/pipeline/synthesis.py` → `synthesize_with_graph_context()`

Add a `max_context_tokens` parameter (default **20,000 tokens**, configurable via `SYNTHESIS_MAX_CONTEXT_TOKENS` env var). Use `tiktoken` (already in project dependencies) to count tokens incrementally as chunks are appended. Stop adding chunks once budget is reached.

```python
# In _build_cited_context():
import tiktoken
enc = tiktoken.encoding_for_model("gpt-4o")
token_count = 0
max_tokens = self.max_context_tokens  # default 20000

for chunk in group:
    text = chunk.get("text", "")
    chunk_tokens = len(enc.encode(text))
    if token_count + chunk_tokens > max_tokens:
        logger.info("context_budget_reached", current=token_count, limit=max_tokens)
        break
    token_count += chunk_tokens
    cited_sections.append(f"[{idx}] {text}")
```

- **Effort:** ~25 lines changed + new `__init__` parameter + env var
- **Risk:** Low — must be placed AFTER re-ranking (Phase 2) to cut the right chunks. Until re-ranking is done, this cuts chunks in entity-appearance order which is suboptimal but still better than no limit.
- **Expected impact:** Caps context at ~20K tokens regardless of entity/chunk count. For Q-L7: 49K → 20K tokens, dropping ~22 irrelevant chunks.
- **Default reasoning:** 20K tokens keeps context within the high-attention zone of all current models while allowing sufficient evidence for complex multi-source answers. Configurable per deployment.

### Phase 2: Use Existing Ranking Signals (Medium Effort, High Impact)

The key insight is that **Routes 2/4 already compute PPR scores but discard them**, and **Route 3 has RRF scores from BM25/Vector search that could be leveraged**. Phase 2 uses these existing signals — zero additional API calls, zero new model dependencies.

#### 2a. PPR Score-Weighted Chunk Allocation (Routes 2/4)

**File:** `src/worker/hybrid_v2/pipeline/synthesis.py` → `_retrieve_text_chunks()`

Instead of giving every entity the same `limit_per_entity=12`, allocate chunks proportionally to PPR score. High-scoring entities get more chunks; low-scoring entities get fewer.

```python
async def _retrieve_text_chunks(
    self, evidence_nodes: List[Tuple[str, float]]
) -> List[Dict[str, Any]]:
    # ... existing cleaning and dedup ...
    
    # NEW: Build score map before budget filter
    score_map: Dict[str, float] = {}
    for name, score in evidence_nodes:
        cleaned = _clean_entity_name(name)
        if cleaned and cleaned not in score_map:
            score_map[cleaned] = score
    
    # Budget filter (unchanged)
    selected_entities = entity_names[:budget_limit]
    
    # NEW: Compute per-entity chunk limits from PPR scores
    if selected_entities:
        max_score = max(score_map.get(e, 0) for e in selected_entities)
        if max_score > 0:
            entity_limits = {}
            for e in selected_entities:
                ratio = score_map.get(e, 0) / max_score
                # Scale: top entity gets full limit, lowest gets min 2
                entity_limits[e] = max(2, int(self.limit_per_entity * ratio))
        else:
            entity_limits = {e: self.limit_per_entity for e in selected_entities}
    
    # Batch query with per-entity limits
    entity_chunks_map = await self.text_store.get_chunks_for_entities(
        selected_entities, per_entity_limits=entity_limits
    )
```

- **Effort:** ~30 lines in `_retrieve_text_chunks()` + minor change to `get_chunks_for_entities()` to accept per-entity limits
- **Risk:** Low — PPR scores are already sorted descending. This just translates the ranking into differentiated allocation.
- **Expected impact (Q-L7 example):**
  | Entity | PPR Score | Old Limit | New Limit (scaled) |
  |--------|-----------|-----------|--------------------|
  | PROPERTY MANAGEMENT AGREEMENT | 5.0 | 12 | 12 |
  | AGENT'S FEES | 3.5 | 12 | 8 |
  | Walt Flood Realty | 2.0 | 12 | 5 |
  | Warranty | 0.2 | 12 | **2** |
  | DISCLAIMER OF GUARANTEES | 0.1 | 12 | **2** |
  | RESPONSIBILITIES OF AGENT | 0.05 | 12 | **2** |

  Total chunks: from ~42 → ~28, with noise entities contributing only 2 each instead of filling their full quota.
- **No additional API calls.** Uses data already computed by PPR.
- **Applies to Routes 2 and 4** which share `_retrieve_text_chunks()`.

#### 2b. PPR Score Thresholding (Routes 2/4)

**File:** `src/worker/services/async_neo4j_service.py` → `personalized_pagerank_native()`

Add a `min_score_ratio` parameter (default **0.10**, configurable via `PPR_MIN_SCORE_RATIO`). After computing PPR scores, drop any entity whose score is less than 10% of the top-scoring entity's score.

```python
# Post-processing in personalized_pagerank_native():
if results:
    max_score = results[0][1]  # Already sorted DESC
    threshold = max_score * min_score_ratio
    results = [(name, score) for name, score in results if score >= threshold]
```

- **Effort:** ~10 lines + env var
- **Risk:** Medium — needs validation that threshold doesn't cut legitimately relevant low-scoring entities. Should be tested across the full 19-question benchmark.
- **Expected impact:** For Q-L7, if `AGENT'S FEES` scores 3.5 and `Warranty` scores 0.2, the 10% threshold (0.35) would eliminate Warranty and several other noise entities. Could reduce 15 entities → 8-10, and chunks from ~42 → ~25.

#### 2c. RRF Score-Based Chunk Ranking for Route 3

**File:** `src/worker/hybrid_v2/pipeline/synthesis.py` → `synthesize_with_graph_context()`

Route 3 cannot use PPR score-weighted allocation (Phase 2a) because it doesn't use `_retrieve_text_chunks()` and PPR often doesn't run. However, Route 3 **does have ranking signals** that are currently ignored:

1. **RRF scores** from Stage 3.3.5 (BM25/Vector hybrid search) — each chunk has an RRF fusion score reflecting its lexical AND semantic relevance to the query
2. **relevance_score** from Stage 3.3 (enhanced graph context) — set by `_get_source_chunks_via_mentions()`: 1.0 if entity has MENTIONS edge to chunk, 0.5 otherwise

These scores exist on `SourceChunk.relevance_score` but are **never used for ordering**. The chunks are assembled in arbitrary `doc_groups` order.

**Fix:** Before the context assembly loop in `synthesize_with_graph_context()`, sort `graph_context.source_chunks` by `relevance_score` descending. Combined with the token budget (Phase 1b), this ensures the highest-relevance chunks fill the budget first and low-relevance chunks get cut.

```python
# In synthesize_with_graph_context(), before context assembly:
# Sort chunks by relevance score (RRF or MENTIONS-based) descending
graph_context.source_chunks.sort(
    key=lambda c: c.relevance_score, reverse=True
)
```

- **Effort:** ~5 lines
- **Risk:** Low — preserves all chunks, just reorders them. Token budget then truncates the tail.
- **Expected impact:** High-RRF chunks (strong lexical + semantic match) appear first in context. Combined with Phase 1b token budget, low-relevance graph-expansion chunks get dropped instead of burying the signal.

### Phase 3: Advanced (Higher Effort, Lower Marginal Impact)

#### 3a. Semantic Re-Ranking of Chunks by Query Similarity

For cases where PPR score-weighting (Phase 2a) still leaves too much noise — e.g., a high-PPR entity whose chunks are topically broad — add an optional semantic re-ranking pass.

**File:** `src/worker/hybrid_v2/pipeline/synthesis.py` → new method `_rerank_chunks_by_query()`

After `_retrieve_text_chunks()` returns, embed the query using `self.embed_model` (already available). Score each chunk's text against the query embedding via cosine similarity. Sort descending. The token budget (Phase 1b) then cuts the lowest-relevance chunks.

```python
async def _rerank_chunks_by_query(
    self, query: str, chunks: List[Dict]
) -> List[Dict]:
    """Re-rank chunks by semantic similarity to the query."""
    query_emb = await self.embed_model.embed(query)
    chunk_texts = [c.get("text", "")[:2000] for c in chunks]
    chunk_embs = await self.embed_model.embed_batch(chunk_texts)
    scored = []
    for chunk, emb in zip(chunks, chunk_embs):
        sim = cosine_similarity(query_emb, emb)
        chunk["_relevance_score"] = sim
        scored.append(chunk)
    scored.sort(key=lambda c: c["_relevance_score"], reverse=True)
    return scored
```

- **Effort:** ~40 lines + call site integration
- **Risk:** Medium — adds embedding API calls (1 + N batch, ~1-2s latency). Mitigate by batching and using first 2000 chars per chunk.
- **When needed:** Only when Phase 2a (PPR score-weighting) + Phase 1b (token budget) aren't sufficient. Likely useful for Route 4 comprehensive queries where coverage chunks dilute the context.
- **Toggle:** `SYNTHESIS_RERANK_ENABLED` env var (default off until needed).

#### 3b. Cross-Document Text Deduplication

After PPR score-weighting, detect near-duplicate chunks from different document copies (same normalized text, >95% Jaccard similarity). Keep only the highest-scored instance.

- **Effort:** ~60 lines new helper method
- **Risk:** Low — but marginal benefit if token budget (Phase 1b) already excludes duplicates
- **Expected impact:** For Q-L7, would reduce the 20 identical "ten percent" chunks to ~4 (one per unique text variant). More impactful for Route 3/4 where context is larger.

#### 3c. Adaptive Token Budget by Route

Different routes serve different query types:
- Route 2 (factual lookup): **12K tokens** should suffice
- Route 3 (thematic/cross-doc): **25K tokens** for multi-document synthesis
- Route 4 (multi-hop): **30K tokens** for complex reasoning chains

Pass `max_context_tokens` from orchestrator based on route, rather than one global default.

#### 3d. Prompt-Level Context Size Awareness

Add context token count to the synthesis prompt so the LLM knows how much material it's processing:

```
You are reviewing {n_chunks} text excerpts ({token_count} tokens) from {n_documents} documents.
Focus on the excerpts most relevant to the question. Some excerpts may be irrelevant.
```

#### 3e. Coverage Gap-Fill Budget for Route 4

For comprehensive queries, Stage 4.3.6 currently calls `get_all_sections_chunks(max_per_section=None)` — potentially the entire corpus. Add a `ROUTE4_COVERAGE_MAX_TOKENS` budget (default 10K) that caps how many coverage chunks are appended. Prioritize coverage chunks by semantic similarity to the query (already available — Stage 4.3.6 computes query embeddings for semantic coverage).

---

## 6. Implementation Priority & Sequencing

```
Week 1:  Phase 1a (chunk dedup) + Phase 1b (token budget)
         → Re-run Q-L7 with gpt-5.1 to validate
         → Full 19-question benchmark regression check

Week 2:  Phase 2a (PPR score-weighted chunk allocation) + Phase 2b (PPR threshold)
         → No new API calls — pure arithmetic on existing data
         → Re-run full benchmark, measure chunk/token savings + accuracy

Week 3:  Phase 3a-3e (stretch goals based on Week 2 results)
         → Semantic re-ranking only if PPR weighting proves insufficient
         → Coverage budget for Route 4 comprehensive queries
```

### Key Design Principle

Phases 1 and 2 require **zero additional API calls** — they use data already computed (PPR scores, chunk IDs). Phase 3 adds optional embedding calls only if needed. This keeps latency impact minimal.

### Rollback Strategy

All changes are behind configuration:
- `SYNTHESIS_MAX_CONTEXT_TOKENS` — set to 0 to disable budget
- `PPR_MIN_SCORE_RATIO` — set to 0.0 to disable threshold
- `PPR_WEIGHTED_ALLOCATION` — set to 0 to revert to uniform 12/entity
- `SYNTHESIS_RERANK_ENABLED` — flag to skip semantic re-ranking (Phase 3)
- `ROUTE4_COVERAGE_MAX_TOKENS` — set to 0 to disable coverage budget
- Cross-entity dedup has no downside → no toggle needed

---

## 7. Verification Criteria

### Immediate (after Phase 1)
- [ ] Q-L7 passes with gpt-5.1 (currently fails 3/3)
- [ ] Context size for Q-L7 drops from ~49K to ≤20K tokens
- [ ] gpt-4.1 maintains 100% (19/19) on full benchmark
- [ ] No new failures introduced on any route

### After Phase 2
- [ ] Chunks related to "AGENT'S FEES" and "fee/commission" rank in top 5 for Q-L7
- [ ] Noise entities (Warranty, DISCLAIMER) produce 0 chunks in final context
- [ ] Average context size across all 19 questions drops by ≥50%
- [ ] Route 3 and Route 4 context sizes measured and documented

### Performance
- [ ] Re-ranking adds no more than 2s latency (batch embedding)
- [ ] Token budget check adds negligible latency (<10ms)
- [ ] PPR threshold adds negligible latency (Python post-filter)

---

## 8. Appendix: Raw Data

### Q-L7 gpt-5.1 Response (Run 0)
```
## Summary

The requested information was not found in the available documents. While the
agreement clearly states a "fee/commission of twenty five percent (25%) of the
gross revenues" for short-term/vacation rentals (reservations of less than 180
days), the specific fee/commission percentage or amount "for long term leases
(leases of more than 180 days)" is not shown; the text around that phrase is
truncated and does not include the actual number.
```

### Q-L7 gpt-4.1 Response (Run 0)
```
## Summary

For **long-term leases (leases of more than 180 days)**, the Agent's
fee/commission is specified as "a fee/commission of ten percent (10%) of the
gross revenues for management services". This 10% commission applies only to
long-term leases, as distinct from the higher commission rate for short-term
or vacation rentals.
```

### Context Size Measurement (Q-L7)

| Stage | Chunks | Unique Chunks | Tokens (est.) |
|-------|--------|--------------|---------------|
| Pre-diversification (13 entities) | 737 rows | 276 | ~273,687 |
| Post-diversification (caps applied) | — | 42 | ~49,042 |
| With "ten percent" in text | — | 20 | — |
| Without "ten percent" (noise) | — | 22 | — |

### Evidence Entities (from gpt-5.1 Q-L7 benchmark run)

```
1.  PROPERTY MANAGEMENT AGREEMENT    (score: high)
2.  Warranty                         (score: medium — NOISE)
3.  AGENCY START-UP FEE              (score: medium)
4.  other features of the home       (score: low — NOISE)
5.  Walt Flood Realty                 (score: medium)
6.  Pacific View Retreat             (score: medium)
7.  456 Palm Tree Avenue, HI 96815  (score: medium)
8.  DISCLAIMER OF GUARANTEES         (score: low — NOISE)
9.  AGENCY                           (score: low — NOISE)
10. RESPONSIBILITIES OF AGENT        (score: low — NOISE)
11. RESPONSIBILITIES OF OWNER        (score: low — NOISE)
12. AGENT'S FEES                     (score: high — KEY ENTITY)
13. warranty period (term)           (score: low — NOISE)
14. TERM                             (score: low)
15. limited warranty term            (score: low — NOISE)
```

Only entities **1, 3, 5, 6, 7, 12** have plausible relevance. Entities **2, 4, 8, 9, 10, 11, 13, 14, 15** are noise from PPR graph expansion.
