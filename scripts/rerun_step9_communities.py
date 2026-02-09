#!/usr/bin/env python3
"""Re-run Step 9 (Louvain community materialization) without full reindex.

Usage:
    python3 scripts/rerun_step9_communities.py --group test-5pdfs-v2-fix2
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, project_root)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(app_root, ".env"))

from src.core.config import settings  # noqa: E402


async def main(group_id: str, min_community_size: int = 2) -> None:
    from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import (
        LazyGraphRAGIndexingPipeline,
        LazyGraphRAGIndexingConfig,
    )
    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
    from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3
    from src.worker.services.llm_service import LLMService

    print(f"🎯 Re-running Step 9 for group: {group_id}")
    print(f"   min_community_size: {min_community_size}")
    print()

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

    config = LazyGraphRAGIndexingConfig(
        chunk_size=512,
        chunk_overlap=64,
        embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,
    )

    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
        embedder=voyage_embedder,
        config=config,
        use_v2_embedding_property=True,
    )

    print(f"   LLM available: {bool(pipeline.llm)}")
    print(f"   Embedder available: {bool(pipeline.embedder)}")
    print()

    t0 = time.time()
    stats = await pipeline._materialize_louvain_communities(
        group_id=group_id,
        min_community_size=min_community_size,
    )
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print("📊 Step 9 Results")
    print("=" * 60)
    print(f"  Communities created:  {stats.get('communities_created', 0)}")
    print(f"  Summaries generated:  {stats.get('summaries_generated', 0)}")
    print(f"  Embeddings stored:    {stats.get('embeddings_stored', 0)}")
    print(f"  Elapsed:              {elapsed:.1f}s")
    print("=" * 60)

    neo4j_store.driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-run Step 9 community materialization")
    parser.add_argument("--group", required=True, help="Group ID")
    parser.add_argument("--min-size", type=int, default=2, help="Min community size (default: 2)")
    args = parser.parse_args()

    asyncio.run(main(args.group, args.min_size))
