"""
Document Management API Endpoints

Provides REST API for managing individual documents in the GraphRAG system.
Supports adding, removing, and updating documents with proper orphan cleanup.
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from app.archive.v3.services.neo4j_store import Neo4jStoreV3
from app.archive.v3.services.document_manager import DocumentManager, DocumentDeletionResult
from app.core.config import settings

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graphrag/v3/documents", tags=["Document Management"])


class DocumentDeleteRequest(BaseModel):
    """Request to delete a document."""
    document_id: str
    orphan_cleanup: bool = True


class DocumentImpactResponse(BaseModel):
    """Impact analysis of deleting a document."""
    document_id: str
    chunks: int
    entities_total: int
    entities_orphaned: int
    warning: Optional[str] = None


class DocumentListItem(BaseModel):
    """Document summary in list."""
    id: str
    title: str
    source: str
    updated_at: str
    chunk_count: int
    entity_count: int


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    orphan_cleanup: bool = True,
    x_group_id: str = Header(..., alias="X-Group-ID")
):
    """
    Delete a document and optionally clean up orphaned entities.
    
    **Orphan Cleanup:**
    When `orphan_cleanup=True` (default), entities that were ONLY mentioned in
    this document will be deleted. Entities mentioned in other documents are preserved.
    
    **Example:**
    - Document A mentions "Einstein" and "Tesla"
    - Document B also mentions "Einstein"
    - Deleting Document A with orphan_cleanup=True:
      - ✅ "Einstein" is preserved (still in Document B)
      - ❌ "Tesla" is deleted (orphaned)
    
    **Use Cases:**
    - `orphan_cleanup=True`: Normal deletion (recommended)
    - `orphan_cleanup=False`: Keep entities for analysis even if document removed
    """
    try:
        neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
            database=settings.NEO4J_DATABASE
        )
        
        manager = DocumentManager(neo4j_store)
        result = manager.delete_document(x_group_id, document_id, orphan_cleanup)
        
        neo4j_store.close()
        
        if not result.document_deleted:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        
        return {
            "status": "deleted",
            "document_id": document_id,
            "group_id": x_group_id,
            "deleted": {
                "chunks": result.chunks_deleted,
                "entities": result.entities_orphaned,
                "communities": result.communities_affected,
                "relationships": result.relationships_deleted
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to delete document {document_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/impact")
async def get_deletion_impact(
    document_id: str,
    x_group_id: str = Header(..., alias="X-Group-ID")
):
    """
    Analyze the impact of deleting a document.
    
    Shows how many chunks, entities, and orphaned entities would be affected.
    Useful for confirming deletions before executing them.
    
    **Response:**
    - `chunks`: Number of text chunks that will be deleted
    - `entities_total`: Total entities mentioned in this document
    - `entities_orphaned`: Entities that would become orphaned (not in other docs)
    """
    try:
        neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
            database=settings.NEO4J_DATABASE
        )
        
        manager = DocumentManager(neo4j_store)
        impact = manager.get_document_impact(x_group_id, document_id)
        
        neo4j_store.close()
        
        warning = None
        if impact["entities_orphaned"] > 0:
            warning = f"{impact['entities_orphaned']} entities will be permanently deleted (not mentioned in other documents)"
        
        return DocumentImpactResponse(
            document_id=document_id,
            chunks=impact["chunks"],
            entities_total=impact["entities_total"],
            entities_orphaned=impact["entities_orphaned"],
            warning=warning
        )
        
    except Exception as e:
        logger.error(f"Failed to analyze impact for {document_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_documents(
    x_group_id: str = Header(..., alias="X-Group-ID")
):
    """
    List all documents in a group with statistics.
    
    Returns document metadata along with:
    - Number of chunks
    - Number of unique entities mentioned
    - Last update timestamp
    """
    try:
        neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
            database=settings.NEO4J_DATABASE
        )
        
        manager = DocumentManager(neo4j_store)
        documents = manager.list_documents(x_group_id)
        
        neo4j_store.close()
        
        return {
            "group_id": x_group_id,
            "count": len(documents),
            "documents": documents
        }
        
    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
