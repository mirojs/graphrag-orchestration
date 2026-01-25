"""
Voyage AI Embedding Service for V2 Contextual Chunking.

Uses Voyage AI models for contextual embeddings via the native voyageai client.

Key insight from docs.voyageai.com/docs/contextualized-chunk-embeddings:
- Contextual embeddings use TUPLES: (chunk_text, document_context)
- The chunk is embedded WITH AWARENESS of the context
- Use input_type="document" for indexing, "query" for search

Configuration:
- Model and dimensions configured via settings (config.py)
- Default: voyage-3-large (2048 dimensions for better accuracy)

See: VOYAGE_V2_CONTEXTUAL_CHUNKING_PLAN_2026-01-25.md
"""

import logging
from typing import List, Optional, Tuple, Union

from app.core.config import settings

logger = logging.getLogger(__name__)

# Graceful import - module may not be installed yet
try:
    import voyageai
    VOYAGE_AVAILABLE = True
except ImportError:
    voyageai = None  # type: ignore
    VOYAGE_AVAILABLE = False
    logger.warning(
        "voyageai not installed. "
        "Install with: pip install voyageai"
    )

# Also try LlamaIndex wrapper for compatibility
try:
    from llama_index.embeddings.voyageai import VoyageEmbedding
    LLAMAINDEX_VOYAGE_AVAILABLE = True
except ImportError:
    VoyageEmbedding = None  # type: ignore
    LLAMAINDEX_VOYAGE_AVAILABLE = False


class VoyageEmbedService:
    """
    Voyage AI embedding service with native contextual embedding support.
    
    Uses tuples (chunk, context) for contextual embeddings as per Voyage API:
    https://docs.voyageai.com/docs/contextualized-chunk-embeddings
    """
    
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
        if not VOYAGE_AVAILABLE:
            raise ImportError(
                "voyageai is not installed. "
                "Install with: pip install voyageai"
            )
        
        self.model_name = model_name or settings.VOYAGE_MODEL_NAME
        self.api_key = api_key or settings.VOYAGE_API_KEY
        
        if not self.api_key:
            raise ValueError(
                "VOYAGE_API_KEY is required for V2 embeddings. "
                "Set VOYAGE_API_KEY in environment or .env file."
            )
        
        # Initialize native Voyage client for contextual embeddings
        self._client = voyageai.Client(api_key=self.api_key)
        
        # Also initialize LlamaIndex wrapper for pipeline compatibility
        self._embed_model = None
        if LLAMAINDEX_VOYAGE_AVAILABLE and VoyageEmbedding is not None:
            self._embed_model = VoyageEmbedding(
                model_name=self.model_name,
                voyage_api_key=self.api_key,
            )
        
        logger.info(f"VoyageEmbedService initialized with model: {self.model_name}")
    
    @property
    def embed_dim(self) -> int:
        """Return embedding dimensions from config."""
        # Dimension configured in settings.VOYAGE_EMBEDDING_DIM
        # Default: 2048 for voyage-3-large
        return settings.VOYAGE_EMBEDDING_DIM
    
    def embed_documents(
        self,
        texts: List[str],
        contexts: Optional[List[str]] = None,
    ) -> List[List[float]]:
        """
        Embed documents with optional context using native Voyage API.
        
        When contexts are provided, uses Voyage's contextual embedding feature
        with tuples (chunk, context) as documented at:
        https://docs.voyageai.com/docs/contextualized-chunk-embeddings
        
        Args:
            texts: List of text chunks to embed
            contexts: Optional list of document context strings
            
        Returns:
            List of embedding vectors
        """
        if contexts and len(contexts) == len(texts):
            # Use native contextual embedding with tuples
            # Format: [(chunk1, context1), (chunk2, context2), ...]
            texts_with_context: List[Tuple[str, str]] = [
                (text, ctx) for text, ctx in zip(texts, contexts)
            ]
            
            result = self._client.embed(
                texts=texts_with_context,  # type: ignore - Voyage accepts tuples
                model=self.model_name,
                input_type="document",
            )
            
            logger.debug(
                f"Contextual embedded {len(texts)} documents with Voyage ({self.model_name})"
            )
        else:
            # Standard embedding without context
            result = self._client.embed(
                texts=texts,
                model=self.model_name,
                input_type="document",
            )
            
            logger.debug(
                f"Embedded {len(texts)} documents with Voyage ({self.model_name})"
            )
        
        return result.embeddings
    
    def embed_query(self, query: str) -> List[float]:
        """
        Embed a query string.
        
        Uses input_type="query" for asymmetric search (doc vs query).
        
        Args:
            query: The search query to embed
            
        Returns:
            Embedding vector
        """
        result = self._client.embed(
            texts=[query],
            model=self.model_name,
            input_type="query",
        )
        return result.embeddings[0]
    
    def embed_query_batch(self, queries: List[str]) -> List[List[float]]:
        """
        Embed multiple queries in a batch.
        
        Args:
            queries: List of search queries to embed
            
        Returns:
            List of embedding vectors
        """
        result = self._client.embed(
            texts=queries,
            model=self.model_name,
            input_type="query",
        )
        return result.embeddings
    
    def get_llama_index_embed_model(self):
        """
        Get the LlamaIndex VoyageEmbedding model for pipeline compatibility.
        
        Note: The LlamaIndex wrapper doesn't support contextual embeddings
        with tuples. Use embed_documents() with contexts for that.
        
        Returns:
            VoyageEmbedding instance or None if not available
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
