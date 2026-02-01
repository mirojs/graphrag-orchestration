"""
Correlation ID Middleware

Generates and propagates correlation IDs for distributed tracing.
Essential for debugging requests across API Gateway → Worker → External Services.

Features:
- Auto-generate UUID if no X-Correlation-ID header provided
- Propagate to request.state for downstream handlers
- Add to response headers for client tracking
- Bind to structlog context for all log messages

Usage:
    # In any handler or service:
    correlation_id = request.state.correlation_id
    
    # In logs (auto-bound):
    logger.info("processing_request")  # correlation_id automatically included
"""

import uuid
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import structlog

logger = structlog.get_logger(__name__)

# Header name for correlation ID (standard across services)
CORRELATION_ID_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware to generate/propagate correlation IDs for request tracing.
    
    Flow:
    1. Check for incoming X-Correlation-ID header
    2. Generate new UUID if not present
    3. Bind to structlog context (all logs include it)
    4. Set in request.state for downstream access
    5. Add to response headers for client tracking
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate correlation ID
        correlation_id = request.headers.get(CORRELATION_ID_HEADER)
        
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        # Store in request state for downstream handlers
        request.state.correlation_id = correlation_id
        
        # Bind to structlog context (all logs in this request will include it)
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
        )
        
        try:
            # Process request
            response = await call_next(request)
            
            # Add correlation ID to response headers
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            
            return response
            
        finally:
            # Clear context to prevent leaking between requests
            try:
                structlog.contextvars.clear_contextvars()
            except Exception:
                pass


def get_correlation_id(request: Request) -> str:
    """
    FastAPI dependency to get correlation ID from request.
    
    Usage:
        @router.get("/endpoint")
        async def handler(correlation_id: str = Depends(get_correlation_id)):
            ...
    """
    return getattr(request.state, "correlation_id", str(uuid.uuid4()))


def get_correlation_headers(correlation_id: Optional[str] = None) -> dict:
    """
    Get headers dict for propagating correlation ID to downstream services.
    
    Usage:
        headers = get_correlation_headers(request.state.correlation_id)
        response = await httpx.post(url, headers=headers, ...)
    """
    if correlation_id:
        return {CORRELATION_ID_HEADER: correlation_id}
    return {}
