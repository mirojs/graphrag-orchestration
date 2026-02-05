#!/usr/bin/env python3
"""Test that semantic coverage respects group isolation."""

import httpx
import json

API_BASE = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Two different groups with different documents
GROUP_A = "test-5pdfs-1768557493369886422"
GROUP_B = "test-5pdfs-1768486622652179443"

def test_group_isolation():
    """Verify that semantic coverage only retrieves chunks from the specified group."""
    
    query = "Which documents mention insurance?"
    
    print("=" * 80)
    print("Testing Group Isolation with Semantic Coverage")
    print("=" * 80)
    
    # Query Group A
    print(f"\n📋 Group A: {GROUP_A}")
    response_a = httpx.post(
        f"{API_BASE}/hybrid/query",
        json={
            "query": query,
            "force_route": "drift_multi_hop",
        },
        headers={"X-Group-ID": GROUP_A},
        timeout=60.0,
    )
    
    if response_a.status_code != 200:
        print(f"  ❌ ERROR: {response_a.status_code}")
        return False
    
    data_a = response_a.json()
    citations_a = data_a.get("citations", [])
    chunk_ids_a = {c["chunk_id"] for c in citations_a}
    
    print(f"  ✓ Retrieved {len(citations_a)} citations")
    print(f"  ✓ Chunk IDs: {list(chunk_ids_a)[:3]}...")
    
    # Query Group B with same question
    print(f"\n📋 Group B: {GROUP_B}")
    response_b = httpx.post(
        f"{API_BASE}/hybrid/query",
        json={
            "query": query,
            "force_route": "drift_multi_hop",
        },
        headers={"X-Group-ID": GROUP_B},
        timeout=60.0,
    )
    
    if response_b.status_code != 200:
        print(f"  ❌ ERROR: {response_b.status_code}")
        return False
    
    data_b = response_b.json()
    citations_b = data_b.get("citations", [])
    chunk_ids_b = {c["chunk_id"] for c in citations_b}
    
    print(f"  ✓ Retrieved {len(citations_b)} citations")
    print(f"  ✓ Chunk IDs: {list(chunk_ids_b)[:3]}...")
    
    # Check for overlap (should be zero)
    overlap = chunk_ids_a & chunk_ids_b
    
    print(f"\n{'=' * 80}")
    print("ISOLATION CHECK:")
    print(f"  Group A chunks: {len(chunk_ids_a)}")
    print(f"  Group B chunks: {len(chunk_ids_b)}")
    print(f"  Overlap: {len(overlap)}")
    
    if overlap:
        print(f"  ❌ FAILED: Found {len(overlap)} chunks appearing in both groups!")
        print(f"  Overlapping chunk IDs: {overlap}")
        return False
    else:
        print(f"  ✅ PASSED: No chunks shared between groups (perfect isolation)")
        return True

if __name__ == "__main__":
    success = test_group_isolation()
    exit(0 if success else 1)
