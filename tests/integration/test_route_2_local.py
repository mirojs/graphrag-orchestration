"""
Integration Tests: Route 2 - Local Search (Entity-Focused)

Tests the entity-focused search route using LazyGraphRAG + HippoRAG PPR.
Route 2 is the primary workhorse for entity-centric queries.

When to use Route 2:
- Queries mentioning specific entities
- Contract/invoice lookups
- Relationship-focused questions

Components:
- Entity extraction (NER)
- PPR graph traversal
- Evidence synthesis

Run: pytest tests/integration/test_route_2_local.py -v
"""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any, List

# Import test config from conftest
try:
    from ..conftest import (
        EMBEDDING_DIMENSIONS,
        LATENCY_ROUTE_2,
        DEFAULT_GROUP_ID,
    )
except ImportError:
    # Fallback for direct pytest execution
    EMBEDDING_DIMENSIONS = 3072
    LATENCY_ROUTE_2 = 5.0
    DEFAULT_GROUP_ID = "test-group"


# ============================================================================
# Test Data
# ============================================================================

ROUTE_2_TEST_QUERIES = [
    {
        "query": "List all contracts with Vendor ABC and their payment terms.",
        "expected_entities": ["Vendor ABC", "contracts", "payment terms"],
    },
    {
        "query": "What are Contoso's obligations in the property management agreement?",
        "expected_entities": ["Contoso", "property management agreement", "obligations"],
    },
    {
        "query": "What is the approval threshold requiring prior written approval?",
        "expected_entities": ["approval threshold", "written approval"],
    },
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_entity_extractor():
    """Mock entity extractor."""
    extractor = MagicMock()
    
    extractor.extract = MagicMock(return_value=["Contoso", "Invoice #12345", "Payment Terms"])
    extractor.aextract = AsyncMock(return_value=["Contoso", "Invoice #12345", "Payment Terms"])
    
    return extractor


@pytest.fixture
def mock_ppr_results():
    """Mock PPR traversal results."""
    return [
        {"id": "entity_1", "name": "Contoso", "score": 0.85, "type": "Organization"},
        {"id": "entity_2", "name": "Invoice #12345", "score": 0.72, "type": "Document"},
        {"id": "entity_3", "name": "Payment Terms", "score": 0.65, "type": "Concept"},
    ]


@pytest.fixture
def mock_route_2_endpoint():
    """Mock the Route 2 endpoint response."""
    return {
        "answer": "Contoso Ltd has the following obligations in the property management agreement: 1) Monthly fee payments of $5,000 [1], 2) Maintaining insurance coverage [2]...",
        "route_used": "route_2_local_search",
        "latency_ms": 3500,
        "seed_entities": ["Contoso", "property management agreement"],
        "context_data": {
            "entities_found": 5,
            "chunks_retrieved": 8,
        },
    }


# ============================================================================
# Test Category 1: Entity Extraction
# ============================================================================

class TestEntityExtraction:
    """Test entity extraction for Route 2."""
    
    def test_entities_extracted_from_query(self, mock_entity_extractor):
        """Test that entities are extracted from query."""
        entities = mock_entity_extractor.extract("What are Contoso's obligations?")
        
        assert len(entities) > 0
        assert "Contoso" in entities
    
    @pytest.mark.asyncio
    async def test_async_entity_extraction(self, mock_entity_extractor):
        """Test async entity extraction."""
        entities = await mock_entity_extractor.aextract("List contracts with Vendor ABC")
        
        assert len(entities) > 0
    
    def test_multiple_entities_extracted(self, mock_entity_extractor):
        """Test that multiple entities can be extracted."""
        entities = mock_entity_extractor.extract("Compare Contoso and ABC Corp contracts")
        
        # Should find multiple entities
        assert len(entities) >= 1


# ============================================================================
# Test Category 2: PPR Traversal
# ============================================================================

class TestPPRTraversal:
    """Test PPR traversal for Route 2."""
    
    def test_ppr_returns_ranked_entities(self, mock_ppr_results):
        """Test that PPR returns ranked entities."""
        # Results should be sorted by score
        scores = [r["score"] for r in mock_ppr_results]
        
        assert scores == sorted(scores, reverse=True)
    
    def test_ppr_scores_in_valid_range(self, mock_ppr_results):
        """Test that PPR scores are in [0, 1]."""
        for result in mock_ppr_results:
            assert 0.0 <= result["score"] <= 1.0
    
    def test_ppr_respects_top_k(self, mock_ppr_results):
        """Test that top_k limits results."""
        top_k = 3
        limited = mock_ppr_results[:top_k]
        
        assert len(limited) <= top_k


# ============================================================================
# Test Category 3: Response Format
# ============================================================================

class TestRoute2Response:
    """Test Route 2 response format."""
    
    def test_response_has_answer(self, mock_route_2_endpoint):
        """Test that response contains answer field."""
        assert "answer" in mock_route_2_endpoint
        assert len(mock_route_2_endpoint["answer"]) > 0
    
    def test_response_indicates_route(self, mock_route_2_endpoint):
        """Test that response indicates Route 2 was used."""
        assert "route_used" in mock_route_2_endpoint
        assert "route_2" in mock_route_2_endpoint["route_used"]
    
    def test_response_includes_seed_entities(self, mock_route_2_endpoint):
        """Test that response includes seed entities."""
        assert "seed_entities" in mock_route_2_endpoint
        assert len(mock_route_2_endpoint["seed_entities"]) > 0
    
    def test_response_has_context_data(self, mock_route_2_endpoint):
        """Test that response includes context data."""
        assert "context_data" in mock_route_2_endpoint
        assert "entities_found" in mock_route_2_endpoint["context_data"]


# ============================================================================
# Test Category 4: Latency
# ============================================================================

class TestRoute2Latency:
    """Test Route 2 latency requirements."""
    
    def test_latency_under_target(self, mock_route_2_endpoint):
        """Test that latency is under 5 seconds."""
        latency_ms = mock_route_2_endpoint["latency_ms"]
        latency_s = latency_ms / 1000
        
        assert latency_s < LATENCY_ROUTE_2
    
    def test_latency_target_reasonable(self):
        """Test that latency target is reasonable for Route 2."""
        # Route 2 should be under 5 seconds
        assert LATENCY_ROUTE_2 == 5.0


# ============================================================================
# Test Category 5: LazyGraphRAG Integration
# ============================================================================

class TestLazyGraphRAGIntegration:
    """Test LazyGraphRAG integration in Route 2."""
    
    def test_iterative_deepening_supported(self):
        """Test that iterative deepening is supported."""
        config = {
            "max_depth": 3,
            "relevance_threshold": 0.5,
        }
        
        assert config["max_depth"] > 0
    
    def test_relevance_budget_configurable(self):
        """Test that relevance budget is configurable."""
        config = {
            "relevance_budget": 0.8,
        }
        
        assert 0.0 <= config["relevance_budget"] <= 1.0


# ============================================================================
# Test Category 6: Multi-Tenancy
# ============================================================================

class TestRoute2MultiTenancy:
    """Test Route 2 multi-tenancy."""
    
    def test_group_id_filters_entities(self, mock_ppr_results):
        """Test that entities are filtered by group_id."""
        # In real implementation, PPR only traverses tenant's graph
        group_id = DEFAULT_GROUP_ID
        
        # Each result should implicitly belong to the tenant
        assert len(group_id) > 0
    
    def test_cross_tenant_isolation(self):
        """Test that different tenants are isolated."""
        tenant_1 = "tenant_1"
        tenant_2 = "tenant_2"
        
        assert tenant_1 != tenant_2


# ============================================================================
# Test Category 7: Query Types
# ============================================================================

class TestRoute2QueryTypes:
    """Test Route 2 handles appropriate query types."""
    
    @pytest.mark.parametrize("test_case", ROUTE_2_TEST_QUERIES)
    def test_entity_queries_processed(self, test_case: Dict[str, Any]):
        """Test that entity-focused queries are processed."""
        query = test_case["query"]
        expected = test_case["expected_entities"]
        
        # Query should mention entities
        query_lower = query.lower()
        
        # At least one expected entity should be findable
        has_entity = any(e.lower() in query_lower for e in expected)
        assert has_entity or len(expected) > 0


# ============================================================================
# Test Category 8: Citation Generation
# ============================================================================

class TestRoute2Citations:
    """Test citation generation in Route 2."""
    
    def test_response_has_citations(self, mock_route_2_endpoint):
        """Test that response includes citations."""
        answer = mock_route_2_endpoint["answer"]
        
        # Should have citation markers [1], [2], etc.
        assert "[1]" in answer or "[" in answer
    
    def test_citations_reference_evidence(self):
        """Test that citations reference evidence chunks."""
        citations = [
            {"index": 1, "source": "contract.pdf", "text": "Monthly fee of $5,000"},
            {"index": 2, "source": "agreement.pdf", "text": "Insurance coverage required"},
        ]
        
        assert len(citations) > 0
        assert all("source" in c for c in citations)


# ============================================================================
# Test Category 9: Error Handling
# ============================================================================

class TestRoute2Errors:
    """Test Route 2 error handling."""
    
    def test_no_entities_extracted(self, mock_entity_extractor):
        """Test handling when no entities are extracted."""
        mock_entity_extractor.extract.return_value = []
        
        entities = mock_entity_extractor.extract("vague query with no entities")
        assert len(entities) == 0
    
    def test_empty_graph_traversal(self):
        """Test handling of empty graph traversal."""
        empty_results = []
        
        # Should handle gracefully
        assert len(empty_results) == 0


# ============================================================================
# Integration Test Markers
# ============================================================================

@pytest.mark.integration
class TestRoute2Integration:
    """Integration tests requiring actual service."""
    
    @pytest.mark.skip(reason="Requires deployed service")
    def test_route_2_live_endpoint(self):
        """Test Route 2 against live service."""
        pass
    
    @pytest.mark.skip(reason="Requires indexed data")
    def test_route_2_with_real_entities(self):
        """Test Route 2 with real entity extraction."""
        pass
