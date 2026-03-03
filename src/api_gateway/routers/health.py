from fastapi import APIRouter, HTTPException, Header, Request
from typing import Dict, Any
import os
import structlog

from src.worker.services import GraphService, LLMService, VectorStoreService

router = APIRouter()
logger = structlog.get_logger()


@router.get("/health")
@router.head("/health")
async def health_check() -> Dict[str, str]:
    """
    Health check endpoint for container orchestration.
    Supports both GET and HEAD (used by Azure health probes).
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
            "error": "connection_failed"
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
            "error": "service_unavailable"
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
            "error": "service_unavailable"
        }
        health_status["status"] = "degraded"
    
    return health_status


@router.get("/health/stream-test")
async def stream_test():
    """Diagnostic: test if SSE streaming works through EasyAuth proxy."""
    import asyncio
    from fastapi.responses import StreamingResponse

    async def generate():
        for i in range(10):
            yield f'{{"tick": {i}, "ts": "{__import__("datetime").datetime.utcnow().isoformat()}Z"}}\n'
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/metrics")
async def metrics() -> Dict[str, Any]:
    """
    Application metrics endpoint.
    Returns JSON metrics for service health, component status, and resource usage.
    """
    components: Dict[str, Any] = {}

    # Neo4j
    try:
        graph_service = GraphService()
        if graph_service.driver:
            with graph_service.driver.session() as session:
                result = session.run("RETURN 1 AS ping")
                result.single()
            components["neo4j"] = {"status": 1}
        else:
            components["neo4j"] = {"status": 0}
    except Exception:
        components["neo4j"] = {"status": 0}

    # LLM service
    try:
        llm_service = LLMService()
        components["llm"] = {
            "status": 1 if llm_service.llm else 0,
            "model": llm_service.config.get("AZURE_OPENAI_DEPLOYMENT_NAME", "unknown"),
        }
    except Exception:
        components["llm"] = {"status": 0}

    # Vector store
    try:
        vector_service = VectorStoreService()
        components["vector_store"] = {
            "status": 1,
            "type": vector_service.store_type,
        }
    except Exception:
        components["vector_store"] = {"status": 0}

    all_up = all(c.get("status") == 1 for c in components.values())

    return {
        "status": "healthy" if all_up else "degraded",
        "components": components,
    }


@router.get("/debug/config")
async def debug_config(
    request: Request,
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
) -> Dict[str, Any]:
    """
    Debug endpoint to check configuration status (admin-only).
    Only exposes boolean flags — never raw values.
    """
    # Inline admin check (health router doesn't use admin dependency)
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Admin access required")

    from src.core.config import settings
    return {
        "neo4j": {
            "uri_set": bool(settings.NEO4J_URI),
            "username_set": bool(settings.NEO4J_USERNAME),
            "password_set": bool(settings.NEO4J_PASSWORD),
        },
        "azure_openai": {
            "endpoint_set": bool(settings.AZURE_OPENAI_ENDPOINT),
            "deployment_set": bool(settings.AZURE_OPENAI_DEPLOYMENT_NAME),
            "api_key_set": bool(settings.AZURE_OPENAI_API_KEY),
        },
        "cosmos": {
            "endpoint_set": bool(settings.COSMOS_ENDPOINT),
            "key_set": bool(settings.COSMOS_KEY),
            "database_set": bool(settings.COSMOS_DATABASE_NAME),
        },
        "group_isolation": settings.ENABLE_GROUP_ISOLATION,
    }
