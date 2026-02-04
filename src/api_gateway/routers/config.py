"""
Runtime Configuration Endpoint

Provides dynamic configuration to the frontend based on environment variables.
This allows a single frontend build to work for both B2B and B2C deployments.

Matches azure-search-openai-demo frontend Config interface.
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
    
    Matches azure-search-openai-demo frontend Config type.
    
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
    
    # Frontend Config interface fields (azure-search-openai-demo compatible)
    config = {
        # Auth settings
        "authType": auth_type,
        "clientId": auth_client_id,
        "authority": authority,
        "requireAuth": require_auth,
        
        # Feature flags matching frontend Config interface
        "showMultimodalOptions": os.getenv("ENABLE_MULTIMODAL", "false").lower() == "true",
        "showSemanticRankerOption": False,  # Not used in GraphRAG
        "showQueryRewritingOption": os.getenv("ENABLE_QUERY_REWRITING", "true").lower() == "true",
        "showReasoningEffortOption": os.getenv("ENABLE_REASONING_EFFORT", "false").lower() == "true",
        "streamingEnabled": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
        "defaultReasoningEffort": os.getenv("DEFAULT_REASONING_EFFORT", "medium"),
        "defaultRetrievalReasoningEffort": os.getenv("DEFAULT_RETRIEVAL_REASONING_EFFORT", "medium"),
        "showVectorOption": True,  # GraphRAG always uses vector search
        "showUserUpload": os.getenv("ENABLE_USER_UPLOAD", "true").lower() == "true",
        "showLanguagePicker": os.getenv("ENABLE_LANGUAGE_PICKER", "false").lower() == "true",
        "showSpeechInput": os.getenv("ENABLE_SPEECH_INPUT", "false").lower() == "true",
        "showSpeechOutputBrowser": os.getenv("ENABLE_SPEECH_OUTPUT_BROWSER", "false").lower() == "true",
        "showSpeechOutputAzure": os.getenv("ENABLE_SPEECH_OUTPUT_AZURE", "false").lower() == "true",
        "showChatHistoryBrowser": os.getenv("ENABLE_CHAT_HISTORY_BROWSER", "true").lower() == "true",
        "showChatHistoryCosmos": os.getenv("ENABLE_CHAT_HISTORY_COSMOS", "true").lower() == "true",
        "showAgenticRetrievalOption": os.getenv("ENABLE_AGENTIC_RETRIEVAL", "false").lower() == "true",
        
        # RAG settings
        "ragSearchTextEmbeddings": True,
        "ragSearchImageEmbeddings": os.getenv("ENABLE_IMAGE_EMBEDDINGS", "false").lower() == "true",
        "ragSendTextSources": True,
        "ragSendImageSources": False,
        
        # Source options
        "webSourceEnabled": os.getenv("ENABLE_WEB_SOURCE", "false").lower() == "true",
        "sharepointSourceEnabled": os.getenv("ENABLE_SHAREPOINT_SOURCE", "false").lower() == "true",
        
        # GraphRAG-specific extensions
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
