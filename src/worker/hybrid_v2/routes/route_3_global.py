"""Route 3 v2: Global Search — LazyGraphRAG Map-Reduce.

Best for thematic/cross-document queries:
- "What are the main compliance risks?"
- "Summarize key themes across documents"
- "Compare termination clauses across agreements"

Architecture (3 steps, replacing the previous 7-stage pipeline):
  1. Community Match  — reuse existing CommunityMatcher (top_k=3)
  2. MAP              — parallel LLM calls: extract claims per community
  3. REDUCE           — single LLM call: synthesize claims into response

Key design decisions:
- No MENTIONS chunk fetch (communities already encode graph structure)
- No BM25/RRF (eliminated 56.5% duplicate retrieval)
- No PPR (was dead code in v1)
- No coverage gap fill (MAP covers all matched communities)
- Token budget: ~4K tokens into REDUCE vs ~80K in v1
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .base import BaseRouteHandler, Citation, RouteResult
from .route_3_prompts import MAP_PROMPT, REDUCE_PROMPT

logger = structlog.get_logger(__name__)


class GlobalSearchHandler(BaseRouteHandler):
    """Route 3 v2: LazyGraphRAG Map-Reduce for thematic queries."""

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
        """Execute Route 3 v2: Map-Reduce global search.

        Steps:
          1. Community matching (unchanged from v1)
          2. MAP — parallel LLM calls per community
          3. REDUCE — synthesize all claims

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

        logger.info(
            "route_3v2_start",
            query=query[:80],
            response_type=response_type,
            max_claims=max_claims,
            community_top_k=community_top_k,
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
        )

        # Negative detection: no communities matched
        if not community_data:
            logger.info("route_3v2_negative_no_communities")
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "negative_detection": True,
                    "detection_reason": "no_communities_matched",
                },
            )

        # ================================================================
        # Step 2: MAP — extract claims from each community (parallel)
        # ================================================================
        t0 = time.perf_counter()
        map_tasks = [
            self._map_community(query, community, max_claims)
            for community in community_data
        ]
        map_results: List[Tuple[str, List[str]]] = await asyncio.gather(*map_tasks)
        timings_ms["step_2_map_ms"] = int((time.perf_counter() - t0) * 1000)

        # Flatten claims with community attribution
        all_claims: List[str] = []
        community_claim_counts: Dict[str, int] = {}
        for community, (title, claims) in zip(community_data, map_results):
            community_claim_counts[title] = len(claims)
            for claim in claims:
                all_claims.append(f"[Community: {title}] {claim}")

        logger.info(
            "step_2_complete",
            total_claims=len(all_claims),
            per_community=community_claim_counts,
        )

        # Negative detection: MAP extracted zero claims
        if not all_claims:
            logger.info("route_3v2_negative_no_claims")
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "negative_detection": True,
                    "detection_reason": "map_no_claims",
                    "matched_communities": [
                        c.get("title", "?") for c in community_data
                    ],
                },
            )

        # ================================================================
        # Step 3: REDUCE — synthesize all claims into response
        # ================================================================
        t0 = time.perf_counter()
        response_text = await self._reduce_claims(
            query, response_type, all_claims,
        )
        timings_ms["step_3_reduce_ms"] = int((time.perf_counter() - t0) * 1000)
        timings_ms["total_ms"] = int((time.perf_counter() - t_route_start) * 1000)

        logger.info(
            "step_3_complete",
            response_length=len(response_text),
            total_ms=timings_ms["total_ms"],
        )

        # ================================================================
        # Build citations (community-level, not chunk-level)
        # ================================================================
        citations = self._build_community_citations(
            community_data, community_scores, community_claim_counts,
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
            "claims_per_community": community_claim_counts,
            "route_description": "LazyGraphRAG map-reduce (v2)",
            "version": "v2",
        }

        if include_context:
            metadata["map_claims"] = all_claims

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
    # REDUCE: synthesize claims into final response
    # ==================================================================

    async def _reduce_claims(
        self,
        query: str,
        response_type: str,
        all_claims: List[str],
    ) -> str:
        """Synthesize all MAP claims into the final response.

        Args:
            query: User query.
            response_type: Desired response format.
            all_claims: List of attributed claim strings.

        Returns:
            Synthesized response text.
        """
        claims_text = "\n".join(
            f"{i}. {claim}" for i, claim in enumerate(all_claims, 1)
        )

        prompt = REDUCE_PROMPT.format(
            query=query,
            response_type=response_type,
            all_claims=claims_text,
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

    @staticmethod
    def _build_community_citations(
        communities: List[Dict[str, Any]],
        scores: List[float],
        claim_counts: Dict[str, int],
    ) -> List[Citation]:
        """Build community-level citations.

        Since map-reduce works from community summaries (not raw chunks),
        citations reference communities rather than chunks.
        """
        citations: List[Citation] = []
        for i, (community, score) in enumerate(zip(communities, scores), 1):
            title = community.get("title", "Untitled")
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
        return citations
