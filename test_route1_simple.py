#!/usr/bin/env python3
"""Simple test to verify Route 1 is accessible and responding."""
import json
import urllib.request
import time

URL = "https://graphrag-orchestration.proudisland-64e79ab7.eastus.azurecontainerapps.io/hybrid/query"
GROUP_ID = "test-5pdfs-1769071711867955961"

payload = {
    "query": "What is the invoice total?",
    "force_route": "vector_rag",
    "response_type": "summary"
}

headers = {
    "Content-Type": "application/json",
    "X-Group-ID": GROUP_ID
}

print(f"Testing Route 1 at: {URL}")
print(f"Group ID: {GROUP_ID}")
print(f"Query: {payload['query']}")
print("-" * 80)

data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(URL, data=data, method='POST')
for k, v in headers.items():
    req.add_header(k, v)

try:
    start = time.time()
    with urllib.request.urlopen(req, timeout=60) as response:
        elapsed = time.time() - start
        body = response.read().decode('utf-8')
        result = json.loads(body)
        
        print(f"✅ SUCCESS ({elapsed:.2f}s)")
        print(f"\nStatus: {response.status}")
        print(f"\nAnswer ({len(result.get('answer', ''))} chars):")
        print(result.get('answer', 'N/A')[:500])
        
        if 'sources' in result:
            print(f"\n\nSources: {len(result['sources'])}")
            for i, src in enumerate(result['sources'][:3], 1):
                print(f"  {i}. {src.get('id', 'N/A')}")
                
except urllib.error.HTTPError as e:
    print(f"❌ HTTP Error {e.code}")
    try:
        print(e.read().decode('utf-8'))
    except:
        print(str(e))
except Exception as e:
    print(f"❌ Error: {e}")
