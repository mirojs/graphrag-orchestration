#!/usr/bin/env python3
"""
Debug: Check if communities exist for the V2 group.
"""

import asyncio
import os
import sys

# Setup path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, app_root)
os.chdir(app_root)

from dotenv import load_dotenv
load_dotenv()

from neo4j import GraphDatabase
from src.core.config import settings

NEO4J_URI = settings.NEO4J_URI
NEO4J_USERNAME = settings.NEO4J_USERNAME
NEO4J_PASSWORD = settings.NEO4J_PASSWORD
GROUP_ID = "test-5pdfs-v2-enhanced-ex"


def check_communities():
    """Check if communities exist for the group."""
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
    )
    
    try:
        with driver.session() as session:
            # Check for Community nodes
            result = session.run("""
                MATCH (c:Community)
                WHERE c.group_id = $group_id
                RETURN count(c) as count
            """, group_id=GROUP_ID)
            count = result.single()["count"]
            print(f"Community nodes for {GROUP_ID}: {count}")
            
            if count > 0:
                # Get sample summaries
                result = session.run("""
                    MATCH (c:Community)
                    WHERE c.group_id = $group_id
                    RETURN c.id as id, left(c.summary, 200) as summary_preview
                    LIMIT 5
                """, group_id=GROUP_ID)
                print("\nSample communities:")
                for record in result:
                    print(f"  {record['id']}: {record['summary_preview']}...")
            
            # Check for Entity nodes
            result = session.run("""
                MATCH (e:Entity)
                WHERE e.group_id = $group_id
                RETURN count(e) as count
            """, group_id=GROUP_ID)
            entity_count = result.single()["count"]
            print(f"\nEntity nodes for {GROUP_ID}: {entity_count}")
            
            if entity_count > 0:
                # Get sample entities
                result = session.run("""
                    MATCH (e:Entity)
                    WHERE e.group_id = $group_id
                    RETURN e.name as name
                    LIMIT 20
                """, group_id=GROUP_ID)
                print("\nSample entities:")
                entities = [r["name"] for r in result]
                print(f"  {entities}")
    finally:
        driver.close()


if __name__ == "__main__":
    check_communities()
