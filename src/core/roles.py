"""
Role and Plan definitions for RBAC and billing.

Entra ID App Roles:
    Configure these in Azure Portal > App Registrations > App Roles:
    - "Admin"  → Full platform management, user analytics, system config
    - "User"   → Standard chat, file upload, personal dashboard

Payment Plans (B2C and B2B):
    Plans are stored per-user/per-tenant and control feature gates.
    The plan is resolved at login time and cached on the user profile.

Usage:
    from src.core.roles import AppRole, PlanTier, PlanLimits, PLAN_DEFINITIONS
"""

from enum import Enum
from typing import Dict, Optional
from pydantic import BaseModel, Field


# ============================================================================
# App Roles (must match Entra ID App Registration > App Roles)
# ============================================================================

class AppRole(str, Enum):
    """Application roles configured in Entra ID app registration."""
    ADMIN = "Admin"
    USER = "User"


# ============================================================================
# Payment Plans
# ============================================================================

class PlanTier(str, Enum):
    """Payment plan tiers for both B2C and B2B customers."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class PlanLimits(BaseModel):
    """Resource limits for a payment plan."""
    # Chat limits
    queries_per_day: int = Field(description="Max chat queries per day")
    queries_per_month: int = Field(description="Max chat queries per month")
    max_tokens_per_query: int = Field(default=4096, description="Max output tokens per query")
    
    # Document limits
    max_documents: int = Field(description="Max documents in knowledge base")
    max_document_size_mb: int = Field(default=10, description="Max single document size in MB")
    max_storage_gb: float = Field(default=1.0, description="Max total storage in GB")
    
    # Feature gates
    graphrag_enabled: bool = Field(default=False, description="Access to GraphRAG routes")
    advanced_analytics: bool = Field(default=False, description="Access to usage analytics dashboard")
    custom_models: bool = Field(default=False, description="Ability to select AI models")
    api_access: bool = Field(default=False, description="Programmatic API access")
    priority_support: bool = Field(default=False, description="Priority support queue")
    
    # B2B specific
    max_users: Optional[int] = Field(default=None, description="Max users per tenant (B2B only)")
    sso_enabled: bool = Field(default=False, description="SSO integration (B2B only)")
    custom_branding: bool = Field(default=False, description="Custom branding (B2B only)")
    dedicated_resources: bool = Field(default=False, description="Dedicated compute (B2B only)")


# Plan definitions — these will eventually move to a database/config service
PLAN_DEFINITIONS: Dict[PlanTier, PlanLimits] = {
    PlanTier.FREE: PlanLimits(
        queries_per_day=20,
        queries_per_month=200,
        max_tokens_per_query=2048,
        max_documents=10,
        max_document_size_mb=5,
        max_storage_gb=0.5,
        graphrag_enabled=False,
        advanced_analytics=False,
        custom_models=False,
        api_access=False,
        priority_support=False,
    ),
    PlanTier.STARTER: PlanLimits(
        queries_per_day=100,
        queries_per_month=2000,
        max_tokens_per_query=4096,
        max_documents=50,
        max_document_size_mb=10,
        max_storage_gb=2.0,
        graphrag_enabled=True,
        advanced_analytics=False,
        custom_models=False,
        api_access=False,
        priority_support=False,
    ),
    PlanTier.PROFESSIONAL: PlanLimits(
        queries_per_day=500,
        queries_per_month=10000,
        max_tokens_per_query=8192,
        max_documents=500,
        max_document_size_mb=50,
        max_storage_gb=20.0,
        graphrag_enabled=True,
        advanced_analytics=True,
        custom_models=True,
        api_access=True,
        priority_support=False,
        max_users=10,
        sso_enabled=False,
    ),
    PlanTier.ENTERPRISE: PlanLimits(
        queries_per_day=999999,
        queries_per_month=999999,
        max_tokens_per_query=16384,
        max_documents=999999,
        max_document_size_mb=200,
        max_storage_gb=500.0,
        graphrag_enabled=True,
        advanced_analytics=True,
        custom_models=True,
        api_access=True,
        priority_support=True,
        max_users=None,  # Unlimited
        sso_enabled=True,
        custom_branding=True,
        dedicated_resources=True,
    ),
}


# ============================================================================
# User Profile Model
# ============================================================================

class UserProfile(BaseModel):
    """User profile with role and plan information."""
    # Identity (from Entra ID token)
    user_id: str = Field(description="Entra ID object ID (oid)")
    display_name: Optional[str] = Field(default=None, description="Display name")
    email: Optional[str] = Field(default=None, description="Email / UPN")
    tenant_id: Optional[str] = Field(default=None, description="Entra tenant ID")
    
    # Authorization
    roles: list[str] = Field(default_factory=list, description="App roles from Entra ID")
    groups: list[str] = Field(default_factory=list, description="Group memberships")
    is_admin: bool = Field(default=False, description="Convenience flag: has Admin role")
    
    # Payment plan
    plan: PlanTier = Field(default=PlanTier.FREE, description="Current payment plan")
    plan_limits: Optional[PlanLimits] = Field(default=None, description="Resolved plan limits")
    billing_type: str = Field(default="b2c", description="'b2c' (individual) or 'b2b' (organization)")
    
    # Usage (populated on request)
    queries_today: int = Field(default=0, description="Queries used today")
    queries_this_month: int = Field(default=0, description="Queries used this month")
    documents_count: int = Field(default=0, description="Documents in knowledge base")
    storage_used_gb: float = Field(default=0.0, description="Storage used in GB")


def resolve_user_profile(
    user_info: Dict,
    plan_tier: Optional[PlanTier] = None,
    billing_type: str = "b2c",
) -> UserProfile:
    """
    Build a UserProfile from JWT claims and plan data.
    
    In production, plan_tier would be looked up from a billing database
    keyed by user_id (B2C) or tenant_id (B2B).
    """
    roles = user_info.get("roles", [])
    is_admin = any(r.lower() == "admin" for r in roles)
    
    tier = plan_tier or PlanTier.FREE
    limits = PLAN_DEFINITIONS.get(tier)
    
    return UserProfile(
        user_id=user_info.get("oid", ""),
        display_name=user_info.get("name"),
        email=user_info.get("preferred_username") or user_info.get("email"),
        tenant_id=user_info.get("tid"),
        roles=roles,
        groups=user_info.get("groups", []),
        is_admin=is_admin,
        plan=tier,
        plan_limits=limits,
        billing_type=billing_type,
    )
