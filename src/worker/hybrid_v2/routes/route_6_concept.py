"""Route 6: Concept Search — Community-Aware Synthesis.

Best for thematic/cross-document concept queries:
- "What are the main compliance risks?"
- "Summarize key themes across documents"
- "Compare termination clauses across agreements"

Architecture (3 steps, 1 LLM call):
  1. Community Match + Sentence Search + Section Heading Search  (parallel)
  1b. Entity-centric sentence expansion via shared MENTIONS edges (R6-XII)
  2. Denoise + Rerank sentence evidence
  3. Synthesize community summaries + section headings + sentence evidence (single LLM call)

Key difference from Route 3 (MAP-REDUCE):
- No MAP phase: community summaries are passed directly to synthesis
- 1 LLM call total instead of N+1
- Community summaries provide thematic framing, not extracted claims
- Section headings provide document structure (via structural_embedding)
- Validated by benchmarks: MAP adds +41% latency for +1% containment

Design rationale:
  ANALYSIS_ROUTE3_LAZYGRAPHRAG_DEVIATION_AND_ROUTE6_PLAN_2026-02-19.md
"""

import asyncio
import json
import os
import re
import time
import threading
from collections import defaultdict
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import structlog
import tiktoken

from src.core.config import settings
from .base import BaseRouteHandler, Citation, RouteResult, rerank_with_retry, make_voyage_client, acomplete_with_retry
from .route_6_prompts import CONCEPT_SYNTHESIS_PROMPT, COMMUNITY_EXTRACT_PROMPT
from ..services.neo4j_retry import retry_session

# Shared tiktoken encoder for token budget control (Feature 4)
_tiktoken_enc = tiktoken.get_encoding("cl100k_base")

logger = structlog.get_logger(__name__)

# Voyage embedding service (lazy singleton) — shared with Route 3
_voyage_service = None
_voyage_init_attempted = False
_voyage_init_lock = threading.Lock()


def _get_voyage_service():
    """Get Voyage embedding service for sentence search."""
    global _voyage_service, _voyage_init_attempted
    if _voyage_init_attempted:
        return _voyage_service
    with _voyage_init_lock:
        if not _voyage_init_attempted:
            _voyage_init_attempted = True
            try:
                from src.core.config import settings
                if settings.VOYAGE_API_KEY:
                    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
                    _voyage_service = VoyageEmbedService()
                    logger.info("route6_voyage_service_initialized")
                else:
                    logger.warning("route6_voyage_service_no_api_key")
            except Exception as e:
                logger.warning("route6_voyage_service_init_failed", error=str(e))
    return _voyage_service


class ConceptSearchHandler(BaseRouteHandler):
    """Route 6: Community-aware concept search with direct synthesis.

    Restores the LazyGraphRAG insight (community summaries as thematic
    context) while keeping Route 3's proven sentence search.  Eliminates
    the MAP phase that added latency without proportional accuracy gain.
    """

    ROUTE_NAME = "route_6_concept_search"

    async def execute(
        self,
        query: str,
        response_type: str = "summary",
        knn_config: Optional[str] = None,
        prompt_variant: Optional[str] = None,
        synthesis_model: Optional[str] = None,
        include_context: bool = False,
        language: Optional[str] = None,
        folder_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RouteResult:
        """Execute Route 6: Community-aware concept synthesis.

        Pipeline:
          1. Community matching + Sentence vector search  (parallel)
          2. Denoise + Rerank sentence evidence
          3. Single LLM synthesis (community summaries + sentence evidence)

        Args:
            query: The user's natural language query.
            response_type: Response format ("summary", "detailed_report", etc.)
            knn_config: Unused (kept for interface compat).
            prompt_variant: Unused (kept for interface compat).
            synthesis_model: Optional override for synthesis LLM model.
            include_context: If True, include full LLM context in metadata.

        Returns:
            RouteResult with response, citations, and metadata.
        """
        enable_timings = os.getenv("ROUTE6_RETURN_TIMINGS", "0").strip().lower() in {
            "1", "true", "yes",
        }
        timings_ms: Dict[str, int] = {}
        t_route_start = time.perf_counter()

        community_top_k = int(os.getenv("ROUTE6_COMMUNITY_TOP_K", "5"))
        sentence_top_k = int(os.getenv("ROUTE6_SENTENCE_TOP_K", "30"))
        section_top_k = int(os.getenv("ROUTE6_SECTION_TOP_K", "10"))

        logger.info(
            "route_6_start",
            query=query[:80],
            response_type=response_type,
            community_top_k=community_top_k,
            sentence_top_k=sentence_top_k,
            section_top_k=section_top_k,
        )

        # ================================================================
        # Step 1: Community Match + Sentence Search + Section Heading Search (PARALLEL)
        # ================================================================
        t0 = time.perf_counter()

        sentence_search_task = asyncio.create_task(
            self._retrieve_sentence_evidence(query, top_k=sentence_top_k)
        )
        section_search_task = asyncio.create_task(
            self._retrieve_section_headings(query, top_k=section_top_k)
        )
        # R6-XI: entity-document coverage map — launched in parallel.
        # Resolves queries like "which entity appears in the most documents?"
        # using a 2-hop Entity←MENTIONS←Sentence→IN_DOCUMENT→Document traversal
        # (same path as Route 7 PPR) to avoid the edge-coverage gap in the
        # pre-materialised APPEARS_IN_DOCUMENT shortcut.
        entity_doc_task = asyncio.create_task(
            self._retrieve_entity_document_map(top_k=20)
        )

        matched_communities = await self.pipeline.community_matcher.match_communities(
            query, top_k=community_top_k,
        )
        community_data: List[Dict[str, Any]] = [c for c, _ in matched_communities]
        community_scores: List[float] = [s for _, s in matched_communities]
        timings_ms["step_1_community_match_ms"] = int(
            (time.perf_counter() - t0) * 1000
        )

        logger.info(
            "route6_step_1_community_match",
            num_communities=len(community_data),
            titles=[c.get("title", "?") for c in community_data],
            top_scores=[round(s, 4) for s in community_scores[:5]],
        )

        # Feature 1: Dynamic Community Selection — LLM-rate matched communities
        dynamic_community = os.getenv(
            "ROUTE6_DYNAMIC_COMMUNITY", "1"
        ).strip().lower() in {"1", "true", "yes"}
        if dynamic_community and community_data:
            t_dc = time.perf_counter()
            try:
                community_data, community_scores = await self._rate_communities_with_llm(
                    query, community_data, community_scores,
                )
            except Exception as e:
                logger.warning("route6_dynamic_community_failed_fallback", error=str(e))
            timings_ms["step_1_dynamic_community_ms"] = int(
                (time.perf_counter() - t_dc) * 1000
            )

        # Feature 2: Community Children Traversal — expand with child communities
        community_children_enabled = os.getenv(
            "ROUTE6_COMMUNITY_CHILDREN", "0"
        ).strip().lower() in {"1", "true", "yes"}
        if community_children_enabled and community_data:
            t_cc = time.perf_counter()
            try:
                children = await self._fetch_community_children(
                    community_data, parent_scores=community_scores,
                )
                if children:
                    # Dedup: skip children already in community_data
                    existing_ids = {c.get("id") for c in community_data}
                    added_count = 0
                    parent_count = len(community_data)
                    for child, child_score in children:
                        if child.get("id") not in existing_ids:
                            community_data.append(child)
                            community_scores.append(child_score)
                            existing_ids.add(child.get("id"))
                            added_count += 1
                    logger.info(
                        "route6_community_children_merged",
                        parent_count=parent_count,
                        children_added=added_count,
                        total=len(community_data),
                    )
            except Exception as e:
                logger.warning("route6_community_children_failed", error=str(e))
            timings_ms["step_1_community_children_ms"] = int(
                (time.perf_counter() - t_cc) * 1000
            )

        # Await sentence search
        try:
            sentence_evidence = await sentence_search_task
        except Exception as e:
            logger.warning("route6_sentence_search_failed", error=str(e))
            sentence_evidence = []

        # Await section heading search
        try:
            section_headings = await section_search_task
        except Exception as e:
            logger.warning("route6_section_search_failed", error=str(e))
            section_headings = []

        # R6-XI: Await entity-document coverage map
        try:
            entity_doc_map = await entity_doc_task
        except Exception as e:
            logger.warning("route6_entity_doc_map_failed", error=str(e))
            entity_doc_map = {}

        timings_ms["step_1_parallel_ms"] = int(
            (time.perf_counter() - t0) * 1000
        )

        logger.info(
            "route6_step_1_complete",
            communities=len(community_data),
            sentences_raw=len(sentence_evidence),
            sections=len(section_headings),
            entity_doc_map_entries=len(entity_doc_map),
        )

        # ================================================================
        # Step 1b: R6-XII Entity-centric sentence expansion
        # After seed sentences are retrieved, traverse shared entities to
        # find additional related sentences for multi-hop reasoning.
        # ================================================================
        expansion_enabled = os.getenv(
            "ROUTE6_ENTITY_EXPANSION", "0"
        ).strip().lower() in {"1", "true", "yes"}
        expansion_count = 0
        expanded: List[Dict[str, Any]] = []

        if expansion_enabled and sentence_evidence:
            t_exp = time.perf_counter()
            exp_seeds = int(os.getenv("ROUTE6_ENTITY_EXPANSION_SEEDS", "10"))
            exp_top_k = int(os.getenv("ROUTE6_ENTITY_EXPANSION_TOP_K", "20"))
            exp_min_overlap = int(
                os.getenv("ROUTE6_ENTITY_EXPANSION_MIN_OVERLAP", "1")
            )

            try:
                expanded = await self._expand_sentences_via_entities(
                    seed_evidence=sentence_evidence,
                    seed_count=exp_seeds,
                    top_k=exp_top_k,
                    min_overlap=exp_min_overlap,
                )
                if expanded:
                    expansion_count = len(expanded)
                    # Do NOT merge into sentence_evidence here — expanded
                    # sentences have synthetic scores that the diversity
                    # score_gate would filter out.  Keep them separate so
                    # they bypass diversity and go straight to the reranker.
                    logger.info(
                        "route6_entity_expansion_retrieved",
                        expanded_count=expansion_count,
                    )
            except Exception as e:
                logger.warning("route6_entity_expansion_failed", error=str(e))

            timings_ms["step_1b_entity_expansion_ms"] = int(
                (time.perf_counter() - t_exp) * 1000
            )

        # ================================================================
        # Step 2: Denoise + Rerank sentence evidence
        # ================================================================
        if sentence_evidence:
            t0 = time.perf_counter()
            raw_count = len(sentence_evidence)
            sentence_evidence = self._denoise_sentences(sentence_evidence)
            denoised_count = len(sentence_evidence)

            rerank_enabled = os.getenv(
                "ROUTE6_SENTENCE_RERANK", "1"
            ).strip().lower() in {"1", "true", "yes"}
            rerank_top_k = int(os.getenv("ROUTE6_RERANK_TOP_K", "15"))
            diversity_enabled = os.getenv(
                "ROUTE6_SENTENCE_DIVERSITY", "1"
            ).strip().lower() in {"1", "true", "yes"}
            min_per_doc = int(os.getenv("ROUTE6_SENTENCE_MIN_PER_DOC", "2"))
            score_gate = float(os.getenv("ROUTE6_SENTENCE_SCORE_GATE", "0.85"))

            # R6-6: Diversity BEFORE reranking but AFTER denoising (correct order).
            #
            #   Pipeline:
            #     1. Denoise  (removes junk sentences)
            #     2. Diversity → pool of 2×rerank_top_k (guarantees document coverage)
            #     3. Rerank   → final rerank_top_k from the diverse pool
            #
            #   The reranker picks the BEST sentences from a pool that already covers
            #   all qualifying documents, so both relevance and coverage are preserved.
            #
            #   Diversity activates whenever we have more evidence than rerank_top_k
            #   (previously required > 2×rerank_top_k, which was never met when
            #   the shared vector index limited raw results).
            if diversity_enabled and sentence_evidence:
                diversity_pool_k = rerank_top_k * 2
                if len(sentence_evidence) > rerank_top_k:
                    sentence_evidence = self._diversify_by_document(
                        sentence_evidence,
                        top_k=diversity_pool_k,
                        min_per_doc=min_per_doc,
                        score_gate=score_gate,
                    )

            # Inject entity-expanded sentences AFTER diversity, BEFORE reranking.
            # Expanded sentences carry synthetic scores that the diversity score_gate
            # would filter out.  By injecting them here the reranker (not the score
            # gate) decides whether they are relevant.
            if expanded:
                expanded_denoised = self._denoise_sentences(expanded)
                if expanded_denoised:
                    seen_ids = {ev.get("sentence_id") for ev in sentence_evidence}
                    for ev in expanded_denoised:
                        if ev.get("sentence_id") not in seen_ids:
                            sentence_evidence.append(ev)
                            seen_ids.add(ev.get("sentence_id"))
                    logger.info(
                        "route6_expansion_injected_for_rerank",
                        injected=len(expanded_denoised),
                        rerank_pool=len(sentence_evidence),
                    )

            if rerank_enabled and sentence_evidence:
                # R6-3: Wrap in try/except — reranker failures must not crash the request.
                try:
                    sentence_evidence = await self._rerank_sentences(
                        query, sentence_evidence, top_k=rerank_top_k,
                    )
                except Exception as e:
                    logger.warning("route6_rerank_failed_fallback", error=str(e))
                    sentence_evidence = sentence_evidence[:rerank_top_k]

            timings_ms["step_2_denoise_rerank_ms"] = int(
                (time.perf_counter() - t0) * 1000
            )
            logger.info(
                "route6_step_2_denoise_rerank",
                raw=raw_count,
                after_denoise=denoised_count,
                after_rerank=len(sentence_evidence),
                rerank_enabled=rerank_enabled,
            )

        # ================================================================
        # Negative detection: no communities AND no sentences AND no sections
        # ================================================================
        if not community_data and not sentence_evidence and not section_headings:
            logger.info("route_6_negative_no_evidence")
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "negative_detection": True,
                    "detection_reason": "no_communities_and_no_sentences",
                },
            )

        # ================================================================
        # Step 3: Single LLM synthesis (communities + sentences)
        # ================================================================
        t0 = time.perf_counter()
        response_text = await self._synthesize(
            query, community_data, section_headings, sentence_evidence,
            entity_doc_map=entity_doc_map,
            language=language,
        )
        timings_ms["step_3_synthesis_ms"] = int(
            (time.perf_counter() - t0) * 1000
        )
        timings_ms["total_ms"] = int(
            (time.perf_counter() - t_route_start) * 1000
        )

        logger.info(
            "route6_step_3_complete",
            response_length=len(response_text),
            total_ms=timings_ms["total_ms"],
        )

        # ================================================================
        # Build citations
        # ================================================================
        citations = self._build_citations(
            community_data, community_scores, sentence_evidence,
        )
        self._enrich_citations_with_geometry(citations)

        # ================================================================
        # Assemble metadata
        # ================================================================
        metadata: Dict[str, Any] = {
            "matched_communities": [c.get("title", "?") for c in community_data],
            "community_scores": {
                c.get("title", "?"): round(s, 4)
                for c, s in zip(community_data, community_scores)
            },
            "matched_sections": [s.get("title", "?") for s in section_headings],
            "section_scores": {
                s.get("title", "?"): round(s.get("score") or 0, 4)
                for s in section_headings
            },
            "sentence_evidence_count": len(sentence_evidence),
            "entity_doc_map_count": len(entity_doc_map),
            "entity_expansion_enabled": expansion_enabled,
            "entity_expansion_count": expansion_count,
            "community_extract_enabled": os.getenv("ROUTE6_COMMUNITY_EXTRACT", "1").strip().lower() in {"1", "true", "yes"},
            "dynamic_community_enabled": dynamic_community,
            "community_children_enabled": community_children_enabled,
            "community_children_count": len([c for c in community_data if c.get("_is_child")]),
            "route_description": "Concept search — direct community synthesis (v2 + section headings)",
            "version": "v2",
        }

        if include_context:
            metadata["community_summaries"] = [
                {
                    "title": c.get("title", ""),
                    "summary": (c.get("summary") or "")[:300],
                    "score": round(s or 0, 4),
                }
                for c, s in zip(community_data, community_scores)
            ]
            metadata["section_headings"] = [
                {
                    "title": s.get("title", ""),
                    "summary": (s.get("summary") or "")[:300],
                    "path_key": s.get("path_key", ""),
                    "document_title": s.get("document_title", ""),
                    "score": round(s.get("score") or 0, 4),
                }
                for s in section_headings
            ]
            metadata["sentence_evidence"] = [
                {
                    "text": (s.get("text") or "")[:200],
                    "source": s.get("document_title", ""),
                    "section_path": s.get("section_path", ""),
                    "score": round(s.get("score") or 0, 4),
                    "expansion_source": s.get("expansion_source", ""),
                }
                for s in sentence_evidence[:10]
            ]
            # R6-XI: include entity-document map for debugging
            if entity_doc_map:
                metadata["entity_doc_map"] = {
                    name: docs for name, docs in list(entity_doc_map.items())[:10]
                }

        if enable_timings:
            metadata["timings_ms"] = timings_ms

        return RouteResult(
            response=response_text,
            route_used=self.ROUTE_NAME,
            citations=citations,
            evidence_path=[c.get("title", "") for c in community_data],
            metadata=metadata,
        )

    # ==================================================================
    # Step 3: Single-call synthesis (NO MAP)
    # ==================================================================

    async def _synthesize(
        self,
        query: str,
        communities: List[Dict[str, Any]],
        section_headings: List[Dict[str, Any]],
        sentence_evidence: List[Dict[str, Any]],
        entity_doc_map: Optional[Dict[str, List[str]]] = None,
        language: Optional[str] = None,
    ) -> str:
        """Synthesize community summaries + section headings + sentence evidence in one LLM call.

        Unlike Route 3's MAP-REDUCE, community summaries are passed directly
        as thematic context — no per-community claim extraction.

        Args:
            query: User query.
            communities: Matched community dicts with title/summary.
            section_headings: Matched section dicts with title/summary/path_key.
            sentence_evidence: Denoised + reranked sentence dicts.
            entity_doc_map: R6-XI — {entity_name: [doc_title, ...]} for top entities
                by document count. Provides structured entity-document coverage for
                comparison queries ("which entity appears in the most documents?").

        Returns:
            Synthesized response text.
        """
        # Build the synthesis prompt (shared with _stream_synthesize)
        prompt = await self._build_synthesis_prompt(
            query, communities, section_headings, sentence_evidence,
            entity_doc_map, language,
        )

        try:
            response = await acomplete_with_retry(self.llm, prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(
                "route6_synthesis_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return (
                "An error occurred while synthesizing the response. "
                f"Please try again. (Error: {type(e).__name__})"
            )

    # ==================================================================
    # Feature 3: Streaming Synthesis
    # ==================================================================

    async def _stream_synthesize(
        self,
        query: str,
        communities: List[Dict[str, Any]],
        section_headings: List[Dict[str, Any]],
        sentence_evidence: List[Dict[str, Any]],
        entity_doc_map: Optional[Dict[str, List[str]]] = None,
        language: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming variant of _synthesize(). Yields token chunks.

        Uses self.llm.astream_complete() (LlamaIndex AzureOpenAI) to stream
        the synthesis response token-by-token. Falls back to a single yield
        of the full response if streaming is not supported.
        """
        # Build prompt identically to _synthesize()
        prompt = await self._build_synthesis_prompt(
            query, communities, section_headings, sentence_evidence,
            entity_doc_map, language,
        )

        try:
            stream_resp = await self.llm.astream_complete(prompt)
            async for chunk in stream_resp:
                if chunk.delta:
                    yield chunk.delta
        except Exception as e:
            logger.error("route6_stream_synthesis_failed", error=str(e))
            yield (
                "An error occurred while synthesizing the response. "
                f"Please try again. (Error: {type(e).__name__})"
            )

    async def stream_execute(
        self,
        query: str,
        response_type: str = "summary",
        language: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming variant of execute(). Yields synthesis chunks.

        Runs the same retrieval pipeline (community match, sentence search,
        section heading search, entity-doc map, denoise, diversity, entity
        expansion, rerank), then streams the LLM synthesis token-by-token.

        Gated by ROUTE6_STREAM_SYNTHESIS env var — caller should check before invoking.
        """
        community_top_k = int(os.getenv("ROUTE6_COMMUNITY_TOP_K", "5"))
        sentence_top_k = int(os.getenv("ROUTE6_SENTENCE_TOP_K", "30"))
        section_top_k = int(os.getenv("ROUTE6_SECTION_TOP_K", "10"))

        # Step 1: Parallel retrieval (same as execute)
        sentence_search_task = asyncio.create_task(
            self._retrieve_sentence_evidence(query, top_k=sentence_top_k)
        )
        section_search_task = asyncio.create_task(
            self._retrieve_section_headings(query, top_k=section_top_k)
        )
        entity_doc_task = asyncio.create_task(
            self._retrieve_entity_document_map(top_k=20)
        )

        matched_communities = await self.pipeline.community_matcher.match_communities(
            query, top_k=community_top_k,
        )
        community_data = [c for c, _ in matched_communities]
        community_scores = [s for _, s in matched_communities]

        # Feature 1: Dynamic Community Selection (if enabled)
        dynamic_community = os.getenv(
            "ROUTE6_DYNAMIC_COMMUNITY", "1"
        ).strip().lower() in {"1", "true", "yes"}
        if dynamic_community and community_data:
            try:
                community_data, community_scores = await self._rate_communities_with_llm(
                    query, community_data, community_scores,
                )
            except Exception:
                pass  # fallback to embedding-only

        # Feature 2: Community Children (if enabled)
        community_children_enabled = os.getenv(
            "ROUTE6_COMMUNITY_CHILDREN", "0"
        ).strip().lower() in {"1", "true", "yes"}
        if community_children_enabled and community_data:
            try:
                children = await self._fetch_community_children(
                    community_data, parent_scores=community_scores,
                )
                if children:
                    existing_ids = {c.get("id") for c in community_data}
                    for child, child_score in children:
                        if child.get("id") not in existing_ids:
                            community_data.append(child)
                            community_scores.append(child_score)
                            existing_ids.add(child.get("id"))
            except Exception:
                pass

        # Await parallel tasks
        try:
            sentence_evidence = await sentence_search_task
        except Exception:
            sentence_evidence = []
        try:
            section_headings = await section_search_task
        except Exception:
            section_headings = []
        try:
            entity_doc_map = await entity_doc_task
        except Exception:
            entity_doc_map = {}

        # Step 1b: Entity expansion (same as execute)
        expansion_enabled = os.getenv(
            "ROUTE6_ENTITY_EXPANSION", "0"
        ).strip().lower() in {"1", "true", "yes"}
        expanded: List[Dict[str, Any]] = []

        if expansion_enabled and sentence_evidence:
            exp_seeds = int(os.getenv("ROUTE6_ENTITY_EXPANSION_SEEDS", "10"))
            exp_top_k = int(os.getenv("ROUTE6_ENTITY_EXPANSION_TOP_K", "20"))
            exp_min_overlap = int(
                os.getenv("ROUTE6_ENTITY_EXPANSION_MIN_OVERLAP", "1")
            )
            try:
                expanded = await self._expand_sentences_via_entities(
                    seed_evidence=sentence_evidence,
                    seed_count=exp_seeds,
                    top_k=exp_top_k,
                    min_overlap=exp_min_overlap,
                )
            except Exception:
                pass

        # Step 2: Denoise + Diversity + Rerank (same as execute)
        if sentence_evidence:
            sentence_evidence = self._denoise_sentences(sentence_evidence)

            rerank_enabled = os.getenv(
                "ROUTE6_SENTENCE_RERANK", "1"
            ).strip().lower() in {"1", "true", "yes"}
            rerank_top_k = int(os.getenv("ROUTE6_RERANK_TOP_K", "15"))
            diversity_enabled = os.getenv(
                "ROUTE6_SENTENCE_DIVERSITY", "1"
            ).strip().lower() in {"1", "true", "yes"}
            min_per_doc = int(os.getenv("ROUTE6_SENTENCE_MIN_PER_DOC", "2"))
            score_gate = float(os.getenv("ROUTE6_SENTENCE_SCORE_GATE", "0.85"))

            # Diversity before reranking (same as execute)
            if diversity_enabled and sentence_evidence:
                diversity_pool_k = rerank_top_k * 2
                if len(sentence_evidence) > diversity_pool_k:
                    sentence_evidence = self._diversify_by_document(
                        sentence_evidence,
                        top_k=diversity_pool_k,
                        min_per_doc=min_per_doc,
                        score_gate=score_gate,
                    )

            # Inject entity-expanded sentences after diversity, before rerank
            if expanded:
                expanded_denoised = self._denoise_sentences(expanded)
                if expanded_denoised:
                    seen_ids = {ev.get("sentence_id") for ev in sentence_evidence}
                    for ev in expanded_denoised:
                        if ev.get("sentence_id") not in seen_ids:
                            sentence_evidence.append(ev)
                            seen_ids.add(ev.get("sentence_id"))

            if rerank_enabled and sentence_evidence:
                try:
                    sentence_evidence = await self._rerank_sentences(
                        query, sentence_evidence, top_k=rerank_top_k,
                    )
                except Exception:
                    sentence_evidence = sentence_evidence[:rerank_top_k]

        # Negative detection (same as execute)
        if not community_data and not sentence_evidence and not section_headings:
            yield "The requested information was not found in the available documents."
            return

        # Step 3: Stream synthesis
        async for chunk in self._stream_synthesize(
            query, community_data, section_headings, sentence_evidence,
            entity_doc_map=entity_doc_map, language=language,
        ):
            yield chunk

    # ==================================================================
    # Feature 1: Dynamic Community Selection (LLM-rated)
    # ==================================================================

    _COMMUNITY_RATING_PROMPT = (
        "Rate how relevant the following community summary is to the query.\n\n"
        "Query: {query}\n\n"
        "Community: {title}\n"
        "Summary: {summary}\n\n"
        "Respond with ONLY a JSON object: {{\"rating\": <0-10>}}\n"
        "0 = completely irrelevant, 10 = perfectly relevant."
    )

    async def _rate_communities_with_llm(
        self,
        query: str,
        communities: List[Dict[str, Any]],
        scores: List[float],
    ) -> Tuple[List[Dict[str, Any]], List[float]]:
        """Rate matched communities using a cheap LLM, filter low-rated ones.

        Inspired by Microsoft GraphRAG's DynamicCommunitySelection. Uses
        gpt-4o-mini (or configurable model) to rate each community's relevance
        on a 0-10 scale, then filters below threshold.

        Args:
            query: User query.
            communities: Community dicts from embedding match.
            scores: Corresponding cosine similarity scores.

        Returns:
            Filtered (communities, scores) tuple.
        """
        threshold = int(os.getenv("ROUTE6_DYNAMIC_COMMUNITY_THRESHOLD", "1"))
        max_concurrent = int(os.getenv("ROUTE6_DYNAMIC_COMMUNITY_CONCURRENCY", "8"))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _rate_one(community: Dict[str, Any]) -> int:
            prompt = self._COMMUNITY_RATING_PROMPT.format(
                query=query,
                title=community.get("title", ""),
                summary=(community.get("summary", "") or "")[:500],
            )
            async with semaphore:
                resp = None
                try:
                    resp = await acomplete_with_retry(self.llm, prompt)
                    text = resp.text.strip()
                    if text.startswith("```"):
                        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
                        text = re.sub(r'\n?```\s*$', '', text)
                    parsed = json.loads(text)
                    return int(parsed.get("rating", 0))
                except (json.JSONDecodeError, ValueError, KeyError):
                    # Try extracting a bare number
                    raw = resp.text if resp else ""
                    match = re.search(r"\b(\d+)\b", raw)
                    return int(match.group(1)) if match else 0
                except Exception as e:
                    logger.warning("route6_community_rating_error", error=str(e))
                    return -1  # -1 means "keep" (LLM failure → don't filter)

        # Rate all communities concurrently
        ratings = await asyncio.gather(*[_rate_one(c) for c in communities])

        # Filter below threshold; keep communities where LLM failed (rating == -1)
        filtered_communities = []
        filtered_scores = []
        for community, score, rating in zip(communities, scores, ratings):
            if rating == -1 or rating >= threshold:
                filtered_communities.append(community)
                filtered_scores.append(score)

        logger.info(
            "route6_dynamic_community_ratings",
            ratings=list(zip(
                [c.get("title", "?") for c in communities],
                ratings,
            )),
            threshold=threshold,
            kept=len(filtered_communities),
            dropped=len(communities) - len(filtered_communities),
        )

        # If all were filtered out, return original (safety fallback)
        if not filtered_communities:
            logger.warning("route6_dynamic_community_all_filtered_fallback")
            return communities, scores

        return filtered_communities, filtered_scores

    # ==================================================================
    # Feature 1b: Community Source-Text MAP (Microsoft-aligned)
    # ==================================================================

    async def _fetch_community_source_sentences(
        self,
        communities: List[Dict[str, Any]],
        max_per_community: int = 50,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch source sentences for matched communities via graph traversal.

        Traverses Community → BELONGS_TO → Entity → MENTIONS → Sentence
        to retrieve the actual document text that belongs to each community.
        This aligns with Microsoft's LazyGraphRAG MAP phase which extracts
        claims from source text, not from abstract community summaries.

        Args:
            communities: Matched community dicts (must have 'id' field).
            max_per_community: Max sentences per community (dedup'd).

        Returns:
            Dict mapping community_id → list of sentence dicts with
            text, document_title, section_path, sentence_id.
        """
        if not self.neo4j_driver:
            logger.warning("route6_community_source_no_neo4j_driver")
            return {}

        community_ids = [c.get("id") for c in communities if c.get("id")]
        if not community_ids:
            return {}

        group_ids = self.group_ids
        folder_id = self.folder_id

        folder_filter_clause = (
            "WITH s, doc, c_id\n"
            "        WHERE $folder_id IS NULL"
            " OR (doc IS NOT NULL AND (doc)-[:IN_FOLDER]->(:Folder {id: $folder_id}))\n"
        )

        cypher = f"""
        UNWIND $community_ids AS c_id
        MATCH (c:Community {{id: c_id}})
        WHERE c.group_id IN $group_ids
        MATCH (c)<-[:BELONGS_TO]-(e:Entity)
        WHERE e.group_id IN $group_ids
        MATCH (e)<-[:MENTIONS]-(s:Sentence)
        WHERE s.group_id IN $group_ids AND s.text IS NOT NULL
        OPTIONAL MATCH (s)-[:IN_DOCUMENT]->(doc:Document)

        {folder_filter_clause}
        WITH c_id, s, doc
        RETURN DISTINCT c_id AS community_id,
               s.id AS sentence_id,
               s.text AS text,
               s.section_path AS section_path,
               s.page AS page,
               doc.title AS document_title
        ORDER BY c_id, s.page, s.id
        """

        try:
            loop = asyncio.get_running_loop()
            driver = self.neo4j_driver

            def _run():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher,
                        community_ids=community_ids,
                        group_ids=group_ids,
                        folder_id=folder_id,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(self._executor, _run)
        except Exception as e:
            logger.warning("route6_community_source_query_failed", error=str(e))
            return {}

        # Group by community, dedup by sentence_id, cap per community
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        seen: Dict[str, set] = defaultdict(set)
        for r in results:
            cid = r["community_id"]
            sid = r["sentence_id"]
            if sid in seen[cid]:
                continue
            seen[cid].add(sid)
            if len(grouped[cid]) < max_per_community:
                grouped[cid].append(r)

        total = sum(len(v) for v in grouped.values())
        logger.info(
            "route6_community_source_fetched",
            num_communities=len(grouped),
            total_sentences=total,
        )
        return dict(grouped)

    async def _extract_community_key_points(
        self,
        query: str,
        communities: List[Dict[str, Any]],
    ) -> str:
        """Extract query-relevant key points from community SOURCE TEXT.

        Aligned with Microsoft's LazyGraphRAG MAP phase:
        1. For each matched community, fetch actual source sentences
           via Community → Entity → MENTIONS → Sentence graph traversal.
        2. Pass source sentences (not abstract summaries) to the LLM.
        3. Extract query-relevant claims with importance scores.

        Falls back to raw summaries if source fetch fails.
        """
        # Fetch source sentences for each matched community
        source_map = await self._fetch_community_source_sentences(communities)

        # Build per-community source text blocks
        community_blocks = []
        for i, c in enumerate(communities, 1):
            title = c.get("title", f"Theme {i}")
            cid = c.get("id", "")
            sentences = source_map.get(cid, [])

            if sentences:
                # Format source sentences grouped by document
                by_doc: Dict[str, List[str]] = defaultdict(list)
                for s in sentences:
                    doc = s.get("document_title") or "Unknown"
                    text = (s.get("text") or "").strip()
                    if text:
                        by_doc[doc].append(text)

                doc_sections = []
                for doc_title, texts in by_doc.items():
                    joined = " ".join(texts)
                    doc_sections.append(f"  [{doc_title}]: {joined}")
                source_text = "\n".join(doc_sections)
                community_blocks.append(
                    f"--- Community {i}: {title} ---\n{source_text}"
                )
            else:
                # Fallback: use the abstract summary if no source text
                summary = (c.get("summary") or "").strip()
                if summary:
                    community_blocks.append(
                        f"--- Community {i}: {title} ---\n  {summary}"
                    )

        if not community_blocks:
            return "(No thematic context available)"

        source_text_block = "\n\n".join(community_blocks)
        prompt = COMMUNITY_EXTRACT_PROMPT.format(
            query=query,
            community_source_text=source_text_block,
        )

        try:
            resp = await acomplete_with_retry(self.llm, prompt)
            text = resp.text.strip()
            # Strip markdown code fences (LLMs often wrap JSON in ```json...```)
            if text.startswith("```"):
                text = re.sub(r'^```(?:json)?\s*\n?', '', text)
                text = re.sub(r'\n?```\s*$', '', text)
            parsed = json.loads(text)
            points = parsed.get("points", [])
            if not points:
                logger.info("route6_community_extract_no_points")
                # Fallback: format raw summaries
                return self._format_raw_summaries(communities)

            # Sort by score descending, filter low-importance
            points = sorted(points, key=lambda p: p.get("score", 0), reverse=True)
            min_score = int(os.getenv("ROUTE6_EXTRACT_MIN_SCORE", "40"))
            points = [p for p in points if p.get("score", 0) >= min_score]
            if not points:
                return self._format_raw_summaries(communities)

            formatted = []
            for p in points:
                desc = p.get("description", "")
                score = p.get("score", 0)
                community = p.get("community", "")
                tag = f" [{community}]" if community else ""
                formatted.append(f"- (importance: {score}) {desc}{tag}")

            logger.info(
                "route6_community_extract_done",
                total_points=len(points),
                top_score=points[0].get("score", 0) if points else 0,
            )
            return "\n".join(formatted)

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("route6_community_extract_parse_error", error=str(e))
            return self._format_raw_summaries(communities)
        except Exception as e:
            logger.warning("route6_community_extract_failed", error=str(e))
            return self._format_raw_summaries(communities)

    @staticmethod
    def _format_raw_summaries(communities: List[Dict[str, Any]]) -> str:
        """Format communities as raw summary text (fallback)."""
        lines = []
        for i, c in enumerate(communities, 1):
            title = c.get("title", f"Theme {i}")
            summary = (c.get("summary") or "").strip()
            if summary:
                lines.append(f"{i}. **{title}**: {summary}")
        return "\n".join(lines) if lines else "(No thematic context available)"

    # ==================================================================
    # Feature 2: Community Children Traversal
    # ==================================================================

    async def _fetch_community_children(
        self,
        parent_communities: List[Dict[str, Any]],
        parent_scores: Optional[List[float]] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Fetch child communities via PARENT_COMMUNITY edges in Neo4j.

        For each parent community, traverses the hierarchy built by
        ensure_community_hierarchy() to find finer-grained child communities.

        Args:
            parent_communities: Matched parent community dicts.

        Returns:
            List of (child_community_dict, synthetic_score) tuples.
        """
        if not self.neo4j_driver:
            return []

        max_depth = int(os.getenv("ROUTE6_COMMUNITY_CHILDREN_MAX_LEVEL", "1"))
        parent_ids = [c.get("id") for c in parent_communities if c.get("id")]
        if not parent_ids:
            return []

        group_ids = self.group_ids

        # Fetch children up to max_depth levels below parents.
        # Neo4j doesn't support parameterised path lengths, so interpolate
        # the int directly (safe — comes from int()).
        cypher = f"""
        UNWIND $parent_ids AS pid
        MATCH (child:Community)-[:PARENT_COMMUNITY*1..{max_depth}]->(parent:Community {{id: pid}})
        WHERE child.group_id IN $group_ids AND parent.group_id IN $group_ids
              AND child.summary IS NOT NULL AND child.summary <> ''
        WITH DISTINCT child, parent
        RETURN child.id AS id,
               child.title AS title,
               child.summary AS summary,
               child.level AS level,
               child.rank AS rank,
               parent.id AS parent_id
        ORDER BY child.rank DESC
        """

        try:
            loop = asyncio.get_running_loop()
            driver = self.neo4j_driver

            def _run():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher,
                        parent_ids=parent_ids,
                        group_ids=group_ids,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(self._executor, _run)
        except Exception as e:
            logger.warning("route6_community_children_query_failed", error=str(e))
            return []

        if not results:
            return []

        # Assign synthetic score (below parent minimum)
        if parent_scores:
            synthetic_score = min(parent_scores) * 0.8
        else:
            synthetic_score = 0.3

        children: List[Tuple[Dict[str, Any], float]] = []
        for r in results:
            child_dict = {
                "id": r["id"],
                "title": r.get("title", ""),
                "summary": r.get("summary", ""),
                "level": r.get("level", 0),
                "rank": r.get("rank", 0),
                "parent_id": r.get("parent_id", ""),
                "_is_child": True,  # marker for metadata traceability
            }
            children.append((child_dict, synthetic_score))

        logger.info(
            "route6_community_children_fetched",
            parent_count=len(parent_ids),
            children_count=len(children),
            child_titles=[c.get("title", "?") for c, _ in children[:5]],
        )

        return children

    # ==================================================================
    # Shared prompt builder (used by _synthesize and _stream_synthesize)
    # ==================================================================

    async def _build_synthesis_prompt(
        self,
        query: str,
        communities: List[Dict[str, Any]],
        section_headings: List[Dict[str, Any]],
        sentence_evidence: List[Dict[str, Any]],
        entity_doc_map: Optional[Dict[str, List[str]]] = None,
        language: Optional[str] = None,
    ) -> str:
        """Build the full synthesis prompt. Shared by _synthesize and _stream_synthesize."""
        # Format community summaries
        community_extract = os.getenv(
            "ROUTE6_COMMUNITY_EXTRACT", "1"
        ).strip().lower() in {"1", "true", "yes"}

        if community_extract and communities:
            summaries_text = await self._extract_community_key_points(query, communities)
        elif communities:
            summary_lines = []
            for i, c in enumerate(communities, 1):
                title = c.get("title", f"Theme {i}")
                summary = (c.get("summary") or "").strip()
                if summary:
                    summary_lines.append(f"{i}. **{title}**: {summary}")
                else:
                    entities = ", ".join(c.get("entity_names", [])[:10])
                    if entities:
                        summary_lines.append(f"{i}. **{title}**: Entities: {entities}")
            summaries_text = "\n".join(summary_lines) if summary_lines else "(No thematic context available)"
        else:
            summaries_text = "(No thematic context available)"

        # Format section headings
        if section_headings:
            heading_lines = []
            for i, sec in enumerate(section_headings, 1):
                title = sec.get("title", f"Section {i}")
                doc_title = sec.get("document_title", "")
                path_key = sec.get("path_key", "").strip()
                parts = []
                if doc_title:
                    parts.append(f"[{doc_title}]")
                if path_key and path_key != title:
                    parts.append(path_key)
                else:
                    parts.append(title)
                heading_lines.append(f"- {' '.join(parts)}")
            headings_text = "\n".join(heading_lines)
        else:
            headings_text = "(No document structure available)"

        # Format sentence evidence
        if sentence_evidence:
            evidence_lines = []
            for i, ev in enumerate(sentence_evidence, 1):
                doc = ev.get("document_title") or "Unknown"
                section = ev.get("section_path") or ""
                text = ev.get("text") or ""
                if section:
                    evidence_lines.append(f"{i}. [{doc} > {section}] {text}")
                else:
                    evidence_lines.append(f"{i}. [{doc}] {text}")
            evidence_text = "\n".join(evidence_lines)
        else:
            evidence_text = "(No document evidence retrieved)"

        # Format entity-document coverage
        if entity_doc_map:
            cov_lines = []
            for entity_name, doc_titles in entity_doc_map.items():
                docs_str = ", ".join(sorted(t for t in doc_titles if t))
                cov_lines.append(
                    f"- {entity_name}: {docs_str} ({len(doc_titles)} document{'s' if len(doc_titles) != 1 else ''})"
                )
            entity_coverage_text = "\n".join(cov_lines)
        else:
            entity_coverage_text = ""

        # Feature 4: Token budget
        max_tokens = int(os.getenv("ROUTE6_MAX_CONTEXT_TOKENS", "0"))
        if max_tokens > 0:
            summaries_tokens = len(_tiktoken_enc.encode(summaries_text))
            sections = [
                ("evidence", evidence_text),
                ("entity_coverage", entity_coverage_text),
                ("headings", headings_text),
            ]
            other_tokens = sum(len(_tiktoken_enc.encode(t)) for _, t in sections)
            total = summaries_tokens + other_tokens
            if total > max_tokens:
                budget = max_tokens - summaries_tokens
                truncated = {}
                for name, text in sections:
                    tokens = _tiktoken_enc.encode(text)
                    if len(tokens) <= budget:
                        truncated[name] = text
                        budget -= len(tokens)
                    else:
                        truncated[name] = _tiktoken_enc.decode(tokens[:max(budget, 0)])
                        budget = 0
                evidence_text = truncated["evidence"]
                entity_coverage_text = truncated["entity_coverage"]
                headings_text = truncated["headings"]

        prompt = CONCEPT_SYNTHESIS_PROMPT.format(
            query=query,
            community_summaries=summaries_text,
            section_headings=headings_text,
            sentence_evidence=evidence_text,
            entity_coverage=entity_coverage_text,
        )

        if language:
            prompt += f"\n\nIMPORTANT: Respond entirely in {language}."

        return prompt

    async def _retrieve_sentence_evidence(
        self,
        query: str,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve sentence-level evidence via Voyage vector search.

        Reuses the same sentence index that Route 3 uses (sentence_embedding).
        Document diversity ensures minority documents get representation.

        Args:
            query: User query to embed and search.
            top_k: Max sentences to retrieve.

        Returns:
            List of sentence dicts with text, metadata, and score.
        """
        voyage_service = _get_voyage_service()
        if not voyage_service:
            logger.warning("route6_sentence_search_no_voyage_service")
            return []

        if not self.neo4j_driver:
            logger.warning("route6_sentence_search_no_neo4j_driver")
            return []

        # 1. Embed query with Voyage
        try:
            query_embedding = voyage_service.embed_query(query)
        except Exception as e:
            logger.warning("route6_sentence_embed_failed", error=str(e))
            return []

        threshold = float(os.getenv("ROUTE6_SENTENCE_THRESHOLD", "0.2"))
        # R6-6: Fetch 3x for denoising headroom; diversity is applied AFTER reranking
        # in execute() so there is no need for diversity logic inside this method.
        fetch_k = top_k * 3
        group_ids = self.group_ids

        # R6-1: Build folder filter clause — applied AFTER OPTIONAL MATCH for doc.
        # Uses Cypher's IS NULL test so the WHERE is a no-op when no folder scope is set.
        folder_filter_clause = (
            "// R6-1: folder scope filter (no-op when $folder_id IS NULL)\n"
            "        WITH sent, score, doc, sec, prev_sent, next_sent\n"
            "        WHERE $folder_id IS NULL"
            " OR (doc IS NOT NULL AND (doc)-[:IN_FOLDER]->(:Folder {id: $folder_id}))\n"
        )

        # 2. Vector search on Sentence nodes + collect parent context
        # sentence_embedding index does NOT have group_id as additional
        # filterable property, so filter group_id OUTSIDE the SEARCH clause.
        cypher = f"""CYPHER 25
        CALL () {{
            MATCH (sent:Sentence)
            SEARCH sent IN (VECTOR INDEX sentence_embedding FOR $embedding LIMIT $top_k)
            SCORE AS score
            WHERE score >= $threshold AND sent.group_id IN $group_ids
            RETURN sent, score
        }}

        // Get document + section context
        OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
        OPTIONAL MATCH (sent)-[:IN_SECTION]->(sec:Section)

        // Expand via NEXT for local context (1 hop each direction)
        OPTIONAL MATCH (sent)-[:NEXT]->(next_sent:Sentence)
        OPTIONAL MATCH (prev_sent:Sentence)-[:NEXT]->(sent)

        {folder_filter_clause}
        RETURN sent.id AS sentence_id,
               sent.text AS text,
               sent.source AS source,
               sent.section_path AS section_path,
               sec.path_key AS section_key,
               sent.page AS page,
               sent.parent_text AS chunk_text,
               doc.title AS document_title,
               doc.id AS document_id,
               score,
               prev_sent.text AS prev_text,
               next_sent.text AS next_text
        ORDER BY score DESC
        """

        try:
            loop = asyncio.get_running_loop()
            driver = self.neo4j_driver
            folder_id = self.folder_id

            def _run_search():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=self.group_id,
                        global_group_id=settings.GLOBAL_GROUP_ID,
                        group_ids=group_ids,
                        top_k=fetch_k,
                        threshold=threshold,
                        folder_id=folder_id,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(self._executor, _run_search)
        except Exception as e:
            logger.warning("route6_sentence_search_failed", error=str(e))
            return []

        if not results:
            logger.info("route6_sentence_search_empty", query=query[:50])
            return []

        # 3. Deduplicate by sentence_id and build context passages
        seen_sentences: set = set()
        evidence: List[Dict[str, Any]] = []

        for r in results:
            sid = r.get("sentence_id", "")
            if sid in seen_sentences:
                continue
            seen_sentences.add(sid)

            # Build passage: prev + current + next for coherent context
            parts = []
            if r.get("prev_text"):
                parts.append(r["prev_text"].strip())
            parts.append((r.get("text") or "").strip())
            if r.get("next_text"):
                parts.append(r["next_text"].strip())
            passage = " ".join(parts)

            # R6-X: include chunk_text (full parent chunk) alongside the
            # sentence-window passage.  chunk_text is fetched by the Cypher
            # query but was previously discarded.  Synthesis can use it as
            # extended context when the passage alone is insufficient (e.g.
            # date-comparison or entity-count queries where the key fact lives
            # in an adjacent clause rather than the retrieved sentence itself).
            chunk_text = (r.get("chunk_text") or "").strip()
            evidence.append({
                "text": passage,
                "sentence_text": r.get("text") or "",
                "chunk_text": chunk_text,
                "score": r.get("score", 0),
                "document_title": r.get("document_title", "Unknown"),
                "document_id": r.get("document_id", ""),
                "section_path": r.get("section_key") or r.get("section_path", ""),
                "page": r.get("page"),
                "sentence_id": sid,
            })

        logger.info(
            "route6_sentence_search_complete",
            query=query[:50],
            results_raw=len(results),
            evidence_deduped=len(evidence),
            top_scores=[round(e["score"], 4) for e in evidence[:5]],
            top_docs=list(set(e["document_title"] for e in evidence[:10])),
        )

        return evidence

    # ==================================================================
    # R6-XII: Entity-Centric Sentence Expansion
    # ==================================================================

    async def _expand_sentences_via_entities(
        self,
        seed_evidence: List[Dict[str, Any]],
        seed_count: int = 10,
        top_k: int = 20,
        min_overlap: int = 1,
    ) -> List[Dict[str, Any]]:
        """Expand sentence pool via shared-entity graph traversal.

        After the initial vector search retrieves seed sentences, this method
        traverses (Sentence)-[:MENTIONS]->(Entity)<-[:MENTIONS]-(Sentence)
        edges to discover additional sentences that share entities with the
        seeds.  This helps multi-hop reasoning where relevant facts live in
        sentences that don't have high vector similarity to the query but
        are topically connected via entities.

        Args:
            seed_evidence: Sentence evidence dicts from vector search (sorted
                by score descending).
            seed_count: Number of top-scoring seeds to use for expansion.
            top_k: Max expanded sentences to return.
            min_overlap: Minimum number of distinct shared entities for a
                sentence to qualify.

        Returns:
            List of evidence dicts matching the schema of
            ``_retrieve_sentence_evidence`` output, with additional fields
            ``expansion_source`` and ``shared_entity_count``.
        """
        if not self.neo4j_driver:
            logger.warning("route6_entity_expansion_no_neo4j_driver")
            return []

        # Use top seed_count sentences as expansion seeds
        seeds = seed_evidence[:seed_count]
        seed_ids = [s["sentence_id"] for s in seeds if s.get("sentence_id")]
        if not seed_ids:
            return []

        # Exclude ALL sentences already in the pool to avoid duplicates
        exclude_ids = [
            s["sentence_id"] for s in seed_evidence if s.get("sentence_id")
        ]

        # Synthetic score: position expanded sentences below genuine vector
        # matches so the reranker controls final ordering.
        seed_scores = [s.get("score", 0) for s in seeds if s.get("score")]
        synthetic_score = min(seed_scores) * 0.8 if seed_scores else 0.3

        group_ids = self.group_ids
        folder_id = self.folder_id

        # R6-1: folder scope filter (same pattern as sentence vector search)
        folder_filter_clause = (
            "// R6-1: folder scope filter (no-op when $folder_id IS NULL)\n"
            "        WITH expanded, shared_entity_count, doc, sec,"
            " prev_sent, next_sent\n"
            "        WHERE $folder_id IS NULL"
            " OR (doc IS NOT NULL AND (doc)-[:IN_FOLDER]->(:Folder {id: $folder_id}))\n"
        )

        cypher = f"""
        UNWIND $seed_ids AS seed_id
        MATCH (seed:Sentence {{id: seed_id}})
        WHERE seed.group_id IN $group_ids
        MATCH (seed)-[:MENTIONS]->(e:Entity)
        WHERE e.group_id IN $group_ids
        MATCH (e)<-[:MENTIONS]-(expanded:Sentence)
        WHERE expanded.group_id IN $group_ids
              AND NOT expanded.id IN $exclude_ids

        WITH expanded, count(DISTINCT e) AS shared_entity_count
        WHERE shared_entity_count >= $min_overlap

        OPTIONAL MATCH (expanded)-[:IN_DOCUMENT]->(doc:Document)
        OPTIONAL MATCH (expanded)-[:IN_SECTION]->(sec:Section)
        OPTIONAL MATCH (expanded)-[:NEXT]->(next_sent:Sentence)
        OPTIONAL MATCH (prev_sent:Sentence)-[:NEXT]->(expanded)

        {folder_filter_clause}
        RETURN DISTINCT expanded.id AS sentence_id,
               expanded.text AS text,
               expanded.source AS source,
               expanded.section_path AS section_path,
               sec.path_key AS section_key,
               expanded.page AS page,
               expanded.parent_text AS chunk_text,
               doc.title AS document_title,
               doc.id AS document_id,
               shared_entity_count,
               prev_sent.text AS prev_text,
               next_sent.text AS next_text
        ORDER BY shared_entity_count DESC
        LIMIT $top_k
        """

        try:
            loop = asyncio.get_running_loop()
            driver = self.neo4j_driver

            def _run_expansion():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher,
                        seed_ids=seed_ids,
                        exclude_ids=exclude_ids,
                        group_ids=group_ids,
                        folder_id=folder_id,
                        min_overlap=min_overlap,
                        top_k=top_k,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(self._executor, _run_expansion)
        except Exception as e:
            logger.warning("route6_entity_expansion_query_failed", error=str(e))
            return []

        if not results:
            logger.info("route6_entity_expansion_empty",
                        seed_count=len(seed_ids))
            return []

        # Build evidence dicts matching _retrieve_sentence_evidence schema
        evidence: List[Dict[str, Any]] = []
        # Collect seed section paths for proximity boosting
        seed_sections = {s.get("section_path", "") for s in seeds if s.get("section_path")}
        for r in results:
            parts = []
            if r.get("prev_text"):
                parts.append(r["prev_text"].strip())
            parts.append((r.get("text") or "").strip())
            if r.get("next_text"):
                parts.append(r["next_text"].strip())
            passage = " ".join(parts)

            chunk_text = (r.get("chunk_text") or "").strip()
            ev_section = r.get("section_key") or r.get("section_path", "")
            # Section-proximity boost: same section as seeds gets 1.3× score
            ev_score = synthetic_score
            if ev_section and ev_section in seed_sections:
                ev_score = synthetic_score * 1.3
            evidence.append({
                "text": passage,
                "sentence_text": r.get("text") or "",
                "chunk_text": chunk_text,
                "score": ev_score,
                "document_title": r.get("document_title", "Unknown"),
                "document_id": r.get("document_id", ""),
                "section_path": ev_section,
                "page": r.get("page"),
                "sentence_id": r.get("sentence_id", ""),
                "expansion_source": "entity",
                "shared_entity_count": r.get("shared_entity_count", 0),
            })

        logger.info(
            "route6_entity_expansion_complete",
            seed_count=len(seed_ids),
            expanded=len(evidence),
            top_overlap=[e["shared_entity_count"] for e in evidence[:5]],
            top_docs=list(set(e["document_title"] for e in evidence[:10])),
        )

        return evidence

    # ==================================================================
    # Section Heading Search (via structural_embedding, Route 5 Tier 2)
    # ==================================================================

    async def _retrieve_section_headings(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Retrieve section headings via structural embedding cosine similarity.

        Uses the same Section.structural_embedding (Voyage 2048d) that Route 5
        Tier 2 uses.  This surfaces document structure like section titles
        ("EXHIBIT A - SCOPE OF WORK") that sentence search misses because
        headings are sparse text without sentence structure.

        Args:
            query: User query to embed and match against section headings.
            top_k: Max sections to retrieve.

        Returns:
            List of section dicts with title, summary, path_key, document_title, score.
        """
        voyage_service = _get_voyage_service()
        if not voyage_service:
            logger.warning("route6_section_search_no_voyage_service")
            return []

        if not self.neo4j_driver:
            logger.warning("route6_section_search_no_neo4j_driver")
            return []

        # 1. Embed query with Voyage
        try:
            query_embedding = voyage_service.embed_query(query)
        except Exception as e:
            logger.warning("route6_section_embed_failed", error=str(e))
            return []

        min_similarity = float(os.getenv("ROUTE6_SECTION_MIN_SIMILARITY", "0.25"))
        group_ids = self.group_ids
        folder_id = self.folder_id

        # 2. Cosine similarity against Section.structural_embedding
        # Note: no vector index exists for Section.structural_embedding (architectural
        # decision — see ARCHITECTURE_ROUTE5_UNIFIED_HIPPORAG_2026-02-16.md §section).
        # Brute-force scan is acceptable: typically <20 sections per group.
        cypher = """
        MATCH (s:Section)
        WHERE s.group_id IN $group_ids AND s.structural_embedding IS NOT NULL
        WITH s, vector.similarity.cosine(s.structural_embedding, $query_embedding) AS score
        WHERE score >= $min_similarity

        // Get parent document title
        OPTIONAL MATCH (s)<-[:HAS_SECTION]-(doc:Document)

        // R6-2: Folder scope filter (no-op when $folder_id IS NULL)
        WITH s, score, doc
        WHERE $folder_id IS NULL
           OR (doc IS NOT NULL AND (doc)-[:IN_FOLDER]->(:Folder {id: $folder_id}))

        RETURN s.title AS title,
               s.summary AS summary,
               s.path_key AS path_key,
               s.depth AS depth,
               doc.title AS document_title,
               score
        ORDER BY score DESC
        LIMIT $top_k
        """

        try:
            loop = asyncio.get_running_loop()
            driver = self.neo4j_driver

            def _run_search():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher,
                        query_embedding=query_embedding,
                        group_ids=group_ids,
                        min_similarity=min_similarity,
                        top_k=top_k,
                        folder_id=folder_id,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(self._executor, _run_search)
        except Exception as e:
            logger.warning("route6_section_search_failed", error=str(e))
            return []

        if not results:
            logger.info("route6_section_search_empty", query=query[:50])
            return []

        logger.info(
            "route6_section_search_complete",
            query=query[:50],
            matched=len(results),
            top_sections=[
                (r.get("title", "?")[:40], round(r.get("score", 0), 4))
                for r in results[:5]
            ],
        )

        return results

    # ==================================================================
    # Entity-Document Coverage (R6-XI)
    # ==================================================================

    async def _retrieve_entity_document_map(
        self,
        top_k: int = 20,
    ) -> Dict[str, List[str]]:
        """Return {entity_name: [doc_title, ...]} for the top entities by document count.

        Uses a 2-hop traversal Entity←MENTIONS←Sentence→IN_DOCUMENT→Document
        (same path the Route 7 PPR engine walks). This is more complete than the
        pre-materialised APPEARS_IN_DOCUMENT edge, which can miss documents when
        ingestion did not populate that shortcut edge for every entity.

        Only includes entities that appear in 2+ documents to filter noise.
        Result is sorted by document count descending so the most cross-document
        entities appear first.

        Used by _synthesize() to answer queries like "which entity appears in
        the most documents?" without relying on heuristic LLM counting from
        sentence snippets.

        Args:
            top_k: Maximum number of entities to return (default 20).

        Returns:
            Dict mapping entity name → list of document titles, or {} on failure.
        """
        if not self.neo4j_driver:
            return {}

        group_ids = self.group_ids
        folder_id = self.folder_id

        cypher = """
        MATCH (e:Entity)<-[:MENTIONS]-(s:Sentence)-[:IN_DOCUMENT]->(d:Document)
        WHERE e.group_id IN $group_ids AND s.group_id IN $group_ids AND d.group_id IN $group_ids

        // R6-1 pattern: folder scope filter (no-op when $folder_id IS NULL)
        WITH e, d
        WHERE $folder_id IS NULL
           OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id})

        WITH e, collect(DISTINCT d.title) AS doc_titles, count(DISTINCT d) AS doc_count
        WHERE doc_count >= 2
        RETURN e.name AS entity_name, doc_titles, doc_count
        ORDER BY doc_count DESC, e.name ASC
        LIMIT $top_k
        """

        try:
            loop = asyncio.get_running_loop()
            driver = self.neo4j_driver

            def _run():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher,
                        group_ids=group_ids,
                        folder_id=folder_id,
                        top_k=top_k,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(self._executor, _run)

            # Filter noise: remove entities that are numbers, single generic
            # words, or too short to be meaningful names.
            def _is_meaningful(name: str) -> bool:
                n = name.strip()
                if len(n) < 3:
                    return False
                # Pure numbers / dates / zip codes
                if re.match(r'^[\d\s,.\-/]+$', n):
                    return False
                # Single generic word (lowercase, no spaces)
                generic = {
                    "contract", "agreement", "document", "owner", "agent",
                    "builder", "customer", "party", "property", "state",
                    "county", "section", "change", "notice", "date",
                    "service", "term", "condition", "fee", "payment",
                }
                if n.lower() in generic:
                    return False
                return True

            entity_map = {
                r["entity_name"]: r["doc_titles"]
                for r in results
                if _is_meaningful(r["entity_name"])
            }

            logger.info(
                "route6_entity_doc_map_complete",
                entities=len(entity_map),
                top_entries=[
                    (r["entity_name"], r["doc_count"]) for r in results[:5]
                ],
            )
            return entity_map

        except Exception as e:
            logger.warning("route6_entity_doc_map_failed", error=str(e))
            return {}

    # ==================================================================
    # Document diversification (reused from Route 3)
    # ==================================================================

    @staticmethod
    def _diversify_by_document(
        evidence: List[Dict[str, Any]],
        top_k: int,
        min_per_doc: int = 2,
        score_gate: float = 0.85,
    ) -> List[Dict[str, Any]]:
        """Ensure every document with relevant sentences gets representation.

        Algorithm:
          1. Group sentences by document_id (preserving score order).
          2. Score-gate: only reserve from a minority document if its
             top sentence scores >= score_gate x top-1 global score.
          3. Reserve the top min_per_doc sentences from each qualifying doc.
          4. Fill remaining slots with globally highest-scoring sentences.
          5. Sort final list by score descending.
        """
        by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for ev in evidence:
            doc_id = ev.get("document_id") or ev.get("document_title") or "unknown"
            by_doc[doc_id].append(ev)

        top_score = evidence[0].get("score", 0) if evidence else 0
        score_floor = top_score * score_gate

        selected_ids: set = set()
        selected: List[Dict[str, Any]] = []

        # Phase 1: reserve min_per_doc from each qualifying document
        for doc_id, doc_evidence in by_doc.items():
            best_doc_score = doc_evidence[0].get("score", 0) if doc_evidence else 0
            if best_doc_score < score_floor:
                continue
            for ev in doc_evidence[:min_per_doc]:
                sid = ev.get("sentence_id", id(ev))
                if sid not in selected_ids:
                    selected_ids.add(sid)
                    selected.append(ev)

        # Phase 2: fill remaining slots
        remaining = top_k - len(selected)
        if remaining > 0:
            for ev in evidence:
                sid = ev.get("sentence_id", id(ev))
                if sid not in selected_ids:
                    selected_ids.add(sid)
                    selected.append(ev)
                    remaining -= 1
                    if remaining <= 0:
                        break

        selected.sort(key=lambda e: e.get("score", 0), reverse=True)

        logger.info(
            "route6_sentence_diversity_applied",
            pool_size=len(evidence),
            selected=len(selected),
            top_k=top_k,
        )

        return selected[:top_k]

    # ==================================================================
    # Denoise + Rerank (reused from Route 3)
    # ==================================================================

    @staticmethod
    def _denoise_sentences(
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove noisy, non-informative sentences before reranking.

        Filters out HTML fragments, signature blocks, tiny fragments,
        and bare headings without sentence punctuation.
        """
        cleaned: List[Dict[str, Any]] = []

        for ev in evidence:
            text = (ev.get("sentence_text") or ev.get("text") or "").strip()
            passage = (ev.get("text") or "").strip()

            # Rule 1: HTML / markup-heavy
            tag_count = len(re.findall(r"<[^>]+>", text))
            if tag_count >= 2:
                continue

            # Rule 2: Too short / fragment
            if len(text) < 25:
                continue

            # Rule 3: Signature / form boilerplate
            if re.search(
                r"(?i)(signature|signed this|print\)|registration number"
                r"|authorized representative)",
                text,
            ):
                continue

            # Rule 4: Bare label ending with colon
            if len(text) < 60 and text.endswith(":"):
                continue

            # Rule 5: No sentence structure (heading-only)
            if len(text) < 50 and not re.search(r"[.?!]", text):
                continue

            # Strip residual HTML tags from the passage
            if "<" in passage:
                passage = re.sub(r"<[^>]+>", "", passage).strip()
                ev = {**ev, "text": passage}

            cleaned.append(ev)

        logger.info(
            "route6_denoise_sentences",
            before=len(evidence),
            after=len(cleaned),
            removed=len(evidence) - len(cleaned),
        )
        return cleaned

    async def _rerank_sentences(
        self,
        query: str,
        evidence: List[Dict[str, Any]],
        top_k: int = 15,
    ) -> List[Dict[str, Any]]:
        """Rerank denoised sentences using voyage-rerank-2.5."""
        rerank_model = os.getenv("ROUTE6_RERANK_MODEL", "rerank-2.5")

        try:
            vc = make_voyage_client()
            documents = [ev.get("sentence_text") or ev.get("text") or "" for ev in evidence]

            rr_result = await rerank_with_retry(
                vc,
                query=query,
                documents=documents,
                model=rerank_model,
                top_k=min(top_k, len(documents)),
                executor=self._executor,
            )

            # Track reranker usage (fire-and-forget)
            try:
                _rerank_tokens = getattr(rr_result, "total_tokens", 0)
                acc = getattr(self, "_token_accumulator", None)
                if acc is not None:
                    acc.add_rerank(rerank_model, _rerank_tokens, len(documents))
                from src.core.services.usage_tracker import get_usage_tracker
                _tracker = get_usage_tracker()
                asyncio.ensure_future(_tracker.log_rerank_usage(
                    partition_id=user_id if user_id else self.group_id,
                    model=rerank_model,
                    total_tokens=_rerank_tokens,
                    documents_reranked=len(documents),
                    route="route_6",
                    user_id=user_id,
                ))
            except Exception:
                pass

            reranked: List[Dict[str, Any]] = []
            for rr in rr_result.results:
                # R6-4: Propagate reranker relevance score to the canonical `score`
                # field so that downstream consumers (citations, diversity) see the
                # reranked score instead of the original embedding similarity score.
                ev = {
                    **evidence[rr.index],
                    "rerank_score": rr.relevance_score,
                    "score": rr.relevance_score,
                }
                reranked.append(ev)

            logger.info(
                "route6_rerank_complete",
                model=rerank_model,
                input_count=len(evidence),
                output_count=len(reranked),
                top_score=round(reranked[0]["rerank_score"], 4) if reranked else 0,
                bottom_score=round(reranked[-1]["rerank_score"], 4) if reranked else 0,
            )
            return reranked

        except Exception as e:
            # R6-3: Reranker failures must not crash the request.  The caller in
            # execute() also wraps this call, but the explicit return here ensures
            # graceful degradation even when called from other contexts.
            logger.warning("route6_rerank_failed", error=str(e))
            return evidence[:top_k]

    # ==================================================================
    # Citations
    # ==================================================================

    @staticmethod
    def _build_citations(
        communities: List[Dict[str, Any]],
        scores: List[float],
        sentence_evidence: List[Dict[str, Any]],
    ) -> List[Citation]:
        """Build citations from communities and sentence evidence.

        Community citations come first (thematic sources), followed by
        sentence-level citations (direct document evidence).
        """
        citations: List[Citation] = []

        # Community-level citations (all matched communities, not just those with claims)
        for i, (community, score) in enumerate(zip(communities, scores), 1):
            title = community.get("title", "Untitled")
            summary = community.get("summary", "")
            if summary.strip():
                citations.append(
                    Citation(
                        index=i,
                        sentence_id=f"community_{community.get('id', i)}",
                        document_id="",
                        document_title=title,
                        score=round(score, 4),
                        text_preview=summary[:200],
                    )
                )

        # Sentence-level citations (top 5 documents to avoid overload)
        offset = len(citations)
        seen_docs: set = set()
        for ev in sentence_evidence:
            doc_id = ev.get("document_id", "")
            doc_title = ev.get("document_title", "Unknown")
            dedup_key = doc_id or doc_title
            if dedup_key in seen_docs:
                continue
            seen_docs.add(dedup_key)
            offset += 1
            sent_text = ev.get("sentence_text", "")
            citations.append(
                Citation(
                    index=offset,
                    sentence_id=ev.get("sentence_id", f"sentence_{offset}"),
                    document_id=ev.get("document_id", ""),
                    document_title=doc_title,
                    score=round(ev.get("score", 0), 4),
                    text_preview=sent_text[:200],
                    page_number=ev.get("page"),
                    sentence_text=sent_text,
                    sentence_length=len(sent_text),
                )
            )
            if len(seen_docs) >= 5:
                break

        return citations
