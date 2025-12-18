#!/usr/bin/env python3
"""Simple v3 test - plain text documents"""
import requests
import time

BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = f"test-{int(time.time())}"

print(f"\n{'='*80}")
print("Testing v3/index with plain text")
print(f"{'='*80}\n")
print(f"Group: {GROUP_ID}")

docs = [
    "Invoice from Contoso Lifts. Elevator service $5000.",
    "Contract between ABC Corp and Contoso Lifts. Elevator X200, $75000, warranty 2 years."
]

print(f"Sending {len(docs)} documents...")
start = time.time()

response = requests.post(
    f"{BASE_URL}/graphrag/v3/index",
    headers={'X-Group-ID': GROUP_ID},
    json={"documents": docs},
    timeout=120
)

elapsed = time.time() - start
print(f"Response: HTTP {response.status_code} in {elapsed:.1f}s")

if response.status_code == 200:
    result = response.json()
    print(f"\n✅ Success!")
    print(f"  Documents: {result.get('documents_processed', 0)}")
    print(f"  Entities: {result.get('entities_created', 0)}")
    print(f"  Relationships: {result.get('relationships_created', 0)}")
else:
    print(f"\n❌ Failed: {response.text[:200]}")
