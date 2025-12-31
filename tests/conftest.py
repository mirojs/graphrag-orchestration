"""
Shared pytest fixtures for GraphRAG Orchestration Test Suite.

This module provides common fixtures used across unit, integration, and cloud tests.
All fixtures are designed for the 4-route hybrid architecture:
- Route 1: Vector RAG (fast lane)
- Route 2: Local Search (entity-focused)
- Route 3: Global Search (thematic + PPR)
- Route 4: DRIFT Multi-Hop (ambiguous queries)

Configuration:
- Embedding dimensions: 3072 (text-embedding-3-large)
- Neo4j: Aura instance with vector indexes
- Azure OpenAI: gpt-4o, gpt-4o-mini, gpt-4.1
"""

import os
import pytest
from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock, AsyncMock


# ============================================================================
# Constants (aligned with current architecture)
# ============================================================================

EMBEDDING_DIMENSIONS = 3072  # text-embedding-3-large
DEFAULT_TOP_K = 10
DEFAULT_GROUP_ID = "test-group"

# Route latency targets (seconds)
LATENCY_ROUTE_1 = 2.0   # Vector RAG
LATENCY_ROUTE_2 = 5.0   # Local Search
LATENCY_ROUTE_3 = 10.0  # Global Search
LATENCY_ROUTE_4 = 20.0  # DRIFT


# ============================================================================
# Environment Configuration
# ============================================================================

@pytest.fixture(scope="session")
def test_config() -> Dict[str, Any]:
    """Session-wide test configuration."""
    return {
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "embedding_model": "text-embedding-3-large",
        "default_group_id": DEFAULT_GROUP_ID,
        "neo4j_uri": os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io"),
        "azure_openai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "cloud_url": os.getenv(
            "GRAPHRAG_CLOUD_URL",
            "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
        ),
    }


# ============================================================================
# Mock Embedding Model (3072 dimensions)
# ============================================================================

@pytest.fixture
def mock_embedder():
    """Mock embedding model that returns 3072-dimensional vectors."""
    embedder = MagicMock()
    
    # Sync methods
    embedder.get_text_embedding = MagicMock(return_value=[0.1] * EMBEDDING_DIMENSIONS)
    embedder.embed_query = MagicMock(return_value=[0.1] * EMBEDDING_DIMENSIONS)
    embedder.embed_documents = MagicMock(
        side_effect=lambda docs: [[0.1] * EMBEDDING_DIMENSIONS for _ in docs]
    )
    
    # Async methods
    embedder.aget_text_embedding = AsyncMock(return_value=[0.1] * EMBEDDING_DIMENSIONS)
    embedder.aembed_query = AsyncMock(return_value=[0.1] * EMBEDDING_DIMENSIONS)
    embedder.aembed_documents = AsyncMock(
        side_effect=lambda docs: [[0.1] * EMBEDDING_DIMENSIONS for _ in docs]
    )
    
    # Metadata
    embedder.dimensions = EMBEDDING_DIMENSIONS
    embedder.model_name = "text-embedding-3-large"
    
    return embedder


# ============================================================================
# Mock LLM Service
# ============================================================================

@pytest.fixture
def mock_llm():
    """Mock LLM for testing without Azure OpenAI calls."""
    llm = MagicMock()
    
    # Sync completion
    response = MagicMock()
    response.text = '{"entities": ["Entity A", "Entity B"]}'
    response.content = response.text
    llm.complete = MagicMock(return_value=response)
    
    # Async completion
    llm.acomplete = AsyncMock(return_value=response)
    
    # Chat completion
    chat_response = MagicMock()
    chat_response.message = MagicMock()
    chat_response.message.content = "This is a synthesized response based on the evidence."
    llm.chat = MagicMock(return_value=chat_response)
    llm.achat = AsyncMock(return_value=chat_response)
    
    return llm


@pytest.fixture
def mock_llm_service(mock_llm, mock_embedder):
    """Mock LLM service with all models configured."""
    service = MagicMock()
    service.llm = mock_llm
    service.embed_model = mock_embedder
    service.router_llm = mock_llm
    service.synthesis_llm = mock_llm
    service.indexing_llm = mock_llm
    return service


# ============================================================================
# Mock Graph Store (Neo4j)
# ============================================================================

@pytest.fixture
def mock_graph_store():
    """Mock Neo4j graph store with sample data."""
    store = MagicMock()
    
    # Sample graph data
    sample_nodes = [
        {"id": "entity_1", "name": "Contoso Ltd", "type": "Organization", "group_id": DEFAULT_GROUP_ID},
        {"id": "entity_2", "name": "Invoice #12345", "type": "Document", "group_id": DEFAULT_GROUP_ID},
        {"id": "entity_3", "name": "Payment Terms", "type": "Concept", "group_id": DEFAULT_GROUP_ID},
    ]
    
    sample_edges = [
        ("entity_1", "entity_2", "ISSUED"),
        ("entity_2", "entity_3", "HAS_TERMS"),
    ]
    
    # Mock query methods
    store.get = AsyncMock(return_value={"nodes": sample_nodes, "edges": sample_edges})
    store.query = MagicMock(return_value=sample_nodes)
    store.aquery = AsyncMock(return_value=sample_nodes)
    store.structured_query = MagicMock(return_value=sample_nodes)
    store.astructured_query = AsyncMock(return_value=sample_nodes)
    
    return store


# ============================================================================
# Mock Retriever Results
# ============================================================================

@pytest.fixture
def mock_retrieval_results():
    """Sample retrieval results for testing synthesis."""
    from llama_index.core.schema import NodeWithScore, TextNode
    
    return [
        NodeWithScore(
            node=TextNode(
                id_="chunk_1",
                text="Invoice #12345 was issued by Contoso Ltd for $50,000.",
                metadata={"source": "invoice.pdf", "group_id": DEFAULT_GROUP_ID}
            ),
            score=0.95
        ),
        NodeWithScore(
            node=TextNode(
                id_="chunk_2",
                text="Payment terms are Net 30 days from invoice date.",
                metadata={"source": "contract.pdf", "group_id": DEFAULT_GROUP_ID}
            ),
            score=0.88
        ),
        NodeWithScore(
            node=TextNode(
                id_="chunk_3",
                text="The agreement is governed by the laws of Delaware.",
                metadata={"source": "contract.pdf", "group_id": DEFAULT_GROUP_ID}
            ),
            score=0.75
        ),
    ]


# ============================================================================
# Question Bank Fixtures
# ============================================================================

@pytest.fixture
def vector_questions() -> List[Dict[str, str]]:
    """Route 1: Vector RAG test questions (simple fact lookups)."""
    return [
        {"qid": "Q-V1", "text": "What is the invoice total amount?"},
        {"qid": "Q-V2", "text": "What is the due date?"},
        {"qid": "Q-V3", "text": "Who is the salesperson?"},
    ]


@pytest.fixture
def local_questions() -> List[Dict[str, str]]:
    """Route 2: Local Search test questions (entity-focused)."""
    return [
        {"qid": "Q-L1", "text": "List all contracts with Vendor ABC and their payment terms."},
        {"qid": "Q-L2", "text": "What are all obligations for Contoso Ltd. in the property management agreement?"},
        {"qid": "Q-L3", "text": "What is the approval threshold requiring prior written approval for expenditures?"},
    ]


@pytest.fixture
def global_questions() -> List[Dict[str, str]]:
    """Route 3: Global Search test questions (thematic)."""
    return [
        {"qid": "Q-G1", "text": "Across the agreements, summarize termination and cancellation rules."},
        {"qid": "Q-G2", "text": "Identify which documents reference governing law or jurisdiction."},
        {"qid": "Q-G3", "text": "Summarize who pays what across the set (fees, charges, taxes)."},
    ]


@pytest.fixture
def drift_questions() -> List[Dict[str, str]]:
    """Route 4: DRIFT Multi-Hop test questions (ambiguous, multi-hop)."""
    return [
        {"qid": "Q-D1", "text": "Analyze our overall risk exposure through subsidiaries and trace relationships."},
        {"qid": "Q-D2", "text": "Compare time windows across the set and list all explicit day-based timeframes."},
        {"qid": "Q-D3", "text": "Explain the implications of dispute resolution mechanisms across the agreements."},
    ]


# ============================================================================
# HTTP Client Fixtures
# ============================================================================

@pytest.fixture
def api_headers() -> Dict[str, str]:
    """Standard headers for API requests."""
    return {
        "Content-Type": "application/json",
        "X-Group-ID": DEFAULT_GROUP_ID,
    }


@pytest.fixture
def sample_index_request() -> Dict[str, Any]:
    """Sample indexing request payload."""
    return {
        "documents": [
            "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
            "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf",
        ],
        "ingestion": "document-intelligence",
        "run_raptor": True,
    }


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def assert_valid_response():
    """Factory fixture for response validation."""
    def _assert(response_data: Dict[str, Any], route: str):
        """Assert response has required fields for given route."""
        assert "answer" in response_data, f"Missing 'answer' field in {route} response"
        assert len(response_data["answer"]) > 0, f"Empty answer in {route} response"
        
        # Route-specific validations
        if route in ("local", "global", "drift"):
            # These routes should return context data
            if "context_data" in response_data:
                assert isinstance(response_data["context_data"], dict)
        
        return True
    
    return _assert


@pytest.fixture
def measure_latency():
    """Factory fixture for latency measurement."""
    import time
    
    class LatencyMeasurer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = time.monotonic()
        
        def stop(self):
            self.end_time = time.monotonic()
        
        @property
        def elapsed(self) -> float:
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return 0.0
        
        def assert_under(self, target: float, route: str):
            assert self.elapsed < target, f"{route} latency {self.elapsed:.2f}s exceeds target {target}s"
    
    return LatencyMeasurer


# ============================================================================
# Cleanup Fixtures
# ============================================================================

@pytest.fixture
def cleanup_test_data():
    """Cleanup fixture for test data (yields None, cleans up after test)."""
    created_ids = []
    
    def track(entity_id: str):
        created_ids.append(entity_id)
    
    yield track
    
    # Cleanup would happen here (mock for now)
    # In real tests, this would delete test entities from Neo4j


# ============================================================================
# Skip Markers
# ============================================================================

requires_neo4j = pytest.mark.skipif(
    not os.getenv("NEO4J_URI"),
    reason="Requires NEO4J_URI environment variable"
)

requires_azure_openai = pytest.mark.skipif(
    not os.getenv("AZURE_OPENAI_ENDPOINT"),
    reason="Requires AZURE_OPENAI_ENDPOINT environment variable"
)

requires_cloud = pytest.mark.skipif(
    not os.getenv("GRAPHRAG_CLOUD_URL"),
    reason="Requires GRAPHRAG_CLOUD_URL environment variable"
)
