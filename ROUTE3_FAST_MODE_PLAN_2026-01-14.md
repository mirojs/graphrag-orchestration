# Route 3 Fast Mode Implementation Plan

**Date:** January 14, 2026  
**Status:** Planning  
**Priority:** Low (Route 3 currently working perfectly with section embeddings)

---

## Executive Summary

With section-aware embeddings now in production, Route 3's multi-stage pipeline may be over-engineered. This document captures the analysis and implementation plan for a simplified `ROUTE3_FAST_MODE` that aligns more closely with Microsoft GraphRAG's Global Search design.

**Key Insight:** Section embeddings solve the retrieval problem that LazyGraphRAG + HippoRAG were designed to address. We can potentially simplify to 4 core stages.

---

## Current Route 3 Pipeline (12 Stages)

| Stage | Name | Time Est. | Purpose |
|:------|:-----|:----------|:--------|
| 3.1 | Community Matching | 2-4s | LazyGraphRAG: match query to communities |
| 3.2 | Hub Extraction | 1-2s | Extract top entities from matched communities |
| 3.3 | Graph Context | 0.5-1s | MENTIONS/RELATED_TO traversal |
| 3.3.1 | Coverage Intent Detection | <0.1s | Regex to detect cross-doc queries |
| 3.3.5 | Cypher25 BM25+Vector RRF | 1-2s | Hybrid retrieval with section embeddings |
| - | Section Boost | 2-4s | Vector search → section expansion |
| - | Keyword Boost | 0.5-1s | Hardcoded clause patterns |
| - | Doc Lead Boost | 0.5s | First chunk per document |
| 3.4 | HippoRAG PPR | 3-5s | Personalized PageRank traversal |
| 3.4.1 | Coverage Gap Fill | 0.5-1s | Ensure all docs represented |
| 3.5 | Synthesis | 5-10s | LLM generation |
| - | Field Validation | 0.5-1s | Neo4j negative detection |

**Current Total:** ~20-30 seconds per query

---

## Proposed Fast Mode Pipeline (4 Stages)

| Stage | Name | Time Est. | Purpose |
|:------|:-----|:----------|:--------|
| A | Hybrid Retrieval | 1-2s | BM25 + Vector RRF (section-aware embeddings) |
| B | Coverage Gap Fill | 0.5-1s | Ensure all docs represented |
| C | Synthesis | 5-10s | LLM generation |
| D | Field Validation | 0.5-1s | Neo4j negative detection (for negatives only) |

**Target Total:** ~7-14 seconds per query (50-60% faster)

---

## What Gets Cut

| Component | Why Cut |
|:----------|:--------|
| Community Matching (3.1) | Section embeddings find themes directly—no need for community → hub indirection |
| Hub Extraction (3.2) | No communities = no hubs needed |
| Graph Context (3.3) | BM25+Vector finds chunks directly, no entity traversal needed for retrieval |
| Section Boost | Redundant—embeddings already encode section structure |
| Keyword Boost | Redundant—embeddings already encode section structure |
| Doc Lead Boost | Covered by Coverage Gap Fill |
| HippoRAG PPR (3.4) | Embeddings find chunks directly, no graph traversal needed |

---

## What We Keep

| Component | Why Keep |
|:----------|:---------|
| BM25+Vector RRF (3.3.5) | **Primary retrieval**—section-aware embeddings do the heavy lifting |
| Coverage Gap Fill (3.4.1) | Ensures Global Search promise (all docs represented) |
| Synthesis (3.5) | Core output generation |
| Field Validation | Deterministic negative detection (our unique value-add) |

---

## Design Rationale

### Microsoft GraphRAG Global Search

```
Query → Community Matching → Community Summaries → LLM Synthesis
```

Simple 3-stage pipeline. Designed for "What are the main themes?"

### Our Original Design (LazyGraphRAG + HippoRAG)

Built to solve: **"Naive embeddings can't find thematic content reliably."**

- Community matching: Semantic topic discovery
- Hub extraction: Find seed entities for graph traversal
- HippoRAG PPR: Deterministic graph traversal from seeds
- Many boosts: Fallbacks for when embeddings fail

### With Section Embeddings

The embedding layer now solves the retrieval problem:
- Query "termination rules" → directly finds "Termination" section chunks
- Query "payment terms" → directly finds "Payment Terms" section chunks

**No need for community → hub → PPR indirection.**

Graph is still valuable for **negative detection** (verifying something doesn't exist), but not needed for positive retrieval.

---

## Implementation Approach

### Option A: Env Var Toggle (Low Risk)

```python
ROUTE3_FAST_MODE=1  # Use simplified pipeline
ROUTE3_FAST_MODE=0  # Use full pipeline (default)
```

**Effort:** ~2-4 hours  
**Risk:** Low—keeps full pipeline as fallback

### Option B: Full Refactor (Higher Risk)

Remove dead code entirely, single clean implementation.

**Effort:** ~1-2 days  
**Risk:** Medium—no fallback if issues found

---

## Recommended Approach

**Go with Option A (Env Var Toggle):**

1. Add `ROUTE3_FAST_MODE` env var check at start of `_execute_route_3_global_search`
2. If enabled, skip directly to Stage 3.3.5 (BM25+Vector RRF)
3. Continue with Coverage Gap Fill → Synthesis → Field Validation
4. Benchmark both modes to validate quality parity

---

## Effort Estimate

| Task | Time |
|:-----|:-----|
| Add ROUTE3_FAST_MODE env var + skip logic | 1 hour |
| Adjust logging/metadata for fast mode | 0.5 hour |
| Test locally | 0.5 hour |
| Deploy + benchmark comparison | 1 hour |
| **Total** | **~3 hours** |

---

## Decision

**Recommendation:** Defer to after Route 4 implementation.

**Rationale:**
1. Route 3 is already working perfectly with 100% benchmark scores
2. Speed optimization is nice-to-have, not blocking
3. Route 4 (DRIFT multi-hop) is not yet implemented
4. ~3 hours is modest but Route 4 should take priority

---

## Next Steps

1. ✅ Document plan (this file)
2. ⏸️ Defer implementation until Route 4 complete
3. 🔜 Implement Route 4 (DRIFT multi-hop reasoning)
4. 🔜 Return to Route 3 Fast Mode optimization
5. 🔜 A/B benchmark full vs fast mode

---

## Appendix: Quick Implementation Sketch

```python
async def _execute_route_3_global_search(self, query: str, response_type: str):
    # Fast mode: skip community/hub/PPR stages
    fast_mode = os.getenv("ROUTE3_FAST_MODE", "0").strip().lower() in {"1", "true", "yes"}
    
    if fast_mode:
        logger.info("route_3_fast_mode_enabled")
        
        # Stage A: Direct BM25+Vector retrieval (section embeddings do the work)
        chunks = await self._search_chunks_cypher25_hybrid_rrf(query, top_k=30)
        
        # Stage B: Coverage gap fill
        chunks = await self._fill_coverage_gaps(chunks)
        
        # Stage C: Synthesis
        result = await self.synthesizer.synthesize(query, chunks, response_type)
        
        # Stage D: Field validation (for negative detection)
        if await self._is_likely_negative(query, result):
            result = await self._validate_with_graph(query, result)
        
        return result
    
    # Full pipeline (existing code)
    ...
```

---

*Document created: 2026-01-14*  
*Author: AI Assistant*
