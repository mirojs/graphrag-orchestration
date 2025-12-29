"""
Hybrid Pipeline API Router

Exposes the LazyGraphRAG + HippoRAG 2 hybrid pipeline via REST endpoints.

Endpoints:
- POST /hybrid/query - Execute a query through the hybrid pipeline
- POST /hybrid/query/audit - Execute with full audit trail
- POST /hybrid/query/fast - Execute via Vector RAG fast lane
- GET /hybrid/health - Health check for hybrid components
- POST /hybrid/configure - Configure pipeline settings
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
import structlog

from app.hybrid.orchestrator import HybridPipeline
from app.hybrid.router.main import DeploymentProfile
from app.hybrid.indexing import DualIndexService, get_hipporag_service

router = APIRouter()
logger = structlog.get_logger(__name__)

# Pipeline instance cache per group
_pipeline_cache: Dict[str, HybridPipeline] = {}


# ============================================================================
# Request/Response Models
# ============================================================================

class DeploymentProfileEnum(str, Enum):
    """Deployment profile selection."""
    GENERAL_ENTERPRISE = "general_enterprise"
    HIGH_ASSURANCE_AUDIT = "high_assurance_audit"


class HybridQueryRequest(BaseModel):
    """Request model for hybrid pipeline queries."""
    query: str = Field(..., description="The natural language query to execute")
    response_type: Literal["detailed_report", "summary", "audit_trail"] = Field(
        default="detailed_report",
        description="Type of response to generate"
    )
    force_route: Optional[Literal["vector_rag", "hybrid_pipeline"]] = Field(
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
    route_used: str = Field(..., description="Which route was taken")
    citations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Source citations with text and metadata"
    )
    evidence_path: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Entity path showing evidence connections"
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
        description="Enable Vector RAG fast lane (Profile A only)"
    )


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    components: Dict[str, str]
    profile: str
    group_id: str


# ============================================================================
# Helper Functions
# ============================================================================

def _get_deployment_profile(profile_enum: DeploymentProfileEnum) -> DeploymentProfile:
    """Convert API enum to internal DeploymentProfile."""
    if profile_enum == DeploymentProfileEnum.HIGH_ASSURANCE_AUDIT:
        return DeploymentProfile.HIGH_ASSURANCE_AUDIT
    return DeploymentProfile.GENERAL_ENTERPRISE


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
        
        # TODO: Initialize actual clients from services
        # For now, create pipeline with None clients (will use fallbacks)
        # In production:
        # - llm_client = LLMService().get_llm()
        # - hipporag_instance = HippoRAGService(group_id).get_instance()
        # - graph_store = GraphService().get_store(group_id)
        # - vector_rag = VectorService().get_query_engine(group_id)
        
        pipeline = HybridPipeline(
            profile=profile,
            llm_client=None,  # TODO: Wire to LLMService
            hipporag_instance=None,  # TODO: Wire to HippoRAG
            graph_store=None,  # TODO: Wire to Neo4j
            text_unit_store=None,  # TODO: Wire to text store
            vector_rag_client=None,  # TODO: Wire to Vector RAG
            relevance_budget=relevance_budget
        )
        
        _pipeline_cache[cache_key] = pipeline
    
    return _pipeline_cache[cache_key]


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/query", response_model=HybridQueryResponse)
async def hybrid_query(request: Request, body: HybridQueryRequest):
    """
    Execute a query through the hybrid LazyGraphRAG + HippoRAG 2 pipeline.
    
    The router automatically decides between:
    - Vector RAG (fast lane) for simple queries
    - Hybrid Pipeline (deep dive) for complex queries
    
    Use `force_route` to override the automatic decision.
    """
    group_id = request.state.group_id
    
    logger.info("hybrid_query_received",
               group_id=group_id,
               query_preview=body.query[:50],
               response_type=body.response_type,
               force_route=body.force_route)
    
    try:
        pipeline = await _get_or_create_pipeline(group_id)
        
        # Handle forced routing
        if body.force_route == "vector_rag":
            result = await pipeline._execute_vector_rag(body.query)
        elif body.force_route == "hybrid_pipeline":
            result = await pipeline._execute_hybrid_pipeline(
                body.query, body.response_type
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
    Execute a query with full audit trail.
    
    This is a convenience endpoint that:
    - Forces response_type to "audit_trail"
    - Always uses the hybrid pipeline (no Vector RAG shortcut)
    - Returns maximum evidence detail for compliance
    
    Recommended for: forensic accounting, legal discovery, compliance audits.
    """
    group_id = request.state.group_id
    
    logger.info("audit_query_received",
               group_id=group_id,
               query_preview=body.query[:50])
    
    try:
        # Use High-Assurance profile for audit queries
        pipeline = await _get_or_create_pipeline(
            group_id,
            profile=DeploymentProfile.HIGH_ASSURANCE_AUDIT,
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
    Execute a query via Vector RAG fast lane only.
    
    This is a convenience endpoint that:
    - Always uses Vector RAG (no hybrid pipeline)
    - Optimized for sub-second latency
    - Best for simple fact lookups
    
    Note: Will fall back to hybrid if Vector RAG is unavailable.
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
        
        result = await pipeline._execute_vector_rag(body.query)
        return HybridQueryResponse(**result)
        
    except Exception as e:
        logger.error("fast_query_failed",
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
        
        return HealthResponse(
            status="healthy" if all(
                v in ["ok", "not_configured", "fallback_mode"]
                for v in health_status.values()
            ) else "degraded",
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
    
    Allows switching between:
    - Profile A (General Enterprise): Vector RAG + Hybrid
    - Profile B (High-Assurance): Hybrid only
    
    Configuration persists for the duration of the session.
    """
    group_id = request.state.group_id
    
    logger.info("configuring_pipeline",
               group_id=group_id,
               profile=config.profile.value,
               relevance_budget=config.relevance_budget)
    
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
        
        return {
            "status": "configured",
            "group_id": group_id,
            "profile": config.profile.value,
            "relevance_budget": config.relevance_budget,
            "vector_rag_enabled": config.enable_vector_rag and profile != DeploymentProfile.HIGH_ASSURANCE_AUDIT
        }
        
    except Exception as e:
        logger.error("configuration_failed",
                    group_id=group_id,
                    error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profiles")
async def list_profiles():
    """
    List available deployment profiles with descriptions.
    
    Helps users understand the tradeoffs between profiles.
    """
    return {
        "profiles": [
            {
                "id": "general_enterprise",
                "name": "General Enterprise (Profile A)",
                "description": "Speed-optimized with Vector RAG fast lane",
                "best_for": [
                    "Customer support",
                    "Internal wikis",
                    "General Q&A"
                ],
                "latency": "Fast (sub-second for simple queries)",
                "accuracy": "Standard (90%+ for fact lookups)"
            },
            {
                "id": "high_assurance_audit",
                "name": "High-Assurance Audit (Profile B)",
                "description": "Precision-only with full hybrid pipeline",
                "best_for": [
                    "Forensic accounting",
                    "Compliance auditing",
                    "Legal discovery"
                ],
                "latency": "Thorough (5-10 seconds)",
                "accuracy": "High (deterministic evidence paths)"
            }
        ]
    }


# ============================================================================
# Indexing Endpoints
# ============================================================================

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
                    with open(filepath) as f:
                        data = json.load(f)
                    status["files"][filename] = {
                        "exists": True,
                        "count": len(data) if isinstance(data, list) else len(data.keys()),
                        "size_bytes": filepath.stat().st_size
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
