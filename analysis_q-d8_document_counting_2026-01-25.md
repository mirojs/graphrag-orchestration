# Q-D8 Document Counting Issue Investigation

**Date:** January 25, 2026  
**Issue:** Q-D8 scored 1/3 in LLM judge evaluation  
**Overall Benchmark:** 55/57 (96.5%) - only Q-D8 failing  

---

## Problem Statement

**Question (Q-D8):**  
> Across the set, which entity appears in the most different documents: `Fabrikam Inc.` or `Contoso Ltd.`?

**Expected Answer:**  
- Fabrikam Inc.: 4 documents (warranty, holding tank, property management, purchase contract)
- Contoso Ltd.: 3 documents (holding tank, property management, purchase contract)
- **Winner: Fabrikam Inc.**

**Actual System Answer:**  
- Fabrikam Inc.: 5 documents
- Contoso Ltd.: 5 documents  
- **Result: Tie** ❌

**LLM Judge Reasoning:**
> The correct answer is that Fabrikam Inc. appears in more documents than Contoso Ltd. (4 vs 3). The system answer instead concludes they are tied and also miscounts the documents (treating Exhibit A and excerpts as separate documents), contradicting the expected ground truth.

---

## Investigation Findings

### System's Document Count

The system response shows:

**Fabrikam Inc. appears in:**
1. Builder's Limited Warranty with Arbitration
2. **Exhibit A – Scope of Work (Bayfront Animal Clinic)** ← Counted as separate
3. Holding Tank Servicing Contract
4. Property Management Agreement
5. Purchase Contract

**Contoso Ltd. appears in:**
1. Builder's Limited Warranty
2. **Exhibit A – Scope of Work** ← Counted as separate
3. Holding Tank Servicing Contract
4. Property Management Agreement
5. **Property Management Agreement – Fees/Signature excerpt** ← Counted as separate

### Root Cause Analysis

#### 1. **Chunk Metadata Structure**
Retrieval returns chunks with `document_title` field that includes section headers:
- `"Builder's Limited Warranty with Arbitration"`
- `"Exhibit A – Scope of Work (Bayfront Animal Clinic)"` ← Should be part of Purchase Contract
- `"Property Management Agreement – Fees/Signature excerpt"` ← Should be part of PMA

#### 2. **Graph Storage Issue**
When PropertyGraphIndex stores chunks in Neo4j, it sets the `doc_title` property to include section headers/exhibits instead of just the base document name.

**Ingestion Service (Correct):**
```python
# cu_standard_ingestion_service.py stores section info separately
doc = Document(
    text=markdown,
    metadata={
        "section_path": section_path,  # ← Separate field
        "url": url,
        "group_id": group_id
    }
)
```

**Storage Issue:**
PropertyGraphIndex combines section information into `doc_title` when creating chunk nodes, leading to:
- `doc_title: "Purchase Contract - Exhibit A"` instead of
- `doc_title: "Purchase Contract"` + `section: "Exhibit A"`

#### 3. **Existing Synthesis Guidance (Not Triggered)**

The synthesis prompt already has document consolidation guidance:
```python
document_guidance = """
IMPORTANT for Per-Document Queries:
- Count UNIQUE top-level documents only - do NOT create separate summaries for:
  * Document sections (e.g., "Section 2: Arbitration" belongs to parent document)
  * Exhibits, Appendices, Schedules (e.g., "Exhibit A" belongs to parent contract)
  * Repeated excerpts from the same document
- If you see "Purchase Contract" and "Exhibit A - Scope of Work", combine into ONE summary.
"""
```

**Problem:** This guidance is only added when `is_per_document_query=True`, which checks for:
```python
patterns = [
    "each document", "every document", "all documents",
    "summarize.*document", "list.*document"
]
```

Q-D8 query: "which entity appears in the most **different documents**" does NOT match these patterns.

---

## Metadata from Benchmark

**Query Decomposition:**
```json
{
  "sub_questions": [
    "Across the set, in how many different documents does the entity `Fabrikam Inc.` appear?",
    "Across the set, in how many different documents does the entity `Contoso Ltd.` appear?",
    "Across the set, which entity appears in the most different documents when comparing `Fabrikam Inc.` and `Contoso Ltd.`?"
  ],
  "confidence_score": 0.7,
  "confidence_loop_triggered": false,
  "entity_concentration": false
}
```

**Coverage Strategy:** `section_based_hybrid_reranked` (with our new keyword+semantic reranking)

**Why Entity Concentration Detection Didn't Trigger:**
- Confidence threshold: `confidence < 0.7 AND concentrated_entities`
- Actual confidence: `0.7` (exactly at threshold, not below)
- Entity concentration detection requires confidence < 0.7

---

## Solution Options

### Option 1: Synthesis Pattern Expansion (Recommended ✅)

**Change:** Expand pattern detection to trigger document consolidation guidance

**Current patterns:**
```python
patterns = [
    "each document", "every document", "all documents",
    "summarize.*document", "list.*document"
]
```

**Proposed addition:**
```python
patterns = [
    "each document", "every document", "all documents",
    "summarize.*document", "list.*document",
    "different documents",  # ← Add for Q-D8
    "how many documents",   # ← Coverage
    "most documents",       # ← Coverage
    "appears in.*documents" # ← Stronger match
]
```

**Pros:**
- Simple, targeted fix
- Low risk (only affects synthesis prompt)
- No re-indexing required
- Leverages existing consolidation logic
- Quick to test and deploy

**Cons:**
- Pattern-based detection might miss future edge cases
- Doesn't fix root cause in storage layer

---

### Option 2: Index Pipeline Refactor (Root Cause Fix)

**Change:** Modify PropertyGraphIndex to separate document name from section metadata

**Implementation:**
1. Store only base document name in `doc_title` field
2. Add new field `section_heading` for section/exhibit info
3. Add new field `full_title` for display purposes
4. Update retrieval queries to use base `doc_title` for document counting

**Example Neo4j schema:**
```cypher
(:Chunk {
  id: "doc_123_chunk_5",
  doc_title: "Purchase Contract",           // ← Base document only
  section_heading: "Exhibit A - Scope of Work",  // ← Section info
  full_title: "Purchase Contract > Exhibit A - Scope of Work",  // ← Display
  text: "...",
  group_id: "test-5pdfs-..."
})
```

**Pros:**
- Fixes root cause at storage layer
- Benefits all queries, not just document counting
- Cleaner data model
- Enables better document-level aggregation

**Cons:**
- Requires re-indexing all documents
- More invasive change (affects indexing, retrieval, synthesis)
- Higher risk of breaking existing functionality
- Longer implementation and testing time

---

## Recommendation

**Implement Option 1 first (Synthesis Pattern Expansion)**

**Rationale:**
1. **Current performance is excellent:** 96.5% (55/57) - only Q-D8 failing
2. **Low-risk, high-speed fix:** Pattern expansion is simple and testable
3. **No re-indexing required:** Can deploy immediately
4. **Validation path:** Test on Q-D8, then full benchmark

**If Option 1 doesn't fully resolve Q-D8:**
- Consider Option 2 for next indexing cycle
- Document as known issue with workaround
- May benefit from hybrid approach (better patterns + cleaner storage)

---

## Related Context

### Hybrid Reranking (Already Implemented)
- **Commit:** 21db20f
- **Purpose:** Keyword+semantic reranking for qualifier-based queries (e.g., "day-based" in Q-D3)
- **Status:** ✅ Working perfectly - Q-D3 scored 3/3
- **Strategy:** `section_based_hybrid_reranked`

This confirms the hybrid reranking logic is solid; Q-D8 issue is specifically about document counting/consolidation.

### Entity Concentration Detection (Existing)
- **Commit:** c24b071
- **Purpose:** Detect over-partitioning in query decomposition
- **Q-D8 behavior:** Didn't trigger (confidence=0.7, threshold is <0.7)
- **Note:** This handles decomposition issues, not storage-level document counting

---

## Next Steps

1. **Implement synthesis pattern expansion** (5 minutes)
2. **Deploy to Azure Container Apps** (5 minutes)
3. **Test Q-D8 specifically** (1 run to verify)
4. **Full benchmark** (if Q-D8 passes spot check)
5. **LLM judge evaluation** (final validation)

**Expected outcome:** Q-D8 score improves to 3/3, overall benchmark reaches 57/57 (100%)

---

## Files Referenced

- `/app/hybrid/pipeline/synthesis.py` - Line 833-849 (pattern detection and guidance)
- `/app/services/cu_standard_ingestion_service.py` - Lines 60-70, 260-280 (section_path metadata)
- `/app/hybrid/pipeline/enhanced_graph_retriever.py` - Line 862, 1021, etc. (doc_title retrieval)
- Benchmark: `benchmarks/route4_drift_multi_hop_20260125T103146Z.json`
- Evaluation: `benchmarks/route4_drift_multi_hop_20260125T103146Z.eval.md`
