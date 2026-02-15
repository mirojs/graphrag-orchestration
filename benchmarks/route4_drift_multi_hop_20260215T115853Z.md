# Route 4 (Drift Multi-Hop) Repeatability Benchmark

**Timestamp:** 20260215T115853Z

**API Base URL:** `http://localhost:8000`

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
| Precision | 0.04 |
| Recall | 0.93 |
| F1 Score | 0.08 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.02 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.24 |
| Evidence Path Jaccard (Min) | 0.22 |
| Latency P50 (ms) | 28861 |
| Latency P95 (ms) | 37964 |
| Latency Min (ms) | 24003 |
| Latency Max (ms) | 37964 |

**Run 1 (37964ms):**

```
## Analysis

### 1. Required notification channel(s) and timing for an emergency defect (e.g., burst pipe)

Under the Builder’s Limited Warranty, the general rule for reporting defects is written notice by certified mail:

- The Buyer/Owner “must…write a letter describing the defect to the Builder and send it by certified mail return receipt requested to the Builder at the Builder's office address” before the end of the applicable warranty period (one year or sixty days, depending on the item).[...
```

**Run 2 (28861ms):**

```
## Analysis

### 1. Required / permitted notification channels for an emergency defect

The Builders Limited Warranty sets out two different notification mechanisms, depending on whether the issue is an emergency:

- **General (non‑emergency) defects**  
  - The owner “must…write a letter describing the defect to the Builder and send it by certified mail return receipt requested to the Builder at the Builder's office address” before the end of the applicable warranty period.[8][12]  
  - This wr...
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
| Min Similarity | 0.12 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.73 |
| Evidence Path Jaccard (Min) | 0.36 |
| Latency P50 (ms) | 29520 |
| Latency P95 (ms) | 30974 |
| Latency Min (ms) | 26878 |
| Latency Max (ms) | 30974 |

**Run 1 (29520ms):**

```
## Analysis

### 1. Definition of “confirmed reservations” and provisions that address them

The Property Management Agreement does **not expressly define** the term “confirmed reservations” anywhere in the text provided. There is no dedicated definition section or clause that states what counts as a “confirmed reservation.” Instead, the term appears only in the clause dealing with termination and sale of the property.  

The relevant provisions are in the **TERM** section:

- The agreement stat...
```

**Run 2 (30974ms):**

```
## Analysis

### 1. Definition of “confirmed reservations” and provisions on termination/sale

The Property Management Agreement does not expressly define the term “confirmed reservations” anywhere in the text.[1][4][6][14][17] There is also no separate definitions section that clarifies this term. Based on the structure of the agreement, “confirmed reservations” must be understood in context with “existing rental agreements made by Agent on Owner’s behalf.”[5][6][7]

The key operative provision...
```

### Q-D3: Compare "time windows" across the set: list all explicit day-based timeframes.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.01 |
| Containment | 0.81 |
| Precision | 0.09 |
| Recall | 0.81 |
| F1 Score | 0.17 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.02 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.87 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 37441 |
| Latency P95 (ms) | 53166 |
| Latency Min (ms) | 16102 |
| Latency Max (ms) | 53166 |

**Run 1 (53166ms):**

```
## Analysis

Below, I walk through the sub‑questions in order, using only **explicitly stated day‑based time windows** (i.e., periods expressed in days, such as “60 days,” “10 business days,” “less than 180 days,” etc.), and then synthesize them.

---

### 1. Identify all explicitly stated day‑based time windows

From the **BUILDERS LIMITED WARRANTY**:

1. **Sixty (60) days – defect‑free coverage for certain items**  
   - “The Builder warrants that … for a period of sixty (60) days that the fol...
```

**Run 2 (37441ms):**

```
## Analysis

Below, each sub-question is addressed in order, using only **explicit day-based timeframes** (i.e., periods expressed in days) from the provided documents.

---

### 1. What explicit day-based timeframes can be identified?

Across the documents, the following explicit day-based timeframes (in days) appear:

**From the Builders Limited Warranty** (doc_e0583fe312dc41439f5abae608cb9f9e):

1. **Sixty (60) days – defect-free warranty for certain items**  
   - Doors (including hardware),...
```

### Q-D4: Which documents mention **insurance** and what limits are specified?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.02 |
| Containment | 0.89 |
| Precision | 0.08 |
| Recall | 0.89 |
| F1 Score | 0.15 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.12 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.20 |
| Evidence Path Jaccard (Min) | 0.67 |
| Latency P50 (ms) | 16184 |
| Latency P95 (ms) | 22246 |
| Latency Min (ms) | 15110 |
| Latency Max (ms) | 22246 |

**Run 1 (22246ms):**

```
## Analysis

### 1. Which documents mention **insurance**?

From the provided documents, explicit mentions of **insurance** occur only in the **Property Management Agreement**:

- The Owner must “Provide Liability **Insurance** coverage for the property…” with specified minimum limits. [8][9]  
- The Agent must deposit rents in “a special trust account in an **insured** financial institution…” [11]

The **Builders Limited Warranty** and the **Holding Tank Servicing Contract** do not mention insu...
```

**Run 2 (15110ms):**

```
## Analysis

### 1. Which documents mention **insurance**?

Reviewing the provided documents:

- **PROPERTY MANAGEMENT AGREEMENT**  
  - Explicitly mentions “Liability Insurance coverage” and “insurance policy” and “certificate of insurance.” [4][5]  
  - Also refers to an “insured financial institution,” but that is about the bank account, not an insurance policy. [7]

- **BUILDERS LIMITED WARRANTY**  
  - Discusses warranties, exclusions, bodily injury, and property damage, but does **not** me...
```

### Q-D5: In the warranty, explain how the "coverage start" is defined and what must happen before coverage ends.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.92 |
| Precision | 0.07 |
| Recall | 0.92 |
| F1 Score | 0.13 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.11 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.86 |
| Evidence Path Jaccard (Min) | 0.88 |
| Latency P50 (ms) | 18755 |
| Latency P95 (ms) | 19392 |
| Latency Min (ms) | 18446 |
| Latency Max (ms) | 19392 |

**Run 1 (18446ms):**

```
## Analysis

### 1. How “coverage start” is defined

The warranty explicitly defines when coverage begins in the “Term” section:

- “The terms of the various coverages of this Builder's Limited Warranty begin on **the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first**.” [5], [13]

This means:

- There are two possible trigger events:
  1. The **date of final settlement** (i.e., closing/settlement on the home), and  
  2. The **date when the...
```

**Run 2 (18755ms):**

```
## Analysis

### 1. How “coverage start” is defined

The warranty explicitly defines when its various coverages begin in the “Term” section:

- “The terms of the various coverages of this Builder's Limited Warranty begin on **the date of final settlement or the date when the Buyer/Owner first occupies the home, whichever comes first**.” [2. Term A; see [5], [13]]

This means:

- There are two possible trigger events:
  1. The **date of final settlement** (i.e., closing/settlement of the purchase...
```

### Q-D6: Do the purchase contract total price and the invoice total match? If so, what is that amount?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.01 |
| Containment | 0.78 |
| Precision | 0.04 |
| Recall | 0.78 |
| F1 Score | 0.08 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.18 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.64 |
| Evidence Path Jaccard (Min) | 0.54 |
| Latency P50 (ms) | 18947 |
| Latency P95 (ms) | 19947 |
| Latency Min (ms) | 14362 |
| Latency Max (ms) | 19947 |

**Run 1 (14362ms):**

```
## Analysis

### 1. Purchase contract total price

The purchase contract between Contoso Lifts LLC (Contractor) and Fabrikam Inc. (Customer) specifies:

> “Total contract price is **$29,900.00**, payable in 3 installments:
> 
> · $20,000.00 upon signing  
> · $7,000.00 upon delivery  
> · $2,900.00 upon completion” [4], [10], [21].

There are no additional taxes, fees, or discounts stated that change this total; the clause on changes only says they “will affect the next payment milestone,” not t...
```

**Run 2 (18947ms):**

```
## Analysis

### 1. Total price specified in the purchase contract

The purchase contract between Contoso Lifts LLC (Contractor) and Fabrikam Inc. (Customer) states:

> “Total contract price is **$29,900.00**, payable in 3 installments:
> 
> · $20,000.00 upon signing  
> · $7,000.00 upon delivery  
> · $2,900.00 upon completion” [4], [10], [21].

No additional taxes, fees, or discounts are listed in the contract’s payment terms; the total contract price is explicitly given as **$29,900.00** with...
```

### Q-D7: Which document has the latest explicit date, and what is it?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.60 |
| Containment | 0.87 |
| Precision | 0.46 |
| Recall | 0.87 |
| F1 Score | 0.60 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 196 |
| Latency P95 (ms) | 1189 |
| Latency Min (ms) | 196 |
| Latency Max (ms) | 1189 |

**Run 1 (1189ms):**

```
The document with the latest explicit date is **purchase_contract**, dated **2025-04-30**.

Other documents by date (descending): HOLDING TANK SERVICING CONTRACT (2024-06-15), contoso_lifts_invoice (2015-12-17), BUILDERS LIMITED WARRANTY (2010-06-15), PROPERTY MANAGEMENT AGREEMENT (2010-06-15)
```

**Run 2 (196ms):**

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
| Fuzzy Score | 0.05 |
| Containment | 0.72 |
| Precision | 0.18 |
| Recall | 0.72 |
| F1 Score | 0.29 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.13 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 0.89 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 12988 |
| Latency P95 (ms) | 15855 |
| Latency Min (ms) | 12619 |
| Latency Max (ms) | 15855 |

**Run 1 (12988ms):**

```
## Analysis

### 1. In how many different documents does `Fabrikam Inc.` appear?

Scanning the provided documents:

1. **PROPERTY MANAGEMENT AGREEMENT**  
   - `Fabrikam Inc.` appears as a signing party:  
     “By: **Fabrikam Inc.** … It’s Principal Broker”[1].  
   → 1 document.

2. **BUILDERS LIMITED WARRANTY**  
   - `Fabrikam Inc.` is the Builder:  
     “this Limited Warranty Agreement is extended by **Fabrikam Inc.** (the Builder)”[2][8].  
   - It also appears in the signature block:  
 ...
```

**Run 2 (12619ms):**

```
## Analysis

### 1. In how many different documents does `Fabrikam Inc.` appear?

Scanning the provided documents:

- **PROPERTY MANAGEMENT AGREEMENT**: `Fabrikam Inc.` appears as the party signing as “Principal Broker” for the Agent, Walt Flood Realty. [1]  
- **BUILDERS LIMITED WARRANTY**: `Fabrikam Inc.` appears multiple times as the Builder and in the representative block. [2][8]  
- **HOLDING TANK SERVICING CONTRACT**: `Fabrikam Inc.` appears as the Pumper. [3]  
- **doc_f7f98f697dac444e9e7...
```

### Q-D9: Compare the "fees" concepts: which doc has a percentage-based fee structure and which has fixed installment payments?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.03 |
| Containment | 0.91 |
| Precision | 0.07 |
| Recall | 0.91 |
| F1 Score | 0.13 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.12 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.45 |
| Evidence Path Jaccard (Min) | 0.30 |
| Latency P50 (ms) | 23733 |
| Latency P95 (ms) | 33785 |
| Latency Min (ms) | 23468 |
| Latency Max (ms) | 33785 |

**Run 1 (23733ms):**

```
## Analysis

### 1. Doc with a percentage-based “fees” concept and its structure

The **PROPERTY MANAGEMENT AGREEMENT** explicitly defines multiple fees as percentages of amounts such as gross revenues and repair costs:

- “A fee/commission of **twenty five percent (25%) of the gross revenues** for management services for short term and/or vacation rentals (reservations of less than 180 days).” [5], [22]  
- “A fee/commission of **ten percent (10%) of the gross revenues** for management services...
```

**Run 2 (33785ms):**

```
## Analysis

### 1. “Fees” concepts in each relevant document and how they are structured

#### A. Property Management Agreement – fee concepts and structures

This document contains an explicit “AGENT’S FEES” section listing multiple fee types. They fall into two structural categories: percentage‑based and fixed (or fixed‑rate) charges.

**Percentage‑based fees**

1. **Management commission – short‑term rentals**  
   - “A fee/commission of twenty five percent (25%) of the gross revenues for ma...
```

### Q-D10: List the three different "risk allocation" statements across the set (risk of loss, liability limitations, non-transferability).

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.01 |
| Containment | 0.97 |
| Precision | 0.06 |
| Recall | 0.97 |
| F1 Score | 0.11 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.08 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.81 |
| Evidence Path Jaccard (Min) | 0.30 |
| Latency P50 (ms) | 32859 |
| Latency P95 (ms) | 38895 |
| Latency Min (ms) | 27849 |
| Latency Max (ms) | 38895 |

**Run 1 (27849ms):**

```
## Analysis

### 1. “Risk of loss” statements across the set

Only the **Purchase Contract** contains an explicit “risk of loss” allocation:

- **Purchase Contract – Section 5 (Risk of Loss)**  
  > “Contractor holds risk until delivery. Customer holds risk thereafter.” [4]  

This clause clearly allocates the risk of loss for the lift and related equipment: the Contractor bears the risk up to the point of delivery, and the Customer bears it after delivery. This is the only direct “risk of loss”...
```

**Run 2 (38895ms):**

```
## Analysis

### 1. Risk allocation – **risk of loss**

Across the three documents, “risk of loss” is addressed indirectly, by specifying who bears responsibility for certain losses or must insure against them.

**a. Property Management Agreement**

- The Owner must “Provide Liability Insurance coverage for the property with minimum limits of $300,000 for bodily injury and $25,000 for property damage to others. The Agent shall be named as additional insured…”[13].  
  - This allocates the risk o...
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
| Latency P50 (ms) | 5031 |
| Latency P95 (ms) | 9035 |
| Latency Min (ms) | 4580 |
| Latency Max (ms) | 9035 |

**Run 1 (9035ms):**

```
Not found in the provided documents.
```

**Run 2 (4580ms):**

```
Not found in the provided documents.
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
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 0.36 |
| Latency P50 (ms) | 11583 |
| Latency P95 (ms) | 12669 |
| Latency Min (ms) | 7053 |
| Latency Max (ms) | 12669 |

**Run 1 (11583ms):**

```
Not found in the provided documents.
```

**Run 2 (7053ms):**

```
Not found in the provided documents.
```

### Q-N3: What is the vendor's **VAT / Tax ID number** on the invoice?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ✅ PASS |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 0.33 |
| Min Similarity | 0.05 |
| Citations (Unique) | 2 |
| Evidence Path (Unique) | 2 |
| Citations Jaccard (Min) | 0.67 |
| Evidence Path Jaccard (Min) | 0.28 |
| Latency P50 (ms) | 16521 |
| Latency P95 (ms) | 22731 |
| Latency Min (ms) | 14707 |
| Latency Max (ms) | 22731 |

**Run 1 (14707ms):**

```
## Analysis

### 1. Which entity is identified as the **vendor** on the **invoice**?

Across the provided documents, several entities appear (Contoso Ltd., Walt Flood Realty, Fabrikam Inc.), but none of the documents is an **invoice**. We have:

- A **Property Management Agreement** between Contoso Ltd. (“Owner”) and Walt Flood Realty (“Agent”). [1]  
- A **Builder’s Limited Warranty** between Fabrikam Inc. (“Builder”) and Contoso Ltd. (“Buyer/Owner”). [2]  
- A **Holding Tank Servicing Contract...
```

**Run 2 (22731ms):**

```
## Analysis

### 1. Identify the vendor on the “invoice”

Across the provided documents, several entities appear, but we must determine which one is acting as the *vendor* in a context where an invoice (or invoice-like billing relationship) exists.

- In the **Property Management Agreement**, Walt Flood Realty is the “Agent” providing property management services to Contoso Ltd. (“Owner”). The Agent:
  - Advertises the rental unit and “Provide[s] the invoice(s) from the media, and pay the charge...
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
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 0.33 |
| Latency P50 (ms) | 9585 |
| Latency P95 (ms) | 10887 |
| Latency Min (ms) | 7939 |
| Latency Max (ms) | 10887 |

**Run 1 (7939ms):**

```
Not found in the provided documents.
```

**Run 2 (9585ms):**

```
Not found in the provided documents.
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
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 0.22 |
| Latency P50 (ms) | 10409 |
| Latency P95 (ms) | 12410 |
| Latency Min (ms) | 10311 |
| Latency Max (ms) | 12410 |

**Run 1 (12410ms):**

```
Not found in the provided documents.
```

**Run 2 (10409ms):**

```
Not found in the provided documents.
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
| Min Similarity | 0.05 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 2 |
| Citations Jaccard (Min) | 0.42 |
| Evidence Path Jaccard (Min) | 0.25 |
| Latency P50 (ms) | 16104 |
| Latency P95 (ms) | 18246 |
| Latency Min (ms) | 10789 |
| Latency Max (ms) | 18246 |

**Run 1 (16104ms):**

```
## Analysis

### 1. Identify the property management Agent

The “PROPERTY MANAGEMENT AGREEMENT (Short Term and/or Vacation/Holiday Rentals)” explicitly defines the parties as:

- Owner: Contoso Ltd.  
- Agent: “Walt Flood Realty, a Hawaii sole proprietorship (hereinafter called ‘Agent’)” [1][5][8].

Thus, the property management Agent referred to in the query is **Walt Flood Realty**.  

### 2. Locate where the Agent’s license number is recorded

Reviewing the full text of the Property Managemen...
```

**Run 2 (18246ms):**

```
## Analysis

### 1. Identify the property management Agent

The agreement explicitly states it is between Contoso Ltd. as “Owner” and “Walt Flood Realty, a Hawaii sole proprietorship (hereinafter called ‘Agent’).”[1][3][6]  
Therefore, the property management Agent referenced in the query is **Walt Flood Realty**.

### 2. Full legal name of the property management Agent

The document consistently uses the same designation: “Walt Flood Realty, a Hawaii sole proprietorship (hereinafter called ‘Age...
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
| Min Similarity | 0.08 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 0.20 |
| Evidence Path Jaccard (Min) | 0.36 |
| Latency P50 (ms) | 16815 |
| Latency P95 (ms) | 26737 |
| Latency Min (ms) | 15106 |
| Latency Max (ms) | 26737 |

**Run 1 (15106ms):**

```
## Analysis

### 1. What payment-related instructions are required by the **purchase contract**?

The purchase contract between Contoso Lifts LLC (Contractor) and Fabrikam Inc. (Customer) specifies **only the timing and amounts of payments**, not the method (e.g., wire, ACH, check) or any bank-routing details.

Under “Payment Terms,” the contract states that the **total contract price is $29,900.00, payable in 3 installments**:  
- **$20,000.00 upon signing**  
- **$7,000.00 upon delivery**  
- ...
```

**Run 2 (16815ms):**

```
## Analysis

### 1. What payment-related requirements are in the **purchase contract**?

The “PURCHASE CONTRACT” between Contoso Lifts LLC (Contractor) and Fabrikam Inc. (Customer) sets out **only the amounts, timing, and conditions of payments**, not any banking or transfer details.

Key payment terms:

- **Total contract price**: $29,900.00 [2], [6], [8].  
- **Installment schedule**:  
  - $20,000.00 upon signing [2], [8]  
  - $7,000.00 upon delivery [2], [8]  
  - $2,900.00 upon completion ...
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
| Evidence Path (Unique) | 3 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 0.46 |
| Latency P50 (ms) | 12974 |
| Latency P95 (ms) | 25298 |
| Latency Min (ms) | 9693 |
| Latency Max (ms) | 25298 |

**Run 1 (9693ms):**

```
Not found in the provided documents.
```

**Run 2 (25298ms):**

```
Not found in the provided documents.
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
| Exact Match Rate | 0.33 |
| Min Similarity | 0.04 |
| Citations (Unique) | 3 |
| Evidence Path (Unique) | 2 |
| Citations Jaccard (Min) | 0.00 |
| Evidence Path Jaccard (Min) | 0.40 |
| Latency P50 (ms) | 12097 |
| Latency P95 (ms) | 16404 |
| Latency Min (ms) | 11706 |
| Latency Max (ms) | 16404 |

**Run 1 (11706ms):**

```
## Analysis

### 1. Location of the **"SHIPPED VIA"** field on the invoice

In the *Contoso Lifts LLC* invoice, there is a header table that lists several order-related fields: **SALESPERSON**, **P.O. NUMBER**, **REQUISITIONER**, **SHIPPED VIA**, **DUE DATE**, and **TERMS**.[3][4]

This table appears beneath the “SHIP TO” section and above the line-item table of quantities and descriptions.[3][4] Within that header table, **"SHIPPED VIA"** is one of the column headers.[3][4]

The corresponding r...
```

**Run 2 (16404ms):**

```
## Analysis

### 1. Location of the **"SHIPPED VIA"** field

The provided evidence includes:

- A **Property Management Agreement** between Contoso Ltd. and Walt Flood Realty, which covers agency, responsibilities, fees, start-up fee, and legal terms, but contains no invoice layout or shipping section and no field labeled **"SHIPPED VIA"**. [1][6]  
- A **Builder’s Limited Warranty** between Fabrikam Inc. and Contoso Ltd., which describes warranty terms, exclusions, arbitration, and signatures, ...
```

---

