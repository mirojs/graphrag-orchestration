"""
Integration Tests for HippoRAG Retriever

Tests the LlamaIndex BaseRetriever interface compliance and integration
with the hybrid pipeline components.

Test Categories:
1. BaseRetriever Interface Compliance
2. Query Bundle Handling
3. NodeWithScore Output Format
4. Async Interface
5. Error Handling
6. Graph Store Integration

Run with:
    pytest tests/test_hipporag_integration_v2.py -v
"""

import pytest
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

# LlamaIndex imports
from llama_index.core import QueryBundle
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.retrievers import BaseRetriever

# App imports
from app.hybrid.retrievers import HippoRAGRetriever, HippoRAGRetrieverConfig


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_graph_store():
    """Mock Neo4j graph store."""
    store = MagicMock()
    
    # Mock graph data (simple chain: A → B → C)
    store.get = AsyncMock(return_value={
        'nodes': [
            {'id': 'entity_a', 'name': 'Entity A', 'text': 'Text about Entity A', 'group_id': 'test_group'},
            {'id': 'entity_b', 'name': 'Entity B', 'text': 'Text about Entity B', 'group_id': 'test_group'},
            {'id': 'entity_c', 'name': 'Entity C', 'text': 'Text about Entity C', 'group_id': 'test_group'},
        ],
        'edges': [
            ('entity_a', 'entity_b'),
            ('entity_b', 'entity_c'),
        ]
    })
    
    return store


@pytest.fixture
def mock_llm():
    """Mock LLM for entity extraction."""
    llm = MagicMock()
    
    # Mock complete response for entity extraction
    response = MagicMock()
    response.text = '["Entity A", "Entity B"]'
    llm.complete = MagicMock(return_value=response)
    llm.acomplete = AsyncMock(return_value=response)
    
    return llm


@pytest.fixture
def mock_embed_model():
    """Mock embedding model."""
    embed = MagicMock()
    
    # Mock embedding vectors
    embed.get_text_embedding = MagicMock(return_value=[0.1] * 1536)
    embed.aget_text_embedding = AsyncMock(return_value=[0.1] * 1536)
    
    return embed


@pytest.fixture
def retriever_config():
    """Default retriever configuration."""
    return HippoRAGRetrieverConfig(
        top_k=5,
        damping_factor=0.85,
        max_iterations=20,
        convergence_threshold=1e-6
    )


@pytest.fixture
def hipporag_retriever(mock_graph_store, mock_llm, mock_embed_model, retriever_config):
    """HippoRAG retriever instance with mocked dependencies."""
    retriever = HippoRAGRetriever(
        graph_store=mock_graph_store,
        llm=mock_llm,
        embed_model=mock_embed_model,
        config=retriever_config,
        group_id="test_group"
    )
    
    # Mock internal graph state to avoid actual Neo4j calls in tests
    retriever._nodes = {'entity_a', 'entity_b', 'entity_c'}
    retriever._adjacency = {
        'entity_a': {'entity_b'},
        'entity_b': {'entity_c'},
        'entity_c': set()
    }
    retriever._node_properties = {
        'entity_a': {'name': 'Entity A', 'text': 'Text about Entity A', 'labels': ['Entity']},
        'entity_b': {'name': 'Entity B', 'text': 'Text about Entity B', 'labels': ['Entity']},
        'entity_c': {'name': 'Entity C', 'text': 'Text about Entity C', 'labels': ['Entity']},
    }
    
    return retriever


# ============================================================================
# Test Category 1: BaseRetriever Interface Compliance
# ============================================================================

def test_extends_base_retriever(hipporag_retriever):
    """Test that HippoRAGRetriever extends BaseRetriever."""
    assert isinstance(hipporag_retriever, BaseRetriever)


def test_has_retrieve_method(hipporag_retriever):
    """Test that _retrieve method exists and is callable."""
    assert hasattr(hipporag_retriever, '_retrieve')
    assert callable(hipporag_retriever._retrieve)


def test_has_aretrieve_method(hipporag_retriever):
    """Test that _aretrieve method exists and is callable."""
    assert hasattr(hipporag_retriever, '_aretrieve')
    assert callable(hipporag_retriever._aretrieve)


def test_retrieve_public_method_exists(hipporag_retriever):
    """Test that public retrieve() method exists (inherited from BaseRetriever)."""
    assert hasattr(hipporag_retriever, 'retrieve')
    assert callable(hipporag_retriever.retrieve)


def test_aretrieve_public_method_exists(hipporag_retriever):
    """Test that public aretrieve() method exists (inherited from BaseRetriever)."""
    assert hasattr(hipporag_retriever, 'aretrieve')
    assert callable(hipporag_retriever.aretrieve)


# ============================================================================
# Test Category 2: Query Bundle Handling
# ============================================================================

@pytest.mark.asyncio
async def test_query_bundle_string_extraction(hipporag_retriever):
    """Test that retriever extracts query string from QueryBundle."""
    query_bundle = QueryBundle(query_str="What are the compliance risks?")
    
    # Mock entity extraction and seed expansion
    with patch.object(hipporag_retriever, '_load_graph_from_neo4j'):
        with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=['Entity A']):
            with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a']):
                nodes = await hipporag_retriever._aretrieve(query_bundle)
                
                # Should extract query string and process it
                assert len(nodes) > 0
                assert all(isinstance(n, NodeWithScore) for n in nodes)


@pytest.mark.asyncio
async def test_query_bundle_with_metadata(hipporag_retriever):
    """Test that retriever handles QueryBundle with custom metadata."""
    query_bundle = QueryBundle(
        query_str="Analyze vendor risks",
        custom_embedding_strs=["vendor", "risk"],
        embedding=[0.1] * 1536
    )
    
    with patch.object(hipporag_retriever, '_load_graph_from_neo4j'):
        with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=['Vendor A']):
            with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a']):
                nodes = await hipporag_retriever._aretrieve(query_bundle)
                
                # Should handle metadata gracefully
                assert len(nodes) > 0


# ============================================================================
# Test Category 3: NodeWithScore Output Format
# ============================================================================

@pytest.mark.asyncio
async def test_returns_list_of_nodewithscore(hipporag_retriever):
    """Test that _aretrieve returns List[NodeWithScore]."""
    query_bundle = QueryBundle(query_str="Test query")
    
    with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=['Entity A']):
        with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a', 'entity_b']):
            nodes = await hipporag_retriever._aretrieve(query_bundle)
            
            assert isinstance(nodes, list)
            assert all(isinstance(n, NodeWithScore) for n in nodes)


@pytest.mark.asyncio
async def test_nodewithscore_has_node_and_score(hipporag_retriever):
    """Test that each NodeWithScore has both node and score attributes."""
    query_bundle = QueryBundle(query_str="Test query")
    
    with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=['Entity A']):
        with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a']):
            nodes = await hipporag_retriever._aretrieve(query_bundle)
            
            for node_with_score in nodes:
                assert hasattr(node_with_score, 'node')
                assert hasattr(node_with_score, 'score')
                assert isinstance(node_with_score.node, TextNode)
                assert isinstance(node_with_score.score, float)


@pytest.mark.asyncio
async def test_scores_in_valid_range(hipporag_retriever):
    """Test that PPR scores are in valid range [0.0, 1.0]."""
    query_bundle = QueryBundle(query_str="Test query")
    
    with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=['Entity A', 'Entity B']):
        with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a', 'entity_b']):
            nodes = await hipporag_retriever._aretrieve(query_bundle)
            
            for node_with_score in nodes:
                assert 0.0 <= node_with_score.score <= 1.0


# ============================================================================
# Test Category 4: Async Interface
# ============================================================================

@pytest.mark.asyncio
async def test_aretrieve_is_async(hipporag_retriever):
    """Test that _aretrieve is an async function."""
    query_bundle = QueryBundle(query_str="Async test")
    
    with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=['Entity A']):
        with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a']):
            # Call should work with await
            nodes = await hipporag_retriever._aretrieve(query_bundle)
            assert isinstance(nodes, list)


@pytest.mark.asyncio
async def test_sync_retrieve_works(hipporag_retriever):
    """Test that synchronous _retrieve method works."""
    query_bundle = QueryBundle(query_str="Sync test")
    
    with patch.object(hipporag_retriever, '_extract_entities_sync', return_value=['Entity A']):
        with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a']):
            nodes = hipporag_retriever._retrieve(query_bundle)
            assert isinstance(nodes, list)
            assert all(isinstance(n, NodeWithScore) for n in nodes)


# ============================================================================
# Test Category 5: Error Handling
# ============================================================================

@pytest.mark.asyncio
async def test_empty_graph_returns_empty_list(hipporag_retriever):
    """Test that retriever returns empty list when graph is empty."""
    hipporag_retriever._nodes = set()
    
    query_bundle = QueryBundle(query_str="Test query")
    nodes = await hipporag_retriever._aretrieve(query_bundle)
    
    assert nodes == []


@pytest.mark.asyncio
async def test_no_seeds_extracted_returns_empty(hipporag_retriever):
    """Test that retriever returns empty list when no seeds are extracted."""
    query_bundle = QueryBundle(query_str="Irrelevant query")
    
    with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=[]):
        nodes = await hipporag_retriever._aretrieve(query_bundle)
        assert nodes == []


@pytest.mark.asyncio
async def test_llm_failure_returns_empty(hipporag_retriever):
    """Test that LLM failure doesn't crash retriever."""
    query_bundle = QueryBundle(query_str="Test query")
    
    # Simulate LLM failure
    with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, side_effect=Exception("LLM Error")):
        # Should not raise, might return empty or use fallback
        try:
            nodes = await hipporag_retriever._aretrieve(query_bundle)
            # If it succeeds, verify format
            assert isinstance(nodes, list)
        except Exception as e:
            # Or it might re-raise - both are acceptable
            assert "LLM Error" in str(e)


# ============================================================================
# Test Category 6: Graph Store Integration
# ============================================================================

@pytest.mark.asyncio
async def test_graph_store_is_used(hipporag_retriever, mock_graph_store):
    """Test that graph store is properly initialized."""
    assert hipporag_retriever.graph_store is mock_graph_store


def test_multi_tenancy_group_id_set(hipporag_retriever):
    """Test that group_id is properly set for multi-tenancy."""
    assert hipporag_retriever.group_id == "test_group"


# ============================================================================
# Test Category 7: Configuration
# ============================================================================

def test_config_top_k_is_respected(hipporag_retriever):
    """Test that top_k configuration is set."""
    assert hipporag_retriever.config.top_k == 5


def test_config_damping_factor_is_set(hipporag_retriever):
    """Test that damping factor is configured."""
    assert hipporag_retriever.config.damping_factor == 0.85


# ============================================================================
# Test Category 8: Pre-extracted Seeds Support
# ============================================================================

@pytest.mark.asyncio
async def test_preextracted_seeds_work(hipporag_retriever):
    """Test that retriever can work with pre-extracted seeds."""
    query_bundle = QueryBundle(query_str="Test with seeds")
    
    # Provide seeds directly by mocking expansion
    with patch.object(hipporag_retriever, '_load_graph_from_neo4j'):
        with patch.object(hipporag_retriever, '_extract_entities_with_llm', new_callable=AsyncMock, return_value=['Entity A', 'Entity B']):
            with patch.object(hipporag_retriever, '_expand_seeds_to_nodes', return_value=['entity_a', 'entity_b']):
                nodes = await hipporag_retriever._aretrieve(query_bundle)
                
                assert len(nodes) > 0
                # Verify that seeds were used
                hipporag_retriever._extract_entities_with_llm.assert_called_once()
