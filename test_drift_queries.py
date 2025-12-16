#!/usr/bin/env python3
"""Test DRIFT queries with existing indexed data"""

import requests
import json

API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "invoice-contract-verification"

def test_drift_query(query_text):
    """Test a DRIFT query"""
    print("=" * 80)
    print(f"QUERY: {query_text}")
    print("=" * 80)
    
    response = requests.post(
        f"{API_URL}/graphrag/v3/query/drift",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={"query": query_text},
        timeout=60
    )
    
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"Answer: {result.get('answer', 'N/A')}")
        print(f"Confidence: {result.get('confidence', 0.0):.2f}")
        print(f"Sources: {len(result.get('sources', []))}")
        
        # Show first 2 sources
        for i, source in enumerate(result.get('sources', [])[:2], 1):
            print(f"\nSource {i}:")
            print(f"  {source.get('text', '')[:200]}...")
        return result
    else:
        print(f"Error: {response.text}")
        return None

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("TESTING DRIFT QUERIES WITH INVOICE/CONTRACT DATA")
    print(f"Group: {GROUP_ID}")
    print("=" * 80 + "\n")
    
    # Test queries
    queries = [
        "What are the payment terms in the contracts?",
        "Compare the invoice amount against the contract terms",
        "What inconsistencies exist between the invoices and contracts?",
        "Who are the parties involved in these agreements?",
    ]
    
    results = []
    for query in queries:
        result = test_drift_query(query)
        results.append({"query": query, "result": result})
        print("\n")
    
    # Save results
    with open("/tmp/drift_query_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print("=" * 80)
    print("Results saved to: /tmp/drift_query_results.json")
    print("=" * 80)
