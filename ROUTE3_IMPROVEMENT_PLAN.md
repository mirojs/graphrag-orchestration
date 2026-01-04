# Route 3 (LazyGraphRAG Global Search) Improvement Plan

**Date:** January 4, 2026  
**Current Baseline:** 64.3/100 avg score, 42% theme coverage  
**Target:** 75+/100 avg score, 60%+ theme coverage

---

## Current Performance Analysis

### Strengths
- ✅ **100% Routing Accuracy** - Correctly identifies global search queries
- ✅ **Response Coherence** - LLM generates well-structured synthesis
- ✅ **Zero Hallucinations** - No claims outside evidence path

### Weaknesses
- ❌ **Low Evidence Discovery** - Only 40% queries meet evidence threshold
- ❌ **Weak Hub Extraction** - Avg 1.6 hub entities (target: 3-5)
- ❌ **Generic Query Failure** - "What are the most important entities?" → 0 results
- ❌ **Keyword Mismatch** - NLP extracts "important entities" but needs actual entity names

---

## Root Cause Analysis

### Problem 1: Weak Keyword Extraction (CommunityMatcher)

**Current Implementation:**
```python
# community_matcher.py: _generate_communities_from_query()
doc = self.nlp(query)
keywords = [token.text.lower() for token in doc 
            if token.pos_ in ["NOUN", "PROPN", "VERB"] 
            and not token.is_stop]
```

**Issues:**
- Extracts generic terms: "important", "entities", "documents" 
- No actual entity names from Neo4j
- No query expansion or synonyms

**Impact:** X-2 query got 0 evidence nodes because "important entities" doesn't match "Microsoft", "AAA", etc.

---

### Problem 2: Limited Hub Entity Discovery (HubExtractor)

**Current Implementation:**
```python
# hub_extractor.py: _query_neo4j_hubs_by_keywords()
keyword_conditions = " OR ".join([
    f"toLower(e.name) CONTAINS toLower('{kw}')" for kw in keywords[:5]
])
```

**Issues:**
- String matching only (no fuzzy/semantic matching)
- No fallback when keywords don't match
- Top-K too conservative (limits to 5 keywords, then top_k entities)

**Impact:** Only finds 1.6 hub entities on average (need 3-5)

---

### Problem 3: Insufficient Evidence Expansion (HippoRAGRetriever)

**Current PPR Settings:**
- `personalization_nodes` = hub_entities (1.6 entities)
- Neighbor expansion likely too conservative

**Impact:** 60% of queries don't meet evidence threshold

---

## Improvement Roadmap

### Phase 1: Quick Wins (30 min) ✅ Priority

#### 1.1 Add Fallback to High-Degree Entities
When keywords match nothing, query for top-K entities by degree:

```python
# hub_extractor.py
async def _query_neo4j_hubs_by_keywords(self, keywords, top_k):
    # Try keyword matching first
    entities = await self._keyword_match(keywords, top_k)
    
    # Fallback: Get top entities by degree
    if len(entities) < 2:
        logger.info("keyword_match_weak_using_degree_fallback")
        entities = await self._get_top_entities_by_degree(top_k * 2)
    
    return entities[:top_k]

async def _get_top_entities_by_degree(self, top_k):
    """Get most connected entities in graph."""
    query = """
    MATCH (e)-[r]-()
    WHERE (e:`__Entity__` OR e:Entity)
    WITH e, count(r) as degree
    ORDER BY degree DESC
    LIMIT $top_k
    RETURN e.name as name, degree
    """
    # ... execute query
```

**Expected Impact:** X-2 score 30→60, evidence discovery 40%→60%

---

#### 1.2 Increase Top-K for Hub Extraction
```python
# orchestrator.py: _execute_route_3_global_search()
hub_entities = await self.hub_extractor.extract_hubs(
    matched_communities,
    top_k=10  # Increase from 5 to 10
)
```

**Expected Impact:** Avg hub entities 1.6→3.5

---

#### 1.3 Add Query Expansion to CommunityMatcher
```python
# community_matcher.py
def _expand_keywords(self, keywords: List[str]) -> List[str]:
    """Expand keywords with common synonyms."""
    expansions = {
        "important": ["key", "main", "primary", "critical"],
        "entities": ["parties", "organizations", "persons"],
        "terms": ["provisions", "conditions", "clauses"],
        # ... more mappings
    }
    expanded = set(keywords)
    for kw in keywords:
        if kw in expansions:
            expanded.update(expansions[kw])
    return list(expanded)
```

**Expected Impact:** Theme coverage 42%→55%

---

### Phase 2: Structural Improvements (2 hours) 🎯 High Value

#### 2.1 Replace NLP Keyword Extraction with Entity Sampling
Instead of extracting generic keywords, sample actual entity names from Neo4j:

```python
# community_matcher.py
async def match_communities(self, query: str, top_k: int):
    # Get query embedding
    query_embedding = await self._embed_query(query)
    
    # Sample entities semantically similar to query
    candidate_entities = await self._sample_entities_by_embedding(
        query_embedding, 
        sample_size=20
    )
    
    # Create community from these entities
    community = {
        "id": f"dynamic-{hash(query)}",
        "keywords": candidate_entities,  # Actual entity names!
        "title": f"Query-relevant entities: {len(candidate_entities)} sampled"
    }
    return [community]

async def _sample_entities_by_embedding(self, query_emb, sample_size):
    """Query Neo4j for entities with similar embeddings."""
    query = """
    MATCH (e:Entity)
    WHERE e.embedding IS NOT NULL
    WITH e, gds.similarity.cosine(e.embedding, $query_emb) as score
    ORDER BY score DESC
    LIMIT $sample_size
    RETURN e.name as name, score
    """
    # ... execute
```

**Expected Impact:**
- Keyword quality: generic→specific
- X-2 score: 30→70
- Theme coverage: 42%→60%

---

#### 2.2 Implement Adaptive PPR Expansion
Dynamically adjust PPR depth based on initial results:

```python
# orchestrator.py
async def _execute_route_3_global_search(self, query, response_type):
    # ... get hub_entities
    
    # Adaptive PPR: Start conservative, expand if needed
    evidence_nodes = await self.hipporag_retriever.ppr_retrieve(
        hub_entities, 
        top_k=50
    )
    
    # If insufficient evidence, expand
    if len(evidence_nodes) < 3:
        logger.info("expanding_ppr_for_more_evidence")
        evidence_nodes = await self.hipporag_retriever.ppr_retrieve(
            hub_entities,
            top_k=100,  # Double expansion
            damping=0.8   # More aggressive spreading
        )
```

**Expected Impact:** Evidence threshold met: 40%→70%

---

### Phase 3: Advanced Enhancements (4 hours) 🚀 High Impact

#### 3.1 Hybrid Community Generation
Combine NLP keywords + entity sampling + pre-computed communities:

```python
async def match_communities(self, query: str, top_k: int):
    # Strategy 1: Try pre-computed communities (if exist)
    precomputed = await self._match_precomputed(query, top_k)
    
    # Strategy 2: Entity sampling via embeddings
    sampled = await self._sample_entities_by_embedding(query, 20)
    
    # Strategy 3: NLP keyword extraction (fallback)
    keywords = self._extract_keywords_nlp(query)
    
    # Merge strategies
    return self._merge_communities(precomputed, sampled, keywords)
```

---

#### 3.2 Add Entity Type Filtering
```python
# hub_extractor.py
async def _query_neo4j_hubs_by_keywords(self, keywords, top_k, entity_types=None):
    type_filter = ""
    if entity_types:
        type_filter = "AND e.type IN $entity_types"
    
    query = f"""
    MATCH (e:Entity)-[r]-()
    WHERE toLower(e.name) CONTAINS ANY $keywords
      {type_filter}
    WITH e, count(r) as degree
    ORDER BY degree DESC
    LIMIT $top_k
    RETURN e.name, e.type, degree
    """
```

---

#### 3.3 LLM-Based Entity Selection (Premium Mode)
For critical queries, use LLM to select relevant entities:

```python
async def _llm_select_entities(self, query: str, candidate_entities: List[str]):
    """Use LLM to filter entities relevant to query."""
    prompt = f"""Given this query: "{query}"
    
    Select the 5 most relevant entities from this list:
    {', '.join(candidate_entities[:50])}
    
    Return only entity names, comma-separated."""
    
    response = await self.llm.complete(prompt, temperature=0)
    return [e.strip() for e in response.text.split(',')]
```

---

## Implementation Priority

| Phase | Task | Impact | Effort | Priority |
|-------|------|--------|--------|----------|
| 1.1 | Degree-based fallback | High | 30min | ✅ Do Now |
| 1.2 | Increase top-K | Medium | 5min | ✅ Do Now |
| 1.3 | Query expansion | Medium | 30min | ✅ Do Now |
| 2.1 | Entity sampling | High | 2hrs | 🎯 Next |
| 2.2 | Adaptive PPR | Medium | 1hr | 🎯 Next |
| 3.1 | Hybrid communities | High | 3hrs | 🚀 Later |
| 3.2 | Entity type filtering | Low | 1hr | 🚀 Later |
| 3.3 | LLM entity selection | Medium | 2hrs | 🚀 Later |

---

## Expected Outcomes

### After Phase 1 (1 hour)
- Average Score: **64→72/100** (+8)
- Theme Coverage: **42%→55%** (+13%)
- Evidence Threshold Met: **40%→60%** (+20%)
- Avg Hub Entities: **1.6→3.5** (+1.9)

### After Phase 2 (3 hours total)
- Average Score: **72→80/100** (+8)
- Theme Coverage: **55%→65%** (+10%)
- Evidence Threshold Met: **60%→75%** (+15%)
- Low-performers fixed: T-1 (35→60), X-2 (30→70)

### After Phase 3 (7 hours total)
- Average Score: **80→85/100** (+5)
- Theme Coverage: **65%→75%** (+10%)
- Production-ready global search
- Handles edge cases gracefully

---

## Testing Strategy

1. **Run thematic benchmark after each phase:**
   ```bash
   python3 scripts/benchmark_route3_thematic.py \
     --group-id test-5pdfs-nlp-1767461862
   ```

2. **Compare metrics:**
   - Overall score trend
   - Low-performer improvements
   - Evidence discovery rate

3. **Manual validation:**
   - Check X-2 response (should find entities now)
   - Verify hub_entities count increases
   - Ensure no regressions on high-performers

---

## Quick Start: Phase 1 Implementation

Ready to implement Phase 1 improvements now? They take ~1 hour and provide immediate +8 point score increase.
