#!/usr/bin/env python3
"""
Backfill document_id property on TextChunk nodes.

The document_id was being passed to Neo4j but not stored as a property on chunks.
This script adds the property by following the PART_OF relationship to get the document ID.

Usage:
    python scripts/backfill_chunk_document_id.py --group-id <GROUP_ID>
"""

import argparse
import os
import sys
from neo4j import GraphDatabase


def backfill_document_ids(driver, group_id: str) -> dict:
    """Add document_id property to all TextChunk nodes."""
    
    query = """
    MATCH (t:TextChunk {group_id: $group_id})-[:PART_OF]->(d:Document)
    WHERE t.document_id IS NULL
    SET t.document_id = d.id
    RETURN count(t) AS updated_chunks
    """
    
    with driver.session(database="neo4j") as session:
        result = session.run(query, group_id=group_id)
        record = result.single()
        updated = record["updated_chunks"] if record else 0
        
        print(f"✅ Updated {updated} chunks with document_id property")
        
        # Verify
        verify_query = """
        MATCH (t:TextChunk {group_id: $group_id})
        RETURN 
            count(t) AS total_chunks,
            count(t.document_id) AS chunks_with_document_id
        """
        result = session.run(verify_query, group_id=group_id)
        record = result.single()
        
        return {
            "updated_chunks": updated,
            "total_chunks": record["total_chunks"],
            "chunks_with_document_id": record["chunks_with_document_id"],
        }


def main():
    parser = argparse.ArgumentParser(description="Backfill document_id on TextChunk nodes")
    parser.add_argument("--group-id", required=True, help="Group ID to process")
    args = parser.parse_args()
    
    # Get Neo4j credentials
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    
    if not uri or not password:
        print("❌ Error: NEO4J_URI and NEO4J_PASSWORD must be set")
        sys.exit(1)
    
    print(f"Connecting to Neo4j at {uri}...")
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    try:
        driver.verify_connectivity()
        print(f"✅ Connected successfully")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        sys.exit(1)
    
    print(f"\nBackfilling document_id for group: {args.group_id}")
    result = backfill_document_ids(driver, args.group_id)
    
    print(f"\nResults:")
    print(f"  Total chunks: {result['total_chunks']}")
    print(f"  Chunks with document_id: {result['chunks_with_document_id']}")
    print(f"  Updated in this run: {result['updated_chunks']}")
    
    driver.close()


if __name__ == "__main__":
    main()
