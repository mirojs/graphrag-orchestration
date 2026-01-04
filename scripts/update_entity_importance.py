#!/usr/bin/env python3
"""
Update entity importance scores in Neo4j.

This script adds degree and chunk_count properties to all Entity nodes
using native Cypher (no GDS required).

Run once to update existing entities:
  python scripts/update_entity_importance.py

Environment variables:
  - NEO4J_URI: bolt://... or neo4j+s://...
  - NEO4J_USERNAME: neo4j
  - NEO4J_PASSWORD: your password
"""

import os
import sys
from neo4j import GraphDatabase

# Neo4j connection
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

if not NEO4J_URI or not NEO4J_PASSWORD:
    print("❌ Missing NEO4J_URI or NEO4J_PASSWORD environment variables")
    sys.exit(1)


def update_entity_importance(driver):
    """
    Update entity importance scores using native Cypher.
    
    Properties added:
    - degree: Total number of relationships (higher = more connected)
    - chunk_count: Number of TextChunk nodes mentioning this entity
    - importance_score: Combined score (degree * 0.3 + chunk_count * 0.7)
    """
    print("\n📊 Updating entity importance scores...")
    
    with driver.session() as session:
        # First, check current state
        result = session.run("""
            MATCH (e:`__Entity__`)
            RETURN count(e) AS entity_count,
                   count(e.degree) AS with_degree,
                   count(e.chunk_count) AS with_chunk_count
        """)
        record = result.single()
        print(f"   Found {record['entity_count']} entities")
        print(f"   Already have degree: {record['with_degree']}")
        print(f"   Already have chunk_count: {record['with_chunk_count']}")
        
        # Update degree (count of all relationships)
        print("\n   Setting degree property...")
        result = session.run("""
            MATCH (e:`__Entity__`)
            SET e.degree = size((e)-[]-())
            RETURN count(e) AS updated
        """)
        print(f"   ✅ Updated degree for {result.single()['updated']} entities")
        
        # Update chunk_count (count of MENTIONS relationships to TextChunk/Chunk nodes)
        print("\n   Setting chunk_count property...")
        result = session.run("""
            MATCH (e:`__Entity__`)
            OPTIONAL MATCH (e)-[:MENTIONS]->(c)
            WHERE c:Chunk OR c:TextChunk OR c:`__Node__`
            WITH e, count(c) AS cc
            SET e.chunk_count = cc
            RETURN count(e) AS updated
        """)
        print(f"   ✅ Updated chunk_count for {result.single()['updated']} entities")
        
        # Compute combined importance score
        print("\n   Computing importance_score...")
        result = session.run("""
            MATCH (e:`__Entity__`)
            SET e.importance_score = coalesce(e.degree, 0) * 0.3 + coalesce(e.chunk_count, 0) * 0.7
            RETURN count(e) AS updated,
                   avg(e.importance_score) AS avg_score,
                   max(e.importance_score) AS max_score
        """)
        record = result.single()
        print(f"   ✅ Computed importance for {record['updated']} entities")
        print(f"   📈 Average importance: {record['avg_score']:.2f}")
        print(f"   📈 Max importance: {record['max_score']:.2f}")
        
        # Show top entities
        print("\n   🏆 Top 10 most important entities:")
        result = session.run("""
            MATCH (e:`__Entity__`)
            RETURN e.name AS name, 
                   e.degree AS degree,
                   e.chunk_count AS chunk_count,
                   e.importance_score AS score
            ORDER BY e.importance_score DESC
            LIMIT 10
        """)
        for record in result:
            print(f"      {record['name'][:40]:<40} deg={record['degree']:<3} chunks={record['chunk_count']:<3} score={record['score']:.1f}")


def main():
    print("=" * 60)
    print("Entity Importance Scoring (Native Cypher - No GDS)")
    print("=" * 60)
    print(f"\n🔗 Connecting to: {NEO4J_URI}")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    try:
        # Verify connection
        driver.verify_connectivity()
        print("   ✅ Connected successfully")
        
        update_entity_importance(driver)
        
        print("\n" + "=" * 60)
        print("✅ Entity importance update complete!")
        print("=" * 60)
        
    finally:
        driver.close()


if __name__ == "__main__":
    main()
