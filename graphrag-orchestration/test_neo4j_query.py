import os
from neo4j import GraphDatabase

uri = os.getenv("NEO4J_URI")
username = os.getenv("NEO4J_USERNAME", "neo4j")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE", "neo4j")

driver = GraphDatabase.driver(uri, auth=(username, password))

group_id = "success-5pdfs-1765645199"

query = """
MATCH (e:Entity {group_id: $group_id})
WITH count(e) AS entities
MATCH (c:Community {group_id: $group_id})
WITH entities, count(c) AS communities
MATCH (r:RaptorNode {group_id: $group_id})
WITH entities, communities, count(r) AS raptor_nodes
MATCH (t:TextChunk {group_id: $group_id})
WITH entities, communities, raptor_nodes, count(t) AS text_chunks
MATCH (d:Document {group_id: $group_id})
WITH entities, communities, raptor_nodes, text_chunks, count(d) AS documents
OPTIONAL MATCH (:Entity {group_id: $group_id})-[rel]->(:Entity {group_id: $group_id})
RETURN entities, communities, raptor_nodes, text_chunks, documents, count(rel) AS relationships
"""

with driver.session(database=database) as session:
    result = session.run(query, group_id=group_id)
    record = result.single()
    if record:
        print(f"Stats for {group_id}:")
        print(f"  Entities: {record['entities']}")
        print(f"  Relationships: {record['relationships']}")
        print(f"  Communities: {record['communities']}")
        print(f"  Raptor nodes: {record['raptor_nodes']}")
        print(f"  Text chunks: {record['text_chunks']}")
        print(f"  Documents: {record['documents']}")

# Also check relationship types
rel_type_query = """
MATCH (:Entity {group_id: $group_id})-[r]->(:Entity {group_id: $group_id})
RETURN type(r) as rel_type, count(*) as count
ORDER BY count DESC
"""

with driver.session(database=database) as session:
    result = session.run(rel_type_query, group_id=group_id)
    print(f"\nRelationship types:")
    for record in result:
        print(f"  {record['rel_type']}: {record['count']}")

driver.close()
