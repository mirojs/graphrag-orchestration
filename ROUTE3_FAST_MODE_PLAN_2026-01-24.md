# Route 3 Fast Mode Implementation Plan (Revised)

**Date:** January 14, 2026  
**Last Updated:** January 24, 2026  
**Status:** Planning (Revised)  
**Priority:** Medium (Performance optimization with quality preservation)

---

## Executive Summary

This document captures the analysis and implementation plan for a simplified `ROUTE3_FAST_MODE` that reduces the 12-stage pipeline to 5 stages while preserving entity-based retrieval quality.

**Key Insight (Revised):** Section embeddings enhance retrieval but do NOT replace entity-graph reasoning. The original plan oversimplified by assuming section vectors could replace community matching entirely. A more careful analysis shows we can eliminate redundant stages while preserving the entity-based retrieval that provides citation provenance and graph-aware reasoning.

**What's Changed Since January 14:**
- ✅ Route 4 (DRIFT) is now complete and working
- ✅ KeyValue (KVP) nodes added (January 22) - high-precision field extraction
- ✅ Table nodes enhanced for structured data retrieval
- ✅ Entity aliases enabled across all routes (85% entity coverage)
- ✅ Vector RAG (Route 1) removed - Local Search handles all simple queries

---

## Critical Correction: What Community Matching Actually Does

**Original Assumption (INCORRECT):**
> "Section embeddings find themes directly—no need for community → hub indirection"

**Reality:** The codebase does NOT use pre-computed Microsoft GraphRAG-style community summaries. 

What `community_matcher.py` actually does:
1. **Entity embedding search** - finds entities matching query via vector similarity
2. **Keyword fallback** - matches entity names/descriptions if embedding fails  
3. **Multi-document sampling** - round-robin across documents for diversity
4. **Returns entities as "community"** - these become hub entities for PPR

**Implication:** "Communities" = query-relevant entity clusters, not pre-indexed summaries. Removing this loses entity discovery, which breaks PPR and citation provenance.

---

## What Section Embeddings Actually Provide

| Capability | Section Embeddings | Entity Graph |
|------------|-------------------|--------------|
| Find relevant chunks | ✅ Direct vector search | ✅ Via MENTIONS edges |
| Cross-document diversity | ⚠️ Needs explicit logic | ✅ Multi-doc sampling built-in |
| Entity relationships | ❌ No | ✅ RELATED_TO edges |
| Citation provenance | ❌ Chunk-level only | ✅ Entity → Chunk → Section → Document |
| Negative detection | ❌ No | ✅ Graph-based field validation |
| Hub entity extraction | ❌ No | ✅ Required for PPR |

**Conclusion:** Section embeddings solve "latent transitions" (finding related sections) but NOT entity-based reasoning.

---

## Current Route 3 Pipeline (12 Stages)

| Stage | Name | Time Est. | Purpose | Keep? |
|:------|:-----|:----------|:--------|:------|
| 3.1 | Community Matching | 2-4s | Entity embedding search + diversity | ⚠️ Simplify |
| 3.2 | Hub Extraction | 1-2s | Extract top entities from matches | ⚠️ Merge with 3.1 |
| 3.3 | Graph Context | 0.5-1s | MENTIONS/RELATED_TO traversal | ✅ Keep |
| 3.3.1 | Coverage Intent Detection | <0.1s | Regex for cross-doc queries | ✅ Keep |
| 3.3.5 | Cypher25 BM25+Vector RRF | 1-2s | Hybrid retrieval | ✅ Keep (PRIMARY) |
| - | Section Boost | 2-4s | Vector → section expansion | ❌ Redundant |
| - | Keyword Boost | 0.5-1s | Hardcoded clause patterns | ❌ Redundant |
| - | Doc Lead Boost | 0.5s | First chunk per document | ❌ Redundant |
| 3.4 | HippoRAG PPR | 3-5s | PageRank traversal | ⚠️ Optional |
| 3.4.1 | Coverage Gap Fill | 0.5-1s | Ensure all docs represented | ✅ Keep |
| 3.5 | Synthesis | 5-10s | LLM generation | ✅ Keep |
| - | Field Validation | 0.5-1s | Neo4j negative detection | ✅ Keep |

**Current Total:** ~20-30 seconds per query

---

## Revised Fast Mode Pipeline (5 Stages)

| Stage | Name | Time Est. | Purpose |
|:------|:-----|:----------|:--------|
| A | Entity Embedding Search | 1-2s | Direct entity matching (merged 3.1+3.2) |
| B | BM25+Vector RRF | 1-2s | Hybrid chunk retrieval + MENTIONS context |
| C | Coverage Gap Fill | 0.5-1s | Ensure all docs represented |
| D | Synthesis | 5-10s | LLM generation |
| E | Field Validation | 0.5-1s | Neo4j negative detection |

**Target Total:** ~8-16 seconds per query (40-50% faster)

---

## What Gets Cut (Revised)

| Component | Why Cut |
|:----------|:--------|
| Section Boost | Redundant—BM25+Vector with section embeddings already does this |
| Keyword Boost | Redundant—hardcoded patterns replaced by BM25 lexical matching |
| Doc Lead Boost | Redundant—Coverage Gap Fill handles this better |
| HippoRAG PPR (3.4) | **Optional**—skip for simple thematic queries, keep for complex ones |

**NOT Cut (Corrected):**
| Component | Why Keep |
|:----------|:---------|
| Entity Embedding Search | Required for multi-document diversity and citation provenance |
| Graph Context (MENTIONS) | Required for entity → chunk relationship mapping |

---

## What We Keep (Revised)

| Component | Why Keep |
|:----------|:---------|
| Entity Embedding Search | Multi-document diversity, entity discovery for citations |
| BM25+Vector RRF (3.3.5) | **Primary retrieval**—hybrid search with section awareness |
| Graph Context (MENTIONS) | Citation provenance via entity → chunk relationships |
| Coverage Gap Fill (3.4.1) | Global Search promise: all documents represented |
| Synthesis (3.5) | Core output generation |
| Field Validation | Deterministic negative detection (unique value-add) |

---

## New Graph Elements to Leverage

### KeyValue (KVP) Nodes (Added January 22, 2026)

**Node Type:** `KeyValue`
- Properties: `key`, `value`, `confidence`, `page_number`, `document_id`, `key_embedding`
- Relationships: `IN_CHUNK`, `IN_SECTION`, `IN_DOCUMENT`
- **80 KVP nodes** in test corpus

**Fast Mode Integration:**
```python
# For field-lookup queries, check KVP first (highest precision)
if is_field_lookup_query(query):
    kvp_result = await self._search_kvp_by_embedding(query)
    if kvp_result and kvp_result.confidence > 0.8:
        return kvp_result  # Skip full retrieval
```

### Table Nodes

- `(Table)-[:IN_CHUNK]->(TextChunk)`
- Structured data extraction for invoice/contract line items
- Can short-circuit for tabular queries

### Entity Aliases (Added January 19, 2026)

- 85% of entities have aliases ("Fabrikam Inc." → ["Fabrikam"])
- Improves entity embedding search recall
- Already integrated into all routes

---

## Design Rationale (Revised)

### Why Not Remove Entity Search Entirely?

1. **PPR needs seeds** - Without entities, no graph traversal possible
2. **Citations need provenance** - Entity → Chunk mapping enables `[Source: contract.pdf, Section 2.3]`
3. **Multi-doc diversity** - Entity search already does round-robin sampling
4. **Negative detection** - Field validation queries entity existence

### Why Remove Section/Keyword/Doc Boosts?

1. **Section Boost** - BM25+Vector with section embeddings already finds relevant sections
2. **Keyword Boost** - Hardcoded patterns are fragile; BM25 lexical matching is superior
3. **Doc Lead Boost** - Coverage Gap Fill already ensures document representation

### Why Make PPR Optional?

1. **Simple thematic queries** - "What are the main themes?" → BM25+Vector sufficient
2. **Complex relationship queries** - "How are vendors connected to risks?" → PPR adds value
3. **Heuristic** - If query has explicit entity mentions, enable PPR; otherwise skip

---

## Implementation Approach (Revised)

### Option A: Selective Stage Skip (Recommended)

```python
ROUTE3_FAST_MODE=1  # Skip Section/Keyword/Doc boosts + optional PPR
ROUTE3_FAST_MODE=0  # Full pipeline (default)
```

**Logic:**
1. Always run Entity Embedding Search (merged community matching)
2. Always run BM25+Vector RRF (primary retrieval)
3. Always run Coverage Gap Fill
4. **Skip PPR** if query is simple thematic (no explicit entities)
5. Always run Synthesis + Field Validation

**Effort:** ~3-4 hours  
**Risk:** Low—preserves entity-based retrieval

### Option B: Full Refactor

Remove dead code (Section Boost, Keyword Boost, Doc Lead Boost).

**Effort:** ~1 day  
**Risk:** Medium—no A/B comparison possible

---

## Effort Estimate (Revised)

| Task | Time |
|:-----|:-----|
| Add ROUTE3_FAST_MODE env var + skip logic | 1 hour |
| Merge community matching + hub extraction | 1 hour |
| Add PPR skip heuristic | 0.5 hour |
| Remove Section/Keyword/Doc boost code paths | 1 hour |
| Add KVP fast-path for field lookups | 1 hour |
| Test locally | 0.5 hour |
| Deploy + benchmark comparison | 1 hour |
| **Total** | **~6 hours** |

---

## Expected Results

| Metric | Full Pipeline | Fast Mode | Change |
|:-------|:--------------|:----------|:-------|
| Latency | 20-30s | 8-16s | -40-50% |
| Accuracy | 100% | ~98-100% | Minimal |
| Citation Quality | Full provenance | Full provenance | Same |
| Negative Detection | Graph-based | Graph-based | Same |

---

## Decision

**Recommendation:** Implement Option A (Selective Stage Skip)

**Rationale:**
1. ✅ Route 4 is now complete - no longer blocking
2. ✅ Route 3 achieving 100% but slow (20-30s)
3. ✅ 40-50% speedup is meaningful for user experience
4. ✅ Entity-based retrieval preserved for quality
5. ✅ KVP integration can further accelerate field lookups

---

## Next Steps

1. ✅ Document revised plan (this file)
2. 🔜 Implement ROUTE3_FAST_MODE toggle
3. 🔜 Merge community matching + hub extraction
4. 🔜 Add PPR skip heuristic for simple queries
5. 🔜 Remove Section/Keyword/Doc boost dead code
6. 🔜 Add KVP fast-path for field-lookup queries
7. 🔜 A/B benchmark full vs fast mode

---

## Appendix: Revised Implementation Sketch

```python
async def _execute_route_3_global_search(self, query: str, response_type: str):
    fast_mode = os.getenv("ROUTE3_FAST_MODE", "0").strip().lower() in {"1", "true", "yes"}
    
    # Stage A: Entity Embedding Search (always run - provides diversity + citations)
    # This merges old 3.1 (community matching) + 3.2 (hub extraction)
    logger.info("stage_A_entity_embedding_search")
    entities = await self._search_entities_by_embedding(query, top_k=15)
    
    # KVP fast-path for field-lookup queries (NEW)
    if fast_mode and await self._is_field_lookup_query(query):
        kvp_result = await self._search_kvp_by_embedding(query)
        if kvp_result and kvp_result.confidence > 0.8:
            return self._format_kvp_response(kvp_result)
    
    # Stage B: BM25+Vector RRF (always run - primary retrieval)
    logger.info("stage_B_hybrid_retrieval")
    chunks = await self._search_chunks_cypher25_hybrid_rrf(query, top_k=30)
    
    # Get MENTIONS context from entities (for citations)
    mentions_chunks = await self._get_entity_mentions(entities)
    chunks = self._merge_and_dedupe(chunks, mentions_chunks)
    
    # Stage B.5: PPR (optional in fast mode)
    if not fast_mode or self._has_explicit_entities(query):
        logger.info("stage_B5_ppr_tracing")
        ppr_chunks = await self._run_ppr_from_entities(entities)
        chunks = self._merge_and_dedupe(chunks, ppr_chunks)
    else:
        logger.info("stage_B5_ppr_skipped", reason="fast_mode_simple_query")
    
    # Stage C: Coverage Gap Fill (always run)
    logger.info("stage_C_coverage_gap_fill")
    chunks = await self._fill_coverage_gaps(chunks)
    
    # Stage D: Synthesis (always run)
    logger.info("stage_D_synthesis")
    result = await self.synthesizer.synthesize(query, chunks, response_type)
    
    # Stage E: Field Validation (always run for negatives)
    if await self._is_likely_negative(query, result):
        result = await self._validate_with_graph(query, result)
    
    return result
```

---

## Appendix: Stage Comparison

### Full Pipeline (Current)
```
Query → Community Match → Hub Extract → Graph Context → Coverage Detect
      → BM25+Vector → Section Boost → Keyword Boost → Doc Lead Boost
      → PPR Tracing → Coverage Fill → Synthesis → Field Validation
```
**12 stages, 20-30 seconds**

### Fast Mode Pipeline (Revised)
```
Query → Entity Embed Search → BM25+Vector → [PPR if complex] → Coverage Fill → Synthesis → Validation
```
**5-6 stages, 8-16 seconds**

---

## Appendix: Comparison with Original Plan

| Aspect | Original Plan (Jan 14) | Revised Plan (Jan 24) |
|:-------|:-----------------------|:----------------------|
| Community Matching | Remove entirely | **Keep** (merged with hub extraction) |
| Entity Search | Not mentioned | **Keep** (critical for citations) |
| PPR | Remove entirely | **Optional** (skip for simple queries) |
| Section Boost | Remove | Remove ✅ |
| Keyword Boost | Remove | Remove ✅ |
| Doc Lead Boost | Remove | Remove ✅ |
| KVP Integration | Not available | **Added** fast-path |
| Stages | 4 | 5-6 |
| Latency Target | 7-14s | 8-16s |
| Quality Risk | Medium (lost entity reasoning) | Low (preserved entity reasoning) |

---

*Document created: 2026-01-14*  
*Revised: 2026-01-24 (corrected assumptions about community matching, added KVP integration)*  
*Supersedes: ROUTE3_FAST_MODE_PLAN_2026-01-14.md*  
*Author: AI Assistant*
