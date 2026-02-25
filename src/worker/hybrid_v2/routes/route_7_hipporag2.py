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
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import structlog

from .base import BaseRouteHandler, Citation, RouteResult
from ..services.neo4j_retry import retry_session

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Entity-doc map v2: exhaustive entity enumeration support
# ---------------------------------------------------------------------------
# Maps query-object keywords to the 5 fixed Entity.type values.
# The type schema is set at indexing time and is NOT corpus-specific.
_ENTITY_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "ORGANIZATION": [
        "party", "parties", "organization", "organizations",
        "company", "companies", "firm", "firms",
        "entity", "entities", "contractor", "contractors",
        "vendor", "vendors", "principal", "principals",
    ],
    "PERSON": [
        "party", "parties", "people", "individual", "individuals",
        "person", "persons", "signatory", "signatories",
        "representative", "representatives", "personnel",
    ],
    "LOCATION": [
        "location", "locations", "place", "places",
        "address", "addresses", "jurisdiction", "jurisdictions",
        "city", "cities", "state", "states", "country", "countries",
    ],
}

# Structural signals for exhaustive intent (no domain nouns)
_EXHAUSTIVE_INTENT_RE = re.compile(
    r"\b(?:list|enumerate|identify|name|find|what\s+are)\b"
    r".{0,40}"
    r"\b(?:all|every|each|across)\b",
    re.IGNORECASE,
)

# Corpus-scope confirmation (query must reference documents/corpus)
_CORPUS_SCOPE_RE = re.compile(
    r"\b(?:documents?|files?|contracts?|agreements?|corpus|set|collection)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Generic role-label filter for entity-doc map.
# Entity extraction often promotes generic role descriptors (e.g. "Builder",
# "Customer", "Agent") to Entity nodes.  These are not named parties and
# should be excluded from the entity-doc map to avoid over-generation.
# Matching is case-insensitive on the normalized (stripped, lowered) name.
# ---------------------------------------------------------------------------
_ROLE_LABEL_BLOCKLIST: set = {
    # contract role labels
    "builder", "buyer", "buyer/owner", "seller", "owner", "agent",
    "customer", "contractor", "subcontractor", "vendor", "supplier",
    "manufacturer", "administrator", "arbitrator", "mediator",
    "pumper", "tenant", "landlord", "lessee", "lessor", "licensee",
    "licensor", "manager", "principal", "representative",
    "authorized representative",
    # generic legal/governance labels
    "party", "parties", "claimant", "respondent", "insured",
    "beneficiary", "guarantor", "indemnitor",
    # governmental/institutional generics
    "county", "state", "municipality", "city", "government",
}


def _is_role_label(entity_name: str) -> bool:
    """Return True if the entity name is a generic role label."""
    return entity_name.strip().lower() in _ROLE_LABEL_BLOCKLIST


# Structured relationship types to surface in the entity-doc map Role column.
# Only these short, schema-defined labels are fetched; freeform co-occurrence
# descriptions (up to 200-char sentence text) are excluded.
_STRUCTURED_ROLE_TYPES: list = [
    "PARTY_TO", "LOCATED_IN", "DEFINES", "REFERENCES", "FOUND_IN",
]

# ---------------------------------------------------------------------------
# Voyage embedding service — shared singleton (same pattern as Route 5)
# ---------------------------------------------------------------------------
_voyage_service = None
_voyage_init_attempted = False
_voyage_init_lock = threading.Lock()


def _get_voyage_service():
    """Get Voyage embedding service for query + triple embedding."""
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
           - DPR passage search (sentence_embeddings_v2 vector index) -> passage seeds
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
        language: Optional[str] = None,
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
        dpr_sentence_top_k = int(os.getenv("ROUTE7_DPR_SENTENCE_TOP_K", "60"))
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

        # 2b. DPR passage search (sentence-level Small-to-Big)
        dpr_task = asyncio.create_task(
            self._dpr_passage_search(query_embedding, dpr_top_k, dpr_sentence_top_k)
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

        # Phase 2+3: Add structural seeds (Tier 2) and community seeds (Tier 3) in parallel
        structural_sections: List[str] = []
        community_data: List[Dict[str, Any]] = []

        _seed_tasks: List[Tuple[str, Any]] = []
        if structural_seeds_enabled and self._async_neo4j:
            _seed_tasks.append(("structural", self._resolve_structural_seeds(query)))
        if community_seeds_enabled and self.pipeline.community_matcher:
            _seed_tasks.append(("community", self._resolve_community_seeds(query)))

        if _seed_tasks:
            _seed_results = await asyncio.gather(*[t[1] for t in _seed_tasks])
            for (label, _), result in zip(_seed_tasks, _seed_results):
                if label == "structural":
                    structural_entity_ids, structural_sections = result
                    w_structural = float(os.getenv("ROUTE7_W_STRUCTURAL", "0.2"))
                    for eid in structural_entity_ids:
                        entity_seeds[eid] = entity_seeds.get(eid, 0) + w_structural
                else:
                    community_entity_ids, community_data = result
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
        # Step 4.5: Entity-doc map for exhaustive enumeration queries
        #
        # When the query asks to "list all X across documents", PPR+synthesis
        # over-includes incidental mentions from raw text.  Instead, query the
        # complete entity-document MENTIONS index (type-filtered) and pass the
        # result as a constraining structural header to synthesis.
        # ------------------------------------------------------------------
        graph_structural_header: Optional[str] = None
        entity_doc_rows: List[Dict[str, Any]] = []
        detected_types: Optional[List[str]] = None

        entity_doc_map_enabled = os.getenv(
            "ROUTE7_ENTITY_DOC_MAP", "1"
        ).strip().lower() in {"1", "true", "yes"}

        if entity_doc_map_enabled:
            detected_types = self._detect_exhaustive_entity_types(query)
            if detected_types:
                t_edm = time.perf_counter()
                entity_doc_rows_raw = await self._query_entity_doc_map(detected_types)
                entity_doc_rows = [
                    r for r in entity_doc_rows_raw
                    if not _is_role_label(r["entity_name"])
                ]
                if entity_doc_rows:
                    # Group rows by entity for bullet-list format
                    entity_groups: Dict[
                        Tuple[str, str], List[Dict[str, Any]]
                    ] = defaultdict(list)
                    for row in entity_doc_rows:
                        key = (row["entity_name"], row["entity_type"])
                        entity_groups[key].append(row)

                    header_lines = [
                        "## Entity-Document Map (from knowledge graph index)",
                        "",
                        "Each entity below lists the documents where it appears.",
                        "[PARTY_TO] = direct party/signatory to the agreement "
                        "in that document.",
                        "[---] = merely referenced (address, job site, invoice "
                        "recipient).",
                        "The context sentence after each entry shows the "
                        "entity's actual contractual role (e.g. owner, "
                        "builder, agent). Use ONLY that context to determine "
                        "roles — do NOT rely on signature-block titles.",
                        "",
                    ]
                    for (ent_name, ent_type), rows in entity_groups.items():
                        header_lines.append(f"### {ent_name} [{ent_type}]")
                        for row in rows:
                            role_labels = row.get("doc_role_labels", [])
                            role_str = (
                                ", ".join(role_labels) if role_labels else "---"
                            )
                            snippet = self._extract_sentence_context(
                                ent_name,
                                row.get("doc_sample_chunk", ""),
                            )
                            doc_title = row["document_title"]
                            header_lines.append(
                                f'- {doc_title} [{role_str}]: "{snippet}"'
                            )
                        header_lines.append("")  # blank line between entities

                    graph_structural_header = "\n".join(header_lines)

                    timings_ms["step_45_entity_doc_map_ms"] = int(
                        (time.perf_counter() - t_edm) * 1000
                    )
                    unique_entities = len(entity_groups)
                    logger.info(
                        "step_45_entity_doc_map_v3",
                        entity_types=detected_types,
                        rows_total=len(entity_doc_rows_raw),
                        rows_after_filter=len(entity_doc_rows),
                        unique_entities=unique_entities,
                        role_labels_removed=len(entity_doc_rows_raw) - len(entity_doc_rows),
                        query=query[:80],
                    )

        # ------------------------------------------------------------------
        # Step 5: Fetch chunk texts + synthesis
        # ------------------------------------------------------------------
        t0 = time.perf_counter()

        # Get top-K passage chunk IDs and fetch their text
        top_passage_scores = passage_scores[:ppr_passage_top_k]
        top_chunk_ids = [cid for cid, _ in top_passage_scores]
        ppr_scores_map = {cid: score for cid, score in top_passage_scores}

        # Pass PPR entity names so _fetch_chunks_by_ids can build focused
        # 3-sentence windows around entity-relevant sentences.
        ppr_entity_names = [name for name, _ in entity_scores[:10]]
        pre_fetched_chunks = await self._fetch_chunks_by_ids(
            top_chunk_ids,
            ppr_scores_map=ppr_scores_map,
            entity_names=ppr_entity_names,
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
            language=language,
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

        # Post-synthesis: narrow chunk citations to specific sentences
        sentence_map = synthesis_result.get("sentence_citation_map", {})
        if sentence_map:
            self._narrow_citations_to_sentences(
                citations, synthesis_result.get("response", ""), sentence_map
            )
        self._enrich_citations_with_geometry(citations)

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

        # Entity-doc map metadata
        if graph_structural_header:
            metadata["entity_doc_map"] = {
                "entity_types": detected_types,
                "entities_found": len(entity_doc_rows),
            }

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
    # Entity-doc map v2: exhaustive entity enumeration
    # ======================================================================

    @staticmethod
    def _detect_exhaustive_entity_types(query: str) -> Optional[List[str]]:
        """Detect if query requires exhaustive entity enumeration.

        Returns a list of entity type strings (e.g. ["ORGANIZATION", "PERSON"])
        when the query has exhaustive intent + corpus scope + a detectable type
        target.  Returns None otherwise (normal pipeline runs unchanged).

        Three gates keep false-positive rate low:
          1. Exhaustive intent — list/enumerate/find + all/every/each/across
          2. Corpus scope — mentions documents/contracts/files/set
          3. Type target — maps query-object words to entity type schema
        """
        q = query.lower()

        if not _EXHAUSTIVE_INTENT_RE.search(q):
            return None

        if not _CORPUS_SCOPE_RE.search(q):
            return None

        matched_types: set = set()
        for entity_type, keywords in _ENTITY_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in q:
                    matched_types.add(entity_type)

        return sorted(matched_types) if matched_types else None

    @staticmethod
    def _extract_sentence_context(
        entity_name: str, chunk_text: str, max_chars: int = 500
    ) -> str:
        """Extract a 3-sentence window around the entity mention.

        Finds the sentence containing the entity, then includes ±1
        adjacent sentences for anaphora and role context.  Returns the
        window capped at *max_chars*.  Falls back to the first
        *max_chars* of the chunk when the entity is not found.
        """
        if not chunk_text:
            return ""

        idx = chunk_text.lower().find(entity_name.lower())
        if idx < 0:
            return chunk_text[:max_chars].strip()

        # ── Split chunk into sentences ──
        import re
        # Split on sentence-ending punctuation followed by whitespace
        sent_spans: list[tuple[int, int]] = []
        for m in re.finditer(r'[^.!?\n]+(?:[.!?]+|\n|$)', chunk_text):
            s, e = m.start(), m.end()
            if m.group().strip():
                sent_spans.append((s, e))

        if not sent_spans:
            return chunk_text[:max_chars].strip()

        # Find which sentence contains the entity
        target_idx = 0
        for i, (s, e) in enumerate(sent_spans):
            if s <= idx < e:
                target_idx = i
                break

        # ±1 sentence window
        win_start = max(0, target_idx - 1)
        win_end = min(len(sent_spans), target_idx + 2)

        window_text = chunk_text[
            sent_spans[win_start][0]:sent_spans[win_end - 1][1]
        ].strip()

        # Truncate if too long, keeping entity visible
        if len(window_text) > max_chars:
            entity_pos = idx - sent_spans[win_start][0]
            half = max_chars // 2
            t_start = max(0, entity_pos - half)
            t_end = min(len(window_text), t_start + max_chars)
            window_text = window_text[t_start:t_end].strip()
            if t_start > 0:
                window_text = "..." + window_text
            if t_end < len(window_text):
                window_text = window_text + "..."

        return window_text

    async def _query_entity_doc_map(
        self,
        entity_types: List[str],
    ) -> List[Dict[str, Any]]:
        """Query ALL entities of given types with per-document granularity.

        Returns one row per (entity, document) pair, each with:
        - doc_mentions: how many TextChunks mention this entity in this doc
        - doc_sample_chunk: a sample chunk from THIS document (not global)
        - doc_role_labels: RELATED_TO role types scoped to this document
          (only includes roles where the related entity also appears
          in the same document)

        Uses the MENTIONS + IN_DOCUMENT edge path — the same structural
        index that PPR traverses, but without PPR's top-K scope limitation.
        """
        if not entity_types or not self.neo4j_driver:
            return []

        group_id = self.group_id
        cypher = """
        MATCH (e:Entity {group_id: $group_id})
              <-[:MENTIONS]-(tc:Sentence {group_id: $group_id})
              -[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
        WHERE e.type IN $entity_types
          AND ($folder_id IS NULL
               OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id}))
        WITH e, d, count(tc) AS doc_mentions,
             collect(tc.text)[0] AS doc_sample_chunk
        OPTIONAL MATCH (e)-[r:RELATED_TO]-(e2:Entity {group_id: $group_id})
        WHERE r.rel_type IN $role_rel_types
          AND EXISTS {
            MATCH (e2)<-[:MENTIONS]-(:Sentence {group_id: $group_id})
                  -[:IN_DOCUMENT]->(d)
          }
        WITH e, d, doc_mentions, doc_sample_chunk,
             collect(DISTINCT r.rel_type)[0..3] AS doc_role_labels
        RETURN e.name AS entity_name, e.type AS entity_type,
               d.title AS document_title, doc_mentions,
               doc_sample_chunk, doc_role_labels
        ORDER BY entity_name, doc_mentions DESC
        """
        driver = self.neo4j_driver

        def _run():
            with retry_session(driver, read_only=True) as session:
                records = session.run(
                    cypher,
                    group_id=group_id,
                    entity_types=entity_types,
                    role_rel_types=_STRUCTURED_ROLE_TYPES,
                    folder_id=self.folder_id,
                )
                return [
                    {
                        "entity_name": r["entity_name"],
                        "entity_type": r["entity_type"],
                        "document_title": r["document_title"] or "",
                        "doc_mentions": r["doc_mentions"],
                        "doc_sample_chunk": r["doc_sample_chunk"] or "",
                        "doc_role_labels": [
                            rl for rl in (r["doc_role_labels"] or []) if rl
                        ],
                    }
                    for r in records
                ]

        try:
            results = await asyncio.to_thread(_run)
            logger.info(
                "route7_entity_doc_map_v3",
                entity_types=entity_types,
                rows_found=len(results),
            )
            return results
        except Exception as e:
            logger.warning("route7_entity_doc_map_v3_failed", error=str(e))
            return []

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
    # DPR Passage Search (Small-to-Big: sentence → parent chunk)
    # ======================================================================

    async def _dpr_passage_search(
        self,
        query_embedding: List[float],
        top_k: int = 20,
        sentence_top_k: int = 60,
    ) -> List[Tuple[str, float]]:
        """Dense Passage Retrieval via sentence-level vector search.

        Searches sentence_embeddings_v2 for sharp single-sentence matches.
        Returns sentence IDs as passage nodes for PPR.
        """
        if not self.neo4j_driver:
            return []

        group_id = self.group_id
        folder_id = self.folder_id

        sentence_cypher = """CYPHER 25
        CALL () {
            MATCH (s:Sentence)
            SEARCH s IN (VECTOR INDEX sentence_embeddings_v2 FOR $embedding WHERE s.group_id = $group_id LIMIT $sentence_top_k)
            SCORE AS score
            OPTIONAL MATCH (s)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
            WITH s, score, d
            WHERE $folder_id IS NULL OR d IS NULL
               OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})
            RETURN s.id AS chunk_id, score
        }
        RETURN chunk_id, max(score) AS score
        ORDER BY score DESC
        LIMIT $top_k
        """

        try:
            driver = self.neo4j_driver

            def _run_sentence():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        sentence_cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        sentence_top_k=sentence_top_k,
                        top_k=top_k,
                        folder_id=folder_id,
                    )
                    return [(r["chunk_id"], r["score"]) for r in records]

            results = await asyncio.to_thread(_run_sentence)
            logger.debug("route7_dpr_sentence_complete", hits=len(results))
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
        entity_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch chunk text + metadata from Neo4j by chunk IDs.

        When *entity_names* is provided, returns **focused 3-sentence
        windows** around sentences that mention those entities instead of
        the full chunk text.  This reduces noise for synthesis while
        keeping the entity-relevant context tight.

        Uses a two-pass approach for speed:
        - Pass 1 (always): fast chunk metadata fetch without sentence join
        - Pass 2 (only when entity_names given): fetch sentences for the
          focused-window logic

        Returns flat list of chunk dicts in the format expected by the
        synthesizer's ``pre_fetched_chunks`` parameter, sorted by PPR
        score descending when ``ppr_scores_map`` is provided.
        """
        if not chunk_ids or not self.neo4j_driver:
            return []

        group_id = self.group_id
        driver = self.neo4j_driver

        # ── Pass 1: Sentence metadata ──
        cypher_chunks = """
        UNWIND $chunk_ids AS cid
        MATCH (node:Sentence {id: cid, group_id: $group_id})
        OPTIONAL MATCH (node)-[:IN_DOCUMENT]->(d:Document)
        WITH cid, node, d
        WHERE $folder_id IS NULL OR d IS NULL
           OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})
        OPTIONAL MATCH (node)-[:IN_SECTION]->(s:Section)
        RETURN cid AS chunk_id,
               coalesce(node.text, '') AS text,
               coalesce(node.index_in_doc, 0) AS chunk_index,
               d.id AS document_id, d.title AS document_title,
               s.title AS section_title, s.id AS section_id
        """

        # ── Pass 2: Sentence texts (only when entity_names given) ──
        ent_lower = (
            {n.lower() for n in entity_names} if entity_names else set()
        )

        async def _fetch_chunk_meta():
            def _run():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher_chunks,
                        chunk_ids=chunk_ids,
                        group_id=group_id,
                        folder_id=self.folder_id,
                    )
                    return [dict(r) for r in records]
            return await asyncio.to_thread(_run)

        async def _fetch_sentences():
            if not ent_lower:
                return {}
            cypher_sents = """
            UNWIND $chunk_ids AS cid
            MATCH (sent:Sentence {id: cid, group_id: $group_id})
            RETURN sent.id AS chunk_id, sent.text AS sent_text, coalesce(sent.index_in_doc, 0) AS idx
            ORDER BY chunk_id, idx
            """
            def _run():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher_sents,
                        chunk_ids=chunk_ids,
                        group_id=group_id,
                    )
                    return [(r["chunk_id"], r["sent_text"]) for r in records]
            rows = await asyncio.to_thread(_run)
            result: Dict[str, List[str]] = {}
            for cid, text in rows:
                result.setdefault(cid, []).append(text)
            return result

        async def _fetch_entity_hits():
            """Use graph MENTIONS edges for precise sentence-entity mapping."""
            if not entity_names:
                return {}
            cypher_hits = """
            UNWIND $chunk_ids AS cid
            MATCH (s:Sentence {id: cid, group_id: $group_id})
            MATCH (s)-[:MENTIONS]->(e:Entity {group_id: $group_id})
            WHERE e.name IN $entity_names
            RETURN cid AS chunk_id, coalesce(s.index_in_doc, 0) AS idx
            """
            def _run():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher_hits,
                        chunk_ids=chunk_ids,
                        group_id=group_id,
                        entity_names=list(entity_names),
                    )
                    return [(r["chunk_id"], r["idx"]) for r in records]
            rows = await asyncio.to_thread(_run)
            result: Dict[str, set] = {}
            for cid, idx in rows:
                result.setdefault(cid, set()).add(idx)
            return result

        try:
            # Run all three queries in parallel
            results, chunk_sentences, entity_hit_map = await asyncio.gather(
                _fetch_chunk_meta(),
                _fetch_sentences(),
                _fetch_entity_hits(),
            )
        except Exception as e:
            logger.warning("route7_fetch_chunks_failed", error=str(e))
            return []

        # Attach sentence_texts and entity hit indices to results
        for r in results:
            cid = r.get("chunk_id", "")
            r["sentence_texts"] = chunk_sentences.get(cid, [])
            r["_entity_hit_indices"] = entity_hit_map.get(cid, set())

        # ── Build focused 3-sentence windows ──
        # Uses pre-computed entity hit indices from graph MENTIONS edges
        # (precise one-to-one sentence→entity mapping from indexing time).
        # Falls back to full chunk text when no entity hits exist.

        def _focused_text(
            sentence_texts: List[str],
            full_text: str,
            hit_indices: set,
        ) -> str:
            if not sentence_texts or not hit_indices:
                return full_text

            # Expand each hit ±1 and merge overlapping ranges
            ranges: list[tuple[int, int]] = []
            for idx in sorted(hit_indices):
                if idx < 0 or idx >= len(sentence_texts):
                    continue
                lo = max(0, idx - 1)
                hi = min(len(sentence_texts), idx + 2)
                if ranges and lo <= ranges[-1][1]:
                    ranges[-1] = (ranges[-1][0], hi)  # merge
                else:
                    ranges.append((lo, hi))

            if not ranges:
                return full_text

            # Build final text from windows
            windows: list[str] = []
            for lo, hi in ranges:
                windows.append(
                    " ".join(sentence_texts[lo:hi])
                )
            return " [...] ".join(windows)

        scores = ppr_scores_map or {}

        # ── Merge adjacent same-section chunks ──
        # Group by (document_id, section_title), sort by chunk_index,
        # and merge consecutive chunks so the LLM receives one coherent
        # block per section instead of fragmented overlapping snippets.
        from collections import defaultdict

        section_groups: dict[tuple, list] = defaultdict(list)
        for r in results:
            key = (r.get("document_id", ""), r.get("section_title", ""))
            section_groups[key].append(r)

        _MAX_MERGE = 2  # merge at most 2 consecutive chunks to prevent mega-blocks

        merged_results: list[dict] = []
        for _key, group in section_groups.items():
            group.sort(key=lambda x: x.get("chunk_index", 0))
            merged = [group[0]]
            for r in group[1:]:
                prev = merged[-1]
                prev_idx = prev.get("chunk_index", 0)
                curr_idx = r.get("chunk_index", 0)
                merge_count = len(prev.get("_merged_ids", [prev.get("chunk_id", "")]))
                if curr_idx == prev_idx + 1 and merge_count < _MAX_MERGE:
                    # Adjacent — merge sentences and text
                    prev_sents = prev.get("sentence_texts") or []
                    curr_sents = r.get("sentence_texts") or []
                    # Offset entity hit indices for the appended chunk
                    prev_hits = prev.get("_entity_hit_indices") or set()
                    curr_hits = r.get("_entity_hit_indices") or set()
                    offset = len(prev_sents)
                    merged_hits = prev_hits | {idx + offset for idx in curr_hits}
                    prev["sentence_texts"] = prev_sents + curr_sents
                    prev["_entity_hit_indices"] = merged_hits
                    prev["text"] = (
                        (prev.get("text", "") + " " + r.get("text", ""))
                        .strip()
                    )
                    prev["chunk_index"] = curr_idx  # advance for next merge
                    # Track merged IDs for PPR score lookup
                    prev.setdefault("_merged_ids", [prev.get("chunk_id", "")])
                    prev["_merged_ids"].append(r.get("chunk_id", ""))
                else:
                    merged.append(r)
            merged_results.extend(merged)

        chunks_list: List[Dict[str, Any]] = []
        for r in merged_results:
            cid = r.get("chunk_id", "")
            sentence_texts = r.get("sentence_texts") or []
            full_text = r.get("text", "")
            hit_indices = r.get("_entity_hit_indices") or set()
            focused = _focused_text(sentence_texts, full_text, hit_indices)

            # Best PPR score among merged chunk IDs
            merged_ids = r.get("_merged_ids", [cid])
            best_score = max(scores.get(mid, 0.0) for mid in merged_ids) if scores else 0.0

            chunks_list.append({
                "id": cid,
                "source": r.get("document_title", "Unknown"),
                "text": focused,
                "entity": "__ppr_passage__",
                "_entity_score": 1.0,
                "_source_entity": "__ppr_passage__",
                "_ppr_score": best_score,
                "metadata": {
                    "document_id": r.get("document_id", ""),
                    "section_path": r.get("section_title", ""),
                    "chunk_index": r.get("chunk_index", 0),
                },
            })

        # Preserve PPR ranking: sort by PPR score descending.
        if scores:
            chunks_list.sort(key=lambda c: c.get("_ppr_score", 0.0), reverse=True)

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
            WHERE $folder_id IS NULL
               OR EXISTS {
                 MATCH (e)<-[:MENTIONS]-(:Sentence {group_id: $group_id})
                       -[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
                       -[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})
               }
            RETURN e.id AS entity_id, e.name AS entity_name, c.id AS community_id
            ORDER BY e.degree DESC
            LIMIT 15
            """

            async with self._async_neo4j._get_session() as session:
                result = await session.run(
                    cypher,
                    community_ids=community_ids,
                    group_id=self.group_id,
                    folder_id=self.folder_id,
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

        OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
        WITH sent, score, doc
        WHERE $folder_id IS NULL OR doc IS NULL
           OR (doc)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})

        RETURN sent.id AS sentence_id,
               sent.text AS text,
               sent.source AS source,
               sent.section_path AS section_path,
               sent.page AS page,
               sent.parent_text AS chunk_text,
               doc.title AS document_title,
               doc.id AS document_id,
               score
        ORDER BY score DESC
        """

        try:
            driver = self.neo4j_driver

            def _run_search():
                with retry_session(driver, read_only=True) as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        top_k=top_k,
                        threshold=threshold,
                        folder_id=self.folder_id,
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
