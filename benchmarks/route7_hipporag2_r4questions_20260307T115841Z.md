# Route 7 (HippoRAG 2) Benchmark

**Timestamp:** 20260307T115841Z

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
| Q-D1 | 0.94 | 0.51 | - | 0.33 | 0.02 | 5280 | 14811 |
| Q-D2 | 1.00 | 0.24 | - | 0.67 | 0.61 | 3862 | 4357 |
| Q-D3 | 0.16 | 0.24 | - | 0.33 | 0.77 | 4897 | 5547 |
| Q-D4 | 0.95 | 0.47 | - | 1.00 | 1.00 | 4234 | 4776 |
| Q-D5 | 0.85 | 0.44 | - | 0.33 | 0.56 | 4538 | 5462 |
| Q-D6 | 0.40 | 0.32 | - | 1.00 | 1.00 | 3999 | 33756 |
| Q-D7 | 0.30 | 0.33 | - | 1.00 | 1.00 | 3557 | 3910 |
| Q-D8 | 0.41 | 0.46 | - | 0.33 | 0.77 | 7393 | 36126 |
| Q-D9 | 0.84 | 0.59 | - | 0.33 | 0.75 | 4130 | 4211 |
| Q-D10 | 0.45 | 0.29 | - | 0.33 | 0.08 | 3977 | 33643 |
| Q-N1 | - | - | PASS | 1.00 | 1.00 | 3334 | 3627 |
| Q-N2 | - | - | PASS | 1.00 | 1.00 | 2825 | 2837 |
| Q-N3 | - | - | PASS | 1.00 | 1.00 | 3481 | 34379 |
| Q-N5 | - | - | PASS | 1.00 | 1.00 | 3069 | 3260 |
| Q-N6 | - | - | PASS | 0.67 | 0.99 | 2933 | 33161 |
| Q-N7 | - | - | PASS | 1.00 | 1.00 | 3149 | 8187 |
| Q-N8 | - | - | PASS | 1.00 | 1.00 | 3128 | 33365 |
| Q-N9 | - | - | PASS | 1.00 | 1.00 | 2934 | 2942 |
| Q-N10 | - | - | PASS | 1.00 | 1.00 | 2876 | 33124 |

**Positive questions avg containment:** 0.63  
**Positive questions avg F1:** 0.39  

**Negative tests passed:** 9/9  

### Per-Question Detail

#### Q-D1: If an emergency defect occurs under the warranty (e.g., burst pipe), what is the required notification channel and consequence of delay?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.01 |
| Containment | 0.94 |
| Precision | 0.35 |
| Recall | 0.94 |
| F1 Score | 0.51 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.02 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 5280 |
| Latency P95 (ms) | 14811 |

**Run 1 (14811ms):**

```
- In the event of an emergency defect under the warranty (e.g., burst pipe), the Buyer/Owner must telephone the Builder immediately. Only emergency reports will be taken by phone. [1], [2]
- Failure to promptly notify the Builder of an emergency under this limited warranty relieves the Builder of all liability for replacement, repair, and all other damages. [2]
```

**Run 2 (5280ms):**

```
- The required notification channel for an emergency defect (e.g., burst pipe) under the warranty is immediate telephone notification to the Builder. Only emergency reports will be taken by phone. [1], [2]
- Failure to promptly notify the Builder of an emergency relieves the Builder of all liability for replacement, repair, and all other damages. [2]
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
| Latency P50 (ms) | 3862 |
| Latency P95 (ms) | 4357 |

**Run 1 (3841ms):**

```
- In the event this agreement is terminated, or the property is sold, the Owner shall honor all confirmed reservations [1].
- Termination of this agreement does not invalidate any existing rental agreements made by Agent on Owner's behalf. Upon termination, Owner shall continue to be responsible or shall cause to be completed all obligations or expenses incurred hereunder by the Agent [2].
```

**Run 2 (3862ms):**

```
- In the event this agreement is terminated, or the property is sold, the Owner shall honor all confirmed reservations [1].
- Termination of this agreement does not invalidate any existing rental agreements made by Agent on Owner's behalf [2].
- Upon termination, Owner shall continue to be responsible or shall cause to be completed all obligations or expenses incurred hereunder by the Agent [2].
```

#### Q-D3: Compare "time windows" across the set: list all explicit day-based timeframes.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.22 |
| Containment | 0.16 |
| Precision | 0.48 |
| Recall | 0.16 |
| F1 Score | 0.24 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.77 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 4897 |
| Latency P95 (ms) | 5547 |

**Run 1 (5547ms):**

```
- sixty (60) days [1], [7], [8], [14], [16]
- one (1) year [2], [8], [14], [16]
- sixty (60) days written notice [9]
- five (5) business days [10]
- 180 days [5], [21]
- ninety (90) days [6]
```

**Run 2 (4897ms):**

```
- sixty (60) days [1], [7], [8], [14], [16]
- one (1) year [2], [8], [14], [16]
- five (5) business days [10]
- sixty (60) days written notice [9]
- 90 days [6]
- 180 days [5], [21]
```

#### Q-D4: Which documents mention **insurance** and what limits are specified?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.10 |
| Containment | 0.95 |
| Precision | 0.32 |
| Recall | 0.95 |
| F1 Score | 0.47 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 4234 |
| Latency P95 (ms) | 4776 |

**Run 1 (4068ms):**

```
- The PROPERTY MANAGEMENT AGREEMENT mentions insurance and specifies the following limits: minimum limits of $300,000 for bodily injury and $25,000 for property damage to others [2].
- The PROPERTY MANAGEMENT AGREEMENT requires the Agent to be named as additional insured and to be furnished with a copy of the insurance policy and a certificate of insurance [1].
- The PROPERTY MANAGEMENT AGREEMENT requires rents to be deposited in a special trust account in an insured financial institution author...
```

**Run 2 (4776ms):**

```
- The PROPERTY MANAGEMENT AGREEMENT mentions insurance and specifies the following limits: minimum limits of $300,000 for bodily injury and $25,000 for property damage to others [2].
- The PROPERTY MANAGEMENT AGREEMENT requires the Agent to be named as additional insured and to be furnished with a copy of the insurance policy and a certificate of insurance [1].
- The PROPERTY MANAGEMENT AGREEMENT requires rents to be deposited in a special trust account in an insured financial institution author...
```

#### Q-D5: In the warranty, explain how the "coverage start" is defined and what must happen before coverage ends.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.08 |
| Containment | 0.85 |
| Precision | 0.29 |
| Recall | 0.85 |
| F1 Score | 0.44 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.56 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 2 |
| Latency P50 (ms) | 4538 |
| Latency P95 (ms) | 5462 |

**Run 1 (5462ms):**

```
- The coverage start is defined as the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first [1].
- Before coverage ends, the Buyer/Owner must write a letter describing the defect and send it by certified mail return receipt requested to the Builder at the Builder's office address, prior to the termination of the one (1) year or sixty (60) day warranty period as applicable [2].
- The warranty automatically terminates if the first purchaser sells...
```

**Run 2 (4538ms):**

```
- The "coverage start" is defined as the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first [1].
- Before coverage ends, the Buyer/Owner must notify the Builder in writing of any defect believed to be covered by the warranty, and this must be done prior to the termination of the one (1) year or sixty (60) day warranty period, as applicable [5].
- The warranty coverage ends one (1) year or sixty (60) days after commencement, as applicable, unl...
```

#### Q-D6: Do the purchase contract total price and the invoice total match? If so, what is that amount?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.23 |
| Containment | 0.40 |
| Precision | 0.27 |
| Recall | 0.40 |
| F1 Score | 0.32 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3999 |
| Latency P95 (ms) | 33756 |

**Run 1 (33756ms):**

```
- The purchase contract total price is $29,900.00 [1].
- The invoice total is $29,900.00 [2].
- The purchase contract total price and the invoice total match at $29,900.00 [1][2].
```

**Run 2 (3996ms):**

```
- The purchase contract total price is $29,900.00 [1].
- The invoice total is $29,900.00 [2].
- The purchase contract total price and the invoice total match at $29,900.00 [1][2].
```

#### Q-D7: Which document has the latest explicit date, and what is it?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.40 |
| Containment | 0.30 |
| Precision | 0.37 |
| Recall | 0.30 |
| F1 Score | 0.33 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3557 |
| Latency P95 (ms) | 3910 |

**Run 1 (3910ms):**

```
- The document "purchase contract" has the latest explicit date: 04/30/2025 [1], [4].
- No other document contains a later explicit date than 04/30/2025.
```

**Run 2 (3552ms):**

```
- The document "purchase contract" has the latest explicit date: 04/30/2025 [1], [4].
- No other document contains a later explicit date than 04/30/2025.
```

#### Q-D8: Across the set, which entity appears in the most different documents: `Fabrikam Inc.` or `Contoso Ltd.`?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.04 |
| Containment | 0.41 |
| Precision | 0.51 |
| Recall | 0.41 |
| F1 Score | 0.46 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.77 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 7393 |
| Latency P95 (ms) | 36126 |

**Run 1 (7393ms):**

```
- Fabrikam Inc. appears in the following unique documents:
  - purchase contract [1], [7], [9]
  - PROPERTY%20MANAGEMENT%20AGREEMENT [2], [5], [10]
  - BUILDERS%20LIMITED%20WARRANTY [3], [6], [19], [21]
  - HOLDING%20TANK%20SERVICING%20CONTRACT [4], [8]
- Contoso Ltd. appears in the following unique documents:
  - purchase contract [1], [9]
  - PROPERTY%20MANAGEMENT%20AGREEMENT [2], [5], [10]
  - BUILDERS%20LIMITED%20WARRANTY [3], [6]
  - HOLDING%20TANK%20SERVICING%20CONTRACT [4], [8]
- Fabrikam...
```

**Run 2 (36126ms):**

```
- "Fabrikam Inc." appears in the following unique documents:
  - purchase contract [1], [7], [9]
  - PROPERTY%20MANAGEMENT%20AGREEMENT [2], [5], [10]
  - BUILDERS%20LIMITED%20WARRANTY [3], [6], [19], [21]
  - HOLDING%20TANK%20SERVICING%20CONTRACT [4], [8]
- "Contoso Ltd." appears in the following unique documents:
  - purchase contract [1], [9]
  - PROPERTY%20MANAGEMENT%20AGREEMENT [2], [5], [10]
  - BUILDERS%20LIMITED%20WARRANTY [3], [6]
  - HOLDING%20TANK%20SERVICING%20CONTRACT [4], [8]
- Both...
```

#### Q-D9: Compare the "fees" concepts: which doc has a percentage-based fee structure and which has fixed installment payments?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.10 |
| Containment | 0.84 |
| Precision | 0.46 |
| Recall | 0.84 |
| F1 Score | 0.59 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.75 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 4130 |
| Latency P95 (ms) | 4211 |

**Run 1 (3936ms):**

```
- The "purchase contract" has a fixed installment payment structure: $20,000.00 upon signing, $7,000.00 upon delivery, $2,900.00 upon completion [1].
- The "PROPERTY MANAGEMENT AGREEMENT" has a percentage-based fee structure: 25% of gross revenues for short term/vacation rentals, 10% of gross revenues for long term leases, and 10% of the total charge for repairs/upgrades/renovations [2], [3].
```

**Run 2 (4130ms):**

```
- The "purchase contract" has a fixed installment payment structure: $20,000.00 upon signing, $7,000.00 upon delivery, and $2,900.00 upon completion [1].
- The "PROPERTY MANAGEMENT AGREEMENT" has a percentage-based fee structure: 25% of gross revenues for short term/vacation rentals, 10% of gross revenues for long term leases, and 10% of the total charge for repairs/upgrades/renovations [2], [3].
- The "PROPERTY MANAGEMENT AGREEMENT" also includes some fixed fees: $35/hour for scheduling/escorti...
```

#### Q-D10: List the three different "risk allocation" statements across the set (risk of loss, liability limitations, non-transferability).

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | No |
| Fuzzy Score | 0.02 |
| Containment | 0.45 |
| Precision | 0.22 |
| Recall | 0.45 |
| F1 Score | 0.29 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.08 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3977 |
| Latency P95 (ms) | 33643 |

**Run 1 (3977ms):**

```
- Customer holds risk thereafter. Contractor holds risk until delivery. [1], [3]
- The Builder does not assume responsibility for any of the following, all of which are excluded from the coverage of this limited warranty. A. CONSEQUENTIAL OR INCIDENTAL DAMAGES. (SOME STATES DO NOT ALLOW THE EXCLUSION OR LIMITATION OF INCIDENTAL OR CONSEQUENTIAL DAMAGES, SO THE LIMITATION OR EXCLUSION MAY NOT APPLY TO YOU). [9]
- This limited warranty is extended to the Buyer/Owner as the first purchaser of the h...
```

**Run 2 (3602ms):**

```
- Customer holds risk thereafter. Contractor holds risk until delivery. [1], [3]
- Neither party may assign this contract without the other's written consent. [6]
- This limited warranty is extended to the Buyer/Owner as the first purchaser of the home and is not transferable. In the event the first purchaser sells the home or moves out of it, this limited warranty automatically terminates. [2]
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
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3334 |
| Latency P95 (ms) | 3627 |

**Run 1 (3627ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3041ms):**

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
| Latency P50 (ms) | 2825 |
| Latency P95 (ms) | 2837 |

**Run 1 (2825ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2803ms):**

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
| Latency P50 (ms) | 3481 |
| Latency P95 (ms) | 34379 |

**Run 1 (34379ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3307ms):**

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
| Latency P50 (ms) | 3069 |
| Latency P95 (ms) | 3260 |

**Run 1 (3260ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3069ms):**

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
| Exact Match Rate | 0.67 |
| Min Similarity | 0.99 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 2933 |
| Latency P95 (ms) | 33161 |

**Run 1 (33161ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (2914ms):**

```
The requested information was not found in the available documents.
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
| Latency P50 (ms) | 3149 |
| Latency P95 (ms) | 8187 |

**Run 1 (3149ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (3105ms):**

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
| Evidence Path (Unique) | 1 |
| Latency P50 (ms) | 3128 |
| Latency P95 (ms) | 33365 |

**Run 1 (3128ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2872ms):**

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
| Latency P50 (ms) | 2934 |
| Latency P95 (ms) | 2942 |

**Run 1 (2934ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2816ms):**

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
| Latency P50 (ms) | 2876 |
| Latency P95 (ms) | 33124 |

**Run 1 (2876ms):**

```
- The requested information was not found in the available documents.
```

**Run 2 (2858ms):**

```
- The requested information was not found in the available documents.
```

---

