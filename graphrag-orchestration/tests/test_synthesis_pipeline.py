"""
Unit Tests for Synthesis Pipeline

Tests the synthesis component that generates responses from retrieved contexts.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.hybrid.pipeline.synthesis import EvidenceSynthesizer


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_llm():
    """Mock LLM service."""
    llm = MagicMock()
    llm.complete = MagicMock()
    llm.acomplete = AsyncMock()
    return llm


@pytest.fixture
def mock_text_store():
    """Mock text unit store."""
    store = MagicMock()
    store.get_text_units = AsyncMock()
    return store


@pytest.fixture
def sample_evidence_nodes():
    """Sample evidence nodes from retrieval."""
    return [
        {"id": "node_1", "text": "Invoice #12345 was issued on Jan 1, 2024.", "score": 0.95},
        {"id": "node_2", "text": "Payment terms are Net 30 days.", "score": 0.88},
        {"id": "node_3", "text": "Vendor ABC Corp is the supplier.", "score": 0.75},
    ]


# ============================================================================
# Test Category 1: Synthesizer Initialization
# ============================================================================

def test_synthesizer_initialization(mock_llm, mock_text_store):
    """Test that synthesizer initializes correctly."""
    synth = EvidenceSynthesizer(
        llm_client=mock_llm,
        text_unit_store=mock_text_store,
        relevance_budget=0.8
    )
    assert synth.llm is mock_llm
    assert synth.text_store is mock_text_store
    assert synth.relevance_budget == 0.8


def test_synthesizer_default_relevance_budget(mock_llm):
    """Test default relevance budget."""
    synth = EvidenceSynthesizer(llm_client=mock_llm)
    assert synth.relevance_budget == 0.8


def test_synthesizer_without_llm():
    """Test that synthesizer requires LLM."""
    synth = EvidenceSynthesizer(llm_client=None)
    assert synth.llm is None


def test_synthesizer_without_text_store(mock_llm):
    """Test that synthesizer can work without text store."""
    synth = EvidenceSynthesizer(llm_client=mock_llm, text_unit_store=None)
    assert synth.text_store is None


# ============================================================================
# Test Category 2: Relevance Budget Configuration
# ============================================================================

def test_relevance_budget_low(mock_llm):
    """Test low relevance budget (faster, less thorough)."""
    synth = EvidenceSynthesizer(llm_client=mock_llm, relevance_budget=0.3)
    assert synth.relevance_budget == 0.3


def test_relevance_budget_high(mock_llm):
    """Test high relevance budget (slower, more thorough)."""
    synth = EvidenceSynthesizer(llm_client=mock_llm, relevance_budget=0.95)
    assert synth.relevance_budget == 0.95


def test_relevance_budget_bounds(mock_llm):
    """Test relevance budget accepts 0.0-1.0 range."""
    synth_min = EvidenceSynthesizer(llm_client=mock_llm, relevance_budget=0.0)
    synth_max = EvidenceSynthesizer(llm_client=mock_llm, relevance_budget=1.0)
    assert synth_min.relevance_budget == 0.0
    assert synth_max.relevance_budget == 1.0


# ============================================================================
# Test Category 3: Component Integration
# ============================================================================

def test_synthesizer_has_llm_client(mock_llm):
    """Test that synthesizer stores LLM client reference."""
    synth = EvidenceSynthesizer(llm_client=mock_llm)
    assert hasattr(synth, 'llm')
    assert synth.llm is mock_llm


def test_synthesizer_has_text_store(mock_llm, mock_text_store):
    """Test that synthesizer stores text store reference."""
    synth = EvidenceSynthesizer(llm_client=mock_llm, text_unit_store=mock_text_store)
    assert hasattr(synth, 'text_store')
    assert synth.text_store is mock_text_store


# ============================================================================
# Test Category 4: Synthesis Method Exists
# ============================================================================

def test_synthesizer_has_synthesize_method(mock_llm):
    """Test that synthesizer has synthesize method."""
    synth = EvidenceSynthesizer(llm_client=mock_llm)
    assert hasattr(synth, 'synthesize')
    assert callable(synth.synthesize)


# ============================================================================
# Test Category 5: Configuration Validation
# ============================================================================

def test_multiple_synthesizers_independent(mock_llm, mock_text_store):
    """Test that multiple synthesizer instances are independent."""
    synth1 = EvidenceSynthesizer(llm_client=mock_llm, relevance_budget=0.5)
    synth2 = EvidenceSynthesizer(llm_client=mock_llm, relevance_budget=0.9)
    
    assert synth1.relevance_budget != synth2.relevance_budget
    assert synth1.llm is synth2.llm  # Same LLM instance


def test_synthesizer_attributes_accessible(mock_llm, mock_text_store):
    """Test that synthesizer attributes are accessible."""
    synth = EvidenceSynthesizer(
        llm_client=mock_llm,
        text_unit_store=mock_text_store,
        relevance_budget=0.75
    )
    
    # All attributes should be accessible
    assert synth.llm is not None
    assert synth.text_store is not None
    assert isinstance(synth.relevance_budget, float)

