"""
Fire-and-Forget Instrumentation Hooks

Provides non-blocking tracking for queries, errors, and resource usage.
All methods return immediately and log asynchronously.

Usage:
    from src.core.instrumentation import track_query, track_error
    
    # Track a query (fire-and-forget)
    track_query(
        group_id="tenant-123",
        query="What is the total invoice amount?",
        route="route_2_local",
        latency_ms=1234,
        tokens_used=500
    )
    
    # Track an error
    track_error(
        group_id="tenant-123",
        error_type="ROUTE3_STRICT_HIGH_QUALITY",
        message="Failed to extract with high quality",
        route="route_3_global"
    )
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import structlog

from src.core.services.usage_tracker import get_usage_tracker, UsageTracker

logger = structlog.get_logger(__name__)


@dataclass
class QueryMetrics:
    """Metrics collected for a single query."""
    query_id: str
    group_id: str
    route: str
    latency_ms: float
    tokens_used: int = 0
    chunks_retrieved: int = 0
    entities_found: int = 0
    success: bool = True
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class InstrumentationHooks:
    """
    Central instrumentation hub for fire-and-forget metrics collection.
    
    All methods are non-blocking and safe to call in the request path.
    Failures are logged but never raised to the caller.
    """
    
    def __init__(self):
        """Initialize instrumentation hooks."""
        self._usage_tracker = get_usage_tracker()
        self._query_buffer: List[QueryMetrics] = []
        self._error_buffer: List[Dict[str, Any]] = []
        self._buffer_size = 100
        self._flush_interval = 60  # seconds
        self._last_flush = time.time()
    
    def track_query(
        self,
        group_id: str,
        query: str,
        route: str,
        latency_ms: float,
        tokens_used: int = 0,
        chunks_retrieved: int = 0,
        entities_found: int = 0,
        query_id: Optional[str] = None,
        user_id: Optional[str] = None,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Track query execution metrics (fire-and-forget).
        
        Args:
            group_id: Tenant identifier
            query: Query text (truncated in logs)
            route: Route used (e.g., "route_2_local")
            latency_ms: Total latency in milliseconds
            tokens_used: Total tokens consumed (LLM + embedding)
            chunks_retrieved: Number of chunks retrieved
            entities_found: Number of entities in evidence path
            query_id: Unique query identifier (auto-generated if not provided)
            user_id: Optional user identifier
            success: Whether query succeeded
            metadata: Additional context
        """
        try:
            # Generate query_id if not provided
            if not query_id:
                query_id = f"{group_id}-{int(time.time() * 1000)}"
            
            # Log immediately (fire-and-forget)
            asyncio.create_task(self._log_query_async(
                query_id=query_id,
                group_id=group_id,
                query=query[:100],  # Truncate for logging
                route=route,
                latency_ms=latency_ms,
                tokens_used=tokens_used,
                chunks_retrieved=chunks_retrieved,
                entities_found=entities_found,
                user_id=user_id,
                success=success,
                metadata=metadata or {},
            ))
        except Exception as e:
            # Never block - just log warning
            logger.warning("track_query_failed", error=str(e))
    
    async def _log_query_async(self, **kwargs) -> None:
        """Async logging for query metrics."""
        try:
            logger.info(
                "query_tracked",
                query_id=kwargs.get("query_id"),
                group_id=kwargs.get("group_id"),
                route=kwargs.get("route"),
                latency_ms=kwargs.get("latency_ms"),
                tokens_used=kwargs.get("tokens_used"),
                chunks_retrieved=kwargs.get("chunks_retrieved"),
                entities_found=kwargs.get("entities_found"),
                success=kwargs.get("success"),
            )
            
            # Store metrics (could be extended to write to Cosmos DB)
            metrics = QueryMetrics(
                query_id=kwargs.get("query_id", ""),
                group_id=kwargs.get("group_id", ""),
                route=kwargs.get("route", ""),
                latency_ms=kwargs.get("latency_ms", 0),
                tokens_used=kwargs.get("tokens_used", 0),
                chunks_retrieved=kwargs.get("chunks_retrieved", 0),
                entities_found=kwargs.get("entities_found", 0),
                success=kwargs.get("success", True),
                metadata=kwargs.get("metadata", {}),
            )
            self._query_buffer.append(metrics)
            
            # Auto-flush if buffer is full
            if len(self._query_buffer) >= self._buffer_size:
                await self._flush_query_buffer()
                
        except Exception as e:
            logger.warning("query_log_failed", error=str(e))
    
    def track_error(
        self,
        group_id: str,
        error_type: str,
        message: str,
        route: Optional[str] = None,
        query_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Track error occurrence (fire-and-forget).
        
        Args:
            group_id: Tenant identifier
            error_type: Error category (e.g., "ROUTE3_STRICT_HIGH_QUALITY")
            message: Error message
            route: Route where error occurred
            query_id: Associated query ID
            user_id: Optional user identifier
            stack_trace: Optional stack trace
            metadata: Additional context
        """
        try:
            asyncio.create_task(self._log_error_async(
                group_id=group_id,
                error_type=error_type,
                message=message,
                route=route,
                query_id=query_id,
                user_id=user_id,
                stack_trace=stack_trace,
                metadata=metadata or {},
            ))
        except Exception as e:
            logger.warning("track_error_failed", error=str(e))
    
    async def _log_error_async(self, **kwargs) -> None:
        """Async logging for errors."""
        try:
            logger.error(
                "error_tracked",
                group_id=kwargs.get("group_id"),
                error_type=kwargs.get("error_type"),
                message=kwargs.get("message"),
                route=kwargs.get("route"),
                query_id=kwargs.get("query_id"),
            )
            
            # Buffer error for potential aggregation
            self._error_buffer.append({
                **kwargs,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            if len(self._error_buffer) >= self._buffer_size:
                await self._flush_error_buffer()
                
        except Exception as e:
            logger.warning("error_log_failed", error=str(e))
    
    def track_llm_usage(
        self,
        group_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        route: Optional[str] = None,
        query_id: Optional[str] = None,
        user_id: Optional[str] = None,
        cost_estimate_usd: Optional[float] = None,
    ) -> None:
        """
        Track LLM token usage (fire-and-forget).
        
        Delegates to UsageTracker for Cosmos DB persistence.
        """
        try:
            asyncio.create_task(self._usage_tracker.log_llm_usage(
                partition_id=group_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                user_id=user_id,
                route=route,
                query_id=query_id,
                cost_estimate_usd=cost_estimate_usd,
            ))
        except Exception as e:
            logger.warning("track_llm_usage_failed", error=str(e))
    
    def track_embedding_usage(
        self,
        group_id: str,
        model: str,
        total_tokens: int,
        dimensions: int,
        chunk_count: int = 1,
        query_id: Optional[str] = None,
        user_id: Optional[str] = None,
        cost_estimate_usd: Optional[float] = None,
    ) -> None:
        """
        Track embedding generation usage (fire-and-forget).
        
        Delegates to UsageTracker for Cosmos DB persistence.
        """
        try:
            asyncio.create_task(self._usage_tracker.log_embedding_usage(
                partition_id=group_id,
                model=model,
                total_tokens=total_tokens,
                dimensions=dimensions,
                chunk_count=chunk_count,
                query_id=query_id,
                user_id=user_id,
                cost_estimate_usd=cost_estimate_usd,
            ))
        except Exception as e:
            logger.warning("track_embedding_usage_failed", error=str(e))
    
    def track_doc_intel_usage(
        self,
        group_id: str,
        pages_analyzed: int,
        document_id: str,
        user_id: Optional[str] = None,
        cost_estimate_usd: Optional[float] = None,
    ) -> None:
        """
        Track Document Intelligence usage (fire-and-forget).
        
        Delegates to UsageTracker for Cosmos DB persistence.
        """
        try:
            asyncio.create_task(self._usage_tracker.log_doc_intel_usage(
                partition_id=group_id,
                pages_analyzed=pages_analyzed,
                document_id=document_id,
                user_id=user_id,
                cost_estimate_usd=cost_estimate_usd,
            ))
        except Exception as e:
            logger.warning("track_doc_intel_usage_failed", error=str(e))
    
    @asynccontextmanager
    async def measure_query(
        self,
        group_id: str,
        route: str,
        query: str,
        query_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """
        Context manager for measuring query execution time.
        
        Usage:
            async with instrumentation.measure_query("tenant-123", "route_2", "Query?") as ctx:
                result = await pipeline.query(...)
                ctx.tokens_used = result.get("tokens", 0)
        """
        @dataclass
        class QueryContext:
            tokens_used: int = 0
            chunks_retrieved: int = 0
            entities_found: int = 0
            success: bool = True
            metadata: Dict[str, Any] = field(default_factory=dict)
        
        ctx = QueryContext()
        start_time = time.time()
        
        try:
            yield ctx
        except Exception as e:
            ctx.success = False
            self.track_error(
                group_id=group_id,
                error_type=type(e).__name__,
                message=str(e),
                route=route,
                query_id=query_id,
                user_id=user_id,
            )
            raise
        finally:
            latency_ms = (time.time() - start_time) * 1000
            self.track_query(
                group_id=group_id,
                query=query,
                route=route,
                latency_ms=latency_ms,
                tokens_used=ctx.tokens_used,
                chunks_retrieved=ctx.chunks_retrieved,
                entities_found=ctx.entities_found,
                query_id=query_id,
                user_id=user_id,
                success=ctx.success,
                metadata=ctx.metadata,
            )
    
    async def _flush_query_buffer(self) -> None:
        """Flush query metrics buffer to storage."""
        if not self._query_buffer:
            return
        
        try:
            # Could write batch to Cosmos DB here
            logger.info("query_buffer_flushed", count=len(self._query_buffer))
            self._query_buffer.clear()
            self._last_flush = time.time()
        except Exception as e:
            logger.warning("query_buffer_flush_failed", error=str(e))
    
    async def _flush_error_buffer(self) -> None:
        """Flush error buffer to storage."""
        if not self._error_buffer:
            return
        
        try:
            # Could write batch to Cosmos DB here
            logger.info("error_buffer_flushed", count=len(self._error_buffer))
            self._error_buffer.clear()
        except Exception as e:
            logger.warning("error_buffer_flush_failed", error=str(e))
    
    async def flush(self) -> None:
        """Flush all buffers."""
        await self._flush_query_buffer()
        await self._flush_error_buffer()
        await self._usage_tracker.flush()


# Singleton instance
_instrumentation: Optional[InstrumentationHooks] = None


def get_instrumentation() -> InstrumentationHooks:
    """Get or create the singleton instrumentation hooks instance."""
    global _instrumentation
    if _instrumentation is None:
        _instrumentation = InstrumentationHooks()
    return _instrumentation


# Convenience functions for common operations
def track_query(
    group_id: str,
    query: str,
    route: str,
    latency_ms: float,
    **kwargs
) -> None:
    """Convenience function for tracking queries."""
    get_instrumentation().track_query(
        group_id=group_id,
        query=query,
        route=route,
        latency_ms=latency_ms,
        **kwargs
    )


def track_error(
    group_id: str,
    error_type: str,
    message: str,
    **kwargs
) -> None:
    """Convenience function for tracking errors."""
    get_instrumentation().track_error(
        group_id=group_id,
        error_type=error_type,
        message=message,
        **kwargs
    )


def track_llm_usage(
    group_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    **kwargs
) -> None:
    """Convenience function for tracking LLM usage."""
    get_instrumentation().track_llm_usage(
        group_id=group_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        **kwargs
    )


def track_embedding_usage(
    group_id: str,
    model: str,
    total_tokens: int,
    dimensions: int,
    **kwargs
) -> None:
    """Convenience function for tracking embedding usage."""
    get_instrumentation().track_embedding_usage(
        group_id=group_id,
        model=model,
        total_tokens=total_tokens,
        dimensions=dimensions,
        **kwargs
    )


def track_doc_intel_usage(
    group_id: str,
    pages_analyzed: int,
    document_id: str,
    **kwargs
) -> None:
    """Convenience function for tracking Document Intelligence usage."""
    get_instrumentation().track_doc_intel_usage(
        group_id=group_id,
        pages_analyzed=pages_analyzed,
        document_id=document_id,
        **kwargs
    )
