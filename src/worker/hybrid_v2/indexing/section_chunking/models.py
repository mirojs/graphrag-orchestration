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
    
    # Span info from Azure DI (character offsets)
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    
    # Page number from Azure DI bounding regions
    page_number: Optional[int] = None
    
    # URL from document metadata (for citation tracking)
    url: Optional[str] = None
    
    # Paragraph/table counts for diagnostics
    paragraph_count: int = 0
    table_count: int = 0
    tables: List[Dict[str, Any]] = field(default_factory=list)
    key_value_pairs: List[Dict[str, Any]] = field(default_factory=list)
    
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
    
    Location metadata (page_number, start_offset, end_offset) enables precise
    citation tracking back to the original document location.
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
    
    # Language metadata (from Azure DI LANGUAGES feature)
    language: Optional[str] = None  # ISO 639-1/BCP 47 locale code (e.g., "zh-Hans", "en")
    
    # Location metadata (from Azure DI) for precise citation tracking
    page_number: Optional[int] = None  # Page number where chunk appears
    start_offset: Optional[int] = None  # Character offset in original document
    end_offset: Optional[int] = None  # End character offset in original document
    
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
                **(({"language": self.language}) if self.language else {}),
                # Location metadata for citation tracking
                **(({"page_number": self.page_number}) if self.page_number is not None else {}),
                **(({"start_offset": self.start_offset}) if self.start_offset is not None else {}),
                **(({"end_offset": self.end_offset}) if self.end_offset is not None else {}),
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
