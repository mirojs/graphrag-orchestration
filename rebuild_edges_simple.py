#!/usr/bin/env python3
"""
Simple script to rebuild SEMANTICALLY_SIMILAR edges using the existing pipeline.
"""
import asyncio
import sys
import os

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'graphrag-orchestration'))

async def main():
    from app.hybrid.indexing.lazygraphrag_pipeline import LazyGraphRAGIndexingPipeline
    from app.hybrid.services.neo4j_store import Neo4jStoreV3
    from app.core.config import settings
    
    GROUP_ID = "test-5pdfs-1768486622652179443"
    
    print(f"🔗 Rebuilding SEMANTICALLY_SIMILAR edges for group: {GROUP_ID}")
    print(f"   Using threshold: 0.43 (from updated pipeline)")
    
    # Create Neo4j store
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD
    )
    
    # Step 1: Delete existing edges
    print(f"\n🗑️  Step 1: Deleting existing SEMANTICALLY_SIMILAR edges...")
    with neo4j_store.driver.session(database=neo4j_store.database) as session:
        result = session.run(
            """
            MATCH (s1:Section {group_id: $group_id})-[r:SEMANTICALLY_SIMILAR]->(s2:Section)
            DELETE r
            RETURN count(r) as deleted_count
            """,
            group_id=GROUP_ID
        )
        deleted = result.single()["deleted_count"]
        print(f"   Deleted {deleted} existing edges")
    
    # Step 2: Create pipeline and rebuild edges
    print(f"\n🔨 Step 2: Creating new edges with threshold 0.43...")
    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=None,  # Not needed for edge building
        embedding_llm=None,  # Not needed for edge building
        graph_store=None
    )
    
    # Call the method directly
    result = await pipeline._build_section_similarity_edges(GROUP_ID)
    
    print(f"\n✅ Done!")
    print(f"   Edges created: {result.get('edges_created', 0)}")
    print(f"   Cross-document pairs analyzed: {result.get('cross_document_pairs', 0)}")
    
    neo4j_store.driver.close()

if __name__ == "__main__":
    asyncio.run(main())
