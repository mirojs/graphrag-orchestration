"""
Runtime Configuration Endpoint

Provides dynamic configuration to the frontend based on environment variables.
This allows a single frontend build to work for both B2B and B2C deployments.
"""

from fastapi import APIRouter
from typing import Dict, Any
import os

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_config() -> Dict[str, Any]:
    """
    Get runtime configuration for the frontend.
    
    This endpoint returns configuration that varies between deployments
    (B2B vs B2C, feature flags, etc.) so the frontend can adapt without
    rebuilding.
    
    Returns:
        Configuration object with auth settings and feature flags
    """
    auth_type = os.getenv("AUTH_TYPE", "B2B")
    auth_client_id = os.getenv("AUTH_CLIENT_ID", os.getenv("CLIENT_ID", ""))
    auth_tenant_id = os.getenv("AUTH_TENANT_ID", "")
    require_auth = os.getenv("REQUIRE_AUTH", "false").lower() == "true"
    
    # Build authority URL for MSAL
    if auth_tenant_id:
        authority = f"https://login.microsoftonline.com/{auth_tenant_id}"
    else:
        authority = os.getenv("AUTHORITY", "")
    
    config = {
        "authType": auth_type,
        "clientId": auth_client_id,
        "authority": authority,
        "requireAuth": require_auth,
        "features": {
            "showAdminPanel": auth_type == "B2B",
            "showFolders": os.getenv("ENABLE_FOLDERS", "true").lower() == "true",
            "showUsageDashboard": os.getenv("ENABLE_USAGE_TRACKING", "true").lower() == "true",
        },
        "routes": {
            "local_search": True,
            "global_search": True,
            "drift_multi_hop": True,
        },
        "apiVersion": "v2",
    }
    
    return config
