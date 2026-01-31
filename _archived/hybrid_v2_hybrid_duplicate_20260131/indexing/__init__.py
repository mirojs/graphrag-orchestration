"""
Hybrid Pipeline Indexing Module

Provides dual indexing capabilities for the LazyGraphRAG + HippoRAG 2 architecture:
- DualIndexService: Syncs Neo4j data to HippoRAG/LazyGraphRAG formats
- HippoRAGService: Wrapper for HippoRAG initialization and retrieval
"""

from .dual_index import DualIndexService
from .hipporag_service import HippoRAGService, get_hipporag_service

__all__ = [
    "DualIndexService",
    "HippoRAGService", 
    "get_hipporag_service"
]
