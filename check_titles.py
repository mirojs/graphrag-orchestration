#!/usr/bin/env python3
"""Check document titles via API."""
import requests

BASE_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-1768558518157"

# Query to check document titles
query = """
MATCH (d:Document)
WHERE d.group_id = $group_id
RETURN d.title AS title, d.source AS source
ORDER BY d.title
"""

resp = requests.post(
    f"{BASE_URL}/api/neo4j/query",
    json={"query": query, "parameters": {"group_id": GROUP_ID}},
    headers={"X-Group-ID": GROUP_ID},
)

if resp.status_code == 200:
    data = resp.json()
    print("\nDocument titles after fix:")
    for record in data.get("records", []):
        title = record.get("title", "")
        source = record.get("source", "")
        source_file = source.split("/")[-1] if source else "no source"
        print(f"  ✅ {title:40} → {source_file}")
else:
    print(f"Error: {resp.status_code}")
    print(resp.text)
