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
5. HippoRAG PPR for detail recovery
6. Coverage gap fill for cross-document queries

Features:
- Theme coverage metric for comprehensive responses
- Section-aware diversification

Note: Section Boost, SHARES_ENTITY expansion, Keyword Boost, and Doc Lead Boost
were removed 2026-01-24 after production benchmarks confirmed 100% theme coverage
without them. BM25 + Vector RRF retrieval is sufficient.
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
        
        # ================================================================
        # FAST MODE: Skip redundant stages for ~40-50% latency reduction
        # ================================================================
        # When enabled, makes PPR conditional on query characteristics.
        # Boost stages (Section, Keyword, Doc Lead) already removed.
        # Default: ON (set ROUTE3_FAST_MODE=0 to use full pipeline)
        fast_mode = os.getenv("ROUTE3_FAST_MODE", "1").strip().lower() in {"1", "true", "yes"}
        
        # Detect coverage intent
        from app.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
        coverage_mode = EnhancedGraphRetriever.detect_coverage_intent(query)
        
        logger.info(
            "route_3_global_search_start",
            query=query[:50],
            response_type=response_type,
            timings_enabled=enable_timings,
            coverage_mode=coverage_mode,
            fast_mode=fast_mode,
        )
        
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
                   num_relationships=len(graph_context.relationships),
                   num_related_entities=len(graph_context.related_entities))
        
        # Stage 3.3.5: Cypher 25 Hybrid RRF (BM25 + Vector)
        t0 = time.perf_counter()
        await self._apply_hybrid_rrf_stage(query, graph_context)
        timings_ms["stage_3.3.5_ms"] = int((time.perf_counter() - t0) * 1000)
        
        # ==================================================================
        # REMOVED: Boost Stages (Section, SHARES_ENTITY, Keyword, Doc Lead)
        # ==================================================================
        # These boost stages were removed 2026-01-24 after production benchmarks
        # confirmed 100% theme coverage WITHOUT them. See orchestrator.py for details.
        # BM25 + Vector RRF retrieval + Coverage Gap Fill is sufficient.
        # ==================================================================
        
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
        
        # Stage 3.4: HippoRAG PPR Tracing (DETAIL RECOVERY)
        # Fast Mode: PPR is conditional - skip for simple thematic queries, keep for relationship queries
        env_disable_ppr = os.getenv("ROUTE3_DISABLE_PPR", "0").strip().lower() in {"1", "true", "yes"}
        
        # In fast mode, only enable PPR if query has relationship indicators
        fast_mode_ppr_skip = False
        if fast_mode and not env_disable_ppr:
            relationship_keywords = [
                "connected", "through", "linked", "related to", 
                "associated with", "path", "chain", "relationship",
                "between", "across"
            ]
            ql = query.lower()
            has_relationship_intent = any(kw in ql for kw in relationship_keywords)
            # Also check for proper nouns (entity mentions)
            words = query.split()
            has_explicit_entity = sum(1 for w in words[1:] if len(w) > 1 and w[0].isupper()) >= 2
            
            fast_mode_ppr_skip = not (has_relationship_intent or has_explicit_entity)
        
        disable_ppr = env_disable_ppr or fast_mode_ppr_skip
        all_seed_entities = list(set(hub_entities + graph_context.related_entities[:10]))
        
        t0 = time.perf_counter()
        if disable_ppr:
            skip_reason = "ROUTE3_DISABLE_PPR" if env_disable_ppr else "fast_mode_simple_query"
            logger.info(
                "stage_3.4_hipporag_ppr_skipped",
                reason=skip_reason,
                seeds=len(all_seed_entities),
                fast_mode=fast_mode,
            )
            # Minimal deterministic fallback: keep seeds as evidence with uniform score
            evidence_nodes = [(e, 1.0) for e in all_seed_entities[:20]]
        else:
            logger.info("stage_3.4_hipporag_ppr_tracing")
            evidence_nodes = []
            if all_seed_entities:
                evidence_nodes = await self.pipeline.tracer.trace(
                    query=query,
                    seed_entities=all_seed_entities,
                    top_k=20  # Larger for global coverage
                )
            logger.info("stage_3.4_complete", num_evidence=len(evidence_nodes))
        timings_ms["stage_3.4_ms"] = int((time.perf_counter() - t0) * 1000)
        
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
            ppr_evidence=evidence_nodes,
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
