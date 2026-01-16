
import os
import neo4j
from dotenv import load_dotenv

load_dotenv()

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

def get_group_id():
    # Mirrored logic from benchmark script
    env = os.getenv("TEST_GROUP_ID") or os.getenv("GROUP_ID")
    if env:
        return env
    try:
        with open("last_test_group_id.txt", "r") as f:
            return f.read().strip()
    except:
        return "test-5pdfs-latest"

GROUP_ID = get_group_id()

def check_purchase_contract():
    driver = neo4j.GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    
    # Check what groups actually exist
    print("--- Available Groups ---")
    with driver.session() as session:
        result = session.run("MATCH (d:Document) RETURN DISTINCT d.group_id AS gid, count(d) as count LIMIT 10")
        for r in result:
             print(f"Group: {r['gid']} (Docs: {r['count']})")
             
    print(f"\nDEBUG: Using Group ID: local-test (overriding {GROUP_ID} since it doesn't exist)")


    
    query = """
    MATCH (d:Document {group_id: $group_id})
    RETURN d.id, d.title, d.source, d.name, 
           properties(d) as all_props
    LIMIT 20
    """
    
    with driver.session() as session:
        result = session.run(query, group_id="local-test")
        found = False
        for record in result:
            found = True
            print(f"\n--- Document ---")
            print(f"ID: {record['d.id']}")
            print(f"Title: {record['d.title']}")
            print(f"Name: {record['d.name']}")
            print(f"Source: {record['d.source']}")
            print(f"All Properties: {record['all_props']}")
            
            # Check content for date 
            chunk_query = """
            MATCH (d:Document {id: $doc_id})<-[:PART_OF]-(c:TextChunk)
            WHERE c.text CONTAINS "2025" OR c.text CONTAINS "04/30"
            RETURN c.text, c.chunk_index
            LIMIT 2
            """
            chunks = session.run(chunk_query, doc_id=record['d.id'])
            for c in chunks:
                snippet = c['c.text'][:100].replace('\n', ' ')
                print(f"  > Chunk {c['c.chunk_index']}: {snippet}...")
                if "04/30/2025" in c['c.text']:
                    print("    >>> FOUND TARGET DATE 04/30/2025!")

        if not found:
            print("No documents found in group.")


    driver.close()

if __name__ == "__main__":
    check_purchase_contract()
