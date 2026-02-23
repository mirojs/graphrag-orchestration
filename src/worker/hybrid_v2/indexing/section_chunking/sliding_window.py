"""
3-Sentence Sliding Window Chunker for HippoRAG 2.

Creates TextChunks from overlapping 3-sentence windows
(target sentence + 1 before + 1 after).

Benefits over fixed-size / section-aware chunking:
1. Enhanced concept density — each chunk is a coherent thought unit
2. Improved coreference resolution — neighboring sentences provide context
3. Better DPR retrieval precision — tight semantic match per passage node
4. voyage-context-3 already provides full-document contextual embeddings

Stride=1: Each sentence appears in up to 3 different chunks (maximum overlap).
Stride=3: No overlap — each sentence in exactly 1 chunk.
"""

import hashlib
import logging
import re
from typing import List, Optional

from .models import SectionChunk

logger = logging.getLogger(__name__)

# Noise thresholds aligned with sentence_extraction_service.py
_MIN_SENTENCE_CHARS = 30
_MIN_SENTENCE_WORDS = 3


def _get_nlp():
    """Reuse the spaCy singleton from sentence_extraction_service."""
    from src.worker.services.sentence_extraction_service import _get_nlp as _ses_get_nlp
    return _ses_get_nlp()


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using spaCy, filtering noise."""
    nlp = _get_nlp()
    # Process in chunks if text exceeds spaCy max_length
    max_len = nlp.max_length
    sentences: List[str] = []
    for start in range(0, len(text), max_len):
        chunk = text[start:start + max_len]
        doc = nlp(chunk)
        for sent in doc.sents:
            s = sent.text.strip()
            if not s:
                continue
            # Noise filter: skip very short or word-poor sentences
            if len(s) < _MIN_SENTENCE_CHARS:
                continue
            if len(s.split()) < _MIN_SENTENCE_WORDS:
                continue
            sentences.append(s)
    return sentences


def chunk_sliding_window_3sentence(
    full_text: str,
    doc_id: str,
    doc_source: str = "",
    doc_title: str = "",
    doc_language: Optional[str] = None,
    window_size: int = 3,
    stride: int = 1,
) -> List[SectionChunk]:
    """
    Create TextChunks from 3-sentence sliding windows.

    Each chunk contains ``window_size`` contiguous sentences, advancing by
    ``stride`` sentences between windows.  Default: window=3, stride=1
    (maximum overlap — each sentence appears in up to 3 chunks).

    Args:
        full_text: Complete document text.
        doc_id: Document identifier.
        doc_source: Document URL / path.
        doc_title: Document title.
        doc_language: ISO 639-1 / BCP 47 locale code.
        window_size: Number of sentences per chunk (default 3).
        stride: Step between windows (default 1).

    Returns:
        List of SectionChunk objects ready for the indexing pipeline.
    """
    if not full_text or not full_text.strip():
        return []

    sentences = _split_sentences(full_text)
    if not sentences:
        logger.warning(
            "sliding_window_no_sentences",
            extra={"doc_id": doc_id, "text_len": len(full_text)},
        )
        return []

    chunks: List[SectionChunk] = []

    for i in range(0, len(sentences), stride):
        window = sentences[i : i + window_size]
        if not window:
            break

        text = " ".join(window)
        chunk_idx = len(chunks)

        # Stable chunk ID based on doc_id and window position
        chunk_id = f"{doc_id}_sw3_{chunk_idx}"

        chunks.append(
            SectionChunk(
                id=chunk_id,
                text=text,
                chunk_index=chunk_idx,
                document_id=doc_id,
                section_id=f"{doc_id}_sliding_window",
                section_title="(3-sentence window)",
                section_level=0,
                section_path=[],
                section_chunk_index=chunk_idx,
                section_chunk_total=-1,  # updated below
                tokens=len(text.split()),
                is_section_start=(chunk_idx == 0),
                is_summary_section=(chunk_idx == 0),
                language=doc_language,
                metadata={
                    "source": doc_source,
                    "title": doc_title,
                    "chunk_strategy": "sliding_window_3sentence",
                    "window_start_sentence": i,
                    "window_size": len(window),
                    "key_value_pairs": [],
                    "kvp_count": 0,
                },
            )
        )

        # If window was shorter than window_size we've reached the end
        if len(window) < window_size:
            break

    # Update totals
    total = len(chunks)
    for c in chunks:
        c.section_chunk_total = total

    logger.info(
        "sliding_window_chunking_complete",
        extra={
            "doc_id": doc_id,
            "sentences": len(sentences),
            "chunks_created": total,
            "window_size": window_size,
            "stride": stride,
        },
    )

    return chunks
