"""
Integration helpers for section-aware chunking.

This module provides drop-in replacements and adapters for integrating
section-aware chunking into the existing lazygraphrag_pipeline.

Usage in lazygraphrag_pipeline.py:

    # Option 1: Full replacement (recommended)
    from app.hybrid_v2.indexing.section_chunking.integration import (
        create_section_aware_chunker,
        section_chunks_to_text_chunks,
    )
    
    # In LazyGraphRAGPipeline.__init__:
    self._section_chunker = create_section_aware_chunker()
    
    # Replace _chunk_di_units method:
    async def _chunk_di_units(self, di_units, doc_id) -> List[TextChunk]:
        section_chunks = await self._section_chunker.chunk_document(
            di_units, doc_id, doc_source, doc_title
        )
        return section_chunks_to_text_chunks(section_chunks)

    # Option 2: Environment variable toggle
    USE_SECTION_CHUNKING = os.getenv("USE_SECTION_CHUNKING", "1") == "1"
    
    async def _chunk_di_units(self, di_units, doc_id) -> List[TextChunk]:
        if USE_SECTION_CHUNKING:
            return await self._chunk_di_units_section_aware(di_units, doc_id)
        else:
            return await self._chunk_di_units_fixed(di_units, doc_id)  # existing
"""
import logging
import os
from typing import List, Optional, Sequence, Any

from .chunker import SectionAwareChunker, SectionChunkConfig
from .models import SectionChunk

# Import TextChunk from the existing codebase
from app.hybrid_v2.services.neo4j_store import TextChunk

logger = logging.getLogger(__name__)


def create_section_aware_chunker(
    min_tokens: int = 100,
    max_tokens: int = 1500,
    overlap_tokens: int = 50,
) -> SectionAwareChunker:
    """
    Factory function to create a configured section-aware chunker.
    
    Default settings are tuned for legal/business documents.
    Adjust max_tokens based on your embedding model's context window.
    """
    config = SectionChunkConfig(
        min_tokens=min_tokens,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        merge_tiny_sections=True,
        preserve_hierarchy=True,
        prefer_paragraph_splits=True,
        fallback_to_fixed_chunking=True,
        fallback_chunk_size=512,
        fallback_overlap=64,
    )
    return SectionAwareChunker(config)


def section_chunks_to_text_chunks(section_chunks: List[SectionChunk]) -> List[TextChunk]:
    """
    Convert SectionChunk objects to TextChunk objects for pipeline compatibility.
    
    This is the bridge between the new section-aware chunking and the existing
    pipeline which expects TextChunk objects.
    """
    text_chunks: List[TextChunk] = []
    
    for sc in section_chunks:
        # Build rich metadata from section info
        metadata = sc.to_text_chunk_dict()["metadata"]
        
        text_chunks.append(
            TextChunk(
                id=sc.id,
                text=sc.text,
                chunk_index=sc.chunk_index,
                document_id=sc.document_id,
                embedding=sc.embedding,
                tokens=sc.tokens,
                metadata=metadata,
            )
        )
    
    return text_chunks


async def chunk_di_units_section_aware(
    di_units: Sequence[Any],
    doc_id: str,
    doc_source: str = "",
    doc_title: str = "",
    chunker: Optional[SectionAwareChunker] = None,
) -> List[TextChunk]:
    """
    Drop-in replacement for _chunk_di_units in lazygraphrag_pipeline.py.
    
    Usage:
        # In lazygraphrag_pipeline.py, replace:
        chunks = await self._chunk_di_units(di_units=di_units, doc_id=doc_id)
        
        # With:
        from app.hybrid_v2.indexing.section_chunking.integration import chunk_di_units_section_aware
        chunks = await chunk_di_units_section_aware(di_units, doc_id, doc_source, doc_title)
    """
    if chunker is None:
        chunker = create_section_aware_chunker()
    
    section_chunks = await chunker.chunk_document(
        di_units=di_units,
        doc_id=doc_id,
        doc_source=doc_source,
        doc_title=doc_title,
    )
    
    return section_chunks_to_text_chunks(section_chunks)


def get_summary_chunks(text_chunks: List[TextChunk]) -> List[TextChunk]:
    """
    Filter to get only summary/introductory chunks.
    
    This is useful for coverage retrieval - instead of getting random chunks,
    get chunks marked as summary sections (Purpose, Introduction, etc.)
    
    Usage in enhanced_graph_retriever.py:
        from app.hybrid_v2.indexing.section_chunking.integration import get_summary_chunks
        
        all_chunks = await self.get_all_document_chunks(group_id)
        summary_chunks = get_summary_chunks(all_chunks)
        # Now have ONE meaningful chunk per document
    """
    summary_chunks: List[TextChunk] = []
    seen_docs: set = set()
    
    for chunk in text_chunks:
        meta = chunk.metadata or {}
        doc_id = chunk.document_id or ""
        
        # Skip if we already have a summary chunk for this doc
        if doc_id in seen_docs:
            continue
        
        # Check if this is a summary section
        is_summary = meta.get("is_summary_section", False)
        is_section_start = meta.get("is_section_start", False)
        section_title = (meta.get("section_title") or "").lower()
        
        # Accept if marked as summary, or if it's the first chunk (chunk_index=0)
        if is_summary or (is_section_start and chunk.chunk_index == 0):
            summary_chunks.append(chunk)
            seen_docs.add(doc_id)
        elif any(pattern in section_title for pattern in [
            "purpose", "summary", "introduction", "overview", "scope", "background"
        ]):
            summary_chunks.append(chunk)
            seen_docs.add(doc_id)
    
    return summary_chunks


def get_chunks_by_section_title(
    text_chunks: List[TextChunk],
    title_patterns: List[str],
    max_per_document: int = 1,
) -> List[TextChunk]:
    """
    Get chunks from sections matching title patterns.
    
    Usage:
        # Get all "Payment" sections across documents
        payment_chunks = get_chunks_by_section_title(
            chunks, 
            ["payment", "compensation", "fees"],
            max_per_document=1
        )
    """
    matching: List[TextChunk] = []
    docs_counts: dict = {}
    
    for chunk in text_chunks:
        meta = chunk.metadata or {}
        doc_id = chunk.document_id or ""
        section_title = (meta.get("section_title") or "").lower()
        section_path_key = (meta.get("section_path_key") or "").lower()
        
        # Check document limit
        if docs_counts.get(doc_id, 0) >= max_per_document:
            continue
        
        # Check pattern match
        search_text = f"{section_title} {section_path_key}"
        if any(pattern.lower() in search_text for pattern in title_patterns):
            matching.append(chunk)
            docs_counts[doc_id] = docs_counts.get(doc_id, 0) + 1
    
    return matching


# Environment variable check for feature flag
def is_section_chunking_enabled() -> bool:
    """Check if section-aware chunking is enabled via environment variable."""
    return os.getenv("USE_SECTION_CHUNKING", "0").strip().lower() in {"1", "true", "yes"}
