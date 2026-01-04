#!/usr/bin/env python3
"""
Compute entity importance scores for all Entity nodes in Neo4j.

This script adds two properties to each Entity node:
- degree: Number of relationships the entity has
- chunk_count: Number of TextChunk nodes that mention this entity

These properties enable fast importance-based filtering during retrieval.
Run this once to update existing data, and ensure the ingestion pipeline
calls compute_importance_for_entities() after upserting new entities.

Usage:
    python scripts/compute_entity_importance.py

Environment variables:
    NEO4J_URI: Neo4j connection URI
    NEO4J_USERNAME: Neo4j username  
    NEO4J_PASSWORD: Neo4j password
"""

import os
import sys
from neo4j import GraphDatabase


def compute_entity_importance(driver) -> dict:
    """
    Compute importance scores for all Entity nodes.
    
    Returns:
        dict with counts of updated entities and stats
    """
    with driver.session() as session:
        # First, count entities
        result = session.run("MATCH (e:Entity) RETURN count(e) as total")
        total = result.single()["total"]
        print(f"Found {total} Entity nodes to update")
        
        if total == 0:
            return {"total": 0, "updated": 0}
        
        # Compute degree (total relationships)
        print("Computing degree (relationship count)...")
        result = session.run("""
            MATCH (e:Entity)
            WITH e, COUNT { (e)-[]-() } as degree
            SET e.degree = degree
            RETURN count(e) as updated
        """)
        degree_updated = result.single()["updated"]
        print(f"  Updated degree for {degree_updated} entities")
        
        # Compute chunk_count (how many chunks mention this entity)
        print("Computing chunk_count (TextChunk mentions)...")
        result = session.run("""
            MATCH (e:Entity)
            WITH e, COUNT { (e)<-[:MENTIONS]-(:TextChunk) } as chunk_count
            SET e.chunk_count = chunk_count
            RETURN count(e) as updated
        """)
        chunk_updated = result.single()["updated"]
        print(f"  Updated chunk_count for {chunk_updated} entities")
        
        # Get some stats
        print("\nComputing statistics...")
        result = session.run("""
            MATCH (e:Entity)
            RETURN 
                avg(e.degree) as avg_degree,
                max(e.degree) as max_degree,
                avg(e.chunk_count) as avg_chunks,
                max(e.chunk_count) as max_chunks
        """)
        stats = result.single()
        
        print(f"\nEntity Importance Statistics:")
        print(f"  Average degree: {stats['avg_degree']:.2f}")
        print(f"  Max degree: {stats['max_degree']}")
        print(f"  Average chunk mentions: {stats['avg_chunks']:.2f}")
        print(f"  Max chunk mentions: {stats['max_chunks']}")
        
        # Show top entities by importance
        print("\nTop 10 entities by degree:")
        result = session.run("""
            MATCH (e:Entity)
            RETURN e.name as name, e.degree as degree, e.chunk_count as chunks
            ORDER BY e.degree DESC
            LIMIT 10
        """)
        for record in result:
            print(f"  {record['name']}: degree={record['degree']}, chunks={record['chunks']}")
        
        return {
            "total": total,
            "updated": degree_updated,
            "avg_degree": stats['avg_degree'],
            "max_degree": stats['max_degree'],
            "avg_chunks": stats['avg_chunks'],
            "max_chunks": stats['max_chunks']
        }


def main():
    # Get Neo4j credentials from environment
    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    
    if not uri or not password:
        print("Error: NEO4J_URI and NEO4J_PASSWORD environment variables required")
        sys.exit(1)
    
    print(f"Connecting to Neo4j at {uri}...")
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    try:
        # Verify connectivity
        driver.verify_connectivity()
        print("Connected successfully!\n")
        
        # Compute importance scores
        stats = compute_entity_importance(driver)
        
        print(f"\n✅ Entity importance computation complete!")
        print(f"   Updated {stats['updated']} entities")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
