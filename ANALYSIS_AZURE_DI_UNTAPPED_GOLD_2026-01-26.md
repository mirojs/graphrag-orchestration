# Analysis: Azure Document Intelligence - Untapped Cross-Section Relationships

**Date:** 2026-01-26  
**Status:** Investigation Complete  
**Verdict:** 🔴 **NOT fully utilized** - significant gold mine untapped

---

## Executive Summary

Azure Document Intelligence (DI) output contains **rich cross-section relationships** through figures, footnotes, and element references that we are **completely ignoring**. This is a massive opportunity for improving graph connectivity without additional LLM calls.

---

## What Azure DI Provides (Current SDK)

### 1. AnalyzeResult Properties
```python
result.figures       # 🔴 NOT USED - Cross-section figure references
result.sections      # ✅ USED - Section hierarchy
result.paragraphs    # ✅ USED - Text content
result.tables        # ✅ USED - Table structure
result.key_value_pairs  # ✅ USED - Form fields
result.languages     # 🔴 NOT USED - Language detection
result.styles        # 🔴 NOT USED - Font/styling info
```

### 2. DocumentFigure (The Gold Mine)
```python
figure.id              # Unique identifier
figure.elements        # "/paragraphs/42", "/tables/5" → CROSS-SECTION REFERENCES!
figure.caption         # Figure caption (entity extraction source)
figure.footnotes       # References to footnotes (cross-section)
figure.bounding_regions  # Spatial location
```

### 3. DocumentSection.elements
```python
# Elements reference content by path, not by containment
section.elements = [
    "/paragraphs/0",    # Section title
    "/paragraphs/1",    # Body text
    "/tables/0",        # Referenced table (may be in another section!)
    "/sections/2",      # Child section
]
```

---

## Current Implementation Gap

### What We're Doing Now
```
[Azure DI] → sections → paragraphs/tables → chunk text → [GraphRAG entity extraction]
                ↓
           key_value_pairs → metadata
```

### What We're Missing

```
[Azure DI] → figures ─────→ elements ────→ CROSS-SECTION EDGES
              ↓                              (Figure→Table, Figure→Paragraph)
           footnotes ────→ CITATION EDGES
              ↓
           caption ──────→ FREE ENTITY EXTRACTION (no LLM needed!)
```

---

## The "Gold Mine" Opportunities

### Opportunity 1: Figure Cross-References (FREE Graph Edges)

**Scenario:** A report says "See Figure 3" in Section A, and Figure 3 references Table 5 in Section B.

**Current State:** We lose this connection - chunks are isolated.

**Proposed Fix:**
```python
def _extract_figure_relationships(self, result: AnalyzeResult) -> List[Dict]:
    """Extract cross-section edges from figures."""
    edges = []
    figures = getattr(result, "figures", None) or []
    
    for fig in figures:
        fig_id = getattr(fig, "id", None)
        elements = getattr(fig, "elements", None) or []
        
        # Build edges from figure to all referenced elements
        for el in elements:
            parsed = self._parse_di_element_ref(el)
            if parsed:
                kind, idx = parsed
                edges.append({
                    "source": f"figure_{fig_id}",
                    "target": f"{kind}_{idx}",
                    "relationship": "REFERENCES",
                    "confidence": 1.0,  # DI extracted - high confidence
                    "source_type": "document_intelligence",
                })
        
        # Extract caption as entity (free NER!)
        caption = getattr(fig, "caption", None)
        if caption:
            caption_text = getattr(caption, "content", "") or ""
            if caption_text:
                edges.append({
                    "source": f"figure_{fig_id}",
                    "target": caption_text,
                    "relationship": "HAS_CAPTION",
                    "confidence": 1.0,
                })
    
    return edges
```

**Impact:**
- No LLM calls needed
- 100% confidence (deterministic extraction)
- Cross-section graph connectivity

### Opportunity 2: Footnotes (Citation Graph)

**Scenario:** Financial report with footnotes explaining assumptions.

**Current State:** Footnotes are lost in chunk text.

**Proposed Fix:**
```python
def _extract_footnote_relationships(self, result: AnalyzeResult) -> List[Dict]:
    """Extract citation edges from footnotes."""
    edges = []
    figures = getattr(result, "figures", None) or []
    
    for fig in figures:
        fig_id = getattr(fig, "id", None)
        footnotes = getattr(fig, "footnotes", None) or []
        
        for fn in footnotes:
            fn_content = getattr(fn, "content", "") or ""
            if fn_content:
                edges.append({
                    "source": f"figure_{fig_id}",
                    "target": fn_content[:200],  # Footnote summary
                    "relationship": "HAS_FOOTNOTE",
                    "confidence": 1.0,
                })
    
    return edges
```

### Opportunity 3: Style-Based Entity Detection

**Scenario:** Bold text often indicates entity names in contracts.

**Current State:** Style information is discarded.

**Proposed Fix:**
```python
def _extract_styled_entities(self, result: AnalyzeResult) -> List[Dict]:
    """Extract potential entities from styled text (bold, italic)."""
    entities = []
    styles = getattr(result, "styles", None) or []
    content = getattr(result, "content", "") or ""
    
    for style in styles:
        is_bold = getattr(style, "font_weight", "") == "bold"
        if is_bold:
            spans = getattr(style, "spans", None) or []
            for span in spans:
                offset = getattr(span, "offset", 0)
                length = getattr(span, "length", 0)
                text = content[offset:offset+length].strip()
                if text and len(text) > 2:  # Skip single chars
                    entities.append({
                        "name": text,
                        "type": "STYLED_ENTITY",
                        "confidence": 0.7,  # Medium confidence
                        "source": "style_detection",
                    })
    
    return entities
```

---

## Implementation Plan

### Phase 1: Extract Figure Cross-References (High Impact)

| Step | Action | Effort |
|------|--------|--------|
| 1.1 | Add `_extract_figure_relationships()` method | 1 hr |
| 1.2 | Call during `_build_section_aware_documents()` | 30 min |
| 1.3 | Include edges in chunk metadata | 30 min |
| 1.4 | Pass to Neo4j during indexing | 1 hr |

### Phase 2: Footnote Citations (Medium Impact)

| Step | Action | Effort |
|------|--------|--------|
| 2.1 | Add `_extract_footnote_relationships()` method | 1 hr |
| 2.2 | Create CITES_FOOTNOTE edge type | 30 min |
| 2.3 | Integrate with entity extraction | 1 hr |

### Phase 3: Style-Based NER (Lower Priority)

| Step | Action | Effort |
|------|--------|--------|
| 3.1 | Enable `STYLE_FONT` feature in DI call | 15 min |
| 3.2 | Add `_extract_styled_entities()` method | 1 hr |
| 3.3 | Merge with LLM-extracted entities | 1 hr |

---

## Cost-Benefit Analysis

| Feature | Cost | Benefit |
|---------|------|---------|
| Figure cross-refs | $0 (already in DI response) | Cross-section graph connectivity |
| Footnote citations | $0 | Citation graph for financial/legal docs |
| Style-based NER | $0 | Reduced LLM entity extraction load |
| Enable `STYLE_FONT` | +$0.50/1K pages | Font-based entity hints |

---

## Files to Modify

1. **document_intelligence_service.py**
   - Add `_extract_figure_relationships()`
   - Add `_extract_footnote_relationships()`
   - Update `_build_section_aware_documents()` to include edges
   - Add new metadata fields: `figure_references`, `footnotes`, `cross_section_edges`

2. **indexing_pipeline.py** (or V2 equivalent)
   - Process cross-section edges from DI metadata
   - Create Neo4j relationships for figure references

3. **Neo4j Schema**
   - Add `REFERENCES` edge type (Figure → Table/Paragraph)
   - Add `CITES_FOOTNOTE` edge type
   - Add `HAS_CAPTION` edge type

---

## Example: Insurance Document

**Input PDF:**
```
Section 1: Policy Overview
  Policy Number: POL-2024-001
  See Figure 1 for premium schedule.

Section 2: Premium Details
  [Figure 1: Premium Schedule]
  | Year | Premium |
  | 2024 | $5,000  |
  | 2025 | $5,250  |
  
  Note¹: Premiums subject to annual adjustment.
```

**Current Output:**
- 2 isolated chunks (Section 1, Section 2)
- No connection between "See Figure 1" and actual Figure 1

**Proposed Output:**
```
Chunk 1 (Section 1):
  metadata: {
    "cross_section_edges": [
      {"source": "chunk_1", "target": "figure_1", "relationship": "REFERENCES_FIGURE"}
    ]
  }

Chunk 2 (Section 2):
  metadata: {
    "figure_id": "figure_1",
    "figure_caption": "Premium Schedule",
    "footnotes": ["Premiums subject to annual adjustment"]
  }

Neo4j Edges (from DI - no LLM needed):
  (Section_1)-[:REFERENCES_FIGURE]->(Figure_1)
  (Figure_1)-[:CONTAINS]->(Table_Premium_Schedule)
  (Figure_1)-[:HAS_FOOTNOTE]->(Note_1)
```

---

## Conclusion

Azure DI provides **FREE cross-section relationships** through figures and footnotes that we're completely ignoring. Implementing this would:

1. **Improve graph connectivity** without LLM calls
2. **Enable citation tracking** for financial/legal documents  
3. **Reduce entity extraction load** via style-based NER hints
4. **Cost: $0** (data is already in the response)

**Recommendation:** Implement Phase 1 (Figure cross-references) in the next sprint.
