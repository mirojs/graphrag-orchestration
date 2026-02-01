#!/usr/bin/env python3
"""
Check the 4 KNN groups in detail.
"""
from neo4j import GraphDatabase
import os

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

def check_knn_groups_detailed():
    """Check the 4 KNN groups with all details."""
    
    groups = [
        "test-5pdfs-v2-knn-disabled",
        "test-5pdfs-v2-knn-1",
        "test-5pdfs-v2-knn-2",
        "test-5pdfs-v2-knn-3",
    ]
    
    with driver.session() as session:
        for group_id in groups:
            print(f"\n{'='*60}")
            print(f"{group_id}")
            print('='*60)
            
            # Count all node types for this group
            result = session.run("""
                MATCH (n {group_id: $group_id})
                RETURN labels(n) as labels, count(n) as count
                ORDER BY count DESC
            """, group_id=group_id)
            
            print("Node types:")
            for record in result:
                labels = record["labels"]
                count = record["count"]
                print(f"  {'/'.join(labels)}: {count}")
            
            # Count all relationships between nodes in this group
            result = session.run("""
                MATCH (n1 {group_id: $group_id})-[r]->(n2 {group_id: $group_id})
                RETURN type(r) as rel_type, count(r) as count
                ORDER BY count DESC
            """, group_id=group_id)
            
            print("\nRelationships:")
            total_rels = 0
            for record in result:
                rel_type = record["rel_type"]
                count = record["count"]
                total_rels += count
                print(f"  {rel_type}: {count}")
            
            print(f"\n  TOTAL: {total_rels} relationships")

if __name__ == "__main__":
    check_knn_groups_detailed()
    driver.close()
