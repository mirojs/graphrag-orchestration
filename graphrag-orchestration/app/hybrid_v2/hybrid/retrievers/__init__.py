"""
LlamaIndex-Native Retrievers for Hybrid Pipeline

This package contains custom retrievers that integrate directly with 
LlamaIndex's BaseRetriever interface and use Azure Managed Identity 
for authentication.
"""

from app.hybrid_v2.retrievers.hipporag_retriever import (
    HippoRAGRetriever,
    HippoRAGRetrieverConfig,
)

__all__ = [
    "HippoRAGRetriever",
    "HippoRAGRetrieverConfig",
]
