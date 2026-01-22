# Route 1 (Vector RAG) Repeatability Benchmark

**Timestamp:** 20260122T150641Z

**API Base URL:** `http://localhost:8000`

**Group ID:** `test-5pdfs-1769071711867955961`

**Force Route:** `vector_rag`

---

## Scenario: hybrid_route1_summary

**Response Type:** `summary`

### Q-V1: What is the invoice **TOTAL** amount?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 4284 |
| Latency P95 (ms) | 6083 |
| Latency Min (ms) | 2302 |
| Latency Max (ms) | 6083 |

**Run 1 (6083ms):**

```
29900.00
```

**Run 2 (4284ms):**

```
29900.00
```

### Q-V2: What is the invoice **DUE DATE**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 2529 |
| Latency P95 (ms) | 4321 |
| Latency Min (ms) | 2420 |
| Latency Max (ms) | 4321 |

**Run 1 (4321ms):**

```
12/17/2015
```

**Run 2 (2420ms):**

```
12/17/2015
```

### Q-V3: What are the invoice **TERMS**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 3171 |
| Latency P95 (ms) | 3802 |
| Latency Min (ms) | 2503 |
| Latency Max (ms) | 3802 |

**Run 1 (2503ms):**

```
Due on contract signing
```

**Run 2 (3802ms):**

```
Due on contract signing
```

### Q-V4: In the purchase contract, list the **3 installment amounts** and their triggers.

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 7892 |
| Latency P95 (ms) | 43163 |
| Latency Min (ms) | 6439 |
| Latency Max (ms) | 43163 |

**Run 1 (43163ms):**

```
$20,000.00 upon signing; $7,000.00 upon delivery; $2,900.00 upon completion
```

**Run 2 (6439ms):**

```
$20,000.00 upon signing; $7,000.00 upon delivery; $2,900.00 upon completion
```

### Q-V5: What is the **labor warranty** duration in the purchase contract?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.14 |
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
| Latency P50 (ms) | 8144 |
| Latency P95 (ms) | 8299 |
| Latency Min (ms) | 7838 |
| Latency Max (ms) | 8299 |

**Run 1 (7838ms):**

```
Not found in the provided documents.
```

**Run 2 (8299ms):**

```
Not found in the provided documents.
```

### Q-V6: In the property management agreement, what is the **approval threshold** requiring prior written approval for expenditures?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ❌ |
| Fuzzy Score | 0.82 |
| Containment | 0.57 |
| Precision | 1.00 |
| Recall | 0.57 |
| F1 Score | 0.73 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 6443 |
| Latency P95 (ms) | 6897 |
| Latency Min (ms) | 5241 |
| Latency Max (ms) | 6897 |

**Run 1 (6443ms):**

```
Three Hundred Dollars ($300.00)
```

**Run 2 (5241ms):**

```
Three Hundred Dollars ($300.00)
```

### Q-V7: In the holding tank contract, what is the pumper’s **registration number**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 2699 |
| Latency P95 (ms) | 3267 |
| Latency Min (ms) | 2632 |
| Latency Max (ms) | 3267 |

**Run 1 (2632ms):**

```
REG-54321
```

**Run 2 (2699ms):**

```
REG-54321
```

### Q-V8: What is the warranty’s builder address city/state/zip?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 3136 |
| Latency P95 (ms) | 26554 |
| Latency Min (ms) | 3049 |
| Latency Max (ms) | 26554 |

**Run 1 (3049ms):**

```
Pocatello, ID 83201
```

**Run 2 (3136ms):**

```
Pocatello, ID 83201
```

### Q-V9: Who is the invoice **SALESPERSON**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 3662 |
| Latency P95 (ms) | 4219 |
| Latency Min (ms) | 3270 |
| Latency Max (ms) | 4219 |

**Run 1 (3662ms):**

```
Jim Contoso
```

**Run 2 (3270ms):**

```
Jim Contoso
```

### Q-V10: What is the invoice **P.O. NUMBER**?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match | ✅ |
| Fuzzy Score | 1.00 |
| Containment | 1.00 |
| Precision | 1.00 |
| Recall | 1.00 |
| F1 Score | 1.00 |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 5408 |
| Latency P95 (ms) | 6331 |
| Latency Min (ms) | 4509 |
| Latency Max (ms) | 6331 |

**Run 1 (4509ms):**

```
30060204
```

**Run 2 (5408ms):**

```
30060204
```

### Q-N1: What is the invoice’s **bank routing number** for payment?

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
| Latency P50 (ms) | 9350 |
| Latency P95 (ms) | 9583 |
| Latency Min (ms) | 8265 |
| Latency Max (ms) | 9583 |

**Run 1 (8265ms):**

```
Not found in the provided documents.
```

**Run 2 (9350ms):**

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
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 3363 |
| Latency P95 (ms) | 4125 |
| Latency Min (ms) | 2657 |
| Latency Max (ms) | 4125 |

**Run 1 (4125ms):**

```
Not found in the provided documents.
```

**Run 2 (3363ms):**

```
Not found in the provided documents.
```

### Q-N3: What is the vendor’s **VAT / Tax ID number** on the invoice?

**Runs:** 3

**Accuracy Metrics:**

| Metric | Value |
|--------|-------|
| Negative Test | ❌ FAIL |

**Repeatability Metrics:**

| Metric | Value |
|--------|-------|
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 3194 |
| Latency P95 (ms) | 4550 |
| Latency Min (ms) | 2827 |
| Latency Max (ms) | 4550 |

**Run 1 (2827ms):**

```
0098765
```

**Run 2 (4550ms):**

```
0098765
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
| Latency P50 (ms) | 6330 |
| Latency P95 (ms) | 10867 |
| Latency Min (ms) | 4992 |
| Latency Max (ms) | 10867 |

**Run 1 (10867ms):**

```
Not found in the provided documents.
```

**Run 2 (6330ms):**

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
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 472 |
| Latency P95 (ms) | 1566 |
| Latency Min (ms) | 439 |
| Latency Max (ms) | 1566 |

**Run 1 (1566ms):**

```
No relevant text found for this query.
```

**Run 2 (439ms):**

```
No relevant text found for this query.
```

### Q-N7: What is the property management Agent’s **license number**?

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
| Latency P50 (ms) | 7951 |
| Latency P95 (ms) | 8004 |
| Latency Min (ms) | 7786 |
| Latency Max (ms) | 8004 |

**Run 1 (8004ms):**

```
Not found in the provided documents.
```

**Run 2 (7786ms):**

```
Not found in the provided documents.
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
| Exact Match Rate | 1.00 |
| Min Similarity | 1.00 |
| Citations (Unique) | 1 |
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 7275 |
| Latency P95 (ms) | 7686 |
| Latency Min (ms) | 6833 |
| Latency Max (ms) | 7686 |

**Run 1 (7275ms):**

```
Not found in the provided documents.
```

**Run 2 (6833ms):**

```
Not found in the provided documents.
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
| Evidence Path (Unique) | 1 |
| Citations Jaccard (Min) | 1.00 |
| Evidence Path Jaccard (Min) | 1.00 |
| Latency P50 (ms) | 9509 |
| Latency P95 (ms) | 11914 |
| Latency Min (ms) | 9063 |
| Latency Max (ms) | 11914 |

**Run 1 (9509ms):**

```
Not found in the provided documents.
```

**Run 2 (9063ms):**

```
Not found in the provided documents.
```

### Q-N10: What is the invoice **shipping method** (value in “SHIPPED VIA”)?

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
| Latency P50 (ms) | 4082 |
| Latency P95 (ms) | 4629 |
| Latency Min (ms) | 3477 |
| Latency Max (ms) | 4629 |

**Run 1 (3477ms):**

```
Not found in the provided documents.
```

**Run 2 (4082ms):**

```
Not found in the provided documents.
```

---

