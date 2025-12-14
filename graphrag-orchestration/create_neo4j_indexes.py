"""
Create Neo4j indexes for multi-tenant GraphRAG performance.

Run this script once after deploying Neo4j to create indexes
that optimize query performance for many small tenant datasets.

Usage:
    python create_neo4j_indexes.py
"""

import sys
import os
from typing import Any
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load environment variables
load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def create_indexes() -> None:
    """Create all required indexes for multi-tenant performance."""
    
    if not NEO4J_URI or not NEO4J_USERNAME or not NEO4J_PASSWORD:
        print("❌ Error: Neo4j credentials not configured in .env")
        sys.exit(1)
    
    # Type narrowing: after the check above, these are guaranteed to be str
    uri: str = NEO4J_URI
    username: str = NEO4J_USERNAME
    password: str = NEO4J_PASSWORD
    
    driver = GraphDatabase.driver(
        uri,
        auth=(username, password)
    )
    
    try:
        driver.verify_connectivity()
        print(f"✅ Connected to Neo4j at {uri}")
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        sys.exit(1)
    
    indexes = [
        {
            "name": "group_id_idx",
            "query": "CREATE INDEX group_id_idx IF NOT EXISTS FOR (n:__Node__) ON (n.group_id)",
            "description": "Index on group_id for tenant isolation",
        },
        {
            "name": "url_idx",
            "query": "CREATE INDEX url_idx IF NOT EXISTS FOR (n:__Node__) ON (n.url)",
            "description": "Index on url for document lookups",
        },
        {
            "name": "tenant_document_idx",
            "query": "CREATE INDEX tenant_document_idx IF NOT EXISTS FOR (n:__Node__) ON (n.group_id, n.url)",
            "description": "Composite index for tenant + document lookups",
        },
        {
            "name": "entity_name_idx",
            "query": "CREATE INDEX entity_name_idx IF NOT EXISTS FOR (n:Entity) ON (n.name)",
            "description": "Index on entity names for relationship queries",
        },
        {
            "name": "entity_embedding",
            "query": "CREATE VECTOR INDEX entity_embedding IF NOT EXISTS FOR (n:Entity) ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 3072, `vector.similarity_function`: 'cosine'}}",
            "description": "Vector index for entity embeddings",
        },
        {
            "name": "chunk_vector",
            "query": "CREATE VECTOR INDEX chunk_vector IF NOT EXISTS FOR (n:__Node__) ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
            "description": "Vector index for chunk embeddings",
        },
    ]
    
    with driver.session() as session:
        print("\n📊 Creating indexes...")
        
        for idx in indexes:
            try:
                # type: ignore needed for neo4j driver's LiteralString requirement
                session.run(idx["query"])  # type: ignore[arg-type]
                print(f"  ✓ {idx['name']}: {idx['description']}")
            except Exception as e:
                print(f"  ⚠ {idx['name']}: {e}")
        
        # Verify indexes were created
        print("\n📋 Listing all indexes...")
        result = session.run("SHOW INDEXES")
        for record in result:
            print(f"  • {record.get('name', 'unnamed')}: {record.get('labelsOrTypes', [])} ON {record.get('properties', [])}")
    
    driver.close()
    print("\n✅ Index creation complete!")


if __name__ == "__main__":
    create_indexes()
