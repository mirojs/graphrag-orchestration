#!/usr/bin/env python3
"""Simple PDF URL test matching working v3 pattern"""
import requests
import sys
import time

BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
TEST_GROUP_ID = f"pdf-url-test-{int(time.time())}"

# Single PDF URL (with fresh SAS - replace with actual token)
PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf?se=2025-12-25T06%3A03Z&sp=r&sv=2022-11-02&sr=b&skoid=ddd5567a-7d84-4703-bbdb-aa00b3b95bd8&sktid=ecaa729a-f04c-4558-a31a-ab714740ee8b&skt=2025-12-18T06%3A03%3A37Z&ske=2025-12-25T06%3A03%3A00Z&sks=b&skv=2022-11-02&sig=oSc7TvC%2Bzh2WieNq2l%2BaDlGg1fOb3hx7EWWACgyGjWQ%3D"
]

print(f"\nTesting PDF URL ingestion with Document Intelligence")
print(f"Group ID: {TEST_GROUP_ID}")
print(f"URL: {PDF_URLS[0][:80]}...\n")

try:
    response = requests.post(
        f"{BASE_URL}/graphrag/v3/index",
        headers={
            'Content-Type': 'application/json',
            'X-Group-ID': TEST_GROUP_ID
        },
        json={
            "documents": PDF_URLS,
            "ingestion": "document-intelligence",
            "run_raptor": True,
            "run_community_detection": True
        },
        timeout=180
    )
    
    print(f"Response: HTTP {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Success!")
        print(f"  Documents: {result.get('documents_processed', 0)}")
        print(f"  Entities: {result.get('entities_created', 0)}")
        print(f"  Relationships: {result.get('relationships_created', 0)}")
        print(f"  Communities: {result.get('communities_created', 0)}")
        sys.exit(0)
    else:
        print(f"❌ Failed")
        print(response.text[:500])
        sys.exit(1)
        
except requests.Timeout:
    print(f"❌ Timeout after 180s")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
