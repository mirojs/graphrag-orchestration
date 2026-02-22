"""Route 7: True HippoRAG 2 with Passage-Node PPR.

Implements the real HippoRAG 2 architecture (ICML '25) as a new route
alongside the existing Route 5.  Two key upstream innovations:

1. **Passage nodes in PPR graph** — PPR walks Entity<->Passage (TextChunk),
   so passage scores come directly from the random walk rather than a
   post-PPR lookup.

2. **Query-to-triple linking** — At query time the full query is embedded
   and matched against triple embeddings (not NER-to-node).  An LLM then
   filters the top-K triples ("recognition memory") before seeding PPR.

Phase 2 custom additions (gated by env vars):
  - ROUTE7_STRUCTURAL_SEEDS: Tier 2 structural seeds (section matching)
  - ROUTE7_COMMUNITY_SEEDS:  Tier 3 community seeds
  - ROUTE7_SENTENCE_SEARCH:  Parallel sentence vector search
  - ROUTE7_SECTION_GRAPH:    Include Section nodes in PPR graph

Reference: https://arxiv.org/abs/2502.14802
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .base import BaseRouteHandler, Citation, RouteResult
from ..services.neo4j_retry import retry_session

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Voyage embedding service — shared singleton (same pattern as Route 5)
# ---------------------------------------------------------------------------
_voyage_service = None
_voyage_init_attempted = False


def _get_voyage_service():
    """Get Voyage embedding service for query + triple embedding."""
    global _voyage_service, _voyage_init_attempted
    if not _voyage_init_attempted:
        _voyage_init_attempted = True
        try:
            from src.core.config import settings

            if settings.VOYAGE_API_KEY:
                from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService

                _voyage_service = VoyageEmbedService()
                logger.info("route7_voyage_service_initialized")
            else:
                logger.warning("route7_voyage_service_no_api_key")
        except Exception as e:
            logger.warning("route7_voyage_service_init_failed", error=str(e))
    return _voyage_service


class HippoRAG2Handler(BaseRouteHandler):
    """Route 7: True HippoRAG 2 with passage-node PPR.

    Pipeline:
      1. Embed query (Voyage)
      2. asyncio.gather(
           - Query-to-triple linking (top 5) -> LLM recognition memory -> entity seeds
           - DPR passage search (chunk_embeddings_v2 vector index) -> passage seeds
           - [Phase 2] Sentence vector search (optional)
         )
      3. [Phase 2] Structural seeds & community seeds (optional)
      4. Build seed vectors -> True PPR (in-memory, damping=0.5, undirected)
      5. Top-K passage scores -> fetch chunk texts -> synthesis
      6. Build RouteResult with citations & metadata
    """

    ROUTE_NAME = "route_7_hipporag2"

    def __init__(self, pipeline: Any) -> None:
        super().__init__(pipeline)
        self._triple_store = None
        self._ppr_engine = None
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        """Lazy-load triple embeddings and PPR graph on first query."""
        if self._triple_store is not None and self._ppr_engine is not None:
            return

        async with self._init_lock:
            # Double-check after acquiring lock
            if self._triple_store is not None and self._ppr_engine is not None:
                return

            from ..retrievers.triple_store import TripleEmbeddingStore
            from ..retrievers.hipporag2_ppr import HippoRAG2PPR

            voyage_service = _get_voyage_service()
            if not voyage_service:
                raise RuntimeError("Voyage API key required for Route 7")

            include_section_graph = os.getenv(
                "ROUTE7_SECTION_GRAPH", "0"
            ).strip().lower() in {"1", "true", "yes"}

            passage_node_weight = float(
                os.getenv("ROUTE7_PASSAGE_NODE_WEIGHT", "0.05")
            )
            synonym_threshold = float(
                os.getenv("ROUTE7_SYNONYM_THRESHOLD", "0.8")
            )

            # Load triple store and PPR graph in parallel
            triple_store = TripleEmbeddingStore()
            ppr_engine = HippoRAG2PPR()

            await asyncio.gather(
                triple_store.load(
                    self.neo4j_driver, self.group_id, voyage_service
                ),
                ppr_engine.load_graph(
                    self.neo4j_driver,
                    self.group_id,
                    passage_node_weight=passage_node_weight,
                    synonym_threshold=synonym_threshold,
                    include_section_graph=include_section_graph,
                ),
            )

            self._triple_store = triple_store
            self._ppr_engine = ppr_engine

            logger.info(
                "route7_initialized",
                triple_count=triple_store.triple_count,
                graph_nodes=ppr_engine.node_count,
            )

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
        """Execute Route 7: True HippoRAG 2 retrieval pipeline."""
        enable_timings = os.getenv(
            "ROUTE7_RETURN_TIMINGS", "0"
        ).strip().lower() in {"1", "true", "yes"}
        timings_ms: Dict[str, int] = {}
        t_route_start = time.perf_counter()

        # Config from env
        triple_top_k = int(os.getenv("ROUTE7_TRIPLE_TOP_K", "5"))
        dpr_top_k = int(os.getenv("ROUTE7_DPR_TOP_K", "20"))
        ppr_damping = float(os.getenv("ROUTE7_DAMPING", "0.5"))
        passage_node_weight = float(os.getenv("ROUTE7_PASSAGE_NODE_WEIGHT", "0.05"))
        ppr_passage_top_k = int(os.getenv("ROUTE7_PPR_PASSAGE_TOP_K", "20"))

        # Phase 2 feature flags
        structural_seeds_enabled = os.getenv(
            "ROUTE7_STRUCTURAL_SEEDS", "0"
        ).strip().lower() in {"1", "true", "yes"}
        community_seeds_enabled = os.getenv(
            "ROUTE7_COMMUNITY_SEEDS", "0"
        ).strip().lower() in {"1", "true", "yes"}
        sentence_search_enabled = os.getenv(
            "ROUTE7_SENTENCE_SEARCH", "0"
        ).strip().lower() in {"1", "true", "yes"}

        logger.info(
            "route_7_hipporag2_start",
            query=query[:80],
            response_type=response_type,
            damping=ppr_damping,
            triple_top_k=triple_top_k,
            dpr_top_k=dpr_top_k,
        )

        # ------------------------------------------------------------------
        # Step 0: Initialize (lazy load triple store + PPR graph)
        # ------------------------------------------------------------------
        await self._ensure_initialized()

        # ------------------------------------------------------------------
        # Step 1: Embed query
        # ------------------------------------------------------------------
        t0 = time.perf_counter()
        voyage_service = _get_voyage_service()
        query_embedding = voyage_service.embed_query(query)
        timings_ms["step_1_embed_ms"] = int((time.perf_counter() - t0) * 1000)

        # ------------------------------------------------------------------
        # Step 2: Parallel — Triple linking + DPR + optional sentence search
        # ------------------------------------------------------------------
        t0 = time.perf_counter()

        # 2a. Query-to-triple linking + recognition memory filter
        triple_task = asyncio.create_task(
            self._query_to_triple_linking(query, query_embedding, triple_top_k)
        )

        # 2b. DPR passage search
        dpr_task = asyncio.create_task(
            self._dpr_passage_search(query_embedding, dpr_top_k)
        )

        # 2c. Optional sentence search (Phase 2)
        sentence_task = None
        if sentence_search_enabled:
            sentence_top_k = int(os.getenv("ROUTE7_SENTENCE_TOP_K", "30"))
            sentence_task = asyncio.create_task(
                self._retrieve_sentence_evidence(query, top_k=sentence_top_k)
            )

        # Await parallel tasks
        tasks = [triple_task, dpr_task]
        if sentence_task:
            tasks.append(sentence_task)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Unpack results
        surviving_triples = results[0] if not isinstance(results[0], BaseException) else []
        dpr_results = results[1] if not isinstance(results[1], BaseException) else []
        sentence_evidence: List[Dict[str, Any]] = []
        if sentence_task and len(results) > 2:
            sentence_evidence = results[2] if not isinstance(results[2], BaseException) else []

        if isinstance(results[0], BaseException):
            logger.warning("route7_triple_linking_failed", error=str(results[0]))
        if isinstance(results[1], BaseException):
            logger.warning("route7_dpr_failed", error=str(results[1]))

        timings_ms["step_2_parallel_ms"] = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "step_2_parallel_complete",
            surviving_triples=len(surviving_triples),
            dpr_hits=len(dpr_results),
            sentence_hits=len(sentence_evidence),
        )

        # ------------------------------------------------------------------
        # Step 3: Build entity seeds from surviving triples
        # ------------------------------------------------------------------
        t0 = time.perf_counter()
        entity_seeds: Dict[str, float] = {}

        for triple in surviving_triples:
            # Accumulate weight for each entity appearing in surviving triples
            entity_seeds[triple.subject_id] = entity_seeds.get(triple.subject_id, 0) + 1.0
            entity_seeds[triple.object_id] = entity_seeds.get(triple.object_id, 0) + 1.0

        # Phase 2: Add structural seeds (Tier 2)
        structural_sections: List[str] = []
        if structural_seeds_enabled and self._async_neo4j:
            structural_entity_ids, structural_sections = await self._resolve_structural_seeds(query)
            w_structural = float(os.getenv("ROUTE7_W_STRUCTURAL", "0.2"))
            for eid in structural_entity_ids:
                entity_seeds[eid] = entity_seeds.get(eid, 0) + w_structural

        # Phase 2: Add community seeds (Tier 3)
        community_data: List[Dict[str, Any]] = []
        if community_seeds_enabled and self.pipeline.community_matcher:
            community_entity_ids, community_data = await self._resolve_community_seeds(query)
            w_community = float(os.getenv("ROUTE7_W_COMMUNITY", "0.1"))
            for eid in community_entity_ids:
                entity_seeds[eid] = entity_seeds.get(eid, 0) + w_community

        # Normalize entity seeds
        total_e = sum(entity_seeds.values())
        if total_e > 0:
            entity_seeds = {k: v / total_e for k, v in entity_seeds.items()}

        # Build passage seeds from DPR scores (Bug 2 fix: normalize before scaling)
        passage_seeds: Dict[str, float] = {}
        for chunk_id, score in dpr_results:
            passage_seeds[chunk_id] = score
        total_p = sum(passage_seeds.values())
        if total_p > 0:
            passage_seeds = {k: (v / total_p) * passage_node_weight for k, v in passage_seeds.items()}

        timings_ms["step_3_seed_build_ms"] = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "step_3_seeds_built",
            entity_seeds=len(entity_seeds),
            passage_seeds=len(passage_seeds),
        )

        # ------------------------------------------------------------------
        # Step 4: PPR or DPR-only fallback
        # ------------------------------------------------------------------
        t0 = time.perf_counter()

        if not entity_seeds and not passage_seeds:
            # No seeds at all — return negative result
            return self._empty_result("no_seeds_resolved")

        if not entity_seeds:
            # Bug 13 fix: passage seeds alone can drive PPR via MENTIONS edges
            logger.info("route7_passage_only_ppr", passage_seeds=len(passage_seeds))

        # Always run PPR (entity-only, passage-only, or combined)
        passage_scores, entity_scores = self._ppr_engine.run_ppr(
            entity_seeds=entity_seeds,
            passage_seeds=passage_seeds,
            damping=ppr_damping,
        )

        # Bug 3 fix: if PPR produced no passage scores, fall back to raw DPR order
        if not passage_scores:
            logger.info("route7_dpr_fallback", reason="ppr_no_passage_scores")
            passage_scores = list(dpr_results)
            entity_scores = []

        timings_ms["step_4_ppr_ms"] = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "step_4_ppr_complete",
            top_passages=len(passage_scores[:ppr_passage_top_k]),
            top_entities=len(entity_scores[:20]),
        )

        # ------------------------------------------------------------------
        # Step 5: Fetch chunk texts + synthesis
        # ------------------------------------------------------------------
        t0 = time.perf_counter()

        # Get top-K passage chunk IDs and fetch their text
        top_passage_scores = passage_scores[:ppr_passage_top_k]
        top_chunk_ids = [cid for cid, _ in top_passage_scores]
        ppr_scores_map = {cid: score for cid, score in top_passage_scores}
        pre_fetched_chunks = await self._fetch_chunks_by_ids(
            top_chunk_ids, ppr_scores_map=ppr_scores_map
        )

        # Convert sentence evidence to coverage_chunks format
        sentence_chunks: List[Dict[str, Any]] = []
        if sentence_evidence:
            for ev in sentence_evidence:
                sentence_chunks.append({
                    "text": ev.get("text", ""),
                    "document_title": ev.get("document_title", "Unknown"),
                    "document_id": ev.get("document_id", ""),
                    "section_path": ev.get("section_path", ""),
                    "page_number": ev.get("page"),
                    "_entity_score": ev.get("score", 0.5),
                    "_source_entity": "__sentence_search__",
                })

        # Use entity_scores as evidence_nodes for the synthesizer
        evidence_nodes = entity_scores[:20]

        # Build graph structural evidence header from surviving triples (§33.25 fix).
        # surviving_triples are LLM-confirmed by recognition memory as query-relevant.
        # Surfacing them to synthesis bridges the "triple discard" gap: the LLM gets
        # explicit contracting-party anchors so it can distinguish principals from
        # incidentally mentioned entities in raw document text.
        graph_structural_header: Optional[str] = None
        if surviving_triples:
            triple_lines = [
                f"- {t.subject_name} → {t.predicate} → {t.object_name}"
                for t in surviving_triples[:15]
            ]
            graph_structural_header = (
                "Graph Structural Evidence"
                " (named relationships confirmed relevant to this query):\n"
                + "\n".join(triple_lines)
            )

        synthesis_result = await self.pipeline.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type,
            coverage_chunks=sentence_chunks if sentence_chunks else None,
            prompt_variant=prompt_variant,
            synthesis_model=synthesis_model,
            include_context=include_context,
            pre_fetched_chunks=pre_fetched_chunks,
            graph_structural_header=graph_structural_header,
        )

        timings_ms["step_5_synthesis_ms"] = int((time.perf_counter() - t0) * 1000)
        timings_ms["total_ms"] = int((time.perf_counter() - t_route_start) * 1000)

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
                    section_path = " > ".join(str(s) for s in section_path if s)
                citations.append(
                    Citation(
                        index=i,
                        chunk_id=c.get("chunk_id", f"chunk_{i}"),
                        document_id=c.get("document_id", ""),
                        document_title=c.get("document_title", c.get("document", "Unknown")),
                        document_url=c.get("document_url", "") or c.get("document_source", "") or meta.get("url", ""),
                        page_number=c.get("page_number") or meta.get("page_number"),
                        section_path=section_path,
                        start_offset=c.get("start_offset") or meta.get("start_offset"),
                        end_offset=c.get("end_offset") or meta.get("end_offset"),
                        score=c.get("score", 0.0),
                        text_preview=c.get("text_preview", c.get("text", ""))[:200],
                        sentences=c.get("sentences"),
                        page_dimensions=c.get("page_dimensions"),
                    )
                )

        # ------------------------------------------------------------------
        # Assemble metadata
        # ------------------------------------------------------------------
        metadata: Dict[str, Any] = {
            "architecture": "hipporag2",
            "damping": ppr_damping,
            "triple_top_k": triple_top_k,
            "surviving_triples": len(surviving_triples),
            "entity_seeds_count": len(entity_seeds),
            "passage_seeds_count": len(passage_seeds),
            "passage_node_weight": passage_node_weight,
            "num_ppr_passages": len(passage_scores[:ppr_passage_top_k]),
            "num_ppr_entities": len(entity_scores[:20]),
            "text_chunks_used": synthesis_result.get("text_chunks_used", 0),
            "sentence_evidence_count": len(sentence_evidence),
            "route_description": "True HippoRAG 2 with passage-node PPR (v7)",
            "version": "v7.0",
        }

        # Phase 2 metadata
        if structural_seeds_enabled:
            metadata["structural_sections"] = structural_sections
        if community_seeds_enabled and community_data:
            metadata["matched_communities"] = [
                c.get("title", "?") for c in community_data[:5]
            ]

        # Triple details
        metadata["triple_seeds"] = [
            t.triple_text for t in surviving_triples[:10]
        ]

        if include_context:
            metadata["ppr_top_passages"] = [
                {"chunk_id": cid, "score": round(s, 6)}
                for cid, s in passage_scores[:10]
            ]
            metadata["ppr_top_entities"] = [
                {"entity": name, "score": round(s, 6)}
                for name, s in entity_scores[:10]
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
            evidence_path=[name for name, _ in entity_scores[:20]],
            metadata=metadata,
            usage=synthesis_result.get("usage"),
            timing=(
                {"total_ms": timings_ms.get("total_ms", 0)}
                if enable_timings
                else None
            ),
        )

    # ======================================================================
    # Helper: Empty result
    # ======================================================================

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

    # ======================================================================
    # Query-to-Triple Linking + Recognition Memory
    # ======================================================================

    async def _query_to_triple_linking(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int = 5,
    ) -> list:
        """Embed query, match against triple embeddings, LLM-filter survivors."""
        from ..retrievers.triple_store import recognition_memory_filter

        # Search triple embeddings
        candidates = self._triple_store.search(query_embedding, top_k=top_k)

        if not candidates:
            logger.info("route7_no_triple_candidates", query=query[:60])
            return []

        logger.debug(
            "route7_triple_candidates",
            count=len(candidates),
            top_scores=[round(s, 4) for _, s in candidates[:5]],
        )

        # LLM recognition memory filter
        llm_client = getattr(self.pipeline.disambiguator, "llm", None)
        if not llm_client:
            logger.warning("route7_no_llm_for_recognition_memory")
            return [triple for triple, _ in candidates]

        surviving = await recognition_memory_filter(llm_client, query, candidates)
        return surviving

    # ======================================================================
    # DPR Passage Search (chunk_embeddings_v2 vector index)
    # ======================================================================

    async def _dpr_passage_search(
        self,
        query_embedding: List[float],
        top_k: int = 20,
    ) -> List[Tuple[str, float]]:
        """Dense Passage Retrieval via Neo4j chunk vector index."""
        if not self.neo4j_driver:
            return []

        group_id = self.group_id

        cypher = """CYPHER 25
        CALL () {
            MATCH (c:TextChunk)
            SEARCH c IN (VECTOR INDEX chunk_embeddings_v2 FOR $embedding WHERE c.group_id = $group_id LIMIT $top_k)
            SCORE AS score
            RETURN c.id AS chunk_id, score
        }
        RETURN chunk_id, score
        ORDER BY score DESC
        """

        try:
            driver = self.neo4j_driver

            def _run():
                with retry_session(driver) as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        top_k=top_k,
                    )
                    return [(r["chunk_id"], r["score"]) for r in records]

            results = await asyncio.to_thread(_run)
            logger.debug("route7_dpr_complete", hits=len(results))
            return results
        except Exception as e:
            logger.warning("route7_dpr_failed", error=str(e))
            return []

    # ======================================================================
    # Fetch Chunk Texts by IDs
    # ======================================================================

    async def _fetch_chunks_by_ids(
        self,
        chunk_ids: List[str],
        ppr_scores_map: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch chunk text + metadata from Neo4j by chunk IDs.

        Returns flat list of chunk dicts in the format expected by the
        synthesizer's ``pre_fetched_chunks`` parameter, sorted by PPR
        score descending when ``ppr_scores_map`` is provided.
        """
        if not chunk_ids or not self.neo4j_driver:
            return []

        group_id = self.group_id

        cypher = """
        UNWIND $chunk_ids AS cid
        MATCH (c:TextChunk {id: cid, group_id: $group_id})
        OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document)
        OPTIONAL MATCH (c)-[:IN_SECTION]->(s:Section)
        RETURN c.id AS chunk_id, c.text AS text,
               c.chunk_index AS chunk_index,
               d.id AS document_id, d.title AS document_title,
               s.title AS section_title, s.id AS section_id
        """

        try:
            driver = self.neo4j_driver

            def _run():
                with retry_session(driver) as session:
                    records = session.run(
                        cypher,
                        chunk_ids=chunk_ids,
                        group_id=group_id,
                    )
                    return [dict(r) for r in records]

            results = await asyncio.to_thread(_run)
        except Exception as e:
            logger.warning("route7_fetch_chunks_failed", error=str(e))
            return []

        # Build flat list of chunk dicts for the synthesizer.
        # Each chunk needs "text", "source", "entity", and "metadata" fields
        # matching what _retrieve_text_chunks() normally returns.
        scores = ppr_scores_map or {}
        chunks_list: List[Dict[str, Any]] = []
        for r in results:
            cid = r.get("chunk_id", "")
            chunks_list.append({
                "id": cid,
                "source": r.get("document_title", "Unknown"),
                "text": r.get("text", ""),
                "entity": "__ppr_passage__",
                # Synthesis weight fix: equal weight within fetched set (paper intent).
                # PPR scores determine *which* chunks to fetch (top-K); once fetched,
                # all chunks pass to the reader equally — consistent with upstream HippoRAG 2.
                "_entity_score": 1.0,
                "_source_entity": "__ppr_passage__",
                "metadata": {
                    "document_id": r.get("document_id", ""),
                    "section_path": r.get("section_title", ""),
                    "chunk_index": r.get("chunk_index", 0),
                },
            })

        # Preserve PPR ranking: sort by PPR score descending.
        # Neo4j UNWIND+MATCH does not guarantee return order matches input order.
        # Sort uses the scores dict (not _entity_score) so equal synthesis weights
        # don't collapse the ordering.
        if scores:
            chunks_list.sort(key=lambda c: scores.get(c["id"], 0.0), reverse=True)

        return chunks_list

    # ======================================================================
    # Phase 2: Structural Seeds (Tier 2)
    # ======================================================================

    async def _resolve_structural_seeds(
        self,
        query: str,
    ) -> Tuple[List[str], List[str]]:
        """Resolve structural seeds via section embedding matching.

        Reuses existing infrastructure from seed_resolver.py.

        Returns:
            Tuple of (entity_ids, section_titles).
        """
        try:
            from ..pipeline.seed_resolver import (
                match_sections_by_embedding,
                resolve_section_entities,
            )

            voyage_service = _get_voyage_service()
            if not voyage_service or not self._async_neo4j:
                return [], []

            # Match sections by embedding similarity
            matched_sections = await match_sections_by_embedding(
                async_neo4j=self._async_neo4j,
                query=query,
                group_id=self.group_id,
                embed_model=voyage_service,
            )

            if not matched_sections:
                return [], []

            # Resolve entities from matched sections
            section_entities = await resolve_section_entities(
                async_neo4j=self._async_neo4j,
                section_paths=matched_sections,
                group_id=self.group_id,
                folder_id=self.folder_id,
            )

            entity_ids = list({e["id"] for e in section_entities if e.get("id")})

            logger.info(
                "route7_structural_seeds",
                sections=len(matched_sections),
                entities=len(entity_ids),
            )
            return entity_ids, matched_sections

        except Exception as e:
            logger.warning("route7_structural_seeds_failed", error=str(e))
            return [], []

    # ======================================================================
    # Phase 2: Community Seeds (Tier 3)
    # ======================================================================

    async def _resolve_community_seeds(
        self,
        query: str,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Resolve community seeds via community embedding matching.

        Returns:
            Tuple of (entity_ids, community_data).
        """
        try:
            community_matcher = self.pipeline.community_matcher
            if not community_matcher or not self._async_neo4j:
                return [], []

            # Match communities
            matched = await community_matcher.match(query, top_k=3)
            if not matched:
                return [], []

            # Resolve entities from matched communities
            community_ids = [c.get("id") for c in matched if c.get("id")]
            if not community_ids:
                return [], matched

            cypher = """
            UNWIND $community_ids AS cid
            MATCH (e:Entity {group_id: $group_id})-[:BELONGS_TO]->(c:Community {id: cid})
            RETURN e.id AS entity_id, e.name AS entity_name, c.id AS community_id
            ORDER BY e.degree DESC
            LIMIT 15
            """

            async with self._async_neo4j._get_session() as session:
                result = await session.run(
                    cypher,
                    community_ids=community_ids,
                    group_id=self.group_id,
                )
                records = await result.data()

            entity_ids = list({r["entity_id"] for r in records if r.get("entity_id")})

            logger.info(
                "route7_community_seeds",
                communities=len(matched),
                entities=len(entity_ids),
            )
            return entity_ids, matched

        except Exception as e:
            logger.warning("route7_community_seeds_failed", error=str(e))
            return [], []

    # ======================================================================
    # Phase 2: Sentence Vector Search (copied from Route 5 pattern)
    # ======================================================================

    async def _retrieve_sentence_evidence(
        self,
        query: str,
        top_k: int = 30,
    ) -> List[Dict[str, Any]]:
        """Retrieve sentence-level evidence via Voyage vector search.

        Uses the sentence_embeddings_v2 Neo4j vector index —
        same pattern as Route 5.
        """
        voyage_service = _get_voyage_service()
        if not voyage_service or not self.neo4j_driver:
            return []

        try:
            query_embedding = voyage_service.embed_query(query)
        except Exception as e:
            logger.warning("route7_sentence_embed_failed", error=str(e))
            return []

        threshold = float(os.getenv("ROUTE7_SENTENCE_THRESHOLD", "0.2"))
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

        RETURN sent.id AS sentence_id,
               sent.text AS text,
               sent.source AS source,
               sent.section_path AS section_path,
               sent.page AS page,
               chunk.text AS chunk_text,
               doc.title AS document_title,
               doc.id AS document_id,
               score
        ORDER BY score DESC
        """

        try:
            driver = self.neo4j_driver

            def _run_search():
                with retry_session(driver) as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        top_k=top_k,
                        threshold=threshold,
                    )
                    return [dict(r) for r in records]

            results = await asyncio.to_thread(_run_search)
        except Exception as e:
            logger.warning("route7_sentence_search_failed", error=str(e))
            return []

        if not results:
            return []

        # Deduplicate
        seen: set = set()
        evidence: List[Dict[str, Any]] = []
        for r in results:
            sid = r.get("sentence_id", "")
            if sid in seen:
                continue
            seen.add(sid)
            evidence.append({
                "text": r.get("text", "").strip(),
                "score": r.get("score", 0),
                "document_title": r.get("document_title", "Unknown"),
                "document_id": r.get("document_id", ""),
                "section_path": r.get("section_path", ""),
                "page": r.get("page"),
                "sentence_id": sid,
            })

        logger.debug(
            "route7_sentence_search_complete",
            raw=len(results),
            deduped=len(evidence),
        )
        return evidence
