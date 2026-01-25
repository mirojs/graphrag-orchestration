"""
V2 Embeddings module for Voyage AI contextual embeddings.

This module provides the embedding service for V2 section-aware chunking
using voyage-context-3 (2048 dimensions).
"""

from app.hybrid_v2.embeddings.voyage_embed import (
    VoyageEmbedService,
    get_voyage_embed_service,
    is_voyage_v2_enabled,
)

__all__ = [
    "VoyageEmbedService",
    "get_voyage_embed_service",
    "is_voyage_v2_enabled",
]
