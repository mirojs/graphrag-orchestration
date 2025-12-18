from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

logger = structlog.get_logger()

class GroupIsolationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip isolation check for health/metrics/docs/admin endpoints
        skip_paths = ["/health", "/health/detailed", "/metrics", "/docs", "/redoc", "/admin"]
        skip_prefixes = ["/api/v1/openapi.json", "/api/v1/graphrag/health"]
        
        if any(request.url.path.startswith(p) for p in skip_paths + skip_prefixes):
            return await call_next(request)
            
        # Check for X-Group-ID header
        group_id = request.headers.get("X-Group-ID")
        
        if not group_id:
            logger.warning("missing_group_id_header", path=request.url.path)
            # Return 401 Unauthorized if header is missing
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing X-Group-ID header. Multi-tenancy requirement not met."}
            )
            
        # Inject group_id into request state for downstream use
        request.state.group_id = group_id
        
        # Add context to structured logging
        structlog.contextvars.bind_contextvars(group_id=group_id)
        
        response = await call_next(request)
        return response
