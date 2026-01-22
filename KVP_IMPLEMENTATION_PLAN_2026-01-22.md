# Azure DI Key-Value Pair Extraction Implementation Plan

**Date:** January 22, 2026  
**Status:** ✅ COMPLETED  
**Estimated Effort:** ~5 hours

---

## Overview

Enable Azure Document Intelligence key-value pair (KVP) extraction to create high-precision `KeyValue` nodes for deterministic field lookups. KVPs will be **section-aware**, aligning with the core architecture principle that sections are the foundation for ground truth verification.

---

## Architecture Alignment

### Core Principle
> **Section-awareness is the foundation. KVPs, Tables, Chunks, and Entities all link to Sections for cohesive, deterministic operation.**

### Graph Structure (Post-Implementation)

```
(:Document)
    ├── [:HAS_SECTION] -> (:Section)
    │       ├── [:SUBSECTION_OF] -> (:Section)  // Hierarchy
    │       ├── <- [:IN_SECTION] - (:TextChunk)
    │       ├── <- [:IN_SECTION] - (:Table)
    │       ├── <- [:IN_SECTION] - (:KeyValue)  // NEW
    │       └── <- [:APPEARS_IN_SECTION] - (:Entity)
    └── [:PART_OF] <- (:TextChunk)
```

### Node Alignment Summary

| Node Type | Primary Relationship | Foundation |
|-----------|---------------------|------------|
| `TextChunk` | `[:IN_SECTION]->(:Section)` | ✅ Section |
| `Table` | `[:IN_SECTION]->(:Section)` | ✅ Section |
| `Entity` | `[:APPEARS_IN_SECTION]->(:Section)` | ✅ Section |
| **`KeyValue`** | **`[:IN_SECTION]->(:Section)`** | ✅ Section |

---

## Cost Analysis

| Component | Cost | Notes |
|-----------|------|-------|
| `prebuilt-layout` | $10/1K pages | Base model |
| `KEY_VALUE_PAIRS` feature | $6/1K pages | Add-on |
| **Total with KVP** | **$16/1K pages** | One-time indexing cost |

**Justification:** Tool is built for precision. One-time indexing cost enables deterministic field lookups and avoids LLM hallucinations on critical fields.

---

## Implementation Phases

### Phase 1: DI Service — Extract KVPs with Section Association ✅

**File:** `app/services/document_intelligence_service.py`

| Step | Action | Status |
|------|--------|--------|
| 1.1 | Add `DocumentAnalysisFeature` to imports | ✅ |
| 1.2 | Add `features=[DocumentAnalysisFeature.KEY_VALUE_PAIRS]` to `begin_analyze_document()` | ✅ |
| 1.3 | Create `_extract_key_value_pairs(result, sections)` method | ✅ |
| 1.4 | Attach KVPs to section metadata in `_build_section_aware_documents()` | ✅ |

**KVP Data Structure:**
```python
{
    "key": "Policy Number",
    "value": "POL-2024-001",
    "confidence": 0.95,
    "section_id": "section_abc123",
    "section_path": ["Coverage Details", "Policy Information"],
    "page_number": 3,
    "key_span": {"offset": 1234, "length": 13},
    "value_span": {"offset": 1250, "length": 12},
}
```

---

### Phase 2: Neo4j Store — KeyValue Nodes with Section Relationship ✅

**File:** `app/hybrid/services/neo4j_store.py`

| Step | Action | Status |
|------|--------|--------|
| 2.1 | Add `KeyValue` dataclass | ✅ |
| 2.2 | Create `_create_keyvalue_nodes()` method | ✅ |
| 2.3 | Create relationships: `[:IN_SECTION]`, `[:IN_CHUNK]`, `[:IN_DOCUMENT]` | ✅ |
| 2.4 | Add schema constraint for KeyValue in `ensure_indexes()` | ✅ |

**Node Schema:**
```cypher
(:KeyValue {
  id: string,           -- "{chunk_id}_kv_{index}"
  key: string,          -- Raw key text
  value: string,        -- Raw value text
  key_embedding: [float], -- For semantic key matching
  confidence: float,
  page_number: int,
  section_path: [string],
  group_id: string
})
```

**Relationships:**
```cypher
-- Primary: Section association (deterministic)
(kv:KeyValue)-[:IN_SECTION]->(s:Section)

-- Secondary: Chunk association (via section)
(kv:KeyValue)-[:IN_CHUNK]->(c:TextChunk)

-- Tertiary: Document scope
(kv:KeyValue)-[:IN_DOCUMENT]->(d:Document)
```

---

### Phase 3: Pipeline — Section-Aware KVP Processing ✅

**File:** `app/hybrid/indexing/lazygraphrag_pipeline.py`

| Step | Action | Status |
|------|--------|--------|
| 3.1 | Pass KVP metadata through chunk processing | ✅ (via DI service) |
| 3.2 | Associate KVPs to sections using span overlap | ✅ (in DI service) |
| 3.3 | Embed unique keys with batch deduplication | ✅ `_embed_keyvalue_keys()` |
| 3.4 | Track `stats["key_values"]` in indexing response | ✅ |

**Key Embedding Deduplication (Implemented):**
```python
# In _embed_keyvalue_keys():
# Deduplicate keys (case-insensitive) for efficient batch embedding
key_to_ids: Dict[str, List[str]] = {}
for kvp in kvps_to_embed:
    normalized_key = (kvp["key"] or "").strip().lower()
    if normalized_key:
        key_to_ids.setdefault(normalized_key, []).append(kvp["id"])
```

---

### Phase 4: Route 1 — Section-Scoped KVP Query ✅

**File:** `app/hybrid/orchestrator.py`

| Step | Action | Status |
|------|--------|--------|
| 4.1 | Add `_extract_from_keyvalue_nodes()` method | ✅ |
| 4.2 | Query KVPs via section graph | ✅ |
| 4.3 | Semantic key matching with section scope | ✅ |
| 4.4 | Update Route 1 flow: KVP → Table → LLM fallback | ✅ |

**Query Pattern (Implemented):**
```cypher
// Find KVPs in sections related to retrieved chunks
MATCH (c:TextChunk)-[:IN_SECTION]->(s:Section)<-[:IN_SECTION]-(kv:KeyValue)
WHERE c.id IN $chunk_ids AND c.group_id = $group_id
  AND kv.key_embedding IS NOT NULL
WITH DISTINCT kv, 
     vector.similarity.cosine(kv.key_embedding, $query_embedding) AS similarity
WHERE similarity > 0.85
RETURN kv.key, kv.value, kv.confidence, similarity
ORDER BY similarity DESC, confidence DESC
LIMIT 5
```

---

### Phase 5: Cleanup & Documentation ✅

| Step | Action | Status |
|------|--------|--------|
| 5.1 | Archive `lazygraphrag_indexing_pipeline.py` | ⏭️ Skipped (wrapper only) |
| 5.2 | Update `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` | ✅ |

---

## Testing Checkpoints

| Checkpoint | Validation | Status |
|------------|------------|--------|
| After Phase 1 | DI response contains `key_value_pairs` | ⬜ |
| After Phase 2 | `MATCH (kv:KeyValue) RETURN count(kv)` shows nodes | ⬜ |
| After Phase 3 | Indexing stats include `key_values` count | ⬜ |
| After Phase 4 | Query "What is the policy number?" hits KVP first | ⬜ |

---

## Route Benefits Summary

| Route | KVP Benefit |
|-------|-------------|
| **Route 1 (Vector RAG)** | Direct field lookup before table/LLM fallback |
| **Route 2 (Local Search)** | KVP values can seed entity matching |
| **Route 3 (Global Search)** | Section-scoped KVPs improve precision |
| **Route 4 (DRIFT)** | KVPs provide anchors for multi-hop reasoning |

---

## Rollback Plan

If issues arise:
1. Set `ENABLE_KVP_EXTRACTION=0` env var (if we add the flag)
2. Delete KVP nodes: `MATCH (kv:KeyValue) DETACH DELETE kv`
3. Re-index without KVP feature

---

## References

- Azure DI Key-Value Pairs: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept-key-value
- Existing Table node implementation: `neo4j_store.py:_create_table_nodes()`
- Section graph implementation: `lazygraphrag_pipeline.py:_build_section_graph()`
