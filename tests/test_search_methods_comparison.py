"""
Test script to compare Local, Global, DRIFT, and RAPTOR search methods.

This script runs the same queries against all four v3 search endpoints to demonstrate:
- Performance differences (response time)
- Answer quality and style
- Best use cases for each method

Prerequisites:
- Documents already indexed with run_raptor=true (use test_managed_identity_pdfs.py first)
- Azure Container App deployed and running
"""

import requests
import time
from datetime import datetime
from typing import Dict, List, Tuple
import json

# Configuration
BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-3072-fresh"  # Fresh group with clean 3072-dim data
HEADERS = {
    "Content-Type": "application/json",
    "X-Group-ID": GROUP_ID
}

# Test queries designed to showcase different search strengths
TEST_QUERIES = [
    {
        "query": "What is GraphRAG?",
        "best_for": "local",  # Specific entity lookup
        "description": "Specific entity definition"
    },
    {
        "query": "What are the main themes across all documents?",
        "best_for": "global",  # High-level themes
        "description": "Cross-document thematic summary"
    },
    {
        "query": "How are machine learning and knowledge graphs connected?",
        "best_for": "drift",  # Multi-hop reasoning
        "description": "Complex relationship reasoning"
    },
    {
        "query": "Extract specific details about data processing mentioned in the documents",
        "best_for": "raptor",  # Detailed content extraction
        "description": "Detailed document content"
    },
]

SEARCH_METHODS = ["local", "global", "drift", "raptor"]


def log(message: str):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def query_endpoint(method: str, query: str, top_k: int = 5) -> Tuple[Dict, float]:
    """
    Query a specific search endpoint and measure response time.
    
    Args:
        method: Search method (local/global/drift/raptor)
        query: Query string
        top_k: Number of results to return
    
    Returns:
        Tuple of (response_data, elapsed_time_seconds)
    """
    url = f"{BASE_URL}/graphrag/v3/query/{method}"
    payload = {
        "query": query,
        "top_k": top_k
    }
    
    # Add method-specific parameters
    if method == "drift":
        payload["max_iterations"] = 3
        payload["convergence_threshold"] = 0.1
    
    start_time = time.time()
    
    try:
        response = requests.post(url, json=payload, headers=HEADERS, timeout=60)
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            return response.json(), elapsed
        else:
            return {
                "error": f"HTTP {response.status_code}",
                "detail": response.text[:200]
            }, elapsed
    
    except Exception as e:
        elapsed = time.time() - start_time
        return {"error": str(e)}, elapsed


def print_separator(char="=", length=100):
    """Print a separator line."""
    print(char * length)


def print_result(method: str, query_info: Dict, result: Dict, elapsed: float):
    """Print formatted search result."""
    print(f"\n{'='*100}")
    print(f"🔍 METHOD: {method.upper()}")
    print(f"❓ QUERY: {query_info['query']}")
    print(f"📊 BEST FOR: {query_info['best_for'].upper()} ({query_info['description']})")
    print(f"⏱️  RESPONSE TIME: {elapsed:.2f}s")
    print(f"{'='*100}")
    
    if "error" in result:
        print(f"❌ ERROR: {result['error']}")
        if "detail" in result:
            print(f"   Detail: {result['detail']}")
        return
    
    # Print answer
    answer = result.get("answer", "No answer provided")
    print(f"\n📝 ANSWER:\n{answer}\n")
    
    # Print metadata
    confidence = result.get("confidence", 0.0)
    sources_count = len(result.get("sources", []))
    entities_count = len(result.get("entities_used", []))
    
    print(f"📈 METADATA:")
    print(f"   • Confidence: {confidence:.2f}")
    print(f"   • Sources used: {sources_count}")
    print(f"   • Entities used: {entities_count}")
    
    # Print entities (first 5)
    entities = result.get("entities_used", [])
    if entities:
        print(f"   • Top entities: {', '.join(entities[:5])}")
    
    # DRIFT-specific: reasoning path
    if method == "drift" and "reasoning_path" in result:
        reasoning = result["reasoning_path"]
        print(f"   • Reasoning iterations: {len(reasoning)}")
        if reasoning:
            print(f"   • Convergence: {reasoning[-1].get('convergence', 'N/A')}")


def compare_methods_for_query(query_info: Dict) -> Dict[str, Tuple[Dict, float]]:
    """
    Run the same query against all search methods.
    
    Returns:
        Dictionary mapping method name to (result, elapsed_time)
    """
    query = query_info["query"]
    log(f"Testing query: '{query}'")
    log(f"Expected best method: {query_info['best_for'].upper()}\n")
    
    results = {}
    
    for method in SEARCH_METHODS:
        log(f"  → Querying {method.upper()}...")
        result, elapsed = query_endpoint(method, query)
        results[method] = (result, elapsed)
        
        # Brief status
        if "error" in result:
            print(f"     ❌ Error: {result['error']}")
        else:
            confidence = result.get("confidence", 0.0)
            print(f"     ✅ {elapsed:.2f}s, confidence: {confidence:.2f}")
    
    return results


def print_comparison_summary(all_results: List[Dict]):
    """Print summary comparing all methods across all queries."""
    print("\n" + "="*100)
    print("📊 COMPARISON SUMMARY")
    print("="*100)
    
    # Performance comparison
    print("\n⏱️  AVERAGE RESPONSE TIME:")
    method_times = {method: [] for method in SEARCH_METHODS}
    
    for query_results in all_results:
        for method in SEARCH_METHODS:
            if method in query_results["results"]:
                _, elapsed = query_results["results"][method]
                method_times[method].append(elapsed)
    
    for method in SEARCH_METHODS:
        times = method_times[method]
        if times:
            avg_time = sum(times) / len(times)
            min_time = min(times)
            max_time = max(times)
            print(f"   • {method.upper():8s}: {avg_time:.2f}s (min: {min_time:.2f}s, max: {max_time:.2f}s)")
    
    # Confidence comparison
    print("\n📈 AVERAGE CONFIDENCE:")
    method_confidences = {method: [] for method in SEARCH_METHODS}
    
    for query_results in all_results:
        for method in SEARCH_METHODS:
            if method in query_results["results"]:
                result, _ = query_results["results"][method]
                if "confidence" in result:
                    method_confidences[method].append(result["confidence"])
    
    for method in SEARCH_METHODS:
        confidences = method_confidences[method]
        if confidences:
            avg_conf = sum(confidences) / len(confidences)
            print(f"   • {method.upper():8s}: {avg_conf:.2f}")
    
    # Use case recommendations
    print("\n💡 RECOMMENDATIONS:")
    print("   • LOCAL:  Fast entity lookups, specific definitions (e.g., 'What is X?')")
    print("   • GLOBAL: High-level themes, cross-document summaries (e.g., 'What are main topics?')")
    print("   • DRIFT:  Complex reasoning, multi-hop connections (e.g., 'How is A related to B?')")
    print("   • RAPTOR: Detailed content, specific fields/values (e.g., 'Extract dates and amounts')")


def main():
    """Run comprehensive search method comparison."""
    log("="*100)
    log("🚀 GraphRAG V3 Search Methods Comparison Test")
    log("="*100)
    log(f"   Base URL: {BASE_URL}")
    log(f"   Group ID: {GROUP_ID}")
    log(f"   Methods: {', '.join([m.upper() for m in SEARCH_METHODS])}")
    log(f"   Test queries: {len(TEST_QUERIES)}")
    log("="*100 + "\n")
    
    all_results = []
    
    # Run each test query against all methods
    for i, query_info in enumerate(TEST_QUERIES, 1):
        print(f"\n{'#'*100}")
        print(f"# TEST {i}/{len(TEST_QUERIES)}")
        print(f"{'#'*100}\n")
        
        results = compare_methods_for_query(query_info)
        
        # Print detailed results for each method
        for method in SEARCH_METHODS:
            if method in results:
                result, elapsed = results[method]
                print_result(method, query_info, result, elapsed)
        
        all_results.append({
            "query_info": query_info,
            "results": results
        })
        
        # Brief pause between queries
        if i < len(TEST_QUERIES):
            time.sleep(1)
    
    # Print summary comparison
    print_comparison_summary(all_results)
    
    # Final summary
    print("\n" + "="*100)
    log("✅ Comparison test completed!")
    print("="*100)


if __name__ == "__main__":
    main()
