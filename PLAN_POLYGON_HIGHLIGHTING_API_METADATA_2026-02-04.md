# Plan: Polygon Highlighting + API Metadata

**Date:** 2026-02-04  
**Status:** Approved for Implementation

## TL;DR

Enhance the GraphRAG pipeline to support pixel-accurate sentence highlighting in the frontend by extracting word-level geometry from Azure Document Intelligence, synthesizing multi-polygon highlights for sentences, and exposing confidence scores plus token/timing telemetry via the API. Full reindex required.

---

## Steps

### 1. Extract Word Geometry and Page Attributes
**File:** `src/worker/services/document_intelligence_service.py`

- Capture `words` with `polygon`, `confidence`, `page_number` from Azure DI result.
- Extract page `width`, `height`, and `rotation` from `pages[]`.
- Normalize all coordinates to `[0, 1]` (percentage of page dimensions).
- Build an interval tree (offset → word list) for efficient sentence-to-polygon mapping.

### 2. Synthesize Sentence Geometry
**File:** `src/worker/services/document_intelligence_service.py`

- For each sentence span, find overlapping words via the interval tree.
- Group words by text line to create **multi-polygon** highlights (handles line-wrapping).
- Compute sentence `confidence` as length-weighted mean of word confidences.

### 3. Persist Geometry for Viewer Use Only
**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

- Store per-sentence: `polygons` (list of quads), `page`, `confidence`.
- Store per-document: `page_dimensions` (list of `{width, height, rotation}`).
- Keep extraction metadata minimal (no full polygons in LLM context).

### 4. Extend API Response Contract
**File:** `src/worker/hybrid_v2/pipeline/synthesis.py`

Add to each citation's sentence:
- `polygons`: `[[x1,y1,x2,y2,x3,y3,x4,y4], ...]` (normalized, multi-polygon)
- `page`: `int`
- `confidence`: `float` (0.0–1.0)

Add top-level response fields:
- `usage`: `{ prompt_tokens, completion_tokens, total_tokens, model }`
- `timing`: `{ retrieval_ms, synthesis_ms, total_ms }`
- `page_dimensions`: `[{ width, height, rotation }, ...]` per document

### 5. Frontend Overlay + Lazy Loading
**File:** `frontend/src/components/AnalysisPanel.tsx`

- Replace iframe with a viewer component using `pdfjs-dist`.
- Draw polygon overlays (SVG/Canvas) on citation click.
- Lazy-load pages on demand to minimize memory.
- Show confidence warning badge for sentences below threshold (e.g., < 80%).

### 6. Dashboard-Ready Telemetry

- Pass `usage` and `timing` through the API unchanged.
- Frontend stores for dashboard display; no inline display in analysis panel until UI is designed.

---

## Geometry Contract

| Field | Type | Description |
|-------|------|-------------|
| `polygons` | `float[][]` | List of quads, each `[x1,y1,...,x4,y4]`, normalized to `[0,1]` |
| `page` | `int` | 1-indexed page number |
| `confidence` | `float` | Weighted average of word OCR confidences |
| `page_dimensions` | `{width, height, rotation}[]` | Per-page size and rotation (degrees) |

**Coordinate System:**
- Origin: top-left
- Units: normalized (0.0 = left/top, 1.0 = right/bottom)
- Rotation: degrees clockwise (0, 90, 180, 270)

---

## API Response Schema

```json
{
  "answer": "...",
  "citations": [
    {
      "document_id": "doc-123",
      "document_name": "report.pdf",
      "sentences": [
        {
          "text": "The total revenue was $1.2M.",
          "offset": 1520,
          "length": 28,
          "page": 3,
          "confidence": 0.94,
          "polygons": [
            [0.12, 0.45, 0.88, 0.45, 0.88, 0.48, 0.12, 0.48]
          ]
        }
      ],
      "page_dimensions": [
        {"width": 612, "height": 792, "rotation": 0}
      ]
    }
  ],
  "usage": {
    "prompt_tokens": 3200,
    "completion_tokens": 450,
    "total_tokens": 3650,
    "model": "gpt-4o"
  },
  "timing": {
    "retrieval_ms": 320,
    "synthesis_ms": 1850,
    "total_ms": 2170
  }
}
```

---

## Further Considerations

1. **Low-Confidence UX:** Show warning badge for sentences with `confidence < 0.80`.
2. **Storage Strategy:** Keep full polygons only for viewer; minimal metadata for LLM context.
3. **Token Display:** Send raw tokens + timings; dashboard decides display format (tokens vs. cost).
4. **Page Rendering:** Lazy-load pages on citation click to minimize memory on large PDFs.

---

## Prerequisites

- Full reindex required (wipe existing graph).
- No backward compatibility with old documents.
