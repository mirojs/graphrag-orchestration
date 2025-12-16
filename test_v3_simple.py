#!/usr/bin/env python3
"""Simple v3 test with short documents to verify entity extraction works"""

import requests
import time

API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "phase1-v3-validation"  # Use the working test group

# Simple test documents (like working test)
TEST_DOCS = [
    {"text": "Contoso Lifts LLC invoiced $25,000 for elevator maintenance on June 15, 2024."},
    {"text": "The purchase contract between Contoso Lifts and ABC Corp specifies $20,000 for maintenance services."},
    {"text": "Payment terms in the contract require net 30 days payment after invoice date."},
]

def test_v3_indexing():
    """Test v3 indexing with simple documents"""
    print("=" * 70)
    print("V3 INDEXING TEST (Simple Documents)")
    print("=" * 70)
    
    response = requests.post(
        f"{API_URL}/graphrag/v3/index",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={"documents": TEST_DOCS},
        timeout=120
    )
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Documents processed: {result.get('documents_processed', 0)}")
        print(f"✓ Entities created: {result.get('entities_created', 0)}")
        print(f"✓ Relationships created: {result.get('relationships_created', 0)}")
        print(f"✓ RAPTOR nodes: {result.get('raptor_nodes_created', 0)}")
        return result.get('entities_created', 0) > 0
    else:
        print(f"✗ Error: {response.text}")
        return False

def test_v3_drift_query():
    """Test DRIFT query after indexing"""
    print("\n" + "=" * 70)
    print("V3 DRIFT QUERY TEST")
    print("=" * 70)
    
    # Wait for indexing to complete
    print("Waiting 10 seconds for indexing to complete...")
    time.sleep(10)
    
    response = requests.post(
        f"{API_URL}/graphrag/v3/query/drift",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={"query": "What is the invoice amount and contract amount?"},
        timeout=60
    )
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"Answer: {result.get('answer', 'N/A')}")
        print(f"Confidence: {result.get('confidence', 0.0):.2f}")
        print(f"Sources: {len(result.get('sources', []))}")
        return True
    else:
        print(f"✗ Error: {response.text}")
        return False

if __name__ == "__main__":
    print("\nTesting v3 with simple documents to verify entity extraction...\n")
    
    if test_v3_indexing():
        print("\n✅ Entity extraction WORKING - v3 pipeline is functional")
        test_v3_drift_query()
    else:
        print("\n❌ Entity extraction FAILED - 0 entities created")
        print("   This indicates a configuration or LLM issue with the v3 pipeline")
