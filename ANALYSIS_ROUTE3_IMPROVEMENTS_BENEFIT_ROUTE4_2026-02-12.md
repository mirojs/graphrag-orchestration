# How Route 3 Improvements Benefit Route 4

**Date:** 2026-02-12  
**Context:** Route 3 v2 (Phase B: sentence-based entity extraction + clean edges) impacts Route 4 through 5 concrete code paths.

---

## TL;DR

The Route 3 improvements are **more valuable to Route 4 than to Route 3 itself**. Route 3's map-reduce
rewrite (Phase A) doesn't depend on entity graph quality at all — it uses community summaries. Route 4's 
semantic beam search traverses the entity graph at every hop. Every noise entity, every false RELATED_TO 
edge, every duplicate MENTIONS link directly degrades Route 4's beam quality. Cleaning the graph at 
source is effectively a Route 4 precision upgrade disguised as a Route 3 project.

---

## 5 Code Paths Where Phase B Directly Improves Route 4

### 1. Seed Resolution — `get_entities_by_names()` (async_neo4j_service.py L186-395)

**Current problem:** Route 4 decomposes the query into sub-questions via LLM, then calls 
`disambiguator.disambiguate()` → `get_entities_by_names()` with a 6-layer matching cascade:
exact → alias → KVP → substring → token overlap → vector similarity.

With chunk-based entity extraction, the entity graph is polluted with noise entities extracted from 
form labels, metadata headers, and overlapping chunk boundaries. This causes:
- **False positives in substring/token matching** — "Pumper's Name" entity matches seed "Name"
- **Alias pollution** — generic aliases from `_generate_generic_aliases()` create false matches
- **Diluted vector similarity** — noise entities with embeddings compete with real entities

**After Phase B:**
- Sentence classifier (`_classify_sentence()`) filters out noise/metadata before entity extraction
- `_generate_generic_aliases()` is **removed** (B.4) — no more false alias matches  
- `_nlp_seed_entities()` regex fallback is **removed** (B.4) — no more heuristic noise entities
- **Result:** Seed resolution becomes dramatically more precise. Fewer false seed → fewer wasted beam search hops.

### 2. Semantic Beam Search — `semantic_multihop_beam()` (async_neo4j_service.py L1286-1510)

**Current problem:** At each hop, the beam expands all neighbors connected by any edge type 
(excluding MENTIONS) and prunes by `vector.similarity.cosine(entity.embedding, query_embedding)`.

When the entity graph has false RELATED_TO edges (from chunk-level co-occurrence of unrelated entities), 
the beam wastes slots on topically irrelevant neighbors. With beam_width=10 and 3 hops, a single false 
edge at hop 0 can cascade into 10 false candidates at hop 1 and 100 at hop 2.

**After Phase B:**
- RELATED_TO edges are now **sentence-scoped co-occurrence** (B.3) — two entities connected only if 
  they appear in the same sentence, not the same 512-token chunk
- This eliminates false co-occurrences caused by:
  - Chunk overlap (64 tokens) creating duplicate entity pairs across adjacent chunks  
  - Distant mentions within a 512-token window (e.g., header entity + footer entity)
- **Result:** Each beam hop encounters fewer false neighbors → the top-10 candidates per hop are 
  more likely to be semantically relevant → better evidence at synthesis.

### 3. PPR Section-Based Hops — Path 2 in `_build_ppr_query_with_section_graph()` (async_neo4j_service.py L780-800)

**Current problem:** PPR Path 2 traverses `seed Entity ← MENTIONS ← Chunk → IN_SECTION → Section → 
SEMANTICALLY_SIMILAR → Section → IN_SECTION → Chunk → MENTIONS → neighbor Entity`. This path is 
available to Route 4 via its fallback and is used by Route 2.

The query hardcodes `(chunk:Chunk OR chunk:TextChunk OR chunk:__Node__)` at both ends. With sentence-based 
MENTIONS, chunks no longer have MENTIONS edges — sentences do.

**After Phase B — BREAKING CHANGE requires update:**
Path 2's Cypher must be updated:
```cypher
-- Before:
MATCH (chunk)-[:MENTIONS]->(seed)
WHERE chunk.group_id = group_id
    AND (chunk:Chunk OR chunk:TextChunk OR chunk:`__Node__`)

-- After:
MATCH (src)-[:MENTIONS]->(seed)
WHERE src.group_id = group_id
    AND (src:Sentence OR src:TextChunk)
OPTIONAL MATCH (src)-[:PART_OF]->(parent_chunk:TextChunk {group_id: group_id})
WITH seed, COALESCE(parent_chunk, src) AS chunk, ...
```

This affects **PPR Path 2 and Path 4** in `_build_ppr_query_with_section_graph()` (L780-800, L842).
Route 4's primary path (`semantic_multihop_beam`) is unaffected because it only traverses Entity-Entity 
edges and explicitly filters `type(r) <> 'MENTIONS'`. But the **PPR fallback** at tracing.py L397 
(`return await self.trace(...)`) would break.

**Action needed:** Update PPR section-based Cypher to handle `Sentence → PART_OF → TextChunk` — 
this is the same pattern already done in `text_store.py` (L361-375). Should be added to Phase C.

### 4. Chunk Retrieval at Synthesis — `_retrieve_text_chunks()` (synthesis.py L1076+) via `text_store.py` (L361-420)

**Current problem:** After beam search returns ranked entities, synthesis calls 
`_retrieve_text_chunks()` which queries `text_store.get_chunks_for_entities_batch_sync()`. This traverses 
`MATCH (src)-[:MENTIONS]->(e)` to find text content for each evidence entity.

With chunk-based MENTIONS:
- **56.5% chunk duplication** — overlapping chunks create multiple MENTIONS edges to the same entity
- `limit_per_entity=12` is uniformly applied regardless of entity importance
- PPR scores are discarded (all entities get equal budgets)

**After Phase B:**
- `text_store.py` already handles both schemas (L361: `src:Sentence OR src:TextChunk`)
- Sentence-based MENTIONS are **1:1** — each entity-sentence pair is deterministic, no overlap inflation
- **Result:** The 12-chunk-per-entity budget retrieves 12 *unique* content windows instead of 
  ~5-6 unique + 6-7 duplicates. Effective context doubles without any code change in Route 4.

### 5. Entity Quality → Confidence Metrics — `_compute_subgraph_confidence()` (route_4_drift.py L540-600)

**Current problem:** Route 4 computes confidence based on entity diversity and evidence satisfaction 
ratio. When noise entities inflate the seed count, metrics are misleading:
- `entity_diversity = unique_entities / total_entities` is artificially high (many unique noise entities)
- `satisfied_ratio` is artificially low (noise entities have 0 matching evidence)
- The confidence loop (Stage 4.3.5) may trigger unnecessary gap-fill iterations

**After Phase B:**
- Fewer noise entities → `disambiguate()` returns cleaner seed lists
- Evidence satisfaction improves (real entities have real evidence)
- Confidence scores become meaningful, not noise-inflated
- **Result:** Confidence loop terminates earlier → fewer redundant LLM calls → lower latency.

---

## Quantified Impact Estimate

| Metric | Current (chunk-based) | After Phase B (sentence-based) | Mechanism |
|--------|----------------------|-------------------------------|-----------|
| Seed resolution false positives | ~15-25% (estimate from alias/substring paths) | <5% | Alias removal + classifier |
| RELATED_TO edge noise | Unknown, likely 30-50% false co-occurrences | ~5% (sentence-scoped) | Sentence co-occurrence |
| Chunk duplication in synthesis | 56.5% (measured) | ~0% (1:1 MENTIONS) | Deterministic sentence links |
| Effective context per entity | ~5-6 unique chunks / 12 retrieved | ~12 unique / 12 retrieved | No overlap inflation |
| Beam search precision | Limited by false edges | Higher (cleaner graph) | Fewer false neighbors per hop |
| Confidence loop iterations | Sometimes 2-3 (noise-driven) | Usually 1 (accurate metrics) | Meaningful confidence scores |

---

## Code Changes Required for Route 4 Compatibility

### Already handled (no Route 4 changes needed):
1. **text_store.py** — Already updated to `src:Sentence OR src:TextChunk` (L361-375, L397-399)
2. **semantic_multihop_beam()** — Only traverses Entity-Entity edges, filters `type(r) <> 'MENTIONS'` 
3. **Route 4 handler** — No direct MENTIONS/TextChunk references
4. **Synthesis** — Calls text_store which handles both schemas

### Changes needed (should be added to Phase C):
1. **PPR Path 2** in `_build_ppr_query_with_section_graph()` (async_neo4j_service.py L780-800):
   - Update `(chunk:Chunk OR chunk:TextChunk)` → `(src:Sentence OR src:TextChunk)`
   - Add `OPTIONAL MATCH (src)-[:PART_OF]->(parent_chunk)` resolution
   - Affects Route 4's PPR fallback path and Route 2's primary path

2. **PPR Path 4** in same method (L842):
   - Same pattern: `(chunk2)-[:MENTIONS]->(chunk_entity)` needs Sentence support

3. **Entity-only PPR** in `_build_ppr_query_entity_only()` (L670-700):
   - This query doesn't traverse MENTIONS (only Entity-Entity edges) — **no change needed**

---

## Key Insight

Route 4's semantic beam search (`semantic_multihop_beam`) is immune to the MENTIONS schema change 
because it explicitly excludes MENTIONS edges: `AND type(r) <> 'MENTIONS'`. It only traverses 
Entity-to-Entity relationships (RELATED_TO, SEMANTICALLY_SIMILAR).

But it benefits **massively** from the *quality* improvement to those Entity-to-Entity edges:
- Fewer noise entities = fewer false RELATED_TO edges = cleaner beam neighborhoods
- Sentence-scoped co-occurrence = edges that actually represent semantic relationships
- Removed compensating mechanisms = no artificial alias/regex entities polluting the graph

The graph *structure* Route 4 traverses doesn't change. The graph *quality* improves dramatically.

---

## Summary

| Phase B Change | Route 4 Impact | Mechanism |
|---------------|----------------|-----------|
| Sentence classifier (B.1) | **High** — fewer noise seeds | Cleaner entity extraction |
| Entity extraction from sentences (B.2) | **High** — better RELATED_TO edges | Sentence-scoped, no overlap |
| Sentence-scoped co-occurrence (B.3) | **Critical** — beam search quality | False edges eliminated |
| Remove generic aliases (B.4) | **Medium** — better seed resolution | No false alias matches |
| Remove NLP seed fallback (B.4) | **Medium** — cleaner entity set | No regex-injected noise |
| MENTIONS schema change (B.5) | **Low** — Route 4 doesn't traverse MENTIONS | Only affects PPR fallback |
| Foundation edge updates (B.6) | **Low** — affects APPEARS_IN_SECTION | Used by PPR, not beam search |

**Bottom line:** Phase B is primarily a graph quality improvement. Route 4 is the route most sensitive 
to graph quality because it traverses entities at every hop. Phase B should improve Route 4's beam 
search precision more than any other route.
