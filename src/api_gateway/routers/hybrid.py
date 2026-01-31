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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
import structlog
import asyncio
import time

from src.worker.hybrid_v2.orchestrator import HybridPipeline, HighQualityError
from src.worker.hybrid_v2.router.main import DeploymentProfile, QueryRoute
from src.worker.hybrid_v2.indexing import DualIndexService, get_hipporag_service
from src.core.config import settings

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
    response_type: Literal["detailed_report", "summary", "audit_trail", "nlp_audit", "nlp_connected"] = Field(
        default="detailed_report",
        description="Type of response to generate (nlp_audit = deterministic extraction, no LLM; nlp_connected = deterministic + rephrasing)"
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
        from src.worker.services import GraphService, LLMService
        from src.worker.services.community_service import CommunityService
        from src.worker.hybrid.indexing.hipporag_service import get_hipporag_service
        # V2 text store has proper IN_DOCUMENT relationship support
        from src.worker.hybrid_v2.indexing.text_store import Neo4jTextUnitStore
        from src.worker.hybrid.indexing.text_store import HippoRAGTextUnitStore

        llm_service = LLMService()
        # Use dedicated synthesis model for final answer generation (Route 2/3)
        llm_client = llm_service.get_synthesis_llm()

        graph_store = None
        neo4j_driver = None
        try:
            graph_service = GraphService()
            graph_store = graph_service.get_store(group_id)
            neo4j_driver = graph_service.driver
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

        # Prefer Neo4j-backed text chunks for citations (preserves DI section_path/page_number).
        # Fall back to HippoRAG on-disk index text if Neo4j is unavailable.
        if neo4j_driver is not None:
            text_unit_store = Neo4jTextUnitStore(neo4j_driver, group_id=group_id)
        else:
            text_unit_store = HippoRAGTextUnitStore(hipporag_service)

        # Auto-detect embedding version from group's data (V1 OpenAI 3072D vs V2 Voyage 2048D)
        # This ensures the query embeddings match how the group was indexed
        embedding_client = llm_service.embed_model  # Default: V1 OpenAI
        embedding_version = "v1"
        
        if settings.VOYAGE_API_KEY:
            try:
                from src.worker.services.async_neo4j_service import AsyncNeo4jService
                # Create temporary service to detect embedding version
                async_service = AsyncNeo4jService(
                    uri=settings.NEO4J_URI,
                    username=settings.NEO4J_USERNAME,
                    password=settings.NEO4J_PASSWORD,
                )
                await async_service.connect()
                embedding_version = await async_service.detect_embedding_version(group_id)
                await async_service.close()
                
                if embedding_version == "v2":
                    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
                    voyage_service = VoyageEmbedService()
                    embedding_client = voyage_service.get_llama_index_model()
                    logger.info("hybrid_using_v2_voyage_embedder", group_id=group_id, 
                               reason="group has embedding_v2 data")
                else:
                    logger.info("hybrid_using_v1_openai_embedder", group_id=group_id,
                               reason="group has v1 embedding data only")
            except Exception as e:
                logger.warning("hybrid_embedding_detection_failed", error=str(e), group_id=group_id,
                              fallback="v1_openai")

        pipeline = HybridPipeline(
            profile=profile,
            llm_client=llm_client,
            embedding_client=embedding_client,  # V2 Voyage (2048D) or V1 OpenAI (3072D) based on detection
            hipporag_instance=hipporag_instance,
            graph_store=graph_store,
            text_unit_store=text_unit_store,
            neo4j_driver=neo4j_driver,
            graph_communities=graph_communities,
            relevance_budget=relevance_budget,
            group_id=group_id,
        )
        
        # Initialize async resources (AsyncNeo4jService connection)
        await pipeline.initialize()
        logger.info("hybrid_pipeline_initialized_for_group", group_id=group_id, 
                   embedding_version=embedding_version)
        
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

    except HighQualityError as e:
        logger.warning(
            "hybrid_query_strict_high_quality_failed",
            group_id=group_id,
            code=getattr(e, "code", "ROUTE3_STRICT_HIGH_QUALITY"),
            error=str(e),
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": getattr(e, "code", "ROUTE3_STRICT_HIGH_QUALITY"),
                    "message": str(e),
                    "details": getattr(e, "details", {}) or {},
                }
            },
        )
        
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

    except HighQualityError as e:
        logger.warning(
            "audit_query_strict_high_quality_failed",
            group_id=group_id,
            code=getattr(e, "code", "ROUTE3_STRICT_HIGH_QUALITY"),
            error=str(e),
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": getattr(e, "code", "ROUTE3_STRICT_HIGH_QUALITY"),
                    "message": str(e),
                    "details": getattr(e, "details", {}) or {},
                }
            },
        )
        
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

    except HighQualityError as e:
        logger.warning(
            "drift_query_strict_high_quality_failed",
            group_id=group_id,
            code=getattr(e, "code", "ROUTE3_STRICT_HIGH_QUALITY"),
            error=str(e),
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": getattr(e, "code", "ROUTE3_STRICT_HIGH_QUALITY"),
                    "message": str(e),
                    "details": getattr(e, "details", {}) or {},
                }
            },
        )
        
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
        from src.worker.services.document_intelligence_service import DocumentIntelligenceService

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
        default=False,
        description="Whether to run community detection upfront (LazyGraphRAG does this on-demand)",
    )
    run_raptor: bool = Field(
        default=False,
        description="Legacy RAPTOR hierarchical summarization (disabled by default)",
    )
    reindex: bool = Field(
        default=False,
        description="If true, delete existing group data before indexing",
    )
    # KNN tuning parameters (for testing different configurations)
    knn_enabled: bool = Field(
        default=True,
        description="Enable GDS KNN to create SEMANTICALLY_SIMILAR edges between entities",
    )
    knn_top_k: int = Field(
        default=5,
        description="Number of nearest neighbors per node in KNN (default: 5)",
    )
    knn_similarity_cutoff: float = Field(
        default=0.60,
        description="Minimum similarity threshold for KNN edges (default: 0.60)",
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
    knn_enabled: bool = True,
    knn_top_k: int = 5,
    knn_similarity_cutoff: float = 0.60,
):
    """Background task to run indexing."""
    _indexing_jobs[job_id]["status"] = "running"
    _indexing_jobs[job_id]["progress"] = "Starting indexing pipeline..."
    
    try:
        from src.core.config import settings
        from src.worker.hybrid_v2.indexing.pipeline_factory import (
            get_lazygraphrag_indexing_pipeline_v2,
        )

        # Use V2 pipeline (with embedding_v2 property) when Voyage V2 is enabled
        pipeline = get_lazygraphrag_indexing_pipeline_v2()
        
        _indexing_jobs[job_id]["progress"] = "Indexing documents..."
        stats = await pipeline.index_documents(
            group_id=group_id,
            documents=docs_for_pipeline,
            reindex=reindex,
            ingestion=ingestion,
            run_community_detection=run_community_detection,
            run_raptor=run_raptor,
            knn_enabled=knn_enabled,
            knn_top_k=knn_top_k,
            knn_similarity_cutoff=knn_similarity_cutoff,
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

    # Convert documents into the V3 pipeline's expected dict format.
    docs_for_pipeline: List[Dict[str, Any]] = []
    for doc in body.documents:
        if isinstance(doc, str):
            if doc.startswith(("http://", "https://")):
                docs_for_pipeline.append(
                    {
                        "content": "",
                        "title": "",  # Empty, let pipeline extract from source
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
                    "title": doc.get("title", ""),  # Empty string, let pipeline extract from source
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
        body.knn_enabled,
        body.knn_top_k,
        body.knn_similarity_cutoff,
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
        from src.worker.services.graph_service import GraphService
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


@router.post("/init_vector_index")
async def init_vector_index(request: Request, force: bool = False):
    """
    Admin endpoint to create the chunk_embedding vector index.
    Required for Route 1 (Vector RAG) to function.
    
    Args:
        force: If True, drop and recreate the index (useful when new chunks are added)
    """
    from src.worker.services.graph_service import GraphService
    
    group_id = request.state.group_id
    graph_service = GraphService()
    
    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")
    
    try:
        with graph_service.driver.session() as session:
            # If force=True, drop the existing index first
            if force:
                try:
                    session.run("DROP INDEX chunk_embedding IF EXISTS")
                    logger.info("vector_index_dropped", group_id=group_id)
                except Exception as drop_error:
                    logger.warning("vector_index_drop_failed", error=str(drop_error))
            
            # Create the vector index
            vector_index_query = """
            CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
            FOR (t:TextChunk) ON (t.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 3072,
                `vector.similarity_function`: 'cosine'
            }}
            """
            session.run(vector_index_query)
        
        logger.info("vector_index_created", group_id=group_id, force=force)
        return {
            "status": "success",
            "message": f"Vector index 'chunk_embedding' {'recreated' if force else 'created'}",
            "group_id": group_id,
            "force": force
        }
    except Exception as e:
        logger.error("vector_index_creation_failed",
                    group_id=group_id,
                    error=str(e))
        return {
            "status": "warning",
            "message": f"Index creation attempt completed (may already exist): {str(e)}",
            "group_id": group_id
        }


@router.post("/init_textchunk_fulltext_index")
async def init_textchunk_fulltext_index(request: Request, force: bool = False):
    """Admin endpoint to create the TextChunk fulltext index.

    Route 1 uses Neo4j fulltext search as part of hybrid + RRF retrieval.

    Args:
        force: If True, drop and recreate the index.
    """
    from src.worker.services.graph_service import GraphService

    group_id = request.state.group_id
    graph_service = GraphService()

    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")

    try:
        with graph_service.driver.session() as session:
            if force:
                try:
                    session.run("DROP INDEX textchunk_fulltext IF EXISTS")
                    logger.info("textchunk_fulltext_index_dropped", group_id=group_id)
                except Exception as drop_error:
                    logger.warning("textchunk_fulltext_index_drop_failed", error=str(drop_error))

            session.run(
                "CREATE FULLTEXT INDEX textchunk_fulltext IF NOT EXISTS FOR (c:TextChunk) ON EACH [c.text]"
            )

        logger.info("textchunk_fulltext_index_created", group_id=group_id, force=force)
        return {
            "status": "success",
            "message": f"Fulltext index 'textchunk_fulltext' {'recreated' if force else 'created'}",
            "group_id": group_id,
            "force": force,
        }
    except Exception as e:
        logger.error(
            "textchunk_fulltext_index_creation_failed",
            group_id=group_id,
            error=str(e),
        )
        return {
            "status": "warning",
            "message": f"Index creation attempt completed (may already exist): {str(e)}",
            "group_id": group_id,
        }


@router.post("/embed_chunks")
async def embed_chunks(request: Request):
    """
    Admin endpoint to backfill embeddings for TextChunk nodes.
    Required for Route 1 (Vector RAG) when chunks were indexed without embeddings.
    """
    from src.worker.services.graph_service import GraphService
    from src.worker.services.llm_service import LLMService
    
    group_id = request.state.group_id
    graph_service = GraphService()
    llm_service = LLMService()
    
    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")
    
    if llm_service.embed_model is None:
        raise HTTPException(status_code=503, detail="Embedding model not initialized")
    
    try:
        # Get chunks without embeddings
        with graph_service.driver.session() as session:
            result = session.run("""
                MATCH (c:TextChunk {group_id: $group_id})
                WHERE c.embedding IS NULL
                RETURN c.id AS id, c.text AS text
                LIMIT 1000
            """, group_id=group_id)
            
            chunks = [(record["id"], record["text"]) for record in result]
        
        if not chunks:
            return {
                "status": "success",
                "message": "All chunks already have embeddings",
                "chunks_updated": 0,
                "group_id": group_id
            }
        
        # Embed chunks in batches
        updated = 0
        batch_size = 10
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            texts = [text for _, text in batch]
            
            # Get embeddings
            embeddings = []
            for text in texts:
                emb = llm_service.embed_model.get_text_embedding(text)
                embeddings.append(emb)
            
            # Update in Neo4j
            with graph_service.driver.session() as session:
                for (chunk_id, _), embedding in zip(batch, embeddings):
                    session.run("""
                        MATCH (c:TextChunk {id: $id, group_id: $group_id})
                        SET c.embedding = $embedding
                    """, id=chunk_id, group_id=group_id, embedding=embedding)
                    updated += 1
        
        logger.info("chunks_embedded", group_id=group_id, count=updated)
        return {
            "status": "success",
            "message": f"Embedded {updated} chunks",
            "chunks_updated": updated,
            "group_id": group_id
        }
        
    except Exception as e:
        logger.error("chunk_embedding_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backfill_document_id")
async def backfill_document_id(request: Request):
    """
    Admin endpoint to backfill document_id property on TextChunk nodes.
    Required for negative detection in Route 1 when chunks were indexed without document_id property.
    
    The document_id is derived from the PART_OF relationship to Document nodes.
    """
    from src.worker.services.graph_service import GraphService
    
    group_id = request.state.group_id
    graph_service = GraphService()
    
    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")
    
    try:
        with graph_service.driver.session() as session:
            # Backfill document_id from PART_OF relationship
            update_query = """
            MATCH (t:TextChunk {group_id: $group_id})-[:PART_OF]->(d:Document)
            WHERE t.document_id IS NULL
            SET t.document_id = d.id
            RETURN count(t) AS updated_chunks
            """
            
            result = session.run(update_query, group_id=group_id)
            record = result.single()
            updated = record["updated_chunks"] if record else 0
            
            # Verify results
            verify_query = """
            MATCH (t:TextChunk {group_id: $group_id})
            RETURN 
                count(t) AS total_chunks,
                count(t.document_id) AS chunks_with_document_id
            """
            
            result = session.run(verify_query, group_id=group_id)
            record = result.single()
            
            logger.info("document_id_backfilled", 
                       group_id=group_id,
                       updated=updated,
                       total=record["total_chunks"],
                       with_document_id=record["chunks_with_document_id"])
            
            return {
                "status": "success",
                "message": f"Backfilled document_id for {updated} chunks",
                "updated_chunks": updated,
                "total_chunks": record["total_chunks"],
                "chunks_with_document_id": record["chunks_with_document_id"],
                "group_id": group_id
            }
        
    except Exception as e:
        logger.error("document_id_backfill_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/chunks")
async def debug_chunks(request: Request):
    """
    Debug endpoint to check TextChunk status for Route 1.
    Shows total chunks, chunks with embeddings, and sample data.
    """
    from src.worker.services.graph_service import GraphService
    
    group_id = request.state.group_id
    graph_service = GraphService()
    
    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")
    
    try:
        with graph_service.driver.session() as session:
            # Count chunks and check embeddings
            result = session.run("""
                MATCH (c:TextChunk {group_id: $group_id})
                RETURN 
                    count(c) AS total_chunks,
                    sum(CASE WHEN c.embedding IS NOT NULL THEN 1 ELSE 0 END) AS chunks_with_embedding,
                    sum(CASE WHEN c.embedding IS NOT NULL AND size(c.embedding) > 0 THEN 1 ELSE 0 END) AS chunks_with_nonempty_embedding
            """, group_id=group_id)
            stats = result.single()
            
            # Get sample chunk
            sample_result = session.run("""
                MATCH (c:TextChunk {group_id: $group_id})
                RETURN c.id AS id, 
                       c.text AS text,
                       c.embedding IS NOT NULL AS has_embedding,
                       CASE WHEN c.embedding IS NOT NULL THEN size(c.embedding) ELSE 0 END AS embedding_size
                LIMIT 1
            """, group_id=group_id)
            sample = sample_result.single()
            
            # Check vector index
            try:
                index_result = session.run("SHOW INDEXES YIELD name, type WHERE name = 'chunk_embedding'")
                index_exists = index_result.single() is not None
            except Exception:
                index_exists = "unknown"
            
        return {
            "group_id": group_id,
            "total_chunks": stats["total_chunks"] if stats else 0,
            "chunks_with_embedding": stats["chunks_with_embedding"] if stats else 0,
            "chunks_with_nonempty_embedding": stats["chunks_with_nonempty_embedding"] if stats else 0,
            "vector_index_exists": index_exists,
            "sample_chunk": {
                "id": sample["id"] if sample else None,
                "text_preview": (sample["text"][:100] + "...") if sample and sample["text"] else None,
                "has_embedding": sample["has_embedding"] if sample else None,
                "embedding_size": sample["embedding_size"] if sample else None,
            } if sample else None
        }
        
    except Exception as e:
        logger.error("debug_chunks_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/search_chunks")
async def debug_search_chunks(request: Request, contains: str, limit: int = 10):
    """Debug endpoint to find chunks whose text contains a substring.

    Notes:
    - Scopes results to the request's `group_id`.
    - Intended for diagnostics only (e.g., verifying whether phrases like
      "monthly statement" exist anywhere in the indexed text).
    """
    from src.worker.services.graph_service import GraphService

    group_id = request.state.group_id
    graph_service = GraphService()

    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")

    contains = (contains or "").strip()
    if not contains:
        raise HTTPException(status_code=400, detail="Query param 'contains' is required")
    if len(contains) > 200:
        raise HTTPException(status_code=400, detail="Query param 'contains' is too long")

    limit = int(limit or 10)
    limit = max(1, min(limit, 25))

    try:
        with graph_service.driver.session() as session:
            rows = session.run(
                """
                MATCH (t:TextChunk {group_id: $group_id})
                WHERE toLower(t.text) CONTAINS toLower($contains)
                OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
                OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
                RETURN
                    t.id AS chunk_id,
                    substring(t.text, 0, 400) AS text_preview,
                    d.title AS document_title,
                    d.source AS document_source,
                    d.id AS document_id,
                    s.id AS section_id,
                    s.path_key AS section_path
                LIMIT $limit
                """,
                group_id=group_id,
                contains=contains,
                limit=limit,
            )
            matches = [dict(r) for r in rows]

        return {
            "group_id": group_id,
            "contains": contains,
            "limit": limit,
            "count": len(matches),
            "matches": matches,
        }
    except Exception as e:
        logger.error("debug_search_chunks_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debug/test_vector_search")
async def debug_test_vector_search(request: Request, body: HybridQueryRequest):
    """
    Debug endpoint to test vector search directly.
    All queries are tenant-scoped (no cross-tenant diagnostics returned).
    """
    from src.worker.services.graph_service import GraphService
    from src.worker.services.llm_service import LLMService
    
    group_id = request.state.group_id
    graph_service = GraphService()
    llm_service = LLMService()
    
    if not graph_service.driver:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")
    
    try:
        # Generate embedding for query using LLMService
        embedding = llm_service.embed(body.query)
        
        results = {
            "group_id": group_id,
            "query": body.query,
            "embedding_length": len(embedding),
            "tests": {}
        }
        
        with graph_service.driver.session() as session:
            # Tunables for diagnosis
            desired_k = 5
            candidate_k = 500

            # Test 1: Naive filter (can return 0 if group isn't in global topK)
            try:
                filtered_result = session.run(
                    """
                    CALL db.index.vector.queryNodes('chunk_embedding', $k, $embedding)
                    YIELD node, score
                    WHERE node.group_id = $group_id
                    RETURN node.id AS id, score
                    ORDER BY score DESC
                    """,
                    embedding=embedding,
                    group_id=group_id,
                    k=desired_k,
                )
                filtered_records = list(filtered_result)
                results["tests"]["filtered_vector_search"] = {
                    "success": True,
                    "k": desired_k,
                    "count": len(filtered_records),
                    "results": [
                        {"id": r["id"], "score": r["score"]}
                        for r in filtered_records
                    ],
                }
            except Exception as e:
                results["tests"]["filtered_vector_search"] = {"success": False, "error": str(e)}

            # Test 2: Oversample then filter+limit within group (the production fix)
            try:
                oversampled = session.run(
                    """
                    CALL db.index.vector.queryNodes('chunk_embedding', $candidate_k, $embedding)
                    YIELD node, score
                    WHERE node.group_id = $group_id
                    RETURN node.id AS id, score
                    ORDER BY score DESC
                    LIMIT $desired_k
                    """,
                    embedding=embedding,
                    group_id=group_id,
                    candidate_k=candidate_k,
                    desired_k=desired_k,
                )
                oversampled_records = list(oversampled)
                results["tests"]["oversampled_filtered_vector_search"] = {
                    "success": True,
                    "candidate_k": candidate_k,
                    "desired_k": desired_k,
                    "count": len(oversampled_records),
                    "results": [
                        {"id": r["id"], "score": r["score"]}
                        for r in oversampled_records
                    ],
                }
            except Exception as e:
                results["tests"]["oversampled_filtered_vector_search"] = {
                    "success": False,
                    "error": str(e),
                }

            # Test 3: Check if chunks exist for this group_id
            try:
                chunk_check = session.run(
                    """
                    MATCH (c:TextChunk {group_id: $group_id})
                    WHERE c.embedding IS NOT NULL AND size(c.embedding) > 0
                    RETURN count(c) AS count, collect(c.id)[0..3] AS sample_ids
                    """,
                    group_id=group_id,
                )
                chunk_rec = chunk_check.single()
                results["tests"]["chunks_for_group"] = {
                    "count": chunk_rec["count"],
                    "sample_ids": chunk_rec["sample_ids"],
                }
            except Exception as e:
                results["tests"]["chunks_for_group"] = {"error": str(e)}

            # Test 4: Index info
            try:
                index_info = session.run(
                    """
                    SHOW INDEXES YIELD name, type, state, populationPercent, labelsOrTypes, properties
                    WHERE name = 'chunk_embedding'
                    """
                )
                idx_rec = index_info.single()
                results["tests"]["index_info"] = (
                    {
                        "name": idx_rec["name"],
                        "type": idx_rec["type"],
                        "state": idx_rec["state"],
                        "populationPercent": idx_rec["populationPercent"],
                        "labelsOrTypes": idx_rec["labelsOrTypes"],
                        "properties": idx_rec["properties"],
                    }
                    if idx_rec
                    else {"error": "Index not found"}
                )
            except Exception as e:
                results["tests"]["index_info"] = {"error": str(e)}

            # Test 5: Presence check - does a chunk from this group appear in vector index results?
            # This avoids the “tie-breaker” ambiguity by directly checking for node.id == c.id.
            try:
                presence = session.run(
                    """
                    MATCH (c:TextChunk {group_id: $group_id})
                    WHERE c.embedding IS NOT NULL AND size(c.embedding) > 0
                    WITH c LIMIT 1
                    CALL db.index.vector.queryNodes('chunk_embedding', $candidate_k, c.embedding)
                    YIELD node, score
                    WITH c, collect({id: node.id, score: score}) AS hits
                    WITH c, [h IN hits WHERE h.id = c.id][0] AS self_hit
                    RETURN c.id AS source_id,
                           self_hit IS NOT NULL AS found_self,
                           self_hit.score AS self_score
                    """,
                    group_id=group_id,
                    candidate_k=candidate_k,
                )
                presence_rec = presence.single()
                results["tests"]["source_chunk_presence"] = {
                    "source_id": presence_rec["source_id"],
                    "found_self": presence_rec["found_self"],
                    "self_score": presence_rec["self_score"],
                    "candidate_k": candidate_k,
                }
            except Exception as e:
                results["tests"]["source_chunk_presence"] = {"error": str(e)}

            # Test 6: Embedding sample from group
            try:
                embed_type_test = session.run(
                    """
                    MATCH (c:TextChunk {group_id: $group_id})
                    WHERE c.embedding IS NOT NULL AND size(c.embedding) > 0
                    WITH c LIMIT 1
                    RETURN c.id AS id,
                           size(c.embedding) AS embed_size,
                           c.embedding[0..5] AS embed_sample,
                           c.updated_at AS updated_at
                    """,
                    group_id=group_id,
                )
                embed_type_rec = embed_type_test.single()
                results["tests"]["embedding_details"] = (
                    {
                        "id": embed_type_rec["id"],
                        "embed_size": embed_type_rec["embed_size"],
                        "embed_sample": embed_type_rec["embed_sample"],
                        "updated_at": str(embed_type_rec.get("updated_at")),
                    }
                    if embed_type_rec
                    else {"error": "No chunk found"}
                )
            except Exception as e:
                results["tests"]["embedding_details"] = {"error": str(e)}
        
        return results
        
    except Exception as e:
        logger.error("debug_test_vector_search_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/section_similarity_distribution")
async def debug_section_similarity_distribution(request: Request):
    """
    Debug endpoint to compute cross-document section embedding similarity distribution.
    
    Returns:
    - Number of sections with embeddings
    - Number of cross-document pairs
    - Similarity distribution (min, p50, p90, p95, p99, max)
    - Suggested threshold to create edges
    
    Use this to understand why semantic_similarity_edges = 0.
    """
    group_id = request.state.group_id
    logger.info("debug_section_similarity_distribution", group_id=group_id)
    
    try:
        from src.worker.hybrid.services.neo4j_store import Neo4jStoreV3
        from src.core.config import settings as app_settings
        import numpy as np
        
        if not app_settings.NEO4J_URI or not app_settings.NEO4J_USERNAME or not app_settings.NEO4J_PASSWORD:
            raise HTTPException(status_code=503, detail="Neo4j not configured")
        
        neo4j_store = Neo4jStoreV3(
            uri=app_settings.NEO4J_URI,
            username=app_settings.NEO4J_USERNAME,
            password=app_settings.NEO4J_PASSWORD,
        )
        
        # Fetch all sections with embeddings
        with neo4j_store.driver.session(database=neo4j_store.database) as session:
            result = session.run(
                """
                MATCH (s:Section {group_id: $group_id})
                WHERE s.embedding IS NOT NULL
                RETURN s.id AS id, s.doc_id AS doc_id, s.embedding AS embedding
                """,
                group_id=group_id,
            )
            sections = [
                {"id": record["id"], "doc_id": record["doc_id"], "embedding": record["embedding"]}
                for record in result
            ]
        
        if len(sections) < 2:
            return {
                "group_id": group_id,
                "sections_with_embeddings": len(sections),
                "message": "Insufficient sections (need at least 2)"
            }
        
        # Compute pairwise cross-document similarities
        similarities = []
        pair_details = []
        
        for i, s1 in enumerate(sections):
            if s1["embedding"] is None:
                continue
            emb1 = np.array(s1["embedding"])
            norm1 = np.linalg.norm(emb1)
            if norm1 == 0:
                continue
            
            for j, s2 in enumerate(sections):
                if j <= i:  # Avoid duplicates and self-comparison
                    continue
                if s1["doc_id"] == s2["doc_id"]:  # Only cross-document
                    continue
                if s2["embedding"] is None:
                    continue
                
                emb2 = np.array(s2["embedding"])
                norm2 = np.linalg.norm(emb2)
                if norm2 == 0:
                    continue
                
                # Cosine similarity
                similarity = float(np.dot(emb1, emb2) / (norm1 * norm2))
                similarities.append(similarity)
                
                # Keep top pairs for inspection
                if len(pair_details) < 10 or similarity > min(p["similarity"] for p in pair_details):
                    pair_details.append({
                        "s1_id": s1["id"],
                        "s1_doc": s1["doc_id"],
                        "s2_id": s2["id"],
                        "s2_doc": s2["doc_id"],
                        "similarity": round(similarity, 4),
                    })
                    pair_details.sort(key=lambda x: x["similarity"], reverse=True)
                    pair_details = pair_details[:10]  # Keep top 10
        
        if not similarities:
            return {
                "group_id": group_id,
                "sections_with_embeddings": len(sections),
                "cross_document_pairs": 0,
                "message": "No cross-document pairs found"
            }
        
        # Compute distribution
        similarities_sorted = sorted(similarities)
        
        def percentile(p):
            idx = int(round(p * (len(similarities_sorted) - 1)))
            return similarities_sorted[idx]
        
        distribution = {
            "min": round(similarities_sorted[0], 4),
            "p25": round(percentile(0.25), 4),
            "p50": round(percentile(0.50), 4),
            "p75": round(percentile(0.75), 4),
            "p90": round(percentile(0.90), 4),
            "p95": round(percentile(0.95), 4),
            "p99": round(percentile(0.99), 4),
            "max": round(similarities_sorted[-1], 4),
        }
        
        # Suggest threshold
        # Target: Create edges for top 5-10% of pairs
        suggested_threshold_conservative = round(percentile(0.90), 2)
        suggested_threshold_moderate = round(percentile(0.75), 2)
        
        # Count how many edges would be created at different thresholds
        thresholds_analysis = {}
        for threshold in [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90]:
            count = sum(1 for s in similarities if s >= threshold)
            thresholds_analysis[f"threshold_{threshold}"] = {
                "edges_created": count,
                "percentage": round(100 * count / len(similarities), 2)
            }
        
        return {
            "group_id": group_id,
            "sections_with_embeddings": len(sections),
            "cross_document_pairs": len(similarities),
            "distribution": distribution,
            "thresholds_analysis": thresholds_analysis,
            "suggestions": {
                "conservative": {
                    "threshold": suggested_threshold_conservative,
                    "description": "Top 10% of pairs (conservative)"
                },
                "moderate": {
                    "threshold": suggested_threshold_moderate,
                    "description": "Top 25% of pairs (moderate)"
                }
            },
            "top_10_pairs": pair_details,
        }
        
    except Exception as e:
        logger.error("debug_section_similarity_distribution_failed", group_id=group_id, error=str(e))
        import traceback
        return {
            "status": "error",
            "group_id": group_id,
            "error": str(e),
            "trace": traceback.format_exc()
        }


@router.post("/debug/rebuild_similarity_edges")
async def debug_rebuild_similarity_edges(request: Request):
    """
    Rebuild SEMANTICALLY_SIMILAR edges for a group.
    
    Deletes existing edges and creates new ones using current threshold (0.43).
    Use this after changing the similarity threshold without full re-indexing.
    """
    group_id = request.state.group_id
    logger.info("debug_rebuild_similarity_edges_start", group_id=group_id)
    
    try:
        from src.worker.hybrid.services.neo4j_store import Neo4jStoreV3
        from src.core.config import settings as app_settings
        from src.worker.hybrid.indexing.lazygraphrag_pipeline import LazyGraphRAGIndexingPipeline
        
        if not app_settings.NEO4J_URI or not app_settings.NEO4J_USERNAME or not app_settings.NEO4J_PASSWORD:
            raise HTTPException(status_code=503, detail="Neo4j not configured")
        
        neo4j_store = Neo4jStoreV3(
            uri=app_settings.NEO4J_URI,
            username=app_settings.NEO4J_USERNAME,
            password=app_settings.NEO4J_PASSWORD,
        )
        
        # Step 1: Delete existing edges
        with neo4j_store.driver.session(database=neo4j_store.database) as session:
            result = session.run(
                """
                MATCH (s1:Section {group_id: $group_id})-[r:SEMANTICALLY_SIMILAR]-(s2:Section {group_id: $group_id})
                DELETE r
                RETURN count(r) as deleted_count
                """,
                group_id=group_id
            )
            deleted_count = result.single()["deleted_count"]
        
        logger.info("deleted_existing_edges", group_id=group_id, count=deleted_count)
        
        # Step 2: Rebuild edges
        pipeline = LazyGraphRAGIndexingPipeline(
            neo4j_store=neo4j_store,
            llm=None,
            embedder=None
        )
        
        result = await pipeline._build_section_similarity_edges(group_id)
        
        neo4j_store.driver.close()
        
        return {
            "status": "success",
            "group_id": group_id,
            "deleted_edges": deleted_count,
            "created_edges": result.get("edges_created", 0),
            "cross_document_pairs": result.get("cross_document_pairs", 0),
            "threshold_used": 0.43
        }
        
    except Exception as e:
        logger.error("debug_rebuild_similarity_edges_failed", group_id=group_id, error=str(e))
        import traceback
        return {
            "status": "error",
            "group_id": group_id,
            "error": str(e),
            "trace": traceback.format_exc()
        }
