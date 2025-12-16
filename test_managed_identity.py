#!/usr/bin/env python3
"""
GraphRAG v3 Managed Identity Integration Test
Tests the complete pipeline with managed identity authentication (no API keys)
"""
import requests
import json
import sys
import time
from typing import Dict, Any

# Configuration
BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
TEST_GROUP_ID = f"test-managed-identity-{int(time.time())}"

# Test data
TEST_DOCUMENTS = [
    "Invoice from Contoso Lifts LLC. Order #12345. Elevator maintenance service for Building A, 10 floors, $5000. Contact: John Smith at 555-1234.",
    "Purchase Contract between ABC Corporation and Contoso Lifts LLC. Equipment: Passenger Elevator Model X200, Capacity: 2000 lbs, Installation Date: June 15, 2024, Total Price: $75,000. Warranty: 2 years.",
    "Service Agreement for property management at Pacific View Retreat. Monthly fee: $2500. Building: B202. Term: 12 months starting June 15, 2010."
]

TEST_QUERIES = [
    "What are the payment terms and amounts mentioned?",
    "What companies are involved in these contracts?",
    "What equipment or services are being provided?"
]


def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{'=' * 80}")
    print(f"  {text}")
    print(f"{'=' * 80}\n")


def print_result(success: bool, message: str):
    """Print a formatted result"""
    symbol = "✅" if success else "❌"
    print(f"{symbol} {message}")


def test_indexing() -> Dict[str, Any]:
    """Test document indexing with managed identity"""
    print_header("TEST 1: Document Indexing with Managed Identity")
    
    print(f"Group ID: {TEST_GROUP_ID}")
    print(f"Documents: {len(TEST_DOCUMENTS)}")
    print("Testing: LLM (GPT-4o) and Embeddings (text-embedding-3-large) with managed identity\n")
    
    try:
        response = requests.post(
            f"{BASE_URL}/graphrag/v3/index",
            headers={
                'Content-Type': 'application/json',
                'X-Group-ID': TEST_GROUP_ID
            },
            json={"documents": TEST_DOCUMENTS},
            timeout=180
        )
        
        result = response.json()
        
        if response.status_code == 200:
            print_result(True, f"Status: {response.status_code} OK")
            print(f"  📄 Documents processed: {result.get('documents_processed', 0)}")
            print(f"  🏷️  Entities created: {result.get('entities_created', 0)}")
            print(f"  🔗 Relationships created: {result.get('relationships_created', 0)}")
            print(f"  👥 Communities created: {result.get('communities_created', 0)}")
            print(f"  🌳 RAPTOR nodes created: {result.get('raptor_nodes_created', 0)}")
            print(f"\n  Message: {result.get('message', 'N/A')}")
            return result
        else:
            print_result(False, f"Status: {response.status_code}")
            print(f"  Error: {json.dumps(result, indent=2)}")
            return None
            
    except Exception as e:
        print_result(False, f"Exception: {str(e)}")
        return None


def test_drift_queries(indexing_result: Dict[str, Any]) -> bool:
    """Test DRIFT queries with embeddings"""
    print_header("TEST 2: DRIFT Queries (Semantic Search with Embeddings)")
    
    if not indexing_result:
        print_result(False, "Skipping - indexing failed")
        return False
    
    print("Testing embedding model initialization and semantic search...")
    print(f"Note: Embeddings use managed identity (no API key)\n")
    
    all_success = True
    
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\nQuery {i}: '{query}'")
        
        try:
            response = requests.post(
                f"{BASE_URL}/graphrag/v3/query/drift",
                headers={
                    'Content-Type': 'application/json',
                    'X-Group-ID': TEST_GROUP_ID
                },
                json={"query": query},
                timeout=60
            )
            
            result = response.json()
            
            if response.status_code == 200:
                # Check if embedder is working (no "not initialized" error)
                answer = result.get('answer', '')
                if 'Embedder not initialized' in answer or 'No data has been indexed' in answer:
                    print_result(False, "Embedder initialization issue")
                    all_success = False
                else:
                    confidence = result.get('confidence', 0)
                    iterations = result.get('iterations', 0)
                    sources_count = len(result.get('sources', []))
                    
                    print_result(True, f"Query succeeded")
                    print(f"  📊 Confidence: {confidence}")
                    print(f"  🔄 Iterations: {iterations}")
                    print(f"  📚 Sources: {sources_count}")
                    print(f"  💬 Answer: {answer[:150]}{'...' if len(answer) > 150 else ''}")
            else:
                print_result(False, f"Status: {response.status_code}")
                print(f"  Error: {json.dumps(result, indent=2)}")
                all_success = False
                
        except Exception as e:
            print_result(False, f"Exception: {str(e)}")
            all_success = False
    
    return all_success


def test_local_query() -> bool:
    """Test local (non-semantic) query"""
    print_header("TEST 3: Local Query (Non-semantic)")
    
    print("Testing local query without embeddings...\n")
    
    try:
        response = requests.post(
            f"{BASE_URL}/graphrag/v3/query/local",
            headers={
                'Content-Type': 'application/json',
                'X-Group-ID': TEST_GROUP_ID
            },
            json={"query": "What companies are mentioned?"},
            timeout=60
        )
        
        result = response.json()
        
        if response.status_code == 200:
            answer = result.get('answer', '')
            confidence = result.get('confidence', 0)
            
            print_result(True, f"Query succeeded")
            print(f"  📊 Confidence: {confidence}")
            print(f"  💬 Answer: {answer[:200]}{'...' if len(answer) > 200 else ''}")
            return True
        else:
            print_result(False, f"Status: {response.status_code}")
            print(f"  Error: {json.dumps(result, indent=2)}")
            return False
            
    except Exception as e:
        print_result(False, f"Exception: {str(e)}")
        return False


def test_global_query() -> bool:
    """Test global community-based query"""
    print_header("TEST 4: Global Query (Community-based)")
    
    print("Testing global query across communities...\n")
    
    try:
        response = requests.post(
            f"{BASE_URL}/graphrag/v3/query/global",
            headers={
                'Content-Type': 'application/json',
                'X-Group-ID': TEST_GROUP_ID
            },
            json={"query": "Summarize all the business contracts and agreements"},
            timeout=60
        )
        
        result = response.json()
        
        if response.status_code == 200:
            answer = result.get('answer', '')
            confidence = result.get('confidence', 0)
            
            print_result(True, f"Query succeeded")
            print(f"  📊 Confidence: {confidence}")
            print(f"  💬 Answer: {answer[:200]}{'...' if len(answer) > 200 else ''}")
            return True
        else:
            print_result(False, f"Status: {response.status_code}")
            print(f"  Error: {json.dumps(result, indent=2)}")
            return False
            
    except Exception as e:
        print_result(False, f"Exception: {str(e)}")
        return False


def print_summary(results: Dict[str, bool]):
    """Print test summary"""
    print_header("TEST SUMMARY")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for test, success in results.items():
        print_result(success, test)
    
    print(f"\n{'=' * 80}")
    print(f"  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print(f"  🎉 All tests passed! Managed identity authentication working perfectly!")
    else:
        print(f"  ⚠️  Some tests failed. Check logs above for details.")
    
    print(f"{'=' * 80}\n")
    
    return passed == total


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("  GraphRAG v3 - Managed Identity Integration Test Suite")
    print("  Testing: No API keys, only Azure AD managed identity")
    print("=" * 80)
    
    results = {}
    
    # Test 1: Indexing
    indexing_result = test_indexing()
    results["Document Indexing (LLM + Embeddings)"] = indexing_result is not None
    
    # Wait a moment for Neo4j to fully commit
    if indexing_result:
        print("\n⏳ Waiting 3 seconds for data to propagate...")
        time.sleep(3)
    
    # Test 2: DRIFT queries (requires embeddings)
    drift_success = test_drift_queries(indexing_result)
    results["DRIFT Queries (Embeddings)"] = drift_success
    
    # Test 3: Local query
    local_success = test_local_query()
    results["Local Query"] = local_success
    
    # Test 4: Global query
    global_success = test_global_query()
    results["Global Query"] = global_success
    
    # Print summary
    all_passed = print_summary(results)
    
    # Exit with appropriate code
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
