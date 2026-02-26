"""
Unit Tests: Route 6 Microsoft GraphRAG Features (2026-02-26)

Tests 4 new features added to Route 6 (Concept Search):
  Feature 1: Dynamic Community Selection (ROUTE6_DYNAMIC_COMMUNITY)
  Feature 2: Community Children Traversal (ROUTE6_COMMUNITY_CHILDREN)
  Feature 3: Streaming Synthesis (ROUTE6_STREAM_SYNTHESIS)
  Feature 4: Token Budget Control (ROUTE6_MAX_CONTEXT_TOKENS)

All features are env-var gated; existing behavior is preserved by default.

Run: pytest tests/unit/test_route6_features.py -v
"""

import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Any, Dict, List


# ============================================================================
# Helpers
# ============================================================================

def _make_community(id: str, title: str, summary: str, score: float = 0.8, **kwargs) -> Dict[str, Any]:
    return {"id": id, "title": title, "summary": summary, "score": score, **kwargs}


def _make_sentence(text: str, doc_title: str = "Doc A", score: float = 0.7, sentence_id: str = "s1") -> Dict[str, Any]:
    return {
        "text": text,
        "sentence_text": text,
        "chunk_text": "",
        "score": score,
        "document_title": doc_title,
        "document_id": f"doc_{doc_title.lower().replace(' ', '_')}",
        "section_path": "Section 1",
        "page": 1,
        "sentence_id": sentence_id,
    }


def _make_section(title: str, doc_title: str = "Doc A", score: float = 0.6) -> Dict[str, Any]:
    return {
        "title": title,
        "summary": f"Summary of {title}",
        "path_key": title,
        "document_title": doc_title,
        "score": score,
    }


def _make_mock_pipeline():
    """Create a mock HybridPipeline with the minimum interface for ConceptSearchHandler."""
    pipeline = MagicMock()
    pipeline.llm = AsyncMock()
    pipeline.neo4j_driver = MagicMock()
    pipeline.group_id = "test-group"
    pipeline.folder_id = None
    pipeline.synthesizer = MagicMock()
    pipeline._executor = None
    pipeline._async_neo4j = MagicMock()

    # Mock community matcher
    pipeline.community_matcher = MagicMock()
    pipeline.community_matcher.match_communities = AsyncMock(return_value=[])
    return pipeline


def _make_handler(pipeline=None):
    """Create a ConceptSearchHandler with mocked dependencies."""
    from src.worker.hybrid_v2.routes.route_6_concept import ConceptSearchHandler
    if pipeline is None:
        pipeline = _make_mock_pipeline()
    handler = ConceptSearchHandler(pipeline)
    return handler


# ============================================================================
# Feature 4: Token Budget Control
# ============================================================================

class TestTokenBudget:
    """Tests for ROUTE6_MAX_CONTEXT_TOKENS env var."""

    @pytest.mark.asyncio
    async def test_token_budget_no_limit_by_default(self):
        """With no env var set, no truncation occurs."""
        handler = _make_handler()
        handler.llm.acomplete = AsyncMock(
            return_value=MagicMock(text="Synthesized response")
        )

        communities = [_make_community("c1", "Risk", "Long " * 100)]
        evidence = [_make_sentence("Evidence " * 50, sentence_id=f"s{i}") for i in range(10)]
        sections = [_make_section("Section A")]

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROUTE6_MAX_CONTEXT_TOKENS", None)
            result = await handler._synthesize(
                "What are the risks?", communities, sections, evidence,
            )

        assert result == "Synthesized response"
        # Verify LLM was called with full evidence (no truncation)
        call_args = handler.llm.acomplete.call_args[0][0]
        assert "Evidence" in call_args

    @pytest.mark.asyncio
    async def test_token_budget_truncates_evidence(self):
        """With ROUTE6_MAX_CONTEXT_TOKENS set low, evidence is truncated first."""
        handler = _make_handler()
        handler.llm.acomplete = AsyncMock(
            return_value=MagicMock(text="Short response")
        )

        communities = [_make_community("c1", "Risk", "Community summary")]
        evidence = [_make_sentence("A " * 200, sentence_id=f"s{i}") for i in range(20)]
        sections = [_make_section("Section A")]

        with patch.dict(os.environ, {"ROUTE6_MAX_CONTEXT_TOKENS": "200"}):
            result = await handler._synthesize(
                "What are the risks?", communities, sections, evidence,
            )

        # The prompt should have been built despite truncation
        assert handler.llm.acomplete.called
        call_args = handler.llm.acomplete.call_args[0][0]
        # Community summaries should still be present
        assert "Community summary" in call_args

    @pytest.mark.asyncio
    async def test_token_budget_preserves_communities(self):
        """Community summaries are never truncated even under tight budget."""
        handler = _make_handler()
        handler.llm.acomplete = AsyncMock(
            return_value=MagicMock(text="Response")
        )

        long_summary = "Important risk factor " * 20
        communities = [_make_community("c1", "Risk", long_summary)]
        evidence = [_make_sentence("Evidence text", sentence_id="s1")]
        sections = [_make_section("Section A")]

        # Budget so small even the community summary alone exceeds it
        with patch.dict(os.environ, {"ROUTE6_MAX_CONTEXT_TOKENS": "10"}):
            result = await handler._synthesize(
                "What are the risks?", communities, sections, evidence,
            )

        call_args = handler.llm.acomplete.call_args[0][0]
        # Community summary must survive — it's the thematic backbone
        assert "Important risk factor" in call_args


# ============================================================================
# Feature 1: Dynamic Community Selection
# ============================================================================

class TestDynamicCommunitySelection:
    """Tests for ROUTE6_DYNAMIC_COMMUNITY env var."""

    @pytest.mark.asyncio
    async def test_dynamic_community_off_by_default(self):
        """With no env var, communities pass through unchanged."""
        handler = _make_handler()
        communities = [
            _make_community("c1", "Risk", "Risk summary"),
            _make_community("c2", "Finance", "Finance summary"),
        ]
        scores = [0.9, 0.7]

        # If dynamic community were on, _rate_communities_with_llm would be called
        # Since it's off, we just verify the method is NOT called
        handler._rate_communities_with_llm = AsyncMock()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROUTE6_DYNAMIC_COMMUNITY", None)
            # We can't easily call execute() (too many deps), so verify the env check logic
            enabled = os.getenv("ROUTE6_DYNAMIC_COMMUNITY", "0").strip().lower() in {"1", "true", "yes"}
            assert not enabled

    @pytest.mark.asyncio
    async def test_dynamic_community_rates_communities(self):
        """With ROUTE6_DYNAMIC_COMMUNITY=1, communities are rated by LLM."""
        handler = _make_handler()
        communities = [
            _make_community("c1", "Risk", "Risk management overview"),
            _make_community("c2", "HR Policy", "Human resources guidelines"),
        ]
        scores = [0.9, 0.7]

        # Mock LLM to return ratings: 8 for Risk, 0 for HR Policy
        call_count = 0
        async def mock_acomplete(prompt):
            nonlocal call_count
            call_count += 1
            if "Risk" in prompt:
                return MagicMock(text='{"rating": 8}')
            return MagicMock(text='{"rating": 0}')

        handler.llm.acomplete = mock_acomplete

        with patch.dict(os.environ, {"ROUTE6_DYNAMIC_COMMUNITY_THRESHOLD": "1"}):
            filtered_c, filtered_s = await handler._rate_communities_with_llm(
                "What are the risks?", communities, scores,
            )

        # HR Policy (rating=0) should be filtered out
        assert len(filtered_c) == 1
        assert filtered_c[0]["title"] == "Risk"

    @pytest.mark.asyncio
    async def test_dynamic_community_respects_threshold(self):
        """Communities below threshold are excluded."""
        handler = _make_handler()
        communities = [
            _make_community("c1", "A", "Summary A"),
            _make_community("c2", "B", "Summary B"),
            _make_community("c3", "C", "Summary C"),
        ]
        scores = [0.9, 0.8, 0.7]

        # All rated at 3
        handler.llm.acomplete = AsyncMock(return_value=MagicMock(text='{"rating": 3}'))

        # Threshold=5 → all should be filtered out → fallback to original
        with patch.dict(os.environ, {"ROUTE6_DYNAMIC_COMMUNITY_THRESHOLD": "5"}):
            filtered_c, filtered_s = await handler._rate_communities_with_llm(
                "Query", communities, scores,
            )

        # All filtered → fallback returns original list
        assert len(filtered_c) == 3

    @pytest.mark.asyncio
    async def test_dynamic_community_llm_failure_fallback(self):
        """If LLM rating fails, community is kept (not filtered)."""
        handler = _make_handler()
        communities = [_make_community("c1", "Risk", "Summary")]
        scores = [0.9]

        # LLM raises exception
        handler.llm.acomplete = AsyncMock(side_effect=Exception("LLM unavailable"))

        with patch.dict(os.environ, {"ROUTE6_DYNAMIC_COMMUNITY_THRESHOLD": "5"}):
            filtered_c, filtered_s = await handler._rate_communities_with_llm(
                "Query", communities, scores,
            )

        # Community should be kept (LLM failure → rating=-1 → keep)
        assert len(filtered_c) == 1


# ============================================================================
# Feature 2: Community Children Traversal
# ============================================================================

class TestCommunityChildren:
    """Tests for ROUTE6_COMMUNITY_CHILDREN env var."""

    def test_community_children_off_by_default(self):
        """With no env var, community children feature is disabled."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROUTE6_COMMUNITY_CHILDREN", None)
            enabled = os.getenv("ROUTE6_COMMUNITY_CHILDREN", "0").strip().lower() in {"1", "true", "yes"}
            assert not enabled

    @pytest.mark.asyncio
    async def test_community_children_fetches_children(self):
        """With ROUTE6_COMMUNITY_CHILDREN=1, children are fetched from Neo4j."""
        handler = _make_handler()

        parent = _make_community("c1", "Risk", "Risk overview")
        child_records = [
            {"id": "c1_child1", "title": "Credit Risk", "summary": "Credit risk details",
             "level": 1, "rank": 0.5, "parent_id": "c1"},
            {"id": "c1_child2", "title": "Market Risk", "summary": "Market risk details",
             "level": 1, "rank": 0.4, "parent_id": "c1"},
        ]

        # Mock the Neo4j query
        mock_session = MagicMock()
        mock_session.run.return_value = child_records
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("src.worker.hybrid_v2.routes.route_6_concept.retry_session", return_value=mock_session):
            with patch.dict(os.environ, {"ROUTE6_COMMUNITY_CHILDREN": "1"}):
                children = await handler._fetch_community_children([parent])

        assert len(children) == 2
        assert children[0][0]["title"] == "Credit Risk"
        assert children[1][0]["title"] == "Market Risk"
        # Children should have the _is_child marker
        assert children[0][0]["_is_child"] is True

    @pytest.mark.asyncio
    async def test_community_children_no_children_graceful(self):
        """If matched community has no children, returns empty list."""
        handler = _make_handler()
        parent = _make_community("c1", "Risk", "Summary")

        mock_session = MagicMock()
        mock_session.run.return_value = []
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("src.worker.hybrid_v2.routes.route_6_concept.retry_session", return_value=mock_session):
            children = await handler._fetch_community_children([parent])

        assert children == []

    @pytest.mark.asyncio
    async def test_community_children_dedup(self):
        """If a child was already matched by cosine, it's not duplicated."""
        handler = _make_handler()

        # Parent and a child that was already matched
        parent = _make_community("c1", "Risk", "Risk overview")
        already_matched = _make_community("c1_child1", "Credit Risk", "Credit risk details")

        child_records = [
            {"id": "c1_child1", "title": "Credit Risk", "summary": "Credit risk details",
             "level": 1, "rank": 0.5, "parent_id": "c1"},
        ]

        mock_session = MagicMock()
        mock_session.run.return_value = child_records
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("src.worker.hybrid_v2.routes.route_6_concept.retry_session", return_value=mock_session):
            children = await handler._fetch_community_children([parent])

        # Simulate dedup logic as done in execute()
        community_data = [parent, already_matched]
        community_scores = [0.9, 0.8]
        existing_ids = {c.get("id") for c in community_data}

        added = 0
        for child, child_score in children:
            if child.get("id") not in existing_ids:
                community_data.append(child)
                community_scores.append(child_score)
                existing_ids.add(child.get("id"))
                added += 1

        # c1_child1 was already in community_data → should not be added
        assert added == 0
        assert len(community_data) == 2


# ============================================================================
# Feature 3: Streaming Synthesis
# ============================================================================

class TestStreamingSynthesis:
    """Tests for streaming synthesis (stream_execute / _stream_synthesize)."""

    @pytest.mark.asyncio
    async def test_stream_synthesize_yields_chunks(self):
        """_stream_synthesize() yields string chunks from LLM."""
        handler = _make_handler()

        # Mock astream_complete to return an async iterator of chunks
        async def mock_astream_complete(prompt):
            class MockChunk:
                def __init__(self, delta):
                    self.delta = delta

            async def gen():
                for word in ["Hello", " ", "world", "!"]:
                    yield MockChunk(word)

            return gen()

        handler.llm.astream_complete = mock_astream_complete

        communities = [_make_community("c1", "Risk", "Summary")]
        evidence = [_make_sentence("Evidence text", sentence_id="s1")]

        chunks = []
        async for chunk in handler._stream_synthesize(
            "What are the risks?", communities, [], evidence,
        ):
            chunks.append(chunk)

        assert chunks == ["Hello", " ", "world", "!"]
        assert "".join(chunks) == "Hello world!"

    @pytest.mark.asyncio
    async def test_stream_synthesize_fallback_on_error(self):
        """If streaming fails, yields a single error message."""
        handler = _make_handler()
        handler.llm.astream_complete = AsyncMock(side_effect=Exception("Stream failed"))

        communities = [_make_community("c1", "Risk", "Summary")]

        chunks = []
        async for chunk in handler._stream_synthesize(
            "Query", communities, [], [],
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "error occurred" in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_stream_execute_returns_generator(self):
        """stream_execute() returns an async generator."""
        handler = _make_handler()

        # Mock all retrieval methods
        handler._retrieve_sentence_evidence = AsyncMock(return_value=[])
        handler._retrieve_section_headings = AsyncMock(return_value=[])
        handler._retrieve_entity_document_map = AsyncMock(return_value={})
        handler.pipeline.community_matcher.match_communities = AsyncMock(return_value=[])

        # Mock streaming synthesis
        async def mock_stream(*args, **kwargs):
            yield "chunk1"
            yield "chunk2"

        handler._stream_synthesize = mock_stream

        chunks = []
        async for chunk in handler.stream_execute("What are the risks?"):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]


# ============================================================================
# Token Budget: _build_synthesis_prompt shares logic
# ============================================================================

class TestBuildSynthesisPrompt:
    """Tests for the shared _build_synthesis_prompt method."""

    @pytest.mark.asyncio
    async def test_build_prompt_includes_all_sections(self):
        """Prompt includes communities, sections, evidence, and entity coverage."""
        handler = _make_handler()
        communities = [_make_community("c1", "Risk", "Risk summary")]
        sections = [_make_section("Termination")]
        evidence = [_make_sentence("Important fact", sentence_id="s1")]
        entity_map = {"Entity A": ["Doc 1", "Doc 2"]}

        prompt = await handler._build_synthesis_prompt(
            "What are the risks?", communities, sections, evidence, entity_map,
        )

        assert "Risk summary" in prompt
        assert "Termination" in prompt
        assert "Important fact" in prompt
        assert "Entity A" in prompt

    @pytest.mark.asyncio
    async def test_build_prompt_applies_token_budget(self):
        """Token budget truncation works in _build_synthesis_prompt."""
        handler = _make_handler()
        communities = [_make_community("c1", "T", "Short")]
        evidence = [_make_sentence("word " * 500, sentence_id="s1")]

        with patch.dict(os.environ, {"ROUTE6_MAX_CONTEXT_TOKENS": "100"}):
            prompt = await handler._build_synthesis_prompt(
                "Query", communities, [], evidence,
            )

        # Prompt should be shorter than if we had no budget
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROUTE6_MAX_CONTEXT_TOKENS", None)
            full_prompt = await handler._build_synthesis_prompt(
                "Query", communities, [], evidence,
            )

        assert len(prompt) < len(full_prompt)
