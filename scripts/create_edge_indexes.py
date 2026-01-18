#!/usr/bin/env python3
"""
Create indexes on new foundation edge properties for performance.

Neo4j doesn't automatically index relationship properties, so we need to
create them manually for efficient filtering by group_id.
"""

import os
from neo4j import GraphDatabase


NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def create_indexes(driver):
    """Create indexes on relationship properties."""
    
    indexes = [
        ("APPEARS_IN_SECTION", "group_id"),
        ("APPEARS_IN_DOCUMENT", "group_id"),
        ("HAS_HUB_ENTITY", "group_id"),
    ]
    
    with driver.session() as session:
        for rel_type, prop in indexes:
            index_name = f"{rel_type.lower()}_{prop}_index"
            
            # Neo4j 5.x syntax for relationship property index
            query = f"""
            CREATE INDEX {index_name} IF NOT EXISTS
            FOR ()-[r:{rel_type}]-()
            ON (r.{prop})
            """
            
            try:
                session.run(query)
                print(f"✅ Created index: {index_name}")
            except Exception as e:
                print(f"⚠️  Index {index_name}: {e}")


def show_indexes(driver):
    """Show all indexes."""
    with driver.session() as session:
        result = session.run("SHOW INDEXES")
        print("\n📊 All Indexes:")
        for record in result:
            print(f"  {record['name']}: {record['type']} on {record['labelsOrTypes']}")


def main():
    if not NEO4J_PASSWORD:
        print("❌ ERROR: NEO4J_PASSWORD environment variable not set")
        return 1
    
    print("🔧 Creating indexes on foundation edge properties...")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    try:
        create_indexes(driver)
        show_indexes(driver)
        print("\n✅ Indexes created successfully!")
    finally:
        driver.close()
    
    return 0


if __name__ == "__main__":
    exit(main())
