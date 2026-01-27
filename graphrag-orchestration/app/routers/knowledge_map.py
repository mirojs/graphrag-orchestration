"""
Knowledge Map Document Processing API

A simplified, batch-first API for document processing that follows
Azure Content Understanding patterns but with a cleaner interface.

Design Decisions:
- Batch-first: `inputs[]` array always (single doc = array of 1)
- Async polling: POST /process -> GET /operations/{id} with Retry-After
- Fail-fast: Stop on first error (no partial success)
- 60s TTL: Results expire 60 seconds after terminal state
- Flat response: {status, documents: [{id, markdown, chunks, embeddings}]}
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Response, status

from app.services.simple_document_analysis_service import (
    SimpleDocumentAnalysisService,
    DocumentAnalysisBackend,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/knowledge-map",
    tags=["knowledge-map"],
)


# ============================================================================
# Operation Store (in-memory with TTL)
# ============================================================================

class OperationStatus(str, Enum):
    """Operation status values."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OperationStore:
    """
    In-memory store for async operations with 60s TTL after terminal state.
    
    Thread-safe for concurrent access. Operations are cleaned up
    when they expire or on periodic cleanup.
    """
    
    TTL_SECONDS = 60  # Time to keep completed operations
    
    def __init__(self):
        self._operations: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
    
    async def create(self, operation_id: str, request: Dict[str, Any]) -> None:
        """Create a new pending operation."""
        async with self._lock:
            self._operations[operation_id] = {
                "id": operation_id,
                "status": OperationStatus.PENDING,
                "request": request,
                "result": None,
                "error": None,
                "created_at": datetime.utcnow().isoformat(),
                "completed_at": None,
                "expires_at": None,
            }
    
    async def get(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get operation by ID, returns None if not found or expired."""
        async with self._lock:
            op = self._operations.get(operation_id)
            if not op:
                return None
            
            # Check if expired
            if op.get("expires_at"):
                expires = datetime.fromisoformat(op["expires_at"])
                if datetime.utcnow() > expires:
                    del self._operations[operation_id]
                    return None
            
            return op.copy()
    
    async def update(
        self,
        operation_id: str,
        status: OperationStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update operation status and set TTL if terminal."""
        async with self._lock:
            if operation_id not in self._operations:
                return
            
            op = self._operations[operation_id]
            op["status"] = status
            
            if result is not None:
                op["result"] = result
            if error is not None:
                op["error"] = error
            
            # Set expiry on terminal states
            if status in (OperationStatus.SUCCEEDED, OperationStatus.FAILED):
                op["completed_at"] = datetime.utcnow().isoformat()
                expires = datetime.utcnow() + timedelta(seconds=self.TTL_SECONDS)
                op["expires_at"] = expires.isoformat()
    
    async def cleanup_expired(self) -> int:
        """Remove expired operations. Returns count of removed."""
        async with self._lock:
            now = datetime.utcnow()
            expired = [
                oid for oid, op in self._operations.items()
                if op.get("expires_at") and datetime.fromisoformat(op["expires_at"]) < now
            ]
            for oid in expired:
                del self._operations[oid]
            return len(expired)


# Global operation store
_operation_store = OperationStore()


# ============================================================================
# Request/Response Models
# ============================================================================

class DocumentInput(BaseModel):
    """Single document input."""
    id: str = Field(..., description="Client-provided document ID")
    url: Optional[str] = Field(None, description="Document URL (PDF, DOCX, etc.)")
    content: Optional[str] = Field(None, description="Raw text content")


class ProcessRequest(BaseModel):
    """Request model for document processing."""
    inputs: List[DocumentInput] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Array of documents to process (1-100)"
    )
    options: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Processing options"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "inputs": [
                    {"id": "doc-1", "url": "https://example.com/report.pdf"},
                    {"id": "doc-2", "content": "Raw text content here..."}
                ],
                "options": {
                    "enable_section_chunking": True
                }
            }
        }


class DocumentResult(BaseModel):
    """Processed document result."""
    id: str = Field(..., description="Document ID from input")
    markdown: str = Field(..., description="Extracted content in markdown")
    chunks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Section-aware chunks with metadata"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Document metadata (pages, tables, etc.)"
    )


class ProcessResponse(BaseModel):
    """Response model for completed processing."""
    status: OperationStatus
    documents: List[DocumentResult] = Field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OperationResponse(BaseModel):
    """Response for operation status check."""
    operation_id: str
    status: OperationStatus
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[ProcessResponse] = None
    error: Optional[str] = None


class ProcessStartResponse(BaseModel):
    """Response when processing starts (returns operation ID)."""
    operation_id: str
    status: OperationStatus = OperationStatus.PENDING
    poll_url: str


# ============================================================================
# Background Processing
# ============================================================================

async def _process_documents(operation_id: str, request: ProcessRequest) -> None:
    """
    Background task to process documents.
    
    Implements fail-fast: stops on first error.
    """
    try:
        await _operation_store.update(operation_id, OperationStatus.RUNNING)
        
        # Initialize service
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.AUTO,
            max_concurrency=5,
        )
        
        # Separate URLs and texts
        urls_with_ids = []
        texts_with_ids = []
        
        for doc_input in request.inputs:
            if not doc_input.url and not doc_input.content:
                # Fail-fast on invalid input
                raise ValueError(f"Document '{doc_input.id}' has neither url nor content")
            
            if doc_input.url:
                urls_with_ids.append((doc_input.id, doc_input.url))
            else:
                texts_with_ids.append((doc_input.id, doc_input.content))
        
        # Process documents
        documents_result = []
        options = request.options or {}
        enable_section_chunking = options.get("enable_section_chunking", True)
        
        # Process all URLs in batch
        if urls_with_ids:
            url_list = [url for _, url in urls_with_ids]
            result = await service.analyze_documents(
                urls=url_list,
                enable_section_chunking=enable_section_chunking,
            )
            
            if not result.success:
                # Fail-fast: stop on error
                raise RuntimeError(f"Failed to process documents: {result.error}")
            
            # Convert to our response format
            # Map documents back to IDs (assuming same order)
            for (doc_id, _), doc in zip(urls_with_ids, result.documents):
                documents_result.append(DocumentResult(
                    id=doc_id,
                    markdown=doc.text or "",
                    chunks=[{
                        "text": doc.text or "",
                        "metadata": doc.metadata,
                    }],
                    metadata=doc.metadata,
                ))
        
        # Process texts one at a time for fail-fast behavior
        for doc_id, text in texts_with_ids:
            result = await service.analyze_documents(
                texts=[text],
                enable_section_chunking=enable_section_chunking,
            )
            
            if not result.success:
                # Fail-fast: stop on first error
                raise RuntimeError(f"Failed to process document '{doc_id}': {result.error}")
            
            for doc in result.documents:
                documents_result.append(DocumentResult(
                    id=doc_id,
                    markdown=doc.text or "",
                    chunks=[{
                        "text": doc.text or "",
                        "metadata": doc.metadata,
                    }],
                    metadata=doc.metadata,
                ))
        
        # Success - store result
        response = ProcessResponse(
            status=OperationStatus.SUCCEEDED,
            documents=documents_result,
            metadata={
                "total_documents": len(documents_result),
                "backend_used": service._selected_backend,
            }
        )
        
        await _operation_store.update(
            operation_id,
            OperationStatus.SUCCEEDED,
            result=response.model_dump(),
        )
        
        logger.info(
            f"Operation {operation_id} completed: {len(documents_result)} documents processed"
        )
        
    except Exception as e:
        logger.error(f"Operation {operation_id} failed: {e}", exc_info=True)
        
        error_response = ProcessResponse(
            status=OperationStatus.FAILED,
            error=str(e),
        )
        
        await _operation_store.update(
            operation_id,
            OperationStatus.FAILED,
            result=error_response.model_dump(),
            error=str(e),
        )


# ============================================================================
# API Endpoints
# ============================================================================

@router.post(
    "/process",
    response_model=ProcessStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start document processing",
    description="""
    Start processing a batch of documents asynchronously.
    
    Returns immediately with an operation ID. Poll `/operations/{operation_id}`
    to check status and retrieve results.
    
    **Design:**
    - Batch-first: Always provide `inputs[]` array (even for single document)
    - Fail-fast: Processing stops on first error (no partial results)
    - 60s TTL: Results expire 60 seconds after completion
    
    **Example:**
    ```json
    {
        "inputs": [
            {"id": "doc-1", "url": "https://example.com/report.pdf"}
        ]
    }
    ```
    """,
)
async def process_documents(request: ProcessRequest) -> ProcessStartResponse:
    """
    Start document processing.
    
    Returns operation ID for polling.
    """
    # Validate inputs
    for doc_input in request.inputs:
        if not doc_input.url and not doc_input.content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document '{doc_input.id}' must have either 'url' or 'content'"
            )
    
    # Create operation
    operation_id = str(uuid.uuid4())
    await _operation_store.create(operation_id, request.model_dump())
    
    # Start background processing
    asyncio.create_task(_process_documents(operation_id, request))
    
    logger.info(f"Started operation {operation_id} with {len(request.inputs)} documents")
    
    return ProcessStartResponse(
        operation_id=operation_id,
        status=OperationStatus.PENDING,
        poll_url=f"/api/v1/knowledge-map/operations/{operation_id}",
    )


@router.get(
    "/operations/{operation_id}",
    response_model=OperationResponse,
    summary="Get operation status",
    description="""
    Poll this endpoint to check processing status.
    
    **Status values:**
    - `pending`: Operation queued
    - `running`: Processing in progress
    - `succeeded`: Completed successfully (result available)
    - `failed`: Failed (error message available)
    
    **Headers:**
    - `Retry-After: 2` returned while status is `pending` or `running`
    
    **TTL:**
    Results expire 60 seconds after reaching terminal state (succeeded/failed).
    """,
)
async def get_operation(operation_id: str, response: Response) -> OperationResponse:
    """
    Get operation status and result.
    
    Returns Retry-After header while processing.
    """
    operation = await _operation_store.get(operation_id)
    
    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operation '{operation_id}' not found or expired"
        )
    
    # Add Retry-After header while processing
    if operation["status"] in (OperationStatus.PENDING, OperationStatus.RUNNING):
        response.headers["Retry-After"] = "2"
    
    # Build response
    result = None
    if operation.get("result"):
        result = ProcessResponse(**operation["result"])
    
    return OperationResponse(
        operation_id=operation["id"],
        status=operation["status"],
        created_at=operation["created_at"],
        completed_at=operation.get("completed_at"),
        result=result,
        error=operation.get("error"),
    )


@router.delete(
    "/operations/{operation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel/delete operation",
    description="Cancel a pending operation or delete a completed one.",
)
async def delete_operation(operation_id: str) -> None:
    """Delete or cancel an operation."""
    operation = await _operation_store.get(operation_id)
    
    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operation '{operation_id}' not found"
        )
    
    # Mark as failed if still running (cancellation)
    if operation["status"] in (OperationStatus.PENDING, OperationStatus.RUNNING):
        await _operation_store.update(
            operation_id,
            OperationStatus.FAILED,
            error="Cancelled by user"
        )
    
    logger.info(f"Operation {operation_id} deleted/cancelled")
