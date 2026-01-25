"""
Voyage AI Embedding Service for V2 Contextual Chunking.

Uses Voyage AI models for contextual embeddings via the native voyageai client.

Key insight from docs.voyageai.com/docs/contextualized-chunk-embeddings:
- Contextual embeddings use contextualized_embed() method
- Input format: list of document chunks, where each document is a list of its chunks
- The chunks are embedded WITH AWARENESS of their document context
- Use input_type="document" for indexing, "query" for search

Configuration:
- Model: voyage-context-3 (the only model that supports contextualized_embed)
- Dimensions: 2048 (via output_dimension parameter)

See: VOYAGE_V2_CONTEXTUAL_CHUNKING_PLAN_2026-01-25.md
"""

import logging
from typing import List, Optional

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

# LlamaIndex wrapper for pipeline compatibility (v0.5.3 supports llama-index-core 0.14.x)
try:
    from llama_index.embeddings.voyageai import VoyageEmbedding
    LLAMAINDEX_VOYAGE_AVAILABLE = True
except ImportError:
    VoyageEmbedding = None  # type: ignore
    LLAMAINDEX_VOYAGE_AVAILABLE = False


class VoyageEmbedService:
    """
    Voyage AI embedding service with native contextual embedding support.
    
    Uses contextualized_embed() method for contextual embeddings as per Voyage API:
    https://docs.voyageai.com/docs/contextualized-chunk-embeddings
    
    The contextualized_embed() method:
    - Input: List[List[str]] - each inner list is all chunks from ONE document
    - Output: result.results[doc_idx].embeddings[chunk_idx]
    - Model: Only voyage-context-3 is supported for contextual embeddings
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize Voyage embedding service.
        
        Args:
            model_name: Voyage model name (default: from settings, voyage-context-3)
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
        self._client = voyageai.Client(api_key=self.api_key)  # type: ignore[union-attr]
        
        # LlamaIndex wrapper kept for legacy pipeline compatibility only
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
        # Dimension: 2048 for voyage-context-3 with output_dimension
        return settings.VOYAGE_EMBEDDING_DIM
    
    def embed_documents_contextualized(
        self,
        document_chunks: List[List[str]],
    ) -> List[List[List[float]]]:
        """
        Embed documents with contextual awareness using Voyage contextualized_embed.
        
        This is the PRIMARY method for V2 contextual chunking. It uses the 
        contextualized_embed() method which embeds chunks with awareness of
        their surrounding document context.
        
        Args:
            document_chunks: List of documents, where each document is a list
                           of its text chunks. E.g.:
                           [
                               ["chunk1 from doc1", "chunk2 from doc1"],
                               ["chunk1 from doc2", "chunk2 from doc2", "chunk3 from doc2"]
                           ]
            
        Returns:
            List of documents, where each document is a list of embedding vectors.
            E.g.: result[doc_idx][chunk_idx] = embedding vector (1024 dims)
        """
        result = self._client.contextualized_embed(
            inputs=document_chunks,
            model=self.model_name,
            input_type="document",
            output_dimension=settings.VOYAGE_EMBEDDING_DIM,
        )
        
        # Extract embeddings from result structure
        # result.results[doc_idx].embeddings[chunk_idx]
        all_embeddings = []
        for doc_result in result.results:
            all_embeddings.append(doc_result.embeddings)
        
        logger.debug(
            f"Contextual embedded {len(document_chunks)} documents with "
            f"{sum(len(doc) for doc in document_chunks)} total chunks "
            f"using Voyage ({self.model_name})"
        )
        
        return all_embeddings
    
    def embed_documents(
        self,
        texts: List[str],
        contexts: Optional[List[str]] = None,
    ) -> List[List[float]]:
        """
        Embed documents - wrapper for backward compatibility.
        
        If contexts are provided and match texts, this creates a "single document"
        with the chunks and uses contextualized_embed(). Otherwise falls back to
        standard embedding.
        
        For proper contextual embedding across multiple documents, use 
        embed_documents_contextualized() directly.
        
        Args:
            texts: List of text chunks to embed
            contexts: Ignored in new implementation (kept for API compatibility)
            
        Returns:
            List of embedding vectors
        """
        if contexts and len(contexts) == len(texts):
            # Treat all texts as chunks from a single document
            # This provides contextual awareness within the batch
            result = self.embed_documents_contextualized([texts])
            return result[0]  # Return the embeddings for the single document
        else:
            # Standard embedding - still use contextualized_embed for consistency
            result = self.embed_documents_contextualized([texts])
            return result[0]
    
    def embed_query(self, query: str) -> List[float]:
        """
        Embed a query string using contextualized_embed.
        
        Uses voyage-context-3 with input_type="query" for asymmetric search.
        Query is treated as a single-chunk document.
        
        Args:
            query: The search query to embed
            
        Returns:
            Embedding vector (2048 dimensions)
        """
        result = self._client.contextualized_embed(
            inputs=[[query]],  # Single document with single chunk
            model=self.model_name,
            input_type="query",
            output_dimension=settings.VOYAGE_EMBEDDING_DIM,
        )
        return result.results[0].embeddings[0]
    
    def embed_query_batch(self, queries: List[str]) -> List[List[float]]:
        """
        Embed multiple queries in a batch.
        
        Uses voyage-context-3 with input_type="query" for asymmetric search.
        Each query is treated as a single-chunk document.
        
        Args:
            queries: List of search queries to embed
            
        Returns:
            List of embedding vectors (2048 dimensions each)
        """
        # Each query as a separate single-chunk document
        inputs = [[q] for q in queries]
        result = self._client.contextualized_embed(
            inputs=inputs,
            model=self.model_name,
            input_type="query",
            output_dimension=settings.VOYAGE_EMBEDDING_DIM,
        )
        return [doc.embeddings[0] for doc in result.results]
    
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
