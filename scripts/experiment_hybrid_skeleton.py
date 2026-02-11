#!/usr/bin/env python3
"""
Phase 0: Hybrid Skeleton Experiment — Deterministic Structure + Sparse k-NN

Tests the "Mature Hybrid Processing Pipeline" approach:
  1. Deterministic skeleton: Sentence/Paragraph nodes with NEXT, PREV, PART_OF edges
  2. Semantic embedding: Voyage-context-3 vectors per sentence
  3. Sparse semantic linking: RELATED_TO edges only where similarity > threshold
  4. Three-stage retrieval: Semantic Anchor → Context Expansion → Re-ranking

Content taxonomy (informed by Azure DI output analysis + industry research):
  EMBED as SentenceNodes:
    - Body text paragraphs → spaCy sentence splitting (NOT regex)
    - Table rows → linearized "Header: value | Header: value"
    - Figure captions → text from DI figure extraction
    - Figure summaries → CU enableFigureDescription (Phase 2)
    - Equations → CU LaTeX or pix2tex (Phase 2)
  Store as METADATA only (not embedded):
    - Key-Value Pairs (KVPs) — already in body text; use for exact lookup
    - Titles / Section headings — stored as section_path on child sentences
    - Page headers / footers — dropped by DI paragraph role filter
    - Barcodes — identifiers for exact-match filter
    - Selection marks — boolean flags on parent paragraph

Architecture:
  DI (primary) → OCR, tables, KVPs, sections, word geometry, barcodes
                  ↓
                chunk text → spaCy → full SentenceNodes
  CU (Phase 2)  → ONLY for figure descriptions + equation LaTeX
                  ↓
                SentenceNodes (source="figure_description" / "equation")

Key design principles:
  - spaCy for sentence detection (handles abbreviations: P.O., Inc., Ltd., FL.)
  - DI regex sentence splitting is replaced — it mis-splits at abbreviation periods
  - Cross-chunk dedup prevents duplicate sentences from overlapping chunks
  - Metadata-driven context: "sentence search, paragraph display" pattern
  - Edge budget: O(n) not O(n²) — only RELATED_TO uses similarity

This is a READ-ONLY experiment — no production changes.
Pulls existing chunk/sentence metadata from Neo4j, creates in-memory graph,
embeds at multiple granularities, and compares retrieval precision.

Usage:
    python scripts/experiment_hybrid_skeleton.py
    python scripts/experiment_hybrid_skeleton.py --group-id test-5pdfs-v2-fix2
    python scripts/experiment_hybrid_skeleton.py --similarity-threshold 0.90 --top-k 5

Requirements:
    pip install neo4j numpy voyageai python-dotenv spacy
    python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import spacy

# Suppress spaCy model version warnings (transitive dep via graphrag)
warnings.filterwarnings("ignore", message=".*W095.*")

# ---------------------------------------------------------------------------
# Setup path for project imports
# ---------------------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
SERVICE_ROOT = PROJECT_ROOT / "graphrag-orchestration"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(SERVICE_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")

VOYAGE_MODEL = "voyage-context-3"
VOYAGE_DIM = 2048

# --- Sentence quality thresholds ---
# We need FULL sentences (not half-sentences split at abbreviation periods).
# spaCy handles abbreviations correctly; these filters are for post-cleanup.
MIN_SENTENCE_CHARS = 30      # Up from 20 — kills more label fragments
MIN_SENTENCE_WORDS = 5       # Up from 4 — requires real sentence structure
MIN_TABLE_ROW_CHARS = 15     # Lower bar for table rows (structured data)

# DI paragraph roles to SKIP (not embeddable content)
SKIP_ROLES = {"pageHeader", "pageFooter", "pageNumber", "title", "sectionHeading"}

# Patterns for noise/label detection
FORM_LABEL_RE = re.compile(
    r"^[A-Z][^.!?]*:\s*[A-Z][a-z]",  # "Key: Value" pattern with proper noun value
)
KVP_PATTERN_RE = re.compile(
    r"^(name|date|address|phone|email|signature|title|page|total|amount|number|id|ref|no\.?|signed|owner|agent|customer)\s*[:_\-#]?\s*$",
    re.IGNORECASE,
)
ALL_CAPS_RE = re.compile(r"^[A-Z\s\d.,!?:;\-()]+$")

# --- spaCy NLP model ---
# Already installed as transitive dependency via graphrag==2.7.0
# Handles abbreviation periods correctly: "Contoso Ltd. is located at P.O. Box 123" = 1 sentence
try:
    NLP = spacy.load("en_core_web_sm")
    NLP.max_length = 50000  # Allow larger chunks
    print("  🧠 spaCy en_core_web_sm loaded for sentence detection")
except OSError:
    print("  ⚠️  spaCy model not found, downloading en_core_web_sm...")
    import subprocess
    subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"], check=True)
    NLP = spacy.load("en_core_web_sm")
    NLP.max_length = 50000


# ---------------------------------------------------------------------------
# Data Models — In-Memory Hybrid Skeleton
# ---------------------------------------------------------------------------
@dataclass
class SentenceNode:
    """A sentence-level node in the skeleton graph.

    Metadata design ("unified node" pattern from industry best practice):
    Each sentence node is a self-contained unit carrying:
      - Its own text + embedding (for semantic search via Voyage)
      - Parent paragraph text (for "sentence search, paragraph display")
      - Structural pointers: prev/next sentence IDs (for context window)
      - Provenance: doc_id, chunk_id, section_path, page, confidence
      - Source type tag for content-type-aware retrieval

    This ensures Voyage semantic search + graph traversal operate on the SAME
    node without requiring joins or separate metadata lookups.

    Why this matters for alignment (from the discussion):
      - Voyage handles semantic proximity (meaning) via its own k-NN internally
      - Graph edges handle structural proximity (document flow) deterministically
      - Both reference the same sentence node → no misalignment, no noise
    """
    id: str
    text: str
    doc_id: str
    chunk_id: str  # Parent TextChunk
    section_path: str  # Section hierarchy
    source: str  # "paragraph" | "table_row" | "figure_caption" | "figure_description" | "equation"
    index_in_chunk: int  # Position within parent chunk
    page: Optional[int] = None
    confidence: float = 1.0
    embedding: Optional[np.ndarray] = None
    tokens: int = 0

    # --- Metadata for "sentence search, paragraph display" pattern ---
    parent_paragraph_id: Optional[str] = None  # ParagraphNode ID
    parent_paragraph_text: Optional[str] = None  # Full paragraph for LLM context
    prev_sentence_id: Optional[str] = None  # Deterministic PREV pointer
    next_sentence_id: Optional[str] = None  # Deterministic NEXT pointer

    # --- Provenance for hallucination control ---
    char_offset: Optional[int] = None  # Character offset in source document
    char_length: Optional[int] = None  # Character length in source document
    polygons: Optional[List[List[float]]] = None  # Pixel-accurate highlighting

    def __post_init__(self):
        self.tokens = len(self.text.split())

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Export metadata for Neo4j node properties or vector DB payload.

        This is the "unified metadata" that aligns semantic search (Voyage)
        with structural search (graph) on the same node — the key insight
        from the discussion about avoiding separate embedding spaces.
        """
        return {
            "sentence_id": self.id,
            "text": self.text,
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "section_path": self.section_path,
            "source": self.source,
            "index_in_chunk": self.index_in_chunk,
            "page": self.page,
            "confidence": self.confidence,
            "tokens": self.tokens,
            "parent_paragraph_id": self.parent_paragraph_id,
            "parent_paragraph_text": self.parent_paragraph_text,
            "prev_sentence_id": self.prev_sentence_id,
            "next_sentence_id": self.next_sentence_id,
        }


@dataclass
class ParagraphNode:
    """A paragraph-level node (groups of sequential sentences)."""
    id: str
    text: str
    doc_id: str
    chunk_id: str
    section_path: str
    section_id: Optional[str] = None  # Link to SectionRef for PART_OF hierarchy
    sentence_ids: List[str] = field(default_factory=list)
    embedding: Optional[np.ndarray] = None


@dataclass
class SectionRef:
    """Lightweight section reference for the deterministic hierarchy.

    The full hierarchy parsed from document structure is:
      SENTENCE ─PART_OF→ PARAGRAPH ─PART_OF→ SECTION ─PART_OF→ DOCUMENT

    Section nodes already exist in Neo4j (created by _build_section_graph).
    This mirrors them in the in-memory skeleton so the complete deterministic
    chain is navigable without Neo4j round-trips.
    """
    id: str
    path_key: str  # e.g. "Section 1 > 1.2 > Definitions"
    doc_id: str
    parent_section_id: Optional[str] = None  # For SUBSECTION_OF hierarchy
    chunk_ids: List[str] = field(default_factory=list)
    paragraph_ids: List[str] = field(default_factory=list)


@dataclass
class SkeletonEdge:
    """An edge in the skeleton graph."""
    source_id: str
    target_id: str
    edge_type: str  # NEXT, PREV, PART_OF, RELATED_TO
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HybridSkeleton:
    """Full in-memory hybrid skeleton graph.

    Deterministic hierarchy (all edges are PART_OF, parsed from document structure):
      SENTENCE ─PART_OF→ PARAGRAPH ─PART_OF→ SECTION ─PART_OF→ DOCUMENT

    Reading order (deterministic, from document parsing):
      SENTENCE ─NEXT→ SENTENCE

    Semantic layer (probabilistic, from k-NN on embeddings — added separately):
      SENTENCE ─RELATED_TO→ SENTENCE
    """
    sentences: Dict[str, SentenceNode] = field(default_factory=dict)
    paragraphs: Dict[str, ParagraphNode] = field(default_factory=dict)
    sections: Dict[str, SectionRef] = field(default_factory=dict)
    edges: List[SkeletonEdge] = field(default_factory=list)
    chunks: Dict[str, Dict] = field(default_factory=dict)  # Original TextChunk data

    # Adjacency index for fast traversal
    _adj: Dict[str, List[SkeletonEdge]] = field(default_factory=dict, repr=False)

    def add_edge(self, edge: SkeletonEdge):
        self.edges.append(edge)
        self._adj.setdefault(edge.source_id, []).append(edge)
        # For undirected traversal, add reverse
        if edge.edge_type in ("NEXT", "RELATED_TO"):
            reverse = SkeletonEdge(
                source_id=edge.target_id,
                target_id=edge.source_id,
                edge_type="PREV" if edge.edge_type == "NEXT" else "RELATED_TO",
                weight=edge.weight,
                metadata=edge.metadata,
            )
            self._adj.setdefault(edge.target_id, []).append(reverse)

    def neighbors(self, node_id: str, edge_types: Optional[List[str]] = None) -> List[Tuple[str, SkeletonEdge]]:
        """Get neighbors of a node, optionally filtered by edge type."""
        result = []
        for edge in self._adj.get(node_id, []):
            if edge_types is None or edge.edge_type in edge_types:
                result.append((edge.target_id, edge))
        return result

    @property
    def stats(self) -> Dict[str, Any]:
        edge_type_counts = {}
        for e in self.edges:
            edge_type_counts[e.edge_type] = edge_type_counts.get(e.edge_type, 0) + 1

        n_sentences = len(self.sentences)
        n_deterministic = sum(v for k, v in edge_type_counts.items() if k in ("NEXT", "PREV", "PART_OF"))
        n_semantic = edge_type_counts.get("RELATED_TO", 0)

        return {
            "sentences": n_sentences,
            "paragraphs": len(self.paragraphs),
            "sections": len(self.sections),
            "chunks": len(self.chunks),
            "edges_total": len(self.edges),
            "edges_deterministic": n_deterministic,
            "edges_semantic (RELATED_TO)": n_semantic,
            "edge_types": edge_type_counts,
            # Edge budget analysis:
            #   Deterministic edges are O(n): each sentence has ≤1 NEXT, ≤1 PREV, 1-2 PART_OF
            #   Semantic edges must be bounded by max_related_per_sentence (default 2)
            #   Total semantic edges should be ≤ 2*n_sentences for sparsity
            "edge_budget_ratio": round(n_semantic / max(n_sentences, 1), 2),
            "edge_budget_ok": n_semantic <= 2 * n_sentences,
            # Metadata completeness — critical for "sentence search, paragraph display"
            "metadata_paragraph_text_pct": round(
                sum(1 for s in self.sentences.values() if s.parent_paragraph_text) / max(n_sentences, 1) * 100, 1
            ),
            "metadata_prev_next_pct": round(
                sum(1 for s in self.sentences.values() if s.prev_sentence_id or s.next_sentence_id) / max(n_sentences, 1) * 100, 1
            ),
        }


# ---------------------------------------------------------------------------
# Step 1: Extract Data from Neo4j
# ---------------------------------------------------------------------------
def extract_chunks_from_neo4j(group_id: str) -> List[Dict[str, Any]]:
    """Pull TextChunk nodes with metadata from Neo4j."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    chunks = []

    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:TextChunk {group_id: $group_id})-[:IN_DOCUMENT]->(d:Document)
            OPTIONAL MATCH (c)-[:IN_SECTION]->(s:Section)
            RETURN c.id AS chunk_id,
                   c.text AS text,
                   c.metadata AS metadata,
                   c.tokens AS tokens,
                   c.embedding_v2 AS embedding_v2,
                   d.id AS doc_id,
                   d.title AS doc_title,
                   s.path_key AS section_path,
                   s.id AS section_id
            ORDER BY d.id, c.chunk_index
            """,
            group_id=group_id,
        )
        for record in result:
            chunks.append({
                "chunk_id": record["chunk_id"],
                "text": record["text"],
                "metadata": json.loads(record["metadata"]) if isinstance(record["metadata"], str) else (record["metadata"] or {}),
                "tokens": record["tokens"],
                "embedding_v2": record["embedding_v2"],
                "doc_id": record["doc_id"],
                "doc_title": record["doc_title"],
                "section_path": record["section_path"] or "[Document Root]",
                "section_id": record["section_id"],
            })

    driver.close()
    print(f"  📦 Extracted {len(chunks)} TextChunks from Neo4j")
    return chunks


# ---------------------------------------------------------------------------
# Step 2: Build Deterministic Skeleton (Sentences + Structure)
# ---------------------------------------------------------------------------
def _is_noise_sentence(text: str, min_chars: int = MIN_SENTENCE_CHARS) -> bool:
    """Filter out noise: very short fragments, pure labels, numeric-only content.

    Post-spaCy cleanup — spaCy handles sentence boundaries correctly but
    the chunk text still contains form labels, structural fragments, and
    numeric-only table cells that aren't useful for embedding.
    """
    text = text.strip()
    if len(text) < min_chars:
        return True
    if len(text.split()) < MIN_SENTENCE_WORDS:
        return True
    if KVP_PATTERN_RE.match(text):
        return True
    # ALL CAPS short text = header/label that leaked through
    if ALL_CAPS_RE.match(text) and len(text.split()) < 10:
        return True
    # Numeric-only content (table cells like "12,450.00")
    cleaned = re.sub(r'[\d,.$%\s\-/·•]', '', text)
    if len(cleaned) < 10:
        return True
    return False


def _is_kvp_label(text: str) -> bool:
    """Detect form-style 'Key: Value' patterns that are short and label-like.

    These exist in body text AND as DI KVPs — no need to embed them twice.
    KVPs are stored as structured metadata for exact-match lookup instead.
    """
    if FORM_LABEL_RE.match(text) and len(text.split()) < 8:
        return True
    return False


def _clean_chunk_text_for_spacy(chunk_text: str) -> str:
    """Clean chunk text before spaCy processing.

    DI chunk text is markdown-formatted. We need to:
    1. Strip markdown headers (# Title) — these are section labels, not sentences
    2. Strip <figure> blocks — figures handled separately
    3. Collapse excessive whitespace
    4. Remove bullet markers that confuse sentence detection
    """
    # Strip markdown headers (already captured in section_path metadata)
    text = re.sub(r'^#+\s+.*$', '', chunk_text, flags=re.MULTILINE)
    # Strip <figure> blocks
    text = re.sub(r'<figure>.*?</figure>', '', text, flags=re.DOTALL)
    # Strip numbered list markers: "1." "2\."
    text = re.sub(r'^\d+\\\.\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    # Strip bullet markers
    text = re.sub(r'^[·•\-\*]\s+', '', text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _extract_sentences_from_chunk(chunk: Dict) -> List[Dict[str, Any]]:
    """Extract sentence units from chunk using spaCy + DI table metadata.

    Architecture (from DI content taxonomy analysis):
      EMBED as SentenceNodes:
        - Body text → spaCy sentence splitting (handles abbreviations correctly)
        - Table rows → linearized from DI metadata (source="table_row")
        - Figure captions → from DI metadata (source="figure_caption")
        - Figure descriptions → Phase 2: CU enableFigureDescription
        - Equations → Phase 2: CU LaTeX or pix2tex
      NOT embedded (metadata only):
        - KVPs, titles, headers/footers, barcodes, selection marks

    Why spaCy replaces regex:
      DI regex "(?<=[.!?])\\s+" mis-splits at abbreviation periods:
        "Contoso Ltd. is located at P.O. Box 123" → 3 fragments
      spaCy keeps it as one sentence.
    """
    sentences = []
    metadata = chunk.get("metadata", {})
    chunk_text = chunk.get("text", "")
    idx = 0

    # ─── Source A: Body text → spaCy sentence detection ───────────────
    clean_text = _clean_chunk_text_for_spacy(chunk_text)
    if clean_text:
        doc = NLP(clean_text)
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if not sent_text:
                continue
            if _is_noise_sentence(sent_text):
                continue
            if _is_kvp_label(sent_text):
                continue
            sentences.append({
                "text": sent_text,
                "source": "paragraph",
                "index": idx,
            })
            idx += 1

    # ─── Source B: Table rows from DI metadata ────────────────────────
    # DI extracts tables with headers+rows. Each row is linearized as
    # "Header1: val1 | Header2: val2" — this IS retrievable content.
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
                # Build linearized row text
                parts = []
                for header in headers:
                    val = row.get(header, "").strip()
                    if val:
                        parts.append(f"{header}: {val}")
                if not parts:
                    continue
                row_text = " | ".join(parts)
                if _is_noise_sentence(row_text, min_chars=MIN_TABLE_ROW_CHARS):
                    continue
                sentences.append({
                    "text": row_text,
                    "source": "table_row",
                    "index": idx,
                })
                idx += 1

    # Also check DI metadata.sentences for source="table" rows
    # (these come from _extract_table_row_sentences in the DI service)
    di_sentences = metadata.get("sentences", [])
    if isinstance(di_sentences, list):
        for ts in di_sentences:
            if isinstance(ts, dict) and ts.get("source") == "table":
                text = ts.get("text", "")
                if text and not _is_noise_sentence(text, min_chars=MIN_TABLE_ROW_CHARS):
                    # Dedup against table rows already extracted above
                    already_exists = any(
                        s["text"] == text or text in s["text"] or s["text"] in text
                        for s in sentences if s["source"] == "table_row"
                    )
                    if not already_exists:
                        sentences.append({
                            "text": text,
                            "source": "table_row",
                            "index": idx,
                            "page": ts.get("page"),
                            "confidence": ts.get("confidence", 0.9),
                        })
                        idx += 1

    # ─── Source C: Figure captions from DI metadata ───────────────────
    # DI detects figures with captions + footnotes. The caption text is
    # embeddable; the image itself is metadata (for frontend display).
    figures = metadata.get("figures", [])
    if isinstance(figures, list):
        for fig in figures:
            if not isinstance(fig, dict):
                continue
            caption = fig.get("caption", "").strip()
            if caption and not _is_noise_sentence(caption, min_chars=15):
                sentences.append({
                    "text": caption,
                    "source": "figure_caption",
                    "index": idx,
                })
                idx += 1
            # Also embed footnotes if substantial
            for fn in fig.get("footnotes", []):
                if isinstance(fn, str) and len(fn.strip()) >= 20:
                    sentences.append({
                        "text": fn.strip(),
                        "source": "figure_caption",
                        "index": idx,
                    })
                    idx += 1

    # ─── Phase 2 stubs (architecture-ready, not called yet) ───────────
    # Figure descriptions: CU enableFigureDescription → natural language
    # summary of visual content. Would add source="figure_description".
    # Equations: CU LaTeX output or pix2tex library → context + LaTeX
    # merged into one sentence. Would add source="equation".
    # Both integrate as standard SentenceNodes — no special treatment.

    return sentences


def build_skeleton(chunks: List[Dict]) -> HybridSkeleton:
    """Build the deterministic skeleton graph from extracted chunks.

    Edge creation strategy (from the discussion — this is critical):
    - NEXT/PREV: Deterministic, based on sentence order. NEVER use k-NN.
    - PART_OF: Deterministic, based on document structure. NEVER use k-NN.
    - RELATED_TO: Added LATER in build_sparse_semantic_links() with strict
      threshold + budget controls. This is the ONLY place k-NN is used.

    Metadata wiring:
    - Each sentence gets prev_sentence_id / next_sentence_id pointers
    - Each sentence gets parent_paragraph_text for "sentence search, paragraph display"
    - This means retrieval can grab context without extra graph hops

    Creates:
    - SentenceNode for each extracted sentence (with full metadata)
    - ParagraphNode for groups of sequential sentences from same source
    - SectionRef for each distinct section (mirrors Neo4j :Section nodes)
    - NEXT edges between sequential sentences within same chunk
    - PART_OF edges: Sentence→Paragraph, Paragraph→Section, Sentence→Chunk

    Full deterministic hierarchy (no algorithms, pure document parsing):
      SENTENCE ─PART_OF→ PARAGRAPH ─PART_OF→ SECTION
      SENTENCE ─NEXT→ SENTENCE
    """
    skeleton = HybridSkeleton()

    # Cross-chunk dedup: WARRANTY doc has duplicate chunks (2/5, 3/6, 4/7).
    # Normalize text → set lookup prevents duplicate SentenceNodes across chunks.
    global_seen: Set[str] = set()

    def _normalize_for_dedup(text: str) -> str:
        """Lowercase, collapse whitespace, strip punctuation for dedup."""
        t = text.lower().strip()
        t = re.sub(r'\s+', ' ', t)
        t = re.sub(r'[^\w\s]', '', t)
        return t

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        doc_id = chunk["doc_id"]
        section_path = chunk["section_path"]
        section_id = chunk.get("section_id")  # From Neo4j query

        skeleton.chunks[chunk_id] = chunk

        # --- Create/reuse SectionRef (one per distinct section) ---
        if section_id and section_id not in skeleton.sections:
            skeleton.sections[section_id] = SectionRef(
                id=section_id,
                path_key=section_path,
                doc_id=doc_id,
                chunk_ids=[chunk_id],
            )
        elif section_id:
            if chunk_id not in skeleton.sections[section_id].chunk_ids:
                skeleton.sections[section_id].chunk_ids.append(chunk_id)

        raw_sentences = _extract_sentences_from_chunk(chunk)
        if not raw_sentences:
            continue

        # Cross-chunk dedup: skip sentences already seen in earlier chunks
        deduped_sentences = []
        for sent_info in raw_sentences:
            norm = _normalize_for_dedup(sent_info["text"])
            if norm in global_seen:
                continue
            global_seen.add(norm)
            deduped_sentences.append(sent_info)
        raw_sentences = deduped_sentences

        if not raw_sentences:
            continue

        prev_sentence_id = None
        current_para_sentences = []
        current_para_source = None
        chunk_sentence_ids = []  # Track all sentence IDs in this chunk for metadata wiring

        for idx, sent_info in enumerate(raw_sentences):
            sent_id = f"{chunk_id}__sent_{idx}"
            sent_node = SentenceNode(
                id=sent_id,
                text=sent_info["text"],
                doc_id=doc_id,
                chunk_id=chunk_id,
                section_path=section_path,
                source=sent_info["source"],
                index_in_chunk=idx,
                page=sent_info.get("page"),
                confidence=sent_info.get("confidence", 1.0),
                char_offset=sent_info.get("offset"),
                char_length=sent_info.get("length"),
                polygons=sent_info.get("polygons"),
            )
            skeleton.sentences[sent_id] = sent_node
            chunk_sentence_ids.append(sent_id)

            # PART_OF → parent chunk
            skeleton.add_edge(SkeletonEdge(
                source_id=sent_id,
                target_id=chunk_id,
                edge_type="PART_OF",
            ))

            # NEXT → previous sentence (within same chunk)
            # Also wire prev/next metadata pointers for direct access
            if prev_sentence_id is not None:
                skeleton.add_edge(SkeletonEdge(
                    source_id=prev_sentence_id,
                    target_id=sent_id,
                    edge_type="NEXT",
                ))
                # Wire metadata pointers (avoids graph hop at retrieval time)
                sent_node.prev_sentence_id = prev_sentence_id
                skeleton.sentences[prev_sentence_id].next_sentence_id = sent_id

            prev_sentence_id = sent_id

            # Group sentences into paragraphs by source type
            if sent_info["source"] == current_para_source:
                current_para_sentences.append(sent_id)
            else:
                if current_para_sentences:
                    _create_paragraph_node(skeleton, current_para_sentences, chunk_id, doc_id, section_path, current_para_source, section_id)
                current_para_sentences = [sent_id]
                current_para_source = sent_info["source"]

        # Flush last paragraph group
        if current_para_sentences:
            _create_paragraph_node(skeleton, current_para_sentences, chunk_id, doc_id, section_path, current_para_source, section_id)

    return skeleton


def _create_paragraph_node(
    skeleton: HybridSkeleton,
    sentence_ids: List[str],
    chunk_id: str,
    doc_id: str,
    section_path: str,
    source: str,
    section_id: Optional[str] = None,
):
    """Create a ParagraphNode that groups sequential sentences.

    Wires the deterministic hierarchy:
      SENTENCE ─PART_OF→ PARAGRAPH ─PART_OF→ SECTION

    Also wires parent_paragraph_text back to each sentence node.
    This enables the "sentence search, paragraph display" pattern — when
    Voyage finds a relevant sentence, the LLM gets the full paragraph
    context without an extra graph traversal.
    """
    if len(sentence_ids) < 1:
        return

    para_id = f"{chunk_id}__para_{sentence_ids[0].split('__sent_')[1]}"
    texts = [skeleton.sentences[sid].text for sid in sentence_ids]
    para_text = " ".join(texts)
    para_node = ParagraphNode(
        id=para_id,
        text=para_text,
        doc_id=doc_id,
        chunk_id=chunk_id,
        section_path=section_path,
        section_id=section_id,
        sentence_ids=sentence_ids,
    )
    skeleton.paragraphs[para_id] = para_node

    # PART_OF → parent chunk (implementation-level containment)
    skeleton.add_edge(SkeletonEdge(
        source_id=para_id,
        target_id=chunk_id,
        edge_type="PART_OF",
    ))

    # PART_OF → parent section (document-structure containment)
    # This completes the deterministic hierarchy:
    #   SENTENCE → PARAGRAPH → SECTION → DOCUMENT
    if section_id:
        skeleton.add_edge(SkeletonEdge(
            source_id=para_id,
            target_id=section_id,
            edge_type="PART_OF",
        ))
        # Track paragraph in section
        if section_id in skeleton.sections:
            skeleton.sections[section_id].paragraph_ids.append(para_id)

    # Each sentence PART_OF → paragraph + wire parent_paragraph_text metadata
    for sid in sentence_ids:
        skeleton.add_edge(SkeletonEdge(
            source_id=sid,
            target_id=para_id,
            edge_type="PART_OF",
        ))
        # Wire the "sentence search, paragraph display" metadata
        skeleton.sentences[sid].parent_paragraph_id = para_id
        skeleton.sentences[sid].parent_paragraph_text = para_text


# ---------------------------------------------------------------------------
# Step 3: Semantic Embedding (Voyage-context-3)
# ---------------------------------------------------------------------------
def embed_sentences(skeleton: HybridSkeleton) -> int:
    """Embed all sentence nodes with voyage-context-3.

    Uses contextualized_embed() - groups sentences by document so the model
    sees document context for each sentence embedding.
    """
    try:
        import voyageai
    except ImportError:
        print("  ⚠️  voyageai not installed — using random embeddings for structure testing")
        return _embed_random(skeleton)

    if not VOYAGE_API_KEY:
        print("  ⚠️  VOYAGE_API_KEY not set — using random embeddings for structure testing")
        return _embed_random(skeleton)

    client = voyageai.Client(api_key=VOYAGE_API_KEY)

    # Group sentences by document for contextualized embedding
    doc_sentences: Dict[str, List[SentenceNode]] = {}
    for sent in skeleton.sentences.values():
        doc_sentences.setdefault(sent.doc_id, []).append(sent)

    total_embedded = 0

    for doc_id, sents in doc_sentences.items():
        texts = [s.text for s in sents]
        if not texts:
            continue

        print(f"    📐 Embedding {len(texts)} sentences for doc {doc_id[:30]}...")

        try:
            # Voyage contextualized embedding — all sentences from same doc as context
            # contextualized_embed() requires inputs=[[sentences_list]] (list of documents,
            # where each document is a list of its text chunks/sentences)
            result = client.contextualized_embed(
                inputs=[texts],  # Single document containing all its sentences
                model=VOYAGE_MODEL,
                input_type="document",
                output_dimension=VOYAGE_DIM,
            )

            for sent, emb in zip(sents, result.results[0].embeddings):
                sent.embedding = np.array(emb, dtype=np.float32)
                total_embedded += 1

        except Exception as e:
            print(f"    ❌ Embedding error for doc {doc_id}: {e}")
            # Fall back to random for this doc
            for sent in sents:
                sent.embedding = np.random.randn(VOYAGE_DIM).astype(np.float32)
                sent.embedding /= np.linalg.norm(sent.embedding)
                total_embedded += 1

    return total_embedded


def _embed_random(skeleton: HybridSkeleton) -> int:
    """Fallback: assign random unit vectors for testing graph structure."""
    count = 0
    for sent in skeleton.sentences.values():
        sent.embedding = np.random.randn(VOYAGE_DIM).astype(np.float32)
        sent.embedding /= np.linalg.norm(sent.embedding)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Step 4: Sparse Semantic Linking (RELATED_TO with threshold)
# ---------------------------------------------------------------------------
def build_sparse_semantic_links(
    skeleton: HybridSkeleton,
    similarity_threshold: float = 0.90,
    max_related_per_sentence: int = 2,
    cross_chunk_only: bool = True,
) -> int:
    """Add RELATED_TO edges between semantically similar sentences.

    This is the "Sparse k-NN" step — only create edges where similarity
    exceeds a high threshold. This keeps the graph sparse while enabling
    semantic discovery of hidden cross-references.

    Args:
        skeleton: The hybrid skeleton with embedded sentences
        similarity_threshold: Minimum cosine similarity (default 0.90)
        max_related_per_sentence: Max RELATED_TO edges per sentence (default 2)
        cross_chunk_only: Only link sentences from different chunks (default True)

    Returns:
        Number of RELATED_TO edges created
    """
    sentences = [s for s in skeleton.sentences.values() if s.embedding is not None]
    if len(sentences) < 2:
        return 0

    # Build embedding matrix for efficient computation
    ids = [s.id for s in sentences]
    embeddings = np.vstack([s.embedding for s in sentences])

    # Normalize for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normed = embeddings / norms

    # Compute similarity matrix
    similarity_matrix = normed @ normed.T

    # Track edge counts per sentence
    edge_counts: Dict[str, int] = {}
    edges_created = 0

    # Find pairs above threshold
    for i in range(len(sentences)):
        if edge_counts.get(ids[i], 0) >= max_related_per_sentence:
            continue

        # Get top-k candidates for this sentence (sorted by similarity descending)
        sims = similarity_matrix[i]
        top_indices = np.argsort(sims)[::-1]

        for j in top_indices:
            if i == j:
                continue
            if sims[j] < similarity_threshold:
                break  # Sorted descending, so all remaining are below threshold

            if edge_counts.get(ids[i], 0) >= max_related_per_sentence:
                break
            if edge_counts.get(ids[j], 0) >= max_related_per_sentence:
                continue

            # Optional: only cross-chunk links
            if cross_chunk_only and sentences[i].chunk_id == sentences[j].chunk_id:
                continue

            skeleton.add_edge(SkeletonEdge(
                source_id=ids[i],
                target_id=ids[j],
                edge_type="RELATED_TO",
                weight=float(sims[j]),
                metadata={"similarity": round(float(sims[j]), 4)},
            ))
            edge_counts[ids[i]] = edge_counts.get(ids[i], 0) + 1
            edge_counts[ids[j]] = edge_counts.get(ids[j], 0) + 1
            edges_created += 1

    return edges_created


# ---------------------------------------------------------------------------
# Step 5: Three-Stage Retrieval
# ---------------------------------------------------------------------------
def embed_query(query: str) -> np.ndarray:
    """Embed a query string with Voyage contextualized_embed."""
    try:
        import voyageai
        if not VOYAGE_API_KEY:
            raise ImportError("no key")
        client = voyageai.Client(api_key=VOYAGE_API_KEY)
        result = client.contextualized_embed(
            inputs=[[query]],  # Single document with single chunk
            model=VOYAGE_MODEL,
            input_type="query",
            output_dimension=VOYAGE_DIM,
        )
        return np.array(result.results[0].embeddings[0], dtype=np.float32)
    except Exception:
        return np.random.randn(VOYAGE_DIM).astype(np.float32)


def stage1_semantic_anchor(
    skeleton: HybridSkeleton,
    query_embedding: np.ndarray,
    top_k: int = 5,
) -> List[Tuple[str, float]]:
    """Stage 1: Find top-k most relevant sentence nodes by cosine similarity.

    This is the "Semantic Anchor" — find the entry points into the graph.
    """
    sentences = [(sid, s) for sid, s in skeleton.sentences.items() if s.embedding is not None]
    if not sentences:
        return []

    # Vectorized cosine similarity
    embeddings = np.vstack([s.embedding for _, s in sentences])
    norms = np.linalg.norm(embeddings, axis=1)
    norms[norms == 0] = 1.0
    query_norm = np.linalg.norm(query_embedding)
    if query_norm == 0:
        return []

    similarities = (embeddings @ query_embedding) / (norms * query_norm)
    top_indices = np.argsort(similarities)[::-1][:top_k]

    return [(sentences[i][0], float(similarities[i])) for i in top_indices]


def stage2_context_expansion(
    skeleton: HybridSkeleton,
    anchor_sentence_ids: List[str],
    expand_window: int = 2,
) -> Dict[str, Dict[str, Any]]:
    """Stage 2: Context Expansion — "sentence search, paragraph display".

    This implements the key retrieval pattern from the discussion:
    - Voyage found precise sentences (Stage 1 anchors)
    - Now we expand context using METADATA FIRST, graph traversal SECOND

    Context assembly order:
    1. Use parent_paragraph_text metadata (zero-hop: already on the node)
    2. Use prev/next_sentence_id metadata (zero-hop: already on the node)
    3. Follow NEXT/PREV edges for wider window (1-2 hops)
    4. Follow RELATED_TO edges for cross-chunk discovery (sparse semantic)

    This means most context is assembled without graph traversal — the
    metadata pointers make it a simple dict lookup.

    Returns dict of chunk_id → {text, sentences, paragraphs, doc_id, section_path, score}
    """
    expanded_chunks: Dict[str, Dict[str, Any]] = {}

    for sent_id in anchor_sentence_ids:
        if sent_id not in skeleton.sentences:
            continue

        sent = skeleton.sentences[sent_id]

        # ---- Priority 1: Metadata-driven context (zero graph hops) ----
        context_sentences = {sent_id}
        paragraph_texts = set()

        # Parent paragraph text — the "paragraph display" from "sentence search, paragraph display"
        if sent.parent_paragraph_text:
            paragraph_texts.add(sent.parent_paragraph_text)

        # Immediate prev/next from metadata pointers (no graph hop needed)
        if sent.prev_sentence_id and sent.prev_sentence_id in skeleton.sentences:
            context_sentences.add(sent.prev_sentence_id)
        if sent.next_sentence_id and sent.next_sentence_id in skeleton.sentences:
            context_sentences.add(sent.next_sentence_id)

        # ---- Priority 2: Graph traversal for wider window ----
        # NEXT edges (expand forward)
        current = sent_id
        for _ in range(expand_window):
            neighbors = skeleton.neighbors(current, ["NEXT"])
            if neighbors:
                next_id = neighbors[0][0]
                if next_id in skeleton.sentences:
                    context_sentences.add(next_id)
                    current = next_id
                else:
                    break
            else:
                break

        # PREV edges (expand backward)
        current = sent_id
        for _ in range(expand_window):
            neighbors = skeleton.neighbors(current, ["PREV"])
            if neighbors:
                prev_id = neighbors[0][0]
                if prev_id in skeleton.sentences:
                    context_sentences.add(prev_id)
                    current = prev_id
                else:
                    break
            else:
                break

        # ---- Priority 3: Sparse semantic links (RELATED_TO) ----
        related = skeleton.neighbors(sent_id, ["RELATED_TO"])
        for rel_id, rel_edge in related:
            if rel_id in skeleton.sentences:
                context_sentences.add(rel_id)
                rel_sent = skeleton.sentences[rel_id]
                # Also grab RELATED sentence's paragraph text
                if rel_sent.parent_paragraph_text:
                    paragraph_texts.add(rel_sent.parent_paragraph_text)
                # And immediate prev/next of related sentence for coherence
                if rel_sent.prev_sentence_id and rel_sent.prev_sentence_id in skeleton.sentences:
                    context_sentences.add(rel_sent.prev_sentence_id)
                if rel_sent.next_sentence_id and rel_sent.next_sentence_id in skeleton.sentences:
                    context_sentences.add(rel_sent.next_sentence_id)

        # ---- Assemble into chunk-grouped output ----
        chunk_id = sent.chunk_id
        chunk_data = skeleton.chunks.get(chunk_id, {})

        if chunk_id not in expanded_chunks:
            expanded_chunks[chunk_id] = {
                "text": chunk_data.get("text", ""),
                "doc_id": sent.doc_id,
                "doc_title": chunk_data.get("doc_title", ""),
                "section_path": sent.section_path,
                "anchor_sentences": [],
                "context_sentences": [],
                "paragraph_texts": [],  # Full paragraphs for "paragraph display"
                "score": 0.0,
            }

        expanded_chunks[chunk_id]["paragraph_texts"] = list(
            set(expanded_chunks[chunk_id]["paragraph_texts"]) | paragraph_texts
        )

        # Collect sentence details with provenance (for hallucination control)
        for cs_id in sorted(context_sentences):
            cs = skeleton.sentences.get(cs_id)
            if cs:
                expanded_chunks[chunk_id]["context_sentences"].append({
                    "id": cs_id,
                    "text": cs.text,
                    "source": cs.source,
                    "is_anchor": cs_id == sent_id,
                    "confidence": cs.confidence,
                    "doc_id": cs.doc_id,
                    "page": cs.page,
                    "parent_paragraph_id": cs.parent_paragraph_id,
                })
                if cs_id == sent_id:
                    expanded_chunks[chunk_id]["anchor_sentences"].append(cs.text)

    return expanded_chunks


def stage3_rerank_and_select(
    expanded_chunks: Dict[str, Dict[str, Any]],
    query: str,
    max_chunks: int = 5,
) -> List[Dict[str, Any]]:
    """Stage 3: Re-rank with hallucination-aware scoring.

    This stage implements the anti-hallucination strategies from the discussion:

    1. **Grounding check**: Only score sentences that come from the source document.
       Each sentence carries its provenance (doc_id, page, confidence, source type).
       Sentences with low confidence or unknown provenance are penalized.

    2. **Pointwise relevance**: Score each chunk independently against the query
       (not pairwise) using keyword overlap as Phase 0 proxy.

       NOTE ON RERANKERS: At sentence level (~20-50 tokens), bi-encoder
       embeddings are already very precise — unlike 641-token chunks where
       topic-level similarity masks irrelevance. A cross-encoder reranker
       (e.g. voyage-rerank-2.5) is optional and should only be added in
       Phase 3+ IF benchmarks show the right sentences are in top-20 but
       not in top-5 (i.e., retrieved but ranked wrong). If the right
       sentences aren't in top-20 at all, that's an embedding/indexing
       problem — no reranker can fix it.

    3. **Structural coherence**: Boost chunks where multiple anchors cluster
       together (same paragraph or consecutive sentences). Penalize isolated
       sentences that are semantically similar but structurally disconnected.

    4. **Confidence gating**: Discard sentences below confidence threshold.
       This extraction-quality filter removes OCR artifacts, partial table
       cells, and form labels before they reach the LLM.

    5. **"Paragraph display" output**: Return full paragraph texts alongside
       anchor sentences, so the LLM gets cohesive context, not fragments.

    Phase 0-2 reranking (heuristic, no external API):
      Stage 3a: Confidence gate (drop extraction confidence < 0.5)
      Stage 3b: Keyword overlap scoring (proxy for relevance)
      Stage 3c: Structural coherence bonus (adjacent anchors boosted)
      Stage 3d: Top-k selection → LLM for SYNTHESIS ONLY (not ranking)

    Phase 3+ reranking (add cross-encoder ONLY if benchmark shows ranking errors):
      Stage 3b becomes: voyage-rerank-2.5 scores (query, passage) pairs
      Adds ~$0.05/1000 pairs per query, 10-50ms latency
      Per-query cost (NOT one-time) — runs on every user query
    """
    CONFIDENCE_FLOOR = 0.5  # Discard sentences below this confidence
    STRUCTURAL_BONUS = 1.5  # Bonus per pair of structurally adjacent anchors

    scored = []
    for chunk_id, data in expanded_chunks.items():
        anchor_count = len(data["anchor_sentences"])

        # --- Confidence gating: filter low-confidence sentences ---
        confident_sentences = [
            s for s in data["context_sentences"]
            if s.get("confidence", 1.0) >= CONFIDENCE_FLOOR
        ]
        low_conf_count = len(data["context_sentences"]) - len(confident_sentences)

        unique_sentences = len(set(s["text"] for s in confident_sentences))

        # --- Structural coherence: are anchors in the same paragraph? ---
        anchor_para_ids = set()
        for s in data["context_sentences"]:
            if s["is_anchor"] and s.get("parent_paragraph_id"):
                anchor_para_ids.add(s["parent_paragraph_id"])
        structural_coherence = STRUCTURAL_BONUS if len(anchor_para_ids) == 1 and anchor_count > 1 else 0.0

        # --- Pointwise relevance (keyword proxy for Phase 0) ---
        query_words = set(query.lower().split())
        context_text = " ".join(s["text"] for s in confident_sentences).lower()
        keyword_hits = sum(1 for w in query_words if w in context_text)
        keyword_density = keyword_hits / max(len(query_words), 1)

        # --- Grounding penalty: penalize mixed-source contexts ---
        source_types = set(s["source"] for s in confident_sentences)
        grounding_penalty = 0.0
        if "language_span" in source_types and len(source_types) > 2:
            grounding_penalty = -0.5  # Mixed sources increase hallucination risk

        # --- Final score ---
        score = (
            anchor_count * 3.0
            + unique_sentences * 0.5
            + structural_coherence
            + keyword_density * 2.0
            + grounding_penalty
        )

        data["score"] = score
        data["chunk_id"] = chunk_id
        data["rerank_details"] = {
            "anchor_count": anchor_count,
            "unique_sentences": unique_sentences,
            "low_confidence_filtered": low_conf_count,
            "structural_coherence": structural_coherence,
            "keyword_density": round(keyword_density, 3),
            "grounding_penalty": grounding_penalty,
            "source_types": list(source_types),
        }
        scored.append(data)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_chunks]


# ---------------------------------------------------------------------------
# Baseline: Chunk-Level Retrieval (for comparison)
# ---------------------------------------------------------------------------
def baseline_chunk_retrieval(
    chunks: List[Dict],
    query_embedding: np.ndarray,
    top_k: int = 5,
) -> List[Tuple[str, float, str]]:
    """Baseline: cosine similarity against TextChunk embeddings."""
    results = []
    for chunk in chunks:
        emb = chunk.get("embedding_v2")
        if emb is None:
            continue
        emb = np.array(emb, dtype=np.float32)
        norm = np.linalg.norm(emb)
        q_norm = np.linalg.norm(query_embedding)
        if norm == 0 or q_norm == 0:
            continue
        sim = float(np.dot(emb, query_embedding) / (norm * q_norm))
        results.append((chunk["chunk_id"], sim, chunk.get("text", "")[:200]))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


# ---------------------------------------------------------------------------
# Evaluation: Compare Retrieval Approaches
# ---------------------------------------------------------------------------
EXPERIMENT_QUERIES = [
    # Table-specific queries (should benefit most from hybrid skeleton)
    {
        "id": "EXP-T1",
        "query": "What is the total invoice amount?",
        "type": "table",
        "keywords": ["invoice", "amount", "total"],
    },
    {
        "id": "EXP-T2",
        "query": "What is the invoice number and date?",
        "type": "table",
        "keywords": ["invoice", "number", "date"],
    },
    # Specific-fact queries (should benefit from sentence precision)
    {
        "id": "EXP-F1",
        "query": "When does the policy become effective?",
        "type": "specific_fact",
        "keywords": ["effective", "date", "policy"],
    },
    {
        "id": "EXP-F2",
        "query": "What is the coverage limit?",
        "type": "specific_fact",
        "keywords": ["coverage", "limit", "amount"],
    },
    # Multi-hop queries (may not benefit — needs broad context)
    {
        "id": "EXP-M1",
        "query": "Compare the coverage terms across all policies",
        "type": "multi_hop",
        "keywords": ["coverage", "terms", "compare", "policy"],
    },
    {
        "id": "EXP-M2",
        "query": "What are all the document types in this collection?",
        "type": "multi_hop",
        "keywords": ["document", "types", "collection"],
    },
]


def evaluate_keyword_hit(retrieved_texts: List[str], keywords: List[str]) -> float:
    """Simple keyword-based relevance score.

    Returns fraction of keywords found in retrieved context.
    In Phase 0 this is a proxy for precision — production would use LLM grading.
    """
    combined = " ".join(retrieved_texts).lower()
    hits = sum(1 for kw in keywords if kw.lower() in combined)
    return hits / len(keywords) if keywords else 0.0


def run_experiment(
    skeleton: HybridSkeleton,
    chunks: List[Dict],
    queries: List[Dict],
    top_k: int = 5,
    expand_window: int = 2,
) -> List[Dict[str, Any]]:
    """Run the full comparison experiment."""
    results = []

    for q in queries:
        query = q["query"]
        print(f"\n  🔍 Query: {query}")
        print(f"     Type: {q['type']} | Keywords: {q['keywords']}")

        # Embed query
        q_emb = embed_query(query)

        # --- Variant A: Baseline (chunk-level) ---
        baseline_results = baseline_chunk_retrieval(chunks, q_emb, top_k)
        baseline_texts = [r[2] for r in baseline_results]
        baseline_score = evaluate_keyword_hit(baseline_texts, q["keywords"])
        baseline_tokens = sum(len(t.split()) for t in baseline_texts)

        # --- Variant B: Hybrid Skeleton (three-stage) ---
        anchors = stage1_semantic_anchor(skeleton, q_emb, top_k)
        anchor_ids = [a[0] for a in anchors]
        expanded = stage2_context_expansion(skeleton, anchor_ids, expand_window)
        selected = stage3_rerank_and_select(expanded, query, max_chunks=top_k)

        skeleton_texts = []
        skeleton_anchor_texts = []
        for sel in selected:
            for cs in sel["context_sentences"]:
                skeleton_texts.append(cs["text"])
                if cs["is_anchor"]:
                    skeleton_anchor_texts.append(cs["text"])

        skeleton_score = evaluate_keyword_hit(skeleton_texts, q["keywords"])
        skeleton_tokens = sum(len(t.split()) for t in skeleton_texts)
        anchor_score = evaluate_keyword_hit(skeleton_anchor_texts, q["keywords"])

        result = {
            "query_id": q["id"],
            "query": query,
            "type": q["type"],
            "_selected": selected,  # For summary to access rerank_details
            "baseline": {
                "keyword_score": baseline_score,
                "context_tokens": baseline_tokens,
                "top_chunks": len(baseline_results),
                "top_similarities": [round(r[1], 4) for r in baseline_results[:3]],
            },
            "hybrid_skeleton": {
                "keyword_score": skeleton_score,
                "anchor_score": anchor_score,
                "context_tokens": skeleton_tokens,
                "anchor_count": len(anchors),
                "expanded_chunks": len(selected),
                "total_sentences": len(skeleton_texts),
                "anchor_similarities": [round(a[1], 4) for a in anchors[:3]],
                "related_to_traversals": sum(
                    1 for sel in selected
                    for cs in sel["context_sentences"]
                    if not cs["is_anchor"]
                ),
            },
            "improvement": {
                "keyword_delta": skeleton_score - baseline_score,
                "token_ratio": round(skeleton_tokens / max(baseline_tokens, 1), 2),
                "verdict": (
                    "HYBRID_WINS" if skeleton_score > baseline_score
                    else "BASELINE_WINS" if baseline_score > skeleton_score
                    else "TIE"
                ),
            },
        }
        results.append(result)

        # Print comparison
        print(f"     Baseline:  keyword_score={baseline_score:.2f}  tokens={baseline_tokens}")
        print(f"     Skeleton:  keyword_score={skeleton_score:.2f}  tokens={skeleton_tokens}  anchors={len(anchors)}")
        print(f"     Verdict:   {result['improvement']['verdict']}  (delta={result['improvement']['keyword_delta']:+.2f})")

    return results


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------
def print_summary(results: List[Dict], skeleton: HybridSkeleton, similarity_threshold: float):
    """Print experiment summary."""
    print("\n" + "=" * 80)
    print("EXPERIMENT SUMMARY: Hybrid Skeleton vs Baseline Chunk Retrieval")
    print("=" * 80)

    print(f"\n📊 Skeleton Graph Stats:")
    stats = skeleton.stats
    for key, val in stats.items():
        print(f"   {key}: {val}")

    print(f"\n   Similarity threshold for RELATED_TO: {similarity_threshold}")

    print(f"\n📈 Results by Query Type:")
    by_type: Dict[str, List[Dict]] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)

    overall_wins = {"HYBRID_WINS": 0, "BASELINE_WINS": 0, "TIE": 0}

    for qtype, qresults in by_type.items():
        avg_baseline = np.mean([r["baseline"]["keyword_score"] for r in qresults])
        avg_skeleton = np.mean([r["hybrid_skeleton"]["keyword_score"] for r in qresults])
        avg_token_ratio = np.mean([r["improvement"]["token_ratio"] for r in qresults])

        print(f"\n   {qtype.upper()} queries ({len(qresults)}):")
        print(f"     Avg baseline keyword_score:  {avg_baseline:.3f}")
        print(f"     Avg skeleton keyword_score:   {avg_skeleton:.3f}")
        print(f"     Avg token ratio (skel/base):  {avg_token_ratio:.2f}x")

        for r in qresults:
            overall_wins[r["improvement"]["verdict"]] += 1

    print(f"\n🏆 Overall Verdict:")
    print(f"   Hybrid wins: {overall_wins['HYBRID_WINS']}")
    print(f"   Baseline wins: {overall_wins['BASELINE_WINS']}")
    print(f"   Ties: {overall_wins['TIE']}")

    # Specific observations
    print(f"\n💡 Key Observations:")
    for r in results:
        if r["improvement"]["keyword_delta"] > 0:
            print(f"   ✅ {r['query_id']}: Hybrid improved by {r['improvement']['keyword_delta']:+.2f} "
                  f"({r['type']})")
        elif r["improvement"]["keyword_delta"] < 0:
            print(f"   ❌ {r['query_id']}: Baseline better by {abs(r['improvement']['keyword_delta']):.2f} "
                  f"({r['type']})")
        else:
            print(f"   ➖ {r['query_id']}: Tied ({r['type']})")

    related_edges = sum(1 for e in skeleton.edges if e.edge_type == "RELATED_TO")
    if related_edges == 0:
        print(f"\n   ⚠️  No RELATED_TO edges created — consider lowering similarity_threshold "
              f"(currently {similarity_threshold})")
    else:
        avg_weight = np.mean([e.weight for e in skeleton.edges if e.edge_type == "RELATED_TO"])
        print(f"\n   🔗 {related_edges} RELATED_TO edges (avg similarity: {avg_weight:.4f})")

    # Hallucination control summary
    print(f"\n🛡️  Hallucination Control Summary:")
    total_low_conf = 0
    total_structural_bonus = 0
    total_grounding_penalty = 0
    for r in results:
        for sel in r.get("_selected", []):
            details = sel.get("rerank_details", {})
            total_low_conf += details.get("low_confidence_filtered", 0)
            if details.get("structural_coherence", 0) > 0:
                total_structural_bonus += 1
            if details.get("grounding_penalty", 0) < 0:
                total_grounding_penalty += 1
    print(f"   Low-confidence sentences filtered: {total_low_conf}")
    print(f"   Chunks with structural coherence bonus: {total_structural_bonus}")
    print(f"   Chunks with grounding penalty: {total_grounding_penalty}")

    # Edge budget check
    stats = skeleton.stats
    if stats.get("edge_budget_ok") is not None:
        budget_status = "✅ PASS" if stats["edge_budget_ok"] else "❌ FAIL"
        print(f"\n   Edge budget invariant: {budget_status} "
              f"(ratio: {stats.get('edge_budget_ratio', 'N/A')})")
    if stats.get("metadata_paragraph_text_pct") is not None:
        print(f"   Metadata completeness: paragraph_text={stats['metadata_paragraph_text_pct']}, "
              f"prev_next={stats.get('metadata_prev_next_pct', 'N/A')}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Phase 0: Hybrid Skeleton Experiment")
    parser.add_argument("--group-id", default=os.getenv("GROUP_ID", "test-5pdfs-v2-fix2"),
                        help="Neo4j group_id")
    parser.add_argument("--similarity-threshold", type=float, default=0.90,
                        help="Min cosine similarity for RELATED_TO edges (default: 0.90)")
    parser.add_argument("--max-related", type=int, default=2,
                        help="Max RELATED_TO edges per sentence (default: 2)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Top-k retrieval (default: 5)")
    parser.add_argument("--expand-window", type=int, default=2,
                        help="NEXT/PREV expansion window (default: 2)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    parser.add_argument("--cross-chunk-only", action="store_true", default=True,
                        help="Only create RELATED_TO edges across chunks")
    parser.add_argument("--sweep-thresholds", action="store_true",
                        help="Sweep multiple similarity thresholds")
    args = parser.parse_args()

    print("=" * 80)
    print("Phase 0: Hybrid Skeleton Experiment")
    print("  Deterministic Structure + Sparse k-NN + Three-Stage Retrieval")
    print("=" * 80)
    print(f"\n  Group ID:              {args.group_id}")
    print(f"  Similarity threshold:  {args.similarity_threshold}")
    print(f"  Max RELATED_TO/sent:   {args.max_related}")
    print(f"  Top-k:                 {args.top_k}")
    print(f"  Expand window:         {args.expand_window}")

    # Step 1: Extract from Neo4j
    print(f"\n{'─'*60}")
    print("Step 1: Extracting chunks from Neo4j...")
    chunks = extract_chunks_from_neo4j(args.group_id)
    if not chunks:
        print("  ❌ No chunks found. Check group_id and Neo4j connection.")
        sys.exit(1)

    # Step 2: Build deterministic skeleton
    print(f"\n{'─'*60}")
    print("Step 2: Building deterministic skeleton (sentences + structure)...")
    skeleton = build_skeleton(chunks)
    print(f"  🦴 Skeleton stats: {skeleton.stats}")

    # Step 3: Embed sentences
    print(f"\n{'─'*60}")
    print("Step 3: Embedding sentence nodes with Voyage...")
    t0 = time.time()
    embedded = embed_sentences(skeleton)
    print(f"  ✅ Embedded {embedded} sentences in {time.time() - t0:.1f}s")

    if args.sweep_thresholds:
        # Sweep multiple thresholds
        thresholds = [0.80, 0.85, 0.90, 0.92, 0.95]
        print(f"\n{'─'*60}")
        print(f"Threshold sweep: {thresholds}")
        for threshold in thresholds:
            print(f"\n{'='*60}")
            print(f"Threshold: {threshold}")

            # Reset edges (keep only structural)
            skeleton.edges = [e for e in skeleton.edges if e.edge_type != "RELATED_TO"]
            skeleton._adj = {}
            for e in skeleton.edges:
                skeleton._adj.setdefault(e.source_id, []).append(e)
                if e.edge_type in ("NEXT",):
                    reverse = SkeletonEdge(
                        source_id=e.target_id, target_id=e.source_id,
                        edge_type="PREV", weight=e.weight, metadata=e.metadata,
                    )
                    skeleton._adj.setdefault(e.target_id, []).append(reverse)

            related_count = build_sparse_semantic_links(
                skeleton, similarity_threshold=threshold,
                max_related_per_sentence=args.max_related,
                cross_chunk_only=args.cross_chunk_only,
            )
            print(f"  🔗 RELATED_TO edges: {related_count}")

            results = run_experiment(skeleton, chunks, EXPERIMENT_QUERIES, args.top_k, args.expand_window)
            print_summary(results, skeleton, threshold)
    else:
        # Step 4: Build sparse semantic links
        print(f"\n{'─'*60}")
        print(f"Step 4: Building sparse semantic links (threshold={args.similarity_threshold})...")
        related_count = build_sparse_semantic_links(
            skeleton,
            similarity_threshold=args.similarity_threshold,
            max_related_per_sentence=args.max_related,
            cross_chunk_only=args.cross_chunk_only,
        )
        print(f"  🔗 Created {related_count} RELATED_TO edges")

        # Step 5: Run experiment
        print(f"\n{'─'*60}")
        print("Step 5: Running retrieval comparison...")
        results = run_experiment(skeleton, chunks, EXPERIMENT_QUERIES, args.top_k, args.expand_window)

        # Summary
        print_summary(results, skeleton, args.similarity_threshold)

        # Save results
        output_path = args.output or f"experiment_hybrid_skeleton_{args.group_id}_{int(time.time())}.json"
        output = {
            "experiment": "hybrid_skeleton_phase0",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "config": {
                "group_id": args.group_id,
                "similarity_threshold": args.similarity_threshold,
                "max_related": args.max_related,
                "top_k": args.top_k,
                "expand_window": args.expand_window,
            },
            "skeleton_stats": skeleton.stats,
            "results": results,
        }
        Path(output_path).write_text(json.dumps(output, indent=2, default=str))
        print(f"\n  📁 Results saved to {output_path}")


if __name__ == "__main__":
    main()
