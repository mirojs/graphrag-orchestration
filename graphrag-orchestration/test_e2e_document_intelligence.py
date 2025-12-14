#!/usr/bin/env python3
"""
End-to-End Integration Test: Document Intelligence → GraphRAG → Neo4j → Query

Tests the complete pipeline:
1. Upload documents via Document Intelligence
2. Extract entities and relationships via GraphRAG
3. Store in Neo4j
4. Query the knowledge graph
"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:8001"
GROUP_ID = "e2e-test-di"
HEADERS = {
    "Content-Type": "application/json",
    "X-Group-ID": GROUP_ID
}

# Test document - Microsoft 10-Q SEC filing (has tables, sections, structured data)
TEST_DOCUMENT = "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/sample-layout.pdf"


def print_section(title):
    """Print formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_health():
    """Verify service is running."""
    print_section("1. Health Check")
    
    try:
        resp = requests.get(f"{BASE_URL}/health", headers=HEADERS, timeout=5)
        print(f"✅ Service is running (status: {resp.status_code})")
        return True
    except Exception as e:
        print(f"❌ Service not available: {e}")
        print("\nPlease start the service:")
        print("  cd services/graphrag-orchestration")
        print("  uvicorn app.main:app --host 0.0.0.0 --port 8001")
        return False


def test_indexing_with_document_intelligence():
    """Index a document using Document Intelligence ingestion."""
    print_section("2. Document Intelligence Ingestion + GraphRAG Indexing")
    
    payload = {
        "documents": [TEST_DOCUMENT],
        "ingestion_mode": "document-intelligence"
    }
    
    print(f"📤 Uploading document: {TEST_DOCUMENT}")
    print(f"   Ingestion mode: document-intelligence")
    
    start_time = time.time()
    
    try:
        resp = requests.post(
            f"{BASE_URL}/graphrag/index",
            headers=HEADERS,
            json=payload,
            timeout=180  # GraphRAG can take time
        )
        
        elapsed = time.time() - start_time
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Indexing completed in {elapsed:.2f}s")
            print(f"   Response: {json.dumps(result, indent=2)}")
            return True
        else:
            print(f"❌ Indexing failed (status {resp.status_code})")
            print(f"   Error: {resp.text}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"⏱️  Request timed out after 180s")
        print("   This may indicate:")
        print("   - Azure OpenAI rate limiting")
        print("   - Large document processing")
        print("   - Network issues")
        return False
    except Exception as e:
        print(f"❌ Indexing error: {e}")
        return False


def test_graph_query():
    """Query Neo4j to verify entities were stored."""
    print_section("3. Neo4j Graph Query - Verify Entities")
    
    # Count nodes for this group
    query = f"""
    MATCH (n {{group_id: '{GROUP_ID}'}})
    RETURN count(n) as entity_count,
           collect(DISTINCT labels(n)[0])[..5] as sample_types
    """
    
    payload = {"query": query}
    
    print(f"🔍 Querying Neo4j for group: {GROUP_ID}")
    
    try:
        resp = requests.post(
            f"{BASE_URL}/graphrag/query/graph",
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        
        if resp.status_code == 200:
            result = resp.json()
            if result.get("results"):
                data = result["results"][0]
                count = data.get("entity_count", 0)
                types = data.get("sample_types", [])
                
                print(f"✅ Found {count} entities in knowledge graph")
                print(f"   Sample entity types: {', '.join(types)}")
                return count > 0
            else:
                print("⚠️  Query returned no results")
                return False
        else:
            print(f"❌ Query failed (status {resp.status_code})")
            print(f"   Error: {resp.text}")
            return False
            
    except Exception as e:
        print(f"❌ Query error: {e}")
        return False


def test_local_search():
    """Test GraphRAG local search on indexed data."""
    print_section("4. GraphRAG Local Search - Document Intelligence Data")
    
    payload = {
        "query": "What is the commission file number mentioned in the document?",
        "community_level": 0,
        "top_k": 5
    }
    
    print(f"💬 Query: {payload['query']}")
    
    try:
        resp = requests.post(
            f"{BASE_URL}/graphrag/query/local",
            headers=HEADERS,
            json=payload,
            timeout=30
        )
        
        if resp.status_code == 200:
            result = resp.json()
            answer = result.get("response", "")
            context = result.get("context", {})
            
            print(f"✅ Search completed")
            print(f"\n📝 Answer:")
            print(f"   {answer[:300]}..." if len(answer) > 300 else f"   {answer}")
            
            if context.get("entities"):
                print(f"\n🔗 Entities used: {len(context['entities'])}")
            if context.get("relationships"):
                print(f"🔗 Relationships used: {len(context['relationships'])}")
                
            return len(answer) > 0
        else:
            print(f"❌ Search failed (status {resp.status_code})")
            print(f"   Error: {resp.text}")
            return False
            
    except Exception as e:
        print(f"❌ Search error: {e}")
        return False


def test_batch_processing():
    """Test batch processing of multiple documents."""
    print_section("5. Batch Processing Test (3 Documents)")
    
    # Use same document 3 times to simulate batch
    payload = {
        "documents": [TEST_DOCUMENT] * 3,
        "ingestion_mode": "document-intelligence"
    }
    
    print(f"📦 Uploading {len(payload['documents'])} documents in parallel")
    
    start_time = time.time()
    
    try:
        resp = requests.post(
            f"{BASE_URL}/graphrag/index",
            headers={**HEADERS, "X-Group-ID": f"{GROUP_ID}-batch"},
            json=payload,
            timeout=240
        )
        
        elapsed = time.time() - start_time
        
        if resp.status_code == 200:
            print(f"✅ Batch indexing completed in {elapsed:.2f}s")
            print(f"   Average per document: {elapsed/3:.2f}s")
            print(f"   Throughput: {3/elapsed:.2f} docs/second")
            return True
        else:
            print(f"❌ Batch indexing failed")
            print(f"   Error: {resp.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"⏱️  Batch request timed out")
        return False
    except Exception as e:
        print(f"❌ Batch error: {e}")
        return False


def main():
    """Run complete E2E test suite."""
    print("\n" + "🧪" * 40)
    print("End-to-End Integration Test: Document Intelligence → GraphRAG")
    print("🧪" * 40)
    
    results = {
        "health": False,
        "indexing": False,
        "graph_query": False,
        "local_search": False,
        "batch": False
    }
    
    # Test 1: Health check
    if not test_health():
        print("\n❌ Service not available. Cannot proceed with tests.")
        sys.exit(1)
    results["health"] = True
    
    # Test 2: Index document with Document Intelligence
    results["indexing"] = test_indexing_with_document_intelligence()
    
    if results["indexing"]:
        # Wait for async indexing to complete
        print("\n⏳ Waiting 5 seconds for indexing to complete...")
        time.sleep(5)
        
        # Test 3: Verify entities in Neo4j
        results["graph_query"] = test_graph_query()
        
        # Test 4: GraphRAG local search
        results["local_search"] = test_local_search()
    
    # Test 5: Batch processing
    results["batch"] = test_batch_processing()
    
    # Summary
    print_section("Test Summary")
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, passed_test in results.items():
        status = "✅ PASS" if passed_test else "❌ FAIL"
        print(f"  {status}  {test_name.replace('_', ' ').title()}")
    
    print(f"\n📊 Results: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n🎉 All integration tests passed!")
        print("   Document Intelligence → GraphRAG pipeline is working!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
