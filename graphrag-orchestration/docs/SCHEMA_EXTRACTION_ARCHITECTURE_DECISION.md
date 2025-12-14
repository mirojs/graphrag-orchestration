# Schema Extraction Architecture Decision Record

## Date: December 12, 2025

## Context

We encountered an issue where `SchemaLLMPathExtractor` with `strict=True` was returning 0 entities and 0 relationships despite the LLM successfully extracting valid triplets.

### Root Cause Analysis

The issue was traced to the `_prune_invalid_triplets` method in LlamaIndex's `SchemaLLMPathExtractor`. When `strict=True`:

1. The LLM extracts triplets like `(Microsoft, HAS, GitHub)` → `(ORGANIZATION, HAS, ORGANIZATION)`
2. These are validated against `kg_validation_schema` which contains only 27 specific allowed patterns
3. `(ORGANIZATION, HAS, ORGANIZATION)` is NOT in the default allowed patterns
4. Valid extractions are silently pruned → 0 results

**LlamaIndex Default Validation Schema (27 patterns):**
```python
{
    'relationships': [
        ('PRODUCT', 'USED_BY', 'PRODUCT'),
        ('PRODUCT', 'USED_FOR', 'MARKET'),
        ('ORGANIZATION', 'LOCATED_IN', 'LOCATION'),
        ('PERSON', 'BORN_IN', 'LOCATION'),
        # ... only 27 specific combinations
    ]
}
```

## Industry Research

We researched how major GraphRAG implementations handle schema validation:

### 1. Microsoft GraphRAG (Original)
- **Method:** Text parsing with custom delimiters (`<|>` and `##`)
- **Schema Validation:** NONE - entity types in prompt are guidance only
- **Triplet Validation:** NONE - any entity can connect to any other
- **Source:** `graphrag/index/operations/extract_graph/graph_extractor.py`

```python
DEFAULT_ENTITY_TYPES = ["organization", "person", "geo", "event"]
# Just inserted into prompt, not enforced
```

### 2. Neo4j GraphRAG Python
- **Method:** JSON extraction via LLM
- **Schema Validation:** NONE - schema is optional guidance for LLM
- **Triplet Validation:** NONE
- **Error Handling:** `OnError.IGNORE` by default
- **Source:** `neo4j_graphrag/experimental/components/entity_relation_extractor.py`

### 3. Cognee (LlamaIndex Integration)
- **Method:** Free-form LLM extraction
- **Schema Validation:** NONE
- **Triplet Validation:** NONE
- **Focus:** Graph completion and semantic search

### 4. LlamaIndex SchemaLLMPathExtractor
- **Method:** Pydantic structured output
- **Schema Validation:** YES - Literal types for entities/relations
- **Triplet Validation:** YES (when `strict=True`)
- **The only framework with strict validation**

## Decision Options

### Option 1: `strict=False`
- ✅ Uses SchemaLLMPathExtractor (maintains architecture)
- ✅ Uses Pydantic structured output
- ✅ Constrains entity types to Literal types
- ✅ Constrains relation types to Literal types
- ❌ Does NOT validate triplet patterns

### Option 2: `strict=True` + Custom kg_validation_schema
- ✅ Full schema enforcement
- ✅ Semantic triplet validation
- ⚠️ Requires maintaining a comprehensive validation schema
- ⚠️ Risk of over-pruning valid patterns

### Option 3: `SimpleLLMPathExtractor`
- ❌ **REJECTED** - Violates architecture
- ❌ No schema guidance
- ❌ Free-form entity/relation types

## Decision

**We chose Option 1: `strict=False`**

### Rationale:

1. **Industry Alignment:** All major GraphRAG implementations (Microsoft, Neo4j, Cognee) do NOT enforce triplet pattern validation.

2. **Type Safety Preserved:** With `strict=False`, we STILL get:
   - Pydantic structured output parsing
   - Entity types constrained to `Literal["PERSON", "ORGANIZATION", ...]`
   - Relation types constrained to `Literal["HAS", "LOCATED_IN", ...]`

3. **Better than Microsoft GraphRAG:** We have type-constrained extraction via Pydantic - something the original Microsoft GraphRAG doesn't have.

4. **Avoids Over-Pruning:** The default 27 patterns are too restrictive for general-purpose document processing.

## Implementation

```python
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor

extractor = SchemaLLMPathExtractor(
    llm=self.llm,
    possible_entities=None,  # Uses DEFAULT_ENTITIES (proper Literal type)
    possible_relations=None,  # Uses DEFAULT_RELATIONS (proper Literal type)
    strict=False,  # Disables triplet pattern validation
    num_workers=1,
    max_triplets_per_chunk=20,
)
```

### What `strict=False` Changes:
1. Entity/relation types are still constrained via Pydantic Literal types
2. Triplet patterns are NOT validated against `kg_validation_schema`
3. Any valid entity type can connect to any other via any valid relation type

## Future Considerations

If we need tighter validation in the future:

1. **Option A:** Provide comprehensive `kg_validation_schema` covering all reasonable patterns
2. **Option B:** Implement post-extraction validation/filtering based on domain rules
3. **Option C:** Use community detection + summarization to clean up noise (Microsoft's approach)

## Test Results

After implementing `strict=False`:
- **Before:** 0 entities, 0 relationships (all pruned)
- **After:** Multiple entities and relationships extracted correctly

## References

- LlamaIndex SchemaLLMPathExtractor: `llama-index-core/llama_index/core/indices/property_graph/transformations/schema_llm.py`
- Microsoft GraphRAG: https://github.com/microsoft/graphrag
- Neo4j GraphRAG Python: https://github.com/neo4j/neo4j-graphrag-python
- Cognee Integration: https://github.com/run-llama/llama_index/tree/main/llama-index-integrations/graph_rag/llama-index-graph-rag-cognee
