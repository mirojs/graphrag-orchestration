#!/usr/bin/env python3
"""
List all group_ids in Neo4j.
"""
from neo4j import GraphDatabase
import os

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

if not NEO4J_PASSWORD:
    print("ERROR: Please set NEO4J_PASSWORD environment variable")
    exit(1)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

def list_all_groups():
    """List all distinct group_ids in the database."""
    
    with driver.session() as session:
        # Get all distinct group_ids
        result = session.run("""
            MATCH (e:__Entity__)
            RETURN DISTINCT e.group_id as group_id, count(e) as entity_count
            ORDER BY group_id
        """)
        
        print("All groups in Neo4j:")
        print("="*60)
        
        for record in result:
            group_id = record["group_id"]
            entity_count = record["entity_count"]
            
            # Count KNN edges for this group
            knn_result = session.run("""
                MATCH (e1:__Entity__ {group_id: $group_id})-[r:KNN_SIMILAR]->(e2:__Entity__ {group_id: $group_id})
                RETURN count(r) as knn_edges
            """, group_id=group_id)
            
            knn_edges = knn_result.single()["knn_edges"]
            
            print(f"\n{group_id}")
            print(f"  Entities: {entity_count}")
            print(f"  KNN edges: {knn_edges}")

if __name__ == "__main__":
    list_all_groups()
    driver.close()
