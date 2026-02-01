#!/usr/bin/env python3
"""
Index 5 Test PDFs with Different KNN Configurations

This script creates 4 test groups with different KNN settings to evaluate
optimal configuration for balancing noise reduction and semantic connectivity.

Usage:
    python3 scripts/index_5pdfs_knn_test.py
"""

import asyncio
import os
import sys
import time

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from src.core.config import settings
from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import (
    LazyGraphRAGIndexingPipeline,
    LazyGraphRAGIndexingConfig,
)
from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3
from src.worker.services.llm_service import LLMService

# 5 Test PDFs
PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS%20LIMITED%20WARRANTY.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf",
]

# Test configurations
TEST_CONFIGS = [
    {
        "name": "knn-disabled",
        "group_id": "test-5pdfs-v2-knn-disabled",
        "knn_enabled": False,
        "knn_top_k": 0,
        "knn_similarity_cutoff": 1.0,
    },
    {
        "name": "knn-1",
        "group_id": "test-5pdfs-v2-knn-1",
        "knn_enabled": True,
        "knn_top_k": 3,
        "knn_similarity_cutoff": 0.80,
    },
    {
        "name": "knn-2",
        "group_id": "test-5pdfs-v2-knn-2",
        "knn_enabled": True,
        "knn_top_k": 5,
        "knn_similarity_cutoff": 0.75,
    },
    {
        "name": "knn-3",
        "group_id": "test-5pdfs-v2-knn-3",
        "knn_enabled": True,
        "knn_top_k": 5,
        "knn_similarity_cutoff": 0.85,
    },
]


def log(msg):
    """Print with flush for real-time output"""
    print(msg, flush=True)


async def index_with_config(config: dict):
    """Index with specific KNN configuration."""
    group_id = config["group_id"]
    name = config["name"]
    
    log("\n" + "=" * 80)
    log(f"🔬 KNN TEST: {name}")
    log("=" * 80)
    log(f"  Group ID:    {group_id}")
    log(f"  KNN Enabled: {config['knn_enabled']}")
    log(f"  K:           {config['knn_top_k']}")
    log(f"  Cutoff:      {config['knn_similarity_cutoff']}")
    log("")
    
    # Initialize pipeline
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI or "",
        username=settings.NEO4J_USERNAME or "",
        password=settings.NEO4J_PASSWORD or "",
    )
    
    llm_service = LLMService()
    
    voyage_embedder = VoyageEmbedService(
        model_name=settings.VOYAGE_MODEL_NAME,
        api_key=settings.VOYAGE_API_KEY,
    )
    
    pipeline_config = LazyGraphRAGIndexingConfig(
        chunk_size=512,
        chunk_overlap=64,
        embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,
    )
    
    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
        embedder=voyage_embedder,
        config=pipeline_config,
        use_v2_embedding_property=True,
    )
    
    # Prepare documents
    documents = [{"source": url} for url in PDF_URLS]
    
    log("📄 Indexing 5 documents...")
    start_time = time.time()
    
    try:
        stats = await pipeline.index_documents(
            group_id=group_id,
            documents=documents,
            reindex=True,  # Always reindex for clean test
            ingestion="document-intelligence",
            run_community_detection=False,
            run_raptor=False,
            knn_enabled=config["knn_enabled"],
            knn_top_k=config["knn_top_k"],
            knn_similarity_cutoff=config["knn_similarity_cutoff"],
        )
        
        elapsed = time.time() - start_time
        
        log("")
        log("📊 Results:")
        log(f"  Documents:     {stats.get('documents', 0)}")
        log(f"  Chunks:        {stats.get('chunks', 0)}")
        log(f"  Entities:      {stats.get('entities', 0)}")
        log(f"  Relationships: {stats.get('relationships', 0)}")
        log(f"  GDS KNN Edges: {stats.get('gds_knn_edges', 0)}")
        log(f"  Communities:   {stats.get('gds_communities', 0)}")
        log(f"  Elapsed:       {elapsed:.1f}s")
        
        if stats.get("knn_config"):
            log(f"  KNN Config:    {stats['knn_config']}")
        
        log(f"✅ {name} complete")
        return {"name": name, "group_id": group_id, "stats": stats, "elapsed": elapsed}
        
    except Exception as e:
        log(f"❌ {name} failed: {e}")
        import traceback
        traceback.print_exc()
        return {"name": name, "group_id": group_id, "error": str(e)}


async def main():
    """Run all KNN test configurations."""
    log("=" * 80)
    log("🧪 KNN TUNING TEST SUITE")
    log("=" * 80)
    log("")
    log("This will create 4 test groups:")
    for cfg in TEST_CONFIGS:
        log(f"  • {cfg['name']}: {cfg['group_id']}")
    log("")
    
    # Verify V2 configuration
    if not settings.VOYAGE_V2_ENABLED:
        log("❌ VOYAGE_V2_ENABLED must be True")
        sys.exit(1)
    
    if not settings.VOYAGE_API_KEY:
        log("❌ VOYAGE_API_KEY not set")
        sys.exit(1)
    
    log("✅ V2 configuration verified")
    log("")
    
    # Run each configuration
    results = []
    for i, config in enumerate(TEST_CONFIGS, 1):
        log(f"\n[{i}/{len(TEST_CONFIGS)}] Starting {config['name']}...")
        result = await index_with_config(config)
        results.append(result)
    
    # Summary
    log("\n" + "=" * 80)
    log("📊 KNN TUNING TEST SUMMARY")
    log("=" * 80)
    for result in results:
        name = result["name"]
        if "error" in result:
            log(f"  ❌ {name}: FAILED - {result['error']}")
        else:
            knn_edges = result["stats"].get("gds_knn_edges", 0)
            elapsed = result["elapsed"]
            log(f"  ✅ {name}: {knn_edges} edges, {elapsed:.1f}s")
    
    log("\n" + "=" * 80)
    log("✅ ALL TESTS COMPLETE")
    log("=" * 80)
    log("\nNext steps:")
    log("  1. Run invoice consistency query on each group")
    log("  2. Run Q-D8 entity counting query on each group")
    log("  3. Compare results in decision matrix")
    log("")


if __name__ == "__main__":
    asyncio.run(main())
