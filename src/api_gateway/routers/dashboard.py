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
import asyncio
import structlog
import os
from datetime import datetime, timezone

from src.api_gateway.middleware.auth import get_current_user, get_user_roles, get_user_id, get_group_id
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
from src.core.services.cosmos_client import get_cosmos_client

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
    # Credit system
    credits_used_month: int = 0
    credits_limit_month: Optional[int] = None
    credits_remaining: Optional[int] = None
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
    group_id: str = Depends(get_group_id),
):
    """
    Get the current user's profile, roles, plan, and usage stats.

    This is the primary endpoint for the personal dashboard.
    """
    user_id = user.get("oid", "")

    # Resolve plan from quota enforcer (Redis-cached) with fallback
    try:
        enforcer = await asyncio.wait_for(get_quota_enforcer(), timeout=10)
        plan_tier = await asyncio.wait_for(enforcer.get_plan(user_id), timeout=5)
        usage = await asyncio.wait_for(enforcer.get_usage(user_id), timeout=5)
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

    # Populate document count and storage from blob storage
    documents_count = 0
    storage_used_gb = 0.0
    blob_mgr = getattr(request.app.state, "user_blob_manager", None)
    if blob_mgr:
        try:
            documents_count = await blob_mgr.count_blobs(group_id)
            storage_bytes = await blob_mgr.get_storage_used_bytes(group_id)
            storage_used_gb = round(storage_bytes / (1024 ** 3), 4)
        except Exception:
            logger.warning("blob_count_failed", group_id=group_id)

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
        documents_count=documents_count,
        storage_used_gb=storage_used_gb,
        features=features,
    )


@router.get("/me/usage", response_model=UsageStatsResponse)
async def get_my_usage(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    group_id: str = Depends(get_group_id),
):
    """
    Get detailed usage statistics for the current user.
    """
    try:
        async with asyncio.timeout(15):
            return await _fetch_user_usage(user, request, group_id)
    except TimeoutError:
        logger.warning("dashboard_usage_timeout", user_id=user.get("oid", ""))
        raise HTTPException(status_code=504, detail="Usage data fetch timed out")


async def _fetch_user_usage(
    user: Dict[str, Any],
    request: Request,
    group_id: str,
) -> UsageStatsResponse:
    user_id = user.get("oid", "")

    # Get plan and usage from quota enforcer
    try:
        enforcer = await asyncio.wait_for(get_quota_enforcer(), timeout=10)
        plan_tier = await asyncio.wait_for(enforcer.get_plan(user_id), timeout=5)
        usage = await asyncio.wait_for(enforcer.get_usage(user_id), timeout=5)
    except Exception:
        plan_tier = PlanTier.FREE
        usage = {"queries_today": 0, "queries_this_month": 0}

    is_admin = any(r.lower() == "admin" for r in user.get("roles", []))
    if is_admin and plan_tier == PlanTier.FREE:
        plan_tier = PlanTier.ENTERPRISE

    limits = PLAN_DEFINITIONS[plan_tier]

    # Fetch document count from blob storage (primary source)
    documents_count = 0
    storage_used_gb = 0.0
    blob_mgr = getattr(request.app.state, "user_blob_manager", None)
    if blob_mgr:
        try:
            documents_count = await blob_mgr.count_blobs(group_id)
            storage_bytes = await blob_mgr.get_storage_used_bytes(group_id)
            storage_used_gb = round(storage_bytes / (1024 ** 3), 4)
        except Exception:
            logger.warning("usage_blob_count_failed", group_id=group_id)

    recent_queries: List[Dict[str, Any]] = []

    try:
        cosmos = get_cosmos_client()
        records = await cosmos.query_usage(
            partition_id=user_id,
            usage_type="llm_completion",
        )
        # Most recent 20 queries
        sorted_records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:20]
        recent_queries = [
            {
                "query_id": r.get("query_id", ""),
                "timestamp": r.get("timestamp", ""),
                "model": r.get("model", ""),
                "route": r.get("route", ""),
                "total_tokens": r.get("total_tokens", 0),
                "credits_used": r.get("credits_used", 0),
            }
            for r in sorted_records
        ]
        # If blob count unavailable, fall back to Cosmos doc_intel records
        if documents_count == 0:
            doc_records = await cosmos.query_usage(
                partition_id=user_id,
                usage_type="doc_intel",
            )
            doc_ids = {r.get("document_id") for r in doc_records if r.get("document_id")}
            documents_count = len(doc_ids)
            total_pages = sum(r.get("pages_analyzed", 0) for r in doc_records)
            storage_used_gb = round(total_pages * 0.0001, 4)
    except Exception:
        logger.warning("dashboard_usage_fetch_failed", user_id=user_id)

    # Read credit balance from Redis
    credits_used_month = 0
    credits_limit_month: Optional[int] = None
    credits_remaining: Optional[int] = None
    try:
        credit_info = await enforcer.check_credit_limits(user_id)
        credits_used_month = credit_info.get("credits_used", 0)
        credits_limit_month = credit_info.get("credits_limit")
        credits_remaining = credit_info.get("credits_remaining")
    except Exception:
        logger.warning("dashboard_credit_fetch_failed", user_id=user_id)

    return UsageStatsResponse(
        queries_today=usage["queries_today"],
        queries_this_month=usage["queries_this_month"],
        queries_limit_day=limits.queries_per_day,
        queries_limit_month=limits.queries_per_month,
        documents_count=documents_count,
        documents_limit=limits.max_documents,
        storage_used_gb=storage_used_gb,
        storage_limit_gb=limits.max_storage_gb,
        credits_used_month=credits_used_month,
        credits_limit_month=credits_limit_month,
        credits_remaining=credits_remaining,
        recent_queries=recent_queries,
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
        enforcer = await asyncio.wait_for(get_quota_enforcer(), timeout=10)
        current_plan = await asyncio.wait_for(enforcer.get_plan(user_id), timeout=5)
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
            "monthly_credits": limits.monthly_credits,
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
    Aggregates data from Cosmos DB usage records.
    """
    from src.core.algorithm_registry import (
        ALGORITHM_VERSIONS,
        get_default_version,
    )
    from collections import Counter

    cosmos = get_cosmos_client()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    # Fetch recent usage records (best-effort)
    total_users = 0
    active_today = 0
    active_month = 0
    queries_today = 0
    queries_month = 0
    total_documents = 0
    total_storage_gb = 0.0
    plan_dist: Dict[str, int] = {"free": 0, "starter": 0, "professional": 0, "enterprise": 0}
    queries_per_hour: List[Dict[str, Any]] = []
    top_users_list: List[Dict[str, Any]] = []
    error_rate = 0.0

    try:
        month_records = await cosmos.query_usage_cross_partition(
            start_time=month_start,
            usage_type="llm_completion",
        )

        user_queries_today: Counter = Counter()
        user_queries_month: Counter = Counter()
        hour_counts: Counter = Counter()

        for r in month_records:
            uid = r.get("user_id") or r.get("partition_id", "")
            ts = r.get("timestamp", "")
            user_queries_month[uid] += 1
            if ts >= today_start:
                user_queries_today[uid] += 1
                # Extract hour for queries_per_hour
                try:
                    hour_counts[ts[:13]] += 1  # "2026-02-25T10"
                except Exception:
                    pass

        all_users = set(user_queries_month.keys())
        total_users = len(all_users)
        active_month = len(user_queries_month)
        active_today = len(user_queries_today)
        queries_month = sum(user_queries_month.values())
        queries_today = sum(user_queries_today.values())

        # Top users (top 10 by query count this month)
        for uid, count in user_queries_month.most_common(10):
            top_users_list.append({
                "user_id": uid,
                "name": uid[:20],
                "queries": count,
                "plan": "enterprise",
                "last_active": "",
            })

        # Queries per hour (last 24 hours)
        for hour_key in sorted(hour_counts.keys())[-24:]:
            queries_per_hour.append({"hour": hour_key, "count": hour_counts[hour_key]})

        # Plan distribution from quota enforcer
        try:
            enforcer = await get_quota_enforcer()
            for uid in list(all_users)[:200]:
                plan = await enforcer.get_plan(uid)
                plan_dist[plan.value] = plan_dist.get(plan.value, 0) + 1
        except Exception:
            plan_dist["enterprise"] = total_users

        # Document count from doc_intel records
        try:
            doc_records = await cosmos.query_usage_cross_partition(
                usage_type="doc_intel",
            )
            doc_ids = {r.get("document_id") for r in doc_records if r.get("document_id")}
            total_documents = len(doc_ids)
            total_pages = sum(r.get("pages_analyzed", 0) for r in doc_records)
            total_storage_gb = round(total_pages * 0.0001, 4)
        except Exception:
            pass

    except Exception as e:
        logger.warning("admin_metrics_fetch_failed", error=str(e))

    return SystemMetricsResponse(
        total_users=total_users,
        active_users_today=active_today,
        active_users_month=active_month,
        total_queries_today=queries_today,
        total_queries_month=queries_month,
        total_documents=total_documents,
        total_storage_gb=total_storage_gb,
        plan_distribution=plan_dist,
        algorithm_version=get_default_version(),
        enabled_versions=[
            v for v, algo in ALGORITHM_VERSIONS.items()
            if algo.is_enabled()
        ],
        system_status="healthy",
        queries_per_hour=queries_per_hour,
        top_users=top_users_list,
        error_rate=error_rate,
    )


@router.get("/admin/users")
async def list_users(
    _: bool = Depends(verify_admin),
    limit: int = 50,
    offset: int = 0,
):
    """
    List users with their activity, aggregated from Cosmos DB usage records.
    """
    from collections import Counter

    cosmos = get_cosmos_client()

    try:
        records = await cosmos.query_usage_cross_partition(
            usage_type="llm_completion",
        )

        user_data: Dict[str, Dict[str, Any]] = {}
        for r in records:
            uid = r.get("user_id") or r.get("partition_id", "")
            if uid not in user_data:
                user_data[uid] = {
                    "user_id": uid,
                    "display_name": uid[:30],
                    "queries": 0,
                    "last_active": "",
                    "total_tokens": 0,
                }
            user_data[uid]["queries"] += 1
            user_data[uid]["total_tokens"] += r.get("total_tokens", 0)
            ts = r.get("timestamp", "")
            if ts > user_data[uid]["last_active"]:
                user_data[uid]["last_active"] = ts

        # Sort by query count descending
        sorted_users = sorted(user_data.values(), key=lambda u: u["queries"], reverse=True)
        total = len(sorted_users)
        page = sorted_users[offset : offset + limit]

        return {
            "users": page,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.warning("admin_users_fetch_failed", error=str(e))
        return {
            "users": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }
