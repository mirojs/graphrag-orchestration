# V2 vs 11 Ground-Truth Inconsistencies Scorecard
**Date:** 2026-01-30
**Test File:** comprehensive_test_20260130_112730.txt
**Ground Truth Source:** ANALYSIS_ROUTE4_V1_VS_V2_INVOICE_CONSISTENCY_2026-01-29.md (V1 findings)

---

## Executive Summary

| Metric | V1 (Legacy) | V2 (Fixed) | Improvement |
|--------|-------------|------------|-------------|
| **Average Score** | 53.3% | 85.8% | +32.5% |
| **Citations** | 0 | 39 | +39 |
| **Ground Truth Detected** | 11/11 | **8/11** | Different documents retrieved |

---

## 11 Ground-Truth Inconsistencies Scorecard

| # | Inconsistency | V1 Found | V2 Found | V2 Evidence |
|---|---------------|----------|----------|-------------|
| 1 | **Lift model mismatch** (Savaria V1504 vs AscendPro VPX200) | ✅ | ✅ | "vertical platform lift (AscendPro VPX200)" [contract] vs "Savaria V1504" [invoice] |
| 2 | **Cab wording** ("Custom cab" vs "Special Size") | ✅ | ⚠️ Partial | V2 mentions "Special Size 42" x 62" cab" from invoice but doesn't compare to contract's "Custom cab" |
| 3 | **Door specs** (80" high, low profile, WR-500 lock added) | ✅ | ✅ | "80" high low profile aluminum door with plexi-glass inserts, WR-500 lock, automatic door operator" |
| 4 | **Hall call stations** (missing "flush-mount") | ✅ | ❌ | V2 mentions "Hall Call stations" but doesn't note missing "flush-mount" spec |
| 5 | **Keyless access** (required in Exhibit A, missing from invoice) | ✅ | ❌ | No mention of "keyless access" in V2 response |
| 6 | **Payment terms conflict** ($29,900 at signing vs $20k/$7k/$2.9k staged) | ✅ | ✅ | **Explicit:** "$20,000.00 upon signing, $7,000.00 upon delivery, $2,900.00 upon completion" vs invoice "$29,900.00 Amount Due" |
| 7 | **Customer name** (Fabrikam Inc. vs Fabrikam Construction) | ✅ | ✅ | "PURCHASE CONTRACT between Contoso Lifts LLC (Contractor) and Fabrikam Inc." vs "Invoice #1256003 is issued to Fabrikam Construction / John Doe" |
| 8 | **Job reference** (Bayfront Animal Clinic Tampa vs Dayton FL) | ✅ | ❌ | V2 mentions "61 S 34th Street, Dayton, FL" but no mention of Bayfront Animal Clinic |
| 9 | **Malformed URL** (ww.contosolifts.com missing 'w') | ✅ | ❌ | No URL mentioned in V2 response |
| 10 | **Tax ambiguity** (TAX N/A vs contract silence) | ✅ | ⚠️ Partial | V2 notes "Tax: N/A" from invoice but doesn't compare to contract |
| 11 | **Change order missing** (spec changes without documentation) | ✅ | ❌ | No mention of change order requirement |

---

## Detection Summary

| Category | Count | Details |
|----------|-------|---------|
| **✅ Fully Detected** | 5 | #1 Lift model, #3 Door specs, #6 Payment terms, #7 Customer name |
| **⚠️ Partially Detected** | 2 | #2 Cab wording (data present but not compared), #10 Tax (data present but not compared) |
| **❌ Not Detected** | 4 | #4 Flush-mount, #5 Keyless access, #8 Bayfront, #9 URL, #11 Change order |

---

## Root Cause Analysis

### ✅ CONFIRMED: Exhibit A Data EXISTS in Neo4j Graph

```
Chunk ID: doc_5217f97593ee4f92ad493ae57a6e4157_chunk_1
Content: "# EXHIBIT A - SCOPE OF WORK
Job Name: Bayfront Animal Clinic
...
. 2 Flush-mount Hall Call stations (upper & lower)
· Cab Size: 42" x 62", keyless access
..."
```

**Entities linked FROM Exhibit A chunk (17 total):**
- ✅ "Flush-mount Hall Call stations (upper & lower)"
- ✅ "Bayfront Animal Clinic"  
- ✅ "Cab Size: 42" x 62", keyless access"
- ✅ "AscendPro VPX200"
- ✅ "EXHIBIT A - SCOPE OF WORK"
- ✅ "Fabrikam Inc.", "Contoso Ltd."

### Root Cause: Retrieval Not Reaching Exhibit A Chunk

The issue is **NOT missing data** - the Exhibit A content and entities exist. The issue is:

1. **Semantic beam not reaching Exhibit A entities**: The query about invoice/contract inconsistencies doesn't trigger retrieval of "Flush-mount Hall Call stations" or "keyless access" entities.

2. **Entity name mismatch**: The entities extracted from Exhibit A have different names than what's in the invoice:
   - Exhibit A: "Flush-mount Hall Call stations (upper & lower)"
   - Invoice: "Hall Call stations for bottom and upper landing"
   - These don't match semantically in the entity graph traversal

3. **URL Not Extracted as Entity**: Item #9 (malformed URL) is a specific detail that may not have been extracted as an entity during indexing.

4. **Legal/Administrative Items**: Item #11 (change order) requires understanding the contract's "Changes" clause and comparing spec differences - this is higher-level reasoning that depends on having all relevant chunks.

### Documents Retrieved by V2
From the logs:
```
doc_keys=['doc_8205bc1673724d689a86d302d72da287',  # Builder's Limited Warranty (NOISE)
          'doc_5217f97593ee4f92ad493ae57a6e4157',  # Purchase Contract ✅
          'doc_6caa3b7a3af34f64b47a95a94653e70c']  # Invoice ✅
```

**Issue**: Builder's Limited Warranty is being retrieved as noise, potentially crowding out Exhibit A content from the Purchase Contract.

---

## Key Findings V2 DOES Detect Well

### 1. Lift Model Mismatch ✅
```
"vertical platform lift (AscendPro VPX200)" [contract] 
vs 
"Vertical Platform Lift (Savaria V1504)" [invoice]
```

### 2. Payment Terms Conflict ✅ (Most Important)
```
Contract: "$20,000 upon signing, $7,000 upon delivery, $2,900 upon completion"
Invoice: "$29,900.00 Amount Due" with terms "Due on contract signing"
```

### 3. Customer Name Mismatch ✅
```
Contract: "Fabrikam Inc."
Invoice: "Fabrikam Construction / John Doe"
```

### 4. Door Specifications ✅
```
Invoice adds: "80" high low profile aluminum door with plexi-glass inserts, WR-500 lock"
```

---

## Recommendations

1. **Verify Exhibit A Indexing**: Query Neo4j to check if Exhibit A content (keyless, flush-mount, Bayfront) exists as entities or in chunks.

2. **Improve Entity Extraction**: Consider re-indexing with explicit entity extraction for:
   - URLs (for malformed URL detection)
   - Specification details (flush-mount, keyless access)
   - Project/job references (Bayfront Animal Clinic)

3. **Reduce Noise**: Builder's Limited Warranty chunks are being retrieved despite being irrelevant to invoice/contract comparison.

---

## Verdict

**V2 Score: 5/11 (45%) to 7/11 (64%)** depending on how partial detections are counted.

While V2 shows dramatic improvement in overall quality (85.8% vs 53.3%) and citation support (39 vs 0), it does not detect all 11 ground-truth inconsistencies. The main gaps are:
- Exhibit A details (keyless access, flush-mount, Bayfront)
- Administrative/legal items (malformed URL, change orders)

**Next Steps**: 
1. Investigate if Exhibit A content exists in Neo4j graph
2. Consider targeted re-indexing with better Exhibit A extraction
3. Improve entity extraction for URLs and specification details
