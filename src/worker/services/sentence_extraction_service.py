"""Sentence extraction service for skeleton enrichment (Strategy A).

Extracts sentence-level nodes from TextChunks using:
- spaCy (body text) — handles abbreviation periods correctly
- DI table metadata (linearized rows) — structured data
- DI figure captions — from metadata

Content taxonomy (from ARCHITECTURE_HYBRID_SKELETON_2026-02-11.md):
  EMBED as Sentence nodes:
    - Body text → spaCy sentence splitting
    - Table rows → linearized from DI metadata (source="table_row")
    - Figure captions → from DI metadata (source="figure_caption")
  NOT embedded (metadata only):
    - KVPs, titles, headers/footers, barcodes, selection marks, signatures

Benchmark results (Strategy A):
  - F1: 0.082 → 0.319 (+289%)
  - Containment: 0.462 → 0.627 (+36%)
  - 8 wins, 0 real losses, 1 tie (1 "loss" was metric artifact)
"""

import re
from typing import Any, Dict, List, Optional

import structlog

from src.core.config import settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# spaCy initialization (lazy singleton)
# ---------------------------------------------------------------------------
_nlp = None


def _get_nlp():
    """Lazy-load spaCy model. Already a transitive dep via graphrag==2.7.0."""
    global _nlp
    if _nlp is None:
        import spacy
        try:
            _nlp = spacy.load("en_core_web_sm")
            _nlp.max_length = 50_000
            logger.info("spacy_loaded", model="en_core_web_sm")
        except OSError:
            logger.warning("spacy_model_not_found, downloading en_core_web_sm")
            import subprocess
            import sys
            subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                check=True,
            )
            _nlp = spacy.load("en_core_web_sm")
            _nlp.max_length = 50_000
    return _nlp


# ---------------------------------------------------------------------------
# DI paragraph roles to skip (not embeddable content)
# ---------------------------------------------------------------------------
SKIP_ROLES = {
    "pageHeader", "pageFooter", "pageNumber",
    "title", "sectionHeading",
    "signature",  # Detected by DI but not semantic content
}

# ---------------------------------------------------------------------------
# Noise detection patterns
# ---------------------------------------------------------------------------
KVP_PATTERN_RE = re.compile(
    r"^(name|date|address|phone|email|signature|title|page|total|amount|"
    r"number|id|ref|no\.?|signed|owner|agent|customer)\s*[:_\-#]?\s*$",
    re.IGNORECASE,
)
ALL_CAPS_RE = re.compile(r"^[A-Z\s\d.,!?:;\-()]+$")
FORM_LABEL_RE = re.compile(
    r"^[A-Z][^.!?]*:\s*[A-Z][a-z]",
)


def _is_noise_sentence(
    text: str,
    min_chars: int = 0,
    min_words: int = 0,
) -> bool:
    """Filter out noise: short fragments, labels, numeric-only content."""
    min_chars = min_chars or settings.SKELETON_MIN_SENTENCE_CHARS
    min_words = min_words or settings.SKELETON_MIN_SENTENCE_WORDS
    
    text = text.strip()
    if len(text) < min_chars:
        return True
    if len(text.split()) < min_words:
        return True
    if KVP_PATTERN_RE.match(text):
        return True
    # ALL CAPS short text = header/label that leaked through
    if ALL_CAPS_RE.match(text) and len(text.split()) < 10:
        return True
    # Numeric-only content (table cells like "12,450.00")
    cleaned = re.sub(r"[\d,.$%\s\-/·•]", "", text)
    if len(cleaned) < 10:
        return True
    return False


def _is_kvp_label(text: str) -> bool:
    """Detect form-style 'Key: Value' patterns that are short and label-like."""
    if FORM_LABEL_RE.match(text) and len(text.split()) < 8:
        return True
    return False


def _clean_chunk_text_for_spacy(chunk_text: str) -> str:
    """Clean chunk text before spaCy processing.

    DI chunk text is markdown-formatted. Strip:
    - Markdown headers (# Title) — already in section_path
    - <figure> blocks — handled separately
    - Numbered list markers, bullets
    - Excessive whitespace
    """
    text = re.sub(r"^#+\s+.*$", "", chunk_text, flags=re.MULTILINE)
    text = re.sub(r"<figure>.*?</figure>", "", text, flags=re.DOTALL)
    text = re.sub(r"^\d+\\\.\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[·•\-\*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_sentences_from_chunk(
    chunk_id: str,
    chunk_text: str,
    metadata: Dict[str, Any],
    document_id: str,
    section_path: str = "",
) -> List[Dict[str, Any]]:
    """Extract sentence-level units from a single TextChunk.

    Returns list of dicts with keys:
      id, text, chunk_id, document_id, source, index_in_chunk,
      section_path, page, confidence, tokens, parent_text

    Sources:
      - "paragraph": spaCy-split body text sentences
      - "table_row": linearized DI table rows
      - "figure_caption": DI figure caption text
    """
    sentences: List[Dict[str, Any]] = []
    idx = 0

    # ─── Source A: Body text → spaCy sentence detection ──────────
    clean_text = _clean_chunk_text_for_spacy(chunk_text)
    if clean_text:
        nlp = _get_nlp()
        doc = nlp(clean_text)
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if not sent_text:
                continue
            if _is_noise_sentence(sent_text):
                continue
            if _is_kvp_label(sent_text):
                continue
            sentences.append({
                "id": f"{chunk_id}_sent_{idx}",
                "text": sent_text,
                "chunk_id": chunk_id,
                "document_id": document_id,
                "source": "paragraph",
                "index_in_chunk": idx,
                "section_path": section_path,
                "page": metadata.get("page_number"),
                "confidence": 1.0,
                "tokens": len(sent_text.split()),
                "parent_text": clean_text[:500] if clean_text else "",
            })
            idx += 1

    # ─── Source B: Table rows from DI metadata ───────────────────
    tables = metadata.get("tables", [])
    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            for row in rows:
                if not isinstance(row, dict):
                    continue
                parts = []
                for header in headers:
                    val = row.get(header, "").strip()
                    if val:
                        parts.append(f"{header}: {val}")
                if not parts:
                    continue
                row_text = " | ".join(parts)
                min_table_chars = 15  # Lower bar for structured data
                if _is_noise_sentence(row_text, min_chars=min_table_chars, min_words=3):
                    continue
                sentences.append({
                    "id": f"{chunk_id}_sent_{idx}",
                    "text": row_text,
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "source": "table_row",
                    "index_in_chunk": idx,
                    "section_path": section_path,
                    "page": metadata.get("page_number"),
                    "confidence": 1.0,
                    "tokens": len(row_text.split()),
                    "parent_text": "",  # Table rows are self-contained
                })
                idx += 1

    # ─── Source C: Figure captions from DI metadata ──────────────
    figures = metadata.get("figures", [])
    if isinstance(figures, list):
        for fig in figures:
            if not isinstance(fig, dict):
                continue
            caption = (fig.get("caption") or "").strip()
            if not caption or len(caption) < 15:
                continue
            sentences.append({
                "id": f"{chunk_id}_sent_{idx}",
                "text": caption,
                "chunk_id": chunk_id,
                "document_id": document_id,
                "source": "figure_caption",
                "index_in_chunk": idx,
                "section_path": section_path,
                "page": fig.get("page_number") or metadata.get("page_number"),
                "confidence": 1.0,
                "tokens": len(caption.split()),
                "parent_text": "",
            })
            idx += 1

    return sentences


def extract_sentences_from_chunks(
    chunks: List[Any],
    chunk_section_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Extract sentences from all chunks, with cross-chunk deduplication.
    
    Args:
        chunks: List of TextChunk dataclass instances
        chunk_section_map: Optional map of chunk_id → section_path
        
    Returns:
        Deduplicated list of sentence dicts ready for Sentence dataclass creation
    """
    all_sentences: List[Dict[str, Any]] = []
    seen_texts: set = set()
    
    for chunk in chunks:
        metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
        # Try to parse JSON metadata if string
        if isinstance(chunk.metadata, str):
            import json
            try:
                metadata = json.loads(chunk.metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        
        section_path = ""
        if chunk_section_map:
            section_path = chunk_section_map.get(chunk.id, "")
        
        chunk_sentences = extract_sentences_from_chunk(
            chunk_id=chunk.id,
            chunk_text=chunk.text,
            metadata=metadata,
            document_id=chunk.document_id,
            section_path=section_path,
        )
        
        # Cross-chunk dedup (WARRANTY document had 3 duplicate chunk pairs)
        for sent in chunk_sentences:
            text_key = sent["text"].strip().lower()
            if text_key in seen_texts:
                continue
            seen_texts.add(text_key)
            all_sentences.append(sent)
    
    logger.info(
        "sentence_extraction_complete",
        total_chunks=len(chunks),
        total_sentences=len(all_sentences),
        dedup_removed=sum(
            len(extract_sentences_from_chunk(c.id, c.text, c.metadata if isinstance(c.metadata, dict) else {}, c.document_id))
            for c in chunks
        ) - len(all_sentences) if len(chunks) <= 50 else "skipped",
    )
    
    return all_sentences


def format_skeleton_context_for_prompt(
    sentence_results: List[Dict[str, Any]],
    max_sentences: int = 8,
) -> str:
    """Format skeleton sentence results for injection into the synthesis prompt.
    
    Uses the same pattern as the benchmark script's `synthesize_with_enriched_context()`.
    Sentence results come from `query_sentences_by_vector()`.
    """
    if not sentence_results:
        return ""
    
    lines = [
        "\n--- Supplementary Sentence-Level Evidence (skeleton retrieval) ---",
    ]
    
    for i, result in enumerate(sentence_results[:max_sentences], 1):
        doc_title = result.get("document_title", "Unknown")
        section = result.get("section_key") or result.get("section_path", "")
        score = result.get("score", 0.0)
        source = result.get("source", "paragraph")
        text = result.get("text", "")
        
        header = f"[S{i}] ({doc_title}"
        if section:
            header += f" > {section}"
        header += f" | {source} | sim={score:.3f})"
        
        lines.append(header)
        lines.append(text)
        lines.append("")
    
    lines.append("--- End supplementary evidence ---\n")
    return "\n".join(lines)
