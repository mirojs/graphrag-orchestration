"""
Hybrid RAG Pipeline

A 4-route query processing system combining:
- LazyGraphRAG for iterative graph exploration
- HippoRAG 2 for deterministic PPR-based retrieval  
- Vector RAG for fast lookups

Routes:
1. Vector RAG - Simple fact lookups (General Enterprise only)
2. Local Search - Entity-focused with LazyGraphRAG
3. Global Search - Thematic with LazyGraphRAG + HippoRAG 2
4. DRIFT Multi-Hop - Ambiguous queries with iterative decomposition

Deployment Profiles:
- General Enterprise: All 4 routes available
- High Assurance: Routes 2-4 only (no Vector RAG shortcuts)
"""

from app.hybrid.orchestrator import HybridPipeline
from app.hybrid.router.main import (
    HybridRouter,
    QueryRoute,
    DeploymentProfile,
)
from app.hybrid.retrievers import (
    HippoRAGRetriever,
    HippoRAGRetrieverConfig,
)

__all__ = [
    "HybridPipeline",
    "HybridRouter",
    "QueryRoute",
    "DeploymentProfile",
    "HippoRAGRetriever",
    "HippoRAGRetrieverConfig",
]
