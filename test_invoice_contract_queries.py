"""
Test invoice and contract queries against the GraphRAG API.
Tests local search, global search, and RAPTOR queries.
"""

import requests
import time
import os

# Configuration
API_BASE = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "phase1-5docs-1766235543"  # From the latest test run

# Test queries based on the documents
TEST_QUERIES = [
    {
        "query": "What is the total amount on the Contoso Lifts invoice?",
        "type": "local",
        "expected_keywords": ["Contoso", "invoice", "amount", "total"]
    },
    {
        "query": "What are the payment terms in the purchase contract?",
        "type": "local", 
        "expected_keywords": ["payment", "terms", "contract"]
    },
    {
        "query": "What is the warranty period mentioned in the Builder's Limited Warranty?",
        "type": "local",
        "expected_keywords": ["warranty", "period", "builder"]
    },
    {
        "query": "What services are included in the Property Management Agreement?",
        "type": "local",
        "expected_keywords": ["property", "management", "services"]
    },
    {
        "query": "What is the frequency of holding tank servicing?",
        "type": "local",
        "expected_keywords": ["holding", "tank", "servicing", "frequency"]
    },
    {
        "query": "Summarize all the contracts and their key terms",
        "type": "global",
        "expected_keywords": ["contract", "agreement"]
    },
    {
        "query": "What are the main payment obligations across all documents?",
        "type": "global",
        "expected_keywords": ["payment", "obligation"]
    },
]

def query_graphrag(query: str, search_type: str = "local") -> dict:
    """Query the GraphRAG API."""
    endpoint = f"{API_BASE}/graphrag/v3/query/{search_type}"
    
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json"
    }
    
    payload = {
        "query": query,
        "top_k": 10,
        "include_sources": True
    }
    
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def main():
    print("=" * 80)
    print("Testing Invoice & Contract Queries")
    print("=" * 80)
    print(f"API: {API_BASE}")
    print(f"Group ID: {GROUP_ID}")
    print()
    
    results = []
    
    for i, test in enumerate(TEST_QUERIES, 1):
        query = test["query"]
        search_type = test["type"]
        expected = test["expected_keywords"]
        
        print(f"\n{'='*80}")
        print(f"Query {i}/{len(TEST_QUERIES)}: {query}")
        print(f"Type: {search_type.upper()}")
        print("=" * 80)
        
        start = time.time()
        result = query_graphrag(query, search_type)
        elapsed = time.time() - start
        
        if "error" in result:
            print(f"❌ Error: {result['error']}")
            results.append({
                "query": query,
                "type": search_type,
                "success": False,
                "error": result["error"],
                "elapsed": elapsed
            })
            continue
        
        answer = result.get("answer", "")
        confidence = result.get("confidence", 0.0)
        sources = result.get("sources", [])
        
        print(f"\n⏱️  Response time: {elapsed:.2f}s")
        print(f"📊 Confidence: {confidence:.2f}")
        print(f"📚 Sources: {len(sources)}")
        
        print(f"\n💬 Answer:")
        print("-" * 80)
        print(answer)
        print("-" * 80)
        
        # Check if expected keywords are in answer
        answer_lower = answer.lower()
        found_keywords = [kw for kw in expected if kw.lower() in answer_lower]
        
        if answer and answer != "No relevant information found for this query.":
            print(f"\n✅ Query successful")
            print(f"   Keywords found: {', '.join(found_keywords) if found_keywords else 'None'}")
            
            if sources:
                print(f"\n   Top sources:")
                for j, source in enumerate(sources[:3], 1):
                    if search_type == "local":
                        print(f"     {j}. {source.get('name', 'Unknown')} ({source.get('type', 'Entity')}) - score: {source.get('score', 0):.3f}")
                    else:
                        print(f"     {j}. Community {source.get('community_id', 'Unknown')} - score: {source.get('relevance', 0):.3f}")
            
            results.append({
                "query": query,
                "type": search_type,
                "success": True,
                "answer_length": len(answer),
                "confidence": confidence,
                "sources": len(sources),
                "elapsed": elapsed,
                "keywords_found": len(found_keywords)
            })
        else:
            print(f"\n⚠️  No relevant information found")
            results.append({
                "query": query,
                "type": search_type,
                "success": False,
                "error": "No information found",
                "elapsed": elapsed
            })
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print("=" * 80)
    
    successful = sum(1 for r in results if r.get("success", False))
    total = len(results)
    
    print(f"\n✅ Successful: {successful}/{total} ({successful/total*100:.1f}%)")
    
    if successful > 0:
        avg_time = sum(r["elapsed"] for r in results if r.get("success", False)) / successful
        avg_confidence = sum(r["confidence"] for r in results if r.get("success", False)) / successful
        avg_sources = sum(r["sources"] for r in results if r.get("success", False)) / successful
        
        print(f"⏱️  Average response time: {avg_time:.2f}s")
        print(f"📊 Average confidence: {avg_confidence:.2f}")
        print(f"📚 Average sources: {avg_sources:.1f}")
    
    print()

if __name__ == "__main__":
    main()
