# Implementation Plan: Route 3 v2 + Source Denoising

**Date:** 2026-02-12  
**Objective:** (1) Rebuild Route 3 as LazyGraphRAG + Map-Reduce, (2) Denoise the graph at source via sentence-based entity extraction  
**Architecture basis:** LazyGraphRAG (community summaries) + HippoRAG 2 (PPR sentence discovery) + Map-Reduce synthesis  
**Denoising principle:** Every graph artifact traces to exactly one source sentence. If it can't, it's noise or metadata.

---

## Overview

```
Phase A — Route 3 v2 (Map-Reduce on current data)          ~200 LOC, 0 indexing changes
Phase B — Source Denoising (sentence-based entity extraction) ~300 LOC, requires re-index
Phase C — Route 2 query update + full benchmark              ~20 LOC
```

Phases A and B are independent. A can ship and validate before B starts.

---

## Phase A: Route 3 v2 — LazyGraphRAG Map-Reduce

**Goal:** Replace the current 7-stage pipeline (659 lines) with a clean 3-step architecture (~200 lines).

### A.1 — New Route 3 Handler

**File:** `src/worker/hybrid_v2/routes/route_3_global.py` (rewrite)

```
Step 1: Community Match          — KEEP existing community_matcher.match_communities(query, top_k=3)
Step 2: MAP (per community)      — NEW: LLM extracts key claims from community summary
Step 3: REDUCE                   — NEW: LLM synthesizes all claims into global report
```

**What gets removed:**
- Stage 3.2 (Hub entity extraction, 30 entities) — replaced by community summary
- Stage 3.3 (MENTIONS chunk fetch, 90 lookups) — primary noise source, eliminated
- Stage 3.3.5 (BM25+RRF merge) — replaced by community summary as primary content
- Stage 3.4 (PPR dead code) — removed entirely
- Stage 3.4.1 (Coverage gap fill) — absorbed into reduce prompt instruction
- Stage 3.5 (single-shot synthesis, 80K tokens) — replaced by map-reduce

**Core logic (pseudocode):**

```python
async def execute(self, query, response_type, ...):
    # Step 1: Community match (unchanged)
    matched = await self.pipeline.community_matcher.match_communities(query, top_k=3)
    communities = [c for c, score in matched]
    
    # Step 2: MAP — parallel, one LLM call per community
    map_results = await asyncio.gather(*[
        self._map_community(query, community) for community in communities
    ])
    
    # Step 3: REDUCE — single LLM call to synthesize
    response = await self._reduce(query, map_results, response_type)
    
    return RouteResult(response=response, ...)

async def _map_community(self, query, community):
    """Extract claims relevant to query from one community summary."""
    prompt = MAP_PROMPT.format(
        query=query,
        community_title=community["title"],
        community_summary=community["summary"],
        entity_names=", ".join(community.get("entity_names", [])[:10]),
    )
    return await self.pipeline.llm.acomplete(prompt)

async def _reduce(self, query, map_results, response_type):
    """Synthesize all community claims into final answer."""
    claims_text = "\n\n".join([
        f"### Community: {r['title']}\n{r['claims']}"
        for r in map_results if r.get("claims")
    ])
    prompt = REDUCE_PROMPT.format(
        query=query,
        claims=claims_text,
        response_type=response_type,
    )
    return await self.pipeline.llm.acomplete(prompt)
```

**Prompts needed (new file):**

**File:** `src/worker/hybrid_v2/routes/route_3_prompts.py` (~80 lines)

- `MAP_PROMPT`: "Given this thematic community summary, extract the key claims and evidence relevant to the user's query. Include specific details, names, dates, numbers. If the community is not relevant, say IRRELEVANT."
- `REDUCE_PROMPT`: "Synthesize the following claims from multiple thematic communities into a coherent {response_type}. Reconcile any conflicts. Cite which community each claim comes from."

**Dependencies:** No new dependencies. Uses existing `community_matcher`, `pipeline.llm`.

### A.2 — Wire Route 3 v2 into Router

**File:** `src/worker/hybrid_v2/routes/route_3_global.py`

- Keep `GlobalSearchHandler` class name and `ROUTE_NAME` for backward compatibility
- Replace `execute()` method body
- Remove all helper methods: `_apply_hybrid_rrf_stage`, `_check_entity_relevance`, `_apply_coverage_gap_fill`, `_synthesize_global_response`

### A.3 — Benchmark Route 3 v2

**Script:** `scripts/benchmark_route3_v2.py` (adapt existing `benchmark_route3_baseline.py`)

- Same 10 questions as baseline
- Compare: theme_coverage, latency, token cost, response quality
- Expected improvements: latency 40s → ~20s, tokens 80K → ~12K, cleaner output

### A.4 — Deliverables

| Item | File | Lines |
|------|------|-------|
| Route 3 handler rewrite | `src/worker/hybrid_v2/routes/route_3_global.py` | ~150 |
| Map/Reduce prompts | `src/worker/hybrid_v2/routes/route_3_prompts.py` | ~80 |
| Benchmark script | `scripts/benchmark_route3_v2.py` | ~200 |
| **Total** | | **~430** |

---

## Phase B: Source Denoising — Sentence-Based Entity Extraction

**Goal:** Extract entities from Sentence nodes instead of TextChunk nodes. Clean the entity graph at source.

### B.1 — Sentence Content Classifier

**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` (new method)

```python
@staticmethod
def _classify_sentence(text: str) -> str:
    """Classify a sentence as 'content', 'metadata', or 'noise'.
    
    content  — extract entities from this
    metadata — store as structured data, skip entity extraction  
    noise    — skip entirely (form labels, empty fields)
    """
    t = text.strip()
    if len(t) < 15:
        return "noise"
    if len(t) < 40 and t.endswith(':'):
        return "noise"        # "Pumper's Name:"
    if len(t) < 50 and not any(c in t for c in '.!?,;'):
        return "metadata"     # "Contract Date: 2024-06-15"
    if re.match(r'^[\d\$,.%\s]+$', t):
        return "metadata"     # "$29,900.00"
    return "content"
```

### B.2 — Entity Extraction from Sentences

**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

**Change `_extract_entities_and_relationships()`:**

Current flow:
```
for chunk in chunks:
    entities, rels = LLM_extract(chunk.text)     # 512 tokens, overlapping
```

New flow:
```
sentences = neo4j_store.get_sentences(group_id)  # already exist from Step 4
content_sentences = [s for s in sentences if _classify_sentence(s.text) == "content"]

# Batch sentences into groups of 5-8 for efficient LLM calls
for batch in batched(content_sentences, batch_size=6):
    combined_text = "\n".join([s.text for s in batch])
    entities, rels = LLM_extract(combined_text)
    
    # Track which sentence each entity came from
    for entity in entities:
        entity.text_unit_ids = [s.id for s in batch if entity.name in s.text]
```

**Key changes:**
1. Source: Sentence nodes (no overlap) instead of TextChunk nodes (64-token overlap)
2. Pre-filter: Only extract from "content" sentences  
3. MENTIONS edges: `(:Sentence)-[:MENTIONS]->(:Entity)` — exactly 1 per occurrence
4. Provenance: Each RELATED_TO edge gets `source_sentence_id` property

### B.3 — Sentence-Scoped Co-occurrence Relationships

**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

Current: LLM generates RELATED_TO edges from 512-token chunks → many false co-occurrences.

New (deterministic alternative for basic relationships):
```python
# After entity extraction, for each sentence with 2+ entities:
# create a RELATED_TO edge with the sentence as provenance
for sentence in content_sentences:
    entities_in_sentence = [e for e in all_entities if sentence.id in e.text_unit_ids]
    if len(entities_in_sentence) >= 2:
        for i, e1 in enumerate(entities_in_sentence):
            for e2 in entities_in_sentence[i+1:]:
                relationships.append(Relationship(
                    source_id=e1.id,
                    target_id=e2.id,
                    description=sentence.text,  # sentence IS the provenance
                    source_sentence_id=sentence.id,
                    weight=1.0,
                ))
```

LLM-extracted relationships (PARTY_TO, LOCATED_IN, etc.) still run but on sentence batches instead of chunks. The LLM sees cleaner input and produces fewer false relationships.

### B.4 — Remove Compensating Mechanisms

These exist to work around chunk-level noise. With sentence-based extraction, they become unnecessary:

| Mechanism | File | Action |
|-----------|------|--------|
| `_generate_generic_aliases()` | `lazygraphrag_pipeline.py` L2614 | **Remove** — entities are precise from sentence context |
| `_nlp_seed_entities()` | `lazygraphrag_pipeline.py` L1413 | **Remove** — sentence extraction is reliable, no regex fallback needed |
| Chunk overlap (64 tokens) | `SentenceSplitter(chunk_overlap=64)` | **Keep chunks for backward compat** but entities no longer extracted from them |

### B.5 — Update MENTIONS Edge Schema

**File:** `src/worker/hybrid_v2/services/neo4j_store.py`

Change `aupsert_entities_batch()` to create `(:Sentence)-[:MENTIONS]->(:Entity)` instead of `(:TextChunk)-[:MENTIONS]->(:Entity)`.

The `text_unit_ids` on Entity now contains Sentence IDs, not Chunk IDs.

```python
# Current (chunk-based):
UNWIND entity.text_unit_ids AS chunk_id
MATCH (c:TextChunk {id: chunk_id, group_id: $group_id})
MERGE (c)-[:MENTIONS]->(e)

# New (sentence-based):
UNWIND entity.text_unit_ids AS sentence_id
MATCH (s:Sentence {id: sentence_id, group_id: $group_id})
MERGE (s)-[:MENTIONS]->(e)
```

### B.6 — Update Foundation Edges

**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` (method `_create_foundation_edges`)

Current path: `Entity ← MENTIONS ← TextChunk → IN_SECTION → Section`  
New path: `Entity ← MENTIONS ← Sentence → IN_SECTION → Section` (Sentence already has IN_SECTION)

Update `APPEARS_IN_SECTION` and `APPEARS_IN_DOCUMENT` queries.

### B.7 — Re-Index Test Group

```bash
# Re-index test-5pdfs-v2-fix2 with sentence-based entity extraction
python scripts/index_4_new_groups_v2.py --group-id test-5pdfs-v2-fix2 --force
```

### B.8 — Deliverables

| Item | File | Change |
|------|------|--------|
| Sentence classifier | `lazygraphrag_pipeline.py` | +30 lines |
| Entity extraction from sentences | `lazygraphrag_pipeline.py` | ~100 lines modified |
| Sentence-scoped co-occurrence | `lazygraphrag_pipeline.py` | +40 lines |
| Remove generic aliases | `lazygraphrag_pipeline.py` | -40 lines |
| Remove NLP seed fallback | `lazygraphrag_pipeline.py` | -60 lines |
| MENTIONS edge schema | `neo4j_store.py` | ~10 lines modified |
| Foundation edge queries | `lazygraphrag_pipeline.py` | ~20 lines modified |
| **Net** | | **~+100 lines** (add 170, remove 100) |

---

## Phase C: Route 2 Update + System Benchmark

**Goal:** Update Route 2's chunk retrieval to work with sentence-based MENTIONS. Benchmark all routes.

### C.1 — Update Route 2 Chunk Retrieval

**File:** `src/worker/hybrid_v2/indexing/text_store.py` (method `_get_chunks_for_entities_batch_sync`)

Change the MENTIONS traversal query:

```cypher
-- Current:
MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)

-- New (sentence-based, return parent chunk text):
MATCH (s:Sentence {group_id: $group_id})-[:MENTIONS]->(e)
OPTIONAL MATCH (s)-[:PART_OF]->(c:TextChunk)
-- Return sentence text if no parent chunk, else chunk text
WITH entity_name, coalesce(c, s) AS content_node, ...
```

OR (simpler — return sentence text directly):
```cypher
MATCH (s:Sentence {group_id: $group_id})-[:MENTIONS]->(e)
```

**Decision needed at implementation time:** Return sentence text (granular, ~25 tokens) or traverse to parent chunk (broader context, ~512 tokens). Likely: return sentence text with surrounding context from NEXT/PREV edges.

### C.2 — System-Wide Benchmark

**Script:** `scripts/benchmark_all_routes_v2.py`

Run the same test queries across Routes 2, 3, 4 with:
- Before: chunk-based entity graph (current)
- After: sentence-based entity graph (Phase B)

Metrics: theme coverage, entity recall, latency, token cost, evidence quality.

### C.3 — Deliverables

| Item | File | Change |
|------|------|--------|
| Text store query update | `text_store.py` | ~20 lines |
| Benchmark script | `scripts/benchmark_all_routes_v2.py` | ~300 lines |
| **Total** | | **~320 lines** |

---

## Execution Order

```
Week 1:  Phase A (Route 3 v2 map-reduce)
         ├── A.1: Write route_3_global.py rewrite + prompts
         ├── A.2: Wire into router
         ├── A.3: Deploy to test, run benchmark
         └── A.4: Compare with baseline, iterate prompts

Week 2:  Phase B (Source denoising)
         ├── B.1-B.2: Sentence classifier + extraction change
         ├── B.3: Sentence-scoped co-occurrence
         ├── B.4: Remove compensating mechanisms
         ├── B.5-B.6: MENTIONS schema + foundation edges
         └── B.7: Re-index test group

Week 3:  Phase C (Route 2 update + system benchmark)
         ├── C.1: Update text_store.py query
         ├── C.2: Run system-wide benchmark
         └── Compare all routes before/after
```

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Community summaries too shallow for map-reduce | Medium | Phase A tests this directly. If summaries lack detail, add PPR sentence evidence (the Phase B path from earlier discussion) |
| Sentence-based extraction produces fewer entities | Low | Sentence text is more focused — LLM extracts better, not fewer. But monitor entity count before/after |
| Route 2 regression after MENTIONS schema change | Low | One Cypher query change. Sentence→Entity MENTIONS is more precise, not less |
| Re-indexing breaks production | None | Test group only. Production groups unchanged until validated |
| Map-reduce latency higher than expected | Low | 3 parallel map calls (~8K tokens each) + 1 reduce (~4K tokens). Should be faster than single 80K-token call |

---

## Success Criteria

| Metric | Current Baseline | Phase A Target | Phase B Target |
|--------|-----------------|----------------|----------------|
| Route 3 theme coverage | 37.5% (benchmark) | > 60% | > 80% |
| Route 3 latency | ~40s | < 25s | < 20s |
| Route 3 token cost | 80K tokens/query | < 15K tokens | < 12K tokens |
| Route 3 duplicate rate | 56.5% | 0% (summaries) | 0% |
| Route 2 precision | Baseline TBD | No change | Improved (precise MENTIONS) |
| Entity noise rate | Unknown | No change | Measurably lower (count form-label entities before/after) |
| MENTIONS accuracy | Overlap-inflated | No change | 1:1 sentence-entity (deterministic) |

---

## Files Changed Summary

| File | Phase | Change Type |
|------|-------|-------------|
| `src/worker/hybrid_v2/routes/route_3_global.py` | A | **Rewrite** — 659→~150 lines |
| `src/worker/hybrid_v2/routes/route_3_prompts.py` | A | **New** — ~80 lines |
| `scripts/benchmark_route3_v2.py` | A | **New** — ~200 lines |
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | B | **Modify** — entity extraction, remove aliases/NLP seed |
| `src/worker/hybrid_v2/services/neo4j_store.py` | B | **Modify** — MENTIONS edge target |
| `src/worker/hybrid_v2/indexing/text_store.py` | C | **Modify** — chunk retrieval query |
| `scripts/benchmark_all_routes_v2.py` | C | **New** — ~300 lines |
