"""
Folder CRUD Endpoints

Provides hierarchical folder organization for documents.
Supports multi-tenant isolation via group_id or user_id.
"""

from contextlib import contextmanager
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request
from typing import List, Optional
from pydantic import BaseModel
import structlog
from datetime import datetime

from src.core.models.folder import Folder, FolderCreate, FolderUpdate
from src.worker.services import GraphService

router = APIRouter(prefix="/folders", tags=["folders"])
logger = structlog.get_logger()


def _folder_from_record(record) -> Folder:
    """Build a Folder model from a Neo4j result record."""
    return Folder(
        id=record["id"],
        name=record["name"],
        group_id=record["group_id"],
        parent_folder_id=record["parent_folder_id"],
        folder_type=record.get("folder_type") or "user",
        analysis_status=record.get("analysis_status"),
        analysis_group_id=record.get("analysis_group_id"),
        source_folder_id=record.get("source_folder_id"),
        analyzed_at=record.get("analyzed_at"),
        file_count=record.get("file_count"),
        entity_count=record.get("entity_count"),
        community_count=record.get("community_count"),
        analysis_files_total=record.get("analysis_files_total"),
        analysis_files_processed=record.get("analysis_files_processed"),
        section_count=record.get("section_count"),
        sentence_count=record.get("sentence_count"),
        relationship_count=record.get("relationship_count"),
        analysis_error=record.get("analysis_error"),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


# Standard RETURN clause for folder queries
_FOLDER_RETURN = """
    f.id as id, f.name as name, f.group_id as group_id,
    f.parent_folder_id as parent_folder_id,
    f.folder_type as folder_type,
    f.analysis_status as analysis_status,
    f.analysis_group_id as analysis_group_id,
    f.source_folder_id as source_folder_id,
    f.analyzed_at as analyzed_at,
    f.file_count as file_count,
    f.entity_count as entity_count,
    f.community_count as community_count,
    f.analysis_files_total as analysis_files_total,
    f.analysis_files_processed as analysis_files_processed,
    f.section_count as section_count,
    f.sentence_count as sentence_count,
    f.relationship_count as relationship_count,
    f.analysis_error as analysis_error,
    f.created_at as created_at, f.updated_at as updated_at
"""


def get_partition_id(request: Request) -> str:
    """Extract partition ID from request state (set by middleware)."""
    return request.state.group_id


def get_graph_driver():
    """Get Neo4j driver with reconnection attempt."""
    graph_service = GraphService()
    if not graph_service.driver:
        if not graph_service.reconnect():
            raise HTTPException(status_code=503, detail="Graph database unavailable")
    return graph_service.driver


@contextmanager
def graph_session(database: str = None):
    """Context manager yielding a Neo4j session with automatic retry.

    Usage for reads::

        with graph_session() as (read, _write):
            records = read(query, param1=val1)

    Usage for writes::

        with graph_session() as (_read, write):
            records = write(query, param1=val1)

    ``read`` / ``write`` wrap ``session.execute_read`` /
    ``session.execute_write`` which retry transient errors
    (network hiccups, leader changes) with exponential back-off.
    On non-transient failures the original Neo4j exception propagates
    and the outer error-handling middleware converts it to 503.
    """
    driver = get_graph_driver()
    db = database or None
    try:
        with driver.session(database=db) as session:

            def _run_read(query: str, **kwargs):
                def _tx(tx, q=query, kw=kwargs):
                    result = tx.run(q, **kw)
                    return list(result)
                return session.execute_read(_tx)

            def _run_write(query: str, **kwargs):
                def _tx(tx, q=query, kw=kwargs):
                    result = tx.run(q, **kw)
                    return list(result)
                return session.execute_write(_tx)

            yield _run_read, _run_write

    except HTTPException:
        raise
    except Exception as e:
        err = str(e)[:200]
        logger.warning("neo4j_session_error", error=err)
        # Trigger reconnect for next request
        try:
            GraphService().reconnect()
        except Exception:
            pass
        raise HTTPException(status_code=503, detail=f"Database temporarily busy: {err}")


@router.post("", response_model=Folder)
async def create_folder(
    folder: FolderCreate,
    partition_id: str = Depends(get_partition_id)
):
    """
    Create a new folder.
    
    Args:
        folder: Folder creation data
        partition_id: Group/user ID from auth middleware
    
    Returns:
        Created folder
    """
    # Validate parent exists (unlimited depth allowed)
    if folder.parent_folder_id:
        parent_query = """
        MATCH (f:Folder {id: $parent_id, group_id: $partition_id})
        RETURN f.id as id
        """
        with graph_session() as (read, _write):
            result = read(parent_query,
                          parent_id=folder.parent_folder_id,
                          partition_id=partition_id)
            if not result:
                raise HTTPException(status_code=404, detail="Parent folder not found")
    
    # Create folder
    create_query = """
    CREATE (f:Folder {
        id: randomUUID(),
        name: $name,
        group_id: $partition_id,
        parent_folder_id: $parent_folder_id,
        folder_type: $folder_type,
        analysis_status: CASE WHEN $folder_type = 'user' THEN 'not_analyzed' ELSE null END,
        created_at: datetime(),
        updated_at: datetime()
    })
    WITH f
    OPTIONAL MATCH (parent:Folder {id: $parent_folder_id, group_id: $partition_id})
    FOREACH (_ IN CASE WHEN parent IS NOT NULL THEN [1] ELSE [] END |
        CREATE (f)-[:SUBFOLDER_OF]->(parent)
    )
    RETURN f.id as id, f.name as name, f.group_id as group_id, 
           f.parent_folder_id as parent_folder_id,
           f.folder_type as folder_type,
           f.analysis_status as analysis_status,
           f.analysis_group_id as analysis_group_id,
           f.source_folder_id as source_folder_id,
           f.analyzed_at as analyzed_at,
           f.file_count as file_count,
           f.entity_count as entity_count,
           f.community_count as community_count,
           f.created_at as created_at, f.updated_at as updated_at
    """
    
    with graph_session() as (_read, write):
        records = write(create_query,
                        name=folder.name,
                        partition_id=partition_id,
                        parent_folder_id=folder.parent_folder_id,
                        folder_type=folder.folder_type)
        record = records[0] if records else None

    if not record:
        raise HTTPException(status_code=500, detail="Folder creation failed: no record returned from database")

    logger.info("folder_created", folder_id=record["id"], partition_id=partition_id)
    
    return _folder_from_record(record)


@router.get("", response_model=List[Folder])
async def list_folders(
    partition_id: str = Depends(get_partition_id),
    parent_folder_id: Optional[str] = None
):
    """
    List folders in the current partition.
    
    Args:
        partition_id: Group/user ID from auth middleware
        parent_folder_id: Filter by parent folder. If omitted, returns all folders.
    
    Returns:
        List of folders
    """
    if parent_folder_id:
        query = f"""
        MATCH (f:Folder {{group_id: $partition_id}})
        WHERE f.parent_folder_id = $parent_folder_id
        RETURN {_FOLDER_RETURN}
        ORDER BY f.name
        """
    else:
        query = f"""
        MATCH (f:Folder {{group_id: $partition_id}})
        RETURN {_FOLDER_RETURN}
        ORDER BY f.name
        """
    
    with graph_session() as (read, _write):
        records = read(query,
                       partition_id=partition_id,
                       parent_folder_id=parent_folder_id)
        folders = [_folder_from_record(record) for record in records]
    
    return folders


@router.get("/{folder_id}", response_model=Folder)
async def get_folder(
    folder_id: str,
    partition_id: str = Depends(get_partition_id)
):
    """Get a specific folder."""
    query = f"""
    MATCH (f:Folder {{id: $folder_id, group_id: $partition_id}})
    RETURN {_FOLDER_RETURN}
    """
    
    with graph_session() as (read, _write):
        records = read(query, folder_id=folder_id, partition_id=partition_id)
        if not records:
            raise HTTPException(status_code=404, detail="Folder not found")
        return _folder_from_record(records[0])


@router.put("/{folder_id}", response_model=Folder)
async def update_folder(
    folder_id: str,
    folder_update: FolderUpdate,
    partition_id: str = Depends(get_partition_id)
):
    """Update a folder."""
    query = f"""
    MATCH (f:Folder {{id: $folder_id, group_id: $partition_id}})
    SET f.name = $name, f.updated_at = datetime()
    RETURN {_FOLDER_RETURN}
    """
    
    with graph_session() as (_read, write):
        records = write(query,
                        folder_id=folder_id,
                        partition_id=partition_id,
                        name=folder_update.name)
        if not records:
            raise HTTPException(status_code=404, detail="Folder not found")
        
        logger.info("folder_updated", folder_id=folder_id, partition_id=partition_id)
        return _folder_from_record(records[0])


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: str,
    partition_id: str = Depends(get_partition_id),
    cascade: bool = False
):
    """
    Delete a folder.
    
    Args:
        folder_id: Folder to delete
        partition_id: Group/user ID from auth middleware
        cascade: If True, delete subfolders and move documents to parent.
                 If False, fail if folder has children.
    """
    if not cascade:
        # Check if folder has children
        check_query = """
        MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
        OPTIONAL MATCH (child:Folder)-[:SUBFOLDER_OF]->(f)
        OPTIONAL MATCH (doc:Document)-[:IN_FOLDER]->(f)
        RETURN count(child) as child_count, count(doc) as doc_count
        """
        with graph_session() as (read, _write):
            records = read(check_query, folder_id=folder_id, partition_id=partition_id)
            record = records[0] if records else None
            
            if record and (record["child_count"] > 0 or record["doc_count"] > 0):
                raise HTTPException(
                    status_code=400,
                    detail="Folder has children. Use cascade=true to delete recursively."
                )
    
    # Delete folder (cascade handled by Neo4j relationship deletion)
    delete_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    OPTIONAL MATCH (f)<-[:IN_FOLDER]-(doc:Document)
    OPTIONAL MATCH (f)<-[:SUBFOLDER_OF]-(child:Folder)
    WITH f, collect(doc) as docs, collect(child) as children
    FOREACH (doc IN docs | SET doc.folder_id = f.parent_folder_id)
    FOREACH (child IN CASE WHEN $cascade THEN children ELSE [] END | DETACH DELETE child)
    DETACH DELETE f
    RETURN count(f) as deleted
    """
    
    with graph_session() as (_read, write):
        records = write(delete_query,
                        folder_id=folder_id,
                        partition_id=partition_id,
                        cascade=cascade)
        record = records[0] if records else None
        
        if not record or record["deleted"] == 0:
            raise HTTPException(status_code=404, detail="Folder not found")
    
    logger.info("folder_deleted", folder_id=folder_id, partition_id=partition_id, cascade=cascade)
    
    return {"status": "deleted", "folder_id": folder_id}


# =============================================================================
# Document-Folder Assignment Endpoints
# =============================================================================

class DocumentFolderAssignment(BaseModel):
    """Request model for assigning a document to a folder."""
    document_id: str
    folder_id: Optional[str] = None  # None to unassign (move to root/unfiled)


class BulkDocumentFolderAssignment(BaseModel):
    """Request model for bulk document-folder assignment."""
    document_ids: List[str]
    folder_id: Optional[str] = None


@router.post("/{folder_id}/documents")
async def assign_document_to_folder(
    folder_id: str,
    assignment: DocumentFolderAssignment,
    request: Request,
    background_tasks: BackgroundTasks,
    partition_id: str = Depends(get_partition_id)
):
    """
    Assign a document to a folder.
    
    Creates an IN_FOLDER relationship between the document and folder.
    Removes any existing folder assignment first (document can only be in one folder).
    
    When the document moves between root folders (different Neo4j partitions),
    triggers a background delete + re-index to migrate the graph data.
    
    Args:
        folder_id: Target folder ID
        assignment: Document ID to assign
        request: FastAPI request (for doc_sync access)
        background_tasks: FastAPI background tasks
        partition_id: Group/user ID from auth middleware
    
    Returns:
        Assignment result with optional reindex status
    """
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    # Verify folder exists and belongs to this partition
    verify_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id
    """
    with graph_session() as (read, _write):
        if not read(verify_query, folder_id=folder_id, partition_id=partition_id):
            raise HTTPException(status_code=404, detail="Folder not found")
    
    # Determine old and new root folder IDs to detect cross-partition moves
    # Documents may have group_id = auth_group_id (unfiled) or root_folder_id (filed)
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id, get_valid_partition_ids

    valid_ids = await get_valid_partition_ids(partition_id)

    old_folder_query = """
    MATCH (d:Document {id: $document_id})
    WHERE d.group_id IN $valid_ids
    OPTIONAL MATCH (d)-[:IN_FOLDER]->(old_f:Folder)
    RETURN d.title as doc_title, d.source as doc_source, d.group_id as doc_group_id, old_f.id as old_folder_id
    """
    with graph_session() as (read, _write):
        records = read(old_folder_query,
                       document_id=assignment.document_id,
                       valid_ids=valid_ids)
        doc_record = records[0] if records else None
        if not doc_record:
            raise HTTPException(status_code=404, detail="Document not found")
    
    old_folder_id = doc_record["old_folder_id"]
    doc_title = doc_record["doc_title"]
    doc_source = doc_record["doc_source"]
    doc_current_gid = doc_record["doc_group_id"]

    old_neo4j_gid = await resolve_neo4j_group_id(partition_id, old_folder_id)
    new_neo4j_gid = await resolve_neo4j_group_id(partition_id, folder_id)
    cross_partition_move = old_neo4j_gid != new_neo4j_gid
    
    # Assign document to folder (remove existing assignment first)
    # Match document by its actual group_id (may be auth_group_id or root_folder_id)
    assign_query = """
    MATCH (d:Document {id: $document_id})
    WHERE d.group_id IN $valid_ids
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    
    // Remove existing folder assignment if any
    OPTIONAL MATCH (d)-[old:IN_FOLDER]->(:Folder)
    DELETE old
    
    // Create new assignment
    CREATE (d)-[:IN_FOLDER]->(f)
    SET d.folder_id = $folder_id
    
    RETURN d.id as document_id, f.id as folder_id, f.name as folder_name
    """
    
    with graph_session() as (_read, write):
        records = write(assign_query,
                        document_id=assignment.document_id,
                        folder_id=folder_id,
                        partition_id=partition_id,
                        valid_ids=valid_ids)
        record = records[0] if records else None
        
        if not record:
            raise HTTPException(status_code=404, detail="Document not found")
    
    reindex_triggered = False
    if cross_partition_move and doc_title:
        # Document moves between root folders → delete from old partition, re-index into new
        try:
            from src.api_gateway.routers.files import _get_doc_sync
            doc_sync = _get_doc_sync(request)
            if doc_sync:
                background_tasks.add_task(doc_sync.on_file_deleted, old_neo4j_gid, doc_title)
                background_tasks.add_task(
                    doc_sync.on_file_uploaded, new_neo4j_gid, doc_title, doc_source or "", ""
                )
                reindex_triggered = True
                logger.info("folder_move_cross_partition_reindex",
                           document_id=assignment.document_id,
                           old_partition=old_neo4j_gid,
                           new_partition=new_neo4j_gid)
        except Exception as e:
            logger.warning("folder_move_reindex_skipped",
                          error=str(e),
                          document_id=assignment.document_id)

    logger.info("document_assigned_to_folder",
                document_id=assignment.document_id,
                folder_id=folder_id,
                partition_id=partition_id,
                cross_partition_move=cross_partition_move)
    
    return {
        "status": "assigned",
        "document_id": record["document_id"],
        "folder_id": record["folder_id"],
        "folder_name": record["folder_name"],
        "reindex_triggered": reindex_triggered,
    }


@router.delete("/{folder_id}/documents/{document_id}")
async def unassign_document_from_folder(
    folder_id: str,
    document_id: str,
    partition_id: str = Depends(get_partition_id)
):
    """
    Remove a document from a folder (move to unfiled/root).
    
    Args:
        folder_id: Folder ID to remove from
        document_id: Document ID to unassign
        partition_id: Group/user ID from auth middleware
    
    Returns:
        Unassignment result
    """
    unassign_query = """
    MATCH (d:Document {id: $document_id})-[r:IN_FOLDER]->(f:Folder {id: $folder_id, group_id: $partition_id})
    DELETE r
    SET d.folder_id = null
    RETURN d.id as document_id
    """
    
    with graph_session() as (_read, write):
        records = write(unassign_query,
                        document_id=document_id,
                        folder_id=folder_id,
                        partition_id=partition_id)
        if not records:
            raise HTTPException(status_code=404, detail="Document not in this folder")
    
    logger.info("document_unassigned_from_folder",
                document_id=document_id,
                folder_id=folder_id,
                partition_id=partition_id)
    
    return {"status": "unassigned", "document_id": document_id}


@router.post("/{folder_id}/documents/bulk")
async def bulk_assign_documents_to_folder(
    folder_id: str,
    assignment: BulkDocumentFolderAssignment,
    partition_id: str = Depends(get_partition_id)
):
    """
    Assign multiple documents to a folder in one operation.
    
    Args:
        folder_id: Target folder ID
        assignment: List of document IDs to assign
        partition_id: Group/user ID from auth middleware
    
    Returns:
        Bulk assignment result with success/failure counts
    """
    # Verify folder exists
    verify_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id
    """
    with graph_session() as (read, _write):
        if not read(verify_query, folder_id=folder_id, partition_id=partition_id):
            raise HTTPException(status_code=404, detail="Folder not found")
    
    # Bulk assign documents
    # Documents may have different group_ids (auth_group_id or root_folder_id)
    # so we traverse through folder ownership for security instead
    bulk_query = """
    UNWIND $document_ids AS doc_id
    MATCH (d:Document {id: doc_id})
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    
    // Remove existing folder assignment
    OPTIONAL MATCH (d)-[old:IN_FOLDER]->(:Folder)
    DELETE old
    
    // Create new assignment
    CREATE (d)-[:IN_FOLDER]->(f)
    SET d.folder_id = $folder_id
    
    RETURN doc_id
    """
    
    with graph_session() as (_read, write):
        records = write(bulk_query,
                        document_ids=assignment.document_ids,
                        folder_id=folder_id,
                        partition_id=partition_id)
        assigned_ids = [r["doc_id"] for r in records]
    
    failed_ids = [d for d in assignment.document_ids if d not in assigned_ids]
    
    logger.info("bulk_documents_assigned_to_folder",
                folder_id=folder_id,
                assigned_count=len(assigned_ids),
                failed_count=len(failed_ids),
                partition_id=partition_id)
    
    return {
        "status": "completed",
        "folder_id": folder_id,
        "assigned_count": len(assigned_ids),
        "assigned_ids": assigned_ids,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids
    }


@router.get("/{folder_id}/documents")
async def list_documents_in_folder(
    folder_id: str,
    partition_id: str = Depends(get_partition_id),
    include_subfolders: bool = False
):
    """
    List all documents in a folder.
    
    Args:
        folder_id: Folder ID to list documents from
        partition_id: Group/user ID from auth middleware
        include_subfolders: If True, include documents from subfolders
    
    Returns:
        List of documents in the folder
    """
    if include_subfolders:
        query = """
        MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
        OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
        WITH collect(f) + collect(sub) AS folders
        UNWIND folders AS folder
        MATCH (d:Document)-[:IN_FOLDER]->(folder)
        RETURN DISTINCT d.id as id, d.title as title, d.source as source,
               d.folder_id as folder_id, d.created_at as created_at
        ORDER BY d.title
        """
    else:
        query = """
        MATCH (d:Document)-[:IN_FOLDER]->(f:Folder {id: $folder_id, group_id: $partition_id})
        RETURN d.id as id, d.title as title, d.source as source,
               d.folder_id as folder_id, d.created_at as created_at
        ORDER BY d.title
        """
    
    with graph_session() as (read, _write):
        records = read(query, folder_id=folder_id, partition_id=partition_id)
        documents = [
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source"],
                "folder_id": r["folder_id"],
                "created_at": str(r["created_at"]) if r["created_at"] else None
            }
            for r in records
        ]
    
    return {"folder_id": folder_id, "documents": documents, "count": len(documents)}


@router.get("/unfiled/documents")
async def list_unfiled_documents(
    partition_id: str = Depends(get_partition_id)
):
    """
    List all documents not assigned to any folder (unfiled/root documents).
    
    Unfiled documents have group_id = auth_group_id (the fallback partition).
    
    Args:
        partition_id: Group/user ID from auth middleware
    
    Returns:
        List of unfiled documents
    """
    query = """
    MATCH (d:Document {group_id: $partition_id})
    WHERE NOT (d)-[:IN_FOLDER]->(:Folder)
    RETURN d.id as id, d.title as title, d.source as source,
           d.created_at as created_at
    ORDER BY d.title
    """
    
    with graph_session() as (read, _write):
        records = read(query, partition_id=partition_id)
        documents = [
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source"],
                "folder_id": None,
                "created_at": str(r["created_at"]) if r["created_at"] else None
            }
            for r in records
        ]
    
    return {"folder_id": None, "documents": documents, "count": len(documents)}


# =============================================================================
# Folder Analysis Endpoint
# =============================================================================

class AnalysisStatusResponse(BaseModel):
    """Lightweight status response for polling."""
    folder_id: str
    analysis_status: Optional[str]
    file_count: Optional[int]
    entity_count: Optional[int]
    community_count: Optional[int]
    analysis_files_total: Optional[int] = None
    analysis_files_processed: Optional[int] = None
    section_count: Optional[int] = None
    sentence_count: Optional[int] = None
    relationship_count: Optional[int] = None
    analysis_error: Optional[str] = None


@router.get("/{folder_id}/file-count")
async def get_folder_file_count(
    folder_id: str,
    request: Request,
    partition_id: str = Depends(get_partition_id)
):
    """Return the recursive file count for a folder, with per-subfolder breakdown.

    Response includes total count and a breakdown array showing each direct
    child subfolder's name and file count (recursively).
    """
    from src.api_gateway.routers.files import _resolve_folder_path

    folder_path = await _resolve_folder_path(partition_id, folder_id)
    if not folder_path:
        raise HTTPException(status_code=404, detail="Folder not found")

    blob_manager = getattr(request.app.state, "user_blob_manager", None)
    if not blob_manager:
        raise HTTPException(status_code=400, detail="File storage not configured")

    blobs = await blob_manager.list_blobs_recursive(partition_id, folder_path)
    total = len(blobs)

    # Build per-subfolder breakdown (direct children only)
    sub_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})<-[:SUBFOLDER_OF]-(child:Folder)
    RETURN child.id AS id, child.name AS name
    ORDER BY child.name
    """
    breakdown = []
    with graph_session() as (read, _write):
        children = read(sub_query, folder_id=folder_id, partition_id=partition_id)

    for child in children:
        child_path = await _resolve_folder_path(partition_id, child["id"])
        if child_path:
            child_blobs = await blob_manager.list_blobs_recursive(partition_id, child_path)
            breakdown.append({"name": child["name"], "count": len(child_blobs)})

    logger.info("folder_file_count", folder_id=folder_id, folder_path=folder_path,
                partition_id=partition_id, count=total)
    return {"folder_id": folder_id, "count": total, "subfolders": breakdown}


@router.post("/{folder_id}/analyze")
async def analyze_folder(
    folder_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    partition_id: str = Depends(get_partition_id)
):
    """
    Trigger analysis (indexing) for a folder and all its contents.

    1. Marks the folder + descendants as 'analyzing'.
    2. Recursively lists all blobs under the folder.
    3. Indexes every file via DocumentSyncService.
    4. On completion, marks the folder as 'analyzed' and stores stats.
    5. Creates a result folder under "Analysis Results".
    """
    # 1) Verify folder exists and is eligible for analysis
    verify_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id, f.name as name, f.analysis_status as analysis_status,
           f.folder_type as folder_type
    """
    with graph_session() as (read, _write):
        records = read(verify_query,
                       folder_id=folder_id,
                       partition_id=partition_id)
        record = records[0] if records else None
        if not record:
            raise HTTPException(status_code=404, detail="Folder not found")
        if record.get("folder_type") == "analysis_result":
            raise HTTPException(status_code=400, detail="Cannot analyze a result folder")
        if record.get("analysis_status") == "analyzing":
            raise HTTPException(status_code=409, detail="Analysis already in progress")

    folder_name = record["name"]

    # 2) Mark folder + subfolders as 'analyzing', clear previous error/progress
    mark_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
    WITH collect(f) + collect(sub) AS folders
    UNWIND folders AS fld
    SET fld.analysis_status = 'analyzing',
        fld.analysis_error = null,
        fld.analysis_files_total = null,
        fld.analysis_files_processed = null,
        fld.updated_at = datetime()
    RETURN count(fld) as marked
    """
    with graph_session() as (_read, write):
        write(mark_query, folder_id=folder_id, partition_id=partition_id)

    # 3) Resolve the neo4j group_id for this folder tree
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id
    neo4j_gid = await resolve_neo4j_group_id(partition_id, folder_id)

    # 4) Collect all folder paths and list blobs across the whole tree
    blob_manager = getattr(request.app.state, "user_blob_manager", None)
    if not blob_manager:
        raise HTTPException(status_code=400, detail="File storage not configured")

    # Resolve full path for the root folder; try hierarchical, fall back to flat name
    from src.api_gateway.routers.files import _resolve_folder_path
    folder_path = await _resolve_folder_path(partition_id, folder_id)
    blobs = await blob_manager.list_blobs_recursive(partition_id, folder_path or folder_name)

    if not blobs:
        # Revert status since there's nothing to analyze
        revert_query = """
        MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
        OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
        WITH collect(f) + collect(sub) AS folders
        UNWIND folders AS fld
        SET fld.analysis_status = 'not_analyzed', fld.updated_at = datetime()
        """
        with graph_session() as (_read, write):
            write(revert_query, folder_id=folder_id, partition_id=partition_id)
        raise HTTPException(status_code=400, detail="No files found in folder to analyze")

    # 5) Kick off indexing in background
    doc_sync = getattr(request.app.state, "document_sync_service", None)
    if not doc_sync:
        raise HTTPException(status_code=503, detail="Indexing service unavailable")

    # Store analysis_group_id on the folder node
    set_gid_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    SET f.analysis_group_id = $neo4j_gid
    """
    with graph_session() as (_read, write):
        write(set_gid_query,
              folder_id=folder_id,
              partition_id=partition_id,
              neo4j_gid=neo4j_gid)

    # Run analysis as a background task on the main event loop.
    # This keeps async compatibility (doc_sync uses async HTTP clients).
    # The tolerant liveness probe (failureThreshold=30, ~15 min) prevents
    # the container from being killed during CPU-heavy entity dedup.
    # _get_session() ensures fresh Neo4j drivers after any blocking.
    background_tasks.add_task(
        _run_folder_analysis,
        doc_sync=doc_sync,
        blobs=blobs,
        neo4j_gid=neo4j_gid,
        folder_id=folder_id,
        folder_name=folder_name,
        partition_id=partition_id,
    )

    logger.info("folder_analysis_started",
                folder_id=folder_id,
                file_count=len(blobs),
                neo4j_gid=neo4j_gid)

    return {
        "status": "analyzing",
        "folder_id": folder_id,
        "analysis_group_id": neo4j_gid,
        "file_count": len(blobs),
        "message": f"Analysis started for {len(blobs)} file(s) in '{folder_name}'",
    }


@router.delete("/{folder_id}/analysis")
async def delete_folder_analysis(
    folder_id: str,
    request: Request,
    partition_id: str = Depends(get_partition_id),
):
    """Delete all analysis data (graph) for a folder, keeping original files.

    This removes all Neo4j graph data (Documents, Sentences, Entities,
    Communities, Sections, etc.) created during folder analysis. The
    original files in blob storage are untouched.

    Resets the folder's analysis_status to 'not_analyzed'.
    """
    # 1) Verify folder exists and has analysis data
    verify_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id, f.name as name,
           f.analysis_status as analysis_status,
           f.analysis_group_id as analysis_group_id,
           f.folder_type as folder_type
    """
    with graph_session() as (read, _write):
        records = read(verify_query,
                       folder_id=folder_id,
                       partition_id=partition_id)
        record = records[0] if records else None
        if not record:
            raise HTTPException(status_code=404, detail="Folder not found")

    analysis_group_id = record.get("analysis_group_id")
    if not analysis_group_id:
        raise HTTPException(status_code=400, detail="Folder has no analysis data to delete")

    # 2) Delete all graph data for this analysis group
    from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3
    from src.core.config import settings
    store = Neo4jStoreV3(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE or "neo4j",
    )
    deleted = store.delete_group_data(analysis_group_id)

    # 3) Reset folder analysis status
    reset_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
    WITH collect(f) + collect(sub) AS folders
    UNWIND folders AS fld
    SET fld.analysis_status = 'not_analyzed',
        fld.analysis_group_id = null,
        fld.analyzed_at = null,
        fld.file_count = null,
        fld.entity_count = null,
        fld.community_count = null,
        fld.analysis_files_total = null,
        fld.analysis_files_processed = null,
        fld.section_count = null,
        fld.sentence_count = null,
        fld.relationship_count = null,
        fld.analysis_error = null,
        fld.updated_at = datetime()
    RETURN count(fld) as reset_count
    """
    with graph_session() as (_read, write):
        records = write(reset_query,
                        folder_id=folder_id,
                        partition_id=partition_id)
        reset_record = records[0] if records else None

    # Note: we intentionally keep the "Analysis Results" subfolder and blobs.
    # Blob storage is cheap; the user can delete those files manually if desired.

    logger.info("folder_analysis_deleted",
                folder_id=folder_id,
                analysis_group_id=analysis_group_id,
                deleted=deleted)

    return {
        "status": "deleted",
        "folder_id": folder_id,
        "analysis_group_id": analysis_group_id,
        "deleted": deleted,
        "message": f"Analysis data removed. Original files are kept.",
    }


@router.post("/{folder_id}/cancel-analysis")
async def cancel_folder_analysis(
    folder_id: str,
    partition_id: str = Depends(get_partition_id),
):
    """Cancel a stuck or in-progress analysis, resetting status to not_analyzed.

    This only resets the folder metadata — any partially-indexed graph data
    remains (use DELETE /analysis to clean it up afterwards if needed).
    """
    verify_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id, f.analysis_status as analysis_status
    """
    with graph_session() as (read, _write):
        records = read(verify_query,
                       folder_id=folder_id,
                       partition_id=partition_id)
        record = records[0] if records else None
        if not record:
            raise HTTPException(status_code=404, detail="Folder not found")
        if record.get("analysis_status") != "analyzing":
            raise HTTPException(status_code=400, detail="Folder is not currently analyzing")

    cancel_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
    WITH collect(f) + collect(sub) AS folders
    UNWIND folders AS fld
    SET fld.analysis_status = 'not_analyzed',
        fld.analysis_files_total = null,
        fld.analysis_files_processed = null,
        fld.analysis_error = 'Analysis was cancelled by user',
        fld.updated_at = datetime()
    RETURN count(fld) as reset_count
    """
    with graph_session() as (_read, write):
        write(cancel_query,
              folder_id=folder_id,
              partition_id=partition_id)

    logger.info("folder_analysis_cancelled", folder_id=folder_id)

    return {
        "status": "cancelled",
        "folder_id": folder_id,
        "message": "Analysis cancelled. You can re-analyze or delete partial data.",
    }


async def _run_folder_analysis(
    *,
    doc_sync,
    blobs: list[dict],
    neo4j_gid: str,
    folder_id: str,
    folder_name: str,
    partition_id: str,
):
    """Background task: index all blobs and update folder status on completion.
    
    Gets a fresh Neo4j driver from the singleton each time a session is needed,
    avoiding "Driver closed" errors when reconnect() replaces the driver mid-task.
    """
    import traceback
    import sys

    logger.info("folder_analysis_task_started",
                folder_id=folder_id,
                file_count=len(blobs),
                neo4j_gid=neo4j_gid)
    print(f"[ANALYSIS TASK STARTED] folder_id={folder_id} files={len(blobs)}", file=sys.stderr, flush=True)

    def _get_session():
        """Get a fresh Neo4j session from the current (possibly reconnected) driver."""
        return get_graph_driver().session()
    file_count = len(blobs)
    try:
        # NOTE: Group-wide cleanup removed — it overwhelms Neo4j Aura and kills
        # the driver connection pool. Per-document cleanup in on_file_uploaded()
        # handles individual files. For full cleanup, use "Delete Analysis" first.

        # Set total file count so the UI can show determinate progress
        init_query = """
        MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
        SET f.analysis_files_total = $total,
            f.analysis_files_processed = 0
        """
        with _get_session() as session:
            session.run(init_query,
                        folder_id=folder_id,
                        partition_id=partition_id,
                        total=file_count)

        for idx, blob in enumerate(blobs):
            await doc_sync.on_file_uploaded(
                group_id=neo4j_gid,
                filename=blob["name"],
                blob_url=blob["url"],
                user_id=partition_id,
            )
            # Update per-file progress
            progress_query = """
            MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
            SET f.analysis_files_processed = $processed
            """
            with _get_session() as session:
                session.run(progress_query,
                            folder_id=folder_id,
                            partition_id=partition_id,
                            processed=idx + 1)

        # Count entities, communities, sections, sentences, relationships
        stats_query = """
        OPTIONAL MATCH (e:Entity {group_id: $gid})
        WITH count(e) as entity_count
        OPTIONAL MATCH (c:Community {group_id: $gid})
        WITH entity_count, count(c) as community_count
        OPTIONAL MATCH (sec:Section {group_id: $gid})
        WITH entity_count, community_count, count(sec) as section_count
        OPTIONAL MATCH (sent:Sentence {group_id: $gid})
        WITH entity_count, community_count, section_count, count(sent) as sentence_count
        OPTIONAL MATCH (:Entity {group_id: $gid})-[r:RELATED_TO]->()
        RETURN entity_count, community_count, section_count, sentence_count,
               count(r) as relationship_count
        """
        entity_count = 0
        community_count = 0
        section_count = 0
        sentence_count = 0
        relationship_count = 0
        with _get_session() as session:
            record = session.run(stats_query, gid=neo4j_gid).single()
            if record:
                entity_count = record["entity_count"]
                community_count = record["community_count"]
                section_count = record["section_count"]
                sentence_count = record["sentence_count"]
                relationship_count = record["relationship_count"]

        # Mark folder + subfolders as 'analyzed' with full stats
        complete_query = """
        MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
        OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
        WITH collect(f) + collect(sub) AS folders
        UNWIND folders AS fld
        SET fld.analysis_status = 'analyzed',
            fld.analyzed_at = datetime(),
            fld.file_count = $file_count,
            fld.entity_count = $entity_count,
            fld.community_count = $community_count,
            fld.section_count = $section_count,
            fld.sentence_count = $sentence_count,
            fld.relationship_count = $relationship_count,
            fld.analysis_files_total = null,
            fld.analysis_files_processed = null,
            fld.analysis_error = null,
            fld.updated_at = datetime()
        """
        with _get_session() as session:
            session.run(complete_query,
                        folder_id=folder_id,
                        partition_id=partition_id,
                        file_count=file_count,
                        entity_count=entity_count,
                        community_count=community_count,
                        section_count=section_count,
                        sentence_count=sentence_count,
                        relationship_count=relationship_count)

        # Auto-create result folder under "Analysis Results"
        await _create_analysis_result_folder(
            partition_id=partition_id,
            source_folder_id=folder_id,
            source_folder_name=folder_name,
            neo4j_gid=neo4j_gid,
            file_count=file_count,
            entity_count=entity_count,
            community_count=community_count,
        )

        logger.info("folder_analysis_complete",
                     folder_id=folder_id,
                     file_count=file_count,
                     entity_count=entity_count,
                     community_count=community_count,
                     section_count=section_count,
                     sentence_count=sentence_count,
                     relationship_count=relationship_count)

    except Exception as e:
        logger.error("folder_analysis_failed",
                     folder_id=folder_id,
                     error=str(e),
                     traceback=traceback.format_exc())
        # Also print to ensure visibility in container logs
        import sys
        print(f"[ANALYSIS FAILED] folder_id={folder_id} error={e}", file=sys.stderr, flush=True)
        # Store error detail and mark folder as stale so user can retry
        try:
            error_msg = str(e)[:500]
            fail_query = """
            MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
            OPTIONAL MATCH (f)<-[:SUBFOLDER_OF*0..]-(sub:Folder)
            WITH collect(f) + collect(sub) AS folders
            UNWIND folders AS fld
            SET fld.analysis_status = 'stale',
                fld.analysis_error = $error_msg,
                fld.analysis_files_total = null,
                fld.analysis_files_processed = null,
                fld.updated_at = datetime()
            """
            with _get_session() as session:
                session.run(fail_query,
                            folder_id=folder_id,
                            partition_id=partition_id,
                            error_msg=error_msg)
        except Exception:
            pass


async def _create_analysis_result_folder(
    *,
    partition_id: str,
    source_folder_id: str,
    source_folder_name: str,
    neo4j_gid: str,
    file_count: int,
    entity_count: int,
    community_count: int,
):
    """Auto-create an 'Analysis Results' root folder (if missing) and a result subfolder."""
    # Ensure "Analysis Results" root exists
    root_query = """
    MERGE (r:Folder {name: 'Analysis Results', group_id: $pid, folder_type: 'analysis_result', parent_folder_id: null_value})
    ON CREATE SET r.id = randomUUID(),
                  r.created_at = datetime(),
                  r.updated_at = datetime()
    RETURN r.id as root_id
    """
    # Neo4j doesn't support null in MERGE, use a sentinel approach
    root_find_query = """
    MATCH (r:Folder {name: 'Analysis Results', group_id: $pid, folder_type: 'analysis_result'})
    WHERE r.parent_folder_id IS NULL
    RETURN r.id as root_id
    """
    root_create_query = """
    CREATE (r:Folder {
        id: randomUUID(),
        name: 'Analysis Results',
        group_id: $pid,
        folder_type: 'analysis_result',
        parent_folder_id: null,
        created_at: datetime(),
        updated_at: datetime()
    })
    RETURN r.id as root_id
    """
    with _get_session() as session:
        record = session.run(root_find_query, pid=partition_id).single()
        if not record:
            record = session.run(root_create_query, pid=partition_id).single()
        root_id = record["root_id"]

    # Create result subfolder
    result_name = f"{source_folder_name} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    result_query = """
    CREATE (f:Folder {
        id: randomUUID(),
        name: $name,
        group_id: $pid,
        parent_folder_id: $root_id,
        folder_type: 'analysis_result',
        analysis_status: 'analyzed',
        analysis_group_id: $neo4j_gid,
        source_folder_id: $source_folder_id,
        analyzed_at: datetime(),
        file_count: $file_count,
        entity_count: $entity_count,
        community_count: $community_count,
        created_at: datetime(),
        updated_at: datetime()
    })
    WITH f
    MATCH (root:Folder {id: $root_id, group_id: $pid})
    CREATE (f)-[:SUBFOLDER_OF]->(root)
    RETURN f.id as result_id
    """
    with _get_session() as session:
        session.run(result_query,
                    name=result_name,
                    pid=partition_id,
                    root_id=root_id,
                    neo4j_gid=neo4j_gid,
                    source_folder_id=source_folder_id,
                    file_count=file_count,
                    entity_count=entity_count,
                    community_count=community_count)

    logger.info("analysis_result_folder_created",
                source_folder=source_folder_name,
                result_name=result_name)

