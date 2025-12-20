"""
Check if entities in Neo4j have embeddings populated.
"""

import neo4j
import os

GROUP_ID = "phase1-5docs-1766238684"

# Connect to Neo4j with hardcoded values from .env
driver = neo4j.GraphDatabase.driver(
    "neo4j+s://a86dcf63.databases.neo4j.io",
    auth=("neo4j", os.getenv("NEO4J_PASSWORD", ""))
)

with driver.session(database="neo4j") as session:
    # Check entities with embeddings
    result = session.run("""
        MATCH (e:Entity {group_id: $group_id})
        RETURN 
            count(e) as total_entities,
            count(e.embedding) as entities_with_embedding,
            size(head(collect(e.embedding))) as embedding_dim
        """, group_id=GROUP_ID)
    
    record = result.single()
    print(f"\n📊 Entity Embedding Check for group: {GROUP_ID}")
    print(f"   Total entities: {record['total_entities']}")
    print(f"   Entities with embeddings: {record['entities_with_embedding']}")
    print(f"   Embedding dimensions: {record['embedding_dim']}")
    
    if record['entities_with_embedding'] == 0:
        print("\n❌ NO ENTITIES HAVE EMBEDDINGS!")
        print("   This explains why local search returns 0 results.")
    elif record['entities_with_embedding'] < record['total_entities']:
        print(f"\n⚠️  Only {record['entities_with_embedding']}/{record['total_entities']} entities have embeddings")
    else:
        print("\n✅ All entities have embeddings!")
    
    # Sample a few entities
    result = session.run("""
        MATCH (e:Entity {group_id: $group_id})
        RETURN e.name, e.type, e.embedding IS NOT NULL as has_embedding
        LIMIT 5
        """, group_id=GROUP_ID)
    
    print("\n📝 Sample entities:")
    for record in result:
        status = "✅" if record['has_embedding'] else "❌"
        print(f"   {status} {record['e.name']} ({record['e.type']})")

driver.close()
