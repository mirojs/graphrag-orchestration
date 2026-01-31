"""Route 2: Local Search - Entity-focused retrieval with LazyGraphRAG.

Best for queries that explicitly mention entities:
- "List all contracts with ABC Corp"
- "What are X's payment terms?"
- "Show me invoices from Contoso"

This route uses:
1. Entity extraction (NER / embedding match) to identify seed entities
2. LazyGraphRAG iterative deepening to expand context
3. Evidence synthesis with citations

Note: No HippoRAG in this route - entities are explicit in the query.
"""

from typing import Dict, Any

import structlog

from .base import BaseRouteHandler, RouteResult, Citation

logger = structlog.get_logger(__name__)


class LocalSearchHandler(BaseRouteHandler):
    """Route 2: Entity-focused search with LazyGraphRAG iterative deepening."""

    ROUTE_NAME = "route_2_local_search"

    async def execute(
        self,
        query: str,
        response_type: str = "summary"
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
        
        # Stage 2.3: Synthesis with Citations
        logger.info("stage_2.3_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type
        )
        logger.info("stage_2.3_complete")
        
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
                citations.append(Citation(
                    index=i,
                    chunk_id=c.get("chunk_id", f"chunk_{i}"),
                    document_id=c.get("document_id", ""),
                    document_title=c.get("document_title", c.get("document", "Unknown")),
                    score=c.get("score", 0.0),
                    text_preview=c.get("text_preview", c.get("text", ""))[:200],
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
                "route_description": "Entity-focused with LazyGraphRAG iterative deepening"
            }
        )
