"""
Debug DRIFT Embedding Compatibility Issue

This script tests the exact failure point to understand why embeddings are incompatible.
"""

import asyncio
import requests
import os

API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "phase1-5docs-1765797213"

async def main():
    print("=" * 80)
    print("DRIFT EMBEDDING COMPATIBILITY DEBUG")
    print("=" * 80)
    
    # Test 1: Simple DRIFT query
    print("\n🧪 Test 1: DRIFT Query with detailed error reporting")
    print("-" * 80)
    
    response = requests.post(
        f"{API_URL}/graphrag/v3/query/drift",
        json={
            "query": "What is the purchase contract about?",
            "max_iterations": 2,
        },
        headers={"X-Group-ID": GROUP_ID}
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    # Test 2: Check if local search works (uses same embeddings)
    print("\n🧪 Test 2: Local Query (same embedding model)")
    print("-" * 80)
    
    response = requests.post(
        f"{API_URL}/graphrag/v3/query/local",
        json={
            "query": "What is the purchase contract about?",
            "top_k": 3,
        },
        headers={"X-Group-ID": GROUP_ID}
    )
    
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Answer: {result.get('answer', 'N/A')[:100]}...")
    print(f"Confidence: {result.get('confidence', 0):.2%}")
    
    print("\n" + "=" * 80)
    print("DEBUG COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
