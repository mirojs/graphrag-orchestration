"""
GraphRAG Integration Module

This module provides integration between the frontend and the GraphRAG orchestration backend,
replacing Azure AI Search with Neo4j-based graph retrieval.
"""

from .client import GraphRAGClient
from .config import GraphRAGConfig

__all__ = ["GraphRAGClient", "GraphRAGConfig"]
