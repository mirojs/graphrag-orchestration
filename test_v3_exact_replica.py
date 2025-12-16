#!/usr/bin/env python3
"""Exact replica of working v3 test but with our group ID"""

import requests
import time

API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "invoice-contract-verification"

# Exact same documents as working test
TEST_DOCS = [
    {"text": "ABC Corporation announced a $10M partnership with XYZ Industries focused on AI development."},
    {"text": "CEO John Smith of ABC Corp stated the XYZ partnership will accelerate machine learning research."},
    {"text": "The ABC Corporation and XYZ Industries collaboration includes joint R&D in artificial intelligence."},
    {"text": "Sarah Johnson, CTO at XYZ Industries, confirmed the strategic alliance with ABC Corporation."},
]

def test_indexing():
    """Test v3 indexing endpoint"""
    print("=" * 80)
    print("V3 INDEXING TEST (Exact replica with invoice-contract-verification group)")
    print("=" * 80)
    
    response = requests.post(
        f"{API_URL}/graphrag/v3/index",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={"documents": TEST_DOCS},
        timeout=120
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Indexing successful")
        print(f"   Documents processed: {result.get('documents_processed', 0)}")
        print(f"   Entities created: {result.get('entities_created', 0)}")
        print(f"   Relationships created: {result.get('relationships_created', 0)}")
        print(f"   RAPTOR nodes created: {result.get('raptor_nodes_created', 0)}")
        return True
    else:
        print(f"❌ Indexing failed: {response.status_code}")
        print(f"   Response: {response.text}")
        return False

if __name__ == "__main__":
    if test_indexing():
        print("\n✅ V3 works with our group!")
        print("Now we can try with actual invoice/contract documents...")
    else:
        print("\n❌ V3 failed even with exact replica")
