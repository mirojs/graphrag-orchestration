"""Route 2: Local Search - Entity-focused retrieval with LazyGraphRAG.

Best for queries that explicitly mention entities:
- "List all contracts with ABC Corp"
- "What are X's payment terms?"
- "Show me invoices from Contoso"

This route uses:
1. Entity extraction (NER / embedding match) to identify seed entities
2. LazyGraphRAG iterative deepening to expand context
3. Evidence synthesis with citations

V2 Mode (VOYAGE_V2_ENABLED=True):
- Uses Voyage embeddings (2048 dim) instead of OpenAI (3072 dim)
- Section-aware chunks for better semantic coherence
- BM25+Vector hybrid approach retained

Note: No HippoRAG in this route - entities are explicit in the query.
"""

import asyncio
import os
import time
from typing import Dict, Any, List, Optional

import structlog

from src.core.config import settings
from .base import BaseRouteHandler, RouteResult, Citation

logger = structlog.get_logger(__name__)

# V2 Voyage embedding service (lazy import to avoid circular deps)
_voyage_service: Optional["VoyageEmbedService"] = None


def _get_voyage_service():
    """Get Voyage embedding service for V2 mode."""
    global _voyage_service
    if _voyage_service is None:
        try:
            from src.worker.hybrid_v2.embeddings import get_voyage_embed_service, is_voyage_v2_enabled
            if is_voyage_v2_enabled():
                _voyage_service = get_voyage_embed_service()
        except Exception as e:
            logger.warning("voyage_service_init_failed", error=str(e))
    return _voyage_service


class LocalSearchHandler(BaseRouteHandler):
    """Route 2: Entity-focused search with LazyGraphRAG iterative deepening.
    
    V2 Mode (when VOYAGE_V2_ENABLED=True):
    - Uses Voyage embeddings (2048 dim) for query embedding
    - Searches embedding_v2 property on TextChunk nodes
    - Section-aware chunks for better semantic coherence
    """

    ROUTE_NAME = "route_2_local_search"

    def _is_v2_enabled(self) -> bool:
        """Check if Voyage embeddings are available (API key present)."""
        return bool(settings.VOYAGE_API_KEY)

    async def _get_query_embedding(self, query: str):
        """Get query embedding using Voyage voyage-context-3."""
        voyage_service = _get_voyage_service()
        if voyage_service:
            logger.info("route_2_using_voyage_embeddings")
            return voyage_service.embed_query(query)
        raise RuntimeError(
            "Route 2 embedding failed — VOYAGE_API_KEY not set. "
            "The deprecated OpenAI text-embedding-3-large fallback has been removed."
        )

    async def execute(
        self,
        query: str,
        response_type: str = "summary",
        knn_config: Optional[str] = None,
        prompt_variant: Optional[str] = None,
        synthesis_model: Optional[str] = None,
        include_context: bool = False,
    ) -> RouteResult:
        """
        Execute Route 2: LazyGraphRAG for entity-focused queries.
        
        Stage 2.1: Extract explicit entities (NER / embedding match)
        Stage 2.2: LazyGraphRAG iterative deepening
        Stage 2.3: Synthesis with citations
        
        Args:
            query: The user's natural language query
            response_type: Response format ("summary", "detailed_report", etc.)
            
        Returns:
            RouteResult with response, citations, and metadata
        """
        # Route 2 provides specific, direct answers — always default to concise
        # extraction prompt unless caller explicitly requests a different variant.
        if prompt_variant is None:
            prompt_variant = "v1_concise"

        enable_timings = os.getenv("ROUTE2_RETURN_TIMINGS", "1").strip().lower() in {"1", "true", "yes"}
        timings_ms: Dict[str, int] = {}
        t_route_start = time.perf_counter()

        logger.info("route_2_local_search_start", 
                   query=query[:50],
                   response_type=response_type,
                   prompt_variant=prompt_variant,
                   timings_enabled=enable_timings)
        
        # Stage 2.1: Entity Extraction (explicit entities)
        logger.info("stage_2.1_entity_extraction")
        t0 = time.perf_counter()
        seed_entities = await self.pipeline.disambiguator.disambiguate(query)
        timings_ms["stage_2.1_ner_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.info("stage_2.1_complete", num_seeds=len(seed_entities),
                   duration_ms=timings_ms["stage_2.1_ner_ms"])
        
        # Stage 2.2: LazyGraphRAG Iterative Deepening
        logger.info("stage_2.2_iterative_deepening")
        t0 = time.perf_counter()
        evidence_nodes = await self.pipeline.tracer.trace(
            query=query,
            seed_entities=seed_entities,
            top_k=15
        )
        timings_ms["stage_2.2_ppr_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.info("stage_2.2_complete", num_evidence=len(evidence_nodes),
                   duration_ms=timings_ms["stage_2.2_ppr_ms"])
        
        # Stage 2.2.5 + 2.2.6: Run in PARALLEL — they are independent.
        # 2.2.5 needs evidence_nodes → chunks → doc_ids → language spans
        # 2.2.6 needs only the query (skeleton enrichment via Voyage vectors)
        enable_sentence_citations = os.getenv("ROUTE2_SENTENCE_CITATIONS", "1").strip().lower() in {"1", "true", "yes"}

        async def _run_stage_2_2_5() -> tuple:
            """Chunk retrieval + language spans."""
            _t = time.perf_counter()
            _doc_spans: Dict[str, List[Dict]] = {}
            _chunks: list = []
            _escores: Dict[str, float] = {}
            _rstats: Dict[str, Any] = {}
            if enable_sentence_citations:
                _chunks, _escores, _rstats = await self.synthesizer._retrieve_text_chunks(evidence_nodes, query=query)
                _doc_ids = list({c.get("metadata", {}).get("document_id", "") for c in _chunks} - {""})
                if _doc_ids:
                    _doc_spans = await self._fetch_language_spans(_doc_ids)
                    logger.info("stage_2.2.5_sentence_spans", num_docs=len(_doc_ids), docs_with_spans=len(_doc_spans))
            _dur = int((time.perf_counter() - _t) * 1000)
            return _chunks, _escores, _rstats, _doc_spans, _dur

        async def _run_stage_2_2_6() -> tuple:
            """Skeleton sentence enrichment."""
            _t = time.perf_counter()
            _skel_chunks: List[Dict[str, Any]] = []
            if settings.SKELETON_ENRICHMENT_ENABLED and settings.VOYAGE_API_KEY:
                try:
                    if settings.SKELETON_GRAPH_TRAVERSAL_ENABLED:
                        _skel_chunks = await self._retrieve_skeleton_graph_traversal(query)
                        _strategy = "B_graph_traversal"
                    else:
                        _skel_chunks = await self._retrieve_skeleton_sentences(query)
                        _strategy = "A_flat_search"
                    if _skel_chunks:
                        logger.info(
                            "stage_2.2.6_skeleton_enrichment",
                            strategy=_strategy,
                            sentences=len(_skel_chunks),
                        )
                except Exception as e:
                    logger.warning("skeleton_enrichment_failed", error=str(e))
            _dur = int((time.perf_counter() - _t) * 1000)
            return _skel_chunks, _dur

        t0_parallel = time.perf_counter()
        (pre_chunks, _entity_scores, _retrieval_stats, doc_language_spans, dur_2_2_5), \
            (skeleton_coverage_chunks, dur_2_2_6) = await asyncio.gather(
                _run_stage_2_2_5(),
                _run_stage_2_2_6(),
            )
        timings_ms["stage_2.2.5_chunks_spans_ms"] = dur_2_2_5
        timings_ms["stage_2.2.6_skeleton_ms"] = dur_2_2_6
        timings_ms["stage_2.2.5_2.2.6_parallel_ms"] = int((time.perf_counter() - t0_parallel) * 1000)
        logger.info("stage_2.2.5_2.2.6_parallel_complete",
                    wall_ms=timings_ms["stage_2.2.5_2.2.6_parallel_ms"],
                    sum_sequential_ms=dur_2_2_5 + dur_2_2_6)

        # Stage 2.3: Synthesis with Citations
        # When skeleton enrichment provides precise sentence-level context,
        # allow a lighter model for extraction (see SKELETON_SYNTHESIS_MODEL).
        effective_model = synthesis_model  # caller override takes priority
        if not effective_model and skeleton_coverage_chunks and settings.SKELETON_SYNTHESIS_MODEL:
            effective_model = settings.SKELETON_SYNTHESIS_MODEL
            logger.info("stage_2.3_skeleton_model_override",
                       model=effective_model,
                       skeleton_sentences=len(skeleton_coverage_chunks))
        logger.info("stage_2.3_synthesis", model=effective_model or "default")
        t0 = time.perf_counter()
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type,
            prompt_variant=prompt_variant,
            synthesis_model=effective_model,
            include_context=include_context,
            language_spans_by_doc=doc_language_spans if doc_language_spans else None,
            pre_fetched_chunks=pre_chunks if enable_sentence_citations else None,
            coverage_chunks=skeleton_coverage_chunks if skeleton_coverage_chunks else None,
        )
        timings_ms["stage_2.3_synthesis_ms"] = int((time.perf_counter() - t0) * 1000)
        timings_ms["total_ms"] = int((time.perf_counter() - t_route_start) * 1000)
        logger.info("stage_2.3_complete",
                   duration_ms=timings_ms["stage_2.3_synthesis_ms"],
                   total_ms=timings_ms["total_ms"])
        
        # Merge retrieval stats when chunks were pre-fetched (retrieval happened in this handler)
        if enable_sentence_citations and _retrieval_stats:
            cs = synthesis_result.get("context_stats")
            if cs and isinstance(cs, dict):
                cs["retrieval"] = _retrieval_stats
        
        # ================================================================
        # POST-SYNTHESIS NEGATIVE DETECTION
        # ================================================================
        # If synthesizer returned 0 chunks used, it means no text content
        # was found. Return "Not found" instead of LLM hallucination.
        # ================================================================
        if synthesis_result.get("text_chunks_used", 0) == 0:
            logger.info(
                "route_2_negative_detection_post_synthesis",
                seed_entities=seed_entities,
                num_evidence_nodes=len(evidence_nodes),
                reason="synthesis_returned_no_chunks"
            )
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "seed_entities": seed_entities,
                    "num_evidence_nodes": len(evidence_nodes),
                    "text_chunks_used": 0,
                    "latency_estimate": "fast",
                    "precision_level": "high",
                    "route_description": "Entity-focused with post-synthesis negative detection",
                    "negative_detection": True,
                    **({
                        "timings_ms": timings_ms,
                    } if enable_timings else {}),
                }
            )
        
        # Build citations from synthesis result
        citations = []
        for i, c in enumerate(synthesis_result.get("citations", []), 1):
            if isinstance(c, dict):
                # Extract metadata for enhanced citations
                meta = c.get("metadata") or {}
                section_path = meta.get("section_path") or meta.get("section_path_key") or c.get("section_path", "")
                if isinstance(section_path, list):
                    section_path = " > ".join(str(s) for s in section_path if s)
                citations.append(Citation(
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
                    # Sentence-level citation data (comprehensive_sentence mode)
                    sentences=c.get("sentences"),
                    page_dimensions=c.get("page_dimensions"),
                ))
        
        return RouteResult(
            response=synthesis_result["response"],
            route_used=self.ROUTE_NAME,
            citations=citations,
            evidence_path=synthesis_result.get("evidence_path", []),
            metadata={
                "seed_entities": seed_entities,
                "num_evidence_nodes": len(evidence_nodes),
                "text_chunks_used": synthesis_result.get("text_chunks_used", 0),
                "latency_estimate": "moderate",
                "precision_level": "high",
                "route_description": "Entity-focused with LazyGraphRAG iterative deepening",
                **({"context_stats": synthesis_result["context_stats"]} if synthesis_result.get("context_stats") else {}),
                **({"llm_context": synthesis_result["llm_context"]} if synthesis_result.get("llm_context") else {}),
                # Pass through raw_extractions from comprehensive mode (2-pass extraction)
                **({
                    "raw_extractions": synthesis_result["raw_extractions"],
                    "processing_mode": synthesis_result.get("processing_mode")
                } if synthesis_result.get("raw_extractions") else {}),
                # Skeleton enrichment metadata (Strategy A)
                **({"skeleton_sentences_injected": len(skeleton_coverage_chunks)} if skeleton_coverage_chunks else {}),
                # Per-stage latency breakdown
                **({
                    "timings_ms": timings_ms,
                } if enable_timings else {}),
            }
        )

    # ================================================================
    # SKELETON ENRICHMENT (Strategy A)
    # ================================================================

    async def _retrieve_skeleton_sentences(self, query: str) -> List[Dict[str, Any]]:
        """Query the sentence vector index and format results as pseudo-chunks.
        
        Returns list of chunk-format dicts compatible with `coverage_chunks`
        parameter of `synthesize()`.
        """
        # 1. Embed query with Voyage
        query_embedding = await self._get_query_embedding(query)
        if not query_embedding:
            logger.warning("skeleton_no_query_embedding")
            return []
        
        # 2. Vector search against sentence_embeddings_v2 index
        top_k = settings.SKELETON_SENTENCE_TOP_K
        threshold = settings.SKELETON_SIMILARITY_THRESHOLD
        group_id = self.group_id
        
        cypher = """
        CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
        YIELD node AS sent, score
        WHERE sent.group_id = $group_id AND score >= $threshold
        OPTIONAL MATCH (sent)-[:PART_OF]->(chunk:TextChunk)
        OPTIONAL MATCH (sent)-[:IN_SECTION]->(sec:Section)
        OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
        RETURN sent.id AS sentence_id,
               sent.text AS text,
               sent.source AS source,
               sent.section_path AS section_path,
               sent.parent_text AS parent_text,
               sent.page AS page,
               sent.chunk_id AS chunk_id,
               sent.document_id AS document_id,
               chunk.text AS chunk_text,
               doc.title AS document_title,
               sec.path_key AS section_key,
               score
        ORDER BY score DESC
        """
        
        sentence_results = []
        try:
            # Run sync Neo4j query in executor to avoid blocking
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.neo4j_driver.session() as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        top_k=top_k,
                        threshold=threshold,
                    )
                    return [dict(r) for r in records]
            
            sentence_results = await loop.run_in_executor(self._executor, _run_query)
        except Exception as e:
            logger.warning("skeleton_vector_query_failed", error=str(e))
            return []
        
        if not sentence_results:
            return []
        
        # 3. Format as coverage_chunks (pseudo-chunks for synthesis injection)
        # The synthesis pipeline processes these as regular text chunks,
        # merging them into the context window alongside entity-retrieved chunks.
        coverage_chunks = []
        for result in sentence_results:
            # Use parent_text for richer context, fall back to sentence text
            display_text = result.get("parent_text") or result.get("text", "")
            if not display_text:
                continue
            
            # Build section path for citation
            section = result.get("section_key") or result.get("section_path", "")
            
            # Prefix with source tag so LLM knows this is supplementary evidence
            source_tag = result.get("source", "paragraph")
            tagged_text = (
                f"[Skeleton: {source_tag}, sim={result.get('score', 0):.3f}] "
                f"{display_text}"
            )
            
            coverage_chunks.append({
                "text": tagged_text,
                "metadata": {
                    "document_id": result.get("document_id", ""),
                    "document_title": result.get("document_title", "Unknown"),
                    "section_path_key": section,
                    "page_number": result.get("page"),
                    "source": f"skeleton_{source_tag}",
                    "skeleton_sentence_id": result.get("sentence_id", ""),
                    "skeleton_score": result.get("score", 0.0),
                },
            })
        
        logger.info(
            "skeleton_sentences_retrieved",
            total=len(sentence_results),
            coverage_chunks=len(coverage_chunks),
        )
        return coverage_chunks

    # ================================================================
    # STRATEGY B: Graph Traversal Retrieval
    # ================================================================

    async def _retrieve_skeleton_graph_traversal(self, query: str) -> List[Dict[str, Any]]:
        """Strategy B: Traverse the sentence graph from vector-matched seeds.
        
        Unlike Strategy A (flat vector search → isolated sentences), Strategy B
        uses the graph structure to discover coherent multi-sentence clusters:
        
        1. ANCHOR: Vector search → top-k seed sentences (same as Strategy A)
        2. EXPAND: From each seed, traverse:
           - RELATED_TO → cross-chunk semantically similar sentences
           - NEXT/PREV → neighbouring sentences in same chunk (context window)
        3. COLLECT: For each discovered sentence, fetch parent chunk context
        4. SCORE: Seed score × decay per hop type
        5. DEDUPLICATE: By sentence ID, keep highest score
        
        This gives the LLM coherent multi-sentence passages (via NEXT),
        cross-document related evidence (via RELATED_TO), and full chunk
        context (via PART_OF) — all from a single graph traversal.
        """
        # 1. Embed query
        query_embedding = await self._get_query_embedding(query)
        if not query_embedding:
            logger.warning("strategy_b_no_query_embedding")
            return []
        
        top_k = settings.SKELETON_SENTENCE_TOP_K
        threshold = settings.SKELETON_SIMILARITY_THRESHOLD
        next_hops = settings.SKELETON_TRAVERSAL_NEXT_HOPS
        related_hops = settings.SKELETON_TRAVERSAL_RELATED_HOPS
        group_id = self.group_id
        
        # 2. Graph traversal query: seed → RELATED_TO → NEXT expansion → parent context
        # Single Cypher query that does the anchor + expand + collect in one round trip.
        cypher = """
        // ANCHOR: Vector search for seed sentences
        CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
        YIELD node AS seed, score
        WHERE seed.group_id = $group_id AND score >= $threshold
        
        // EXPAND: Traverse RELATED_TO edges (cross-chunk semantic links)
        OPTIONAL MATCH (seed)-[rel:RELATED_TO {source: 'knn_sentence'}]-(related:Sentence)
        WHERE related.group_id = $group_id
        
        // Collect seed + related into a unified set
        WITH collect(DISTINCT {node: seed, score: score, hop: 0, via: 'seed'}) AS seeds,
             collect(DISTINCT {node: related, score: score * rel.similarity * 0.8, hop: 1, via: 'related_to'}) AS related_nodes
        WITH seeds + [r IN related_nodes WHERE r.node IS NOT NULL] AS all_anchors
        UNWIND all_anchors AS anchor
        WITH DISTINCT anchor.node AS sent, max(anchor.score) AS sent_score, 
             min(anchor.hop) AS min_hop, collect(DISTINCT anchor.via)[0] AS via
        
        // EXPAND: NEXT/PREV neighbours for local context window
        CALL {
            WITH sent
            OPTIONAL MATCH path = (sent)-[:NEXT*1..2]->(fwd:Sentence)
            RETURN collect(DISTINCT {node: fwd, hop_type: 'next'}) AS next_nodes
        }
        CALL {
            WITH sent
            OPTIONAL MATCH path = (sent)<-[:NEXT*1..2]-(prev:Sentence)
            RETURN collect(DISTINCT {node: prev, hop_type: 'prev'}) AS prev_nodes
        }
        
        // Merge: anchor sentence + its NEXT/PREV neighbours
        WITH sent, sent_score, min_hop, via, next_nodes, prev_nodes
        WITH sent, sent_score, min_hop, via,
             [n IN next_nodes WHERE n.node IS NOT NULL | n.node] AS fwd_list,
             [n IN prev_nodes WHERE n.node IS NOT NULL | n.node] AS prev_list
        
        // Collect all sentences from this anchor's expansion
        WITH collect({
            node: sent, score: sent_score, hop: min_hop, via: via,
            fwd: fwd_list, prev: prev_list
        }) AS expansions
        UNWIND expansions AS exp
        
        // Flatten: anchor + its forward/prev expansions
        WITH collect({node: exp.node, score: exp.score, via: exp.via}) AS anchor_entries,
             [e IN expansions | [f IN e.fwd | {node: f, score: e.score * 0.9, via: 'next'}]] AS fwd_entries,
             [e IN expansions | [p IN e.prev | {node: p, score: e.score * 0.9, via: 'prev'}]] AS prev_entries
        WITH anchor_entries + 
             reduce(acc=[], x IN fwd_entries | acc + x) +
             reduce(acc=[], x IN prev_entries | acc + x) AS all_entries
        UNWIND all_entries AS entry
        WITH DISTINCT entry.node AS sent, max(entry.score) AS final_score, 
             collect(DISTINCT entry.via) AS sources
        
        // COLLECT: Parent chunk + document context
        OPTIONAL MATCH (sent)-[:PART_OF]->(chunk:TextChunk)
        OPTIONAL MATCH (sent)-[:IN_SECTION]->(sec:Section)
        OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
        
        RETURN sent.id AS sentence_id,
               sent.text AS text,
               sent.source AS source,
               sent.section_path AS section_path,
               sent.parent_text AS parent_text,
               sent.page AS page,
               sent.chunk_id AS chunk_id,
               sent.document_id AS document_id,
               chunk.text AS chunk_text,
               doc.title AS document_title,
               sec.path_key AS section_key,
               final_score AS score,
               sources
        ORDER BY final_score DESC
        """
        
        traversal_results = []
        try:
            loop = asyncio.get_event_loop()
            
            def _run_traversal():
                with self.neo4j_driver.session() as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        top_k=top_k,
                        threshold=threshold,
                    )
                    return [dict(r) for r in records]
            
            traversal_results = await loop.run_in_executor(self._executor, _run_traversal)
        except Exception as e:
            logger.warning("strategy_b_traversal_failed", error=str(e))
            # Fallback to Strategy A
            logger.info("strategy_b_fallback_to_strategy_a")
            return await self._retrieve_skeleton_sentences(query)
        
        if not traversal_results:
            return []
        
        # 3. Format as coverage_chunks (same format as Strategy A for seamless integration)
        seen_chunks: set = set()  # Deduplicate by chunk_id (multiple sentences per chunk)
        coverage_chunks = []
        
        for result in traversal_results:
            chunk_id = result.get("chunk_id", "")
            sentence_id = result.get("sentence_id", "")
            
            # Use parent_text for richer sentence context, fall back to sentence text
            display_text = result.get("parent_text") or result.get("text", "")
            if not display_text:
                continue
            
            # For sentences expanded via NEXT, use the chunk text to provide
            # full coherent context rather than individual sentence fragments
            sources = result.get("sources", [])
            is_context_expansion = any(s in ("next", "prev") for s in sources) and "seed" not in sources
            
            if is_context_expansion and chunk_id and chunk_id not in seen_chunks:
                # Context expansion: inject the full chunk text (coherent multi-sentence passage)
                chunk_text = result.get("chunk_text", "")
                if chunk_text and len(chunk_text) > len(display_text):
                    display_text = chunk_text
                    seen_chunks.add(chunk_id)
                    source_label = "chunk_expansion"
                else:
                    source_label = "next_sentence"
            elif "related_to" in sources:
                source_label = "related_to"
            else:
                source_label = result.get("source", "paragraph")
            
            section = result.get("section_key") or result.get("section_path", "")
            score = result.get("score", 0)
            
            tagged_text = (
                f"[Skeleton-B: {source_label}, sim={score:.3f}] "
                f"{display_text}"
            )
            
            coverage_chunks.append({
                "text": tagged_text,
                "metadata": {
                    "document_id": result.get("document_id", ""),
                    "document_title": result.get("document_title", "Unknown"),
                    "section_path_key": section,
                    "page_number": result.get("page"),
                    "source": f"skeleton_b_{source_label}",
                    "skeleton_sentence_id": sentence_id,
                    "skeleton_score": score,
                    "skeleton_sources": sources,
                },
            })
        
        logger.info(
            "strategy_b_graph_traversal_complete",
            seeds=sum(1 for r in traversal_results if "seed" in (r.get("sources") or [])),
            related=sum(1 for r in traversal_results if "related_to" in (r.get("sources") or [])),
            next_expanded=sum(1 for r in traversal_results if "next" in (r.get("sources") or []) or "prev" in (r.get("sources") or [])),
            total_results=len(traversal_results),
            coverage_chunks=len(coverage_chunks),
        )
        return coverage_chunks