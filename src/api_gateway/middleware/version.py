"""
Version Headers Middleware

Handles API version negotiation via request/response headers.

Request Headers (processed):
- X-API-Version: Date-based version (e.g., "2026-01-30")
- X-Algorithm-Version: Explicit version (e.g., "v2")

Response Headers (added):
- X-API-Version-Used: Resolved API version
- X-Algorithm-Version-Used: Algorithm version used for this request
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import structlog

from src.core.algorithm_registry import get_version_for_header, get_algorithm

logger = structlog.get_logger(__name__)


class VersionHeaderMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle API version negotiation.
    
    Resolves requested version from headers, attaches to request state,
    and adds version info to response headers.
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Get version from headers (X-Algorithm-Version takes precedence)
        algorithm_header = request.headers.get("X-Algorithm-Version")
        api_header = request.headers.get("X-API-Version")
        
        # Resolve version
        header_value = algorithm_header or api_header
        resolved_version = get_version_for_header(header_value)
        
        # Attach to request state for downstream use
        request.state.algorithm_version = resolved_version
        
        # Get algorithm details
        try:
            algo = get_algorithm(resolved_version)
            request.state.algorithm = algo
            algorithm_model = algo.embedding_model
        except ValueError:
            algorithm_model = "unknown"
        
        # Log version resolution
        if header_value:
            logger.debug(
                "version_resolved",
                requested=header_value,
                resolved=resolved_version,
            )
        
        # Call next middleware/handler
        response = await call_next(request)
        
        # Add version headers to response
        response.headers["X-API-Version-Used"] = resolved_version
        response.headers["X-Algorithm-Version-Used"] = f"{resolved_version}-{algorithm_model}"
        
        return response
