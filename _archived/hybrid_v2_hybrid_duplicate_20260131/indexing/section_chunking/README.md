# Section-Aware Chunking Module (v2)

A drop-in replacement for fixed-size chunking that respects Azure Document Intelligence section boundaries.

## Quick Start

```bash
# 1. Run standalone test
cd graphrag-orchestration
python -m app.hybrid.indexing.section_chunking.test_chunker

# 2. Test with mock data
python scripts/test_section_chunking_real.py --mock

# 3. Test with real Azure DI (requires credentials)
python scripts/test_section_chunking_real.py --url <blob-url>

# 4. See integration plan
cat app/hybrid/indexing/section_chunking/INTEGRATION_PLAN.md

# 5. See exact code changes needed
cat app/hybrid/indexing/section_chunking/CODE_CHANGES.py
```

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Module exports |
| `models.py` | `SectionNode`, `SectionChunk` dataclasses |
| `chunker.py` | `SectionAwareChunker` - main chunking logic |
| `integration.py` | Helpers to integrate with existing pipeline |
| `test_chunker.py` | Unit tests |
| `INTEGRATION_PLAN.md` | **Step-by-step test & integration guide** |
| `CODE_CHANGES.py` | **Exact code snippets to add/modify** |
| `README.md` | This file |

## Problem

Fixed-size chunking (512 tokens) creates semantic misalignment:
- Chunks can cut mid-sentence or mid-thought
- One chunk may contain parts of multiple sections
- Embeddings represent mixed, incoherent content
- Coverage retrieval gets arbitrary chunks, not meaningful summaries

## Solution

Section-aware chunking uses Azure DI's section extraction to create semantically coherent chunks:
- Each chunk represents a complete section (or part of one if too large)
- Embeddings capture complete thoughts
- Coverage retrieval can target "Purpose" or "Introduction" sections
- Retrieval precision improves (section boundaries = semantic boundaries)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Azure Document Intelligence                                      │
│   - Extracts sections (H1, H2, H3...)                           │
│   - Provides paragraph boundaries                               │
│   - Returns hierarchical structure                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ SectionAwareChunker                                              │
│                                                                  │
│   1. Extract sections from DI metadata                          │
│   2. Merge tiny sections (< 100 tokens) with siblings           │
│   3. Split large sections (> 1500 tokens) at paragraph breaks   │
│   4. Mark summary sections (Purpose, Introduction, etc.)        │
│   5. Preserve parent-child hierarchy in metadata                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ SectionChunk                                                     │
│   - id, text, tokens                                            │
│   - section_id, section_title, section_level                    │
│   - section_path (e.g., ["Terms", "Payment"])                   │
│   - is_summary_section (True for Purpose/Introduction)          │
│   - is_section_start (True for first chunk of section)          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Neo4j :TextChunk                                                 │
│   - Compatible with existing pipeline                           │
│   - Rich metadata enables section-aware retrieval               │
└─────────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Module exports |
| `models.py` | `SectionNode`, `SectionChunk` dataclasses |
| `chunker.py` | `SectionAwareChunker` - main chunking logic |
| `integration.py` | Helpers to integrate with existing pipeline |
| `test_chunker.py` | Unit tests |

## Usage

### Option 1: Full Replacement

```python
# In lazygraphrag_pipeline.py

from app.hybrid.indexing.section_chunking import SectionAwareChunker

class LazyGraphRAGPipeline:
    def __init__(self, ...):
        ...
        self._section_chunker = SectionAwareChunker()
    
    async def _chunk_di_units(self, di_units, doc_id) -> List[TextChunk]:
        from app.hybrid.indexing.section_chunking.integration import (
            chunk_di_units_section_aware
        )
        return await chunk_di_units_section_aware(
            di_units, doc_id, doc_source, doc_title
        )
```

### Option 2: Feature Flag

```python
import os

USE_SECTION_CHUNKING = os.getenv("USE_SECTION_CHUNKING", "0") == "1"

async def _chunk_di_units(self, di_units, doc_id) -> List[TextChunk]:
    if USE_SECTION_CHUNKING:
        from app.hybrid.indexing.section_chunking.integration import (
            chunk_di_units_section_aware
        )
        return await chunk_di_units_section_aware(...)
    else:
        return await self._chunk_di_units_fixed(...)  # existing
```

### Coverage Retrieval Integration

```python
# In enhanced_graph_retriever.py

from app.hybrid.indexing.section_chunking.integration import (
    get_summary_chunks,
    get_chunks_by_section_title,
)

async def get_coverage_chunks_v2(self, group_id: str) -> List[SourceChunk]:
    """Get ONE meaningful chunk per document using section metadata."""
    
    # Get all chunks
    all_chunks = await self.get_all_chunks(group_id)
    
    # Filter to summary sections (Purpose, Introduction, etc.)
    summary_chunks = get_summary_chunks(all_chunks)
    
    # One per document, semantically meaningful
    return summary_chunks
```

## Configuration

```python
from app.hybrid.indexing.section_chunking import SectionChunkConfig

config = SectionChunkConfig(
    min_tokens=100,        # Merge sections below this
    max_tokens=1500,       # Split sections above this
    overlap_tokens=50,     # Overlap between split chunks
    merge_tiny_sections=True,
    preserve_hierarchy=True,
    prefer_paragraph_splits=True,
    fallback_to_fixed_chunking=True,  # Use fixed chunking if no sections
)
```

## Testing

```bash
cd graphrag-orchestration
python -m app.hybrid.indexing.section_chunking.test_chunker
```

## Migration Notes

1. **Re-ingestion required**: Existing documents need re-processing to get section-aware chunks
2. **Backward compatible**: Old :TextChunk nodes still work; new ones have richer metadata
3. **Fallback**: Documents without DI sections automatically use fixed chunking
4. **Index updates**: May need to update fulltext/vector indexes after re-ingestion

## Summary Section Patterns

The following section titles are automatically marked as `is_summary_section=True`:

- Purpose
- Summary / Executive Summary
- Introduction
- Overview
- Scope
- Background
- Abstract
- Objectives
- Recitals (legal)
- Whereas (legal preamble)

## Prior Art

This implementation incorporates learnings from:

1. **LlamaIndex HierarchicalNodeParser**: Parent-child relationships for context expansion
2. **LangChain MarkdownHeaderTextSplitter**: Header metadata preservation
3. **Unstructured.io chunk_by_title**: Element-based boundaries with size constraints
4. **Greg Kamradt Semantic Chunking**: Natural break detection (via DI sections)
5. **RAPTOR**: Hierarchical summarization concept (section = natural summary unit)
