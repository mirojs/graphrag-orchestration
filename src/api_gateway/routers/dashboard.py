"""
Dashboard API Router

Provides endpoints for:
- Personal dashboard: user profile, usage stats, plan info
- Management dashboard: system metrics, user analytics (admin only)

These endpoints serve data to the frontend dashboard pages.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
import structlog
import os
from datetime import datetime, timezone

from src.api_gateway.middleware.auth import get_current_user, get_user_roles, get_user_id
from src.api_gateway.routers.admin import verify_admin
from src.core.roles import (
    AppRole,
    PlanTier,
    PlanLimits,
    PLAN_DEFINITIONS,
    UserProfile,
    resolve_user_profile,
)
from src.core.services.quota_enforcer import get_quota_enforcer

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ============================================================================
# Response Models
# ============================================================================

class UserProfileResponse(BaseModel):
    """User profile with role, plan, and usage data."""
    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: list[str] = []
    is_admin: bool = False

    # Plan
    plan: str
    plan_limits: Optional[PlanLimits] = None
    billing_type: str = "b2c"

    # Usage
    queries_today: int = 0
    queries_this_month: int = 0
    documents_count: int = 0
    storage_used_gb: float = 0.0

    # Feature flags derived from plan
    features: Dict[str, bool] = {}


class UsageStatsResponse(BaseModel):
    """Personal usage statistics."""
    queries_today: int = 0
    queries_this_month: int = 0
    queries_limit_day: int = 0
    queries_limit_month: int = 0
    documents_count: int = 0
    documents_limit: int = 0
    storage_used_gb: float = 0.0
    storage_limit_gb: float = 0.0
    # Recent activity
    recent_queries: List[Dict[str, Any]] = []
    top_topics: List[Dict[str, Any]] = []


class SystemMetricsResponse(BaseModel):
    """System-wide metrics for admin dashboard."""
    total_users: int = 0
    active_users_today: int = 0
    active_users_month: int = 0
    total_queries_today: int = 0
    total_queries_month: int = 0
    total_documents: int = 0
    total_storage_gb: float = 0.0

    # Per-plan distribution
    plan_distribution: Dict[str, int] = {}

    # System health
    algorithm_version: str = ""
    enabled_versions: List[str] = []
    system_status: str = "healthy"

    # Recent activity
    queries_per_hour: List[Dict[str, Any]] = []
    top_users: List[Dict[str, Any]] = []
    error_rate: float = 0.0


class PlanInfoResponse(BaseModel):
    """Available plans and pricing."""
    current_plan: str
    billing_type: str
    plans: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# Personal Dashboard Endpoints
# ============================================================================

@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Get the current user's profile, roles, plan, and usage stats.

    This is the primary endpoint for the personal dashboard.
    """
    user_id = user.get("oid", "")

    # Resolve plan from quota enforcer (Redis-cached) with fallback
    try:
        enforcer = await get_quota_enforcer()
        plan_tier = await enforcer.get_plan(user_id)
        usage = await enforcer.get_usage(user_id)
    except Exception:
        plan_tier = PlanTier.FREE
        usage = {"queries_today": 0, "queries_this_month": 0}

    # Admin override: admins get Enterprise if they have no explicit plan
    is_admin = any(r.lower() == "admin" for r in user.get("roles", []))
    if is_admin and plan_tier == PlanTier.FREE:
        plan_tier = PlanTier.ENTERPRISE

    # Detect billing type from auth middleware
    auth_type = getattr(request.app.state, "auth_type", "B2B")
    billing_type = "b2b" if auth_type == "B2B" else "b2c"

    profile = resolve_user_profile(user, plan_tier=plan_tier, billing_type=billing_type)

    limits = profile.plan_limits or PLAN_DEFINITIONS[PlanTier.FREE]

    features = {
        "graphrag": limits.graphrag_enabled,
        "advanced_analytics": limits.advanced_analytics,
        "custom_models": limits.custom_models,
        "api_access": limits.api_access,
        "priority_support": limits.priority_support,
        "sso": limits.sso_enabled,
        "custom_branding": limits.custom_branding,
    }

    return UserProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        email=profile.email,
        tenant_id=profile.tenant_id,
        roles=profile.roles,
        is_admin=profile.is_admin,
        plan=profile.plan.value,
        plan_limits=profile.plan_limits,
        billing_type=billing_type,
        queries_today=usage["queries_today"],
        queries_this_month=usage["queries_this_month"],
        documents_count=profile.documents_count,
        storage_used_gb=profile.storage_used_gb,
        features=features,
    )


@router.get("/me/usage", response_model=UsageStatsResponse)
async def get_my_usage(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Get detailed usage statistics for the current user.
    """
    user_id = user.get("oid", "")

    # Get plan and usage from quota enforcer
    try:
        enforcer = await get_quota_enforcer()
        plan_tier = await enforcer.get_plan(user_id)
        usage = await enforcer.get_usage(user_id)
    except Exception:
        plan_tier = PlanTier.FREE
        usage = {"queries_today": 0, "queries_this_month": 0}

    is_admin = any(r.lower() == "admin" for r in user.get("roles", []))
    if is_admin and plan_tier == PlanTier.FREE:
        plan_tier = PlanTier.ENTERPRISE

    limits = PLAN_DEFINITIONS[plan_tier]

    return UsageStatsResponse(
        queries_today=usage["queries_today"],
        queries_this_month=usage["queries_this_month"],
        queries_limit_day=limits.queries_per_day,
        queries_limit_month=limits.queries_per_month,
        documents_count=0,  # TODO: count from blob/cosmos
        documents_limit=limits.max_documents,
        storage_used_gb=0.0,  # TODO: calculate from blob
        storage_limit_gb=limits.max_storage_gb,
        recent_queries=[],  # TODO: from Cosmos usage records
        top_topics=[],
    )


@router.get("/plans", response_model=PlanInfoResponse)
async def get_available_plans(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Get available payment plans and the user's current plan.
    Used for the plan upgrade/comparison UI.
    """
    user_id = user.get("oid", "")

    try:
        enforcer = await get_quota_enforcer()
        current_plan = await enforcer.get_plan(user_id)
    except Exception:
        current_plan = PlanTier.FREE

    is_admin = any(r.lower() == "admin" for r in user.get("roles", []))
    if is_admin and current_plan == PlanTier.FREE:
        current_plan = PlanTier.ENTERPRISE

    plans = {}
    for tier, limits in PLAN_DEFINITIONS.items():
        plans[tier.value] = {
            "name": tier.value.title(),
            "queries_per_day": limits.queries_per_day,
            "queries_per_month": limits.queries_per_month,
            "max_documents": limits.max_documents,
            "max_storage_gb": limits.max_storage_gb,
            "graphrag_enabled": limits.graphrag_enabled,
            "advanced_analytics": limits.advanced_analytics,
            "custom_models": limits.custom_models,
            "api_access": limits.api_access,
            "sso_enabled": limits.sso_enabled,
        }

    return PlanInfoResponse(
        current_plan=current_plan.value,
        billing_type="b2c",
        plans=plans,
    )


# ============================================================================
# Management Dashboard Endpoints (Admin Only)
# ============================================================================

@router.get("/admin/metrics", response_model=SystemMetricsResponse)
async def get_system_metrics(
    _: bool = Depends(verify_admin),
):
    """
    Get system-wide metrics for the admin management dashboard.

    TODO: Wire to actual metrics sources (App Insights, Cosmos DB analytics).
    """
    from src.core.algorithm_registry import (
        ALGORITHM_VERSIONS,
        get_default_version,
    )

    return SystemMetricsResponse(
        total_users=0,
        active_users_today=0,
        active_users_month=0,
        total_queries_today=0,
        total_queries_month=0,
        total_documents=0,
        total_storage_gb=0.0,
        plan_distribution={
            "free": 0,
            "starter": 0,
            "professional": 0,
            "enterprise": 0,
        },
        algorithm_version=get_default_version(),
        enabled_versions=[
            v for v, algo in ALGORITHM_VERSIONS.items()
            if algo.is_enabled()
        ],
        system_status="healthy",
        queries_per_hour=[],
        top_users=[],
        error_rate=0.0,
    )


@router.get("/admin/users")
async def list_users(
    _: bool = Depends(verify_admin),
    limit: int = 50,
    offset: int = 0,
):
    """
    List users with their roles and plan information.

    TODO: Wire to user store (Entra ID Graph API + billing database).
    """
    return {
        "users": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }
