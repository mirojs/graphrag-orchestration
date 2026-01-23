# Multi-Language Support Plan for GraphRAG API

**Date:** January 23, 2026

## Overview

Enable language-aware document processing and response generation by leveraging Azure Document Intelligence's free language detection, then propagating language metadata through the entire pipeline.

## Background

### Current State Issues

| Component | Issue | Impact |
|-----------|-------|--------|
| Entity Canonicalization | `_canonical_entity_key()` strips all non-ASCII characters | CJK entities become empty strings and are lost |
| Token Counting | Whitespace-based split doesn't work for CJK | Chinese/Japanese chunks severely undercounted |
| Sentence Splitting | Only detects `.!?`, misses `。！？` | Poor chunking quality for CJK documents |
| Synthesis Prompts | English-only instructions | Responses always in English regardless of content |

### Azure DI Language Detection Add-On

Azure Document Intelligence provides free, accurate language detection (300+ languages) with zero additional latency. It returns per-span language info:

```json
{
  "languages": [
    {"locale": "zh-Hans", "confidence": 0.95, "spans": [{"offset": 0, "length": 120}]},
    {"locale": "en", "confidence": 0.98, "spans": [{"offset": 121, "length": 45}]}
  ]
}
```

## Implementation Steps

### Step 1: Enable Azure DI Language Detection

**File:** `app/services/document_intelligence_service.py`

- Add `DocumentAnalysisFeature.LANGUAGES` to features list (line 750)
- Extract `result.languages` from Azure DI response
- Compute dominant language per page/section
- Propagate to `Document` metadata dict

**Deliverable:** Language metadata flows through indexing pipeline

---

### Step 2: Store Document + Chunk Language

**Files:** 
- `app/hybrid/services/neo4j_store.py`
- `app/models/document.py`

- Add `language` property to `Document` model
- Add `language` property to `TextChunk` nodes in Neo4j schema
- Store document-level dominant language
- Store chunk-level language for mixed-language documents

**Deliverable:** Language persisted in graph database

---

### Step 3: Create Language Utility Module

**File:** `app/hybrid/utils/language.py` (new)

Create helper functions:

```python
def is_cjk(locale: str) -> bool:
    """Check if locale is CJK (Chinese, Japanese, Korean)."""
    return locale.startswith(('zh', 'ja', 'ko'))

def normalize_text(text: str, locale: str) -> str:
    """Apply language-specific text normalization."""
    # NFKC normalization
    # Full-width to half-width conversion for CJK
    # Preserve entity integrity

def get_sentence_delimiters(locale: str) -> list[str]:
    """Return sentence boundary markers for language."""
    if is_cjk(locale):
        return ['.', '!', '?', '。', '！', '？', '．']
    return ['.', '!', '?']
```

**Deliverable:** Reusable language utilities

---

### Step 4: Fix Entity Canonicalization

**File:** `app/hybrid/indexing/lazygraphrag_pipeline.py` (line 1248)

Update `_canonical_entity_key()` to:
- Check chunk language before applying regex
- Preserve non-ASCII characters for CJK languages
- Apply `normalize_text()` for consistent matching
- Use language-appropriate stopword filtering

**Before:**
```python
s = re.sub(r"[^a-z0-9_&\s]", " ", s)  # Strips ALL non-ASCII
```

**After:**
```python
if not is_cjk(language):
    s = re.sub(r"[^a-z0-9_&\s]", " ", s)
else:
    s = normalize_text(s, language)
```

**Deliverable:** CJK entities preserved in graph

---

### Step 5: Implement Language-Specific Chunking

**File:** `app/hybrid/indexing/lazygraphrag_pipeline.py`

- Detect chunk language from metadata
- Use character-based chunking for CJK (e.g., `RecursiveCharacterTextSplitter`)
- Use sentence-based chunking for Latin scripts (current `SentenceSplitter`)
- Apply `get_sentence_delimiters(locale)` for boundary detection

**Deliverable:** Properly sized chunks for all languages

---

### Step 6: Add Response Language Parameter

**File:** `app/routers/hybrid.py`

Update request model:

```python
class HybridQueryRequest(BaseModel):
    query: str
    response_type: Literal[...]
    language: Optional[str] = None  # ISO 639-1 or full name (e.g., "Chinese")
    force_route: Optional[RouteEnum] = None
    relevance_budget: Optional[float] = None
```

**Default behavior:** If `language=None`, use evidence's dominant language

**Deliverable:** User can specify response language

---

### Step 7: Update Synthesis Prompts

**File:** `app/hybrid/pipeline/synthesis.py`

Modify `_build_synthesis_prompt()` to:
- Accept `language` parameter
- Append instruction: `"Respond in {language}"`
- Add fallback instruction: `"If evidence is in another language, translate key information before answering"`

**Example addition:**
```python
if language:
    prompt += f"\n\nIMPORTANT: Generate your response in {language}."
    prompt += "\nIf the evidence is in another language, translate relevant excerpts before answering."
```

**Deliverable:** LLM generates responses in requested language

---

### Step 8: Add Language to Response Metadata

**File:** `app/routers/hybrid.py`

Update response models:

```python
class Citation(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    document_title: str
    score: float
    text_preview: str
    language: Optional[str] = None  # NEW

class HybridQueryResponse(BaseModel):
    answer: str
    route_used: str
    citations: List[Citation]
    metadata: Dict[str, Any]
    # NEW fields:
    evidence_language: Optional[str] = None  # Dominant language of evidence
    language_mismatch: bool = False  # True if query lang ≠ evidence lang
```

**Deliverable:** Clients can display citations in correct language context

---

## Further Considerations

### 1. Mixed-Language Chunks

**Question:** How to handle documents with multiple languages in a single chunk?

**Options:**
- **A (Recommended):** Use dominant language per chunk (simplest)
- **B:** Split chunks at language boundaries (complex, better quality)

**Decision:** Start with Option A for V1

---

### 2. Cross-Lingual Embedding Boost

**Concept:** Prepend `[{Language}]` tag to chunk text before embedding to improve cross-lingual retrieval accuracy.

**Example:** `"[Chinese] 合同编号: CONTRACT-2024-001"`

**Status:** Worth testing; defer to V2 (requires index migration)

---

### 3. Re-indexing Strategy

**Problem:** Existing CJK documents have corrupted entity graphs (entities lost to canonicalization bug)

**Options:**
- **A:** Flag affected docs via language heuristic, re-index on-demand
- **B:** Full re-index of all documents
- **C:** Lazy re-index triggered on next query

**Recommendation:** Option A with batch re-indexing job

---

### 4. Native Entity Extraction Prompts

**Concept:** Dynamically switch entity extraction prompts to document language

**Example:** For German document, use:
```
"Extrahieren Sie Entitäten wie Firmen, Orte, Personen..."
```

**Status:** Adds LLM cost and complexity; defer to V2

---

### 5. Language Detection Fallback

**Scenario:** Azure DI unavailable or not used for certain file types

**Options:**
- Use lightweight library (`langdetect`, `fasttext`) as backup
- Default to English if detection fails

**Recommendation:** Add fallback for robustness

---

## Success Metrics

### Data Quality
- CJK entity count > 0 after indexing (currently 0)
- Chunk token count accuracy within 10% for CJK documents
- Entity canonicalization preserves 95%+ of non-ASCII entities

### Response Quality
- Responses match requested language 100% of the time
- Cross-lingual queries return relevant results (e.g., English query → Chinese docs)
- Mixed-language citations display correctly in client

### Performance
- Zero additional latency (language detection is free)
- No impact on English-only workflows

---

## Implementation Timeline

| Phase | Steps | Estimated Effort |
|-------|-------|-----------------|
| Phase 1: Infrastructure | Steps 1-3 | 1-2 days |
| Phase 2: Indexing Fixes | Steps 4-5 | 2-3 days |
| Phase 3: Response Language | Steps 6-7 | 1 day |
| Phase 4: Metadata & Testing | Step 8 | 1 day |
| **Total** | | **5-7 days** |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing indexes | Implement backward compatibility; add migration script |
| Language detection accuracy | Use Azure DI confidence scores; fallback to heuristics |
| LLM hallucination in non-English | Add confidence scoring; language mismatch warnings |
| Performance degradation | Profile CJK text processing; cache normalized entities |

---

## Appendix: Code Locations Reference

| Component | File | Lines |
|-----------|------|-------|
| Azure DI Client | `app/services/document_intelligence_service.py` | 72-78, 746-751 |
| Entity Canonicalization | `app/hybrid/indexing/lazygraphrag_pipeline.py` | 1248-1254 |
| Token Counting | `app/services/document_intelligence_service.py` | 888-895 |
| Synthesis Prompts | `app/hybrid/pipeline/synthesis.py` | 480, 750 |
| Request Schema | `app/routers/hybrid.py` | - |
| Neo4j Storage | `app/hybrid/services/neo4j_store.py` | 1393 |
