"""
Algorithm Version Registry

Centralized registry for all algorithm versions with metadata.
Supports feature flags, version switching, and canary deployments.

Usage:
    from src.core.algorithm_registry import get_algorithm, get_default_version
    
    version = get_default_version()  # "v2"
    algo = get_algorithm(version)
    handler = algo.get_handler()
"""

from typing import Dict, Optional, Any, Literal
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import structlog

from src.core.config import settings

logger = structlog.get_logger(__name__)


class AlgorithmStatus(str, Enum):
    """Algorithm version lifecycle status."""
    PREVIEW = "preview"      # Beta testing, may change
    STABLE = "stable"        # Production ready, current
    DEPRECATED = "deprecated"  # Still works, sunset planned
    SUNSET = "sunset"        # Disabled, no longer available


@dataclass
class AlgorithmVersion:
    """Metadata for an algorithm version."""
    version: str
    status: AlgorithmStatus
    embedding_model: str
    embedding_dim: int
    routes: list = field(default_factory=lambda: [2, 3, 4])
    handler_module: str = ""
    handler_class: str = ""
    release_date: Optional[date] = None
    sunset_date: Optional[date] = None
    feature_flag: Optional[str] = None
    description: str = ""
    
    def is_enabled(self) -> bool:
        """Check if this version is enabled via feature flag or config."""
        if self.status == AlgorithmStatus.SUNSET:
            return False
        
        if self.feature_flag:
            # Check environment variable
            return getattr(settings, self.feature_flag, False)
        
        # Version-specific checks
        if self.version == "v1":
            return getattr(settings, "ALGORITHM_V1_ENABLED", True)
        elif self.version == "v2":
            return getattr(settings, "VOYAGE_V2_ENABLED", False) or getattr(settings, "ALGORITHM_V2_ENABLED", True)
        elif self.version == "v3":
            return getattr(settings, "ALGORITHM_V3_PREVIEW_ENABLED", False)
        
        return True
    
    def get_handler(self):
        """Dynamically import and return the handler class."""
        import importlib
        module = importlib.import_module(self.handler_module)
        return getattr(module, self.handler_class)


# ============================================================================
# Algorithm Version Definitions
# ============================================================================

ALGORITHM_VERSIONS: Dict[str, AlgorithmVersion] = {
    "v1": AlgorithmVersion(
        version="v1",
        status=AlgorithmStatus.DEPRECATED,
        embedding_model="text-embedding-3-large",
        embedding_dim=3072,
        routes=[2, 3, 4],
        handler_module="src.worker.hybrid.orchestrator",
        handler_class="HybridPipelineOrchestrator",
        release_date=date(2025, 6, 1),
        sunset_date=date(2026, 6, 1),
        description="OpenAI embeddings (text-embedding-3-large). Deprecated, use V2.",
    ),
    "v2": AlgorithmVersion(
        version="v2",
        status=AlgorithmStatus.STABLE,
        embedding_model="voyage-context-3",
        embedding_dim=2048,
        routes=[2, 3, 4],
        handler_module="src.worker.hybrid_v2.orchestrator",
        handler_class="HybridPipeline",
        release_date=date(2026, 1, 15),
        description="Voyage contextual embeddings with section-aware chunking.",
    ),
    "v3": AlgorithmVersion(
        version="v3",
        status=AlgorithmStatus.PREVIEW,
        embedding_model="voyage-context-3",  # May change
        embedding_dim=2048,
        routes=[2, 3, 4],
        handler_module="src.worker.hybrid_v3.orchestrator",
        handler_class="HybridPipelineV3",
        feature_flag="ALGORITHM_V3_PREVIEW_ENABLED",
        description="Next-generation pipeline (preview).",
    ),
}


# ============================================================================
# Public API
# ============================================================================

def get_algorithm(version: str) -> AlgorithmVersion:
    """
    Get algorithm version by name.
    
    Args:
        version: Version string like "v1", "v2", "v3"
        
    Returns:
        AlgorithmVersion metadata
        
    Raises:
        ValueError: If version not found or disabled
    """
    algo = ALGORITHM_VERSIONS.get(version)
    if not algo:
        raise ValueError(f"Unknown algorithm version: {version}")
    
    if not algo.is_enabled():
        raise ValueError(f"Algorithm version {version} is disabled")
    
    return algo


def get_default_version() -> str:
    """
    Get the default algorithm version.
    
    Respects DEFAULT_ALGORITHM_VERSION env var, falls back to "v2".
    """
    default = getattr(settings, "DEFAULT_ALGORITHM_VERSION", "v2")
    
    # Validate it's enabled
    try:
        algo = get_algorithm(default)
        return algo.version
    except ValueError:
        logger.warning(
            "default_algorithm_disabled",
            default=default,
            fallback="v2",
        )
        return "v2"


def list_versions(include_disabled: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    List all algorithm versions with their status.
    
    Args:
        include_disabled: Include disabled/sunset versions
        
    Returns:
        Dict mapping version to metadata dict
    """
    result = {}
    for version, algo in ALGORITHM_VERSIONS.items():
        if not include_disabled and not algo.is_enabled():
            continue
        
        result[version] = {
            "version": algo.version,
            "status": algo.status.value,
            "enabled": algo.is_enabled(),
            "embedding_model": algo.embedding_model,
            "embedding_dim": algo.embedding_dim,
            "routes": algo.routes,
            "description": algo.description,
            "release_date": algo.release_date.isoformat() if algo.release_date else None,
            "sunset_date": algo.sunset_date.isoformat() if algo.sunset_date else None,
        }
    
    return result


def get_version_for_header(header_value: Optional[str]) -> str:
    """
    Resolve algorithm version from request header.
    
    Supports:
    - Explicit version: "v2", "v3"
    - Date-based: "2026-01-30" → maps to version active on that date
    - None: returns default version
    
    Args:
        header_value: Value from X-Algorithm-Version or X-API-Version header
        
    Returns:
        Resolved version string
    """
    if not header_value:
        return get_default_version()
    
    # Direct version match
    if header_value in ALGORITHM_VERSIONS:
        try:
            return get_algorithm(header_value).version
        except ValueError:
            pass
    
    # Date-based resolution (format: YYYY-MM-DD)
    try:
        request_date = date.fromisoformat(header_value)
        
        # Find latest version released before or on that date
        candidates = [
            algo for algo in ALGORITHM_VERSIONS.values()
            if algo.is_enabled() 
            and algo.release_date 
            and algo.release_date <= request_date
        ]
        
        if candidates:
            # Sort by release date descending, pick latest
            # Note: release_date is guaranteed non-None by filter above
            candidates.sort(key=lambda a: a.release_date or date.min, reverse=True)
            return candidates[0].version
    except ValueError:
        pass
    
    # Fallback to default
    logger.warning(
        "unknown_version_header",
        header_value=header_value,
        fallback=get_default_version(),
    )
    return get_default_version()
