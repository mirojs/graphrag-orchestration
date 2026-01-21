"""
Section-Aware Chunker

This chunker respects Azure Document Intelligence section boundaries,
creating semantically coherent chunks aligned with document structure.

Key strategies (learned from prior art):
1. LlamaIndex Hierarchical: Parent-child relationships for context expansion
2. LangChain MarkdownHeader: Header metadata preservation
3. Unstructured.io: Element-based boundaries with size constraints
4. Semantic Chunking: Natural break detection (we use DI sections as breaks)

Splitting rules:
- MIN_TOKENS (100): Merge tiny sections with parent/sibling
- MAX_TOKENS (1500): Split large sections at paragraph boundaries
- OVERLAP_TOKENS (50): Add overlap between split chunks
"""
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import SectionChunk, SectionNode, is_summary_section

logger = logging.getLogger(__name__)


@dataclass
class SectionChunkConfig:
    """Configuration for section-aware chunking."""
    
    # Size thresholds (in tokens, using whitespace tokenization)
    min_tokens: int = 100       # Sections below this merge with parent/sibling
    max_tokens: int = 1500      # Sections above this get split
    overlap_tokens: int = 50    # Overlap between split chunks
    
    # Behavior flags
    merge_tiny_sections: bool = True        # Merge sections below min_tokens
    preserve_hierarchy: bool = True         # Keep parent_section_id links
    prefer_paragraph_splits: bool = True    # Split at \n\n when possible
    
    # Fallback behavior
    fallback_to_fixed_chunking: bool = True  # Use fixed chunking if no sections
    fallback_chunk_size: int = 512
    fallback_overlap: int = 64


class SectionAwareChunker:
    """
    Chunks documents based on Azure DI section structure.
    
    This is a drop-in replacement for fixed-window chunking that:
    1. Preserves semantic boundaries (sections = complete thoughts)
    2. Enables structure-aware retrieval (H1/H2 metadata)
    3. Supports coverage retrieval (one "summary" section per doc)
    """
    
    def __init__(self, config: Optional[SectionChunkConfig] = None):
        self.config = config or SectionChunkConfig()
    
    async def chunk_document(
        self,
        di_units: Sequence[Any],  # LlamaDocument from DI
        doc_id: str,
        doc_source: str = "",
        doc_title: str = "",
    ) -> List[SectionChunk]:
        """
        Chunk a document using Azure DI section structure.
        
        Args:
            di_units: LlamaDocument objects from Document Intelligence
            doc_id: Document identifier
            doc_source: Document URL/path
            doc_title: Document title
            
        Returns:
            List of SectionChunk objects ready for embedding and storage
        """
        if not di_units:
            return []
        
        # Step 1: Extract section tree from DI metadata
        sections = self._extract_sections_from_di(di_units, doc_id)
        
        if not sections:
            # Fallback: No sections found, use fixed chunking
            if self.config.fallback_to_fixed_chunking:
                logger.warning(
                    "section_chunking_fallback",
                    extra={"doc_id": doc_id, "reason": "no_sections_found"},
                )
                return self._fallback_fixed_chunking(di_units, doc_id, doc_source, doc_title)
            return []
        
        # Step 2: Build hierarchy and merge tiny sections
        if self.config.merge_tiny_sections:
            sections = self._merge_tiny_sections(sections)
        
        # Step 3: Split large sections
        chunks = self._sections_to_chunks(sections, doc_id, doc_source, doc_title)
        
        logger.info(
            "section_chunking_complete",
            extra={
                "doc_id": doc_id,
                "sections_found": len(sections),
                "chunks_created": len(chunks),
                "summary_sections": sum(1 for c in chunks if c.is_summary_section),
            },
        )
        
        return chunks
    
    def _extract_sections_from_di(
        self,
        di_units: Sequence[Any],
        doc_id: str,
    ) -> List[SectionNode]:
        """Extract section structure from DI LlamaDocuments."""
        sections: List[SectionNode] = []
        
        for unit_idx, unit in enumerate(di_units):
            meta = getattr(unit, "metadata", None) or {}
            text = getattr(unit, "text", "") or ""
            
            if not text.strip():
                continue
            
            # Check if this unit has section metadata from DI
            section_path = meta.get("section_path") or []
            di_section_path = meta.get("di_section_path") or []
            chunk_type = meta.get("chunk_type", "")
            
            # Determine section level from path length or chunk_type
            level = len(section_path) if section_path else 1
            
            # Generate section title
            if section_path and isinstance(section_path, list):
                title = section_path[-1] if section_path else f"Section {unit_idx}"
            else:
                title = f"Section {unit_idx}"
            
            # Generate stable section ID
            section_id = self._generate_section_id(doc_id, section_path, unit_idx)
            
            # Determine parent
            parent_id = None
            if self.config.preserve_hierarchy and len(section_path) > 1:
                parent_path = section_path[:-1]
                parent_id = self._generate_section_id(doc_id, parent_path, -1)
            
            sections.append(
                SectionNode(
                    id=section_id,
                    title=title,
                    level=level,
                    content=text,
                    parent_id=parent_id,
                    paragraph_count=meta.get("paragraph_count", 0),
                    table_count=meta.get("table_count", 0),
                    tables=list(meta.get("tables", []) or []),
                )
            )
        
        return sections
    
    def _generate_section_id(
        self,
        doc_id: str,
        section_path: List[str],
        fallback_idx: int,
    ) -> str:
        """Generate a stable, deterministic section ID."""
        if section_path:
            path_str = " > ".join(str(p) for p in section_path)
            hash_input = f"{doc_id}:{path_str}"
        else:
            hash_input = f"{doc_id}:section_{fallback_idx}"
        
        return f"sec_{hashlib.md5(hash_input.encode()).hexdigest()[:16]}"
    
    def _merge_tiny_sections(self, sections: List[SectionNode]) -> List[SectionNode]:
        """Merge sections below min_tokens threshold with siblings/parents."""
        if not sections:
            return sections
        
        merged: List[SectionNode] = []
        pending_merge: Optional[SectionNode] = None
        
        for section in sections:
            if section.token_count < self.config.min_tokens:
                # This section is too small
                if pending_merge is not None:
                    # Merge with previous pending section
                    pending_merge.content += "\n\n" + section.content
                    pending_merge.token_count += section.token_count
                    pending_merge.paragraph_count += section.paragraph_count
                    pending_merge.table_count += section.table_count
                    if section.tables:
                        pending_merge.tables.extend(section.tables)
                elif merged:
                    # Merge with last completed section
                    merged[-1].content += "\n\n" + section.content
                    merged[-1].token_count += section.token_count
                    if section.tables:
                        merged[-1].tables.extend(section.tables)
                else:
                    # First section and it's tiny - keep as pending
                    pending_merge = section
            else:
                # Normal-sized section
                if pending_merge is not None:
                    # Prepend pending content to this section
                    section.content = pending_merge.content + "\n\n" + section.content
                    section.token_count += pending_merge.token_count
                    if pending_merge.tables:
                        section.tables = pending_merge.tables + section.tables
                    pending_merge = None
                merged.append(section)
        
        # Handle trailing pending section
        if pending_merge is not None:
            if merged:
                merged[-1].content += "\n\n" + pending_merge.content
                merged[-1].token_count += pending_merge.token_count
                if pending_merge.tables:
                    merged[-1].tables.extend(pending_merge.tables)
            else:
                merged.append(pending_merge)
        
        return merged
    
    def _sections_to_chunks(
        self,
        sections: List[SectionNode],
        doc_id: str,
        doc_source: str,
        doc_title: str,
    ) -> List[SectionChunk]:
        """Convert sections to chunks, splitting large sections as needed."""
        chunks: List[SectionChunk] = []
        global_chunk_idx = 0
        
        for section in sections:
            section_path = self._build_section_path(section, sections)
            is_summary = is_summary_section(section.title)
            
            if section.token_count <= self.config.max_tokens:
                # Section fits in one chunk
                chunks.append(
                    SectionChunk(
                        id=f"{doc_id}_chunk_{global_chunk_idx}",
                        text=section.content,
                        chunk_index=global_chunk_idx,
                        document_id=doc_id,
                        section_id=section.id,
                        section_title=section.title,
                        section_level=section.level,
                        section_path=section_path,
                        section_chunk_index=0,
                        section_chunk_total=1,
                        tokens=section.token_count,
                        is_section_start=True,
                        is_summary_section=is_summary,
                        metadata={
                            "source": doc_source,
                            "title": doc_title,
                            "paragraph_count": section.paragraph_count,
                            "table_count": section.table_count,
                                "tables": section.tables,
                        },
                    )
                )
                global_chunk_idx += 1
            else:
                # Section too large - split it
                sub_chunks = self._split_large_section(
                    section=section,
                    section_path=section_path,
                    doc_id=doc_id,
                    doc_source=doc_source,
                    doc_title=doc_title,
                    start_chunk_idx=global_chunk_idx,
                    is_summary=is_summary,
                )
                chunks.extend(sub_chunks)
                global_chunk_idx += len(sub_chunks)
        
        return chunks
    
    def _build_section_path(
        self,
        section: SectionNode,
        all_sections: List[SectionNode],
    ) -> List[str]:
        """Build the full path from root to this section."""
        # Simple approach: use title. For deeper hierarchy, traverse parents.
        path = [section.title]
        
        if self.config.preserve_hierarchy and section.parent_id:
            # Find parent and prepend its path
            parent = next((s for s in all_sections if s.id == section.parent_id), None)
            if parent:
                parent_path = self._build_section_path(parent, all_sections)
                path = parent_path + path
        
        return path
    
    def _split_large_section(
        self,
        section: SectionNode,
        section_path: List[str],
        doc_id: str,
        doc_source: str,
        doc_title: str,
        start_chunk_idx: int,
        is_summary: bool,
    ) -> List[SectionChunk]:
        """Split a large section into smaller chunks at paragraph boundaries."""
        content = section.content
        max_tokens = self.config.max_tokens
        overlap = self.config.overlap_tokens
        
        # Strategy: Split at paragraph boundaries (\n\n) when possible
        if self.config.prefer_paragraph_splits:
            paragraphs = re.split(r'\n\n+', content)
        else:
            # Fall back to sentence splitting
            paragraphs = re.split(r'(?<=[.!?])\s+', content)
        
        chunks: List[SectionChunk] = []
        current_text = ""
        current_tokens = 0
        chunk_idx_in_section = 0
        include_tables = True if section.tables else False
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            para_tokens = len(para.split())
            
            if current_tokens + para_tokens <= max_tokens:
                # Add to current chunk
                if current_text:
                    current_text += "\n\n" + para
                else:
                    current_text = para
                current_tokens += para_tokens
            else:
                # Current chunk is full, emit it
                if current_text:
                    chunks.append(
                        SectionChunk(
                            id=f"{doc_id}_chunk_{start_chunk_idx + len(chunks)}",
                            text=current_text,
                            chunk_index=start_chunk_idx + len(chunks),
                            document_id=doc_id,
                            section_id=section.id,
                            section_title=section.title,
                            section_level=section.level,
                            section_path=section_path,
                            section_chunk_index=chunk_idx_in_section,
                            section_chunk_total=-1,  # Will update after
                            tokens=current_tokens,
                            is_section_start=(chunk_idx_in_section == 0),
                            is_summary_section=is_summary,
                            metadata={
                                "source": doc_source,
                                "title": doc_title,
                                "table_count": section.table_count,
                                "tables": section.tables if include_tables and chunk_idx_in_section == 0 else [],
                            },
                        )
                    )
                    chunk_idx_in_section += 1
                
                # Start new chunk with overlap
                if overlap > 0 and current_text:
                    # Take last N tokens as overlap
                    words = current_text.split()
                    overlap_text = " ".join(words[-overlap:]) if len(words) > overlap else ""
                    current_text = overlap_text + "\n\n" + para if overlap_text else para
                    current_tokens = len(current_text.split())
                else:
                    current_text = para
                    current_tokens = para_tokens
        
        # Emit final chunk
        if current_text:
            chunks.append(
                SectionChunk(
                    id=f"{doc_id}_chunk_{start_chunk_idx + len(chunks)}",
                    text=current_text,
                    chunk_index=start_chunk_idx + len(chunks),
                    document_id=doc_id,
                    section_id=section.id,
                    section_title=section.title,
                    section_level=section.level,
                    section_path=section_path,
                    section_chunk_index=chunk_idx_in_section,
                    section_chunk_total=-1,
                    tokens=current_tokens,
                    is_section_start=(chunk_idx_in_section == 0),
                    is_summary_section=is_summary,
                    metadata={
                        "source": doc_source,
                        "title": doc_title,
                        "table_count": section.table_count,
                        "tables": section.tables if include_tables and chunk_idx_in_section == 0 else [],
                    },
                )
            )
        
        # Update section_chunk_total for all chunks
        total = len(chunks)
        for chunk in chunks:
            chunk.section_chunk_total = total
        
        return chunks
    
    def _fallback_fixed_chunking(
        self,
        di_units: Sequence[Any],
        doc_id: str,
        doc_source: str,
        doc_title: str,
    ) -> List[SectionChunk]:
        """Fallback to fixed-size chunking when no sections available."""
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.core.schema import Document as LlamaDocument
        
        # Combine all DI unit text
        full_text = "\n\n".join(
            (getattr(unit, "text", "") or "").strip()
            for unit in di_units
        )
        
        if not full_text.strip():
            return []
        
        splitter = SentenceSplitter(
            chunk_size=self.config.fallback_chunk_size,
            chunk_overlap=self.config.fallback_overlap,
        )
        
        llama_doc = LlamaDocument(text=full_text, id_=doc_id)
        nodes = splitter.get_nodes_from_documents([llama_doc])
        
        chunks: List[SectionChunk] = []
        for idx, node in enumerate(nodes):
            text = node.get_content().strip()
            if not text:
                continue
            
            chunks.append(
                SectionChunk(
                    id=f"{doc_id}_chunk_{idx}",
                    text=text,
                    chunk_index=idx,
                    document_id=doc_id,
                    section_id=f"{doc_id}_fallback",
                    section_title="(No section - fixed chunking)",
                    section_level=0,
                    section_path=[],
                    section_chunk_index=idx,
                    section_chunk_total=len(nodes),
                    tokens=len(text.split()),
                    is_section_start=(idx == 0),
                    is_summary_section=(idx == 0),  # First chunk as pseudo-summary
                    metadata={
                        "source": doc_source,
                        "title": doc_title,
                        "chunk_strategy": "fixed_fallback",
                    },
                )
            )
        
        return chunks


# Convenience function for quick integration
async def chunk_with_sections(
    di_units: Sequence[Any],
    doc_id: str,
    doc_source: str = "",
    doc_title: str = "",
    config: Optional[SectionChunkConfig] = None,
) -> List[SectionChunk]:
    """
    Convenience function to chunk DI output using section-aware strategy.
    
    Example usage in lazygraphrag_pipeline.py:
    
        from app.hybrid.indexing.section_chunking import chunk_with_sections
        
        # Replace _chunk_di_units:
        section_chunks = await chunk_with_sections(di_units, doc_id, doc_source, doc_title)
        
        # Convert to TextChunk for existing pipeline compatibility:
        text_chunks = [
            TextChunk(
                id=sc.id,
                text=sc.text,
                chunk_index=sc.chunk_index,
                document_id=sc.document_id,
                embedding=None,
                tokens=sc.tokens,
                metadata=sc.to_text_chunk_dict()["metadata"],
            )
            for sc in section_chunks
        ]
    """
    chunker = SectionAwareChunker(config)
    return await chunker.chunk_document(di_units, doc_id, doc_source, doc_title)
