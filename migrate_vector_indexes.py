#!/usr/bin/env python3
"""
Migrate vector indexes to be compatible with db.create.setVectorProperty().

This script drops and recreates vector indexes to ensure they work properly
with the Neo4j 5.x vector property API.
"""

import os
import sys
from neo4j import GraphDatabase

def migrate_vector_indexes():
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    
    if not all([uri, username, password]):
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD must be set")
        return 1
    
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    try:
        with driver.session() as session:
            print("🔍 Checking existing vector indexes...")
            result = session.run("SHOW INDEXES WHERE type = 'VECTOR'")
            indexes = [(r["name"], r["labelsOrTypes"], r["properties"]) for r in result]
            
            print(f"Found {len(indexes)} vector indexes:")
            for name, labels, props in indexes:
                print(f"  - {name}: {labels} ON {props}")
            
            # Drop existing vector indexes
            print("\n🗑️  Dropping existing vector indexes...")
            for name, _, _ in indexes:
                session.run(f"DROP INDEX {name} IF EXISTS")
                print(f"  ✓ Dropped {name}")
            
            # Recreate with correct configuration
            print("\n✨ Creating new vector indexes...")
            
            vector_indexes = [
                """
                CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
                FOR (t:TextChunk) ON (t.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 3072,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
                """
                CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
                FOR (e:Entity) ON (e.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 1536,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
                """
                CREATE VECTOR INDEX raptor_embedding IF NOT EXISTS
                FOR (r:RaptorNode) ON (r.embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 3072,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
            ]
            
            for query in vector_indexes:
                session.run(query)
                # Extract index name from query
                name = query.split("INDEX")[1].split("IF")[0].strip()
                print(f"  ✓ Created {name}")
            
            print("\n✅ Vector index migration complete!")
            print("\n⚠️  NOTE: Existing embeddings are still in the database.")
            print("   They will be automatically indexed when the vector index is created.")
            
            return 0
            
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        driver.close()

if __name__ == "__main__":
    # Load .env if it exists
    env_file = "graphrag-orchestration/.env"
    if os.path.exists(env_file):
        print(f"Loading environment from {env_file}")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
    
    sys.exit(migrate_vector_indexes())
