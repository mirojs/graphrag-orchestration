#!/usr/bin/env python3
"""
Check creation timestamps for KNN groups.
"""
from neo4j import GraphDatabase
import os
from datetime import datetime

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

def check_creation_dates():
    """Check creation dates for all test-5pdfs-v2 groups."""
    
    with driver.session() as session:
        # Get all test-5pdfs-v2 groups with their GroupMeta
        result = session.run("""
            MATCH (g:GroupMeta)
            WHERE g.group_id STARTS WITH 'test-5pdfs-v2'
            RETURN g.group_id as group_id, 
                   g.created_at as created_at,
                   g.indexed_at as indexed_at,
                   g
            ORDER BY g.group_id
        """)
        
        print("GroupMeta nodes for test-5pdfs-v2-* groups:")
        print("="*80)
        
        for record in result:
            group_id = record["group_id"]
            created_at = record["created_at"]
            indexed_at = record["indexed_at"]
            meta = record["g"]
            
            print(f"\n{group_id}")
            if created_at:
                print(f"  created_at: {created_at}")
            if indexed_at:
                print(f"  indexed_at: {indexed_at}")
            
            # Show all properties
            print(f"  All properties:")
            for key, value in meta.items():
                if key not in ['group_id']:
                    print(f"    {key}: {value}")

if __name__ == "__main__":
    check_creation_dates()
    driver.close()
