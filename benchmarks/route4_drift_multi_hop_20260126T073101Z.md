# Route 4 (Drift Multi-Hop) Repeatability Benchmark

**Timestamp:** 20260126T073101Z

**API Base URL:** `https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`

**Group ID:** `test-5pdfs-1769071711867955961`

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
| F1 Score | 0.09 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.07 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 29073 |
| Latency P95 (ms) | 31031 |
| Latency Min (ms) | 28175 |
| Latency Max (ms) | 31031 |

**Run 1 (31031ms):**

```
## Analysis

### Q1 & Q5 – Required notification channel(s) for an emergency defect

The Builders Limited Warranty specifies two different channels, depending on whether the issue is routine or an emergency:

1. **Standard (non‑emergency) defects**  
   - Must be reported **in writing by letter**, sent **by certified mail, return receipt requested**, to the Builder’s office address listed in the warranty.[1][2][3]  
   - This written notice is required “prior to the termination of the one (1) ye...
```

**Run 2 (28175ms):**

```
## Analysis

### Q1 – Required notification channel and timing for an emergency defect (e.g., burst pipe)

Under the Builders Limited Warranty, the general rule is that defects must be reported in writing by certified mail to the Builder’s office address before the warranty period expires.[1][2][3] However, there is a specific rule for emergencies:

- If an emergency exists or if delay will cause extra damage (example given: “a defective pipe has burst”), the Buyer/Owner **must telephone the Bui...
```

### Q-D2: In the property management agreement, what happens to confirmed reservations if the agreement is terminated or the property is sold?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 1.00 |
| Precision | 0.01 |
| Recall | 1.00 |
| F1 Score | 0.03 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.05 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.14 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 24525 |
| Latency P95 (ms) | 39021 |
| Latency Min (ms) | 21643 |
| Latency Max (ms) | 39021 |

**Run 1 (39021ms):**

```
## Analysis

### Q1. How are “confirmed reservations” defined and identified at termination or sale?

The Property Management Agreement mentions “confirmed reservations” only once, in the TERM clause:

> “Termination of this agreement does not invalidate any existing rental agreements made by Agent on Owner's behalf. Upon termination, Owner shall continue to be responsible or shall cause to be completed all obligations or expenses incurred hereunder by the Agent. **In the event this agreement is...
```

**Run 2 (21643ms):**

```
## Analysis

### Q1: How are “confirmed reservations” defined and identified at termination or sale?

The Property Management Agreement does not provide an explicit definition of “confirmed reservations” or a special mechanism for identifying them at the moment of termination or sale. The relevant language appears in the TERM clause:

> “Termination of this agreement does not invalidate any existing rental agreements made by Agent on Owner's behalf. Upon termination, Owner shall continue to be r...
```

### Q-D3: Compare "time windows" across the set: list all explicit day-based timeframes.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.03 |
| Containment | 0.86 |
| Precision | 0.18 |
| Recall | 0.86 |
| F1 Score | 0.29 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.04 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.80 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 28752 |
| Latency P95 (ms) | 38990 |
| Latency Min (ms) | 23386 |
| Latency Max (ms) | 38990 |

**Run 1 (23386ms):**

```
## Analysis

### Q1: Compare "time windows" across the set: list all explicit day-based timeframes.

Below are all explicit *day-based* time windows (i.e., expressed in days, business days, or days within longer periods) found in the provided documents.

#### Builders Limited Warranty / Coverage

1. **One-year warranty period**
   - Structural components, plumbing, heating, electrical systems, and roof are warranted “for a period of one (1) year” against defects in materials or workmanship.[1][1...
```

**Run 2 (38990ms):**

```
## Analysis

Below, “explicit day-based time windows” means any period expressed directly in days (e.g., “60 days,” “3 business days,” “ten (10) business days”).

---

### Q3. What are all the explicitly stated day-based time windows mentioned?

From the corpus, the following explicit day-based windows appear:

1. **Sixty (60) days – Builder’s Limited Warranty (coverage for certain items)**  
   - “The Builder warrants … for a period of sixty (60) days that the following items will be free of de...
```

### Q-D4: Which documents mention **insurance** and what limits are specified?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.03 |
| Containment | 0.94 |
| Precision | 0.13 |
| Recall | 0.94 |
| F1 Score | 0.23 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.46 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 12368 |
| Latency P95 (ms) | 13725 |
| Latency Min (ms) | 11434 |
| Latency Max (ms) | 13725 |

**Run 1 (11434ms):**

```
## Analysis

### Q1 & Q3: Which documents mention **insurance**?

Reviewing the provided documents, only the **PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals)** contains the term “Insurance.” In the “RESPONSIBILITIES OF OWNER” section, clause (f) states:

> “Provide Liability Insurance coverage for the property with minimum limits of $300,000 for bodily injury and $25,000 for property damage to others. The Agent shall be named as additional insured and shall be furnish...
```

**Run 2 (13725ms):**

```
## Analysis

### Q1: Which documents mention **insurance**?

Reviewing the provided documents, only the **PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals)** contains the term “Insurance.” In the “RESPONSIBILITIES OF OWNER” section, clause (f) states:

> “Provide Liability Insurance coverage for the property with minimum limits of $300,000 for bodily injury and $25,000 for property damage to others. The Agent shall be named as additional insured and shall be furnished wi...
```

### Q-D5: In the warranty, explain how the “coverage start” is defined and what must happen before coverage ends.

**Runs:** 3

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.07 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.71 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 18981 |
| Latency P95 (ms) | 23707 |
| Latency Min (ms) | 17056 |
| Latency Max (ms) | 23707 |

**Run 1 (17056ms):**

```
## Analysis

### Q1. How “coverage start” is defined

The warranty’s coverage start (commencement) is defined in Section 2.A of the Builder’s Limited Warranty. It states:

> “The terms of the various coverages of this Builder's Limited Warranty begin on the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first.” [2][3]

So, coverage begins automatically on the earlier of these two events:

1. **Date of final settlement** (i.e., closing/settlemen...
```

**Run 2 (23707ms):**

```
## Analysis

### Q1. How the “coverage start” is defined

The warranty defines a single “commencement” point for all of its coverages in Section 2 (“Term”):

- “The terms of the various coverages of this Builder's Limited Warranty begin on **the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first**.” [2][3]

Key elements of the coverage start:

- It is tied to **events**, not a fixed calendar date in the text:
  - Event 1: “date of final settl...
```

### Q-D6: Do the purchase contract total price and the invoice total match? If so, what is that amount?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.01 |
| Containment | 0.67 |
| Precision | 0.04 |
| Recall | 0.67 |
| F1 Score | 0.08 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.17 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 18952 |
| Latency P95 (ms) | 22527 |
| Latency Min (ms) | 12807 |
| Latency Max (ms) | 22527 |

**Run 1 (18952ms):**

```
## Analysis

### Q1: Total price in the purchase contract

The purchase contract between Contoso Lifts LLC and Fabrikam Inc. explicitly states:

> “Total contract price is $29,900.00, payable in 3 installments:
> · $20,000.00 upon signing  
> · $7,000.00 upon delivery  
> · $2,900.00 upon completion” [3][4]

Thus, the total price specified in the purchase contract is **$29,900.00**.

### Q2: Total amount on the invoice

The invoice from Contoso Lifts LLC to Fabrikam Construction lists multiple l...
```

**Run 2 (12807ms):**

```
## Analysis

### Q1: Purchase contract total price

The purchase contract between Contoso Lifts LLC (Contractor) and Fabrikam Inc. (Customer) explicitly states:

> “Total contract price is $29,900.00, payable in 3 installments:
> · $20,000.00 upon signing  
> · $7,000.00 upon delivery  
> · $2,900.00 upon completion” [3][4].

There are no additional adjustments, taxes, or discounts specified that change this overall total. Therefore, the total price specified in the purchase contract is **$29,90...
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
| Latency P50 (ms) | 206 |
| Latency P95 (ms) | 1151 |
| Latency Min (ms) | 205 |
| Latency Max (ms) | 1151 |

**Run 1 (1151ms):**

```
The document with the latest explicit date is **purchase_contract**, dated **2025-04-30**.

Other documents by date (descending): HOLDING TANK SERVICING CONTRACT (2024-06-15), contoso_lifts_invoice (2015-12-17), BUILDERS LIMITED WARRANTY (2010-06-15), PROPERTY MANAGEMENT AGREEMENT (2010-06-15)
```

**Run 2 (206ms):**

```
The document with the latest explicit date is **purchase_contract**, dated **2025-04-30**.

Other documents by date (descending): HOLDING TANK SERVICING CONTRACT (2024-06-15), contoso_lifts_invoice (2015-12-17), BUILDERS LIMITED WARRANTY (2010-06-15), PROPERTY MANAGEMENT AGREEMENT (2010-06-15)
```

### Q-D8: Across the set, which entity appears in the most different documents: `Fabrikam Inc.` or `Contoso Ltd.`?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.03 |
| Containment | 0.62 |
| Precision | 0.21 |
| Recall | 0.62 |
| F1 Score | 0.32 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.41 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.71 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 15724 |
| Latency P95 (ms) | 17707 |
| Latency Min (ms) | 13233 |
| Latency Max (ms) | 17707 |

**Run 1 (13233ms):**

```
## Analysis

### Q1: Across the set, in how many different documents does `Fabrikam Inc.` appear?

`Fabrikam Inc.` appears as a party or company name in multiple distinct documents in the set:

1. **Builder’s Limited Warranty with Arbitration** – Fabrikam Inc. is the Builder and is listed in the signature block and contact details.[1][14][16]  
2. **Exhibit A – Scope of Work (Bayfront Animal Clinic)** – Fabrikam Inc. appears in the signature block as an Authorized Representative.[5][6]  
3. **Ho...
```

**Run 2 (17707ms):**

```
## Analysis

### Q1: In how many different documents does `Fabrikam Inc.` appear?

`Fabrikam Inc.` appears in multiple distinct documents in the provided set:

- As Builder and company address in the Builder’s Limited Warranty / Arbitration document, including the representative block and signature section, where “Company Fabrikam Inc.” and “Fabrikam Inc.” are listed repeatedly as the Builder and signatory.[1][16][14][15]  
- In the Exhibit A – Scope of Work document, where an authorized represe...
```

### Q-D9: Compare the “fees” concepts: which doc has a percentage-based fee structure and which has fixed installment payments?

**Runs:** 3

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.10 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.62 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 32051 |
| Latency P95 (ms) | 34748 |
| Latency Min (ms) | 29860 |
| Latency Max (ms) | 34748 |

**Run 1 (34748ms):**

```
## Analysis

### Q1: For each relevant doc, what “fees” concepts are described, and are any explicitly percentage‑based?

**Relevant docs with “fees” language:**

1. **PROPERTY MANAGEMENT AGREEMENT** (short‑term/vacation rentals) – percentage‑based fees  
   The “AGENT'S FEES” section lists several fees, some explicitly as percentages of amounts:  
   - “A fee/commission of twenty five percent (25%) of the gross revenues for management services for short term and/or vacation rentals”[13]  
   - ...
```

**Run 2 (32051ms):**

```
## Analysis

### Q1 – Documents with a percentage‑based fee structure and how it is described

The **PROPERTY MANAGEMENT AGREEMENT** contains multiple percentage‑based fees:

- “A fee/commission of **twenty five percent (25%) of the gross revenues** for management services for short term and/or vacation rentals (reservations of less than 180 days).” [13], [14], [17]  
- “A fee/commission of **ten percent (10%) of the gross revenues** for management services for long term leases (leases of more t...
```

### Q-D10: List the three different “risk allocation” statements across the set (risk of loss, liability limitations, non-transferability).

**Runs:** 3

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.03 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.70 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 43861 |
| Latency P95 (ms) | 46960 |
| Latency Min (ms) | 31162 |
| Latency Max (ms) | 46960 |

**Run 1 (43861ms):**

```
## Analysis

### Q1 & Q5 – “Risk of loss” statements across the set

The only explicit “risk of loss” allocation language in the set appears in the Purchase Contract for the vertical platform lift:

> “### 5. Risk of Loss  
> Contractor holds risk until delivery. Customer holds risk thereafter.”[10][11]

This clause clearly allocates who bears the risk if the lift is damaged or destroyed at different points in time: the Contractor bears that risk before delivery; once delivery occurs, the Custom...
```

**Run 2 (46960ms):**

```
## Analysis

### Q1. What “risk allocation” statements appear across the set?

Across the documents, the provisions that allocate risk between the parties fall into three conceptual buckets:

1. **Risk of loss** – who bears the risk if the goods are damaged or lost.
2. **Liability limitations / exclusions** – who bears (or does not bear) responsibility for certain damages or claims.
3. **Non‑transferability / assignment restrictions** – who can transfer rights or obligations, and when.

Concrete...
```

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
| Evidence Path (Unique) | 2 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 0.00 |
| Latency P50 (ms) | 4883 |
| Latency P95 (ms) | 7609 |
| Latency Min (ms) | 3305 |
| Latency Max (ms) | 7609 |

**Run 1 (7609ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (4883ms):**

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
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 8453 |
| Latency P95 (ms) | 8580 |
| Latency Min (ms) | 8194 |
| Latency Max (ms) | 8580 |

**Run 1 (8580ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (8194ms):**

```
The requested information was not found in the available documents.
```

### Q-N3: What is the vendor's **VAT / Tax ID number** on the invoice?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ❌ FAIL |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.10 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.50 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 16925 |
| Latency P95 (ms) | 18026 |
| Latency Min (ms) | 14439 |
| Latency Max (ms) | 18026 |

**Run 1 (18026ms):**

```
## Analysis

### Q1 & Q3: Which entity is identified as the vendor on the invoice, with full legal name and registration details?

The only invoice in the corpus is the “Contoso Lifts LLC” invoice dated 12/17/2015. The header clearly identifies:

- “Contoso Lifts LLC” at the top, followed by “INVOICE” and the tagline “Your elevator and lift experts.”  
- The address block: “Contoso Lifts LLC, P.O. Box 123567 Key West, FL. 33304-0708” along with phone and fax numbers.  
- Payment instructions: “M...
```

**Run 2 (14439ms):**

```
## Analysis

### Q1: Which entity is identified as the **vendor** on the invoice?

The only invoice in the provided corpus is the “Contoso Lifts LLC” invoice dated 12/17/2015.[2] On this document, the company issuing the invoice is:

> “Contoso Lifts LLC  
> INVOICE  
> Your elevator and lift experts  
> Contoso Lifts LLC  
> P.O. Box 123567 Key West, FL. 33304-0708”[2]

The payment instructions also state:

> “Make all checks payable to Contoso Lifts LLC”[2]

This clearly identifies **Contoso L...
```

### Q-N5: What is the invoice’s **bank account number** for ACH/wire payments?

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
| Latency P50 (ms) | 8338 |
| Latency P95 (ms) | 9538 |
| Latency Min (ms) | 8110 |
| Latency Max (ms) | 9538 |

**Run 1 (9538ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (8338ms):**

```
The requested information was not found in the available documents.
```

### Q-N6: Which documents are governed by the laws of **California**?

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
| Latency P50 (ms) | 11697 |
| Latency P95 (ms) | 11958 |
| Latency Min (ms) | 7685 |
| Latency Max (ms) | 11958 |

**Run 1 (11697ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (11958ms):**

```
The requested information was not found in the available documents.
```

### Q-N7: What is the property management Agent's **license number**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ✅ PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.03 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.50 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 13252 |
| Latency P95 (ms) | 24412 |
| Latency Min (ms) | 11878 |
| Latency Max (ms) | 24412 |

**Run 1 (13252ms):**

```
## Analysis

### Q1: What is the **official license number** issued to this property management Agent?

The relevant document for identifying the property management Agent is the **PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals)**. In this agreement:

- The Owner is **Contoso Ltd.** and the Agent is **Walt Flood Realty, a Hawaii sole proprietorship**.[1]  
- The agreement is governed by the laws of the State of Hawaii and is signed by the Owner and the Agent’s Principa...
```

**Run 2 (11878ms):**

```
## Analysis

### Q1: According to the relevant licensing authority’s records, what is the license number associated with this specific property management Agent?

The property management Agent in the documents is identified as **“Walt Flood Realty, a Hawaii sole proprietorship”** in the **PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals)** between Contoso Ltd. (Owner) and Walt Flood Realty (Agent).[1] The agreement is governed by the laws of the State of Hawaii and is si...
```

### Q-N8: What is the purchase contract’s required **wire transfer / ACH instructions**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ✅ PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.06 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.38 |
| Evidence Path Jaccard (Min) | 0.00 |
| Latency P50 (ms) | 13050 |
| Latency P95 (ms) | 23736 |
| Latency Min (ms) | 11066 |
| Latency Max (ms) | 23736 |

**Run 1 (13050ms):**

```
## Analysis

### Q1: What is the purchase contract’s required wire transfer / ACH instructions?

The “PURCHASE CONTRACT” between Contoso Lifts LLC (Contractor) and Fabrikam Inc. (Customer) specifies the scope of work, payment amounts and milestones, governing law, and other terms, but it does **not** provide any bank account details, routing numbers, or other wire transfer / ACH instructions. The payment terms section only states that the total contract price of $29,900 is payable in three insta...
```

**Run 2 (11066ms):**

```
## Analysis

### Sub-question 1: “that must be used?” (i.e., what specific wire/ACH instructions are required?)

The only relevant contract in the corpus that matches the “purchase contract” is the **PURCHASE CONTRACT** between Contoso Lifts LLC (Contractor) and Fabrikam Inc. (Customer).[10][13]  

That contract:

- Specifies the **total price** and **payment milestones**:  
  - $20,000 upon signing  
  - $7,000 upon delivery  
  - $2,900 upon completion[10][13]  
- States that the contract is e...
```

### Q-N9: What is the exact clause about **mold damage** coverage in the warranty?

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
| Evidence Path Jaccard (Min) | 0.91 |
| Latency P50 (ms) | 12568 |
| Latency P95 (ms) | 15297 |
| Latency Min (ms) | 5459 |
| Latency Max (ms) | 15297 |

**Run 1 (15297ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (5459ms):**

```
The requested information was not found in the available documents.
```

### Q-N10: What is the invoice **shipping method** (value in "SHIPPED VIA")?

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
| Latency P50 (ms) | 8631 |
| Latency P95 (ms) | 11734 |
| Latency Min (ms) | 8274 |
| Latency Max (ms) | 11734 |

**Run 1 (11734ms):**

```
The requested information was not found in the available documents.
```

**Run 2 (8631ms):**

```
The requested information was not found in the available documents.
```

---

