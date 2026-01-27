"""
Document Analysis API Router

Simplified API endpoints for document analysis that serve as a drop-in
replacement for Azure Content Understanding.

Features:
- Clean, simple API surface
- Automatic backend selection (no need to choose CU vs DI)
- Transparent authentication
- Batch processing support
- Standardized response format
"""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, status

from app.services.simple_document_analysis_service import (
    SimpleDocumentAnalysisService,
    DocumentAnalysisBackend,
    DocumentAnalysisResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/document-analysis",
    tags=["document-analysis"],
)


# Request/Response Models
class DocumentAnalysisRequest(BaseModel):
    """Request model for document analysis."""
    urls: Optional[List[str]] = Field(
        None,
        description="List of document URLs to analyze (PDF, DOCX, etc.)"
    )
    texts: Optional[List[str]] = Field(
        None,
        description="List of raw text content to analyze"
    )
    enable_section_chunking: bool = Field(
        default=True,
        description="Enable section-aware chunking for better retrieval"
    )
    backend: Optional[str] = Field(
        default="auto",
        description="Backend to use: 'auto', 'document_intelligence', or 'content_understanding'"
    )
    max_concurrency: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of concurrent document analyses"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "urls": ["https://example.com/document.pdf"],
                "enable_section_chunking": True,
                "backend": "auto",
                "max_concurrency": 5,
            }
        }


class DocumentInfo(BaseModel):
    """Information about an analyzed document."""
    doc_id: str
    text_preview: str = Field(..., description="First 200 characters of document text")
    metadata: dict = Field(default_factory=dict)


class DocumentAnalysisResponse(BaseModel):
    """Response model for document analysis."""
    success: bool
    backend_used: str
    documents_count: int
    documents: List[DocumentInfo]
    metadata: dict
    error: Optional[str] = None


class BackendInfoResponse(BaseModel):
    """Information about available backends."""
    available_backends: List[str]
    selected_backend: Optional[str]
    requested_backend: str
    max_concurrency: int
    configuration: dict


# API Endpoints
@router.post(
    "/analyze",
    response_model=DocumentAnalysisResponse,
    summary="Analyze documents",
    description="""
    Analyze documents from URLs or raw text content.
    
    This endpoint automatically selects the best available backend
    (Document Intelligence or Content Understanding) and processes
    the documents with optimal settings.
    
    The response includes:
    - Extracted document content with metadata
    - Section hierarchy (if section chunking enabled)
    - Tables and structured data
    - Page numbers and bounding boxes
    
    This is a drop-in replacement for Azure Content Understanding
    with a simpler, more reliable API.
    """,
)
async def analyze_documents(request: DocumentAnalysisRequest) -> DocumentAnalysisResponse:
    """
    Analyze documents from URLs or text content.
    
    Args:
        request: DocumentAnalysisRequest with URLs or texts
    
    Returns:
        DocumentAnalysisResponse with analyzed documents
    
    Raises:
        HTTPException: If analysis fails
    """
    if not request.urls and not request.texts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'urls' or 'texts' must be provided"
        )
    
    # Parse backend
    backend = DocumentAnalysisBackend.AUTO
    if request.backend:
        try:
            backend = DocumentAnalysisBackend(request.backend.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid backend: {request.backend}. Must be 'auto', "
                       f"'document_intelligence', or 'content_understanding'"
            )
    
    # Create service
    service = SimpleDocumentAnalysisService(
        backend=backend,
        max_concurrency=request.max_concurrency,
    )
    
    # Analyze documents
    result = await service.analyze_documents(
        urls=request.urls,
        texts=request.texts,
        enable_section_chunking=request.enable_section_chunking,
    )
    
    # Handle errors
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Document analysis failed"
        )
    
    # Build response
    documents_info = []
    for doc in result.documents:
        # Handle None text gracefully
        doc_text = doc.text if doc.text is not None else ""
        text_preview = doc_text[:200] if len(doc_text) > 200 else doc_text
        documents_info.append(
            DocumentInfo(
                doc_id=doc.doc_id or "unknown",
                text_preview=text_preview,
                metadata=doc.metadata,
            )
        )
    
    return DocumentAnalysisResponse(
        success=True,
        backend_used=result.backend_used,
        documents_count=len(result.documents),
        documents=documents_info,
        metadata=result.metadata,
    )


@router.get(
    "/backend-info",
    response_model=BackendInfoResponse,
    summary="Get backend information",
    description="""
    Get information about available document analysis backends
    and current configuration.
    
    Useful for debugging and understanding which backend will
    be used for document analysis.
    """,
)
async def get_backend_info(backend: str = "auto") -> BackendInfoResponse:
    """
    Get information about available backends.
    
    Args:
        backend: Requested backend (auto, document_intelligence, content_understanding)
    
    Returns:
        BackendInfoResponse with configuration details
    """
    # Parse backend
    backend_enum = DocumentAnalysisBackend.AUTO
    if backend:
        try:
            backend_enum = DocumentAnalysisBackend(backend.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid backend: {backend}"
            )
    
    # Create service to get info
    service = SimpleDocumentAnalysisService(backend=backend_enum)
    info = service.get_backend_info()
    
    return BackendInfoResponse(**info)


@router.post(
    "/analyze-single",
    response_model=DocumentAnalysisResponse,
    summary="Analyze a single document",
    description="""
    Convenience endpoint for analyzing a single document.
    
    Simplified version of /analyze for single document use cases.
    """,
)
async def analyze_single_document(
    url: Optional[str] = None,
    text: Optional[str] = None,
    enable_section_chunking: bool = True,
) -> DocumentAnalysisResponse:
    """
    Analyze a single document.
    
    Args:
        url: Document URL (optional)
        text: Raw text content (optional)
        enable_section_chunking: Enable section-aware chunking
    
    Returns:
        DocumentAnalysisResponse
    
    Raises:
        HTTPException: If neither URL nor text provided
    """
    if not url and not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'url' or 'text' must be provided"
        )
    
    # Use the batch endpoint with single item
    request = DocumentAnalysisRequest(
        urls=[url] if url else None,
        texts=[text] if text else None,
        enable_section_chunking=enable_section_chunking,
    )
    
    return await analyze_documents(request)
