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
- Context Window: 32,000 tokens (requires bin-packing for large documents)

Bin-Packing Strategy (January 26, 2026):
- Large documents (>30K tokens) are split into bins that fit the context window
- NO OVERLAP needed between bins because the knowledge graph provides cross-bin connections:
  * Entities mentioned in multiple bins have graph edges connecting them
  * PPR traversal naturally hops across bins via MENTIONS_ENTITY edges
  * SHARES_ENTITY and RELATED_TO edges preserve semantic relationships
- Section coverage retrieval is retained as fallback for large documents

See: VOYAGE_V2_CONTEXTUAL_CHUNKING_PLAN_2026-01-25.md
     PROPOSED_NEO4J_DOC_TITLE_FIX_2026-01-26.md
"""

import logging
from typing import List, Optional

from src.core.config import settings
from src.core.services.usage_tracker import get_usage_tracker

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


# ============================================================================
# Bin-Packing Constants for Large Documents
# ============================================================================
# Voyage-context-3 has a 32K token context window for contextualized_embed()
# Leave headroom for safety (30K instead of 32K)
MAX_CONTEXT_TOKENS = 30000
# Approximate tokens per character (conservative estimate for English)
TOKENS_PER_CHAR_ESTIMATE = 0.25


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
                output_dimension=settings.VOYAGE_EMBEDDING_DIM,  # Must match native calls (2048)
            )
        
        logger.info(f"VoyageEmbedService initialized with model: {self.model_name}")
    
    @property
    def embed_dim(self) -> int:
        """Return embedding dimensions from config."""
        # Dimension: 2048 for voyage-context-3 with output_dimension
        return settings.VOYAGE_EMBEDDING_DIM
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for a text string.
        
        Uses character-based estimation (conservative for English).
        For production, consider using tiktoken or voyageai's tokenizer.
        
        Args:
            text: Input text string
            
        Returns:
            Estimated token count
        """
        return int(len(text) * TOKENS_PER_CHAR_ESTIMATE)
    
    def _bin_pack_chunks(
        self,
        chunks: List[str],
        max_context_tokens: int = MAX_CONTEXT_TOKENS,
    ) -> List[List[str]]:
        """
        Bin-pack chunks into groups that fit within Voyage's 32K context window.
        
        Strategy:
        - Each bin is treated as a separate "document" for contextualized_embed()
        - NO OVERLAP between bins (the knowledge graph provides cross-bin connections)
        - Graph advantages that replace traditional overlap:
          * Entities span bins via MENTIONS_ENTITY edges
          * PPR traversal hops across bins naturally
          * SHARES_ENTITY edges connect related chunks
        
        Args:
            chunks: List of text chunks from a single document
            max_context_tokens: Maximum tokens per bin (default: 30K with 2K headroom)
            
        Returns:
            List of bins, where each bin is a list of chunks
        """
        if not chunks:
            return []
        
        # Check if all chunks fit in one bin
        total_tokens = sum(self._estimate_tokens(c) for c in chunks)
        if total_tokens <= max_context_tokens:
            return [chunks]  # Single bin - no splitting needed
        
        # Bin-pack chunks (no overlap - graph provides cross-bin connections)
        bins: List[List[str]] = []
        current_bin: List[str] = []
        current_tokens = 0
        
        for chunk in chunks:
            chunk_tokens = self._estimate_tokens(chunk)
            
            # If this chunk alone exceeds the limit, it's a single-chunk bin
            if chunk_tokens > max_context_tokens:
                # Save current bin if non-empty
                if current_bin:
                    bins.append(current_bin)
                # Large chunk gets its own bin (will be truncated by API if needed)
                bins.append([chunk])
                current_bin = []
                current_tokens = 0
                logger.warning(
                    f"Chunk exceeds context window ({chunk_tokens} > {max_context_tokens} tokens). "
                    "Placed in separate bin - may lose some context."
                )
            elif current_tokens + chunk_tokens > max_context_tokens:
                # Start a new bin
                if current_bin:
                    bins.append(current_bin)
                current_bin = [chunk]
                current_tokens = chunk_tokens
            else:
                # Add to current bin
                current_bin.append(chunk)
                current_tokens += chunk_tokens
        
        # Don't forget the last bin
        if current_bin:
            bins.append(current_bin)
        
        if len(bins) > 1:
            logger.info(
                f"Large document bin-packed into {len(bins)} bins "
                f"({total_tokens} total tokens, {len(chunks)} chunks). "
                "Graph edges provide cross-bin connections (no overlap needed)."
            )
        
        return bins
    
    def embed_documents_contextualized(
        self,
        document_chunks: List[List[str]],
        group_id: Optional[str] = None,
        user_id: Optional[str] = None,
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
            group_id: Optional group ID for usage tracking
            user_id: Optional user ID for usage tracking
            
        Returns:
            List of documents, where each document is a list of embedding vectors.
            E.g.: result[doc_idx][chunk_idx] = embedding vector (1024 dims)
            
        Note on Large Documents:
            Documents exceeding the 32K token context window are automatically
            bin-packed into multiple batches. Each bin is embedded separately,
            then results are concatenated. Cross-bin context is preserved via
            the knowledge graph (no token overlap needed).
        """
        all_embeddings: List[List[List[float]]] = []
        total_tokens_used = 0
        total_chunks = 0
        
        for doc_chunks in document_chunks:
            # Check if document needs bin-packing
            bins = self._bin_pack_chunks(doc_chunks)
            total_chunks += len(doc_chunks)
            
            if len(bins) == 1:
                # Small document - single API call
                result = self._client.contextualized_embed(
                    inputs=[doc_chunks],
                    model=self.model_name,
                    input_type="document",
                    output_dimension=settings.VOYAGE_EMBEDDING_DIM,
                )
                all_embeddings.append(result.results[0].embeddings)
                # Track tokens used
                if hasattr(result, 'usage') and result.usage:
                    total_tokens_used += result.usage.total_tokens
            else:
                # Large document - embed each bin, concatenate results
                doc_embeddings: List[List[float]] = []
                for bin_idx, bin_chunks in enumerate(bins):
                    result = self._client.contextualized_embed(
                        inputs=[bin_chunks],
                        model=self.model_name,
                        input_type="document",
                        output_dimension=settings.VOYAGE_EMBEDDING_DIM,
                    )
                    doc_embeddings.extend(result.results[0].embeddings)
                    # Track tokens used
                    if hasattr(result, 'usage') and result.usage:
                        total_tokens_used += result.usage.total_tokens
                    logger.debug(
                        f"Embedded bin {bin_idx + 1}/{len(bins)} with {len(bin_chunks)} chunks"
                    )
                all_embeddings.append(doc_embeddings)
        
        # Log usage (fire-and-forget)
        if total_tokens_used > 0:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(get_usage_tracker().log_embedding_usage(
                    partition_id=group_id or "indexing",
                    model=self.model_name,
                    total_tokens=total_tokens_used,
                    dimensions=settings.VOYAGE_EMBEDDING_DIM,
                    chunk_count=total_chunks,
                    user_id=user_id,
                ))
            except Exception:
                pass  # Fire-and-forget: ignore failures
        
        logger.debug(
            f"Contextual embedded {len(document_chunks)} documents with "
            f"{total_chunks} total chunks ({total_tokens_used} tokens) "
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
    
    def embed_query(self, query: str, group_id: Optional[str] = None, user_id: Optional[str] = None) -> List[float]:
        """
        Embed a query string using contextualized_embed with usage tracking.
        
        Uses voyage-context-3 with input_type="query" for asymmetric search.
        Query is treated as a single-chunk document.
        
        Args:
            query: The search query to embed
            group_id: Optional group ID for usage tracking
            user_id: Optional user ID for usage tracking
            
        Returns:
            Embedding vector (2048 dimensions)
        """
        result = self._client.contextualized_embed(
            inputs=[[query]],  # Single document with single chunk
            model=self.model_name,
            input_type="query",
            output_dimension=settings.VOYAGE_EMBEDDING_DIM,
        )
        
        # Track usage (Voyage API returns usage in result)
        if hasattr(result, 'usage') and result.usage:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(get_usage_tracker().log_embedding_usage(
                    partition_id=group_id or "unknown",
                    model=self.model_name,
                    total_tokens=result.usage.total_tokens,
                    dimensions=settings.VOYAGE_EMBEDDING_DIM,
                    chunk_count=1,
                    user_id=user_id,
                ))
            except Exception:
                pass  # Fire-and-forget: ignore failures
        
        return result.results[0].embeddings[0]
    
    def embed_query_batch(self, queries: List[str], group_id: Optional[str] = None, user_id: Optional[str] = None) -> List[List[float]]:
        """
        Embed multiple queries in a batch with usage tracking.
        
        Uses voyage-context-3 with input_type="query" for asymmetric search.
        Each query is treated as a single-chunk document.
        
        Args:
            queries: List of search queries to embed
            group_id: Optional group ID for usage tracking
            user_id: Optional user ID for usage tracking
            
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
        
        # Track usage
        if hasattr(result, 'usage') and result.usage:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(get_usage_tracker().log_embedding_usage(
                    partition_id=group_id or "unknown",
                    model=self.model_name,
                    total_tokens=result.usage.total_tokens,
                    dimensions=settings.VOYAGE_EMBEDDING_DIM,
                    chunk_count=len(queries),
                    user_id=user_id,
                ))
            except Exception:
                pass  # Fire-and-forget: ignore failures
        
        return [doc.embeddings[0] for doc in result.results]
    
    async def aget_text_embedding_batch(
        self, 
        texts: List[str],
        show_progress: bool = False,
    ) -> List[List[float]]:
        """
        Async embedding method for LlamaIndex pipeline compatibility.
        
        Wraps embed_documents() in an async interface. This is required
        because the LazyGraphRAG pipeline uses async embedding calls.
        
        For V2 contextual embeddings, treats all texts as chunks from a
        single document, providing contextual awareness within the batch.
        
        Args:
            texts: List of text chunks to embed
            show_progress: Ignored (kept for API compatibility)
            
        Returns:
            List of embedding vectors (2048 dimensions each)
        """
        import asyncio
        
        # Run synchronous embedding in executor to avoid blocking
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self.embed_documents(texts)
        )
        return embeddings
    
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
