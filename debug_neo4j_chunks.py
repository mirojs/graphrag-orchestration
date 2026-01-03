"""Direct Neo4j query to debug chunk storage"""
from neo4j import GraphDatabase
import os

uri = os.getenv("NEO4J_URI", "neo4j+s://36a4a71f.databases.neo4j.io")
username = os.getenv("NEO4J_USERNAME", "neo4j")
password = os.getenv("NEO4J_PASSWORD")

if not password:
    print("❌ NEO4J_PASSWORD not set")
    exit(1)

driver = GraphDatabase.driver(uri, auth=(username, password))

test_group = "test-final-1767465633"

print(f"Checking Neo4j for group: {test_group}\n")

with driver.session() as session:
    # Check if chunks exist
    result = session.run("""
        MATCH (c:TextChunk {group_id: $group_id})
        RETURN c.id as id, 
               c.text as text,
               c.embedding IS NOT NULL as has_embedding,
               size(coalesce(c.embedding, [])) as embedding_size,
               c.chunk_index as chunk_index
        LIMIT 5
        """, group_id=test_group)
    
    records = list(result)
    print(f"Found {len(records)} chunks:\n")
    
    for rec in records:
        print(f"Chunk ID: {rec['id']}")
        print(f"  Text length: {len(rec['text'])} chars")
        print(f"  Has embedding: {rec['has_embedding']}")
        print(f"  Embedding size: {rec['embedding_size']} dims")
        print(f"  Text preview: {rec['text'][:150]}...")
        print()
    
    if not records:
        print("❌ No chunks found!")
        print("\nChecking if ANY chunks exist...")
        result = session.run("MATCH (c:TextChunk) RETURN count(c) as total")
        total = result.single()['total']
        print(f"Total chunks in database: {total}")

driver.close()
