"""
Check if entities in Neo4j actually have embeddings stored.
"""
import requests
import json

API_BASE = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-warnings-1766244680"

# Custom diagnostic query to check embeddings directly in Neo4j
# We'll use the search endpoint but examine what it returns

print(f"Checking group: {GROUP_ID}\n")

# Test 1: Try local search with very simple query
print("=== Test 1: Simple local search ===")
response = requests.post(
    f"{API_BASE}/graphrag/v3/query/local",
    headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
    json={"query": "Contoso", "top_k": 10, "include_sources": True}
)
result = response.json()
print(f"Status: {response.status_code}")
print(f"Entities found: {len(result.get('entities_used', []))}")
print(f"Answer: {result.get('answer', 'No answer')[:150]}")

# Test 2: Try with different query
print("\n=== Test 2: Numeric query ===")
response = requests.post(
    f"{API_BASE}/graphrag/v3/query/local",
    headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
    json={"query": "total amount invoice", "top_k": 10, "include_sources": True}
)
result = response.json()
print(f"Entities found: {len(result.get('entities_used', []))}")
print(f"Answer: {result.get('answer', 'No answer')[:150]}")

# Test 3: Global search (should work)
print("\n=== Test 3: Global search ===")
response = requests.post(
    f"{API_BASE}/graphrag/v3/query/global",
    headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
    json={"query": "What is the invoice about?", "top_k": 5}
)
result = response.json()
print(f"Communities found: {len(result.get('communities_used', []))}")
print(f"Confidence: {result.get('confidence', 0)}")
print(f"Answer: {result.get('answer', 'No answer')[:200]}")
