"""
Fix RAPTOR vector index dimension mismatch using Neo4j HTTP API.
No neo4j package required - uses REST API directly.
"""
import requests
import json
import base64

def main():
    # Neo4j Aura connection details
    host = "3a8f50d9.databases.neo4j.io"
    username = "neo4j"
    password = "Cbu7xPlVn9qNSSK_yiZkFcW2tWF_IblWAJbPmSrMOJg"
    database = "neo4j"
    
    # Neo4j HTTP API endpoint
    url = f"https://{host}/db/{database}/tx/commit"
    
    # Basic auth header
    auth_string = f"{username}:{password}"
    auth_bytes = auth_string.encode('ascii')
    base64_bytes = base64.b64encode(auth_bytes)
    base64_auth = base64_bytes.decode('ascii')
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {base64_auth}"
    }
    
    # Step 1: Drop the old index
    print("🗑️  Dropping raptor_embedding index...")
    payload = {
        "statements": [
            {"statement": "DROP INDEX raptor_embedding IF EXISTS"}
        ]
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print("✅ Dropped")
    else:
        print(f"⚠️  Response: {response.status_code} - {response.text[:200]}")
    
    # Step 2: Delete all RAPTOR nodes for test-3072-fresh
    print("\n🗑️  Deleting RAPTOR nodes for test-3072-fresh...")
    payload = {
        "statements": [
            {
                "statement": 'MATCH (r:RaptorNode {group_id: "test-3072-fresh"}) DELETE r RETURN count(*) as deleted'
            }
        ]
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        result = response.json()
        if result.get("results") and result["results"][0].get("data"):
            deleted = result["results"][0]["data"][0]["row"][0]
            print(f"✅ Deleted {deleted} RAPTOR nodes")
        else:
            print("✅ Query executed (0 nodes found)")
    else:
        print(f"⚠️  Response: {response.status_code} - {response.text[:200]}")
    
    # Step 3: Recreate the index with 3072 dimensions
    print("\n🔧 Creating raptor_embedding index with 3072 dimensions...")
    payload = {
        "statements": [
            {
                "statement": """
                    CREATE VECTOR INDEX raptor_embedding IF NOT EXISTS
                    FOR (r:RaptorNode) ON (r.embedding)
                    OPTIONS {indexConfig: {
                        `vector.dimensions`: 3072,
                        `vector.similarity_function`: 'cosine'
                    }}
                """
            }
        ]
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print("✅ Created")
    else:
        print(f"⚠️  Response: {response.status_code} - {response.text[:200]}")
    
    print("\n✅ All done! Now run: python test_managed_identity_pdfs.py")
    print("   This will create new RAPTOR nodes with 3072-dim embeddings.")

if __name__ == "__main__":
    main()
