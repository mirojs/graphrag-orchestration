"""
V2 Embeddings module for Voyage AI contextual embeddings.

This module provides the embedding service for V2 section-aware chunking
using voyage-3-large (2048 dimensions) with native contextual embedding support.

Key feature: Uses tuples (chunk, context) for contextual embeddings.
Docs: https://docs.voyageai.com/docs/contextualized-chunk-embeddings
"""

from src.worker.hybrid_v2.embeddings.voyage_embed import (
    VoyageEmbedService,
    get_voyage_embed_service,
    is_voyage_v2_enabled,
    VOYAGE_AVAILABLE,
)

__all__ = [
    "VoyageEmbedService",
    "get_voyage_embed_service",
    "is_voyage_v2_enabled",
    "VOYAGE_AVAILABLE",
]
