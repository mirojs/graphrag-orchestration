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
    - Letterhead → page-1 pre-heading heuristic (source="letterhead")
  NOT embedded (metadata only):
    - KVPs, titles, headers/footers, barcodes, selection marks, signatures

Benchmark results (Strategy A):
  - F1: 0.082 → 0.319 (+289%)
  - Containment: 0.462 → 0.627 (+36%)
  - 8 wins, 0 real losses, 1 tie (1 "loss" was metric artifact)
"""

import json as json_mod
import os
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
# LLM sentence-boundary review (bundled)
# ---------------------------------------------------------------------------

_LLM_REVIEW_SINGLE_PROMPT = """You are a sentence boundary reviewer. Below are text segments produced by an automated sentence splitter. Some boundaries may be WRONG.

RULES — you must follow ALL of these:
1. You may MERGE adjacent segments (remove a split between them).
2. You may SPLIT one segment into two (add a split inside it).
3. You must NOT add, remove, or change any character.
4. You must NOT reorder segments.
5. Every character from the input must appear exactly once in the output.

Segments to review (JSON array):
{segments_json}

Return ONLY a JSON array of the corrected segments. If no changes are needed, return the input unchanged.
"""

_LLM_REVIEW_BUNDLED_PROMPT = """You are a sentence boundary reviewer. Below are text segments from multiple sections, produced by an automated sentence splitter. Some boundaries may be WRONG.

RULES — you must follow ALL of these:
1. You may MERGE adjacent segments within a section (remove a split between them).
2. You may SPLIT one segment into two within a section (add a split inside it).
3. You must NOT add, remove, or change any character.
4. You must NOT reorder segments.
5. You must NOT move segments between sections.
6. Every character from the input must appear exactly once in the output.

Sections to review:
{sections_json}

Return ONLY a JSON array of objects with "id" and "sentences" keys, matching the input structure. If no changes are needed for a section, return it unchanged.
"""

# Maximum sentences per section before it gets its own LLM call
_LLM_REVIEW_SECTION_CEILING = 30


def verify_llm_review(
    original_segments: List[str],
    reviewed_segments: List[str],
) -> bool:
    """Return True iff the LLM only moved boundaries (no text changes)."""
    orig = " ".join(s.strip() for s in original_segments)
    rev = " ".join(s.strip() for s in reviewed_segments)
    return orig == rev


def llm_review_sections_bundled(
    sections: List[Tuple[str, List[str]]],
) -> Dict[str, List[str]]:
    """Review sentence boundaries for multiple sections in one LLM call.

    Args:
        sections: list of (section_id, sentences) pairs.

    Returns:
        dict mapping section_id → reviewed sentences.
        Sections that fail verification keep their original sentences.
    """
    if not sections:
        return {}

    results: Dict[str, List[str]] = {}
    # Separate oversized sections (> ceiling) for individual calls
    normal: List[Tuple[str, List[str]]] = []
    oversized: List[Tuple[str, List[str]]] = []
    for sid, sents in sections:
        if len(sents) > _LLM_REVIEW_SECTION_CEILING:
            oversized.append((sid, sents))
        else:
            normal.append((sid, sents))

    # Handle oversized sections individually
    for sid, sents in oversized:
        segments_json = json_mod.dumps(sents, ensure_ascii=False)
        prompt = _LLM_REVIEW_SINGLE_PROMPT.format(segments_json=segments_json)
        try:
            corrected = _call_llm_for_review(prompt)
        except Exception:
            corrected = None
        if corrected and verify_llm_review(sents, corrected):
            results[sid] = corrected
            logger.info("llm_review_section_complete", section=sid,
                        original=len(sents), reviewed=len(corrected))
        else:
            results[sid] = sents

    if not normal:
        return results

    # Bundle normal sections into one call
    payload = [{"id": sid, "sentences": sents} for sid, sents in normal]
    sections_json = json_mod.dumps(payload, ensure_ascii=False)
    prompt = _LLM_REVIEW_BUNDLED_PROMPT.format(sections_json=sections_json)

    try:
        raw = _call_llm_for_review_raw(prompt)
    except Exception as exc:
        logger.debug("llm_review_bundled_call_failed", error=str(exc))
        for sid, sents in normal:
            results[sid] = sents
        return results

    if raw is None:
        for sid, sents in normal:
            results[sid] = sents
        return results

    # Parse bundled response: list of {id, sentences}
    if not isinstance(raw, list):
        for sid, sents in normal:
            results[sid] = sents
        return results

    # Build lookup from original sections
    orig_map = {sid: sents for sid, sents in normal}
    reviewed_map: Dict[str, List[str]] = {}
    for item in raw:
        if isinstance(item, dict) and "id" in item and "sentences" in item:
            reviewed_map[str(item["id"])] = item["sentences"]

    # Verify each section independently
    for sid, orig_sents in normal:
        reviewed = reviewed_map.get(sid)
        if reviewed and verify_llm_review(orig_sents, reviewed):
            results[sid] = reviewed
            if reviewed != orig_sents:
                logger.info("llm_review_section_changed", section=sid,
                            original=len(orig_sents), reviewed=len(reviewed))
        else:
            results[sid] = orig_sents

    logger.info("llm_review_bundled_complete",
                sections=len(normal), changed=sum(
                    1 for sid, sents in normal if results[sid] != sents))
    return results


def _call_llm_json(prompt: str) -> Optional[Any]:
    """Synchronous LLM call that returns parsed JSON (any type) or None."""
    try:
        from llama_index.llms.azure_openai import AzureOpenAI
    except ImportError:
        logger.debug("llm_sentence_review_no_llama_index")
        return None

    from src.core.config import settings

    model = os.getenv("SENTENCE_REVIEW_MODEL", "gpt-4.1")
    deployment = os.getenv("SENTENCE_REVIEW_DEPLOYMENT", model)
    api_version = settings.AZURE_OPENAI_API_VERSION or "2025-03-01-preview"

    # Auth: mirror LLMService._create_llm_client() pattern
    llm_kwargs: dict = {
        "engine": deployment,
        "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
        "api_version": api_version,
        "temperature": 0.0,
    }
    if settings.AZURE_OPENAI_API_KEY:
        llm_kwargs["api_key"] = settings.AZURE_OPENAI_API_KEY
    else:
        env_token = os.getenv("AZURE_OPENAI_BEARER_TOKEN")
        if env_token:
            llm_kwargs["use_azure_ad"] = True
            llm_kwargs["azure_ad_token_provider"] = lambda: env_token
        else:
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                credential = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(
                    credential, "https://cognitiveservices.azure.com/.default"
                )
                llm_kwargs["use_azure_ad"] = True
                llm_kwargs["azure_ad_token_provider"] = token_provider
            except Exception:
                logger.debug("llm_sentence_review_no_credential")
                return None

    try:
        llm = AzureOpenAI(**llm_kwargs)
        response = llm.complete(prompt)
        text = (response.text or "").strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].rstrip()
        if text.startswith("json"):
            text = text[4:].lstrip()
        return json_mod.loads(text)
    except Exception as exc:
        logger.debug("llm_sentence_review_parse_failed", error=str(exc))
        return None


def _call_llm_for_review(prompt: str) -> Optional[List[str]]:
    """LLM call expecting a JSON array of strings. Returns list or None."""
    parsed = _call_llm_json(prompt)
    if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
        return parsed
    return None


def _call_llm_for_review_raw(prompt: str) -> Optional[Any]:
    """LLM call expecting any JSON structure (for bundled review)."""
    return _call_llm_json(prompt)

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
# Bare form labels with no value (e.g. "Name:", "Date:", "Phone:")
KVP_PATTERN_RE = re.compile(
    r"^(name|date|address|phone|email|signature|title|page|total|amount|"
    r"number|id|ref|no\.?|signed|owner|agent|customer)\s*[:_\-#]?\s*$",
    re.IGNORECASE,
)
# ALL-CAPS text — catches DI heading-role misses (e.g. "EXHIBIT A")
ALL_CAPS_RE = re.compile(r"^[A-Z\s\d.,!?:;\-()]+$")


# Max letterhead paragraphs / words before we treat it as real body text
_LETTERHEAD_MAX_PARAGRAPHS = 5
_LETTERHEAD_MAX_WORDS = 50

# KVP-like paragraph start — stops letterhead collection.
# Matches "Invoice #: 12345", "Date: December", "Bill To: Address",
# and standalone labels like "TO:", "FROM:", "BILL TO:" (colon at end).
_LETTERHEAD_KVP_STOP_RE = re.compile(
    r'^[A-Za-z][A-Za-z\s]{0,20}(?:#\s*)?:\s*\S|^[A-Za-z][A-Za-z\s]{0,20}:\s*$',
)

_SIG_UNDERSCORE_RE = re.compile(r'^[_\-=\s]{3,}$')
_SIG_FIELD_LABEL_RE = re.compile(
    r'^(?:Date[d]?|Signature[s]?|Sign|Initials?|Print(?:ed)?|'
    r'Title[s]?|Name[s]?|N/?A|By)\s*[:\s]*$',
    re.IGNORECASE,
)


def _page_for_sentence(sent_text: str, unit_text: str,
                       paragraph_pages: List[Dict],
                       default_page) -> Any:
    """Look up the page number for a sentence using paragraph_pages map.

    Finds the sentence's position in the unit text, then locates which
    paragraph span contains that position to inherit its page number.
    Falls back to *default_page* if no match is found.
    """
    if not paragraph_pages or not sent_text or not unit_text:
        return default_page
    # Find sentence position in unit text
    pos = unit_text.find(sent_text)
    if pos < 0:
        return default_page
    for pp in paragraph_pages:
        pp_start = pp["offset"]
        pp_end = pp_start + pp["length"]
        if pp_start <= pos < pp_end:
            return pp["page"]
    return default_page


# Pattern: short "Key: Value" spec-list items (e.g. "Hall Call: 1")
_SPEC_LIST_RE = re.compile(r'^[A-Za-z0-9][^:]{0,30}:\s*.{1,40}$')
_LIST_JOIN_MAX_TOKENS = 15
_LIST_JOIN_GROUP_MAX_TOKENS = 120

# Preamble merge: colon-terminated stubs and very short fragments
_PREAMBLE_RE = re.compile(r"[:\.][\s.]*$")  # ends with : or :. (possibly trailing spaces/dots)


def _join_preamble_sentences(sentences: List[Dict]) -> List[Dict]:
    """Merge stub/preamble sentences with the sentence that follows them.

    Targets two patterns that wtpsplit over-splits:
      1. List preambles ending with ':' or ':.' (e.g. "Owner agrees to and shall:.")
      2. Very short fragments (≤ 3 words) that are incomplete on their own
         (e.g. "(f) Provide Liability" split from "Insurance coverage …")

    Only merges consecutive *paragraph* sources sharing the same section_path
    to avoid cross-section contamination.
    """
    if len(sentences) < 2:
        return sentences

    result: List[Dict] = []
    i = 0
    while i < len(sentences):
        sent = sentences[i]
        text = sent.get("text", "").strip()
        source = sent.get("source", "")

        # Only merge paragraph sentences (not tables, signatures, etc.)
        if source == "paragraph" and i + 1 < len(sentences):
            nxt = sentences[i + 1]
            same_section = (
                nxt.get("source") == "paragraph"
                and nxt.get("section_path", "") == sent.get("section_path", "")
            )
            is_preamble = (
                text.endswith(":") or text.endswith(":.") or text.endswith(": .")
            )
            # Only merge very short fragments that don't end with a period
            # (period = likely a complete sentence, e.g. "Manufacturer warranty applies.")
            is_tiny = len(text.split()) <= 3 and not text.rstrip().endswith(".")

            if same_section and (is_preamble or is_tiny):
                nxt_text = nxt.get("text", "").strip()
                joined_text = f"{text} {nxt_text}"
                merged = dict(sent)
                merged["text"] = joined_text
                merged["tokens"] = len(joined_text.split())
                result.append(merged)
                i += 2
                continue

        result.append(sent)
        i += 1
    return result


def _join_spec_list_sentences(sentences: List[Dict]) -> List[Dict]:
    """Join consecutive short spec-list sentences into grouped sentences.

    Spec-list items like "Hall Call: 1", "Door Height: 7 ft" are too short
    for meaningful retrieval individually.  Group consecutive short items
    sharing a Key:Value pattern into a single joined sentence.
    """
    if not sentences:
        return sentences

    result: List[Dict] = []
    group: List[Dict] = []
    group_tokens = 0

    def flush_group():
        nonlocal group, group_tokens
        if not group:
            return
        if len(group) == 1:
            result.append(group[0])
        else:
            joined_text = " | ".join(s["text"] for s in group)
            merged = dict(group[0])
            merged["text"] = joined_text
            merged["tokens"] = len(joined_text.split())
            result.append(merged)
        group = []
        group_tokens = 0

    for sent in sentences:
        tokens = sent.get("tokens", len(sent.get("text", "").split()))
        text = sent.get("text", "")
        is_spec = (
            tokens <= _LIST_JOIN_MAX_TOKENS
            and _SPEC_LIST_RE.match(text)
            and sent.get("source") == "paragraph"
        )
        if is_spec and group_tokens + tokens <= _LIST_JOIN_GROUP_MAX_TOKENS:
            group.append(sent)
            group_tokens += tokens
        else:
            flush_group()
            if is_spec:
                group = [sent]
                group_tokens = tokens
            else:
                result.append(sent)
    flush_group()
    return result


def _detect_letterhead_indices(di_units: List[Any]) -> List[int]:
    """Identify letterhead paragraphs: page 1, before first heading, no role.

    Collects contiguous no-role paragraphs from the document start.
    Stops at: first heading, first KVP-like paragraph (``Key: Value``),
    page boundary, or size thresholds.

    Returns ordered list of unit indices that form the letterhead block.
    Empty list if no letterhead detected or candidates exceed size thresholds.
    """
    candidates: List[int] = []
    candidate_texts: List[str] = []

    for i, unit in enumerate(di_units):
        meta = getattr(unit, "metadata", None) or {}
        role = meta.get("role", "")
        # Stop at first heading — everything after is real content
        if role in ("title", "sectionHeading"):
            break
        # Skip already-handled DI roles (headers, footers, page numbers, letterhead)
        if role in ("pageHeader", "pageFooter", "pageNumber", "signature", "letterhead"):
            continue
        page = meta.get("page_number")
        # Only page 1 (or unknown page)
        if page is not None and page != 1:
            break
        text = (getattr(unit, "text", "") or "").strip()
        if not text:
            continue
        # Stop at KVP-like content (e.g. "Invoice #: 12345", "Date: Dec")
        if _LETTERHEAD_KVP_STOP_RE.match(text):
            break
        candidates.append(i)
        candidate_texts.append(text)
        if len(candidates) > _LETTERHEAD_MAX_PARAGRAPHS:
            return []  # Too many — likely real body text

    if not candidates:
        return []
    total_words = sum(len(t.split()) for t in candidate_texts)
    if total_words > _LETTERHEAD_MAX_WORDS:
        return []  # Too long — not letterhead
    return candidates


def _synthesize_signature_sentences(sig_block: dict) -> List[str]:
    """Return a single joined sentence from a structured signature block.

    Instead of constructing a template sentence from parsed party/role data
    (which is brittle and depends on regex extraction), we join the **raw
    paragraph lines** into one sentence — filtering only underscore filler
    and bare field labels.

    Joining keeps all fragments (party names, roles, dates) in one embedding
    vector so semantic search can match any combination (e.g. "who is the
    authorized representative" matches the sentence containing both the name
    and the role).  The sentence is stored with ``source="signature_party"``
    which bypasses the noise-denoiser and gets a ``[Signature Block]``
    embedding context prefix.
    """
    raw_lines = sig_block.get("raw_lines") or []

    parts: List[str] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        if _SIG_UNDERSCORE_RE.match(line):
            continue
        if _SIG_FIELD_LABEL_RE.match(line):
            continue
        parts.append(line)

    if not parts:
        return []
    # Strip trailing periods before joining to avoid "Ltd.." doubles
    joined = ". ".join(p.rstrip(".") for p in parts)
    return [joined]


def _is_noise_sentence(
    text: str,
    min_chars: int = 0,
    min_words: int = 0,
) -> bool:
    """Filter DI artifacts: short fragments, numeric-only cells, heading leaks.

    Upstream layers (DI service role filtering, SKIP_ROLES, letterhead/signature
    detection, text cleaning) handle most noise.  This filter is the last safety
    net for table-cell fragments, DI heading-role misses, and bare labels.
    """
    min_chars = min_chars or settings.SKELETON_MIN_SENTENCE_CHARS
    min_words = min_words or settings.SKELETON_MIN_SENTENCE_WORDS

    text = text.strip()

    # Rule 1: Minimum length — catches list markers, abbreviations, codes
    if len(text) < min_chars:
        return True
    if len(text.split()) < min_words:
        return True

    # Rule 2: Bare form labels without values ("Name:", "Date:")
    if KVP_PATTERN_RE.match(text):
        return True

    # Rule 3: ALL-CAPS leaked headings that DI missed labelling
    if ALL_CAPS_RE.match(text) and len(text.split()) <= 5:
        return True

    # Rule 4: Numeric-only content (standalone table cells like "$12,450.00")
    cleaned = re.sub(r"[\d,.$%\s\-/·•]", "", text)
    if len(cleaned) < 8:
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
    # Normalize single newlines to spaces (DI PDF line wrapping) while
    # preserving paragraph breaks (double newlines).
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    # Convert remaining paragraph breaks to sentence boundaries so the
    # sentence splitter treats them as separate sentences.
    text = re.sub(r"\n\n+", ". ", text)
    # Clean up double periods from paragraph-break normalization
    text = re.sub(r"\.{2,}", ".", text)
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
      id, text, document_id, source,
      section_path, page, confidence, tokens, parent_text

    Sources:
      - "paragraph":       wtpsplit-split body text sentences
      - "table_row":       linearized DI table rows
      - "table_caption":   DI table caption text
      - "figure_caption":  DI figure caption text
      - "signature_party": party name + role from DI signature block
      - "page_header":     first occurrence of DI pageHeader (deduped)
      - "page_footer":     first occurrence of DI pageFooter (deduped)
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
            sentences.append({
                "id": f"{chunk_id}_sent_{idx}",
                "text": sent_text,
                "document_id": document_id,
                "source": "paragraph",
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
                    "document_id": document_id,
                    "source": "table_row",
                    "section_path": section_path,
                    "page": metadata.get("page_number"),
                    "confidence": 1.0,
                    "tokens": len(row_text.split()),
                    "parent_text": "",  # Table rows are self-contained
                })
                idx += 1

            # Table caption (if DI detected one)
            caption = (table.get("caption") or "").strip()
            if caption and len(caption) >= 10:
                sentences.append({
                    "id": f"{chunk_id}_sent_{idx}",
                    "text": caption,
                    "document_id": document_id,
                    "source": "table_caption",
                    "section_path": section_path,
                    "page": metadata.get("page_number"),
                    "confidence": 1.0,
                    "tokens": len(caption.split()),
                    "parent_text": "",
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
                "document_id": document_id,
                "source": "figure_caption",
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
        sig_meta = {
            "parties": sig_block.get("parties", []),
            "signed_date": sig_block.get("signed_date", ""),
            "type": "signature_block",
        }
        for sig_text in _synthesize_signature_sentences(sig_block):
            sentences.append({
                "id": f"{chunk_id}_sent_{idx}",
                "text": sig_text,
                "document_id": document_id,
                "source": "signature_party",
                "section_path": section_path,
                "page": metadata.get("page_number"),
                "confidence": 1.0,
                "tokens": len(sig_text.split()),
                "parent_text": "",
                "metadata": sig_meta,
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


def _match_geometry_for_sentence(
    sent_text: str,
    geometry_sentences: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Find the DI geometry sentence that best matches a wtpsplit sentence.

    Returns the matching geometry dict (with ``polygons``, ``page``, etc.)
    or *None* if no reasonable match is found.
    """
    if not geometry_sentences or not sent_text:
        return None

    norm_sent = " ".join(sent_text.lower().split())
    if len(norm_sent) < 5:
        return None

    best: Optional[Dict[str, Any]] = None
    best_overlap = 0

    for geo in geometry_sentences:
        geo_text = geo.get("text", "")
        if not geo_text:
            continue
        norm_geo = " ".join(geo_text.lower().split())

        # Quick containment check (covers 90%+ of cases)
        if norm_sent in norm_geo or norm_geo in norm_sent:
            overlap = min(len(norm_sent), len(norm_geo))
            if overlap > best_overlap:
                best_overlap = overlap
                best = geo
            continue

        # Partial overlap: first 40 chars of sentence in geometry text
        probe = norm_sent[:40]
        if probe in norm_geo:
            overlap = len(probe)
            if overlap > best_overlap:
                best_overlap = overlap
                best = geo

    if best and best_overlap >= 20:
        return best
    return None


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
        id, text, document_id, source,
        index_in_doc, section_path, page, confidence, tokens, parent_text.
    """
    all_sentences: List[Dict[str, Any]] = []
    seen_texts: Dict[str, str] = {}  # lowered text → sentence id (dedup)
    global_idx = 0
    section_counters: Dict[str, int] = {}  # section_path → next index_in_section
    # Track first occurrence of header/footer for dedup (one per doc)
    _first_header_captured = False
    _first_footer_captured = False

    # ─── Source F: Letterhead detection (page 1, before first heading) ──
    # DI doesn't label letterhead specifically — it comes through as regular
    # paragraphs with no role.  Detect top-of-page-1 orphaned text and
    # consolidate into one sentence with source="letterhead".
    letterhead_indices = set(_detect_letterhead_indices(di_units))
    if letterhead_indices:
        lh_texts = []
        lh_page = None
        for li in sorted(letterhead_indices):
            u = di_units[li]
            lh_texts.append((getattr(u, "text", "") or "").strip())
            if lh_page is None:
                lh_page = (getattr(u, "metadata", None) or {}).get("page_number")
        lh_joined = ". ".join(t.rstrip(".") for t in lh_texts if t)
        if lh_joined:
            text_key = lh_joined.strip().lower()
            if text_key not in seen_texts:
                sent_id = f"{doc_id}_sent_{global_idx}"
                seen_texts[text_key] = sent_id
                section_key = "[Letterhead]"
                idx_in_section = section_counters.get(section_key, 0)
                section_counters[section_key] = idx_in_section + 1
                all_sentences.append({
                    "id": sent_id,
                    "text": lh_joined,
                    "document_id": doc_id,
                    "source": "letterhead",
                    "index_in_doc": global_idx,
                    "section_path": "[Letterhead]",
                    "page": lh_page,
                    "confidence": 1.0,
                    "tokens": len(lh_joined.split()),
                    "parent_text": "",
                    "index_in_section": idx_in_section,
                })
                global_idx += 1
        logger.info(
            "letterhead_detected",
            doc_id=doc_id,
            paragraph_count=len(letterhead_indices),
            text_preview=lh_joined[:100] if lh_joined else "",
        )

    for unit_idx, unit in enumerate(di_units):
        # Skip letterhead paragraphs — already consolidated above
        if unit_idx in letterhead_indices:
            continue
        meta = getattr(unit, "metadata", None) or {}
        unit_text = getattr(unit, "text", "") or ""

        # ─── DI geometry data for pixel-accurate highlighting ────
        unit_geometry_sentences = meta.get("sentences") or []
        unit_page_dimensions = meta.get("page_dimensions") or []

        # Section path from DI metadata
        section_path_raw = meta.get("section_path") or meta.get("di_section_path") or ""
        if isinstance(section_path_raw, list):
            section_path = " > ".join(str(s) for s in section_path_raw if str(s).strip())
        elif isinstance(section_path_raw, str) and section_path_raw.strip():
            section_path = section_path_raw.strip()
        else:
            section_path = ""

        page = meta.get("page_number")
        # Per-paragraph page map for cross-page sections (Fix A2)
        paragraph_pages = meta.get("paragraph_pages") or []

        # ─── Source E: First-occurrence page header / footer ─────
        # DI tags repeated header/footer paragraphs on every page.
        # Capture only the first occurrence as a searchable sentence
        # (denoising: one node per doc instead of N duplicate nodes).
        role = meta.get("role", "")
        if role == "pageHeader" and not _first_header_captured:
            hdr_text = unit_text.strip()
            if hdr_text and len(hdr_text) >= 3:
                _first_header_captured = True
                text_key = hdr_text.strip().lower()
                if text_key not in seen_texts:
                    sent_id = f"{doc_id}_sent_{global_idx}"
                    seen_texts[text_key] = sent_id
                    section_key = "[Page Header]"
                    idx_in_section = section_counters.get(section_key, 0)
                    section_counters[section_key] = idx_in_section + 1
                    all_sentences.append({
                        "id": sent_id,
                        "text": hdr_text,
                        "document_id": doc_id,
                        "source": "page_header",
                        "index_in_doc": global_idx,
                        "section_path": "[Page Header]",
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(hdr_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                    })
                    global_idx += 1
            continue
        if role == "pageFooter" and not _first_footer_captured:
            ftr_text = unit_text.strip()
            if ftr_text and len(ftr_text) >= 3:
                _first_footer_captured = True
                text_key = ftr_text.strip().lower()
                if text_key not in seen_texts:
                    sent_id = f"{doc_id}_sent_{global_idx}"
                    seen_texts[text_key] = sent_id
                    section_key = "[Page Footer]"
                    idx_in_section = section_counters.get(section_key, 0)
                    section_counters[section_key] = idx_in_section + 1
                    all_sentences.append({
                        "id": sent_id,
                        "text": ftr_text,
                        "document_id": doc_id,
                        "source": "page_footer",
                        "index_in_doc": global_idx,
                        "section_path": "[Page Footer]",
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(ftr_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                    })
                    global_idx += 1
            continue

        # ─── Source F: Letterhead (tagged by section-aware path) ─────
        if role == "letterhead":
            lh_text = unit_text.strip()
            if lh_text:
                text_key = lh_text.strip().lower()
                if text_key not in seen_texts:
                    sent_id = f"{doc_id}_sent_{global_idx}"
                    seen_texts[text_key] = sent_id
                    section_key = "[Letterhead]"
                    idx_in_section = section_counters.get(section_key, 0)
                    section_counters[section_key] = idx_in_section + 1
                    all_sentences.append({
                        "id": sent_id,
                        "text": lh_text,
                        "document_id": doc_id,
                        "source": "letterhead",
                        "index_in_doc": global_idx,
                        "section_path": "[Letterhead]",
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(lh_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                    })
                    global_idx += 1
            continue

        # ─── Source G: Signature block (tagged by section-aware path) ──
        if role == "signature":
            sig_text = unit_text.strip()
            if sig_text:
                text_key = sig_text.strip().lower()
                if text_key not in seen_texts:
                    sent_id = f"{doc_id}_sent_{global_idx}"
                    seen_texts[text_key] = sent_id
                    section_key = "[Signature Block]"
                    idx_in_section = section_counters.get(section_key, 0)
                    section_counters[section_key] = idx_in_section + 1
                    all_sentences.append({
                        "id": sent_id,
                        "text": sig_text,
                        "document_id": doc_id,
                        "source": "signature_block",
                        "index_in_doc": global_idx,
                        "section_path": "[Signature Block]",
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(sig_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                    })
                    global_idx += 1
            continue

        # Skip non-content DI roles (remaining headers/footers, page numbers, etc.)
        if role in SKIP_ROLES:
            continue

        # ─── Source A: Body text → wtpsplit sentences ────────────
        clean_text = _clean_chunk_text_for_spacy(unit_text)
        if clean_text:
            for sent_text in _split_sentences(clean_text):
                if not sent_text or _is_noise_sentence(sent_text):
                    continue
                # Strip leading sentence-boundary artifacts from \n\n→". " conversion
                sent_text = re.sub(r'^[\.\s]+', '', sent_text).strip()
                if not sent_text:
                    continue
                text_key = sent_text.strip().lower()
                if text_key in seen_texts:
                    continue
                sent_id = f"{doc_id}_sent_{global_idx}"
                seen_texts[text_key] = sent_id
                section_key = section_path or "[Document Root]"
                idx_in_section = section_counters.get(section_key, 0)
                section_counters[section_key] = idx_in_section + 1
                sent_dict: Dict[str, Any] = {
                    "id": sent_id,
                    "text": sent_text,
                    "document_id": doc_id,
                    "source": "paragraph",
                    "index_in_doc": global_idx,
                    "section_path": section_path,
                    "page": _page_for_sentence(sent_text, unit_text, paragraph_pages, page),
                    "confidence": 1.0,
                    "tokens": len(sent_text.split()),
                    "parent_text": clean_text[:500] if clean_text else "",
                    "index_in_section": idx_in_section,
                }
                # Attach DI polygon geometry for pixel-accurate highlighting
                if unit_geometry_sentences:
                    geo = _match_geometry_for_sentence(sent_text, unit_geometry_sentences)
                    if geo and geo.get("polygons"):
                        sent_dict["polygons"] = geo["polygons"]
                        if geo.get("page"):
                            sent_dict["page"] = geo["page"]
                if unit_page_dimensions:
                    sent_dict["page_dimensions"] = unit_page_dimensions
                all_sentences.append(sent_dict)
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
                    row_dict: Dict[str, Any] = {
                        "id": sent_id,
                        "text": row_text,
                        "document_id": doc_id,
                        "source": "table_row",
                        "index_in_doc": global_idx,
                        "section_path": section_path,
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(row_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                    }
                    # Attach DI polygon geometry for table row highlighting
                    if unit_geometry_sentences:
                        geo = _match_geometry_for_sentence(row_text, unit_geometry_sentences)
                        if geo and geo.get("polygons"):
                            row_dict["polygons"] = geo["polygons"]
                            if geo.get("page"):
                                row_dict["page"] = geo["page"]
                    if unit_page_dimensions:
                        row_dict["page_dimensions"] = unit_page_dimensions
                    all_sentences.append(row_dict)
                    global_idx += 1

                # Table caption (if DI detected one)
                caption = (table.get("caption") or "").strip()
                if caption and len(caption) >= 10:
                    text_key = caption.strip().lower()
                    if text_key not in seen_texts:
                        sent_id = f"{doc_id}_sent_{global_idx}"
                        seen_texts[text_key] = sent_id
                        section_key = section_path or "[Document Root]"
                        idx_in_section = section_counters.get(section_key, 0)
                        section_counters[section_key] = idx_in_section + 1
                        all_sentences.append({
                            "id": sent_id,
                            "text": caption,
                            "document_id": doc_id,
                            "source": "table_caption",
                            "index_in_doc": global_idx,
                            "section_path": section_path,
                            "page": page,
                            "confidence": 1.0,
                            "tokens": len(caption.split()),
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
                    "document_id": doc_id,
                    "source": "figure_caption",
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
            sig_meta = {
                "parties": sig_block.get("parties", []),
                "signed_date": sig_block.get("signed_date", ""),
                "type": "signature_block",
            }
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
                        "document_id": doc_id,
                        "source": "signature_party",
                        "index_in_doc": global_idx,
                        "section_path": section_path,
                        "page": page,
                        "confidence": 1.0,
                        "tokens": len(sig_text.split()),
                        "parent_text": "",
                        "index_in_section": idx_in_section,
                        "metadata": sig_meta,
                    })
                    global_idx += 1

    # Merge preamble stubs (colon-terminated, tiny fragments) with next sentence
    if not os.getenv("DISABLE_PREAMBLE_MERGE"):
        all_sentences = _join_preamble_sentences(all_sentences)
    # Join consecutive short spec-list sentences (Fix A7)
    all_sentences = _join_spec_list_sentences(all_sentences)

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
        if not sent_text or _is_noise_sentence(sent_text):
            continue
        sentences.append({
            "id": f"{doc_id}_sent_{sent_idx}",
            "text": sent_text,
            "document_id": doc_id,
            "source": "paragraph",
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
