#!/usr/bin/env python3
"""
Initialize Neo4j V3 Schema

Creates indexes and constraints for V3 pipeline.
Run this once before indexing documents.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.v3.services.neo4j_store import Neo4jStoreV3
from dotenv import load_dotenv

load_dotenv()

async def main():
    print("=" * 70)
    print("🔧 Initializing Neo4j V3 Schema")
    print("=" * 70)
    
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_username = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
    
    print(f"\n📍 Connecting to: {neo4j_uri}")
    
    store = Neo4jStoreV3(
        uri=neo4j_uri,
        username=neo4j_username,
        password=neo4j_password,
    )
    
    print("✅ Connected to Neo4j")
    print("\n🏗️  Creating schema (indexes, constraints, vector indexes)...")
    
    try:
        store.initialize_schema()
        print("✅ Schema initialization complete!")
        
        # Verify vector indexes
        print("\n🔍 Verifying vector indexes...")
        with store.driver.session() as session:
            result = session.run("SHOW INDEXES")
            indexes = list(result)
            
            vector_indexes = [idx for idx in indexes if 'VECTOR' in str(idx.get('type', ''))]
            
            print(f"\n📊 Found {len(vector_indexes)} vector indexes:")
            for idx in vector_indexes:
                print(f"  - {idx.get('name')}: {idx.get('labelsOrTypes')} on {idx.get('properties')}")
            
            if not vector_indexes:
                print("⚠️  No vector indexes found - this may cause query failures!")
        
        print("\n✅ Neo4j V3 schema is ready!")
        
    except Exception as e:
        print(f"\n❌ Schema initialization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        store.close()

if __name__ == "__main__":
    asyncio.run(main())
