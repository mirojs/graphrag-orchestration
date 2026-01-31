# Section-Aware Chunking Module (v2)
#
# This module provides an alternative chunking strategy that respects
# Azure Document Intelligence section boundaries instead of fixed token windows.
#
# Key benefits:
# - Embeddings represent complete semantic units (sections)
# - Natural alignment with document structure (H1, H2, etc.)
# - Better coverage retrieval (one section per document makes sense)
# - Improved retrieval precision (no orphaned context)
#
# Usage:
#   from src.worker.hybrid.indexing.section_chunking import SectionAwareChunker
#   chunker = SectionAwareChunker(config)
#   chunks = await chunker.chunk_document(di_result, doc_id)
#
# To replace existing chunking in lazygraphrag_pipeline.py:
#   Replace _chunk_di_units() with SectionAwareChunker.chunk_document()

from .chunker import SectionAwareChunker, SectionChunkConfig
from .models import SectionChunk, SectionNode

__all__ = [
    "SectionAwareChunker",
    "SectionChunkConfig",
    "SectionChunk",
    "SectionNode",
]
