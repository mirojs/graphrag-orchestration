#!/usr/bin/env python3
"""
Non-interactive Neo4j cleanup script.

Run with:
    export NEO4J_PASSWORD="your_neo4j_password"
    python scripts/clean_neo4j_noninteractive.py [--confirm-delete]

Without --confirm-delete, only shows what would be deleted.
With --confirm-delete, actually deletes data and recreates indexes.
"""

import argparse
import os
import sys

from neo4j import GraphDatabase


# Configuration
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# 3072 dimensions for text-embedding-3-large
EMBEDDING_DIMENSIONS = 3072


def main():
    parser = argparse.ArgumentParser(description="Clean Neo4j database for fresh start")
    parser.add_argument("--confirm-delete", action="store_true", 
                       help="Actually delete data (without this flag, just shows what would be deleted)")
    args = parser.parse_args()
    
    if not NEO4J_PASSWORD:
        print("ERROR: NEO4J_PASSWORD environment variable not set")
        print("  export NEO4J_PASSWORD='your_password'")
        sys.exit(1)
    
    print("=" * 70)
    print("NEO4J CLEAN START SCRIPT")
    print("=" * 70)
    print(f"URI:      {NEO4J_URI}")
    print(f"Database: {NEO4J_DATABASE}")
    print(f"Mode:     {'DELETE MODE' if args.confirm_delete else 'DRY RUN (use --confirm-delete to actually delete)'}")
    print(f"Embedding Dimensions: {EMBEDDING_DIMENSIONS}")
    print("=" * 70)
    print()
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            # Step 1: Show current data
            print("📊 CURRENT DATA SUMMARY")
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
                print(f"  {label}: {count:,}")
            print(f"  TOTAL: {total_nodes:,}")
            print()
            
            # Count by group_id
            print("📁 DATA BY GROUP ID")
            print("-" * 50)
            result = session.run("""
                MATCH (n) WHERE n.group_id IS NOT NULL 
                RETURN n.group_id as group_id, count(n) as count 
                ORDER BY count DESC LIMIT 20
            """)
            groups = list(result)
            if groups:
                for record in groups:
                    print(f"  {record['group_id']}: {record['count']:,}")
            else:
                print("  No group_id data found")
            print()
            
            # List current indexes
            print("📋 CURRENT INDEXES")
            print("-" * 50)
            result = session.run("SHOW INDEXES")
            vector_indexes = []
            for record in result:
                idx_name = record.get("name", "")
                idx_type = record.get("type", "")
                state = record.get("state", "")
                if idx_type == "VECTOR":
                    vector_indexes.append(idx_name)
                print(f"  {idx_name} ({idx_type}) - {state}")
            print()
            
            if not args.confirm_delete:
                print("⚠️  DRY RUN MODE - No changes made")
                print("    Run with --confirm-delete to actually delete data")
                print()
                return
            
            # Step 2: Drop vector indexes
            print("🗑️  DROPPING VECTOR INDEXES")
            print("-" * 50)
            
            for idx_name in vector_indexes:
                try:
                    session.run(f"DROP INDEX {idx_name}")
                    print(f"  ✓ Dropped {idx_name}")
                except Exception as e:
                    print(f"  ✗ Failed to drop {idx_name}: {e}")
            print()
            
            # Step 3: Delete all data
            print("🗑️  DELETING ALL DATA")
            print("-" * 50)
            
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
                print(f"  Deleted {deleted_total:,} nodes...")
            
            print(f"  ✓ Deleted {deleted_total:,} nodes total")
            print()
            
            # Step 4: Create new indexes with 3072 dimensions
            print("🔧 CREATING NEW INDEXES (3072 dims)")
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
            
            # Step 5: Create fulltext indexes
            print("🔧 CREATING FULLTEXT INDEXES")
            print("-" * 50)
            
            try:
                session.run("""
                    CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
                    FOR (n:Entity) ON EACH [n.name, n.description]
                """)
                print("  ✓ Created entity_fulltext")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print("  - entity_fulltext already exists")
                else:
                    print(f"  ✗ Failed entity_fulltext: {e}")
            print()
            
            # Step 6: Verify
            print("✅ VERIFICATION")
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
    print("✅ CLEAN START COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
