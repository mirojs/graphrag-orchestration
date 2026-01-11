#!/usr/bin/env python3
"""
Quick test to run migration via the deployed service's Neo4j connection.
"""

import requests
import json

url = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
group_id = "test-cypher25-final-1768129960"

# Use the graphrag/debug endpoint which has Neo4j access
response = requests.post(
    f"{url}/graphrag/v2/debug/run-query",
    headers={"X-Group-ID": group_id},
    json={
        "query": """
        MATCH (t:TextChunk {group_id: $group_id})-[:PART_OF]->(d:Document)
        WHERE t.document_id IS NULL
        SET t.document_id = d.id
        RETURN count(t) AS updated_chunks
        """,
        "params": {"group_id": group_id}
    }
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
