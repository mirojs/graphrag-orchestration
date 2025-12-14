# Entity Extraction Schema Decision - December 2025

## Summary

This document records the decision to use `strict=False` with `SchemaLLMPathExtractor` for entity/relationship extraction in our GraphRAG implementation.

## Problem

When using LlamaIndex's `SchemaLLMPathExtractor` with `strict=True`, we encountered 0 entities/relationships being extracted despite valid input text. The root cause was discovered through extensive debugging:

### Root Cause Analysis

1. **LLM was extracting valid triplets** - The LLM returned proper entities like:
   - `(ORGANIZATION, "Microsoft")` 
   - `(ORGANIZATION, "GitHub")`
   - `(MISCELLANEOUS, "7.5 billion dollars")`
   - With relation: `HAS`

2. **`_prune_invalid_triplets()` was removing ALL triplets** - The `strict=True` mode validates triplets against `kg_validation_schema`, which only allows specific `(EntityType, Relation, EntityType)` patterns:
   ```python
   # DEFAULT_VALIDATION_SCHEMA only allows 27 specific patterns like:
   ('ORGANIZATION', 'LOCATED_IN', 'LOCATION')  # ✅ Allowed
   ('ORGANIZATION', 'HAS', 'ORGANIZATION')      # ❌ NOT allowed!
   ```

3. **The LLM-extracted triplet `(ORGANIZATION, HAS, ORGANIZATION)` for "Microsoft HAS GitHub" was pruned** because this pattern isn't in the default validation schema.

## Industry Research

We analyzed how major GraphRAG implementations handle entity extraction:

### Microsoft GraphRAG (Original)
- **NO schema validation** at all
- Uses free-form text extraction with regex parsing
- Entity types are provided as guidance in the prompt, not for validation
- Relationships are extracted freely without type constraints
- Default entity types: `["organization", "person", "geo", "event"]`

```python
# From microsoft/graphrag - NO validation, just prompt guidance
GRAPH_EXTRACTION_PROMPT = """
- entity_type: One of the following types: [{entity_types}]
...
"""
```

### Neo4j GraphRAG Python
- **NO strict schema validation**
- Uses `OnError.IGNORE` to skip extraction errors gracefully
- Schema is **optional** - passed to guide the LLM but NOT used for post-validation
- Focus on flexibility over strict typing

```python
# From neo4j/neo4j-graphrag-python
extractor = LLMEntityRelationExtractor(
    llm=llm,
    on_error=OnError.IGNORE,  # Don't fail on extraction errors
)
# schema is guidance, not enforcement
```

### Cognee GraphRAG (LlamaIndex Integration)
- **NO strict schema validation**
- Uses LLM to extract entities/relations freely
- Builds ontology dynamically from extracted data
- Focus on graph completion and semantic search

### LlamaIndex SchemaLLMPathExtractor
- **Only implementation with strict validation**
- Even their docs show `strict=False` in examples:
```python
kg_extractor = SchemaLLMPathExtractor(
    llm=llm,
    strict=False,  # "Set to False to showcase..."
    possible_entities=None,  # USE DEFAULT ENTITIES
    possible_relations=None,  # USE DEFAULT RELATIONSHIPS
)
```

## Decision

**Use `strict=False` with explicit entity/relation type guidance.**

### What `strict=False` Does:
- ✅ Still uses `SchemaLLMPathExtractor` (maintains our architecture)
- ✅ Still uses Pydantic structured output for reliable parsing
- ✅ Still constrains entity types to `Literal["PERSON", "ORGANIZATION", ...]`
- ✅ Still constrains relation types to `Literal["HAS", "LOCATED_IN", ...]`
- ❌ Does NOT prune triplets based on `(EntityType, Relation, EntityType)` pattern validation

### Why This Is Acceptable:
1. **Industry Standard** - Microsoft, Neo4j, and Cognee all use schema-free or schema-guided (not schema-enforced) extraction
2. **Type Consistency** - Entity/relation types are still constrained via Pydantic Literal types
3. **LLM Trust** - Modern LLMs (GPT-4, etc.) produce reasonable extractions without needing post-validation
4. **Recall vs Precision** - For GraphRAG, higher recall (more relationships) is generally better than higher precision

## Alternative Approaches Considered

### Option 1: Custom `kg_validation_schema` (Rejected)
- Create permissive schema allowing all entity-type combinations
- Pros: Maintains `strict=True`
- Cons: 100+ pattern combinations needed, maintenance overhead, still might miss valid patterns

### Option 2: Fully permissive validation schema (Rejected)  
- Pass empty `kg_validation_schema={}` with `strict=True`
- Cons: Unclear behavior, potential edge cases

### Option 3: `strict=False` (Chosen)
- Simple, aligns with industry practice
- Clear semantics: types constrained, patterns free

## Implementation

```python
extractor = SchemaLLMPathExtractor(
    llm=self.llm,
    possible_entities=None,  # Uses DEFAULT_ENTITIES Literal type
    possible_relations=None,  # Uses DEFAULT_RELATIONS Literal type
    strict=False,  # Don't prune based on triplet patterns
    num_workers=1,
    max_triplets_per_chunk=20,
)
```

## Future Considerations

If extraction quality becomes an issue:
1. **Fine-tune entity types** - Customize `possible_entities` for your domain
2. **Add relation types** - Customize `possible_relations` for common patterns
3. **Post-processing** - Add custom validation/filtering after extraction
4. **Switch to Microsoft GraphRAG** - Consider using the original implementation directly

## References

- Microsoft GraphRAG: https://github.com/microsoft/graphrag
- Neo4j GraphRAG Python: https://github.com/neo4j/neo4j-graphrag-python
- LlamaIndex PropertyGraph: https://docs.llamaindex.ai/en/latest/examples/property_graph/
- Cognee GraphRAG: https://github.com/run-llama/llama_index/tree/main/llama-index-integrations/graph_rag/llama-index-graph-rag-cognee

## Date

Decision made: December 12, 2025
