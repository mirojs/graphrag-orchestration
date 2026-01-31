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
    
    config = {
        "authType": auth_type,
        "clientId": os.getenv("CLIENT_ID", ""),
        "authority": os.getenv("AUTHORITY", ""),
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
