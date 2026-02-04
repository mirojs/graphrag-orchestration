"""
Instrumentation Module - Fire-and-Forget Observability

Provides lightweight, non-blocking hooks for:
- Query performance tracking
- Token/cost usage logging  
- Error rate monitoring
- Request tracing

All hooks use asyncio.create_task() for fire-and-forget execution.
"""

from .hooks import (
    InstrumentationHooks,
    get_instrumentation,
    QueryMetrics,
    track_query,
    track_error,
    track_llm_usage,
    track_embedding_usage,
    track_doc_intel_usage,
)

__all__ = [
    "InstrumentationHooks",
    "get_instrumentation",
    "QueryMetrics",
    "track_query",
    "track_error",
    "track_llm_usage",
    "track_embedding_usage",
    "track_doc_intel_usage",
]
