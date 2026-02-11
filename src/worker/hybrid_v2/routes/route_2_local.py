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
        """Check if V2 Voyage mode is enabled."""
        return settings.VOYAGE_V2_ENABLED and bool(settings.VOYAGE_API_KEY)

    async def _get_query_embedding(self, query: str):
        """Get query embedding using V2 Voyage or V1 OpenAI based on config."""
        if self._is_v2_enabled():
            voyage_service = _get_voyage_service()
            if voyage_service:
                logger.info("route_2_using_voyage_embeddings")
                return voyage_service.embed_query(query)
        
        # Fallback to V1 OpenAI embeddings via pipeline
        if hasattr(self.pipeline, 'embed_model') and self.pipeline.embed_model:
            return await self.pipeline.embed_model.aget_query_embedding(query)
        
        return None

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
        logger.info("route_2_local_search_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 2.1: Entity Extraction (explicit entities)
        logger.info("stage_2.1_entity_extraction")
        seed_entities = await self.pipeline.disambiguator.disambiguate(query)
        logger.info("stage_2.1_complete", num_seeds=len(seed_entities))
        
        # Stage 2.2: LazyGraphRAG Iterative Deepening
        logger.info("stage_2.2_iterative_deepening")
        evidence_nodes = await self.pipeline.tracer.trace(
            query=query,
            seed_entities=seed_entities,
            top_k=15
        )
        logger.info("stage_2.2_complete", num_evidence=len(evidence_nodes))
        
        # Stage 2.2.5: Fetch language spans for sentence-level citations
        enable_sentence_citations = os.getenv("ROUTE2_SENTENCE_CITATIONS", "1").strip().lower() in {"1", "true", "yes"}
        doc_language_spans: Dict[str, List[Dict]] = {}
        if enable_sentence_citations:
            # Retrieve text chunks first to get document IDs
            # _retrieve_text_chunks returns (deduped_chunks, entity_scores, retrieval_stats) tuple after de-noising changes
            pre_chunks, _entity_scores, _retrieval_stats = await self.synthesizer._retrieve_text_chunks(evidence_nodes, query=query)
            doc_ids = list({c.get("metadata", {}).get("document_id", "") for c in pre_chunks} - {""})
            if doc_ids:
                doc_language_spans = await self._fetch_language_spans(doc_ids)
                logger.info("stage_2.2.5_sentence_spans", num_docs=len(doc_ids), docs_with_spans=len(doc_language_spans))

        # Stage 2.2.6: Skeleton sentence enrichment (Strategy A).
        # Query sentence vector index for top-k matches, format as supplementary
        # evidence chunks for injection into the synthesis prompt.
        skeleton_coverage_chunks: List[Dict[str, Any]] = []
        if settings.SKELETON_ENRICHMENT_ENABLED and settings.VOYAGE_V2_ENABLED:
            try:
                skeleton_coverage_chunks = await self._retrieve_skeleton_sentences(query)
                if skeleton_coverage_chunks:
                    logger.info(
                        "stage_2.2.6_skeleton_enrichment",
                        sentences=len(skeleton_coverage_chunks),
                    )
            except Exception as e:
                logger.warning("skeleton_enrichment_failed", error=str(e))

        # Stage 2.3: Synthesis with Citations
        logger.info("stage_2.3_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type,
            prompt_variant=prompt_variant,
            synthesis_model=synthesis_model,
            include_context=include_context,
            language_spans_by_doc=doc_language_spans if doc_language_spans else None,
            pre_fetched_chunks=pre_chunks if enable_sentence_citations else None,
            coverage_chunks=skeleton_coverage_chunks if skeleton_coverage_chunks else None,
        )
        logger.info("stage_2.3_complete")
        
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
                    "negative_detection": True
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