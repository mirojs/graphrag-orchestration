#!/usr/bin/env python3
"""
Run GDS KNN on already-indexed groups.

This script runs the GDS algorithms (KNN, Louvain, PageRank) on groups
that were indexed but didn't get GDS processing due to session expiry.

Usage:
    python3 scripts/run_gds_knn.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "graphrag-orchestration", ".env")
load_dotenv(env_path)

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, app_root)

from app.core.config import settings
from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3
from app.hybrid_v2.indexing.lazygraphrag_pipeline import LazyGraphRAGIndexingPipeline

# Test groups with their KNN configurations
TEST_GROUPS = [
    {"group_id": "test-5pdfs-v2-knn-disabled", "knn_top_k": 0, "knn_cutoff": 1.0},
    {"group_id": "test-5pdfs-v2-knn-1", "knn_top_k": 3, "knn_cutoff": 0.80},
    {"group_id": "test-5pdfs-v2-knn-2", "knn_top_k": 5, "knn_cutoff": 0.75},
    {"group_id": "test-5pdfs-v2-knn-3", "knn_top_k": 5, "knn_cutoff": 0.85},
]


def log(msg):
    print(msg, flush=True)


async def run_gds_for_group(group_id: str, knn_top_k: int, knn_cutoff: float):
    """Run GDS algorithms for a specific group."""
    log(f"\n{'='*70}")
    log(f"🔬 Running GDS for: {group_id}")
    log(f"{'='*70}")
    log(f"  K: {knn_top_k}, Cutoff: {knn_cutoff}")
    
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI or "",
        username=settings.NEO4J_USERNAME or "",
        password=settings.NEO4J_PASSWORD or "",
    )
    
    # Create a minimal pipeline just to access _run_gds_graph_algorithms
    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=None,
        embedder=None,
        config=None,
        use_v2_embedding_property=True,
    )
    
    try:
        stats = await pipeline._run_gds_graph_algorithms(
            group_id=group_id,
            knn_top_k=knn_top_k,
            knn_similarity_cutoff=knn_cutoff,
        )
        
        log(f"  ✅ GDS Complete:")
        log(f"     KNN Edges: {stats.get('knn_edges', 0)}")
        log(f"     Entity Edges: {stats.get('entity_edges', 0)}")
        log(f"     Communities: {stats.get('communities', 0)}")
        log(f"     PageRank Nodes: {stats.get('pagerank_nodes', 0)}")
        
        return {"group_id": group_id, "success": True, "stats": stats}
        
    except Exception as e:
        log(f"  ❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return {"group_id": group_id, "success": False, "error": str(e)}


async def main():
    log("="*70)
    log("🔬 Running GDS KNN on Test Groups")
    log("="*70)
    
    results = []
    for config in TEST_GROUPS:
        result = await run_gds_for_group(
            config["group_id"],
            config["knn_top_k"],
            config["knn_cutoff"]
        )
        results.append(result)
    
    log(f"\n{'='*70}")
    log("📊 Summary")
    log("="*70)
    for result in results:
        if result["success"]:
            edges = result["stats"].get("knn_edges", 0)
            log(f"  ✅ {result['group_id']}: {edges} KNN edges")
        else:
            log(f"  ❌ {result['group_id']}: {result['error']}")
    
    log("="*70)


if __name__ == "__main__":
    asyncio.run(main())
