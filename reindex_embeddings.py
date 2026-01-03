#!/usr/bin/env python3
"""
Reindex all chunk embeddings using db.create.setVectorProperty().

This ensures embeddings are properly indexed in the vector index.
"""

import os
import sys
from neo4j import GraphDatabase

def reindex_embeddings():
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    
    if not all([uri, username, password]):
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD must be set")
        return 1
    
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    try:
        with driver.session() as session:
            # Count chunks with embeddings
            result = session.run("""
                MATCH (c:TextChunk)
                WHERE c.embedding IS NOT NULL
                RETURN count(c) as total
                """)
            total = result.single()['total']
            print(f"🔍 Found {total} chunks with embeddings")
            
            if total == 0:
                print("No chunks to reindex")
                return 0
            
            print("\n⚙️  Reindexing embeddings using db.create.setVectorProperty()...")
            
            # Process in batches
            batch_size = 100
            for offset in range(0, total, batch_size):
                result = session.run("""
                    MATCH (c:TextChunk)
                    WHERE c.embedding IS NOT NULL
                    WITH c
                    SKIP $offset
                    LIMIT $batch_size
                    WITH c, c.embedding as old_embedding
                    CALL db.create.setVectorProperty(c, 'embedding', old_embedding)
                    YIELD node
                    RETURN count(node) as updated
                    """, offset=offset, batch_size=batch_size)
                
                updated = result.single()['updated']
                progress = min(offset + batch_size, total)
                print(f"  Progress: {progress}/{total} chunks reindexed")
            
            print(f"\n✅ Reindexed {total} chunk embeddings!")
            
            # Test vector search
            print("\n🧪 Testing vector search...")
            result = session.run("""
                MATCH (c:TextChunk)
                WHERE c.embedding IS NOT NULL
                WITH c LIMIT 1
                CALL db.index.vector.queryNodes('chunk_embedding', 5, c.embedding)
                YIELD node, score
                RETURN node.id as id, score
                ORDER BY score DESC
                """)
            
            results = list(result)
            print(f"  Found {len(results)} results")
            if results:
                print("  ✅ Vector search is working!")
                for r in results[:3]:
                    print(f"    - {r['id'][:50]}: score={r['score']:.4f}")
            else:
                print("  ❌ Vector search still returning 0 results")
            
            return 0
            
    except Exception as e:
        print(f"\n❌ Reindexing failed: {e}")
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
    
    sys.exit(reindex_embeddings())
