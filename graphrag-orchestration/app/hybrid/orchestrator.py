"""
Hybrid Pipeline Orchestrator

Coordinates the 3-stage pipeline:
1. Intent Disambiguation (LazyGraphRAG)
2. Deterministic Tracing (HippoRAG 2)
3. Evidence Synthesis (LazyGraphRAG)

This is the main entry point for the Hybrid Architecture.
"""

from typing import Dict, Any, Optional
import structlog

from .pipeline.intent import IntentDisambiguator
from .pipeline.tracing import DeterministicTracer
from .pipeline.synthesis import EvidenceSynthesizer
from .router.main import HybridRouter, QueryRoute, DeploymentProfile

logger = structlog.get_logger(__name__)


class HybridPipeline:
    """
    The main orchestrator for the LazyGraphRAG + HippoRAG 2 hybrid system.
    
    Usage:
        pipeline = HybridPipeline(
            profile=DeploymentProfile.HIGH_ASSURANCE_AUDIT,
            llm_client=llm,
            hipporag_instance=hrag,
            ...
        )
        result = await pipeline.query("What is our exposure to vendor X?")
    """
    
    def __init__(
        self,
        profile: DeploymentProfile = DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=None,
        hipporag_instance=None,
        graph_store=None,
        text_unit_store=None,
        vector_rag_client=None,
        graph_communities: Optional[list] = None,
        relevance_budget: float = 0.8
    ):
        """
        Initialize the hybrid pipeline.
        
        Args:
            profile: Deployment profile (General Enterprise or High-Assurance).
            llm_client: LLM client for query processing and synthesis.
            hipporag_instance: Initialized HippoRAG instance for tracing.
            graph_store: Graph database connection (Neo4j).
            text_unit_store: Store for raw text chunks.
            vector_rag_client: Client for Vector RAG (Profile A only).
            graph_communities: Community summaries for disambiguation.
            relevance_budget: 0.0-1.0, controls thoroughness vs speed.
        """
        self.profile = profile
        self.llm = llm_client
        self.relevance_budget = relevance_budget
        
        # Initialize components
        self.router = HybridRouter(
            profile=profile,
            llm_client=llm_client
        )
        
        self.disambiguator = IntentDisambiguator(
            llm_client=llm_client,
            graph_communities=graph_communities
        )
        
        self.tracer = DeterministicTracer(
            hipporag_instance=hipporag_instance,
            graph_store=graph_store
        )
        
        self.synthesizer = EvidenceSynthesizer(
            llm_client=llm_client,
            text_unit_store=text_unit_store,
            relevance_budget=relevance_budget
        )
        
        self.vector_rag = vector_rag_client
        
        logger.info("hybrid_pipeline_initialized",
                   profile=profile.value,
                   relevance_budget=relevance_budget,
                   has_hipporag=hipporag_instance is not None,
                   has_vector_rag=vector_rag_client is not None)
    
    async def query(
        self,
        query: str,
        response_type: str = "detailed_report"
    ) -> Dict[str, Any]:
        """
        Execute a query through the hybrid pipeline.
        
        Args:
            query: The user's natural language query.
            response_type: "detailed_report" | "summary" | "audit_trail"
            
        Returns:
            Dictionary containing:
            - response: The generated answer.
            - route_used: Which route was taken.
            - citations: Source citations (if hybrid route).
            - evidence_path: Entity path (if hybrid route).
            - metadata: Additional execution metadata.
        """
        # Step 0: Route the query
        route = await self.router.route(query)
        
        if route == QueryRoute.VECTOR_RAG:
            return await self._execute_vector_rag(query)
        else:
            return await self._execute_hybrid_pipeline(query, response_type)
    
    async def _execute_vector_rag(self, query: str) -> Dict[str, Any]:
        """Execute simple Vector RAG for fast queries."""
        logger.info("executing_vector_rag", query=query[:50])
        
        if not self.vector_rag:
            logger.warning("vector_rag_not_configured_fallback_to_hybrid")
            return await self._execute_hybrid_pipeline(query, "summary")
        
        try:
            result = await self.vector_rag.aquery(query)
            
            return {
                "response": result.response if hasattr(result, 'response') else str(result),
                "route_used": "vector_rag",
                "citations": [],
                "evidence_path": [],
                "metadata": {
                    "latency_estimate": "fast",
                    "precision_level": "standard"
                }
            }
        except Exception as e:
            logger.error("vector_rag_failed", error=str(e))
            # Fallback to hybrid
            return await self._execute_hybrid_pipeline(query, "summary")
    
    async def _execute_hybrid_pipeline(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Execute the full 3-stage hybrid pipeline.
        
        Stage 1: Disambiguate → Seed Entities
        Stage 2: Trace → Evidence Nodes
        Stage 3: Synthesize → Response with Citations
        """
        logger.info("executing_hybrid_pipeline", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 1: Intent Disambiguation
        logger.info("stage_1_disambiguation_start")
        seed_entities = await self.disambiguator.disambiguate(query)
        logger.info("stage_1_disambiguation_complete", 
                   num_seeds=len(seed_entities))
        
        # Stage 2: Deterministic Tracing
        logger.info("stage_2_tracing_start")
        evidence_nodes = await self.tracer.trace(
            query=query,
            seed_entities=seed_entities,
            top_k=15
        )
        logger.info("stage_2_tracing_complete",
                   num_evidence_nodes=len(evidence_nodes))
        
        # Stage 3: Evidence Synthesis
        logger.info("stage_3_synthesis_start")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type
        )
        logger.info("stage_3_synthesis_complete")
        
        return {
            "response": synthesis_result["response"],
            "route_used": "hybrid_pipeline",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "seed_entities": seed_entities,
                "num_evidence_nodes": len(evidence_nodes),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "thorough",
                "precision_level": "high_assurance",
                "response_type": response_type
            }
        }
    
    async def query_with_audit_trail(self, query: str) -> Dict[str, Any]:
        """
        Convenience method for audit-focused queries.
        Forces audit_trail response type.
        """
        return await self.query(query, response_type="audit_trail")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check the health of all pipeline components."""
        status = {
            "router": "ok",
            "disambiguator": "ok" if self.llm else "no_llm",
            "tracer": "ok" if self.tracer._use_hipporag else "fallback_mode",
            "synthesizer": "ok" if self.llm else "no_llm",
            "vector_rag": "ok" if self.vector_rag else "not_configured",
            "profile": self.profile.value
        }
        
        return status
