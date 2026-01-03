"""LazyGraphRAG indexing pipeline wiring for the hybrid router.

This module intentionally owns the hybrid indexing wiring so `/hybrid/index/documents`
does not depend on the V3 API router (which previously caused accidental pipeline
coupling and production failures).
"""

from __future__ import annotations

from app.core.config import settings


_neo4j_store = None
_indexing_pipeline = None
_drift_adapter = None


def get_neo4j_store():
    global _neo4j_store
    if _neo4j_store is None:
        from app.v3.services.neo4j_store import Neo4jStoreV3

        _neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI or "",
            username=settings.NEO4J_USERNAME or "",
            password=settings.NEO4J_PASSWORD or "",
        )
    return _neo4j_store


def get_lazygraphrag_indexing_pipeline():
    """Create (or reuse) the indexing pipeline used by the hybrid LazyGraphRAG system."""
    global _indexing_pipeline

    if _indexing_pipeline is None:
        from app.services.llm_service import LLMService
        from app.hybrid.indexing.lazygraphrag_pipeline import (
            LazyGraphRAGIndexingConfig,
            LazyGraphRAGIndexingPipeline,
        )

        store = get_neo4j_store()
        llm_service = LLMService()

        config = LazyGraphRAGIndexingConfig(
            chunk_size=512,
            chunk_overlap=64,
            embedding_dimensions=settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS,
        )

        # Best-effort: allow hybrid indexing to run even when LLM/embeddings are not configured.
        # This keeps the endpoint usable for chunk-only indexing in constrained environments.
        _indexing_pipeline = LazyGraphRAGIndexingPipeline(
            neo4j_store=store,
            llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
            embedder=llm_service.embed_model,
            config=config,
        )

    return _indexing_pipeline


def get_lazygraphrag_drift_adapter():
    """DRIFT cache adapter used by hybrid indexing to avoid stale post-index results."""
    global _drift_adapter

    if _drift_adapter is None:
        from app.services.llm_service import LLMService
        from app.v3.services.drift_adapter import DRIFTAdapter

        store = get_neo4j_store()
        llm_service = LLMService()

        _drift_adapter = DRIFTAdapter(
            neo4j_driver=store.driver,
            llm=llm_service.llm,
            embedder=llm_service.embed_model,
        )

    return _drift_adapter
