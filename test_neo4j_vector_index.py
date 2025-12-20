"""
Test Neo4j vector index directly using raw Cypher query.
"""
from neo4j import GraphDatabase
import os

# Connect to Neo4j
driver = GraphDatabase.driver(
    "neo4j+s://a86dcf63.databases.neo4j.io",
    auth=("neo4j", os.getenv("NEO4J_PASSWORD", ""))
)

GROUP_ID = "test-diag-1766245406"

with driver.session(database="neo4j") as session:
    # Check if entities exist with embeddings
    print("=== Check 1: Do entities exist with embeddings? ===")
    result = session.run("""
        MATCH (e:Entity {group_id: $group_id})
        RETURN count(e) as total,
               count(e.embedding) as with_embedding,
               size(head(collect(e.embedding))) as embedding_dim
        LIMIT 1
    """, group_id=GROUP_ID)
    
    record = result.single()
    if record:
        print(f"Total entities: {record['total']}")
        print(f"With embeddings: {record['with_embedding']}")
        print(f"Embedding dimensions: {record['embedding_dim']}")
    
    # Check if vector index exists
    print("\n=== Check 2: Does vector index exist? ===")
    result = session.run("SHOW INDEXES")
    for record in result:
        if 'entity_embedding' in str(record.get('name', '')):
            print(f"Found index: {record}")
    
    # Try vector search directly
    print("\n=== Check 3: Try vector search directly ===")
    # Get a sample entity embedding to use as query
    result = session.run("""
        MATCH (e:Entity {group_id: $group_id})
        WHERE e.embedding IS NOT NULL
        RETURN e.embedding as emb
        LIMIT 1
    """, group_id=GROUP_ID)
    
    record = result.single()
    if record and record['emb']:
        sample_emb = record['emb']
        print(f"Got sample embedding with {len(sample_emb)} dimensions")
        
        # Try vector search
        try:
            result = session.run("""
                CALL db.index.vector.queryNodes('entity_embedding', 5, $embedding)
                YIELD node, score
                RETURN node.name as name, node.group_id as group_id, score
                LIMIT 5
            """, embedding=sample_emb)
            
            print("Vector search results:")
            for record in result:
                print(f"  - {record['name']} (group: {record['group_id']}, score: {record['score']:.3f})")
        except Exception as e:
            print(f"Vector search failed: {e}")

driver.close()
