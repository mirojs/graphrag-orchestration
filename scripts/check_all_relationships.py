#!/usr/bin/env python3
"""
Check all relationship types for KNN groups.
"""
from neo4j import GraphDatabase
import os

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

def check_all_relationships():
    """Check all relationship types for each KNN group."""
    
    groups = [
        ("test-5pdfs-v2-enhanced-ex", "Yesterday's V2"),
        ("test-5pdfs-v2-knn-disabled", "KNN Baseline"),
        ("test-5pdfs-v2-knn-1", "KNN-1"),
        ("test-5pdfs-v2-knn-2", "KNN-2"),
        ("test-5pdfs-v2-knn-3", "KNN-3"),
    ]
    
    # All possible relationship types
    rel_types = [
        "KNN_SIMILAR",
        "SEMANTICALLY_SIMILAR",
        "SIMILAR_TO",
        "RELATED_TO",
        "MENTIONS",
    ]
    
    with driver.session() as session:
        for group_id, desc in groups:
            print(f"\n{'='*60}")
            print(f"{group_id} ({desc})")
            print('='*60)
            
            # Count entities
            result = session.run("""
                MATCH (e:Entity {group_id: $group_id})
                RETURN count(e) as count
            """, group_id=group_id)
            entity_count = result.single()["count"]
            print(f"Entities: {entity_count}")
            
            # Check each relationship type
            for rel_type in rel_types:
                result = session.run(f"""
                    MATCH (e1:Entity {{group_id: $group_id}})-[r:`{rel_type}`]->(e2:Entity {{group_id: $group_id}})
                    RETURN count(r) as count
                """, group_id=group_id)
                count = result.single()["count"]
                if count > 0:
                    print(f"  {rel_type}: {count}")

if __name__ == "__main__":
    check_all_relationships()
    driver.close()
