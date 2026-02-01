#!/usr/bin/env python3
"""
Check KNN groups with Entity label (not __Entity__).
"""
from neo4j import GraphDatabase
import os

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

def check_knn_groups():
    """Check KNN groups structure."""
    
    groups = [
        ("test-5pdfs-v2-enhanced-ex", "Yesterday's V2 (15/16)"),
        ("test-5pdfs-v2-knn-disabled", "KNN Baseline (K=0)"),
        ("test-5pdfs-v2-knn-1", "KNN-1 (K=3, cutoff=0.80)"),
        ("test-5pdfs-v2-knn-2", "KNN-2 (K=5, cutoff=0.75)"),
        ("test-5pdfs-v2-knn-3", "KNN-3 (K=5, cutoff=0.85)"),
    ]
    
    with driver.session() as session:
        for group_id, desc in groups:
            print(f"\n{'='*60}")
            print(f"{group_id}")
            print(f"{desc}")
            print('='*60)
            
            # Count entities
            result = session.run("""
                MATCH (e:Entity {group_id: $group_id})
                RETURN count(e) as count
            """, group_id=group_id)
            entity_count = result.single()["count"]
            print(f"Entities: {entity_count}")
            
            # Count KNN_SIMILAR relationships
            knn_result = session.run("""
                MATCH (e1:Entity {group_id: $group_id})-[r:KNN_SIMILAR]->(e2:Entity {group_id: $group_id})
                RETURN count(r) as count
            """, group_id=group_id)
            knn_count = knn_result.single()["count"]
            print(f"KNN edges: {knn_count}")
            
            # Count RELATED_TO relationships
            rel_result = session.run("""
                MATCH (e1:Entity {group_id: $group_id})-[r:RELATED_TO]->(e2:Entity {group_id: $group_id})
                RETURN count(r) as count
            """, group_id=group_id)
            rel_count = rel_result.single()["count"]
            print(f"RELATED_TO edges: {rel_count}")
            
            # Count TextChunks
            chunk_result = session.run("""
                MATCH (c:TextChunk {group_id: $group_id})
                RETURN count(c) as count
            """, group_id=group_id)
            chunk_count = chunk_result.single()["count"]
            print(f"TextChunks: {chunk_count}")

if __name__ == "__main__":
    check_knn_groups()
    driver.close()
