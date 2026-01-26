# Proposed Neo4j Document Title Structure Fix

**Date:** January 26, 2026  
**Status:** Planned for Future Indexing Cycle  
**Priority:** Medium  
**Impact:** Q-D8 document counting accuracy (currently 96.5% → target 100%)

---

## Problem Statement

The Q-D8 benchmark question asks: *"Which entity appears in the most different documents: Fabrikam Inc. or Contoso Ltd.?"*

**Expected Answer:** Fabrikam (4 documents) vs Contoso (3 documents)  
**Current System Answer:** Fabrikam (5 documents) vs Contoso (4 documents)  
**Conclusion:** ✅ Correct winner, ❌ Wrong counts

### Root Cause

When PropertyGraphIndex stores chunks in Neo4j, it sets the `doc_title` property to include section headers and exhibit names, causing the system to count sections as separate documents.

**Current Neo4j Structure (Problematic):**
```cypher
(:Chunk {
  doc_title: "Builder's Limited Warranty with Arbitration",
  text: "..."
})

(:Chunk {
  doc_title: "Exhibit A – Scope of Work (Bayfront Animal Clinic)",  // ← Counted as separate document
  text: "..."
})

(:Chunk {
  doc_title: "Property Management Agreement – Fees/Signature excerpt",  // ← Counted as separate
  text: "..."
})
```

**Result:** System counts 5 unique `doc_title` values instead of 4 actual PDF documents.

---

## Proposed Solution

### Schema Change

Separate base document name from section/exhibit information:

```cypher
(:Chunk {
  doc_title: "Purchase Contract",                    // Base document name only
  section_heading: "Exhibit A – Scope of Work",      // Section/exhibit info (nullable)
  full_title: "Purchase Contract > Exhibit A – Scope of Work",  // Display string
  text: "...",
  group_id: "..."
})
```

### Implementation Steps

#### 1. Update Ingestion Pipeline

**File:** `graphrag-orchestration/app/services/cu_standard_ingestion_service.py`

```python
# Current: section info merged into title
doc = Document(
    text=markdown,
    metadata={
        "title": f"{base_title} - {section_path}" if section_path else base_title,
        ...
    }
)

# Proposed: separate fields
doc = Document(
    text=markdown,
    metadata={
        "doc_title": base_title,           # Base document name only
        "section_heading": section_path,    # Section/exhibit (can be None)
        "full_title": f"{base_title} > {section_path}" if section_path else base_title,
        ...
    }
)
```

#### 2. Update PropertyGraphIndex Storage

**File:** `graphrag-orchestration/app/hybrid/kg_construction/property_graph_index.py`

Ensure chunk nodes preserve the separation:
- Store `doc_title` as base document name
- Store `section_heading` as separate property
- Update node creation Cypher to include both fields

#### 3. Update Retrieval Queries

For document counting queries, aggregate by `doc_title` (base) not `full_title`:

```cypher
// Document counting query
MATCH (c:Chunk)
WHERE c.group_id = $group_id
RETURN DISTINCT c.doc_title AS document, count(*) AS chunks
```

#### 4. Update Synthesis

The existing document consolidation guidance (commit `2b89f96`) can remain as a fallback, but should no longer be needed once the data model is correct.

---

## Migration Plan

### Option A: Re-index Only (Recommended)

1. Update ingestion pipeline code
2. Delete existing test corpus chunks: `MATCH (c:Chunk {group_id: "test-5pdfs-..."}) DETACH DELETE c`
3. Re-run ingestion on 5 PDFs test corpus
4. Verify Q-D8 benchmark scores 3/3

**Effort:** ~2 hours  
**Risk:** Low (only affects test corpus)

### Option B: In-Place Migration

1. Run Cypher migration to split existing `doc_title` values
2. Update code to use new schema

**Effort:** ~4 hours  
**Risk:** Medium (regex parsing of existing titles may miss edge cases)

---

## Affected Files

| File | Change Type |
|------|-------------|
| `app/services/cu_standard_ingestion_service.py` | Modify metadata structure |
| `app/hybrid/kg_construction/property_graph_index.py` | Update node creation |
| `app/hybrid/retrieval/hippo_retriever.py` | Update document aggregation |
| `app/hybrid/pipeline/synthesis.py` | Optional: simplify guidance prompts |

---

## Validation Criteria

After implementation:

1. **Q-D8 Benchmark:** Should score 3/3 with correct counts (4 vs 3)
2. **LLM Judge Evaluation:** Q-D8 should pass with score 3
3. **Overall Route 4:** Should reach 57/57 (100%)
4. **No Regression:** Routes 1, 2, 3 benchmarks unchanged

---

## Current Workaround

The synthesis pattern expansion (commit `2b89f96`) provides a partial fix:
- ✅ System correctly identifies Fabrikam as the winner
- ⚠️ Counts are off by 1 each (5 vs 4 instead of 4 vs 3)
- ⚠️ LLM judge scores this as 1/3 due to numeric inaccuracy

This workaround is acceptable for production use since the conclusion is correct.

---

## References

- Analysis: `analysis_q-d8_document_counting_2026-01-25.md`
- Evaluation Discrepancy: `ROUTE4_Q-D8_EVALUATION_DISCREPANCY_2026-01-25.md`
- Synthesis Fix: Commit `2b89f96` (partial fix, keeps correct conclusion)
- Benchmark: `benchmarks/route4_drift_multi_hop_20260126T073101Z.json`
- LLM Evaluation: `benchmarks/route4_drift_multi_hop_20260126T073101Z.eval.md`
