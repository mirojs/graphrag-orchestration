#!/usr/bin/env python3
"""Quick test to check if document_id exists and keywords match in Neo4j."""

import requests
import json

url = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
group_id = "test-5pdfs-1767429340223041632"
doc_id = "1f55a0d4-c35d-46b1-8604-2a3455df27dd"

# Test the exact query that negative detection uses
print("Testing Neo4j query for negative detection...\n")

# First, let's check if any chunks have the keywords
print(f"Looking for chunks in document {doc_id} with keywords: invoice, total, amount\n")

response = requests.post(
    f"{url}/hybrid/query",
    headers={
        "Content-Type": "application/json",
        "X-Group-ID": group_id
    },
    json={
        "query": "What is the invoice TOTAL amount?",
        "response_type": "summary",
        "force_route": "vector_rag"
    }
)

data = response.json()
print(f"Response: {data.get('response')}")
print(f"\nFirst citation document_id: {data['citations'][0].get('document_id') if data.get('citations') else 'None'}")
print(f"Text preview contains 'total': {'total' in data['citations'][0].get('text_preview', '').lower() if data.get('citations') else False}")
print(f"Text preview contains 'invoice': {'invoice' in data['citations'][0].get('text_preview', '').lower() if data.get('citations') else False}")
print(f"Text preview contains 'amount': {'amount' in data['citations'][0].get('text_preview', '').lower() if data.get('citations') else False}")

if data.get('citations'):
    print(f"\nFirst 200 chars of text: {data['citations'][0].get('text_preview', '')[:200]}")
