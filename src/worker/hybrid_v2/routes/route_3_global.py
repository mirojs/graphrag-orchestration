"""Route 3 v3: Global Search — Sentence-Enriched Map-Reduce.

Best for thematic/cross-document queries:
- "What are the main compliance risks?"
- "Summarize key themes across documents"
- "Compare termination clauses across agreements"

Architecture (v3 — 4 steps):
  1. Community Match   — reuse existing CommunityMatcher (top_k=10)
  1B. Sentence Search  — parallel Voyage vector search on Sentence nodes
  2. MAP               — parallel LLM calls: extract claims per community
  3. REDUCE            — single LLM call: synthesize claims + sentence evidence

v3 improvement over v2:
- Added sentence-level vector search (reuses Route 2's skeleton infrastructure)
- REDUCE now sees both community claims AND direct sentence evidence
- Eliminates false negatives for clause-level themes (confidentiality, insurance)
- Community matching fixed (was returning 0.0 similarity for all queries)
"""

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .base import BaseRouteHandler, Citation, RouteResult
from .route_3_prompts import MAP_PROMPT, REDUCE_WITH_EVIDENCE_PROMPT

logger = structlog.get_logger(__name__)

# Voyage embedding service (lazy singleton)
# NOTE: We do NOT gate on is_voyage_v2_enabled() because that requires
# VOYAGE_V2_ENABLED=true env var which isn't always set in all deployment
# paths.  hybrid.py already checks settings.VOYAGE_API_KEY directly and
# creates VoyageEmbedService — we mirror that pattern here.
_voyage_service = None
_voyage_init_attempted = False


def _get_voyage_service():
    """Get Voyage embedding service for sentence search.

    Matches hybrid.py's init pattern: check VOYAGE_API_KEY directly,
    skip the is_voyage_v2_enabled() gate that requires VOYAGE_V2_ENABLED.
    """
    global _voyage_service, _voyage_init_attempted
    if not _voyage_init_attempted:
        _voyage_init_attempted = True
        try:
            from src.core.config import settings
            if settings.VOYAGE_API_KEY:
                from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
                _voyage_service = VoyageEmbedService()
                logger.info("route3_voyage_service_initialized")
            else:
                logger.warning("route3_voyage_service_no_api_key")
        except Exception as e:
            logger.warning("route3_voyage_service_init_failed", error=str(e))
    return _voyage_service


class GlobalSearchHandler(BaseRouteHandler):
    """Route 3 v3: Sentence-enriched map-reduce for thematic queries."""

    ROUTE_NAME = "route_3_global_search"

    async def execute(
        self,
        query: str,
        response_type: str = "summary",
        knn_config: Optional[str] = None,
        prompt_variant: Optional[str] = None,
        synthesis_model: Optional[str] = None,
        include_context: bool = False,
    ) -> RouteResult:
        """Execute Route 3 v3: Sentence-enriched Map-Reduce global search.

        Steps:
          1. Community matching
          1B. Sentence vector search (parallel with step 2)
          2. MAP — parallel LLM calls per community
          3. REDUCE — synthesize claims + sentence evidence

        Args:
            query: The user's natural language query.
            response_type: Response format ("summary", "detailed_report", etc.)
            knn_config: Unused (kept for interface compat).
            prompt_variant: Unused (kept for interface compat).
            synthesis_model: Optional override for synthesis LLM model.
            include_context: If True, include MAP claims in metadata.

        Returns:
            RouteResult with response, citations, and metadata.
        """
        enable_timings = os.getenv("ROUTE3_RETURN_TIMINGS", "0").strip().lower() in {
            "1", "true", "yes",
        }
        timings_ms: Dict[str, int] = {}
        t_route_start = time.perf_counter()

        max_claims = int(os.getenv("ROUTE3_MAP_MAX_CLAIMS", "10"))
        community_top_k = int(os.getenv("ROUTE3_COMMUNITY_TOP_K", "10"))
        sentence_top_k = int(os.getenv("ROUTE3_SENTENCE_TOP_K", "30"))

        logger.info(
            "route_3v3_start",
            query=query[:80],
            response_type=response_type,
            max_claims=max_claims,
            community_top_k=community_top_k,
            sentence_top_k=sentence_top_k,
        )

        # ================================================================
        # Step 1: Community Matching (reuse CommunityMatcher)
        # ================================================================
        t0 = time.perf_counter()
        matched_communities = await self.pipeline.community_matcher.match_communities(
            query, top_k=community_top_k,
        )
        community_data: List[Dict[str, Any]] = [c for c, _ in matched_communities]
        community_scores: List[float] = [s for _, s in matched_communities]
        timings_ms["step_1_community_match_ms"] = int(
            (time.perf_counter() - t0) * 1000
        )

        logger.info(
            "step_1_complete",
            num_communities=len(community_data),
            titles=[c.get("title", "?") for c in community_data],
            top_scores=[round(s, 4) for s in community_scores[:5]],
        )

        # ================================================================
        # Steps 1B + 2: Sentence search + MAP (parallel)
        # ================================================================
        t0 = time.perf_counter()

        # Build MAP tasks
        map_tasks = [
            self._map_community(query, community, max_claims)
            for community in community_data
        ] if community_data else []

        # Run sentence search + MAP in parallel
        sentence_task = self._retrieve_sentence_evidence(query, top_k=sentence_top_k)

        # Gather all: sentence search + all MAP calls
        all_results = await asyncio.gather(
            sentence_task,
            *map_tasks,
            return_exceptions=True,
        )

        # Unpack: first result is sentence evidence, rest are MAP results
        sentence_evidence: List[Dict[str, Any]] = []
        if isinstance(all_results[0], list):
            sentence_evidence = all_results[0]
        elif isinstance(all_results[0], Exception):
            logger.warning("sentence_search_failed", error=str(all_results[0]))

        map_results: List[Tuple[str, List[str]]] = []
        for r in all_results[1:]:
            if isinstance(r, tuple):
                map_results.append(r)
            elif isinstance(r, Exception):
                logger.warning("map_call_failed", error=str(r))

        timings_ms["step_1b_2_parallel_ms"] = int((time.perf_counter() - t0) * 1000)

        # Flatten claims with community attribution
        all_claims: List[str] = []
        community_claim_counts: Dict[str, int] = {}
        for community, (title, claims) in zip(community_data, map_results):
            community_claim_counts[title] = len(claims)
            for claim in claims:
                all_claims.append(f"[Community: {title}] {claim}")

        logger.info(
            "step_1b_2_complete",
            total_claims=len(all_claims),
            sentence_evidence_count=len(sentence_evidence),
            per_community=community_claim_counts,
        )

        # ================================================================
        # Step 2B: Denoise + Rerank sentence evidence
        # ================================================================
        if sentence_evidence:
            t0 = time.perf_counter()
            raw_count = len(sentence_evidence)
            sentence_evidence = self._denoise_sentences(sentence_evidence)
            denoised_count = len(sentence_evidence)

            # Rerank denoised sentences with voyage-rerank-2.5
            rerank_enabled = os.getenv(
                "ROUTE3_SENTENCE_RERANK", "1"
            ).strip().lower() in {"1", "true", "yes"}
            rerank_top_k = int(os.getenv("ROUTE3_RERANK_TOP_K", "15"))
            if rerank_enabled and sentence_evidence:
                sentence_evidence = await self._rerank_sentences(
                    query, sentence_evidence, top_k=rerank_top_k,
                )

            timings_ms["step_2b_denoise_rerank_ms"] = int(
                (time.perf_counter() - t0) * 1000
            )
            logger.info(
                "step_2b_denoise_rerank_complete",
                raw=raw_count,
                after_denoise=denoised_count,
                after_rerank=len(sentence_evidence),
                rerank_enabled=rerank_enabled,
            )

        # ================================================================
        # Negative detection: only if BOTH claims and sentences are empty
        # ================================================================
        if not all_claims and not sentence_evidence:
            logger.info("route_3v3_negative_no_evidence")
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "negative_detection": True,
                    "detection_reason": "no_claims_and_no_sentences",
                    "matched_communities": [
                        c.get("title", "?") for c in community_data
                    ],
                },
            )

        # ================================================================
        # Step 3: REDUCE — synthesize claims + sentence evidence
        # ================================================================
        t0 = time.perf_counter()
        response_text = await self._reduce_with_evidence(
            query, response_type, all_claims, sentence_evidence,
        )
        timings_ms["step_3_reduce_ms"] = int((time.perf_counter() - t0) * 1000)
        timings_ms["total_ms"] = int((time.perf_counter() - t_route_start) * 1000)

        logger.info(
            "step_3_complete",
            response_length=len(response_text),
            total_ms=timings_ms["total_ms"],
        )

        # ================================================================
        # Build citations
        # ================================================================
        citations = self._build_citations(
            community_data, community_scores, community_claim_counts,
            sentence_evidence,
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
            "total_claims": len(all_claims),
            "sentence_evidence_count": len(sentence_evidence),
            "claims_per_community": community_claim_counts,
            "route_description": "Sentence-enriched map-reduce (v3)",
            "version": "v3",
        }

        if include_context:
            metadata["map_claims"] = all_claims
            metadata["sentence_evidence"] = [
                {
                    "text": s.get("text", "")[:200],
                    "source": s.get("document_title", ""),
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
    # Step 1B: Sentence Vector Search
    # ==================================================================

    async def _retrieve_sentence_evidence(
        self,
        query: str,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve sentence-level evidence via Voyage vector search.

        Reuses the same sentence index that Route 2 skeleton enrichment uses.
        This provides a direct query→source path that bypasses community
        abstraction layers.

        Args:
            query: User query to embed and search.
            top_k: Max sentences to retrieve.

        Returns:
            List of sentence dicts with text, metadata, and score.
        """
        voyage_service = _get_voyage_service()
        if not voyage_service:
            logger.warning("route3_sentence_search_no_voyage_service")
            return []

        if not self.neo4j_driver:
            logger.warning("route3_sentence_search_no_neo4j_driver")
            return []

        # 1. Embed query with Voyage
        try:
            query_embedding = voyage_service.embed_query(query)
        except Exception as e:
            logger.warning("route3_sentence_embed_failed", error=str(e))
            return []

        threshold = float(os.getenv("ROUTE3_SENTENCE_THRESHOLD", "0.2"))
        group_id = self.group_id

        # 2. Vector search on Sentence nodes + collect parent context
        cypher = """
        CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
        YIELD node AS sent, score
        WHERE sent.group_id = $group_id AND score >= $threshold

        // Get parent chunk + document context
        OPTIONAL MATCH (sent)-[:PART_OF]->(chunk:TextChunk)
        OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)

        // Expand via NEXT for local context (1 hop each direction)
        OPTIONAL MATCH (sent)-[:NEXT]->(next_sent:Sentence)
        OPTIONAL MATCH (prev_sent:Sentence)-[:NEXT]->(sent)

        RETURN sent.id AS sentence_id,
               sent.text AS text,
               sent.source AS source,
               sent.section_path AS section_path,
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

            def _run_search():
                with driver.session() as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        top_k=top_k,
                        threshold=threshold,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(self._executor, _run_search)
        except Exception as e:
            logger.warning("route3_sentence_search_failed", error=str(e))
            return []

        if not results:
            logger.info("route3_sentence_search_empty", query=query[:50])
            return []

        # 3. Deduplicate by chunk and build context passages
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
                "section_path": r.get("section_path", ""),
                "page": r.get("page"),
                "sentence_id": sid,
            })

        logger.info(
            "route3_sentence_search_complete",
            query=query[:50],
            results_raw=len(results),
            evidence_deduped=len(evidence),
            top_scores=[round(e["score"], 4) for e in evidence[:5]],
            top_docs=list(set(e["document_title"] for e in evidence[:10])),
        )

        return evidence

    # ==================================================================
    # MAP: extract claims from one community
    # ==================================================================

    async def _map_community(
        self,
        query: str,
        community: Dict[str, Any],
        max_claims: int,
    ) -> Tuple[str, List[str]]:
        """Extract relevant claims from a single community summary.

        Args:
            query: User query.
            community: Community dict with title, summary, entity_names.
            max_claims: Max claims to extract from this community.

        Returns:
            Tuple of (community_title, list_of_claim_strings).
        """
        title = community.get("title", "Untitled")
        summary = community.get("summary", "")
        entity_names = ", ".join(community.get("entity_names", [])[:20])

        if not summary.strip():
            logger.warning("map_skip_empty_summary", community=title)
            return (title, [])

        prompt = MAP_PROMPT.format(
            query=query,
            community_title=title,
            community_summary=summary,
            entity_names=entity_names or "N/A",
            max_claims=max_claims,
        )

        try:
            response = await self.llm.acomplete(prompt)
            text = response.text.strip()

            # Check for explicit "no relevant claims"
            if "NO RELEVANT CLAIMS" in text.upper():
                logger.info("map_no_relevant_claims", community=title)
                return (title, [])

            # Parse numbered list
            claims = self._parse_numbered_list(text)
            # Enforce max
            claims = claims[:max_claims]

            logger.info(
                "map_community_done",
                community=title,
                claims_extracted=len(claims),
            )
            return (title, claims)

        except Exception as e:
            logger.error(
                "map_community_failed",
                community=title,
                error=str(e),
                error_type=type(e).__name__,
            )
            return (title, [])

    # ==================================================================
    # REDUCE: synthesize claims + sentence evidence
    # ==================================================================

    async def _reduce_with_evidence(
        self,
        query: str,
        response_type: str,
        all_claims: List[str],
        sentence_evidence: List[Dict[str, Any]],
    ) -> str:
        """Synthesize MAP claims + sentence evidence into final response.

        Args:
            query: User query.
            response_type: Desired response format.
            all_claims: List of attributed claim strings from MAP.
            sentence_evidence: List of sentence dicts from vector search.

        Returns:
            Synthesized response text.
        """
        # Format community claims
        if all_claims:
            claims_text = "\n".join(
                f"{i}. {claim}" for i, claim in enumerate(all_claims, 1)
            )
        else:
            claims_text = "(No community claims extracted)"

        # Format sentence evidence — group by document for readability
        if sentence_evidence:
            evidence_lines = []
            for i, ev in enumerate(sentence_evidence, 1):
                doc = ev.get("document_title", "Unknown")
                score = ev.get("score", 0)
                text = ev.get("text", "")
                evidence_lines.append(
                    f"{i}. [Source: {doc}, relevance: {score:.2f}] {text}"
                )
            evidence_text = "\n".join(evidence_lines)
        else:
            evidence_text = "(No direct sentence evidence retrieved)"

        prompt = REDUCE_WITH_EVIDENCE_PROMPT.format(
            query=query,
            response_type=response_type,
            community_claims=claims_text,
            sentence_evidence=evidence_text,
        )

        try:
            response = await self.llm.acomplete(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(
                "reduce_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return (
                "An error occurred while synthesizing the response. "
                f"Please try again. (Error: {type(e).__name__})"
            )

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _parse_numbered_list(text: str) -> List[str]:
        """Parse a numbered list from LLM output.

        Handles multi-line items where continuation lines are joined
        back to their numbered item.

        Returns:
            List of claim strings (without numbering).
        """
        lines = text.strip().splitlines()
        items: List[str] = []
        current: Optional[str] = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Check if line starts with a number+period/paren
            # e.g. "1. Claim text" or "1) Claim text"
            if len(stripped) > 2 and stripped[0].isdigit():
                # Find the separator
                rest = stripped.lstrip("0123456789")
                if rest and rest[0] in ".)" and len(rest) > 1:
                    if current is not None:
                        items.append(current)
                    current = rest[1:].strip()
                    continue
            # Continuation line
            if current is not None:
                current += " " + stripped
            # Ignore lines before the first numbered item

        if current is not None:
            items.append(current)

        return items

    # ==================================================================
    # Step 2B: Denoise + Rerank
    # ==================================================================

    @staticmethod
    def _denoise_sentences(
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove noisy, non-informative sentences before reranking.

        Filters out:
        - HTML table fragments / markup-heavy content
        - Signature blocks and form labels
        - Tiny fragments that lack sentence structure
        - Bare headings without sentence punctuation

        This ensures the downstream reranker (voyage-rerank-2.5) receives
        clean, complete sentences — its accuracy is highest on well-formed
        natural language, not markup or fragments.

        Returns:
            Filtered list of evidence dicts.
        """
        cleaned: List[Dict[str, Any]] = []

        for ev in evidence:
            text = (ev.get("sentence_text") or ev.get("text", "")).strip()
            # Also clean the passage text (prev + current + next)
            passage = (ev.get("text", "")).strip()

            # --- Rule 1: HTML / markup-heavy ---
            tag_count = len(re.findall(r"<[^>]+>", text))
            if tag_count >= 2:
                continue

            # --- Rule 2: Too short / fragment ---
            if len(text) < 25:
                continue

            # --- Rule 3: Signature / form boilerplate ---
            if re.search(
                r"(?i)(signature|signed this|print\)|registration number"
                r"|authorized representative)",
                text,
            ):
                continue

            # --- Rule 4: Bare label ending with colon ---
            if len(text) < 60 and text.endswith(":"):
                continue

            # --- Rule 5: No sentence structure (heading-only) ---
            if len(text) < 50 and not re.search(r"[.?!]", text):
                continue

            # Strip any residual HTML tags from the passage that gets sent
            if "<" in passage:
                passage = re.sub(r"<[^>]+>", "", passage).strip()
                ev = {**ev, "text": passage}

            cleaned.append(ev)

        logger.info(
            "route3_denoise_sentences",
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
        """Rerank denoised sentences using voyage-rerank-2.5.

        Cross-encoder reranking produces a much wider score spread than
        bi-encoder vector search (which was 0.597-0.625 = 0.028 spread).
        This allows meaningful top-k selection.

        Args:
            query: User query.
            evidence: Denoised sentence evidence list.
            top_k: Max sentences to keep after reranking.

        Returns:
            Top-k evidence sorted by rerank score (descending).
        """
        rerank_model = os.getenv("ROUTE3_RERANK_MODEL", "rerank-2.5")

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

            # Build reranked list ordered by relevance_score descending
            reranked: List[Dict[str, Any]] = []
            for rr in rr_result.results:
                ev = {**evidence[rr.index], "rerank_score": rr.relevance_score}
                reranked.append(ev)

            logger.info(
                "route3_rerank_complete",
                model=rerank_model,
                input_count=len(evidence),
                output_count=len(reranked),
                top_score=round(reranked[0]["rerank_score"], 4) if reranked else 0,
                bottom_score=round(reranked[-1]["rerank_score"], 4) if reranked else 0,
            )
            return reranked

        except Exception:
            logger.exception("route3_rerank_failed")
            raise

    @staticmethod
    def _build_citations(
        communities: List[Dict[str, Any]],
        scores: List[float],
        claim_counts: Dict[str, int],
        sentence_evidence: List[Dict[str, Any]],
    ) -> List[Citation]:
        """Build citations from both communities and sentence evidence.

        Community citations come first (thematic sources), followed by
        sentence-level citations (direct document evidence).
        """
        citations: List[Citation] = []

        # Community-level citations
        for i, (community, score) in enumerate(zip(communities, scores), 1):
            title = community.get("title", "Untitled")
            if claim_counts.get(title, 0) > 0:
                citations.append(
                    Citation(
                        index=i,
                        chunk_id=f"community_{community.get('id', i)}",
                        document_id="",
                        document_title=title,
                        score=round(score, 4),
                        text_preview=(
                            community.get("summary", "")[:200]
                            if community.get("summary")
                            else ""
                        ),
                    )
                )

        # Sentence-level citations (top 5 to avoid overload)
        offset = len(citations)
        seen_docs: set = set()
        for ev in sentence_evidence:
            doc_title = ev.get("document_title", "Unknown")
            if doc_title in seen_docs:
                continue
            seen_docs.add(doc_title)
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
