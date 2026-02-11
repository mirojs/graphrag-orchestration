"""
Admin API Router

Provides administrative endpoints for:
- Algorithm version management (list, switch default, enable/disable)
- System configuration
- Health and diagnostics

Requires admin role (checked via JWT appRole claim or API key).
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel, Field
import structlog
import os

from src.core.algorithm_registry import (
    ALGORITHM_VERSIONS,
    AlgorithmVersion,
    AlgorithmStatus,
    get_algorithm,
    get_default_version,
    list_versions,
)
from src.core.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================================
# Auth Helpers
# ============================================================================

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")


async def verify_admin(
    request: Request,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
) -> bool:
    """
    Verify admin access via:
    1. X-Admin-Key header matching ADMIN_API_KEY env var
    2. JWT appRole claim with 'Admin' role (set in Entra ID app registration)
    
    Returns True if authorized, raises 403 if not.
    """
    # Check API key
    if ADMIN_API_KEY and x_admin_key == ADMIN_API_KEY:
        return True
    
    # Check JWT claims for admin role (populated by JWTAuthMiddleware)
    roles = getattr(request.state, "roles", [])
    if roles:
        if any(r.lower() == "admin" for r in roles):
            user = getattr(request.state, "user", {})
            logger.info(
                "admin_access_via_role",
                user_id=user.get("oid"),
                username=user.get("preferred_username"),
                roles=roles,
            )
            return True
    
    # For development: allow if no ADMIN_API_KEY is set
    if not ADMIN_API_KEY:
        logger.warning("admin_access_no_key", note="ADMIN_API_KEY not set, allowing access")
        return True
    
    raise HTTPException(
        status_code=403,
        detail="Admin access required. Provide X-Admin-Key header or have Admin role assigned in Entra ID."
    )


# ============================================================================
# Request/Response Models
# ============================================================================

class VersionInfo(BaseModel):
    """Algorithm version information."""
    version: str
    status: str
    enabled: bool
    is_default: bool
    embedding_model: str
    embedding_dim: int
    routes: List[int]
    description: str
    release_date: Optional[str] = None
    sunset_date: Optional[str] = None


class VersionListResponse(BaseModel):
    """Response for listing all versions."""
    default_version: str
    versions: Dict[str, VersionInfo]
    

class SetDefaultRequest(BaseModel):
    """Request to set default version."""
    version: str = Field(..., description="Version to set as default (v1, v2, v3)")


class SetDefaultResponse(BaseModel):
    """Response after setting default version."""
    previous_default: str
    new_default: str
    message: str


class EnableVersionRequest(BaseModel):
    """Request to enable/disable a version."""
    enabled: bool = Field(..., description="Whether to enable or disable")


class VersionStatusResponse(BaseModel):
    """Response after changing version status."""
    version: str
    enabled: bool
    message: str


class CanaryRequest(BaseModel):
    """Request to set canary percentage."""
    percent: int = Field(..., ge=0, le=100, description="Traffic percentage (0-100)")


class CanaryResponse(BaseModel):
    """Response after setting canary."""
    version: str
    canary_percent: int
    message: str


class SystemConfigResponse(BaseModel):
    """System configuration overview."""
    default_algorithm_version: str
    algorithm_v1_enabled: bool
    algorithm_v2_enabled: bool
    algorithm_v3_preview_enabled: bool
    algorithm_v3_canary_percent: int
    voyage_v2_enabled: bool
    worker_preview_url: Optional[str]


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/versions", response_model=VersionListResponse)
async def list_all_versions(
    include_disabled: bool = False,
    _: bool = Depends(verify_admin),
):
    """
    List all algorithm versions and their status.
    
    Returns:
        - default_version: Current default
        - versions: Dict of all versions with metadata
    """
    default = get_default_version()
    versions_data = list_versions(include_disabled=include_disabled)
    
    # Enrich with is_default flag
    versions = {}
    for v, data in versions_data.items():
        versions[v] = VersionInfo(
            version=data["version"],
            status=data["status"],
            enabled=data["enabled"],
            is_default=(v == default),
            embedding_model=data["embedding_model"],
            embedding_dim=data["embedding_dim"],
            routes=data["routes"],
            description=data["description"],
            release_date=data.get("release_date"),
            sunset_date=data.get("sunset_date"),
        )
    
    return VersionListResponse(
        default_version=default,
        versions=versions,
    )


@router.post("/versions/default", response_model=SetDefaultResponse)
async def set_default_version(
    request: SetDefaultRequest,
    _: bool = Depends(verify_admin),
):
    """
    Set the default algorithm version.
    
    This updates the DEFAULT_ALGORITHM_VERSION environment variable.
    Note: Changes require container restart to take full effect.
    
    For immediate effect without restart, clients should use
    X-Algorithm-Version header.
    """
    new_version = request.version
    
    # Validate version exists and is enabled
    if new_version not in ALGORITHM_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown version: {new_version}. Available: {list(ALGORITHM_VERSIONS.keys())}"
        )
    
    algo = ALGORITHM_VERSIONS[new_version]
    if not algo.is_enabled():
        raise HTTPException(
            status_code=400,
            detail=f"Version {new_version} is disabled. Enable it first."
        )
    
    previous = get_default_version()
    
    # Update environment variable (in-memory)
    os.environ["DEFAULT_ALGORITHM_VERSION"] = new_version
    
    # Also update settings object
    settings.DEFAULT_ALGORITHM_VERSION = new_version
    
    logger.info(
        "default_version_changed",
        previous=previous,
        new=new_version,
    )
    
    return SetDefaultResponse(
        previous_default=previous,
        new_default=new_version,
        message=f"Default version changed from {previous} to {new_version}. "
                f"Note: For persistent change, update container environment variable.",
    )


@router.post("/versions/{version}/enable", response_model=VersionStatusResponse)
async def enable_version(
    version: str,
    request: EnableVersionRequest,
    _: bool = Depends(verify_admin),
):
    """
    Enable or disable an algorithm version.
    
    Changes the corresponding feature flag:
    - v1: ALGORITHM_V1_ENABLED
    - v2: ALGORITHM_V2_ENABLED  
    - v3: ALGORITHM_V3_PREVIEW_ENABLED
    """
    if version not in ALGORITHM_VERSIONS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown version: {version}"
        )
    
    # Map version to environment variable
    env_var_map = {
        "v1": "ALGORITHM_V1_ENABLED",
        "v2": "ALGORITHM_V2_ENABLED",
        "v3": "ALGORITHM_V3_PREVIEW_ENABLED",
    }
    
    env_var = env_var_map.get(version)
    if not env_var:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change enable status for version {version}"
        )
    
    # Update environment variable
    os.environ[env_var] = str(request.enabled).lower()
    
    # Update settings object
    setattr(settings, env_var, request.enabled)
    
    action = "enabled" if request.enabled else "disabled"
    logger.info(
        f"version_{action}",
        version=version,
        env_var=env_var,
    )
    
    return VersionStatusResponse(
        version=version,
        enabled=request.enabled,
        message=f"Version {version} {action}. Note: For persistent change, update container environment.",
    )


@router.post("/versions/{version}/canary", response_model=CanaryResponse)
async def set_canary_percent(
    version: str,
    request: CanaryRequest,
    _: bool = Depends(verify_admin),
):
    """
    Set canary traffic percentage for a version.
    
    This controls what percentage of traffic uses the specified version
    when no explicit X-Algorithm-Version header is provided.
    
    Currently only supported for v3.
    """
    if version != "v3":
        raise HTTPException(
            status_code=400,
            detail="Canary deployment only supported for v3"
        )
    
    if version not in ALGORITHM_VERSIONS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown version: {version}"
        )
    
    # Update environment variable
    os.environ["ALGORITHM_V3_CANARY_PERCENT"] = str(request.percent)
    settings.ALGORITHM_V3_CANARY_PERCENT = request.percent
    
    logger.info(
        "canary_percent_changed",
        version=version,
        percent=request.percent,
    )
    
    return CanaryResponse(
        version=version,
        canary_percent=request.percent,
        message=f"Canary traffic for {version} set to {request.percent}%",
    )


@router.get("/config", response_model=SystemConfigResponse)
async def get_system_config(
    _: bool = Depends(verify_admin),
):
    """
    Get current system configuration.
    
    Returns all version-related settings and their current values.
    """
    return SystemConfigResponse(
        default_algorithm_version=getattr(settings, "DEFAULT_ALGORITHM_VERSION", "v2"),
        algorithm_v1_enabled=getattr(settings, "ALGORITHM_V1_ENABLED", True),
        algorithm_v2_enabled=getattr(settings, "ALGORITHM_V2_ENABLED", True),
        algorithm_v3_preview_enabled=getattr(settings, "ALGORITHM_V3_PREVIEW_ENABLED", False),
        algorithm_v3_canary_percent=getattr(settings, "ALGORITHM_V3_CANARY_PERCENT", 0),
        voyage_v2_enabled=getattr(settings, "VOYAGE_V2_ENABLED", False),
        worker_preview_url=getattr(settings, "WORKER_PREVIEW_URL", None),
    )


@router.post("/promote/{from_version}/{to_version}")
async def promote_version(
    from_version: str,
    to_version: str,
    _: bool = Depends(verify_admin),
):
    """
    Promote a version to replace another.
    
    Example: /admin/promote/v2/v3 promotes v3 to be the new default,
    and marks v2 as deprecated.
    
    This is a convenience endpoint that:
    1. Enables the target version if not enabled
    2. Sets the target as default
    3. Logs the promotion for audit
    """
    if from_version not in ALGORITHM_VERSIONS:
        raise HTTPException(status_code=404, detail=f"Unknown version: {from_version}")
    if to_version not in ALGORITHM_VERSIONS:
        raise HTTPException(status_code=404, detail=f"Unknown version: {to_version}")
    
    # Ensure to_version is enabled
    to_algo = ALGORITHM_VERSIONS[to_version]
    if not to_algo.is_enabled():
        # Enable it
        env_var_map = {
            "v1": "ALGORITHM_V1_ENABLED",
            "v2": "ALGORITHM_V2_ENABLED",
            "v3": "ALGORITHM_V3_PREVIEW_ENABLED",
        }
        env_var = env_var_map.get(to_version)
        if env_var:
            os.environ[env_var] = "true"
            setattr(settings, env_var, True)
    
    # Set new default
    previous_default = get_default_version()
    os.environ["DEFAULT_ALGORITHM_VERSION"] = to_version
    settings.DEFAULT_ALGORITHM_VERSION = to_version
    
    logger.info(
        "version_promoted",
        from_version=from_version,
        to_version=to_version,
        previous_default=previous_default,
    )
    
    return {
        "success": True,
        "from_version": from_version,
        "to_version": to_version,
        "previous_default": previous_default,
        "new_default": to_version,
        "message": f"Promoted {to_version} to default. {from_version} remains available. "
                   f"For persistent change, update container environment variables.",
        "next_steps": [
            f"Update container env: DEFAULT_ALGORITHM_VERSION={to_version}",
            f"Consider setting ALGORITHM_V3_PREVIEW_ENABLED=true if promoting to v3",
            f"Monitor metrics for 48h before deprecating {from_version}",
        ],
    }


@router.get("/health/detailed")
async def detailed_health(
    _: bool = Depends(verify_admin),
):
    """
    Detailed health check with version information.
    
    Returns system status including:
    - Current default version
    - All enabled versions
    - Container environment
    """
    return {
        "status": "healthy",
        "default_version": get_default_version(),
        "enabled_versions": [
            v for v, algo in ALGORITHM_VERSIONS.items() 
            if algo.is_enabled()
        ],
        "environment": {
            "DEFAULT_ALGORITHM_VERSION": os.environ.get("DEFAULT_ALGORITHM_VERSION", "v2"),
            "ALGORITHM_V1_ENABLED": os.environ.get("ALGORITHM_V1_ENABLED", "true"),
            "ALGORITHM_V2_ENABLED": os.environ.get("ALGORITHM_V2_ENABLED", "true"),
            "ALGORITHM_V3_PREVIEW_ENABLED": os.environ.get("ALGORITHM_V3_PREVIEW_ENABLED", "false"),
            "WORKER_PREVIEW_URL": os.environ.get("WORKER_PREVIEW_URL", ""),
        },
    }
