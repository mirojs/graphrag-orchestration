#!/usr/bin/env python3
"""Debug script to test PPR section graph query directly against Neo4j."""

import asyncio
import os
import sys

# Add the app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

from src.worker.services.async_neo4j_service import AsyncNeo4jService

GROUP_ID = "test-5pdfs-1768557493369886422"

# A known seed entity from the corpus
TEST_SEEDS = ["timeframe", "warranty", "builder"]


async def test_entity_only():
    """Test entity-only PPR (baseline)."""
    print("\n" + "="*60)
    print("TEST 1: Entity-Only PPR (include_section_graph=False)")
    print("="*60)
    
    async with AsyncNeo4jService.from_settings() as service:
        try:
            results = await service.personalized_pagerank_native(
                group_id=GROUP_ID,
                seed_entity_ids=TEST_SEEDS,
                top_k=10,
                include_section_graph=False,
            )
            print(f"✓ Success! Got {len(results)} results")
            for name, score in results[:5]:
                print(f"  - {name}: {score:.4f}")
        except Exception as e:
            print(f"✗ FAILED: {e}")
            import traceback
            traceback.print_exc()


async def test_with_section_graph():
    """Test PPR with section graph traversal."""
    print("\n" + "="*60)
    print("TEST 2: PPR with Section Graph (include_section_graph=True)")
    print("="*60)
    
    async with AsyncNeo4jService.from_settings() as service:
        try:
            results = await service.personalized_pagerank_native(
                group_id=GROUP_ID,
                seed_entity_ids=TEST_SEEDS,
                top_k=10,
                include_section_graph=True,
            )
            print(f"✓ Success! Got {len(results)} results")
            for name, score in results[:5]:
                print(f"  - {name}: {score:.4f}")
        except Exception as e:
            print(f"✗ FAILED: {e}")
            import traceback
            traceback.print_exc()


async def test_section_graph_exists():
    """Check if SEMANTICALLY_SIMILAR edges exist."""
    print("\n" + "="*60)
    print("TEST 3: Check SEMANTICALLY_SIMILAR edges exist")
    print("="*60)
    
    async with AsyncNeo4jService.from_settings() as service:
        query = """
        MATCH (s1:Section)-[sim:SEMANTICALLY_SIMILAR]-(s2:Section)
        WHERE s1.group_id = $group_id
        RETURN count(sim) AS edge_count,
               avg(sim.similarity) AS avg_similarity,
               min(sim.similarity) AS min_similarity,
               max(sim.similarity) AS max_similarity
        """
        async with service._get_session() as session:
            result = await session.run(query, group_id=GROUP_ID)
            record = await result.single()
            
            if record:
                print(f"  Edge count: {record['edge_count']}")
                print(f"  Avg similarity: {record['avg_similarity']:.3f}" if record['avg_similarity'] else "  No edges!")
                print(f"  Min similarity: {record['min_similarity']:.3f}" if record['min_similarity'] else "")
                print(f"  Max similarity: {record['max_similarity']:.3f}" if record['max_similarity'] else "")
            else:
                print("  No SEMANTICALLY_SIMILAR edges found!")


async def test_section_path_traversal():
    """Test the section path traversal portion in isolation."""
    print("\n" + "="*60)
    print("TEST 4: Section Path Traversal (isolated)")
    print("="*60)
    
    async with AsyncNeo4jService.from_settings() as service:
        # Test just the section traversal part
        query = """
        UNWIND $seed_ids AS seed_id
        MATCH (seed {id: seed_id})
        WHERE seed.group_id = $group_id
          AND (seed:Entity OR seed:`__Entity__`)
        
        // Find chunks the seed entity mentions
        MATCH (seed)-[:MENTIONS]->(chunk)
        WHERE chunk.group_id = $group_id
        
        // Navigate to section
        MATCH (chunk)-[:IN_SECTION]->(s1:Section)
        WHERE s1.group_id = $group_id
        
        // Traverse SEMANTICALLY_SIMILAR
        MATCH (s1)-[sim:SEMANTICALLY_SIMILAR]-(s2:Section)
        WHERE s2.group_id = $group_id
        
        // Get chunks in the related section
        MATCH (chunk2)-[:IN_SECTION]->(s2)
        WHERE chunk2.group_id = $group_id
        
        // Find entities mentioned in those chunks
        MATCH (neighbor)-[:MENTIONS]->(chunk2)
        WHERE neighbor.group_id = $group_id
          AND (neighbor:Entity OR neighbor:`__Entity__`)
          AND neighbor.id <> seed.id
        
        RETURN DISTINCT neighbor.name AS name, 
               max(sim.similarity) AS max_sim,
               count(*) AS path_count
        ORDER BY max_sim DESC
        LIMIT 10
        """
        
        async with service._get_session() as session:
            try:
                result = await session.run(query, group_id=GROUP_ID, seed_ids=TEST_SEEDS)
                records = await result.data()
                
                print(f"✓ Section path found {len(records)} entities")
                for r in records[:5]:
                    print(f"  - {r['name']}: sim={r['max_sim']:.3f}, paths={r['path_count']}")
            except Exception as e:
                print(f"✗ FAILED: {e}")
                import traceback
                traceback.print_exc()


async def main():
    print("PPR Section Graph Debug Script")
    print(f"Group ID: {GROUP_ID}")
    print(f"Test seeds: {TEST_SEEDS}")
    
    await test_section_graph_exists()
    await test_section_path_traversal()
    await test_entity_only()
    await test_with_section_graph()


if __name__ == "__main__":
    asyncio.run(main())
