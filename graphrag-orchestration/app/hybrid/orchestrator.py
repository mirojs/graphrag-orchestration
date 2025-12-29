"""
Hybrid Pipeline Orchestrator

Coordinates 3 distinct query routes:
1. Vector RAG - Fast lane for simple fact lookups
2. Local/Global Equivalent - Entity-focused with LazyGraphRAG + HippoRAG 2
3. DRIFT Equivalent - Multi-hop iterative reasoning for ambiguous queries

This is the main entry point for the Hybrid Architecture.
"""

from typing import Dict, Any, Optional, List
import structlog

from .pipeline.intent import IntentDisambiguator
from .pipeline.tracing import DeterministicTracer
from .pipeline.synthesis import EvidenceSynthesizer
from .router.main import HybridRouter, QueryRoute, DeploymentProfile

logger = structlog.get_logger(__name__)


class HybridPipeline:
    """
    The main orchestrator for the 3-way routing system.
    
    Routes:
        1. Vector RAG - Simple fact lookups
        2. Local/Global - Entity-focused with HippoRAG 2
        3. DRIFT Multi-Hop - Ambiguous queries with iterative decomposition
    
    Usage:
        pipeline = HybridPipeline(
            profile=DeploymentProfile.HIGH_ASSURANCE_AUDIT,
            llm_client=llm,
            hipporag_instance=hrag,
            ...
        )
        result = await pipeline.query("Analyze our risk exposure to tech vendors")
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
            profile: Deployment profile (General Enterprise, High-Assurance, Speed-Critical).
            llm_client: LLM client for query processing and synthesis.
            hipporag_instance: Initialized HippoRAG instance for tracing.
            graph_store: Graph database connection (Neo4j).
            text_unit_store: Store for raw text chunks.
            vector_rag_client: Client for Vector RAG (Route 1).
            graph_communities: Community summaries for disambiguation.
            relevance_budget: 0.0-1.0, controls thoroughness vs speed.
        """
        self.profile = profile
        self.llm = llm_client
        self.relevance_budget = relevance_budget
        self.graph_communities = graph_communities
        
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
        Execute a query through the appropriate route.
        
        Args:
            query: The user's natural language query.
            response_type: "detailed_report" | "summary" | "audit_trail"
            
        Returns:
            Dictionary containing:
            - response: The generated answer.
            - route_used: Which route was taken.
            - citations: Source citations (if Routes 2/3).
            - evidence_path: Entity path (if Routes 2/3).
            - metadata: Additional execution metadata.
        """
        # Step 0: Route the query
        route = await self.router.route(query)
        
        if route == QueryRoute.VECTOR_RAG:
            return await self._execute_route_1_vector_rag(query)
        elif route == QueryRoute.LOCAL_GLOBAL:
            return await self._execute_route_2_local_global(query, response_type)
        else:  # DRIFT_MULTI_HOP
            return await self._execute_route_3_drift(query, response_type)
    
    # =========================================================================
    # Route 1: Vector RAG (Fast Lane)
    # =========================================================================
    
    async def _execute_route_1_vector_rag(self, query: str) -> Dict[str, Any]:
        """
        Route 1: Simple Vector RAG for fast fact lookups.
        
        Best for: "What is X's address?", "How much is invoice Y?"
        """
        logger.info("route_1_vector_rag_start", query=query[:50])
        
        if not self.vector_rag:
            logger.warning("vector_rag_not_configured_fallback_to_route_2")
            return await self._execute_route_2_local_global(query, "summary")
        
        try:
            result = await self.vector_rag.aquery(query)
            
            return {
                "response": result.response if hasattr(result, 'response') else str(result),
                "route_used": "route_1_vector_rag",
                "citations": [],
                "evidence_path": [],
                "metadata": {
                    "latency_estimate": "fast",
                    "precision_level": "standard",
                    "route_description": "Simple embedding-based retrieval"
                }
            }
        except Exception as e:
            logger.error("route_1_failed_fallback", error=str(e))
            return await self._execute_route_2_local_global(query, "summary")
    
    # =========================================================================
    # Route 2: Local/Global Equivalent (Entity-Focused Hybrid)
    # =========================================================================
    
    async def _execute_route_2_local_global(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 2: LazyGraphRAG + HippoRAG 2 for entity-focused queries.
        
        Best for: "List all contracts with ABC Corp", "What are X's payment terms?"
        
        Stage 2.1: Identify seed entities
        Stage 2.2: HippoRAG PPR tracing
        Stage 2.3: LazyGraphRAG synthesis with citations
        """
        logger.info("route_2_local_global_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 2.1: Seed Identification
        logger.info("stage_2.1_seed_identification")
        seed_entities = await self.disambiguator.disambiguate(query)
        logger.info("stage_2.1_complete", num_seeds=len(seed_entities))
        
        # Stage 2.2: Deterministic Tracing (HippoRAG PPR)
        logger.info("stage_2.2_hipporag_tracing")
        evidence_nodes = await self.tracer.trace(
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
        
        return {
            "response": synthesis_result["response"],
            "route_used": "route_2_local_global",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "seed_entities": seed_entities,
                "num_evidence_nodes": len(evidence_nodes),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "moderate",
                "precision_level": "high",
                "route_description": "Entity-focused with HippoRAG PPR"
            }
        }
    
    # =========================================================================
    # Route 3: DRIFT Equivalent (Multi-Hop Iterative Reasoning)
    # =========================================================================
    
    async def _execute_route_3_drift(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 3: DRIFT-style iterative reasoning for ambiguous queries.
        
        Best for: "Analyze risk exposure", "How are we connected through subsidiaries?"
        
        Stage 3.1: Query decomposition (DRIFT-style)
        Stage 3.2: Iterative entity discovery
        Stage 3.3: Consolidated HippoRAG tracing
        Stage 3.4: Multi-source synthesis
        """
        logger.info("route_3_drift_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 3.1: Query Decomposition
        logger.info("stage_3.1_query_decomposition")
        sub_questions = await self._drift_decompose(query)
        logger.info("stage_3.1_complete", num_sub_questions=len(sub_questions))
        
        # Stage 3.2: Iterative Entity Discovery
        logger.info("stage_3.2_iterative_discovery")
        all_seeds: List[str] = []
        intermediate_results: List[Dict[str, Any]] = []
        
        for i, sub_q in enumerate(sub_questions):
            logger.info(f"processing_sub_question_{i+1}", question=sub_q[:50])
            
            # Get entities for this sub-question
            sub_entities = await self.disambiguator.disambiguate(sub_q)
            all_seeds.extend(sub_entities)
            
            # Optional: Run partial search for context building
            if len(sub_entities) > 0:
                partial_evidence = await self.tracer.trace(
                    query=sub_q,
                    seed_entities=sub_entities,
                    top_k=5  # Smaller for sub-questions
                )
                intermediate_results.append({
                    "question": sub_q,
                    "entities": sub_entities,
                    "evidence_count": len(partial_evidence)
                })
        
        # Deduplicate seeds
        all_seeds = list(set(all_seeds))
        logger.info("stage_3.2_complete", 
                   total_unique_seeds=len(all_seeds),
                   sub_question_results=len(intermediate_results))
        
        # Stage 3.3: Consolidated Tracing
        logger.info("stage_3.3_consolidated_tracing")
        complete_evidence = await self.tracer.trace(
            query=query,
            seed_entities=all_seeds,
            top_k=30  # More nodes for comprehensive coverage
        )
        logger.info("stage_3.3_complete", num_evidence=len(complete_evidence))
        
        # Stage 3.4: Multi-Source Synthesis
        logger.info("stage_3.4_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=complete_evidence,
            response_type=response_type,
            sub_questions=sub_questions,
            intermediate_context=intermediate_results
        )
        logger.info("stage_3.4_complete")
        
        return {
            "response": synthesis_result["response"],
            "route_used": "route_3_drift_multi_hop",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "sub_questions": sub_questions,
                "all_seeds_discovered": all_seeds,
                "intermediate_results": intermediate_results,
                "num_evidence_nodes": len(complete_evidence),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "thorough",
                "precision_level": "maximum",
                "route_description": "DRIFT-style iterative multi-hop reasoning"
            }
        }
    
    async def _drift_decompose(self, query: str) -> List[str]:
        """
        Decompose an ambiguous query into concrete sub-questions.
        
        Uses DRIFT-style prompting to break down vague queries.
        """
        if not self.llm:
            # Fallback: treat as single question
            return [query]
        
        prompt = f"""Break down this complex query into specific, answerable sub-questions.

Original Query: "{query}"

Guidelines:
- Each sub-question should focus on identifying specific entities or relationships
- Questions should build on each other (entity discovery → relationship exploration → analysis)
- Generate 2-5 sub-questions depending on complexity

Format your response as a numbered list:
1. [First sub-question]
2. [Second sub-question]
...

Sub-questions:"""

        try:
            response = await self.llm.acomplete(prompt)
            text = response.text.strip()
            
            # Parse numbered list
            lines = text.split('\n')
            sub_questions = []
            for line in lines:
                line = line.strip()
                if line and line[0].isdigit():
                    # Remove numbering (e.g., "1. " or "1) ")
                    content = line.split('.', 1)[-1].strip()
                    content = content.split(')', 1)[-1].strip()
                    if content:
                        sub_questions.append(content)
            
            return sub_questions if sub_questions else [query]
            
        except Exception as e:
            logger.warning("drift_decompose_failed", error=str(e))
            return [query]
    
    # =========================================================================
    # Convenience Methods
    # =========================================================================
    
    async def query_with_audit_trail(self, query: str) -> Dict[str, Any]:
        """
        Convenience method for audit-focused queries.
        Forces audit_trail response type and uses Route 2 or 3.
        """
        return await self.query(query, response_type="audit_trail")
    
    async def force_route(
        self,
        query: str,
        route: QueryRoute,
        response_type: str = "detailed_report"
    ) -> Dict[str, Any]:
        """
        Force a specific route regardless of classification.
        
        Useful for testing or when you know the query type.
        """
        if route == QueryRoute.VECTOR_RAG:
            return await self._execute_route_1_vector_rag(query)
        elif route == QueryRoute.LOCAL_GLOBAL:
            return await self._execute_route_2_local_global(query, response_type)
        else:
            return await self._execute_route_3_drift(query, response_type)
    
    async def health_check(self) -> Dict[str, Any]:
        """Check the health of all pipeline components."""
        return {
            "router": "ok",
            "disambiguator": "ok" if self.llm else "no_llm",
            "tracer": "ok" if self.tracer._use_hipporag else "fallback_mode",
            "synthesizer": "ok" if self.llm else "no_llm",
            "vector_rag": "ok" if self.vector_rag else "not_configured",
            "profile": self.profile.value,
            "routes_available": {
                "route_1_vector_rag": self.vector_rag is not None,
                "route_2_local_global": True,
                "route_3_drift": self.llm is not None
            }
        }
