from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog
from src.core.config import settings
from src.api_gateway.middleware.group_isolation import GroupIsolationMiddleware
from src.api_gateway.middleware.auth import JWTAuthMiddleware
from src.api_gateway.middleware.correlation import CorrelationIdMiddleware
from src.api_gateway.middleware.version import VersionHeaderMiddleware
from src.api_gateway.routers import health, graphrag, orchestration, hybrid, document_analysis, knowledge_map, config, folders, chat
from src.api_gateway.routers.admin import router as admin_router
from src.worker.hybrid_v2.routers.document_lifecycle import router as document_lifecycle_router
from src.worker.hybrid_v2.routers.maintenance import router as maintenance_router

# NOTE: GraphService and LLMService are core services used by V3
# IndexingService and RetrievalService are legacy V1/V2 only (lazy-loaded in deprecated endpoints)
from src.worker.services import GraphService, LLMService

# Configure structured logging with context variables support
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,  # Merge correlation_id, group_id from context
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
                from src.worker.hybrid.services.neo4j_store import Neo4jStoreV3
                from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3 as Neo4jStoreV3_V2
                from src.core.config import settings as app_settings
                if app_settings.NEO4J_URI and app_settings.NEO4J_USERNAME and app_settings.NEO4J_PASSWORD:
                    # V1 schema (OpenAI 3072-dim embeddings)
                    hybrid_store = Neo4jStoreV3(
                        uri=app_settings.NEO4J_URI,
                        username=app_settings.NEO4J_USERNAME,
                        password=app_settings.NEO4J_PASSWORD,
                    )
                    hybrid_store.initialize_schema()
                    logger.info("hybrid_neo4j_schema_initialized", 
                               message="V1 vector indexes and constraints created")
                    
                    # V2 schema (Voyage 2048-dim embeddings) 
                    hybrid_store_v2 = Neo4jStoreV3_V2(
                        uri=app_settings.NEO4J_URI,
                        username=app_settings.NEO4J_USERNAME,
                        password=app_settings.NEO4J_PASSWORD,
                    )
                    hybrid_store_v2.initialize_schema()
                    logger.info("hybrid_v2_neo4j_schema_initialized", 
                               message="V2 vector indexes (entity_embedding_v2) created")
                else:
                    logger.warning("hybrid_schema_skip",
                                  message="Neo4j credentials incomplete - skipping schema init")
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

# Custom Middleware (order matters: first added = last executed)
# Execution order: CORS → Correlation → Version → JWT → GroupIsolation → Handler

# 1. Correlation ID - generates/propagates trace ID for all requests
app.add_middleware(CorrelationIdMiddleware)

# 2. Version Header - resolves API/algorithm version from request headers
app.add_middleware(VersionHeaderMiddleware)

# 3. JWT Authentication - validates Azure Easy Auth tokens and extracts tenant claims
# Set require_auth=False for development without Easy Auth
app.add_middleware(
    JWTAuthMiddleware,
    auth_type=settings.AUTH_TYPE if hasattr(settings, "AUTH_TYPE") else "B2B",
    require_auth=settings.REQUIRE_AUTH if hasattr(settings, "REQUIRE_AUTH") else False
)

# 4. Group Isolation - enforces tenant isolation using JWT or legacy headers
app.add_middleware(GroupIsolationMiddleware)

# Include Routers
app.include_router(health.router, tags=["health"])
app.include_router(config.router, tags=["config"])
app.include_router(folders.router, tags=["folders"])
app.include_router(chat.router, tags=["chat"])  # OpenAI-compatible chat API

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
# Knowledge Map API - Batch-first Async Document Processing
# ============================================================================
# Follows Azure CU polling pattern with simplified response format
# POST /process -> GET /operations/{id} with Retry-After, 60s TTL, fail-fast
app.include_router(knowledge_map.router, tags=["knowledge-map"])

# ============================================================================
# Document Lifecycle & Maintenance API
# ============================================================================
# Document deprecation, restoration, and hard deletion
app.include_router(document_lifecycle_router, prefix="/lifecycle", tags=["document-lifecycle"])
# Maintenance jobs: GC orphans, stale edges, GDS recompute, health checks
app.include_router(maintenance_router, prefix="/maintenance", tags=["maintenance"])

# ============================================================================
# Admin API - Version Management & Configuration
# ============================================================================
# Requires X-Admin-Key header or admin role in JWT
app.include_router(admin_router, tags=["admin"])

# ============================================================================
# V3 Endpoints - Alternative DRIFT-based Implementation
# ============================================================================
# Deprecated V3 endpoints are intentionally not included.
