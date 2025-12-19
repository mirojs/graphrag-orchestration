# GraphRAG Query Schema Enhancement Plan

**Date:** 2025-12-19  
**Status:** Planning Phase  
**Priority:** High (Improves query accuracy and performance)

## Problem Statement

Our current V3 implementation uses LlamaIndex's `SchemaLLMPathExtractor` for **extraction** (indexing time), but we don't have schema-aware **retrieval** (query time). This creates several issues:

### Current State
- ✅ **Extraction**: Uses `SchemaLLMPathExtractor` with default entities/relations
- ✅ **Storage**: Neo4j stores entities with proper labels (PERSON, ORGANIZATION, etc.)
- ❌ **Query**: No schema-aware retrieval (only vector + full-text hybrid search)
- ❌ **Text-to-Cypher**: Cannot translate natural language to graph traversal
- ❌ **Schema Introspection**: No way to view/validate extracted schema
- ❌ **Query Routing**: All queries use same retrieval path regardless of complexity

### Impact
1. **Missing Relationship Queries**: "Who works at Microsoft?" requires graph traversal, not just keyword match
2. **No Multi-hop Reasoning**: "Which companies in London compete with Apple's suppliers?" needs Cypher
3. **Inefficient Queries**: Simple questions use expensive hybrid search when vector would suffice
4. **No Schema Validation**: Can't verify extraction schema matches query expectations

## LlamaIndex Query Schema Patterns

Based on the conversation, LlamaIndex provides these components for schema-aware querying:

### 1. Schema Definition (Extraction Time)
```python
from typing import Literal

entities = Literal["PERSON", "ORGANIZATION", "LOCATION", "PRODUCT"]
relations = Literal["WORKS_AT", "LOCATED_IN", "DEVELOPED_BY", "COMPETES_WITH"]

validation_schema = {
    "PERSON": ["WORKS_AT"],
    "ORGANIZATION": ["LOCATED_IN", "DEVELOPED_BY", "COMPETES_WITH"],
}

extractor = SchemaLLMPathExtractor(
    possible_entities=entities,
    possible_relations=relations,
    kg_validation_schema=validation_schema,
    strict=True  # Enforce schema
)
```

### 2. Schema-Aware Retrievers (Query Time)
- **LLMSynonymRetriever**: Expands query terms to match entity labels
- **VectorContextRetriever**: Vector search on entity names/descriptions
- **TextToCypherRetriever**: Generates Cypher from natural language + schema
- **CypherTemplateRetriever**: Pre-defined Cypher templates with parameter filling

### 3. Self-Healing Queries
- Catch Cypher syntax errors
- Feed error + schema back to LLM
- Retry with corrected query
- Trade-off: +3-5s latency vs guaranteed correctness

### 4. Concurrent Retrieval
- Run Vector + Cypher searches in parallel with `asyncio`
- Reduces latency for hybrid approach
- Router pattern: simple queries → vector only, complex → graph

## Proposed Implementation Plan

### Phase 1: Schema Introspection & Documentation (Week 1)
**Goal:** Make extraction schema visible and manageable

**Tasks:**
1. Add schema introspection API endpoint
   ```python
   GET /graphrag/v3/schema/{group_id}
   Response: {
       "entities": ["PERSON", "ORGANIZATION", ...],
       "relations": ["WORKS_AT", "LOCATED_IN", ...],
       "validation": {...},
       "statistics": {
           "entity_counts": {"PERSON": 123, ...},
           "relation_counts": {"WORKS_AT": 45, ...}
       }
   }
   ```

2. Schema visualization endpoint (Jupyter-compatible)
   ```python
   GET /graphrag/v3/schema/{group_id}/visualize
   Returns: Interactive graph widget or static diagram
   ```

3. Schema validation during indexing
   - Log when entities/relations don't match schema
   - Alert if extraction produces unexpected labels
   - Track schema drift over time

**Files to Create:**
- `app/v3/services/schema_manager.py` - Schema introspection logic
- `app/v3/api/schema.py` - REST API endpoints
- `app/v3/visualization/schema_viz.py` - Graph visualization

### Phase 2: Text-to-Cypher Retrieval (Week 2)
**Goal:** Enable natural language → Cypher query translation

**Tasks:**
1. Implement `TextToCypherRetriever` wrapper
   ```python
   class GraphRAGCypherRetriever:
       def __init__(self, neo4j_store, llm, schema_manager):
           self.store = neo4j_store
           self.llm = llm
           self.schema = schema_manager.get_schema()
       
       def retrieve(self, query: str) -> List[Entity]:
           # 1. Generate Cypher from query + schema
           cypher = self._text_to_cypher(query)
           # 2. Execute against Neo4j
           # 3. Return as Entity objects
   ```

2. Prompt engineering for Cypher generation
   - Include schema in system prompt
   - Few-shot examples for common patterns
   - Template library for frequent queries

3. Cypher validation before execution
   - Check for forbidden operations (DELETE, DROP)
   - Validate node labels match schema
   - Ensure group_id isolation in query

**Files to Create:**
- `app/v3/services/cypher_retriever.py` - Text-to-Cypher logic
- `app/v3/prompts/cypher_templates.py` - Prompt templates
- `app/v3/validation/cypher_validator.py` - Query validation

### Phase 3: Self-Healing Queries (Week 3)
**Goal:** Automatically recover from Cypher generation errors

**Tasks:**
1. Implement retry logic with error feedback
   ```python
   class SelfHealingCypherRetriever:
       async def retrieve_with_healing(self, query: str, max_retries: int = 2):
           for attempt in range(max_retries):
               try:
                   cypher = self.generate_cypher(query)
                   return self.execute(cypher)
               except Neo4jError as e:
                   if attempt == max_retries - 1:
                       raise
                   # Feed error back to LLM
                   cypher = self.heal_cypher(query, cypher, str(e))
   ```

2. Performance monitoring
   - Track healing frequency (should be <10%)
   - Log failed queries for prompt improvement
   - Alert if healing rate increases (schema drift indicator)

3. Async execution to minimize latency
   - Use asyncio for concurrent retrieval
   - Stream partial results while healing
   - Timeout after 10 seconds max

**Files to Create:**
- `app/v3/services/healing_retriever.py` - Self-healing logic
- `app/v3/monitoring/query_metrics.py` - Performance tracking

### Phase 4: Query Router & Hybrid Retrieval (Week 4)
**Goal:** Automatically select optimal retrieval strategy per query

**Tasks:**
1. Implement query classifier
   ```python
   class QueryRouter:
       def classify(self, query: str) -> QueryType:
           # Simple: "What is X?" → Vector only
           # Relationship: "Who works at X?" → Cypher
           # Complex: "Find X where Y and Z" → Hybrid
           # Global: "Summarize all X" → Community summaries
   ```

2. Concurrent hybrid retrieval
   ```python
   async def hybrid_retrieve(query: str):
       vector_task = vector_retriever.aretrieve(query)
       cypher_task = cypher_retriever.aretrieve(query)
       results = await asyncio.gather(vector_task, cypher_task)
       return self.merge_results(results)
   ```

3. Performance comparison dashboard
   - A/B test: old retrieval vs. schema-aware
   - Measure: latency, accuracy, user satisfaction
   - Automatic fallback if schema queries fail

**Files to Create:**
- `app/v3/services/query_router.py` - Query classification
- `app/v3/services/hybrid_retriever.py` - Concurrent retrieval
- `app/v3/api/query_v3_enhanced.py` - New query endpoints

### Phase 5: Custom Schema Support (Week 5)
**Goal:** Allow users to define domain-specific schemas

**Tasks:**
1. Schema definition API
   ```python
   POST /graphrag/v3/schema/{group_id}
   Body: {
       "entities": ["INVOICE", "CONTRACT", "VENDOR"],
       "relations": ["ISSUED_BY", "REFERENCES"],
       "validation": {
           "INVOICE": ["ISSUED_BY", "REFERENCES"]
       }
   }
   ```

2. Schema-aware re-indexing
   - Apply new schema to existing documents
   - Migrate entities to new labels
   - Preserve relationships where possible

3. Schema templates for common domains
   - Financial documents: INVOICE, PAYMENT, ACCOUNT
   - Legal documents: CONTRACT, PARTY, CLAUSE
   - Scientific papers: AUTHOR, PUBLICATION, CITATION

**Files to Create:**
- `app/v3/api/schema_management.py` - Schema CRUD endpoints
- `app/v3/services/schema_migration.py` - Schema update logic
- `app/v3/templates/` - Pre-built schema templates

## Architecture Changes

### Current Architecture
```
Query → Hybrid Search (Vector + FullText) → Entities → LLM Synthesis
         ↓
    No schema awareness
```

### Enhanced Architecture
```
Query → Query Router → [Vector | Cypher | Hybrid | Community]
         ↓              ↓
    Schema Classifier   Schema-Aware Retrievers
         ↓              ↓
    Route Decision      Self-Healing if needed
                        ↓
                   Concurrent Execution
                        ↓
                   Result Merging → LLM Synthesis
```

## Performance Targets

| Metric | Current | Target (Phase 4) |
|--------|---------|------------------|
| Simple Query Latency | 2-3s | 1-2s (vector only) |
| Relationship Query | Not supported | 3-5s (Cypher) |
| Complex Query | 2-3s | 4-6s (concurrent hybrid) |
| Query Success Rate | 85% (hybrid misses) | 95% (schema-aware) |
| Healing Required | N/A | <10% of queries |

## Risks & Mitigations

### Risk 1: Increased Latency
**Impact:** Self-healing adds 3-5s per failed query  
**Mitigation:**
- Use fast model (GPT-4o-mini) for initial attempt
- Concurrent retrieval to mask healing time
- Cache successful Cypher patterns
- Router to avoid Cypher for simple queries

### Risk 2: Schema Drift
**Impact:** Extraction schema diverges from query expectations  
**Mitigation:**
- Schema validation during indexing
- Monitoring alerts for unexpected labels
- Regular schema audits
- Version control for schemas

### Risk 3: Cypher Injection
**Impact:** Malicious queries could exploit graph access  
**Mitigation:**
- Query validation before execution
- Whitelist allowed Cypher operations
- Enforce group_id in all generated queries
- Rate limiting per user/group

### Risk 4: Complexity Overload
**Impact:** Too many retrieval paths confuses users  
**Mitigation:**
- Simple default: hybrid retrieval (current behavior)
- Advanced: opt-in schema-aware mode
- Clear documentation and examples
- Gradual rollout with A/B testing

## Success Metrics

### Quantitative
- [ ] Query accuracy +10% (measured by user thumbs up/down)
- [ ] Relationship queries 95% success rate
- [ ] Average latency increase <1s
- [ ] Schema awareness adoption >50% of groups

### Qualitative
- [ ] Users can query "Who works at X?" successfully
- [ ] Multi-hop queries ("X's suppliers in Y") work
- [ ] Schema visualization helps users understand data
- [ ] Debugging tools reduce support tickets

## Open Questions

1. **Schema Granularity**: Should we support per-document schemas or only per-group?
2. **Schema Evolution**: How to handle schema changes without full re-indexing?
3. **Community Summaries**: Do we need schema-aware community detection?
4. **Cypher Templates**: Should we pre-build common queries or always generate?
5. **Fallback Strategy**: If Cypher fails after healing, fall back to hybrid or error?

## References

- LlamaIndex PropertyGraph docs: https://docs.llamaindex.ai/en/stable/module_guides/indexing/lpg_index_guide/
- Neo4j Cypher docs: https://neo4j.com/docs/cypher-manual/current/
- Microsoft GraphRAG paper: https://arxiv.org/abs/2404.16130
- Our current implementation: `app/v3/services/indexing_pipeline.py` (lines 640-710)

## Next Steps

1. **Review & Approve**: Team review of this plan
2. **Phase 1 Prototype**: Build schema introspection in 2 days
3. **User Testing**: Test with phase1-v3-validation group
4. **Iterate**: Adjust based on feedback
5. **Production Rollout**: Gradual deployment starting Phase 2

---

**Document Owner:** AI Architecture Team  
**Last Updated:** 2025-12-19  
**Next Review:** After Phase 1 completion
