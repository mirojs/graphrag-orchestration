#!/usr/bin/env python3
"""
Test invoice consistency query on all KNN configurations via HTTP API.
Simple requests-based approach without complex dependencies.
"""

import json
import time
import sys

try:
    import requests
except ImportError:
    print("Installing requests...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

API_URL = "https://graphrag-orchestration-container.proudgrass-23d0c91d.eastus.azurecontainerapps.io/hybrid/query"

TEST_GROUPS = [
    {"name": "V2 Baseline", "group_id": "test-5pdfs-v2-1769609082", "edges": 806},
    {"name": "KNN Disabled", "group_id": "test-5pdfs-v2-knn-disabled", "edges": 0},
    {"name": "KNN-1 (K=3, 0.80)", "group_id": "test-5pdfs-v2-knn-1", "edges": 268},
    {"name": "KNN-2 (K=5, 0.75)", "group_id": "test-5pdfs-v2-knn-2", "edges": 476},
    {"name": "KNN-3 (K=5, 0.85)", "group_id": "test-5pdfs-v2-knn-3", "edges": 444},
]

QUERY = "Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms"


def count_inconsistencies(response_text):
    """Count likely inconsistencies in response."""
    count = 0
    for line in response_text.split('\n'):
        # Look for numbered lists or bullet points
        if any(marker in line for marker in ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.', '•', '-']):
            if any(word in line.lower() for word in ['invoice', 'contract', 'amount', 'quantity', 'price', 'item', 'inconsistenc', 'mismatch', 'discrepanc']):
                count += 1
    return count


def analyze_citations(citations):
    """Analyze citation relevance."""
    if not citations:
        return 0, 0, 0
    
    relevant = 0
    for citation in citations[:5]:
        text_preview = citation.get('text_preview', '').lower()
        if any(word in text_preview for word in ['invoice', 'contract', 'purchase', 'agreement']):
            relevant += 1
    
    total = min(len(citations), 5)
    relevance_pct = (relevant / total * 100) if total > 0 else 0
    return len(citations), relevant, relevance_pct


def test_group(name, group_id, edges):
    """Run query on a single group."""
    print("\n" + "="*70)
    print(f"🔬 Testing: {name}")
    print("="*70)
    print(f"  Group ID: {group_id}")
    print(f"  KNN Edges: {edges}")
    print()
    
    try:
        response = requests.post(
            API_URL,
            headers={
                "Content-Type": "application/json",
                "X-Group-ID": group_id
            },
            json={
                "query": QUERY,
                "force_route": "drift_multi_hop",
                "response_type": "summary"
            },
            timeout=180
        )
        
        if response.status_code != 200:
            print(f"❌ HTTP Error: {response.status_code}")
            print(response.text[:500])
            return None
        
        result = response.json()
        answer = result.get("response", "")
        route = result.get("route_used", "unknown")
        citations = result.get("citations", [])
        
        # Analysis
        inconsistencies = count_inconsistencies(answer)
        total_cites, relevant_cites, relevance_pct = analyze_citations(citations)
        
        print("✅ Query Complete")
        print(f"🛣️  Route: {route}")
        print(f"📊 Inconsistencies Found: {inconsistencies}")
        print(f"📚 Citations: {total_cites}")
        if total_cites > 0:
            print(f"  Relevance (top 5): {relevant_cites}/5 ({relevance_pct:.0f}%)")
        print()
        print("Response (first 800 chars):")
        print(answer[:800])
        if len(answer) > 800:
            print("...")
        print()
        
        # Save detailed result
        output_file = f"/tmp/knn_test_{name.replace(' ', '_').replace('(', '').replace(')', '')}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        
        return {
            "name": name,
            "group_id": group_id,
            "edges": edges,
            "route": route,
            "inconsistencies": inconsistencies,
            "citations": total_cites,
            "relevance_pct": relevance_pct
        }
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Network Error: {e}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("="*70)
    print("🧪 Testing Invoice Consistency Query on KNN Configurations")
    print("="*70)
    
    results = []
    for group in TEST_GROUPS:
        result = test_group(
            name=group["name"],
            group_id=group["group_id"],
            edges=group["edges"]
        )
        if result:
            results.append(result)
        time.sleep(3)  # Rate limiting
    
    # Summary
    print("\n" + "="*70)
    print("📊 Summary")
    print("="*70)
    print(f"{'Configuration':<25s} | {'Edges':>5s} | {'Inconsist':>10s} | {'Citations':>9s} | {'Relevance':>9s}")
    print("-" * 70)
    for r in results:
        print(f"{r['name']:<25s} | {r['edges']:>5d} | {r['inconsistencies']:>10d} | {r['citations']:>9d} | {r['relevance_pct']:>8.0f}%")
    print("="*70)
    
    # Save summary
    with open("/tmp/knn_test_summary.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n💾 Results saved to /tmp/knn_test_*.json")


if __name__ == "__main__":
    main()
