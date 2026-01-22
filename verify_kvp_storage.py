"""Verify KeyValue nodes were stored correctly in Neo4j."""
from neo4j import GraphDatabase
import os

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://b5b74e16.databases.neo4j.io")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

GROUP_ID = "test-5pdfs-1769071711867955961"

def verify_kvp_storage():
    """Verify KeyValue nodes and relationships."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Check KeyValue node count
        result = session.run("""
            MATCH (kv:KeyValue {group_id: $group_id})
            RETURN count(kv) AS count
        """, group_id=GROUP_ID)
        kv_count = result.single()["count"]
        print(f"✅ KeyValue nodes: {kv_count}")
        
        # Check sample KeyValue nodes with keys
        result = session.run("""
            MATCH (kv:KeyValue {group_id: $group_id})
            RETURN kv.key AS key, kv.value AS value, kv.confidence AS conf
            LIMIT 10
        """, group_id=GROUP_ID)
        print(f"\n📋 Sample KeyValue Pairs:")
        for record in result:
            print(f"  • {record['key']}: {record['value'][:50]}... (conf: {record['conf']:.2f})")
        
        # Check KeyValue relationships
        result = session.run("""
            MATCH (kv:KeyValue {group_id: $group_id})-[:IN_DOCUMENT]->(d:Document)
            RETURN count(DISTINCT kv) AS kv_with_doc
        """, group_id=GROUP_ID)
        kv_with_doc = result.single()["kv_with_doc"]
        print(f"\n🔗 KeyValues with [:IN_DOCUMENT]: {kv_with_doc}")
        
        result = session.run("""
            MATCH (kv:KeyValue {group_id: $group_id})-[:IN_CHUNK]->(c:TextChunk)
            RETURN count(DISTINCT kv) AS kv_with_chunk
        """, group_id=GROUP_ID)
        kv_with_chunk = result.single()["kv_with_chunk"]
        print(f"🔗 KeyValues with [:IN_CHUNK]: {kv_with_chunk}")
        
        result = session.run("""
            MATCH (kv:KeyValue {group_id: $group_id})-[:IN_SECTION]->(s:Section)
            RETURN count(DISTINCT kv) AS kv_with_section
        """, group_id=GROUP_ID)
        kv_with_section = result.single()["kv_with_section"]
        print(f"🔗 KeyValues with [:IN_SECTION]: {kv_with_section}")
        
        # Check key embeddings
        result = session.run("""
            MATCH (kv:KeyValue {group_id: $group_id})
            WHERE kv.key_embedding IS NOT NULL
            RETURN count(kv) AS with_embedding
        """, group_id=GROUP_ID)
        with_embedding = result.single()["with_embedding"]
        print(f"\n🧠 KeyValues with key embeddings: {with_embedding}")
        
        # Check unique keys
        result = session.run("""
            MATCH (kv:KeyValue {group_id: $group_id})
            RETURN count(DISTINCT toLower(kv.key)) AS unique_keys
        """, group_id=GROUP_ID)
        unique_keys = result.single()["unique_keys"]
        print(f"🔑 Unique keys (case-insensitive): {unique_keys}")
        
        # Check documents with KVPs
        result = session.run("""
            MATCH (d:Document {group_id: $group_id})<-[:IN_DOCUMENT]-(kv:KeyValue)
            RETURN d.filename AS doc, count(kv) AS kvp_count
            ORDER BY kvp_count DESC
        """, group_id=GROUP_ID)
        print(f"\n📄 KeyValue distribution by document:")
        for record in result:
            print(f"  • {record['doc']}: {record['kvp_count']} KVPs")
    
    driver.close()
    print(f"\n✅ KeyValue storage verification complete!")

if __name__ == "__main__":
    verify_kvp_storage()
