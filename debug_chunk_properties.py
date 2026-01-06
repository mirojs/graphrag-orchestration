#!/usr/bin/env python3
"""Check what properties chunks actually have in Neo4j."""

import asyncio
import os
from neo4j import AsyncGraphDatabase


async def main():
    uri = "neo4j+s://a86dcf63.databases.neo4j.io"
    username = "neo4j"
    password = os.getenv("NEO4J_PASSWORD", "graphrag-neo4j-password-123")
    
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
    
    # Check one chunk and see all its properties
    query = """
    MATCH (c)
    WHERE c.group_id = $group_id
      AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
    RETURN c.chunk_id, keys(c) AS properties, 
           c.url, c.document_id, c.source,
           substring(c.text, 0, 150) AS preview
    LIMIT 5
    """
    
    async with driver.session(database="neo4j") as session:
        result = await session.run(
            query,
            group_id="test-5pdfs-1767429340223041632"
        )
        records = await result.data()
        
        print(f"Found {len(records)} chunks\n")
        for i, rec in enumerate(records, 1):
            print(f"=== Chunk {i} ===")
            print(f"chunk_id: {rec.get('c.chunk_id')}")
            print(f"properties: {rec.get('properties')}")
            print(f"c.url: {rec.get('c.url')}")
            print(f"c.document_id: {rec.get('c.document_id')}")
            print(f"c.source: {rec.get('c.source')}")
            print(f"preview: {rec.get('preview')}")
            print()
    
    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
