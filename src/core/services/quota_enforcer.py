"""
Quota Enforcement Service — Redis-based rate limiting for plan tiers.

Uses Redis atomic INCR on date-partitioned keys for O(1) quota checks.
Designed to be injected as a FastAPI dependency on chat/upload endpoints.

Keys:
    quota:{user_id}:daily:{YYYYMMDD}    → daily query count  (TTL: 48h)
    quota:{user_id}:monthly:{YYYYMM}    → monthly query count (TTL: 35d)
    quota:{user_id}:plan                 → cached PlanTier     (TTL: 1h)

Fail-open: If Redis is unavailable, requests are allowed through
with a warning log — availability beats strict enforcement.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import asyncio
import structlog
from fastapi import Depends, HTTPException, Request
from starlette import status

from src.core.roles import (
    PLAN_DEFINITIONS,
    PlanLimits,
    PlanTier,
)
from src.core.services.redis_service import RedisService, get_redis_service

logger = structlog.get_logger(__name__)

# Key prefixes
_PREFIX = "quota"
_DAILY_TTL = 48 * 3600       # 48 hours — allows reads after midnight rollover
_MONTHLY_TTL = 35 * 86400    # 35 days  — covers full billing month + buffer
_PLAN_CACHE_TTL = 3600       # 1 hour   — re-resolve plan periodically
_CREDIT_TTL = 35 * 86400     # 35 days  — aligned with monthly billing cycle


# =============================================================================
# QuotaEnforcer — core logic
# =============================================================================

class QuotaEnforcer:
    """
    Redis-backed query quota tracker and enforcer.

    All operations are atomic via Redis INCR and use date-partitioned
    keys so counters auto-reset daily/monthly via TTL expiry.
    """

    def __init__(self, redis_service: RedisService):
        self._redis = redis_service._redis  # raw aioredis.Redis

    # ── Key builders ─────────────────────────────────────────────────────

    @staticmethod
    def _daily_key(user_id: str, dt: Optional[datetime] = None) -> str:
        d = dt or datetime.utcnow()
        return f"{_PREFIX}:{user_id}:daily:{d.strftime('%Y%m%d')}"

    @staticmethod
    def _monthly_key(user_id: str, dt: Optional[datetime] = None) -> str:
        d = dt or datetime.utcnow()
        return f"{_PREFIX}:{user_id}:monthly:{d.strftime('%Y%m')}"

    @staticmethod
    def _plan_key(user_id: str) -> str:
        return f"{_PREFIX}:{user_id}:plan"

    @staticmethod
    def _credit_key(user_id: str, dt: Optional[datetime] = None) -> str:
        d = dt or datetime.utcnow()
        return f"{_PREFIX}:{user_id}:credits:{d.strftime('%Y%m')}"

    # ── Plan resolution ──────────────────────────────────────────────────

    async def get_plan(self, user_id: str) -> PlanTier:
        """
        Get user's plan tier from Redis cache.

        Falls back to FREE if not cached yet.
        In production, a billing webhook or login hook calls set_plan().
        """
        try:
            cached = await self._redis.get(self._plan_key(user_id))
            if cached:
                return PlanTier(cached)
        except Exception as e:
            logger.warning("quota_get_plan_failed", user_id=user_id, error=str(e))
        return PlanTier.FREE

    async def set_plan(self, user_id: str, plan: PlanTier) -> None:
        """
        Cache user's plan tier in Redis.

        Called by:
        - Login hook (resolve from billing DB, cache here)
        - Payment webhook (plan upgrade/downgrade)
        - Admin override endpoint
        """
        try:
            await self._redis.set(
                self._plan_key(user_id),
                plan.value,
                ex=_PLAN_CACHE_TTL,
            )
            logger.info("quota_plan_set", user_id=user_id, plan=plan.value)
        except Exception as e:
            logger.warning("quota_set_plan_failed", user_id=user_id, error=str(e))

    # ── Counter operations ───────────────────────────────────────────────

    async def record_query(self, user_id: str) -> Tuple[int, int]:
        """
        Atomically increment daily and monthly counters.

        Returns (daily_count, monthly_count) after increment.
        """
        now = datetime.utcnow()
        dk = self._daily_key(user_id, now)
        mk = self._monthly_key(user_id, now)

        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.incr(dk)
            pipe.expire(dk, _DAILY_TTL)
            pipe.incr(mk)
            pipe.expire(mk, _MONTHLY_TTL)
            results = await pipe.execute()

            daily = int(results[0])
            monthly = int(results[2])

            logger.debug(
                "quota_recorded",
                user_id=user_id,
                daily=daily,
                monthly=monthly,
            )
            return daily, monthly

        except Exception as e:
            logger.warning("quota_record_failed", user_id=user_id, error=str(e))
            return 0, 0  # fail-open

    async def get_usage(self, user_id: str) -> Dict[str, int]:
        """
        Read current usage without incrementing.

        Returns {"queries_today": N, "queries_this_month": M}.
        """
        now = datetime.utcnow()
        dk = self._daily_key(user_id, now)
        mk = self._monthly_key(user_id, now)

        try:
            pipe = self._redis.pipeline(transaction=False)
            pipe.get(dk)
            pipe.get(mk)
            results = await pipe.execute()

            return {
                "queries_today": int(results[0] or 0),
                "queries_this_month": int(results[1] or 0),
            }

        except Exception as e:
            logger.warning("quota_get_usage_failed", user_id=user_id, error=str(e))
            return {"queries_today": 0, "queries_this_month": 0}

    # ── Credit operations ────────────────────────────────────────────────

    async def record_credits(self, user_id: str, credits: int) -> int:
        """
        Atomically add credits consumed to the monthly counter.

        Returns the new total credits used this month.
        """
        now = datetime.utcnow()
        ck = self._credit_key(user_id, now)

        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.incrby(ck, credits)
            pipe.expire(ck, _CREDIT_TTL)
            results = await pipe.execute()
            used = int(results[0])

            logger.debug(
                "credits_recorded",
                user_id=user_id,
                credits_added=credits,
                credits_used_month=used,
            )
            return used

        except Exception as e:
            logger.warning("credit_record_failed", user_id=user_id, error=str(e))
            return 0  # fail-open

    async def get_credit_usage(self, user_id: str) -> int:
        """Read current monthly credit usage without incrementing."""
        now = datetime.utcnow()
        ck = self._credit_key(user_id, now)

        try:
            val = await self._redis.get(ck)
            return int(val or 0)
        except Exception as e:
            logger.warning("credit_get_failed", user_id=user_id, error=str(e))
            return 0

    async def check_credit_limits(self, user_id: str) -> Dict[str, Any]:
        """Check if user is within credit limits."""
        plan = await self.get_plan(user_id)
        limits: PlanLimits = PLAN_DEFINITIONS[plan]
        monthly_limit = limits.monthly_credits
        credits_used = await self.get_credit_usage(user_id)

        if monthly_limit is None:
            # Unlimited credits (Enterprise)
            return {
                "credits_allowed": True,
                "credits_used": credits_used,
                "credits_limit": None,
                "credits_remaining": None,
            }

        remaining = max(0, monthly_limit - credits_used)
        allowed = credits_used < monthly_limit

        return {
            "credits_allowed": allowed,
            "credits_used": credits_used,
            "credits_limit": monthly_limit,
            "credits_remaining": remaining,
        }

    async def check_limits(
        self, user_id: str
    ) -> Dict[str, Any]:
        """
        Check if user is within plan limits WITHOUT consuming a unit.

        Returns a dict with:
            allowed: bool
            plan: str
            daily_used / daily_limit / daily_remaining
            monthly_used / monthly_limit / monthly_remaining
            retry_after_seconds: int (seconds until daily reset, if blocked)
        """
        plan = await self.get_plan(user_id)
        limits: PlanLimits = PLAN_DEFINITIONS[plan]
        usage = await self.get_usage(user_id)

        daily_used = usage["queries_today"]
        monthly_used = usage["queries_this_month"]
        daily_remaining = max(0, limits.queries_per_day - daily_used)
        monthly_remaining = max(0, limits.queries_per_month - monthly_used)

        over_daily = daily_used >= limits.queries_per_day
        over_monthly = monthly_used >= limits.queries_per_month

        # Check credit limits
        credit_info = await self.check_credit_limits(user_id)
        over_credits = not credit_info["credits_allowed"]

        allowed = not over_daily and not over_monthly and not over_credits

        # Calculate seconds until next daily reset (midnight UTC)
        now = datetime.utcnow()
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        retry_after = int((next_midnight - now).total_seconds())

        # Determine blocking reason
        reason = None
        if over_daily:
            reason = f"Daily limit of {limits.queries_per_day} queries reached"
        elif over_monthly:
            reason = f"Monthly limit of {limits.queries_per_month} queries reached"
            # For monthly, retry_after is next month
            next_month_start = (now.replace(day=1) + timedelta(days=32)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            retry_after = int((next_month_start - now).total_seconds())
        elif over_credits:
            reason = f"Monthly credit limit of {credit_info['credits_limit']} credits exhausted"
            next_month_start = (now.replace(day=1) + timedelta(days=32)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            retry_after = int((next_month_start - now).total_seconds())

        return {
            "allowed": allowed,
            "reason": reason,
            "plan": plan.value,
            "daily_used": daily_used,
            "daily_limit": limits.queries_per_day,
            "daily_remaining": daily_remaining,
            "monthly_used": monthly_used,
            "monthly_limit": limits.queries_per_month,
            "monthly_remaining": monthly_remaining,
            "credits_used": credit_info["credits_used"],
            "credits_limit": credit_info["credits_limit"],
            "credits_remaining": credit_info["credits_remaining"],
            "retry_after_seconds": retry_after if not allowed else 0,
        }

    async def check_and_consume(
        self, user_id: str
    ) -> Dict[str, Any]:
        """
        Atomic check-and-increment.

        If the user is within limits, increments counters and returns allowed=True.
        If over limits, does NOT increment and returns allowed=False.

        This is the primary method used by the enforcement dependency.
        """
        plan = await self.get_plan(user_id)
        limits: PlanLimits = PLAN_DEFINITIONS[plan]
        usage = await self.get_usage(user_id)

        daily_used = usage["queries_today"]
        monthly_used = usage["queries_this_month"]

        over_daily = daily_used >= limits.queries_per_day
        over_monthly = monthly_used >= limits.queries_per_month

        # Also check credit limits
        credit_info = await self.check_credit_limits(user_id)
        over_credits = not credit_info["credits_allowed"]

        if over_daily or over_monthly or over_credits:
            # Over limit — don't increment, return limit info
            return await self.check_limits(user_id)

        # Within limits — consume a query unit
        new_daily, new_monthly = await self.record_query(user_id)

        return {
            "allowed": True,
            "reason": None,
            "plan": plan.value,
            "daily_used": new_daily,
            "daily_limit": limits.queries_per_day,
            "daily_remaining": max(0, limits.queries_per_day - new_daily),
            "monthly_used": new_monthly,
            "monthly_limit": limits.queries_per_month,
            "monthly_remaining": max(0, limits.queries_per_month - new_monthly),
            "credits_used": credit_info["credits_used"],
            "credits_limit": credit_info["credits_limit"],
            "credits_remaining": credit_info["credits_remaining"],
            "retry_after_seconds": 0,
        }


# =============================================================================
# Singleton accessor
# =============================================================================

_enforcer: Optional[QuotaEnforcer] = None
_enforcer_lock = asyncio.Lock()


async def get_quota_enforcer() -> QuotaEnforcer:
    """Get or create singleton QuotaEnforcer."""
    global _enforcer
    if _enforcer is not None:
        return _enforcer
    async with _enforcer_lock:
        if _enforcer is None:
            redis_svc = await get_redis_service()
            _enforcer = QuotaEnforcer(redis_svc)
    return _enforcer


# =============================================================================
# FastAPI dependency — drop this into any endpoint
# =============================================================================

async def enforce_plan_limits(
    request: Request,
) -> Dict[str, Any]:
    """
    FastAPI dependency that enforces plan query limits.

    Usage:
        @router.post("/completions")
        async def chat_completions(
            ...,
            quota: dict = Depends(enforce_plan_limits),
        ):
            # quota["plan"], quota["daily_remaining"], etc.

    On success:
        Returns quota info dict (can be used for response headers).

    On failure:
        Raises HTTP 429 with:
        - Retry-After header (seconds until limit resets)
        - X-RateLimit-Limit / X-RateLimit-Remaining headers
        - JSON body with plan info and upgrade suggestion

    Fail-open:
        If Redis is unavailable, returns a permissive dict and logs warning.
    """
    # Extract user_id from auth middleware
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        # Anonymous / unauthenticated — apply free tier limits with IP-based key
        user_id = f"anon:{request.client.host}" if request.client else "anon:unknown"

    try:
        enforcer = await get_quota_enforcer()
        result = await enforcer.check_and_consume(user_id)

        if not result["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "quota_exceeded",
                    "message": result["reason"],
                    "plan": result["plan"],
                    "daily_used": result["daily_used"],
                    "daily_limit": result["daily_limit"],
                    "monthly_used": result["monthly_used"],
                    "monthly_limit": result["monthly_limit"],
                    "credits_used": result.get("credits_used"),
                    "credits_limit": result.get("credits_limit"),
                    "credits_remaining": result.get("credits_remaining"),
                    "retry_after_seconds": result["retry_after_seconds"],
                    "upgrade_url": "/dashboard#plans",
                },
                headers={
                    "Retry-After": str(result["retry_after_seconds"]),
                    "X-RateLimit-Limit-Daily": str(result["daily_limit"]),
                    "X-RateLimit-Remaining-Daily": str(result["daily_remaining"]),
                    "X-RateLimit-Limit-Monthly": str(result["monthly_limit"]),
                    "X-RateLimit-Remaining-Monthly": str(result["monthly_remaining"]),
                },
            )

        # Stash quota info for response header injection
        request.state.quota = result
        return result

    except HTTPException:
        raise  # Re-raise 429
    except Exception as e:
        # Fail-open: Redis down → allow the request
        logger.error("quota_enforcement_failed_open", user_id=user_id, error=str(e))
        fallback = {
            "allowed": True,
            "reason": None,
            "plan": "unknown",
            "daily_used": 0,
            "daily_limit": 0,
            "daily_remaining": 0,
            "monthly_used": 0,
            "monthly_limit": 0,
            "monthly_remaining": 0,
            "credits_used": 0,
            "credits_limit": None,
            "credits_remaining": None,
            "retry_after_seconds": 0,
        }
        request.state.quota = fallback
        return fallback


# =============================================================================
# Response header helper — call after successful response
# =============================================================================

def quota_response_headers(quota: Dict[str, Any]) -> Dict[str, str]:
    """
    Build X-RateLimit-* headers to include in successful responses.

    Usage:
        response = JSONResponse(content=data)
        for k, v in quota_response_headers(quota).items():
            response.headers[k] = v
    """
    headers = {
        "X-RateLimit-Limit-Daily": str(quota.get("daily_limit", "")),
        "X-RateLimit-Remaining-Daily": str(quota.get("daily_remaining", "")),
        "X-RateLimit-Limit-Monthly": str(quota.get("monthly_limit", "")),
        "X-RateLimit-Remaining-Monthly": str(quota.get("monthly_remaining", "")),
        "X-RateLimit-Plan": str(quota.get("plan", "")),
    }
    # Credit headers (only if credit system is active for this plan)
    if quota.get("credits_limit") is not None:
        headers["X-Credits-Limit"] = str(quota.get("credits_limit", ""))
        headers["X-Credits-Remaining"] = str(quota.get("credits_remaining", ""))
        headers["X-Credits-Used"] = str(quota.get("credits_used", ""))
    return headers
