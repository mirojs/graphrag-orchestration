# Q-D3 Timeframe Retrieval Issue Analysis

**Date:** January 17, 2026  
**Question:** "Compare 'time windows' across the set: list all explicit day-based timeframes."  
**Score:** 2/3 (Acceptable, but missed some timeframes)

## Summary

The system correctly identified several timeframes but missed 4 explicit day-based timeframes that exist in the documents. This is a **retrieval issue**, not an LLM reasoning issue.

## 🔍 ROOT CAUSE IDENTIFIED (Deep Investigation)

### Benchmark Metadata Analysis

From the benchmark JSON, Q-D3 shows:

```
Seeds Discovered: 0 (CRITICAL - entity discovery completely failed)
Evidence Path: 0 items (no PPR tracing possible)
Coverage Retrieval: {applied: True, strategy: 'semantic', chunks_added: 5, docs_added: 5}
Confidence Score: 0.0 (triggering confidence loop)
```

### What Happened

1. **Stage 4.1 (Query Decomposition)** generated 3 abstract sub-questions:
   - "Which entities, events, or conditions... are associated with each specific day-based timeframe?"
   - "How do these day-based timeframes differ..."
   - "Are there any overlaps or conflicts..."

2. **Stage 4.2 (Entity Discovery) FAILED** - All 7 sub-questions returned 0 entities because:
   - Sub-questions don't contain proper nouns (uppercase/digits)
   - IntentDisambiguator filters aggressively: `has_upper or has_digit`
   - No community context was available to guide entity extraction

3. **Stage 4.3 (PPR Tracing) SKIPPED** - No seeds = no tracing

4. **Stage 4.3.5 (Confidence Loop) TRIGGERED** but refined questions were malformed fragments

5. **Stage 4.3.6 (Coverage Gap Fill) PARTIALLY SAVED** - Added 5 chunks (1 per document) via semantic search

6. **Stage 4.4 (Synthesis)** worked with only 5 chunks → Missed timeframes in other chunks

### Why Coverage Retrieval Wasn't Enough

The coverage retrieval uses `max_per_document=1`, meaning each document contributes only its SINGLE most semantically similar chunk to the query "list all day-based timeframes".

For the **purchase_contract** document:
- **Chunk 9** (warranty section) was selected - contains "60 days" warranty term
- **Chunk 10** (Right to Cancel) was MISSED - contains "3 business days cancel window"

The "3 business days" chunk wasn't the MOST similar to "time windows/timeframes" but it DOES contain relevant information.

## ✅ FIX IMPLEMENTED (January 17, 2026)

### Code Change: `app/hybrid/orchestrator.py`

Added comprehensive query detection in Stage 4.3.6:

```python
# Detect comprehensive enumeration queries that need more chunks per document
def _is_comprehensive_query(q: str) -> bool:
    """Detect queries asking for exhaustive lists or comparisons."""
    q_lower = q.lower()
    comprehensive_patterns = [
        "list all", "list every", "enumerate", "compare all",
        "compare the", "all explicit", "all the", "every ",
        "what are all", "find all", "identify all", "show all",
        "across all", "across the set", "in all documents",
        "each document", "every document", "comprehensive",
    ]
    return any(pattern in q_lower for pattern in comprehensive_patterns)

is_comprehensive = _is_comprehensive_query(query)
# For comprehensive queries, get more chunks per document
chunks_per_doc = 3 if is_comprehensive else 1
```

### What This Fixes

| Query Type | Before | After |
|------------|--------|-------|
| "List all timeframes" | 1 chunk/doc (5 total) | 3 chunks/doc (15 total) |
| "What is the warranty?" | 1 chunk/doc | 1 chunk/doc (unchanged) |
| "Compare the terms" | 1 chunk/doc | 3 chunks/doc |

### Expected Impact on Q-D3

With `chunks_per_doc=3`, the semantic coverage will retrieve:
- **purchase_contract**: chunk_9 (warranty), chunk_10 (Right to Cancel - 3 business days), chunk_X
- **warranty document**: chunk_17, chunk_3 (60 days repair), chunk_11
- **Other docs**: Multiple chunks each

This should capture all the missing timeframes.

## What the System Found ✅

1. **1 year** - Builder's Limited Warranty term
2. **60 days** - Builder's Limited Warranty (short duration coverage)
3. **90 days** - Contractor labor warranty  
4. **5 business days** - Property management listing notification
5. **<180 days / >180 days** - Rental classification thresholds

## What the System Missed ❌

Based on the expected ground truth, the system missed:

1. **3 business days cancel window** (purchase contract)  
   - ✅ **CONFIRMED EXISTS** in Neo4j: `doc_5bc50d29e867468ca5ce231f692defbd_chunk_10`
   - Text: "Customer may cancel within 3 business days for full refund"
   
2. **10 business days to file changes** (holding tank contract)  
   - ❓ **NOT VERIFIED** in Neo4j search (relationship mismatch issue)
   - Expected in HOLDING TANK SERVICING CONTRACT
   
3. **60 days repair window after defect report** (warranty repair timeline)  
   - ✅ **CONFIRMED EXISTS** in Neo4j: `doc_52affdc2ed7e4e0cb58a3d5d4b057ffa_chunk_3`
   - The system found "60 days" but in the context of warranty **term**, not repair **window**
   - Text mentions repair procedures after defect report
   
4. **60 days after service of complaint** (arbitration timing)  
   - ✅ **CONFIRMED EXISTS** in Neo4j: Contains "60 days" + "arbitration" context
   - Found in warranty document regarding dispute resolution

## Root Cause Analysis

### Issue 1: Retrieval Coverage
The Route 4 system retrieved 3 documents successfully (warranty, property management, purchase contract) but may have insufficient coverage of specific clauses:

**Retrieved Citations:**
- `[1]` BUILDERS LIMITED WARRANTY.pdf - chunk_17
- `[2]` PROPERTY MANAGEMENT AGREEMENT.pdf - chunk_1  
- `[3]` purchase_contract.pdf - chunk_9 (warranty section only)

**Missing Chunks:**
- Purchase contract chunk_10 (Right to Cancel - 3 business days) ❌
- Warranty chunks with repair timeline details ❌
- Warranty chunks with arbitration timing ❌
- HOLDING TANK document entirely ❌ (NOT in citations)

### Issue 2: Query Routing & Retrieval Strategy
The query asked for "all explicit day-based timeframes" which should trigger:
- ✅ Comprehensive document retrieval
- ✅ Multiple chunks per document
- ❌ **Failed to retrieve cancellation clauses**
- ❌ **Failed to retrieve HOLDING TANK document**

### Issue 3: Semantic Similarity Threshold
Route 4 uses:
- Semantic search for initial retrieval
- Graph traversal for connected information
- PPR (Personalized PageRank) for entity relevance

**Hypothesis:** The chunks containing "3 business days cancel" and "10 business days file changes" may have:
- Lower semantic similarity to query about "time windows"
- Not connected via strong graph relationships
- Lower PPR scores from seed entities

## Recommendations

### 1. Improve Chunk Retrieval for Comprehensive Queries ⭐ (High Priority)

**Problem:** When query asks for "all" or "list all", system doesn't ensure comprehensive document coverage.

**Solution:**
- Add query classification to detect "comprehensive listing" requests
- For such queries, increase retrieval budget:
  - Retrieve more chunks per document (currently ~1-2, should be 5-10)
  - Lower semantic similarity threshold (0.3 → 0.2)
  - Include more documents (currently 3, should be all 5 for small corpus)

**Implementation:**
- Modify `drift_multi_hop` route in [`app/routers/hybrid.py`](app/routers/hybrid.py)
- Add keywords detection: "all", "list", "compare across", "enumerate"
- Increase `top_k_chunks` parameter for these queries

### 2. Ensure All Documents Are Considered

**Problem:** HOLDING TANK document not in citations at all.

**Solution:**
- Verify document indexing completed for all 5 PDFs
- Check if HOLDING TANK has sufficient entities/relationships
- Ensure BM25 fulltext search includes all documents

**Verification Query:**
```cypher
MATCH (d:Document {group_id: 'test-5pdfs-1768557493369886422'})
RETURN d.title, 
       size((d)-[:HAS_CHUNK]->()) as chunk_count,
       size((d)<-[:MENTIONS]-()) as entity_count
ORDER BY d.title
```

### 3. Enhance Query Decomposition

**Problem:** Query asks for comprehensive list, but sub-questions may not cover all documents.

**Solution:**
- Improve `_decompose_question()` to generate document-specific sub-questions:
  - "What timeframes are in the warranty document?"
  - "What timeframes are in the purchase contract?"
  - "What timeframes are in the property management agreement?"
  - "What timeframes are in the holding tank contract?"
  - "What timeframes are in the invoice?"

**File:** [`app/hybrid/query/question_decomposer.py`](app/hybrid/query/question_decomposer.py) or inline in route handler

### 4. Add Negative Keywords to Improve Precision

**Problem:** System found "60 days" (warranty term) but missed "60 days repair window"

**Solution:**
- When listing timeframes, also capture their **context**:
  - "60 days warranty **term**"
  - "60 days **repair** window after defect report"
  - "60 days after service of complaint for **arbitration**"

**Implementation:**
- Modify prompt to ask: "For each timeframe, what is the **purpose** or **event** it applies to?"
- This will help distinguish between multiple uses of same duration

### 5. Test with Forced Document Coverage

**Quick Test:**
Run a modified query that explicitly mentions all documents:

```
"List all explicit day-based timeframes found in: 
1) Builder's warranty, 
2) Property management agreement, 
3) Purchase contract, 
4) Holding tank contract, 
5) Invoice"
```

This will verify if explicit mention improves coverage.

## Priority Actions

1. **Immediate (Today):**
   - Verify HOLDING TANK document indexing
   - Check if increasing `top_k_chunks` to 10 helps

2. **Short-term (This Week):**
   - Add query classification for comprehensive requests
   - Increase retrieval budget for "list all" queries
   - Test with modified prompts

3. **Medium-term (Next Sprint):**
   - Implement document-aware query decomposition
   - Add context capture for timeframes
   - Create regression test for Q-D3 type queries

## Validation

After implementing fixes, re-run Q-D3 and verify all timeframes are found:
- ✅ 1 year (warranty term)
- ✅ 60 days (warranty short coverage)  
- ✅ **3 business days** (cancel window) ← Target
- ✅ **10 business days** (file changes) ← Target
- ✅ **60 days** (repair window after defect) ← Target
- ✅ **60 days** (arbitration timing) ← Target
- ✅ 90 days (labor warranty)
- ✅ 5 business days (listing notice)
- ✅ <180 days / >180 days (rental classification)

Expected new score: **3/3** (Perfect)

---

## Technical Details

### Current Route 4 Flow
```
User Query 
  ↓
Question Decomposition (3-5 sub-questions)
  ↓
For each sub-question:
  - Semantic search (embedding similarity)
  - Entity extraction + PPR graph traversal
  - Top-K chunks (k=3-5)
  ↓
LLM synthesis with all evidence
```

### Proposed Enhanced Flow for Comprehensive Queries
```
User Query
  ↓
Query Classification: Is this "list all"? YES
  ↓
Document-Level Decomposition (1 sub-Q per document)
  ↓
For each document:
  - Semantic search with lower threshold (0.2)
  - BM25 keyword search for "days", "business days", etc.
  - Top-K chunks (k=10 per document)
  ↓
LLM synthesis with comprehensive evidence
```

### Files to Modify

1. **Query Handler:** [`app/routers/hybrid.py`](app/routers/hybrid.py) - Line ~450, `drift_multi_hop` function
2. **Retrieval:** [`app/hybrid/retrieval/`](app/hybrid/retrieval/) - Increase chunk limits
3. **Prompt:** Inline in route handler - Add "be comprehensive" instruction

---

**Status:** Investigation complete, recommendations ready for implementation.
