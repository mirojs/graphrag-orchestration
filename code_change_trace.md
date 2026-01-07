# Code Change Trace - Last 5 Deployments

## Deployment -2: Section Boost Implementation (20260107085131) 
**Purpose:** Add semantic section discovery to Route 3
**Result:** Section boost enabled, Q-G1 improvement from previous baselines

### Changes (from conversation summary):
- Added `enable_section_boost` environment variable check
- Implemented semantic section discovery workflow:
  - Hybrid RRF search for seed chunks
  - Extract section IDs from chunks
  - Rank sections by relevance
  - Fetch all chunks from top sections via graph expansion
- Added section boost metadata tracking
- Section boost applied universally to all Route 3 queries

### Logging:
```python
logger.info(
    "route_3_section_boost_applied",
    strategy="semantic_section_discovery",
    boost_candidates=len(boost_chunks),
    boost_added=len(added_chunks),
    total_source_chunks=len(graph_context.source_chunks),
)
```

---

## Deployment -1: Keyword Boost Normalization (20260107092521)
**Purpose:** Tune keyword boost for better balance
**Note:** `ROUTE3_KEYWORD_BOOST=0` (disabled) according to conversation summary

### Changes:
- Keyword boost disabled or tuned down
- This is when Q-G4 dropped from 100% to 50% 
- Missing terms: "monthly statement", "income", "expenses"
- No code changes to logging or structure, just configuration

---

## Deployment 1: Working (20260107142142) - PPR Metadata Fix
**Result:** Q-G1: 88%, Q-G2-G10 maintained ✅

### Stage 3.1 Community Matching:
```python
logger.info("stage_3.1_complete", num_communities=len(community_data))
```

### Stage 3.3 Graph Context:
```python
logger.info("stage_3.3_complete",
           num_source_chunks=len(graph_context.source_chunks),
           num_relationships=len(graph_context.relationships),
           num_related_entities=len(graph_context.related_entities))
```

### Section Boost:
```python
logger.info(
    "route_3_section_boost_applied",
    strategy="semantic_section_discovery",
    boost_candidates=len(boost_chunks),
    boost_added=len(added_chunks),
    total_source_chunks=len(graph_context.source_chunks),
)
```

---

## Deployment 2: Broken (20260107144555) - Enhanced Logging Added
**Result:** theme=0% for ALL queries ❌

### Stage 3.1 Community Matching (ADDED):
```python
logger.info("stage_3.1_complete", 
           num_communities=len(community_data),
           community_titles=[c.get("title", "?") for c in community_data],
           zero_communities_warning=len(community_data) == 0)
```

### Stage 3.3 Graph Context (ADDED):
```python
logger.info("stage_3.3_complete",
           num_source_chunks=len(graph_context.source_chunks),
           num_relationships=len(graph_context.relationships),
           num_related_entities=len(graph_context.related_entities),
           chunk_sources=[c.get("source_path", "?")[:50] for c in graph_context.source_chunks[:5]])
```

### Section Boost (ADDED):
```python
logger.info(
    "route_3_section_boost_applied",
    strategy="semantic_section_discovery",
    boost_candidates=len(boost_chunks),
    boost_added=len(added_chunks),
    total_source_chunks=len(graph_context.source_chunks),
    added_documents=list(set(c.get("source_path", "?")[:60] for c in added_chunks)),
    section_ids=semantic_section_ids[:5],
)
```

---

## Deployment 3: Current (20260107154503) - Attempted Revert
**Code changes made in this session's revert:**

### Stage 3.1 - REVERTED CORRECTLY ✅
### Stage 3.3 - REVERTED CORRECTLY ✅ 
### Section Boost - REVERTED CORRECTLY ✅

### BUT FOUND DUPLICATE:
There was a SECOND `stage_3.3_complete` at line 2009 that was added incorrectly and just removed.

---

## Problem Found:
The duplicate `stage_3.3_complete` log at line ~2009 was NOT in the original working code.
This was introduced somewhere and needs to be traced.
