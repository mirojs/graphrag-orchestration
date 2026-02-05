#!/usr/bin/env python3
"""Test semantic coverage with existing group (no re-indexing needed)."""

import httpx
import json
import sys

API_BASE = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-1768557493369886422"

def test_query(query: str):
    """Test a query and show retrieved chunks."""
    print(f"\n{'='*80}")
    print(f"Query: {query}")
    print('='*80)
    
    response = httpx.post(
        f"{API_BASE}/v1/query",
        json={
            "query": query,
            "force_route": "drift_multi_hop",
        },
        headers={
            "X-Group-ID": GROUP_ID,
        },
        timeout=60.0,
    )
    
    if response.status_code != 200:
        print(f"ERROR: {response.status_code}")
        print(response.text)
        return
    
    data = response.json()
    answer = data.get("answer", "")
    citations = data.get("citations", [])
    
    print(f"\nAnswer: {answer[:400]}...")
    print(f"\nCitations ({len(citations)}):")
    for i, cite in enumerate(citations[:5], 1):
        title = cite.get("title", "")
        preview = (cite.get("content", "") or "")[:150].replace("\n", " ")
        print(f"  {i}. {title}")
        print(f"     {preview}...")

if __name__ == "__main__":
    # Test Q-D4: Insurance query (should find chunk with insurance, not chunk 0)
    test_query("Which documents mention insurance and what limits are specified?")
    
    # Test Q-D7: Date query (should find chunk with 04/30/2025, not chunk 0)
    test_query("Which document has the latest date?")
