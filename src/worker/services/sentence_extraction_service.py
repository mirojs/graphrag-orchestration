"""Sentence extraction service for skeleton enrichment (Strategy A).

Extracts sentence-level nodes from TextChunks using:
- wtpsplit (body text) — neural sentence segmentation, handles abbreviations
  and compound sentences better than spaCy's dependency parser
- DI table metadata (linearized rows) — structured data
- DI figure captions — from metadata

Content taxonomy (from ARCHITECTURE_HYBRID_SKELETON_2026-02-11.md):
  EMBED as Sentence nodes:
    - Body text → wtpsplit sentence splitting
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
import threading
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.config import settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# wtpsplit initialization (lazy singleton)
# ---------------------------------------------------------------------------
_sat = None
_sat_lock = threading.Lock()

# Model choice: sat-3l-sm balances speed and quality.
# Quality matches sat-6l-sm on our legal PDF tests; 3× faster on CPU.
_WTPSPLIT_MODEL = "sat-3l-sm"


def _get_sat():
    """Lazy-load wtpsplit SaT model (thread-safe)."""
    global _sat
    if _sat is not None:
        return _sat
    with _sat_lock:
        if _sat is None:
            from wtpsplit import SaT
            _sat = SaT(_WTPSPLIT_MODEL, ort_providers=["CPUExecutionProvider"])
            logger.info("wtpsplit_loaded", model=_WTPSPLIT_MODEL)
    return _sat


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using wtpsplit.

    Uses do_paragraph_segmentation=True to handle embedded newlines
    from DI-extracted PDF text (line wrapping, section breaks).
    Returns a flat list of stripped, non-empty sentence strings.
    """
    sat = _get_sat()
    result = sat.split(text, do_paragraph_segmentation=True)
    sentences = []
    for item in result:
        if isinstance(item, list):
            sentences.extend(s.strip() for s in item if s.strip())
        elif isinstance(item, str) and item.strip():
            sentences.append(item.strip())
    return sentences


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
# Phone/fax pattern — lines whose primary content is phone numbers
PHONE_FAX_RE = re.compile(
    r"^(phone|fax|tel|mobile|cell|emergency\s+number)\b.*\(?\d{3}\)?[\s\-]\d{3}",
    re.IGNORECASE,
)
# Address-only line — street number + city/state/zip, no sentence content
ADDRESS_ONLY_RE = re.compile(
    r"^\d+\s+[A-Z][a-z]+.*,\s*[A-Z]{2}\s+\d{4,5}$",
)
# Subtotal/total aggregation rows in tables
SUBTOTAL_RE = re.compile(
    r"^(subtotal|total|grand\s*total|amount\s*due|balance\s*due)\b",
    re.IGNORECASE,
)


def _synthesize_signature_sentences(sig_block: dict) -> List[str]:
    """Synthesize semantically meaningful sentences from a structured signature block.

    Returns a list of sentences (typically one) that capture all parties and
    the signed date in natural language so they are retrievable via semantic search.
    """
    parties = sig_block.get("parties") or []
    signed_date = (sig_block.get("signed_date") or "").strip()

    sentences: List[str] = []

    if parties:
        # Build one sentence listing all signing parties with their roles.
        party_parts = []
        for p in parties:
            name = (p.get("name") or "").strip()
            role = (p.get("role") or "").strip()
            if name and role:
                party_parts.append(f"{name} as {role}")
            elif name:
                party_parts.append(name)
        if party_parts:
            joined = ", ".join(party_parts[:-1]) + " and " + party_parts[-1] if len(party_parts) > 1 else party_parts[0]
            if signed_date:
                sentences.append(f"This document was signed by {joined} on {signed_date}.")
            else:
                sentences.append(f"This document was signed by {joined}.")
    elif signed_date:
        sentences.append(f"This document was signed on {signed_date}.")

    return sentences


def _is_noise_sentence(
    text: str,
    min_chars: int = 0,
    min_words: int = 0,
) -> bool:
    """Filter out noise: short fragments, labels, numeric-only, metadata patterns."""
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
    # Phone/fax lines — contact metadata, not sentence content
    if PHONE_FAX_RE.match(text):
        return True
    # Address-only lines (e.g. "811 Ocean Drive, Suite 405, Tampa, FL 33602")
    if ADDRESS_ONLY_RE.match(text):
        return True
    # Multi-line form layout blocks (2+ lines with few words per line)
    # But keep blocks containing dollar amounts — those are financial content.
    if "\n" in text and "$" not in text:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) >= 3 and all(len(l.split()) <= 4 for l in lines):
            return True
        # 2-line form blocks (e.g. "Authorized Representative\nFabrikam Inc.")
        if len(lines) == 2 and all(len(l.split()) <= 3 for l in lines):
            return True
    # Subtotal/total aggregation rows — only noise when value is N/A or missing
    if SUBTOTAL_RE.match(text) and re.search(r"N/?A|n/?a", text):
        return True
    return False


def _is_kvp_label(text: str) -> bool:
    """Detect form-style 'Key: Value' patterns that are short and label-like."""
    if FORM_LABEL_RE.match(text) and len(text.split()) < 8:
        return True
    return False


def _clean_chunk_text_for_spacy(chunk_text: str) -> str:
    """Clean chunk text before sentence splitting.

    DI chunk text is markdown-formatted. Strip:
    - Signature block section — handled separately via structured metadata
    - HTML elements (<table>, <!-- --> comments) — not sentence content
    - Markdown headers (# Title) — already in section_path
    - <figure> blocks — handled separately
    - Numbered list markers, bullets
    - Excessive whitespace
    """
    # Strip everything from "## Signature Block" onwards (DI-labeled, handled via Source D)
    text = re.sub(r"^##\s+Signature\s+Block\b.*", "", chunk_text, flags=re.MULTILINE | re.DOTALL)
    # Strip HTML table elements and HTML comments (DI artifacts)
    text = re.sub(r"<table>.*?</table>", "", text, flags=re.DOTALL)
    text = re.sub(r"<table\b[^>]*>.*?$", "", text, flags=re.MULTILINE | re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"^#+\s+.*$", "", text, flags=re.MULTILINE)
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
      - "paragraph":       wtpsplit-split body text sentences
      - "table_row":       linearized DI table rows
      - "figure_caption":  DI figure caption text
      - "signature_party": party name + role from DI signature block
    """
    sentences: List[Dict[str, Any]] = []
    idx = 0

    # ─── Source A: Body text → wtpsplit sentence detection ─────
    clean_text = _clean_chunk_text_for_spacy(chunk_text)
    if clean_text:
        for sent_text in _split_sentences(clean_text):
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

    # ─── Source D: Signature block ──────────────────────────────
    # Synthesize semantically rich sentences from structured signature
    # metadata so party names, roles, and dates are retrievable.
    sig_block = metadata.get("signature_block", {})
    if isinstance(sig_block, dict):
        for sig_text in _synthesize_signature_sentences(sig_block):
            sentences.append({
                "id": f"{chunk_id}_sent_{idx}",
                "text": sig_text,
                "chunk_id": chunk_id,
                "document_id": document_id,
                "source": "signature_block",
                "index_in_chunk": idx,
                "section_path": section_path,
                "page": metadata.get("page_number"),
                "confidence": 1.0,
                "tokens": len(sig_text.split()),
                "parent_text": "",
            })
            idx += 1

    return sentences


def extract_sentences_from_chunks(
    chunks: List[Any],
    chunk_section_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """Extract sentences from all chunks, with cross-chunk deduplication.
    
    Args:
        chunks: List of TextChunk dataclass instances
        chunk_section_map: Optional map of chunk_id → section_path
        
    Returns:
        Tuple of:
        - Deduplicated list of sentence dicts ready for Sentence dataclass creation
        - extra_chunk_map: sentence_id → [extra_chunk_ids] for duplicate chunks
          that contain the same sentence text. Used to create additional PART_OF
          edges so every chunk has Sentence nodes for denoising.
    """
    all_sentences: List[Dict[str, Any]] = []
    seen_texts: Dict[str, str] = {}  # text_key → sentence_id of first occurrence
    extra_chunk_map: Dict[str, List[str]] = {}  # sentence_id → [extra chunk_ids]
    
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
        
        # Cross-chunk dedup: keep first occurrence, track extra chunk_ids
        for sent in chunk_sentences:
            text_key = sent["text"].strip().lower()
            if text_key in seen_texts:
                # Record extra chunk_id so PART_OF edge can be created later
                first_sent_id = seen_texts[text_key]
                extra_chunk_map.setdefault(first_sent_id, []).append(chunk.id)
                continue
            seen_texts[text_key] = sent["id"]
            all_sentences.append(sent)
    
    extra_links = sum(len(v) for v in extra_chunk_map.values())
    logger.info(
        "sentence_extraction_complete",
        total_chunks=len(chunks),
        total_sentences=len(all_sentences),
        extra_chunk_links=extra_links,
        dedup_removed=sum(
            len(extract_sentences_from_chunk(c.id, c.text, c.metadata if isinstance(c.metadata, dict) else {}, c.document_id))
            for c in chunks
        ) - len(all_sentences) if len(chunks) <= 50 else "skipped",
    )
    
    return all_sentences, extra_chunk_map


def extract_sentences_from_di_units(
    di_units: List[Any],
    doc_id: str,
    doc_title: str = "",
    doc_source: str = "",
) -> List[Dict[str, Any]]:
    """Extract sentences directly from DI units, bypassing TextChunk creation.

    Each DI unit is a LlamaIndex Document with ``.text`` and ``.metadata``.
    Body text is split with wtpsplit; tables, figures, and signature blocks are
    extracted from DI metadata the same way ``extract_sentences_from_chunk``
    handles them.

    Returns a deduplicated list of sentence dicts with:
        id, text, chunk_id (empty), document_id, source, index_in_chunk (0),
        index_in_doc, section_path, page, confidence, tokens, parent_text.
    """
    all_sentences: List[Dict[str, Any]] = []
    seen_texts: Dict[str, str] = {}  # lowered text → sentence id (dedup)
    global_idx = 0
    section_counters: Dict[str, int] = {}  # section_path → next index_in_section

    for unit in di_units:
        meta = getattr(unit, "metadata", None) or {}
        unit_text = getattr(unit, "text", "") or ""

        # Section path from DI metadata
        section_path_raw = meta.get("section_path") or meta.get("di_section_path") or ""
        if isinstance(section_path_raw, list):
            section_path = " > ".join(str(s) for s in section_path_raw if str(s).strip())
        elif isinstance(section_path_raw, str) and section_path_raw.strip():
            section_path = section_path_raw.strip()
        else:
            section_path = ""

        page = meta.get("page_number")

        # Skip non-content DI roles
        role = meta.get("role", "")
        if role in SKIP_ROLES:
            continue

        # ─── Source A: Body text → wtpsplit sentences ────────────
        clean_text = _clean_chunk_text_for_spacy(unit_text)
        if clean_text:
            for sent_text in _split_sentences(clean_text):
                if not sent_text or _is_noise_sentence(sent_text) or _is_kvp_label(sent_text):
                    continue
                text_key = sent_text.strip().lower()
                if text_key in seen_texts:
                    continue
                sent_id = f"{doc_id}_sent_{global_idx}"
                seen_texts[text_key] = sent_id
                section_key = section_path or "[Document Root]"
                idx_in_section = section_counters.get(section_key, 0)
                section_counters[section_key] = idx_in_section + 1
                all_sentences.append({
                    "id": sent_id,
                    "text": sent_text,
                    "chunk_id": "",
                    "document_id": doc_id,
                    "source": "paragraph",
                    "index_in_chunk": 0,
                    "index_in_doc": global_idx,
                    "section_path": section_path,
                    "page": page,
                    "confidence": 1.0,
                    "tokens": len(sent_text.split()),
                    "parent_text": clean_text[:500] if clean_text else "",
                    "index_in_section": idx_in_section,
                })
                global_idx += 1

        # ─── Source B: Table rows ────────────────────────────────
        tables = meta.get("tables", [])
        if isinstance(tables, list):
            for table in tables:
                if not isinstance(table, dict):
                    continue
                headers = table.get("headers", [])
                for row in table.get("rows", []):
                    if not isinstance(row, dict):
                        continue
                    parts = [f"{h}: {row[h].strip()}" for h in headers if row.get(h, "").strip()]
                    if not parts:
                        continue
                    row_text = " | ".join(parts)
                    if _is_noise_sentence(row_text, min_chars=15, min_words=3):
                        continue
                    text_key = row_text.strip().lower()
                    if text_key in seen_texts:
                        continue
                    sent_id = f"{doc_id}_sent_{global_idx}"
                    seen_texts[text_key] = sent_id
                    section_key = section_path or "[Document Root]"
                    idx_in_section = section_counters.get(section_key, 0)
                    section_counters[section_key] = idx_in_section + 1
                    all_sentences.append({
                        "id": sent_id,
                        "text": row_text,
                        "chunk_id": "",
                        "document_id": doc_id,
                        "source": "table_row",
                        "index_in_chunk": 0,
                        "index_in_doc": global_idx,
                        "section_path": section_path,
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(row_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                    })
                    global_idx += 1

        # ─── Source C: Figure captions ───────────────────────────
        figures = meta.get("figures", [])
        if isinstance(figures, list):
            for fig in figures:
                if not isinstance(fig, dict):
                    continue
                caption = (fig.get("caption") or "").strip()
                if not caption or len(caption) < 15:
                    continue
                text_key = caption.strip().lower()
                if text_key in seen_texts:
                    continue
                sent_id = f"{doc_id}_sent_{global_idx}"
                seen_texts[text_key] = sent_id
                section_key = section_path or "[Document Root]"
                idx_in_section = section_counters.get(section_key, 0)
                section_counters[section_key] = idx_in_section + 1
                all_sentences.append({
                    "id": sent_id,
                    "text": caption,
                    "chunk_id": "",
                    "document_id": doc_id,
                    "source": "figure_caption",
                    "index_in_chunk": 0,
                    "index_in_doc": global_idx,
                    "section_path": section_path,
                    "page": fig.get("page_number") or page,
                    "confidence": 1.0,
                    "tokens": len(caption.split()),
                    "parent_text": "",
                    "index_in_section": idx_in_section,
                })
                global_idx += 1

        # ─── Source D: Signature block ────────────────────────────
        # Synthesize semantically rich sentences from structured signature
        # metadata so party names, roles, and dates are retrievable.
        sig_block = meta.get("signature_block", {})
        if isinstance(sig_block, dict):
            for sig_text in _synthesize_signature_sentences(sig_block):
                text_key = sig_text.strip().lower()
                if text_key not in seen_texts:
                    sent_id = f"{doc_id}_sent_{global_idx}"
                    seen_texts[text_key] = sent_id
                    section_key = section_path or "[Document Root]"
                    idx_in_section = section_counters.get(section_key, 0)
                    section_counters[section_key] = idx_in_section + 1
                    all_sentences.append({
                        "id": sent_id,
                        "text": sig_text,
                        "chunk_id": "",
                        "document_id": doc_id,
                        "source": "signature_block",
                        "index_in_chunk": 0,
                        "index_in_doc": global_idx,
                        "section_path": section_path,
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(sig_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                    })
                    global_idx += 1

    # Backfill total_in_section from section_counters
    for sent in all_sentences:
        sk = sent.get("section_path") or "[Document Root]"
        sent["total_in_section"] = section_counters.get(sk, 0)

    logger.info(
        "di_sentence_extraction_complete",
        doc_id=doc_id,
        di_units=len(di_units),
        sentences=len(all_sentences),
    )
    return all_sentences


def extract_sentences_from_raw_text(
    text: str,
    doc_id: str,
    doc_title: str = "",
    doc_source: str = "",
) -> List[Dict[str, Any]]:
    """Extract sentences from raw text (non-DI fallback) using wtpsplit."""
    sentences: List[Dict[str, Any]] = []
    clean_text = _clean_chunk_text_for_spacy(text)
    if not clean_text:
        return sentences

    sent_idx = 0
    for sent_text in _split_sentences(clean_text):
        if not sent_text or _is_noise_sentence(sent_text) or _is_kvp_label(sent_text):
            continue
        sentences.append({
            "id": f"{doc_id}_sent_{sent_idx}",
            "text": sent_text,
            "chunk_id": "",
            "document_id": doc_id,
            "source": "paragraph",
            "index_in_chunk": 0,
            "index_in_doc": sent_idx,
            "section_path": "",
            "page": None,
            "confidence": 1.0,
            "tokens": len(sent_text.split()),
            "parent_text": clean_text[:500],
            "index_in_section": sent_idx,
        })
        sent_idx += 1

    # Backfill total_in_section (all sentences are in root section)
    for sent in sentences:
        sent["total_in_section"] = len(sentences)

    logger.info(
        "raw_text_sentence_extraction_complete",
        doc_id=doc_id,
        sentences=len(sentences),
    )
    return sentences


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
