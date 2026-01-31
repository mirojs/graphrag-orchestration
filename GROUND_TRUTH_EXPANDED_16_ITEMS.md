# Expanded Ground Truth: 16 Inconsistency Items

**Created:** 2026-01-31
**Updated:** 2026-01-31 (Corrected for Unicode normalization)
**Purpose:** Comprehensive evaluation benchmark for V1 vs V2 comparison

## Summary

| Metric | V1 (OpenAI) | V2 (Voyage) |
|--------|-------------|-------------|
| **Items Found** | 14/16 (87.5%) | **15/16 (93.8%)** |
| Citations | 46 | 42 |
| Response Length | 19,354 chars | 22,820 chars |
| Missed Items | C7, C8 | C7 |

## ⚠️ Unicode Normalization Note

Initial analysis showed V1 outperforming V2, but this was due to **Unicode hyphen differences**:
- V1 uses ASCII hyphen: `-` (U+002D)  
- V2 uses non-breaking hyphen: `‑` (U+2011)

When normalized, V2 actually finds **one more item** than V1.

## Category A - MAJOR Inconsistencies (3 items)

| ID | Description | Invoice | Contract/Exhibit | V1 | V2 |
|----|-------------|---------|------------------|----|----|
| A1 | Lift model mismatch | Savaria V1504 | AscendPro VPX200 | ✓ | ✓ |
| A2 | Payment structure conflict | Full $29,900 at signing | 3-stage ($20k/$7k/$2.9k) | ✓ | ✓ |
| A3 | Customer entity mismatch | Fabrikam Construction | Fabrikam Inc. | ✓ | ✓ |

## Category B - MEDIUM Inconsistencies (5 items)

| ID | Description | Invoice | Contract/Exhibit | V1 | V2 |
|----|-------------|---------|------------------|----|----|
| B1 | Hall call spec gap | "Hall Call stations" | "Flush-mount Hall Call stations" | ✓ | ✓ |
| B2 | Door height added | "80" High" specified | Height not specified | ✓ | ✓ |
| B3 | WR-500 lock added | "WR-500 lock" specified | Lock model not specified | ✓ | ✓ |
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
| C8 | Delivery timeline | No dates specified | "8-10 weeks after drawing approval" | ✗ | **✓** |

## Key Findings

### V2 Advantages (Voyage voyage-context-3, 2048d):
1. **Finds more items**: 15/16 vs 14/16
2. **Catches delivery timeline**: Mentions "8-10 weeks" that V1 misses
3. **Longer, more comprehensive response**: 22,820 chars

### V1 Characteristics (OpenAI text-embedding-3-large, 3072d):
1. **More citations**: 46 vs 42
2. **More concise response**: 19,354 chars
3. **Same on MAJOR/MEDIUM items**: 100% parity

### Neither Found:
- C7: Invoice number #45239 (trivial - invoice-specific identifier)

## Scoring Methodology

### Expanded Scoring (16 items):
- V1: 14/16 = 87.5%
- **V2: 15/16 = 93.8%** ✓ Winner

### Weighted Scoring (MAJOR=3, MEDIUM=2, MINOR=1):
- Max possible: 3×3 + 5×2 + 8×1 = 27 points
- V1: 3×3 + 5×2 + 6×1 = 25/27 = 92.6%
- **V2: 3×3 + 5×2 + 7×1 = 26/27 = 96.3%** ✓ Winner

## Interpretation

After correcting for Unicode encoding differences, **V2 (Voyage) slightly outperforms V1 (OpenAI)** on this document analysis task:

1. **V2 finds the delivery timeline item** that V1 misses
2. **V1 has more citations** (46 vs 42) but this doesn't translate to better coverage
3. Both are **equivalent on MAJOR and MEDIUM items** (8/8 each)

The hypothesis that "V2 should excel" is **SUPPORTED** - V2 achieves 93.8% vs V1's 87.5%.

## Technical Note: Unicode Handling

When comparing LLM outputs, always normalize Unicode characters:
\`\`\`python
def normalize_text(text):
    return text.replace('‑', '-').replace('–', '-').replace('—', '-')
\`\`\`

Different embedding models may produce different Unicode representations that affect keyword-based scoring.
