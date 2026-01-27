from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog
from app.core.config import settings
# Force rebuild - fixed embedder None check and DRIFT API key requirement
from app.middleware.group_isolation import GroupIsolationMiddleware
from app.routers import health, graphrag, orchestration, hybrid, document_analysis

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
            
            # Initialize Neo4j schema for hybrid routes (vector indexes, constraints)
            try:
                from app.hybrid.services.neo4j_store import Neo4jStoreV3
                from app.core.config import settings as app_settings
                hybrid_store = Neo4jStoreV3(
                    uri=app_settings.NEO4J_URI,
                    username=app_settings.NEO4J_USERNAME,
                    password=app_settings.NEO4J_PASSWORD,
                )
                hybrid_store.initialize_schema()
                logger.info("hybrid_neo4j_schema_initialized", 
                           message="Vector indexes and constraints created")
            except Exception as e:
                logger.error("hybrid_schema_initialization_failed", error=str(e))
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
            if llm_service.embed_model:
                logger.info(
                    "embedder_initialized",
                    deployment=llm_service.config.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
                    endpoint=llm_service.config.get("AZURE_OPENAI_ENDPOINT"),
                )
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

    **Hybrid Endpoints (Primary):**
    - `/hybrid/query` - 4-way routing (Route 1-4)

    **Deprecated / Archived:**
    - The legacy GraphRAG V3 implementation has been archived under `app/archive/v3` and is not mounted.
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

# ============================================================================
# DEPRECATED V1/V2 Endpoints - Use Hybrid Pipeline or V3 instead
# ============================================================================
# Legacy graphrag router (replaced by hybrid pipeline)
# app.include_router(graphrag.router, prefix="/graphrag", tags=["graphrag"])
# Legacy orchestration router (replaced by hybrid pipeline)
# app.include_router(orchestration.router, prefix="/orchestrate", tags=["orchestration"])

# ============================================================================
# NEW ARCHITECTURE: Hybrid Pipeline (LazyGraphRAG + HippoRAG 2)
# ============================================================================
# This is the primary interface for the 4-way routing system
app.include_router(hybrid.router, prefix="/hybrid", tags=["hybrid-pipeline"])

# ============================================================================
# Document Analysis API - Simplified Drop-in Replacement for Azure CU
# ============================================================================
# Unified, simplified API for document analysis (replaces Azure Content Understanding)
app.include_router(document_analysis.router, tags=["document-analysis"])

# ============================================================================
# V3 Endpoints - Alternative DRIFT-based Implementation
# ============================================================================
# Deprecated V3 endpoints are intentionally not included.
