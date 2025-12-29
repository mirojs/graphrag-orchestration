"""
Hybrid Pipeline Orchestrator

Coordinates 4 distinct query routes:
1. Vector RAG - Fast lane for simple fact lookups
2. Local Search Equivalent - Entity-focused with LazyGraphRAG iterative deepening
3. Global Search Equivalent - Thematic queries with LazyGraphRAG + HippoRAG 2 PPR
4. DRIFT Equivalent - Multi-hop iterative reasoning for ambiguous queries

This is the main entry point for the Hybrid Architecture.

Profiles:
=========
- General Enterprise: All 4 routes (Route 1 default for simple queries)
- High Assurance: Routes 2, 3, 4 only (no Vector RAG shortcuts)

Model Selection by Route:
========================
Route 1 (Vector RAG):
  - Embeddings: text-embedding-3-large

Route 2 (Local Search):
  - Entity Extraction: NER or embedding match (deterministic)
  - LazyGraphRAG Iterative Deepening
  - Answer Synthesis: HYBRID_SYNTHESIS_MODEL (gpt-4o)

Route 3 (Global Search):
  - Community Matching: Embedding similarity (deterministic)
  - Hub Entity Extraction: Graph topology (deterministic)
  - HippoRAG PPR: Algorithmic (deterministic)
  - Answer Synthesis: HYBRID_SYNTHESIS_MODEL (gpt-5.2)

Route 4 (DRIFT Multi-Hop):
  - Query Decomposition: HYBRID_DECOMPOSITION_MODEL (gpt-4.1)
  - Entity Resolution: HYBRID_NER_MODEL (gpt-4o)
  - HippoRAG PPR: Algorithmic (deterministic)
  - Final Consolidation: HYBRID_SYNTHESIS_MODEL (gpt-5.2)

Router (all routes):
  - Query Classification: HYBRID_ROUTER_MODEL (gpt-4o-mini)
"""

from typing import Dict, Any, Optional, List
import structlog

from .pipeline.intent import IntentDisambiguator
from .pipeline.tracing import DeterministicTracer
from .pipeline.synthesis import EvidenceSynthesizer
from .pipeline.community_matcher import CommunityMatcher
from .pipeline.hub_extractor import HubExtractor
from .router.main import HybridRouter, QueryRoute, DeploymentProfile

logger = structlog.get_logger(__name__)


class HybridPipeline:
    """
    The main orchestrator for the 4-way routing system.
    
    Routes:
        1. Vector RAG - Simple fact lookups (General Enterprise only)
        2. Local Search - Entity-focused with LazyGraphRAG
        3. Global Search - Thematic with LazyGraphRAG + HippoRAG 2
        4. DRIFT Multi-Hop - Ambiguous queries with iterative decomposition
    
    Usage:
        pipeline = HybridPipeline(
            profile=DeploymentProfile.HIGH_ASSURANCE,
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
        embedding_client=None,
        hipporag_instance=None,
        graph_store=None,
        neo4j_driver=None,
        text_unit_store=None,
        vector_rag_client=None,
        graph_communities: Optional[list] = None,
        communities_path: Optional[str] = None,
        relevance_budget: float = 0.8,
        group_id: str = "default"
    ):
        """
        Initialize the hybrid pipeline.
        
        Args:
            profile: Deployment profile (General Enterprise or High Assurance).
            llm_client: LLM client for query processing and synthesis.
            embedding_client: Embedding client for community matching.
            hipporag_instance: Initialized HippoRAG instance for tracing.
            graph_store: Graph database connection (Neo4j).
            neo4j_driver: Neo4j async driver for direct queries.
            text_unit_store: Store for raw text chunks.
            vector_rag_client: Client for Vector RAG (Route 1).
            graph_communities: Community summaries for disambiguation.
            communities_path: Path to community data file.
            relevance_budget: 0.0-1.0, controls thoroughness vs speed.
            group_id: Tenant identifier.
        """
        self.profile = profile
        self.llm = llm_client
        self.relevance_budget = relevance_budget
        self.graph_communities = graph_communities
        self.group_id = group_id
        
        # Initialize components
        self.router = HybridRouter(
            profile=profile,
            llm_client=llm_client
        )
        
        # Route 2: Entity disambiguation (for explicit entity queries)
        self.disambiguator = IntentDisambiguator(
            llm_client=llm_client,
            graph_communities=graph_communities
        )
        
        # Route 3: Community matching (for thematic queries)
        self.community_matcher = CommunityMatcher(
            embedding_client=embedding_client,
            communities_path=communities_path,
            group_id=group_id
        )
        
        # Route 3: Hub extraction (for seeding HippoRAG)
        self.hub_extractor = HubExtractor(
            graph_store=graph_store,
            neo4j_driver=neo4j_driver
        )
        
        # Routes 3 & 4: Deterministic tracing
        self.tracer = DeterministicTracer(
            hipporag_instance=hipporag_instance,
            graph_store=graph_store
        )
        
        # All routes: Synthesis
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
                   has_vector_rag=vector_rag_client is not None,
                   has_community_matcher=embedding_client is not None,
                   group_id=group_id)
    
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
            - citations: Source citations (if Routes 2/3/4).
            - evidence_path: Entity path (if Routes 2/3/4).
            - metadata: Additional execution metadata.
        """
        # Step 0: Route the query
        route = await self.router.route(query)
        
        if route == QueryRoute.VECTOR_RAG:
            return await self._execute_route_1_vector_rag(query)
        elif route == QueryRoute.LOCAL_SEARCH:
            return await self._execute_route_2_local_search(query, response_type)
        elif route == QueryRoute.GLOBAL_SEARCH:
            return await self._execute_route_3_global_search(query, response_type)
        else:  # DRIFT_MULTI_HOP
            return await self._execute_route_4_drift(query, response_type)
    
    # =========================================================================
    # Route 1: Vector RAG (Fast Lane)
    # =========================================================================
    
    async def _execute_route_1_vector_rag(self, query: str) -> Dict[str, Any]:
        """
        Route 1: Simple Vector RAG for fast fact lookups.
        
        Best for: "What is X's address?", "How much is invoice Y?"
        Profile: General Enterprise only (disabled in High Assurance)
        """
        logger.info("route_1_vector_rag_start", query=query[:50])
        
        if not self.vector_rag:
            logger.warning("vector_rag_not_configured_fallback_to_route_2")
            return await self._execute_route_2_local_search(query, "summary")
        
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
            return await self._execute_route_2_local_search(query, "summary")
    
    # =========================================================================
    # Route 2: Local Search Equivalent (LazyGraphRAG Only)
    # =========================================================================
    
    async def _execute_route_2_local_search(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 2: LazyGraphRAG for entity-focused queries.
        
        Best for: "List all contracts with ABC Corp", "What are X's payment terms?"
        
        Stage 2.1: Extract explicit entities (NER / embedding match)
        Stage 2.2: LazyGraphRAG iterative deepening
        Stage 2.3: Synthesis with citations
        
        Note: No HippoRAG in this route - entities are explicit.
        """
        logger.info("route_2_local_search_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 2.1: Entity Extraction (explicit entities)
        logger.info("stage_2.1_entity_extraction")
        seed_entities = await self.disambiguator.disambiguate(query)
        logger.info("stage_2.1_complete", num_seeds=len(seed_entities))
        
        # Stage 2.2: LazyGraphRAG Iterative Deepening
        # For now, we use the tracer as a simplified exploration
        # TODO: Replace with true LazyGraphRAG iterative deepening
        logger.info("stage_2.2_iterative_deepening")
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
            "route_used": "route_2_local_search",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "seed_entities": seed_entities,
                "num_evidence_nodes": len(evidence_nodes),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "moderate",
                "precision_level": "high",
                "route_description": "Entity-focused with LazyGraphRAG iterative deepening"
            }
        }
    
    # =========================================================================
    # Route 3: Global Search Equivalent (LazyGraphRAG + HippoRAG PPR)
    # =========================================================================
    
    async def _execute_route_3_global_search(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 3: LazyGraphRAG + HippoRAG for thematic queries.
        
        Best for: "What are the main compliance risks?", "Summarize key themes"
        
        Stage 3.1: Community matching (LazyGraphRAG)
        Stage 3.2: Hub entity extraction (deterministic)
        Stage 3.3: HippoRAG PPR tracing (detail recovery)
        Stage 3.4: Raw text chunk fetching
        Stage 3.5: Synthesis with citations
        """
        logger.info("route_3_global_search_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 3.1: Community Matching
        logger.info("stage_3.1_community_matching")
        matched_communities = await self.community_matcher.match_communities(query, top_k=3)
        community_data = [c for c, _ in matched_communities]
        logger.info("stage_3.1_complete", num_communities=len(community_data))
        
        # Stage 3.2: Hub Entity Extraction
        logger.info("stage_3.2_hub_extraction")
        hub_entities = await self.hub_extractor.extract_hub_entities(
            communities=community_data,
            top_k_per_community=3
        )
        logger.info("stage_3.2_complete", num_hubs=len(hub_entities))
        
        # Stage 3.3: HippoRAG PPR Tracing (DETAIL RECOVERY)
        logger.info("stage_3.3_hipporag_ppr_tracing")
        evidence_nodes = await self.tracer.trace(
            query=query,
            seed_entities=hub_entities,
            top_k=20  # Larger for global coverage
        )
        logger.info("stage_3.3_complete", num_evidence=len(evidence_nodes))
        
        # Stage 3.4 & 3.5: Synthesis with Citations
        logger.info("stage_3.4_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type
        )
        logger.info("stage_3.4_complete")
        
        return {
            "response": synthesis_result["response"],
            "route_used": "route_3_global_search",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "matched_communities": [c.get("title", "?") for c in community_data],
                "hub_entities": hub_entities,
                "num_evidence_nodes": len(evidence_nodes),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "thorough",
                "precision_level": "high",
                "route_description": "Thematic with community matching + HippoRAG PPR detail recovery"
            }
        }
    
    # =========================================================================
    # Route 4: DRIFT Equivalent (Multi-Hop Iterative Reasoning)
    # =========================================================================
    
    async def _execute_route_4_drift(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 4: DRIFT-style iterative reasoning for ambiguous queries.
        
        Best for: "Analyze risk exposure", "How are we connected through subsidiaries?"
        
        Stage 4.1: Query decomposition (DRIFT-style)
        Stage 4.2: Iterative entity discovery
        Stage 4.3: Consolidated HippoRAG tracing
        Stage 4.4: Multi-source synthesis
        """
        logger.info("route_4_drift_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 4.1: Query Decomposition
        logger.info("stage_4.1_query_decomposition")
        sub_questions = await self._drift_decompose(query)
        logger.info("stage_4.1_complete", num_sub_questions=len(sub_questions))
        
        # Stage 4.2: Iterative Entity Discovery
        logger.info("stage_4.2_iterative_discovery")
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
        logger.info("stage_4.2_complete", 
                   total_unique_seeds=len(all_seeds),
                   sub_question_results=len(intermediate_results))
        
        # Stage 4.3: Consolidated Tracing
        logger.info("stage_4.3_consolidated_tracing")
        complete_evidence = await self.tracer.trace(
            query=query,
            seed_entities=all_seeds,
            top_k=30  # More nodes for comprehensive coverage
        )
        logger.info("stage_4.3_complete", num_evidence=len(complete_evidence))
        
        # Stage 4.4: Multi-Source Synthesis
        logger.info("stage_4.4_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=complete_evidence,
            response_type=response_type,
            sub_questions=sub_questions,
            intermediate_context=intermediate_results
        )
        logger.info("stage_4.4_complete")
        
        return {
            "response": synthesis_result["response"],
            "route_used": "route_4_drift_multi_hop",
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
                "route_description": "DRIFT-style iterative multi-hop reasoning with HippoRAG PPR"
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
        elif route == QueryRoute.LOCAL_SEARCH:
            return await self._execute_route_2_local_search(query, response_type)
        elif route == QueryRoute.GLOBAL_SEARCH:
            return await self._execute_route_3_global_search(query, response_type)
        else:  # DRIFT_MULTI_HOP
            return await self._execute_route_4_drift(query, response_type)
    
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
                "route_2_local_search": True,
                "route_3_global_search": True,
                "route_4_drift": self.llm is not None
            }
        }
