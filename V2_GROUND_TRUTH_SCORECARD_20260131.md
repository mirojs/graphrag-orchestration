# V1 vs V2: 16 Ground-Truth Inconsistencies Scorecard
**Date:** 2026-01-31
**Test Files:** v1_test_20260131_081143.json, v2_test_20260131_075939.json
**Ground Truth Source:** GROUND_TRUTH_EXPANDED_16_ITEMS.md (expanded from original 11)

---

## Executive Summary

| Metric | V1 (OpenAI) | V2 (Voyage) | Winner |
|--------|-------------|-------------|--------|
| **Ground Truth Score** | 14/16 (87.5%) | **15/16 (93.8%)** | **V2** |
| **Total Citations** | 46 | 42 | V1 |
| **Unique Chunks** | 5 | **8** | **V2** |
| **Unique Documents** | 2 | **5** | **V2** |
| **Invoice Citations** | 1 | **6** | **V2** (6x better) |
| **Citation Diversity** | 10.9% | **19.0%** | **V2** |
| **Response Length** | 19,354 chars | 22,820 chars | V2 |

### ⚠️ Critical Note: Unicode Normalization

Initial analysis showed V1 outperforming V2 due to **Unicode hyphen encoding differences**:
- V1 uses ASCII hyphen: `-` (U+002D)
- V2 uses non-breaking hyphen: `‑` (U+2011)

All scores below are **Unicode-normalized**.

---

## 16 Ground-Truth Inconsistencies Scorecard

### Category A - MAJOR Inconsistencies (3 items)

| # | ID | Inconsistency | V1 | V2 | Notes |
|---|----|--------------|----|----|----|
| 1 | A1 | **Lift model mismatch** (Savaria V1504 vs AscendPro VPX200) | ✅ | ✅ | Both explicitly identify this as primary conflict |
| 2 | A2 | **Payment structure conflict** (Full $29,900 at signing vs $20k/$7k/$2.9k staged) | ✅ | ✅ | Both detail the 3-stage vs lump-sum discrepancy |
| 3 | A3 | **Customer entity mismatch** (Fabrikam Construction vs Fabrikam Inc.) | ✅ | ✅ | Both note contract vs invoice party names differ |

**Category A Score: V1 3/3, V2 3/3** ✓ Parity

---

### Category B - MEDIUM Inconsistencies (5 items)

| # | ID | Inconsistency | V1 | V2 | Notes |
|---|----|--------------|----|----|----|
| 4 | B1 | **Hall call spec gap** (Invoice omits "flush-mount" qualifier) | ✅ | ✅ | Both identify invoice doesn't specify flush-mount |
| 5 | B2 | **Door height added** (Invoice specifies 80" not in contract) | ✅ | ✅ | Both note 80" High specification |
| 6 | B3 | **WR-500 lock added** (Invoice adds lock model not in contract) | ✅ | ✅ | Both mention WR-500 (V2 uses `WR‑500` Unicode) |
| 7 | B4 | **Outdoor terminology** ("Outdoor fitting" vs "Outdoor configuration package") | ✅ | ✅ | Both note terminology difference |
| 8 | B5 | **Invoice self-contradiction** ("Initial payment" but demands full $29,900) | ✅ | ✅ | Both identify internal inconsistency in invoice |

**Category B Score: V1 5/5, V2 5/5** ✓ Parity

---

### Category C - MINOR Inconsistencies (8 items)

| # | ID | Inconsistency | V1 | V2 | Notes |
|---|----|--------------|----|----|----|
| 9 | C1 | **URL malformed** (ww.contosolifts.com instead of www) | ✅ | ✅ | Both identify URL typo |
| 10 | C2 | **John Doe contact** (Individual name not in contract) | ✅ | ✅ | Both note John Doe appears only on invoice |
| 11 | C3 | **Contoso Ltd vs LLC** (Exhibit A: Contoso Ltd vs Contract: Contoso Lifts LLC) | ✅ | ✅ | Both identify different contractor entity names |
| 12 | C4 | **Bayfront site mismatch** (Exhibit A: Bayfront Animal Clinic vs 61 S 34th St) | ✅ | ✅ | Both note different job sites |
| 13 | C5 | **Keyless access** (Exhibit A mentions, invoice silent) | ✅ | ✅ | Both identify keyless access gap |
| 14 | C6 | **No change order** (Contract requires written changes; none shown) | ✅ | ✅ | Both note substitution without change order |
| 15 | C7 | **Invoice number 45239** (Not referenced in contract) | ❌ | ❌ | Neither mentions invoice # as inconsistency |
| 16 | C8 | **Delivery timeline** (Invoice lacks "8-10 weeks" delivery reference) | ❌ | ✅ | **V2 only** - mentions 8–10 weeks delivery timeline |

**Category C Score: V1 6/8, V2 7/8** - V2 wins by 1

---

## Score Summary

| Category | Max | V1 Score | V2 Score | Winner |
|----------|-----|----------|----------|--------|
| **A - MAJOR** | 3 | 3 (100%) | 3 (100%) | Tie |
| **B - MEDIUM** | 5 | 5 (100%) | 5 (100%) | Tie |
| **C - MINOR** | 8 | 6 (75%) | 7 (87.5%) | **V2** |
| **TOTAL** | 16 | **14 (87.5%)** | **15 (93.8%)** | **V2** |

### Weighted Score (MAJOR=3, MEDIUM=2, MINOR=1)

- Max possible: 3×3 + 5×2 + 8×1 = **27 points**
- V1: 3×3 + 5×2 + 6×1 = 9 + 10 + 6 = **25/27 (92.6%)**
- V2: 3×3 + 5×2 + 7×1 = 9 + 10 + 7 = **26/27 (96.3%)** ✓ Winner

---

## Citation Quality Analysis

| Metric | V1 (OpenAI) | V2 (Voyage) | Analysis |
|--------|-------------|-------------|----------|
| **Total Citations** | 46 | 42 | V1 higher raw count |
| **Unique Chunks** | 5 | 8 | V2 retrieves 60% more unique content |
| **Unique Documents** | 2 | 5 | V2 covers 2.5x more documents |
| **Invoice Citations** | 1 | 6 | V2 cites invoice 6x more (critical for comparison) |
| **Citation Diversity** | 10.9% | 19.0% | V2 has 1.75x better diversity |

### Document Distribution

**V1:**
- purchase_contract: 45/46 (97.8%)
- contoso_lifts_invoice: 1/46 (2.2%)
- **Total unique docs: 2**

**V2:**
- purchase_contract: 33/42 (78.6%)
- contoso_lifts_invoice: 6/42 (14.3%)
- Builder's Limited Warranty: 1/42 (2.4%)
- Holding Tank Servicing Contract: 1/42 (2.4%)
- Property Management Agreement: 1/42 (2.4%)
- **Total unique docs: 5**

### Interpretation

V1's 46 citations appear higher but are **inflated by redundancy**:
- 45 citations from the same purchase_contract document
- Only 1 invoice citation (the key document for inconsistency detection!)

V2's 42 citations show **higher quality**:
- 8 unique chunks vs V1's 5
- 6 invoice citations vs V1's 1 (6x better)
- Broader document coverage including related contracts

---

## Test Configuration

### V1 Group: `test-5pdfs-1769071711867955961`
- **Embedding Model:** OpenAI text-embedding-3-large
- **Dimensions:** 3072
- **Vector DB:** Azure AI Search

### V2 Group: `test-5pdfs-v2-enhanced-ex`
- **Embedding Model:** Voyage voyage-context-3
- **Dimensions:** 2048
- **Vector DB:** Azure AI Search

### Query Used
```
Analyze all inconsistencies, conflicts, and discrepancies between the invoice 
details and the contract/exhibit terms. Include model numbers, specifications, 
payment terms, dates, customer information, and any URLs or references.
```

### Route
Both tested with `force_route="drift_multi_hop"` (Route 4 DRIFT)

---

## Key Findings

### V2 Advantages
1. **Higher ground truth score:** 93.8% vs 87.5%
2. **Better citation diversity:** 8 unique chunks vs 5
3. **More document coverage:** 5 unique docs vs 2
4. **Better invoice coverage:** 6x more invoice citations
5. **Catches delivery timeline (C8)** that V1 misses

### V1 Characteristics
1. **Higher raw citation count:** 46 vs 42
2. **More concise response:** 19,354 chars vs 22,820 chars
3. **Same MAJOR/MEDIUM coverage:** 100% parity on 8 critical items

### Items Neither Found
- **C7: Invoice number 45239** - trivial, not a meaningful inconsistency

---

## Conclusion

**V2 (Voyage) outperforms V1 (OpenAI)** on this invoice/contract inconsistency detection task:

| Dimension | Winner | Margin |
|-----------|--------|--------|
| Ground Truth Score | **V2** | +6.3% (93.8% vs 87.5%) |
| Citation Quality | **V2** | 6x better invoice coverage |
| Document Diversity | **V2** | 2.5x more unique docs |
| Chunk Diversity | **V2** | 1.6x more unique chunks |

The hypothesis that "V2 should excel at citation richness" is **SUPPORTED** when measuring quality over quantity. V2's lower raw citation count masks higher-quality retrieval with better diversity and document coverage.

---

## Change from Original 11-Item Scorecard

This expanded 16-item scorecard adds 5 new items from detailed analysis:

| New Items | Description | Source |
|-----------|-------------|--------|
| B1 | Hall call flush-mount gap | Specification analysis |
| B3 | WR-500 lock addition | Invoice detail review |
| C3 | Contoso Ltd vs LLC | Exhibit A vs Contract |
| C4 | Bayfront site mismatch | Exhibit A vs Invoice |
| C7 | Invoice number reference | Metadata comparison |
| C8 | Delivery timeline | Contract terms |

Original 11 items → Expanded to 16 items with finer granularity.
