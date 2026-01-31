"""
Simplified Document Analysis Service

A unified, drop-in replacement for Azure Content Understanding that:
- Provides a clean, simple API for document analysis
- Automatically selects the best backend (Document Intelligence or Content Understanding)
- Handles authentication transparently (API key + managed identity)
- Returns standardized output without schema analyzer complexity
- Supports batch processing with graceful error handling

This service abstracts away the complexity of choosing between CU and DI,
providing clients with a single, reliable interface for document analysis.
"""

import asyncio
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from llama_index.core import Document

from src.core.config import settings
from src.worker.services.document_intelligence_service import DocumentIntelligenceService
from src.worker.services.cu_standard_ingestion_service_v2 import CUStandardIngestionServiceV2

logger = logging.getLogger(__name__)


class DocumentAnalysisBackend(str, Enum):
    """Available document analysis backends."""
    DOCUMENT_INTELLIGENCE = "document_intelligence"
    CONTENT_UNDERSTANDING = "content_understanding"
    AUTO = "auto"  # Automatically select best available backend


@dataclass
class DocumentAnalysisResult:
    """Standardized result from document analysis."""
    documents: List[Document]
    backend_used: str
    metadata: Dict[str, Any]
    success: bool
    error: Optional[str] = None


class SimpleDocumentAnalysisService:
    """
    Simplified document analysis service that abstracts backend complexity.
    
    Features:
    - Single, clean API for document analysis
    - Automatic backend selection (DI preferred, falls back to CU)
    - Transparent authentication handling
    - Batch processing with configurable concurrency
    - Standardized output format
    - No schema analyzer dependencies
    
    Usage:
        service = SimpleDocumentAnalysisService()
        result = await service.analyze_documents(urls=["https://..."])
        if result.success:
            documents = result.documents
    """
    
    def __init__(
        self,
        backend: DocumentAnalysisBackend = DocumentAnalysisBackend.AUTO,
        max_concurrency: int = 5,
    ):
        """
        Initialize the simplified document analysis service.
        
        Args:
            backend: Which backend to use (AUTO selects best available)
            max_concurrency: Maximum number of concurrent document analyses
        """
        self.backend = backend
        self.max_concurrency = max_concurrency
        self._selected_backend: Optional[str] = None
        self._di_service: Optional[DocumentIntelligenceService] = None
        self._cu_service: Optional[CUStandardIngestionServiceV2] = None
        
        logger.info(
            f"SimpleDocumentAnalysisService initialized with backend={backend}, "
            f"max_concurrency={max_concurrency}"
        )
    
    def _get_available_backends(self) -> List[str]:
        """Determine which backends are configured and available."""
        available = []
        
        # Check Document Intelligence
        # Note: DI service has backwards compatibility - it can use the CU endpoint
        # if DI endpoint is not set. This allows gradual migration from CU to DI.
        di_endpoint = settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT or settings.AZURE_CONTENT_UNDERSTANDING_ENDPOINT
        
        if di_endpoint:
            # DI is available if endpoint exists (auth is handled by the DI service itself)
            available.append(DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE)
        
        # Check Content Understanding  
        if settings.AZURE_CONTENT_UNDERSTANDING_ENDPOINT:
            # CU is available if endpoint exists (auth is handled by the CU service itself)
            available.append(DocumentAnalysisBackend.CONTENT_UNDERSTANDING)
        
        return available
    
    def _select_backend(self) -> str:
        """Select the best available backend based on configuration."""
        if self._selected_backend:
            return self._selected_backend
        
        available = self._get_available_backends()
        
        if not available:
            raise RuntimeError(
                "No document analysis backend is configured. "
                "Please set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT or "
                "AZURE_CONTENT_UNDERSTANDING_ENDPOINT"
            )
        
        # If specific backend requested, validate it's available
        if self.backend != DocumentAnalysisBackend.AUTO:
            if self.backend not in available:
                raise RuntimeError(
                    f"Requested backend {self.backend} is not configured. "
                    f"Available: {available}"
                )
            self._selected_backend = self.backend
        else:
            # Auto mode: prefer Document Intelligence (more stable, better features)
            if DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE in available:
                self._selected_backend = DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE
            else:
                self._selected_backend = available[0]
        
        logger.info(f"Selected document analysis backend: {self._selected_backend}")
        return self._selected_backend
    
    async def analyze_documents(
        self,
        urls: Optional[List[str]] = None,
        texts: Optional[List[str]] = None,
        enable_section_chunking: bool = True,
    ) -> DocumentAnalysisResult:
        """
        Analyze documents from URLs or raw text.
        
        This is the main entry point for document analysis. It automatically:
        - Selects the best available backend
        - Handles authentication
        - Processes documents with configurable concurrency
        - Returns standardized output
        
        Args:
            urls: List of document URLs to analyze (optional)
            texts: List of raw text content to analyze (optional)
            enable_section_chunking: If True, use section-aware chunking (V2 behavior)
        
        Returns:
            DocumentAnalysisResult with documents, metadata, and status
        """
        if not urls and not texts:
            return DocumentAnalysisResult(
                documents=[],
                backend_used="none",
                metadata={},
                success=False,
                error="No URLs or texts provided for analysis"
            )
        
        try:
            backend = self._select_backend()
            
            # Initialize backend service if not already done
            if backend == DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE:
                if not self._di_service:
                    self._di_service = DocumentIntelligenceService(
                        max_concurrency=self.max_concurrency
                    )
                service = self._di_service
            else:
                if not self._cu_service:
                    self._cu_service = CUStandardIngestionServiceV2()
                service = self._cu_service
            
            # Process documents
            documents = []
            failed_urls = []
            failed_texts = []
            metadata = {
                "backend": backend,
                "section_chunking_enabled": enable_section_chunking,
                "total_urls": len(urls or []),
                "total_texts": len(texts or []),
            }
            
            # Process URLs
            if urls:
                logger.info(f"Analyzing {len(urls)} documents from URLs using {backend}")
                
                if backend == DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE:
                    # DI has native batch processing via extract_documents
                    try:
                        # DocumentIntelligenceService needs group_id
                        group_id = "default"  # Could be passed as parameter if needed
                        url_docs = await service.extract_documents(group_id, urls)
                        documents.extend(url_docs)
                    except Exception as e:
                        logger.error(f"Failed to analyze URLs in batch: {e}")
                        failed_urls.extend(urls)
                else:
                    # CU processes one at a time
                    for url in urls:
                        try:
                            doc_list = await service.ingest_from_url(url)
                            documents.extend(doc_list)
                        except Exception as e:
                            logger.error(f"Failed to analyze URL {url}: {e}")
                            failed_urls.append(url)
                            # Continue with other URLs instead of failing completely
            
            # Process texts
            if texts:
                logger.info(f"Analyzing {len(texts)} text documents using {backend}")
                
                for idx, text in enumerate(texts):
                    try:
                        if backend == DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE:
                            # DI doesn't support direct text input
                            error_msg = (
                                f"Document Intelligence doesn't support direct text input. "
                                f"Text document {idx} skipped. Use Content Understanding backend "
                                f"or convert text to document URL."
                            )
                            logger.warning(error_msg)
                            failed_texts.append(idx)
                        else:
                            doc_list = await service.ingest_from_text(text, f"text_{idx}")
                            documents.extend(doc_list)
                    except Exception as e:
                        logger.error(f"Failed to analyze text {idx}: {e}")
                        failed_texts.append(idx)
            
            metadata["documents_extracted"] = len(documents)
            if failed_urls:
                metadata["failed_urls"] = failed_urls
                metadata["failed_url_count"] = len(failed_urls)
            if failed_texts:
                metadata["failed_texts"] = failed_texts
                metadata["failed_text_count"] = len(failed_texts)
            
            logger.info(
                f"Document analysis complete: {len(documents)} documents extracted "
                f"using {backend}"
            )
            
            return DocumentAnalysisResult(
                documents=documents,
                backend_used=backend,
                metadata=metadata,
                success=True,
            )
            
        except Exception as e:
            logger.error(f"Document analysis failed: {e}", exc_info=True)
            return DocumentAnalysisResult(
                documents=[],
                backend_used=self._selected_backend or "unknown",
                metadata={},
                success=False,
                error=str(e),
            )
    
    async def analyze_single_document(
        self,
        url: Optional[str] = None,
        text: Optional[str] = None,
    ) -> DocumentAnalysisResult:
        """
        Analyze a single document (convenience method).
        
        Args:
            url: Document URL (optional)
            text: Raw text content (optional)
        
        Returns:
            DocumentAnalysisResult
        """
        urls = [url] if url else None
        texts = [text] if text else None
        return await self.analyze_documents(urls=urls, texts=texts)
    
    def get_backend_info(self) -> Dict[str, Any]:
        """
        Get information about the selected backend and configuration.
        
        Returns:
            Dict with backend details, availability, and configuration
        """
        available_backends = self._get_available_backends()
        
        return {
            "available_backends": available_backends,
            "selected_backend": self._selected_backend,
            "requested_backend": self.backend,
            "max_concurrency": self.max_concurrency,
            "configuration": {
                "di_endpoint": bool(settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT),
                "di_key": bool(settings.AZURE_DOCUMENT_INTELLIGENCE_KEY),
                "cu_endpoint": bool(settings.AZURE_CONTENT_UNDERSTANDING_ENDPOINT),
                "cu_key": bool(settings.AZURE_CONTENT_UNDERSTANDING_API_KEY),
            }
        }
