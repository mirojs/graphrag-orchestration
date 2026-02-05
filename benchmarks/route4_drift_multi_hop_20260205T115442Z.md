# Route 4 (Drift Multi-Hop) Repeatability Benchmark

**Timestamp:** 20260205T115442Z

**API Base URL:** `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`

**Group ID:** `test-5pdfs-v2-fix2`

**Force Route:** `drift_multi_hop`

---

## Scenario: hybrid_route4_summary

**Response Type:** `summary`

### Q-D1: If an emergency defect occurs under the warranty (e.g., burst pipe), what is the required notification channel and consequence of delay?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.93 |
| Precision | 0.05 |
| Recall | 0.93 |
| F1 Score | 0.10 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.02 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.50 |
| Evidence Path Jaccard (Min) | 0.00 |
| Latency P50 (ms) | 65147 |
| Latency P95 (ms) | 73587 |
| Latency Min (ms) | 27017 |
| Latency Max (ms) | 73587 |

**Run 1 (27017ms):**

```
## Analysis

### Q1. How are emergency defects defined and what notification channel is required?

The Builders Limited Warranty states that if “an emergency exists or if a delay will cause extra damage (for instance, a defective pipe has burst)” the Buyer/Owner must treat this as an emergency situation.[10][19] A burst pipe is explicitly given as an example of such an emergency.[10][19]

For these emergencies, the warranty specifies a different notification channel than for ordinary defects:

-...
```

**Run 2 (65147ms):**

```
## Analysis

### Q1 & Q5 – What notification channel is required, and who must use it?

The Builders Limited Warranty specifies two different notification methods, depending on whether the issue is an emergency:

- **General (non‑emergency) defects**:  
  The Buyer/Owner “must…write a letter describing the defect to the Builder and send it by certified mail return receipt requested” to the Builder’s office address.[6]  
- **Emergency defects or situations where delay will cause extra damage (e.g...
```

### Q-D2: In the property management agreement, what happens to confirmed reservations if the agreement is terminated or the property is sold?

**Runs:** 2

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.01 |
| Containment | 1.00 |
| Precision | 0.02 |
| Recall | 1.00 |
| F1 Score | 0.04 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.50 |
| Min Similarity | 0.13 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 60769 |
| Latency P95 (ms) | 62497 |
| Latency Min (ms) | 60769 |
| Latency Max (ms) | 62497 |

**Run 1 (62497ms):**

```
## Analysis

### Q1. How are “confirmed reservations” defined and identified at termination or sale?

The Property Management Agreement mentions “confirmed reservations” only in the TERM clause:

> “In the event this agreement is terminated, or the property is sold, the Owner shall honor all confirmed reservations.” [5], [19], [29], [36], [40], [49], [57], [59], [70]

The agreement does **not** provide:
- an explicit definition of “confirmed reservations,” nor  
- a procedure for how they are id...
```

**Run 2 (60769ms):**

```
## Analysis

### Q1: How are “confirmed reservations” defined and identified at termination or sale?

The Property Management Agreement states:

> “Termination of this agreement does not invalidate any existing rental agreements made by Agent on Owner's behalf. Upon termination, Owner shall continue to be responsible or shall cause to be completed all obligations or expenses incurred hereunder by the Agent. **In the event this agreement is terminated, or the property is sold, the Owner shall hon...
```

### Q-D3: Compare "time windows" across the set: list all explicit day-based timeframes.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.01 |
| Containment | 0.82 |
| Precision | 0.10 |
| Recall | 0.82 |
| F1 Score | 0.18 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.05 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.80 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 42882 |
| Latency P95 (ms) | 51345 |
| Latency Min (ms) | 37713 |
| Latency Max (ms) | 51345 |

**Run 1 (51345ms):**

```
## Analysis

Below, “time windows” means explicit, day-based timeframes (e.g., X days, Y business days, Z months/years) that define when something can or must happen.

---

### Q1 – Identify all “time windows” across the set

Across all documents, the following explicit day‑based timeframes appear:

**Builders Limited Warranty**  
1. One (1) year warranty period for major components (floors, ceilings, walls, internal structural components, plumbing, heating, electrical, roof) [12].  
2. Sixty (6...
```

**Run 2 (42882ms):**

```
## Analysis

The original query is: **“Compare ‘time windows’ across the set: list all explicit day-based timeframes.”**  
Below are all the **explicit day-based timeframes** found in the provided documents, organized by document and tied back to the notion of “time windows.”

---

### 1. BUILDERS LIMITED WARRANTY

**Warranty coverage periods**

- Structural components, plumbing, heating, wiring, roof:  
  - “for a period of **one (1) year**” [12]  
- Doors, windows, switches, receptacles, fixtu...
```

### Q-D4: Which documents mention **insurance** and what limits are specified?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.02 |
| Containment | 0.89 |
| Precision | 0.10 |
| Recall | 0.89 |
| F1 Score | 0.18 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.08 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.33 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 16058 |
| Latency P95 (ms) | 29620 |
| Latency Min (ms) | 13487 |
| Latency Max (ms) | 29620 |

**Run 1 (29620ms):**

```
## Analysis

### Q1 & Q4: Which documents mention **insurance**?

Among the listed documents, only the **PROPERTY MANAGEMENT AGREEMENT** explicitly mentions insurance:

- PROPERTY MANAGEMENT AGREEMENT – Section “RESPONSIBILITIES OF OWNER,” clause (f): “Provide Liability Insurance coverage for the property…”[2]

The other documents shown (BUILDERS LIMITED WARRANTY and HOLDING TANK SERVICING CONTRACT) do not contain the word “insurance” in the provided excerpts.

**Answer to Q1/Q4:**  
- Documents...
```

**Run 2 (16058ms):**

```
## Analysis

### Q1: Which documents mention **insurance**?

Reviewing the provided documents, only the **PROPERTY MANAGEMENT AGREEMENT** explicitly mentions insurance. In the “RESPONSIBILITIES OF OWNER” section, clause (f) requires the Owner to “Provide Liability Insurance coverage for the property…”[2].

No references to insurance appear in the excerpts from:
- BUILDERS LIMITED WARRANTY
- HOLDING TANK SERVICING CONTRACT
- (No insurance language is shown from the purchase_contract or contoso_li...
```

### Q-D5: In the warranty, explain how the “coverage start” is defined and what must happen before coverage ends.

**Runs:** 1

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 137638 |
| Latency P95 (ms) | 137638 |
| Latency Min (ms) | 137638 |
| Latency Max (ms) | 137638 |

**Run 3 (137638ms):**

```
## Analysis

### Q1. How “coverage start” is defined

The Builders Limited Warranty does not use the phrase “coverage start,” but it explicitly defines when the warranty term begins in Section 2 (“Term”):

> “The terms of the various coverages of this Builder's Limited Warranty begin on **the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first**.”【10†L2-L2】【20†L2-L2】

So, the coverage start is triggered by the earlier of two events:
1. The dat...
```

### Q-D6: Do the purchase contract total price and the invoice total match? If so, what is that amount?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.01 |
| Containment | 0.44 |
| Precision | 0.02 |
| Recall | 0.44 |
| F1 Score | 0.04 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.07 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 2 |
| Citations Jaccard (Min) | 0.00 |
| Evidence Path Jaccard (Min) | 0.67 |
| Latency P50 (ms) | 66437 |
| Latency P95 (ms) | 85176 |
| Latency Min (ms) | 59604 |
| Latency Max (ms) | 85176 |

**Run 1 (85176ms):**

```
## Analysis

### Q1: Purchase contract total price

The purchase contract between Contoso Lifts LLC and Fabrikam Inc. states:

> “Total contract price is $29,900.00, payable in 3 installments…”【2†L23-L29】【3†L23-L29】.

No additional taxes, fees, or discounts are specified that change this total; the $29,900.00 is explicitly labeled as the “Total contract price”【2†L23-L29】. Therefore, the purchase contract total price is:

- **$29,900.00**【2†L23-L29】.

### Q2 & Q6: Invoice total amount

The Contos...
```

**Run 2 (66437ms):**

```
## Analysis

### Q1: Purchase contract total price

The purchase contract between Contoso Lifts LLC and Fabrikam Inc. states under “Payment Terms”:

> “Total contract price is $29,900.00, payable in 3 installments:
> · $20,000.00 upon signing  
> · $7,000.00 upon delivery  
> · $2,900.00 upon completion”【2†L33-L40】【3†L33-L40】.

This same total and installment breakdown is repeated consistently across the contract copies【5†L33-L40】【18†L33-L40】. There are no additional amounts specified that chang...
```

### Q-D7: Which document has the latest explicit date, and what is it?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.03 |
| Containment | 0.22 |
| Precision | 0.07 |
| Recall | 0.22 |
| F1 Score | 0.11 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 222 |
| Latency P95 (ms) | 256 |
| Latency Min (ms) | 210 |
| Latency Max (ms) | 256 |

**Run 1 (256ms):**

```
The document with the latest explicit date is **purchase_contract**, dated **2025-04-30**.

Other documents by date (descending): HOLDING TANK SERVICING CONTRACT (2024-06-15), contoso_lifts_invoice (2015-12-17), BUILDERS LIMITED WARRANTY (2010-06-15), PROPERTY MANAGEMENT AGREEMENT (2010-06-15)
```

**Run 2 (210ms):**

```
The document with the latest explicit date is **purchase_contract**, dated **2025-04-30**.

Other documents by date (descending): HOLDING TANK SERVICING CONTRACT (2024-06-15), contoso_lifts_invoice (2015-12-17), BUILDERS LIMITED WARRANTY (2010-06-15), PROPERTY MANAGEMENT AGREEMENT (2010-06-15)
```

### Q-D8: Across the set, which entity appears in the most different documents: `Fabrikam Inc.` or `Contoso Ltd.`?

**No successful runs.**

### Q-D9: Compare the “fees” concepts: which doc has a percentage-based fee structure and which has fixed installment payments?

**Runs:** 3

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.06 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.40 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 32638 |
| Latency P95 (ms) | 42088 |
| Latency Min (ms) | 29311 |
| Latency Max (ms) | 42088 |

**Run 1 (29311ms):**

```
## Analysis

### Q1. Document with a percentage-based fee structure and how it is defined

The **PROPERTY MANAGEMENT AGREEMENT** describes several “fees” that are calculated as percentages of underlying amounts:

- A **25% commission** “of the gross revenues for management services for short term and/or vacation rentals (reservations of less than 180 days)”[13].
- A **10% commission** “of the gross revenues for management services for long term leases (leases of more than 180 days)”[13].
- A **1...
```

**Run 2 (42088ms):**

```
## Analysis

### Q1: “Fees” concepts in each relevant document, and whether they are percentage-based or fixed installments

**PROPERTY MANAGEMENT AGREEMENT – “AGENT’S FEES”**  
This document contains multiple fee concepts, many of which are percentage-based and some of which are fixed dollar amounts or hourly rates:

- 25% commission on gross revenues for short-term/vacation rentals (reservations < 180 days) – percentage-based fee on gross revenues.[13][14][17]  
- 10% commission on gross reven...
```

### Q-D10: List the three different “risk allocation” statements across the set (risk of loss, liability limitations, non-transferability).

**No successful runs.**

### Q-N1: What is the invoice's **bank routing number** for payment?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ✅ PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 8199 |
| Latency P95 (ms) | 9325 |
| Latency Min (ms) | 6268 |
| Latency Max (ms) | 9325 |

**Run 1 (9325ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (6268ms):**

```
The requested information was not found in the available documents.
```

### Q-N2: What is the invoice’s **IBAN / SWIFT (BIC)** for international payments?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ✅ PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 2 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 0.00 |
| Latency P50 (ms) | 6224 |
| Latency P95 (ms) | 6863 |
| Latency Min (ms) | 6025 |
| Latency Max (ms) | 6863 |

**Run 1 (6224ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (6863ms):**

```
The requested information was not found in the available documents.
```

### Q-N3: What is the vendor's **VAT / Tax ID number** on the invoice?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ✅ PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 21480 |
| Latency P95 (ms) | 21480 |
| Latency Min (ms) | 21480 |
| Latency Max (ms) | 21480 |

**Run 1 (21480ms):**

```
## Analysis

### Q1: Who is the vendor listed on the invoice?

Across the provided documents, we see multiple contracts and agreements (Builders Limited Warranty, Holding Tank Servicing Contract, Property Management Agreement, Purchase Contract, Exhibit A – Scope of Work), but **none of these are invoices**. They identify parties such as:

- Fabrikam Inc. and Contoso Ltd. in various roles (builder/buyer, pumper/owner, owner/agent, contractor/customer) [1][2][3][4].  

However, there is **no docu...
```

### Q-N5: What is the invoice’s **bank account number** for ACH/wire payments?

**No successful runs.**

### Q-N6: Which documents are governed by the laws of **California**?

**No successful runs.**

### Q-N7: What is the property management Agent's **license number**?

**No successful runs.**

### Q-N8: What is the purchase contract’s required **wire transfer / ACH instructions**?

**No successful runs.**

### Q-N9: What is the exact clause about **mold damage** coverage in the warranty?

**No successful runs.**

### Q-N10: What is the invoice **shipping method** (value in "SHIPPED VIA")?

**No successful runs.**

---

