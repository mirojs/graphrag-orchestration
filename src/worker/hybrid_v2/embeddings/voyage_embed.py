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

import asyncio
import logging
import threading
from typing import List, Optional

from src.core.config import settings
from src.core.services.usage_tracker import get_usage_tracker

logger = logging.getLogger(__name__)

# Strong references for fire-and-forget background tasks (prevent GC)
_background_tasks: set = set()

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
# Approximate tokens per character.  0.30 is conservative for mixed
# English/table/numeric content where token density is higher.
TOKENS_PER_CHAR_ESTIMATE = 0.30

# ============================================================================
# API Batch Limits (per contextualized_embed() call)
# ============================================================================
# See: https://docs.voyageai.com/docs/contextualized-chunk-embeddings
MAX_API_INPUTS = 1000       # Max inner lists (documents/bins) per call
MAX_API_TOTAL_TOKENS = 110000  # Conservative limit (API allows 120K)
MAX_API_TOTAL_CHUNKS = 16000   # Max chunks across all inputs per call


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
        
        # Retry configuration for transient API failures
        self._max_retries = 3
        self._base_delay = 1.0  # seconds, exponential backoff base
        
        # LlamaIndex wrapper kept for legacy pipeline compatibility only
        self._embed_model = None
        if LLAMAINDEX_VOYAGE_AVAILABLE and VoyageEmbedding is not None:
            self._embed_model = VoyageEmbedding(
                model_name=self.model_name,
                voyage_api_key=self.api_key,
                output_dimension=settings.VOYAGE_EMBEDDING_DIM,  # Must match native calls (2048)
            )
        
        logger.info(f"VoyageEmbedService initialized with model: {self.model_name}")

    def _call_with_retry(self, **kwargs):
        """Call Voyage contextualized_embed with retry + exponential backoff.

        Retries on transient errors (rate limits, server errors, timeouts).
        Non-retryable errors (e.g., invalid API key) are raised immediately.
        """
        import time as _time

        last_exc = None
        for attempt in range(self._max_retries):
            try:
                return self._client.contextualized_embed(**kwargs)
            except Exception as e:
                last_exc = e
                err_msg = str(e).lower()
                is_retryable = any(k in err_msg for k in (
                    "rate limit", "429", "500", "502", "503", "504",
                    "timeout", "connection", "reset by peer", "server error",
                ))
                if not is_retryable or attempt >= self._max_retries - 1:
                    raise
                delay = self._base_delay * (2 ** attempt)
                logger.warning(
                    "Voyage API transient error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, self._max_retries, delay, e,
                )
                _time.sleep(delay)
        raise last_exc  # pragma: no cover
    
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
            
            # If this chunk alone exceeds the limit, truncate it to fit
            if chunk_tokens > max_context_tokens:
                # Save current bin if non-empty
                if current_bin:
                    bins.append(current_bin)
                # Truncate chunk to fit within context window
                max_chars = int(max_context_tokens / TOKENS_PER_CHAR_ESTIMATE)
                truncated = chunk[:max_chars]
                bins.append([truncated])
                current_bin = []
                current_tokens = 0
                logger.warning(
                    f"Chunk truncated to fit context window ({chunk_tokens} > {max_context_tokens} tokens, "
                    f"kept {max_chars} chars)."
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
        
        Per the Voyage AI docs, all documents are passed in a single API call
        (or batched into a few calls respecting API limits). Each inner list
        represents one document's chunks:
            inputs = [["doc1_s1", "doc1_s2"], ["doc2_s1", "doc2_s2", "doc2_s3"]]
        
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
            bin-packed into multiple bins. Each bin becomes a separate input in
            the API call, then results are concatenated. Cross-bin context is
            preserved via the knowledge graph (no token overlap needed).
        """
        total_chunks = sum(len(dc) for dc in document_chunks)

        # Phase 1: Bin-pack large documents, track mapping
        # Each entry: (original_doc_idx, bin_chunks)
        effective_inputs: List[tuple] = []
        for doc_idx, doc_chunks in enumerate(document_chunks):
            bins = self._bin_pack_chunks(doc_chunks)
            for bin_chunks in bins:
                effective_inputs.append((doc_idx, bin_chunks))

        # Phase 2: Batch effective inputs into API calls respecting limits
        batches: List[List[int]] = []  # Each batch is list of indices into effective_inputs
        current_batch: List[int] = []
        current_tokens = 0
        current_chunks = 0

        for ei_idx, (_, bin_chunks) in enumerate(effective_inputs):
            bin_tokens = sum(self._estimate_tokens(c) for c in bin_chunks)
            bin_chunk_count = len(bin_chunks)

            would_exceed = (
                len(current_batch) + 1 > MAX_API_INPUTS
                or current_tokens + bin_tokens > MAX_API_TOTAL_TOKENS
                or current_chunks + bin_chunk_count > MAX_API_TOTAL_CHUNKS
            )

            if would_exceed and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
                current_chunks = 0

            current_batch.append(ei_idx)
            current_tokens += bin_tokens
            current_chunks += bin_chunk_count

        if current_batch:
            batches.append(current_batch)

        # Phase 3: Call API once per batch (ideally just 1 call)
        effective_embeddings: List[Optional[List[List[float]]]] = [None] * len(effective_inputs)
        total_tokens_used = 0

        for batch_idx, batch in enumerate(batches):
            inputs = [effective_inputs[i][1] for i in batch]
            result = self._call_with_retry(
                inputs=inputs,
                model=self.model_name,
                input_type="document",
                output_dimension=settings.VOYAGE_EMBEDDING_DIM,
            )

            # Map results back using the index field for safety
            for result_item in result.results:
                ei_idx = batch[result_item.index]
                effective_embeddings[ei_idx] = result_item.embeddings

            if hasattr(result, 'usage') and result.usage:
                total_tokens_used += result.usage.total_tokens

            if len(batches) > 1:
                logger.debug(
                    f"Embedded batch {batch_idx + 1}/{len(batches)} "
                    f"with {len(inputs)} document inputs"
                )

        # Phase 4: Reassemble by original document (maintain chunk order)
        all_embeddings: List[List[List[float]]] = [[] for _ in document_chunks]
        for ei_idx, (doc_idx, _) in enumerate(effective_inputs):
            if effective_embeddings[ei_idx] is not None:
                all_embeddings[doc_idx].extend(effective_embeddings[ei_idx])
        
        # Log usage (fire-and-forget)
        if total_tokens_used > 0:
            try:
                loop = asyncio.get_event_loop()
                task = loop.create_task(get_usage_tracker().log_embedding_usage(
                    partition_id=group_id or "indexing",
                    model=self.model_name,
                    total_tokens=total_tokens_used,
                    dimensions=settings.VOYAGE_EMBEDDING_DIM,
                    chunk_count=total_chunks,
                    user_id=user_id,
                ))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            except Exception:
                pass  # Fire-and-forget: ignore failures
        
        logger.debug(
            f"Contextual embedded {len(document_chunks)} documents with "
            f"{total_chunks} total chunks ({total_tokens_used} tokens) "
            f"in {len(batches)} API call(s) using Voyage ({self.model_name})"
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
            # Independent texts — batch into groups that fit within context window
            # to avoid exceeding voyage-context-3's 32K token limit
            bins = self._bin_pack_chunks(texts)
            if len(bins) == 1:
                result = self.embed_documents_contextualized([bins[0]])
                return result[0]
            else:
                all_embeddings: List[List[float]] = []
                result = self.embed_documents_contextualized(bins)
                for bin_embeddings in result:
                    all_embeddings.extend(bin_embeddings)
                return all_embeddings
    
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
        result = self._call_with_retry(
            inputs=[[query]],  # Single document with single chunk
            model=self.model_name,
            input_type="query",
            output_dimension=settings.VOYAGE_EMBEDDING_DIM,
        )
        
        # Track usage (Voyage API returns usage in result)
        if hasattr(result, 'usage') and result.usage:
            try:
                loop = asyncio.get_event_loop()
                task = loop.create_task(get_usage_tracker().log_embedding_usage(
                    partition_id=group_id or "unknown",
                    model=self.model_name,
                    total_tokens=result.usage.total_tokens,
                    dimensions=settings.VOYAGE_EMBEDDING_DIM,
                    chunk_count=1,
                    user_id=user_id,
                ))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
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
        result = self._call_with_retry(
            inputs=inputs,
            model=self.model_name,
            input_type="query",
            output_dimension=settings.VOYAGE_EMBEDDING_DIM,
        )
        
        # Track usage
        if hasattr(result, 'usage') and result.usage:
            try:
                loop = asyncio.get_event_loop()
                task = loop.create_task(get_usage_tracker().log_embedding_usage(
                    partition_id=group_id or "unknown",
                    model=self.model_name,
                    total_tokens=result.usage.total_tokens,
                    dimensions=settings.VOYAGE_EMBEDDING_DIM,
                    chunk_count=len(queries),
                    user_id=user_id,
                ))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            except Exception:
                pass  # Fire-and-forget: ignore failures
        
        return [doc.embeddings[0] for doc in result.results]
    
    def embed_independent_texts(
        self,
        texts: List[str],
        group_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[List[float]]:
        """
        Embed texts independently — each text as its own single-chunk document.
        
        Unlike embed_documents() which treats all texts as chunks of one document
        (enabling contextual awareness), this method embeds each text in isolation.
        
        CRITICAL: Use this for short independent texts like entity names where
        cross-text contextual bleed would corrupt embeddings. When 252 entity
        names are batched as chunks of one document, contextualized_embed() makes
        each name's vector a mix of ALL names, destroying pairwise similarity
        (e.g., cos("3 business days","five 5 business days") drops from 0.93→0.54).
        
        Args:
            texts: List of independent texts to embed (e.g., entity names)
            group_id: Optional group ID for usage tracking
            user_id: Optional user ID for usage tracking
            
        Returns:
            List of embedding vectors (2048 dimensions each)
        """
        if not texts:
            return []
        
        all_embeddings: List[Optional[List[float]]] = [None] * len(texts)
        total_tokens_used = 0
        
        # Batch respecting API limits (each text is 1 input + 1 chunk)
        for batch_start in range(0, len(texts), MAX_API_INPUTS):
            batch_end = min(batch_start + MAX_API_INPUTS, len(texts))
            batch_texts = texts[batch_start:batch_end]
            
            # Each text as its own single-chunk document (no contextual bleed)
            inputs = [[t] for t in batch_texts]
            result = self._call_with_retry(
                inputs=inputs,
                model=self.model_name,
                input_type="document",
                output_dimension=settings.VOYAGE_EMBEDDING_DIM,
            )
            
            for res_item in result.results:
                all_embeddings[batch_start + res_item.index] = res_item.embeddings[0]
            
            if hasattr(result, 'usage') and result.usage:
                total_tokens_used += result.usage.total_tokens
        
        # Track usage
        if total_tokens_used > 0:
            try:
                loop = asyncio.get_event_loop()
                task = loop.create_task(get_usage_tracker().log_embedding_usage(
                    partition_id=group_id or "unknown",
                    model=self.model_name,
                    total_tokens=total_tokens_used,
                    dimensions=settings.VOYAGE_EMBEDDING_DIM,
                    chunk_count=len(texts),
                    user_id=user_id,
                ))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            except Exception:
                pass
        
        return all_embeddings  # type: ignore[return-value]
    
    async def aembed_independent_texts(
        self,
        texts: List[str],
        group_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[List[float]]:
        """Async wrapper for embed_independent_texts()."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.embed_independent_texts(texts, group_id, user_id)
        )
    
    async def aget_text_embedding_batch(
        self, 
        texts: List[str],
        show_progress: bool = False,
    ) -> List[List[float]]:
        """
        Async embedding method for LlamaIndex pipeline compatibility.
        
        Wraps embed_documents() in an async interface. This is required
        because the LazyGraphRAG pipeline uses async embedding calls.
        
        Treats all texts as chunks from a single document, providing
        contextual awareness within the batch. Suitable for sections,
        community summaries, and KVP keys where context is beneficial.
        
        WARNING: Do NOT use this for entity names — batching entity names
        as chunks of one document causes contextual bleed that destroys
        pairwise similarity (cos drops from 0.93→0.54). Use
        embed_independent_texts() / aembed_independent_texts() instead.
        
        Args:
            texts: List of text chunks to embed (from the same document/context)
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
_voyage_service_lock = threading.Lock()


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
    if _voyage_service is not None:
        return _voyage_service
    with _voyage_service_lock:
        if _voyage_service is None:
            _voyage_service = VoyageEmbedService()
    return _voyage_service


def is_voyage_v2_enabled() -> bool:
    """
    Check if Voyage embeddings are available.
    
    Returns:
        True if VOYAGE_API_KEY is set.  The old VOYAGE_V2_ENABLED gate
        has been removed — Voyage voyage-context-3 is the only embedding
        model (Feb 14 2026).
    """
    return bool(settings.VOYAGE_API_KEY)
