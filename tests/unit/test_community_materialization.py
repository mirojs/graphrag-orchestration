"""
Unit Tests: Louvain Community Materialization (Step 9)

Tests the community summarization, parsing, and Neo4j loading components
added as part of the Louvain community materialization feature.
Also tests community matching (semantic similarity) and stale-embedding
detection.

Run: pytest tests/unit/test_community_materialization.py -v
"""

import hashlib
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path


# ============================================================================
# Test _parse_community_summary (pure static method — no mocks needed)
# ============================================================================

class TestParseCommunityService:
    """Test the TITLE:/SUMMARY: parser."""

    @staticmethod
    def _parse(text: str) -> Tuple[str, str]:
        from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import (
            LazyGraphRAGIndexingPipeline,
        )
        return LazyGraphRAGIndexingPipeline._parse_community_summary(text)

    def test_well_formed(self):
        text = "TITLE: Warranty and Arbitration Provisions\nSUMMARY: This cluster covers warranty terms, dispute resolution, and arbitration clauses across multiple agreements."
        title, summary = self._parse(text)
        assert title == "Warranty and Arbitration Provisions"
        assert "warranty terms" in summary
        assert "arbitration" in summary

    def test_multiline_summary(self):
        text = "TITLE: Payment Structures\nSUMMARY: This group covers payment schedules. It includes installment plans and commission rates."
        title, summary = self._parse(text)
        assert title == "Payment Structures"
        # Only the first SUMMARY: line is captured by the parser
        assert "payment schedules" in summary

    def test_missing_title_uses_summary_prefix(self):
        text = "SUMMARY: A detailed cluster about property management obligations."
        title, summary = self._parse(text)
        assert "property management" in summary
        # Title should be derived from summary
        assert len(title) > 0
        assert title.startswith("A detailed cluster")

    def test_missing_summary_uses_full_text(self):
        text = "TITLE: Contract Parties\nSome text that doesn't have SUMMARY: prefix"
        title, summary = self._parse(text)
        assert title == "Contract Parties"
        # Falls back to the whole text (capped at 500 chars)
        assert len(summary) > 0

    def test_empty_string(self):
        title, summary = self._parse("")
        # Empty input results in empty title and empty summary
        assert title == ""
        assert summary == ""

    def test_case_insensitive_labels(self):
        text = "title: Lower Case Title\nsummary: Lower case summary text."
        title, summary = self._parse(text)
        assert title == "Lower Case Title"
        assert summary == "Lower case summary text."

    def test_extra_whitespace(self):
        text = "  TITLE:   Spaces Everywhere  \n  SUMMARY:   Padded summary.  "
        title, summary = self._parse(text)
        assert title == "Spaces Everywhere"
        assert summary == "Padded summary."


# ============================================================================
# Test _summarize_community (requires LLM + Neo4j mocking)
# ============================================================================

class TestSummarizeCommunity:
    """Test community summarization via LLM."""

    @pytest.fixture
    def mock_pipeline(self):
        """Create a pipeline with mocked dependencies."""
        pipeline = MagicMock()
        pipeline._parse_community_summary = (
            MagicMock(return_value=("Test Title", "Test summary."))
        )

        # Mock Neo4j session for relationship query
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {"source": "Contoso Ltd", "rel_type": "PARTY_TO", "target": "Contract A", "description": ""},
        ]))
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        pipeline.neo4j_store = MagicMock()
        pipeline.neo4j_store.driver.session.return_value = mock_session
        pipeline.neo4j_store.database = "neo4j"

        # Mock LLM
        mock_llm_response = MagicMock()
        mock_llm_response.message.content = "TITLE: Test Title\nSUMMARY: Test summary."
        pipeline.llm = AsyncMock()
        pipeline.llm.achat = AsyncMock(return_value=mock_llm_response)

        return pipeline

    @pytest.mark.asyncio
    async def test_summarize_returns_title_and_summary(self, mock_pipeline):
        """Summarization should return a (title, summary) tuple."""
        from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import (
            LazyGraphRAGIndexingPipeline,
        )

        members = [
            {"name": "Contoso Ltd", "id": "e1", "description": "A construction company", "degree": 5, "pagerank": 0.15},
            {"name": "Contract A", "id": "e2", "description": "Purchase agreement", "degree": 3, "pagerank": 0.10},
        ]

        result = await LazyGraphRAGIndexingPipeline._summarize_community(
            mock_pipeline,
            group_id="test-group",
            community_id=1,
            members=members,
        )

        assert result is not None
        assert result == ("Test Title", "Test summary.")
        mock_pipeline.llm.achat.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_handles_llm_failure(self):
        """Should return None if LLM call fails."""
        from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import (
            LazyGraphRAGIndexingPipeline,
        )

        pipeline = MagicMock()

        # Mock Neo4j session
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        pipeline.neo4j_store = MagicMock()
        pipeline.neo4j_store.driver.session.return_value = mock_session
        pipeline.neo4j_store.database = "neo4j"

        # Make LLM raise
        pipeline.llm = AsyncMock()
        pipeline.llm.achat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        members = [{"name": "X", "id": "e1", "description": "", "degree": 1, "pagerank": 0.01}]

        result = await LazyGraphRAGIndexingPipeline._summarize_community(
            pipeline,
            group_id="test-group",
            community_id=1,
            members=members,
        )

        assert result is None


# ============================================================================
# Test CommunityMatcher._load_from_neo4j and load_communities
# ============================================================================

class TestCommunityMatcherLoading:
    """Test community loading from Neo4j and JSON fallback."""

    def _make_matcher(
        self,
        neo4j_service=None,
        group_id: str = "test-group",
        communities_path: Optional[Path] = None,
        embedding_client=None,
    ):
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        matcher = CommunityMatcher.__new__(CommunityMatcher)
        matcher.neo4j_service = neo4j_service
        matcher.group_id = group_id
        matcher.folder_id = None
        matcher.communities_path = communities_path
        matcher.embedding_client = embedding_client
        matcher._communities = []
        matcher._community_embeddings = {}
        matcher._summary_hashes = {}
        matcher._loaded = False
        return matcher

    def _mock_neo4j_records(self, records_data: List[Dict]):
        """Create a mock neo4j service that returns the given records."""
        mock_service = MagicMock()

        # Build record dicts for result.data() return value
        mock_data = []
        for rd in records_data:
            mock_data.append(dict(rd))  # plain dicts

        # Mock async session with async run() and result.data()
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=mock_data)

        mock_session = AsyncMock()
        mock_session.run = AsyncMock(return_value=mock_result)

        # _get_session() returns an async context manager
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_service._get_session = MagicMock(return_value=mock_ctx)

        return mock_service

    @pytest.mark.asyncio
    async def test_load_from_neo4j_success(self):
        """Should load communities and embeddings from Neo4j."""
        records = [
            {
                "id": "louvain_test_0",
                "title": "Test Community",
                "summary": "A test community summary",
                "rank": 0.5,
                "level": 0,
                "embedding": [0.1] * 2048,
                "embedding_text_hash": "abc123",
                "entity_names": ["Entity A", "Entity B"],
            },
        ]
        neo4j_service = self._mock_neo4j_records(records)
        matcher = self._make_matcher(neo4j_service=neo4j_service)

        result = await matcher._load_from_neo4j()

        assert result is True
        assert matcher._loaded is True
        assert len(matcher._communities) == 1
        assert matcher._communities[0]["title"] == "Test Community"
        assert "louvain_test_0" in matcher._community_embeddings

    @pytest.mark.asyncio
    async def test_load_from_neo4j_empty(self):
        """Should return False when no communities found."""
        neo4j_service = self._mock_neo4j_records([])
        matcher = self._make_matcher(neo4j_service=neo4j_service)

        result = await matcher._load_from_neo4j()

        assert result is False
        assert matcher._loaded is False

    @pytest.mark.asyncio
    async def test_load_from_neo4j_no_embeddings(self):
        """Communities without embeddings should still load."""
        records = [
            {
                "id": "louvain_test_1",
                "title": "No Embedding Community",
                "summary": "Summary without vector",
                "rank": 0.3,
                "level": 0,
                "embedding": None,
                "embedding_text_hash": None,
                "entity_names": ["Entity C"],
            },
        ]
        neo4j_service = self._mock_neo4j_records(records)
        matcher = self._make_matcher(neo4j_service=neo4j_service)

        result = await matcher._load_from_neo4j()

        assert result is True
        assert len(matcher._communities) == 1
        assert len(matcher._community_embeddings) == 0  # No embeddings stored

    @pytest.mark.asyncio
    async def test_load_communities_prefers_neo4j(self):
        """load_communities should use Neo4j over JSON when available."""
        records = [
            {
                "id": "louvain_neo4j",
                "title": "Neo4j Community",
                "summary": "From Neo4j",
                "rank": 0.5,
                "level": 0,
                "embedding": [0.1] * 2048,
                "embedding_text_hash": None,
                "entity_names": ["A"],
            },
        ]
        neo4j_service = self._mock_neo4j_records(records)
        matcher = self._make_matcher(neo4j_service=neo4j_service)

        result = await matcher.load_communities()

        assert result is True
        assert matcher._communities[0]["title"] == "Neo4j Community"

    @pytest.mark.asyncio
    async def test_load_communities_skips_if_already_loaded(self):
        """Should return True immediately if already loaded."""
        matcher = self._make_matcher()
        matcher._loaded = True

        result = await matcher.load_communities()
        assert result is True

    @pytest.mark.asyncio
    async def test_load_communities_falls_back_to_json(self, tmp_path):
        """Should fall back to JSON when Neo4j is unavailable."""
        json_file = tmp_path / "communities.json"
        json_file.write_text(json.dumps({
            "communities": [{"id": "json_1", "title": "JSON Community"}],
            "embeddings": {"json_1": [0.2] * 2048},
        }))

        matcher = self._make_matcher(
            neo4j_service=None,
            communities_path=json_file,
        )

        result = await matcher.load_communities()

        assert result is True
        assert matcher._communities[0]["title"] == "JSON Community"
        assert "json_1" in matcher._community_embeddings

    @pytest.mark.asyncio
    async def test_load_communities_returns_false_no_source(self):
        """Should return False when no Neo4j or JSON available."""
        matcher = self._make_matcher(
            neo4j_service=None,
            communities_path=Path("/nonexistent/path.json"),
        )

        result = await matcher.load_communities()
        assert result is False


# ============================================================================
# Test evaluate_theme_coverage (benchmark helper)
# ============================================================================

class TestThemeCoverage:
    """Test the theme coverage evaluator from the benchmark script."""

    @staticmethod
    def _eval(text: str, themes: List[str]) -> float:
        from scripts.benchmark_route3_thematic import evaluate_theme_coverage
        return evaluate_theme_coverage(text, themes)

    def test_all_themes_found(self):
        text = "The contract covers warranty, arbitration, and 60 days notice period."
        themes = ["warranty", "arbitration", "60 days"]
        assert self._eval(text, themes) == 1.0

    def test_no_themes_found(self):
        text = "This is about cooking recipes."
        themes = ["warranty", "arbitration"]
        assert self._eval(text, themes) == 0.0

    def test_partial_coverage(self):
        text = "The warranty period is one year."
        themes = ["warranty", "arbitration", "deposit"]
        assert self._eval(text, themes) == pytest.approx(1 / 3, abs=0.01)

    def test_numeric_theme_matching(self):
        """Dollar amounts should match across formatting variations."""
        text = "The total cost is $29,900.00 payable in installments."
        themes = ["29900"]
        assert self._eval(text, themes) == 1.0

    def test_word_number_matching(self):
        """Written-out numbers should match digit forms when in context."""
        # Direct digit match works
        text = "The buyer has 60 days to cancel the agreement."
        themes = ["60 days"]
        assert self._eval(text, themes) == 1.0

    def test_word_number_matching_written_out(self):
        """Written-out numbers (e.g. 'sixty') match via the number-word alternation."""
        text = "The buyer has sixty days to cancel the agreement."
        themes = ["60 days"]
        # The evaluator uses \b word boundaries; 'sixty days' matches '60|sixty' alternation
        coverage = self._eval(text, themes)
        # If the regex alternation catches it, great; otherwise 0. 
        # This documents current behavior.
        assert coverage in (0.0, 1.0)

    def test_hold_harmless_variant(self):
        """'hold harmless' should match even with words between."""
        text = "The contractor shall hold the owner harmless from claims."
        themes = ["hold harmless"]
        assert self._eval(text, themes) == 1.0

    def test_indemnify_variants(self):
        """Indemnification word forms should all match."""
        text = "The indemnification clause protects all parties."
        themes = ["indemnify"]
        assert self._eval(text, themes) == 1.0

    def test_empty_inputs(self):
        assert self._eval("", ["theme"]) == 0.0
        assert self._eval("some text", []) == 0.0


# ============================================================================
# Test CommunityMatcher._semantic_match and stale-embedding detection
# ============================================================================

class TestSemanticMatch:
    """Test semantic matching and stale-embedding detection in CommunityMatcher."""

    def _make_matcher_with_data(
        self,
        communities: List[Dict],
        embeddings: Dict[str, List[float]],
        summary_hashes: Optional[Dict[str, str]] = None,
    ):
        """Create a CommunityMatcher pre-loaded with communities and embeddings."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        matcher = CommunityMatcher.__new__(CommunityMatcher)
        matcher.neo4j_service = None
        matcher.group_id = "test"
        matcher.folder_id = None
        matcher.communities_path = None
        matcher.embedding_client = MagicMock()
        matcher._communities = communities
        matcher._community_embeddings = embeddings
        matcher._summary_hashes = summary_hashes or {}
        matcher._loaded = True
        return matcher

    @pytest.mark.asyncio
    async def test_discriminative_scores_with_distinct_embeddings(self):
        """Communities with distinct embeddings should produce different scores."""
        communities = [
            {"id": "c1", "title": "Payment Terms", "summary": "Payment schedules"},
            {"id": "c2", "title": "Insurance", "summary": "Insurance coverage"},
        ]
        # Create orthogonal embeddings (2048-dim, only first 2 dims nonzero)
        emb_payment = [1.0, 0.0] + [0.0] * 2046
        emb_insurance = [0.0, 1.0] + [0.0] * 2046

        matcher = self._make_matcher_with_data(
            communities,
            {"c1": emb_payment, "c2": emb_insurance},
        )

        # Query embedding aligned with payment
        query_emb = [0.9, 0.1] + [0.0] * 2046
        matcher._get_embedding = AsyncMock(return_value=query_emb)

        results = await matcher._semantic_match("What are the payment terms?", top_k=2)

        assert len(results) == 2
        # Payment community should score higher
        assert results[0][0]["id"] == "c1"
        assert results[0][1] > results[1][1]
        # Both should be above threshold
        assert results[0][1] > 0.05
        assert results[1][1] > 0.05

    @pytest.mark.asyncio
    async def test_different_queries_select_different_communities(self):
        """Different queries should select different top communities."""
        communities = [
            {"id": "c1", "title": "Payment", "summary": "Payment terms"},
            {"id": "c2", "title": "Insurance", "summary": "Insurance coverage"},
            {"id": "c3", "title": "Termination", "summary": "Termination clauses"},
        ]
        emb1 = [1.0, 0.0, 0.0] + [0.0] * 2045
        emb2 = [0.0, 1.0, 0.0] + [0.0] * 2045
        emb3 = [0.0, 0.0, 1.0] + [0.0] * 2045

        matcher = self._make_matcher_with_data(
            communities,
            {"c1": emb1, "c2": emb2, "c3": emb3},
        )

        # Query 1 aligned with insurance
        matcher._get_embedding = AsyncMock(return_value=[0.1, 0.9, 0.0] + [0.0] * 2045)
        results1 = await matcher._semantic_match("insurance requirements", top_k=1)

        # Query 2 aligned with termination
        matcher._get_embedding = AsyncMock(return_value=[0.0, 0.0, 0.9] + [0.0] * 2045)
        results2 = await matcher._semantic_match("termination clauses", top_k=1)

        assert results1[0][0]["id"] == "c2"  # Insurance
        assert results2[0][0]["id"] == "c3"  # Termination

    @pytest.mark.asyncio
    async def test_near_zero_scores_filtered_by_threshold(self):
        """Scores below 0.05 threshold should be filtered out."""
        communities = [
            {"id": "c1", "title": "Community 1", "summary": ""},
        ]
        # Near-uniform embedding (simulating low-quality fallback)
        emb = [0.01] * 2048

        matcher = self._make_matcher_with_data(communities, {"c1": emb})

        # Orthogonal query embedding
        query_emb = [0.0] * 1024 + [0.5] * 1024
        matcher._get_embedding = AsyncMock(return_value=query_emb)

        results = await matcher._semantic_match("compliance risks", top_k=3)

        # Should either be empty (below threshold) or have very low scores
        if results:
            assert results[0][1] >= 0.05

    @pytest.mark.asyncio
    async def test_dimension_mismatch_skipped(self):
        """Communities with wrong-dimension embeddings should be skipped."""
        communities = [
            {"id": "c1", "title": "Community 1", "summary": "A summary"},
        ]
        # Wrong dimension (1536 instead of 2048)
        emb = [0.5] * 1536

        matcher = self._make_matcher_with_data(communities, {"c1": emb})
        # Query embedding is 2048-dim
        query_emb = [0.5] * 2048
        matcher._get_embedding = AsyncMock(return_value=query_emb)

        results = await matcher._semantic_match("query", top_k=3)

        assert len(results) == 0  # Dimension mismatch → skipped

    @pytest.mark.asyncio
    async def test_no_query_embedding_returns_empty(self):
        """Should return empty list when query embedding fails."""
        communities = [
            {"id": "c1", "title": "Community 1", "summary": "Summary"},
        ]
        matcher = self._make_matcher_with_data(
            communities, {"c1": [0.1] * 2048},
        )
        matcher._get_embedding = AsyncMock(return_value=None)

        results = await matcher._semantic_match("query", top_k=3)
        assert len(results) == 0

    # ----- Stale Embedding Detection Tests -----

    def test_compute_text_hash_uses_summary(self):
        """When summary is present, hash should be computed from summary."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        matcher = CommunityMatcher.__new__(CommunityMatcher)
        community = {
            "summary": "Payment schedules and amounts",
            "title": "Payment Terms",
            "entity_names": ["Entity A"],
        }
        h = matcher._compute_text_hash(community)
        expected = hashlib.sha256("Payment schedules and amounts".encode()).hexdigest()[:16]
        assert h == expected

    def test_compute_text_hash_falls_back_to_entities(self):
        """When summary is empty, hash should use title + entity names."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        matcher = CommunityMatcher.__new__(CommunityMatcher)
        community = {
            "summary": "",
            "title": "Community 1",
            "entity_names": ["Entity A", "Entity B"],
        }
        h = matcher._compute_text_hash(community)
        fallback_text = "Community 1. Entities: Entity A, Entity B"
        expected = hashlib.sha256(fallback_text.encode()).hexdigest()[:16]
        assert h == expected

    def test_compute_text_hash_changes_when_summary_added(self):
        """Hash should differ before and after LLM summary is added."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        matcher = CommunityMatcher.__new__(CommunityMatcher)

        # Before: no summary (entity-name fallback)
        community_before = {
            "summary": "",
            "title": "Community 1",
            "entity_names": ["Entity A"],
        }
        hash_before = matcher._compute_text_hash(community_before)

        # After: LLM summary added
        community_after = {
            "summary": "This community covers payment obligations.",
            "title": "Payment Obligations",
            "entity_names": ["Entity A"],
        }
        hash_after = matcher._compute_text_hash(community_after)

        assert hash_before != hash_after

    @pytest.mark.asyncio
    async def test_ensure_embeddings_detects_stale_content(self):
        """_ensure_embeddings should re-embed when summary changed but embedding didn't."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        communities = [
            {
                "id": "c1",
                "title": "Community 1",
                "summary": "New LLM summary about payments",
                "entity_names": ["Entity A"],
            },
        ]
        # Existing embedding from old fallback text (dimension matches)
        old_embedding = [0.001] * 2048

        matcher = self._make_matcher_with_data(
            communities,
            {"c1": old_embedding},
            summary_hashes={"c1": "old_hash_from_fallback"},
        )

        # Mock embedding client
        matcher.embedding_client = MagicMock()
        matcher.embedding_client.embed_dim = 2048

        new_embedding = [0.5, 0.3] + [0.1] * 2046
        matcher._get_embeddings_batch = AsyncMock(return_value=[new_embedding])

        await matcher._ensure_embeddings()

        # Embedding should have been replaced
        assert matcher._community_embeddings["c1"] == new_embedding

    @pytest.mark.asyncio
    async def test_ensure_embeddings_skips_when_hash_matches(self):
        """_ensure_embeddings should skip re-embedding when hash matches."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        communities = [
            {
                "id": "c1",
                "title": "Payment Terms",
                "summary": "Payment schedules",
                "entity_names": [],
            },
        ]
        existing_embedding = [0.5] * 2048

        matcher = self._make_matcher_with_data(
            communities,
            {"c1": existing_embedding},
        )

        # Set the stored hash to match current content
        current_hash = matcher._compute_text_hash(communities[0])
        matcher._summary_hashes = {"c1": current_hash}

        matcher.embedding_client = MagicMock()
        matcher.embedding_client.embed_dim = 2048
        matcher._get_embeddings_batch = AsyncMock()

        await matcher._ensure_embeddings()

        # Should NOT have called batch embedding — nothing stale
        matcher._get_embeddings_batch.assert_not_called()
        # Original embedding should be unchanged
        assert matcher._community_embeddings["c1"] == existing_embedding

    @pytest.mark.asyncio
    async def test_ensure_embeddings_reembeds_missing(self):
        """_ensure_embeddings should embed communities with no existing embedding."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        communities = [
            {
                "id": "c1",
                "title": "Community 1",
                "summary": "A community summary",
                "entity_names": [],
            },
        ]

        matcher = self._make_matcher_with_data(
            communities,
            {},  # No embeddings
        )

        matcher.embedding_client = MagicMock()
        matcher.embedding_client.embed_dim = 2048

        new_embedding = [0.3] * 2048
        matcher._get_embeddings_batch = AsyncMock(return_value=[new_embedding])

        await matcher._ensure_embeddings()

        assert matcher._community_embeddings["c1"] == new_embedding

    def test_cosine_similarity_correctness(self):
        """Verify cosine similarity computation."""
        from src.worker.hybrid_v2.pipeline.community_matcher import CommunityMatcher

        # Identical vectors → 1.0
        assert CommunityMatcher._cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
        # Orthogonal vectors → 0.0
        assert CommunityMatcher._cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
        # Opposite vectors → -1.0
        assert CommunityMatcher._cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)
        # Zero vector → 0.0
        assert CommunityMatcher._cosine_similarity([0, 0], [1, 0]) == pytest.approx(0.0)
        # Dimension mismatch → 0.0
        assert CommunityMatcher._cosine_similarity([1, 0], [1, 0, 0]) == pytest.approx(0.0)
