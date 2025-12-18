# GraphRAG V3 Search Methods Comparison Results

**Test Date:** December 18, 2025  
**Test Data:** 5 PDFs (invoices, contracts, agreements) - 390 entities, 540 relationships, 16 communities, 14 RAPTOR nodes  
**Group ID:** test-managed-identity-pdfs

## Performance Summary

| Method | Avg Response Time | Confidence | Status |
|--------|------------------|------------|---------|
| **LOCAL** | 0.76s (0.44-1.68s) | 0.00 | ⚠️ No data found |
| **GLOBAL** | 4.49s (3.70-5.39s) | 0.85 | ✅ Working excellently |
| **DRIFT** | 0.02s (0.01-0.03s) | 0.00 | ⚠️ No data indexed |
| **RAPTOR** | 1.23s (1.17-1.38s) | N/A | ❌ Embedding dimension error |

## Detailed Findings

### ✅ GLOBAL Search - Working Excellently

**Performance:**
- Response time: 3.7-5.4 seconds
- Confidence: 0.85 consistently
- Sources: 5 community summaries per query

**Answer Quality:**
- Comprehensive cross-document synthesis
- Structured thematic organization
- Context-aware interpretation

**Example Query:** "What are the main themes across all documents?"

**Answer Highlights:**
1. Construction and Dispute Resolution (arbitration processes)
2. Elevator and Lift Industry (specialized products, online payments)
3. Warranty Agreements (responsibilities, limitations, conditions)
4. Business Operations and Property Management (contracts, insurance)
5. Financial Transactions (fees, charges, rental management)

**Best For:**
- High-level overviews
- Cross-document pattern identification
- Thematic understanding
- Strategic insights

---

### ⚠️ LOCAL Search - No Data Found

**Issue:** Returns "No relevant information found" for all queries

**Possible Causes:**
1. Entity embeddings not properly indexed
2. Vector search query embedding mismatch
3. Graph neighborhood expansion not finding relevant entities

**Next Steps:**
- Verify entity embeddings in Neo4j (`MATCH (e:Entity) RETURN e.embedding LIMIT 1`)
- Check embedding dimensions match (should be 1536)
- Test with entity-specific queries like "What is Fabrikam Inc.?"

---

### ⚠️ DRIFT Search - No Data Indexed

**Issue:** Returns "No data has been indexed for this group yet"

**Possible Causes:**
1. DRIFT adapter using different database/schema
2. Not querying Neo4j entities/relationships
3. Initialization issue with drift_adapter

**Next Steps:**
- Check DRIFT adapter Neo4j connection
- Verify group_id filtering in DRIFT queries
- Test DRIFT with simple entity lookup

---

### ❌ RAPTOR Search - Embedding Dimension Mismatch

**Error:**
```
Index query vector has 3072 dimensions, but indexed vectors have 1536
```

**Root Cause:**
- RAPTOR nodes indexed with 1536-dimension embeddings (text-embedding-3-small)
- Query using 3072-dimension embeddings (text-embedding-3-large or different model)

**Fix Required:**
1. **Option A:** Update RAPTOR indexing to use consistent embedding model
2. **Option B:** Update RAPTOR query to use same model as indexing

**Code Location:**
- Indexing: `graphrag-orchestration/app/v3/services/indexing_pipeline.py`
- Query: `graphrag-orchestration/app/v3/routers/graphrag_v3.py` (line 513)

---

## Test Queries Analysis

### Query 1: "What is GraphRAG?"
**Expected Best:** LOCAL (specific entity definition)  
**Actual Best:** GLOBAL (inference from domain knowledge)

- **LOCAL:** No data ❌
- **GLOBAL:** Comprehensive explanation using community context ✅
- **DRIFT:** No data ❌
- **RAPTOR:** Dimension error ❌

**Winner:** GLOBAL (by default, creative interpretation)

---

### Query 2: "What are the main themes across all documents?"
**Expected Best:** GLOBAL (cross-document thematic summary)  
**Actual Best:** GLOBAL ✅

- **LOCAL:** No data ❌
- **GLOBAL:** Excellent synthesis - 5 major themes identified ✅
- **DRIFT:** No data ❌
- **RAPTOR:** Dimension error ❌

**Winner:** GLOBAL (perfect use case)

---

### Query 3: "How are machine learning and knowledge graphs connected?"
**Expected Best:** DRIFT (complex reasoning)  
**Actual Best:** GLOBAL (creative inference)

- **LOCAL:** No data ❌
- **GLOBAL:** Inferred connections from domain context ✅
- **DRIFT:** No data ❌
- **RAPTOR:** Dimension error ❌

**Winner:** GLOBAL (by default, but answer is speculative)

---

### Query 4: "Extract specific details about data processing"
**Expected Best:** RAPTOR (detailed content extraction)  
**Actual Best:** GLOBAL (inference)

- **LOCAL:** No data ❌
- **GLOBAL:** Inferred data processing activities from context ✅
- **DRIFT:** No data ❌
- **RAPTOR:** Dimension error ❌

**Winner:** GLOBAL (by default, but not ideal for this use case)

---

## Recommendations

### Immediate Fixes

1. **Fix RAPTOR embedding dimensions:**
   ```python
   # In graphrag_v3.py query/raptor endpoint
   # Ensure using same embedder as indexing pipeline
   query_embedding = adapter.embedder.embed_query(payload.query)  # Must match indexing
   ```

2. **Debug LOCAL search:**
   ```cypher
   # Check entity embeddings exist
   MATCH (e:Entity {group_id: 'test-managed-identity-pdfs'})
   WHERE e.embedding IS NOT NULL
   RETURN count(e) as entities_with_embeddings
   ```

3. **Debug DRIFT adapter:**
   ```python
   # Verify DRIFT using correct Neo4j connection
   # Check group_id filtering in drift_search()
   ```

### Query Strategy Guide

Based on current working state:

| Query Type | Best Method | Why |
|------------|-------------|-----|
| "What are main themes?" | **GLOBAL** ✅ | Cross-document synthesis |
| "Summarize all contracts" | **GLOBAL** ✅ | Community aggregation |
| "What is X?" | ~~LOCAL~~ → **GLOBAL** | LOCAL not working yet |
| "How is A connected to B?" | ~~DRIFT~~ → **GLOBAL** | DRIFT not working yet |
| "Extract specific values" | ~~RAPTOR~~ → Manual | RAPTOR needs fix |

### Future Testing

Once fixes are applied, re-test with:

1. **LOCAL-optimized queries:**
   - "What is Fabrikam Inc.?"
   - "Tell me about Contoso Lifts"
   - "Define Payment Terms"

2. **DRIFT-optimized queries:**
   - "How is Fabrikam Inc. connected to the warranty agreement?"
   - "Trace relationships between Contoso Lifts and payment systems"

3. **RAPTOR-optimized queries:**
   - "What are all the dollar amounts mentioned?"
   - "Extract dates from warranty agreements"
   - "Compare contract terms across documents"

---

## Current Winner: GLOBAL Search 🏆

**Why GLOBAL Dominates:**
1. Only fully working method in current deployment
2. High confidence (0.85) across all queries
3. Comprehensive, well-structured answers
4. Handles diverse query types through inference

**Strengths:**
- Cross-document pattern recognition
- Thematic organization
- Context-aware synthesis
- Robust to missing specific data

**Limitations:**
- Slower than LOCAL (4.5s vs <1s)
- May infer beyond actual document content
- Not suitable for specific entity lookups
- Can't extract precise values/fields

---

## Next Steps

1. ✅ **Completed:** Comprehensive comparison test created
2. 🔧 **Priority 1:** Fix RAPTOR embedding dimension mismatch
3. 🔧 **Priority 2:** Debug LOCAL search (entity embedding issues)
4. 🔧 **Priority 3:** Debug DRIFT adapter (connection/group_id)
5. 📊 **Priority 4:** Re-run comparison after fixes
6. 📚 **Priority 5:** Create decision matrix for method selection

---

## Conclusion

**GLOBAL search is production-ready** for thematic queries and cross-document analysis. The other methods require debugging:

- **RAPTOR:** Embedding model consistency fix needed
- **LOCAL:** Entity embedding or vector search configuration issue
- **DRIFT:** Adapter initialization or group_id filtering issue

The comparison framework is solid and can be reused once fixes are applied to validate that all four methods work correctly.
