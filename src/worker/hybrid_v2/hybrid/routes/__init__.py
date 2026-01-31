"""Route handlers for the Hybrid GraphRAG pipeline.

Each route is a self-contained handler that inherits from BaseRouteHandler
and implements a specific retrieval strategy:

- Route 2 (LocalSearchHandler): Entity-focused with LazyGraphRAG
- Route 3 (GlobalSearchHandler): Thematic queries with HippoRAG PPR
- Route 4 (DRIFTHandler): Multi-hop iterative reasoning

Note: Route 1 (Vector RAG) was deprecated after testing showed Route 2
handles all Vector RAG cases with superior quality.

Usage:
    from src.worker.hybrid_v2.routes import LocalSearchHandler, RouteResult

    handler = LocalSearchHandler(pipeline)
    result = await handler.execute(query)
"""

from .base import BaseRouteHandler, RouteResult, Citation
from .route_2_local import LocalSearchHandler
from .route_3_global import GlobalSearchHandler
from .route_4_drift import DRIFTHandler

__all__ = [
    # Base classes
    "BaseRouteHandler",
    "RouteResult",
    "Citation",
    # Route handlers
    "LocalSearchHandler",
    "GlobalSearchHandler",
    "DRIFTHandler",
]
