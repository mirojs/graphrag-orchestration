"""Route 3: Global Search - Thematic queries with LazyGraphRAG + HippoRAG PPR.

Best for thematic/cross-document queries:
- "What are the main compliance risks?"
- "Summarize key themes across documents"
- "What termination clauses exist?"

This route uses:
1. Community matching (LazyGraphRAG)
2. Hub entity extraction
3. Enhanced graph context (MENTIONS + RELATED_TO)
4. Cypher 25 Hybrid RRF (BM25 + Vector)
5. Section boost for document-structure-aware retrieval
6. HippoRAG PPR for detail recovery
7. Coverage gap fill for cross-document queries

Features:
- Theme coverage metric for comprehensive responses
- Section-aware diversification
- Cross-document SHARES_ENTITY expansion
- Keyword boost for termination/reporting/remedies/insurance queries
"""

import os
import re
import time
from typing import Dict, Any, List, Tuple, Optional

import structlog

from .base import BaseRouteHandler, RouteResult, Citation

logger = structlog.get_logger(__name__)


class GlobalSearchHandler(BaseRouteHandler):
    """Route 3: LazyGraphRAG + HippoRAG for thematic queries."""

    ROUTE_NAME = "route_3_global_search"

    async def execute(
        self,
        query: str,
        response_type: str = "summary"
    ) -> RouteResult:
        """
        Execute Route 3: Global Search for thematic queries.
        
        Stages:
        - 3.1: Community matching (LazyGraphRAG)
        - 3.2: Hub entity extraction
        - 3.3: Enhanced graph context (MENTIONS + RELATED_TO)
        - 3.3.5: Cypher 25 Hybrid RRF (BM25 + Vector)
        - Section Boost: Semantic section discovery
        - 3.4: HippoRAG PPR tracing (detail recovery)
        - 3.4.1: Coverage gap fill for cross-document queries
        - 3.5: Synthesis with theme coverage
        
        Args:
            query: The user's natural language query
            response_type: Response format ("summary", "detailed_report", etc.)
            
        Returns:
            RouteResult with response, citations, and metadata
        """
        enable_timings = os.getenv("ROUTE3_RETURN_TIMINGS", "0").strip().lower() in {"1", "true", "yes"}
        timings_ms: Dict[str, int] = {}
        t_route0 = time.perf_counter()
        
        # Detect coverage intent
        from app.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
        coverage_mode = EnhancedGraphRetriever.detect_coverage_intent(query)
        
        logger.info("route_3_global_search_start",
                   query=query[:50],
                   response_type=response_type,
                   coverage_mode=coverage_mode)
        
        # Stage 3.1: Community Matching
        logger.info("stage_3.1_community_matching")
        t0 = time.perf_counter()
        matched_communities = await self.pipeline.community_matcher.match_communities(query, top_k=3)
        community_data = [c for c, _ in matched_communities]
        timings_ms["stage_3.1_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.info("stage_3.1_complete", num_communities=len(community_data))
        
        # Stage 3.2: Hub Entity Extraction
        logger.info("stage_3.2_hub_extraction")
        t0 = time.perf_counter()
        hub_entities = await self.pipeline.hub_extractor.extract_hub_entities(
            communities=community_data,
            top_k_per_community=10
        )
        timings_ms["stage_3.2_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.info("stage_3.2_complete", num_hubs=len(hub_entities))
        
        # Stage 3.3: Enhanced Graph Context
        logger.info("stage_3.3_enhanced_graph_context")
        t0 = time.perf_counter()
        graph_context = await self.pipeline.enhanced_retriever.get_full_context(
            hub_entities=hub_entities,
            expand_relationships=True,
            get_source_chunks=True,
            max_chunks_per_entity=3,
            max_relationships=30,
        )
        timings_ms["stage_3.3_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.info("stage_3.3_complete",
                   num_source_chunks=len(graph_context.source_chunks),
                   num_relationships=len(graph_context.relationships))
        
        # Stage 3.3.5: Cypher 25 Hybrid RRF (BM25 + Vector)
        t0 = time.perf_counter()
        await self._apply_hybrid_rrf_stage(query, graph_context)
        timings_ms["stage_3.3.5_ms"] = int((time.perf_counter() - t0) * 1000)
        
        # Section Boost: Semantic Section Discovery
        t0 = time.perf_counter()
        section_boost_metadata = await self._apply_section_boost(query, graph_context)
        timings_ms["section_boost_ms"] = int((time.perf_counter() - t0) * 1000)
        
        # SHARES_ENTITY Cross-Document Expansion
        shares_entity_metadata = await self._apply_shares_entity_boost(
            query, graph_context, section_boost_metadata
        )
        
        # Keyword Boost for specific query types
        await self._apply_keyword_boost(query, graph_context)
        
        # Doc Lead Boost for cross-document queries
        await self._apply_doc_lead_boost(query, graph_context)
        
        # Graph signal check for negative detection
        has_graph_signal = (
            bool(hub_entities) or
            bool(graph_context.related_entities) or
            bool(graph_context.relationships) or
            bool(graph_context.source_chunks)
        )
        
        # Negative detection: No graph signal = topic doesn't exist
        if not has_graph_signal and not coverage_mode:
            logger.info("route_3_negative_detection_no_graph_signal",
                       num_hubs=len(hub_entities))
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "matched_communities": [c.get("title", "?") for c in community_data],
                    "hub_entities": hub_entities,
                    "negative_detection": True,
                    "detection_reason": "no_graph_signal"
                }
            )
        
        # Entity-Query relevance check (for weak signals only)
        if not self._check_entity_relevance(query, hub_entities, graph_context, coverage_mode):
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "matched_communities": [c.get("title", "?") for c in community_data],
                    "hub_entities": hub_entities,
                    "negative_detection": True,
                    "detection_reason": "weak_graph_signal_no_relevance"
                }
            )
        
        # Stage 3.4: HippoRAG PPR Tracing
        logger.info("stage_3.4_ppr_tracing")
        t0 = time.perf_counter()
        ppr_seeds = hub_entities + graph_context.related_entities
        ppr_evidence = []
        if ppr_seeds:
            ppr_evidence = await self.pipeline.tracer.trace(
                query=query,
                seed_entities=ppr_seeds,
                top_k=15
            )
        timings_ms["stage_3.4_ms"] = int((time.perf_counter() - t0) * 1000)
        logger.info("stage_3.4_complete", num_ppr_evidence=len(ppr_evidence))
        
        # Stage 3.4.1: Coverage Gap Fill
        if coverage_mode:
            await self._apply_coverage_gap_fill(query, graph_context)
        
        # Stage 3.5: Synthesis
        logger.info("stage_3.5_synthesis")
        t0 = time.perf_counter()
        synthesis_result = await self._synthesize_global_response(
            query=query,
            graph_context=graph_context,
            community_data=community_data,
            hub_entities=hub_entities,
            ppr_evidence=ppr_evidence,
            response_type=response_type,
        )
        timings_ms["stage_3.5_ms"] = int((time.perf_counter() - t0) * 1000)
        
        # Post-synthesis negative detection
        if synthesis_result.get("text_chunks_used", 0) == 0:
            logger.info("route_3_negative_detection_post_synthesis")
            return RouteResult(
                response="The requested information was not found in the available documents.",
                route_used=self.ROUTE_NAME,
                citations=[],
                evidence_path=[],
                metadata={
                    "negative_detection": True,
                    "detection_reason": "synthesis_no_chunks"
                }
            )
        
        # Build citations
        citations = []
        for i, c in enumerate(synthesis_result.get("citations", []), 1):
            if isinstance(c, dict):
                citations.append(Citation(
                    index=i,
                    chunk_id=c.get("chunk_id", f"chunk_{i}"),
                    document_id=c.get("document_id", ""),
                    document_title=c.get("document_title", c.get("document", "Unknown")),
                    score=c.get("score", 0.0),
                    text_preview=c.get("text_preview", c.get("text", ""))[:200],
                ))
        
        timings_ms["total_ms"] = int((time.perf_counter() - t_route0) * 1000)
        
        metadata = {
            "matched_communities": [c.get("title", "?") for c in community_data],
            "hub_entities": hub_entities,
            "num_source_chunks": len(graph_context.source_chunks),
            "num_relationships": len(graph_context.relationships),
            "theme_coverage": synthesis_result.get("theme_coverage"),
            "text_chunks_used": synthesis_result.get("text_chunks_used", 0),
            "latency_estimate": "moderate",
            "precision_level": "high",
            "route_description": "LazyGraphRAG + HippoRAG thematic search",
        }
        
        if enable_timings:
            metadata["timings_ms"] = timings_ms
        
        return RouteResult(
            response=synthesis_result["response"],
            route_used=self.ROUTE_NAME,
            citations=citations,
            evidence_path=synthesis_result.get("evidence_path", []),
            metadata=metadata
        )

    # ==========================================================================
    # HYBRID RRF STAGE (with BM25 Merge Diversification)
    # ==========================================================================
    
    async def _apply_hybrid_rrf_stage(self, query: str, graph_context) -> Dict[str, Any]:
        """Apply Cypher 25 Hybrid BM25 + Vector with RRF Fusion.
        
        Includes BM25 merge diversification with per-doc caps to ensure
        document diversity (helps coverage for invoices/short contracts
        that may be drowned out by longer agreements).
        """
        enable_hybrid = os.getenv("ROUTE3_CYPHER25_HYBRID_RRF", "1").strip().lower() in {"1", "true", "yes"}
        enable_bm25 = os.getenv("ROUTE3_GRAPH_NATIVE_BM25", "1").strip().lower() in {"1", "true", "yes"}
        enable_fulltext_boost = os.getenv("ROUTE3_FULLTEXT_BOOST", "1").strip().lower() in {"1", "true", "yes"}
        
        metadata: Dict[str, Any] = {
            "enabled": enable_hybrid or enable_bm25,
            "hybrid_rrf": enable_hybrid,
            "applied": False,
            "results": 0,
            "added": 0,
        }
        
        if not (enable_hybrid or enable_bm25):
            return metadata
        
        try:
            from app.hybrid.pipeline.enhanced_graph_retriever import SourceChunk
            
            # Get query embedding
            query_embedding = None
            if enable_hybrid:
                try:
                    from app.services.llm_service import LLMService
                    llm_service = LLMService()
                    if llm_service.embed_model:
                        query_embedding = llm_service.embed_model.get_text_embedding(query)
                except Exception as e:
                    logger.warning("hybrid_rrf_embedding_failed", error=str(e))
            
            # Choose search strategy
            bm25_results: List[Tuple[Dict[str, Any], float, bool]] = []
            
            if enable_hybrid and query_embedding:
                # Cypher 25 Hybrid: BM25 + Vector + RRF (best quality)
                # Returns List[Tuple[Dict, float, bool]]
                hybrid_results = await self.pipeline._search_chunks_cypher25_hybrid_rrf(
                    query_text=query,
                    embedding=query_embedding,
                    top_k=20,
                    vector_k=30,
                    bm25_k=30,
                    rrf_k=60,
                    use_phrase_boost=True,
                )
                bm25_results = list(hybrid_results)
                metadata["hybrid_rrf"] = True
            else:
                # Fallback: Pure BM25 (fast, no embedding required)
                # Returns List[Tuple[Dict, float, bool]]
                bm25_only_results = await self.pipeline._search_chunks_graph_native_bm25(
                    query_text=query,
                    top_k=20,
                    use_phrase_boost=True,
                )
                bm25_results = list(bm25_only_results)
            
            metadata["results"] = len(bm25_results)
            
            # ==================================================================
            # BM25 MERGE DIVERSIFICATION
            # When integrating BM25 hits into a thematic/cross-document route,
            # prefer document diversity over taking many hits from the same doc.
            # This helps coverage for cases like invoices/short docs that may
            # otherwise be drowned out by longer agreements.
            # ==================================================================
            bm25_merge_top_k = int(os.getenv("ROUTE3_BM25_MERGE_TOP_K", "20"))
            bm25_max_per_doc = int(os.getenv("ROUTE3_BM25_MAX_PER_DOC", "2"))
            bm25_min_docs = int(os.getenv("ROUTE3_BM25_MIN_DOCS", "3"))
            
            def _bm25_doc_key(chunk_dict: Dict[str, Any]) -> str:
                return (
                    (chunk_dict.get("document_id") or "")
                    or (chunk_dict.get("doc_id") or "")
                    or (chunk_dict.get("document_source") or "")
                    or (chunk_dict.get("document_title") or "")
                    or (chunk_dict.get("url") or "")
                    or "unknown"
                ).strip()
            
            # Compute which BM25 candidates are actually addable (not already present)
            existing_ids = {c.chunk_id for c in graph_context.source_chunks}
            sorted_bm25 = sorted(bm25_results, key=lambda t: float(t[1] or 0.0), reverse=True)
            
            diversified_bm25: List[Tuple[Dict[str, Any], float, bool]] = []
            picked_chunk_ids: set = set()
            per_doc_counts: Dict[str, int] = {}
            picked_docs: set = set()
            
            # Pass 1: pick the best new chunk per document until we hit bm25_min_docs
            for chunk_dict, score, is_anchor in sorted_bm25:
                if len(diversified_bm25) >= bm25_merge_top_k:
                    break
                cid = (chunk_dict.get("id") or "").strip()
                if not cid or cid in existing_ids or cid in picked_chunk_ids:
                    continue
                doc_key = _bm25_doc_key(chunk_dict)
                if doc_key in picked_docs:
                    continue
                diversified_bm25.append((chunk_dict, score, is_anchor))
                picked_chunk_ids.add(cid)
                picked_docs.add(doc_key)
                per_doc_counts[doc_key] = 1
                if len(picked_docs) >= bm25_min_docs:
                    break
            
            # Pass 2: fill remaining slots, respecting per-document caps
            for chunk_dict, score, is_anchor in sorted_bm25:
                if len(diversified_bm25) >= bm25_merge_top_k:
                    break
                cid = (chunk_dict.get("id") or "").strip()
                if not cid or cid in existing_ids or cid in picked_chunk_ids:
                    continue
                doc_key = _bm25_doc_key(chunk_dict)
                if per_doc_counts.get(doc_key, 0) >= bm25_max_per_doc:
                    continue
                diversified_bm25.append((chunk_dict, score, is_anchor))
                picked_chunk_ids.add(cid)
                per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
            
            metadata["merge"] = {
                "top_k": bm25_merge_top_k,
                "max_per_doc": bm25_max_per_doc,
                "min_docs": bm25_min_docs,
                "selected": len(diversified_bm25),
                "unique_docs": len(per_doc_counts),
            }
            
            # Merge into graph_context.source_chunks (deduplicated by chunk_id)
            added_count = 0
            
            for chunk_dict, score, is_anchor in diversified_bm25:
                cid = (chunk_dict.get("id") or "").strip()
                if not cid or cid in existing_ids:
                    continue
                
                # Extract section path from section_path_key if available
                spk = (chunk_dict.get("section_path_key") or "").strip()
                section_path = spk.split(" > ") if spk else []
                
                # Mark source for traceability
                source_marker = "bm25_phrase"
                
                graph_context.source_chunks.append(
                    SourceChunk(
                        chunk_id=cid,
                        text=chunk_dict.get("text") or "",
                        entity_name=source_marker,
                        section_path=list(section_path),
                        section_id=(chunk_dict.get("section_id") or "").strip(),
                        document_id=(chunk_dict.get("document_id") or "").strip(),
                        document_title=(chunk_dict.get("document_title") or "").strip(),
                        document_source=(chunk_dict.get("document_source") or "").strip(),
                        relevance_score=float(score or 0.0),
                    )
                )
                existing_ids.add(cid)
                added_count += 1
            
            metadata["applied"] = added_count > 0
            metadata["added"] = added_count
            
            if added_count > 0:
                logger.info(
                    "stage_3.3.5_bm25_phrase_applied",
                    results=metadata["results"],
                    added=added_count,
                    unique_docs=len(per_doc_counts),
                    total_source_chunks=len(graph_context.source_chunks),
                )
            else:
                logger.info(
                    "stage_3.3.5_bm25_phrase_no_new_chunks",
                    results=metadata["results"],
                    reason="All BM25 matches already in source_chunks",
                )
            
            return metadata
            
        except Exception as e:
            logger.warning("stage_3.3.5_bm25_phrase_failed", error=str(e))
            # Fall back to simple fulltext if BM25 phrase search fails
            if enable_fulltext_boost:
                logger.info("stage_3.3.5_fallback_to_simple_fulltext")
                try:
                    from app.hybrid.pipeline.enhanced_graph_retriever import SourceChunk
                    fulltext_chunks = await self.pipeline._search_text_chunks_fulltext(
                        query_text=query,
                        top_k=15,
                    )
                    existing_ids = {c.chunk_id for c in graph_context.source_chunks}
                    for chunk_dict, score in fulltext_chunks:
                        cid = (chunk_dict.get("id") or "").strip()
                        if not cid or cid in existing_ids:
                            continue
                        spk = (chunk_dict.get("section_path_key") or "").strip()
                        section_path = spk.split(" > ") if spk else []
                        graph_context.source_chunks.append(
                            SourceChunk(
                                chunk_id=cid,
                                text=chunk_dict.get("text") or "",
                                entity_name="fulltext_fallback",
                                section_path=list(section_path),
                                section_id=(chunk_dict.get("section_id") or "").strip(),
                                document_id=(chunk_dict.get("document_id") or "").strip(),
                                document_title=(chunk_dict.get("document_title") or "").strip(),
                                document_source=(chunk_dict.get("document_source") or "").strip(),
                                relevance_score=float(score or 0.0),
                            )
                        )
                        existing_ids.add(cid)
                except Exception as fallback_e:
                    logger.warning("stage_3.3.5_fulltext_fallback_failed", error=str(fallback_e))
        
        return metadata

    # ==========================================================================
    # SECTION BOOST (with Multi-Seed for Reporting Queries)
    # ==========================================================================
    
    async def _apply_section_boost(self, query: str, graph_context) -> Dict[str, Any]:
        """Apply semantic section discovery boost.
        
        For reporting/record-keeping queries, uses multi-seed query expansion
        to cover both clause families (e.g., "monthly statement" and "pumper/volumes"),
        then merges/deduplicates by chunk id.
        """
        enable = os.getenv("ROUTE3_SECTION_BOOST", "1").strip().lower() in {"1", "true", "yes"}
        
        if not enable:
            return {"enabled": False, "applied": False}
        
        metadata: Dict[str, Any] = {
            "enabled": True,
            "applied": False,
            "strategy": None,
            "semantic": {
                "enabled": False,
                "seed_candidates": 0,
                "seed_mode": None,
                "top_sections": []
            }
        }
        
        # Store section IDs for downstream use (SHARES_ENTITY boost)
        semantic_section_ids: List[str] = []
        
        try:
            from app.services.llm_service import LLMService
            from app.hybrid.pipeline.enhanced_graph_retriever import SourceChunk
            llm_service = LLMService()
            
            # Light query expansion for semantic *section discovery only*.
            # Some reporting clauses are phrased as "monthly statement of income and expenses"
            # and may not rank well for a query that only says "reporting/record-keeping".
            seed_query = query
            ql_seed = (query or "").lower()
            is_reporting_query_seed = any(
                k in ql_seed
                for k in [
                    "reporting",
                    "record-keeping",
                    "record keeping",
                    "recordkeeping",
                ]
            )
            if is_reporting_query_seed:
                seed_query = f"{query} servicing report monthly statement income expenses accounting"
            
            metadata["semantic"]["enabled"] = True
            
            # Semantic section discovery via hybrid RRF (vector + fulltext)
            seed_chunks: List[Tuple[Dict[str, Any], float]] = []
            if llm_service.embed_model is not None:
                try:
                    # For reporting/record-keeping queries, run two semantic seed queries to
                    # cover both clause families (e.g., "monthly statement" and "pumper/volumes"),
                    # then merge/deduplicate by chunk id. This helps avoid a single document
                    # dominating the seed set while still using the section-boost mechanism.
                    seed_queries = [seed_query]
                    if is_reporting_query_seed:
                        seed_queries = [
                            f"{query} monthly statement income expenses accounting",
                            f"{query} pumper county volumes servicing report",
                        ]

                    merged_by_id: Dict[str, Tuple[Dict[str, Any], float]] = {}
                    for sq in seed_queries:
                        query_embedding = llm_service.embed_model.get_text_embedding(sq)
                        chunks = await self.pipeline._search_text_chunks_hybrid_rrf(
                            query_text=sq,
                            embedding=query_embedding,
                            top_k=24,
                            vector_k=60,
                            fulltext_k=60,
                            section_diversify=True,
                            max_per_section=3,
                            max_per_document=1 if is_reporting_query_seed else 5,
                        )
                        for chunk_dict, score in chunks:
                            cid = (chunk_dict.get("id") or "").strip()
                            if not cid:
                                continue
                            prev = merged_by_id.get(cid)
                            if prev is None or float(score or 0.0) > float(prev[1] or 0.0):
                                merged_by_id[cid] = (chunk_dict, float(score or 0.0))

                    seed_chunks = sorted(merged_by_id.values(), key=lambda kv: kv[1], reverse=True)
                    metadata["semantic"]["seed_mode"] = (
                        "hybrid_rrf_multi" if is_reporting_query_seed else "hybrid_rrf"
                    )
                    metadata["semantic"]["seed_query_count"] = len(seed_queries)
                except Exception as e:
                    logger.warning("route_3_section_boost_embedding_failed", error=str(e))
                    seed_chunks = await self.pipeline._search_text_chunks_fulltext(query_text=seed_query, top_k=30)
                    metadata["semantic"]["seed_mode"] = "fulltext"
            else:
                # Fallback to fulltext if embeddings unavailable
                seed_chunks = await self.pipeline._search_text_chunks_fulltext(query_text=seed_query, top_k=30)
                metadata["semantic"]["seed_mode"] = "fulltext"

            metadata["semantic"]["seed_candidates"] = len(seed_chunks)

            if is_reporting_query_seed and seed_chunks:
                try:
                    preview = []
                    for chunk_dict, score in seed_chunks[:5]:
                        preview.append(
                            {
                                "score": float(score or 0.0),
                                "document_title": (chunk_dict.get("document_title") or "")[:160],
                                "section_path_key": (chunk_dict.get("section_path_key") or "")[:220],
                            }
                        )
                    logger.info(
                        "route_3_section_boost_seed_debug",
                        seed_mode=metadata["semantic"].get("seed_mode"),
                        seed_candidates=len(seed_chunks),
                        seed_preview=preview,
                    )
                except Exception as e:
                    logger.warning("route_3_section_boost_seed_debug_failed", error=str(e))

            # If we already found highly relevant chunks during the semantic *section discovery* seed
            # (especially after light expansion for reporting clauses), include a small number of
            # those chunks directly as evidence. This stays within the section-boost mechanism and
            # prevents losing clause-style obligations that may appear late in long sections.
            seed_evidence_added = 0
            seed_evidence_take = 6 if is_reporting_query_seed else 0
            if seed_evidence_take > 0 and seed_chunks:
                existing_ids = {c.chunk_id for c in graph_context.source_chunks}
                for chunk_dict, score in seed_chunks[:seed_evidence_take]:
                    cid = (chunk_dict.get("id") or "").strip()
                    if not cid or cid in existing_ids:
                        continue

                    spk = (chunk_dict.get("section_path_key") or "").strip()
                    section_path = spk.split(" > ") if spk else []

                    graph_context.source_chunks.append(
                        SourceChunk(
                            chunk_id=cid,
                            text=chunk_dict.get("text") or "",
                            entity_name="section_seed",
                            section_path=list(section_path),
                            section_id=(chunk_dict.get("section_id") or "").strip(),
                            document_id=(chunk_dict.get("document_id") or "").strip(),
                            document_title=(chunk_dict.get("document_title") or "").strip(),
                            document_source=(chunk_dict.get("document_source") or "").strip(),
                            relevance_score=float(score or 0.0),
                        )
                    )
                    existing_ids.add(cid)
                    seed_evidence_added += 1

                metadata["semantic"]["seed_evidence_added"] = seed_evidence_added

            # Extract section IDs and rank by relevance score
            section_scores: Dict[str, float] = {}
            section_paths: Dict[str, str] = {}
            for chunk_dict, score in seed_chunks:
                section_id = (chunk_dict.get("section_id") or "").strip()
                if not section_id:
                    continue
                section_scores[section_id] = section_scores.get(section_id, 0.0) + float(score or 0.0)
                spk = (chunk_dict.get("section_path_key") or "").strip()
                if spk and section_id not in section_paths:
                    section_paths[section_id] = spk

            # Get top sections (slightly larger for reporting/record-keeping so we don't miss
            # clause-style obligations that appear later in long agreements).
            ranked_sections = sorted(section_scores.items(), key=lambda kv: kv[1], reverse=True)
            top_n_sections = 15 if is_reporting_query_seed else 10
            semantic_section_ids = [sid for sid, _ in ranked_sections[:top_n_sections]]
            metadata["semantic"]["top_sections"] = [
                {
                    "section_id": sid,
                    "path_key": section_paths.get(sid, ""),
                    "score": round(section_scores.get(sid, 0.0), 6),
                }
                for sid in semantic_section_ids
            ]

            # Fetch all chunks from these sections via IN_SECTION graph expansion
            if semantic_section_ids:
                # For reporting/record-keeping, increase budgets so we include later chunks in
                # the selected sections (e.g., monthly statement clauses), while keeping other
                # queries on the tighter default budget.
                max_per_section = 6 if is_reporting_query_seed else 3
                max_per_document = 6 if is_reporting_query_seed else 4
                max_total = 30 if is_reporting_query_seed else 20
                boost_chunks = await self.pipeline.enhanced_retriever.get_section_id_boost_chunks(
                    section_ids=semantic_section_ids,
                    max_per_section=max_per_section,
                    max_per_document=max_per_document,
                    max_total=max_total,
                    spread_within_section=is_reporting_query_seed,
                )
                
                # Merge into existing chunks (deduplicated)
                existing_ids = {c.chunk_id for c in graph_context.source_chunks}
                added_chunks = [c for c in boost_chunks if c.chunk_id not in existing_ids]
                if added_chunks:
                    graph_context.source_chunks.extend(added_chunks)
                    metadata["applied"] = True
                    metadata["strategy"] = "semantic_section_discovery"
                    metadata["boost_candidates"] = len(boost_chunks)
                    metadata["boost_added"] = len(added_chunks)
                    
                    logger.info(
                        "route_3_section_boost_applied",
                        strategy="semantic_section_discovery",
                        boost_candidates=len(boost_chunks),
                        boost_added=len(added_chunks),
                        total_source_chunks=len(graph_context.source_chunks),
                    )
            
            # Store section IDs in metadata for downstream use
            metadata["semantic_section_ids"] = semantic_section_ids
                    
        except Exception as e:
            logger.warning("section_boost_failed", error=str(e))
        
        return metadata

    # ==========================================================================
    # SHARES_ENTITY BOOST
    # ==========================================================================
    
    async def _apply_shares_entity_boost(
        self, query: str, graph_context, section_metadata: Dict
    ) -> Dict[str, Any]:
        """Apply SHARES_ENTITY cross-document expansion."""
        enable = os.getenv("ROUTE3_SHARES_ENTITY_BOOST", "1").strip().lower() in {"1", "true", "yes"}
        
        if not enable or not section_metadata.get("applied"):
            return {"applied": False}
        
        metadata = {"applied": False}
        
        try:
            # Use sections discovered by Section Boost as seeds (1:1 with original)
            # Prioritize explicit semantic section IDs if available
            if section_metadata.get("semantic_section_ids"):
                seed_section_ids = section_metadata["semantic_section_ids"]
            else:
                # Fallback: extract from whatever chunks we have
                seed_section_ids = list(set(
                    c.section_id for c in graph_context.source_chunks
                    if c.section_id
                ))[:10]
            
            if seed_section_ids:
                cross_doc_sections = await self.pipeline.enhanced_retriever.get_related_sections_via_shared_entities(
                    section_ids=seed_section_ids,
                    cross_doc_only=True,
                    min_shared_count=2,
                    max_per_section=2,
                )
                
                if cross_doc_sections:
                    cross_doc_ids = list(set(
                        r.get("related_section_id", "") for r in cross_doc_sections
                        if r.get("related_section_id")
                    ))
                    
                    cross_doc_chunks = await self.pipeline.enhanced_retriever.get_section_id_boost_chunks(
                        section_ids=cross_doc_ids,
                        max_per_section=2,
                        max_per_document=3,
                        max_total=15,
                    )
                    
                    existing_ids = {c.chunk_id for c in graph_context.source_chunks}
                    added = [c for c in cross_doc_chunks if c.chunk_id not in existing_ids]
                    
                    if added:
                        for c in added:
                            c.entity_name = "shares_entity_cross_doc"
                        graph_context.source_chunks.extend(added)
                        metadata = {"applied": True, "chunks_added": len(added)}
                        logger.info("shares_entity_boost_applied", added=len(added))
                        
        except Exception as e:
            logger.warning("shares_entity_boost_failed", error=str(e))
        
        return metadata

    # ==========================================================================
    # KEYWORD BOOST (Full Profiles from Original)
    # ==========================================================================
    
    async def _apply_keyword_boost(self, query: str, graph_context) -> None:
        """Apply targeted keyword boost for specific query types.
        
        This uses extended keyword lists with 12-16 terms per profile plus
        min_matches thresholds for precision. Helps surface explicit obligations/
        numbers that may not map to hub entities.
        """
        enable = os.getenv("ROUTE3_KEYWORD_BOOST", "1").strip().lower() in {"1", "true", "yes"}
        
        ql = query.lower()
        
        # Detect query types with extended patterns
        is_termination_query = any(
            k in ql
            for k in [
                "termination",
                "terminate",
                "cancellation",
                "cancel",
                "refund",
                "deposit",
                "forfeit",
                "forfeiture",
            ]
        )

        is_reporting_query = any(
            k in ql
            for k in [
                "reporting",
                "record-keeping",
                "record keeping",
                "recordkeeping",
                "monthly statement",
                "statement",
                "income",
                "expenses",
            ]
        )

        is_remedies_query = any(
            k in ql
            for k in [
                "remedies",
                "remedy",
                "dispute",
                "arbitration",
                "default",
                "legal fees",
                "attorney",
                "contractor",
                "small claims",
            ]
        )

        is_insurance_query = any(
            k in ql
            for k in [
                "insurance",
                "liability",
                "liability insurance",
                "additional insured",
                "indemnify",
                "indemnity",
                "hold harmless",
                "gross negligence",
            ]
        )
        
        if not enable:
            if is_termination_query or is_reporting_query or is_remedies_query or is_insurance_query:
                logger.info(
                    "route_3_keyword_boost_disabled",
                    reason="ROUTE3_KEYWORD_BOOST not enabled",
                )
            return
        
        if not any([is_termination_query, is_reporting_query, is_remedies_query, is_insurance_query]):
            return
        
        keyword_sets: List[Tuple[str, List[str], int]] = []
        
        if is_termination_query:
            keyword_sets.append(
                (
                    "termination",
                    [
                        "termination",
                        "terminate",
                        "cancellation",
                        "cancel",
                        "notice",
                        "written notice",
                        "refund",
                        "deposit",
                        "non-refundable",
                        "not refundable",
                        "forfeit",
                        "forfeiture",
                        "transfer",
                        "transferable",
                        "3 business days",
                        "three (3) business days",
                    ],
                    2,
                )
            )

        if is_reporting_query:
            keyword_sets.append(
                (
                    "reporting",
                    [
                        "reporting",
                        "record-keeping",
                        "record keeping",
                        "monthly statement",
                        "income",
                        "expenses",
                        "statement",
                        "accounting",
                        "servicing report",
                        "volumes",
                        "gallons",
                    ],
                    1,
                )
            )

        if is_remedies_query:
            keyword_sets.append(
                (
                    "remedies",
                    [
                        "default",
                        "customer default",
                        "breach",
                        "contractor",
                        "legal fees",
                        "attorney fees",
                        "costs and fees",
                        "arbitration",
                        "binding",
                        "small claims",
                    ],
                    1,
                )
            )

        if is_insurance_query:
            keyword_sets.append(
                (
                    "insurance",
                    [
                        "liability insurance",
                        "additional insured",
                        "hold harmless",
                        "indemnify",
                        "indemnification",
                        "gross negligence",
                        "$300,000",
                        "300,000",
                        "300000",
                        "$25,000",
                        "25,000",
                        "25000",
                    ],
                    1,
                )
            )
        
        existing_ids = {c.chunk_id for c in graph_context.source_chunks}
        total_candidates = 0
        total_added = 0
        applied_profiles: List[str] = []
        
        for profile, keywords, min_matches in keyword_sets:
            boost_chunks = await self.pipeline.enhanced_retriever.get_keyword_boost_chunks(
                keywords=keywords,
                max_per_document=2,
                max_total=10,
                min_matches=min_matches,
            )
            total_candidates += len(boost_chunks)
            added = [c for c in boost_chunks if c.chunk_id not in existing_ids]
            if added:
                graph_context.source_chunks.extend(added)
                for c in added:
                    existing_ids.add(c.chunk_id)
                total_added += len(added)
            applied_profiles.append(profile)
        
        logger.info(
            "route_3_keyword_boost_applied",
            profiles=applied_profiles,
            boost_candidates=total_candidates,
            boost_added=total_added,
            total_source_chunks=len(graph_context.source_chunks),
        )

    # ==========================================================================
    # ENTITY RELEVANCE CHECK
    # ==========================================================================
    
    def _check_entity_relevance(
        self, query: str, hub_entities: List[str], graph_context, coverage_mode: bool
    ) -> bool:
        """Check if entities are relevant to query (for weak signals only)."""
        # Skip check if we have strong signal or coverage mode
        has_strong_signal = len(hub_entities) >= 3 or len(graph_context.relationships) >= 10
        
        if has_strong_signal or coverage_mode or graph_context.source_chunks:
            return True
        
        # Extract query terms
        stopwords = {
            "what", "when", "where", "which", "about", "does", "there", "their",
            "have", "this", "that", "with", "from", "they", "been", "were",
            "will", "would", "could", "should", "across", "list", "summarize"
        }
        query_terms = [
            w.lower() for w in re.findall(r"[A-Za-z]{4,}", query)
            if w.lower() not in stopwords
        ]
        
        if len(query_terms) < 2:
            return True
        
        # Check entity matches
        all_entities = hub_entities + graph_context.related_entities
        entity_text = " ".join(all_entities).lower()
        matching = [t for t in query_terms if t in entity_text]
        
        # Also check relationships
        rel_types = [r.relationship_type for r in graph_context.relationships]
        rel_text = " ".join(rel_types).lower()
        rel_matching = [t for t in query_terms if t in rel_text]
        
        total_matches = len(set(matching + rel_matching))
        
        if total_matches == 0:
            logger.info("entity_relevance_check_failed",
                       query_terms=query_terms[:5], num_entities=len(all_entities))
            return False
        
        return True

    # ==========================================================================
    # DOC LEAD BOOST (Cross-Document Queries)
    # ==========================================================================
    
    async def _apply_doc_lead_boost(self, query: str, graph_context) -> Dict[str, Any]:
        """Apply doc lead boost for cross-document queries.
        
        Cross-document lead boost: add one early chunk per document to improve
        thematic coverage for explicitly cross-document questions (invoices and
        short contracts often have weak entity graphs and can be missed otherwise).
        """
        enable = os.getenv("ROUTE3_DOC_LEAD_BOOST", "0").strip().lower() in {"1", "true", "yes"}
        
        ql_cross = (query or "").lower()
        is_cross_document_query = any(
            k in ql_cross
            for k in [
                "across the agreements",
                "across agreements",
                "across the documents",
                "across documents",
                "across the set",
                "across the contracts",
                "each document",
                "main purpose",
            ]
        )
        
        metadata: Dict[str, Any] = {
            "enabled": enable,
            "is_cross_document_query": is_cross_document_query,
            "applied": False,
        }
        
        if not enable or not is_cross_document_query:
            return metadata
        
        try:
            lead_chunks = await self.pipeline.enhanced_retriever.get_document_lead_chunks(
                max_total=10,  # Ensure all docs in typical groups are covered
                min_text_chars=20,
            )
            if lead_chunks:
                existing_ids = {c.chunk_id for c in graph_context.source_chunks}
                added = [c for c in lead_chunks if c.chunk_id not in existing_ids]
                if added:
                    graph_context.source_chunks.extend(added)
                    metadata["applied"] = True
                    metadata["candidates"] = len(lead_chunks)
                    metadata["added"] = len(added)
                    
                    logger.info(
                        "route_3_doc_lead_boost_applied",
                        candidates=len(lead_chunks),
                        added=len(added),
                        total_source_chunks=len(graph_context.source_chunks),
                    )
        except Exception as e:
            logger.warning("route_3_doc_lead_boost_failed", error=str(e))
        
        return metadata

    # ==========================================================================
    # COVERAGE GAP FILL
    # ==========================================================================
    
    async def _apply_coverage_gap_fill(self, query: str, graph_context) -> None:
        """Fill coverage gaps for cross-document queries."""
        try:
            # Get lead chunks from all documents
            fill_chunks = await self.pipeline.enhanced_retriever.get_document_lead_chunks(
                max_total=10,
                min_text_chars=20,
            )
            
            if not fill_chunks:
                return
            
            existing_ids = {c.chunk_id for c in graph_context.source_chunks}
            added = [c for c in fill_chunks if c.chunk_id not in existing_ids]
            
            if added:
                for c in added:
                    c.entity_name = "coverage_fill"
                graph_context.source_chunks.extend(added)
                logger.info("coverage_gap_fill_applied", added=len(added))
                           
        except Exception as e:
            logger.warning("coverage_gap_fill_failed", error=str(e))

    # ==========================================================================
    # SYNTHESIS
    # ==========================================================================
    
    async def _synthesize_global_response(
        self,
        query: str,
        graph_context,
        community_data: List[Dict],
        hub_entities: List[str],
        ppr_evidence: List,
        response_type: str,
    ) -> Dict[str, Any]:
        """Synthesize global response with theme coverage.
        
        Uses synthesize_with_graph_context() which expects:
        - evidence_nodes: List[Tuple[str, float]] - entity names with PPR scores
        - graph_context: EnhancedGraphContext with source_chunks for citations
        
        This matches the orchestrator's Route 3 implementation.
        """
        # ppr_evidence from tracer.trace() returns List[Tuple[str, float]]
        # Pass it directly to synthesize_with_graph_context
        synthesis_result = await self.pipeline.synthesizer.synthesize_with_graph_context(
            query=query,
            evidence_nodes=ppr_evidence,
            graph_context=graph_context,
            response_type=response_type,
        )
        
        return synthesis_result
