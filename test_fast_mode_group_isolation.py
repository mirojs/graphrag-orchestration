#!/usr/bin/env python3
"""
Comprehensive test for Fast Mode with Group Isolation
Verifies that ROUTE3_FAST_MODE respects tenant boundaries
"""

import httpx
import json
import time

API_BASE = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Two different groups
GROUP_A = "test-5pdfs-1768557493369886422"
GROUP_B = "test-5pdfs-1768486622652179443"

def test_fast_mode_group_isolation():
    """
    Test that Fast Mode (ROUTE3_FAST_MODE=1) maintains group isolation
    across multiple query types.
    """
    
    print("=" * 80)
    print("FAST MODE + GROUP ISOLATION TEST")
    print("=" * 80)
    print(f"\nTesting with:")
    print(f"  - Group A: {GROUP_A}")
    print(f"  - Group B: {GROUP_B}")
    print(f"  - Route: global_search (Route 3 with Fast Mode)")
    print(f"  - Expected: No chunk overlap between groups")
    print("=" * 80)
    
    test_queries = [
        {
            "query": "What are the main compliance risks?",
            "description": "Simple thematic (PPR should be skipped)",
        },
        {
            "query": "Summarize all termination clauses",
            "description": "Cross-document summary (PPR should be skipped)",
        },
        {
            "query": "What insurance policies are mentioned?",
            "description": "Entity-focused query",
        },
    ]
    
    all_passed = True
    
    for i, test_case in enumerate(test_queries, 1):
        query = test_case["query"]
        description = test_case["description"]
        
        print(f"\n{'─' * 80}")
        print(f"Test {i}: {description}")
        print(f"Query: '{query}'")
        print(f"{'─' * 80}")
        
        # Query Group A
        print(f"\n  📋 Group A...")
        start_a = time.time()
        response_a = httpx.post(
            f"{API_BASE}/hybrid/query",
            json={
                "query": query,
                "force_route": "global_search",
            },
            headers={"X-Group-ID": GROUP_A},
            timeout=90.0,
        )
        latency_a = time.time() - start_a
        
        if response_a.status_code != 200:
            print(f"    ❌ ERROR: {response_a.status_code}")
            all_passed = False
            continue
        
        data_a = response_a.json()
        citations_a = data_a.get("citations", [])
        chunk_ids_a = {c["chunk_id"] for c in citations_a}
        
        print(f"    ✓ Retrieved {len(citations_a)} citations ({latency_a:.1f}s)")
        
        # Query Group B
        print(f"  📋 Group B...")
        start_b = time.time()
        response_b = httpx.post(
            f"{API_BASE}/hybrid/query",
            json={
                "query": query,
                "force_route": "global_search",
            },
            headers={"X-Group-ID": GROUP_B},
            timeout=90.0,
        )
        latency_b = time.time() - start_b
        
        if response_b.status_code != 200:
            print(f"    ❌ ERROR: {response_b.status_code}")
            all_passed = False
            continue
        
        data_b = response_b.json()
        citations_b = data_b.get("citations", [])
        chunk_ids_b = {c["chunk_id"] for c in citations_b}
        
        print(f"    ✓ Retrieved {len(citations_b)} citations ({latency_b:.1f}s)")
        
        # Check isolation
        overlap = chunk_ids_a & chunk_ids_b
        
        print(f"\n  📊 Isolation Check:")
        print(f"    Group A chunks: {len(chunk_ids_a)}")
        print(f"    Group B chunks: {len(chunk_ids_b)}")
        print(f"    Overlap: {len(overlap)}")
        
        if overlap:
            print(f"    ❌ FAILED: {len(overlap)} chunks shared between groups!")
            print(f"    Overlapping: {list(overlap)[:3]}")
            all_passed = False
        else:
            print(f"    ✅ PASSED: Perfect isolation")
        
        # Check latency (Fast Mode should be faster)
        avg_latency = (latency_a + latency_b) / 2
        print(f"\n  ⏱️  Average Latency: {avg_latency:.1f}s")
        if avg_latency > 20:
            print(f"    ⚠️  WARNING: Latency higher than expected for Fast Mode")
        else:
            print(f"    ✓ Latency within expected range (<20s)")
    
    print(f"\n{'=' * 80}")
    print("FINAL RESULT:")
    if all_passed:
        print("  ✅ ALL TESTS PASSED")
        print("  Fast Mode correctly maintains group isolation")
        print("=" * 80)
        return True
    else:
        print("  ❌ SOME TESTS FAILED")
        print("  Check logs above for details")
        print("=" * 80)
        return False

if __name__ == "__main__":
    success = test_fast_mode_group_isolation()
    exit(0 if success else 1)
