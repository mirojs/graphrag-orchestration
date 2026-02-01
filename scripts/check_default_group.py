#!/usr/bin/env python3
"""
Check for default group and common group patterns.
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

def check_default_and_common():
    """Check for default group and common patterns."""
    
    groups_to_check = [
        "default",
        "test-5pdfs",
        "test-5pdfs-v1",
        "test-5pdfs-v2",
    ]
    
    with driver.session() as session:
        # First, get count of all entities
        total_result = session.run("MATCH (e:__Entity__) RETURN count(e) as total")
        total = total_result.single()["total"]
        print(f"Total entities in database: {total}\n")
        
        if total == 0:
            print("⚠️  DATABASE IS EMPTY - No entities at all!")
            return
        
        for group_id in groups_to_check:
            result = session.run("""
                MATCH (e:__Entity__ {group_id: $group_id})
                RETURN count(e) as entity_count
            """, group_id=group_id)
            
            record = result.single()
            count = record["entity_count"] if record else 0
            
            if count > 0:
                print(f"✓ {group_id}: {count} entities")
            else:
                print(f"✗ {group_id}: not found")

if __name__ == "__main__":
    check_default_and_common()
    driver.close()
