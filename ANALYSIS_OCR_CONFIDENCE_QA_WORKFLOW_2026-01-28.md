# Analysis: Azure DI OCR Confidence & Pre-Indexing QA Workflow

**Date:** January 28, 2026  
**Context:** Route 4 benchmark achieved 98.2% (56/57) on GDS V2 unified index  
**Topic:** Should Azure Document Intelligence confidence scores be stored in the graph?

---

## 1. Background

During Route 4 benchmark analysis, Q-D8 (entity document counting) was initially suspected to be an Azure DI confidence issue. Investigation revealed the actual cause was a **ground truth error** - "Contoso Ltd." correctly appeared in 4 documents (including WARRANTY as Buyer/Owner), not 3 as originally documented.

This prompted the question: **Should we include Azure DI confidence scores in the graph?**

---

## 2. Azure DI Confidence Score Availability

### What Azure DI Provides

| Element | Has Confidence? | Location | Notes |
|---------|----------------|----------|-------|
| **Words** | ✅ Yes | `DocumentWord.confidence` | OCR confidence per word (0.0-1.0) |
| **Lines** | ❌ No | N/A | N/A |
| **Paragraphs** | ❌ No | N/A | Structural element |
| **Tables** | ❌ No | N/A | Structural element |
| **Sections** | ❌ No | N/A | Structural element |
| **Barcodes** | ✅ Yes | `DocumentBarcode.confidence` | Detection confidence |
| **Key-Value Pairs** | ✅ Yes | `DocumentKeyValuePair.confidence` | Extraction confidence |
| **Selection Marks** | ✅ Yes | `DocumentSelectionMark.confidence` | Checkbox detection |

### Currently Stored in Graph

| Node Type | Confidence Property | Status |
|-----------|-------------------|--------|
| `Barcode` | `b.confidence` | ✅ Stored |
| `KeyValuePair` | `k.confidence` | ✅ Stored |
| `Entity` | N/A | ❌ Not applicable (LLM-extracted) |
| `TextChunk` | N/A | ❌ Not stored |

### Key Insight

**Entities are NOT extracted by Azure DI** - they come from LLM extraction (LlamaIndex PropertyGraphIndex with OpenAI). Azure DI provides:
- Layout extraction (paragraphs, sections, tables)
- Barcodes/QR codes
- Key-value pairs (form fields)
- Selection marks (checkboxes)

OCR confidence is available at the **word level only**, which makes sense because OCR confidence answers: "How sure am I that this word is 'Contract'?"

---

## 3. Two Approaches to Using OCR Confidence

### Option A: Query-Time Filtering

```
Query → Retrieve chunks → Filter by confidence → Return results
```

| Pros | Cons |
|------|------|
| Fast onboarding | Bad data still in graph |
| No human bottleneck | May exclude relevant chunks |
| Dynamic thresholds | Hard to explain to auditors |
| | Confidence not tied to correctness |

### Option B: Pre-Indexing QA (Recommended)

```
Document → Azure DI → Confidence Check → [High] → Index
                                       → [Low]  → Human Review Queue
```

| Pros | Cons |
|------|------|
| **Prevents bad data from entering** | Adds latency to onboarding |
| Human fixes before indexing | Requires review workflow |
| Clean graph = reliable answers | May delay document availability |
| Audit trail for compliance | |
| **Insurance regulators love this** | |

---

## 4. Recommendation: Pre-Indexing QA

For insurance and high-stakes enterprise use cases, **data quality at ingestion is critical**:

| Insurance Reality | Why Pre-Indexing QA Wins |
|-------------------|-------------------------|
| Claims decisions | Can't risk wrong policy terms |
| Regulatory audits | Need to prove data quality |
| Legal liability | Bad OCR → bad advice → lawsuit |
| Document types | Scanned forms, faxes, handwritten |

### Why Not Query-Time?

- Query-time filtering leaves bad data in the graph
- Confidence scores don't guarantee correctness
- Harder to audit and explain decisions
- May filter out relevant (correct) low-confidence chunks

---

## 5. Pre-Indexing QA Workflow Design

### 5.1 Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PRE-INDEXING QA PIPELINE                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐ │
│   │   Document   │───▶│   Azure DI   │───▶│  Confidence Aggregation  │ │
│   │    Input     │    │  Processing  │    │  (per chunk/page/doc)    │ │
│   └──────────────┘    └──────────────┘    └────────────┬─────────────┘ │
│                                                        │               │
│                                                        ▼               │
│                                           ┌────────────────────────┐   │
│                                           │    QA Decision Gate    │   │
│                                           │  min_confidence >= T?  │   │
│                                           └───────────┬────────────┘   │
│                                                       │                │
│                              ┌─────────────────────────┼────────────────┐
│                              │                         │                │
│                              ▼                         ▼                │
│                   ┌──────────────────┐     ┌──────────────────────┐    │
│                   │   AUTO-APPROVE   │     │    HUMAN REVIEW      │    │
│                   │  (High Quality)  │     │      QUEUE           │    │
│                   └────────┬─────────┘     └──────────┬───────────┘    │
│                            │                          │                │
│                            │                          ▼                │
│                            │               ┌──────────────────────┐    │
│                            │               │   Human Reviewer     │    │
│                            │               │  - Correct OCR       │    │
│                            │               │  - Approve/Reject    │    │
│                            │               │  - Add notes         │    │
│                            │               └──────────┬───────────┘    │
│                            │                          │                │
│                            ▼                          ▼                │
│                   ┌──────────────────────────────────────────────────┐ │
│                   │              GRAPH INDEXING                      │ │
│                   │  (Neo4j with ocr_reviewed flag)                  │ │
│                   └──────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Confidence Thresholds

| Threshold | Range | Action | Rationale |
|-----------|-------|--------|-----------|
| **HIGH** | ≥ 0.90 | Auto-approve | Clean digital documents |
| **MEDIUM** | 0.75 - 0.90 | Auto-approve with flag | Minor issues, acceptable |
| **LOW** | < 0.75 | Human review required | Potential OCR errors |

> **Note:** Thresholds should be tuned based on document corpus. Digital PDFs typically have 0.99+ confidence.

### 5.3 Confidence Aggregation Methods

For chunk-level quality assessment:

```python
def compute_chunk_confidence(words: List[DocumentWord]) -> Dict[str, float]:
    """Aggregate word-level confidence to chunk level."""
    confidences = [w.confidence for w in words if w.confidence is not None]
    
    if not confidences:
        return {"min": 1.0, "avg": 1.0, "p10": 1.0}
    
    return {
        "min": min(confidences),           # Worst word
        "avg": sum(confidences) / len(confidences),  # Average
        "p10": sorted(confidences)[len(confidences) // 10],  # 10th percentile
    }
```

**Recommendation:** Use `min_confidence` for QA gating (catches the worst word in chunk).

### 5.4 Data Model Additions

#### Document Node (metadata)

```cypher
(:Document {
    id: "doc-123",
    group_id: "tenant-abc",
    title: "Policy_2026.pdf",
    // ... existing properties ...
    
    // NEW: OCR Quality Metadata
    ocr_min_confidence: 0.87,      // Minimum word confidence in doc
    ocr_avg_confidence: 0.96,      // Average word confidence
    ocr_reviewed: true,            // Human reviewed flag
    ocr_review_date: datetime(),   // When reviewed
    ocr_reviewer: "john.doe@company.com"  // Who reviewed
})
```

#### TextChunk Node (optional, for granular tracking)

```cypher
(:TextChunk {
    id: "chunk-456",
    // ... existing properties ...
    
    // OPTIONAL: Chunk-level confidence
    ocr_min_confidence: 0.85,
    ocr_avg_confidence: 0.94
})
```

### 5.5 Review Queue API

```
POST /api/v1/qa/documents/{doc_id}/review
{
    "action": "approve" | "reject" | "correct",
    "corrections": [
        {"chunk_id": "chunk-123", "original": "Contrsct", "corrected": "Contract"}
    ],
    "notes": "Scanned document with minor OCR issues on page 3"
}

GET /api/v1/qa/pending
{
    "documents": [
        {
            "id": "doc-789",
            "title": "Claim_Form_Scan.pdf",
            "min_confidence": 0.72,
            "low_confidence_chunks": 3,
            "submitted_at": "2026-01-28T10:30:00Z"
        }
    ]
}
```

### 5.6 Workflow States

```
┌──────────┐    ┌───────────┐    ┌──────────────┐    ┌─────────┐
│ UPLOADED │───▶│ ANALYZING │───▶│ QA_PENDING   │───▶│ INDEXED │
└──────────┘    └───────────┘    └──────────────┘    └─────────┘
                                        │
                                        ▼
                                 ┌──────────────┐
                                 │  REJECTED    │
                                 └──────────────┘
```

---

## 6. What NOT to Store

| Don't Store | Reason |
|-------------|--------|
| Word-level confidence array | Huge data volume, rarely queried |
| Line-level confidence | Not provided by Azure DI |
| Entity confidence | Entities come from LLM, not Azure DI |

---

## 7. Implementation Priority

| Phase | Component | Priority |
|-------|-----------|----------|
| 1 | Compute doc-level `ocr_min_confidence` during indexing | High |
| 2 | Add `ocr_reviewed` flag to Document nodes | High |
| 3 | Build review queue API | Medium |
| 4 | Build reviewer UI | Low (can use Cosmos DB / external tool) |
| 5 | Add chunk-level confidence (optional) | Low |

---

## 8. When This Matters vs. When It Doesn't

### High Value (Implement QA Workflow)

| Document Type | Typical Confidence | QA Need |
|---------------|-------------------|---------|
| Scanned claims forms | 0.70-0.90 | **Critical** |
| Handwritten notes | 0.50-0.80 | **Critical** |
| Faxed documents | 0.75-0.92 | **High** |
| Old photocopies | 0.65-0.85 | **High** |
| Mobile phone photos | 0.70-0.95 | **Medium** |

### Low Value (Skip for Now)

| Document Type | Typical Confidence | QA Need |
|---------------|-------------------|---------|
| Digital PDFs | 0.98-1.00 | **Low** |
| Word exports | 0.99-1.00 | **Low** |
| Modern scans (300+ DPI) | 0.95-0.99 | **Low** |

---

## 9. Conclusion

**Decision:** Implement pre-indexing QA workflow with:
1. Document-level confidence aggregation (min/avg)
2. Human review queue for low-confidence documents
3. `ocr_reviewed` audit flag on Document nodes
4. Query-time filtering NOT recommended

**Rationale:** For insurance use cases, preventing bad data from entering the graph is more valuable than filtering at query time. This provides:
- Clean, reliable knowledge graph
- Audit trail for compliance
- Human-in-the-loop quality control
- Defensible data lineage

---

## 10. References

- [Azure Document Intelligence Word Confidence](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept-read)
- Route 4 Benchmark Results: `bench_route4_drift_multi_hop_20260128T165001Z.txt`
- Q-D8 Ground Truth Fix: `QUESTION_BANK_5PDFS_2025-12-24.md`
