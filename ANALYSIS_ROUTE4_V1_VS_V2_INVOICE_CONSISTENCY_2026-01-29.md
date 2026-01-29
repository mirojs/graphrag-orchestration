# 
oute 4 Analysis: V1 vs V2 Invoice Consistency Query
**Date:** 2026-01-29  
**Purpose:** Compare Route 4 (DRIFT Multi-Hop) performance between V1 (OpenAI embeddings) and V2 (Voyage embeddings) for invoice-contract inconsistency detection

---

## ⚠️ CRITICAL FINDING: Graph Structure Differences

**Neo4j Graph Analysis (2026-01-29):**

| Metric | V1 (OpenAI) | V2 Baseline | V2 KNN-disabled |
|--------|-------------|-------------|-----------------|
| **Entities** | 120 | 187 | 182 |
| **TextChunks** | 17 | 17 | 17 |
| **MENTIONS edges** | 222 | 314 | 343 |
| **RELATES_TO edges** | 0 | 0 | 0 |
| **SEMANTICALLY_SIMILAR** | 0 | 806 | 0 |
| **Total edges** | 222 | 1,120 | 343 |

### Why KNN-disabled (0 edges) Performed WORSE Than V1

**The puzzle:** V2 KNN-disabled has MORE entities (182 vs 120) and MORE MENTIONS edges (343 vs 222), yet performed WORSE than V1 on invoice consistency detection.

**Root Cause Analysis:**

1. **Entity Over-Extraction (Primary Hypothesis)**
   - V2's Voyage embeddings + NER extracted **50% more entities** (182 vs 120)
   - More entities = **sparser connections per entity** = weaker PPR signal
   - V1's OpenAI may have extracted fewer but **more semantically precise** entities
   - Example: V2 might extract "payment", "terms", "contract" as separate entities instead of "payment terms"

2. **Entity Naming Differences**
   - Same concept might have different entity names in V1 vs V2
   - "$29,900" vs "twenty-nine thousand nine hundred" vs "total price"
   - LLM IntentDisambiguator can't find entities with different names

3. **PPR Traversal Dilution**
   - With 182 entities but only MENTIONS edges (no RELATES_TO, no KNN)
   - PPR spreads across MORE entities but with WEAKER per-entity signal
   - V1's 120 entities create a TIGHTER graph with stronger connections

4. **KNN as Critical Entity Bridge**
   - Without KNN edges, entities are ISLANDS connected only via shared chunks
   - Invoice entity "$29,900" and contract entity "payment schedule" share no direct edge
   - KNN creates: `$29,900 -[SEMANTICALLY_SIMILAR]-> payment terms`
   - This bridge allows PPR to discover related payment concepts

### Why KNN-enabled Configs Work Better

KNN edges create **semantic bridges between entity islands**:
- Without KNN: Payment entity → Chunk A → Contract entity (indirect)
- With KNN: Payment entity → Contract entity (direct semantic link)

The PPR algorithm needs entity-entity edges to traverse from:
- "invoice amount" → "payment schedule" → "contract terms"

**Conclusion:** It's NOT the embedding model (Voyage vs OpenAI) that matters for Route 4. It's the **graph connectivity**. KNN edges provide the critical semantic bridges that MENTIONS edges alone cannot.

---

## Test Questions

### Context/Summary
> "Analyze invoice to confirm total consistency with signed contract."

### Three Detailed Questions (Combined into Single Query)

```
List all areas of inconsistency identified in the invoice, organized by:
(1) all inconsistencies with corresponding evidence,
(2) inconsistencies in goods or services sold including detailed specifications for every line item, and
(3) inconsistencies regarding billing logistics and administrative or legal issues.
```

**Individual Question Breakdown:**
1. "List all areas of inconsistency identified in the invoice with corresponding evidence."
2. "List all areas of inconsistency identified in the invoice in the goods or services sold (including detailed specifications for every line item)."
3. "List all areas of inconsistency identified in the invoice regarding billing logistics and administrative or legal issues."

---

## API Call Method

### Endpoint
```
POST https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query
```

### Headers
```
Content-Type: application/json
X-Group-ID: <group-id>
```

### Payload (Combined Query)
```json
{
  "query": "List all areas of inconsistency identified in the invoice, organized by: (1) all inconsistencies with corresponding evidence, (2) inconsistencies in goods or services sold including detailed specifications for every line item, and (3) inconsistencies regarding billing logistics and administrative or legal issues.",
  "force_route": "drift_multi_hop",
  "response_type": "summary"
}
```

### Full curl Command
```bash
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: <group-id>" \
  -d '{
    "query": "List all areas of inconsistency identified in the invoice, organized by: (1) all inconsistencies with corresponding evidence, (2) inconsistencies in goods or services sold including detailed specifications for every line item, and (3) inconsistencies regarding billing logistics and administrative or legal issues.",
    "force_route": "drift_multi_hop",
    "response_type": "summary"
  }'
```

---

## Test Groups

| Version | Group ID | Embedding Model | Embedding Dim | Date Indexed |
|---------|----------|-----------------|---------------|--------------|
| **V1** | `test-5pdfs-1769071711867955961` | OpenAI | 1536 | Jan 22, 2026 |
| **V2** | `test-5pdfs-v2-1769609082` | Voyage voyage-context-3 | 2048 | Jan 28, 2026 |

### Dataset: 5 PDFs
1. BUILDERS LIMITED WARRANTY.pdf
2. HOLDING TANK SERVICING CONTRACT.pdf
3. PROPERTY MANAGEMENT AGREEMENT.pdf
4. **contoso_lifts_invoice.pdf** ← Invoice being analyzed
5. **purchase_contract.pdf** ← Contract to compare against

---

## Test Results

### V1 Results: 11 Distinct Inconsistencies

#### (1) All Inconsistencies with Corresponding Evidence
1. **Lift model mismatch** - Invoice: Savaria V1504 vs. Contract: AscendPro VPX200
2. **Cab feature omission** - Invoice omits "keyless access" required in Exhibit A
3. **Door specification divergence** - Invoice adds "80\" High low profile" and "WR-500 lock" not in contract
4. **Hall call station type omission** - Invoice omits "flush-mount" requirement
5. **Outdoor package terminology ambiguity** - "Outdoor fitting" vs. "Outdoor configuration package"
6. **Payment terms conflict** - Invoice demands full $29,900 at signing vs. contract's 3 installments ($20,000 → $7,000 → $2,900)
7. **Customer name inconsistency** - "Fabrikam Construction" vs. "Fabrikam Inc."
8. **Job identification ambiguity** - Invoice uses Dayton address while Exhibit A references Bayfront Animal Clinic in Tampa
9. **Malformed online payment URL** - "https://ww.contosolifts.com/portal/pay" (missing 'w')
10. **Tax handling ambiguity** - "TAX N/A" on invoice vs. contract silence on tax
11. **Lack of referenced change order** - Changed specifications without written change documentation

#### (2) Inconsistencies in Goods/Services (Detailed Specifications)
- **Lift:** Savaria V1504 ($11,200) ≠ AscendPro VPX200
- **Cab:** 42" x 62", Type 3 90-degree matches, but missing keyless access feature
- **Door:** Invoice specifies 80" high, low profile, WR-500 lock; contract only requires aluminum door with plexi-glass and automatic opener
- **Hall Call stations:** Invoice: generic "Hall Call stations"; Contract: "Flush-mount Hall Call stations"
- **Outdoor configuration:** Invoice: "Outdoor fitting"; Contract: "Outdoor configuration package"

#### (3) Billing Logistics and Administrative/Legal Issues
**Billing Logistics:**
- Full contract amount invoiced as due at signing vs. agreed installment schedule
- "Initial payment" label contradicts amount due
- Malformed online payment URL
- "TAX N/A" without clarity on tax treatment

**Administrative/Legal:**
- Customer named as "Fabrikam Construction" instead of "Fabrikam Inc."
- No explicit reference to specific contract or job (Bayfront Animal Clinic)
- Specification changes without written change order, violating contract's "Changes" clause

#### V1 Citations (5 chunks - all relevant)
```
[1] contoso_lifts_invoice - chunk_0
[2] purchase_contract - chunk_0
[3] purchase_contract - chunk_2
[4] purchase_contract - chunk_1
[5] purchase_contract - chunk_3
```

---

### V2 Results: 7 Main Inconsistencies (Fewer Details)

#### (1) All Inconsistencies with Corresponding Evidence
1. **Lift model mismatch** - Invoice: Savaria V1504 vs. Contract: AscendPro VPX200
2. **Door hardware/specification mismatch** - Invoice adds WR-500 lock not specified in contract
3. **Hall call station description** - Invoice omits "flush-mount" requirement
4. **Payment schedule conflict** - Full $29,900 at signing vs. 3 installments
5. **Tax handling ambiguity** - "TAX N/A" vs. contract silence
6. **Product substitution without change order** - Different lift model without documentation
7. **Specification deviations without change order** - Hall call and door changes not authorized

#### Missing from V2 (compared to V1)
- ❌ **Customer name inconsistency** (Fabrikam Construction vs Inc.) - mentioned only briefly
- ❌ **Malformed payment URL** - NOT explicitly called out
- ❌ **"Keyless access" missing** - NOT mentioned as separate item
- ❌ **Job identification ambiguity** (Dayton vs Tampa) - NOT highlighted

#### V2 Citations (9 chunks - includes noise)
```
[1] PROPERTY MANAGEMENT AGREEMENT - chunk_0  ❌ (irrelevant)
[2] BUILDERS LIMITED WARRANTY - chunk_0       ❌ (irrelevant)
[3] contoso_lifts_invoice - chunk_0           ✓
[4] BUILDERS LIMITED WARRANTY - chunk_5       ❌ (irrelevant)
[5] purchase_contract - chunk_0               ✓
[6] purchase_contract - chunk_2               ✓
[7] HOLDING TANK SERVICING CONTRACT - chunk_0 ❌ (irrelevant)
[8] purchase_contract - chunk_1               ✓
[9] purchase_contract - chunk_3               ✓
```

---

## Comparative Analysis

### Summary Comparison

| Metric | V1 | V2 |
|--------|----|----|
| Total inconsistencies identified | **11** | **7** |
| Citations (chunks used) | 5 | 9 |
| Relevant citations | 5/5 (100%) | 5/9 (56%) |
| Irrelevant citations (noise) | 0 | 4 |
| Customer name issue detected | ✅ Yes | ⚠️ Brief mention |
| Malformed URL detected | ✅ Yes | ❌ No |
| Keyless access missing detected | ✅ Yes | ❌ No |
| Job location ambiguity detected | ✅ Yes | ❌ No |

### Root Cause Analysis

#### Graph Edge Comparison

| Edge Type | V1 | V2 | Notes |
|-----------|----|----|-------|
| SEMANTICALLY_SIMILAR (Entity-Entity) | **0** | **806** | V2 has KNN-created edges |
| SIMILAR_TO (Chunk-Chunk) | 50 | 0 | V1 threshold-filtered |
| Total Semantic Edges | 56 | 1012 | 18x more in V2 |

#### V2 Entity SEMANTICALLY_SIMILAR Edges (Cross-Document Noise)

V2's GDS KNN creates high-scoring edges between entities in **different documents**:

**Relevant connections (helpful):**
- "Invoice #1256003" <-> "Purchase Contract" (0.905)
- "Contract" <-> "Payment Terms" (0.908)
- "Fabrikam Construction" <-> "Purchase Contract" (0.884)

**Noisy connections (harmful):**
- "HOLDING TANK SERVICING CONTRACT" <-> "PROPERTY MANAGEMENT AGREEMENT" (0.849)
- "WI Code SPS 383.21(2)5" <-> "PROPERTY MANAGEMENT AGREEMENT" (0.800)

#### How Noise Affects Retrieval

1. Route 4 coverage retrieval starts with relevant entities (Invoice, Contract)
2. Follows SEMANTICALLY_SIMILAR edges to find related context
3. **KNN edges lead to irrelevant documents** (Property Management, Builders Warranty, Holding Tank)
4. Retrieval pulls chunks from those irrelevant documents
5. LLM receives **diluted context** with noise from 4 irrelevant document chunks
6. Result: Fewer specific inconsistencies detected, some details missed

---

## Conclusion

**V2's KNN-based Entity SEMANTICALLY_SIMILAR edges introduce noise during retrieval**, causing:
1. More chunks retrieved (9 vs 5)
2. Lower relevance ratio (56% vs 100%)
3. Fewer inconsistencies detected (7 vs 11)
4. Specific details missed (malformed URL, customer name, keyless access)

**This is NOT an embedding quality issue** - Voyage embeddings correctly identify semantic similarity. The problem is **KNN parameter/threshold tuning** that creates too many cross-document entity connections without sufficient filtering.

---

## Recommended Investigation Areas

1. **KNN Threshold Tuning** - Investigate if raising the similarity threshold for SEMANTICALLY_SIMILAR edges reduces cross-document noise
2. **Edge Filtering** - Consider filtering SEMANTICALLY_SIMILAR edges that connect entities from completely different document types
3. **Coverage Retrieval Strategy** - Modify coverage retrieval to prefer same-document connections over cross-document semantic edges
4. **Hybrid Approach** - Use V1-style chunk-level SIMILAR_TO edges with threshold filtering instead of KNN for entity edges

---

## KNN Tuning Plan

### Objective
Find the optimal KNN configuration that balances:
1. **Invoice consistency detection** (target: ≥10 inconsistencies, up from V2's 7)
2. **Q-D8 entity counting** (hard constraint: must pass - Contoso = 4 docs)
3. **Citation relevance** (target: ≥80%, up from V2's 56%)

### Current State (V2 Baseline)
- **806 Entity-to-Entity SEMANTICALLY_SIMILAR edges**
- Created via GDS KNN algorithm with default params (K=5, cutoff=0.60)
- Cross-document entity connections introduce noise during retrieval
- Q-D8 **passed** due to "Contoso Ltd." ↔ "Buyer/Owner" edge connecting to WARRANTY

### Implementation Complete ✅

KNN parameters are now exposed via the indexing API:

```bash
POST /hybrid/index/documents
{
  "documents": [...],
  "knn_enabled": true,        # Set to false to disable KNN entirely
  "knn_top_k": 5,            # Number of nearest neighbors (default: 5)
  "knn_similarity_cutoff": 0.60  # Minimum similarity threshold (default: 0.60)
}
```

**Files Modified:**
- [app/routers/hybrid.py](graphrag-orchestration/app/routers/hybrid.py): Added `knn_enabled`, `knn_top_k`, `knn_similarity_cutoff` to request model
- [app/hybrid_v2/indexing/lazygraphrag_pipeline.py](graphrag-orchestration/app/hybrid_v2/indexing/lazygraphrag_pipeline.py): Pass KNN params to GDS algorithms

### Test Groups to Create

| Group Name | knn_enabled | knn_top_k | knn_similarity_cutoff | Expected Edges |
|------------|-------------|-----------|----------------------|----------------|
| `test-5pdfs-v2-knn-disabled` | ❌ false | - | - | 0 |
| `test-5pdfs-v2-knn-1` | ✅ true | 3 | 0.80 | ~200? |
| `test-5pdfs-v2-knn-2` | ✅ true | 5 | 0.75 | ~500? |
| `test-5pdfs-v2-knn-3` | ✅ true | 5 | 0.85 | ~400? |

### Indexing Commands

```bash
# Group 1: KNN Disabled
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/index/documents" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-v2-knn-disabled" \
  -d '{
    "documents": [
      "https://graphragpoc.blob.core.windows.net/pdfdocs/contoso_lifts_invoice.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/purchase_contract.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/BUILDERS%20LIMITED%20WARRANTY.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"
    ],
    "ingestion": "document-intelligence",
    "reindex": true,
    "knn_enabled": false
  }'

# Group 2: KNN-1 (K=3, threshold=0.80 - tight)
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/index/documents" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-v2-knn-1" \
  -d '{
    "documents": [
      "https://graphragpoc.blob.core.windows.net/pdfdocs/contoso_lifts_invoice.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/purchase_contract.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/BUILDERS%20LIMITED%20WARRANTY.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"
    ],
    "ingestion": "document-intelligence",
    "reindex": true,
    "knn_enabled": true,
    "knn_top_k": 3,
    "knn_similarity_cutoff": 0.80
  }'

# Group 3: KNN-2 (K=5, threshold=0.75 - moderate)
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/index/documents" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-v2-knn-2" \
  -d '{
    "documents": [
      "https://graphragpoc.blob.core.windows.net/pdfdocs/contoso_lifts_invoice.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/purchase_contract.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/BUILDERS%20LIMITED%20WARRANTY.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"
    ],
    "ingestion": "document-intelligence",
    "reindex": true,
    "knn_enabled": true,
    "knn_top_k": 5,
    "knn_similarity_cutoff": 0.75
  }'

# Group 4: KNN-3 (K=5, threshold=0.85 - threshold-only)
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/index/documents" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-v2-knn-3" \
  -d '{
    "documents": [
      "https://graphragpoc.blob.core.windows.net/pdfdocs/contoso_lifts_invoice.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/purchase_contract.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/BUILDERS%20LIMITED%20WARRANTY.pdf",
      "https://graphragpoc.blob.core.windows.net/pdfdocs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf"
    ],
    "ingestion": "document-intelligence",
    "reindex": true,
    "knn_enabled": true,
    "knn_top_k": 5,
    "knn_similarity_cutoff": 0.85
  }'
```

### Test Queries

**Invoice Consistency Query:**
```bash
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: <GROUP_ID>" \
  -d '{
    "query": "List all areas of inconsistency identified in the invoice, organized by: (1) all inconsistencies with corresponding evidence, (2) inconsistencies in goods or services sold including detailed specifications for every line item, and (3) inconsistencies regarding billing logistics and administrative or legal issues.",
    "force_route": "drift_multi_hop",
    "response_type": "summary"
  }'
```

**Q-D8 Entity Counting Query:**
```bash
curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: <GROUP_ID>" \
  -d '{
    "query": "Across the set, which entity appears in the most different documents: Fabrikam Inc. or Contoso Ltd.?",
    "force_route": "drift_multi_hop",
    "response_type": "summary"
  }'
```

**Expected Q-D8 Answer (Ground Truth - Corrected):**
- Both **Fabrikam Inc.** and **Contoso Ltd.** appear in **4 documents each** (tied)
- Contoso Ltd. appears in: Invoice, Contract, Holding Tank, **WARRANTY (as Buyer/Owner)**

### Decision Matrix (Phase 1 - No De-noising)

| Config | KNN Edges | Q-D8 | Inconsistencies | Relevance | Items | Viable? |
|--------|-----------|------|-----------------|-----------|-------|---------|
| V1 (reference) | 0 | ✅ | 11 | 100% | 4/4 | - |
| V2 baseline | 806 | ✅ | 7 | 56% | 2/4 | Yes |
| knn-disabled | TBD | TBD | TBD | TBD | TBD | TBD |
| knn-1 (K=3, 0.80) | TBD | TBD | TBD | TBD | TBD | TBD |
| knn-2 (K=5, 0.75) | TBD | TBD | TBD | TBD | TBD | TBD |
| knn-3 (K=5, 0.85) | TBD | TBD | TBD | TBD | TBD | TBD |

*Any row with Q-D8 = ❌ is rejected (hard constraint).*

### Phase 1b: Decision Point

| If results show... | Then... |
|-------------------|---------|
| One KNN config achieves ≥10 + Q-D8 ✅ | **Done.** Use that config. |
| knn-disabled beats V2 baseline | Voyage alone is better; KNN adds noise only |
| All improve but not enough | **Phase 2:** Implement de-noising |
| All break Q-D8 | Re-evaluate constraints |

### Phase 2 (Only If Needed): De-noising

Implement cross-document edge penalty in Route 4 PPR traversal:
- **Soft (0.5):** Traverse edge but multiply score by 0.5
- **Hard (0.0):** Skip cross-document SEMANTICALLY_SIMILAR edges entirely

---

## Full Response Records

### V1 Full Response (test-5pdfs-1769071711867955961)

<details>
<summary>Click to expand V1 full response</summary>

```
## Analysis

Below, "invoice" refers to **contoso_lifts_invoice** and "contract" refers to the **purchase_contract** (and its Exhibit A) unless otherwise noted.

---

### Q1 & Q4 – All inconsistencies in the invoice, with clearly linked evidence

#### 1. Product model discrepancy: Savaria vs. AscendPro

- **Invoice description:**  
  The main lift line item is "Vertical Platform Lift (Savaria V1504)" with quantity 1 and total $11,200.00.[10]  
- **Contract scope of work:**  
  The contract requires "1 Vertical Platform Lift (AscendPro VPX200)" as the specified model.[13][14]  
- **Exhibit A scope of work:**  
  Exhibit A also specifies "1 Vertical Platform Lift (AscendPro VPX200)" for the job.[16][17]

**Inconsistency:**  
The invoice bills for a **Savaria V1504** lift, while the contract and Exhibit A require an **AscendPro VPX200** lift.[10][13][14][16][17]

---

#### 2. Cab description wording vs. contract wording

- **Invoice line item:**  
  "Special Size 42\" x 62\" cab with 90 degree Type 3" for $5,800.00.[10]  
- **Contract scope:**  
  "1 Custom cab 42\" x 62\" with Type 3 90-degree access."[13][14]  
- **Exhibit A:**  
  "1 Custom cab 42\" x 62\" with Type 3 90-degree access" and "Cab Size: 42\" x 62\", keyless access."[16][17]

**Inconsistency:**  
The **functional specification** (42\" x 62\", Type 3 90-degree access) matches, but the invoice uses "Special Size" and omits "custom" and "keyless access."[10][13][14][16][17]  
This is a **partial/specification inconsistency**: the core dimensions and access type align, but the invoice does not reflect the "keyless access" feature explicitly required in Exhibit A.[16][17]

---

#### 3. Door specification discrepancy: "low profile" vs. unspecified profile

- **Invoice line item:**  
  "80\" High low profile aluminum door with plexi-glass inserts, WR-500 lock, automatic door operator" for $5,000.00.[10]  
- **Contract scope:**  
  "1 Aluminum door with plexi-glass inserts & automatic opener."[13][14]  
- **Exhibit A:**  
  Same: "1 Aluminum door with plexi-glass inserts & automatic opener."[16][17]

**Inconsistency:**  
The invoice adds "80\" High low profile" and a specific "WR-500 lock," which are **not mentioned** in the contract or Exhibit A.[10][13][14][16][17]  
This is a **specification mismatch/extension**: the contract does not confirm that the door should be "low profile" or 80\" high or use a WR‑500 lock, so the invoice includes uncontracted technical details.

---

#### 4. Hall call station type discrepancy: flush‑mount vs. unspecified

- **Invoice line item:**  
  "2 Hall Call stations for bottom and upper landing" at $1,450.00 each, total $2,900.00.[10]  
- **Contract scope:**  
  "2 Flush-mount Hall Call stations (upper & lower)."[13][14]  
- **Exhibit A:**  
  Same: "2 Flush-mount Hall Call stations (upper & lower)."[16][17]

**Inconsistency:**  
The invoice does **not specify "flush-mount"**, while the contract and Exhibit A explicitly require **flush-mount** stations.[10][13][14][16][17]  
This is a **specification omission** that could allow a non‑flush‑mount product to be supplied under the invoice.

---

#### 5. Missing "keyless access" feature in cab description

- **Invoice cab line:**  
  "Special Size 42\" x 62\" cab with 90 degree Type 3."[10]  
- **Exhibit A:**  
  "Cab Size: 42\" x 62\", keyless access."[16][17]

**Inconsistency:**  
The contract's Exhibit A requires **keyless access** for the cab, but the invoice cab description does not mention keyless access at all.[10][16][17]  
This is a **feature omission** relative to the agreed scope.

---

#### 6. Price structure vs. contract payment terms

- **Invoice total:**  
  Subtotal $29,900.00, tax N/A, total $29,900.00, amount due $29,900.00.[10]  
- **Contract total and installments:**  
  Total contract price $29,900.00, payable in three installments:  
  – $20,000.00 upon signing  
  – $7,000.00 upon delivery  
  – $2,900.00 upon completion.[13][14]

**Inconsistency:**  
The invoice demands the **full $29,900.00** as "AMOUNT DUE" with comment "Initial payment in accordance with contract" and terms "Due on contract signing."[10]  
However, the contract states that **only $20,000.00** is due upon signing, with the remaining $9,900.00 due at later milestones.[13][14]  
Thus, the invoice's due amount and terms **conflict with the agreed installment schedule**.

---

#### 7. Customer name discrepancy: Fabrikam Construction vs. Fabrikam Inc.

- **Invoice customer:**  
  "TO: John Doe, Fabrikam Construction, 61 S 34th Street, Dayton, FL 33155."[10]  
- **Contract customer:**  
  "Fabrikam Inc. (Customer), located at 61 S 34th Street, Dayton, FL 33155."[13][14]

**Inconsistency:**  
The invoice is addressed to **"Fabrikam Construction"**, while the contract is with **"Fabrikam Inc."** at the same address.[10][13][14]  
This is a **legal entity name inconsistency** that may affect enforceability and clarity of who is contractually obligated.

---

#### 8. Job / project identification mismatch

- **Invoice:**  
  No explicit job name or project reference; only customer name and address.[10]  
- **Exhibit A:**  
  Job Name: "Bayfront Animal Clinic," with a different job location (811 Ocean Drive, Suite 405, Tampa, FL 33602).[16][17]  
- **Contract:**  
  Ties to the same parties and address as Exhibit A but does not explicitly name "Bayfront Animal Clinic" in the main body.[13][14][16][17]

**Inconsistency:**  
The invoice uses the **Dayton, FL** address and "Fabrikam Construction" but does not reference the **Bayfront Animal Clinic** job or the Tampa address used in Exhibit A.[10][16][17]  
This creates ambiguity as to whether the invoice is for the same project governed by the purchase contract and Exhibit A.

---

#### 9. Online payment URL appears malformed

- **Invoice payment instructions:**  
  "Payments can also be made via our online portal: https://ww.contosolifts.com/portal/pay."[10]

**Inconsistency:**  
The URL uses "https://ww.contosolifts.com/…" (two "w"s) instead of the standard "www."[10]  
This is a **logistical/administrative inconsistency** that could misdirect or prevent online payment.

---

#### 10. Tax handling ambiguity

- **Invoice:**  
  Shows "TAX N/A" and total equal to subtotal ($29,900.00).[10]  
- **Contract:**  
  Does not explicitly state whether the $29,900.00 is tax-inclusive or exclusive, nor how sales tax is to be handled.[13][14]

**Inconsistency:**  
Because the contract is silent on tax treatment and the invoice explicitly lists "TAX N/A," there is a **potential inconsistency/ambiguity** about whether tax is being properly applied or whether the contract price was intended to include tax.[10][13][14]  
This may have regulatory implications depending on Florida tax law.

---

### Q2 & Q5 – How detailed specifications reveal or support inconsistencies

Here we focus line‑item by line‑item on the invoice and compare to the contract/Exhibit A specifications.

#### A. Lift model line item

- **Invoice:** "Vertical Platform Lift (Savaria V1504)" – 1 unit, $11,200.00.[10]  
- **Contract/Exhibit A:** "1 Vertical Platform Lift (AscendPro VPX200)."[13][14][16][17]

**How this reveals inconsistency:**  
The **model name** is a core specification. A Savaria V1504 is a different product line than an AscendPro VPX200. The contract and Exhibit A consistently specify AscendPro VPX200, so billing for Savaria V1504 indicates either:  
- a unilateral substitution without written change order (contrary to the contract's "Changes" clause requiring written agreement), or  
- an error in the invoice description.[13][14]

Thus, the detailed model designation on the invoice directly evidences a **goods‑specification inconsistency**.[10][13][14][16][17]

---

#### B. Power system line item

- **Invoice:** "110 VAC 60 Hz up, 12 VAC down operation parts" – 1 unit, $3,000.00.[10]  
- **Contract/Exhibit A:** "1 Power system: 110 VAC 60 Hz up, 12 VAC down."[13][14][16][17]

**How this reveals inconsistency:**  
Here, the detailed specification **matches** the contract wording (110 VAC 60 Hz up, 12 VAC down).[10][13][14][16][17]  
This line item **supports consistency** and shows that the invoice is intended to correspond to the same project, which in turn strengthens the argument that the lift model discrepancy is not just a different job but a true inconsistency.

---

#### C. Cab line item

- **Invoice:** "Special Size 42\" x 62\" cab with 90 degree Type 3" – 1 unit, $5,800.00.[10]  
- **Contract/Exhibit A:**  
  – "1 Custom cab 42\" x 62\" with Type 3 90-degree access."[13][14][16][17]  
  – "Cab Size: 42\" x 62\", keyless access."[16][17]

**How this reveals inconsistency:**  
- The **dimensions (42\" x 62\")** and **Type 3 90-degree access** match, indicating the same basic configuration.[10][13][14][16][17]  
- However, the invoice omits "keyless access," a specific feature required in Exhibit A.[16][17]  
- The invoice uses "Special Size" instead of "Custom cab," which is not inherently inconsistent but is less precise relative to the contract language.[10][13][14][16][17]

Thus, the detailed cab specification on the invoice partially aligns but **fails to include a required feature**, revealing a **scope/specification shortfall**.

---

#### D. Outdoor configuration line item

- **Invoice:** "Outdoor fitting" – 1 unit, $2,000.00.[10]  
- **Contract/Exhibit A:** "1 Outdoor configuration package."[13][14][16][17]

**How this reveals inconsistency:**  
The invoice's "Outdoor fitting" is likely intended to correspond to the "Outdoor configuration package," but the wording is less specific and does not confirm that all elements of the "package" are included.[10][13][14][16][17]  
This is a **terminology/specification ambiguity**: the invoice's description is not clearly equivalent to the contract's "configuration package," leaving room for under‑delivery.

---

#### E. Door line item

- **Invoice:** "80\" High low profile aluminum door with plexi-glass inserts, WR-500 lock, automatic door operator" – 1 unit, $5,000.00.[10]  
- **Contract/Exhibit A:** "1 Aluminum door with plexi-glass inserts & automatic opener."[13][14][16][17]

**How this reveals inconsistency:**  
- The invoice adds **height (80\")**, **low profile**, and a specific **WR‑500 lock**, none of which are in the contract.[10][13][14][16][17]  
- The contract only requires an aluminum door with plexi‑glass inserts and automatic opener; it does not specify door profile, height, or lock model.[13][14][16][17]

These extra specifications could be beneficial or could represent a deviation from what was expected (e.g., if a different profile or lock type was desired). The mismatch shows the invoice is **not a clean reflection of the agreed specifications**, and any cost implications of these added features are not documented as a change order.

---

#### F. Hall call station line item

- **Invoice:** "2 Hall Call stations for bottom and upper landing" – 2 units at $1,450.00 each.[10]  
- **Contract/Exhibit A:** "2 Flush-mount Hall Call stations (upper & lower)."[13][14][16][17]

**How this reveals inconsistency:**  
The invoice omits the critical **"flush-mount"** requirement.[10][13][14][16][17]  
Given that flush‑mount vs. surface‑mount affects both aesthetics and installation, the omission is material. The detailed invoice description thus reveals a **potential downgrade or ambiguity** in the type of station being supplied.

---

#### G. Price and payment terms

- **Invoice:**  
  – Subtotal/Total: $29,900.00.[10]  
  – Comment: "Initial payment in accordance with contract."[10]  
  – Terms: "Due on contract signing."[10]  
  – Amount Due: $29,900.00.[10]  
- **Contract:**  
  – Total contract price: $29,900.00.[13][14]  
  – Payment schedule: $20,000.00 upon signing; $7,000.00 upon delivery; $2,900.00 upon completion.[13][14]

**How this reveals inconsistency:**  
The invoice's detailed payment terms and amount due show that it is **requesting the entire contract price at the initial milestone**, contrary to the contract's installment structure.[10][13][14]  
The explicit phrase "Initial payment in accordance with contract" is contradicted by the actual amount due, which is **not** in accordance with the contract.[10][13][14]  
This is a clear **billing logistics inconsistency**.

---

### Q3 & Q6 – Administrative and legal issues, with evidence

#### 1. Incorrect / inconsistent customer legal entity name

- **Invoice:** Customer is "Fabrikam Construction."[10]  
- **Contract:** Customer is "Fabrikam Inc."[13][14]

**Issue:**  
The invoice is not addressed to the exact legal entity that is party to the contract. This can create legal ambiguity about who owes the money and who is entitled to enforce the contract.[10][13][14]  
Evidence: differing names at the same address.

---

#### 2. Misalignment with contractual payment terms

- **Invoice:** Full $29,900.00 due on contract signing.[10]  
- **Contract:** Only $20,000.00 due upon signing; remaining amounts due later.[13][14]

**Issue:**  
The invoice's terms conflict with the contract's agreed payment schedule, potentially constituting a **breach of contract** if enforced as written.[10][13][14]  
This is both a **billing logistics** and **legal compliance** issue with the contract.

---

#### 3. Lack of explicit reference to the governing contract / job

- **Invoice:** No contract number or job name; only "P.O. NUMBER 30060204" and customer details.[10]  
- **Contract/Exhibit A:** Identify the parties and, in Exhibit A, the job name "Bayfront Animal Clinic" and Tampa job location.[13][14][16][17]

**Issue:**  
The invoice does not clearly reference the specific contract or job (e.g., "Bayfront Animal Clinic" or a contract number), which can create **administrative ambiguity** about which contract the invoice is tied to, especially since the address on the invoice (Dayton, FL) differs from the job location in Exhibit A (Tampa, FL).[10][16][17]

---

#### 4. Potential tax compliance ambiguity

- **Invoice:** "TAX N/A."[10]  
- **Contract:** No explicit tax clause.[13][14]

**Issue:**  
If Florida law requires sales tax on this type of equipment and installation, "TAX N/A" may indicate **non‑compliance** or at least a lack of clarity about whether tax is included in the contract price.[10][13][14]  
While the documents do not explicitly prove a violation, the inconsistency between a fixed contract price and an invoice that explicitly sets tax to "N/A" raises a **regulatory risk**.

---

#### 5. Online payment URL error

- **Invoice:** "https://ww.contosolifts.com/portal/pay."[10]

**Issue:**  
The malformed URL is an **administrative/logistical issue** that could prevent customers from paying via the advertised online portal, potentially affecting timely payment and creating disputes about late fees or default.

---

#### 6. Absence of explicit change documentation

- **Contract "Changes" clause:**  
  "Any changes must be agreed to in writing and will affect the next payment milestone."[13][14]  
- **Invoice:**  
  Shows a different lift model (Savaria V1504) and additional door specifications (low profile, WR‑500 lock) but does not reference any written change order.[10]

**Issue:**  
The presence of materially different specifications on the invoice without any reference to a written change order suggests **non‑compliance with the contract's change‑management requirement**.[10][13][14]  
This is a **legal/administrative inconsistency**.

---

## Key Connections

1. **Goods vs. Contract Scope:**  
   - The **lift model** (Savaria vs. AscendPro), **cab features** (missing keyless access), **door details**, and **hall call station type** all show that the invoice's line‑item specifications do not fully match the contract and Exhibit A.[10][13][14][16][17]  
   - These specification mismatches are not isolated; they collectively indicate that the invoice is not a faithful reflection of the agreed scope.

2. **Billing vs. Payment Terms:**  
   - The invoice's demand for the full contract price at signing directly conflicts with the contract's three‑installment structure.[10][13][14]  
   - This connects the **technical/specification inconsistencies** with **financial/logistical inconsistencies**, suggesting broader misalignment between contract and invoice.

3. **Administrative / Legal Identity and Job Reference:**  
   - The customer name difference (Fabrikam Construction vs. Fabrikam Inc.) and the lack of explicit job reference on the invoice, combined with the different job location in Exhibit A, create uncertainty about which legal entity and which project the invoice pertains to.[10][13][14][16][17]  
   - This administrative ambiguity interacts with the specification and payment inconsistencies to increase legal risk.

4. **Change‑management and Compliance:**  
   - The contract requires written agreement for changes, yet the invoice reflects changed or additional specifications (different lift model, door details) without referencing any change order.[10][13][14]  
   - This ties the **technical deviations** directly to a **contractual compliance issue**.

5. **Tax and Regulatory Ambiguity:**  
   - The "TAX N/A" entry on the invoice, against a contract that is silent on tax, raises potential compliance questions and connects the **financial** and **regulatory** dimensions of the inconsistencies.[10][13][14]

---

## Conclusion

Organized by the structure requested in the original query:

### (1) All inconsistencies with corresponding evidence

- **Lift model mismatch:** Invoice bills for "Savaria V1504" vs. contract's "AscendPro VPX200."[10][13][14][16][17]  
- **Cab feature omission:** Invoice cab description omits "keyless access" required in Exhibit A.[10][16][17]  
- **Door specification divergence:** Invoice adds "80\" High low profile" and "WR‑500 lock," not specified in contract/Exhibit A.[10][13][14][16][17]  
- **Hall call station type omission:** Invoice omits "flush-mount" requirement.[10][13][14][16][17]  
- **Outdoor package terminology ambiguity:** "Outdoor fitting" vs. "Outdoor configuration package."[10][13][14][16][17]  
- **Payment terms conflict:** Invoice demands full $29,900.00 at signing vs. contract's three‑installment schedule.[10][13][14]  
- **Customer name inconsistency:** "Fabrikam Construction" vs. "Fabrikam Inc."[10][13][14]  
- **Job identification ambiguity:** Invoice lacks job name and uses Dayton address, while Exhibit A references Bayfront Animal Clinic in Tampa.[10][16][17]  
- **Malformed online payment URL:** "https://ww.contosolifts.com/portal/pay."[10]  
- **Tax handling ambiguity:** "TAX N/A" on invoice vs. contract silence on tax.[10][13][14]  
- **Lack of referenced change order:** Changed specifications on invoice without written change documentation as required by contract.[10][13][14]

### (2) Inconsistencies in goods or services sold, with detailed specifications

- **Lift:** Savaria V1504 (invoice) vs. AscendPro VPX200 (contract/Exhibit A).[10][13][14][16][17]  
- **Cab:** 42\" x 62\", Type 3 90‑degree access on both, but invoice omits keyless access required in Exhibit A.[10][16][17]  
- **Door:** Invoice specifies 80\" high, low profile, WR‑500 lock; contract only requires aluminum door with plexi‑glass inserts and automatic opener.[10][13][14][16][17]  
- **Hall call stations:** Invoice generic "Hall Call stations"; contract requires "Flush-mount Hall Call stations."[10][13][14][16][17]  
- **Outdoor configuration:** Invoice "Outdoor fitting" vs. contract "Outdoor configuration package."[10][13][14][16][17]

Each of these detailed specifications either **directly contradicts** or **fails to fully reflect** the contract and Exhibit A, thereby supporting the identified inconsistencies.

### (3) Inconsistencies regarding billing logistics and administrative/legal issues

- **Billing logistics:**  
  – Full contract amount invoiced as due at signing vs. agreed installment schedule.[10][13][14]  
  – "Initial payment in accordance with contract" statement contradicted by the amount due.[10][13][14]  
  – Malformed online payment URL.[10]  
  – "TAX N/A" without clarity on tax treatment.[10][13][14]

- **Administrative/legal:**  
  – Customer named as "Fabrikam Construction" instead of "Fabrikam Inc."[10][13][14]  
  – No explicit reference to the specific contract or job (e.g., Bayfront Animal Clinic), despite differing job location in Exhibit A.[10][16][17]  
  – Specification changes (different lift model, door details) without reference to a written change order, contrary to the contract's "Changes" clause.[10][13][14]

Taken together, these issues show that the invoice is **not fully consistent** with the governing purchase contract and Exhibit A in terms of product specifications, payment terms, and administrative/legal details.
```

**Metadata:**
- Route: `route_4_drift_multi_hop`
- Confidence Score: 0.4 (confidence loop triggered)
- Sub-questions decomposed: 6
- Text chunks used: 17
- Coverage retrieval: applied (section_based_hybrid_reranked)

**Citations:**
```json
[
  {"index": 1, "document_title": "contoso_lifts_invoice", "chunk_id": "doc_2d0e8d47ba7540efa95d79743679c19e_chunk_0"},
  {"index": 2, "document_title": "purchase_contract", "chunk_id": "doc_6b62c0bafc0644f39d2d17e3e7433c22_chunk_0"},
  {"index": 3, "document_title": "purchase_contract", "chunk_id": "doc_6b62c0bafc0644f39d2d17e3e7433c22_chunk_2"},
  {"index": 4, "document_title": "purchase_contract", "chunk_id": "doc_6b62c0bafc0644f39d2d17e3e7433c22_chunk_1"},
  {"index": 5, "document_title": "purchase_contract", "chunk_id": "doc_6b62c0bafc0644f39d2d17e3e7433c22_chunk_3"}
]
```

</details>

---

### V2 Full Response (test-5pdfs-v2-1769609082)

<details>
<summary>Click to expand V2 full response</summary>

```
## Analysis

Below, "invoice" refers to **contoso_lifts_invoice** and "contract" to **purchase_contract** (and its Exhibit A). I focus only on inconsistencies that can be grounded in the provided documents.

---

### Q1 & Q4 – All identified inconsistencies and their evidence

#### 1. Product model discrepancy (lift model)

- **Inconsistency:**  
  The invoice bills for a **Savaria V1504** vertical platform lift, while the contract and Exhibit A specify an **AscendPro VPX200** lift.

- **Invoice evidence:**  
  - Line item: "Vertical Platform Lift (**Savaria V1504**)" with quantity 1 and total $11,200.00.[10]

- **Contract / Exhibit evidence:**  
  - Purchase Contract Scope of Work: "1 Vertical Platform Lift (**AscendPro VPX200**)"[13][14]  
  - Exhibit A – Scope of Work: "1 Vertical Platform Lift (**AscendPro VPX200**)"[16][17]

- **Conclusion:**  
  The model of lift invoiced (Savaria V1504) does not match the model contracted (AscendPro VPX200).[10][13][14][16][17]

---

#### 2. Door specification discrepancy

- **Inconsistency:**  
  The invoice describes a door with a specific lock model (WR‑500) and does not mention "flush‑mount," while the contract and Exhibit A specify a flush‑mount hall call configuration and a door without naming a lock model.

- **Invoice evidence:**  
  - Line item: "80\" High low profile aluminum door with plexi-glass inserts, **WR-500 lock, automatic door operator**"[10]

- **Contract / Exhibit evidence:**  
  - Contract Scope of Work: "1 Aluminum door with plexi-glass inserts & **automatic opener**" (no lock model specified).[13][14]  
  - Contract also specifies "2 **Flush-mount** Hall Call stations (upper & lower)"[13][14]  
  - Exhibit A repeats: "1 Aluminum door with plexi-glass inserts & automatic opener" and "2 **Flush-mount** Hall Call stations (upper & lower)"[16][17]

- **Nature of inconsistency:**  
  - The contract does not mention a WR‑500 lock at all.[13][14][16][17]  
  - The invoice adds a specific lock model (WR‑500) that is not clearly authorized or described in the contract documents.[10]  
  - While not a direct contradiction, this is a **specification mismatch / undocumented upgrade**: the invoiced door hardware is more specific than the contracted description.

---

#### 3. Hall call station description discrepancy

- **Inconsistency:**  
  The invoice describes "Hall Call stations for bottom and upper landing" without specifying "flush‑mount," whereas the contract and Exhibit A explicitly require **flush‑mount** hall call stations.

- **Invoice evidence:**  
  - Line item: "2 Hall Call stations for bottom and upper landing"[10]

- **Contract / Exhibit evidence:**  
  - Contract Scope of Work: "2 **Flush-mount** Hall Call stations (upper & lower)"[13][14]  
  - Exhibit A: "2 **Flush-mount** Hall Call stations (upper & lower)"[16][17]

- **Conclusion:**  
  The invoice omits the "flush‑mount" requirement that appears in the contract and Exhibit A, creating a **potential scope/specification inconsistency**.[10][13][14][16][17]

---

#### 4. Cab description wording discrepancy

- **Inconsistency:**  
  The invoice and contract describe the cab similarly but with slightly different wording; this is minor but worth noting.

- **Invoice evidence:**  
  - "Special Size 42\" x 62\" cab with 90 degree Type 3"[10]

- **Contract / Exhibit evidence:**  
  - "1 Custom cab 42\" x 62\" with Type 3 90-degree access"[13][14]  
  - Exhibit A: "1 Custom cab 42\" x 62\" with Type 3 90-degree access"[16][17]

- **Assessment:**  
  The dimensions and "Type 3 90-degree" concept match; the difference is phrasing ("Special Size" vs "Custom cab"). This is **not a substantive inconsistency** in quantity or function, but it is a **terminology variation** that could cause confusion if strict matching is required.[10][13][14][16][17]

---

#### 5. Payment timing / milestone description discrepancy

- **Inconsistency:**  
  The invoice describes the payment as "Initial payment in accordance with contract" and "Due on contract signing," while the contract specifies a structured three‑installment schedule with defined amounts.

- **Invoice evidence:**  
  - Comment: "Initial payment in accordance with contract"[10]  
  - Terms: "Due on contract signing"[10]  
  - Amount due on this invoice: $29,900.00 (see next item).[10]

- **Contract evidence:**  
  - Total contract price: $29,900.00.[13][14]  
  - Payment terms:  
    - "$20,000.00 upon signing"  
    - "$7,000.00 upon delivery"  
    - "$2,900.00 upon completion"[13][14]

- **Nature of inconsistency:**  
  - The invoice labels the entire $29,900.00 as "Due on contract signing," which conflicts with the contract's staged payment schedule.[10][13][14]  
  - The comment "Initial payment in accordance with contract" is inconsistent with the fact that the invoice demands the **full** contract price, not just the initial $20,000 installment.[10][13][14]

---

#### 6. Amount and milestone mismatch (full contract price invoiced as "initial payment")

- **Inconsistency:**  
  The invoice total equals the entire contract price, yet it is framed as an initial payment due at signing.

- **Invoice evidence:**  
  - Subtotal: $29,900.00; Tax: N/A; Total: $29,900.00; Amount Due: $29,900.00.[10]  
  - Comment: "Initial payment in accordance with contract"[10]  
  - Terms: "Due on contract signing"[10]

- **Contract evidence:**  
  - Total contract price: $29,900.00.[13][14]  
  - Initial payment upon signing: $20,000.00 (not $29,900.00).[13][14]

- **Conclusion:**  
  The invoice demands the **entire contract price** at signing, contrary to the contract's requirement that only $20,000 is due at signing and the remainder is due upon delivery and completion. This is a **major billing inconsistency**.[10][13][14]

---

#### 7. Tax treatment ambiguity

- **Inconsistency:**  
  The invoice lists "TAX: N/A," while the contract is silent on tax; this is not a direct contradiction but a potential compliance or expectation issue.

- **Invoice evidence:**  
  - Line: "TAX N/A"[10]

- **Contract evidence:**  
  - No explicit tax line or statement in the payment terms; only "Total contract price is $29,900.00, payable in 3 installments."[13][14]

- **Assessment:**  
  - Because the contract does not specify whether the $29,900.00 is tax‑inclusive or exclusive, "TAX: N/A" on the invoice could be consistent (if the price is tax‑inclusive) or inconsistent (if tax should be separately itemized under applicable law). The documents alone do not prove a violation, so this is best characterized as a **potential tax/administrative ambiguity**, not a confirmed inconsistency.[10][13][14]

---

### Q2 & Q5 – Documents, data points, and materials that demonstrate or relate to these inconsistencies

For each inconsistency above, the key evidence sources are:

1. **Invoice document – contoso_lifts_invoice**  
   - Provides all billed line items, descriptions, quantities, unit prices, total, tax line, terms, and comments.[10]  
   - Used to identify: product model (Savaria V1504), door description (WR‑500 lock), hall call description, cab description, payment terms ("Due on contract signing"), and total amount due ($29,900.00).[10]

2. **Purchase Contract – purchase_contract**  
   - Scope of Work: defines the contracted equipment and configuration, including model (AscendPro VPX200), power system, custom cab, outdoor package, aluminum door with plexi‑glass inserts & automatic opener, and 2 flush‑mount hall call stations.[13][14]  
   - Payment Terms: defines total price ($29,900.00) and the three‑installment schedule ($20,000 upon signing; $7,000 upon delivery; $2,900 upon completion).[13][14]  
   - These sections are the basis for identifying model, specification, and payment schedule inconsistencies.

3. **Exhibit A – Scope of Work**  
   - Reiterates and details the scope: AscendPro VPX200, 110 VAC/12 VAC power system, custom cab 42\" x 62\" with Type 3 90‑degree access, outdoor configuration, aluminum door with plexi‑glass inserts & automatic opener, 2 flush‑mount hall call stations, cab size, pit depth, and site prep responsibilities.[16][17]  
   - Confirms that the contracted model and configuration are AscendPro VPX200 and flush‑mount hall calls, reinforcing the inconsistencies with the invoice's Savaria V1504 and generic hall call description.[10][16][17]

4. **Other documents (Property Management Agreement, Builder's Limited Warranty, Holding Tank Servicing Contract)**  
   - These documents involve different parties, properties, and subject matter (property management, home construction warranty, holding tank servicing).[1][7][15]  
   - They do **not** relate to the elevator/lift invoice or its contract and therefore do not provide evidence of inconsistencies for this invoice.

Each inconsistency listed in Q1/Q4 is supported by a direct comparison between the invoice [10] and the contract/Exhibit A [13][14][16][17].

---

### Q3 & Q6 – Administrative or legal inconsistencies (contract compliance, required notices, signatures/authorizations)

Within the provided materials, the main administrative/legal issues related to the invoice are:

#### A. Non‑compliance with contractual payment schedule

- **Issue:**  
  The invoice's payment terms conflict with the contract's agreed installment schedule, which is a contract‑compliance problem.

- **Invoice evidence:**  
  - Terms: "Due on contract signing"[10]  
  - Amount Due: $29,900.00.[10]  
  - Comment: "Initial payment in accordance with contract"[10]

- **Contract evidence:**  
  - Payment Terms:  
    - "Total contract price is $29,900.00, payable in 3 installments:"  
    - "$20,000.00 upon signing"  
    - "$7,000.00 upon delivery"  
    - "$2,900.00 upon completion"[13][14]

- **Legal/administrative implication:**  
  - Issuing an invoice that demands the full contract price at signing, contrary to the agreed installment schedule, is a **billing practice inconsistent with the contract** and could be treated as a breach or at least a non‑conforming demand for payment.[10][13][14]

---

#### B. Scope of work / product substitution without documented change order

- **Issue:**  
  The invoice appears to bill for a different lift model (Savaria V1504) than the one specified in the contract (AscendPro VPX200), with no evidence of a written change order as required by the contract.

- **Invoice evidence:**  
  - "Vertical Platform Lift (Savaria V1504)"[10]

- **Contract evidence:**  
  - "1 Vertical Platform Lift (AscendPro VPX200)"[13][14]  
  - Changes clause: "Any changes must be agreed to in writing and will affect the next payment milestone."[13][14]

- **Legal/administrative implication:**  
  - Billing for a different model without a documented written change order is inconsistent with the contract's "Changes" clause and may constitute an **unauthorized product substitution** or non‑compliant invoice.[10][13][14]

---

#### C. Specification deviations (hall call stations, door hardware) without documented change order

- **Issue:**  
  The invoice's less‑specific hall call description and additional door lock detail are not clearly supported by the contract or a written change order.

- **Invoice evidence:**  
  - "2 Hall Call stations for bottom and upper landing"[10]  
  - "80\" High low profile aluminum door with plexi-glass inserts, WR-500 lock, automatic door operator"[10]

- **Contract / Exhibit evidence:**  
  - "2 Flush-mount Hall Call stations (upper & lower)"[13][14][16][17]  
  - "1 Aluminum door with plexi-glass inserts & automatic opener" (no lock model specified).[13][14][16][17]  
  - Changes must be agreed to in writing.[13][14]

- **Legal/administrative implication:**  
  - If the invoiced configuration differs materially from the specified "flush‑mount" hall calls or introduces hardware not agreed in writing, this may violate the contract's change‑management requirement.[10][13][14][16][17]  
  - The documents provided do not show any written change order, so the invoice is **not clearly supported** by the contract on these points.

---

#### D. Missing or unclear linkage to job/site and contract reference

- **Issue:**  
  The invoice does not explicitly reference the job name or Exhibit A site (Bayfront Animal Clinic, Tampa) or the contract's effective date, which can be an administrative weakness.

- **Invoice evidence:**  
  - Invoice lists customer as "John Doe / Fabrikam Construction, 61 S 34th Street, Dayton, FL 33155" and references P.O. Number "30060204," but does not mention "Bayfront Animal Clinic" or the Tampa job address.[10]

- **Contract / Exhibit evidence:**  
  - Contract customer: "Fabrikam Inc., 61 S 34th Street, Dayton, FL 33155."[13][14]  
  - Exhibit A job location: "Bayfront Animal Clinic, 811 Ocean Drive, Suite 405, Tampa, FL 33602."[16][17]

- **Assessment:**  
  - The invoice's "TO/SHIP TO" address matches the contract's customer address but not the job site.[10][13][14][16][17]  
  - This is more of an **administrative clarity issue** than a strict inconsistency; however, it can complicate contract compliance and audit trails.

---

#### E. Regulatory / legal notices, signatures, authorizations

- **Invoice evidence:**  
  - Standard invoice header, contact info, and payment portal link; no signatures or legal notices are required by the contract.[10]

- **Contract evidence:**  
  - The contract itself contains legal provisions (applicable law, right to cancel, etc.) but does not impose specific legal‑notice or signature requirements on invoices.[13][14]

- **Assessment:**  
  - There is **no clear evidence** in the provided documents that the invoice violates any explicit regulatory requirement or contract‑mandated legal notice/signature requirement.  
  - Thus, beyond the payment schedule and scope‑of‑work issues already identified, no additional administrative/legal inconsistencies can be substantiated from the corpus.

---

## Key Connections

1. **Goods/services vs. contract scope:**  
   - The **model discrepancy** (Savaria V1504 vs AscendPro VPX200) and **hall call/door specification differences** directly connect the invoice's line items to the contract's Scope of Work and Exhibit A.[10][13][14][16][17]  
   - These show that the invoiced goods/services are not a clean match to what was contractually agreed, and there is no documented change order as required by the contract.[13][14]

2. **Billing logistics vs. payment terms:**  
   - The invoice's "Due on contract signing" and full‑amount billing conflict with the contract's three‑installment payment structure.[10][13][14]  
   - This links the invoice's billing logistics to a clear contract‑compliance issue.

3. **Administrative/legal framework:**  
   - The contract's "Changes" clause and payment terms provide the legal framework against which the invoice must be evaluated.[13][14]  
   - The inconsistencies in model, specifications, and payment timing all represent **non‑alignment with these contractual provisions**, which is the core administrative/legal concern.

4. **Evidence mapping:**  
   - Every inconsistency is supported by a direct comparison between specific invoice lines [10] and specific contract/Exhibit clauses [13][14][16][17], ensuring that each factual claim is traceable.

---

## Conclusion

Organized by the structure you requested:

### (1) All inconsistencies with corresponding evidence

1. **Lift model mismatch:**  
   - Invoice: Savaria V1504.[10]  
   - Contract/Exhibit: AscendPro VPX200.[13][14][16][17]

2. **Door hardware/specification mismatch (WR‑500 lock not in contract):**  
   - Invoice: door with WR‑500 lock and automatic operator.[10]  
   - Contract/Exhibit: aluminum door with plexi‑glass inserts & automatic opener; no lock model specified.[13][14][16][17]

3. **Hall call station description vs. "flush‑mount" requirement:**  
   - Invoice: "Hall Call stations for bottom and upper landing" (no "flush‑mount").[10]  
   - Contract/Exhibit: "2 Flush-mount Hall Call stations (upper & lower)."[13][14][16][17]

4. **Payment schedule / amount due inconsistency:**  
   - Invoice: $29,900.00 due "on contract signing" and labeled as "Initial payment in accordance with contract."[10]  
   - Contract: total $29,900.00 payable in three installments ($20,000 at signing; $7,000 at delivery; $2,900 at completion).[13][14]

5. **Potential tax/administrative ambiguity:**  
   - Invoice: "TAX N/A."[10]  
   - Contract: silent on tax treatment.[13][14]  
   - This is a possible ambiguity, not a proven contradiction.

### (2) Inconsistencies in goods or services sold, with detailed specifications for each line item

- **Vertical Platform Lift:**  
  - Invoiced: 1 × "Vertical Platform Lift (Savaria V1504)" at $11,200.00.[10]  
  - Contracted: 1 × "Vertical Platform Lift (AscendPro VPX200)."[13][14][16][17]  
  - Inconsistency: different manufacturer/model.

- **Power system:**  
  - Invoiced: "110 VAC 60 Hz up, 12 VAC down operation parts" at $3,000.00.[10]  
  - Contracted: "1 Power system: 110 VAC 60 Hz up, 12 VAC down."[13][14][16][17]  
  - Inconsistency: wording differs ("operation parts" vs "power system"), but functionally aligned; no clear substantive conflict.

- **Cab:**  
  - Invoiced: "Special Size 42\" x 62\" cab with 90 degree Type 3" at $5,800.00.[10]  
  - Contracted: "1 Custom cab 42\" x 62\" with Type 3 90-degree access."[13][14][16][17]  
  - Inconsistency: minor terminology difference; specs (size and Type 3 90‑degree access) match.

- **Outdoor configuration:**  
  - Invoiced: "Outdoor fitting" at $2,000.00.[10]  
  - Contracted: "1 Outdoor configuration package."[13][14][16][17]  
  - Inconsistency: terminology difference only; likely same scope.

- **Door assembly:**  
  - Invoiced: "80\" High low profile aluminum door with plexi-glass inserts, WR-500 lock, automatic door operator" at $5,000.00.[10]  
  - Contracted: "1 Aluminum door with plexi-glass inserts & automatic opener."[13][14][16][17]  
  - Inconsistency: invoice adds specific WR‑500 lock not mentioned in contract; potential undocumented change or upgrade.

- **Hall Call stations:**  
  - Invoiced: "2 Hall Call stations for bottom and upper landing" at $1,450.00 each, total $2,900.00.[10]  
  - Contracted: "2 Flush-mount Hall Call stations (upper & lower)."[13][14][16][17]  
  - Inconsistency: invoice omits "flush‑mount" requirement.

### (3) Inconsistencies regarding billing logistics and administrative/legal issues

- **Billing logistics:**
  - Invoice demands full contract price at signing and labels it as "Initial payment," conflicting with the contract's three‑stage payment schedule.[10][13][14]  
  - This is a clear **billing logistics inconsistency**.

- **Contract compliance / change management:**
  - Invoice bills for a different lift model (Savaria V1504) than the contract's AscendPro VPX200, with no evidence of a written change order as required by the contract's "Changes" clause.[10][13][14]  
  - Specification differences in hall call stations and door hardware are also not supported by any documented change order.[10][13][14][16][17]

- **Administrative clarity:**
  - Invoice does not reference the job name or site (Bayfront Animal Clinic, Tampa) that appears in Exhibit A, which may complicate traceability but is not a direct contractual violation.[10][16][17]

- **Regulatory/legal notices and signatures:**
  - No explicit requirement in the contract for specific invoice notices or signatures, and no clear evidence that the invoice violates any such requirement.[10][13][14]

Overall, the most significant inconsistencies are:  
(1) the **lift model substitution** (Savaria V1504 vs AscendPro VPX200), and  
(2) the **billing of the full contract price at signing** contrary to the agreed installment schedule, both clearly supported by the cited documents.[10][13][14][16][17]
```

**Metadata:**
- Route: `route_4_drift_multi_hop`
- Confidence Score: 0.4 (confidence loop triggered)
- Sub-questions decomposed: 6
- Text chunks used: 17
- Coverage retrieval: applied (section_based_hybrid_reranked)

**Citations:**
```json
[
  {"index": 1, "document_title": "PROPERTY%20MANAGEMENT%20AGREEMENT", "chunk_id": "doc_22394262cf3e47d3b27d268d4aa03a64_chunk_0"},
  {"index": 2, "document_title": "BUILDERS%20LIMITED%20WARRANTY", "chunk_id": "doc_7bdf5ccf799540fb9e0d25e3da3d0180_chunk_0"},
  {"index": 3, "document_title": "contoso_lifts_invoice", "chunk_id": "doc_fb8f853cad5046ff9abac013552ad653_chunk_0"},
  {"index": 4, "document_title": "BUILDERS%20LIMITED%20WARRANTY", "chunk_id": "doc_7bdf5ccf799540fb9e0d25e3da3d0180_chunk_5"},
  {"index": 5, "document_title": "purchase_contract", "chunk_id": "doc_89a2c68e4e8b4d3d814bc73aea197e58_chunk_0"},
  {"index": 6, "document_title": "purchase_contract", "chunk_id": "doc_89a2c68e4e8b4d3d814bc73aea197e58_chunk_2"},
  {"index": 7, "document_title": "HOLDING%20TANK%20SERVICING%20CONTRACT", "chunk_id": "doc_cecff5cf491047d382262308a523310a_chunk_0"},
  {"index": 8, "document_title": "purchase_contract", "chunk_id": "doc_89a2c68e4e8b4d3d814bc73aea197e58_chunk_1"},
  {"index": 9, "document_title": "purchase_contract", "chunk_id": "doc_89a2c68e4e8b4d3d814bc73aea197e58_chunk_3"}
]
```

</details>

---

## Files for Reference

- **V1 Group:** `test-5pdfs-1769071711867955961`
- **V2 Group:** `test-5pdfs-v2-1769609082`
- **Question Bank:** `docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md`
- **Architecture:** `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` (lines 2216-2217 for group IDs)

---

## Phase 1: KNN Tuning Results (2026-01-29)

### Test Groups Created

Successfully created 4 KNN test groups with different configurations:

| Group ID | Name | KNN Enabled | K (neighbors) | Similarity Cutoff | KNN Edges Created |
|----------|------|-------------|---------------|-------------------|-------------------|
| `test-5pdfs-v2-knn-disabled` | KNN Disabled | No | 0 | 1.0 | **0** |
| `test-5pdfs-v2-knn-1` | KNN-1 | Yes | 3 | 0.80 | **268** |
| `test-5pdfs-v2-knn-2` | KNN-2 | Yes | 5 | 0.75 | **476** |
| `test-5pdfs-v2-knn-3` | KNN-3 | Yes | 5 | 0.85 | **444** |

**Baseline for comparison:** V2 baseline (`test-5pdfs-v2-1769609082`) has **806 edges** (K=5, cutoff=0.60)

### Indexing Commands

```bash
# Create all test groups
python3 ../scripts/index_5pdfs_knn_test.py

# Re-run GDS after session fix
python3 scripts/run_gds_knn.py
```

### GDS Session Fix Applied

**Problem:** GDS KNN failed with "Session expired due to inactivity" error when using hardcoded session name `"graphrag_session"`.

**Root Cause:** Sequential indexing runs attempted to reuse the same session name, but GdsSessions expire after inactivity and cannot be recreated without deletion.

**Solution:** Modified `lazygraphrag_pipeline.py` (lines 1614-1629):
- Changed session name to unique: `f"graphrag_session_{timestamp}_{random_suffix}"`
- Added `sessions.delete(session_name)` before creation to handle stale sessions
- Added session cleanup after successful completion
- Added session cleanup in exception handler

**Commit:** `186ca8f` - "Fix GDS session handling - use unique names and explicit cleanup"

### Entity and Relationship Counts

| Group | Entities | Relationships | KNN Edges | Louvain Communities | PageRank Nodes |
|-------|----------|---------------|-----------|---------------------|----------------|
| knn-disabled | 182 | 380 | 0 | 0 | 0 |
| knn-1 | 161 | 318 | 268 | 57 | 199 |
| knn-2 | 166 | 366 | 476 | 65 | 204 |
| knn-3 | 164 | 345 | 444 | 49 | 202 |

### KNN Configuration Analysis

**KNN Edge Counts vs Parameters:**
- V2 baseline (K=5, 0.60): 806 edges — **Too many** (56% citation relevance, cross-document noise)
- KNN-2 (K=5, 0.75): 476 edges — **Moderate reduction** (41% fewer edges)
- KNN-3 (K=5, 0.85): 444 edges — **Strict cutoff** (45% fewer edges)
- KNN-1 (K=3, 0.80): 268 edges — **Aggressive reduction** (67% fewer edges)
- KNN Disabled: 0 edges — **Maximum sparsity** (like V1)

**Hypothesis:** Reducing edge count should improve citation precision by eliminating cross-document semantic connections that cause noise in Route 4's PPR traversal and coverage retrieval stages.

### Next Steps

1. **Query Testing:** Run invoice consistency query on all 5 groups:
   - V2 baseline (806 edges)
   - knn-disabled (0 edges)
   - knn-1 (268 edges)
   - knn-2 (476 edges)
   - knn-3 (444 edges)

2. **Metrics to Record:**
   - Inconsistencies found
   - Citation relevance %
   - Q-D8 pass/fail (hard constraint: must find Contoso in WARRANTY)

3. **Decision Matrix:** Determine optimal KNN config:
   - Best case: ≥10 inconsistencies + Q-D8 ✅ → Done
   - Fallback: If no config passes both → Phase 2 (de-noising)

---

## Phase 1b: Query Testing Results (2026-01-29)

### Invoice Consistency Query Results

All 5 KNN configurations tested with the query:
> "Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms"

**Raw Results (as reported by counting tool):**

| Configuration | KNN Edges | Inconsistencies* | Citations | Relevance |
|---------------|-----------|------------------|-----------|-----------|
| **V2 Baseline** | 403 | 14 | 6 | 100% |
| **KNN Disabled** | 0 | 8 | 5 | 100% |
| **KNN-1** (K=3, 0.80) | 208 | 22 | 3 | 100% |
| **KNN-2** (K=5, 0.75) | 379 | 38 | 3 | 100% |
| **KNN-3** (K=5, 0.85) | 350 | 20 | 3 | 100% |

*Note: Inconsistency counts are inflated by keyword counting method - see corrected analysis below.

### ⚠️ CRITICAL CORRECTION: Quality Analysis

The raw "inconsistency counts" above are **misleading** - they count keyword occurrences, not actual distinct findings. Manual review of conclusions reveals the **actual quality**:

**V1 Reference (OpenAI, 0 edges):** Found **11 actual inconsistencies** including:
1. ✅ Lift model mismatch (Savaria V1504 vs AscendPro VPX200)
2. ✅ Cab keyless access missing
3. ✅ Door spec additions (80" High, WR-500 lock)
4. ✅ Hall call flush-mount requirement missing
5. ✅ Outdoor terminology (fitting vs configuration package)
6. ✅ **Payment terms conflict** ($29,900 at signing vs staged $20k/$7k/$2.9k)
7. ✅ Customer name (Fabrikam Construction vs Fabrikam Inc)
8. ✅ Job ID (Dayton FL vs Tampa/Bayfront Animal Clinic)
9. ✅ Malformed URL (https://ww... missing 'w')
10. ✅ Tax handling ambiguity
11. ✅ No written change order for spec changes

### Key Finding: Payment Conflict Detection

The **Payment Conflict** is a CRITICAL inconsistency:
- Contract: $20,000 at signing → $7,000 at delivery → $2,900 at completion
- Invoice: $29,900 due at signing (full amount!)

| Configuration | Payment Conflict Flagged? | Conclusion Quality |
|---------------|--------------------------|-------------------|
| V2 Baseline (403 edges) | ✗ **NO** | "No inconsistency in overall amount" |
| KNN Disabled (0 edges) | ✗ **NO** | "Amounts CONSISTENT" - **MISSED IT** |
| KNN-1 (208 edges) | ✓ **YES** | Correctly flagged milestone conflict |
| KNN-2 (379 edges) | ✓ **YES** | "Two key inconsistencies" - model + payment |
| KNN-3 (350 edges) | ✓ **YES** | Flagged payment timing conflict |

### Why KNN-Disabled Performed WORST

**KNN-Disabled (Voyage embeddings, 0 edges)** concluded:
> "the invoice is **CONSISTENT** with the contract in terms of amounts and quantities, and the **only** material inconsistency is the difference in the specified lift model"

This is **WORSE than V1** which found 11 issues including the payment conflict!

**Root Cause Hypothesis:** Without entity-entity KNN edges, the graph lacks connectivity to traverse from "invoice payment terms" → "contract payment schedule". The retrieval may have fetched chunks mentioning both values, but the lack of semantic connections prevented the LLM from recognizing them as conflicting information requiring synthesis.

### K=5 vs K=3 Interpretation

Your intuition about K=5 helping with relationships is partially correct:

- **K=3** (KNN-1): 208 edges - Found payment + model (good)
- **K=5** (KNN-2): 379 edges - Found payment + model with clearer focus (good)
- **K=5 strict** (KNN-3): 350 edges - Similar quality

With K=5, each entity connects to 5 nearest neighbors instead of 3. This provides:
- **More connection diversity** = more paths for PPR traversal
- **Not necessarily "longer range"** in document distance
- **Tradeoff:** Potentially more noise

The **cutoff threshold** matters more than K:
- Lower cutoff (0.75): More edges, looser similarity = better coverage
- Higher cutoff (0.85): Fewer edges, stricter similarity = less noise

### Actual Quality Ranking

Based on **conclusion quality** (not raw keyword counts):

1. **KNN-1, KNN-2, KNN-3** (tie): All correctly identified **both major issues** (lift model + payment conflict)
2. **V2 Baseline**: Found spec issues but **missed payment conflict**
3. **KNN Disabled**: **WORST** - only found 1 real issue (lift model)

### V1 vs V2 with KNN

| Finding | V1 (OpenAI, 0 edges) | V2 + KNN-enabled |
|---------|----------------------|------------------|
| Lift model mismatch | ✅ | ✅ |
| Payment conflict | ✅ | ✅ (only with KNN) |
| Keyless access | ✅ | ❓ (not explicit) |
| Flush-mount | ✅ | ✅ (mentioned) |
| Door specs (WR-500) | ✅ | ✅ |
| Outdoor terminology | ✅ | ✅ |
| Customer name | ✅ | ✅ |
| Job ID (Bayfront) | ✅ | ❌ |
| Malformed URL | ✅ | ❌ |
| Tax handling | ✅ | ✅ |
| Change order | ✅ | ✅ (implicit) |

**V1 found more minor issues** (URL, Job ID) but **V2 + KNN found the CRITICAL issues**.

### Corrected Conclusions

1. **KNN Disabled (0 edges)**: ❌ **WORST** - missing KNN edges cripples cross-document reasoning. Cannot properly synthesize payment terms from different document chunks.

2. **KNN-1/2/3 (208-379 edges)**: ✅ **ALL GOOD** - any amount of KNN edges above 0 enables proper cross-document synthesis. All three found both major inconsistencies.

3. **V2 Baseline (403 edges)**: ⚠️ **MIXED** - has edges but conclusion didn't flag payment conflict. May be LLM response variation, not structural.

4. **K=5 vs K=3**: Minimal quality difference. Both K values with reasonable cutoffs work well.

### Recommendation (REVISED)

**DO NOT USE knn_enabled=False** - it breaks cross-document reasoning.

For production, use any of:
- **K=3, cutoff=0.80** (fewer edges, slightly more focused)
- **K=5, cutoff=0.75** (more edges, broader coverage)
- **K=5, cutoff=0.85** (moderate edges, balance)

The "38 vs 22 vs 20" inconsistency counts are **not meaningful** - all three KNN-enabled configs perform similarly well in detecting the **actual critical issues**.

### Next Steps

1. **Run Q-D8 test** on all configs to verify Contoso WARRANTY detection (hard constraint)
2. **Re-run invoice query** with slightly different phrasing to test consistency
3. **Phase 2 (de-noising) likely NOT needed** since KNN-enabled configs achieve good quality

---

## Phase 2: Generic Alias Fix (2026-01-29)

### Root Cause: V2 Missing Generic Aliases

**Discovery:** V2 KNN-disabled was failing to find payment conflict because PPR couldn't resolve "Invoice" seed entity.

| Version | Invoice Entity Aliases | PPR Seed Resolution |
|---------|------------------------|---------------------|
| V1 | `['INVOICE', 'invoice 1256003']` | ✅ "Invoice" matches |
| V2 | `['INVOICE # 1256003', 'the invoice']` | ❌ No match for "Invoice" |

**Fix Applied:** Added `_generate_generic_aliases()` function to indexing pipeline and manually updated 138 entities in V2 KNN-disabled group with generic aliases.

### V2 (Generic Aliases, No KNN) - Full Test Results

After adding generic aliases to V2 KNN-disabled, re-ran the 3-part invoice consistency query.

---

## V1 vs V2 Full Output Comparison (2026-01-29)

### Query
> "List all areas of inconsistency identified in the invoice, organized by: (1) all inconsistencies with corresponding evidence, (2) inconsistencies in goods or services sold including detailed specifications for every line item, and (3) inconsistencies regarding billing logistics and administrative or legal issues."

---

### Side-by-Side: Section (1) All Inconsistencies with Evidence

| # | Inconsistency | V1 (OpenAI) | V2 (Voyage + Aliases) |
|---|---------------|-------------|----------------------|
| 1 | **Lift model mismatch** (Savaria V1504 vs AscendPro VPX200) | ✅ Found | ✅ Found |
| 2 | **Hall call stations** (missing "flush-mount") | ✅ Found | ✅ Found |
| 3 | **Door hardware** (WR-500 lock not in contract) | ✅ Found | ✅ Found |
| 4 | **Door specs** (80" height, low profile not in contract) | ✅ Found | ✅ Found |
| 5 | **Cab keyless access** (Exhibit A requires it, invoice silent) | ✅ Found | ❌ Not found |
| 6 | **Payment terms conflict** ($29,900 at signing vs staged) | ✅ Found | ✅ Found |
| 7 | **"Initial payment" mislabel** (full amount != initial) | ✅ Found | ✅ Found |
| 8 | **Customer name** (Fabrikam Construction vs Fabrikam Inc) | ✅ Found | ✅ Found |
| 9 | **Job identification** (missing Bayfront Animal Clinic/Tampa) | ✅ Found | ❌ Not explicit |
| 10 | **Malformed URL** (https://ww... missing 'w') | ✅ Found | ✅ Found |
| 11 | **Tax handling ambiguity** (TAX N/A vs contract silence) | ✅ Found | ✅ Found |
| 12 | **No written change order** (contract requires it) | ✅ Found | ✅ Found |
| 13 | **Power system wording** ("operation parts" vs "Power system") | ❌ Not flagged | ✅ Found |
| 14 | **Cab terminology** ("Special Size" vs "Custom cab") | ❌ Not flagged | ✅ Found |
| 15 | **Outdoor terminology** ("Outdoor fitting" vs "package") | ✅ Mentioned | ✅ Found |
| 16 | **PO/Contract reference ambiguity** | ❌ Not flagged | ✅ Found |
| 17 | **Right to cancel vs full payment** | ❌ Not flagged | ✅ Found |
| **TOTAL** | | **11-12** | **14-15** |

---

### Side-by-Side: Section (2) Goods/Services Line-Item Specifications

| Line Item | V1 Findings | V2 Findings |
|-----------|-------------|-------------|
| **Lift** (Savaria V1504) | ❌ Wrong model vs AscendPro VPX200 | ❌ Wrong model vs AscendPro VPX200 |
| **Power system** ($3,000) | ✅ Specs match (110 VAC/12 VAC) | ⚠️ "operation parts" vs "Power system" wording |
| **Cab** ($5,800) | ✅ Size matches, ❌ missing keyless access | ✅ Size matches, ⚠️ terminology differs |
| **Outdoor** ($2,000) | ✅ "fitting" ≈ "package" (minor) | ⚠️ "fitting" vs "package" (flagged) |
| **Door** ($5,000) | ❌ WR-500 lock not authorized, ❌ 80" height/low profile | ❌ WR-500 lock not authorized, ❌ 80" height/low profile |
| **Hall Call** ($2,900) | ❌ Missing "flush-mount" requirement | ❌ Missing "flush-mount" requirement |

---

### Side-by-Side: Section (3) Billing Logistics & Admin/Legal

| Issue | V1 | V2 |
|-------|----|----|
| **Full payment at signing vs 3 installments** | ✅ $29,900 vs $20k/$7k/$2.9k | ✅ $29,900 vs $20k/$7k/$2.9k |
| **"Initial payment" mislabel** | ✅ Full amount ≠ initial | ✅ Full amount ≠ initial |
| **Customer entity mismatch** | ✅ Fabrikam Construction vs Fabrikam Inc | ✅ Fabrikam Construction vs Fabrikam Inc |
| **Project identification missing** | ✅ No Bayfront Animal Clinic/Tampa | ⚠️ Mentioned briefly |
| **PO/Contract reference ambiguity** | ❌ Not flagged | ✅ Found |
| **Tax handling ambiguity** | ✅ TAX N/A vs silence | ✅ TAX N/A vs silence |
| **Malformed URL** | ✅ https://ww... | ✅ https://ww... |
| **No written change order** | ✅ Contract requires it | ✅ Contract requires it |
| **Right to cancel tension** | ❌ Not flagged | ✅ 3-day cancel vs full payment demand |

---

### Summary Metrics

| Metric | V1 (OpenAI) | V2 (Voyage + Aliases, No KNN) |
|--------|-------------|-------------------------------|
| **Section 1 inconsistencies** | 11 | 14-15 |
| **Section 2 line items analyzed** | 6/6 | 6/6 |
| **Section 3 admin/legal issues** | 7 | 9 |
| **Payment conflict found** | ✅ Yes | ✅ Yes |
| **Lift model mismatch** | ✅ Yes | ✅ Yes |
| **Keyless access issue** | ✅ Yes (explicit) | ❌ Not found |
| **Job ID (Bayfront/Tampa)** | ✅ Explicit | ⚠️ Brief |
| **PO/Contract reference** | ❌ No | ✅ Yes |
| **Right to cancel tension** | ❌ No | ✅ Yes |
| **Terminology issues** | ❌ Minimal | ✅ Flagged |
| **Answer length** | ~3,500 words | ~3,200 words |
| **Citations relevance** | 100% | 100% |

---

### Key Conclusions

1. **Both found CRITICAL issues**: Lift model, payment conflict, hall call flush-mount, door hardware, customer name
2. **V1 better on Exhibit A details**: Keyless access, Bayfront Animal Clinic/Tampa project
3. **V2 better on terminology/admin issues**: PO reference, power system wording, right-to-cancel tension
4. **Quality is COMPARABLE** after generic alias fix

---

## ROOT CAUSE DEEP DIVE: Why V2 Didn't Have Generic Aliases

### Architecture Discovery (2026-01-29)

**Q:** Why didn't V2 have generic aliases? Wasn't V2 built on top of V1's improved pipeline?

**A:** **NO.** V2 is a SEPARATE codebase, not derived from V1.

### Two Separate Pipelines

| Component | V1 Pipeline | V2 Pipeline |
|-----------|-------------|-------------|
| **Location** | `app/hybrid/indexing/lazygraphrag_pipeline.py` | `app/hybrid_v2/indexing/lazygraphrag_pipeline.py` |
| **Size** | ~100 KB | ~123 KB |
| **Embedding** | OpenAI `text-embedding-ada-002` | Voyage `voyage-3-large` |
| **KNN** | Not implemented | GDS KNN integration |
| **Generic Aliases** | ✅ Added Jan 19 (`faee71f`) | ❌ Missing (until today) |

### Git History Timeline

```
Jan 19, 2026 - faee71f - "feat: Auto-generate entity aliases when LLM doesn't provide them"
                        └── Applied to: app/hybrid/indexing/lazygraphrag_pipeline.py (V1)
                        └── NOT applied to: V2 (didn't exist yet!)

Jan 25, 2026 - 72280b2 - "feat(hybrid_v2): Phase 2 - Section-aware chunking + Voyage embeddings"
                        └── Created: app/hybrid_v2/indexing/lazygraphrag_pipeline.py
                        └── COPIED from V1 at some point BEFORE Jan 19 (alias feature)
```

### The Sequence of Events

1. **Before Jan 19:** V1 pipeline exists at `app/hybrid/indexing/`
2. **Jan 19:** Generic alias feature added to V1 (`faee71f`)
3. **Jan 25:** V2 pipeline created at `app/hybrid_v2/indexing/` 
   - Copy of V1 structure but **from an earlier snapshot** (before Jan 19)
   - OR manual adaptation that missed the alias feature
4. **Jan 29:** We discovered V2 missing aliases, added `_generate_generic_aliases()`

### Why the Feature Wasn't Ported

The `hybrid_v2` directory was created as a **parallel implementation**, not a branch:
- Different embedding model (Voyage vs OpenAI)
- Different features (GDS KNN, Louvain, PageRank)
- Independent development track

The alias feature in V1 (`app/hybrid/indexing/`) was never merged or ported to V2 (`app/hybrid_v2/indexing/`).

### Fix Applied

Added `_generate_generic_aliases()` to V2 pipeline at line 2030:
```python
def _generate_generic_aliases(name: str) -> List[str]:
    """Generate generic aliases for entity names lacking them."""
    # Extract base entity type (e.g., "INVOICE # 1256003" -> "INVOICE")
    # Provides PPR seed resolution for IntentDisambiguator
    ...
```

---

## Next Steps: Combining Aliases + KNN

### Hypothesis
V2 with BOTH generic aliases AND KNN edges should be optimal:
- **Generic aliases:** Enable PPR seed entity resolution (fixes "Invoice" → Invoice entity)
- **KNN edges:** Provide semantic bridges between related entities

### Recommended Test
| Config | Aliases | KNN K | KNN Cutoff |
|--------|---------|-------|------------|
| V2 Aliases-Only | ✅ | 0 | N/A |
| V2 Aliases+KNN | ✅ | 5 | 0.80 |
| V2 Aliases+KNN-Aggressive | ✅ | 10 | 0.75 |

### Expected Outcome
V2 Aliases+KNN should:
1. Resolve "Invoice" → Invoice entity (via aliases)
2. Bridge "Invoice amount" → "Payment terms" (via KNN)
3. Achieve V1-level quality + V2 extra findings

---

## 9. Critical Discovery: AsyncNeo4jService Connection Bug (2026-01-29 11:30 AM)

### 9.1 The Error

```
async_neo4j_ppr_failed error='AsyncNeo4jService not connected. Call connect() first.'
no_graph_store_available
```

**Impact**: Route 4 DRIFT was running WITHOUT graph traversal → NO multi-hop reasoning!

### 9.2 Root Cause

1. `HybridPipeline.__init__()` creates `AsyncNeo4jService` but doesn't connect
2. `await pipeline.initialize()` **MUST** be called to establish connection
3. Test scripts were **missing** `await pipeline.initialize()` call
4. Without connection, PPR graph traversal **fails completely**

### 9.3 The Dangerous Fallback (NOW REMOVED)

**Before**: When PPR failed, code had `_trace_with_fallback()` that returned seed entities unchanged:

```python
async def _trace_with_fallback(...):
    if not self.graph_store:
        logger.warning("no_graph_store_available")
        return [(entity, 1.0) for entity in seed_entities]  # Just return seeds!
```

**Problem**: Route 4 silently degraded to **vector-only search** (no graph, no multi-hop, no reasoning).

**After**: **Fail-fast approach** - raise explicit error:

```python
except Exception as e:
    logger.error("async_neo4j_ppr_failed", error=str(e))
    raise RuntimeError(
        f"Route 4 DRIFT requires AsyncNeo4jService for PPR graph traversal. "
        f"Error: {e}. Ensure pipeline.initialize() was called."
    )
```

**Rationale**: Vector-only cannot do multi-hop reasoning. Better to fail loudly than pretend to work.

### 9.4 Fixes Applied

**1. Scripts Fixed** (added `await pipeline.initialize()`):
- `scripts/test_knn_direct.py`
- `scripts/test_v1_v2_differentiation.py`

**2. Fallback Removed** (replaced with fail-fast):
- `app/hybrid/pipeline/tracing.py`
- `app/hybrid_v2/pipeline/tracing.py`
- `app/hybrid_v2/hybrid/pipeline/tracing.py`

**3. Production API** - Already correct:
- `app/routers/hybrid.py` line 268: `await pipeline.initialize()`

### 9.5 No Deployment Needed

**Production is FINE** - the API already calls `initialize()`. This bug only affected test scripts.

Test can run immediately after script fix.

---

## 10. Summary

### Issues Found & Fixed Today

1. **✅ V2 Missing Generic Aliases** → Added `_generate_generic_aliases()`
2. **✅ AsyncNeo4j Connection Bug** → Fixed test scripts, removed dangerous fallback
3. **✅ HippoRAG Seed Resolution** → Added alias + KVP key matching (5-strategy)
4. **✅ Architecture Documentation** → Updated with Jan 29 changes

### Testing Status

- **V1 vs V2 Comparison Test** - Running now with proper connection
- **Expected**: V2 (with aliases) should match or exceed V1 quality
- **Deployment**: NOT needed (production already has initialize() call)

---

## 11. Corrected V1 vs V2 Comparison (2026-01-29 1:10 PM)

### 11.1 Test Configuration

| Property | V1 | V2 |
|----------|----|----|
| **Pipeline** | `app/hybrid/orchestrator.py` | `app/hybrid_v2/orchestrator.py` |
| **Group ID** | `test-5pdfs-1769071711867955961` | `test-5pdfs-v2-knn-disabled` |
| **Embedding Model** | OpenAI text-embedding-3-large | Voyage voyage-context-3 |
| **Chunks in Group** | 17 | 17 |
| **Neo4j Driver** | Sync (required) | Sync (required) |

### 11.2 Critical Fix: `neo4j_driver` Required for Both Pipelines

**Root Cause Found:** V2's `EnhancedGraphRetriever.get_all_documents()` returned 0 documents because `self.driver` was `None`.

**Fix:** Both V1 and V2 require a **sync** `neo4j_driver` passed to the constructor:

```python
from neo4j import GraphDatabase

neo4j_driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
)

# V1
pipeline_v1 = V1Pipeline(
    group_id=V1_GROUP,
    llm_client=llm_client,
    neo4j_driver=neo4j_driver,  # REQUIRED
    text_unit_store=text_store   # Optional but recommended
)

# V2 - SAME PATTERN
pipeline_v2 = V2Pipeline(
    group_id=V2_GROUP,
    llm_client=llm_client,
    neo4j_driver=neo4j_driver  # REQUIRED - same as V1!
)
```

**Test Script Created:** `scripts/test_route4_v1_v2_invoice_consistency.py`

### 11.3 Test Results (Original 3-Part Query)

**Query:**
```
List all areas of inconsistency identified in the invoice, organized by: 
(1) all inconsistencies with corresponding evidence, 
(2) inconsistencies in goods or services sold including detailed specifications for every line item, and 
(3) inconsistencies regarding billing logistics and administrative or legal issues.
```

| Metric | V1 | V2 | Notes |
|--------|----|----|-------|
| **Latency** | 242.3s | 164.4s | V2 32% faster |
| **Response Length** | 21,468 chars | 20,809 chars | ~3% smaller |
| **Citations** | 2 | 9 | V2 more citations |
| **Coverage Chunks** | 17 | 17 | Same |

### 11.4 Key Findings Coverage

| Finding | V1 | V2 |
|---------|:--:|:--:|
| **Savaria V1504 vs AscendPro VPX200** | ✓ | ✓ |
| **$29,900 amount** | ✓ | ✓ |
| **Fabrikam Inc vs Construction** | ✓ | ✓ |
| **Flush-mount omitted** | ✓ | ✓ |
| **Outdoor config vs fitting** | ✓ | ✓ |
| **WR-500 lock** | ✓ | ✓ |
| **Payment installments ($20,000)** | ✓ | ✓ |
| **Keyless access** | ✗ | ✗ |

**Summary:** Both V1 and V2 cover 8/9 key findings equally. Neither mentions "keyless access" in this run.

**Note on Sections 1-10:** The original "11 inconsistencies" findings (including keyless access) were from **earlier API calls** which may have had different LLM synthesis or prompt behavior. Today's direct pipeline tests show V1 and V2 perform identically on key findings.

### 11.5 Response Quality Comparison

**V1 Strengths:**
- More structured "Knowns/Unknowns/Interpretations" format
- Detailed "To resolve" sections

**V2 Strengths:**
- 32% faster execution
- More citations (9 vs 2)
- Better document identification (Invoice #1256003, dated 12/17/2015)
- Cleaner numbered inconsistency list

**Both Cover:**
- Lift model mismatch (Savaria V1504 vs AscendPro VPX200)
- Payment amount conflict ($29,900 at signing vs installments)
- Customer name discrepancy (Fabrikam Inc vs Construction)
- Terminology differences (outdoor fitting, flush-mount, door specs)
- Administrative gaps (no contract reference on invoice)

### 11.6 Conclusion

**V2 with proper `neo4j_driver` achieves V1-equivalent quality:**
- ✓ All major inconsistencies identified
- ✓ Proper citations to source documents
- ✓ Coverage gap fill works (17 chunks from 5 docs)
- ✓ Faster execution (32% improvement)

**The earlier "V2 found 0 evidence" failures were due to missing `neo4j_driver`, not embedding model differences.**

---

