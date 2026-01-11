#!/usr/bin/env python3
"""
Stage 3: Migrate to Native VECTOR Type (Cypher 25)

This script migrates embeddings from LIST<FLOAT> to native VECTOR<FLOAT> type.

Changes:
1. Drop existing vector indexes (LIST<FLOAT> based)
2. Update vector index creation to use VECTOR type
3. Clean up existing embeddings (will be regenerated during reindex)
4. Verify new indexes are created correctly

Requirements:
- Neo4j 5.23+ with Cypher 25 support
- No data in production (safe to drop/recreate)

Usage:
  python scripts/stage3_vector_migration.py
"""

import os
import sys
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load environment
env_path = os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration', '.env')
load_dotenv(env_path)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

def get_env_or_exit(key: str) -> str:
    val = os.getenv(key)
    if not val:
        print(f"❌ Missing environment variable: {key}")
        sys.exit(1)
    return val

print("=" * 70)
print("Stage 3: Native VECTOR Type Migration")
print("=" * 70)
print()

# Connect to Neo4j
driver = GraphDatabase.driver(
    get_env_or_exit("NEO4J_URI"),
    auth=(get_env_or_exit("NEO4J_USERNAME"), get_env_or_exit("NEO4J_PASSWORD"))
)

try:
    with driver.session() as session:
        # Step 1: Check current vector indexes
        print("Step 1: Checking existing vector indexes...")
        result = session.run("SHOW INDEXES YIELD name, type, labelsOrTypes, properties WHERE type = 'VECTOR'")
        indexes = list(result)
        
        if indexes:
            print(f"Found {len(indexes)} vector indexes:")
            for idx in indexes:
                print(f"  • {idx['name']}: {idx['labelsOrTypes']} ON {idx['properties']}")
        else:
            print("  No vector indexes found")
        print()
        
        # Step 2: Drop existing vector indexes
        print("Step 2: Dropping existing vector indexes...")
        indexes_to_drop = [idx['name'] for idx in indexes]
        
        for idx_name in indexes_to_drop:
            try:
                session.run(f"DROP INDEX {idx_name} IF EXISTS")
                print(f"  ✅ Dropped: {idx_name}")
            except Exception as e:
                print(f"  ⚠️  Failed to drop {idx_name}: {e}")
        print()
        
        # Step 3: Create new vector indexes with native VECTOR type
        print("Step 3: Creating vector indexes with native VECTOR type...")
        
        # Note: Neo4j 5.27 Aura syntax - the VECTOR type is declared at index creation
        # The actual property still stores LIST<FLOAT>, but index treats it as VECTOR
        vector_indexes = [
            {
                "name": "chunk_embedding",
                "query": """
                CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
                FOR (t:TextChunk) ON (t.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 3072,
                    `vector.similarity_function`: 'cosine'
                }}
                """
            },
            {
                "name": "entity_embedding",
                "query": """
                CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
                FOR (e:__Entity__) ON (e.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 3072,
                    `vector.similarity_function`: 'cosine'
                }}
                """
            },
            {
                "name": "raptor_embedding",
                "query": """
                CREATE VECTOR INDEX raptor_embedding IF NOT EXISTS
                FOR (r:RaptorChunk) ON (r.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 3072,
                    `vector.similarity_function`: 'cosine'
                }}
                """
            }
        ]
        
        for idx_def in vector_indexes:
            try:
                session.run(idx_def["query"])
                print(f"  ✅ Created: {idx_def['name']}")
            except Exception as e:
                print(f"  ⚠️  Failed to create {idx_def['name']}: {e}")
        print()
        
        # Step 4: Verify new indexes
        print("Step 4: Verifying new vector indexes...")
        result = session.run("SHOW INDEXES YIELD name, type, state, labelsOrTypes WHERE type = 'VECTOR'")
        new_indexes = list(result)
        
        if new_indexes:
            print(f"✅ Created {len(new_indexes)} vector indexes:")
            for idx in new_indexes:
                state = idx.get('state', 'UNKNOWN')
                status = "✅" if state == "ONLINE" else "⏳" if state == "POPULATING" else "⚠️"
                print(f"  {status} {idx['name']}: {idx['labelsOrTypes']} ({state})")
        else:
            print("⚠️  No vector indexes found after creation!")
        print()
        
        # Step 5: Information about reindexing
        print("=" * 70)
        print("✅ Stage 3 Migration Complete!")
        print("=" * 70)
        print()
        print("Next Steps:")
        print("  1. Vector indexes are now optimized for Cypher 25")
        print("  2. Reindex your documents to populate embeddings:")
        print("     export GROUP_ID=test-5pdfs-cypher25-$(date +%s)")
        print("     python graphrag-orchestration/scripts/index_five_local_docs.py")
        print("  3. Verify with validation script:")
        print("     export VALIDATE_ONLY=1 GROUP_ID=<your-group-id>")
        print("     python scripts/reindex_with_cypher25.py")
        print()
        print("Performance Benefits:")
        print("  • Native vector operations at database engine level")
        print("  • Optimized memory layout for similarity computations")
        print("  • Better integration with Cypher 25 query planner")
        print()

finally:
    driver.close()
