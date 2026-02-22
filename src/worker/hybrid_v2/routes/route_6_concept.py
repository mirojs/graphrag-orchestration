"""Route 6: Concept Search — Community-Aware Synthesis.

Best for thematic/cross-document concept queries:
- "What are the main compliance risks?"
- "Summarize key themes across documents"
- "Compare termination clauses across agreements"

Architecture (3 steps, 1 LLM call):
  1. Community Match + Sentence Search + Section Heading Search  (parallel)
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
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .base import BaseRouteHandler, Citation, RouteResult
from .route_6_prompts import CONCEPT_SYNTHESIS_PROMPT

logger = structlog.get_logger(__name__)

# Voyage embedding service (lazy singleton) — shared with Route 3
_voyage_service = None
_voyage_init_attempted = False


def _get_voyage_service():
    """Get Voyage embedding service for sentence search."""
    global _voyage_service, _voyage_init_attempted
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

        community_top_k = int(os.getenv("ROUTE6_COMMUNITY_TOP_K", "10"))
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

        timings_ms["step_1_parallel_ms"] = int(
            (time.perf_counter() - t0) * 1000
        )

        logger.info(
            "route6_step_1_complete",
            communities=len(community_data),
            sentences_raw=len(sentence_evidence),
            sections=len(section_headings),
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
            #   Previously diversity ran inside _retrieve_sentence_evidence on the raw
            #   fetch, then reranking nullified it by cutting the diverse set to top_k.
            #
            #   Correct pipeline:
            #     1. Denoise  (removes junk sentences)
            #     2. Diversity → pool of 2×rerank_top_k (guarantees document coverage)
            #     3. Rerank   → final rerank_top_k from the diverse pool
            #
            #   The reranker picks the BEST sentences from a pool that already covers
            #   all qualifying documents, so both relevance and coverage are preserved.
            if diversity_enabled and sentence_evidence:
                diversity_pool_k = rerank_top_k * 2
                if len(sentence_evidence) > diversity_pool_k:
                    sentence_evidence = self._diversify_by_document(
                        sentence_evidence,
                        top_k=diversity_pool_k,
                        min_per_doc=min_per_doc,
                        score_gate=score_gate,
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
                s.get("title", "?"): round(s.get("score", 0), 4)
                for s in section_headings
            },
            "sentence_evidence_count": len(sentence_evidence),
            "route_description": "Concept search — direct community synthesis (v2 + section headings)",
            "version": "v2",
        }

        if include_context:
            metadata["community_summaries"] = [
                {
                    "title": c.get("title", ""),
                    "summary": c.get("summary", "")[:300],
                    "score": round(s, 4),
                }
                for c, s in zip(community_data, community_scores)
            ]
            metadata["section_headings"] = [
                {
                    "title": s.get("title", ""),
                    "summary": s.get("summary", "")[:300],
                    "path_key": s.get("path_key", ""),
                    "document_title": s.get("document_title", ""),
                    "score": round(s.get("score", 0), 4),
                }
                for s in section_headings
            ]
            metadata["sentence_evidence"] = [
                {
                    "text": s.get("text", "")[:200],
                    "source": s.get("document_title", ""),
                    "section_path": s.get("section_path", ""),
                    "score": round(s.get("score", 0), 4),
                }
                for s in sentence_evidence[:10]
            ]

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
    ) -> str:
        """Synthesize community summaries + section headings + sentence evidence in one LLM call.

        Unlike Route 3's MAP-REDUCE, community summaries are passed directly
        as thematic context — no per-community claim extraction.

        Args:
            query: User query.
            communities: Matched community dicts with title/summary.
            section_headings: Matched section dicts with title/summary/path_key.
            sentence_evidence: Denoised + reranked sentence dicts.

        Returns:
            Synthesized response text.
        """
        # Format community summaries as thematic context
        if communities:
            summary_lines = []
            for i, c in enumerate(communities, 1):
                title = c.get("title", f"Theme {i}")
                summary = c.get("summary", "").strip()
                if summary:
                    summary_lines.append(f"{i}. **{title}**: {summary}")
                else:
                    # Include entity names as fallback context
                    entities = ", ".join(c.get("entity_names", [])[:10])
                    if entities:
                        summary_lines.append(f"{i}. **{title}**: Entities: {entities}")
            summaries_text = "\n".join(summary_lines) if summary_lines else "(No thematic context available)"
        else:
            summaries_text = "(No thematic context available)"

        # Format section headings as compact document structure (titles only, no summaries)
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

        # Format sentence evidence (with section header labels)
        if sentence_evidence:
            evidence_lines = []
            for i, ev in enumerate(sentence_evidence, 1):
                doc = ev.get("document_title", "Unknown")
                text = ev.get("text", "")
                section = ev.get("section_path", "")
                if section:
                    evidence_lines.append(
                        f"{i}. [{doc} > {section}] {text}"
                    )
                else:
                    evidence_lines.append(
                        f"{i}. [{doc}] {text}"
                    )
            evidence_text = "\n".join(evidence_lines)
        else:
            evidence_text = "(No document evidence retrieved)"

        prompt = CONCEPT_SYNTHESIS_PROMPT.format(
            query=query,
            community_summaries=summaries_text,
            section_headings=headings_text,
            sentence_evidence=evidence_text,
        )

        try:
            response = await self.llm.acomplete(prompt)
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
    # Sentence Vector Search (reused from Route 3 pattern)
    # ==================================================================

    async def _retrieve_sentence_evidence(
        self,
        query: str,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve sentence-level evidence via Voyage vector search.

        Reuses the same sentence index that Route 3 uses (sentence_embeddings_v2).
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
        group_id = self.group_id

        # R6-1: Build folder filter clause — applied AFTER OPTIONAL MATCH for doc.
        # Uses Cypher's IS NULL test so the WHERE is a no-op when no folder scope is set.
        folder_filter_clause = (
            "// R6-1: folder scope filter (no-op when $folder_id IS NULL)\n"
            "        WITH sent, score, chunk, doc, sec, prev_sent, next_sent\n"
            "        WHERE $folder_id IS NULL OR doc IS NULL"
            " OR (doc)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})\n"
        )

        # 2. Vector search on Sentence nodes + collect parent context
        cypher = f"""CYPHER 25
        CALL () {{
            MATCH (sent:Sentence)
            SEARCH sent IN (VECTOR INDEX sentence_embeddings_v2 FOR $embedding WHERE sent.group_id = $group_id LIMIT $top_k)
            SCORE AS score
            WHERE score >= $threshold
            RETURN sent, score
        }}

        // Get parent chunk + document + section context
        OPTIONAL MATCH (sent)-[:PART_OF]->(chunk:TextChunk)
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
               chunk.text AS chunk_text,
               doc.title AS document_title,
               doc.id AS document_id,
               score,
               prev_sent.text AS prev_text,
               next_sent.text AS next_text
        ORDER BY score DESC
        """

        try:
            loop = asyncio.get_event_loop()
            driver = self.neo4j_driver
            folder_id = self.folder_id

            def _run_search():
                with driver.session() as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
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
            parts.append(r.get("text", "").strip())
            if r.get("next_text"):
                parts.append(r["next_text"].strip())
            passage = " ".join(parts)

            evidence.append({
                "text": passage,
                "sentence_text": r.get("text", ""),
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
        group_id = self.group_id
        folder_id = self.folder_id

        # 2. Cosine similarity against Section.structural_embedding
        # Note: no vector index exists for Section.structural_embedding (architectural
        # decision — see ARCHITECTURE_ROUTE5_UNIFIED_HIPPORAG_2026-02-16.md §section).
        # Brute-force scan is acceptable: typically <20 sections per group.
        cypher = """
        MATCH (s:Section {group_id: $group_id})
        WHERE s.structural_embedding IS NOT NULL
        WITH s, vector.similarity.cosine(s.structural_embedding, $query_embedding) AS score
        WHERE score >= $min_similarity

        // Get parent document title
        OPTIONAL MATCH (s)<-[:HAS_SECTION]-(doc:Document)

        // R6-2: Folder scope filter (no-op when $folder_id IS NULL)
        WITH s, score, doc
        WHERE $folder_id IS NULL OR doc IS NULL
           OR (doc)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})

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
            loop = asyncio.get_event_loop()
            driver = self.neo4j_driver

            def _run_search():
                with driver.session() as session:
                    records = session.run(
                        cypher,
                        query_embedding=query_embedding,
                        group_id=group_id,
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
            text = (ev.get("sentence_text") or ev.get("text", "")).strip()
            passage = (ev.get("text", "")).strip()

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
            import voyageai
            from src.core.config import settings

            vc = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
            documents = [ev.get("sentence_text") or ev.get("text", "") for ev in evidence]

            loop = asyncio.get_event_loop()
            rr_result = await loop.run_in_executor(
                self._executor,
                lambda: vc.rerank(
                    query=query,
                    documents=documents,
                    model=rerank_model,
                    top_k=min(top_k, len(documents)),
                ),
            )

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
                        chunk_id=f"community_{community.get('id', i)}",
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
            citations.append(
                Citation(
                    index=offset,
                    chunk_id=ev.get("sentence_id", f"sentence_{offset}"),
                    document_id=ev.get("document_id", ""),
                    document_title=doc_title,
                    score=round(ev.get("score", 0), 4),
                    text_preview=ev.get("sentence_text", "")[:200],
                )
            )
            if len(seen_docs) >= 5:
                break

        return citations
