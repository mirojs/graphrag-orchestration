import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    'neo4j+s://a86dcf63.databases.neo4j.io',
    auth=('neo4j', os.getenv('NEO4J_PASSWORD')),
    database='neo4j'
)

with driver.session() as session:
    # Check vector indices
    print("Vector indices:")
    result = session.run("SHOW VECTOR INDEXES")
    for record in result:
        print(f"  {record}")
    
    print("\nFulltext indices:")
    result = session.run("SHOW FULLTEXT INDEXES")
    for record in result:
        print(f"  {record}")
    
    # Check if entities have embeddings
    print("\nEntity embedding status:")
    result = session.run("""
        MATCH (e:Entity {group_id: $group_id})
        RETURN 
            count(e) as total,
            count(e.embedding) as with_embedding,
            head(collect(e.embedding))[0] as sample_first_value
        LIMIT 1
    """, group_id='phase1-5docs-1766235543')
    for record in result:
        print(f"  Total entities: {record['total']}")
        print(f"  With embeddings: {record['with_embedding']}")
        print(f"  Sample first value: {record['sample_first_value']}")

driver.close()
