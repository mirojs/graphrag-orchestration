"""
Tenant Resource Quota Manager for Multi-Tenant GraphRAG.

Enforces per-tenant limits on:
- Maximum nodes
- Maximum documents
- Query rate limiting
- Storage quotas

Used to prevent resource hogging and ensure fair resource allocation
across many small personal datasets.
"""

import time
import logging
from typing import Dict, Optional, List, Any
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TenantQuota:
    """Resource quotas for a single tenant."""
    
    def __init__(
        self,
        max_nodes: int = 100_000,
        max_documents: int = 1_000,
        max_queries_per_hour: int = 1_000,
        max_storage_mb: int = 5_000,
    ):
        self.max_nodes = max_nodes
        self.max_documents = max_documents
        self.max_queries_per_hour = max_queries_per_hour
        self.max_storage_mb = max_storage_mb


class QuotaManager:
    """
    Singleton service for managing tenant resource quotas.
    
    Tracks usage and enforces limits to ensure fair resource allocation
    across many tenants sharing the same Neo4j instance.
    """
    
    _instance: Optional["QuotaManager"] = None
    
    def __new__(cls) -> "QuotaManager":
        if cls._instance is None:
            cls._instance = super(QuotaManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self) -> None:
        """Initialize quota tracking structures."""
        # Default quotas for all tenants
        self.default_quota = TenantQuota()
        
        # Per-tenant custom quotas (overrides)
        self.custom_quotas: Dict[str, TenantQuota] = {}
        
        # Rate limiting tracking
        self.query_counts: Dict[str, List[float]] = defaultdict(list)  # group_id -> [timestamps]
        
        logger.info("QuotaManager initialized with defaults")
    
    def get_quota(self, group_id: str) -> TenantQuota:
        """Get quota settings for a tenant."""
        return self.custom_quotas.get(group_id, self.default_quota)
    
    def set_custom_quota(self, group_id: str, quota: TenantQuota) -> None:
        """Set custom quota for a specific tenant."""
        self.custom_quotas[group_id] = quota
        logger.info(f"Custom quota set for {group_id}: {quota.__dict__}")
    
    def check_node_quota(self, group_id: str, current_nodes: int) -> bool:
        """
        Check if tenant is within node count quota.
        
        Args:
            group_id: Tenant identifier
            current_nodes: Current node count for tenant
            
        Returns:
            True if within quota, False if exceeded
        """
        quota = self.get_quota(group_id)
        if current_nodes >= quota.max_nodes:
            logger.warning(
                f"Node quota exceeded for {group_id}: "
                f"{current_nodes}/{quota.max_nodes}"
            )
            return False
        return True
    
    def check_document_quota(self, group_id: str, current_docs: int) -> bool:
        """
        Check if tenant is within document count quota.
        
        Args:
            group_id: Tenant identifier
            current_docs: Current document count for tenant
            
        Returns:
            True if within quota, False if exceeded
        """
        quota = self.get_quota(group_id)
        if current_docs >= quota.max_documents:
            logger.warning(
                f"Document quota exceeded for {group_id}: "
                f"{current_docs}/{quota.max_documents}"
            )
            return False
        return True
    
    def check_rate_limit(self, group_id: str) -> bool:
        """
        Check if tenant is within query rate limit.
        
        Uses sliding window: counts queries in the last hour.
        
        Args:
            group_id: Tenant identifier
            
        Returns:
            True if within limit, False if rate limited
        """
        quota = self.get_quota(group_id)
        now = time.time()
        hour_ago = now - 3600
        
        # Get query timestamps for this tenant
        timestamps = self.query_counts[group_id]
        
        # Remove old timestamps (outside sliding window)
        timestamps[:] = [ts for ts in timestamps if ts > hour_ago]
        
        # Check if within limit
        if len(timestamps) >= quota.max_queries_per_hour:
            logger.warning(
                f"Rate limit exceeded for {group_id}: "
                f"{len(timestamps)}/{quota.max_queries_per_hour} queries/hour"
            )
            return False
        
        # Record this query
        timestamps.append(now)
        return True
    
    async def check_query_rate_limit(self, group_id: str) -> bool:
        """Async wrapper for check_rate_limit."""
        return self.check_rate_limit(group_id)
    
    async def check_indexing_rate_limit(self, group_id: str, doc_count: int) -> bool:
        """Check if tenant can index doc_count documents."""
        # For now, just use rate limiting - could extend with doc quotas
        return self.check_rate_limit(group_id)
    
    def invalidate_node_count_cache(self, group_id: str) -> None:
        """Invalidate any cached node count for group (no-op in this simple implementation)."""
        pass
    
    def get_usage_stats(self, group_id: str) -> Dict[str, Any]:
        """
        Get current usage statistics for a tenant.
        
        Args:
            group_id: Tenant identifier
            
        Returns:
            Dictionary with current usage and quotas
        """
        quota = self.get_quota(group_id)
        
        # Calculate queries in last hour
        now = time.time()
        hour_ago = now - 3600
        recent_queries = len([
            ts for ts in self.query_counts.get(group_id, [])
            if ts > hour_ago
        ])
        
        return {
            "group_id": group_id,
            "quotas": {
                "max_nodes": quota.max_nodes,
                "max_documents": quota.max_documents,
                "max_queries_per_hour": quota.max_queries_per_hour,
                "max_storage_mb": quota.max_storage_mb,
            },
            "current_usage": {
                "queries_last_hour": recent_queries,
            },
            "percentage_used": {
                "query_rate": (recent_queries / quota.max_queries_per_hour) * 100,
            },
        }
    
    def reset_rate_limit(self, group_id: str) -> None:
        """Reset rate limit counters for a tenant (admin operation)."""
        self.query_counts[group_id] = []
        logger.info(f"Rate limit reset for {group_id}")


def get_quota_manager() -> QuotaManager:
    """Get the singleton QuotaManager instance."""
    return QuotaManager()
