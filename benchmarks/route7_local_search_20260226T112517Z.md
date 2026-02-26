# Route 7 (HippoRAG2) Repeatability Benchmark

**Timestamp:** 20260226T112517Z

**API Base URL:** `https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`

**Group ID:** `test-5pdfs-v2-fix2`

**Force Route:** `hipporag2_search`

---

## Scenario: hybrid_route2_summary

**Response Type:** `summary`

### Q-L1: Who is the **Agent** in the property management agreement?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.13 |
| Containment | 1.00 |
| Precision | 0.12 |
| Recall | 1.00 |
| F1 Score | 0.22 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 35897 |
| Latency P95 (ms) | 35897 |
| Latency Min (ms) | 35897 |
| Latency Max (ms) | 35897 |

**Run 1 (35897ms):**

```
## Summary

The Agent in the property management agreement is Walt Flood Realty, a Hawaii sole proprietorship. The agreement is made between Contoso Ltd. (the Owner) and Walt Flood Realty (the Agent), with the Agent being exclusively appointed to rent, lease, operate, and manage the property located at 456 Palm Tree Avenue, Honolulu, HI 96815, known as Pacific View Retreat, Unit B202 [1][3][4][5][6][7][8][9].

## Key Points

- The Agent is Walt Flood Realty, a Hawaii sole proprietorship [1][3][4...
```

### Q-L2: Who is the **Owner** in the property management agreement?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 1.00 |
| Precision | 0.04 |
| Recall | 1.00 |
| F1 Score | 0.07 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 5311 |
| Latency P95 (ms) | 5311 |
| Latency Min (ms) | 5311 |
| Latency Max (ms) | 5311 |

**Run 1 (5311ms):**

```
## Summary

The **Owner** in the property management agreement is Contoso Ltd., as explicitly stated in the agreement. Contoso Ltd. is repeatedly identified as the party referred to as "Owner" throughout the document, and is the entity that appoints Walt Flood Realty as the Agent to manage the property located at 456 Palm Tree Avenue, Honolulu, HI 96815 (Pacific View Retreat, Unit # B202) [1][2][3][4][5][7][8].

## Key Points

- The Owner is Contoso Ltd. [1][2][3][4][5][7][8]
- Contoso Ltd. is e...
```

### Q-L3: What is the managed property address in the property management agreement?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.15 |
| Containment | 1.00 |
| Precision | 0.16 |
| Recall | 1.00 |
| F1 Score | 0.28 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 5365 |
| Latency P95 (ms) | 5365 |
| Latency Min (ms) | 5365 |
| Latency Max (ms) | 5365 |

**Run 1 (5365ms):**

```
## Summary

The managed property address specified in the property management agreement is 456 Palm Tree Avenue, Honolulu, HI 96815. The property is named "Pacific View Retreat" and the unit number is B202. This information is consistently stated across all provided documents [1][2][3][4][5][6][7].

## Key Points

- The managed property address is 456 Palm Tree Avenue, Honolulu, HI 96815 [1][2][3][4][5][6][7].
- The property name is Pacific View Retreat [1][2][3][4][5][6][7].
- The unit number i...
```

### Q-L4: What is the initial term start date in the property management agreement?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.02 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4435 |
| Latency P95 (ms) | 4435 |
| Latency Min (ms) | 4435 |
| Latency Max (ms) | 4435 |

**Run 1 (4435ms):**

```
## Summary

The property management agreement specifies that the initial term is for a period of twelve months; however, the exact start date is not provided in the available evidence. The agreement repeatedly states, "This agreement shall be for an initial period of twelve months beginning on:" but does not include a specific date following this phrase in any of the provided excerpts [1][2][4][5][6][7].

## Key Points

- The agreement is for an initial period of twelve months [1][2][4][5][6][7]...
```

### Q-L5: What written notice period is required for termination of the property management agreement?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.06 |
| Containment | 0.00 |
| Precision | 0.04 |
| Recall | 0.40 |
| F1 Score | 0.07 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4733 |
| Latency P95 (ms) | 4733 |
| Latency Min (ms) | 4733 |
| Latency Max (ms) | 4733 |

**Run 1 (4733ms):**

```
## Summary

The available documents do not specify any written notice period required for termination of the property management agreement. The evidence context provides details about the parties, property, and the initial term of twelve months, but does not include any information regarding the notice period for termination.

## Key Points

- The property management agreement is for an initial period of twelve months [1][2][3][4][5][6][7][8].
- No written notice period for termination is specif...
```

### Q-L6: What is the Agent fee/commission for **short-term** rentals (<180 days)?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.14 |
| Containment | 1.00 |
| Precision | 0.15 |
| Recall | 1.00 |
| F1 Score | 0.26 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4692 |
| Latency P95 (ms) | 4692 |
| Latency Min (ms) | 4692 |
| Latency Max (ms) | 4692 |

**Run 1 (4692ms):**

```
## Summary

For short-term rentals (defined as reservations of less than 180 days), the agent fee/commission is twenty five percent (25%) of the gross revenues for management services. This applies specifically to short term and/or vacation/holiday rentals as outlined in the agreement [6].

## Key Points

- The agent is entitled to a fee/commission of twenty five percent (25%) of the gross revenues for management services for short term and/or vacation rentals (reservations of less than 180 days...
```

### Q-L7: What is the Agent fee/commission for **long-term** leases (>180 days)?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.09 |
| Containment | 1.00 |
| Precision | 0.11 |
| Recall | 1.00 |
| F1 Score | 0.20 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4371 |
| Latency P95 (ms) | 4371 |
| Latency Min (ms) | 4371 |
| Latency Max (ms) | 4371 |

**Run 1 (4371ms):**

```
## Summary

For long-term leases (defined as reservations greater than 180 days), the Agent fee/commission is ten percent (10%) of the gross revenues for management services. This fee is explicitly stated as separate from the short-term/vacation rental commission, which is twenty-five percent (25%) for reservations of less than 180 days [6].

## Key Points

- The Agent's fee/commission for long-term leases (reservations greater than 180 days) is ten percent (10%) of the gross revenues for manage...
```

### Q-L8: What is the pro-ration advertising charge and minimum admin/accounting charge in the property management agreement?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.27 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4048 |
| Latency P95 (ms) | 4048 |
| Latency Min (ms) | 4048 |
| Latency Max (ms) | 4048 |

**Run 1 (4048ms):**

```
The requested information was not found in the available documents.
```

### Q-L9: In the purchase contract Exhibit A, what is the job location?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.13 |
| Containment | 1.00 |
| Precision | 0.17 |
| Recall | 1.00 |
| F1 Score | 0.29 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 3951 |
| Latency P95 (ms) | 3951 |
| Latency Min (ms) | 3951 |
| Latency Max (ms) | 3951 |

**Run 1 (3951ms):**

```
## Summary

The job location specified in Exhibit A of the purchase contract is 811 Ocean Drive, Suite 405, Tampa, FL 33602. This address is consistently listed as the job location for the Bayfront Animal Clinic project, which involves the installation of a Vertical Platform Lift (AscendPro VPX200) and related equipment [2][5].

## Key Points

- The job location for the Bayfront Animal Clinic project in the purchase contract Exhibit A is 811 Ocean Drive, Suite 405, Tampa, FL 33602 [2][5].
- The ...
```

### Q-L10: In the purchase contract Exhibit A, what is the contact’s name and email?   - **Expected Route:** Route 2 (Local Search)   - **Expected:** `Elizabeth Nolasco; enolasco@fabrikam.com`

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.20 |
| Containment | 1.00 |
| Precision | 0.14 |
| Recall | 1.00 |
| F1 Score | 0.24 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 3709 |
| Latency P95 (ms) | 3709 |
| Latency Min (ms) | 3709 |
| Latency Max (ms) | 3709 |

**Run 1 (3709ms):**

```
## Summary

The contact's name in the purchase contract Exhibit A is Elizabeth Nolasco, and the email address is enolasco@fabrikam.com. This information is explicitly listed under the job details for Bayfront Animal Clinic in the contract documentation [1][6][7].

## Key Points

- Contact’s name: Elizabeth Nolasco [1][6][7]
- Contact’s email: enolasco@fabrikam.com [1][6][7]
```

### Q-N1: What is the invoice's **bank routing number** for payment?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 2979 |
| Latency P95 (ms) | 2979 |
| Latency Min (ms) | 2979 |
| Latency Max (ms) | 2979 |

**Run 1 (2979ms):**

```
Not found in the provided documents.
```

### Q-N2: What is the invoice’s **IBAN / SWIFT (BIC)** for international payments?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 2469 |
| Latency P95 (ms) | 2469 |
| Latency Min (ms) | 2469 |
| Latency Max (ms) | 2469 |

**Run 1 (2469ms):**

```
Not found in the provided documents.
```

### Q-N3: What is the vendor's **VAT / Tax ID number** on the invoice?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 1993 |
| Latency P95 (ms) | 1993 |
| Latency Min (ms) | 1993 |
| Latency Max (ms) | 1993 |

**Run 1 (1993ms):**

```
Not found in the provided documents.
```

### Q-N5: What is the invoice’s **bank account number** for ACH/wire payments?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 1950 |
| Latency P95 (ms) | 1950 |
| Latency Min (ms) | 1950 |
| Latency Max (ms) | 1950 |

**Run 1 (1950ms):**

```
Not found in the provided documents.
```

### Q-N6: Which documents are governed by the laws of **California**?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 1962 |
| Latency P95 (ms) | 1962 |
| Latency Min (ms) | 1962 |
| Latency Max (ms) | 1962 |

**Run 1 (1962ms):**

```
Not found in the provided documents.
```

### Q-N7: What is the property management Agent's **license number**?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4748 |
| Latency P95 (ms) | 4748 |
| Latency Min (ms) | 4748 |
| Latency Max (ms) | 4748 |

**Run 1 (4748ms):**

```
## Summary

The property management Agent's license number is not provided in the available documents. The documents identify the Agent as "Walt Flood Realty, a Hawaii sole proprietorship," but do not include any license number or similar identifier [1][2][3][4][5][6][7][8].

## Key Points

- The Agent is named "Walt Flood Realty, a Hawaii sole proprietorship" [1][2][3][4][5][6][7][8].
- No license number for the Agent is mentioned in any of the provided documents [1][2][3][4][5][6][7][8].

Resp...
```

### Q-N8: What is the purchase contract’s required **wire transfer / ACH instructions**?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4030 |
| Latency P95 (ms) | 4030 |
| Latency Min (ms) | 4030 |
| Latency Max (ms) | 4030 |

**Run 1 (4030ms):**

```
## Summary

The available evidence does not provide any wire transfer or ACH instructions, such as bank account numbers, routing numbers, or payment processing details, within the purchase contract or related documents. The contract references initial payment requirements and identifies the parties involved, but does not specify the method, account, or instructions for wire transfer or ACH payments [1][2][3][4][5][6].

## Key Points

- The purchase contract does not include wire transfer or ACH ...
```

### Q-N9: What is the exact clause about **mold damage** coverage in the warranty?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 1952 |
| Latency P95 (ms) | 1952 |
| Latency Min (ms) | 1952 |
| Latency Max (ms) | 1952 |

**Run 1 (1952ms):**

```
Not found in the provided documents.
```

### Q-N10: What is the invoice **shipping method** (value in "SHIPPED VIA")?

**Runs:** 1

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.00 |
| Containment | 0.00 |
| Precision | 0.00 |
| Recall | 0.00 |
| F1 Score | 0.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4630 |
| Latency P95 (ms) | 4630 |
| Latency Min (ms) | 4630 |
| Latency Max (ms) | 4630 |

**Run 1 (4630ms):**

```
## Summary

The invoice from Contoso Lifts LLC includes a table with a column labeled "SHIPPED VIA," which is intended to indicate the shipping method. However, the corresponding cell for "SHIPPED VIA" in the invoice is blank, and no shipping method is specified in the available evidence [1].

## Key Points

- The "SHIPPED VIA" field in the invoice is present but contains no value; the shipping method is not specified [1].
```

---

