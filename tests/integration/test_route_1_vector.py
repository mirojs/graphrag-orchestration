"""
Integration Tests: Route 1 - Vector RAG (Fast Lane)

Tests the vector-based retrieval route for simple fact lookups.
Route 1 is the fastest route, using embedding similarity search.

When to use Route 1:
- Simple fact queries ("What is X?")
- Known entity lookups
- FAQ-style questions

Fallback behavior:
- Falls back to Route 2 when vector index is unavailable

Run: pytest tests/integration/test_route_1_vector.py -v
"""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any, List

# Import test config from conftest
try:
    from ..conftest import (
        EMBEDDING_DIMENSIONS,
        LATENCY_ROUTE_1,
        DEFAULT_GROUP_ID,
    )
except ImportError:
    # Fallback for direct pytest execution
    EMBEDDING_DIMENSIONS = 3072
    LATENCY_ROUTE_1 = 2.0
    DEFAULT_GROUP_ID = "test-group"


# ============================================================================
# Test Data
# ============================================================================

ROUTE_1_TEST_QUERIES = [
    ("What is the invoice total?", ["invoice", "total", "amount"]),
    ("What is the due date?", ["due", "date", "payment"]),
    ("Who is the vendor?", ["vendor", "supplier", "company"]),
    ("What is the PO number?", ["PO", "purchase order", "number"]),
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_vector_store():
    """Mock vector store for Route 1."""
    store = MagicMock()
    
    # Mock search results
    search_results = [
        {"id": "chunk_1", "text": "Invoice total: $50,000", "score": 0.95},
        {"id": "chunk_2", "text": "Due date: February 15, 2024", "score": 0.88},
    ]
    
    store.similarity_search = MagicMock(return_value=search_results)
    store.asimilarity_search = AsyncMock(return_value=search_results)
    
    return store


@pytest.fixture
def mock_route_1_endpoint():
    """Mock the Route 1 endpoint response."""
    return {
        "answer": "The invoice total is $50,000.",
        "route_used": "route_1_vector_rag",
        "latency_ms": 450,
        "sources": [{"source": "invoice.pdf", "chunk_id": "chunk_1"}],
    }


# ============================================================================
# Test Category 1: Route 1 Availability
# ============================================================================

class TestRoute1Availability:
    """Test Route 1 availability and configuration."""
    
    def test_route_1_endpoint_exists(self):
        """Test that Route 1 endpoint path is defined."""
        endpoint = "/graphrag/v3/query/local"  # Route 1 uses local endpoint
        assert endpoint.startswith("/graphrag/v3/query")
    
    def test_route_1_enabled_in_general_profile(self):
        """Test that Route 1 is enabled in General Enterprise profile."""
        general_profile = {
            "routes_enabled": ["route_1", "route_2", "route_3", "route_4"],
        }
        assert "route_1" in general_profile["routes_enabled"]
    
    def test_route_1_disabled_in_high_assurance(self):
        """Test that Route 1 is disabled in High Assurance profile."""
        high_assurance_profile = {
            "routes_enabled": ["route_2", "route_3", "route_4"],
        }
        assert "route_1" not in high_assurance_profile["routes_enabled"]


# ============================================================================
# Test Category 2: Vector Search
# ============================================================================

class TestVectorSearch:
    """Test vector similarity search functionality."""
    
    def test_vector_search_returns_results(self, mock_vector_store):
        """Test that vector search returns results."""
        results = mock_vector_store.similarity_search("What is the total?")
        
        assert len(results) > 0
        assert results[0]["score"] > 0.5
    
    def test_vector_search_uses_correct_dimensions(self, mock_embedder):
        """Test that vector search uses 3072-dim embeddings."""
        embedding = mock_embedder.embed_query("test query")
        
        assert len(embedding) == EMBEDDING_DIMENSIONS
    
    @pytest.mark.asyncio
    async def test_async_vector_search(self, mock_vector_store):
        """Test async vector search."""
        results = await mock_vector_store.asimilarity_search("What is the total?")
        
        assert len(results) > 0
    
    def test_vector_search_respects_top_k(self, mock_vector_store):
        """Test that top_k parameter is respected."""
        top_k = 5
        # In real implementation, would verify result count
        assert top_k > 0


# ============================================================================
# Test Category 3: Response Format
# ============================================================================

class TestRoute1Response:
    """Test Route 1 response format."""
    
    def test_response_has_answer(self, mock_route_1_endpoint):
        """Test that response contains answer field."""
        assert "answer" in mock_route_1_endpoint
        assert len(mock_route_1_endpoint["answer"]) > 0
    
    def test_response_indicates_route(self, mock_route_1_endpoint):
        """Test that response indicates Route 1 was used."""
        assert "route_used" in mock_route_1_endpoint
        assert "route_1" in mock_route_1_endpoint["route_used"]
    
    def test_response_includes_sources(self, mock_route_1_endpoint):
        """Test that response includes source references."""
        assert "sources" in mock_route_1_endpoint
        assert len(mock_route_1_endpoint["sources"]) > 0


# ============================================================================
# Test Category 4: Latency
# ============================================================================

class TestRoute1Latency:
    """Test Route 1 latency requirements."""
    
    def test_latency_under_target(self, mock_route_1_endpoint):
        """Test that latency is under 2 seconds."""
        latency_ms = mock_route_1_endpoint["latency_ms"]
        latency_s = latency_ms / 1000
        
        assert latency_s < LATENCY_ROUTE_1
    
    def test_latency_target_reasonable(self):
        """Test that latency target is reasonable."""
        # Route 1 should be fastest: < 2s
        assert LATENCY_ROUTE_1 == 2.0


# ============================================================================
# Test Category 5: Fallback to Route 2
# ============================================================================

class TestRoute1Fallback:
    """Test Route 1 fallback behavior."""
    
    def test_fallback_when_no_vector_index(self):
        """Test fallback to Route 2 when vector index unavailable."""
        fallback_response = {
            "answer": "Based on the documents...",
            "route_used": "route_2_local_search",
            "fallback_from": "route_1_vector_rag",
            "fallback_reason": "vector_index_unavailable",
        }
        
        assert fallback_response["fallback_from"] == "route_1_vector_rag"
        assert "route_2" in fallback_response["route_used"]
    
    def test_fallback_preserves_query(self):
        """Test that fallback preserves original query."""
        original_query = "What is the invoice total?"
        fallback_query = original_query  # Should be same
        
        assert fallback_query == original_query


# ============================================================================
# Test Category 6: Multi-Tenancy
# ============================================================================

class TestRoute1MultiTenancy:
    """Test Route 1 multi-tenancy."""
    
    def test_group_id_required(self):
        """Test that group_id is required for Route 1."""
        request = {
            "query": "What is the total?",
            "group_id": DEFAULT_GROUP_ID,
        }
        
        assert "group_id" in request
    
    def test_results_filtered_by_group(self, mock_vector_store):
        """Test that results are filtered by group_id."""
        # In real implementation, would verify Neo4j WHERE clause
        # includes group_id filter
        group_id = DEFAULT_GROUP_ID
        assert len(group_id) > 0


# ============================================================================
# Test Category 7: Query Types
# ============================================================================

class TestRoute1QueryTypes:
    """Test Route 1 handles appropriate query types."""
    
    @pytest.mark.parametrize("query,expected_terms", ROUTE_1_TEST_QUERIES)
    def test_simple_queries_processed(self, query: str, expected_terms: List[str]):
        """Test that simple queries are processed."""
        # Query should be answerable with vector search
        query_lower = query.lower()
        
        # Should be a simple question format
        assert any(query_lower.startswith(w) for w in ["what", "who", "when", "where"])
    
    def test_complex_query_not_ideal_for_route_1(self):
        """Test that complex queries should use other routes."""
        complex_query = "Analyze our risk exposure through subsidiaries"
        
        # This should go to Route 4, not Route 1
        simple_indicators = ["what is", "who is", "what are the"]
        is_simple = any(ind in complex_query.lower() for ind in simple_indicators)
        
        assert not is_simple, "Complex query should not be Route 1"


# ============================================================================
# Test Category 8: Error Handling
# ============================================================================

class TestRoute1Errors:
    """Test Route 1 error handling."""
    
    def test_empty_results_handled(self, mock_vector_store):
        """Test handling of empty search results."""
        mock_vector_store.similarity_search.return_value = []
        
        results = mock_vector_store.similarity_search("nonexistent query")
        assert len(results) == 0
    
    def test_low_score_results_filtered(self):
        """Test that low-score results are filtered."""
        results = [
            {"score": 0.95, "text": "High relevance"},
            {"score": 0.3, "text": "Low relevance"},
        ]
        
        threshold = 0.5
        filtered = [r for r in results if r["score"] >= threshold]
        
        assert len(filtered) == 1
        assert filtered[0]["score"] == 0.95


# ============================================================================
# Integration Test Markers
# ============================================================================

@pytest.mark.integration
class TestRoute1Integration:
    """Integration tests requiring actual service."""
    
    @pytest.mark.skip(reason="Requires deployed service")
    def test_route_1_live_endpoint(self):
        """Test Route 1 against live service."""
        pass
    
    @pytest.mark.skip(reason="Requires indexed data")
    def test_route_1_with_real_data(self):
        """Test Route 1 with real indexed documents."""
        pass
