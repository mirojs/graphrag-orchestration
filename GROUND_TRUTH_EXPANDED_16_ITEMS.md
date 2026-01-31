# Expanded Ground Truth: 16 Inconsistency Items

**Created:** 2026-01-31
**Purpose:** Comprehensive evaluation benchmark for V1 vs V2 comparison

## Summary

| Metric | V1 (OpenAI) | V2 (Voyage) |
|--------|-------------|-------------|
| Items Found | 14/16 (88%) | 12/16 (75%) |
| Citations | 46 | 42 |
| Response Length | 19,354 chars | 22,820 chars |
| V1 Only | B1, B3 | - |
| V2 Only | - | - |
| Missed (Both) | C7, C8 | C7, C8 |

## Category A - MAJOR Inconsistencies (3 items)

| ID | Description | Invoice | Contract/Exhibit | V1 | V2 |
|----|-------------|---------|------------------|----|----|
| A1 | Lift model mismatch | Savaria V1504 | AscendPro VPX200 | ✓ | ✓ |
| A2 | Payment structure conflict | Full $29,900 at signing | 3-stage ($20k/$7k/$2.9k) | ✓ | ✓ |
| A3 | Customer entity mismatch | Fabrikam Construction | Fabrikam Inc. | ✓ | ✓ |

## Category B - MEDIUM Inconsistencies (5 items)

| ID | Description | Invoice | Contract/Exhibit | V1 | V2 |
|----|-------------|---------|------------------|----|----|
| B1 | Hall call spec gap | "Hall Call stations" | "Flush-mount Hall Call stations" | ✓ | ✗ |
| B2 | Door height added | "80\" High" specified | Height not specified | ✓ | ✓ |
| B3 | WR-500 lock added | "WR-500 lock" specified | Lock model not specified | ✓ | ✗ |
| B4 | Outdoor terminology | "Outdoor fitting" | "Outdoor configuration package" | ✓ | ✓ |
| B5 | Invoice self-contradiction | "Initial payment" but demands full $29,900 | - | ✓ | ✓ |

## Category C - MINOR Inconsistencies (8 items)

| ID | Description | Invoice | Contract/Exhibit | V1 | V2 |
|----|-------------|---------|------------------|----|----|
| C1 | URL malformed | ww.contosolifts.com | No URL mentioned | ✓ | ✓ |
| C2 | John Doe contact | John Doe listed | Name not in contract | ✓ | ✓ |
| C3 | Contoso Ltd vs LLC | - | Exhibit A: Contoso Ltd., Contract: Contoso Lifts LLC | ✓ | ✓ |
| C4 | Bayfront site mismatch | 61 S 34th Street | Exhibit A: Bayfront Animal Clinic | ✓ | ✓ |
| C5 | Keyless access | Not mentioned | Exhibit A mentions keyless | ✓ | ✓ |
| C6 | No change order | Substituted product | Contract requires written changes | ✓ | ✓ |
| C7 | Invoice number | #45239 | Not in contract | ✗ | ✗ |
| C8 | Delivery timeline | No dates specified | "8-10 weeks after drawing approval" | ✗ | ✗ |

## Key Findings

### V1 Advantages (OpenAI text-embedding-3-large, 3072d):
1. **Finds more specification gaps**: B1 (flush-mount) and B3 (WR-500 lock)
2. **More citations**: 46 vs 42
3. **Better at detail-level inconsistencies**

### V2 Characteristics (Voyage voyage-context-3, 2048d):
1. **Longer response**: 22,820 vs 19,354 characters
2. **Finds all MAJOR items**: 3/3 (100%)
3. **Misses 2 MEDIUM specification gaps**

### Neither Found:
- C7: Invoice number #45239 (trivial - invoice-specific identifier)
- C8: Delivery timeline comparison (8-10 weeks vs no dates)

## Scoring Methodology

### Original Scoring (11 items) - Both 100%:
Used the 11 core items from Categories A (3) + B-simplified (5) + C-simplified (3)

### Expanded Scoring (16 items):
- V1: 14/16 = 87.5%
- V2: 12/16 = 75.0%

### Weighted Scoring (MAJOR=3, MEDIUM=2, MINOR=1):
- Max possible: 3×3 + 5×2 + 8×1 = 27 points
- V1: 3×3 + 4×2 + 6×1 = 23/27 = **85.2%**
- V2: 3×3 + 2×2 + 6×1 = 19/27 = **70.4%**

## Interpretation

V1 (OpenAI) outperforms V2 (Voyage) on this specific document analysis task because:

1. **Higher citation count** (46 vs 42) indicates better retrieval coverage
2. **Better specification-level detail** (catches flush-mount and WR-500 gaps)
3. **Same performance on MAJOR items** but edge on MEDIUM items

The hypothesis that "V2 should excel at citation richness" is **NOT supported** by this test.
