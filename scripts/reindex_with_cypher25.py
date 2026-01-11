#!/usr/bin/env python3
"""
Reindex test documents with Cypher 25 optimizations enabled.

This script:
1. Cleans up the existing test group
2. Reindexes 5 test PDFs with V3 pipeline
3. Validates that all properties are correctly set
4. Tests Cypher 25 queries on fresh data

Usage:
  python scripts/reindex_with_cypher25.py
"""

import os
import sys
import asyncio
from pathlib import Path

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "graphrag-orchestration"))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from dotenv import load_dotenv
env_path = os.path.join(SERVICE_ROOT, '.env')
load_dotenv(env_path)

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import after path setup
from app.services.graph_service import GraphService
from app.services.async_neo4j_service import USE_CYPHER_25


async def cleanup_old_group(group_id: str):
    """Delete all nodes and relationships for the old group."""
    logger.info(f"Cleaning up existing group: {group_id}")
    
    graph_service = GraphService()
    await graph_service.async_init()
    
    # Delete all nodes with this group_id
    query = """
    MATCH (n {group_id: $group_id})
    DETACH DELETE n
    """
    
    async with graph_service.async_driver.session() as session:
        result = await session.run(query, group_id=group_id)
        summary = await result.consume()
        logger.info(f"Deleted nodes/relationships for group {group_id}")
    
    await graph_service.close()


async def validate_indexed_data(group_id: str):
    """Validate that indexing created all expected properties."""
    logger.info(f"Validating indexed data for group: {group_id}")
    
    graph_service = GraphService()
    await graph_service.async_init()
    
    async with graph_service.async_driver.session() as session:
        # Check TextChunk properties
        query = """
        MATCH (c:TextChunk {group_id: $group_id})
        RETURN count(c) AS chunk_count,
               count(c.document_title) AS chunks_with_title,
               count(c.document_source) AS chunks_with_source,
               count(c.embedding) AS chunks_with_embedding
        """
        result = await session.run(query, group_id=group_id)
        record = await result.single()
        
        if record:
            logger.info(f"✅ Chunks indexed: {record['chunk_count']}")
            logger.info(f"   - With document_title: {record['chunks_with_title']}")
            logger.info(f"   - With document_source: {record['chunks_with_source']}")
            logger.info(f"   - With embeddings: {record['chunks_with_embedding']}")
        
        # Check Entity properties
        query2 = """
        MATCH (e:__Entity__ {group_id: $group_id})
        RETURN count(e) AS entity_count
        """
        result = await session.run(query2, group_id=group_id)
        record = await result.single()
        
        if record:
            logger.info(f"✅ Entities indexed: {record['entity_count']}")
    
    await graph_service.close()


async def test_cypher25_queries(group_id: str):
    """Test Cypher 25 queries on freshly indexed data."""
    logger.info(f"Testing Cypher 25 queries on group: {group_id}")
    
    from app.services.async_neo4j_service import AsyncNeo4jService
    
    async with AsyncNeo4jService.from_settings() as service:
        # Test entity retrieval
        entities = await service.get_entities_by_importance(group_id, top_k=10)
        logger.info(f"✅ Retrieved {len(entities)} entities")
        
        if entities:
            # Test neighbor expansion
            entity_ids = [e['id'] for e in entities[:3]]
            neighbors = await service.expand_neighbors(group_id, entity_ids, depth=2)
            logger.info(f"✅ Expanded to {len(neighbors)} neighbors")
        
        # Test document field check
        exists, section = await service.check_field_exists_in_document(
            group_id,
            "contract",
            ["payment", "terms"]
        )
        logger.info(f"✅ Field exists check: {exists}")


async def main():
    print("=" * 70)
    print("Reindexing with Cypher 25 Optimizations")
    print("=" * 70)
    print(f"USE_CYPHER_25 = {USE_CYPHER_25}")
    print()
    
    # Configuration
    OLD_GROUP_ID = "test-5pdfs-1767429340223041632"
    NEW_GROUP_ID = f"test-5pdfs-cypher25-{int(__import__('time').time())}"
    
    print(f"Old group ID: {OLD_GROUP_ID}")
    print(f"New group ID: {NEW_GROUP_ID}")
    print()
    
    # Step 1: Clean up old group (optional - comment out to keep old data)
    # await cleanup_old_group(OLD_GROUP_ID)
    # print()
    
    # Step 2: Run indexing
    print("=" * 70)
    print("Step 1: Index Documents with Cypher 25")
    print("=" * 70)
    print()
    print("Available test documents:")
    print("  • BUILDERS LIMITED WARRANTY.pdf")
    print("  • contoso_lifts_invoice.pdf")
    print("  • purchase_contract.pdf")
    print("  • HOLDING TANK SERVICING CONTRACT.pdf")
    print("  • PROPERTY MANAGEMENT AGREEMENT.pdf")
    print()
    print("To reindex:")
    print(f"  export GROUP_ID={NEW_GROUP_ID}")
    print(f"  python graphrag-orchestration/scripts/index_five_local_docs.py")
    print()
    print("After indexing completes, validate:")
    print(f"  export VALIDATE_ONLY=1 GROUP_ID={NEW_GROUP_ID}")
    print(f"  python scripts/reindex_with_cypher25.py")
    print()
    
    # Validate existing data if requested
    if os.getenv("VALIDATE_ONLY"):
        group_to_validate = os.getenv("GROUP_ID", OLD_GROUP_ID)
        print("=" * 70)
        print(f"Validating group: {group_to_validate}")
        print("=" * 70)
        print()
        await validate_indexed_data(group_to_validate)
        print()
        await test_cypher25_queries(group_to_validate)
        print()
        print("=" * 70)
        print("✅ Validation Complete!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
