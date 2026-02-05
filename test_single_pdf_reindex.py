"""
Test: Index a single PDF and verify chunks contain expected values
"""
import asyncio
import requests
import time

BASE_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
TEST_GROUP = f"test-invoice-debug-{int(time.time())}"

PDF_URL = "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf"

print(f"Test Group: {TEST_GROUP}")
print(f"PDF: {PDF_URL}")
print("="*60)

# Step 1: Index the single PDF
print("\n1. Indexing PDF...")
response = requests.post(
    f"{BASE_URL}/hybrid/index/documents",
    headers={"X-Group-ID": TEST_GROUP},
    json={
        "documents": [PDF_URL]
    }
)

if response.status_code != 200:
    print(f"❌ Indexing failed: {response.status_code}")
    print(response.text[:500])
    exit(1)

result = response.json()
print(f"✅ Indexing completed")
print(f"   Documents: {result.get('documents_processed', 0)}")
print(f"   Chunks: {result.get('chunks_created', 0)}")

# Step 2: Query for the P.O. NUMBER
print("\n2. Querying for P.O. NUMBER...")
time.sleep(2)  # Give it a moment to complete

response = requests.post(
    f"{BASE_URL}/hybrid/query",
    headers={"X-Group-ID": TEST_GROUP},
    json={
        "query": "What is the P.O. NUMBER?",
        "search_type": "hybrid",
        "top_k": 5
    }
)

if response.status_code == 200:
    result = response.json()
    citations = result.get('citations', [])
    answer = result.get('answer', '')
    
    print(f"   Retrieved {len(citations)} citations")
    print(f"   Answer: {answer[:200]}")
    
    # Check citations for 30060204
    found = False
    for i, cit in enumerate(citations):
        text = cit.get('text', '')
        if '30060204' in text:
            found = True
            print(f"\n✅ FOUND '30060204' in citation {i+1}:")
            print(f"   Text length: {len(text)} chars")
            idx = text.find('30060204')
            print(f"   Context: ...{text[max(0,idx-100):min(len(text),idx+100)]}...")
            break
    
    if not found:
        print(f"\n❌ '30060204' NOT FOUND in any citations")
        print(f"\nFirst citation text:")
        if citations:
            print(citations[0].get('text', '')[:500])
else:
    print(f"❌ Query failed: {response.status_code}")

print(f"\n{'='*60}")
print(f"Test group for cleanup: {TEST_GROUP}")
