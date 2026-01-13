"""
GraphRAG V3 Package

This package contains the V3 implementation of GraphRAG with:
- Neo4j as the single query-time data store
- LlamaIndex for indexing (~90%)
- MS GraphRAG DRIFT algorithm for multi-step reasoning (~5%)
- RAPTOR for hierarchical summaries
- graspologic for community detection

IMPORTANT: This is separate from V1 (LanceDB) and V2 (mixed) implementations.
Do not import from v1/v2 services into v3.
"""

__version__ = "3.0.0"
