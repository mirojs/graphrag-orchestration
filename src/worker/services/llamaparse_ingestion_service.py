"""
LlamaParse Ingestion Service

Uses LlamaParse for layout-aware document parsing that preserves:
- Document structure (headers, sections, paragraphs)
- Table formatting and structure
- Bounding box information
- Reading order
- Spatial relationships

LlamaParse directly integrates with LlamaIndex PropertyGraphIndex,
providing superior entity extraction compared to flat text.
"""

from typing import List, Dict, Any, Optional
import logging
from pathlib import Path

from llama_index.core import Document
from llama_parse import LlamaParse

from src.core.config import settings

logger = logging.getLogger(__name__)


class LlamaParseIngestionService:
    """
    Ingestion service using LlamaParse for layout-aware document parsing.
    
    LlamaParse advantages over flat text extraction:
    1. Preserves document structure as metadata
    2. Maintains table relationships
    3. Provides bounding box information
    4. Respects reading order
    5. Direct LlamaIndex integration
    
    This enables GraphRAG to:
    - Extract entities with spatial context
    - Understand document hierarchy
    - Preserve table-entity relationships
    - Maintain cross-references
    """
    
    def __init__(self):
        """Initialize LlamaParse with API key from settings."""
        api_key = getattr(settings, "LLAMA_CLOUD_API_KEY", None)
        if not api_key:
            raise RuntimeError(
                "LLAMA_CLOUD_API_KEY not configured. "
                "Get your key from https://cloud.llamaindex.ai/"
            )
        
        # Use a conservative set of known-stable constructor args
        # to avoid runtime/type issues from vendor option changes.
        self.parser = LlamaParse(
            api_key=api_key,
            result_type="markdown",
            verbose=True,
            language="en",
        )
    
    async def parse_documents(
        self,
        file_paths: List[str],
        group_id: str,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Parse documents with layout awareness.
        
        Args:
            file_paths: Paths to local files or URLs to parse
            group_id: Tenant ID for multi-tenancy
            extra_metadata: Additional metadata to attach to documents
            
        Returns:
            List of LlamaIndex Document objects with:
            - Structured markdown text (preserves layout)
            - Rich metadata (page numbers, sections, tables)
            - group_id for tenant isolation
            
        Example:
            ```python
            service = LlamaParseIngestionService()
            docs = await service.parse_documents(
                file_paths=["contract.pdf", "invoice.pdf"],
                group_id="tenant-001",
                extra_metadata={"source": "upload"}
            )
            # docs ready for PropertyGraphIndex
            ```
        """
        logger.info(f"Parsing {len(file_paths)} documents with LlamaParse for group {group_id}")
        
        # Parse files with LlamaParse
        try:
            documents = await self.parser.aload_data(file_paths)
        except Exception as e:
            logger.error(f"LlamaParse failed: {e}")
            raise RuntimeError(f"Failed to parse documents with LlamaParse: {e}")
        
        # Enrich metadata for multi-tenancy and tracking
        base_metadata = {"group_id": group_id}
        if extra_metadata:
            base_metadata.update(extra_metadata)
        
        enriched_docs = []
        for i, doc in enumerate(documents):
            # Merge metadata
            doc.metadata.update(base_metadata)
            
            # Add document index for tracking
            doc.metadata["doc_index"] = i
            
            # Add source file if available
            if i < len(file_paths):
                doc.metadata["source_file"] = Path(file_paths[i]).name
            
            enriched_docs.append(doc)
        
        logger.info(
            f"Successfully parsed {len(enriched_docs)} documents. "
            f"Total text length: {sum(len(d.text) for d in enriched_docs)} chars"
        )
        
        return enriched_docs
    
    async def parse_from_urls(
        self,
        blob_urls: List[str],
        group_id: str,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        Parse documents from Azure Blob Storage URLs.
        
        LlamaParse can directly parse from URLs (including Azure Blob SAS URLs).
        
        Args:
            blob_urls: Azure Blob Storage URLs (with SAS tokens)
            group_id: Tenant ID
            extra_metadata: Additional metadata
            
        Returns:
            Parsed Document objects ready for GraphRAG indexing
        """
        return await self.parse_documents(
            file_paths=blob_urls,
            group_id=group_id,
            extra_metadata=extra_metadata
        )
    
    def get_parsing_instructions(self, document_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get custom parsing instructions for specific document types.
        
        LlamaParse supports custom instructions to improve parsing quality
        for domain-specific documents.
        
        Args:
            document_type: Type of document (e.g., "contract", "invoice", "technical")
            
        Returns:
            Parsing configuration optimized for document type
        """
        instructions = {
            "contract": {
                "parsing_instruction": (
                    "This is a legal contract. Pay special attention to:\n"
                    "- Section headings and numbering\n"
                    "- Party names and roles\n"
                    "- Dates and deadlines\n"
                    "- Monetary amounts and payment terms\n"
                    "- Tables with terms and conditions\n"
                    "Preserve the hierarchical structure and cross-references."
                ),
                "result_type": "markdown",
                "parse_tables": True,
            },
            "invoice": {
                "parsing_instruction": (
                    "This is a financial invoice. Focus on:\n"
                    "- Invoice number and date\n"
                    "- Vendor and customer information\n"
                    "- Line items table (description, quantity, price)\n"
                    "- Subtotals, taxes, and total amounts\n"
                    "- Payment terms and due date\n"
                    "Maintain table structure for line items."
                ),
                "result_type": "markdown",
                "parse_tables": True,
            },
            "technical": {
                "parsing_instruction": (
                    "This is a technical document. Preserve:\n"
                    "- Section hierarchy and numbering\n"
                    "- Diagrams and figure references\n"
                    "- Tables with specifications\n"
                    "- Code blocks and technical notation\n"
                    "- Cross-references between sections"
                ),
                "result_type": "markdown",
                "parse_tables": True,
            },
            "default": {
                "result_type": "markdown",
                "parse_tables": True,
            }
        }
        
        return instructions.get(document_type, instructions["default"])


# Helper function for backward compatibility with existing code
async def parse_with_layout(
    file_paths: List[str],
    group_id: str,
) -> List[Document]:
    """
    Convenience function for parsing documents with layout awareness.
    
    This replaces the old CU Standard approach with LlamaParse.
    
    Args:
        file_paths: Local files or URLs to parse
        group_id: Tenant ID
        
    Returns:
        LlamaIndex Documents with preserved layout
        
    Example:
        ```python
        docs = await parse_with_layout(
            file_paths=["contract.pdf"],
            group_id="tenant-001"
        )
        # Use docs with PropertyGraphIndex
        ```
    """
    service = LlamaParseIngestionService()
    return await service.parse_documents(file_paths, group_id)
