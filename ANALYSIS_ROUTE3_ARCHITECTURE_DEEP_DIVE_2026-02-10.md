# Route 3 Architecture Deep Dive — Design Review and Denoising Strategy

**Date:** 2026-02-10  
**Objective:** Review Route 3 (Global Search) end-to-end architecture, assess whether it's truly LazyGraphRAG, identify fundamental design flaws, evaluate each processing step's contribution vs. noise, and propose specific improvements to reduce context noise before synthesis.  
**Key files:**  
- Orchestrator: `src/worker/hybrid_v2/orchestrator.py` L486–L1200  
- Synthesis: `src/worker/hybrid_v2/pipeline/synthesis.py` L323 (`synthesize_with_graph_context`)  
- Enhanced Retriever: `src/worker/hybrid_v2/pipeline/enhanced_graph_retriever.py` L711 (`get_full_context`)  
- Community Matcher: `src/worker/hybrid_v2/pipeline/community_matcher.py` L166 (`match_communities`)  
- Hub Extractor: `src/worker/hybrid_v2/pipeline/hub_extractor.py` L69 (`extract_hub_entities`)  
- Architecture Design: `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md`  
- Prior analysis: `ANALYSIS_CONTEXT_OVERRETRIEVAL_ALL_ROUTES_2026-02-08.md`, `ANALYSIS_CONTEXT_QUALITY_AND_DEDUP_2026-02-08.md`

---

## 1. Is Route 3 Actually LazyGraphRAG?

### 1.1 What Is LazyGraphRAG (the paper)?

Microsoft's LazyGraphRAG (2024) is a design principle with two key ideas:

1. **Eager index-time structural work:** Run Louvain community detection on the entity graph → produce community partitions → generate LLM summaries for each community → embed those summaries. This is the "expensive upfront" phase.
2. **Lazy query-time resolution:** At query time, match the query embedding against community summary embeddings → retrieve the top-k community summaries → feed them (not raw chunks) to the LLM. The LLM synthesizes from **high-level community summaries**, not from raw source text.

The critical design insight of LazyGraphRAG is: **the LLM sees community summaries, not chunks.** Summaries are pre-distilled at index time — they're already clean, deduplicated, and coherent. The synthesis LLM reasons over condensed thematic representations.

### 1.2 What Route 3 Actually Does

Route 3 borrows the **top half** of LazyGraphRAG (community matching, hub entity extraction) but then **abandons the LazyGraphRAG synthesis model entirely**:

```
LazyGraphRAG (paper):
  Query → Community Match → Retrieve Community Summaries → LLM synthesizes from summaries
                                                            ↑ clean, pre-distilled

Route 3 (our code):
  Query → Community Match → Hub Entities → MENTIONS chunk fetch → BM25+Vector chunk fetch
        → [PPR optional] → Coverage gap fill → Pass ALL raw chunks to LLM
                                                ↑ noisy, duplicated, unfiltered
```

**Verdict: Route 3 is NOT LazyGraphRAG.** It uses LazyGraphRAG's community matching as a seed discovery mechanism, then pivots to a completely different retrieval-and-synthesis pattern that:
- Retrieves raw `TextChunk` text via MENTIONS edges (Stage 3.3)
- Retrieves more raw chunks via BM25+Vector RRF (Stage 3.3.5)
- Merges both chunk sets with only chunk-ID dedup
- Passes the full, untruncated, unfiltered chunk text to the synthesis LLM
- Has **no token budget, no content filtering, no re-ranking by query relevance**

The system is more accurately described as: **"Community-seeded entity expansion + hybrid chunk retrieval → unfiltered LLM synthesis"** — a custom hybrid that uses community matching for seeding and HippoRAG PPR for optional enrichment, but synthesizes from raw chunks like a basic RAG system.

### 1.3 Why This Matters

LazyGraphRAG's power comes from **pre-distilled summaries** being the input to synthesis. By abandoning summaries and falling back to raw chunks, Route 3 inherits all the noise problems of naive chunk-based RAG:
- Duplicate chunks (56.5% measured)
- Form labels, bare headings, signature blocks
- No content quality filtering
- No token budget — context can be 80K+ chars
- No re-ranking by query relevance

---

## 2. The Full Pipeline: Step-by-Step Architecture Trace

```
Query: "What are the main compliance risks in our portfolio?"
  │
  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3.1: Community Matching                                       │
│ community_matcher.match_communities(query, top_k=3)                │
│                                                                     │
│ INPUT:  query embedding                                            │
│ PROCESS: cosine similarity vs Community node embeddings (Neo4j)    │
│ OUTPUT: 3 community dicts (id, title, summary, entity_names)       │
│                                                                     │
│ NOISE CONTRIBUTION: LOW ✅                                          │
│ This is clean — semantic matching against pre-computed summaries.   │
│ Returns community metadata, not chunks.                            │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3.2: Hub Entity Extraction                                    │
│ hub_extractor.extract_hub_entities(communities, top_k_per_community=10)│
│                                                                     │
│ INPUT:  3 communities                                              │
│ PROCESS: For each community, get entity_names from community data  │
│          or query Neo4j for highest-degree entities                 │
│          Dedup, filter out chunk-ID artifacts                      │
│ OUTPUT: up to 30 hub entity names (unique, filtered)               │
│                                                                     │
│ NOISE CONTRIBUTION: MODERATE ⚠️                                    │
│ top_k_per_community=10 is aggressive. 3 communities × 10 = 30     │
│ hub entities. Many of these will be tangential to the query.       │
│ There's NO query-relevance filtering — all entities in the         │
│ community are treated equally, regardless of whether they're       │
│ relevant to the specific question asked.                           │
│                                                                     │
│ Example: Community "Contract Terms" may include entities for       │
│ payment, termination, insurance, liability — but query only asks   │
│ about "compliance risks". All 10 entities are kept.                │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3.3: Enhanced Graph Context (CHUNK SOURCE #1)                 │
│ enhanced_retriever.get_full_context(                               │
│   hub_entities,                                                    │
│   max_chunks_per_entity=3, max_relationships=30,                   │
│   section_diversify=True, max_per_section=3, max_per_document=6)   │
│                                                                     │
│ INPUT:  30 hub entity names                                        │
│ PROCESS:                                                           │
│   In parallel:                                                     │
│   a) _get_source_chunks_via_mentions(): For EACH of 30 entities,   │
│      query (TextChunk)-[:MENTIONS]->(Entity) → up to 3 chunks each │
│   b) _get_relationships(): Get up to 30 Entity→Entity relationships│
│   c) _get_entity_descriptions(): Get descriptions for hub entities │
│   Then: _diversify_chunks_by_section() → cap per section/doc       │
│                                                                     │
│ OUTPUT:                                                            │
│   source_chunks: ~20-40 unique chunks (post-diversification)       │
│   relationships: up to 30                                          │
│   entity_descriptions: up to 30                                    │
│                                                                     │
│ NOISE CONTRIBUTION: HIGH ❌                                         │
│                                                                     │
│ Problem 1 — NO CROSS-ENTITY DEDUP IN CYPHER QUERY:                │
│ The Cypher query UNWINDs entity_names and collects chunks per      │
│ entity independently. If Entity A and Entity B are both MENTIONED  │
│ in chunk X, chunk X appears TWICE. Section diversification dedup   │
│ may help but is section-based, not chunk-ID-based.                 │
│                                                                     │
│ Problem 2 — NO QUERY RELEVANCE:                                   │
│ Chunks are selected by graph structure (which entities they        │
│ MENTION), not by semantic relevance to the query. A chunk about    │
│ "payment terms" mentioning entity "contract" is retrieved even     │
│ when asking about "compliance risks".                              │
│                                                                     │
│ Problem 3 — FORM LABELS AND NOISE CHUNKS:                         │
│ Any TextChunk that happens to MENTION a hub entity is retrieved,   │
│ including chunks that are pure form labels ("Pumper's Name:"),     │
│ signature blocks, or bare headings.                                │
│                                                                     │
│ Problem 4 — 30 ENTITIES × 3 CHUNKS = 90 PRE-DIVERSIFICATION:     │
│ Even after diversification, the chunk set is based on entity       │
│ connectivity, not query relevance.                                 │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3.3.5: BM25 + Vector RRF Hybrid (CHUNK SOURCE #2)            │
│ _search_chunks_cypher25_hybrid_rrf(                                │
│   query, embedding, top_k=20, vector_k=30, bm25_k=30, rrf_k=60)  │
│                                                                     │
│ INPUT:  query text + query embedding                               │
│ PROCESS: Single Cypher query running both BM25 and vector search   │
│          RRF fusion of both rankings                               │
│          Document diversity enforcement (max_per_doc=2, min_docs=3)│
│          Dedup against existing graph_context.source_chunks by ID  │
│ OUTPUT: up to 20 additional chunks                                 │
│                                                                     │
│ NOISE CONTRIBUTION: MODERATE-LOW ⚠️                                │
│                                                                     │
│ This is the BEST retrieval step in the pipeline.                  │
│ - It's query-relevant (BM25 matches query terms, vector matches   │
│   query semantics)                                                 │
│ - It has document diversity controls                              │
│ - It has RRF score ranking                                        │
│                                                                     │
│ However:                                                           │
│ - No content quality filtering (form labels still pass through)   │
│ - max_per_doc=2 is restrictive for rich documents                 │
│ - RRF scores are not used for downstream re-ranking               │
│ - The 20 chunks are merged into the existing set without any      │
│   comparative re-ranking of the combined pool                     │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3.4: HippoRAG PPR (CONDITIONAL — usually SKIPPED)            │
│                                                                     │
│ IF fast_mode=ON (default) AND query has no relationship keywords   │
│ AND query has <2 proper nouns → SKIP PPR                           │
│                                                                     │
│ WHEN EXECUTED:                                                     │
│   tracer.trace(query, seeds=hub+related[:10], top_k=20)           │
│   → evidence_nodes (entity, score) pairs                          │
│   BUT: evidence_nodes ONLY used for metadata, NOT for chunk       │
│   retrieval. Chunks are already determined.                        │
│                                                                     │
│ NOISE CONTRIBUTION: N/A (usually skipped) or WASTED COMPUTE       │
│ When PPR runs, its output is NEVER used to filter, re-rank, or    │
│ select chunks. The evidence_nodes are stored in metadata.          │
│ This is a complete architectural dead-end.                         │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3.4.1: Coverage Gap Fill (only for coverage_mode queries)     │
│                                                                     │
│ IF coverage_mode (detected by regex):                              │
│   Get all documents → find which are missing from source_chunks    │
│   → add 1 lead chunk per missing document                         │
│                                                                     │
│ NOISE CONTRIBUTION: LOW for coverage queries ✅                     │
│ This adds targeted content only for missing documents.             │
│ Appropriate for "summarize each document" style queries.           │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3.5: Synthesis (synthesize_with_graph_context)                │
│                                                                     │
│ INPUT: ALL source_chunks (40-70), relationships (30), entity desc  │
│                                                                     │
│ PROCESS:                                                           │
│   1. Group chunks by doc_id                                        │
│   2. For EACH chunk: append FULL text with citation marker         │
│      → NO truncation, NO filtering, NO dedup at this stage        │
│   3. Add relationship context (up to 30 relationships)             │
│   4. Add entity descriptions (up to 10)                            │
│   5. Concatenate everything → full_context                         │
│   6. Send to LLM with prompt                                      │
│                                                                     │
│ NOISE CONTRIBUTION: CRITICAL ❌❌                                   │
│                                                                     │
│ This is where ALL the noise from previous stages converges:        │
│ - No dedup: Stage 3.3 + 3.3.5 can contribute the same chunk      │
│   (should be caught by ID dedup in 3.3.5, but Stage 3.3's own    │
│   cross-entity duplicates survive)                                 │
│ - No content filter: form labels, bare headings pass through      │
│ - No token budget: 50-70 chunks × ~1150 tokens = 57-80K tokens   │
│ - No re-ranking: chunks from entity traversal (irrelevant) are    │
│   mixed with query-relevant BM25 hits without distinction         │
│ - No relevance scoring: all chunks treated equally in the prompt  │
│ - relationships and entity_descriptions added ON TOP of chunks    │
│   (~2-3K extra tokens)                                            │
│                                                                     │
│ MEASURED: 56.5% of chunks are exact duplicates.                   │
│ MEASURED: 80K+ chars per query sent to synthesis LLM.             │
│ MEASURED: "pumper" appears 26× as form labels, missed by 5/5 LLMs│
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Fundamental Design Flaws

### Flaw 1: Abandoned the LazyGraphRAG Insight (Community Summaries → Raw Chunks)

The most fundamental flaw is that Route 3 **starts** with LazyGraphRAG's community matching but then **abandons** its synthesis model. Instead of synthesizing from community summaries (which are clean, deduplicated, and thematic), it:
1. Uses communities only to find hub entities
2. Uses hub entities only to find TextChunks via MENTIONS
3. Adds more raw chunks via BM25+Vector
4. Passes all raw chunks (unfiltered) to the LLM

**This means the community summaries — the most expensive and highest-quality indexed artifacts — are never seen by the synthesis LLM.** They serve only as indirect seed selectors.

**Fix:** Consider a tiered synthesis approach:
- **Tier 1:** Pass community summaries to the LLM as "executive overview"
- **Tier 2:** Pass re-ranked, deduplicated chunks as "supporting evidence"
- This would give the LLM both thematic structure AND evidentiary detail

### Flaw 2: Two Independent Chunk Sources, One Blind Merge

Chunks come from two independent sources with different quality profiles:

| Source | Relevance basis | Quality |
|--------|----------------|---------|
| Stage 3.3 (MENTIONS) | Graph structure (entity connectivity) | Low — not query-relevant, includes form labels |
| Stage 3.3.5 (BM25+RRF) | Query text & semantics | Higher — directly query-relevant |

These two chunk sets are **merged blindly** — Stage 3.3.5 chunks are appended to the existing list with only chunk-ID dedup. There is:
- No comparative scoring across sources
- No preference for query-relevant chunks over graph-structural chunks
- No unified re-ranking of the combined pool

**Fix:** After merging, apply a unified re-ranking step:
1. Score all chunks by query-embedding cosine similarity
2. Or use RRF scores from 3.3.5 and entity-relevance from 3.3 for a unified rank
3. Take top-N from the combined ranked list

### Flaw 3: No Token Budget Anywhere

This is the ONLY route in the system with zero token budget enforcement. Route 2/4 also lack budgets but Route 3's chunk count is the highest due to two independent retrieval sources plus coverage gap-fill.

- **Stage 3.3:** Up to 90 chunks pre-diversification, ~20-40 post
- **Stage 3.3.5:** Up to 20 more chunks
- **Stage 3.4.1:** 1 per missing document (coverage mode)
- **Synthesis:** All chunks passed verbatim, full text, no truncation

With 5 documents and typical parameters: **50-70 chunks × ~1,150 tokens = 57K–80K tokens** before entity/relationship/description context is added.

**Fix:** Add token budget enforcement in `synthesize_with_graph_context()` before building the prompt. Budget of 32K-48K tokens for context, with re-ranked chunks filling the budget.

### Flaw 4: PPR Is Architecturally Dead

PPR (Stage 3.4) in Route 3 is a vestigial organ:
- In fast_mode (default ON), it's skipped for ~90% of thematic queries
- When it runs, its output (`evidence_nodes`) is **never used for chunk retrieval or re-ranking**
- evidence_nodes are only stored as metadata in the response
- Chunks are already determined by Stages 3.3 + 3.3.5 BEFORE PPR runs

This is fundamentally different from Routes 2/4 where PPR drives entity discovery. In Route 3, PPR is a post-hoc decoration that consumes compute without influencing the result.

**Fix:** Either:
- **Remove PPR from Route 3** (simplify, save latency), or
- **Move PPR before chunk retrieval** and use PPR scores to select/weight which hub entities get chunk expansion in Stage 3.3

### Flaw 5: Hub Entity Count Is Blind to Query Scope

`top_k_per_community=10`, with 3 communities, means up to 30 hub entities. This is a **fixed number regardless of query specificity:**
- "What are the termination clauses?" → 30 hub entities (most irrelevant)
- "Summarize all documents" → 30 hub entities (need breadth)

The fixed count creates two failure modes:
- **Too many for focused queries:** 30 entities means 90 chunk lookups, most irrelevant
- **Not diverse enough for broad queries:** 10 per community may miss entities in under-represented documents

**Fix:** Scale hub entity count by query breadth:
- Focused queries (few expected themes): 3-5 hub entities
- Broad thematic queries: 15-20 hub entities
- Coverage queries: use coverage gap-fill, not more hub entities

### Flaw 6: No Content Quality Gate Before Synthesis

No step in the pipeline filters chunks by content quality. All of the following pass through to the LLM:
- `Date:` (standalone form field) — appears up to 12× per query
- `Pumper's Name:` (empty form label) — 26× in Q-G6
- `4. Customer Default` (bare heading, no body text) — 1× in Q-G5
- Signature blocks, page numbers, metadata fragments

**Fix:** Add content quality filter before synthesis:
```python
def _is_low_content(chunk_text: str) -> bool:
    text = chunk_text.strip()
    if len(text) < 20 and text.endswith(':'):  # Form labels
        return True
    if len(text) < 40 and not any(c in text for c in '.!?'):  # Bare headings
        return True
    if len(text) < 15:  # Tiny fragments
        return True
    return False
```

---

## 4. Step-by-Step Evaluation: Contribution vs. Noise

| Stage | Purpose | Contributes to Answer? | Contributes to Noise? | Verdict |
|:------|:--------|:----------------------|:---------------------|:--------|
| **3.1 Community Matching** | Find thematic clusters | ✅ Yes — identifies relevant topic areas | ❌ No — returns metadata only | **KEEP ✅** Good seed discovery. But summaries should also go to the LLM. |
| **3.2 Hub Entity Extraction** | Find seed entities | ⚠️ Partially — provides graph entry points | ⚠️ Moderate — 30 indiscriminate entities | **KEEP but NARROW** — reduce top_k or add query-relevance filter |
| **3.3 MENTIONS Chunk Fetch** | Get chunks for hub entities | ⚠️ Partially — some chunks are relevant | ❌ HIGH — graph-structural, not query-relevant, duplicates | **RETHINK** — this is the primary noise source |
| **3.3.5 BM25+Vector RRF** | Direct query retrieval | ✅ Yes — strongest relevance signal | ⚠️ Low — no content filter | **KEEP ✅** This should be the PRIMARY retrieval, not secondary |
| **3.4 PPR** | Detail recovery | ❌ No — output unused | N/A — usually skipped | **REMOVE or REPOSITION** — dead code in current flow |
| **3.4.1 Coverage Gap Fill** | Ensure all docs represented | ✅ For coverage queries | ⚠️ Adds noise for non-coverage queries | **KEEP for coverage_mode only ✅** |
| **3.5 Synthesis** | Generate answer | ✅ Core function | ❌ CRITICAL — no dedup, no budget, no filter | **FIX** — add distillation before LLM call |

---

## 5. Root Cause Hierarchy of Noise

Ranked by impact on synthesis quality:

### Priority 1: Context Assembly Has No Processing (synthesis.py L323-600)

The `synthesize_with_graph_context()` method does **zero processing** between receiving chunks and sending them to the LLM. It's a concatenation function, not a distillation function. This is the #1 noise amplifier because every upstream noise source flows through unchecked.

### Priority 2: MENTIONS Chunk Fetch Is Graph-Structural, Not Query-Relevant (Stage 3.3)

Stage 3.3 fetches chunks based on **which entities they mention**, not based on **whether they answer the query**. A chunk about "Pumper's Name" is retrieved because it mentions "holding tank contract" entity, not because it answers "What are the key parties?". This is the #1 noise generator.

### Priority 3: No Cross-Source Re-Ranking After Merge

After Stage 3.3 and 3.3.5, we have a pool of 40-60 chunks from two sources with different relevance profiles. Merging them by append (with only ID dedup) means:
- Graph-structural chunks (low relevance) are mixed with query-relevant chunks (high relevance)
- The LLM sees them as equally authoritative
- No signal tells the LLM which chunks are more relevant

### Priority 4: Excessive Hub Entity Count

30 hub entities × 3 chunks/entity = 90 chunk lookups. Even after diversification, this produces 20-40 chunks based solely on entity connectivity. For a focused query, most of these are noise.

---

## 6. Proposed Improvement Plan

### Phase 0: Quick Wins (immediate, ~100 lines)

**0a. Exact chunk dedup in `synthesize_with_graph_context()`**
```python
# Before building context, dedup by chunk text hash
seen_hashes = set()
deduped_chunks = []
for chunk in graph_context.source_chunks:
    h = hash(chunk.text.strip())
    if h not in seen_hashes:
        seen_hashes.add(h)
        deduped_chunks.append(chunk)
graph_context.source_chunks = deduped_chunks
```
Expected impact: -56.5% context size (measured)

**0b. Low-content chunk filter**
```python
def _is_noise_chunk(text: str) -> bool:
    t = text.strip()
    if len(t) < 20:  # Tiny fragments
        return True
    if len(t) < 40 and t.endswith(':'):  # Form labels
        return True
    if len(t) < 50 and not any(c in t for c in '.!?,;'):  # Bare headings
        return True
    return False
```
Expected impact: removes ~5-10% of remaining unique chunks (form labels, bare headings)

### Phase 1: Structural Improvements (~200 lines)

**1a. Token budget enforcement in synthesis**
- Set budget (e.g., 40K tokens for context)
- After dedup + filter, if chunks exceed budget, truncate from bottom of list
- This requires re-ranking first (see 1b)

**1b. Unified re-ranking after merge**
- After Stage 3.3.5, compute query-embedding cosine similarity for ALL chunks in the combined pool
- Sort by similarity score
- Keep top-N that fit within token budget
- This naturally prioritizes BM25+Vector chunks (query-relevant) over MENTIONS chunks (graph-structural)

**1c. Inject community summaries into synthesis context**
- Community summaries are high-quality, pre-distilled thematic context
- Add them as a "## Thematic Overview" section at the top of the synthesis prompt
- This gives the LLM the LazyGraphRAG insight: thematic structure before evidence chunks

### Phase 2: Architectural Refinements (~300 lines)

**2a. Reduce hub entity count and add query-relevance filter**
- Reduce top_k_per_community from 10 to 5
- After extraction, compute embedding similarity between query and each entity name
- Keep top-10 most query-relevant entities (instead of all 30)

**2b. Make Stage 3.3 (MENTIONS) subordinate to Stage 3.3.5 (BM25+RRF)**
- Execute BM25+RRF FIRST (it's query-relevant)
- Then use Stage 3.3 only to ENRICH with graph context for entities found in BM25 results
- This reverses the current priority: query-relevant chunks first, graph enrichment second

**2c. Remove PPR from Route 3 (or make it useful)**
- Option A: Remove entirely — it's dead code in the current flow
- Option B: Move before chunk retrieval, use PPR scores to weight which entities get chunk expansion

### Phase 3: Advanced Distillation (~400 lines)

**3a. Near-duplicate merging**
- Jaccard similarity > 0.9 → keep longest variant
- Handles OCR variations of the same content

**3b. Heading-body consolidation**
- If a chunk is a bare heading (e.g., "4. Customer Default"), search for adjacent chunks that contain the body text
- Merge heading + body into a single richer chunk

**3c. Form-label entity extraction**
- Parse form labels ("Pumper's Name:", "Contractor's Signature:") → extract entity role
- Insert a structured "## Named Party Roles" section in the synthesis prompt

---

## 7. Proposed Architecture (Post-Improvement)

```
Query
  │
  ▼
Stage 3.1: Community Matching (unchanged)
  │ → 3 communities + summaries
  ▼
Stage 3.2: Hub Entity Extraction (NARROWED)
  │ → top_k_per_community=5, then filter by query-relevance
  │ → 10-15 query-relevant hub entities (was 30)
  ▼
Stage 3.3.5: BM25+Vector RRF (PROMOTED TO PRIMARY RETRIEVAL)
  │ → 20 query-relevant chunks with RRF scores
  ▼
Stage 3.3: MENTIONS Chunk Fetch (DEMOTED TO ENRICHMENT)
  │ → For entities found in Stage 3.3.5 results,
  │   add graph-adjacent chunks for richer context
  │ → ~10-15 additional chunks (was 20-40)
  ▼
Stage 3.4.1: Coverage Gap Fill (unchanged, coverage_mode only)
  │
  ▼
NEW: Context Distillation
  │ 1. Exact dedup (hash-based)
  │ 2. Low-content filter (form labels, bare headings, tiny fragments)
  │ 3. Unified re-ranking (query-embedding cosine similarity)
  │ 4. Token budget enforcement (top-N within 40K tokens)
  │ 5. Community summaries prepended as thematic overview
  ▼
Stage 3.5: Synthesis
  │ LLM receives:
  │   - Community summaries (thematic context, ~2K tokens)
  │   - 25-35 high-quality, deduplicated, re-ranked chunks (~30K tokens)
  │   - Relationship context (up to 30 relationships, ~2K tokens)
  │   - Entity descriptions (up to 10, ~1K tokens)
  │   - Total: ~35K tokens (was 57-80K)
  ▼
Response
```

---

## 8. Expected Impact

| Metric | Current | After Phase 0 | After Phase 1 | After Phase 2 |
|--------|---------|---------------|---------------|---------------|
| Chunks to synthesis | 50-70 | 25-35 | 25-35 (ranked) | 20-30 (targeted) |
| Context tokens | 57K-80K | 30K-40K | 30K-40K | 25K-35K |
| Duplicate rate | 56.5% | ~0% | ~0% | ~0% |
| Token cost per query | $0.08-0.12 | $0.04-0.06 | $0.04-0.06 | $0.03-0.05 |
| Theme coverage (avg) | ~80% | ~82% (dedup) | ~88% (re-ranked) | ~92% (targeted) |
| Q-G5 `default` coverage | 63% | 63% | ~75% (heading merge) | ~85% |
| Q-G6 `pumper` coverage | 63% | 63% | ~70% (prompt) | ~80% (entity extract) |
| Latency (synthesis) | 6-20s | 4-12s | 4-12s | 3-10s |

---

## 9. Summary of Findings

1. **Route 3 is NOT LazyGraphRAG.** It borrows community matching for seed discovery but abandons the core LazyGraphRAG insight (synthesize from summaries). It synthesizes from raw, unfiltered chunks.

2. **The most fundamental design flaw** is that there is NO processing between retrieval and synthesis. The context assembly is a pure concatenation function. Every upstream noise source (duplicates, form labels, irrelevant graph-structural chunks) flows straight to the LLM.

3. **Stage 3.3 (MENTIONS chunk fetch)** is the primary noise generator — it retrieves chunks based on graph structure, not query relevance. This made sense when Route 3 was designed as "graph-enriched retrieval" but it produces low-quality context for thematic queries.

4. **Stage 3.3.5 (BM25+Vector RRF)** is the strongest retrieval step but is treated as secondary enrichment rather than the primary retrieval source.

5. **PPR (Stage 3.4)** is architecturally dead in Route 3 — its output is never used for chunk selection or re-ranking.

6. **Quick wins are available:** Exact dedup alone would reduce context by ~56%, and low-content filtering would remove another ~5-10%. These require ~100 lines of code in `synthesize_with_graph_context()`.

7. **The biggest architectural improvement** would be to: (a) promote BM25+RRF to primary retrieval, (b) add unified re-ranking with token budget, and (c) inject community summaries into synthesis context. This would move Route 3 closer to the LazyGraphRAG ideal while keeping its hybrid retrieval advantages.
