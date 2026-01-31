#!/usr/bin/env python3
"""
Initialize Neo4j schema for hierarchical folder management.

Creates:
- Uniqueness constraint on Folder.id
- Indexes on Folder.group_id and Folder.parent_folder_id for query performance
"""

import os
import sys
from neo4j import GraphDatabase


def init_folder_schema(uri: str, username: str, password: str):
    """Initialize folder schema in Neo4j."""
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    try:
        with driver.session() as session:
            print("Creating Folder schema...")
            
            # 1. Uniqueness constraint on Folder.id
            print("  - Creating uniqueness constraint on Folder.id...")
            session.run("""
                CREATE CONSTRAINT folder_id_unique IF NOT EXISTS
                FOR (f:Folder) REQUIRE f.id IS UNIQUE
            """)
            
            # 2. Index on Folder.group_id for tenant isolation
            print("  - Creating index on Folder.group_id...")
            session.run("""
                CREATE INDEX folder_group_id IF NOT EXISTS
                FOR (f:Folder) ON (f.group_id)
            """)
            
            # 3. Index on Folder.parent_folder_id for hierarchy queries
            print("  - Creating index on Folder.parent_folder_id...")
            session.run("""
                CREATE INDEX folder_parent_id IF NOT EXISTS
                FOR (f:Folder) ON (f.parent_folder_id)
            """)
            
            # 4. Index on Folder.name for search
            print("  - Creating index on Folder.name...")
            session.run("""
                CREATE INDEX folder_name IF NOT EXISTS
                FOR (f:Folder) ON (f.name)
            """)
            
            # 5. Verify schema
            print("\nVerifying schema...")
            constraints = session.run("SHOW CONSTRAINTS").data()
            indexes = session.run("SHOW INDEXES").data()
            
            folder_constraints = [c for c in constraints if 'Folder' in str(c.get('labelsOrTypes', []))]
            folder_indexes = [i for i in indexes if 'Folder' in str(i.get('labelsOrTypes', []))]
            
            print(f"\nFolder Constraints: {len(folder_constraints)}")
            for c in folder_constraints:
                print(f"  - {c.get('name')}: {c.get('type')}")
            
            print(f"\nFolder Indexes: {len(folder_indexes)}")
            for i in folder_indexes:
                print(f"  - {i.get('name')}: {i.get('type')}")
            
            print("\n✅ Folder schema initialized successfully!")
            
    finally:
        driver.close()


def main():
    """Main entry point."""
    # Get Neo4j connection details from environment
    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    
    if not uri or not password:
        print("❌ Error: NEO4J_URI and NEO4J_PASSWORD must be set")
        print("\nUsage:")
        print("  export NEO4J_URI=bolt://localhost:7687")
        print("  export NEO4J_PASSWORD=your-password")
        print("  python scripts/init_folder_schema.py")
        sys.exit(1)
    
    print(f"Connecting to Neo4j at {uri}...\n")
    init_folder_schema(uri, username, password)


if __name__ == "__main__":
    main()
