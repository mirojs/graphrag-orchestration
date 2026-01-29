#!/usr/bin/env python3
"""
Test invoice consistency query on all KNN configurations.
Uses the production pipeline initialization pattern.
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
import structlog
logger = structlog.get_logger(__name__)

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


async def create_pipeline(group_id: str) -> HybridPipeline:
    """Create a properly initialized pipeline for the group."""
    from app.services import GraphService, LLMService
    from app.hybrid_v2.indexing.text_store import Neo4jTextUnitStore
    
    # LLM service
    llm_service = LLMService()
    llm_client = llm_service.get_synthesis_llm()
    
    # Graph service
    graph_store = None
    neo4j_driver = None
    try:
        graph_service = GraphService()
        graph_store = graph_service.get_store(group_id)
        neo4j_driver = graph_service.driver
    except Exception as e:
        logger.warning(f"Graph store unavailable: {e}")
    
    # V2 Voyage embedder
    embedding_client = None
    if settings.VOYAGE_V2_ENABLED and settings.VOYAGE_API_KEY:
        try:
            from app.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
            voyage_service = VoyageEmbedService()
            embedding_client = voyage_service.get_llama_index_model()
        except Exception as e:
            logger.warning(f"Voyage embedder failed: {e}")
    
    # Text store
    text_unit_store = None
    if neo4j_driver is not None:
        text_unit_store = Neo4jTextUnitStore(neo4j_driver, group_id=group_id)
    
    # Create pipeline
    pipeline = HybridPipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_client,
        embedding_client=embedding_client,
        hipporag_instance=None,
        graph_store=graph_store,
        text_unit_store=text_unit_store,
        neo4j_driver=neo4j_driver,
        graph_communities=None,
        relevance_budget=0.8,
        group_id=group_id,
    )
    
    # Initialize async resources
    await pipeline.initialize()
    
    return pipeline


async def test_group(name, group_id, edges):
    """Run query on a single group."""
    print(f"\n{'='*70}")
    print(f"🔬 Testing: {name}")
    print(f"{'='*70}")
    print(f"  Group ID: {group_id}")
    print(f"  KNN Edges: {edges}")
    print()
    
    try:
        # Create properly initialized pipeline
        pipeline = await create_pipeline(group_id)
        
        # Run query with forced route
        result = await pipeline.force_route(
            query=QUERY,
            route=QueryRoute.DRIFT_MULTI_HOP,
            response_type="summary"
        )
        
        # Cleanup
        await pipeline.close()
        
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
