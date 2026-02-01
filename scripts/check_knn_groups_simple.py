#!/usr/bin/env python3
"""
Simple script to check KNN groups in Neo4j.
"""
from neo4j import GraphDatabase
import json

# Hardcoded from your setup
NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
# Password needs to be provided via environment or command line
import os
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

if not NEO4J_PASSWORD:
    print("ERROR: Please set NEO4J_PASSWORD environment variable")
    exit(1)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

def check_groups():
    """Check existence and metadata of KNN test groups."""
    
    groups_to_check = [
        "test-5pdfs-v2-enhanced-ex",  # Yesterday's V2 group (15/16)
        "test-5pdfs-v2-knn-disabled",  # Today's KNN baseline
        "test-5pdfs-v2-knn-1",
        "test-5pdfs-v2-knn-2",
        "test-5pdfs-v2-knn-3",
    ]
    
    results = {}
    
    with driver.session() as session:
        for group_id in groups_to_check:
            print(f"\n{'='*60}")
            print(f"Group: {group_id}")
            print('='*60)
            
            # Check if group exists by counting entities
            result = session.run("""
                MATCH (e:__Entity__ {group_id: $group_id})
                RETURN count(e) as entity_count
            """, group_id=group_id)
            
            record = result.single()
            entity_count = record["entity_count"] if record else 0
            
            if entity_count == 0:
                print(f"❌ NOT FOUND - 0 entities")
                results[group_id] = {"exists": False}
                continue
            
            print(f"✓ Found {entity_count} entities")
            
            # Count KNN edges
            knn_result = session.run("""
                MATCH (e1:__Entity__ {group_id: $group_id})-[r:KNN_SIMILAR]->(e2:__Entity__ {group_id: $group_id})
                RETURN count(r) as knn_edge_count
            """, group_id=group_id)
            
            knn_record = knn_result.single()
            knn_edges = knn_record["knn_edge_count"] if knn_record else 0
            print(f"  KNN edges: {knn_edges}")
            
            # Count regular relationships  
            rel_result = session.run("""
                MATCH (e1:__Entity__ {group_id: $group_id})-[r]-(e2:__Entity__ {group_id: $group_id})
                WHERE type(r) <> 'KNN_SIMILAR'
                RETURN count(DISTINCT r) as rel_count
            """, group_id=group_id)
            
            rel_record = rel_result.single()
            rel_count = rel_record["rel_count"] if rel_record else 0
            print(f"  Regular relationships: {rel_count}")
            
            results[group_id] = {
                "exists": True,
                "entities": entity_count,
                "knn_edges": knn_edges,
                "relationships": rel_count
            }
    
    print(f"\n\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    check_groups()
    driver.close()
