"""
Hybrid Pipeline API Router

Exposes the 3-way routing system via REST endpoints:
- Route 1: Vector RAG (fast lane for simple queries)
- Route 2: Local/Global equivalent (entity-focused with HippoRAG 2)
- Route 3: DRIFT equivalent (multi-hop iterative reasoning)

Endpoints:
- POST /hybrid/query - Auto-route to appropriate handler
- POST /hybrid/query/audit - Force Route 2/3 with audit trail
- POST /hybrid/query/fast - Force Route 1 (Vector RAG)
- POST /hybrid/query/drift - Force Route 3 (multi-hop)
- GET /hybrid/health - Health check for hybrid components
- POST /hybrid/configure - Configure pipeline settings
"""

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
import structlog
import asyncio
import time

from app.hybrid.orchestrator import HybridPipeline
from app.hybrid.router.main import DeploymentProfile, QueryRoute
from app.hybrid.indexing import DualIndexService, get_hipporag_service

router = APIRouter()
logger = structlog.get_logger(__name__)

# Pipeline instance cache per group
_pipeline_cache: Dict[str, HybridPipeline] = {}

# Indexing job tracking
_indexing_jobs: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# Request/Response Models
# ============================================================================

class DeploymentProfileEnum(str, Enum):
    """Deployment profile selection."""
    GENERAL_ENTERPRISE = "general_enterprise"     # All 4 routes
    HIGH_ASSURANCE = "high_assurance"             # Routes 2, 3, 4 only (no Vector RAG)


class RouteEnum(str, Enum):
    """Available query routes."""
    VECTOR_RAG = "vector_rag"           # Route 1: Fast lane
    LOCAL_SEARCH = "local_search"       # Route 2: Entity-focused (LazyGraphRAG)
    GLOBAL_SEARCH = "global_search"     # Route 3: Thematic (LazyGraphRAG + HippoRAG)
    DRIFT_MULTI_HOP = "drift_multi_hop" # Route 4: Multi-hop iterative


class HybridQueryRequest(BaseModel):
    """Request model for hybrid pipeline queries."""
    query: str = Field(..., description="The natural language query to execute")
    response_type: Literal["detailed_report", "summary", "audit_trail"] = Field(
        default="detailed_report",
        description="Type of response to generate"
    )
    force_route: Optional[RouteEnum] = Field(
        default=None,
        description="Force a specific route (overrides router decision)"
    )
    relevance_budget: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override relevance budget (0.0=fast, 1.0=thorough)"
    )


class HybridQueryResponse(BaseModel):
    """Response model for hybrid pipeline queries."""
    response: str = Field(..., description="The generated answer")
    route_used: str = Field(..., description="Which route was taken (route_1/route_2/route_3)")
    citations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Source citations with text and metadata"
    )
    evidence_path: List[Any] = Field(
        default_factory=list,
        description="Evidence path (entity IDs/names or structured nodes)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional execution metadata"
    )


class PipelineConfigRequest(BaseModel):
    """Request to configure the hybrid pipeline."""
    profile: DeploymentProfileEnum = Field(
        default=DeploymentProfileEnum.GENERAL_ENTERPRISE,
        description="Deployment profile to use"
    )
    relevance_budget: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Thoroughness vs speed tradeoff"
    )
    enable_vector_rag: bool = Field(
        default=True,
        description="Enable Route 1 (Vector RAG)"
    )
    enable_drift: bool = Field(
        default=True,
        description="Enable Route 3 (DRIFT multi-hop)"
    )


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    components: Dict[str, Any]
    profile: str
    group_id: str


# =========================================================================
# Document Intelligence (DI) Preflight
# =========================================================================

class DiExtractRequest(BaseModel):
    """Run Document Intelligence extraction only (no indexing).

    Useful for validating that DI can access the PDF and that section/subsection
    metadata is being produced as expected before running full indexing.
    """

    documents: List[Any] = Field(
        ..., description="Documents to extract (URLs or dicts with {url})"
    )
    model_strategy: Literal["auto", "layout", "invoice", "receipt"] = Field(
        default="auto",
        description="DI model selection strategy",
    )


class DiExtractResponse(BaseModel):
    status: Literal["success"]
    group_id: str
    requested: int
    extracted_units: int
    by_url: Dict[str, Any]


# ============================================================================
# Helper Functions
# ============================================================================

def _get_deployment_profile(profile_enum: DeploymentProfileEnum) -> DeploymentProfile:
    """Convert API enum to internal DeploymentProfile."""
    profile_map = {
        DeploymentProfileEnum.GENERAL_ENTERPRISE: DeploymentProfile.GENERAL_ENTERPRISE,
        DeploymentProfileEnum.HIGH_ASSURANCE: DeploymentProfile.HIGH_ASSURANCE,
    }
    return profile_map.get(profile_enum, DeploymentProfile.GENERAL_ENTERPRISE)


async def _get_or_create_pipeline(
    group_id: str,
    profile: DeploymentProfile = DeploymentProfile.GENERAL_ENTERPRISE,
    relevance_budget: float = 0.8
) -> HybridPipeline:
    """
    Get or create a HybridPipeline for the given group.
    
    In production, this would initialize:
    - LLM client from settings
    - HippoRAG instance from indexed data
    - Graph store connection
    - Vector RAG client
    """
    cache_key = f"{group_id}:{profile.value}"
    
    if cache_key not in _pipeline_cache:
        logger.info("creating_hybrid_pipeline",
                   group_id=group_id,
                   profile=profile.value)

        # Real wiring (E2E-real): use in-process services.
        # If a dependency is unavailable, we still construct the pipeline but
        # downstream behavior may degrade (and E2E tests should catch it).
        from app.services import GraphService, LLMService
        from app.services.community_service import CommunityService
        from app.hybrid.indexing.hipporag_service import get_hipporag_service
        from app.hybrid.indexing.text_store import HippoRAGTextUnitStore

        llm_service = LLMService()
        llm_client = llm_service.llm

        graph_store = None
        try:
            graph_service = GraphService()
            graph_store = graph_service.get_store(group_id)
        except Exception as e:
            logger.warning("hybrid_graph_store_unavailable", group_id=group_id, error=str(e))

        # Community summaries (optional but improves intent disambiguation)
        graph_communities = None
        try:
            community_service = CommunityService()
            summaries = community_service.get_community_summaries(group_id)
            graph_communities = [
                {"title": f"Community {cid}", "summary": summary}
                for cid, summary in sorted((summaries or {}).items(), key=lambda x: x[0])
            ]
        except Exception as e:
            logger.warning("hybrid_community_summaries_unavailable", group_id=group_id, error=str(e))

        # HippoRAG (Route 2/3 tracer + citation text backing)
        hipporag_service = get_hipporag_service(group_id, "./hipporag_index")
        try:
            await hipporag_service.initialize()
        except Exception as e:
            logger.warning("hybrid_hipporag_initialize_failed", group_id=group_id, error=str(e))

        hipporag_instance = hipporag_service.get_instance()
        text_unit_store = HippoRAGTextUnitStore(hipporag_service)

        pipeline = HybridPipeline(
            profile=profile,
            llm_client=llm_client,
            hipporag_instance=hipporag_instance,
            graph_store=graph_store,
            text_unit_store=text_unit_store,
            vector_rag_client=None,
            graph_communities=graph_communities,
            relevance_budget=relevance_budget,
        )
        
        _pipeline_cache[cache_key] = pipeline
    
    return _pipeline_cache[cache_key]


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/query", response_model=HybridQueryResponse)
async def hybrid_query(request: Request, body: HybridQueryRequest):
    """
    Execute a query through the 3-way routing hybrid pipeline.
    
    The router automatically decides between:
    - Route 1: Vector RAG for simple fact lookups
    - Route 2: Local/Global (LazyGraphRAG + HippoRAG 2) for entity-focused queries
    - Route 3: DRIFT multi-hop for ambiguous/complex queries
    
    Use `force_route` to override the automatic decision.
    """
    group_id = request.state.group_id
    
    logger.info("hybrid_query_received",
               group_id=group_id,
               query_preview=body.query[:50],
               response_type=body.response_type,
               force_route=body.force_route.value if body.force_route else None)
    
    try:
        pipeline = await _get_or_create_pipeline(group_id)
        
        # Handle forced routing
        if body.force_route:
            route_map: Dict[RouteEnum, QueryRoute] = {
                RouteEnum.VECTOR_RAG: QueryRoute.VECTOR_RAG,
                RouteEnum.LOCAL_SEARCH: QueryRoute.LOCAL_SEARCH,
                RouteEnum.GLOBAL_SEARCH: QueryRoute.GLOBAL_SEARCH,
                RouteEnum.DRIFT_MULTI_HOP: QueryRoute.DRIFT_MULTI_HOP,
            }
            forced_route = route_map[body.force_route]
            result = await pipeline.force_route(
                query=body.query,
                route=forced_route,
                response_type=body.response_type
            )
        else:
            result = await pipeline.query(body.query, body.response_type)
        
        return HybridQueryResponse(**result)
        
    except Exception as e:
        logger.error("hybrid_query_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/audit", response_model=HybridQueryResponse)
async def hybrid_query_audit(request: Request, body: HybridQueryRequest):
    """
    Execute a query with full audit trail (Routes 2 or 3 only).
    
    This is a convenience endpoint that:
    - Forces response_type to "audit_trail"
    - Bypasses Vector RAG (Route 1) - always uses Routes 2 or 3
    - Returns maximum evidence detail for compliance
    
    Recommended for: forensic accounting, legal discovery, compliance audits.
    """
    group_id = request.state.group_id
    
    logger.info("audit_query_received",
               group_id=group_id,
               query_preview=body.query[:50])
    
    try:
        # Use High-Assurance profile for audit queries (Routes 2, 3, 4 only)
        pipeline = await _get_or_create_pipeline(
            group_id,
            profile=DeploymentProfile.HIGH_ASSURANCE,
            relevance_budget=0.95  # Maximum thoroughness
        )
        
        result = await pipeline.query_with_audit_trail(body.query)
        return HybridQueryResponse(**result)
        
    except Exception as e:
        logger.error("audit_query_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/fast", response_model=HybridQueryResponse)
async def hybrid_query_fast(request: Request, body: HybridQueryRequest):
    """
    Execute a query via Route 1 (Vector RAG) only.
    
    This is a convenience endpoint that:
    - Always uses Vector RAG (Route 1)
    - Optimized for sub-second latency (<500ms)
    - Best for simple fact lookups
    
    Note: Will fall back to Route 2 if Vector RAG is unavailable.
    """
    group_id = request.state.group_id
    
    logger.info("fast_query_received",
               group_id=group_id,
               query_preview=body.query[:50])
    
    try:
        pipeline = await _get_or_create_pipeline(
            group_id,
            relevance_budget=0.5  # Speed over thoroughness
        )
        
        result = await pipeline.force_route(
            query=body.query,
            route=QueryRoute.VECTOR_RAG,
            response_type=body.response_type
        )
        return HybridQueryResponse(**result)
        
    except Exception as e:
        logger.error("fast_query_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/drift", response_model=HybridQueryResponse)
async def hybrid_query_drift(request: Request, body: HybridQueryRequest):
    """
    Execute a query via Route 3 (DRIFT multi-hop reasoning).
    
    This is a convenience endpoint that:
    - Always uses DRIFT-style iterative query decomposition
    - Decomposes ambiguous queries into sub-questions
    - Discovers entities through intermediate steps
    - Consolidates evidence for comprehensive answers
    
    Best for:
    - Ambiguous queries without clear entity references
    - Complex multi-hop reasoning
    - Questions requiring discovery of related concepts
    
    Example queries that benefit:
    - "What regulatory implications exist?" (no specific entity)
    - "How do ESG factors affect valuations?" (needs decomposition)
    """
    group_id = request.state.group_id
    
    logger.info("drift_query_received",
               group_id=group_id,
               query_preview=body.query[:50])
    
    try:
        pipeline = await _get_or_create_pipeline(
            group_id,
            relevance_budget=0.9  # Thoroughness for complex queries
        )
        
        result = await pipeline.force_route(
            query=body.query,
            route=QueryRoute.DRIFT_MULTI_HOP,
            response_type=body.response_type
        )
        return HybridQueryResponse(**result)
        
    except Exception as e:
        logger.error("drift_query_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def hybrid_health(request: Request):
    """
    Health check for hybrid pipeline components.
    
    Returns status of:
    - Router
    - Intent Disambiguator
    - Deterministic Tracer (HippoRAG)
    - Evidence Synthesizer
    - Vector RAG (if enabled)
    """
    group_id = request.state.group_id
    
    try:
        pipeline = await _get_or_create_pipeline(group_id)
        health_status = await pipeline.health_check()

        allowed = {"ok", "not_configured", "fallback_mode", "no_llm"}
        component_values = [
            v for k, v in health_status.items() if isinstance(v, str) and k not in {"profile"}
        ]
        
        return HealthResponse(
            status="healthy" if component_values and all(v in allowed for v in component_values) else "degraded",
            components=health_status,
            profile=health_status.get("profile", "unknown"),
            group_id=group_id
        )
        
    except Exception as e:
        logger.error("health_check_failed",
                    group_id=group_id,
                    error=str(e))
        return HealthResponse(
            status="unhealthy",
            components={"error": str(e)},
            profile="unknown",
            group_id=group_id
        )


@router.post("/configure")
async def configure_pipeline(request: Request, config: PipelineConfigRequest):
    """
    Configure the hybrid pipeline for this group.
    
    Allows switching between deployment profiles:
    - Profile A (General Enterprise): All 3 routes
    - Profile B (High-Assurance): Routes 2+3 only (no Vector RAG)
    - Profile C (Speed-Critical): Routes 1+2 only (no DRIFT)
    
    Configuration persists for the duration of the session.
    """
    group_id = request.state.group_id
    
    logger.info("configuring_pipeline",
               group_id=group_id,
               profile=config.profile.value,
               relevance_budget=config.relevance_budget,
               enable_vector_rag=config.enable_vector_rag,
               enable_drift=config.enable_drift)
    
    try:
        profile = _get_deployment_profile(config.profile)
        
        # Clear cache to force recreation with new settings
        cache_keys_to_remove = [
            k for k in _pipeline_cache.keys() if k.startswith(f"{group_id}:")
        ]
        for key in cache_keys_to_remove:
            del _pipeline_cache[key]
        
        # Create new pipeline with updated config
        pipeline = await _get_or_create_pipeline(
            group_id,
            profile=profile,
            relevance_budget=config.relevance_budget
        )
        
        # Determine which routes are enabled based on profile + overrides
        routes_enabled = {
            "vector_rag": config.enable_vector_rag and profile != DeploymentProfile.HIGH_ASSURANCE,
            "local_search": True,  # Always enabled
            "global_search": True,  # Always enabled
            "drift_multi_hop": config.enable_drift
        }
        
        return {
            "status": "configured",
            "group_id": group_id,
            "profile": config.profile.value,
            "relevance_budget": config.relevance_budget,
            "routes_enabled": routes_enabled
        }
        
    except Exception as e:
        logger.error("configuration_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/di/extract", response_model=DiExtractResponse)
async def di_extract_preflight(request: Request, body: DiExtractRequest):
    """Run DI extraction only and return a small summary.

    This endpoint is intentionally read-only (does not write to Neo4j).
    """

    group_id = request.state.group_id

    # Normalize inputs into DI input_items format.
    input_items: List[Any] = []
    for doc in body.documents:
        if isinstance(doc, str):
            input_items.append(doc)
        elif isinstance(doc, dict):
            if "url" in doc:
                input_items.append({"url": doc["url"]})
            else:
                raise HTTPException(status_code=400, detail="DI preflight dict documents must include 'url'")
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported document type: {type(doc)}")

    try:
        from app.services.document_intelligence_service import DocumentIntelligenceService

        di_service = DocumentIntelligenceService()
        extracted = await di_service.extract_documents(
            group_id=group_id,
            input_items=input_items,
            fail_fast=True,
            model_strategy=body.model_strategy,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("di_extract_preflight_failed", extra={"group_id": group_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))

    # Summarize per URL. Do not return full text to avoid huge payloads.
    by_url: Dict[str, Any] = {}
    for d in extracted:
        md = d.metadata or {}
        url = str(md.get("url") or "")
        if url not in by_url:
            by_url[url] = {
                "units": 0,
                "has_section_path": 0,
                "has_di_section_path": 0,
                "has_tables": 0,
                "sample": None,
            }
        entry = by_url[url]
        entry["units"] += 1
        if md.get("section_path"):
            entry["has_section_path"] += 1
        if md.get("di_section_path") is not None:
            entry["has_di_section_path"] += 1
        if md.get("tables"):
            entry["has_tables"] += 1
        if entry["sample"] is None:
            entry["sample"] = {
                "page_number": md.get("page_number"),
                "chunk_type": md.get("chunk_type"),
                "section_path": md.get("section_path"),
                "di_section_path": md.get("di_section_path"),
                "di_section_part": md.get("di_section_part"),
                "table_count": md.get("table_count"),
                "paragraph_count": md.get("paragraph_count"),
                "text_preview": (d.text or "")[:200],
            }

    return DiExtractResponse(
        status="success",
        group_id=group_id,
        requested=len(input_items),
        extracted_units=len(extracted),
        by_url=by_url,
    )


@router.get("/profiles")
async def list_profiles():
    """
    List available deployment profiles with descriptions.
    
    Helps users understand the tradeoffs between the 3-way routing system.
    """
    return {
        "routes": [
            {
                "id": "route_1",
                "name": "Vector RAG",
                "description": "Embedding-based retrieval for fast fact lookups",
                "latency": "<500ms",
                "best_for": ["Simple fact queries", "Known entity lookups", "FAQ-style questions"],
                "mechanism": "Cosine similarity search on vector embeddings"
            },
            {
                "id": "route_2",
                "name": "Local/Global (LazyGraphRAG + HippoRAG 2)",
                "description": "Entity-focused graph traversal with deterministic evidence paths",
                "latency": "3-8 seconds",
                "best_for": [
                    "Queries with clear entity references",
                    "Evidence tracing requirements",
                    "Relationship mapping"
                ],
                "mechanism": "NER → PPR graph traversal → Iterative deepening"
            },
            {
                "id": "route_3",
                "name": "DRIFT Multi-Hop",
                "description": "Iterative query decomposition for ambiguous multi-hop reasoning",
                "latency": "8-15 seconds",
                "best_for": [
                    "Ambiguous queries without clear entities",
                    "Complex multi-hop reasoning",
                    "Discovery-oriented questions"
                ],
                "mechanism": "Query decomposition → Sub-question resolution → Consolidated synthesis"
            }
        ],
        "profiles": [
            {
                "id": "general_enterprise",
                "name": "General Enterprise (Profile A)",
                "description": "All 3 routes enabled - automatic routing",
                "available_routes": ["route_1", "route_2", "route_3"],
                "best_for": [
                    "General business intelligence",
                    "Customer support",
                    "Knowledge management"
                ],
                "routing_behavior": "Auto-select optimal route based on query complexity and ambiguity"
            },
            {
                "id": "high_assurance_audit",
                "name": "High-Assurance Audit (Profile B)",
                "description": "Routes 2+3 only - no Vector RAG, always deterministic paths",
                "available_routes": ["route_2", "route_3"],
                "best_for": [
                    "Forensic accounting",
                    "Compliance auditing",
                    "Legal discovery"
                ],
                "routing_behavior": "Always use graph-based routes with full evidence trails"
            },
            {
                "id": "speed_critical",
                "name": "Speed-Critical (Profile C)",
                "description": "Routes 1+2 only - no DRIFT, optimized for latency",
                "available_routes": ["route_1", "route_2"],
                "best_for": [
                    "Real-time dashboards",
                    "Interactive Q&A",
                    "High-volume queries"
                ],
                "routing_behavior": "Prioritize speed, skip expensive multi-hop reasoning"
            }
        ]
    }


# ============================================================================
# Indexing Endpoints
# ============================================================================

class HybridIndexDocumentsRequest(BaseModel):
    """Index documents for the Hybrid (LazyGraphRAG + HippoRAG 2 + Vector RAG) system.

    Notes:
    - This indexes into Neo4j (and vector backends) via the existing V3 indexing pipeline.
    - It does NOT require RAPTOR; by default, RAPTOR is disabled.
    - After document indexing completes, run /hybrid/index/sync to build HippoRAG artifacts.
    """

    documents: List[Any] = Field(
        ..., description="Documents to index (URLs, text strings, or structured dicts)"
    )
    ingestion: Literal["document-intelligence", "llamaparse", "none"] = Field(
        default="document-intelligence",
        description="Document extraction method for PDFs/images",
    )
    run_community_detection: bool = Field(
        default=True,
        description="Whether to run community detection (improves thematic routing)",
    )
    run_raptor: bool = Field(
        default=False,
        description="Legacy RAPTOR hierarchical summarization (disabled by default)",
    )
    reindex: bool = Field(
        default=False,
        description="If true, delete existing group data before indexing",
    )


class HybridIndexDocumentsResponse(BaseModel):
    status: Literal["accepted", "success", "failed"]
    group_id: str
    job_id: str
    documents_received: int
    message: str
    stats: Optional[Dict[str, Any]] = None


class IndexingStatusResponse(BaseModel):
    status: Literal["pending", "running", "completed", "failed"]
    group_id: str
    job_id: str
    progress: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


async def _run_indexing_job(
    job_id: str,
    group_id: str,
    docs_for_pipeline: List[Dict[str, Any]],
    reindex: bool,
    ingestion: str,
    run_community_detection: bool,
    run_raptor: bool,
):
    """Background task to run indexing."""
    _indexing_jobs[job_id]["status"] = "running"
    _indexing_jobs[job_id]["progress"] = "Starting indexing pipeline..."
    
    try:
        from app.v3.routers.graphrag_v3 import get_indexing_pipeline
        pipeline = get_indexing_pipeline()
        
        _indexing_jobs[job_id]["progress"] = "Indexing documents..."
        stats = await pipeline.index_documents(
            group_id=group_id,
            documents=docs_for_pipeline,
            reindex=reindex,
            ingestion=ingestion,
            run_community_detection=run_community_detection,
            run_raptor=run_raptor,
        )
        
        _indexing_jobs[job_id]["status"] = "completed"
        _indexing_jobs[job_id]["stats"] = stats
        _indexing_jobs[job_id]["completed_at"] = time.time()
        _indexing_jobs[job_id]["progress"] = "Indexing complete"
        
        logger.info("hybrid_index_documents_complete", group_id=group_id, job_id=job_id, stats=stats)
        
    except Exception as e:
        _indexing_jobs[job_id]["status"] = "failed"
        _indexing_jobs[job_id]["error"] = str(e)
        _indexing_jobs[job_id]["completed_at"] = time.time()
        logger.exception(
            "hybrid_index_documents_failed",
            extra={"group_id": group_id, "job_id": job_id, "error": str(e)},
        )


@router.post("/index/documents", response_model=HybridIndexDocumentsResponse)
async def hybrid_index_documents(
    request: Request,
    body: HybridIndexDocumentsRequest,
    background_tasks: BackgroundTasks,
):
    """Run document indexing for the Hybrid system.

    This is the preferred indexing entrypoint for the LazyGraphRAG + HippoRAG 2 + Vector RAG architecture.

    Implementation detail: runs the V3 indexing pipeline to populate Neo4j, with RAPTOR disabled by default.
    """

    group_id = request.state.group_id
    logger.info(
        "hybrid_index_documents_start",
        group_id=group_id,
        num_documents=len(body.documents),
        ingestion=body.ingestion,
        run_community_detection=body.run_community_detection,
        run_raptor=body.run_raptor,
        reindex=body.reindex,
    )

    # Keep DRIFT/triple-engine caches from serving stale results post-index.
    try:
        from app.v3.routers.graphrag_v3 import get_drift_adapter

        adapter = get_drift_adapter()
        adapter.clear_cache(group_id)
        logger.info("hybrid_index_cleared_drift_cache", group_id=group_id)
    except Exception as e:
        logger.warning("hybrid_index_clear_drift_cache_failed", group_id=group_id, error=str(e))

    # Convert documents into the V3 pipeline's expected dict format.
    docs_for_pipeline: List[Dict[str, Any]] = []
    for doc in body.documents:
        if isinstance(doc, str):
            if doc.startswith(("http://", "https://")):
                docs_for_pipeline.append(
                    {
                        "content": "",
                        "title": doc.split("/")[-1] if "/" in doc else "Untitled",
                        "source": doc,
                        "metadata": {},
                    }
                )
            else:
                docs_for_pipeline.append(
                    {"content": doc, "title": "Untitled", "source": "", "metadata": {}}
                )
        elif isinstance(doc, dict):
            docs_for_pipeline.append(
                {
                    "content": doc.get("text", doc.get("content", "")),
                    "title": doc.get("title", "Untitled"),
                    "source": doc.get("source", doc.get("url", "")),
                    "metadata": doc.get("metadata", {}),
                }
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported document type: {type(doc)}")

    # Create job ID and track it
    job_id = f"{group_id}_{int(time.time() * 1000)}"
    _indexing_jobs[job_id] = {
        "status": "pending",
        "group_id": group_id,
        "job_id": job_id,
        "documents": len(docs_for_pipeline),
        "started_at": time.time(),
        "progress": "Queued",
    }
    
    # Start background indexing
    background_tasks.add_task(
        _run_indexing_job,
        job_id,
        group_id,
        docs_for_pipeline,
        body.reindex,
        body.ingestion,
        body.run_community_detection,
        body.run_raptor,
    )
    
    logger.info(
        "hybrid_index_documents_accepted",
        group_id=group_id,
        job_id=job_id,
        num_documents=len(docs_for_pipeline),
    )
    
    return HybridIndexDocumentsResponse(
        status="accepted",
        group_id=group_id,
        job_id=job_id,
        documents_received=len(docs_for_pipeline),
        message=(
            f"Indexing job {job_id} started. Poll /hybrid/index/status/{job_id} for progress. "
            "After completion, run /hybrid/index/sync and /hybrid/index/initialize-hipporag."
        ),
    )


@router.get("/index/status/{job_id}", response_model=IndexingStatusResponse)
async def get_indexing_status(request: Request, job_id: str):
    """Check the status of an indexing job."""
    
    if job_id not in _indexing_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = _indexing_jobs[job_id]
    
    return IndexingStatusResponse(
        status=job["status"],
        group_id=job["group_id"],
        job_id=job_id,
        progress=job.get("progress"),
        stats=job.get("stats"),
        error=job.get("error"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
    )

class SyncIndexRequest(BaseModel):
    """Request to sync HippoRAG index from Neo4j."""
    output_dir: str = Field(
        default="./hipporag_index",
        description="Directory to save HippoRAG indexes"
    )
    dry_run: bool = Field(
        default=False,
        description="If true, only report what would be indexed"
    )


class SyncIndexResponse(BaseModel):
    """Response from index sync operation."""
    status: str
    group_id: str
    entities_indexed: Optional[int] = None
    triples_indexed: Optional[int] = None
    text_units_indexed: Optional[int] = None
    hipporag_index_path: Optional[str] = None
    would_index: Optional[Dict[str, int]] = None
    error: Optional[str] = None


@router.post("/index/sync", response_model=SyncIndexResponse)
async def sync_hipporag_index(request: Request, body: SyncIndexRequest):
    """
    Sync GraphRAG data from Neo4j to HippoRAG format.
    
    This must be run after indexing documents before using the Hybrid Pipeline.
    
    The sync creates:
    - HippoRAG triples (Subject-Predicate-Object) for PageRank
    - Entity-text mappings for synthesis
    - LazyGraphRAG text units for Iterative Deepening
    """
    group_id = request.state.group_id
    
    logger.info("sync_hipporag_index_request",
               group_id=group_id,
               output_dir=body.output_dir,
               dry_run=body.dry_run)
    
    try:
        # Import graph service
        from app.services.graph_service import GraphService
        graph_service = GraphService()
        
        if not graph_service.driver:
            raise HTTPException(
                status_code=503,
                detail="Neo4j not configured"
            )
        
        if body.dry_run:
            # Just count what would be indexed
            with graph_service.driver.session() as session:
                entity_count = session.run(
                    "MATCH (e) WHERE e.group_id = $gid AND NOT e:__Community__ AND NOT e:__Chunk__ RETURN count(e) as cnt",
                    gid=group_id
                ).single()["cnt"]
                
                rel_count = session.run(
                    "MATCH (s)-[r]->(o) WHERE s.group_id = $gid RETURN count(r) as cnt",
                    gid=group_id
                ).single()["cnt"]
                
                chunk_count = session.run(
                    "MATCH (c:__Chunk__) WHERE c.group_id = $gid RETURN count(c) as cnt",
                    gid=group_id
                ).single()["cnt"]
            
            return SyncIndexResponse(
                status="dry_run",
                group_id=group_id,
                would_index={
                    "entities": entity_count,
                    "relationships": rel_count,
                    "text_chunks": chunk_count
                }
            )
        
        # Actual sync
        dual_index = DualIndexService(
            neo4j_driver=graph_service.driver,
            hipporag_save_dir=body.output_dir,
            group_id=group_id
        )
        
        result = await dual_index.sync_from_neo4j()
        
        if result["status"] == "success":
            return SyncIndexResponse(
                status="success",
                group_id=group_id,
                entities_indexed=result.get("entities_indexed"),
                triples_indexed=result.get("triples_indexed"),
                text_units_indexed=result.get("text_units_indexed"),
                hipporag_index_path=result.get("hipporag_index_path")
            )
        else:
            return SyncIndexResponse(
                status="error",
                group_id=group_id,
                error=result.get("error", "Unknown error")
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("sync_hipporag_index_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/index/status")
async def get_index_status(request: Request, index_dir: str = "./hipporag_index"):
    """
    Get the status of HippoRAG indexes for this group.
    
    Shows:
    - Whether indexes exist
    - Number of entities/triples indexed
    - Last sync timestamp
    """
    group_id = request.state.group_id
    
    try:
        from pathlib import Path
        import json
        
        group_dir = Path(index_dir) / group_id
        
        status = {
            "group_id": group_id,
            "index_dir": str(group_dir),
            "exists": group_dir.exists(),
            "files": {}
        }
        
        if group_dir.exists():
            # Check each index file
            for filename in ["entities.json", "hipporag_triples.json", 
                           "entity_texts.json", "lazygraphrag_units.json",
                           "entity_index.json"]:
                filepath = group_dir / filename
                if filepath.exists():
                    try:
                        with open(filepath) as f:
                            data = json.load(f)
                        status["files"][filename] = {
                            "exists": True,
                            "count": len(data) if isinstance(data, list) else len(data.keys()),
                            "size_bytes": filepath.stat().st_size
                        }
                    except Exception as e:
                        status["files"][filename] = {
                            "exists": True,
                            "unreadable": True,
                            "error": str(e),
                            "size_bytes": filepath.stat().st_size,
                        }
                else:
                    status["files"][filename] = {"exists": False}
        
        # Check HippoRAG service status
        hipporag_service = get_hipporag_service(group_id, index_dir)
        status["hipporag"] = await hipporag_service.health_check()
        
        return status
        
    except Exception as e:
        logger.error("get_index_status_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/index/initialize-hipporag")
async def initialize_hipporag(request: Request, index_dir: str = "./hipporag_index"):
    """
    Initialize the HippoRAG instance for this group.
    
    This loads the synced index into memory for fast retrieval.
    Call this after sync_hipporag_index before querying.
    """
    group_id = request.state.group_id
    
    try:
        hipporag_service = get_hipporag_service(group_id, index_dir)
        
        success = await hipporag_service.initialize()
        
        if success:
            return {
                "status": "initialized",
                "group_id": group_id,
                "hipporag_available": True
            }
        else:
            return {
                "status": "not_initialized",
                "group_id": group_id,
                "hipporag_available": hipporag_service.is_available,
                "reason": "HippoRAG not installed or index not found"
            }
            
    except Exception as e:
        logger.error("initialize_hipporag_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
