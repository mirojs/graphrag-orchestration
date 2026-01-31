"""
Maintenance API Router for V2 GraphRAG.

Provides REST endpoints for maintenance jobs, health checks, and admin operations.
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime

from src.worker.hybrid_v2.services.maintenance import (
    MaintenanceService,
    MaintenanceJobType,
    MaintenanceJobResult,
    GroupHealth,
)
from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3
from src.core.config import settings

router = APIRouter(prefix="/api/v2/maintenance", tags=["maintenance"])


# ==================== Request/Response Models ====================

class RunJobRequest(BaseModel):
    """Request to run a maintenance job."""
    job_type: str = Field(
        ..., 
        description="Job type: gc_orphan_entities, gc_stale_edges, gc_deprecated_vectors, recompute_gds, validate_group_isolation, full_group_cleanup"
    )
    group_id: str = Field(..., description="Target group ID")
    dry_run: bool = Field(False, description="If true, report what would be done without making changes")


class JobResultResponse(BaseModel):
    """Response from a maintenance job."""
    job_type: str
    group_id: str
    success: bool
    stats: dict
    errors: List[str]
    duration_ms: int
    dry_run: bool


class GroupHealthResponse(BaseModel):
    """Health metrics for a group."""
    group_id: str
    total_documents: int
    active_documents: int
    deprecated_documents: int
    total_chunks: int
    total_entities: int
    orphan_entities: int
    stale_edges: int
    gds_stale: bool
    gds_last_computed: Optional[str]
    isolation_violations: int
    health_score: float  # Computed health score 0-100


class StaleGroupResponse(BaseModel):
    """Information about a stale group."""
    group_id: str
    stale_since: Optional[str]
    last_change: Optional[str]


# ==================== Helper ====================

def get_maintenance_service() -> MaintenanceService:
    """Get or create MaintenanceService instance."""
    # settings imported from src.core.config
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE,
    )
    return MaintenanceService(neo4j_store)


def parse_job_type(job_type_str: str) -> MaintenanceJobType:
    """Parse job type string to enum."""
    try:
        return MaintenanceJobType(job_type_str)
    except ValueError:
        valid_types = [t.value for t in MaintenanceJobType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job_type. Must be one of: {valid_types}"
        )


def compute_health_score(health: GroupHealth) -> float:
    """Compute a 0-100 health score based on metrics."""
    score = 100.0
    
    # Deduct for orphan entities (up to 20 points)
    if health.total_entities > 0:
        orphan_ratio = health.orphan_entities / health.total_entities
        score -= min(20, orphan_ratio * 100)
    
    # Deduct for stale edges (up to 15 points)
    if health.stale_edges > 0:
        score -= min(15, health.stale_edges / 10)
    
    # Deduct for GDS staleness (10 points)
    if health.gds_stale:
        score -= 10
    
    # Deduct for isolation violations (up to 30 points)
    if health.isolation_violations > 0:
        score -= min(30, health.isolation_violations * 5)
    
    # Deduct for high deprecation ratio (up to 10 points)
    if health.total_documents > 0:
        deprecated_ratio = health.deprecated_documents / health.total_documents
        if deprecated_ratio > 0.5:
            score -= min(10, (deprecated_ratio - 0.5) * 20)
    
    return max(0, round(score, 1))


# ==================== Endpoints ====================

@router.post(
    "/jobs",
    response_model=JobResultResponse,
    summary="Run a maintenance job",
    description="Execute a specific maintenance job on a group.",
)
async def run_maintenance_job(request: RunJobRequest):
    """Run a maintenance job."""
    service = get_maintenance_service()
    job_type = parse_job_type(request.job_type)
    
    result = await service.run_job(
        job_type=job_type,
        group_id=request.group_id,
        dry_run=request.dry_run,
    )
    
    return JobResultResponse(
        job_type=result.job_type.value,
        group_id=result.group_id,
        success=result.success,
        stats=result.stats,
        errors=result.errors,
        duration_ms=result.duration_ms,
        dry_run=result.dry_run,
    )


@router.post(
    "/groups/{group_id}/run-all-gc",
    response_model=List[JobResultResponse],
    summary="Run all GC jobs",
    description="Execute all garbage collection jobs in the correct order.",
)
async def run_all_gc(
    group_id: str,
    dry_run: bool = Query(False, description="If true, report without making changes"),
):
    """Run all GC jobs for a group."""
    service = get_maintenance_service()
    
    results = await service.run_all_gc(
        group_id=group_id,
        dry_run=dry_run,
    )
    
    return [
        JobResultResponse(
            job_type=r.job_type.value,
            group_id=r.group_id,
            success=r.success,
            stats=r.stats,
            errors=r.errors,
            duration_ms=r.duration_ms,
            dry_run=r.dry_run,
        )
        for r in results
    ]


@router.get(
    "/groups/{group_id}/health",
    response_model=GroupHealthResponse,
    summary="Get group health",
    description="Get comprehensive health metrics for a group.",
)
async def get_group_health(group_id: str):
    """Get health metrics for a group."""
    service = get_maintenance_service()
    
    health = await service.get_group_health(group_id)
    health_score = compute_health_score(health)
    
    return GroupHealthResponse(
        group_id=health.group_id,
        total_documents=health.total_documents,
        active_documents=health.active_documents,
        deprecated_documents=health.deprecated_documents,
        total_chunks=health.total_chunks,
        total_entities=health.total_entities,
        orphan_entities=health.orphan_entities,
        stale_edges=health.stale_edges,
        gds_stale=health.gds_stale,
        gds_last_computed=health.gds_last_computed.isoformat() if health.gds_last_computed else None,
        isolation_violations=health.isolation_violations,
        health_score=health_score,
    )


@router.post(
    "/groups/{group_id}/recompute-gds",
    response_model=JobResultResponse,
    summary="Trigger GDS recompute",
    description="Force recomputation of GDS properties (communities, PageRank, KNN).",
)
async def trigger_gds_recompute(
    group_id: str,
    dry_run: bool = Query(False),
):
    """Trigger GDS recomputation for a group."""
    service = get_maintenance_service()
    
    result = await service.run_job(
        job_type=MaintenanceJobType.RECOMPUTE_GDS,
        group_id=group_id,
        dry_run=dry_run,
    )
    
    return JobResultResponse(
        job_type=result.job_type.value,
        group_id=result.group_id,
        success=result.success,
        stats=result.stats,
        errors=result.errors,
        duration_ms=result.duration_ms,
        dry_run=result.dry_run,
    )


@router.get(
    "/admin/groups/stale",
    response_model=List[StaleGroupResponse],
    summary="List stale groups",
    description="List all groups that need GDS recomputation.",
)
async def list_stale_groups():
    """List groups needing GDS recompute."""
    service = get_maintenance_service()
    
    groups = await service.get_stale_groups()
    
    return [
        StaleGroupResponse(
            group_id=g["group_id"],
            stale_since=g["stale_since"].isoformat() if g.get("stale_since") else None,
            last_change=g["last_change"].isoformat() if g.get("last_change") else None,
        )
        for g in groups
    ]


@router.post(
    "/groups/{group_id}/validate-isolation",
    response_model=JobResultResponse,
    summary="Validate group isolation",
    description="Check for nodes/edges missing group_id (isolation violations).",
)
async def validate_group_isolation(group_id: str):
    """Validate group isolation."""
    service = get_maintenance_service()
    
    result = await service.run_job(
        job_type=MaintenanceJobType.VALIDATE_GROUP_ISOLATION,
        group_id=group_id,
        dry_run=True,  # Always dry_run for validation
    )
    
    return JobResultResponse(
        job_type=result.job_type.value,
        group_id=result.group_id,
        success=result.success,
        stats=result.stats,
        errors=result.errors,
        duration_ms=result.duration_ms,
        dry_run=result.dry_run,
    )
