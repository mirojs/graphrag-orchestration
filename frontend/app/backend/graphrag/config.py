"""
GraphRAG Configuration

Defines configuration settings for connecting to the GraphRAG orchestration backend.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class GraphRAGConfig:
    """Configuration for GraphRAG backend connection."""
    
    # Backend API URL (the GraphRAG orchestration service)
    api_base_url: str = ""
    
    # API timeout in seconds
    timeout: int = 120
    
    # Default route for queries (2=Local, 3=Global, 4=DRIFT)
    default_route: int = 3
    
    # Whether to use streaming responses
    enable_streaming: bool = True
    
    # API key for authentication (if required)
    api_key: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> "GraphRAGConfig":
        """Load configuration from environment variables."""
        return cls(
            api_base_url=os.getenv("GRAPHRAG_API_URL", "http://localhost:8000"),
            timeout=int(os.getenv("GRAPHRAG_API_TIMEOUT", "120")),
            default_route=int(os.getenv("GRAPHRAG_DEFAULT_ROUTE", "3")),
            enable_streaming=os.getenv("GRAPHRAG_ENABLE_STREAMING", "true").lower() == "true",
            api_key=os.getenv("GRAPHRAG_API_KEY"),
        )
