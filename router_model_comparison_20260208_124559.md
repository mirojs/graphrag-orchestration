# Router Model Comparison — Production Prompt
**Date:** 2026-02-08 12:45:59  
**Questions:** 41 (full bank, production prompt, markdown output)

## Summary

| # | Model | Hard Acc | Soft Acc | Avg Latency | Errors |
|---|-------|----------|----------|-------------|--------|
| 1 | gpt-4.1-mini | 97.6% (40/41) | 98.8% | 669 ms | 1 |
| 2 | gpt-5-mini | 97.6% (40/41) | 98.8% | 1780 ms | 1 |
| 3 | gpt-5.1 | 95.1% (39/41) | 96.3% | 889 ms | 2 |
| 4 | gpt-4o-mini | 92.7% (38/41) | 95.1% | 614 ms | 3 |
| 5 | gpt-4.1 | 92.7% (38/41) | 96.3% | 796 ms | 3 |
| 6 | gpt-5-nano | 92.7% (38/41) | 93.9% | 3080 ms | 3 |

## Per-Route Breakdown

### gpt-4.1-mini  —  97.6%

| Route | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| local_search | 100.0% | 96.2% | 0.980 | 26 |
| global_search | 88.9% | 100.0% | 0.941 | 8 |
| drift_multi_hop | 100.0% | 100.0% | 1.000 | 7 |

**Misclassifications (1):**
- Q-N6: exp=local_search, act=global_search *(soft)*  — "Which documents are governed by the laws of **California**?"

### gpt-5-mini  —  97.6%

| Route | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| local_search | 100.0% | 96.2% | 0.980 | 26 |
| global_search | 88.9% | 100.0% | 0.941 | 8 |
| drift_multi_hop | 100.0% | 100.0% | 1.000 | 7 |

**Misclassifications (1):**
- Q-N6: exp=local_search, act=global_search *(soft)*  — "Which documents are governed by the laws of **California**?"

### gpt-5.1  —  95.1%

| Route | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| local_search | 96.2% | 96.2% | 0.962 | 26 |
| global_search | 88.9% | 100.0% | 0.941 | 8 |
| drift_multi_hop | 100.0% | 85.7% | 0.923 | 7 |

**Misclassifications (2):**
- Q-D1: exp=drift_multi_hop, act=local_search  — "If an emergency defect occurs under the warranty (e.g., burst pipe), what is the"
- Q-N6: exp=local_search, act=global_search *(soft)*  — "Which documents are governed by the laws of **California**?"

### gpt-4o-mini  —  92.7%

| Route | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| local_search | 96.0% | 92.3% | 0.941 | 26 |
| global_search | 87.5% | 87.5% | 0.875 | 8 |
| drift_multi_hop | 87.5% | 100.0% | 0.933 | 7 |

**Misclassifications (3):**
- Q-V4: exp=local_search, act=drift_multi_hop  — "In the purchase contract, list the **3 installment amounts** and their triggers."
- Q-G4: exp=global_search, act=local_search *(soft)*  — "What obligations are explicitly described as **reporting / record-keeping**?"
- Q-N6: exp=local_search, act=global_search *(soft)*  — "Which documents are governed by the laws of **California**?"

### gpt-4.1  —  92.7%

| Route | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| local_search | 92.6% | 96.2% | 0.943 | 26 |
| global_search | 85.7% | 75.0% | 0.800 | 8 |
| drift_multi_hop | 100.0% | 100.0% | 1.000 | 7 |

**Misclassifications (3):**
- Q-G4: exp=global_search, act=local_search *(soft)*  — "What obligations are explicitly described as **reporting / record-keeping**?"
- Q-G5: exp=global_search, act=local_search *(soft)*  — "What remedies / dispute-resolution mechanisms are described?"
- Q-N6: exp=local_search, act=global_search *(soft)*  — "Which documents are governed by the laws of **California**?"

### gpt-5-nano  —  92.7%

| Route | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| local_search | 100.0% | 96.2% | 0.980 | 26 |
| global_search | 85.7% | 75.0% | 0.800 | 8 |
| drift_multi_hop | 77.8% | 100.0% | 0.875 | 7 |

**Misclassifications (3):**
- Q-G4: exp=global_search, act=drift_multi_hop  — "What obligations are explicitly described as **reporting / record-keeping**?"
- Q-G6: exp=global_search, act=drift_multi_hop  — "List all **named parties/organizations** across the documents and which document"
- Q-N6: exp=local_search, act=global_search *(soft)*  — "Which documents are governed by the laws of **California**?"

## Recommendation

**gpt-4.1-mini** — 97.6% hard accuracy, 669 ms avg latency.

---
*Generated: 2026-02-08 12:45:59*
