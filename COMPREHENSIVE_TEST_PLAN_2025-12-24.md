# Comprehensive GraphRAG Testing Plan
**Date:** 2025-12-24  
**Status:** Ready for Execution  
**Architecture:** Low Latency Engine (GPT-5.2 + 1536-dim embeddings)

---

## Testing Philosophy

### Progressive Validation Strategy
1. **Phase 1:** Test GraphRAG Core (without RAPTOR enhancement) - Baseline validation
2. **Phase 2:** Test RAPTOR Integration - Enhancement validation
3. **Phase 3:** Test Routing Logic - Intelligent mode selection
4. **Phase 4:** Test Vector RAG - Alternative retrieval path

### Why Test Without RAPTOR First?
- **Isolation:** Separate GraphRAG bugs from RAPTOR integration bugs
- **Baseline:** Establish performance/accuracy baseline for comparison
- **Debugging:** If combined mode fails, know which layer caused it

---

## Test Data Setup

### Required Documents (5 PDFs)
1. **BUILDERS LIMITED WARRANTY.pdf** - Warranty agreement
2. **HOLDING TANK SERVICING CONTRACT.pdf** - Service contract
3. **PROPERTY MANAGEMENT AGREEMENT.pdf** - Management contract
4. **contoso_lifts_invoice.pdf** - Invoice with amounts
5. **purchase_contract.pdf** - Purchase agreement

### Group ID
```
test-comprehensive-{timestamp}
```

### Expected Indexing Results
- **Entities:** ~220-250
- **Relationships:** ~200-220
- **RAPTOR Nodes:** ~18-22 (3-4 at level > 0)
- **Communities:** ~18-22

---

## Phase 1: GraphRAG Core Testing (No RAPTOR)

### Configuration
**File:** `app/v3/services/triple_engine_retriever.py`

**Disable RAPTOR Enhancement:**
```python
# Temporarily comment out RAPTOR enhancement logic
# In search_local_with_raptor():
#   return self.search_local(group_id, query, top_k)
# In search_global_with_raptor():
#   return self.search_global(group_id, query, top_k)
# In search_drift_with_raptor():
#   return self.search_drift(group_id, query, top_k)
```

---

### Test 1.1: LOCAL Search (Entity-Focused)
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `local`  
**Purpose:** Validate entity extraction and hybrid search (vector + full-text)

#### Test Questions (10)

1. **Q1.1:** "What is the invoice amount in the Contoso Lifts invoice?"
   - **Expected:** Specific dollar amount from invoice
   - **Validates:** Entity extraction, numeric content search

2. **Q1.2:** "Who is the property manager in the property management agreement?"
   - **Expected:** Specific party name
   - **Validates:** Entity type detection (PERSON/ORGANIZATION)

3. **Q1.3:** "What is the warranty period for the builders limited warranty?"
   - **Expected:** Time period (e.g., "12 months", "1 year")
   - **Validates:** Temporal entity extraction

4. **Q1.4:** "What services are covered under the holding tank servicing contract?"
   - **Expected:** List of services
   - **Validates:** Multi-entity retrieval, list extraction

5. **Q1.5:** "What is the purchase price in the purchase contract?"
   - **Expected:** Specific amount with currency
   - **Validates:** Financial entity extraction

6. **Q1.6:** "Who are the parties involved in the property management agreement?"
   - **Expected:** Landlord and property manager names
   - **Validates:** Multi-entity relationship

7. **Q1.7:** "What is the payment schedule in the servicing contract?"
   - **Expected:** Payment frequency and amounts
   - **Validates:** Structured data extraction

8. **Q1.8:** "What exclusions are mentioned in the warranty?"
   - **Expected:** List of exclusions
   - **Validates:** Negative constraint extraction

9. **Q1.9:** "What is the service fee mentioned in the property management agreement?"
   - **Expected:** Percentage or dollar amount
   - **Validates:** Fee extraction from contracts

10. **Q1.10:** "What is the effective date of the purchase contract?"
    - **Expected:** Specific date
    - **Validates:** Date entity extraction

**Success Criteria:**
- ✅ 9/10 questions answered correctly (90% accuracy)
- ✅ Entity citations provided
- ✅ Response time <30 seconds per query
- ✅ No cross-group data leakage

---

### Test 1.2: GLOBAL Search (Community-Based)
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `global`  
**Purpose:** Validate community detection and high-level summarization

#### Test Questions (10)

1. **Q2.1:** "What are the main themes across all documents?"
   - **Expected:** Thematic summary (contracts, warranties, services, financial obligations)
   - **Validates:** Community detection across documents

2. **Q2.2:** "Summarize the financial obligations mentioned in all contracts."
   - **Expected:** Aggregated view of all payment terms
   - **Validates:** Cross-document synthesis

3. **Q2.3:** "What types of agreements are present in the document collection?"
   - **Expected:** Categories (warranty, service, management, purchase)
   - **Validates:** Document classification

4. **Q2.4:** "Compare the liability terms across all contracts."
   - **Expected:** Comparative analysis of liability clauses
   - **Validates:** Multi-document comparison

5. **Q2.5:** "What common conditions appear in multiple contracts?"
   - **Expected:** Shared clauses (termination, dispute resolution)
   - **Validates:** Pattern recognition across documents

6. **Q2.6:** "Summarize all payment-related terms across documents."
   - **Expected:** Consolidated payment information
   - **Validates:** Topic-based aggregation

7. **Q2.7:** "What are the key dates mentioned across all documents?"
   - **Expected:** Timeline of important dates
   - **Validates:** Temporal aggregation

8. **Q2.8:** "Describe the relationships between parties across all agreements."
   - **Expected:** Party interaction map
   - **Validates:** Relationship aggregation

9. **Q2.9:** "What risk factors are mentioned across the document set?"
   - **Expected:** Consolidated risk assessment
   - **Validates:** Risk pattern detection

10. **Q2.10:** "Summarize the scope of work across all service-related documents."
    - **Expected:** Comprehensive scope summary
    - **Validates:** Service aggregation

**Success Criteria:**
- ✅ 8/10 questions answered correctly (80% accuracy - global is harder)
- ✅ Community reports cited
- ✅ Response time <45 seconds per query
- ✅ Thematic coherence in answers

---

### Test 1.3: DRIFT Search (Multi-Hop Reasoning)
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `drift`  
**Purpose:** Validate graph traversal and relationship reasoning

#### Test Questions (10)

1. **Q3.1:** "How does the invoice amount compare to the service contract terms?"
   - **Expected:** Comparison between invoice and contract
   - **Validates:** Cross-document entity linking

2. **Q3.2:** "Is the property manager's fee aligned with the service invoice?"
   - **Expected:** Verification of fee consistency
   - **Validates:** Financial relationship reasoning

3. **Q3.3:** "What is the chain of liability from the purchase contract to the warranty?"
   - **Expected:** Multi-hop path through relationships
   - **Validates:** Graph traversal

4. **Q3.4:** "Which contract governs the services billed in the invoice?"
   - **Expected:** Contract → Invoice relationship
   - **Validates:** Document linking

5. **Q3.5:** "Trace the responsibility for tank servicing from the invoice back to the contract."
   - **Expected:** Invoice → Service → Contract path
   - **Validates:** Backward traversal

6. **Q3.6:** "What dependencies exist between the property management agreement and other contracts?"
   - **Expected:** Dependency graph
   - **Validates:** Relationship extraction

7. **Q3.7:** "If the warranty is voided, what other agreements are affected?"
   - **Expected:** Impact analysis
   - **Validates:** Consequence reasoning

8. **Q3.8:** "Who is ultimately responsible for payment according to the contract chain?"
   - **Expected:** Final responsible party
   - **Validates:** Authority resolution

9. **Q3.9:** "What is the sequence of events from purchase to service to invoice?"
   - **Expected:** Timeline reconstruction
   - **Validates:** Temporal reasoning

10. **Q3.10:** "Are there any contradictions between the warranty terms and service contract?"
    - **Expected:** Conflict detection
    - **Validates:** Inconsistency detection

**Success Criteria:**
- ✅ 8/10 questions answered correctly (80% accuracy - multi-hop is complex)
- ✅ Relationship paths cited
- ✅ Response time <60 seconds per query
- ✅ Correct multi-hop reasoning

---

## Phase 2: RAPTOR-Enhanced Testing

### Configuration
**File:** `app/v3/services/triple_engine_retriever.py`

**Enable RAPTOR Enhancement:**
```python
# Uncomment RAPTOR enhancement logic
# Use search_local_with_raptor()
# Use search_global_with_raptor()
# Use search_drift_with_raptor()
```

---

### Test 2.1: LOCAL + RAPTOR (Contextual Zoom)
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `local`  
**Purpose:** Validate entity retrieval + parent summary context

#### Test Questions (10)
**Note:** Same questions as Test 1.1, but with RAPTOR context

1. **Q4.1:** "What is the invoice amount in the Contoso Lifts invoice?"
   - **Additional Validation:** Check if answer includes thematic context from parent RAPTOR summary
   - **Expected Enhancement:** "Invoice amount is $X, which is part of the maintenance services billing..."

2. **Q4.2:** "Who is the property manager in the property management agreement?"
   - **Expected Enhancement:** Party name + role context from summary

3. **Q4.3:** "What is the warranty period for the builders limited warranty?"
   - **Expected Enhancement:** Period + coverage scope from summary

4. **Q4.4:** "What services are covered under the holding tank servicing contract?"
   - **Expected Enhancement:** Services + contract purpose from summary

5. **Q4.5:** "What is the purchase price in the purchase contract?"
   - **Expected Enhancement:** Price + transaction context from summary

6. **Q4.6:** "Who are the parties involved in the property management agreement?"
   - **Expected Enhancement:** Parties + relationship nature from summary

7. **Q4.7:** "What is the payment schedule in the servicing contract?"
   - **Expected Enhancement:** Schedule + payment terms context from summary

8. **Q4.8:** "What exclusions are mentioned in the warranty?"
   - **Expected Enhancement:** Exclusions + warranty scope from summary

9. **Q4.9:** "What is the service fee mentioned in the property management agreement?"
   - **Expected Enhancement:** Fee + service scope from summary

10. **Q4.10:** "What is the effective date of the purchase contract?"
    - **Expected Enhancement:** Date + contract activation context from summary

**Success Criteria:**
- ✅ 9/10 questions answered correctly (same as baseline)
- ✅ **Improvement:** Answers include thematic context from RAPTOR summaries
- ✅ **Improvement:** Richer explanations with "why" and "how" context
- ✅ Response time <35 seconds (slight overhead acceptable)

**Comparison Metrics:**
- Context richness: RAPTOR > Baseline by 30-50%
- Answer completeness: RAPTOR > Baseline by 20%

---

### Test 2.2: GLOBAL + RAPTOR (Thematic Pruning)
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `global`  
**Purpose:** Validate RAPTOR-guided community filtering

#### Test Questions (10)
**Note:** Same questions as Test 1.2, but with RAPTOR pruning

**Success Criteria:**
- ✅ 9/10 questions answered correctly (improvement from 8/10 baseline)
- ✅ **Improvement:** Faster response time due to community pruning
- ✅ **Improvement:** More focused answers (less irrelevant information)
- ✅ Response time <35 seconds (10s faster than baseline)

**Comparison Metrics:**
- Relevance: RAPTOR > Baseline by 15%
- Speed: RAPTOR 20% faster
- Noise reduction: 90% fewer irrelevant communities

---

### Test 2.3: DRIFT + RAPTOR (Multi-Hop Highway)
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `drift`  
**Purpose:** Validate RAPTOR "teleporter" for graph navigation

#### Test Questions (10)
**Note:** Same questions as Test 1.3, but with RAPTOR teleportation

**Success Criteria:**
- ✅ 9/10 questions answered correctly (improvement from 8/10 baseline)
- ✅ **Improvement:** Cleaner traversal paths (fewer dead-end entities)
- ✅ **Improvement:** Better handling of disconnected graph sections
- ✅ Response time <50 seconds (10s faster than baseline)

**Comparison Metrics:**
- Path quality: RAPTOR > Baseline by 25%
- Traversal efficiency: 40% fewer entity hops
- Disconnected section handling: RAPTOR bridges gaps that baseline cannot

---

## Phase 3: Routing Logic Testing

### Configuration
**File:** `app/v3/services/query_router.py`

**Enable Routing:**
```python
# Use route_query() to automatically select mode
```

---

### Test 3.1: GraphRAG Router (4-Way Routing)
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `auto` (let router decide)  
**Purpose:** Validate intelligent mode selection

#### Test Questions (10)

1. **Q5.1:** "What is the invoice amount?" → Should route to **LOCAL**
   - **Validates:** Specific fact query routing

2. **Q5.2:** "Summarize all financial obligations." → Should route to **GLOBAL**
   - **Validates:** Aggregation query routing

3. **Q5.3:** "How does the invoice relate to the service contract?" → Should route to **DRIFT**
   - **Validates:** Relationship query routing

4. **Q5.4:** "Who is the property manager?" → Should route to **LOCAL**
   - **Validates:** Entity query routing

5. **Q5.5:** "What are the main themes in these documents?" → Should route to **GLOBAL**
   - **Validates:** Theme query routing

6. **Q5.6:** "Trace the payment chain from invoice to contract." → Should route to **DRIFT**
   - **Validates:** Chain query routing

7. **Q5.7:** "What is the warranty period?" → Should route to **LOCAL**
   - **Validates:** Attribute query routing

8. **Q5.8:** "Compare all liability terms across contracts." → Should route to **GLOBAL**
   - **Validates:** Comparison query routing

9. **Q5.9:** "Is there a conflict between warranty and service terms?" → Should route to **DRIFT**
   - **Validates:** Conflict detection routing

10. **Q5.10:** "List all payment amounts mentioned." → Should route to **LOCAL** or **GLOBAL**
    - **Validates:** Ambiguous query handling

**Success Criteria:**
- ✅ 9/10 routing decisions correct
- ✅ Router explains reasoning in response metadata
- ✅ Fallback to LOCAL when uncertain
- ✅ Response time overhead <5 seconds for routing

---

### Test 3.2: Vector RAG vs GraphRAG Routing
**Endpoint:** `POST /graphrag/v3/query`  
**Mode:** `auto`  
**Purpose:** Validate top-level routing between Vector RAG and GraphRAG

#### Test Questions (10)

1. **Q6.1:** "What is on page 3 of the warranty document?" → Should route to **Vector RAG**
   - **Validates:** Page-specific query routing

2. **Q6.2:** "How do entities relate across documents?" → Should route to **GraphRAG**
   - **Validates:** Graph reasoning routing

3. **Q6.3:** "Find the section about payment terms." → Should route to **Vector RAG**
   - **Validates:** Section-level retrieval routing

4. **Q6.4:** "What connections exist between the invoice and contracts?" → Should route to **GraphRAG**
   - **Validates:** Relationship routing

5. **Q6.5:** "Quote the exact text about warranty exclusions." → Should route to **Vector RAG**
   - **Validates:** Direct retrieval routing

6. **Q6.6:** "Summarize the community structure of these documents." → Should route to **GraphRAG (GLOBAL)**
   - **Validates:** Graph-specific feature routing

7. **Q6.7:** "What does paragraph 5.3 say?" → Should route to **Vector RAG**
   - **Validates:** Structural query routing

8. **Q6.8:** "What dependencies exist between contracts?" → Should route to **GraphRAG (DRIFT)**
   - **Validates:** Dependency routing

9. **Q6.9:** "Retrieve chunks about 'liability'." → Should route to **Vector RAG**
   - **Validates:** Keyword-based routing

10. **Q6.10:** "Explain the entity-relationship graph." → Should route to **GraphRAG (LOCAL/DRIFT)**
    - **Validates:** Meta-query routing

**Success Criteria:**
- ✅ 9/10 routing decisions correct
- ✅ Clear separation: Vector RAG for direct retrieval, GraphRAG for reasoning
- ✅ Router model (`o4-mini`) performs efficiently
- ✅ Routing overhead <3 seconds

---

## Phase 4: Vector RAG Testing

### Test 4.1: Pure Vector RAG (No Graph)
**Endpoint:** `POST /vectorrag/query` (if exists) or `POST /graphrag/v3/query` with mode=`vector`  
**Purpose:** Validate vector-only retrieval without graph logic

#### Test Questions (10)

1. **Q7.1:** "What is mentioned in the introduction section?"
   - **Expected:** Direct text retrieval from introduction
   - **Validates:** Semantic search

2. **Q7.2:** "Find all mentions of 'liability' in the documents."
   - **Expected:** All chunks containing "liability"
   - **Validates:** Keyword matching

3. **Q7.3:** "What does the warranty say about water damage?"
   - **Expected:** Specific warranty clause
   - **Validates:** Topic-based retrieval

4. **Q7.4:** "Retrieve the payment terms section."
   - **Expected:** Full payment terms text
   - **Validates:** Section-level retrieval

5. **Q7.5:** "What is the exact wording of the termination clause?"
   - **Expected:** Verbatim clause text
   - **Validates:** Exact match retrieval

6. **Q7.6:** "Find information about maintenance schedules."
   - **Expected:** Maintenance-related chunks
   - **Validates:** Semantic similarity

7. **Q7.7:** "What does the invoice say about labor costs?"
   - **Expected:** Labor cost details from invoice
   - **Validates:** Document-specific retrieval

8. **Q7.8:** "Retrieve all date references in the documents."
   - **Expected:** All date mentions
   - **Validates:** Pattern-based retrieval

9. **Q7.9:** "What is said about dispute resolution?"
   - **Expected:** Dispute resolution text
   - **Validates:** Legal clause retrieval

10. **Q7.10:** "Find the paragraph mentioning 'subcontractor'."
    - **Expected:** Subcontractor-related text
    - **Validates:** Entity-free retrieval

**Success Criteria:**
- ✅ 9/10 questions answered correctly
- ✅ Fast response time <20 seconds (no graph overhead)
- ✅ Exact text citations provided
- ✅ No hallucinations (direct retrieval only)

---

### Test 4.2: RAPTOR Hierarchical Search
**Endpoint:** `POST /raptor/query` (if exists) or `POST /graphrag/v3/query` with mode=`raptor`  
**Purpose:** Validate pure RAPTOR hierarchical summarization

#### Test Questions (10)

1. **Q8.1:** "Summarize the high-level themes in the document set."
   - **Expected:** Level 2 RAPTOR summary
   - **Validates:** Hierarchical abstraction

2. **Q8.2:** "What are the main topics covered?"
   - **Expected:** Level 1 cluster summaries
   - **Validates:** Topic clustering

3. **Q8.3:** "Provide an executive summary of all contracts."
   - **Expected:** Highest-level RAPTOR node
   - **Validates:** Document-level synthesis

4. **Q8.4:** "What themes emerge from the warranty and service documents?"
   - **Expected:** Cross-document thematic analysis
   - **Validates:** Cluster coherence

5. **Q8.5:** "Summarize the financial aspects of all documents."
   - **Expected:** Financial theme summary
   - **Validates:** Topic-based clustering

6. **Q8.6:** "What patterns exist in the contract structures?"
   - **Expected:** Structural pattern analysis
   - **Validates:** Meta-level reasoning

7. **Q8.7:** "Describe the relationships between document themes."
   - **Expected:** Theme interaction map
   - **Validates:** Inter-cluster relationships

8. **Q8.8:** "What is the overall narrative across the document set?"
   - **Expected:** Story-level synthesis
   - **Validates:** Narrative construction

9. **Q8.9:** "Summarize the obligations across all agreements."
   - **Expected:** Obligation-focused summary
   - **Validates:** Semantic clustering

10. **Q8.10:** "What is the conceptual hierarchy of these documents?"
    - **Expected:** RAPTOR tree visualization
    - **Validates:** Hierarchical structure

**Success Criteria:**
- ✅ 8/10 questions answered correctly (80% - summarization is subjective)
- ✅ Multi-level summaries provided (Level 0, 1, 2)
- ✅ Coherence scores displayed in metadata
- ✅ Response time <30 seconds

---

## Test Execution Guide

### Prerequisites
1. **Index Test Documents:**
   ```bash
   python3 test_phase1_5docs.py
   ```
   - Verify: ~220 entities, ~200 relationships, ~20 RAPTOR nodes

2. **Check System Health:**
   ```bash
   curl -H 'X-Group-ID: test-comprehensive-{timestamp}' \
     https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/health
   ```

3. **Verify Configuration:**
   ```bash
   # Check .env
   AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5-2
   AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
   AZURE_OPENAI_DRIFT_DEPLOYMENT_NAME=gpt-5-2
   ```

### Test Execution Order
1. **Phase 1:** GraphRAG Core (3 test suites × 10 questions = 30 queries)
2. **Phase 2:** RAPTOR-Enhanced (3 test suites × 10 questions = 30 queries)
3. **Phase 3:** Routing Logic (2 test suites × 10 questions = 20 queries)
4. **Phase 4:** Vector RAG (2 test suites × 10 questions = 20 queries)

**Total: 100 test queries**

### Test Script Template
```python
import requests
import json
import time

BASE_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-comprehensive-1766565399"

def test_query(question: str, mode: str = "local", expected_route: str = None):
    """Execute a single test query."""
    start_time = time.time()
    
    response = requests.post(
        f"{BASE_URL}/graphrag/v3/query",
        headers={
            "X-Group-ID": GROUP_ID,
            "Content-Type": "application/json"
        },
        json={
            "query": question,
            "mode": mode
        }
    )
    
    elapsed = time.time() - start_time
    
    result = response.json()
    
    print(f"\n{'='*80}")
    print(f"Question: {question}")
    print(f"Mode: {mode}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Answer: {result.get('answer', 'ERROR')[:200]}...")
    print(f"Sources: {len(result.get('sources', []))}")
    
    if expected_route:
        actual_route = result.get('metadata', {}).get('route_selected')
        print(f"Expected Route: {expected_route}")
        print(f"Actual Route: {actual_route}")
        print(f"✅ PASS" if actual_route == expected_route else "❌ FAIL")
    
    return result, elapsed

# Example: Run Phase 1, Test 1.1, Q1
test_query("What is the invoice amount in the Contoso Lifts invoice?", mode="local")
```

---

## Success Metrics

### Accuracy Targets
- **LOCAL:** ≥90% (9/10 correct)
- **GLOBAL:** ≥80% (8/10 correct)
- **DRIFT:** ≥80% (8/10 correct)
- **LOCAL+RAPTOR:** ≥90% (9/10 correct)
- **GLOBAL+RAPTOR:** ≥90% (improvement)
- **DRIFT+RAPTOR:** ≥90% (improvement)
- **Routing:** ≥90% (9/10 correct)
- **Vector RAG:** ≥90% (9/10 correct)
- **RAPTOR:** ≥80% (8/10 correct)

### Performance Targets
- **LOCAL:** <30s per query
- **GLOBAL:** <45s per query (baseline), <35s (with RAPTOR)
- **DRIFT:** <60s per query (baseline), <50s (with RAPTOR)
- **Routing Overhead:** <5s
- **Vector RAG:** <20s per query
- **RAPTOR:** <30s per query
- **End-to-End:** <2 minutes (SLA requirement)

### Quality Targets
- **No Cross-Group Leakage:** 100% isolation
- **Citation Accuracy:** ≥95% valid sources
- **Hallucination Rate:** <5%
- **Context Richness (RAPTOR):** +30-50% vs baseline
- **Noise Reduction (RAPTOR):** 90% fewer irrelevant results

---

## Reporting Template

### Test Report Structure
```markdown
## Test Results: {Phase Name}
**Date:** {date}
**Group ID:** {group_id}
**Configuration:** {RAPTOR enabled/disabled}

### Summary
- **Total Questions:** {total}
- **Correct Answers:** {correct}
- **Accuracy:** {accuracy}%
- **Avg Response Time:** {avg_time}s

### Failed Queries
1. Q{X}: {question}
   - Expected: {expected}
   - Actual: {actual}
   - Root Cause: {analysis}

### Performance Analysis
- Fastest Query: {time}s
- Slowest Query: {time}s
- Median: {time}s

### Recommendations
- {recommendation 1}
- {recommendation 2}
```

---

## Next Steps After Testing

1. **Analyze Results:**
   - Compare baseline vs RAPTOR performance
   - Identify failure patterns
   - Measure routing accuracy

2. **Optimize Based on Findings:**
   - Tune routing prompts if misrouting detected
   - Adjust RAPTOR coherence thresholds if quality issues
   - Fix group isolation if leakage found

3. **Document Findings:**
   - Update ARCHITECTURE_DECISIONS.md
   - Create TEST_RESULTS_{date}.md
   - Share insights with team

4. **Deploy to Production:**
   - Only after all tests pass
   - Enable monitoring and alerting
   - Set up performance dashboards

---

## Emergency Rollback Plan

If critical issues found during testing:

1. **Disable RAPTOR:**
   ```python
   # In triple_engine_retriever.py
   # Revert to pure GraphRAG modes
   ```

2. **Revert Model Configuration:**
   ```bash
   # In .env
   AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o  # Fallback model
   ```

3. **Restore Previous Indexes:**
   ```bash
   # If dimension change causes issues
   python3 drop_indexes.py
   # Re-create with previous dimensions
   ```

4. **Notify Team:**
   - Document issue in GitHub Issue
   - Alert on-call engineer
   - Update status page

---

## Conclusion

This comprehensive test plan provides:
- ✅ **100 test queries** across 9 test suites
- ✅ **Progressive validation** from core to enhanced modes
- ✅ **Baseline comparison** to measure RAPTOR improvement
- ✅ **Routing validation** for intelligent mode selection
- ✅ **Performance benchmarking** against <2 minute SLA
- ✅ **Quality metrics** for accuracy and isolation

**Estimated Test Duration:** 4-6 hours for complete execution

**Ready to Execute:** Yes - all configuration and test questions defined
