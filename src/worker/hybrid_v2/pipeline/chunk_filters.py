"""
Chunk Noise Filters — Phase 2 Context De-noising (February 9, 2026)

Filters that deprioritize structurally useless chunks before token budget
enforcement.  These run *after* content-hash dedup but *before* score-ranked
budget truncation, so noisy chunks are penalised and pushed below the budget
cutoff rather than hard-deleted (preserving recall for edge cases).

Filters:
    1. Form-label filter:   Chunks dominated by blank form fields
                            (e.g. "Name:____", "Date:____", "Signature:____")
    2. Bare heading filter: Chunks with very little substantive text
                            (e.g. "4. Customer Default" — heading only)
    3. Minimum content:     Chunks below a configurable token floor

Design:
    Each filter returns a *penalty multiplier* in (0, 1].  The final score of
    a chunk is  original_score × Π(penalties).  A multiplier of 1.0 means
    "no change"; 0.1 means "reduce score by 90%".  This keeps the interface
    additive — new filters compose without needing mutual awareness.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum substantive characters after stripping blanks/underscores/colons
BARE_HEADING_CHAR_THRESHOLD = 20

# Minimum estimated tokens of actual content (below → penalise)
MIN_CONTENT_TOKENS = 50

# If ≥ this fraction of "lines" in a chunk match the form-label pattern,
# the chunk is considered a form-label chunk.
FORM_LABEL_LINE_RATIO = 0.50

# Penalty multipliers (lower = stronger penalty, 0 < p ≤ 1)
FORM_LABEL_PENALTY = 0.05     # Nearly eliminate form-label chunks
BARE_HEADING_PENALTY = 0.10   # Nearly eliminate bare headings
LOW_CONTENT_PENALTY = 0.20    # Strong penalty for low-content chunks

# Regex for form-label lines:
#   "SomeLabel: ______"  or  "SomeLabel:_____"  or  "Label: "
#   Also matches lines that are all underscores/dashes/dots (separator lines)
_FORM_LABEL_RE = re.compile(
    r"^"
    r"(?:"
    r"[A-Za-z0-9 ''\-/()]+[:]\s*[_\-\.]{2,}"  # Label: _____
    r"|[A-Za-z0-9 ''\-/()]+[:]\s*$"             # Label:  (empty value)
    r"|[_\-\.=]{4,}"                              # Separator lines: ____ or ---- or ....
    r"|[A-Za-z0-9 ''\-/()]+[:]\s*\[?\s*\]?\s*$"  # Label: [] (checkbox)
    r")"
    r"$",
    re.MULTILINE,
)

# Regex for FILLED label-value lines:
#   "By: Contoso Ltd." or "Authorized Representative: Fabrikam Inc."
#   Matches "Label: NonBlankValue" where the value starts with a word character.
#   Used to exempt short-but-meaningful structured content from _min_content_penalty.
_FILLED_LABEL_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9 /\-()']+:\s*[A-Za-z0-9]",
    re.MULTILINE,
)

# Regex for purely structural/whitespace content
_STRUCTURAL_RE = re.compile(r"^[\s_\-\.=:|\[\]()]+$")


# ---------------------------------------------------------------------------
# Individual filter functions
# ---------------------------------------------------------------------------

def _form_label_penalty(text: str) -> float:
    """Return penalty multiplier for form-label dominated chunks.

    Splits text into lines and checks what fraction matches form-label
    patterns.  If the ratio exceeds FORM_LABEL_LINE_RATIO, returns
    FORM_LABEL_PENALTY; otherwise 1.0.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return BARE_HEADING_PENALTY  # empty → treat as bare heading
    
    form_lines = sum(1 for ln in lines if _FORM_LABEL_RE.match(ln))
    ratio = form_lines / len(lines)
    
    if ratio >= FORM_LABEL_LINE_RATIO:
        return FORM_LABEL_PENALTY
    return 1.0


def _bare_heading_penalty(text: str) -> float:
    """Return penalty if the chunk has fewer than BARE_HEADING_CHAR_THRESHOLD
    substantive characters (after stripping blanks, underscores, punctuation).
    """
    # Strip whitespace, underscores, dashes, dots, colons, pipe chars
    substantive = re.sub(r"[\s_\-\.=:|/\[\]()\#\*>`]+", "", text)
    if len(substantive) < BARE_HEADING_CHAR_THRESHOLD:
        return BARE_HEADING_PENALTY
    return 1.0


def _min_content_penalty(text: str) -> float:
    """Return penalty if estimated token count is below MIN_CONTENT_TOKENS.

    Short chunks that contain filled label-value pairs (e.g. ``By: Contoso Ltd.``,
    ``Authorized Representative: Fabrikam Inc.``) are **exempted** from the
    penalty.  These are entity-bearing structured content (signature blocks,
    populated form fields), not blank form noise.
    """
    # Fast estimate: ~4 chars per token
    est_tokens = len(text) // 4 + 1
    if est_tokens >= MIN_CONTENT_TOKENS:
        return 1.0
    # Exempt short chunks that carry filled structured content
    if _FILLED_LABEL_RE.search(text):
        return 1.0
    return LOW_CONTENT_PENALTY


# ---------------------------------------------------------------------------
# Composite scorer
# ---------------------------------------------------------------------------

_FILTERS = [
    ("form_label", _form_label_penalty),
    ("bare_heading", _bare_heading_penalty),
    ("min_content", _min_content_penalty),
]


def compute_noise_penalty(text: str) -> float:
    """Compute the combined noise penalty for a chunk's text.

    Returns a multiplier in (0, 1] that should be applied to the chunk's
    entity score.  1.0 = clean chunk, <1.0 = noisy.
    """
    penalty = 1.0
    for _name, fn in _FILTERS:
        penalty *= fn(text)
    return penalty


def apply_noise_filters(
    chunks: List[Dict[str, Any]],
    score_key: str = "_entity_score",
) -> Dict[str, Any]:
    """Apply noise penalties to a list of chunks **in place**.

    For each chunk, `chunk[score_key]` is multiplied by the noise penalty.
    A `_noise_penalty` field is added to each chunk for observability.
    A `_noise_filters_hit` list is added with the names of filters that fired.

    Args:
        chunks: List of chunk dicts (must have `text` and `score_key`).
        score_key: Key holding the relevance score to penalise.

    Returns:
        Dict with per-filter counts and total penalised count:
        {
            "total_penalised": int,
            "form_label": int,
            "bare_heading": int,
            "min_content": int,
        }
    """
    filter_counts: Dict[str, int] = {name: 0 for name, _fn in _FILTERS}
    penalised = 0
    for chunk in chunks:
        text = chunk.get("text", "")
        combined_penalty = 1.0
        filters_hit: List[str] = []
        for name, fn in _FILTERS:
            p = fn(text)
            if p < 1.0:
                filter_counts[name] += 1
                filters_hit.append(name)
            combined_penalty *= p
        chunk["_noise_penalty"] = combined_penalty
        chunk["_noise_filters_hit"] = filters_hit
        if combined_penalty < 1.0:
            original = chunk.get(score_key, 0.0)
            chunk[score_key] = original * combined_penalty
            penalised += 1
    return {"total_penalised": penalised, **filter_counts}
