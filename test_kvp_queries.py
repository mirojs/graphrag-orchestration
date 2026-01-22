"""Test KeyValue nodes extraction with Route 1 queries."""
import requests
import json
import time

BASE_URL = "https://graphrag-orchestration.proudisland-64e79ab7.eastus.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-1769071711867955961"

def test_query(question: str, route: str = "route1") -> dict:
    """Send test query and return results."""
    url = f"{BASE_URL}/hybrid/query/standard"
    
    payload = {
        "question": question,
        "group_id": GROUP_ID,
        "route": route,
        "top_k": 5
    }
    
    print(f"\n{'='*80}")
    print(f"QUESTION: {question}")
    print(f"ROUTE: {route}")
    print(f"{'='*80}\n")
    
    start = time.time()
    response = requests.post(url, json=payload, timeout=60)
    elapsed = time.time() - start
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ SUCCESS ({elapsed:.2f}s)")
        print(f"\nANSWER:\n{result.get('answer', 'N/A')}\n")
        
        # Show context if available
        if 'context_used' in result:
            print(f"CONTEXT CHUNKS: {len(result['context_used'])}")
            for i, ctx in enumerate(result['context_used'][:3], 1):
                print(f"  {i}. {ctx.get('text', '')[:100]}...")
        
        # Show KeyValue matches if available
        if 'keyvalue_matches' in result:
            print(f"\nKEYVALUE MATCHES: {len(result['keyvalue_matches'])}")
            for kv in result['keyvalue_matches'][:5]:
                print(f"  • {kv.get('key', 'N/A')}: {kv.get('value', 'N/A')}")
        
        return result
    else:
        print(f"❌ FAILED ({elapsed:.2f}s)")
        print(f"Status: {response.status_code}")
        print(f"Error: {response.text}")
        return {}

def main():
    """Run test queries for KVP extraction."""
    
    # Test 1: Invoice number (should find KeyValue node)
    test_query("What is the invoice number?", "route1")
    
    # Test 2: Due date (should find KeyValue node)
    test_query("What is the due date?", "route1")
    
    # Test 3: Policy number (fuzzy match test - "policy #" vs "policy number")
    test_query("What is the policy number?", "route1")
    
    # Test 4: Total amount (might be in table or KVP)
    test_query("What is the total amount?", "route1")
    
    # Test 5: General entity extraction (should use existing flow)
    test_query("Who are the parties involved?", "route1")

if __name__ == "__main__":
    main()
