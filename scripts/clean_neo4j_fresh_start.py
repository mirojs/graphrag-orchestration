#!/usr/bin/env python3
"""
Clean Neo4j Database for Fresh Start

This script:
1. Lists all existing data by group_id
2. Drops ALL existing vector indexes (1536 dimension)
3. Deletes ALL nodes and relationships
4. Recreates indexes with 3072 dimensions (text-embedding-3-large)

Run:
    export NEO4J_PASSWORD="your_password"
    python scripts/clean_neo4j_fresh_start.py
"""

import os
import sys

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo4j import GraphDatabase


# Configuration
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# 3072 dimensions for text-embedding-3-large
EMBEDDING_DIMENSIONS = 3072


def main():
    if not NEO4J_PASSWORD:
        print("ERROR: NEO4J_PASSWORD environment variable not set")
        print("  export NEO4J_PASSWORD='your_password'")
        sys.exit(1)
    
    print("=" * 70)
    print("NEO4J CLEAN START SCRIPT")
    print("=" * 70)
    print(f"URI:      {NEO4J_URI}")
    print(f"Database: {NEO4J_DATABASE}")
    print(f"Embedding Dimensions: {EMBEDDING_DIMENSIONS}")
    print("=" * 70)
    print()
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            # Step 1: Show current data
            print("STEP 1: Current Data Summary")
            print("-" * 50)
            
            # Count nodes by label
            result = session.run("""
                MATCH (n) 
                RETURN labels(n)[0] as label, count(n) as count 
                ORDER BY count DESC LIMIT 20
            """)
            total_nodes = 0
            for record in result:
                label = record["label"] or "unlabeled"
                count = record["count"]
                total_nodes += count
                print(f"  {label}: {count}")
            print(f"  TOTAL: {total_nodes}")
            print()
            
            # Count by group_id
            print("Data by Group ID:")
            result = session.run("""
                MATCH (n) WHERE n.group_id IS NOT NULL 
                RETURN n.group_id as group_id, count(n) as count 
                ORDER BY count DESC LIMIT 20
            """)
            for record in result:
                print(f"  {record['group_id']}: {record['count']}")
            print()
            
            # Step 2: List and drop indexes
            print("STEP 2: Drop Existing Vector Indexes")
            print("-" * 50)
            
            result = session.run("SHOW INDEXES")
            indexes_to_drop = []
            for record in result:
                idx_name = record.get("name", "")
                idx_type = record.get("type", "")
                if idx_type == "VECTOR":
                    indexes_to_drop.append(idx_name)
                    print(f"  Found vector index: {idx_name}")
            
            if indexes_to_drop:
                confirm = input(f"\nDrop {len(indexes_to_drop)} vector indexes? [y/N]: ")
                if confirm.lower() == 'y':
                    for idx_name in indexes_to_drop:
                        try:
                            session.run(f"DROP INDEX {idx_name}")
                            print(f"  ✓ Dropped {idx_name}")
                        except Exception as e:
                            print(f"  ✗ Failed to drop {idx_name}: {e}")
                else:
                    print("  Skipped index dropping")
            else:
                print("  No vector indexes found")
            print()
            
            # Step 3: Delete all data
            print("STEP 3: Delete All Data")
            print("-" * 50)
            
            if total_nodes > 0:
                confirm = input(f"DELETE ALL {total_nodes} NODES? This cannot be undone! [y/N]: ")
                if confirm.lower() == 'y':
                    # Delete in batches to avoid memory issues
                    batch_size = 10000
                    deleted_total = 0
                    
                    while True:
                        result = session.run(f"""
                            MATCH (n)
                            WITH n LIMIT {batch_size}
                            DETACH DELETE n
                            RETURN count(*) as deleted
                        """)
                        deleted = result.single()["deleted"]
                        if deleted == 0:
                            break
                        deleted_total += deleted
                        print(f"  Deleted {deleted_total} nodes...")
                    
                    print(f"  ✓ Deleted {deleted_total} nodes total")
                else:
                    print("  Skipped data deletion")
            else:
                print("  Database already empty")
            print()
            
            # Step 4: Create new indexes with 3072 dimensions
            print("STEP 4: Create New Indexes (3072 dimensions)")
            print("-" * 50)
            
            indexes = [
                {
                    "name": "entity_embedding",
                    "query": f"""
                        CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
                        FOR (n:Entity) ON (n.embedding)
                        OPTIONS {{indexConfig: {{
                            `vector.dimensions`: {EMBEDDING_DIMENSIONS},
                            `vector.similarity_function`: 'cosine'
                        }}}}
                    """,
                    "description": "Entity embeddings (text-embedding-3-large)"
                },
                {
                    "name": "chunk_vector",
                    "query": f"""
                        CREATE VECTOR INDEX chunk_vector IF NOT EXISTS
                        FOR (n:__Node__) ON (n.embedding)
                        OPTIONS {{indexConfig: {{
                            `vector.dimensions`: {EMBEDDING_DIMENSIONS},
                            `vector.similarity_function`: 'cosine'
                        }}}}
                    """,
                    "description": "Chunk embeddings for LlamaIndex"
                },
                {
                    "name": "raptor_embedding",
                    "query": f"""
                        CREATE VECTOR INDEX raptor_embedding IF NOT EXISTS
                        FOR (r:RaptorNode) ON (r.embedding)
                        OPTIONS {{indexConfig: {{
                            `vector.dimensions`: {EMBEDDING_DIMENSIONS},
                            `vector.similarity_function`: 'cosine'
                        }}}}
                    """,
                    "description": "RAPTOR node embeddings"
                },
            ]
            
            for idx in indexes:
                try:
                    session.run(idx["query"])
                    print(f"  ✓ Created {idx['name']}: {idx['description']}")
                except Exception as e:
                    print(f"  ✗ Failed {idx['name']}: {e}")
            print()
            
            # Step 5: Create fulltext indexes for hybrid search
            print("STEP 5: Create Fulltext Indexes")
            print("-" * 50)
            
            fulltext_indexes = [
                {
                    "name": "entity_fulltext",
                    "query": """
                        CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
                        FOR (n:Entity) ON EACH [n.name, n.description]
                    """,
                    "description": "Entity name/description search"
                },
            ]
            
            for idx in fulltext_indexes:
                try:
                    session.run(idx["query"])
                    print(f"  ✓ Created {idx['name']}: {idx['description']}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  - {idx['name']} already exists")
                    else:
                        print(f"  ✗ Failed {idx['name']}: {e}")
            print()
            
            # Step 6: Verify
            print("STEP 6: Verify Setup")
            print("-" * 50)
            
            result = session.run("SHOW INDEXES")
            print("Current indexes:")
            for record in result:
                idx_name = record.get("name", "")
                idx_type = record.get("type", "")
                state = record.get("state", "")
                print(f"  {idx_name} ({idx_type}) - {state}")
            
            result = session.run("MATCH (n) RETURN count(n) as count")
            count = result.single()["count"]
            print(f"\nTotal nodes: {count}")
            
    finally:
        driver.close()
    
    print()
    print("=" * 70)
    print("CLEAN START COMPLETE")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Deploy updated service: cd graphrag-orchestration && ./deploy-simple.sh")
    print("  2. Index documents with 3072-dim embeddings")
    print("  3. Run cloud tests: pytest tests/cloud/ -v --cloud")


if __name__ == "__main__":
    main()
