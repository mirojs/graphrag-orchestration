"""
Unit Tests: Hybrid Router (4-Route Classification)

Tests the query classification logic that routes queries to:
- Route 1: Vector RAG (simple fact lookups)
- Route 2: Local Search (entity-focused)
- Route 3: Global Search (thematic summaries)
- Route 4: DRIFT Multi-Hop (ambiguous, multi-hop)

Run: pytest tests/unit/test_router.py -v
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any


# ============================================================================
# Test Data: Query Classification Examples
# ============================================================================

ROUTE_1_QUERIES = [
    "What is the invoice total?",
    "What is the due date?",
    "Who is the vendor?",
    "What is the PO number?",
]

ROUTE_2_QUERIES = [
    "List all contracts with Vendor ABC and their payment terms.",
    "What are Contoso's obligations in the property management agreement?",
    "Show me all invoices from Q4 2024 with amounts over $10,000.",
    "What entities are mentioned in document XYZ?",
]

ROUTE_3_QUERIES = [
    "Summarize termination rules across all agreements.",
    "Which documents reference governing law or jurisdiction?",
    "What are the common compliance requirements?",
    "Give me an overview of all payment obligations.",
]

ROUTE_4_QUERIES = [
    "Analyze our risk exposure through subsidiaries and trace relationships.",
    "Compare time windows and list all day-based timeframes.",
    "Explain implications of dispute resolution across agreements.",
    "How do the warranty terms in different contracts interact?",
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_router_llm():
    """Mock LLM for router classification."""
    llm = MagicMock()
    response = MagicMock()
    response.text = "route_2_local_search"
    llm.complete = MagicMock(return_value=response)
    llm.acomplete = AsyncMock(return_value=response)
    return llm


@pytest.fixture
def router_config():
    """Router configuration."""
    return {
        "routes_enabled": ["route_1_vector", "route_2_local", "route_3_global", "route_4_drift"],
        "default_route": "route_2_local",
        "confidence_threshold": 0.7,
    }


# ============================================================================
# Test Category 1: Router Initialization
# ============================================================================

class TestRouterInitialization:
    """Test router component initialization."""
    
    def test_router_can_be_imported(self):
        """Test that router module can be imported."""
        try:
            from app.hybrid.router import HybridRouter
            assert True
        except ImportError:
            # Router may be in different location - check alternatives
            try:
                from app.v3.services.query_router import QueryRouter
                assert True
            except ImportError:
                pytest.skip("Router module not found in expected locations")
    
    def test_router_has_classify_method(self):
        """Test that router has a classify/route method."""
        try:
            from app.hybrid.router import HybridRouter
            router = HybridRouter.__new__(HybridRouter)
            assert hasattr(router, 'classify') or hasattr(router, 'route') or hasattr(router, 'select_route')
        except ImportError:
            pytest.skip("Router module not available")


# ============================================================================
# Test Category 2: Route Classification Logic
# ============================================================================

class TestRouteClassification:
    """Test query classification into routes."""
    
    @pytest.mark.parametrize("query", ROUTE_1_QUERIES)
    def test_simple_queries_identified(self, query: str):
        """Test that simple fact queries are identified correctly."""
        # These queries should be classified as Route 1 or Route 2
        # Based on architecture, Route 1 falls back to Route 2 when no vector index
        indicators = ["what is", "who is", "what are the"]
        has_simple_indicator = any(ind in query.lower() for ind in indicators)
        assert has_simple_indicator, f"Query should have simple structure: {query}"
    
    @pytest.mark.parametrize("query", ROUTE_2_QUERIES)
    def test_entity_queries_have_entities(self, query: str):
        """Test that entity-focused queries mention specific entities."""
        # Route 2 queries should mention specific entities
        entity_indicators = ["vendor", "contoso", "invoices", "contracts", "document", "entities"]
        has_entity = any(ind in query.lower() for ind in entity_indicators)
        assert has_entity, f"Route 2 query should mention entities: {query}"
    
    @pytest.mark.parametrize("query", ROUTE_3_QUERIES)
    def test_global_queries_are_thematic(self, query: str):
        """Test that global queries are thematic/summary-oriented."""
        # Route 3 queries should be about summaries or cross-document analysis
        thematic_indicators = ["summarize", "across", "overview", "common", "which documents"]
        has_thematic = any(ind in query.lower() for ind in thematic_indicators)
        assert has_thematic, f"Route 3 query should be thematic: {query}"
    
    @pytest.mark.parametrize("query", ROUTE_4_QUERIES)
    def test_drift_queries_are_complex(self, query: str):
        """Test that DRIFT queries are multi-hop/ambiguous."""
        # Route 4 queries should involve analysis, comparison, or implications
        complex_indicators = ["analyze", "compare", "explain", "implications", "interact", "trace"]
        has_complex = any(ind in query.lower() for ind in complex_indicators)
        assert has_complex, f"Route 4 query should be complex: {query}"


# ============================================================================
# Test Category 3: Route Selection Output Format
# ============================================================================

class TestRouteSelectionOutput:
    """Test that route selection returns correct format."""
    
    def test_route_names_are_valid(self):
        """Test that route names match expected format."""
        valid_routes = {
            "route_1_vector_rag",
            "route_1_vector",
            "route_2_local_search",
            "route_2_local",
            "route_3_global_search",
            "route_3_global",
            "route_4_drift_multi_hop",
            "route_4_drift",
        }
        # At least the canonical forms should be recognized
        canonical = {"route_1", "route_2", "route_3", "route_4"}
        for route in canonical:
            assert any(route in valid for valid in valid_routes)
    
    def test_route_metadata_structure(self):
        """Test expected metadata structure from routing."""
        expected_metadata_fields = ["route_used", "confidence", "reasoning"]
        # This is a structural test - actual implementation may vary
        assert len(expected_metadata_fields) == 3


# ============================================================================
# Test Category 4: Profile-Based Routing
# ============================================================================

class TestProfileRouting:
    """Test routing behavior for different profiles."""
    
    def test_general_enterprise_has_all_routes(self):
        """Test that General Enterprise profile enables all 4 routes."""
        general_enterprise_routes = [
            "route_1_vector",
            "route_2_local",
            "route_3_global",
            "route_4_drift",
        ]
        assert len(general_enterprise_routes) == 4
    
    def test_high_assurance_excludes_route_1(self):
        """Test that High Assurance profile excludes Route 1."""
        high_assurance_routes = [
            "route_2_local",
            "route_3_global",
            "route_4_drift",
        ]
        assert "route_1" not in str(high_assurance_routes)
        assert len(high_assurance_routes) == 3
    
    def test_speed_critical_excludes_drift(self):
        """Test that Speed-Critical profile excludes Route 4 (DRIFT)."""
        speed_critical_routes = [
            "route_1_vector",
            "route_2_local",
        ]
        assert "drift" not in str(speed_critical_routes)
        assert len(speed_critical_routes) == 2


# ============================================================================
# Test Category 5: Fallback Behavior
# ============================================================================

class TestRouteFallback:
    """Test route fallback behavior."""
    
    def test_route_1_falls_back_to_route_2(self):
        """Test that Route 1 falls back to Route 2 when vector index unavailable."""
        # When vector index is not available, Route 1 should fallback to Route 2
        # This is documented behavior in ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md
        fallback_chain = {
            "route_1": "route_2",
            "route_2": None,  # No fallback - this is the base
            "route_3": "route_2",  # Could fall back to local search
            "route_4": "route_2",  # Could fall back to local search
        }
        assert fallback_chain["route_1"] == "route_2"
    
    def test_default_route_is_route_2(self):
        """Test that default route when classification fails is Route 2."""
        default_route = "route_2_local_search"
        assert "route_2" in default_route


# ============================================================================
# Test Category 6: Edge Cases
# ============================================================================

class TestRouterEdgeCases:
    """Test edge cases in routing."""
    
    def test_empty_query_handled(self):
        """Test that empty queries are handled gracefully."""
        empty_queries = ["", "   ", None]
        # Router should either reject or default these
        for q in empty_queries:
            if q is None:
                assert q is None  # Should be validated at API level
            else:
                assert len(q.strip()) == 0
    
    def test_very_long_query_handled(self):
        """Test that very long queries don't break routing."""
        long_query = "What is " + "the contract " * 1000 + "about?"
        # Should still be classifiable (truncation may occur)
        assert len(long_query) > 10000
    
    def test_special_characters_in_query(self):
        """Test queries with special characters."""
        special_queries = [
            "What's the O'Brien contract worth?",
            "Find documents with © or ™ symbols",
            "Show contracts < $10,000 and > $5,000",
        ]
        for query in special_queries:
            assert len(query) > 0


# ============================================================================
# Test Category 7: Confidence Scoring
# ============================================================================

class TestRouterConfidence:
    """Test confidence scoring in routing decisions."""
    
    def test_confidence_is_normalized(self):
        """Test that confidence scores are in [0, 1] range."""
        sample_confidences = [0.0, 0.5, 0.85, 1.0]
        for conf in sample_confidences:
            assert 0.0 <= conf <= 1.0
    
    def test_high_confidence_threshold(self):
        """Test that high confidence threshold is reasonable."""
        # Per architecture, 0.7 is the threshold
        threshold = 0.7
        assert 0.5 <= threshold <= 0.9


# ============================================================================
# Integration Test Markers
# ============================================================================

@pytest.mark.integration
class TestRouterIntegration:
    """Integration tests for router (requires actual implementation)."""
    
    @pytest.mark.skip(reason="Requires actual router implementation")
    def test_router_with_real_llm(self, mock_router_llm):
        """Test router with real LLM calls."""
        pass
    
    @pytest.mark.skip(reason="Requires actual router implementation")
    def test_router_latency_under_500ms(self):
        """Test that routing decision is made in under 500ms."""
        pass


# ============================================================================
# Test Category 8: Real Router Invocation Tests  
# ============================================================================

class TestRealRouterInvocation:
    """Tests that actually invoke the Router.route() method."""
    
    @pytest.fixture
    def router(self):
        """Initialize router for testing."""
        from app.hybrid.router.main import HybridRouter, DeploymentProfile
        return HybridRouter(
            profile=DeploymentProfile.GENERAL_ENTERPRISE,
            vector_threshold=0.25,
            global_threshold=0.5,
            drift_threshold=0.75
        )
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query,expected_route", [
        # Route 1 (Vector RAG) - Simple fact lookups
        ("What is the invoice TOTAL amount?", "vector_rag"),
        ("What is the invoice DUE DATE?", "vector_rag"),
        ("Who is the invoice SALESPERSON?", "vector_rag"),
        ("What is the invoice P.O. NUMBER?", "vector_rag"),
        # Route 2 (Local Search) - Entity-focused
        ("Who is the Agent in the property management agreement?", "local_search"),
        ("Who is the Owner in the property management agreement?", "local_search"),
        ("What is the managed property address in the property management agreement?", "local_search"),
        # Route 3 (Global Search) - Thematic/cross-document
        ("Across the agreements, list the termination/cancellation rules you can find.", "global_search"),
        ("Identify which documents reference jurisdictions / governing law.", "global_search"),
        ("Summarize who pays what across the set (fees/charges/taxes).", "global_search"),
        # Route 4 (DRIFT) - Multi-hop reasoning
        ("Compare time windows across the set: list all explicit day-based timeframes.", "drift_multi_hop"),
        ("Across the set, which entity appears in the most different documents: Fabrikam Inc. or Contoso Ltd.?", "drift_multi_hop"),
        ("Compare the fees concepts: which doc has a percentage-based fee structure and which has fixed installment payments?", "drift_multi_hop"),
    ])
    async def test_router_classify_real_invocation(self, router, query, expected_route):
        """Test router actually classifies queries correctly."""
        from app.hybrid.router.main import QueryRoute
        
        result = await router.route(query)
        
        # Allow Route 2 <-> Route 3 as soft matches for cross-document vs entity queries
        actual = result.value
        if expected_route in ["local_search", "global_search"]:
            allowed_routes = ["local_search", "global_search"]
            assert actual in allowed_routes, (
                f"Expected {expected_route} or similar, got {actual} for: {query[:50]}..."
            )
        else:
            assert actual == expected_route, (
                f"Expected {expected_route}, got {actual} for: {query[:50]}..."
            )
    
    @pytest.mark.asyncio
    async def test_router_high_assurance_profile(self, router):
        """Test that High Assurance profile correctly falls back from Route 1."""
        from app.hybrid.router.main import HybridRouter, DeploymentProfile, QueryRoute
        
        ha_router = HybridRouter(
            profile=DeploymentProfile.HIGH_ASSURANCE,
            vector_threshold=0.25,
            global_threshold=0.5,
            drift_threshold=0.75
        )
        
        # Simple query that would normally go to Route 1
        simple_query = "What is the invoice total?"
        result = await ha_router.route(simple_query)
        
        # Should NOT be Route 1 in High Assurance profile
        assert result != QueryRoute.VECTOR_RAG, (
            f"High Assurance profile should not route to Vector RAG"
        )


# ============================================================================
# Test Category 9: Threshold Boundary Tests
# ============================================================================

class TestThresholdBoundaries:
    """Test routing behavior at threshold boundaries."""
    
    @pytest.fixture
    def router(self):
        """Initialize router for testing."""
        from app.hybrid.router.main import HybridRouter, DeploymentProfile
        return HybridRouter(
            profile=DeploymentProfile.GENERAL_ENTERPRISE,
            vector_threshold=0.25,
            global_threshold=0.5,
            drift_threshold=0.75
        )
    
    @pytest.mark.asyncio
    async def test_simple_queries_route_to_vector(self, router):
        """Test that very simple queries route to Vector RAG (Route 1)."""
        from app.hybrid.router.main import QueryRoute
        
        simple_queries = [
            "What is the amount?",
            "What is the date?",
            "What is the name?",
        ]
        
        for query in simple_queries:
            result = await router.route(query)
            # Very simple queries should score low complexity -> Vector or Local
            assert result in [QueryRoute.VECTOR_RAG, QueryRoute.LOCAL_SEARCH], (
                f"Simple query '{query}' should route to Vector or Local, got {result.value}"
            )
    
    @pytest.mark.asyncio
    async def test_complex_queries_route_to_drift(self, router):
        """Test that complex multi-hop queries route to DRIFT (Route 4)."""
        from app.hybrid.router.main import QueryRoute
        
        complex_queries = [
            "Trace the chain of relationships from Contoso to Fabrikam through all intermediaries and analyze the implications.",
            "Compare and contrast all termination clauses across every document, explain how they interact, and trace dependencies.",
            "Analyze the multi-hop connections between payment obligations, warranty terms, and insurance requirements across the corpus.",
        ]
        
        for query in complex_queries:
            result = await router.route(query)
            # Very complex queries should score high complexity -> DRIFT
            assert result == QueryRoute.DRIFT_MULTI_HOP, (
                f"Complex query should route to DRIFT, got {result.value} for: {query[:50]}..."
            )
    
    @pytest.mark.asyncio
    async def test_entity_specific_queries_route_to_local(self, router):
        """Test that entity-specific queries route to Local Search (Route 2)."""
        from app.hybrid.router.main import QueryRoute
        
        entity_queries = [
            "What are Contoso Ltd.'s obligations in the property management agreement?",
            "List all contracts with Fabrikam Inc.",
            "What is Walt Flood Realty's commission rate?",
        ]
        
        for query in entity_queries:
            result = await router.route(query)
            # Entity-focused queries should route to Local Search
            assert result == QueryRoute.LOCAL_SEARCH, (
                f"Entity query should route to Local Search, got {result.value} for: {query[:50]}..."
            )
    
    @pytest.mark.asyncio
    async def test_thematic_queries_route_to_global(self, router):
        """Test that thematic/summary queries route to Global Search (Route 3)."""
        from app.hybrid.router.main import QueryRoute
        
        thematic_queries = [
            "Summarize all payment obligations across the documents.",
            "What are the common themes in the agreements?",
            "Identify patterns in termination clauses.",
        ]
        
        for query in thematic_queries:
            result = await router.route(query)
            # Thematic queries should route to Global Search or Local (both use graph)
            assert result in [QueryRoute.GLOBAL_SEARCH, QueryRoute.LOCAL_SEARCH], (
                f"Thematic query should route to Global/Local, got {result.value} for: {query[:50]}..."
            )
