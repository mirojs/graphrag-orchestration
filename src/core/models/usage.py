"""Usage tracking models."""

from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class UsageType(str, Enum):
    """Type of usage being tracked."""
    LLM_COMPLETION = "llm_completion"
    EMBEDDING = "embedding"
    DOC_INTEL = "doc_intel"
    RERANK = "rerank"
    GDS_SESSION = "gds_session"
    TRANSLATION = "translation"


class UsageRecord(BaseModel):
    """Usage record for token/page consumption tracking."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    partition_id: str = Field(..., description="Group ID (B2B) or User ID (B2C)")
    user_id: Optional[str] = Field(None, description="User ID if available")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    usage_type: UsageType = Field(..., description="Type of usage")
    
    # LLM-specific fields
    model: Optional[str] = Field(None, description="Model name (e.g., gpt-4o)")
    prompt_tokens: Optional[int] = Field(None, description="Input tokens")
    completion_tokens: Optional[int] = Field(None, description="Output tokens")
    total_tokens: Optional[int] = Field(None, description="Total tokens")
    
    # Embedding-specific fields
    dimensions: Optional[int] = Field(None, description="Embedding dimensions")
    chunk_count: Optional[int] = Field(None, description="Number of chunks embedded")
    
    # Reranker-specific fields
    rerank_model: Optional[str] = Field(None, description="Reranker model name")
    documents_reranked: Optional[int] = Field(None, description="Number of documents reranked")
    
    # Document Intelligence-specific fields
    pages_analyzed: Optional[int] = Field(None, description="Pages processed by Azure DI")
    document_id: Optional[str] = Field(None, description="Document ID")
    
    # GDS session-specific fields
    gds_memory_gb: Optional[int] = Field(None, description="GDS session memory tier in GB")
    gds_duration_seconds: Optional[int] = Field(None, description="GDS session wall-clock duration")
    gds_algorithms_run: Optional[list[str]] = Field(None, description="GDS algorithms executed")
    gds_nodes_processed: Optional[int] = Field(None, description="Nodes in GDS projection")
    
    # Translation-specific fields
    characters_translated: Optional[int] = Field(None, description="Characters sent to Azure Translator")
    detected_language: Optional[str] = Field(None, description="Auto-detected source language code (e.g., 'ja')")
    was_translated: Optional[bool] = Field(None, description="Whether query was translated before retrieval")

    # Speech input fields
    speech_detected_language: Optional[str] = Field(None, description="Language detected by Azure Speech SDK (e.g., 'ja')")
    was_speech_input: Optional[bool] = Field(None, description="Whether query originated from voice input with translation")

    # Common fields
    route: Optional[str] = Field(None, description="Route used (route_2, route_3, route_4)")
    query_id: Optional[str] = Field(None, description="Associated query ID")
    cost_estimate_usd: Optional[float] = Field(None, description="Estimated cost in USD")
    
    # Cosmos DB TTL (90 days)
    ttl: int = Field(default=7776000, description="Time to live in seconds")
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "partition_id": "group-123",
                "user_id": "user-456",
                "usage_type": "llm_completion",
                "model": "gpt-4o",
                "prompt_tokens": 1500,
                "completion_tokens": 350,
                "total_tokens": 1850,
                "route": "route_2",
                "cost_estimate_usd": 0.0285
            }
        }
