"""
Admin endpoints for maintenance operations.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import structlog
import os
from app.archive.v3.services.neo4j_store import Neo4jStoreV3

logger = structlog.get_logger(__name__)
router = APIRouter()


class CleanupRaptorRequest(BaseModel):
    """Request to clean up RAPTOR data."""
    group_id: str
    recreate_index: bool = True


class CleanupRaptorResponse(BaseModel):
    """Response from RAPTOR cleanup."""
    nodes_deleted: int
    index_dropped: bool
    index_created: bool
    message: str


@router.post("/cleanup-raptor", response_model=CleanupRaptorResponse)
async def cleanup_raptor_data(request: CleanupRaptorRequest):
    """
    Clean up RAPTOR data and optionally recreate index.
    
    This is useful when changing embedding dimensions - deletes old RAPTOR nodes
    and recreates the vector index with new dimensions.
    """
    try:
        # Get Neo4j credentials from environment
        neo4j_uri = os.getenv("NEO4J_URI")
        neo4j_username = os.getenv("NEO4J_USERNAME", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD")
        neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        if not neo4j_uri or not neo4j_password:
            raise HTTPException(
                status_code=500,
                detail="Neo4j credentials not configured"
            )
        
        store = Neo4jStoreV3(
            uri=neo4j_uri,
            username=neo4j_username,
            password=neo4j_password,
            database=neo4j_database
        )
        
        nodes_deleted = 0
        index_dropped = False
        index_created = False
        
        with store.driver.session(database=store.database) as session:
            # Drop the index
            if request.recreate_index:
                logger.info("Dropping raptor_embedding index...")
                session.run("DROP INDEX raptor_embedding IF EXISTS")
                index_dropped = True
                logger.info("Index dropped")
            
            # Delete RAPTOR nodes for this group
            logger.info(f"Deleting RAPTOR nodes for group {request.group_id}...")
            result = session.run(
                "MATCH (r:RaptorNode {group_id: $group_id}) DELETE r RETURN count(*) as deleted",
                group_id=request.group_id
            )
            record = result.single()
            if record:
                nodes_deleted = record["deleted"]
            logger.info(f"Deleted {nodes_deleted} RAPTOR nodes")
            
            # Recreate index with 3072 dimensions (text-embedding-3-large)
            if request.recreate_index:
                logger.info("Creating raptor_embedding index with 3072 dimensions...")
                session.run("""
                    CREATE VECTOR INDEX raptor_embedding IF NOT EXISTS
                    FOR (r:RaptorNode) ON (r.embedding)
                    OPTIONS {indexConfig: {
                        `vector.dimensions`: 3072,
                        `vector.similarity_function`: 'cosine'
                    }}
                """)
                index_created = True
                logger.info("Index created")
        
        return CleanupRaptorResponse(
            nodes_deleted=nodes_deleted,
            index_dropped=index_dropped,
            index_created=index_created,
            message=f"Successfully cleaned up RAPTOR data. Deleted {nodes_deleted} nodes."
        )
        
    except Exception as e:
        logger.error(f"Failed to cleanup RAPTOR data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")
