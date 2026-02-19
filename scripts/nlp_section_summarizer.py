"""NLP-based section summarization for comparison against LLM summaries.

Provides two strategies:
  1. TF-IDF keyword extraction (corpus-wide IDF, bigram-inclusive)
  2. TextRank sentence extraction (PageRank on intra-section similarity graph)

Both are deterministic, require no LLM API calls, and use only sklearn + networkx
(already in project requirements).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine


# ---------------------------------------------------------------------------
# 1. TF-IDF keyword extraction
# ---------------------------------------------------------------------------

def generate_tfidf_summaries(
    sections: List[Dict[str, Any]],
    top_n: int = 15,
    ngram_range: Tuple[int, int] = (1, 2),
    max_df: float = 0.85,
    min_df: int = 1,
) -> Dict[str, str]:
    """Generate keyword-based summaries using TF-IDF.

    Fits a TfidfVectorizer across ALL sections (corpus-wide IDF),
    then extracts top_n keywords per section ordered by TF-IDF weight.

    Args:
        sections: List of dicts with keys ``id``, ``title``, ``path_key``,
            ``chunk_texts`` (list of raw text strings from the section's
            TextChunks).
        top_n: Number of top keywords to extract per section.
        ngram_range: (min_n, max_n) for n-gram extraction.
        max_df: Ignore terms appearing in more than this fraction of sections.
        min_df: Minimum number of sections a term must appear in.

    Returns:
        Dict mapping section_id -> keyword summary string.
    """
    corpus: List[str] = []
    section_ids: List[str] = []
    for sec in sections:
        text = " ".join(ct for ct in (sec.get("chunk_texts") or []) if ct)
        text = re.sub(r"\s+", " ", text).strip()
        corpus.append(text)
        section_ids.append(sec["id"])

    if not corpus or all(not t for t in corpus):
        return {}

    vectorizer = TfidfVectorizer(
        ngram_range=ngram_range,
        max_df=max_df,
        min_df=min_df,
        stop_words="english",
        sublinear_tf=True,  # log(1 + tf) — prevents long sections dominating
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        # All documents are empty or only stop-words
        return {}

    feature_names = vectorizer.get_feature_names_out()

    summaries: Dict[str, str] = {}
    for i, sec_id in enumerate(section_ids):
        row = tfidf_matrix[i].toarray().flatten()
        top_indices = row.argsort()[-top_n:][::-1]
        keywords = [feature_names[idx] for idx in top_indices if row[idx] > 0]
        summaries[sec_id] = ", ".join(keywords)

    return summaries


# ---------------------------------------------------------------------------
# 2. TextRank sentence extraction
# ---------------------------------------------------------------------------

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _split_sentences(text: str, min_len: int = 20) -> List[str]:
    """Regex sentence splitter (no spaCy dependency).

    Splits on sentence-ending punctuation followed by whitespace and an
    uppercase letter.  Filters fragments shorter than *min_len* chars.
    """
    raw = _SENT_SPLIT_RE.split(text.strip())
    return [s.strip() for s in raw if len(s.strip()) >= min_len]


def generate_textrank_summaries(
    sections: List[Dict[str, Any]],
    num_sentences: int = 2,
) -> Dict[str, str]:
    """Extract the most central sentence(s) per section via TextRank.

    Builds a sentence similarity graph (TF-IDF cosine) within each section,
    then runs PageRank to find the most "central" sentence(s).

    Args:
        sections: Same format as :func:`generate_tfidf_summaries`.
        num_sentences: Number of top sentences to extract per section.

    Returns:
        Dict mapping section_id -> extracted sentence(s) joined by space.
    """
    import networkx as nx  # already in requirements (networkx==3.4.2)

    summaries: Dict[str, str] = {}
    for sec in sections:
        all_text = " ".join(ct for ct in (sec.get("chunk_texts") or []) if ct)
        sentences = _split_sentences(all_text)

        if not sentences:
            summaries[sec["id"]] = ""
            continue

        if len(sentences) <= num_sentences:
            summaries[sec["id"]] = " ".join(sentences)
            continue

        # Build per-section TF-IDF vectors for sentences
        vec = TfidfVectorizer(stop_words="english")
        try:
            sent_matrix = vec.fit_transform(sentences)
        except ValueError:
            summaries[sec["id"]] = sentences[0] if sentences else ""
            continue

        # Cosine similarity graph
        sim_matrix = sklearn_cosine(sent_matrix)
        # Zero out self-loops
        np.fill_diagonal(sim_matrix, 0.0)

        G = nx.from_numpy_array(sim_matrix)
        scores = nx.pagerank(G, max_iter=200)

        # Top sentences by PageRank, preserving original document order
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_indices = sorted([idx for idx, _ in ranked[:num_sentences]])
        summaries[sec["id"]] = " ".join(sentences[i] for i in top_indices)

    return summaries


# ---------------------------------------------------------------------------
# 3. Structural text builder (mirrors lazygraphrag_pipeline.py:3634-3648)
# ---------------------------------------------------------------------------

def build_structural_text(
    title: str,
    path_key: str,
    summary: str,
    max_chars: int = 600,
) -> str:
    """Combine title + path_key + summary into the text to embed.

    Mirrors the logic in ``lazygraphrag_pipeline.py:3634-3648``:
    - Deduplicates when title is the last segment of path_key
    - Appends summary with " — " separator
    - Caps at *max_chars* for the embedding model
    """
    title = (title or "").strip()
    path_key = (path_key or "").strip()
    summary = (summary or "").strip()

    if path_key and title and path_key.endswith(title):
        header_text = path_key
    else:
        parts = [p for p in [title, path_key] if p]
        header_text = " | ".join(parts) if parts else "[Untitled Section]"

    if summary:
        combined = f"{header_text} — {summary}"
    else:
        combined = header_text

    return combined[:max_chars]


# ---------------------------------------------------------------------------
# 4. Cosine similarity helper
# ---------------------------------------------------------------------------

def cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    a_arr, b_arr = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)
