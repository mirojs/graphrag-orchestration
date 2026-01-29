#!/usr/bin/env python3
"""
Test invoice consistency query on all KNN configurations using local route execution.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Setup paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, app_root)
os.chdir(app_root)

# Load env
load_dotenv(os.path.join(app_root, '.env'))

from app.core.config import settings
from app.hybrid_v2.orchestrator import HybridPipeline, DeploymentProfile
from app.hybrid_v2.router.main import QueryRoute

# Initialize LlamaIndex Azure OpenAI LLM
from llama_index.llms.azure_openai import AzureOpenAI as LlamaIndexAzureOpenAI
llm_client = LlamaIndexAzureOpenAI(
    engine=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version="2024-08-01-preview"
)

TEST_GROUPS = [
    {"name": "V2 Baseline", "group_id": "test-5pdfs-v2-1769609082", "edges": 403},
    {"name": "KNN Disabled", "group_id": "test-5pdfs-v2-knn-disabled", "edges": 0},
    {"name": "KNN-1 (K=3,0.80)", "group_id": "test-5pdfs-v2-knn-1", "edges": 208},
    {"name": "KNN-2 (K=5,0.75)", "group_id": "test-5pdfs-v2-knn-2", "edges": 379},
    {"name": "KNN-3 (K=5,0.85)", "group_id": "test-5pdfs-v2-knn-3", "edges": 350},
]

QUERY = "Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms"


def count_inconsistencies(response_text):
    """Count likely inconsistencies in response."""
    count = 0
    for line in response_text.split('\n'):
        if any(marker in line for marker in ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.', '•']):
            if any(word in line.lower() for word in ['invoice', 'contract', 'amount', 'quantity', 'price', 'item', 'inconsistenc', 'mismatch', 'discrepanc', 'lift', 'payment', 'door', 'cab']):
                count += 1
    return count


async def test_group(name, group_id, edges):
    """Run query on a single group."""
    print(f"\n{'='*70}")
    print(f"🔬 Testing: {name}")
    print(f"{'='*70}")
    print(f"  Group ID: {group_id}")
    print(f"  KNN Edges: {edges}")
    print()
    
    try:
        # Initialize pipeline with LLM
        pipeline = HybridPipeline(
            profile=DeploymentProfile.GENERAL_ENTERPRISE,
            llm_client=llm_client,
            group_id=group_id
        )
        
        # CRITICAL: Connect async Neo4j for PPR graph traversal
        await pipeline.initialize()
        
        # Run query with forced route
        result = await pipeline.force_route(
            query=QUERY,
            route=QueryRoute.DRIFT_MULTI_HOP,
            response_type="summary"
        )
        
        answer = result.get("response", "")
        route = result.get("route_used", "unknown")
        citations = result.get("citations", [])
        
        # Analysis
        inconsistencies = count_inconsistencies(answer)
        
        # Citation relevance
        relevant = 0
        for cite in citations[:5]:
            text = str(cite.get('text_preview', '') or cite.get('document_title', '')).lower()
            if any(word in text for word in ['invoice', 'contract', 'purchase', 'agreement', 'contoso', 'fabrikam']):
                relevant += 1
        total = min(len(citations), 5)
        relevance_pct = (relevant / total * 100) if total > 0 else 0
        
        print("✅ Query Complete")
        print(f"🛣️  Route: {route}")
        print(f"📊 Inconsistencies Found: {inconsistencies}")
        print(f"📚 Citations: {len(citations)}")
        if total > 0:
            print(f"  Relevance (top 5): {relevant}/{total} ({relevance_pct:.0f}%)")
        print()
        print("Response (first 1000 chars):")
        print(answer[:1000])
        if len(answer) > 1000:
            print("...")
        
        return {
            "name": name,
            "group_id": group_id,
            "edges": edges,
            "route": route,
            "inconsistencies": inconsistencies,
            "citations": len(citations),
            "relevance_pct": relevance_pct,
            "answer": answer
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {"name": name, "group_id": group_id, "edges": edges, "error": str(e)}


async def main():
    print("="*70)
    print("🧪 Testing Invoice Consistency Query on KNN Configurations")
    print("="*70)
    
    results = []
    for group in TEST_GROUPS:
        result = await test_group(
            name=group["name"],
            group_id=group["group_id"],
            edges=group["edges"]
        )
        results.append(result)
        await asyncio.sleep(2)
    
    # Summary
    print("\n" + "="*70)
    print("📊 SUMMARY")
    print("="*70)
    print(f"{'Configuration':<20s} | {'Edges':>5s} | {'Inconsist':>9s} | {'Citations':>9s} | {'Relevance':>9s}")
    print("-" * 70)
    for r in results:
        if "error" in r:
            print(f"{r['name']:<20s} | {r['edges']:>5d} | {'ERROR':>9s} |")
        else:
            print(f"{r['name']:<20s} | {r['edges']:>5d} | {r['inconsistencies']:>9d} | {r['citations']:>9d} | {r['relevance_pct']:>8.0f}%")
    print("="*70)
    
    # Save results
    import json
    with open("/tmp/knn_invoice_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\n💾 Results saved to /tmp/knn_invoice_results.json")


if __name__ == "__main__":
    asyncio.run(main())
