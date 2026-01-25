"""
Voyage AI Embedding Service for V2 Contextual Chunking.

Uses voyage-context-3 (2048 dimensions) via LlamaIndex.

This service provides contextual embeddings that understand document structure,
enabling better retrieval when chunks contain section context.

See: VOYAGE_V2_CONTEXTUAL_CHUNKING_PLAN_2026-01-25.md
"""

import logging
from typing import List, Optional

from llama_index.embeddings.voyageai import VoyageEmbedding

from app.core.config import settings

logger = logging.getLogger(__name__)


class VoyageEmbedService:
    """Voyage AI embedding service with contextual embedding support."""
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize Voyage embedding service.
        
        Args:
            model_name: Voyage model name (default: from settings)
            api_key: Voyage API key (default: from settings)
        """
        self.model_name = model_name or settings.VOYAGE_MODEL_NAME
        self.api_key = api_key or settings.VOYAGE_API_KEY
        
        if not self.api_key:
            raise ValueError(
                "VOYAGE_API_KEY is required for V2 embeddings. "
                "Set VOYAGE_API_KEY in environment or .env file."
            )
        
        self._embed_model = VoyageEmbedding(
            model_name=self.model_name,
            voyage_api_key=self.api_key,
        )
        
        logger.info(f"VoyageEmbedService initialized with model: {self.model_name}")
    
    @property
    def embed_dim(self) -> int:
        """Return embedding dimensions (2048 for voyage-context-3)."""
        return settings.VOYAGE_EMBEDDING_DIM
    
    def embed_documents(
        self,
        texts: List[str],
        contexts: Optional[List[str]] = None,
    ) -> List[List[float]]:
        """
        Embed documents with optional context.
        
        For section-aware chunking, the context parameter allows prepending
        section titles to chunks, improving retrieval for hierarchical documents.
        
        Args:
            texts: List of text chunks to embed
            contexts: Optional list of context strings (e.g., section titles)
            
        Returns:
            List of embedding vectors (2048 dimensions each)
        """
        if contexts:
            # Prepend context to each text for contextual embedding
            # This helps voyage-context-3 understand the semantic scope
            texts_with_context = [
                f"{ctx}:\n{text}" if ctx else text
                for ctx, text in zip(contexts, texts)
            ]
        else:
            texts_with_context = texts
        
        embeddings = self._embed_model.get_text_embedding_batch(texts_with_context)
        
        logger.debug(f"Embedded {len(texts)} documents with Voyage ({self.model_name})")
        return embeddings
    
    def embed_query(self, query: str) -> List[float]:
        """
        Embed a query string.
        
        Args:
            query: The search query to embed
            
        Returns:
            Embedding vector (2048 dimensions)
        """
        return self._embed_model.get_query_embedding(query)
    
    def get_llama_index_embed_model(self) -> VoyageEmbedding:
        """
        Get the underlying LlamaIndex VoyageEmbedding model.
        
        Useful for integration with LlamaIndex pipelines that expect
        an embed_model object.
        
        Returns:
            VoyageEmbedding instance
        """
        return self._embed_model


# Singleton instance for reuse across the application
_voyage_service: Optional[VoyageEmbedService] = None


def get_voyage_embed_service() -> VoyageEmbedService:
    """
    Get or create singleton VoyageEmbedService.
    
    This ensures we reuse the same service instance across the application,
    avoiding repeated initialization overhead.
    
    Returns:
        VoyageEmbedService singleton instance
        
    Raises:
        ValueError: If VOYAGE_API_KEY is not configured
    """
    global _voyage_service
    if _voyage_service is None:
        _voyage_service = VoyageEmbedService()
    return _voyage_service


def is_voyage_v2_enabled() -> bool:
    """
    Check if Voyage V2 pipeline is enabled.
    
    Returns:
        True if VOYAGE_V2_ENABLED=True and VOYAGE_API_KEY is set
    """
    return settings.VOYAGE_V2_ENABLED and bool(settings.VOYAGE_API_KEY)
