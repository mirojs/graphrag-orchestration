#!/usr/bin/env python3
"""
Inspect Neo4j graph structure for MENTIONS edges and entity properties.
"""
import os
import sys
import asyncio
from pathlib import Path
from neo4j import AsyncGraphDatabase

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).parent / "graphrag-orchestration"))

from app.core.config import settings

NEO4J_URI = settings.NEO4J_URI
NEO4J_USERNAME = settings.NEO4J_USERNAME
NEO4J_PASSWORD = settings.NEO4J_PASSWORD
GROUP_ID = "test-5pdfs-cypher25-1768222317"


async def main():
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    try:
        async with driver.session() as session:
            # 1. Check MENTIONS edge count and structure
            print("\n=== MENTIONS Edge Statistics ===")
            result = await session.run("""
                MATCH (c)-[m:MENTIONS]->(e)
                WHERE c.group_id = $group_id
                RETURN 
                    count(*) as total_mentions,
                    collect(DISTINCT labels(c)) as chunk_labels,
                    collect(DISTINCT labels(e)) as entity_labels,
                    collect(DISTINCT type(m)) as rel_types
                LIMIT 1
            """, group_id=GROUP_ID)
            record = await result.single()
            if record:
                print(f"Total MENTIONS edges: {record['total_mentions']}")
                print(f"Chunk labels: {record['chunk_labels']}")
                print(f"Entity labels: {record['entity_labels']}")
                print(f"Relationship types: {record['rel_types']}")
            
            # 2. Sample entity properties
            print("\n=== Sample Entity Properties (first 20) ===")
            result = await session.run("""
                MATCH (e)
                WHERE e.group_id = $group_id AND (e:Entity OR e:`__Entity__`)
                RETURN e.id as entity_id, e.name as entity_name, labels(e) as entity_labels
                LIMIT 20
            """, group_id=GROUP_ID)
            async for record in result:
                print(f"ID: {record['entity_id']}, Name: {record['entity_name']}, Labels: {record['entity_labels']}")
            
            # 3. Check if synthetic IDs exist as entity names or IDs
            print("\n=== Checking for Synthetic Entity IDs ===")
            result = await session.run("""
                MATCH (e)
                WHERE e.group_id = $group_id 
                  AND (e:Entity OR e:`__Entity__`)
                  AND (e.name STARTS WITH 'doc_' OR e.id STARTS WITH 'doc_')
                RETURN count(*) as synthetic_count, 
                       collect(e.name)[0..5] as sample_names,
                       collect(e.id)[0..5] as sample_ids
            """, group_id=GROUP_ID)
            record = await result.single()
            if record:
                print(f"Entities with synthetic IDs: {record['synthetic_count']}")
                print(f"Sample names: {record['sample_names']}")
                print(f"Sample IDs: {record['sample_ids']}")
            
            # 4. Check specific hub entities from logs
            test_entities = [
                "Documents",
                "Building Arbitration Rules",
                "doc_6dee3910d6ae4a68b24788dc718d30c4_chunk_6:4",
                "doc_5db84c320ff44c79b5b05bc7d7fb7199_chunk_3:2"
            ]
            
            print("\n=== Testing Hub Entities from Logs ===")
            for entity_name in test_entities:
                result = await session.run("""
                    MATCH (e)
                    WHERE e.group_id = $group_id 
                      AND (e:Entity OR e:`__Entity__`)
                      AND (toLower(e.name) = toLower($entity_name) OR e.id = $entity_name)
                    RETURN count(*) as match_count, 
                           collect(e.name)[0] as matched_name,
                           collect(e.id)[0] as matched_id
                """, group_id=GROUP_ID, entity_name=entity_name)
                record = await result.single()
                if record:
                    print(f"Entity '{entity_name}': {record['match_count']} matches")
                    if record['match_count'] > 0:
                        print(f"  -> Matched name: {record['matched_name']}, ID: {record['matched_id']}")
            
            # 5. Check MENTIONS for real entities
            print("\n=== MENTIONS Edges for Real Entities ===")
            result = await session.run("""
                MATCH (c)-[:MENTIONS]->(e)
                WHERE e.group_id = $group_id 
                  AND (e.name = 'Documents' OR e.name = 'Building Arbitration Rules')
                RETURN e.name as entity_name, count(c) as chunk_count
            """, group_id=GROUP_ID)
            async for record in result:
                print(f"Entity '{record['entity_name']}': {record['chunk_count']} chunks mention it")
            
            # 6. Check total entity count
            print("\n=== Total Entity Count ===")
            result = await session.run("""
                MATCH (e)
                WHERE e.group_id = $group_id AND (e:Entity OR e:`__Entity__`)
                RETURN count(*) as total_entities
            """, group_id=GROUP_ID)
            record = await result.single()
            if record:
                print(f"Total entities in group: {record['total_entities']}")
    
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
