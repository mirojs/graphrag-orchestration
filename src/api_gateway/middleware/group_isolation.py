"""
Group Isolation Middleware

Ensures tenant isolation by requiring a valid group_id on all requests.

Priority for group_id extraction (highest to lowest):
1. request.state.group_id (set by JWTAuthMiddleware from token claims)
2. Path parameter /groups/{group_id}/...
3. X-Group-ID header (DEPRECATED - for backward compatibility only)

Security Note:
- JWT-based group_id is authoritative and cannot be overridden
- X-Group-ID header will be removed in future versions
- Use Azure AD groups for production multi-tenancy
"""

import re

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from src.core.config import settings

logger = structlog.get_logger()

# Use settings for legacy header control (defaults to True for backward compatibility)
ALLOW_LEGACY_GROUP_HEADER = getattr(settings, "ALLOW_LEGACY_GROUP_HEADER", True)


class GroupIsolationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce tenant isolation via group_id.
    
    Works in conjunction with JWTAuthMiddleware:
    - If JWT provides group_id, it is authoritative
    - Falls back to path/header only when JWT doesn't provide it
    """
    
    async def dispatch(self, request: Request, call_next):
        # Skip isolation check for health/metrics/docs/admin endpoints
        skip_paths = ["/health", "/health/detailed", "/metrics", "/docs", "/redoc", "/admin", "/openapi.json"]
        skip_prefixes = ["/api/v1/openapi.json", "/api/v1/graphrag/health"]
        
        if any(request.url.path.startswith(p) for p in skip_paths + skip_prefixes):
            return await call_next(request)
        
        # Priority 1: JWT-extracted group_id (set by JWTAuthMiddleware)
        jwt_group_id = getattr(request.state, "group_id", None)
        
        # Priority 2: Extract group_id from path if present (e.g., /groups/{group_id}/...)
        path_group_id = None
        path_match = re.search(r'/groups/([^/]+)', request.url.path)
        if path_match:
            path_group_id = path_match.group(1)
        
        # Priority 3: X-Group-ID header (DEPRECATED)
        header_group_id = request.headers.get("X-Group-ID")
        
        # Determine final group_id with proper priority
        group_id = None
        
        if jwt_group_id:
            # JWT is authoritative - use it
            group_id = jwt_group_id
            
            # Validate path matches JWT if path contains group_id
            if path_group_id and path_group_id != jwt_group_id:
                logger.warning(
                    "group_id_path_jwt_mismatch",
                    path=request.url.path,
                    path_group_id=path_group_id,
                    jwt_group_id=jwt_group_id
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": f"Access denied: Your token grants access to group '{jwt_group_id}' but path requires '{path_group_id}'"
                    }
                )
            
            # Warn if legacy header is also present (it's ignored)
            if header_group_id and header_group_id != jwt_group_id:
                logger.warning(
                    "ignoring_legacy_x_group_id_header",
                    header_value=header_group_id,
                    jwt_value=jwt_group_id,
                    message="X-Group-ID header is deprecated. JWT group claim takes precedence."
                )
        
        elif path_group_id:
            # No JWT, use path parameter
            group_id = path_group_id
            
            # Validate header matches path if both present
            if header_group_id and header_group_id != path_group_id:
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
        
        elif header_group_id and ALLOW_LEGACY_GROUP_HEADER:
            # Fallback to legacy header (with deprecation warning)
            group_id = header_group_id
            logger.warning(
                "using_deprecated_x_group_id_header",
                group_id=header_group_id,
                path=request.url.path,
                message="X-Group-ID header is deprecated. Use JWT authentication with Azure AD groups."
            )
        
        else:
            # No group_id available from any source
            logger.warning("missing_group_id", path=request.url.path)
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required. No valid group identity found. "
                              "Use JWT authentication or X-Group-ID header (deprecated)."
                }
            )
        
        # Only set request.state.group_id if not already set by JWT middleware
        # This preserves JWT authority while allowing path/header fallback
        if not jwt_group_id:
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
