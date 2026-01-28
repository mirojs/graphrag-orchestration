"""
Document Lifecycle API Router for V2 GraphRAG.

Provides REST endpoints for document deprecation, restoration, and deletion.
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field

from app.hybrid_v2.services.document_lifecycle import (
    DocumentLifecycleService,
    DocumentStatus,
    DeprecationResult,
    RestorationResult,
    DeletionResult,
)
from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3
from app.core.config import settings

router = APIRouter(prefix="/api/v2/lifecycle", tags=["document-lifecycle"])


# ==================== Request/Response Models ====================

class DeprecateRequest(BaseModel):
    """Request to deprecate a document."""
    reason: Optional[str] = Field(None, description="Reason for deprecation")
    deprecated_by: Optional[str] = Field(None, description="User or system identifier")


class BulkDeprecateRequest(BaseModel):
    """Request to deprecate multiple documents."""
    document_ids: List[str] = Field(..., description="List of document IDs to deprecate")
    reason: Optional[str] = Field(None, description="Reason for deprecation")
    deprecated_by: Optional[str] = Field(None, description="User or system identifier")


class DeprecationResponse(BaseModel):
    """Response from deprecation operation."""
    document_id: str
    group_id: str
    success: bool
    children_deprecated: int
    gds_marked_stale: bool
    errors: List[str]


class RestorationResponse(BaseModel):
    """Response from restoration operation."""
    document_id: str
    group_id: str
    success: bool
    children_restored: int
    errors: List[str]


class DeletionResponse(BaseModel):
    """Response from hard deletion operation."""
    document_id: str
    group_id: str
    success: bool
    chunks_deleted: int
    sections_deleted: int
    entities_orphaned: int
    edges_deleted: int
    vectors_removed: int
    errors: List[str]


class DocumentListResponse(BaseModel):
    """Response containing list of documents."""
    documents: List[dict]
    total: int


class ImpactResponse(BaseModel):
    """Response showing impact of deprecation/deletion."""
    document_id: str
    title: Optional[str]
    is_deprecated: bool
    chunk_count: int
    section_count: int
    orphan_entities: int
    table_count: int
    figure_count: int
    keyvalue_count: int


# ==================== Helper ====================

def get_lifecycle_service() -> DocumentLifecycleService:
    """Get or create DocumentLifecycleService instance."""
    # settings imported from app.core.config
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE,
    )
    return DocumentLifecycleService(neo4j_store)


# ==================== Endpoints ====================

@router.post(
    "/groups/{group_id}/documents/{document_id}/deprecate",
    response_model=DeprecationResponse,
    summary="Deprecate a document",
    description="Soft-delete a document by marking it as deprecated. Children are cascaded.",
)
async def deprecate_document(
    group_id: str,
    document_id: str,
    request: Optional[DeprecateRequest] = None,
):
    """Deprecate a document (soft delete)."""
    service = get_lifecycle_service()
    
    result = await service.deprecate_document(
        group_id=group_id,
        document_id=document_id,
        reason=request.reason if request else None,
        deprecated_by=request.deprecated_by if request else None,
    )
    
    if not result.success:
        raise HTTPException(status_code=404, detail=result.errors)
    
    return DeprecationResponse(
        document_id=result.document_id,
        group_id=result.group_id,
        success=result.success,
        children_deprecated=result.children_deprecated,
        gds_marked_stale=result.gds_marked_stale,
        errors=result.errors,
    )


@router.post(
    "/groups/{group_id}/documents/{document_id}/restore",
    response_model=RestorationResponse,
    summary="Restore a deprecated document",
    description="Restore a previously deprecated document and its children.",
)
async def restore_document(
    group_id: str,
    document_id: str,
):
    """Restore a deprecated document."""
    service = get_lifecycle_service()
    
    result = await service.restore_document(
        group_id=group_id,
        document_id=document_id,
    )
    
    if not result.success:
        raise HTTPException(status_code=404, detail=result.errors)
    
    return RestorationResponse(
        document_id=result.document_id,
        group_id=result.group_id,
        success=result.success,
        children_restored=result.children_restored,
        errors=result.errors,
    )


@router.delete(
    "/groups/{group_id}/documents/{document_id}",
    response_model=DeletionResponse,
    summary="Hard delete a document",
    description="Permanently delete a document. Requires confirmation.",
)
async def hard_delete_document(
    group_id: str,
    document_id: str,
    confirm: bool = Query(False, description="Must be true to confirm deletion"),
    orphan_cleanup: bool = Query(True, description="Delete orphaned entities"),
):
    """Hard delete a document (permanent)."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Deletion requires confirm=true query parameter"
        )
    
    service = get_lifecycle_service()
    
    result = await service.hard_delete_document(
        group_id=group_id,
        document_id=document_id,
        orphan_cleanup=orphan_cleanup,
    )
    
    return DeletionResponse(
        document_id=result.document_id,
        group_id=result.group_id,
        success=result.success,
        chunks_deleted=result.chunks_deleted,
        sections_deleted=result.sections_deleted,
        entities_orphaned=result.entities_orphaned,
        edges_deleted=result.edges_deleted,
        vectors_removed=result.vectors_removed,
        errors=result.errors,
    )


@router.post(
    "/groups/{group_id}/documents/bulk-deprecate",
    response_model=List[DeprecationResponse],
    summary="Bulk deprecate documents",
    description="Deprecate multiple documents in a single request.",
)
async def bulk_deprecate_documents(
    group_id: str,
    request: BulkDeprecateRequest,
):
    """Bulk deprecate multiple documents."""
    service = get_lifecycle_service()
    
    results = []
    for doc_id in request.document_ids:
        result = await service.deprecate_document(
            group_id=group_id,
            document_id=doc_id,
            reason=request.reason,
            deprecated_by=request.deprecated_by,
        )
        results.append(DeprecationResponse(
            document_id=result.document_id,
            group_id=result.group_id,
            success=result.success,
            children_deprecated=result.children_deprecated,
            gds_marked_stale=result.gds_marked_stale,
            errors=result.errors,
        ))
    
    return results


@router.get(
    "/groups/{group_id}/documents",
    response_model=DocumentListResponse,
    summary="List documents by status",
    description="List documents in a group, optionally filtered by lifecycle status.",
)
async def list_documents(
    group_id: str,
    status: Optional[str] = Query(None, description="Filter: active, deprecated, or all"),
    limit: int = Query(100, ge=1, le=1000),
):
    """List documents with optional status filter."""
    service = get_lifecycle_service()
    
    doc_status = None
    if status == "active":
        doc_status = DocumentStatus.ACTIVE
    elif status == "deprecated":
        doc_status = DocumentStatus.DEPRECATED
    
    documents = await service.list_documents(
        group_id=group_id,
        status=doc_status,
        limit=limit,
    )
    
    return DocumentListResponse(
        documents=documents,
        total=len(documents),
    )


@router.get(
    "/groups/{group_id}/documents/{document_id}/impact",
    response_model=ImpactResponse,
    summary="Preview deprecation impact",
    description="Show what would be affected by deprecating/deleting a document.",
)
async def get_document_impact(
    group_id: str,
    document_id: str,
):
    """Preview the impact of deprecating/deleting a document."""
    service = get_lifecycle_service()
    
    impact = await service.get_document_impact(
        group_id=group_id,
        document_id=document_id,
    )
    
    if "error" in impact:
        raise HTTPException(status_code=404, detail=impact["error"])
    
    return ImpactResponse(
        document_id=impact.get("document_id", document_id),
        title=impact.get("title"),
        is_deprecated=impact.get("is_deprecated", False),
        chunk_count=impact.get("chunk_count", 0),
        section_count=impact.get("section_count", 0),
        orphan_entities=impact.get("orphan_entities", 0),
        table_count=impact.get("table_count", 0),
        figure_count=impact.get("figure_count", 0),
        keyvalue_count=impact.get("keyvalue_count", 0),
    )
