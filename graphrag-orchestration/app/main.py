from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog
from app.core.config import settings
# Force rebuild - fixed embedder None check and DRIFT API key requirement
from app.middleware.group_isolation import GroupIsolationMiddleware
from app.routers import health, graphrag, orchestration
from app.v3.routers import graphrag_v3, admin  # V3 endpoints (separate from V1/V2)

# NOTE: GraphService and LLMService are core services used by V3
# IndexingService and RetrievalService are legacy V1/V2 only (lazy-loaded in deprecated endpoints)
from app.services import GraphService, LLMService

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown events.
    Initializes and cleans up service connections.
    """
    # Startup
    logger.info("service_startup", config=settings.dict())
    
    # Initialize services (singletons - will be reused across requests)
    try:
        graph_service = GraphService()
        if graph_service.driver:
            # Verify Neo4j connectivity
            with graph_service.driver.session() as session:
                result = session.run("RETURN 1 as ping")
                result.single()
            logger.info("neo4j_connected", uri=graph_service.config.get("NEO4J_URI"))
        else:
            logger.warning("neo4j_not_configured", 
                          message="Neo4j URI not set - graph features disabled")
    except Exception as e:
        logger.error("neo4j_connection_failed", error=str(e))
    
    try:
        llm_service = LLMService()
        if llm_service.llm:
            logger.info("llm_service_initialized", 
                       model=llm_service.config.get("AZURE_OPENAI_DEPLOYMENT_NAME"))
        else:
            logger.warning("llm_not_configured",
                          message="Azure OpenAI not configured - LLM features disabled")
    except Exception as e:
        logger.error("llm_initialization_failed", error=str(e))
    
    yield  # Application runs here
    
    # Shutdown
    logger.info("service_shutdown")
    try:
        graph_service = GraphService()
        graph_service.close()
        logger.info("neo4j_connection_closed")
    except Exception as e:
        logger.error("neo4j_close_failed", error=str(e))


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="""
    GraphRAG Orchestration API
    
    **V3 Endpoints (Recommended):**
    - `/graphrag/v3/index` - Index documents using Neo4j + RAPTOR
    - `/graphrag/v3/query/local` - Local search (entity-focused)
    - `/graphrag/v3/query/global` - Global search (community summaries)
    - `/graphrag/v3/query/drift` - DRIFT multi-step reasoning
    - `/graphrag/v3/stats/{group_id}` - Get indexing statistics
    
    **V1/V2 Endpoints (Deprecated):**
    - Legacy endpoints under `/graphrag/` without `/v3/` prefix are deprecated
    - Will be removed in a future release
    - Use V3 endpoints for new development
    """,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Allow frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom Middleware
app.add_middleware(GroupIsolationMiddleware)

# Include Routers
app.include_router(health.router, tags=["health"])
app.include_router(graphrag.router, prefix="/graphrag", tags=["graphrag"])
app.include_router(orchestration.router, prefix="/orchestrate", tags=["orchestration"])

# V3 Router - Completely separate from V1/V2
# Uses Neo4j ONLY at query time, MS GraphRAG DRIFT for reasoning
app.include_router(graphrag_v3.router, prefix="/graphrag", tags=["graphrag-v3"])

# Admin endpoints for maintenance
app.include_router(admin.router, prefix="/admin", tags=["admin"])
