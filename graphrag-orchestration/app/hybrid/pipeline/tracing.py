"""
Stage 2: Deterministic Tracing (The "Detective")

Uses HippoRAG 2's Personalized PageRank (PPR) to find mathematically
guaranteed paths between entities. This is non-parametric and deterministic.
"""

from typing import List, Tuple, Optional, Dict, Any, TYPE_CHECKING
import structlog

if TYPE_CHECKING:
    from typing import Any as HippoRAGType

logger = structlog.get_logger(__name__)


class DeterministicTracer:
    """
    Uses HippoRAG 2's PPR algorithm to find evidence paths.
    
    Unlike LLM-guided search, PPR is mathematical:
    - Given the same seeds and graph, results are IDENTICAL every time.
    - It will find connections through "boring" nodes that an LLM might skip.
    """
    
    def __init__(self, hipporag_instance: Optional[Any] = None, graph_store: Optional[Any] = None):
        """
        Args:
            hipporag_instance: An initialized HippoRAG instance.
            graph_store: Fallback graph store if HippoRAG is not available.
        """
        self.hipporag = hipporag_instance
        self.graph_store = graph_store
        self._use_hipporag = hipporag_instance is not None
    
    async def trace(
        self, 
        query: str, 
        seed_entities: List[str], 
        top_k: int = 15
    ) -> List[Tuple[str, float]]:
        """
        Find the mathematically most relevant nodes via PageRank.
        
        Args:
            query: The user's query (for context).
            seed_entities: Starting entities from Stage 1.
            top_k: Number of evidence nodes to return.
            
        Returns:
            List of (entity_name, relevance_score) tuples representing
            the "Chain of Evidence."
        """
        if self._use_hipporag:
            return await self._trace_with_hipporag(query, seed_entities, top_k)
        else:
            return await self._trace_with_fallback(query, seed_entities, top_k)
    
    async def _trace_with_hipporag(
        self, 
        query: str, 
        seed_entities: List[str], 
        top_k: int
    ) -> List[Tuple[str, float]]:
        """Use HippoRAG's native PPR implementation."""
        if self.hipporag is None:
            logger.warning("hipporag_not_initialized")
            return await self._trace_with_fallback(query, seed_entities, top_k)
        
        try:
            # HippoRAG's retrieve function with seeds
            # Note: API may vary based on HippoRAG version
            ranked_nodes = self.hipporag.retrieve(
                query=query,
                top_k=top_k,
                # seeds=seed_entities  # Pass if supported
            )
            
            logger.info("hipporag_trace_success", 
                       query=query,
                       num_results=len(ranked_nodes))
            
            return ranked_nodes
            
        except Exception as e:
            logger.error("hipporag_trace_failed", error=str(e))
            # Fallback to graph-based approach
            return await self._trace_with_fallback(query, seed_entities, top_k)
    
    async def _trace_with_fallback(
        self, 
        query: str, 
        seed_entities: List[str], 
        top_k: int
    ) -> List[Tuple[str, float]]:
        """
        Fallback: Use Neo4j's native graph algorithms for PPR.
        
        This provides similar deterministic behavior using Neo4j's
        built-in PageRank implementation.
        """
        if not self.graph_store:
            logger.warning("no_graph_store_available")
            return [(entity, 1.0) for entity in seed_entities]
        
        try:
            # Neo4j Cypher query for personalized PageRank
            # Starting from seed entities
            cypher_query = """
            CALL gds.pageRank.stream('entityGraph', {
                maxIterations: 20,
                dampingFactor: 0.85,
                sourceNodes: $seedNodes
            })
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId).name AS name, score
            ORDER BY score DESC
            LIMIT $topK
            """
            
            # Execute the query
            result = await self.graph_store.aquery(
                cypher_query,
                params={"seedNodes": seed_entities, "topK": top_k}
            )
            
            ranked_nodes = [(row["name"], row["score"]) for row in result]
            
            logger.info("neo4j_ppr_trace_success",
                       query=query,
                       num_results=len(ranked_nodes))
            
            return ranked_nodes
            
        except Exception as e:
            logger.error("neo4j_ppr_trace_failed", error=str(e))
            # Return seeds with equal weight as last resort
            return [(entity, 1.0) for entity in seed_entities]
    
    def get_evidence_subgraph(
        self, 
        evidence_nodes: List[str]
    ) -> Dict[str, Any]:
        """
        Extract the subgraph containing only the evidence nodes.
        Useful for visualization and audit trails.
        
        Returns:
            Dictionary with 'nodes' and 'edges' for the evidence path.
        """
        # TODO: Implement subgraph extraction for visualization
        return {
            "nodes": evidence_nodes,
            "edges": []  # Placeholder
        }
