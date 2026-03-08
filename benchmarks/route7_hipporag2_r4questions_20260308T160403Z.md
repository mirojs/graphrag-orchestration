# Route 7 (HippoRAG 2) Benchmark

**Timestamp:** 20260308T160403Z

**API Base URL:** `http://localhost:8000`

**Group ID:** `test-5pdfs-v2-fix2`

**Force Route:** `hipporag2_search`

**Architecture:** True HippoRAG 2 with passage-node PPR, query-to-triple linking, and recognition memory filtering.

---

## Scenario: route7_hipporag2_r4questions_summary

**Response Type:** `summary`

### Summary Table

| QID | Containment | F1 | Neg Pass | Exact Rate | Min Sim | P50 ms | P95 ms |
|-----|-------------|-----|----------|------------|---------|--------|--------|
| Q-D1 | 0.94 | 0.47 | - | 0.33 | 0.99 | 3900 | 16736 |
| Q-D2 | 1.00 | 0.24 | - | 0.67 | 0.61 | 3427 | 3549 |
| Q-D3 | 0.56 | 0.44 | - | 0.33 | 0.87 | 6558 | 6604 |
| Q-D4 | 1.00 | 0.54 | - | 1.00 | 1.00 | 4299 | 34849 |
| Q-D5 | 0.74 | 0.40 | - | 0.67 | 0.88 | 4581 | 4800 |
| Q-D6 | 0.40 | 0.31 | - | 1.00 | 1.00 | 4196 | 34524 |
| Q-D7 | 0.30 | 0.38 | - | 1.00 | 1.00 | 3360 | 3517 |
| Q-D8 | 0.45 | 0.45 | - | 0.33 | 0.36 | 4858 | 35101 |
| Q-D9 | 0.88 | 0.57 | - | 1.00 | 1.00 | 3870 | 4582 |
| Q-D10 | 0.84 | 0.50 | - | 0.33 | 0.51 | 5021 | 35025 |
| Q-N1 | - | - | PASS | 1.00 | 1.00 | 3094 | 3170 |
| Q-N2 | - | - | PASS | 1.00 | 1.00 | 2934 | 33796 |
| Q-N3 | - | - | PASS | 1.00 | 1.00 | 3145 | 3173 |
| Q-N5 | - | - | PASS | 1.00 | 1.00 | 2882 | 33764 |
| Q-N6 | - | - | PASS | 1.00 | 1.00 | 3055 | 34055 |
| Q-N7 | - | - | PASS | 1.00 | 1.00 | 2975 | 3168 |
| Q-N8 | - | - | PASS | 1.00 | 1.00 | 2832 | 33766 |
| Q-N9 | - | - | PASS | 1.00 | 1.00 | 3016 | 3096 |
| Q-N10 | - | - | PASS | 1.00 | 1.00 | 2967 | 33590 |

**Positive questions avg containment:** 0.71  
**Positive questions avg F1:** 0.43  

**Negative tests passed:** 9/9  

### Per-Question Detail

#### Q-D1: If an emergency defect occurs under the warranty (e.g., burst pipe), what is the required notification channel and consequence of delay?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.05 |
| Containment | 0.94 |
| Precision | 0.31 |
| Recall | 0.94 |
| F1 Score | 0.47 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.99 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3900 |
| Latency P95 (ms) | 16736 |

**Run 1 (16736ms):**

```
- The Buyer/Owner must telephone the Builder immediately if an emergency exists or if a delay will cause extra damage (e.g., burst pipe). Only emergency reports will be taken by phone [1].
- Failure to promptly notify the Builder of an emergency under this limited warranty relieves the Builder of all liability for replacement, repair, and all other damages [2].
```

**Run 2 (3900ms):**

```
- The Buyer/Owner must telephone the Builder immediately if an emergency exists or if a delay will cause extra damage (e.g., burst pipe). Only emergency reports will be taken by phone. [1]
- Failure to promptly notify the Builder of an emergency under this limited warranty relieves the Builder of all liability for replacement, repair, and all other damages. [2]
```

#### Q-D2: In the property management agreement, what happens to confirmed reservations if the agreement is terminated or the property is sold?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.21 |
| Containment | 1.00 |
| Precision | 0.14 |
| Recall | 1.00 |
| F1 Score | 0.24 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.67 |
| Min Similarity | 0.61 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3427 |
| Latency P95 (ms) | 3549 |

**Run 1 (3549ms):**

```
- In the event this agreement is terminated, or the property is sold, the Owner shall honor all confirmed reservations. [1]
- Termination of this agreement does not invalidate any existing rental agreements made by Agent on Owner's behalf. [3]
- Upon termination, Owner shall continue to be responsible or shall cause to be completed all obligations or expenses incurred hereunder by the Agent. [3]
```

**Run 2 (3362ms):**

```
- In the event this agreement is terminated, or the property is sold, the Owner shall honor all confirmed reservations. [1]
- Termination of this agreement does not invalidate any existing rental agreements made by Agent on Owner's behalf. [3]
- Upon termination, Owner shall continue to be responsible or shall cause to be completed all obligations or expenses incurred hereunder by the Agent. [3]
```

#### Q-D3: Compare "time windows" across the set: list all explicit day-based timeframes.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.08 |
| Containment | 0.56 |
| Precision | 0.37 |
| Recall | 0.56 |
| F1 Score | 0.44 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.87 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 6558 |
| Latency P95 (ms) | 6604 |

**Run 1 (6558ms):**

```
- Initial period of twelve months (365 days) for the property management agreement [6]
- Either party may terminate the property management agreement upon sixty (60) days written notice [6]
- Provide Agent with written notification within five (5) business days of a listing agreement if the property is for sale [8]
- Long term leases defined as leases of more than 180 days [16]
- Builder warrants certain items free of defects for a period of sixty (60) days [2]
- Builder will repair or replace a...
```

**Run 2 (6255ms):**

```
- Sixty (60) days written notice required to terminate the property management agreement [6]
- Provide Agent with written notification within five (5) business days of a listing agreement if the property is for sale [8]
- Long term leases defined as leases of more than 180 days [16]
- Builder warrants certain items free of defects for a period of sixty (60) days [2]
- Builder will repair or replace covered defects within sixty (60) days (longer if delays) [9]
- Arbitration to be concluded within...
```

#### Q-D4: Which documents mention **insurance** and what limits are specified?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.33 |
| Containment | 1.00 |
| Precision | 0.37 |
| Recall | 1.00 |
| F1 Score | 0.54 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 4299 |
| Latency P95 (ms) | 34849 |

**Run 1 (4299ms):**

```
- PROPERTY MANAGEMENT AGREEMENT: Requires liability insurance coverage for the property with minimum limits of $300,000 for bodily injury and $25,000 for property damage to others. The Agent must be named as additional insured and provided with a copy of the insurance policy and certificate of insurance [1(f)].
- PROPERTY MANAGEMENT AGREEMENT: Rents must be deposited in a special trust account in an insured financial institution authorized to do business in the State of Hawaii [5(c)].
```

**Run 2 (4202ms):**

```
- PROPERTY MANAGEMENT AGREEMENT: Requires liability insurance coverage for the property with minimum limits of $300,000 for bodily injury and $25,000 for property damage to others. The Agent must be named as additional insured and provided with a copy of the insurance policy and certificate of insurance [1(f)].
- PROPERTY MANAGEMENT AGREEMENT: Rents must be deposited in a special trust account in an insured financial institution authorized to do business in the State of Hawaii [5(c)].
```

#### Q-D5: In the warranty, explain how the "coverage start" is defined and what must happen before coverage ends.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.11 |
| Containment | 0.74 |
| Precision | 0.28 |
| Recall | 0.74 |
| F1 Score | 0.40 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.67 |
| Min Similarity | 0.88 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 4581 |
| Latency P95 (ms) | 4800 |

**Run 1 (4581ms):**

```
- The coverage start is defined as the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first [1].
- Before coverage ends, the Buyer/Owner must write a letter describing the defect to the Builder and send it by certified mail return receipt requested to the Builder at the Builder's office address, and this must be done prior to the termination of the one (1) year or sixty (60) day warranty period as applicable [2].
- The warranty coverage ends on...
```

**Run 2 (4800ms):**

```
- The coverage start is defined as the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first [1].
- Before coverage ends, the Buyer/Owner must write a letter describing the defect to the Builder and send it by certified mail return receipt requested to the Builder at the Builder's office address, and this must be done prior to the termination of the one (1) year or sixty (60) day warranty period as applicable [2].
- The warranty coverage ends on...
```

#### Q-D6: Do the purchase contract total price and the invoice total match? If so, what is that amount?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.23 |
| Containment | 0.40 |
| Precision | 0.25 |
| Recall | 0.40 |
| F1 Score | 0.31 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 2 |
| Latency P50 (ms) | 4196 |
| Latency P95 (ms) | 34524 |

**Run 1 (3683ms):**

```
- The purchase contract total price is $29,900.00 [2].
- The invoice total is $29,900.00 [1], [3].
- The purchase contract total price and the invoice total match at $29,900.00 [1], [2], [3].
```

**Run 2 (4196ms):**

```
- The purchase contract total price is $29,900.00 [2].
- The invoice total is $29,900.00 [1], [3].
- The purchase contract total price and the invoice total match at $29,900.00 [1], [2], [3].
```

#### Q-D7: Which document has the latest explicit date, and what is it?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.31 |
| Containment | 0.30 |
| Precision | 0.50 |
| Recall | 0.30 |
| F1 Score | 0.38 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3360 |
| Latency P95 (ms) | 3517 |

**Run 1 (3309ms):**

```
- The document with the latest explicit date is the "purchase contract" with the date 04/30/2025 [2], [4].
```

**Run 2 (3517ms):**

```
- The document with the latest explicit date is the "purchase contract" with the date 04/30/2025 [2], [4].
```

#### Q-D8: Across the set, which entity appears in the most different documents: `Fabrikam Inc.` or `Contoso Ltd.`?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.11 |
| Containment | 0.45 |
| Precision | 0.44 |
| Recall | 0.45 |
| F1 Score | 0.45 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.36 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 2 |
| Latency P50 (ms) | 4858 |
| Latency P95 (ms) | 35101 |

**Run 1 (4182ms):**

```
- Contoso Ltd. appears in the following documents:
  - HOLDING TANK SERVICING CONTRACT [1], [7]
  - purchase contract [2], [3]
  - BUILDERS LIMITED WARRANTY [4], [6]
  - PROPERTY MANAGEMENT AGREEMENT [5], [8], [10]
- Fabrikam Inc. appears in the following documents:
  - HOLDING TANK SERVICING CONTRACT [1], [7]
  - purchase contract [2], [3], [9]
  - BUILDERS LIMITED WARRANTY [4], [6], [11]
  - PROPERTY MANAGEMENT AGREEMENT [5], [8]
- Both Contoso Ltd. and Fabrikam Inc. appear in four unique docu...
```

**Run 2 (4858ms):**

```
- Fabrikam Inc. appears in the following unique documents:
  - HOLDING TANK SERVICING CONTRACT [1], [7]
  - purchase contract [2], [3], [9], [16]
  - BUILDERS LIMITED WARRANTY [4], [6], [11]
  - PROPERTY MANAGEMENT AGREEMENT [5], [8]
- Contoso Ltd. appears in the following unique documents:
  - HOLDING TANK SERVICING CONTRACT [1], [7]
  - purchase contract [2], [3]
  - BUILDERS LIMITED WARRANTY [4], [6]
  - PROPERTY MANAGEMENT AGREEMENT [5], [8], [10]
- Both Fabrikam Inc. and Contoso Ltd. appear...
```

#### Q-D9: Compare the "fees" concepts: which doc has a percentage-based fee structure and which has fixed installment payments?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.35 |
| Containment | 0.88 |
| Precision | 0.42 |
| Recall | 0.88 |
| F1 Score | 0.57 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3870 |
| Latency P95 (ms) | 4582 |

**Run 1 (3870ms):**

```
- The "PROPERTY MANAGEMENT AGREEMENT" document has a percentage-based fee structure, including a 10% commission of gross revenues for long-term leases, a 25% commission of gross revenues for short-term/vacation rentals, and a 10% fee on the total charge for repairs, upgrades, and/or renovations [1][3][4].
- The "purchase contract" document has fixed installment payments: $20,000.00 upon signing, $7,000.00 upon delivery, and $2,900.00 upon completion [2].
```

**Run 2 (4582ms):**

```
- The "PROPERTY MANAGEMENT AGREEMENT" document has a percentage-based fee structure, including a 10% commission of gross revenues for long-term leases, a 25% commission of gross revenues for short-term/vacation rentals, and a 10% fee on the total charge for repairs, upgrades, and/or renovations [1][3][4].
- The "purchase contract" document has fixed installment payments: $20,000.00 upon signing, $7,000.00 upon delivery, and $2,900.00 upon completion [2].
```

#### Q-D10: List the three different "risk allocation" statements across the set (risk of loss, liability limitations, non-transferability).

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.08 |
| Containment | 0.84 |
| Precision | 0.36 |
| Recall | 0.84 |
| F1 Score | 0.50 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.51 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 5021 |
| Latency P95 (ms) | 35025 |

**Run 1 (5021ms):**

```
- Risk of loss: Contractor holds risk until delivery. Customer holds risk thereafter. [purchase contract, 3]
- Liability limitations: The Owner agrees that Agent shall not be liable for any claim for loss or injury to any person or property located on the property subject to this agreement, except for loss or injury caused by Agent's gross negligence or wilful misconduct, and Owner shall hold Agent harmless and indemnify Agent for any such claim or liability. [PROPERTY MANAGEMENT AGREEMENT, 2]
-...
```

**Run 2 (35025ms):**

```
- Contractor holds risk until delivery. Customer holds risk thereafter. [3]
- The Owner agrees that Agent shall not be liable for any claim for loss or injury to any person or property located on the property subject to this agreement, except for loss or injury caused by Agent's gross negligence or wilful misconduct, and Owner shall hold Agent harmless and indemnify Agent for any such claim or liability. [1]
- This limited warranty is extended to the Buyer/Owner as the first purchaser of the hom...
```

#### Q-N1: What is the invoice's **bank routing number** for payment?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 2 |
| Latency P50 (ms) | 3094 |
| Latency P95 (ms) | 3170 |

**Run 1 (3094ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3170ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N2: What is the invoice’s **IBAN / SWIFT (BIC)** for international payments?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 2934 |
| Latency P95 (ms) | 33796 |

**Run 1 (2874ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (33796ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N3: What is the vendor's **VAT / Tax ID number** on the invoice?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 2 |
| Latency P50 (ms) | 3145 |
| Latency P95 (ms) | 3173 |

**Run 1 (3084ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3173ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N5: What is the invoice’s **bank account number** for ACH/wire payments?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 2882 |
| Latency P95 (ms) | 33764 |

**Run 1 (33764ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2882ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N6: Which documents are governed by the laws of **California**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3055 |
| Latency P95 (ms) | 34055 |

**Run 1 (2996ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3055ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N7: What is the property management Agent's **license number**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 2975 |
| Latency P95 (ms) | 3168 |

**Run 1 (2975ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2796ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N8: What is the purchase contract’s required **wire transfer / ACH instructions**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 2 |
| Latency P50 (ms) | 2832 |
| Latency P95 (ms) | 33766 |

**Run 1 (2825ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2832ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N9: What is the exact clause about **mold damage** coverage in the warranty?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3016 |
| Latency P95 (ms) | 3096 |

**Run 1 (3096ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3016ms):**

```
- The requested information was not found in the available documents.
```

#### Q-N10: What is the invoice **shipping method** (value in "SHIPPED VIA")?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 2967 |
| Latency P95 (ms) | 33590 |

**Run 1 (33590ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2967ms):**

```
- The requested information was not found in the available documents.
```

---

