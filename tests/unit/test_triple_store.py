"""
Unit Tests: Triple Embedding Store + Recognition Memory Filter

Tests the HippoRAG 2 query-to-triple linking and LLM recognition memory
filtering used in Route 7.

Run: pytest tests/unit/test_triple_store.py -v
"""

import importlib.util
import sys

import pytest
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch

# Direct import to avoid the full app dependency chain triggered by
# hybrid_v2.__init__.py  →  orchestrator  →  routes  →  config  →  pydantic_settings
_spec = importlib.util.spec_from_file_location(
    "triple_store",
    "src/worker/hybrid_v2/retrievers/triple_store.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["triple_store"] = _mod
_spec.loader.exec_module(_mod)
Triple = _mod.Triple
TripleEmbeddingStore = _mod.TripleEmbeddingStore
recognition_memory_filter = _mod.recognition_memory_filter


# ============================================================================
# Test Data
# ============================================================================

def make_triple(subj_name: str, pred: str, obj_name: str) -> Triple:
    """Create a test Triple."""
    return Triple(
        subject_id=f"id_{subj_name.lower().replace(' ', '_')}",
        subject_name=subj_name,
        predicate=pred,
        object_id=f"id_{obj_name.lower().replace(' ', '_')}",
        object_name=obj_name,
        triple_text=f"{subj_name} {pred} {obj_name}",
    )


SAMPLE_TRIPLES = [
    make_triple("Alpha Corp", "acquired", "Beta Fund"),
    make_triple("Beta Fund", "manages", "Gamma LLC"),
    make_triple("Delta Inc", "is subsidiary of", "Alpha Corp"),
    make_triple("Gamma LLC", "headquartered in", "New York"),
    make_triple("Alpha Corp", "founded in", "2010"),
]


# ============================================================================
# Test Category 1: TripleEmbeddingStore Search
# ============================================================================

class TestTripleEmbeddingStoreSearch:
    """Test the cosine similarity search on cached embeddings."""

    def _build_loaded_store(self) -> TripleEmbeddingStore:
        """Build a store with pre-loaded synthetic embeddings."""
        store = TripleEmbeddingStore()
        store._triples = list(SAMPLE_TRIPLES)

        # Create 5 synthetic embeddings (4-dim for simplicity)
        # Each triple gets a distinct direction
        raw = np.array([
            [1.0, 0.0, 0.0, 0.0],   # Triple 0: Alpha acquired Beta
            [0.0, 1.0, 0.0, 0.0],   # Triple 1: Beta manages Gamma
            [0.5, 0.5, 0.0, 0.0],   # Triple 2: Delta subsidiary of Alpha
            [0.0, 0.0, 1.0, 0.0],   # Triple 3: Gamma in New York
            [0.0, 0.0, 0.0, 1.0],   # Triple 4: Alpha founded 2010
        ], dtype=np.float32)

        # Normalize
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        store._embeddings_matrix = raw / norms
        store._loaded = True
        return store

    def test_search_returns_correct_count(self):
        """Search should return at most top_k results."""
        store = self._build_loaded_store()
        query_emb = [1.0, 0.0, 0.0, 0.0]
        results = store.search(query_emb, top_k=3)
        assert len(results) == 3

    def test_search_top_k_exceeds_total(self):
        """top_k larger than total triples should return all triples."""
        store = self._build_loaded_store()
        query_emb = [1.0, 0.0, 0.0, 0.0]
        results = store.search(query_emb, top_k=100)
        assert len(results) == 5

    def test_search_sorted_descending(self):
        """Results should be sorted by score descending."""
        store = self._build_loaded_store()
        query_emb = [1.0, 0.0, 0.0, 0.0]
        results = store.search(query_emb, top_k=5)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_best_match(self):
        """Query aligned with triple 0 embedding should return triple 0 first."""
        store = self._build_loaded_store()
        query_emb = [1.0, 0.0, 0.0, 0.0]  # Aligned with triple 0
        results = store.search(query_emb, top_k=1)
        top_triple, top_score = results[0]
        assert top_triple.subject_name == "Alpha Corp"
        assert top_triple.predicate == "acquired"
        assert top_score > 0.9  # High cosine similarity

    def test_search_orthogonal_query(self):
        """Query orthogonal to all triples should have low scores."""
        store = self._build_loaded_store()
        # Orthogonal to all our 4D basis vectors? Not possible with 4D basis,
        # but a mixed vector should have lower max score than aligned
        query_emb = [0.25, 0.25, 0.25, 0.25]
        results = store.search(query_emb, top_k=5)
        # All scores should be moderate (around 0.5)
        scores = [s for _, s in results]
        assert max(scores) < 0.9

    def test_search_zero_query(self):
        """Zero query vector should return empty."""
        store = self._build_loaded_store()
        results = store.search([0.0, 0.0, 0.0, 0.0], top_k=5)
        assert results == []

    def test_search_not_loaded(self):
        """Search on unloaded store should return empty."""
        store = TripleEmbeddingStore()
        results = store.search([1.0, 0.0], top_k=5)
        assert results == []

    def test_triple_count_property(self):
        """triple_count should reflect loaded triples."""
        store = self._build_loaded_store()
        assert store.triple_count == 5

    def test_loaded_property(self):
        """loaded flag should reflect initialization state."""
        store = TripleEmbeddingStore()
        assert not store.loaded
        store._loaded = True
        assert store.loaded


# ============================================================================
# Test Category 2: Recognition Memory Filter
# ============================================================================

class TestRecognitionMemoryFilter:
    """Test the LLM-based recognition memory filtering."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM client."""
        llm = MagicMock()
        llm.acomplete = AsyncMock()
        return llm

    @pytest.fixture
    def sample_candidates(self):
        """Create sample (Triple, score) pairs."""
        return [
            (SAMPLE_TRIPLES[0], 0.95),
            (SAMPLE_TRIPLES[1], 0.82),
            (SAMPLE_TRIPLES[2], 0.71),
            (SAMPLE_TRIPLES[3], 0.55),
            (SAMPLE_TRIPLES[4], 0.42),
        ]

    @pytest.mark.asyncio
    async def test_selects_relevant_triples(self, mock_llm, sample_candidates):
        """LLM returning "1, 3" should keep triples 1 and 3."""
        response = MagicMock()
        response.text = "1, 3"
        mock_llm.acomplete.return_value = response

        result = await recognition_memory_filter(
            mock_llm, "What did Alpha Corp acquire?", sample_candidates
        )
        assert len(result) == 2
        assert result[0].subject_name == "Alpha Corp"
        assert result[0].predicate == "acquired"
        assert result[1].subject_name == "Delta Inc"

    @pytest.mark.asyncio
    async def test_none_response_returns_empty(self, mock_llm, sample_candidates):
        """LLM returning 'NONE' should result in empty list."""
        response = MagicMock()
        response.text = "NONE"
        mock_llm.acomplete.return_value = response

        result = await recognition_memory_filter(
            mock_llm, "Irrelevant query", sample_candidates
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_all_selected(self, mock_llm, sample_candidates):
        """LLM returning all indices keeps all triples."""
        response = MagicMock()
        response.text = "1, 2, 3, 4, 5"
        mock_llm.acomplete.return_value = response

        result = await recognition_memory_filter(
            mock_llm, "Tell me everything", sample_candidates
        )
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_single_selection(self, mock_llm, sample_candidates):
        """LLM returning a single number should work."""
        response = MagicMock()
        response.text = "2"
        mock_llm.acomplete.return_value = response

        result = await recognition_memory_filter(
            mock_llm, "What does Beta Fund manage?", sample_candidates
        )
        assert len(result) == 1
        assert result[0].subject_name == "Beta Fund"

    @pytest.mark.asyncio
    async def test_invalid_indices_ignored(self, mock_llm, sample_candidates):
        """Out-of-range indices should be silently ignored."""
        response = MagicMock()
        response.text = "1, 99, 2"
        mock_llm.acomplete.return_value = response

        result = await recognition_memory_filter(
            mock_llm, "Alpha Corp history", sample_candidates
        )
        assert len(result) == 2  # indices 1 and 2, 99 ignored

    @pytest.mark.asyncio
    async def test_llm_failure_passes_through_all(self, mock_llm, sample_candidates):
        """On LLM failure, all candidates should be passed through."""
        mock_llm.acomplete.side_effect = RuntimeError("LLM timeout")

        result = await recognition_memory_filter(
            mock_llm, "query", sample_candidates
        )
        assert len(result) == 5  # All passed through on failure

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self, mock_llm):
        """Empty candidate list should return empty without calling LLM."""
        result = await recognition_memory_filter(mock_llm, "query", [])
        assert result == []
        mock_llm.acomplete.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_prompt_contains_query(self, mock_llm, sample_candidates):
        """The prompt sent to LLM should contain the query."""
        response = MagicMock()
        response.text = "1"
        mock_llm.acomplete.return_value = response

        query = "What are Alpha Corp's subsidiaries?"
        await recognition_memory_filter(mock_llm, query, sample_candidates)

        prompt_arg = mock_llm.acomplete.call_args[0][0]
        assert query in prompt_arg

    @pytest.mark.asyncio
    async def test_llm_prompt_contains_triple_text(self, mock_llm, sample_candidates):
        """The prompt should contain all triple texts."""
        response = MagicMock()
        response.text = "NONE"
        mock_llm.acomplete.return_value = response

        await recognition_memory_filter(mock_llm, "query", sample_candidates)

        prompt_arg = mock_llm.acomplete.call_args[0][0]
        for triple, _ in sample_candidates:
            assert triple.triple_text in prompt_arg

    @pytest.mark.asyncio
    async def test_handles_whitespace_in_response(self, mock_llm, sample_candidates):
        """LLM responses with extra whitespace should be handled."""
        response = MagicMock()
        response.text = "  1 ,  3 , 5  "
        mock_llm.acomplete.return_value = response

        result = await recognition_memory_filter(
            mock_llm, "query", sample_candidates
        )
        assert len(result) == 3


# ============================================================================
# Test Category 3: Triple Dataclass
# ============================================================================

class TestTripleDataclass:
    """Test the Triple dataclass."""

    def test_triple_creation(self):
        t = Triple(
            subject_id="s1",
            subject_name="Alpha",
            predicate="acquired",
            object_id="o1",
            object_name="Beta",
            triple_text="Alpha acquired Beta",
        )
        assert t.subject_name == "Alpha"
        assert t.predicate == "acquired"
        assert t.object_name == "Beta"
        assert t.embedding is None

    def test_triple_text_format(self):
        t = make_triple("A", "relates to", "B")
        assert t.triple_text == "A relates to B"

    def test_triple_ids_generated(self):
        t = make_triple("Alpha Corp", "acquired", "Beta Fund")
        assert t.subject_id == "id_alpha_corp"
        assert t.object_id == "id_beta_fund"
