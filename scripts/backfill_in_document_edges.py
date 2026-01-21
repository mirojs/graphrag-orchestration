#!/usr/bin/env python3
"""
Backfill IN_DOCUMENT relationships between TextChunk and Document nodes.

The indexing pipeline was updated to create (TextChunk)-[:IN_DOCUMENT]->(Document)
relationships, but existing groups may be missing these edges. This script creates
them by matching chunk.id prefix to document.id.

Pattern: chunk.id = "doc_XXX_chunk_N" should link to document.id = "doc_XXX"

Usage:
    python scripts/backfill_in_document_edges.py --group-id <GROUP_ID>
    python scripts/backfill_in_document_edges.py --all-groups
"""

import argparse
import os
import sys
from neo4j import GraphDatabase


def backfill_in_document_edges(driver, group_id: str) -> dict:
    """Create IN_DOCUMENT edges for TextChunks missing them."""
    
    # Create edges by matching chunk ID prefix to document ID
    query = """
    MATCH (c:TextChunk), (d:Document)
    WHERE c.group_id = $group_id
      AND d.group_id = $group_id
      AND c.id STARTS WITH d.id
      AND NOT (c)-[:IN_DOCUMENT]->(d)
    CREATE (c)-[:IN_DOCUMENT]->(d)
    RETURN count(*) AS edges_created
    """
    
    with driver.session(database="neo4j") as session:
        result = session.run(query, group_id=group_id)
        record = result.single()
        created = record["edges_created"] if record else 0
        
        print(f"✅ Created {created} IN_DOCUMENT edges")
        
        # Verify
        verify_query = """
        MATCH (c:TextChunk {group_id: $group_id})
        OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document)
        RETURN 
            count(c) AS total_chunks,
            count(d) AS chunks_with_in_document
        """
        result = session.run(verify_query, group_id=group_id)
        record = result.single()
        
        return {
            "edges_created": created,
            "total_chunks": record["total_chunks"],
            "chunks_linked": record["chunks_with_in_document"],
        }


def get_all_groups(driver) -> list:
    """Get all unique group IDs."""
    query = """
    MATCH (c:TextChunk)
    RETURN DISTINCT c.group_id AS group_id
    ORDER BY c.group_id
    """
    with driver.session(database="neo4j") as session:
        result = session.run(query)
        return [r["group_id"] for r in result if r["group_id"]]


def main():
    parser = argparse.ArgumentParser(description="Backfill IN_DOCUMENT edges")
    parser.add_argument("--group-id", help="Specific group to backfill")
    parser.add_argument("--all-groups", action="store_true", help="Backfill all groups")
    args = parser.parse_args()
    
    if not args.group_id and not args.all_groups:
        parser.error("Must specify --group-id or --all-groups")
    
    # Load environment
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "graphrag-orchestration", ".env"))
    
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    
    if not neo4j_uri or not neo4j_password:
        print("❌ NEO4J_URI and NEO4J_PASSWORD must be set")
        sys.exit(1)
    
    driver = GraphDatabase.driver(neo4j_uri, auth=("neo4j", neo4j_password))
    
    try:
        if args.all_groups:
            groups = get_all_groups(driver)
            print(f"Found {len(groups)} groups to process")
            
            total_created = 0
            for gid in groups:
                print(f"\n--- Processing {gid} ---")
                stats = backfill_in_document_edges(driver, gid)
                total_created += stats["edges_created"]
            
            print(f"\n=== TOTAL: Created {total_created} IN_DOCUMENT edges ===")
        else:
            stats = backfill_in_document_edges(driver, args.group_id)
            print(f"\nStats: {stats}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
