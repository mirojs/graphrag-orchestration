import sys
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

# Mock heavy dependencies before they are imported
sys.modules["graspologic"] = MagicMock()
sys.modules["graspologic.partition"] = MagicMock()
sys.modules["tensorflow"] = MagicMock()
sys.modules["torch"] = MagicMock()

@pytest.fixture
async def client():
    """Async client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def mock_services():
    """Mock all external services to test API logic in isolation."""
    with patch("app.v3.routers.graphrag_v3.get_neo4j_store") as mock_store_fn, \
         patch("app.v3.routers.graphrag_v3.get_indexing_pipeline") as mock_pipeline_fn, \
         patch("app.v3.routers.graphrag_v3.get_drift_adapter") as mock_drift_fn:
        
        # Mock Store
        mock_store = MagicMock()
        mock_store_fn.return_value = mock_store
        
        # Mock Pipeline
        mock_pipeline = MagicMock()
        mock_pipeline_fn.return_value = mock_pipeline
        
        # Mock DRIFT Adapter
        mock_drift = MagicMock()
        mock_drift_fn.return_value = mock_drift
        
        # Mock Embedder/LLM inside adapter
        mock_drift.embedder.embed_query.return_value = [0.1] * 1536
        
        mock_llm_response = MagicMock()
        mock_llm_response.text = "Mocked answer"
        mock_drift.llm.complete.return_value = mock_llm_response
        
        yield {
            "store": mock_store,
            "pipeline": mock_pipeline,
            "drift": mock_drift
        }

@pytest.mark.asyncio
async def test_v3_index_endpoint(client, mock_services):
    """Test /graphrag/v3/index endpoint."""
    mock_pipeline = mock_services["pipeline"]
    
    # Mock successful indexing (async)
    mock_pipeline.index_documents = AsyncMock(return_value={
        "documents": 1,
        "entities": 10,
        "relationships": 20,
        "communities": 5,
        "raptor_nodes": 2
    })
    
    payload = {
        "documents": ["Test document content"],
        "run_raptor": True
    }
    
    response = await client.post(
        "/graphrag/v3/index",
        json=payload,
        headers={"X-Group-ID": "test-group"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["group_id"] == "test-group"
    assert data["documents_processed"] == 1

@pytest.mark.asyncio
async def test_v3_local_search_endpoint(client, mock_services):
    """Test /graphrag/v3/query/local endpoint."""
    mock_store = mock_services["store"]
    
    # Mock search results
    mock_entity = MagicMock()
    mock_entity.name = "Test Entity"
    mock_entity.type = "TEST"
    mock_entity.description = "A test entity"
    mock_entity.id = "e1"
    
    mock_store.search_entities_by_embedding.return_value = [(mock_entity, 0.9)]
    
    payload = {
        "query": "What is test?",
        "top_k": 5
    }
    
    response = await client.post(
        "/graphrag/v3/query/local",
        json=payload,
        headers={"X-Group-ID": "test-group"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Mocked answer"
    assert data["search_type"] == "local"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["name"] == "Test Entity"

@pytest.mark.asyncio
async def test_v3_global_search_endpoint(client, mock_services):
    """Test /graphrag/v3/query/global endpoint."""
    mock_store = mock_services["store"]
    
    # Mock community results
    mock_community = MagicMock()
    mock_community.id = "c1"
    mock_community.title = "Test Community"
    mock_community.summary = "This is a summary"
    mock_community.level = 0
    mock_community.entity_ids = ["e1", "e2"]
    
    mock_store.get_communities_by_level.return_value = [mock_community]
    
    payload = {
        "query": "Summarize everything",
        "top_k": 5
    }
    
    response = await client.post(
        "/graphrag/v3/query/global",
        json=payload,
        headers={"X-Group-ID": "test-group"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Mocked answer"
    assert data["search_type"] == "global"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Test Community"

@pytest.mark.asyncio
async def test_v3_drift_search_endpoint(client, mock_services):
    """Test /graphrag/v3/query/drift endpoint."""
    mock_drift = mock_services["drift"]
    
    # Mock DRIFT results (async)
    mock_drift.drift_search = AsyncMock(return_value={
        "answer": "DRIFT answer",
        "confidence": 0.95,
        "iterations": 3,
        "sources": [{"id": "s1"}],
        "reasoning_path": [{"step": 1}]
    })
    
    payload = {
        "query": "Complex question?",
        "max_iterations": 3
    }
    
    response = await client.post(
        "/graphrag/v3/query/drift",
        json=payload,
        headers={"X-Group-ID": "test-group"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "DRIFT answer"
    assert data["search_type"] == "drift"
    assert data["iterations"] == 3

@pytest.mark.asyncio
async def test_missing_group_id(client):
    """Test that missing X-Group-ID header returns 401."""
    response = await client.post(
        "/graphrag/v3/query/local",
        json={"query": "test"}
    )
    assert response.status_code == 401
    assert "Missing X-Group-ID header" in response.json()["detail"]
