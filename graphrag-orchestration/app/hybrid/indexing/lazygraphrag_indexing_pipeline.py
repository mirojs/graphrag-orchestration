"""LazyGraphRAG indexing pipeline wiring for the hybrid router.

This module intentionally owns the hybrid indexing wiring so `/hybrid/index/documents`
does not depend on the V3 API router (which previously caused accidental pipeline
coupling and production failures).

V2 Mode (January 26, 2026):
When VOYAGE_V2_ENABLED=true, the pipeline uses:
- Voyage voyage-context-3 embeddings (2048 dim)
- Contextual chunking (chunks embedded with document context awareness)
- Stores embeddings in `embedding_v2` property on TextChunk nodes
- Universal multilingual support (CJK, Arabic, Hindi, Thai, Cyrillic, Greek, etc.)
"""

from __future__ import annotations

import logging
from app.core.config import settings


logger = logging.getLogger(__name__)

_neo4j_store = None
_indexing_pipeline = None
_indexing_pipeline_v2 = None  # V2 with Voyage embeddings


def get_neo4j_store():
    global _neo4j_store
    if _neo4j_store is None:
        from app.hybrid.services.neo4j_store import Neo4jStoreV3

        _neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI or "",
            username=settings.NEO4J_USERNAME or "",
            password=settings.NEO4J_PASSWORD or "",
        )
    return _neo4j_store


def _is_v2_enabled() -> bool:
    """Check if V2 Voyage embeddings are enabled."""
    return settings.VOYAGE_V2_ENABLED and bool(settings.VOYAGE_API_KEY)


def get_lazygraphrag_indexing_pipeline():
    """Create (or reuse) the indexing pipeline used by the hybrid LazyGraphRAG system.
    
    When VOYAGE_V2_ENABLED=true and VOYAGE_API_KEY is set, uses V2 pipeline with:
    - Voyage voyage-context-3 embeddings (2048 dimensions)
    - Contextual chunking (chunks are embedded with document context awareness)
    - Embeddings stored in `embedding_v2` property
    - Universal multilingual entity canonicalization
    
    Otherwise, uses the standard V1 pipeline with Azure OpenAI embeddings.
    """
    global _indexing_pipeline, _indexing_pipeline_v2
    
    # Check if V2 mode is enabled
    if _is_v2_enabled():
        return _get_v2_indexing_pipeline()
    else:
        return _get_v1_indexing_pipeline()


def _get_v1_indexing_pipeline():
    """Get V1 indexing pipeline (Azure OpenAI embeddings)."""
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
        
        logger.info("V1 indexing pipeline initialized (Azure OpenAI embeddings)")

    return _indexing_pipeline


def _get_v2_indexing_pipeline():
    """Get V2 indexing pipeline (Voyage contextual embeddings).
    
    Uses voyage-context-3 model with contextualized_embed() for:
    - 2048-dimension embeddings
    - Document context awareness (chunks know their surrounding context)
    - Universal multilingual support
    - Bin-packing for large documents (>32K tokens)
    """
    global _indexing_pipeline_v2

    if _indexing_pipeline_v2 is None:
        from app.services.llm_service import LLMService
        from app.hybrid_v2.indexing.lazygraphrag_pipeline import (
            LazyGraphRAGIndexingConfig,
            LazyGraphRAGIndexingPipeline,
        )
        from app.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
        from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3 as Neo4jStoreV2

        # Use V2 Neo4j store (supports embedding_v2 property)
        store = Neo4jStoreV2(
            uri=settings.NEO4J_URI or "",
            username=settings.NEO4J_USERNAME or "",
            password=settings.NEO4J_PASSWORD or "",
        )
        
        llm_service = LLMService()
        
        # Create Voyage embedding service
        voyage_embedder = VoyageEmbedService(
            model_name=settings.VOYAGE_MODEL_NAME,
            api_key=settings.VOYAGE_API_KEY,
        )

        config = LazyGraphRAGIndexingConfig(
            chunk_size=512,
            chunk_overlap=64,
            embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,  # 2048 for voyage-context-3
        )

        # V2 pipeline with Voyage embeddings stored in embedding_v2 property
        _indexing_pipeline_v2 = LazyGraphRAGIndexingPipeline(
            neo4j_store=store,
            llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
            embedder=voyage_embedder,
            config=config,
            use_v2_embedding_property=True,  # Store in embedding_v2
        )
        
        logger.info(
            "V2 indexing pipeline initialized",
            extra={
                "embeddings": "voyage-context-3",
                "dimensions": settings.VOYAGE_EMBEDDING_DIM,
                "property": "embedding_v2",
            }
        )

    return _indexing_pipeline_v2
