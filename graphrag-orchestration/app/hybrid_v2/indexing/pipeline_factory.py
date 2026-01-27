"""LazyGraphRAG indexing pipeline wiring for the hybrid router.

This module intentionally owns the hybrid indexing wiring so `/hybrid/index/documents`
does not depend on the V3 API router (which previously caused accidental pipeline
coupling and production failures).

V2 Update: Added get_lazygraphrag_indexing_pipeline_v2() for Voyage embeddings.
See VOYAGE_V2_IMPLEMENTATION_PLAN_2026-01-25.md for context.
"""

from __future__ import annotations

from app.core.config import settings


_neo4j_store = None
_indexing_pipeline = None
_indexing_pipeline_v2 = None  # V2 pipeline with Voyage embeddings


def get_neo4j_store():
    global _neo4j_store
    if _neo4j_store is None:
        from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3

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
        from app.hybrid_v2.indexing.lazygraphrag_pipeline import (
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


def get_lazygraphrag_indexing_pipeline_v2():
    """
    Create (or reuse) the V2 indexing pipeline with Voyage embeddings.
    
    V2 uses:
    - voyage-3-large (2048 dimensions) instead of text-embedding-3-large (3072)
    - Contextual embeddings with tuples (chunk, context) per Voyage API
    - Section-aware chunking from cu_standard_ingestion_service_v2.py
    - Stores embeddings in `embedding_v2` property for parallel operation
    
    Docs: https://docs.voyageai.com/docs/contextualized-chunk-embeddings
    Ref: VOYAGE_V2_IMPLEMENTATION_PLAN_2026-01-25.md
    """
    global _indexing_pipeline_v2

    if _indexing_pipeline_v2 is None:
        from app.services.llm_service import LLMService
        from app.hybrid_v2.indexing.lazygraphrag_pipeline import (
            LazyGraphRAGIndexingConfig,
            LazyGraphRAGIndexingPipeline,
        )
        from app.hybrid_v2.embeddings import get_voyage_embed_service, is_voyage_v2_enabled

        store = get_neo4j_store()
        llm_service = LLMService()

        # V2 config: Voyage dimensions (2048 for better accuracy)
        config = LazyGraphRAGIndexingConfig(
            chunk_size=1500,  # Section-aware: larger chunks (section boundaries)
            chunk_overlap=50,  # Overlap for split sections
            embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,  # 2048
        )

        # Get Voyage embedder if enabled, otherwise fallback to OpenAI
        embedder = None
        if is_voyage_v2_enabled():
            try:
                voyage_service = get_voyage_embed_service()
                embedder = voyage_service.get_llama_index_embed_model()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"V2 Voyage embedder init failed, falling back to OpenAI: {e}"
                )
                embedder = llm_service.embed_model
        else:
            embedder = llm_service.embed_model

        _indexing_pipeline_v2 = LazyGraphRAGIndexingPipeline(
            neo4j_store=store,
            llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
            embedder=embedder,
            config=config,
            # V2 flag: store in embedding_v2 property
            use_v2_embedding_property=True,
        )

    return _indexing_pipeline_v2
