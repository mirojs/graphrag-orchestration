"""
Folder CRUD Endpoints

Provides hierarchical folder organization for documents.
Supports multi-tenant isolation via group_id or user_id.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
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
