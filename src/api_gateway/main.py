import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import os

from dotenv import load_dotenv
load_dotenv()  # pick up .env for local development; no-op in containerized deployments

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import structlog
import logging
from src.core.config import settings
from src.api_gateway.middleware.group_isolation import GroupIsolationMiddleware
from src.api_gateway.middleware.auth import JWTAuthMiddleware
from src.api_gateway.middleware.correlation import CorrelationIdMiddleware
from src.api_gateway.middleware.version import VersionHeaderMiddleware
from src.api_gateway.routers import (
    health, graphrag, orchestration, hybrid, document_analysis, knowledge_map,
    config, folders, chat,
    spa, files, chat_history, file_metadata, speech,
    documents,
)
from src.api_gateway.routers.admin import router as admin_router
from src.api_gateway.routers.dashboard import router as dashboard_router
from src.worker.hybrid_v2.routers.document_lifecycle import router as document_lifecycle_router
from src.worker.hybrid_v2.routers.maintenance import router as maintenance_router

# NOTE: GraphService and LLMService are core services used by V3
# IndexingService and RetrievalService are legacy V1/V2 only (lazy-loaded in deprecated endpoints)
from src.worker.services import GraphService, LLMService

# Configure standard logging level
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Configure structured logging with context variables support
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,  # Merge correlation_id, group_id from context
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

# Frontend static directory
STATIC_DIR = Path(os.getenv("FRONTEND_STATIC_DIR", "/app/static"))


async def _auto_resume_zombie_analyses(app: FastAPI):
    """Detect folders stuck in 'analyzing' and auto-resume their pipelines.

    Runs once after startup.  Uses the same code path as the /analyze endpoint
    but skips already-processed files (file-level resume) and already-completed
    pipeline steps (step checkpoint on GroupMeta).
    """
    await asyncio.sleep(10)  # let all services finish initializing

    try:
        from src.worker.services.graph_service import GraphService

        driver = GraphService().driver
        if driver is None:
            return

        # Find zombie folders: status = "analyzing" means a previous container
        # was killed mid-pipeline.
        with driver.session() as session:
            records = list(session.run("""
                MATCH (f:Folder {analysis_status: "analyzing"})
                RETURN f.id AS folder_id, f.name AS folder_name,
                       f.group_id AS partition_id, f.analysis_group_id AS neo4j_gid,
                       f.analysis_files_processed AS processed,
                       f.analysis_files_total AS total
            """))

        if not records:
            logger.info("auto_resume: no zombie analyses found")
            return

        doc_sync = getattr(app.state, "document_sync_service", None)
        blob_manager = getattr(app.state, "user_blob_manager", None)
        if not doc_sync or not blob_manager:
            logger.warning("auto_resume: doc_sync or blob_manager not available, skipping")
            return

        for rec in records:
            folder_id = rec["folder_id"]
            folder_name = rec["folder_name"]
            partition_id = rec["partition_id"]
            neo4j_gid = rec["neo4j_gid"]

            if not neo4j_gid or not partition_id:
                logger.warning(f"auto_resume: skipping folder {folder_id} — missing neo4j_gid or partition_id")
                continue

            logger.info(
                "auto_resume: resuming analysis",
                folder_id=folder_id,
                folder_name=folder_name,
                processed=rec["processed"],
                total=rec["total"],
            )

            try:
                # Resolve blob list (same logic as analyze_folder endpoint)
                from src.api_gateway.routers.files import _resolve_folder_path
                folder_path = await _resolve_folder_path(partition_id, folder_id)
                blobs = await blob_manager.list_blobs_recursive(partition_id, folder_path or folder_name)

                if not blobs:
                    logger.warning(f"auto_resume: no blobs found for folder {folder_id}, marking stale")
                    with driver.session() as session:
                        session.run("""
                            MATCH (f:Folder {id: $fid, group_id: $pid})
                            SET f.analysis_status = 'stale',
                                f.analysis_error = 'Auto-resume found no files'
                        """, fid=folder_id, pid=partition_id)
                    continue

                from src.api_gateway.routers.folders import _run_folder_analysis
                asyncio.create_task(
                    _run_folder_analysis(
                        doc_sync=doc_sync,
                        blobs=blobs,
                        neo4j_gid=neo4j_gid,
                        folder_id=folder_id,
                        folder_name=folder_name,
                        partition_id=partition_id,
                    )
                )
                logger.info(f"auto_resume: kicked off analysis for folder {folder_id}")

            except Exception as e:
                logger.error(f"auto_resume: failed for folder {folder_id}: {e}")

    except Exception as e:
        logger.error(f"auto_resume: top-level error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown events.
    Initializes and cleans up service connections.
    """
    # Startup
    # Log config with secrets redacted
    _secret_keys = {
        "AZURE_OPENAI_API_KEY", "NEO4J_PASSWORD", "COSMOS_KEY", "VOYAGE_API_KEY",
        "AZURE_SEARCH_API_KEY", "AURA_DS_CLIENT_SECRET", "AZURE_DOCUMENT_INTELLIGENCE_KEY",
        "LLAMA_CLOUD_API_KEY", "ADMIN_API_KEY", "AZURE_OPENAI_BEARER_TOKEN",
        "AZURE_OPENAI_API_KEY_SMALL", "REDIS_PASSWORD",
    }
    _safe_config = {
        k: "***" if k in _secret_keys else v
        for k, v in settings.dict().items()
    }
    logger.info("service_startup", config=_safe_config)
    
    # Initialize services (singletons - will be reused across requests)
    try:
        graph_service = GraphService()
        if graph_service.driver:
            # Verify Neo4j connectivity (async-safe: run in thread to avoid blocking event loop)
            import asyncio
            loop = asyncio.get_running_loop()
            def _ping():
                with graph_service.driver.session() as session:
                    result = session.run("RETURN 1 as ping")
                    result.single()
            await loop.run_in_executor(None, _ping)
            logger.info("neo4j_connected", uri=graph_service.config.get("NEO4J_URI"))
            
            # Initialize Neo4j schema for hybrid routes (vector indexes, constraints)
            try:
                from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3 as Neo4jStoreV3_V2
                from src.core.config import settings as app_settings
                if app_settings.NEO4J_URI and app_settings.NEO4J_USERNAME and app_settings.NEO4J_PASSWORD:
                    # V2 schema (Voyage 2048-dim embeddings) 
                    hybrid_store_v2 = Neo4jStoreV3_V2(
                        uri=app_settings.NEO4J_URI,
                        username=app_settings.NEO4J_USERNAME,
                        password=app_settings.NEO4J_PASSWORD,
                    )
                    hybrid_store_v2.initialize_schema()
                    logger.info("hybrid_v2_neo4j_schema_initialized",
                               message="V2 vector indexes (entity_embedding) created")

                    # Initialize DocumentSyncService for file→graph sync
                    try:
                        from src.api_gateway.services.document_sync import DocumentSyncService
                        app.state.document_sync_service = DocumentSyncService()
                        logger.info("document_sync_service_initialized")
                    except Exception as e:
                        logger.error("document_sync_service_init_failed", error=str(e))
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
                       model=llm_service.config.get("AZURE_OPENAI_DEPLOYMENT_NAME"),
                       embedder=app_settings.VOYAGE_MODEL_NAME,
                       embedding_dim=app_settings.VOYAGE_EMBEDDING_DIM)
        else:
            logger.warning("llm_not_configured",
                          message="Azure OpenAI not configured - LLM features disabled")
    except Exception as e:
        logger.error("llm_initialization_failed", error=str(e))
    
    # ====================================================================
    # Initialize Frontend Services (Cosmos DB, ADLS, Azure Credential)
    # ====================================================================
    azure_credential = None

    try:
        running_on_azure = (
            os.getenv("WEBSITE_HOSTNAME") is not None
            or os.getenv("RUNNING_IN_PRODUCTION") is not None
        )

        if running_on_azure:
            from azure.identity.aio import ManagedIdentityCredential
            client_id = os.getenv("AZURE_CLIENT_ID")
            azure_credential = (
                ManagedIdentityCredential(client_id=client_id)
                if client_id
                else ManagedIdentityCredential()
            )
        else:
            from azure.identity.aio import AzureDeveloperCliCredential
            tenant_id = os.getenv("AZURE_TENANT_ID")
            azure_credential = (
                AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
                if tenant_id
                else AzureDeveloperCliCredential(process_timeout=60)
            )

        app.state.azure_credential = azure_credential

        # Chat history (Cosmos DB)
        if os.getenv("USE_CHAT_HISTORY_COSMOS", "").lower() == "true":
            cosmosdb_account = os.getenv("AZURE_COSMOSDB_ACCOUNT")
            history_db = os.getenv("AZURE_CHAT_HISTORY_DATABASE")
            history_container_name = os.getenv("AZURE_CHAT_HISTORY_CONTAINER")

            if cosmosdb_account and history_db and history_container_name:
                from azure.cosmos.aio import CosmosClient
                cosmos_client = CosmosClient(
                    url=f"https://{cosmosdb_account}.documents.azure.com:443/",
                    credential=azure_credential,
                )
                db = cosmos_client.get_database_client(history_db)
                app.state.cosmos_history_container = db.get_container_client(history_container_name)
                app.state.cosmos_history_version = os.getenv("AZURE_CHAT_HISTORY_VERSION", "1")
                app.state._cosmos_history_client = cosmos_client
                logger.info("cosmos_chat_history_initialized")

        # File metadata (Cosmos DB)
        if os.getenv("USE_FILE_METADATA", "").lower() == "true":
            cosmosdb_account = os.getenv("AZURE_COSMOSDB_ACCOUNT")
            metadata_db = os.getenv("AZURE_FILE_METADATA_DATABASE", "graphrag")
            metadata_container_name = os.getenv("AZURE_FILE_METADATA_CONTAINER", "file_metadata")

            if cosmosdb_account:
                from azure.cosmos.aio import CosmosClient as CosmosClient2
                cosmos_client2 = CosmosClient2(
                    url=f"https://{cosmosdb_account}.documents.azure.com:443/",
                    credential=azure_credential,
                )
                db2 = cosmos_client2.get_database_client(metadata_db)
                container2 = db2.get_container_client(metadata_container_name)
                from src.api_gateway.services.file_metadata_service import FileMetadataService
                app.state.file_metadata_service = FileMetadataService(container2)
                app.state._cosmos_metadata_client = cosmos_client2
                logger.info("cosmos_file_metadata_initialized")

        # Blob Manager (for user file uploads)
        enable_upload = os.getenv(
            "USE_USER_UPLOAD", os.getenv("ENABLE_USER_UPLOAD", "")
        ).lower() == "true"
        if enable_upload:
            storage_account = os.getenv("AZURE_USERSTORAGE_ACCOUNT")
            storage_container = os.getenv("AZURE_USERSTORAGE_CONTAINER")
            if storage_account and storage_container:
                from src.api_gateway.services.user_blob_manager import UserBlobManager
                app.state.user_blob_manager = UserBlobManager(
                    endpoint=f"https://{storage_account}.blob.core.windows.net",
                    container=storage_container,
                    credential=azure_credential,
                )
                logger.info("user_blob_manager_initialized")

        # Global blob manager (for content/citations)
        global_storage = os.getenv("AZURE_STORAGE_ACCOUNT")
        global_container = os.getenv("AZURE_STORAGE_CONTAINER")
        if global_storage and global_container:
            from prepdocslib.blobmanager import BlobManager
            app.state.global_blob_manager = BlobManager(
                endpoint=f"https://{global_storage}.blob.core.windows.net",
                credential=azure_credential,
                container=global_container,
                image_container=os.getenv("AZURE_IMAGESTORAGE_CONTAINER"),
            )

        # Redis — warm the singleton so the first /dashboard/me doesn't cold-start
        try:
            from src.core.services.redis_service import get_redis_service
            await get_redis_service()
            logger.info("redis_connected")
            # Also warm QuotaEnforcer to avoid lock contention on first dashboard load
            from src.core.services.quota_enforcer import get_quota_enforcer
            await get_quota_enforcer()
            logger.info("quota_enforcer_warmed")
        except Exception as e:
            logger.warning("redis_init_failed", error=str(e))

        # Usage tracking (Cosmos DB) — initialize the singleton so dashboard works
        if os.getenv("COSMOS_DB_ENDPOINT"):
            try:
                from src.core.services.cosmos_client import get_cosmos_client
                cosmos_usage = get_cosmos_client()
                await cosmos_usage.initialize()
                logger.info("cosmos_usage_tracking_initialized")
            except Exception as e:
                logger.warning("cosmos_usage_tracking_init_failed", error=str(e))

    except Exception as e:
        logger.error("frontend_services_init_failed", error=str(e))

    # ── Auto-resume zombie analyses on container restart ───────────────
    # If the previous container was killed mid-indexing, the folder stays
    # as "analyzing" with a partial pipeline_checkpoint.  We detect this
    # and auto-resume in the background so the user doesn't have to
    # manually re-trigger.
    asyncio.create_task(_auto_resume_zombie_analyses(app))

    yield  # Application runs here

    # Shutdown
    logger.info("service_shutdown")
    try:
        graph_service = GraphService()
        graph_service.close()
        logger.info("neo4j_connection_closed")
    except Exception as e:
        logger.error("neo4j_close_failed", error=str(e))

    # Close Cosmos DB clients
    for attr in ["_cosmos_history_client", "_cosmos_metadata_client"]:
        client = getattr(app.state, attr, None)
        if client:
            try:
                await client.close()
            except Exception as e:
                logger.error("%s_close_failed", attr, error=str(e))

    # Close blob managers
    for attr in ["user_blob_manager", "global_blob_manager"]:
        manager = getattr(app.state, attr, None)
        if manager:
            try:
                await manager.close()
            except Exception as e:
                logger.error("%s_close_failed", attr, error=str(e))

    # Close Azure credential
    if azure_credential:
        try:
            await azure_credential.close()
        except Exception:
            pass


_require_auth_for_docs = settings.REQUIRE_AUTH if hasattr(settings, "REQUIRE_AUTH") else True

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="""
    GraphRAG Orchestration API (Unified Fullstack)

    **Hybrid Endpoints (Primary):**
    - `/hybrid/query` - 4-way routing (Route 1-4)

    **Frontend Endpoints:**
    - `/chat`, `/chat/stream` - Chat with streaming
    - `/upload`, `/delete_uploaded`, `/list_uploaded` - File management
    - `/rename_uploaded`, `/move_uploaded`, `/copy_uploaded` - File operations
    - `/chat_history` - Chat session history (Cosmos DB)
    - `/file_metadata` - File metadata with e-tag concurrency
    - `/speech` - Azure Text-to-Speech
    - `/config` - Runtime configuration
    - `/auth_setup` - MSAL authentication setup
    """,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    # SECURITY: Disable Swagger UI and ReDoc in production to prevent API surface disclosure
    docs_url=None if _require_auth_for_docs else "/docs",
    redoc_url=None if _require_auth_for_docs else "/redoc",
    lifespan=lifespan
)

# CORS Middleware — localhost origins only in dev mode
_cors_origins = []
if not settings.REQUIRE_AUTH:
    _cors_origins = [
        "http://localhost:3000",
        "http://localhost:5173",   # Vite dev server
        "http://localhost:50505",  # Legacy Quart port (if still used locally)
    ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Group-ID", "X-Algorithm-Version",
                   "X-Admin-Key", "X-Correlation-ID", "Accept", "Accept-Language"],
)

# Custom Middleware (order matters: first added = last executed)
# Execution order: CORS → Correlation → Version → JWT → GroupIsolation → Handler

# 1. Correlation ID - generates/propagates trace ID for all requests
app.add_middleware(CorrelationIdMiddleware)

# 2. Version Header - resolves API/algorithm version from request headers
app.add_middleware(VersionHeaderMiddleware)

# 3. Group Isolation - enforces tenant isolation using JWT or legacy headers
app.add_middleware(GroupIsolationMiddleware)

# 4. JWT Authentication - validates Azure Easy Auth tokens and extracts tenant claims
# SECURITY: REQUIRE_AUTH defaults to True (fail closed). Set REQUIRE_AUTH=false for local dev.
_require_auth = settings.REQUIRE_AUTH if hasattr(settings, "REQUIRE_AUTH") else True
if not _require_auth:
    import warnings
    warnings.warn(
        "REQUIRE_AUTH is False — all API endpoints accept unauthenticated requests. "
        "Set REQUIRE_AUTH=true before deploying to production.",
        stacklevel=1,
    )
if _require_auth and settings.GROUP_ID_OVERRIDE:
    import warnings
    warnings.warn(
        f"GROUP_ID_OVERRIDE is set to '{settings.GROUP_ID_OVERRIDE}' while REQUIRE_AUTH is True. "
        "All requests will use this fixed group_id, overriding JWT group claims. "
        "Unset GROUP_ID_OVERRIDE before deploying to production.",
        stacklevel=1,
    )
_auth_type = settings.AUTH_TYPE if hasattr(settings, "AUTH_TYPE") else "B2B"
app.state.auth_type = _auth_type
app.add_middleware(
    JWTAuthMiddleware,
    auth_type=_auth_type,
    require_auth=_require_auth,
)

# ============================================================================
# Include Routers - Core API
# ============================================================================
app.include_router(health.router, tags=["health"])
app.include_router(config.router, tags=["config"])
app.include_router(folders.router, tags=["folders"])
app.include_router(chat.router, tags=["chat"])  # OpenAI-compatible chat API
app.include_router(documents.router)  # BFF-facing document lifecycle notifications

# ============================================================================
# Frontend-Serving Routers (replaces Quart backend)
# ============================================================================
app.include_router(spa.router, tags=["spa"])
app.include_router(files.router, tags=["files"])
app.include_router(chat_history.router, tags=["chat-history"])
app.include_router(file_metadata.router, tags=["file-metadata"])
app.include_router(speech.router, tags=["speech"])

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
# Dashboard API - Personal & Management Dashboards
# ============================================================================
# Personal endpoints require auth; admin endpoints require Admin role
app.include_router(dashboard_router, tags=["dashboard"])

# ============================================================================
# V3 Endpoints - Alternative DRIFT-based Implementation
# ============================================================================
# Deprecated V3 endpoints are intentionally not included.

# ============================================================================
# Static Files (React SPA) - MUST be last (catch-all)
# ============================================================================
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    # Serve /assets/* for Vite-built JS/CSS bundles
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # SPA catch-all: serve index.html for any unmatched GET route
    @app.api_route("/{path:path}", methods=["GET"], include_in_schema=False)
    async def spa_catch_all(path: str):
        """Serve index.html for unmatched GET routes (SPA client-side routing)."""
        # Don't catch API-like paths
        if path.startswith((
            "api/", "hybrid/", "lifecycle/", "maintenance/", "admin/",
            "chat", "config", "health", "dashboard", "folders", "upload",
            "delete_uploaded", "list_uploaded", "rename_uploaded",
            "move_uploaded", "copy_uploaded", "chat_history",
            "file_metadata", "speech", "auth_setup", "content/",
        )):
            raise HTTPException(status_code=404, detail="Not found")

        # Check if it's a specific static file
        static_file = STATIC_DIR / path
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))

        # Default: serve index.html for client-side routing
        # no-cache ensures browser revalidates on every load so new
        # deployments are picked up without manual cache clearing.
        return FileResponse(
            str(STATIC_DIR / "index.html"),
            headers={"Cache-Control": "no-cache"},
        )

    logger.info("spa_serving_enabled", static_dir=str(STATIC_DIR))
else:
    logger.warning(
        "spa_not_found",
        static_dir=str(STATIC_DIR),
        message="Frontend static files not found - SPA serving disabled",
    )
