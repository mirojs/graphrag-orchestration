"""
Folder CRUD Endpoints

Provides hierarchical folder organization for documents.
Supports multi-tenant isolation via group_id or user_id.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request
from typing import List, Optional
from pydantic import BaseModel
import structlog
from datetime import datetime

from src.core.models.folder import Folder, FolderCreate, FolderUpdate
from src.worker.services import GraphService

router = APIRouter(prefix="/folders", tags=["folders"])
logger = structlog.get_logger()


def get_partition_id(request: Request) -> str:
    """Extract partition ID from request state (set by middleware)."""
    return request.state.group_id


def get_graph_driver():
    """Get Neo4j driver with null check."""
    graph_service = GraphService()
    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    return graph_service.driver


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
    driver = get_graph_driver()
    
    # Validate max depth (2 levels max)
    if folder.parent_folder_id:
        # Check parent exists and get its depth
        parent_query = """
        MATCH (f:Folder {id: $parent_id, group_id: $partition_id})
        OPTIONAL MATCH path = (f)-[:SUBFOLDER_OF*]->(root:Folder)
        RETURN f, length(path) as depth
        """
        with driver.session() as session:
            result = session.run(parent_query, 
                               parent_id=folder.parent_folder_id,
                               partition_id=partition_id)
            parent = result.single()
            
            if not parent:
                raise HTTPException(status_code=404, detail="Parent folder not found")
            
            depth = parent["depth"] if parent["depth"] is not None else 0
            if depth >= 1:  # Parent is already at depth 1, can't add child
                raise HTTPException(status_code=400, detail="Maximum folder depth (2) exceeded")
    
    # Create folder
    create_query = """
    CREATE (f:Folder {
        id: randomUUID(),
        name: $name,
        group_id: $partition_id,
        parent_folder_id: $parent_folder_id,
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
           f.created_at as created_at, f.updated_at as updated_at
    """
    
    with driver.session() as session:
        result = session.run(create_query,
                           name=folder.name,
                           partition_id=partition_id,
                           parent_folder_id=folder.parent_folder_id)
        record = result.single()
        
    logger.info("folder_created", folder_id=record["id"], partition_id=partition_id)
    
    return Folder(
        id=record["id"],
        name=record["name"],
        group_id=record["group_id"],
        parent_folder_id=record["parent_folder_id"],
        created_at=record["created_at"],
        updated_at=record["updated_at"]
    )


@router.get("", response_model=List[Folder])
async def list_folders(
    partition_id: str = Depends(get_partition_id),
    parent_folder_id: Optional[str] = None
):
    """
    List folders in the current partition.
    
    Args:
        partition_id: Group/user ID from auth middleware
        parent_folder_id: Filter by parent folder (None = root level)
    
    Returns:
        List of folders
    """
    driver = get_graph_driver()
    
    if parent_folder_id:
        query = """
        MATCH (f:Folder {group_id: $partition_id})
        WHERE f.parent_folder_id = $parent_folder_id
        RETURN f.id as id, f.name as name, f.group_id as group_id,
               f.parent_folder_id as parent_folder_id,
               f.created_at as created_at, f.updated_at as updated_at
        ORDER BY f.name
        """
    else:
        query = """
        MATCH (f:Folder {group_id: $partition_id})
        WHERE f.parent_folder_id IS NULL
        RETURN f.id as id, f.name as name, f.group_id as group_id,
               f.parent_folder_id as parent_folder_id,
               f.created_at as created_at, f.updated_at as updated_at
        ORDER BY f.name
        """
    
    with driver.session() as session:
        result = session.run(query, 
                           partition_id=partition_id,
                           parent_folder_id=parent_folder_id)
        folders = [
            Folder(
                id=record["id"],
                name=record["name"],
                group_id=record["group_id"],
                parent_folder_id=record["parent_folder_id"],
                created_at=record["created_at"],
                updated_at=record["updated_at"]
            )
            for record in result
        ]
    
    return folders


@router.get("/{folder_id}", response_model=Folder)
async def get_folder(
    folder_id: str,
    partition_id: str = Depends(get_partition_id)
):
    """Get a specific folder."""
    driver = get_graph_driver()
    
    query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id, f.name as name, f.group_id as group_id,
           f.parent_folder_id as parent_folder_id,
           f.created_at as created_at, f.updated_at as updated_at
    """
    
    with driver.session() as session:
        result = session.run(query, folder_id=folder_id, partition_id=partition_id)
        record = result.single()
        
        if not record:
            raise HTTPException(status_code=404, detail="Folder not found")
        
        return Folder(
            id=record["id"],
            name=record["name"],
            group_id=record["group_id"],
            parent_folder_id=record["parent_folder_id"],
            created_at=record["created_at"],
            updated_at=record["updated_at"]
        )


@router.put("/{folder_id}", response_model=Folder)
async def update_folder(
    folder_id: str,
    folder_update: FolderUpdate,
    partition_id: str = Depends(get_partition_id)
):
    """Update a folder."""
    driver = get_graph_driver()
    
    query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    SET f.name = $name, f.updated_at = datetime()
    RETURN f.id as id, f.name as name, f.group_id as group_id,
           f.parent_folder_id as parent_folder_id,
           f.created_at as created_at, f.updated_at as updated_at
    """
    
    with driver.session() as session:
        result = session.run(query, 
                           folder_id=folder_id,
                           partition_id=partition_id,
                           name=folder_update.name)
        record = result.single()
        
        if not record:
            raise HTTPException(status_code=404, detail="Folder not found")
        
        logger.info("folder_updated", folder_id=folder_id, partition_id=partition_id)
        
        return Folder(
            id=record["id"],
            name=record["name"],
            group_id=record["group_id"],
            parent_folder_id=record["parent_folder_id"],
            created_at=record["created_at"],
            updated_at=record["updated_at"]
        )


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
    driver = get_graph_driver()
    
    if not cascade:
        # Check if folder has children
        check_query = """
        MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
        OPTIONAL MATCH (child:Folder)-[:SUBFOLDER_OF]->(f)
        OPTIONAL MATCH (doc:Document)-[:IN_FOLDER]->(f)
        RETURN count(child) as child_count, count(doc) as doc_count
        """
        with driver.session() as session:
            result = session.run(check_query, folder_id=folder_id, partition_id=partition_id)
            record = result.single()
            
            if record["child_count"] > 0 or record["doc_count"] > 0:
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
    
    with driver.session() as session:
        result = session.run(delete_query,
                           folder_id=folder_id,
                           partition_id=partition_id,
                           cascade=cascade)
        record = result.single()
        
        if record["deleted"] == 0:
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

    driver = get_graph_driver()
    
    # Verify folder exists and belongs to this partition
    verify_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id
    """
    with driver.session() as session:
        result = session.run(verify_query, folder_id=folder_id, partition_id=partition_id)
        if not result.single():
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
    with driver.session() as session:
        doc_record = session.run(old_folder_query,
                                document_id=assignment.document_id,
                                valid_ids=valid_ids).single()
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
    
    with driver.session() as session:
        result = session.run(assign_query,
                           document_id=assignment.document_id,
                           folder_id=folder_id,
                           partition_id=partition_id,
                           valid_ids=valid_ids)
        record = result.single()
        
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
    driver = get_graph_driver()
    
    unassign_query = """
    MATCH (d:Document {id: $document_id})-[r:IN_FOLDER]->(f:Folder {id: $folder_id, group_id: $partition_id})
    DELETE r
    SET d.folder_id = null
    RETURN d.id as document_id
    """
    
    with driver.session() as session:
        result = session.run(unassign_query,
                           document_id=document_id,
                           folder_id=folder_id,
                           partition_id=partition_id)
        record = result.single()
        
        if not record:
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
    driver = get_graph_driver()
    
    # Verify folder exists
    verify_query = """
    MATCH (f:Folder {id: $folder_id, group_id: $partition_id})
    RETURN f.id as id
    """
    with driver.session() as session:
        result = session.run(verify_query, folder_id=folder_id, partition_id=partition_id)
        if not result.single():
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
    
    assigned_ids = []
    with driver.session() as session:
        result = session.run(bulk_query,
                           document_ids=assignment.document_ids,
                           folder_id=folder_id,
                           partition_id=partition_id)
        assigned_ids = [r["doc_id"] for r in result]
    
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
    driver = get_graph_driver()
    
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
    
    with driver.session() as session:
        result = session.run(query, folder_id=folder_id, partition_id=partition_id)
        documents = [
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source"],
                "folder_id": r["folder_id"],
                "created_at": str(r["created_at"]) if r["created_at"] else None
            }
            for r in result
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
    driver = get_graph_driver()
    
    query = """
    MATCH (d:Document {group_id: $partition_id})
    WHERE NOT (d)-[:IN_FOLDER]->(:Folder)
    RETURN d.id as id, d.title as title, d.source as source,
           d.created_at as created_at
    ORDER BY d.title
    """
    
    with driver.session() as session:
        result = session.run(query, partition_id=partition_id)
        documents = [
            {
                "id": r["id"],
                "title": r["title"],
                "source": r["source"],
                "folder_id": None,
                "created_at": str(r["created_at"]) if r["created_at"] else None
            }
            for r in result
        ]
    
    return {"folder_id": None, "documents": documents, "count": len(documents)}

