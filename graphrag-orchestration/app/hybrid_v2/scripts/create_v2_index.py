"""Create V2 Vector Index for Voyage Embeddings (1024 dimensions)

This script creates the chunk_embeddings_v2 index in Neo4j for V2 section-aware
chunking with Voyage contextual embeddings.

V2 uses voyage-context-3 (1024 dimensions) with contextualized_embed() method.
This provides contextual awareness - chunks are embedded with knowledge of
their surrounding document context.

Usage:
    python -m app.hybrid_v2.scripts.create_v2_index

Ref: VOYAGE_V2_IMPLEMENTATION_PLAN_2026-01-25.md Phase 2, Step 2.2
"""

import asyncio
import logging
from typing import Optional

from neo4j import AsyncGraphDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)

# V2 Index Configuration
V2_INDEX_NAME = "chunk_embeddings_v2"
V2_EMBEDDING_DIM = 2048  # voyage-context-3 with output_dimension=2048
V2_EMBEDDING_PROPERTY = "embedding_v2"


async def create_v2_index(
    uri: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
) -> bool:
    """
    Create the V2 vector index for Voyage embeddings.
    
    Args:
        uri: Neo4j URI (default: from settings)
        username: Neo4j username (default: from settings)
        password: Neo4j password (default: from settings)
        database: Neo4j database (default: from settings)
        
    Returns:
        True if index was created or already exists
    """
    uri = uri or settings.NEO4J_URI
    username = username or settings.NEO4J_USERNAME
    password = password or settings.NEO4J_PASSWORD
    database = database or settings.NEO4J_DATABASE or "neo4j"
    
    if not all([uri, username, password]):
        raise ValueError("Neo4j credentials not configured")
    
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
    
    try:
        async with driver.session(database=database) as session:
            # Check if index already exists
            check_query = """
            SHOW INDEXES
            YIELD name, type
            WHERE name = $index_name
            RETURN count(*) as count
            """
            result = await session.run(check_query, index_name=V2_INDEX_NAME)
            record = await result.single()
            
            if record and record["count"] > 0:
                logger.info(f"V2 index '{V2_INDEX_NAME}' already exists")
                return True
            
            # Create the V2 vector index
            create_query = f"""
            CREATE VECTOR INDEX {V2_INDEX_NAME} IF NOT EXISTS
            FOR (c:TextChunk)
            ON c.{V2_EMBEDDING_PROPERTY}
            OPTIONS {{
              indexConfig: {{
                `vector.dimensions`: {V2_EMBEDDING_DIM},
                `vector.similarity_function`: 'cosine'
              }}
            }}
            """
            
            await session.run(create_query)
            logger.info(
                f"Created V2 vector index '{V2_INDEX_NAME}' "
                f"({V2_EMBEDDING_DIM} dimensions, cosine similarity)"
            )
            
            # Verify index was created
            result = await session.run(check_query, index_name=V2_INDEX_NAME)
            record = await result.single()
            
            if record and record["count"] > 0:
                logger.info(f"V2 index '{V2_INDEX_NAME}' verified")
                return True
            else:
                logger.warning(f"V2 index '{V2_INDEX_NAME}' creation not verified")
                return False
                
    finally:
        await driver.close()


async def drop_v2_index(
    uri: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
) -> bool:
    """
    Drop the V2 vector index (for testing/rollback).
    
    Returns:
        True if index was dropped or didn't exist
    """
    uri = uri or settings.NEO4J_URI
    username = username or settings.NEO4J_USERNAME
    password = password or settings.NEO4J_PASSWORD
    database = database or settings.NEO4J_DATABASE or "neo4j"
    
    if not all([uri, username, password]):
        raise ValueError("Neo4j credentials not configured")
    
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
    
    try:
        async with driver.session(database=database) as session:
            drop_query = f"DROP INDEX {V2_INDEX_NAME} IF EXISTS"
            await session.run(drop_query)
            logger.info(f"Dropped V2 index '{V2_INDEX_NAME}'")
            return True
    finally:
        await driver.close()


async def get_index_status() -> dict:
    """
    Get status of both V1 and V2 indexes.
    
    Returns:
        Dict with index status information
    """
    uri = settings.NEO4J_URI
    username = settings.NEO4J_USERNAME
    password = settings.NEO4J_PASSWORD
    database = settings.NEO4J_DATABASE or "neo4j"
    
    if not all([uri, username, password]):
        return {"error": "Neo4j credentials not configured"}
    
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
    
    try:
        async with driver.session(database=database) as session:
            query = """
            SHOW INDEXES
            YIELD name, type, state, populationPercent
            WHERE name IN ['chunk_embeddings', 'chunk_embeddings_v2']
            RETURN name, type, state, populationPercent
            """
            result = await session.run(query)
            records = await result.data()
            
            return {
                "indexes": records,
                "v1_exists": any(r["name"] == "chunk_embeddings" for r in records),
                "v2_exists": any(r["name"] == "chunk_embeddings_v2" for r in records),
            }
    finally:
        await driver.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        print("Creating V2 vector index...")
        success = await create_v2_index()
        
        if success:
            print("\n✅ V2 index created successfully!")
            print(f"   Index name: {V2_INDEX_NAME}")
            print(f"   Dimensions: {V2_EMBEDDING_DIM}")
            print(f"   Property: {V2_EMBEDDING_PROPERTY}")
        else:
            print("\n❌ V2 index creation failed")
            
        # Show index status
        print("\nIndex status:")
        status = await get_index_status()
        for idx in status.get("indexes", []):
            print(f"   - {idx['name']}: {idx['state']} ({idx.get('populationPercent', 0):.1f}% populated)")
    
    asyncio.run(main())
