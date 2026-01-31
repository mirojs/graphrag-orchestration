from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog
import re

logger = structlog.get_logger()

class GroupIsolationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip isolation check for health/metrics/docs/admin endpoints
        skip_paths = ["/health", "/health/detailed", "/metrics", "/docs", "/redoc", "/admin"]
        skip_prefixes = ["/api/v1/openapi.json", "/api/v1/graphrag/health"]
        
        if any(request.url.path.startswith(p) for p in skip_paths + skip_prefixes):
            return await call_next(request)
        
        # Extract group_id from path if present (e.g., /groups/{group_id}/...)
        path_group_id = None
        path_match = re.search(r'/groups/([^/]+)', request.url.path)
        if path_match:
            path_group_id = path_match.group(1)
            
        # Check for X-Group-ID header
        header_group_id = request.headers.get("X-Group-ID")
        
        # Determine which group_id to use
        if path_group_id and header_group_id:
            # Both present: validate they match
            if path_group_id != header_group_id:
                logger.warning(
                    "group_id_mismatch",
                    path=request.url.path,
                    path_group_id=path_group_id,
                    header_group_id=header_group_id
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": f"Group ID mismatch: path has '{path_group_id}' but X-Group-ID header has '{header_group_id}'"
                    }
                )
            group_id = path_group_id
        elif path_group_id:
            # Only path parameter present: use it
            group_id = path_group_id
        elif header_group_id:
            # Only header present: use it
            group_id = header_group_id
        else:
            # Neither present: error
            logger.warning("missing_group_id", path=request.url.path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing X-Group-ID header. Multi-tenancy requirement not met."}
            )
            # Neither present: error
            logger.warning("missing_group_id", path=request.url.path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing X-Group-ID header. Multi-tenancy requirement not met."}
            )
            
        # Inject group_id into request state for downstream use
        request.state.group_id = group_id
        
        # Add context to structured logging
        structlog.contextvars.bind_contextvars(group_id=group_id)
        
        try:
            response = await call_next(request)
            return response
        finally:
            # Ensure per-request context does not leak across requests.
            try:
                structlog.contextvars.clear_contextvars()
            except Exception:
                pass
