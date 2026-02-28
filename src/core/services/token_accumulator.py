"""Per-request token accumulator for tracking all API usage across a query pipeline.

Each query request creates one TokenAccumulator that is threaded through
orchestrator → route → synthesis. All acomplete()/complete() calls via
TrackedLLM add their token counts here, and the route reads the snapshot
to populate RouteResult.usage.

Also tracks reranker and embedding usage for credit computation.
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class _CallRecord:
    """One LLM call's token usage."""
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class _RerankRecord:
    """One reranker call's usage."""
    model: str
    total_tokens: int
    documents_reranked: int


@dataclass
class _EmbedRecord:
    """One embedding call's usage."""
    model: str
    total_tokens: int


class TokenAccumulator:
    """Thread-safe accumulator for all API usage within a single request.

    Usage::

        acc = TokenAccumulator()
        # ... pass acc through pipeline; TrackedLLM calls acc.add() ...
        usage = acc.snapshot()  # {"prompt_tokens": N, "credits_used": M, ...}
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: List[_CallRecord] = []
        self._rerank_calls: List[_RerankRecord] = []
        self._embed_calls: List[_EmbedRecord] = []
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._total_tokens: int = 0
        self._rerank_tokens: int = 0
        self._embed_tokens: int = 0
        self._model: Optional[str] = None

    def add(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int = 0,
    ) -> None:
        """Record token usage from one LLM call."""
        total = total_tokens or (prompt_tokens + completion_tokens)
        with self._lock:
            self._calls.append(_CallRecord(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total,
            ))
            self._prompt_tokens += prompt_tokens
            self._completion_tokens += completion_tokens
            self._total_tokens += total
            # Keep track of last model used (typically the synthesis model)
            self._model = model

    def add_rerank(
        self,
        model: str,
        total_tokens: int,
        documents_reranked: int = 0,
    ) -> None:
        """Record usage from one reranker call."""
        with self._lock:
            self._rerank_calls.append(_RerankRecord(
                model=model,
                total_tokens=total_tokens,
                documents_reranked=documents_reranked,
            ))
            self._rerank_tokens += total_tokens

    def add_embedding(
        self,
        model: str,
        total_tokens: int,
    ) -> None:
        """Record usage from one embedding call."""
        with self._lock:
            self._embed_calls.append(_EmbedRecord(
                model=model,
                total_tokens=total_tokens,
            ))
            self._embed_tokens += total_tokens

    def compute_credits(self) -> int:
        """Compute total credits consumed from all tracked API calls."""
        from src.core.services.credit_schedule import (
            compute_llm_credits,
            compute_rerank_credits,
            compute_embedding_credits,
        )
        credits = 0
        with self._lock:
            for call in self._calls:
                credits += compute_llm_credits(
                    call.model, call.prompt_tokens, call.completion_tokens
                )
            for rr in self._rerank_calls:
                credits += compute_rerank_credits(rr.model, rr.total_tokens)
            for em in self._embed_calls:
                credits += compute_embedding_credits(em.model, em.total_tokens)
        return credits

    def snapshot(self) -> Dict[str, Any]:
        """Return a summary dict suitable for RouteResult.usage."""
        credits = self.compute_credits()
        with self._lock:
            return {
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": self._total_tokens,
                "rerank_tokens": self._rerank_tokens,
                "embed_tokens": self._embed_tokens,
                "model": self._model,
                "llm_calls": len(self._calls),
                "rerank_calls": len(self._rerank_calls),
                "credits_used": credits,
            }

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return self._total_tokens

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._calls)
