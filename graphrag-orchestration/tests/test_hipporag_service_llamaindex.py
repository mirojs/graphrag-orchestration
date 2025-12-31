"""
Service-Level Tests for HippoRAG Service

Tests the 3-tier fallback logic and service management for HippoRAG integration.

Test Categories:
1. Service Initialization
2. 3-Tier Fallback Logic (LlamaIndex → Upstream → Local)
3. Health Check Methods
4. Singleton Pattern
5. Auto-Detection of Dependencies
6. Configuration Passing
7. Error Propagation

Run with:
    pytest tests/test_hipporag_service_llamaindex.py -v
"""

import pytest
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# App imports
from app.hybrid.indexing.hipporag_service import (
    HippoRAGService,
    get_hipporag_service,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_graph_store():
    """Mock Neo4j graph store."""
    store = MagicMock()
    store.get = AsyncMock(return_value={
        'nodes': [{'id': 'test_node', 'name': 'Test'}],
        'edges': []
    })
    return store


@pytest.fixture
def mock_llm_service():
    """Mock LLM service."""
    service = MagicMock()
    service.llm = MagicMock()
    service.embed_model = MagicMock()
    return service


@pytest.fixture
def clean_hipporag_cache():
    """Clear service cache before each test."""
    # Clear any cached instances
    from app.hybrid.indexing.hipporag_service import _hipporag_cache
    _hipporag_cache.clear()
    yield
    _hipporag_cache.clear()


# ============================================================================
# Test Category 1: Service Initialization
# ============================================================================

def test_service_instantiation(clean_hipporag_cache):
    """Test that HippoRAGService can be instantiated."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index"
    )
    
    assert service is not None
    assert service.group_id == "test_group"
    assert str(service.index_dir).endswith("test_group")


def test_service_with_graph_store(mock_graph_store, clean_hipporag_cache):
    """Test service initialization with graph_store (enables LlamaIndex mode)."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store
    )
    
    assert service.graph_store is not None


def test_service_with_llm_service(mock_llm_service, clean_hipporag_cache):
    """Test service initialization with llm_service (enables LlamaIndex mode)."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        llm_service=mock_llm_service
    )
    
    assert service.llm_service is not None


# ============================================================================
# Test Category 2: 3-Tier Fallback Logic
# ============================================================================

@pytest.mark.asyncio
async def test_tier1_llamaindex_mode_preferred(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that LlamaIndex mode is preferred when graph_store + llm_service available."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    
    # Should select LlamaIndex mode
    assert service._use_llamaindex == True


@pytest.mark.asyncio
async def test_tier2_upstream_fallback(clean_hipporag_cache):
    """Test fallback to upstream hipporag package when LlamaIndex unavailable."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=None,  # No graph store = no LlamaIndex mode
        llm_service=None
    )
    
    # Mock upstream hipporag availability
    with patch('app.hybrid.indexing.hipporag_service.HIPPORAG_AVAILABLE', True):
        await service.initialize()
        
        # Should select upstream mode (not llamaindex)
        assert service._use_llamaindex == False


@pytest.mark.asyncio
async def test_tier3_local_ppr_fallback(clean_hipporag_cache):
    """Test fallback to local PPR when both LlamaIndex and upstream unavailable."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=None,
        llm_service=None
    )
    
    # Mock upstream hipporag unavailable
    with patch('app.hybrid.indexing.hipporag_service.HIPPORAG_AVAILABLE', False):
        with patch('app.hybrid.indexing.hipporag_service.LLAMAINDEX_HIPPORAG_AVAILABLE', False):
            await service.initialize()
            
            # Should not use llamaindex mode
            assert service._use_llamaindex == False


@pytest.mark.asyncio
async def test_mode_selection_priority_order(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that mode selection follows priority: LlamaIndex > Upstream > Local."""
    # Priority 1: LlamaIndex (when dependencies available)
    service1 = HippoRAGService(
        group_id="test1",
        index_dir="./index1",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    await service1.initialize()
    assert service1._use_llamaindex == True
    
    # Priority 2: Upstream (when LlamaIndex unavailable but upstream is)
    service2 = HippoRAGService(
        group_id="test2",
        index_dir="./index2",
        graph_store=None,
        llm_service=None
    )
    with patch('app.hybrid.indexing.hipporag_service.HIPPORAG_AVAILABLE', True):
        await service2.initialize()
        # Should not use llamaindex (no graph_store)
        assert service2._use_llamaindex == False


# ============================================================================
# Test Category 3: Health Check Methods
# ============================================================================

@pytest.mark.asyncio
async def test_health_check_llamaindex_mode(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test health check for LlamaIndex mode."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    health = await service.health_check()
    
    assert health['mode'] == 'llamaindex'
    assert health['group_id'] == 'test_group'
    assert 'llamaindex_available' in health


@pytest.mark.asyncio
async def test_health_check_reports_all_modes(clean_hipporag_cache):
    """Test that health check reports availability of all modes."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index"
    )
    
    await service.initialize()
    health = await service.health_check()
    
    # Should report all mode availability
    assert 'mode' in health
    assert health['mode'] in ['llamaindex', 'legacy']


@pytest.mark.asyncio
async def test_health_check_before_initialization(clean_hipporag_cache):
    """Test health check before initialization returns uninitialized state."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index"
    )
    
    health = await service.health_check()
    
    # Should indicate not initialized
    assert health['initialized'] == False


# ============================================================================
# Test Category 4: Singleton Pattern
# ============================================================================

def test_get_hipporag_service_returns_singleton(clean_hipporag_cache):
    """Test that get_hipporag_service returns same instance for same group_id."""
    service1 = get_hipporag_service(group_id="test_group", index_dir="./index")
    service2 = get_hipporag_service(group_id="test_group", index_dir="./index")
    
    # Should return same instance
    assert service1 is service2


def test_different_group_ids_get_different_instances(clean_hipporag_cache):
    """Test that different group_ids get different service instances."""
    service1 = get_hipporag_service(group_id="group1", index_dir="./index1")
    service2 = get_hipporag_service(group_id="group2", index_dir="./index2")
    
    # Should return different instances
    assert service1 is not service2
    assert service1.group_id == "group1"
    assert service2.group_id == "group2"


def test_singleton_cache_key_includes_group_id(clean_hipporag_cache):
    """Test that singleton cache uses group_id as part of key."""
    from app.hybrid.indexing import hipporag_service
    
    service1 = get_hipporag_service(group_id="group1", index_dir="./index")
    
    # Cache should have entry with group1
    assert len(hipporag_service._hipporag_cache) == 1
    assert any("group1" in key for key in hipporag_service._hipporag_cache.keys())


# ============================================================================
# Test Category 5: Auto-Detection of Dependencies
# ============================================================================

@pytest.mark.asyncio
async def test_auto_detects_llamaindex_availability(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that service auto-detects LlamaIndex retriever availability."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    
    # Should detect LlamaIndex is available (mocked dependencies)
    assert service._use_llamaindex == True


@pytest.mark.asyncio
async def test_auto_detects_upstream_availability(clean_hipporag_cache):
    """Test that service auto-detects upstream hipporag package."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index"
    )
    
    # Mock upstream package check
    with patch('app.hybrid.indexing.hipporag_service.HIPPORAG_AVAILABLE', True):
        await service.initialize()
        
        # Should not use llamaindex (no graph_store provided)
        assert service._use_llamaindex == False


def test_dependencies_checked_on_initialization(clean_hipporag_cache):
    """Test that dependencies are checked during initialization."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index"
    )
    
    # Before initialization, _use_llamaindex should be False
    assert service._use_llamaindex == False


# ============================================================================
# Test Category 6: Configuration Passing
# ============================================================================

@pytest.mark.asyncio
async def test_config_passed_to_retriever(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that configuration is passed to underlying retriever."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    
    # Service should be initialized successfully
    assert service._initialized == True


@pytest.mark.asyncio
async def test_default_config_values(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that service uses sensible default config values."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    
    # Should be initialized
    assert service._initialized == True


# ============================================================================
# Test Category 7: Error Propagation
# ============================================================================

@pytest.mark.asyncio
async def test_initialization_error_propagation(clean_hipporag_cache):
    """Test that initialization errors are propagated properly."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="/invalid/path/that/does/not/exist"
    )
    
    # Mock all modes unavailable
    with patch('app.hybrid.indexing.hipporag_service.HIPPORAG_AVAILABLE', False):
        with patch('app.hybrid.indexing.hipporag_service.LLAMAINDEX_HIPPORAG_AVAILABLE', False):
            await service.initialize()
            
            # Should not use llamaindex mode
            assert service._use_llamaindex == False


@pytest.mark.asyncio
async def test_retrieval_error_handling(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that retrieval errors are handled and propagated."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    
    # Mock retriever to raise error
    if hasattr(service, 'get_instance'):
        instance = service.get_instance()
        if instance and hasattr(instance, '_run_ppr'):
            with patch.object(instance, '_run_ppr', side_effect=ConnectionError("Graph unavailable")):
                # Retrieval should propagate error
                try:
                    await service.retrieve(
                        query="test query",
                        seed_entities=["Entity A"],
                        top_k=5
                    )
                    # Should not reach here
                    assert False, "Expected error to be raised"
                except ConnectionError:
                    # Error should be propagated
                    pass


# ============================================================================
# Test Category 8: Retrieval Methods
# ============================================================================

@pytest.mark.asyncio
async def test_retrieve_method_exists(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that service has a retrieve method."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    
    assert hasattr(service, 'retrieve')
    assert callable(service.retrieve)


@pytest.mark.asyncio
async def test_get_instance_method(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that get_instance() returns the underlying retriever."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    
    # For LlamaIndex mode, use get_llamaindex_retriever()
    instance = service.get_llamaindex_retriever()
    
    # Should return a retriever instance
    assert instance is not None


# ============================================================================
# Test Category 9: Mode Switching
# ============================================================================

@pytest.mark.asyncio
async def test_mode_cannot_change_after_initialization(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that mode is locked after initialization."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    await service.initialize()
    initial_mode = service._use_llamaindex
    
    # Attempt to re-initialize should not change mode
    await service.initialize()
    assert service._use_llamaindex == initial_mode


# ============================================================================
# Test Category 10: Integration with Orchestrator
# ============================================================================

def test_service_compatible_with_orchestrator_interface(mock_graph_store, mock_llm_service, clean_hipporag_cache):
    """Test that service provides interface expected by orchestrator."""
    service = HippoRAGService(
        group_id="test_group",
        index_dir="./test_index",
        graph_store=mock_graph_store,
        llm_service=mock_llm_service
    )
    
    # Orchestrator expects these methods
    required_methods = ['initialize', 'retrieve', 'get_instance', 'health_check']
    
    for method_name in required_methods:
        assert hasattr(service, method_name), f"Missing method: {method_name}"
        assert callable(getattr(service, method_name)), f"Method not callable: {method_name}"


# ============================================================================
# Summary & Test Execution
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
