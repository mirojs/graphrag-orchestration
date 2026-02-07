# Route 4 gpt-4.1 Synthesis Quality Analysis — Feb 7, 2026

## Executive Summary

**Test:** "3 Deep Questions" invoice consistency query — 16 ground truth items  
**Group:** test-5pdfs-v2-fix2 (freshly reindexed Feb 7)

| Model | Score | Chars | Latency |
|-------|-------|-------|---------|
| **gpt-5.1** | **12/16 (75.0%)** | 18,483 | 42.4s |
| **gpt-4.1** | **9/16 (56.2%)** | 9,410 | 49.1s |

**gpt-5.1 finds 3 more items than gpt-4.1** (Malformed URL, John Doe, Keyless access) while being faster on this run. gpt-4.1 is 49% shorter but loses ground truth coverage.

---

## Test Question: "3 Deep Questions" Invoice Consistency Query

**Single Comprehensive Query** (Route 4 automatically decomposes into 3 sub-questions):

> *"List all areas of inconsistency identified in the invoice, organized by: (1) all inconsistencies with corresponding evidence, (2) inconsistencies in goods or services sold including detailed specifications for every line item, and (3) inconsistencies regarding billing logistics and administrative or legal issues."*

**Route 4 Automatic Decomposition:**
- **Q1:** All inconsistencies with corresponding evidence
- **Q2:** Inconsistencies in goods/services sold (detailed line item specs)
- **Q3:** Billing logistics and administrative/legal issues

---

## Test Results (Feb 7, 2026 — post-reindex)

**Group:** test-5pdfs-v2-fix2

| Model | Score | Length | Latency | Citations |
|-------|-------|--------|---------|-----------|
| **gpt-5.1** | **12/16 (75.0%)** | 18,483 chars | 42.4s | 6 |
| **gpt-4.1** | **9/16 (56.2%)** | 9,410 chars | 49.1s | 33 |

### Ground Truth Scoring: Item-by-Item

| # | Item | gpt-5.1 | gpt-4.1 |
|---|------|---------|---------|
| 1 | Model mismatch (Savaria vs AscendPro) | ✅ | ✅ |
| 2 | Payment conflict ($29,900 vs installments) | ✅ | ✅ |
| 3 | Customer name (Construction vs Inc) | ✅ | ✅ |
| 4 | Hall call flush-mount omission | ✅ | ✅ |
| 5 | Door height 80" spec | ✅ | ✅ |
| 6 | WR-500 lock added | ✅ | ✅ |
| 7 | Outdoor fitting vs configuration | ✅ | ✅ |
| 8 | Invoice due on signing | ✅ | ✅ |
| 9 | Malformed URL (ww.) | ✅ | ❌ |
| 10 | John Doe signature | ✅ | ❌ |
| 11 | Contoso LLC vs Ltd | ❌ | ❌ |
| 12 | Bayfront/Dayton location | ❌ | ❌ |
| 13 | Keyless access omission | ✅ | ❌ |
| 14 | Change order missing | ❌ | ❌ |
| 15 | Invoice number 1256003 | ❌ | ❌ |
| 16 | Delivery milestone $7,000 | ✅ | ✅ |
| | **TOTAL** | **12/16** | **9/16** |

### Items gpt-5.1 Found That gpt-4.1 Missed

1. **Malformed URL** — ww.contosolifts.com (missing 'w')
2. **John Doe** — generic placeholder name on invoice
3. **Keyless access** — contract specifies keyless, invoice omits it

### Items Neither Model Found

- Contoso LLC vs Ltd entity suffix mismatch
- Bayfront Animal Clinic / Dayton location discrepancy
- Missing change order documentation
- Invoice number 1256003 reference

---

## Potential Concerns & Mitigations

### ❓ gpt-4.1 scores 3 items lower than gpt-5.1
gpt-5.1 finds 12/16 vs gpt-4.1's 9/16. The gap is 3 items (malformed URL, John Doe, keyless access). These are details that gpt-5.1's longer output (18K vs 9K chars) captures but gpt-4.1's conciseness omits.

### ❓ Rate limiting (429 errors during testing)
During Feb 6 testing, gpt-4.1 hit rate limits because both decomposition (Stage 4.1) and synthesis (Stage 4.4) use gpt-4.1 concurrently, exceeding the 300K TPM limit.

**Mitigation Options:**
1. **Create separate gpt-4.1 deployment for synthesis** (isolates quota)
2. Increase gpt-4.1 capacity beyond 300K TPM
3. Switch decomposition to different model (e.g., gpt-4o-mini)

---

## Conclusion

gpt-5.1 scores **12/16 (75%)** vs gpt-4.1's **9/16 (56%)**. gpt-4.1 is shorter (9K vs 18K chars) but misses 3 items that gpt-5.1 catches. Neither model finds 4 of the 16 items.

---

*Test completed 2026-02-07. Data: `bench_gpt51_3deep_20260207.json`, `bench_gpt41_3deep_20260207.json`*
