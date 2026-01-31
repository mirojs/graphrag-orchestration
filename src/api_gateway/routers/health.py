from fastapi import APIRouter
from typing import Dict, Any
import structlog

from src.worker.services import GraphService, LLMService, VectorStoreService

router = APIRouter()
logger = structlog.get_logger()


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """
    Health check endpoint for container orchestration.
    """
    return {"status": "healthy", "service": "graphrag-orchestration"}


@router.get("/health/detailed")
async def detailed_health_check() -> Dict[str, Any]:
    """
    Detailed health check including all service dependencies.
    """
    health_status = {
        "status": "healthy",
        "service": "graphrag-orchestration",
        "components": {}
    }
    
    # Check Neo4j connectivity
    try:
        graph_service = GraphService()
        if graph_service.driver:
            # Run a simple query to verify connectivity
            with graph_service.driver.session() as session:
                result = session.run("RETURN 1 as ping")
                result.single()
            health_status["components"]["neo4j"] = {
                "status": "healthy",
                "uri": graph_service.config.get("NEO4J_URI", "not configured")
            }
        else:
            health_status["components"]["neo4j"] = {
                "status": "not_configured",
                "message": "Neo4j driver not initialized"
            }
    except Exception as e:
        logger.error("neo4j_health_check_failed", error=str(e))
        health_status["components"]["neo4j"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check LLM service
    try:
        llm_service = LLMService()
        health_status["components"]["llm"] = {
            "status": "healthy" if llm_service.llm else "not_configured",
            "model": llm_service.config.get("AZURE_OPENAI_DEPLOYMENT_NAME", "not configured")
        }
    except Exception as e:
        logger.error("llm_health_check_failed", error=str(e))
        health_status["components"]["llm"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check Vector store
    try:
        vector_service = VectorStoreService()
        health_status["components"]["vector_store"] = {
            "status": "healthy",
            "type": vector_service.store_type
        }
    except Exception as e:
        logger.error("vector_store_health_check_failed", error=str(e))
        health_status["components"]["vector_store"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    return health_status


@router.get("/metrics")
async def metrics():
    """
    Placeholder for Prometheus metrics.
    """
    return {"status": "ok"}


@router.get("/debug/config")
async def debug_config() -> Dict[str, Any]:
    """
    Debug endpoint to check configuration values.
    """
    from src.core.config import settings
    return {
        "neo4j": {
            "uri": settings.NEO4J_URI,
            "username": settings.NEO4J_USERNAME,
            "password_set": bool(settings.NEO4J_PASSWORD),
            "password_length": len(settings.NEO4J_PASSWORD) if settings.NEO4J_PASSWORD else 0
        },
        "azure_openai": {
            "endpoint": settings.AZURE_OPENAI_ENDPOINT,
            "deployment": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            "api_key_set": bool(settings.AZURE_OPENAI_API_KEY),
            "bearer_token_set": bool(settings.AZURE_OPENAI_BEARER_TOKEN)
        },
        "cosmos": {
            "endpoint": settings.COSMOS_ENDPOINT,
            "key_set": bool(settings.COSMOS_KEY),
            "database": settings.COSMOS_DATABASE_NAME
        },
        "group_isolation": settings.ENABLE_GROUP_ISOLATION
    }


@router.get("/debug/config")
async def debug_config() -> Dict[str, Any]:
    """
    Debug endpoint to check configuration values.
    """
    from src.core.config import settings
    return {
        "neo4j_uri": settings.NEO4J_URI,
        "neo4j_username": settings.NEO4J_USERNAME,
        "neo4j_password_set": bool(settings.NEO4J_PASSWORD),
        "azure_openai_endpoint": settings.AZURE_OPENAI_ENDPOINT,
        "cosmos_endpoint": settings.COSMOS_ENDPOINT,
        "vector_store_type": settings.VECTOR_STORE_TYPE,
        "enable_group_isolation": settings.ENABLE_GROUP_ISOLATION,
    }
