#!/usr/bin/env python3
"""
GraphRAG v3 - PDF Batch Test (Cloud URLs)
Uses exact pattern from test_managed_identity.py
"""
import requests
import json
import sys
import time

BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
TEST_GROUP_ID = f"pdf-batch-{int(time.time())}"

# PDF URLs from storage (pass directly as strings)
PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf?se=2025-12-25T06%3A03Z&sp=r&sv=2022-11-02&sr=b&skoid=ddd5567a-7d84-4703-bbdb-aa00b3b95bd8&sktid=ecaa729a-f04c-4558-a31a-ab714740ee8b&skt=2025-12-18T06%3A03%3A37Z&ske=2025-12-25T06%3A03%3A00Z&sks=b&skv=2022-11-02&sig=oSc7TvC%2Bzh2WieNq2l%2BaDlGg1fOb3hx7EWWACgyGjWQ%3D",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf?se=2025-12-25T06%3A03Z&sp=r&sv=2022-11-02&sr=b&skoid=ddd5567a-7d84-4703-bbdb-aa00b3b95bd8&sktid=ecaa729a-f04c-4558-a31a-ab714740ee8b&skt=2025-12-18T06%3A03%3A37Z&ske=2025-12-25T06%3A03%3A00Z&sks=b&skv=2022-11-02&sig=oSc7TvC%2Bzh2WieNq2l%2BaDlGg1fOb3hx7EWWACgyGjWQ%3D",
]

TEST_QUERIES = [
    "What are the payment terms and amounts?",
    "What companies are involved?"
]

print(f"\n{'=' * 80}")
print(f"  GraphRAG v3 - PDF Batch Test")
print(f"{'=' * 80}\n")

# Step 1: Index PDFs
print(f"📄 Indexing {len(PDF_URLS)} PDFs...")
print(f"Group ID: {TEST_GROUP_ID}\n")

start = time.time()
try:
    response = requests.post(
        f"{BASE_URL}/graphrag/v3/index",
        headers={
            'Content-Type': 'application/json',
            'X-Group-ID': TEST_GROUP_ID
        },
        json={
            "documents": PDF_URLS,
            "ingestion": "document-intelligence"
        },
        timeout=180
    )
    
    elapsed = time.time() - start
    result = response.json()
    
    if response.status_code == 200:
        print(f"✅ Indexing completed in {elapsed:.1f}s")
        print(f"  Documents: {result.get('documents_processed', 0)}")
        print(f"  Entities: {result.get('entities_created', 0)}")
        print(f"  Relationships: {result.get('relationships_created', 0)}")
        print(f"  Communities: {result.get('communities_created', 0)}")
    else:
        print(f"❌ Failed with HTTP {response.status_code}")
        print(json.dumps(result, indent=2))
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)

# Step 2: Wait for propagation
print("\n⏳ Waiting 3s for Neo4j propagation...")
time.sleep(3)

# Step 3: Test queries
print(f"\n🔍 Testing {len(TEST_QUERIES)} queries...\n")
for i, query in enumerate(TEST_QUERIES, 1):
    print(f"[{i}/{len(TEST_QUERIES)}] {query}")
    try:
        response = requests.post(
            f"{BASE_URL}/graphrag/v3/query/drift",
            headers={'X-Group-ID': TEST_GROUP_ID},
            json={"query": query},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get('answer', '')[:200]
            print(f"  ✅ {answer}...\n")
        else:
            print(f"  ❌ HTTP {response.status_code}\n")
    except Exception as e:
        print(f"  ❌ {e}\n")

print(f"{'=' * 80}")
print("✅ Test complete")
print(f"{'=' * 80}\n")
