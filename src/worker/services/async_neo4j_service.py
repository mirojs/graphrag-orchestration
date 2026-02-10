"""
Async-native Neo4j Service for high-performance graph queries.

Uses Neo4j's native AsyncGraphDatabase driver for true non-blocking I/O.
This is optimized for Route 2/3 hot paths where latency is critical.

Key features:
- True async/await (no thread pool overhead)
- Connection pooling with async driver
- Optimized for read-heavy graph traversal queries
- Multi-tenant isolation via group_id filtering
- Cypher 25 runtime support for performance optimizations

Usage:
    async with AsyncNeo4jService.from_settings() as service:
        entities = await service.get_entities_by_importance(group_id, top_k=50)
        neighbors = await service.expand_neighbors(group_id, entity_ids, depth=2)

Cypher 25 Migration (January 2026):
    Queries can optionally use CYPHER_25_PREFIX to access Cypher 25 optimizations:
    - MergeUniqueNode: Faster MERGE on uniquely constrained properties
    - State-aware pruning (allReduce): Kill invalid paths mid-expansion
    - WHEN...THEN...ELSE: Native conditional branching
    - REPEATABLE ELEMENTS: Native cyclic path support
    
    Use cypher25_query() helper for automatic prefix injection.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from neo4j.exceptions import Neo4jError

from src.core.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Cypher 25 Runtime Support
# =============================================================================

# Cypher 25 prefix for opting into new runtime optimizations
# Set USE_CYPHER_25 = True to enable Cypher 25 features globally
# Toggle this to False to run legacy (pre-Cypher25) benchmarks
USE_CYPHER_25: bool = True
CYPHER_25_PREFIX: str = "CYPHER 25\n"


def cypher25_query(query: str, *, use_cypher25: bool = USE_CYPHER_25) -> str:
    """
    Optionally prepend CYPHER 25 prefix to a query.
    
    Cypher 25 unlocks:
    - MergeUniqueNode: Faster MERGE with uniqueness constraints
    - MergeInto: Optimized MERGE when endpoints are known
    - allReduce: State-aware path pruning (mid-expansion termination)
    - WHEN...THEN...ELSE: Native conditional branching
    - REPEATABLE ELEMENTS: Cyclic path traversal
    - Parallel runtime optimizations for declarative patterns
    
    Args:
        query: The Cypher query string
        use_cypher25: Whether to add the CYPHER 25 prefix (default: USE_CYPHER_25 global)
        
    Returns:
        Query with CYPHER 25 prefix if enabled, otherwise unchanged
        
    Example:
        >>> cypher25_query("MATCH (n) RETURN n")
        'CYPHER 25\\nMATCH (n) RETURN n'
    """
    if use_cypher25 and not query.strip().upper().startswith("CYPHER"):
        return f"{CYPHER_25_PREFIX}{query}"
    return query


class AsyncNeo4jService:
    """
    Async-native Neo4j service for performance-critical graph operations.
    
    Unlike LlamaIndex's Neo4jPropertyGraphStore (which wraps sync calls),
    this uses Neo4j's native async driver for true non-blocking I/O.
    """
    
    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
        max_connection_pool_size: int = 50,
    ):
        self._uri = uri
        self._username = username
        self._password = password
        self._database = database
        self._driver: Optional[AsyncDriver] = None
        self._max_pool_size = max_connection_pool_size
    
    @classmethod
    def from_settings(cls) -> "AsyncNeo4jService":
        """Create service from application settings."""
        return cls(
            uri=settings.NEO4J_URI or "",
            username=settings.NEO4J_USERNAME or "neo4j",
            password=settings.NEO4J_PASSWORD or "",
            database=settings.NEO4J_DATABASE or "neo4j",
        )
    
    async def connect(self) -> None:
        """Initialize the async driver connection pool."""
        if self._driver is not None:
            return
        
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._username, self._password),
            max_connection_pool_size=self._max_pool_size,
        )
        # Verify connectivity
        await self._driver.verify_connectivity()
        logger.info("async_neo4j_connected", extra={"uri": self._uri})
    
    async def close(self) -> None:
        """Close the driver and release connections."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("async_neo4j_closed")
    
    async def __aenter__(self) -> "AsyncNeo4jService":
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
    
    def _get_session(self) -> AsyncSession:
        """Get an async session from the driver."""
        if not self._driver:
            raise RuntimeError("AsyncNeo4jService not connected. Call connect() first.")
        return self._driver.session(database=self._database)
    
    # =========================================================================
    # Entity Retrieval (Route 2 Hot Path)
    # =========================================================================
    
    async def get_entities_by_importance(
        self,
        group_id: str,
        top_k: int = 50,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Get top entities by importance score (native async)."""
        query = cypher25_query("""
        MATCH (e)
        WHERE e.group_id = $group_id
          AND (e:Entity OR e:`__Entity__`)
        WITH e, coalesce(e.importance_score, e.degree, 0) AS score
        WHERE score >= $min_importance
        RETURN e.id AS id,
               e.name AS name,
               e.degree AS degree,
               e.chunk_count AS chunk_count,
               score AS importance_score,
               labels(e) AS labels
        ORDER BY score DESC
        LIMIT $top_k
        """)

        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                top_k=top_k,
                min_importance=min_importance,
            )
            records = await result.data()
            logger.debug("get_entities_by_importance", extra={"count": len(records), "group_id": group_id})
            return records
    
    async def get_entities_by_names(
        self,
        group_id: str,
        entity_names: List[str],
        use_extended_matching: bool = True,
        return_unmatched: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get specific entities by name using multi-strategy matching.
        
        Matching strategies (in priority order):
        1. Exact match on entity name (case-insensitive)
        2. Alias match - check entity aliases for exact match
        3. KVP key match - check KeyValue node keys for exact match
        4. Substring match on entity name/aliases
        5. Token overlap (Jaccard-like) via CONTAINS on individual words
        
        Strategy 6 (Vector similarity) is handled separately via
        get_entities_by_vector_similarity() when needed. The caller can use
        return_unmatched=True to get unmatched seeds for Strategy 6 processing.
        
        Args:
            group_id: Tenant isolation ID
            entity_names: List of seed names to resolve
            use_extended_matching: If True, use strategies 3-5 for unmatched seeds
            return_unmatched: If True, return tuple of (records, unmatched_seeds)
            
        Returns:
            If return_unmatched=False: List of entity records with id, name, etc.
            If return_unmatched=True: Tuple of (records, unmatched_seed_names)
        """
        if not entity_names:
            return []
        
        # Strategy 1 & 2: Exact name match + Alias match
        query_exact = cypher25_query("""
        UNWIND $names AS name
        MATCH (e)
        WHERE (e:Entity OR e:`__Entity__`)
            AND e.group_id = $group_id
            AND (
                toLower(e.name) = toLower(name)
                OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(name))
            )
        RETURN DISTINCT
            e.id AS id,
            e.name AS name,
            e.degree AS degree,
            e.chunk_count AS chunk_count,
            coalesce(e.degree, 0) AS importance_score,
            name AS matched_seed,
            'exact_or_alias' AS match_strategy
        """)
        
        async with self._get_session() as session:
            result = await session.run(query_exact, group_id=group_id, names=entity_names)
            records = await result.data()
        
        # Track which seeds were matched
        matched_seeds = {r["matched_seed"].lower() for r in records}
        unmatched_seeds = [n for n in entity_names if n.lower() not in matched_seeds]
        
        if not unmatched_seeds or not use_extended_matching:
            logger.info(
                "get_entities_by_names_result",
                extra={
                    "total_seeds": len(entity_names),
                    "matched_exact": len(records),
                    "unmatched": len(unmatched_seeds),
                }
            )
            return records
        
        # Strategy 3: KVP key match for unmatched seeds
        query_kvp = cypher25_query("""
        UNWIND $names AS name
        MATCH (k:KeyValuePair {group_id: $group_id})
        WHERE toLower(k.key) = toLower(name)
        // KVP nodes link to entities via SIMILAR_TO
        OPTIONAL MATCH (k)-[:SIMILAR_TO]->(e)
        WHERE (e:Entity OR e:`__Entity__`) AND e.group_id = $group_id
        WITH name, COALESCE(e, k) AS node
        WHERE node IS NOT NULL
        RETURN DISTINCT
            node.id AS id,
            COALESCE(node.name, node.key) AS name,
            COALESCE(node.degree, 0) AS degree,
            COALESCE(node.chunk_count, 0) AS chunk_count,
            COALESCE(node.degree, 0) AS importance_score,
            name AS matched_seed,
            'kvp_key' AS match_strategy
        """)
        
        async with self._get_session() as session:
            result = await session.run(query_kvp, group_id=group_id, names=unmatched_seeds)
            kvp_records = await result.data()
        
        records.extend(kvp_records)
        matched_seeds.update(r["matched_seed"].lower() for r in kvp_records)
        unmatched_seeds = [n for n in unmatched_seeds if n.lower() not in matched_seeds]
        
        if not unmatched_seeds:
            logger.info(
                "get_entities_by_names_result",
                extra={
                    "total_seeds": len(entity_names),
                    "matched_exact": len(records) - len(kvp_records),
                    "matched_kvp": len(kvp_records),
                }
            )
            return records
        
        # Strategy 4: Substring match for unmatched seeds
        query_substring = cypher25_query("""
        UNWIND $names AS name
        MATCH (e)
        WHERE (e:Entity OR e:`__Entity__`)
            AND e.group_id = $group_id
            AND (
                toLower(e.name) CONTAINS toLower(name)
                OR toLower(name) CONTAINS toLower(e.name)
                OR ANY(alias IN coalesce(e.aliases, []) WHERE 
                    toLower(alias) CONTAINS toLower(name) OR toLower(name) CONTAINS toLower(alias)
                )
            )
        RETURN DISTINCT
            e.id AS id,
            e.name AS name,
            e.degree AS degree,
            e.chunk_count AS chunk_count,
            coalesce(e.degree, 0) AS importance_score,
            name AS matched_seed,
            'substring' AS match_strategy
        LIMIT 10
        """)
        
        async with self._get_session() as session:
            result = await session.run(query_substring, group_id=group_id, names=unmatched_seeds)
            substring_records = await result.data()
        
        records.extend(substring_records)
        matched_seeds.update(r["matched_seed"].lower() for r in substring_records)
        unmatched_seeds = [n for n in unmatched_seeds if n.lower() not in matched_seeds]
        
        if not unmatched_seeds:
            logger.info(
                "get_entities_by_names_result",
                extra={
                    "total_seeds": len(entity_names),
                    "matched_substring": len(substring_records),
                }
            )
            return records
        
        # Strategy 5: Token overlap (word-level CONTAINS) for remaining seeds
        # Split seeds into words and find entities containing those words
        query_token = cypher25_query("""
        UNWIND $names AS name
        WITH name, split(toLower(name), ' ') AS words
        UNWIND words AS word
        WITH name, word
        WHERE size(word) >= 3  // Skip short words like 'the', 'a'
        MATCH (e)
        WHERE (e:Entity OR e:`__Entity__`)
            AND e.group_id = $group_id
            AND toLower(e.name) CONTAINS word
        WITH name, e, count(DISTINCT word) AS word_matches
        WHERE word_matches >= 1
        RETURN
            e.id AS id,
            e.name AS name,
            e.degree AS degree,
            e.chunk_count AS chunk_count,
            coalesce(e.degree, 0) AS importance_score,
            name AS matched_seed,
            'token_overlap' AS match_strategy,
            word_matches AS match_score
        ORDER BY match_score DESC
        LIMIT 10
        """)
        
        async with self._get_session() as session:
            result = await session.run(query_token, group_id=group_id, names=unmatched_seeds)
            token_records = await result.data()
        
        records.extend(token_records)
        
        # Log final results
        final_unmatched = [n for n in entity_names if n.lower() not in 
                          {r["matched_seed"].lower() for r in records}]
        
        logger.info(
            "get_entities_by_names_result",
            extra={
                "total_seeds": len(entity_names),
                "total_matched": len(records),
                "strategies_used": list({r.get("match_strategy", "unknown") for r in records}),
                "unmatched_seeds": final_unmatched[:5] if final_unmatched else [],
            }
        )
        
        if return_unmatched:
            return records, final_unmatched
        return records
    
    async def get_entities_by_vector_similarity(
        self,
        group_id: str,
        seed_text: str,
        seed_embedding: List[float],
        top_k: int = 3,
        index_name: str = "entity_embedding",  # V1: entity_embedding, V2: entity_embedding_v2
    ) -> List[Dict[str, Any]]:
        """
        Strategy 6: Find entities using vector similarity on entity embeddings.
        
        Uses Neo4j's native vector index to find semantically similar entities
        when lexical matching (strategies 1-5) fails.
        
        Index selection:
        - V1 (OpenAI 3072d): Use 'entity_embedding' index
        - V2 (Voyage 2048d): Use 'entity_embedding_v2' index
        
        This is the last-resort fallback for cases like:
        - "elevator equipment" → matches "Vertical Platform Lift" 
        - "payment portal" → matches "Online Remittance URL"
        
        Args:
            group_id: Tenant isolation ID
            seed_text: The seed phrase (for logging)
            seed_embedding: Vector embedding of the seed phrase
            top_k: Number of similar entities to return
            index_name: Vector index to query ('entity_embedding' or 'entity_embedding_v2')
            
        Returns:
            List of entity records with id, name, degree, importance_score, similarity
        """
        if not seed_embedding:
            return []
        
        # Query vector index with group filtering
        # Note: Neo4j vector search returns top-k globally, we filter by group after
        # Use parameterized index name - try both Entity and __Entity__ labels
        query = cypher25_query(f"""
        CALL db.index.vector.queryNodes('{index_name}', $top_k_oversample, $embedding)
        YIELD node, score
        WHERE node.group_id = $group_id
        RETURN
            node.id AS id,
            node.name AS name,
            node.degree AS degree,
            node.chunk_count AS chunk_count,
            coalesce(node.degree, 0) AS importance_score,
            score AS similarity,
            $seed_text AS matched_seed,
            'vector_similarity' AS match_strategy
        ORDER BY score DESC
        LIMIT $top_k
        """)
        
        try:
            async with self._get_session() as session:
                result = await session.run(
                    query,
                    group_id=group_id,
                    embedding=seed_embedding,
                    top_k=top_k,
                    top_k_oversample=top_k * 3,  # Oversample to account for group filtering
                    seed_text=seed_text,
                )
                records = await result.data()
            
            if records:
                logger.info(
                    "get_entities_by_vector_similarity_success: seed=%s num_results=%d top_match=%s top_similarity=%.3f",
                    seed_text,
                    len(records),
                    records[0]["name"] if records else None,
                    records[0]["similarity"] if records else 0,
                )
            
            return records
            
        except Exception as e:
            logger.warning(
                "get_entities_by_vector_similarity_failed: seed=%s error=%s",
                seed_text,
                str(e),
            )
            return []
    
    # =========================================================================
    # Graph Traversal (Route 2/3 - No GDS Required)
    # =========================================================================
    
    async def expand_neighbors(
        self,
        group_id: str,
        entity_ids: List[str],
        depth: int = 2,
        limit_per_entity: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Expand from seed entities to find neighbors (native async).
        
        Uses native Cypher path patterns - no GDS required.
        """
        query = cypher25_query(f"""
        UNWIND $entity_ids AS eid
        MATCH (seed)
        WHERE (seed:Entity OR seed:`__Entity__`)
          AND seed.id = eid
          AND seed.group_id = $group_id
        MATCH path = (seed)-[r*1..{depth}]-(neighbor)
        WHERE (neighbor:Entity OR neighbor:`__Entity__`)
          AND neighbor.group_id = $group_id
          AND neighbor.id <> seed.id
          AND ALL(rel IN relationships(path) WHERE type(rel) <> 'MENTIONS')
        WITH neighbor, 
             min(length(path)) AS distance,
             count(DISTINCT path) AS path_count
        RETURN neighbor.id AS id,
               neighbor.name AS name,
               coalesce(neighbor.degree, 0) AS importance_score,
               distance,
               path_count
        ORDER BY distance ASC, coalesce(neighbor.degree, 0) DESC
        LIMIT $limit
        """)
        
        async with self._get_session() as session:
            # Cast to str to satisfy Neo4j type checker
            result = await session.run(
                str(query),  # type: ignore[arg-type]
                group_id=group_id,
                entity_ids=entity_ids,
                limit=limit_per_entity * len(entity_ids),
            )
            records = await result.data()
            logger.debug("expand_neighbors", extra={
                "seeds": len(entity_ids), 
                "neighbors": len(records)
            })
            return records
    
    async def get_entity_relationships(
        self,
        group_id: str,
        entity_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get all relationships for a specific entity.
        """
        query = cypher25_query("""
        MATCH (e)-[r]-(other)
        WHERE (e:Entity OR e:`__Entity__`)
          AND (other:Entity OR other:`__Entity__`)
          AND e.id = $entity_id
          AND e.group_id = $group_id 
          AND other.group_id = $group_id
          AND type(r) <> 'MENTIONS'
        RETURN e.name AS source,
               type(r) AS relationship,
               other.name AS target,
               other.id AS target_id,
               coalesce(other.degree, 0) AS target_importance
        LIMIT $limit
        """)
        
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                entity_id=entity_id,
                limit=limit,
            )
            return await result.data()
    
    # =========================================================================
    # Personalized PageRank (Native Cypher - No GDS)
    # =========================================================================
    
    async def personalized_pagerank_native(
        self,
        group_id: str,
        seed_entity_ids: List[str],
        damping: float = 0.85,
        max_iterations: int = 20,
        top_k: int = 20,
        per_seed_limit: int = 25,
        per_neighbor_limit: int = 10,
        include_section_graph: bool = True,  # Re-enabled after bug fix
        # Path weight multipliers (Step 11 — February 9, 2026)
        # Each multiplier scales its path's contribution to the final score.
        # Default 1.0 preserves original behavior.  Set via env vars for tuning.
        weight_entity: float = 1.0,
        weight_section: float = 1.0,
        weight_similar: float = 1.0,
        weight_shares: float = 1.0,
        weight_hub: float = 1.0,
    ) -> List[Tuple[str, float]]:
        """
        Native Cypher approximation of Personalized PageRank.
        
        This uses iterative neighbor expansion with decay - not true PPR,
        but provides similar "spread from seeds" behavior without GDS.
        
        Phase C Enhancement (January 2026):
        When include_section_graph=True, also traverse SEMANTICALLY_SIMILAR
        edges between Section nodes. This addresses HippoRAG 2's "Latent
        Transitions" weakness by allowing PPR to jump between thematically
        related sections even when they share no explicit entities.
        
        Traversal paths when include_section_graph=True:
        1. Standard: seed Entity -> Entity relationships -> neighbor Entity
        2. Section:  seed Entity -> MENTIONS -> Chunk -> IN_SECTION -> Section
                     -> SEMANTICALLY_SIMILAR -> Section -> IN_SECTION -> Chunk
                     -> MENTIONS -> neighbor Entity
        
        For true PPR, consider:
        1. Install GDS Community (free for self-managed Neo4j)
        2. Use NetworkX in Python (slower but more accurate)
        """
        # Performance note:
        # A naive variable-length path expansion like (seed)-[*1..3]-(neighbor)
        # can explode combinatorially and produce multi-second (or worse) queries
        # even on modest graphs. For Route 3, we primarily need a deterministic,
        # fast evidence spread. We approximate PPR by sampling top neighbors
        # (by degree) at 1 hop and optionally 2 hops, with strict per-seed limits.
        #
        # max_iterations is kept for API compatibility but is not used by this
        # approximation.
        
        # Build the query based on whether section graph traversal is enabled
        if include_section_graph:
            query = self._build_ppr_query_with_section_graph()
        else:
            query = self._build_ppr_query_entity_only()
        
        import time

        t0 = time.perf_counter()
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                seed_ids=seed_entity_ids,
                damping=damping,
                top_k=top_k,
                per_seed_limit=per_seed_limit,
                per_neighbor_limit=per_neighbor_limit,
                weight_entity=weight_entity,
                weight_section=weight_section,
                weight_similar=weight_similar,
                weight_shares=weight_shares,
                weight_hub=weight_hub,
            )
            records = await result.data()
        dt_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "async_neo4j_ppr_native_complete group_id=%s seeds=%s top_k=%s duration_ms=%s per_seed_limit=%s per_neighbor_limit=%s include_section_graph=%s",
            group_id,
            len(seed_entity_ids),
            top_k,
            dt_ms,
            per_seed_limit,
            per_neighbor_limit,
            include_section_graph,
        )

        # Return as (name, score) tuples for compatibility
        return [(r["name"], r["score"]) for r in records]
    
    def _build_ppr_query_entity_only(self) -> str:
        """Build the original Entity-only PPR query."""
        return cypher25_query("""
            UNWIND $seed_ids AS seed_id
            MATCH (seed {id: seed_id})
            WHERE seed.group_id = $group_id
              AND (seed:Entity OR seed:`__Entity__`)

            // Always include the seed itself
            WITH seed,
                 seed_id,
                 $group_id AS group_id,
                 $per_seed_limit AS per_seed_limit,
                 $per_neighbor_limit AS per_neighbor_limit,
                 $damping AS damping,
                 $weight_entity AS w_entity
            CALL (seed, group_id, per_seed_limit) {
                MATCH (seed)-[r1]-(n1)
                WHERE n1.group_id = group_id
                    AND (n1:Entity OR n1:`__Entity__`)
                    AND type(r1) <> 'MENTIONS'
                WITH n1
                ORDER BY coalesce(n1.degree, 0) DESC
                LIMIT $per_seed_limit
                RETURN collect(n1) AS hop1
            }

            WITH seed, hop1, group_id, per_neighbor_limit, damping
            UNWIND (hop1 + [seed]) AS hop1_node
            WITH seed, hop1_node, group_id, per_neighbor_limit, damping

            // Optional 2-hop expansion capped per hop1_node
            CALL (seed, hop1_node, group_id, per_neighbor_limit) {
                MATCH (hop1_node)-[r2]-(n2)
                WHERE n2.group_id = group_id
                    AND (n2:Entity OR n2:`__Entity__`)
                    AND type(r2) <> 'MENTIONS'
                WITH n2
                ORDER BY coalesce(n2.degree, 0) DESC
                LIMIT $per_neighbor_limit
                RETURN collect(n2) AS hop2
            }

            WITH seed, hop1_node, hop2, damping
            UNWIND (hop2 + [hop1_node]) AS entity
            WITH entity, seed, hop1_node, damping,
                 sum(
                     CASE
                         WHEN entity.id = seed.id THEN 1.0
                         WHEN entity.id = hop1_node.id THEN damping
                         ELSE damping * damping
                     END
                 ) AS score
            RETURN entity.id AS id,
                   entity.name AS name,
                   score AS score,
                   coalesce(entity.degree, 0) AS importance
            ORDER BY score DESC
            LIMIT $top_k
        """)
    
    def _build_ppr_query_with_section_graph(self) -> str:
        """
        Build PPR query that traverses Entity graph, Section graph, AND Phase 1-3 edges.
        
        This enables multiple traversal paths for comprehensive evidence discovery:
        
        Path 1: Standard Entity-to-Entity relationships (original behavior)
        Path 2: SEMANTICALLY_SIMILAR between Sections (thematic hops)
        Path 3: SEMANTICALLY_SIMILAR between Entities (GDS KNN semantic similarity, unified Jan 28 2026)
        Path 4: SHARES_ENTITY between Sections (Phase 2 cross-document links)
        Path 5: APPEARS_IN_SECTION + HAS_HUB_ENTITY (Phase 1 foundation edges)
        
        Scoring:
        - Direct entity relationships: damping (0.85)
        - 2-hop entity relationships: damping² (0.72)
        - Section-path entities: similarity * damping²
        - SEMANTICALLY_SIMILAR entities: similarity * damping (GDS KNN with cutoff 0.60)
        - SHARES_ENTITY path: shared_entities * damping² (normalized)
        - Hub entities: mention_count/10 * damping
        
        Addresses HippoRAG 2's weaknesses:
        - "Latent Transitions": SEMANTICALLY_SIMILAR (sections + entities)
        - "Cross-document reasoning": SHARES_ENTITY
        - "Hub entity importance": HAS_HUB_ENTITY
        """
        return cypher25_query("""
            UNWIND $seed_ids AS seed_id
            MATCH (seed {id: seed_id})
            WHERE seed.group_id = $group_id
              AND (seed:Entity OR seed:`__Entity__`)

            WITH seed,
                 seed_id,
                 $group_id AS group_id,
                 $per_seed_limit AS per_seed_limit,
                 $per_neighbor_limit AS per_neighbor_limit,
                 $damping AS damping,
                 $weight_entity AS w_entity,
                 $weight_section AS w_section,
                 $weight_similar AS w_similar,
                 $weight_shares AS w_shares,
                 $weight_hub AS w_hub

            // =====================================================================
            // Path 1: Standard Entity-to-Entity relationships (original behavior)
            // =====================================================================
            CALL (seed, group_id, per_seed_limit) {
                MATCH (seed)-[r1]-(n1)
                WHERE n1.group_id = group_id
                    AND (n1:Entity OR n1:`__Entity__`)
                    AND NOT (type(r1) IN ['MENTIONS', 'SIMILAR_TO', 'APPEARS_IN_SECTION'])
                WITH n1
                ORDER BY coalesce(n1.degree, 0) DESC
                LIMIT $per_seed_limit
                RETURN collect(n1) AS entity_hop1
            }

            // =====================================================================
            // Path 2: Section-based thematic hops via SEMANTICALLY_SIMILAR edges
            // =====================================================================
            CALL (seed, group_id, per_seed_limit) {
                MATCH (chunk)-[:MENTIONS]->(seed)
                WHERE chunk.group_id = group_id
                    AND (chunk:Chunk OR chunk:TextChunk OR chunk:`__Node__`)
                
                MATCH (chunk)-[:IN_SECTION]->(s1:Section)
                WHERE s1.group_id = group_id
                
                MATCH (s1)-[sim:SEMANTICALLY_SIMILAR]-(s2:Section)
                WHERE s2.group_id = group_id
                  AND coalesce(sim.similarity, 0.5) >= 0.5
                
                MATCH (chunk2)-[:IN_SECTION]->(s2)
                WHERE chunk2.group_id = group_id
                    AND (chunk2:Chunk OR chunk2:TextChunk OR chunk2:`__Node__`)
                
                MATCH (chunk2)-[:MENTIONS]->(neighbor)
                WHERE neighbor.group_id = group_id
                    AND (neighbor:Entity OR neighbor:`__Entity__`)
                    AND neighbor.id <> seed.id
                
                WITH neighbor, max(coalesce(sim.similarity, 0.5)) AS sim_weight
                ORDER BY sim_weight * coalesce(neighbor.degree, 0) DESC
                LIMIT $per_seed_limit
                RETURN collect({node: neighbor, weight: sim_weight, path: 'semantic_similar'}) AS section_hop1
            }

            // =====================================================================
            // Path 3: SEMANTICALLY_SIMILAR edges (GDS KNN - unified semantic similarity)
            // =====================================================================
            CALL (seed, group_id, per_seed_limit) {
                MATCH (seed)-[sim:SEMANTICALLY_SIMILAR|SIMILAR_TO]-(neighbor)
                WHERE neighbor.group_id = group_id
                    AND (neighbor:Entity OR neighbor:`__Entity__`)
                    AND coalesce(sim.similarity, 0.60) >= 0.60
                WITH neighbor, max(coalesce(sim.similarity, 0.60)) AS sim_weight
                ORDER BY sim_weight * coalesce(neighbor.degree, 0) DESC
                LIMIT $per_seed_limit
                RETURN collect({node: neighbor, weight: sim_weight, path: 'semantically_similar'}) AS similar_entities
            }

            // =====================================================================
            // Path 4: SHARES_ENTITY edges (Phase 2 - cross-document section links)
            // =====================================================================
            CALL (seed, group_id, per_seed_limit) {
                // Use APPEARS_IN_SECTION for faster 1-hop to sections
                MATCH (seed)-[:APPEARS_IN_SECTION]->(s1:Section)
                WHERE s1.group_id = group_id
                
                // Traverse SHARES_ENTITY to cross-document sections
                MATCH (s1)-[se:SHARES_ENTITY]-(s2:Section)
                WHERE s2.group_id = group_id
                  AND coalesce(se.shared_entities, 1) >= 2
                
                // Get entities from the related section via HAS_HUB_ENTITY or chunk traversal
                OPTIONAL MATCH (s2)-[hub:HAS_HUB_ENTITY]->(hub_entity:Entity)
                WHERE hub_entity.group_id = group_id
                
                // Also get entities via chunks for sections without hub entities
                OPTIONAL MATCH (chunk2)-[:IN_SECTION]->(s2)
                WHERE chunk2.group_id = group_id
                OPTIONAL MATCH (chunk2)-[:MENTIONS]->(chunk_entity)
                WHERE chunk_entity.group_id = group_id
                    AND (chunk_entity:Entity OR chunk_entity:`__Entity__`)
                    AND chunk_entity.id <> seed.id
                
                WITH coalesce(hub_entity, chunk_entity) AS neighbor, 
                     coalesce(se.shared_entities, 1) AS shared_count,
                     CASE WHEN hub_entity IS NOT NULL THEN coalesce(hub.mention_count, 1) / 10.0 ELSE 0.3 END AS hub_weight
                WHERE neighbor IS NOT NULL
                
                WITH neighbor, max(shared_count * hub_weight / 10.0) AS se_weight
                ORDER BY se_weight * coalesce(neighbor.degree, 0) DESC
                LIMIT $per_seed_limit
                RETURN collect({node: neighbor, weight: se_weight, path: 'shares_entity'}) AS shares_entity_hop
            }

            // =====================================================================
            // Path 5: HAS_HUB_ENTITY direct traversal (Phase 1 hub entities)
            // =====================================================================
            CALL (seed, group_id, per_seed_limit) {
                MATCH (seed)-[:APPEARS_IN_SECTION]->(s:Section)
                WHERE s.group_id = group_id
                
                MATCH (s)-[hub:HAS_HUB_ENTITY]->(hub_entity:Entity)
                WHERE hub_entity.group_id = group_id
                    AND hub_entity.id <> seed.id
                
                WITH hub_entity, max(coalesce(hub.mention_count, 1) / 10.0) AS hub_weight
                ORDER BY hub_weight * coalesce(hub_entity.degree, 0) DESC
                LIMIT $per_seed_limit
                RETURN collect({node: hub_entity, weight: hub_weight, path: 'hub_entity'}) AS hub_entities
            }

            // =====================================================================
            // Process entity-path with 2-hop expansion
            // =====================================================================
            WITH seed, entity_hop1, section_hop1, similar_entities, shares_entity_hop, hub_entities,
                 group_id, per_neighbor_limit, damping,
                 w_entity, w_section, w_similar, w_shares, w_hub

            // Process entity-path neighbors (standard decay)
            UNWIND (entity_hop1 + [seed]) AS hop1_node
            WITH seed, hop1_node, entity_hop1, section_hop1, similar_entities, shares_entity_hop, hub_entities,
                 group_id, per_neighbor_limit, damping,
                 w_entity, w_section, w_similar, w_shares, w_hub

            // 2-hop expansion from entity path
            CALL (seed, hop1_node, group_id, per_neighbor_limit) {
                MATCH (hop1_node)-[r2]-(n2)
                WHERE n2.group_id = group_id
                    AND (n2:Entity OR n2:`__Entity__`)
                    AND NOT (type(r2) IN ['MENTIONS', 'SIMILAR_TO', 'APPEARS_IN_SECTION'])
                WITH n2
                ORDER BY coalesce(n2.degree, 0) DESC
                LIMIT $per_neighbor_limit
                RETURN collect(n2) AS hop2
            }

            // Collect all entity IDs from entity-path for scoring
            WITH seed, hop1_node, hop2, entity_hop1, section_hop1, similar_entities, 
                 shares_entity_hop, hub_entities, damping,
                 w_entity, w_section, w_similar, w_shares, w_hub,
                 [e IN entity_hop1 | e.id] AS hop1_ids,
                 [e IN hop2 | e.id] AS hop2_ids

            // Extract all path entities as nodes for inclusion
            WITH seed, hop1_node, hop2, section_hop1, similar_entities, shares_entity_hop, 
                 hub_entities, damping, hop1_ids, hop2_ids,
                 w_entity, w_section, w_similar, w_shares, w_hub,
                 [item IN section_hop1 | item.node] AS section_nodes,
                 [item IN similar_entities | item.node] AS similar_nodes,
                 [item IN shares_entity_hop | item.node] AS shares_nodes,
                 [item IN hub_entities | item.node] AS hub_nodes

            // UNION all paths
            UNWIND (hop2 + [hop1_node] + section_nodes + similar_nodes + shares_nodes + hub_nodes) AS entity
            
            // Calculate combined scores (with configurable path weights)
            WITH DISTINCT entity, seed, hop1_node, section_hop1, similar_entities, 
                 shares_entity_hop, hub_entities, damping, hop1_ids, hop2_ids,
                 w_entity, w_section, w_similar, w_shares, w_hub,
                 // Entity-path contribution (scaled by w_entity)
                 w_entity * CASE
                     WHEN entity.id = seed.id THEN 1.0
                     WHEN entity.id = hop1_node.id THEN damping
                     WHEN entity.id IN hop1_ids THEN damping
                     WHEN entity.id IN hop2_ids THEN damping * damping
                     ELSE 0.0
                 END AS entity_path_score,
                 // Section-path (SEMANTICALLY_SIMILAR)
                 [item IN section_hop1 WHERE item.node.id = entity.id] AS section_matches,
                 // SIMILAR_TO path
                 [item IN similar_entities WHERE item.node.id = entity.id] AS similar_matches,
                 // SHARES_ENTITY path
                 [item IN shares_entity_hop WHERE item.node.id = entity.id] AS shares_matches,
                 // HUB_ENTITY path
                 [item IN hub_entities WHERE item.node.id = entity.id] AS hub_matches

            WITH entity, seed, damping, entity_path_score, 
                 section_matches, similar_matches, shares_matches, hub_matches,
                 // Section path score (scaled by w_section)
                 w_section * CASE WHEN size(section_matches) > 0 
                      THEN section_matches[0].weight * damping * damping
                      ELSE 0.0 END AS section_path_score,
                 // SIMILAR_TO score (scaled by w_similar)
                 w_similar * CASE WHEN size(similar_matches) > 0 
                      THEN similar_matches[0].weight * damping
                      ELSE 0.0 END AS similar_to_score,
                 // SHARES_ENTITY score (scaled by w_shares)
                 w_shares * CASE WHEN size(shares_matches) > 0 
                      THEN shares_matches[0].weight * damping * damping
                      ELSE 0.0 END AS shares_entity_score,
                 // HUB_ENTITY score (scaled by w_hub)
                 w_hub * CASE WHEN size(hub_matches) > 0 
                      THEN hub_matches[0].weight * damping
                      ELSE 0.0 END AS hub_entity_score

            // Final combined score from all paths
            WITH entity.id AS id,
                 entity.name AS name,
                 entity_path_score + section_path_score + similar_to_score + 
                 shares_entity_score + hub_entity_score AS score,
                 coalesce(entity.degree, 0) AS importance
            WHERE score > 0

            RETURN id, name, max(score) AS score, importance
            ORDER BY score DESC
            LIMIT $top_k
        """)
    
    # =========================================================================
    # Community-Aware Seed Expansion (Step 12 — February 9, 2026)
    # =========================================================================

    async def get_community_peers(
        self,
        group_id: str,
        seed_entity_ids: List[str],
        max_peers: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find high-degree entities in the same Louvain communities as the seeds.

        For each seed, looks up its ``community_id`` property (set by GDS Louvain
        at indexing time), then returns the top-degree entities from those
        communities that are **not already seeds**.

        This biases PPR toward the topological neighbourhood identified by
        Louvain's modularity optimisation, improving recall for queries that
        map cleanly onto a community cluster.

        Args:
            group_id: Tenant isolation key.
            seed_entity_ids: IDs of the resolved seed entities.
            max_peers: Maximum number of community peers to return (across
                       all communities).

        Returns:
            List of dicts with keys ``id``, ``name``, ``community_id``, ``degree``.
            Empty if no community_id data exists on the seeds.
        """
        query = cypher25_query("""
        // Collect distinct community_ids from the seed entities
        UNWIND $seed_ids AS sid
        MATCH (seed {id: sid})
        WHERE seed.group_id = $group_id
          AND (seed:Entity OR seed:`__Entity__`)
          AND seed.community_id IS NOT NULL
        WITH collect(DISTINCT seed.community_id) AS cids,
             collect(DISTINCT seed.id) AS seed_id_set

        // Find top-degree peers in those communities (excluding seeds)
        UNWIND cids AS cid
        MATCH (peer)
        WHERE peer.group_id = $group_id
          AND (peer:Entity OR peer:`__Entity__`)
          AND peer.community_id = cid
          AND NOT peer.id IN seed_id_set
        WITH peer, cid
        ORDER BY coalesce(peer.degree, 0) DESC
        LIMIT $max_peers
        RETURN peer.id AS id,
               peer.name AS name,
               cid AS community_id,
               coalesce(peer.degree, 0) AS degree
        """)
        import time
        t0 = time.perf_counter()
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                seed_ids=seed_entity_ids,
                max_peers=max_peers,
            )
            records = await result.data()
        dt_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "community_peers_found",
            group_id=group_id,
            num_seeds=len(seed_entity_ids),
            num_peers=len(records),
            duration_ms=dt_ms,
        )
        return records

    # =========================================================================
    # Chunk Retrieval (Route 2/3)
    # =========================================================================
    
    async def get_chunks_for_entities(
        self,
        group_id: str,
        entity_ids: List[str],
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Get text chunks that mention the given entities.
        """
        # Support both Entity and __Entity__ labels
        query = cypher25_query("""
        UNWIND $entity_ids AS eid
        MATCH (e)
        WHERE (e:Entity OR e:`__Entity__`)
          AND e.id = eid
          AND e.group_id = $group_id
        MATCH (c:TextChunk)-[:MENTIONS]->(e)
        WHERE c.group_id = $group_id
        WITH DISTINCT c
        RETURN c.id AS chunk_id,
               c.text AS text,
               c.url AS url,
               c.page_number AS page,
               c.section_path AS section_path
        LIMIT $limit
        """)
        
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                entity_ids=entity_ids,
                limit=limit,
            )
            return await result.data()
    
    # =========================================================================
    # Entity Existence Check (Route 1 Negative Detection)
    # =========================================================================
    
    async def check_field_exists_in_document(
        self,
        group_id: str,
        doc_url: str,
        field_keywords: List[str],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a document contains chunks with field-related keywords.
        
        Returns:
            (exists: bool, matched_section: Optional[str])
        """
        query = cypher25_query("""
        MATCH (c)
        WHERE c.group_id = $group_id 
          AND (c.url = $doc_url OR c.document_id = $doc_url)
          AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
        WITH c, 
             [kw IN $keywords WHERE 
               toLower(c.text) CONTAINS toLower(kw) OR
               toLower(coalesce(c.section_path, '')) CONTAINS toLower(kw)
             ] AS matched_keywords
        WHERE size(matched_keywords) > 0
        RETURN c.section_path AS section_path, 
               matched_keywords,
               substring(c.text, 0, 200) AS preview
        LIMIT 1
        """)
        
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                doc_url=doc_url,
                keywords=field_keywords,
            )
            record = await result.single()
            
            # Debug logging
            logger.info(
                "negative_detection_query_result group_id=%s doc_url=%s found=%s matched_keywords=%s preview=%s",
                group_id,
                doc_url,
                record is not None,
                record.get("matched_keywords") if record else None,
                record.get("preview") if record else None,
            )
            
            if record:
                return True, record.get("section_path")
            return False, None
    
    async def check_field_pattern_in_document(
        self,
        group_id: str,
        doc_url: str,
        pattern: str,
    ) -> bool:
        """
        Check if a document contains chunks matching a specific regex pattern.
        
        This provides more precise negative detection by validating that fields
        exist in the expected format (e.g., VAT numbers, URLs, bank accounts).
        
        Args:
            group_id: The group ID for the chunks
            doc_url: Document URL or ID to check
            pattern: Regex pattern to match (e.g., r'(?i)(VAT|Tax ID).{0,50}\\d{5,}')
            
        Returns:
            True if pattern found in any chunk, False otherwise
        """
        query = cypher25_query("""
        MATCH (c)
        WHERE c.group_id = $group_id 
          AND (c.url = $doc_url OR c.document_id = $doc_url)
          AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
          AND c.text =~ $pattern
        RETURN count(c) > 0 AS exists
        """)
        
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                doc_url=doc_url,
                pattern=pattern,
            )
            record = await result.single()
            
            exists = record["exists"] if record else False
            
            logger.info(
                "pattern_based_negative_detection",
                group_id=group_id,
                doc_url=doc_url,
                pattern=pattern[:50],  # Truncate for logging
                found=exists,
            )
            
            return exists

    async def check_pattern_in_docs_by_keyword(
        self,
        group_id: str,
        doc_keyword: str,
        pattern: str,
        *,
        limit: int = 1,
    ) -> bool:
        """
        Check if any chunk in documents whose title/source contains doc_keyword matches pattern.

        This is a lightweight, graph-backed existence check that avoids relying on a specific
        document URL (useful for Route 3 where multiple docs may be in evidence).

        Args:
            group_id: Tenant/group id
            doc_keyword: Lowercase keyword to match against document_title/document_source
            pattern: Cypher regex pattern (Neo4j '=~' syntax)
            limit: early-exit limit (kept small for speed)

        Returns:
            True if any matching chunk exists, else False.
        """
        # Prefer checking the parent Document node for title/source metadata
        # to avoid UnknownPropertyKey warnings when those properties are not set on chunks.
        query = cypher25_query("""
        MATCH (c)
        OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
        WHERE c.group_id = $group_id
          AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
          AND (
            toLower(coalesce(d.title, '')) CONTAINS $doc_keyword OR
            toLower(coalesce(d.source, '')) CONTAINS $doc_keyword OR
            toLower(coalesce(c.url, '')) CONTAINS $doc_keyword
          )
          AND c.text =~ $pattern
        RETURN count(c) > 0 AS exists
        LIMIT $limit
        """)

        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                doc_keyword=(doc_keyword or "").lower(),
                pattern=pattern,
                limit=limit,
            )
            record = await result.single()
            exists = record["exists"] if record else False

            # If the scoped keyword search didn't find a match, fall back to a
            # lightweight group-wide search for the pattern (keeps limit small).
            if not exists:
                fallback_query = cypher25_query("""
                MATCH (c)
                WHERE c.group_id = $group_id
                  AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
                  AND c.text =~ $pattern
                RETURN count(c) > 0 AS exists
                LIMIT $limit
                """)
                async with self._get_session() as s2:
                    result2 = await s2.run(
                        fallback_query,
                        group_id=group_id,
                        pattern=pattern,
                        limit=limit,
                    )
                    record2 = await result2.single()
                    fallback_exists = record2["exists"] if record2 else False
                    if fallback_exists:
                        logger.info(
                            "pattern_exists_in_docs_by_keyword_fallback_hit",
                            group_id=group_id,
                            doc_keyword=doc_keyword,
                            pattern=pattern[:60],
                        )
                        exists = True

            logger.info(
                "pattern_exists_in_docs_by_keyword",
                group_id=group_id,
                doc_keyword=doc_keyword,
                pattern=pattern[:60],
                found=exists,
            )
            return exists
    
    # =========================================================================
    # Semantic-Guided Multi-Hop (Beam Search with Vector Pruning)
    # =========================================================================

    async def semantic_multihop_beam(
        self,
        group_id: str,
        query_embedding: List[float],
        seed_entity_ids: List[str],
        max_hops: int = 3,
        beam_width: int = 10,
        damping: float = 0.85,
        seed_names: Optional[Dict[str, str]] = None,
        knn_config: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """
        Semantic-guided multi-hop expansion using beam search + vector similarity.

        At each hop, expands neighbors and prunes to the top beam_width candidates
        using `vector.similarity.cosine(entity.embedding, $query_embedding)`.
        This avoids the classic "enumerate all paths then filter" trap.

        Requires entities to have embeddings stored in `.embedding` property.

        Args:
            group_id: Tenant isolation key.
            query_embedding: Query vector for semantic scoring.
            seed_entity_ids: Starting entity IDs (from Route 4 decomposition).
            max_hops: Number of expansion rounds (default 3).
            beam_width: How many candidates to keep per hop (default 10).
            damping: Decay applied per hop to accumulator score.
            knn_config: Optional KNN configuration filter for SEMANTICALLY_SIMILAR edges.
                        If None (default), ALL SEMANTICALLY_SIMILAR edges are traversed
                        (consistent with PPR Path 3 — edges already quality-filtered at
                        indexing time with similarity_cutoff=0.60).
                        If "none", no SEMANTICALLY_SIMILAR edges are traversed (A/B baseline).
                        If set (e.g., 'knn-1', 'knn-2', 'knn-3'), only traverse 
                        SEMANTICALLY_SIMILAR edges with matching knn_config property.

        Returns:
            List of (entity_name, score) sorted descending by accumulated score.
        """
        # Query uses native vector.similarity.cosine (available in Neo4j 5.18+/Aura)
        # Runs a single hop at a time; Python loop controls iteration.
        #
        # KNN config filtering (normalized Feb 2026 to match PPR Path 3):
        # - If knn_config is None: include ALL SEMANTICALLY_SIMILAR edges (consistent with PPR)
        # - If knn_config == "none": explicitly exclude all SEMANTICALLY_SIMILAR edges (A/B baseline)
        # - If knn_config is set (e.g., 'knn-1'): only edges matching that config tag
        if knn_config == "none":
            # A/B testing baseline: exclude all SEMANTICALLY_SIMILAR edges
            hop_query = cypher25_query("""
            UNWIND $current_ids AS eid
            MATCH (src)-[r]-(neighbor)
            WHERE (src:Entity OR src:`__Entity__`)
              AND (neighbor:Entity OR neighbor:`__Entity__`)
              AND src.id = eid
              AND neighbor.group_id = $group_id
              AND type(r) <> 'MENTIONS'
              AND type(r) <> 'SEMANTICALLY_SIMILAR'
              AND (neighbor.embedding_v2 IS NOT NULL OR neighbor.embedding IS NOT NULL)
            WITH DISTINCT neighbor,
                 vector.similarity.cosine(COALESCE(neighbor.embedding_v2, neighbor.embedding), $query_embedding) AS sim
            ORDER BY sim DESC
            LIMIT $beam_width
            RETURN neighbor.id AS id,
                   neighbor.name AS name,
                   sim AS similarity
            """)
        elif knn_config:
            # A/B testing: only traverse SEMANTICALLY_SIMILAR edges with matching knn_config tag
            hop_query = cypher25_query("""
            UNWIND $current_ids AS eid
            MATCH (src)-[r]-(neighbor)
            WHERE (src:Entity OR src:`__Entity__`)
              AND (neighbor:Entity OR neighbor:`__Entity__`)
              AND src.id = eid
              AND neighbor.group_id = $group_id
              AND type(r) <> 'MENTIONS'
              AND (
                  type(r) <> 'SEMANTICALLY_SIMILAR' 
                  OR r.knn_config = $knn_config
              )
              AND (neighbor.embedding_v2 IS NOT NULL OR neighbor.embedding IS NOT NULL)
            WITH DISTINCT neighbor,
                 vector.similarity.cosine(COALESCE(neighbor.embedding_v2, neighbor.embedding), $query_embedding) AS sim
            ORDER BY sim DESC
            LIMIT $beam_width
            RETURN neighbor.id AS id,
                   neighbor.name AS name,
                   sim AS similarity
            """)
        else:
            # Default: include ALL SEMANTICALLY_SIMILAR edges (normalized to match PPR Path 3)
            # Edges are already quality-filtered at indexing time (similarity_cutoff=0.60)
            hop_query = cypher25_query("""
            UNWIND $current_ids AS eid
            MATCH (src)-[r]-(neighbor)
            WHERE (src:Entity OR src:`__Entity__`)
              AND (neighbor:Entity OR neighbor:`__Entity__`)
              AND src.id = eid
              AND neighbor.group_id = $group_id
              AND type(r) <> 'MENTIONS'
              AND (neighbor.embedding_v2 IS NOT NULL OR neighbor.embedding IS NOT NULL)
            WITH DISTINCT neighbor,
                 vector.similarity.cosine(COALESCE(neighbor.embedding_v2, neighbor.embedding), $query_embedding) AS sim
            ORDER BY sim DESC
            LIMIT $beam_width
            RETURN neighbor.id AS id,
                   neighbor.name AS name,
                   sim AS similarity
            """)
        
        # Vector expansion query (hop 0) - finds semantically similar entities
        # regardless of relationship edges. Critical for isolated entities like
        # Exhibit A details that may not have edges to other entities.
        vector_expansion_query = cypher25_query("""
        CALL db.index.vector.queryNodes('entity_embedding_v2', $top_k, $query_embedding)
        YIELD node, score
        WHERE node.group_id = $group_id
          AND (node:Entity OR node:`__Entity__`)
        RETURN node.id AS id,
               node.name AS name,
               score AS similarity
        ORDER BY score DESC
        LIMIT $beam_width
        """)

        import time

        t0 = time.perf_counter()

        # Initialize beam with seeds (each seed gets full score 1.0)
        scores: Dict[str, float] = {eid: 1.0 for eid in seed_entity_ids}
        # Initialize names from seed_names parameter to ensure seeds return names, not IDs
        names: Dict[str, str] = dict(seed_names) if seed_names else {}
        current_ids = list(seed_entity_ids)
        
        # HOP 0: Vector expansion - discover semantically similar entities regardless of edges
        # This is critical for finding isolated entities (e.g., Exhibit A details)
        try:
            async with self._get_session() as session:
                result = await session.run(
                    vector_expansion_query,
                    query_embedding=query_embedding,
                    group_id=group_id,
                    top_k=beam_width * 2,  # Oversample for filtering
                    beam_width=beam_width,
                )
                vector_records = await result.data()
            
            # Add vector-matched entities to the beam with slightly lower initial score
            vector_boost_count = 0
            for r in vector_records:
                eid = r["id"]
                sim = float(r["similarity"])
                if eid not in scores:
                    # Slight penalty vs seed entities (0.9 vs 1.0)
                    scores[eid] = sim * 0.9
                    names[eid] = r["name"]
                    current_ids.append(eid)
                    vector_boost_count += 1
            
            if vector_boost_count > 0:
                logger.info(
                    "semantic_beam_vector_expansion group=%s vector_entities=%d",
                    group_id,
                    vector_boost_count,
                )
        except Exception as e:
            # Log but don't fail - fall back to relationship-only traversal
            logger.warning("semantic_beam_vector_expansion_failed: %s", str(e))

        for hop in range(max_hops):
            if not current_ids:
                break

            async with self._get_session() as session:
                # Pass knn_config only if the query uses it (not baseline)
                params = {
                    "current_ids": current_ids,
                    "group_id": group_id,
                    "query_embedding": query_embedding,
                    "beam_width": beam_width,
                }
                if knn_config:
                    params["knn_config"] = knn_config
                    
                result = await session.run(hop_query, **params)
                records = await result.data()

            if not records:
                break

            # Accumulate scores with damping
            hop_factor = damping ** (hop + 1)
            next_ids: List[str] = []
            for r in records:
                eid = r["id"]
                sim = float(r["similarity"])
                added_score = hop_factor * sim
                scores[eid] = scores.get(eid, 0.0) + added_score
                names[eid] = r["name"]
                next_ids.append(eid)

            # Keep top beam_width for next hop
            sorted_ids = sorted(next_ids, key=lambda x: scores.get(x, 0), reverse=True)
            current_ids = sorted_ids[:beam_width]

        dt_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "semantic_multihop_beam_complete",
            group_id=group_id,
            seeds=len(seed_entity_ids),
            max_hops=max_hops,
            beam_width=beam_width,
            results=len(scores),
            duration_ms=dt_ms,
            knn_config=knn_config or "baseline",
        )

        # Return sorted by accumulated score
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [(names.get(eid, eid), score) for eid, score in ranked]

    # =========================================================================
    # Batch Operations
    # =========================================================================
    
    async def batch_execute(
        self,
        queries: List[Tuple[str, Dict[str, Any]]],
    ) -> List[List[Dict[str, Any]]]:
        """
        Execute multiple queries in a single transaction (batch).
        
        Args:
            queries: List of (cypher_query, params) tuples
            
        Returns:
            List of result sets, one per query
        """
        results = []
        
        async with self._get_session() as session:
            tx = await session.begin_transaction()
            try:
                for query, params in queries:
                    # Cast to str to satisfy Neo4j type checker
                    result = await tx.run(str(query), **params)  # type: ignore[arg-type]
                    records = await result.data()
                    results.append(records)
                await tx.commit()
            except Exception:
                await tx.rollback()
                raise
        
        return results

    async def execute_read(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a read-only Cypher query and return results as a list of dicts.
        
        This is a generic query method for ad-hoc reads that don't warrant
        their own dedicated method.
        
        Args:
            query: Cypher query string
            params: Query parameters
            
        Returns:
            List of record dicts
        """
        async with self._get_session() as session:
            result = await session.run(query, **(params or {}))
            records = await result.data()
            return records

    async def detect_embedding_version(self, group_id: str) -> str:
        """
        Detect which embedding version a group uses (V1 OpenAI or V2 Voyage).
        
        Checks if entities in the group have embedding_v2 property (V2 Voyage 2048D)
        or only embedding property (V1 OpenAI 3072D).
        
        Args:
            group_id: The group ID to check
            
        Returns:
            "v2" if group has embedding_v2 properties, "v1" otherwise
        """
        query = """
        MATCH (e:Entity {group_id: $group_id})
        WHERE e.embedding_v2 IS NOT NULL
        RETURN count(e) AS v2_count
        LIMIT 1
        """
        try:
            async with self._get_session() as session:
                result = await session.run(query, group_id=group_id)
                record = await result.single()
                if record and record["v2_count"] > 0:
                    logger.info("embedding_version_detected", extra={"group_id": group_id, "version": "v2"})
                    return "v2"
                logger.info("embedding_version_detected", extra={"group_id": group_id, "version": "v1"})
                return "v1"
        except Exception as e:
            logger.warning("embedding_version_detection_failed", extra={"group_id": group_id, "error": str(e)})
            return "v1"  # Default to V1 for safety

    # =========================================================================
    # Document-Aware Retrieval — Target Document Resolution (February 10, 2026)
    # =========================================================================

    async def get_entity_document_coverage(
        self,
        group_id: str,
        entity_names: List[str],
    ) -> List[Dict[str, Any]]:
        """
        For each seed entity, find which documents it appears in via
        APPEARS_IN_DOCUMENT edges.  Returns per-document coverage stats
        used by the document-scoping algorithm.

        Returns list of dicts:
            [{doc_id, doc_title, matching_seeds: [str], seed_coverage: int,
              entity_doc_counts: {entity_name: num_docs_it_spans}}]
        """
        query = """
        UNWIND $entity_names AS ename
        MATCH (e)-[:APPEARS_IN_DOCUMENT]->(d:Document {group_id: $group_id})
        WHERE (e:Entity OR e:`__Entity__`) AND e.group_id = $group_id
          AND (toLower(e.name) = toLower(ename)
               OR ANY(alias IN coalesce(e.aliases, [])
                      WHERE toLower(alias) = toLower(ename)))
        WITH ename, d, count(DISTINCT d) AS _dummy
        // Per-entity: how many distinct docs does this entity span?
        WITH ename, d,
             size([(e2)-[:APPEARS_IN_DOCUMENT]->(d2:Document {group_id: $group_id})
                   WHERE (e2:Entity OR e2:`__Entity__`) AND e2.group_id = $group_id
                     AND (toLower(e2.name) = toLower(ename)
                          OR ANY(a IN coalesce(e2.aliases, []) WHERE toLower(a) = toLower(ename)))
                   | d2]) AS entity_doc_count
        WITH d.id AS doc_id, d.title AS doc_title,
             collect(DISTINCT {name: ename, doc_count: entity_doc_count}) AS seed_info
        RETURN doc_id, doc_title,
               [s IN seed_info | s.name] AS matching_seeds,
               size(seed_info) AS seed_coverage,
               seed_info
        ORDER BY seed_coverage DESC
        """
        try:
            async with self._get_session() as session:
                result = await session.run(
                    query,
                    group_id=group_id,
                    entity_names=entity_names,
                )
                records = await result.data()

            # Build per-entity doc count map from the first record that has all
            entity_doc_counts: Dict[str, int] = {}
            for rec in records:
                for info in rec.get("seed_info", []):
                    name = info["name"]
                    if name not in entity_doc_counts:
                        entity_doc_counts[name] = info["doc_count"]

            # Attach to each record for downstream convenience
            for rec in records:
                rec["entity_doc_counts"] = entity_doc_counts

            logger.info(
                "entity_document_coverage",
                num_entities=len(entity_names),
                num_docs=len(records),
                top_doc=records[0]["doc_title"] if records else None,
                top_coverage=records[0]["seed_coverage"] if records else 0,
            )
            return records

        except Exception as e:
            logger.warning("entity_document_coverage_failed", error=str(e))
            return []
