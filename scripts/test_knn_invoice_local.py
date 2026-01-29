#!/usr/bin/env python3
"""
Test invoice consistency query on all KNN configurations locally.

Runs Route 4 directly on all test groups.
"""

import asyncio
import os
import sys
import json
from dotenv import load_dotenv

# Load environment variables
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "graphrag-orchestration", ".env")
load_dotenv(env_path)

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, app_root)

from app.core.config import settings
from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3
from app.hybrid_v2.routes.route_4_drift import DRIFTHandler

# Test groups
TEST_GROUPS = [
    {"group_id": "test-5pdfs-v2-1769609082", "name": "V2 Baseline", "edges": 806},
    {"group_id": "test-5pdfs-v2-knn-disabled", "name": "KNN Disabled", "edges": 0},
    {"group_id": "test-5pdfs-v2-knn-1", "name": "KNN-1 (K=3, 0.80)", "edges": 268},
    {"group_id": "test-5pdfs-v2-knn-2", "name": "KNN-2 (K=5, 0.75)", "edges": 476},
    {"group_id": "test-5pdfs-v2-knn-3", "name": "KNN-3 (K=5, 0.85)", "edges": 444},
]

QUERY = "Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms"


async def test_group(group_id: str, group_name: str, edges: int):
    """Run invoice consistency query on a single group."""
    print(f"\n{'='*70}")
    print(f"🔬 Testing: {group_name}")
    print(f"{'='*70}")
    print(f"  Group ID: {group_id}")
    print(f"  KNN Edges: {edges}")
    print()
    
    try:
        # Initialize
        neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI or "",
            username=settings.NEO4J_USERNAME or "",
            password=settings.NEO4J_PASSWORD or "",
        )
        handler = DRIFTHandler(
            neo4j_store=neo4j_store,
            group_id=group_id
        )
        
        # Run query
        result = await handler.execute(
            query=QUERY,
            response_type="summary"
        )
        
        # Extract response
        answer = result.response
        
        # Count inconsistencies
        inconsistencies = 0
        if "inconsistenc" in answer.lower():
            # Look for numbered lists or bullet points
            lines = answer.split('\n')
            for line in lines:
                if any(c in line for c in ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.', '•', '-']):
                    if any(word in line.lower() for word in ['invoice', 'contract', 'amount', 'quantity', 'price', 'item']):
                        inconsistencies += 1
        
        print(f"✅ Query Complete")
        print(f"🛣️  Route: {result.route_used}")
        print(f"📊 Inconsistencies Found: {inconsistencies}")
        print()
        print("Response (first 800 chars):")
        print(answer[:800])
        print("..." if len(answer) > 800 else "")
        
        # Get source citations
        citations = result.citations
        if citations:
            print(f"\n📚 Citations: {len(citations)}")
            relevant = 0
            for i, citation in enumerate(citations[:5], 1):
                doc_id = citation.document_id
                score = citation.score
                # Check if citation is relevant (mentions invoice or contract)
                text_preview = citation.text_preview[:200].lower() if citation.text_preview else ""
                is_relevant = any(word in text_preview for word in ['invoice', 'contract', 'purchase', 'agreement'])
                relevant += 1 if is_relevant else 0
                relevance_mark = "✓" if is_relevant else "✗"
                print(f"  {relevance_mark} [{i}] {doc_id} (score: {score:.3f})")
            
            relevance_pct = (relevant / len(citations[:5])) * 100 if citations[:5] else 0
            print(f"\n  Relevance: {relevant}/{len(citations[:5])} ({relevance_pct:.0f}%)")
        
        return {
            "group_id": group_id,
            "name": group_name,
            "edges": edges,
            "route": result.route_used,
            "inconsistencies": inconsistencies,
            "citations": len(citations),
            "relevance_pct": relevance_pct if citations else 0,
            "answer": answer
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Test all groups."""
    print("="*70)
    print("🧪 Testing Invoice Consistency Query on KNN Configurations")
    print("="*70)
    
    results = []
    for group in TEST_GROUPS:
        result = await test_group(
            group_id=group["group_id"],
            group_name=group["name"],
            edges=group["edges"]
        )
        if result:
            results.append(result)
        
        # Small delay between tests
        await asyncio.sleep(2)
    
    # Summary
    print("\n" + "="*70)
    print("📊 Summary")
    print("="*70)
    print(f"{'Configuration':<20s} | {'Edges':>5s} | {'Inconsist':>10s} | {'Citations':>9s} | {'Relevance':>9s}")
    print("-" * 70)
    for r in results:
        print(f"{r['name']:<20s} | {r['edges']:>5d} | {r['inconsistencies']:>10d} | {r['citations']:>9d} | {r['relevance_pct']:>8.0f}%")
    print("="*70)
    
    # Save detailed results
    with open("/afh/projects/graphrag-orchestration/knn_invoice_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n💾 Detailed results saved to: knn_invoice_test_results.json")


if __name__ == "__main__":
    asyncio.run(main())
