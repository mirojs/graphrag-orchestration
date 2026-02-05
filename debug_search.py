"""
Debug script to check entity embeddings and search directly.
"""
import requests
import json

API_BASE = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "phase1-5docs-1766238684"

# Test 1: Check health
print("=== Test 1: Health Check ===")
response = requests.get(f"{API_BASE}/health")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")

# Test 2: Try to get group stats
print("\n=== Test 2: Group Stats ===")
try:
    response = requests.get(
        f"{API_BASE}/graphrag/v3/groups/{GROUP_ID}/stats",
        headers={"X-Group-ID": GROUP_ID}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    else:
        print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")

# Test 3: Try local search with debug
print("\n=== Test 3: Local Search ===")
response = requests.post(
    f"{API_BASE}/graphrag/v3/query/local",
    headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
    json={"query": "Contoso", "top_k": 10, "include_sources": True}
)
print(f"Status: {response.status_code}")
result = response.json()
print(f"Answer: {result.get('answer', '')[:100]}")
print(f"Confidence: {result.get('confidence', 0)}")
print(f"Entities used: {len(result.get('entities_used', []))}")
print(f"Sources: {len(result.get('sources', []))}")

# Test 4: Try global search
print("\n=== Test 4: Global Search ===")
response = requests.post(
    f"{API_BASE}/graphrag/v3/query/global",
    headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
    json={"query": "What are the main contracts?", "top_k": 10, "include_sources": True}
)
print(f"Status: {response.status_code}")
result = response.json()
print(f"Answer: {result.get('answer', '')[:200]}")
print(f"Confidence: {result.get('confidence', 0)}")
print(f"Communities used: {len(result.get('communities_used', []))}")
