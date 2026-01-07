# Route 3 Testing Summary - January 7, 2026

## Test Execution

**Benchmark:** Route 3 Global Search (LazyGraphRAG)
**Date:** 2026-01-07 05:49:19Z
**Group ID:** test-5pdfs-1767429340223041632
**Repeats:** 2
**Questions:** 20 (10 positive Q-G*, 10 negative Q-N*)

---

## Results Overview

### Positive Questions (Q-G1 to Q-G10)

| Question | Theme Coverage | F1 Score | Containment | Status |
|----------|---------------|----------|-------------|---------|
| Q-G1 (Termination rules) | 100% (8/8) | 0.23 | 0.81 | ✅ Excellent |
| Q-G2 (Jurisdictions) | 100% (6/6) | 0.12 | 0.71 | ✅ Good |
| Q-G3 (Fees/charges) | **62% (5/8)** | 0.11 | 0.39 | ⚠️ **NEEDS IMPROVEMENT** |
| Q-G4 (Reporting) | **50% (3/6)** | 0.12 | 0.64 | ⚠️ **NEEDS IMPROVEMENT** |
| Q-G5 (Dispute resolution) | 100% (6/6) | 0.08 | 0.65 | ✅ Good |
| Q-G6 (Entity relationships) | 100% (8/8) | 0.14 | 0.68 | ✅ Good |
| Q-G7 (Notice requirements) | 83% (5/6) | 0.17 | 0.67 | ✅ Good |
| Q-G8 (Insurance/liability) | 100% (6/6) | 0.09 | 0.68 | ✅ Good |
| Q-G9 (Deposits/refunds) | 100% (6/6) | 0.09 | 0.87 | ✅ Good |
| Q-G10 (Contract types) | 71% (5/7) | 0.12 | 0.62 | ✅ Acceptable |

**Average Theme Coverage:** 87.5%
**Average F1 Score:** 0.137
**Average Latency:** ~16s (p50: 12-24s)

### Negative Questions (Q-N1 to Q-N10)

**Critical Issue:** Only 1/10 negative tests passed ❌

| Question | Status | Issue |
|----------|--------|-------|
| Q-N1 (Bank routing) | FAIL | Response said "does not explicitly provide" but continued with related info |
| Q-N2 | FAIL | Too helpful - provided context instead of "not found" |
| Q-N3 | FAIL | Too helpful |
| Q-N4 | FAIL | Too helpful |
| Q-N5 | FAIL | Too helpful |
| Q-N6 | FAIL | Too helpful |
| Q-N7 | FAIL | Too helpful |
| Q-N8 | **PASS** ✅ | Correctly returned not found |
| Q-N9 | FAIL | Too helpful |
| Q-N10 | FAIL | Too helpful |

---

## Detailed Analysis

### Issue #1: Q-G3 (Pricing/Fees) - 62% Coverage

**Missing Terms:**
- "29900" (purchase price from purchase_contract.pdf)
- "25%" (commission rate)  
- "installment" (payment structure)

**What Was Found:**
- ✅ $75 pro-ration advertising charge
- ✅ $50 administrative fee
- ✅ 10% repairs fee
- ✅ 4.712% Hawaii tax
- ✅ $250 start-up fee
- ❌ $29,900 purchase price (missing)
- ❌ 25% commission (missing)
- ❌ Installment payment terms (missing)

**Root Cause:** Route 3 global search focuses on management agreement fees but misses purchase contract pricing details. The community/hub entities may not be adequately capturing the purchase_contract.pdf financial terms.

### Issue #2: Q-G4 (Reporting Requirements) - 50% Coverage

**Missing Terms:**
- "monthly statement"
- "income"
- "expenses"

**What Was Found:**
- ✅ "pumper" reporting obligations
- ✅ "county" as reporting recipient
- ✅ "volumes" data to be reported
- ❌ Monthly statement cadence (missing)
- ❌ Income reporting (missing)
- ❌ Expense tracking (missing)

**Root Cause:** Similar to Q-G3, the system finds general reporting requirements but misses specific financial reporting details (monthly statements, income/expense tracking).

### Issue #3: Negative Test Failures (9/10 fail)

**Problem:** Route 3 responses are "too helpful" - they provide context and related information even when the specific requested information doesn't exist.

**Example (Q-N1 - Bank Routing Number):**
```
Response: "The invoice does not explicitly provide a bank routing number 
for payment. However, the following payment-related details are available:
1. Payment Instructions: The invoice specifies that all checks should be 
made payable to Contoso Lifts LLC..."
```

**Expected:** Clear "not found" or "information not available" response without additional context.

**Detection Logic:** The benchmark looks for phrases:
- "not found", "not specified", "not mentioned", "not provided"
- "does not specify", "doesn't specify", "no information"
- "not available", "cannot be determined", "information is not"

**Issue:** Responses contain "does not explicitly provide" but then continue with tangential information, which makes the overall response unhelpful for out-of-scope queries.

---

## Recommendations

### Priority 1: Fix Negative Test Handling 🔴

**Action:** Update Route 3 synthesis prompt to be more conservative when requested information is not in the knowledge graph.

**Change Location:** `app/hybrid/lazy_global_rag.py` - synthesis prompt

**Proposed Fix:**
```python
# Add instruction to synthesis prompt:
If the specific information requested is not available in the evidence,
respond with: "The requested information is not found in the provided documents."
Do not provide tangential or related information unless it directly answers the question.
```

**Validation:** Re-run benchmark expecting 8-10/10 negative tests to pass.

### Priority 2: Improve Financial Term Coverage for Q-G3 and Q-G4 🟡

**Root Cause Hypothesis:** 
- Hub entities may not be emphasizing purchase contract financial terms
- Community summaries may be focusing on management agreements over purchase contracts

**Investigation Steps:**
1. Check which communities contain purchase_contract.pdf entities
2. Verify if "$29,900" and "25%" appear in community summaries
3. Check if "monthly statement", "income", "expenses" are in community descriptions

**Potential Fixes:**
- Increase hub entity count to capture more financial entities
- Adjust PPR walk parameters to better traverse purchase contract subgraph
- Enhance community detection to create separate financial/pricing communities

### Priority 3: Route 3 Repeatability Validation ✅

**Current:** 
- text_norm_exact_rate: 0.50 (50% exact match across repeats)
- min_similarity: varies by question (0.09 to 0.58)

**Status:** This is acceptable for LLM-synthesized responses. Evidence stability (citations/paths) is high (1.00 Jaccard similarity).

---

## Comparison with Previous Testing

From [HANDOVER_2026-01-06_v2.md](HANDOVER_2026-01-06_v2.md):
- Previous Route 3 test showed 0% theme coverage (system was broken)
- Current test shows 87.5% average theme coverage ✅ **Major improvement**
- Negative test handling remains problematic (historical issue, not new)

---

## Files Generated

- Benchmark JSON: `benchmarks/route3_global_search_20260107T054919Z.json`
- Benchmark MD: `benchmarks/route3_global_search_20260107T054919Z.md`
- Console log: `bench_route3_full_20260107.txt`

---

## Next Steps

1. ✅ **DONE:** Route 3 benchmark execution
2. **TODO:** Fix negative test handling in synthesis prompt
3. **TODO:** Investigate Q-G3/Q-G4 missing terms (community/hub analysis)
4. **TODO:** Re-run benchmark to validate fixes
5. **TODO:** Compare Route 3 vs Route 1 performance (cross-route analysis)

---

## Environment Info

- **URL:** https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
- **Neo4j URI:** neo4j+s://a86dcf63.databases.neo4j.io
- **Group ID:** test-5pdfs-1767429340223041632
- **Endpoint:** `/hybrid/query` (force_route=global_search)

---

**Last Updated:** 2026-01-07 06:15 UTC
**Status:** Route 3 testing completed, analysis documented, ready for fixes
