"""
Unit Tests: Route 7 Query Mode Presets (2026-02-26)

Tests the router-adaptive query mode preset system added to Route 7
(HippoRAG 2) based on ANALYSIS_ROUTE7_LATENCY_OPTIMIZATION_2026-02-26.md.

When the orchestrator passes query_mode to Route 7, it selects a preset
that adjusts ppr_passage_top_k, prompt_variant, and max_tokens for the
query type. Without query_mode, Route 7 behaves exactly as before.

Run: pytest tests/unit/test_route7_query_mode.py -v
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict


# ============================================================================
# Helpers
# ============================================================================

def _get_handler_class():
    from src.worker.hybrid_v2.routes.route_7_hipporag2 import HippoRAG2Handler
    return HippoRAG2Handler


# ============================================================================
# Preset Definition Tests
# ============================================================================

class TestQueryModePresets:
    """Tests for QUERY_MODE_PRESETS class attribute."""

    def test_presets_defined(self):
        """QUERY_MODE_PRESETS contains the 4 expected modes."""
        Handler = _get_handler_class()
        assert "local_search" in Handler.QUERY_MODE_PRESETS
        assert "global_search" in Handler.QUERY_MODE_PRESETS
        assert "drift_multi_hop" in Handler.QUERY_MODE_PRESETS
        assert "community_search" in Handler.QUERY_MODE_PRESETS

    def test_local_search_preset_values(self):
        """local_search preset has concise parameters."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS["local_search"]
        assert preset["ppr_passage_top_k"] == 5
        assert preset["prompt_variant"] == "v1_concise"
        assert preset["max_tokens"] == 150

    def test_global_search_preset_values(self):
        """global_search preset has broader parameters."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS["global_search"]
        assert preset["ppr_passage_top_k"] == 15
        assert preset["prompt_variant"] is None

    def test_drift_multi_hop_preset_values(self):
        """drift_multi_hop preset has full-context parameters."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS["drift_multi_hop"]
        assert preset["ppr_passage_top_k"] == 20
        assert preset["prompt_variant"] is None

    def test_community_search_preset_values(self):
        """community_search preset enables community passage seeding."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS["community_search"]
        assert preset["ppr_passage_top_k"] == 50
        assert preset["community_passage_seeds"] is True
        assert preset["prompt_variant"] is None

    def test_unknown_mode_returns_empty_preset(self):
        """Unknown query_mode results in empty preset (env var defaults used)."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS.get("nonexistent_mode", {})
        assert preset == {}

    def test_none_mode_returns_empty_preset(self):
        """None query_mode results in empty preset (backward compatible)."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS.get(None or "", {})
        assert preset == {}


# ============================================================================
# Preset Application Logic Tests
# ============================================================================

class TestPresetApplication:
    """Tests for how presets override env vars in execute()."""

    def test_local_search_overrides_ppr_passage_top_k(self):
        """local_search preset overrides ROUTE7_PPR_PASSAGE_TOP_K env var."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS.get("local_search", {})

        # Simulate the env var override logic from execute()
        ppr_passage_top_k = preset.get("ppr_passage_top_k") or int(
            os.getenv("ROUTE7_PPR_PASSAGE_TOP_K", "20")
        )
        assert ppr_passage_top_k == 5  # Preset wins over default 20

    def test_no_mode_uses_env_var_default(self):
        """Without query_mode, ppr_passage_top_k comes from env var."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS.get("", {})

        ppr_passage_top_k = preset.get("ppr_passage_top_k") or int(
            os.getenv("ROUTE7_PPR_PASSAGE_TOP_K", "20")
        )
        assert ppr_passage_top_k == 20  # Default from env var

    def test_env_var_override_wins_over_default(self):
        """Explicit env var overrides default when no preset."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS.get("", {})

        with patch.dict(os.environ, {"ROUTE7_PPR_PASSAGE_TOP_K": "10"}):
            ppr_passage_top_k = preset.get("ppr_passage_top_k") or int(
                os.getenv("ROUTE7_PPR_PASSAGE_TOP_K", "20")
            )
            assert ppr_passage_top_k == 10

    def test_prompt_variant_override_only_when_caller_didnt_set(self):
        """Preset prompt_variant only applies when caller passes None."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS.get("local_search", {})

        # Caller didn't set prompt_variant → preset applies
        prompt_variant = None
        if prompt_variant is None and preset.get("prompt_variant"):
            prompt_variant = preset["prompt_variant"]
        assert prompt_variant == "v1_concise"

        # Caller explicitly set prompt_variant → preset does NOT override
        prompt_variant = "v0"
        if prompt_variant is None and preset.get("prompt_variant"):
            prompt_variant = preset["prompt_variant"]
        assert prompt_variant == "v0"  # Caller's choice preserved

    def test_global_search_no_prompt_override(self):
        """global_search preset has None prompt_variant → no override."""
        Handler = _get_handler_class()
        preset = Handler.QUERY_MODE_PRESETS.get("global_search", {})

        prompt_variant = None
        if prompt_variant is None and preset.get("prompt_variant"):
            prompt_variant = preset["prompt_variant"]
        assert prompt_variant is None  # No override applied


# ============================================================================
# Backward Compatibility Tests
# ============================================================================

class TestBackwardCompatibility:
    """Ensure Route 7 works identically without query_mode."""

    def test_execute_signature_accepts_query_mode(self):
        """execute() method accepts query_mode as keyword argument."""
        import inspect
        Handler = _get_handler_class()
        sig = inspect.signature(Handler.execute)
        assert "query_mode" in sig.parameters
        assert sig.parameters["query_mode"].default is None

    def test_execute_still_accepts_old_params(self):
        """All pre-existing parameters are still present."""
        import inspect
        Handler = _get_handler_class()
        sig = inspect.signature(Handler.execute)
        expected = ["self", "query", "response_type", "knn_config",
                    "prompt_variant", "synthesis_model", "include_context",
                    "weight_profile", "language", "query_mode", "folder_id",
                    "config_overrides"]
        actual = list(sig.parameters.keys())
        assert actual == expected
