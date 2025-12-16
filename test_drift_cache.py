#!/usr/bin/env python3
"""
Test DRIFT cache optimization
Compares query response times to verify global cache is working
"""

import requests
import time
import json
from datetime import datetime

# Configuration
API_ENDPOINT = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-group-cache"
DRIFT_ENDPOINT = f"{API_ENDPOINT}/graphrag/v3/query/drift"

# Test query
QUERY = {
    "query": "What are the key relationships in the data?"
}

HEADERS = {
    "Content-Type": "application/json",
    "X-Group-ID": GROUP_ID
}

def test_drift_query(query_num: int) -> dict:
    """Execute a DRIFT query and measure response time"""
    print(f"\n{'='*70}")
    print(f"Query #{query_num}: {QUERY['query']}")
    print(f"{'='*70}")
    
    start_time = time.time()
    
    try:
        response = requests.post(
            DRIFT_ENDPOINT,
            headers=HEADERS,
            json=QUERY,
            timeout=120
        )
        
        elapsed = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Time: {elapsed:.2f}s")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Answer: {data.get('answer', 'N/A')[:100]}...")
            print(f"Confidence: {data.get('confidence', 0):.2f}")
            print(f"Sources: {len(data.get('sources', []))} items")
            return {
                "query_num": query_num,
                "status": "success",
                "elapsed_seconds": elapsed,
                "confidence": data.get('confidence', 0),
                "sources_count": len(data.get('sources', []))
            }
        else:
            print(f"Error: {response.text[:200]}")
            return {
                "query_num": query_num,
                "status": "error",
                "elapsed_seconds": elapsed,
                "error": response.text[:100]
            }
    
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"Exception: {str(e)}")
        return {
            "query_num": query_num,
            "status": "exception",
            "elapsed_seconds": elapsed,
            "error": str(e)
        }

def main():
    print("\n" + "="*70)
    print("DRIFT Cache Optimization Test")
    print("="*70)
    print(f"Endpoint: {DRIFT_ENDPOINT}")
    print(f"Group ID: {GROUP_ID}")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*70)
    
    # Health check first
    print("\n[1/4] Health Check...")
    try:
        health = requests.get(f"{API_ENDPOINT}/health", timeout=10).json()
        print(f"✓ Health: {health.get('status')}")
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return
    
    # Run 2 queries
    print("\n[2/4] Running Query #1 (loading data from Neo4j)...")
    result1 = test_drift_query(1)
    
    print("\n[3/4] Running Query #2 (should use global cache)...")
    result2 = test_drift_query(2)
    
    # Analysis
    print("\n[4/4] Cache Performance Analysis")
    print("="*70)
    
    if result1["status"] == "success" and result2["status"] == "success":
        time_saved = result1["elapsed_seconds"] - result2["elapsed_seconds"]
        time_saved_pct = (time_saved / result1["elapsed_seconds"]) * 100
        speedup = result1["elapsed_seconds"] / result2["elapsed_seconds"]
        
        print(f"\n✓ Both queries successful!")
        print(f"\nTiming Results:")
        print(f"  Query 1 (first run):  {result1['elapsed_seconds']:.2f}s")
        print(f"  Query 2 (cached):     {result2['elapsed_seconds']:.2f}s")
        print(f"  Time saved:           {time_saved:.2f}s ({time_saved_pct:.1f}%)")
        print(f"  Speedup factor:       {speedup:.2f}x faster")
        
        # Check if cache is working
        if time_saved > 30:  # Expect at least 30s improvement
            print(f"\n✅ CACHE IS WORKING! Second query ~{speedup:.1f}x faster")
        else:
            print(f"\n⚠️  Cache improvement below expected. Saved only {time_saved:.2f}s")
    else:
        print(f"\n✗ Queries failed:")
        print(f"  Query 1: {result1['status']}")
        print(f"  Query 2: {result2['status']}")
    
    # Summary JSON
    print("\n" + "="*70)
    print("Test Results Summary")
    print("="*70)
    summary = {
        "test_time": datetime.now().isoformat(),
        "endpoint": DRIFT_ENDPOINT,
        "group_id": GROUP_ID,
        "results": [result1, result2]
    }
    
    if result1["status"] == "success" and result2["status"] == "success":
        summary["cache_improvement"] = {
            "time_saved_seconds": result1["elapsed_seconds"] - result2["elapsed_seconds"],
            "time_saved_percent": ((result1["elapsed_seconds"] - result2["elapsed_seconds"]) / result1["elapsed_seconds"]) * 100,
            "speedup_factor": result1["elapsed_seconds"] / result2["elapsed_seconds"]
        }
    
    print(json.dumps(summary, indent=2))
    
    # Save results
    with open("/tmp/drift_cache_test_results.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults saved to: /tmp/drift_cache_test_results.json")

if __name__ == "__main__":
    main()
