"""
Data models for section-aware chunking.

These models extend the existing TextChunk model with section-specific metadata
to enable structure-aware retrieval and coverage control.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SectionNode:
    """Represents a document section from Azure DI.
    
    This is an intermediate representation used during chunking,
    capturing the hierarchical structure before flattening to chunks.
    """
    id: str
    title: str
    level: int  # 1 = H1, 2 = H2, etc.
    content: str
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    
    # Span info from Azure DI
    start_offset: int = 0
    end_offset: int = 0
    
    # Paragraph/table counts for diagnostics
    paragraph_count: int = 0
    table_count: int = 0
    tables: List[Dict[str, Any]] = field(default_factory=list)
    
    # Token count (computed during processing)
    token_count: int = 0
    
    def __post_init__(self):
        """Compute token count from content."""
        if self.content and self.token_count == 0:
            # Simple whitespace tokenization; override with tiktoken if needed
            self.token_count = len(self.content.split())


@dataclass
class SectionChunk:
    """A chunk derived from a document section.
    
    This is compatible with TextChunk but carries additional section metadata.
    When stored in Neo4j, it maps to :TextChunk nodes with enriched metadata.
    """
    id: str
    text: str
    chunk_index: int
    document_id: str
    
    # Section metadata (key differentiator from fixed chunking)
    section_id: str
    section_title: str
    section_level: int
    section_path: List[str]  # e.g., ["Introduction", "Purpose"]
    
    # Position within section (if section was split)
    section_chunk_index: int = 0
    section_chunk_total: int = 1
    
    # Standard chunk fields
    embedding: Optional[List[float]] = None
    tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Coverage-related flags
    is_section_start: bool = True  # True if this is the first chunk of a section
    is_summary_section: bool = False  # True if section matches summary patterns
    
    def to_text_chunk_dict(self) -> Dict[str, Any]:
        """Convert to TextChunk-compatible dict for Neo4j storage."""
        return {
            "id": self.id,
            "text": self.text,
            "chunk_index": self.chunk_index,
            "document_id": self.document_id,
            "embedding": self.embedding,
            "tokens": self.tokens,
            "metadata": {
                **self.metadata,
                "section_id": self.section_id,
                "section_title": self.section_title,
                "section_level": self.section_level,
                "section_path": self.section_path,
                "section_path_key": " > ".join(self.section_path),
                "section_chunk_index": self.section_chunk_index,
                "section_chunk_total": self.section_chunk_total,
                "is_section_start": self.is_section_start,
                "is_summary_section": self.is_summary_section,
                "chunk_strategy": "section_aware_v2",
            },
        }


# Summary section patterns (case-insensitive)
SUMMARY_SECTION_PATTERNS = [
    "purpose",
    "summary",
    "executive summary",
    "introduction",
    "overview",
    "scope",
    "background",
    "abstract",
    "objectives",
    "recitals",  # Common in legal contracts
    "whereas",   # Legal preamble
]


def is_summary_section(title: str) -> bool:
    """Check if a section title indicates a summary/introductory section."""
    title_lower = title.lower().strip()
    return any(pattern in title_lower for pattern in SUMMARY_SECTION_PATTERNS)
