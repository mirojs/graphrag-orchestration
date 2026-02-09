"""
SPA (Single Page Application) Router

Serves the React frontend and provides MSAL auth setup endpoint.
Replaces the Quart static file serving and auth_setup endpoint.
Updated 2026-02-09 with new file management UI.
"""

import os
import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["spa"])


@router.get("/auth_setup")
async def auth_setup() -> Dict[str, Any]:
    """
    Return MSAL.js configuration for the frontend.

    The frontend fetches this on startup to configure MSAL authentication.
    """
    use_authentication = os.getenv("AZURE_USE_AUTHENTICATION", "").lower() == "true"
    server_app_id = os.getenv("AZURE_SERVER_APP_ID", "")
    client_app_id = os.getenv("AZURE_CLIENT_APP_ID", "")
    tenant_id = os.getenv("AZURE_AUTH_TENANT_ID", os.getenv("AZURE_TENANT_ID", ""))
    enforce_access_control = os.getenv("AZURE_ENFORCE_ACCESS_CONTROL", "").lower() == "true"
    enable_unauthenticated_access = os.getenv("AZURE_ENABLE_UNAUTHENTICATED_ACCESS", "").lower() == "true"

    scopes = []
    if server_app_id:
        scopes = [f"api://{server_app_id}/access_as_user"]

    return {
        "useLogin": use_authentication,
        "requireAccessControl": enforce_access_control,
        "enableUnauthenticatedAccess": enable_unauthenticated_access,
        "msalConfig": {
            "auth": {
                "clientId": client_app_id,
                "authority": f"https://login.microsoftonline.com/{tenant_id}" if tenant_id else "",
                "redirectUri": "/redirect",
                "postLogoutRedirectUri": "/",
                "navigateToLoginRequestUrl": True,
            },
            "cache": {
                "cacheLocation": "sessionStorage",
                "storeAuthStateInCookie": False,
            },
        },
        "loginRequest": {"scopes": scopes},
        "tokenRequest": {"scopes": scopes},
    }


@router.get("/redirect")
async def redirect_page():
    """Empty page for MSAL login redirect."""
    return HTMLResponse("")
