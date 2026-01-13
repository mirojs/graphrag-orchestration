#!/usr/bin/env python3
"""Inspect Neo4j graph structure for MENTIONS edges.

This is a standalone diagnostic script intended to be run locally against a
Neo4j instance (Aura/VM/etc) for a given `group_id`.

Usage:
    python inspect_neo4j_mentions.py [group_id]
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

from neo4j import AsyncGraphDatabase
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives in the graphrag-orchestration subdirectory
ENV_FILE = Path(__file__).parent / "graphrag-orchestration" / ".env"


class Config(BaseSettings):
    NEO4J_URI: Optional[str] = None
    NEO4J_USERNAME: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: str = "neo4j"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

settings = Config()


async def execute_query(driver, query, params):
    """Execute a query and return results."""
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = await session.run(query, params)
        return [dict(record) async for record in result]


async def main():
    # Get group_id from command line or use default
    group_id = sys.argv[1] if len(sys.argv) > 1 else "test-5pdfs-cypher25-1768222317"
    
    print(f"Inspecting group_id: {group_id}\n")
    
    if not settings.NEO4J_URI:
        print("ERROR: NEO4J_URI not set. Please set environment variables.")
        return

    if not settings.NEO4J_USERNAME or not settings.NEO4J_PASSWORD:
        print("ERROR: NEO4J_USERNAME/NEO4J_PASSWORD not set.")
        return

    auth = (settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
    
    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=auth,
    )
    
    try:
        print("\n=== 1. MENTIONS Edge Statistics ===")
        query1 = """
            MATCH (c)-[m:MENTIONS]->(e)
            WHERE c.group_id = $group_id
            RETURN 
                count(*) as total_mentions,
                collect(DISTINCT labels(c))[0..5] as chunk_labels,
                collect(DISTINCT labels(e))[0..5] as entity_labels
            LIMIT 1
        """
        result = await execute_query(driver, query1, {"group_id": group_id})
        if result:
            print(f"Total MENTIONS edges: {result[0].get('total_mentions', 0)}")
            print(f"Chunk labels (sample): {result[0].get('chunk_labels', [])}")
            print(f"Entity labels (sample): {result[0].get('entity_labels', [])}")
        
        print("\n=== 2. Sample Entity Properties ===")
        query2 = """
            MATCH (e)
            WHERE e.group_id = $group_id AND (e:Entity OR e:`__Entity__`)
            RETURN e.id as entity_id, e.name as entity_name, labels(e) as entity_labels
            LIMIT 20
        """
        result = await execute_query(driver, query2, {"group_id": group_id})
        for rec in result[:20]:
            print(f"  ID: {rec.get('entity_id')}, Name: {rec.get('entity_name')}, Labels: {rec.get('entity_labels')}")
        
        print(f"\n=== 3. Total Entity Count ===")
        query3 = """
            MATCH (e)
            WHERE e.group_id = $group_id AND (e:Entity OR e:`__Entity__`)
            RETURN count(*) as total_entities
        """
        result = await execute_query(driver, query3, {"group_id": group_id})
        if result:
            print(f"Total entities: {result[0].get('total_entities', 0)}")
        
        print("\n=== 4. Testing Specific Hub Entities ===")
        test_entities = [
            "Documents",
            "Building Arbitration Rules",
            "doc_6dee3910d6ae4a68b24788dc718d30c4_chunk_6:4",
            "doc_5db84c320ff44c79b5b05bc7d7fb7199_chunk_3:2"
        ]
        
        for entity_name in test_entities:
            query4 = """
                MATCH (e)
                WHERE e.group_id = $group_id 
                  AND (e:Entity OR e:`__Entity__`)
                  AND (toLower(e.name) = toLower($entity_name) OR e.id = $entity_name)
                RETURN count(*) as match_count, 
                       collect(e.name)[0] as matched_name,
                       collect(e.id)[0] as matched_id
            """
            result = await execute_query(driver, query4, {"group_id": group_id, "entity_name": entity_name})
            if result:
                match_count = result[0].get('match_count', 0)
                print(f"  Entity '{entity_name}': {match_count} matches")
                if match_count > 0:
                    print(f"    -> Name: {result[0].get('matched_name')}, ID: {result[0].get('matched_id')}")
        
        print("\n=== 5. MENTIONS for Real Entities ===")
        query5 = """
            MATCH (c)-[:MENTIONS]->(e)
            WHERE e.group_id = $group_id 
              AND (e.name = 'Documents' OR e.name = 'Building Arbitration Rules')
            RETURN e.name as entity_name, count(c) as chunk_count
        """
        result = await execute_query(driver, query5, {"group_id": group_id})
        for rec in result:
            print(f"  Entity '{rec.get('entity_name')}': {rec.get('chunk_count')} chunks")
        
        print("\n=== 6. Check for Synthetic IDs in Graph ===")
        query6 = """
            MATCH (e)
            WHERE e.group_id = $group_id 
              AND (e:Entity OR e:`__Entity__`)
              AND (e.name STARTS WITH 'doc_' OR e.id STARTS WITH 'doc_')
            RETURN count(*) as synthetic_count, 
                   collect(e.name)[0..5] as sample_names,
                   collect(e.id)[0..5] as sample_ids
        """
        result = await execute_query(driver, query6, {"group_id": group_id})
        if result:
            print(f"Entities with synthetic doc_ IDs: {result[0].get('synthetic_count', 0)}")
            print(f"Sample names: {result[0].get('sample_names', [])}")
            print(f"Sample IDs: {result[0].get('sample_ids', [])}")
    
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
