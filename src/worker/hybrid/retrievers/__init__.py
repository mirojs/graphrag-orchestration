"""
LlamaIndex-Native Retrievers for Hybrid Pipeline

This package contains custom retrievers that integrate directly with 
LlamaIndex's BaseRetriever interface and use Azure Managed Identity 
for authentication.
"""

from src.worker.hybrid.retrievers.hipporag_retriever import (
    HippoRAGRetriever,
    HippoRAGRetrieverConfig,
)

__all__ = [
    "HippoRAGRetriever",
    "HippoRAGRetrieverConfig",
]
