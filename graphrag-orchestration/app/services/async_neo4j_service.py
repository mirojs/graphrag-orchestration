"""
Async-native Neo4j Service for high-performance graph queries.

Uses Neo4j's native AsyncGraphDatabase driver for true non-blocking I/O.
This is optimized for Route 2/3 hot paths where latency is critical.

Key features:
- True async/await (no thread pool overhead)
- Connection pooling with async driver
- Optimized for read-heavy graph traversal queries
- Multi-tenant isolation via group_id filtering

Usage:
    async with AsyncNeo4jService.from_settings() as service:
        entities = await service.get_entities_by_importance(group_id, top_k=50)
        neighbors = await service.expand_neighbors(group_id, entity_ids, depth=2)
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from neo4j.exceptions import Neo4jError

from app.core.config import settings

logger = logging.getLogger(__name__)


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
        """
        Get top entities by importance score (native async).
        
        Uses pre-computed importance_score from entity importance scoring.
        """
        query = """
        MATCH (e:`__Entity__`)
        WHERE e.group_id = $group_id 
          AND coalesce(e.importance_score, 0) >= $min_importance
        RETURN e.id AS id, 
               e.name AS name, 
               e.degree AS degree,
               e.chunk_count AS chunk_count,
               e.importance_score AS importance_score,
               labels(e) AS labels
        ORDER BY e.importance_score DESC
        LIMIT $top_k
        """
        
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
    ) -> List[Dict[str, Any]]:
        """
        Get specific entities by name (case-insensitive).
        """
        query = """
        UNWIND $names AS name
        MATCH (e:`__Entity__`)
        WHERE e.group_id = $group_id 
          AND toLower(e.name) = toLower(name)
        RETURN e.id AS id,
               e.name AS name,
               e.degree AS degree,
               e.chunk_count AS chunk_count,
               coalesce(e.degree, 0) AS importance_score
        """
        
        async with self._get_session() as session:
            result = await session.run(query, group_id=group_id, names=entity_names)
            records = await result.data()
            return records
    
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
        query = f"""
        UNWIND $entity_ids AS eid
        MATCH (seed:`__Entity__` {{id: eid}})
        WHERE seed.group_id = $group_id
        MATCH path = (seed)-[r*1..{depth}]-(neighbor:`__Entity__`)
        WHERE neighbor.group_id = $group_id
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
        """
        
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
        query = """
        MATCH (e:`__Entity__` {id: $entity_id})-[r]-(other:`__Entity__`)
        WHERE e.group_id = $group_id AND other.group_id = $group_id
          AND type(r) <> 'MENTIONS'
        RETURN e.name AS source,
               type(r) AS relationship,
               other.name AS target,
               other.id AS target_id,
               coalesce(other.degree, 0) AS target_importance
        LIMIT $limit
        """
        
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
    ) -> List[Tuple[str, float]]:
        """
        Native Cypher approximation of Personalized PageRank.
        
        This uses iterative neighbor expansion with decay - not true PPR,
        but provides similar "spread from seeds" behavior without GDS.
        
        For true PPR, consider:
        1. Install GDS Community (free for self-managed Neo4j)
        2. Use NetworkX in Python (slower but more accurate)
        """
        # Multi-hop expansion with distance-based decay (PPR approximation)
        query = """
        // Start from seeds with score 1.0
        UNWIND $seed_ids AS seed_id
        MATCH (seed:`__Entity__` {id: seed_id})
        WHERE seed.group_id = $group_id
        
        // Expand 3 hops with decay
        OPTIONAL MATCH path = (seed)-[*1..3]-(neighbor:`__Entity__`)
        WHERE neighbor.group_id = $group_id
          AND ALL(r IN relationships(path) WHERE type(r) <> 'MENTIONS')
        
        WITH neighbor, 
             seed,
             CASE 
               WHEN neighbor IS NULL THEN 0
               ELSE pow($damping, length(path))  // Decay by distance
             END AS contribution
        
        // Aggregate scores across all seeds
        WITH coalesce(neighbor, seed) AS entity,
             sum(contribution) AS raw_score
        
        // Normalize and return top-K
        WITH entity, raw_score
        WHERE raw_score > 0
        RETURN entity.id AS id,
               entity.name AS name,
               raw_score AS score,
               coalesce(entity.degree, 0) AS importance
        ORDER BY raw_score DESC
        LIMIT $top_k
        """
        
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                seed_ids=seed_entity_ids,
                damping=damping,
                top_k=top_k,
            )
            records = await result.data()
            
            # Return as (name, score) tuples for compatibility
            return [(r["name"], r["score"]) for r in records]
    
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
        query = """
        UNWIND $entity_ids AS eid
        MATCH (e:`__Entity__` {id: eid})-[:MENTIONS]->(c)
        WHERE e.group_id = $group_id
          AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
        WITH DISTINCT c
        RETURN c.id AS chunk_id,
               c.text AS text,
               c.url AS url,
               c.page_number AS page,
               c.section_path AS section_path
        LIMIT $limit
        """
        
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
        query = """
        MATCH (c)
        WHERE c.group_id = $group_id 
          AND c.url = $doc_url
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
        """
        
        async with self._get_session() as session:
            result = await session.run(
                query,
                group_id=group_id,
                doc_url=doc_url,
                keywords=field_keywords,
            )
            record = await result.single()
            
            if record:
                return True, record.get("section_path")
            return False, None
    
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
