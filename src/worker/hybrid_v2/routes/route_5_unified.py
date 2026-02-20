"""Route 5: Unified HippoRAG Search — Hierarchical Seed PPR.

Merges Route 3 (Global MAP-REDUCE) and Route 4 (DRIFT multi-hop) into a
single PPR-driven retrieval pass with configurable three-tier seed weighting.

Architecture (from ARCHITECTURE_ROUTE5_UNIFIED_HIPPORAG_2026-02-16):

  Query
    ├── Tier 1: NER entity seeds (w₁)
    ├── Tier 2: Structural seeds — derived bottom-up from sentence search (w₂)
    └── Tier 3: Thematic seeds — community → entity resolution (w₃)
          │
          ▼
    Unified PPR (weighted teleportation vector, dynamic damping)
          │
    ┌─────┴──────┐
    │     +      │
    │  Sentence  │  (parallel, seed-independent)
    │  vector    │
    │  search    │
    └─────┬──────┘
          ▼
      Synthesis
          │
      RouteResult

Key improvements over Routes 3/4 separately:
  • 2 LLM calls (1 NER + 1 synthesis) instead of 12-15
  • Multi-tier seeds → PPR is "sighted", not blind
  • Dynamic damping adjusts exploration breadth per query type
  • Released PPR constraints (per_seed_limit 50, per_neighbor_limit 20)
    with adaptive memory guard to stay within AuraDB tx-memory budget
  • No decomposition hallucination (38% rate eliminated)
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .base import BaseRouteHandler, Citation, RouteResult

logger = structlog.get_logger(__name__)


# Voyage embedding service — shared singleton (same pattern as Routes 3/4)
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
                logger.info("route5_voyage_service_initialized")
            else:
                logger.warning("route5_voyage_service_no_api_key")
        except Exception as e:
            logger.warning("route5_voyage_service_init_failed", error=str(e))
    return _voyage_service


class UnifiedSearchHandler(BaseRouteHandler):
    """Route 5: Unified Hierarchical Seed PPR search.

    Replaces both Route 3 (global MAP-REDUCE) and Route 4 (DRIFT multi-hop)
    with a single PPR pass using three-tier weighted seeds.  The weight
    profile (selected by the router) controls whether the search behaves
    globally, locally, or somewhere in between.
    """

    ROUTE_NAME = "route_5_unified"

    async def execute(
        self,
        query: str,
        response_type: str = "summary",
        knn_config: Optional[str] = None,
        prompt_variant: Optional[str] = None,
        synthesis_model: Optional[str] = None,
        include_context: bool = False,
        weight_profile: Optional[str] = None,
    ) -> RouteResult:
        """Execute Route 5: Unified Hierarchical Seed PPR.

        Pipeline:
          0. Select weight profile
          1. Parallel: NER + Sentence search + Community match
          2. Derive structural seeds (bottom-up from sentence hits)
          3. Resolve all tiers → weighted PPR teleportation vector
          4. Unified PPR traversal (weighted, dynamic damping)
          5. Denoise + Rerank sentence evidence
          6. Merge PPR chunks + sentence evidence
          7. Synthesis (single LLM call)

        Args:
            weight_profile: Optional weight profile name (e.g.
                ``"fact_extraction"``, ``"thematic_survey"``).  When
                provided by the router/orchestrator this takes precedence
                over the ``ROUTE5_WEIGHT_PROFILE`` env var.
        """
        enable_timings = os.getenv(
            "ROUTE5_RETURN_TIMINGS", "0"
        ).strip().lower() in {"1", "true", "yes"}
        timings_ms: Dict[str, int] = {}
        t_route_start = time.perf_counter()

        sentence_top_k = int(os.getenv("ROUTE5_SENTENCE_TOP_K", "30"))
        ppr_top_k = int(os.getenv("ROUTE5_PPR_TOP_K", "30"))
        per_seed_limit = int(os.getenv("ROUTE5_PPR_PER_SEED_LIMIT", "50"))
        per_neighbor_limit = int(os.getenv("ROUTE5_PPR_PER_NEIGHBOR_LIMIT", "20"))
        rerank_enabled = os.getenv(
            "ROUTE5_SENTENCE_RERANK", "1"
        ).strip().lower() in {"1", "true", "yes"}
        rerank_top_k = int(os.getenv("ROUTE5_RERANK_TOP_K", "15"))

        # ------------------------------------------------------------------
        # Step 0: Select seed mode + weight profile
        # ------------------------------------------------------------------
        seed_mode = os.getenv("ROUTE5_SEED_MODE", "weighted").strip().lower()

        if seed_mode == "flat":
            from ..pipeline.seed_resolver import resolve_flat_seed_pool

            profile_label = "flat"
            logger.info(
                "route_5_unified_start",
                query=query[:80],
                response_type=response_type,
                seed_mode="flat",
                sentence_top_k=sentence_top_k,
                ppr_top_k=ppr_top_k,
            )
        else:
            from ..pipeline.seed_resolver import (
                DEFAULT_PROFILE,
                WEIGHT_PROFILES,
                WeightProfile,
                resolve_all_tiers,
            )

            # Priority: explicit parameter > env var > balanced default
            profile_name = weight_profile or os.getenv("ROUTE5_WEIGHT_PROFILE", "balanced")
            profile = WEIGHT_PROFILES.get(profile_name, DEFAULT_PROFILE)
            profile_label = profile.label

            logger.info(
                "route_5_unified_start",
                query=query[:80],
                response_type=response_type,
                seed_mode="weighted",
                profile=profile.label,
                weights=f"w1={profile.w1} w2={profile.w2} w3={profile.w3}",
                sentence_top_k=sentence_top_k,
                ppr_top_k=ppr_top_k,
            )

        # ------------------------------------------------------------------
        # Step 1: Parallel — NER + Sentence search + Community match
        # ------------------------------------------------------------------
        t0 = time.perf_counter()

        # 1a. NER on original query (Tier 1 seed names)
        ner_task = asyncio.create_task(
            self.pipeline.disambiguator.disambiguate(query)
        )

        # 1b. Sentence vector search (independent of everything else)
        sentence_task = asyncio.create_task(
            self._retrieve_sentence_evidence(query, top_k=sentence_top_k)
        )

        # Await NER + sentence search (community match is inside resolve_all_tiers)
        entity_seed_names, sentence_evidence = await asyncio.gather(
            ner_task, sentence_task
        )

        # Handle exceptions from tasks
        if isinstance(entity_seed_names, BaseException):
            logger.warning("route5_ner_failed", error=str(entity_seed_names))
            entity_seed_names = []
        if isinstance(sentence_evidence, BaseException):
            logger.warning("route5_sentence_search_failed", error=str(sentence_evidence))
            sentence_evidence = []

        timings_ms["step_1_parallel_ms"] = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "step_1_parallel_complete",
            ner_entities=entity_seed_names[:10] if entity_seed_names else [],
            sentence_hits=len(sentence_evidence),
        )

        # ------------------------------------------------------------------
        # Step 2: Denoise sentence evidence (before deriving structural seeds)
        # ------------------------------------------------------------------
        if sentence_evidence:
            t0 = time.perf_counter()
            raw_count = len(sentence_evidence)
            sentence_evidence = self._denoise_sentences(sentence_evidence)

            if rerank_enabled and sentence_evidence:
                try:
                    sentence_evidence = await self._rerank_sentences(
                        query, sentence_evidence, top_k=rerank_top_k
                    )
                except Exception as e:
                    logger.warning("route5_rerank_failed", error=str(e))

            timings_ms["step_2_denoise_rerank_ms"] = int(
                (time.perf_counter() - t0) * 1000
            )
            logger.info(
                "step_2_denoise_rerank_complete",
                raw=raw_count,
                after_denoise_rerank=len(sentence_evidence),
            )

        # ------------------------------------------------------------------
        # Step 3: Resolve seeds (mode-dependent)
        # ------------------------------------------------------------------
        t0 = time.perf_counter()

        if not self._async_neo4j:
            logger.error("route5_no_async_neo4j")
            return self._empty_result("AsyncNeo4jService required for Route 5")

        # Variables populated by whichever branch runs
        community_data: List[Dict[str, Any]] = []
        structural_sections: List[str] = []

        if seed_mode == "flat":
            # Flat pool: NER + 3 addon seeds → deduped flat list
            pool_result = await resolve_flat_seed_pool(
                query=query,
                sentence_evidence=sentence_evidence,
                async_neo4j=self._async_neo4j,
                community_matcher=self.pipeline.community_matcher,
                group_id=self.group_id,
                entity_seed_names=entity_seed_names,
                folder_id=self.folder_id,
                embed_model=self.pipeline.tracer.embed_model if hasattr(self.pipeline, 'tracer') else None,
                llm_client=getattr(self.pipeline.disambiguator, 'llm', None) if hasattr(self.pipeline, 'disambiguator') else None,
            )

            flat_seed_ids = pool_result["seed_ids"]
            community_data = pool_result["community_data"]
            structural_sections = pool_result["structural_sections"]
            pool_metadata = pool_result["pool_metadata"]

            timings_ms["step_3_seed_resolution_ms"] = int(
                (time.perf_counter() - t0) * 1000
            )

            logger.info(
                "step_3_flat_pool_complete",
                pool_total=len(flat_seed_ids),
                ner=len(pool_result["ner_ids"]),
                community_addon=len(pool_result["community_addon_ids"]),
                structural_addon=len(pool_result["structural_addon_ids"]),
                semantic_addon=len(pool_result["semantic_addon_ids"]),
                structural_sections=structural_sections[:5],
            )

        else:
            # Weighted tiers: T1/T2/T3 → weighted teleportation vector
            resolver_result = await resolve_all_tiers(
                query=query,
                sentence_evidence=sentence_evidence,
                async_neo4j=self._async_neo4j,
                community_matcher=self.pipeline.community_matcher,
                group_id=self.group_id,
                entity_seed_names=entity_seed_names,
                profile=profile,
                folder_id=self.folder_id,
                embed_model=self.pipeline.tracer.embed_model if hasattr(self.pipeline, 'tracer') else None,
                llm_client=getattr(self.pipeline.disambiguator, 'llm', None) if hasattr(self.pipeline, 'disambiguator') else None,
            )

            weighted_seeds = resolver_result["weighted_seeds"]
            damping = resolver_result["damping"]
            community_data = resolver_result["community_data"]
            structural_sections = resolver_result["structural_sections"]

            timings_ms["step_3_seed_resolution_ms"] = int(
                (time.perf_counter() - t0) * 1000
            )

            logger.info(
                "step_3_seed_resolution_complete",
                total_seeds=len(weighted_seeds),
                tier1=len(resolver_result["tier1_ids"]),
                tier2=len(resolver_result["tier2_ids"]),
                tier3=len(resolver_result["tier3_ids"]),
                damping=damping,
                structural_sections=structural_sections[:5],
            )

        # ------------------------------------------------------------------
        # Step 4: PPR traversal (mode-dependent)
        # ------------------------------------------------------------------
        t0 = time.perf_counter()
        ppr_evidence: List[Tuple[str, float]] = []

        if seed_mode == "flat":
            # Flat pool: equal weight, fixed damping 0.85
            if flat_seed_ids:
                # Cap seeds if pool is too large
                max_flat_seeds = int(os.getenv("ROUTE5_MAX_FLAT_SEEDS", "30"))
                if len(flat_seed_ids) > max_flat_seeds:
                    # Priority order: NER > semantic > structural > community
                    priority_ids: List[str] = []
                    seen: set = set()
                    for source in [
                        pool_result["ner_ids"],
                        pool_result["semantic_addon_ids"],
                        pool_result["structural_addon_ids"],
                        pool_result["community_addon_ids"],
                    ]:
                        for eid in source:
                            if eid not in seen:
                                priority_ids.append(eid)
                                seen.add(eid)
                    flat_seed_ids = priority_ids[:max_flat_seeds]
                    logger.info(
                        "flat_seeds_capped",
                        original=pool_metadata["pool_total"],
                        kept=len(flat_seed_ids),
                    )

                # Adaptive limits based on seed count
                n_seeds = len(flat_seed_ids)
                eff_per_seed = min(per_seed_limit, max(10, 500 // max(n_seeds, 1)))
                eff_per_neighbor = min(per_neighbor_limit, max(5, 200 // max(n_seeds, 1)))

                try:
                    ppr_evidence = await self._async_neo4j.personalized_pagerank_native(
                        group_id=self.group_id,
                        seed_entity_ids=flat_seed_ids,
                        damping=0.85,
                        top_k=ppr_top_k,
                        per_seed_limit=eff_per_seed,
                        per_neighbor_limit=eff_per_neighbor,
                    )
                except Exception as e:
                    logger.warning("route5_flat_ppr_failed", error=str(e))
        else:
            # Weighted PPR (existing logic)
            if weighted_seeds:
                try:
                    ppr_evidence = await self._async_neo4j.personalized_pagerank_weighted(
                        group_id=self.group_id,
                        weighted_seeds=weighted_seeds,
                        damping=damping,
                        top_k=ppr_top_k,
                        per_seed_limit=per_seed_limit,
                        per_neighbor_limit=per_neighbor_limit,
                    )
                except Exception as e:
                    logger.warning("route5_ppr_failed", error=str(e))
                    # Fall back to flat PPR with seed IDs
                    try:
                        ppr_evidence = await self.pipeline.tracer.trace(
                            query=query,
                            seed_entities=entity_seed_names,
                            top_k=ppr_top_k,
                        )
                    except Exception as e2:
                        logger.error("route5_ppr_fallback_failed", error=str(e2))

        timings_ms["step_4_ppr_ms"] = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "step_4_ppr_complete",
            evidence_count=len(ppr_evidence),
            top_entities=[
                (name, round(score, 4))
                for name, score in ppr_evidence[:5]
            ],
        )

        # ------------------------------------------------------------------
        # Negative detection: both PPR and sentence search returned nothing
        # ------------------------------------------------------------------
        if not ppr_evidence and not sentence_evidence:
            logger.info("route_5_negative_no_evidence")
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "negative_detection": True,
                    "detection_reason": "no_ppr_evidence_and_no_sentences",
                    "ner_entities": entity_seed_names,
                    "profile": profile_label,
                },
            )

        # ------------------------------------------------------------------
        # Step 5: Merge PPR evidence + sentence evidence → synthesis
        # ------------------------------------------------------------------
        t0 = time.perf_counter()

        # Convert sentence evidence to coverage_chunks format for synthesizer
        sentence_chunks: List[Dict[str, Any]] = []
        for ev in sentence_evidence:
            sentence_chunks.append(
                {
                    "text": ev.get("text", ""),
                    "document_title": ev.get("document_title", "Unknown"),
                    "document_id": ev.get("document_id", ""),
                    "section_path": ev.get("section_path", ""),
                    "page_number": ev.get("page"),
                    "_entity_score": ev.get(
                        "rerank_score", ev.get("score", 0.5)
                    ),
                    "_source_entity": "__sentence_search__",
                }
            )

        # Build community summary context (optional — replaces MAP step)
        community_context: Optional[str] = None
        if community_data:
            community_summaries = []
            for c in community_data[:5]:
                title = c.get("title", "Unknown Community")
                summary = c.get("summary", c.get("full_content", ""))
                if summary:
                    community_summaries.append(
                        f"[Community: {title}] {summary[:500]}"
                    )
            if community_summaries:
                community_context = "\n\n".join(community_summaries)

        # Synthesize with both PPR evidence and sentence chunks
        synthesis_result = await self.pipeline.synthesizer.synthesize(
            query=query,
            evidence_nodes=ppr_evidence,
            response_type=response_type,
            coverage_chunks=sentence_chunks if sentence_chunks else None,
            prompt_variant=prompt_variant,
            synthesis_model=synthesis_model,
            include_context=include_context,
            ner_seed_count=len(entity_seed_names),
        )

        timings_ms["step_5_synthesis_ms"] = int(
            (time.perf_counter() - t0) * 1000
        )
        timings_ms["total_ms"] = int(
            (time.perf_counter() - t_route_start) * 1000
        )

        logger.info(
            "step_5_synthesis_complete",
            response_length=len(synthesis_result.get("response", "")),
            text_chunks_used=synthesis_result.get("text_chunks_used", 0),
            total_ms=timings_ms["total_ms"],
        )

        # ------------------------------------------------------------------
        # Step 6: Build citations
        # ------------------------------------------------------------------
        citations: List[Citation] = []
        for i, c in enumerate(synthesis_result.get("citations", []), 1):
            if isinstance(c, dict):
                meta = c.get("metadata") or {}
                section_path = (
                    meta.get("section_path")
                    or meta.get("section_path_key")
                    or c.get("section_path", "")
                )
                if isinstance(section_path, list):
                    section_path = " > ".join(
                        str(s) for s in section_path if s
                    )
                citations.append(
                    Citation(
                        index=i,
                        chunk_id=c.get("chunk_id", f"chunk_{i}"),
                        document_id=c.get("document_id", ""),
                        document_title=c.get(
                            "document_title", c.get("document", "Unknown")
                        ),
                        document_url=c.get("document_url", "")
                        or c.get("document_source", "")
                        or meta.get("url", ""),
                        page_number=c.get("page_number")
                        or meta.get("page_number"),
                        section_path=section_path,
                        start_offset=c.get("start_offset")
                        or meta.get("start_offset"),
                        end_offset=c.get("end_offset")
                        or meta.get("end_offset"),
                        score=c.get("score", 0.0),
                        text_preview=c.get(
                            "text_preview", c.get("text", "")
                        )[:200],
                        sentences=c.get("sentences"),
                        page_dimensions=c.get("page_dimensions"),
                    )
                )

        # ------------------------------------------------------------------
        # Assemble metadata
        # ------------------------------------------------------------------
        if seed_mode == "flat":
            metadata: Dict[str, Any] = {
                "seed_mode": "flat",
                "ner_entities": entity_seed_names,
                "ner_seed_count": len(pool_result["ner_ids"]),
                "community_addon_count": len(pool_result["community_addon_ids"]),
                "structural_addon_count": len(pool_result["structural_addon_ids"]),
                "semantic_addon_count": len(pool_result["semantic_addon_ids"]),
                "pool_total_seeds": len(flat_seed_ids),
                "pool_metadata": pool_metadata,
                "damping": 0.85,
                "structural_sections": structural_sections,
                "num_ppr_evidence": len(ppr_evidence),
                "sentence_evidence_count": len(sentence_evidence),
                "text_chunks_used": synthesis_result.get("text_chunks_used", 0),
                "route_description": "Unified flat-pool PPR (v5-flat)",
                "version": "v5.1-flat",
            }
        else:
            metadata: Dict[str, Any] = {
                "seed_mode": "weighted",
                "profile": profile.label,
                "weights": {
                    "w1_entity": profile.w1,
                    "w2_structural": profile.w2,
                    "w3_thematic": profile.w3,
                },
                "damping": damping,
                "ner_entities": entity_seed_names,
                "tier1_seed_count": len(resolver_result["tier1_ids"]),
                "tier2_seed_count": len(resolver_result["tier2_ids"]),
                "tier3_seed_count": len(resolver_result["tier3_ids"]),
                "total_unique_seeds": len(weighted_seeds),
                "tier_contribution": resolver_result.get("tier_contribution", {}),
                "structural_sections": structural_sections,
                "num_ppr_evidence": len(ppr_evidence),
                "sentence_evidence_count": len(sentence_evidence),
                "text_chunks_used": synthesis_result.get("text_chunks_used", 0),
                "route_description": "Unified hierarchical seed PPR (v5)",
                "version": "v5.0",
            }

        if community_data:
            metadata["matched_communities"] = [
                c.get("title", "?") for c in community_data[:5]
            ]

        if include_context:
            metadata["ppr_top_entities"] = [
                {"entity": name, "score": round(score, 4)}
                for name, score in ppr_evidence[:10]
            ]
            metadata["sentence_evidence"] = [
                {
                    "text": s.get("text", "")[:200],
                    "source": s.get("document_title", ""),
                    "score": round(s.get("score", 0), 4),
                }
                for s in sentence_evidence[:10]
            ]
            if synthesis_result.get("context_stats"):
                metadata["context_stats"] = synthesis_result["context_stats"]
            if synthesis_result.get("llm_context"):
                metadata["llm_context"] = synthesis_result["llm_context"]

        if synthesis_result.get("raw_extractions"):
            metadata["raw_extractions"] = synthesis_result["raw_extractions"]
        if synthesis_result.get("processing_mode"):
            metadata["processing_mode"] = synthesis_result["processing_mode"]

        if enable_timings:
            metadata["timings_ms"] = timings_ms

        return RouteResult(
            response=synthesis_result.get("response", ""),
            route_used=self.ROUTE_NAME,
            citations=citations,
            evidence_path=[
                name for name, _ in ppr_evidence[:20]
            ],
            metadata=metadata,
            usage=synthesis_result.get("usage"),
            timing=(
                {"total_ms": timings_ms.get("total_ms", 0)}
                if enable_timings
                else None
            ),
        )

    # ==================================================================
    # Helper: Empty result
    # ==================================================================

    def _empty_result(self, reason: str) -> RouteResult:
        """Return a negative-detection RouteResult."""
        return RouteResult(
            response="The requested information was not found in the available documents.",
            route_used=self.ROUTE_NAME,
            citations=[],
            evidence_path=[],
            metadata={
                "negative_detection": True,
                "detection_reason": reason,
            },
        )

    # ==================================================================
    # Sentence Vector Search (shared pattern from Routes 3/4)
    # ==================================================================

    async def _retrieve_sentence_evidence(
        self,
        query: str,
        top_k: int = 30,
    ) -> List[Dict[str, Any]]:
        """Retrieve sentence-level evidence via Voyage vector search.

        Uses the same ``sentence_embeddings_v2`` Neo4j vector index as
        Routes 3 and 4 — provides a direct query→source evidence path
        that bypasses entity resolution and graph traversal.
        """
        voyage_service = _get_voyage_service()
        if not voyage_service:
            logger.warning("route5_sentence_search_no_voyage_service")
            return []

        if not self.neo4j_driver:
            logger.warning("route5_sentence_search_no_neo4j_driver")
            return []

        try:
            query_embedding = voyage_service.embed_query(query)
        except Exception as e:
            logger.warning("route5_sentence_embed_failed", error=str(e))
            return []

        threshold = float(os.getenv("ROUTE5_SENTENCE_THRESHOLD", "0.2"))
        group_id = self.group_id

        cypher = """CYPHER 25
        CALL () {
            MATCH (sent:Sentence)
            SEARCH sent IN (VECTOR INDEX sentence_embeddings_v2 FOR $embedding WHERE sent.group_id = $group_id LIMIT $top_k)
            SCORE AS score
            WHERE score >= $threshold
            RETURN sent, score
        }

        OPTIONAL MATCH (sent)-[:PART_OF]->(chunk:TextChunk)
        OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
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
            logger.warning("route5_sentence_search_failed", error=str(e))
            return []

        if not results:
            logger.info("route5_sentence_search_empty", query=query[:50])
            return []

        # Deduplicate and build context passages
        seen: set = set()
        evidence: List[Dict[str, Any]] = []

        for r in results:
            sid = r.get("sentence_id", "")
            if sid in seen:
                continue
            seen.add(sid)

            parts = []
            if r.get("prev_text"):
                parts.append(r["prev_text"].strip())
            parts.append(r.get("text", "").strip())
            if r.get("next_text"):
                parts.append(r["next_text"].strip())
            passage = " ".join(parts)

            evidence.append(
                {
                    "text": passage,
                    "sentence_text": r.get("text", ""),
                    "score": r.get("score", 0),
                    "document_title": r.get("document_title", "Unknown"),
                    "document_id": r.get("document_id", ""),
                    "section_path": r.get("section_path", ""),
                    "page": r.get("page"),
                    "sentence_id": sid,
                }
            )

        logger.info(
            "route5_sentence_search_complete",
            query=query[:50],
            raw=len(results),
            deduped=len(evidence),
            top_scores=[round(e["score"], 4) for e in evidence[:5]],
        )
        return evidence

    # ==================================================================
    # Denoise + Rerank (same logic as Routes 3/4)
    # ==================================================================

    @staticmethod
    def _denoise_sentences(
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove noisy, non-informative sentences before reranking.

        Structured source sentences (signature_party, table_row, figure_caption)
        are curated by the ingestion pipeline and bypass all content-heuristic
        filters.  Only residual HTML is stripped from them.
        """
        cleaned: List[Dict[str, Any]] = []

        # Sources that carry structured content — skip content heuristics.
        _STRUCTURED_SOURCES = {"signature_party", "table_row", "figure_caption"}

        for ev in evidence:
            text = (ev.get("sentence_text") or ev.get("text", "")).strip()
            passage = ev.get("text", "").strip()

            # Structured-source sentences: skip all content heuristics.
            if ev.get("source") in _STRUCTURED_SOURCES:
                if "<" in passage:
                    passage = re.sub(r"<[^>]+>", "", passage).strip()
                    ev = {**ev, "text": passage}
                cleaned.append(ev)
                continue

            # HTML / markup-heavy
            if len(re.findall(r"<[^>]+>", text)) >= 2:
                continue

            # Too short
            if len(text) < 25:
                continue

            # Signature / form boilerplate
            if re.search(
                r"(?i)(signature|signed this|print\)|registration number"
                r"|authorized representative)",
                text,
            ):
                continue

            # Bare label ending with colon
            if len(text) < 60 and text.endswith(":"):
                continue

            # Heading-only (no sentence punctuation)
            if len(text) < 50 and not re.search(r"[.?!]", text):
                continue

            # Strip residual HTML
            if "<" in passage:
                passage = re.sub(r"<[^>]+>", "", passage).strip()
                ev = {**ev, "text": passage}

            cleaned.append(ev)

        logger.info(
            "route5_denoise_sentences",
            before=len(evidence),
            after=len(cleaned),
        )
        return cleaned

    async def _rerank_sentences(
        self,
        query: str,
        evidence: List[Dict[str, Any]],
        top_k: int = 15,
    ) -> List[Dict[str, Any]]:
        """Rerank denoised sentences using voyage-rerank-2.5."""
        rerank_model = os.getenv("ROUTE5_RERANK_MODEL", "rerank-2.5")

        try:
            import voyageai
            from src.core.config import settings

            vc = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
            documents = [
                ev.get("sentence_text") or ev.get("text", "")
                for ev in evidence
            ]

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
                ev = {**evidence[rr.index], "rerank_score": rr.relevance_score}
                reranked.append(ev)

            logger.info(
                "route5_rerank_complete",
                model=rerank_model,
                input=len(evidence),
                output=len(reranked),
                top_score=round(reranked[0]["rerank_score"], 4)
                if reranked
                else 0,
            )
            return reranked

        except Exception:
            logger.exception("route5_rerank_failed")
            raise
