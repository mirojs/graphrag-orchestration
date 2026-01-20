"""
Stage 2: Deterministic Tracing (The "Detective")

Uses HippoRAG 2's Personalized PageRank (PPR) to find mathematically
guaranteed paths between entities. This is non-parametric and deterministic.

Now with async-native Neo4j support for better performance.
"""

from typing import List, Tuple, Optional, Dict, Any, TYPE_CHECKING
import structlog

if TYPE_CHECKING:
    from typing import Any as HippoRAGType
    from app.services.async_neo4j_service import AsyncNeo4jService

logger = structlog.get_logger(__name__)


class DeterministicTracer:
    """
    Uses HippoRAG 2's PPR algorithm to find evidence paths.
    
    Unlike LLM-guided search, PPR is mathematical:
    - Given the same seeds and graph, results are IDENTICAL every time.
    - It will find connections through "boring" nodes that an LLM might skip.
    
    Now supports:
    - HippoRAG native PPR (if available)
    - Async Neo4j service with native PPR approximation (recommended)
    - Sync graph_store fallback (legacy)
    """
    
    def __init__(
        self, 
        hipporag_instance: Optional[Any] = None, 
        graph_store: Optional[Any] = None,
        async_neo4j: Optional["AsyncNeo4jService"] = None,
        group_id: Optional[str] = None,
    ):
        """
        Args:
            hipporag_instance: An initialized HippoRAG instance.
            graph_store: Fallback graph store if HippoRAG is not available.
            async_neo4j: AsyncNeo4jService for native async Neo4j queries (preferred).
            group_id: Tenant ID for multi-tenant isolation.
        """
        self.hipporag = hipporag_instance
        self.graph_store = graph_store
        self.async_neo4j = async_neo4j
        self.group_id = group_id
        self._use_hipporag = hipporag_instance is not None
        self._use_async_neo4j = async_neo4j is not None
    
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
        elif self._use_async_neo4j:
            return await self._trace_with_async_neo4j(query, seed_entities, top_k)
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
            try:
                ranked_nodes = self.hipporag.retrieve(
                    query=query,
                    top_k=top_k,
                    seeds=seed_entities,
                )
            except TypeError:
                ranked_nodes = self.hipporag.retrieve(
                    query=query,
                    top_k=top_k,
                    seed_entities=seed_entities,
                )
            
            logger.info("hipporag_trace_success", 
                       query=query,
                       num_results=len(ranked_nodes))
            
            return ranked_nodes
            
        except Exception as e:
            logger.error("hipporag_trace_failed", error=str(e))
            # Fallback to async Neo4j or sync graph_store
            if self._use_async_neo4j:
                return await self._trace_with_async_neo4j(query, seed_entities, top_k)
            return await self._trace_with_fallback(query, seed_entities, top_k)
    
    async def _trace_with_async_neo4j(
        self,
        query: str,
        seed_entities: List[str],
        top_k: int
    ) -> List[Tuple[str, float]]:
        """
        Use native async Neo4j service for PPR-like traversal.
        
        This is the recommended approach - true async with no thread pool overhead.
        Uses distance-based decay as PPR approximation (no GDS required).
        """
        if not self.async_neo4j:
            logger.warning("async_neo4j_not_available", reason="Service not initialized")
            return await self._trace_with_fallback(query, seed_entities, top_k)
        
        if not self.group_id:
            logger.warning("async_neo4j_no_group_id")
            return await self._trace_with_fallback(query, seed_entities, top_k)

        # If we have no seeds at all, don't log this as a warning.
        # Route 4 is allowed to proceed via query-based retrieval.
        if not seed_entities:
            return []
        
        try:
            import os

            def _get_int_env(name: str, default: int) -> int:
                raw = (os.getenv(name, str(default)) or "").strip()
                try:
                    v = int(raw)
                    return v if v > 0 else default
                except Exception:
                    return default

            per_seed_limit = _get_int_env("ROUTE3_PPR_PER_SEED_LIMIT", 25)
            per_neighbor_limit = _get_int_env("ROUTE3_PPR_PER_NEIGHBOR_LIMIT", 10)

            # First, resolve seed entity names to IDs
            seed_records = await self.async_neo4j.get_entities_by_names(
                group_id=self.group_id,
                entity_names=seed_entities,
            )
            seed_ids = [r["id"] for r in seed_records]
            
            if not seed_ids:
                # These seeds were discovered by the LLM but do not correspond
                # to entities present in the graph for this group_id. Route 4 can
                # proceed via query-based retrieval, so treat this as a normal
                # non-graph case rather than as evidence.
                logger.info(
                    "seed_entities_not_resolved",
                    seeds=seed_entities,
                    group_id=self.group_id,
                )
                return []
            
            # Use native PPR approximation (distance-based decay)
            ranked_nodes = await self.async_neo4j.personalized_pagerank_native(
                group_id=self.group_id,
                seed_entity_ids=seed_ids,
                damping=0.85,
                max_iterations=20,
                top_k=top_k,
                per_seed_limit=per_seed_limit,
                per_neighbor_limit=per_neighbor_limit,
            )
            
            logger.info("async_neo4j_ppr_success",
                       query=query[:50],
                       num_seeds=len(seed_ids),
                       num_results=len(ranked_nodes))
            
            return ranked_nodes
            
        except Exception as e:
            logger.error("async_neo4j_ppr_failed", error=str(e))
            return await self._trace_with_fallback(query, seed_entities, top_k)

    async def trace_semantic_beam(
        self,
        query: str,
        query_embedding: List[float],
        seed_entities: List[str],
        max_hops: int = 3,
        beam_width: int = 10,
    ) -> List[Tuple[str, float]]:
        """
        Semantic-guided multi-hop using beam search + native vector similarity.

        Unlike PPR (graph-structure-only), this uses query embedding at each hop
        to prune candidates, keeping only the most query-relevant expansions.
        This is ideal for Route 4 deep reasoning where semantic alignment matters.

        Requires:
            - Entities have embeddings (`.embedding` property in Neo4j)
            - async_neo4j service configured

        Args:
            query: User query (for logging).
            query_embedding: Query vector (same model as entity embeddings).
            seed_entities: Starting entity names.
            max_hops: Number of hops (default 3).
            beam_width: Candidates per hop (default 10).

        Returns:
            List of (entity_name, accumulated_score) sorted descending.
        """
        if not self.async_neo4j or not self.group_id:
            logger.warning("semantic_beam_not_available", reason="async_neo4j/group_id missing")
            return await self.trace(query, seed_entities, top_k=beam_width)

        try:
            # Resolve seed names to IDs
            seed_records = await self.async_neo4j.get_entities_by_names(
                group_id=self.group_id,
                entity_names=seed_entities,
            )
            seed_ids = [r["id"] for r in seed_records]

            if not seed_ids:
                logger.warning("semantic_beam_no_seeds", seeds=seed_entities)
                return [(e, 1.0) for e in seed_entities]

            ranked = await self.async_neo4j.semantic_multihop_beam(
                group_id=self.group_id,
                query_embedding=query_embedding,
                seed_entity_ids=seed_ids,
                max_hops=max_hops,
                beam_width=beam_width,
            )

            logger.info(
                "semantic_beam_trace_success",
                query=query[:50],
                seeds=len(seed_ids),
                results=len(ranked),
            )
            return ranked

        except Exception as e:
            logger.error("semantic_beam_trace_failed", error=str(e))
            # Fallback to structure-only PPR
            return await self.trace(query, seed_entities, top_k=beam_width)

    async def _trace_with_fallback(
        self, 
        query: str, 
        seed_entities: List[str], 
        top_k: int
    ) -> List[Tuple[str, float]]:
        """
        Legacy fallback: Use sync graph_store with asyncio.to_thread.
        
        This wraps the sync LlamaIndex Neo4jPropertyGraphStore.
        Less efficient than async_neo4j but provides compatibility.
        """
        import asyncio
        
        if not self.graph_store:
            logger.warning("no_graph_store_available")
            return [(entity, 1.0) for entity in seed_entities]
        
        try:
            # Use simple neighbor expansion instead of GDS PPR
            # (GDS requires separate license)
            # Note: Includes alias support for flexible seed entity matching
            cypher_query = """
            UNWIND $seedNames AS seedName
            MATCH (seed:`__Entity__`)
            WHERE (toLower(seed.name) = toLower(seedName)
                   OR ANY(alias IN coalesce(seed.aliases, []) WHERE toLower(alias) = toLower(seedName)))
              AND seed.group_id = $group_id
            
            // Expand to neighbors with decay
            OPTIONAL MATCH path = (seed)-[*1..3]-(neighbor:`__Entity__`)
            WHERE neighbor.group_id = $group_id
              AND ALL(r IN relationships(path) WHERE type(r) <> 'MENTIONS')
            
            WITH coalesce(neighbor, seed) AS entity,
                 CASE 
                   WHEN neighbor IS NULL THEN 1.0
                   ELSE 0.85 ^ length(path)
                 END AS score
            
            WITH entity.name AS name, sum(score) AS total_score
            RETURN name, total_score AS score
            ORDER BY total_score DESC
            LIMIT $topK
            """
            
            # Execute via sync graph_store (wrapped in to_thread)
            result = await asyncio.to_thread(
                self.graph_store.structured_query,
                cypher_query,
                {"seedNames": seed_entities, "topK": top_k, "group_id": self.graph_store.group_id}
            )
            
            if result:
                ranked_nodes = [(row["name"], row["score"]) for row in result]
                logger.info("fallback_ppr_trace_success",
                           query=query[:50],
                           num_results=len(ranked_nodes))
                return ranked_nodes
            
            return [(entity, 1.0) for entity in seed_entities]
            
        except Exception as e:
            logger.error("fallback_ppr_trace_failed", error=str(e))
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
