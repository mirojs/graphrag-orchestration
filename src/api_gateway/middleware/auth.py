"""
JWT validation middleware for Azure Easy Auth integration.

Validates JWT tokens from Azure App Service Easy Auth and extracts
tenant claims (group_id or user_id) based on deployment type.

Easy Auth Headers:
- X-MS-TOKEN-AAD-ID-TOKEN: JWT token from Azure AD
- X-MS-CLIENT-PRINCIPAL: Base64-encoded claims (backup)

Token Claims:
- B2B: groups[0] → group_id (organization tenant)
- B2C: oid → user_id (individual tenant)
"""

import base64
import json
import logging
from typing import Optional

from fastapi import Header, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from src.core.config import settings

logger = logging.getLogger(__name__)

# Security scheme for OpenAPI docs
security = HTTPBearer()


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate JWT tokens and extract tenant claims.
    
    Sets request.state.group_id and request.state.user_id for downstream handlers.
    """
    
    def __init__(self, app, auth_type: str = "B2B", require_auth: bool = True):
        """
        Initialize JWT auth middleware.
        
        Args:
            app: FastAPI application
            auth_type: "B2B" (Azure AD with groups) or "B2C" (Azure AD B2C with oid)
            require_auth: If True, reject requests without valid tokens
        """
        super().__init__(app)
        self.auth_type = auth_type.upper()
        self.require_auth = require_auth
        
    async def dispatch(self, request: Request, call_next):
        """Process request and validate JWT token."""
        
        # Skip auth for health and config endpoints
        if request.url.path in ["/health", "/config", "/docs", "/openapi.json", "/redoc"]:
            return await call_next(request)
        
        try:
            # Extract token from Easy Auth headers or Authorization header
            token = self._extract_token(request)
            
            if token:
                # Validate and decode token
                claims = self._decode_token(token)
                
                # Extract tenant claims based on auth type
                if self.auth_type == "B2B":
                    # B2B: Use groups[0] as group_id
                    groups = claims.get("groups", [])
                    if not groups:
                        if settings.GROUP_ID_OVERRIDE:
                            request.state.group_id = settings.GROUP_ID_OVERRIDE
                            request.state.user_id = claims.get("oid")
                            logger.warning(
                                "auth_group_override_used",
                                group_id=request.state.group_id,
                                user_id=request.state.user_id,
                                message="No group claim found in token. Using GROUP_ID_OVERRIDE."
                            )
                            groups = [request.state.group_id]
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="No group claim found in token. User must be assigned to an Azure AD group."
                        )
                    request.state.group_id = groups[0]
                    request.state.user_id = claims.get("oid")  # Optional user tracking
                    
                elif self.auth_type == "B2C":
                    # B2C: Use oid as user_id (individual tenant)
                    user_id = claims.get("oid") or claims.get("sub")
                    if not user_id:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="No user identifier found in token"
                        )
                    request.state.user_id = user_id
                    request.state.group_id = user_id  # Use user_id as group_id for consistency
                    
                else:
                    raise ValueError(f"Unknown auth_type: {self.auth_type}")
                
                logger.info(
                    f"Authenticated request: group_id={request.state.group_id}, "
                    f"user_id={request.state.user_id}, path={request.url.path}"
                )
                
            elif self.require_auth:
                # No token found and auth is required
                logger.warning(
                    "auth_no_token_headers: %s",
                    list(request.headers.keys())
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required. No valid token found.",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            else:
                # Auth not required, proceed without token claims
                # Only set to None if GroupIsolation middleware hasn't already set a value
                if not getattr(request.state, "group_id", None):
                    request.state.group_id = None
                if not getattr(request.state, "user_id", None):
                    request.state.user_id = None
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"JWT validation error: {e}", exc_info=True)
            if self.require_auth:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid authentication: {str(e)}",
                    headers={"WWW-Authenticate": "Bearer"}
                )
        
        return await call_next(request)
    
    def _extract_token(self, request: Request) -> Optional[str]:
        """
        Extract JWT token from request headers.
        
        Priority:
        1. X-MS-TOKEN-AAD-ID-TOKEN (Easy Auth)
        2. X-MS-CLIENT-PRINCIPAL (Easy Auth backup)
        3. Authorization: Bearer <token>
        """
        # 1. Easy Auth primary header
        easy_auth_token = request.headers.get("X-MS-TOKEN-AAD-ID-TOKEN")
        if easy_auth_token:
            return easy_auth_token
        
        # 2. Easy Auth backup (base64-encoded claims)
        client_principal = request.headers.get("X-MS-CLIENT-PRINCIPAL")
        if client_principal:
            try:
                decoded = base64.b64decode(client_principal).decode("utf-8")
                principal = json.loads(decoded)
                # Extract access token or id token
                return principal.get("access_token") or principal.get("id_token")
            except Exception as e:
                logger.warning(f"Failed to parse X-MS-CLIENT-PRINCIPAL: {e}")
        
        # 3. Forwarded/Original Authorization headers (some proxies strip Authorization)
        auth_header = (
            request.headers.get("X-Forwarded-Authorization")
            or request.headers.get("X-Original-Authorization")
            or request.headers.get("Authorization")
        )
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        
        return None
    
    def _decode_token(self, token: str) -> dict:
        """
        Decode and validate JWT token.
        
        Note: In production, this should validate:
        - Token signature using Azure AD public keys (JWKS)
        - Issuer (iss claim)
        - Audience (aud claim)
        - Expiration (exp claim)
        
        For Easy Auth, Azure App Service already validates the token,
        so we can safely decode without re-verification.
        """
        try:
            # Decode without verification (Easy Auth already validated)
            # In production without Easy Auth, use jwt.decode() with verify=True
            claims = jwt.get_unverified_claims(token)
            return claims
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid JWT token: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"}
            )


def get_group_id(
    request: Request,
    x_group_id: Optional[str] = Header(None, alias="X-Group-ID")
) -> str:
    """
    Dependency to extract group_id from request state or fallback to header.
    
    Priority:
    1. request.state.group_id (set by JWT middleware)
    2. X-Group-ID header (legacy, trusted environments only)
    
    Args:
        request: FastAPI request
        x_group_id: Legacy X-Group-ID header
        
    Returns:
        str: Group ID for tenant isolation
        
    Raises:
        HTTPException: If no group_id available
    """
    # Try JWT-extracted group_id first
    if hasattr(request.state, "group_id") and request.state.group_id:
        return request.state.group_id
    
    # Fallback to X-Group-ID header (legacy)
    if x_group_id:
        logger.warning(f"Using legacy X-Group-ID header: {x_group_id}")
        return x_group_id
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Group ID not found. Authentication required."
    )


def get_user_id(
    request: Request,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
) -> str:
    """
    Dependency to extract user_id from request state or fallback to header.
    
    Priority:
    1. request.state.user_id (set by JWT middleware)
    2. X-User-ID header (legacy, trusted environments only)
    
    Args:
        request: FastAPI request
        x_user_id: Legacy X-User-ID header
        
    Returns:
        str: User ID for tracking
        
    Raises:
        HTTPException: If no user_id available
    """
    # Try JWT-extracted user_id first
    if hasattr(request.state, "user_id") and request.state.user_id:
        return request.state.user_id
    
    # Fallback to X-User-ID header (legacy)
    if x_user_id:
        logger.warning(f"Using legacy X-User-ID header: {x_user_id}")
        return x_user_id
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User ID not found. Authentication required."
    )
