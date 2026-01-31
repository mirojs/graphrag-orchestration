"""Usage tracking service with fire-and-forget pattern."""

from typing import Optional, List
import asyncio
import structlog
from datetime import datetime

from src.core.models.usage import UsageRecord, UsageType
from src.core.services.cosmos_client import get_cosmos_client

logger = structlog.get_logger(__name__)


class UsageTracker:
    """
    Usage tracker with fire-and-forget pattern.
    
    Logs token and page consumption to Cosmos DB asynchronously without
    blocking the main request flow. Falls back to structured logging if
    Cosmos is unavailable.
    """
    
    def __init__(self):
        """Initialize usage tracker."""
        self._cosmos_client = get_cosmos_client()
        self._batch_queue: List[UsageRecord] = []
        self._batch_size = 10
        self._batch_interval = 60  # seconds
        self._last_flush = datetime.utcnow()
    
    async def log_llm_usage(
        self,
        partition_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        user_id: Optional[str] = None,
        route: Optional[str] = None,
        query_id: Optional[str] = None,
        cost_estimate_usd: Optional[float] = None
    ) -> None:
        """
        Log LLM completion usage.
        
        Fire-and-forget: Does not raise exceptions or block the caller.
        """
        try:
            record = UsageRecord(
                partition_id=partition_id,
                user_id=user_id,
                usage_type=UsageType.LLM_COMPLETION,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                route=route,
                query_id=query_id,
                cost_estimate_usd=cost_estimate_usd
            )
            
            # Log immediately to structlog for visibility
            logger.info("llm_usage_tracked",
                       partition_id=partition_id,
                       model=model,
                       total_tokens=record.total_tokens,
                       route=route)
            
            # Queue for async write
            await self._write_record(record)
        except Exception as e:
            logger.warning("llm_usage_tracking_failed", error=str(e))
    
    async def log_embedding_usage(
        self,
        partition_id: str,
        model: str,
        total_tokens: int,
        dimensions: int,
        chunk_count: int = 1,
        user_id: Optional[str] = None,
        query_id: Optional[str] = None,
        cost_estimate_usd: Optional[float] = None
    ) -> None:
        """
        Log embedding generation usage.
        
        Fire-and-forget: Does not raise exceptions or block the caller.
        """
        try:
            record = UsageRecord(
                partition_id=partition_id,
                user_id=user_id,
                usage_type=UsageType.EMBEDDING,
                model=model,
                total_tokens=total_tokens,
                dimensions=dimensions,
                chunk_count=chunk_count,
                query_id=query_id,
                cost_estimate_usd=cost_estimate_usd
            )
            
            logger.info("embedding_usage_tracked",
                       partition_id=partition_id,
                       model=model,
                       total_tokens=total_tokens,
                       dimensions=dimensions)
            
            await self._write_record(record)
        except Exception as e:
            logger.warning("embedding_usage_tracking_failed", error=str(e))
    
    async def log_doc_intel_usage(
        self,
        partition_id: str,
        pages_analyzed: int,
        document_id: str,
        user_id: Optional[str] = None,
        cost_estimate_usd: Optional[float] = None
    ) -> None:
        """
        Log Document Intelligence usage.
        
        Fire-and-forget: Does not raise exceptions or block the caller.
        """
        try:
            record = UsageRecord(
                partition_id=partition_id,
                user_id=user_id,
                usage_type=UsageType.DOC_INTEL,
                pages_analyzed=pages_analyzed,
                document_id=document_id,
                cost_estimate_usd=cost_estimate_usd
            )
            
            logger.info("doc_intel_usage_tracked",
                       partition_id=partition_id,
                       pages=pages_analyzed,
                       document_id=document_id)
            
            await self._write_record(record)
        except Exception as e:
            logger.warning("doc_intel_usage_tracking_failed", error=str(e))
    
    async def _write_record(self, record: UsageRecord) -> None:
        """
        Write record to Cosmos DB asynchronously.
        
        Uses fire-and-forget pattern - logs warnings on failure but doesn't raise.
        """
        try:
            # Write immediately (non-blocking)
            asyncio.create_task(self._cosmos_client.write_usage_record(record))
        except Exception as e:
            # Fallback: just log to structlog
            logger.warning("cosmos_write_failed_using_structlog",
                          error=str(e),
                          record_id=record.id)
    
    async def flush(self) -> None:
        """Flush any pending batched records (if batching is enabled)."""
        # Currently writes immediately, but kept for future batching implementation
        pass


# Singleton instance
_usage_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    """Get or create the singleton usage tracker."""
    global _usage_tracker
    if _usage_tracker is None:
        _usage_tracker = UsageTracker()
    return _usage_tracker
