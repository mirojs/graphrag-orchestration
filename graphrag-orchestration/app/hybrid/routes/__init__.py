"""Route handlers for the Hybrid GraphRAG pipeline.

Each route is a self-contained handler that inherits from BaseRouteHandler
and implements a specific retrieval strategy:

- Route 1 (VectorRAGHandler): Fast vector search for simple fact lookups
- Route 2 (LocalSearchHandler): Entity-focused with LazyGraphRAG
- Route 3 (GlobalSearchHandler): Thematic queries with HippoRAG PPR
- Route 4 (DRIFTHandler): Multi-hop iterative reasoning

Usage:
    from app.hybrid.routes import VectorRAGHandler, RouteResult

    handler = VectorRAGHandler(pipeline)
    result = await handler.execute(query)
"""

from .base import BaseRouteHandler, RouteResult, Citation
from .route_1_vector import VectorRAGHandler
from .route_2_local import LocalSearchHandler
from .route_3_global import GlobalSearchHandler
from .route_4_drift import DRIFTHandler

__all__ = [
    # Base classes
    "BaseRouteHandler",
    "RouteResult",
    "Citation",
    # Route handlers
    "VectorRAGHandler",
    "LocalSearchHandler",
    "GlobalSearchHandler",
    "DRIFTHandler",
]
