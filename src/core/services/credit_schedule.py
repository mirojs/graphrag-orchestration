"""
Credit schedule — USD-based exchange rates for normalizing API costs.

1 credit = $0.001 USD (1,000 credits = $1.00).

Exchange rates are derived from actual API pricing and can be updated
centrally when providers change prices. All cost math stays in the
backend; the frontend only sees credits.
"""

from __future__ import annotations

import math
from typing import Optional

# ============================================================================
# 1 credit = $0.001 USD
# ============================================================================
CREDIT_VALUE_USD = 0.001  # $0.001 per credit

# ============================================================================
# LLM Completion — per 1M tokens (Azure OpenAI pricing, pay-as-you-go)
# ============================================================================
LLM_PRICING_PER_1M: dict[str, dict[str, float]] = {
    # model_deployment_name → {"input": $/1M, "output": $/1M}
    "gpt-4o":          {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":     {"input": 0.15,  "output": 0.60},
    "gpt-4.1":         {"input": 2.00,  "output": 8.00},
    "gpt-4.1-mini":    {"input": 0.40,  "output": 1.60},
    "gpt-4.1-nano":    {"input": 0.10,  "output": 0.40},
    "o4-mini":         {"input": 1.10,  "output": 4.40},
}

# Fallback for unknown models
_LLM_DEFAULT = {"input": 2.50, "output": 10.00}

# ============================================================================
# Embedding — per 1M tokens (Voyage AI pricing)
# ============================================================================
EMBEDDING_PRICING_PER_1M: dict[str, float] = {
    "voyage-3":           0.06,
    "voyage-3-lite":      0.02,
    "voyage-context-3":   0.06,   # contextual embedding
    "voyage-code-3":      0.12,
}

_EMBED_DEFAULT = 0.06

# ============================================================================
# Reranker — per 1M tokens (Voyage AI pricing)
# ============================================================================
RERANKER_PRICING_PER_1M: dict[str, float] = {
    "rerank-2":     0.05,
    "rerank-2.5":   0.05,
}

_RERANK_DEFAULT = 0.05

# ============================================================================
# Azure Document Intelligence — per page
# ============================================================================
DOC_INTEL_PRICE_PER_PAGE: float = 0.01  # $0.01/page for prebuilt-layout

# ============================================================================
# Neo4j Aura Serverless GDS — per memory-hour
# ============================================================================
GDS_PRICE_PER_HOUR_PER_GB: float = 0.035  # ~$0.07/hr for a 2 GB session


# ============================================================================
# Azure Translator — per 1M characters (S1 pay-as-you-go)
# ============================================================================
TRANSLATOR_PRICE_PER_1M_CHARS: float = 10.00  # $10 per 1M characters


# ============================================================================
# Credit computation helpers
# ============================================================================

def _usd_to_credits(usd: float) -> int:
    """Convert a USD cost to credits (rounded up)."""
    return max(1, math.ceil(usd / CREDIT_VALUE_USD))


def compute_llm_credits(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    """Compute credits for an LLM completion call."""
    pricing = LLM_PRICING_PER_1M.get(model, _LLM_DEFAULT)
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return _usd_to_credits(input_cost + output_cost)


def compute_embedding_credits(
    model: str,
    total_tokens: int,
) -> int:
    """Compute credits for an embedding call."""
    rate = EMBEDDING_PRICING_PER_1M.get(model, _EMBED_DEFAULT)
    cost = (total_tokens / 1_000_000) * rate
    return _usd_to_credits(cost)


def compute_rerank_credits(
    model: str,
    total_tokens: int,
) -> int:
    """Compute credits for a reranker call."""
    rate = RERANKER_PRICING_PER_1M.get(model, _RERANK_DEFAULT)
    cost = (total_tokens / 1_000_000) * rate
    return _usd_to_credits(cost)


def compute_doc_intel_credits(pages: int) -> int:
    """Compute credits for a Document Intelligence call."""
    cost = pages * DOC_INTEL_PRICE_PER_PAGE
    return _usd_to_credits(cost)


def compute_gds_credits(memory_gb: int, duration_seconds: int) -> int:
    """Compute credits for a GDS session (billed by memory-hours)."""
    hours = duration_seconds / 3600
    cost = memory_gb * hours * GDS_PRICE_PER_HOUR_PER_GB
    return _usd_to_credits(cost)


def compute_translation_credits(characters: int) -> int:
    """Compute credits for an Azure Translator call."""
    cost = (characters / 1_000_000) * TRANSLATOR_PRICE_PER_1M_CHARS
    return _usd_to_credits(cost)


def estimate_query_credits(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    llm_model: str = "gpt-4o",
    embed_tokens: int = 0,
    embed_model: str = "voyage-context-3",
    rerank_tokens: int = 0,
    rerank_model: str = "rerank-2.5",
) -> int:
    """Estimate total credits for a complete query (convenience wrapper)."""
    total = 0
    if prompt_tokens or completion_tokens:
        total += compute_llm_credits(llm_model, prompt_tokens, completion_tokens)
    if embed_tokens:
        total += compute_embedding_credits(embed_model, embed_tokens)
    if rerank_tokens:
        total += compute_rerank_credits(rerank_model, rerank_tokens)
    return max(1, total)
