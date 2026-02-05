#!/usr/bin/env python3
"""
Test Route 3 with enhanced Neo4j retrieval and fail-fast behavior.

Tests:
1. Success case: Group with proper MENTIONS edges
2. Fail case: Group without MENTIONS edges (should fail fast)
"""

import json
import requests
import sys

BASE_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Test groups
GROUP_WITH_MENTIONS = "test-5pdfs-1767429340223041632"  # Has MENTIONS edges
GROUP_WITHOUT_MENTIONS = "test-5pdfs-nlp-1767461862"    # No entities/MENTIONS

def test_route3_success():
    """Test Route 3 with a properly indexed group."""
    print("\n" + "="*60)
    print("TEST 1: Route 3 with MENTIONS edges (should succeed)")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/hybrid/query",
        headers={
            "Content-Type": "application/json",
            "X-Group-ID": GROUP_WITH_MENTIONS,
        },
        json={
            "query": "What are the warranty obligations?",
            "response_type": "detailed_report",
            "force_route": "global_search",
        },
        timeout=30,
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ SUCCESS")
        print(f"Route used: {data.get('route_used')}")
        print(f"Citations: {len(data.get('citations', []))}")
        print(f"Source chunks: {data.get('metadata', {}).get('num_source_chunks', 0)}")
        print(f"Relationships: {data.get('metadata', {}).get('num_relationships_found', 0)}")
        
        if data.get('citations'):
            print("\nFirst citation:")
            c = data['citations'][0]
            print(f"  Section: {c.get('section')}")
            print(f"  Entity: {c.get('entity')}")
            print(f"  Source: {c.get('source', '')[:60]}...")
        
        return True
    else:
        print(f"❌ FAILED: {response.status_code}")
        print(response.text[:500])
        return False


def test_route3_fail_fast():
    """Test Route 3 with a group that has no MENTIONS edges."""
    print("\n" + "="*60)
    print("TEST 2: Route 3 without MENTIONS edges (should fail fast)")
    print("="*60)
    
    response = requests.post(
        f"{BASE_URL}/hybrid/query",
        headers={
            "Content-Type": "application/json",
            "X-Group-ID": GROUP_WITHOUT_MENTIONS,
        },
        json={
            "query": "What are the warranty obligations?",
            "response_type": "detailed_report",
            "force_route": "global_search",
        },
        timeout=30,
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 500:
        data = response.json()
        error_detail = data.get('detail', '')
        print(f"✅ FAILED FAST AS EXPECTED")
        print(f"Error: {error_detail[:200]}...")
        
        # Check that error mentions MENTIONS edges
        if "MENTIONS" in error_detail or "source chunks" in error_detail.lower():
            print("✅ Error message is informative")
            return True
        else:
            print("⚠️  Error message doesn't mention MENTIONS edges")
            return False
    else:
        print(f"❌ UNEXPECTED: Should have returned 500, got {response.status_code}")
        print(response.text[:500])
        return False


def main():
    print("\nRoute 3 Fail-Fast Testing")
    print("="*60)
    
    # Test 1: Success case
    success_test = test_route3_success()
    
    # Test 2: Fail-fast case
    fail_fast_test = test_route3_fail_fast()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Success case: {'✅ PASS' if success_test else '❌ FAIL'}")
    print(f"Fail-fast case: {'✅ PASS' if fail_fast_test else '❌ FAIL'}")
    print("="*60)
    
    if success_test and fail_fast_test:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
