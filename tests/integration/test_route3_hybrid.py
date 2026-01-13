import os
import sys
import pathlib
import pytest

# Ensure inner package dir is on PYTHONPATH for test discovery
root = pathlib.Path(__file__).resolve().parents[2]
# inner package folder (where 'app' package lives)
pkg_dir = root / "graphrag-orchestration"
if pkg_dir.exists():
    sys.path.insert(0, str(pkg_dir))
else:
    # fallback: add repo root
    sys.path.insert(0, str(root))

from app.services.graph_service import GraphService
from app.services.llm_service import LLMService
from app.hybrid.orchestrator import HybridPipeline


def _default_group_id() -> str:
    env = os.environ.get("TEST_GROUP_ID") or os.environ.get("GROUP_ID")
    if env:
        return env
    try:
        p = root / "last_test_group_id.txt"
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            if s:
                return s
    except Exception:
        pass
    return "test-5pdfs-latest"


@pytest.mark.integration
def test_cypher25_hybrid_rrf_basic():
    """Integration test: ensure Cypher25 BM25+Vector RRF returns results."""
    graph_service = GraphService()
    if graph_service.driver is None:
        pytest.skip("Neo4j driver not configured")

    llm_service = LLMService()
    if llm_service.embed_model is None:
        pytest.skip("Embedding model not configured")

    group_id = _default_group_id()

    pipeline = HybridPipeline(
        neo4j_driver=graph_service.driver,
        llm_client=llm_service.llm,
        embedding_client=llm_service.embed_model,
        group_id=group_id,
    )

    # ensure async resources are ready
    import asyncio

    async def _run():
        await pipeline.initialize()
        try:
            query = "compliance requirements"
            embedding = llm_service.embed_model.get_text_embedding(query)
            results = await pipeline._search_chunks_cypher25_hybrid_rrf(
                query_text=query,
                embedding=embedding,
                top_k=5,
                vector_k=25,
                bm25_k=25,
                use_phrase_boost=True,
            )
            # results are list of tuples (chunk, rrf_score, is_anchor)
            assert isinstance(results, list)
            assert len(results) > 0, "Expected at least one hybrid result"

            # Check rrf_score present and monotonic descending
            scores = [r[1] for r in results]
            assert all(s >= 0 for s in scores)
            assert scores == sorted(scores, reverse=True)
        finally:
            await pipeline.close()

    asyncio.get_event_loop().run_until_complete(_run())
