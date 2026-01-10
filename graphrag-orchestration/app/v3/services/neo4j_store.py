"""
Neo4j Store for V3 GraphRAG

This module provides a unified Neo4j storage layer for all V3 data types:
- Entities and Relationships (GraphRAG)
- Communities (hierarchical, from graspologic)
- RAPTOR nodes (hierarchical summaries)
- Text chunks (with embeddings)
- Documents (metadata)

All operations include group_id for multi-tenancy.
"""

import logging
import uuid
import json
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, cast
from dataclasses import dataclass, field

import neo4j
from neo4j import GraphDatabase, AsyncGraphDatabase
from neo4j import Query

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Entity node data."""
    id: str
    name: str
    type: str
    description: str = ""
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    text_unit_ids: List[str] = field(default_factory=list)  # For DRIFT MENTIONS relationships


@dataclass
class Relationship:
    """Relationship edge data."""
    source_id: str
    target_id: str
    type: str = "RELATED_TO"
    description: str = ""
    weight: float = 1.0
    id: Optional[str] = None
    
    def __post_init__(self):
        if self.id is None:
            self.id = f"{self.source_id}->{self.target_id}"


@dataclass
class Community:
    """Community node data."""
    id: str
    level: int
    title: str = ""
    summary: str = ""
    full_content: str = ""
    rank: float = 0.0
    entity_ids: List[str] = field(default_factory=list)


@dataclass
class RaptorNode:
    """RAPTOR tree node data."""
    id: str
    text: str
    level: int
    embedding: Optional[List[float]] = None
    parent_id: Optional[str] = None
    child_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class TextChunk:
    """Text chunk (text unit) data."""
    id: str
    text: str
    chunk_index: int
    document_id: str
    embedding: Optional[List[float]] = None
    tokens: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """Document metadata."""
    id: str
    title: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class Neo4jStoreV3:
    """
    Unified Neo4j store for V3 GraphRAG.
    
    This is the single source of truth for all query-time data.
    All data types are stored in Neo4j with proper indexes.
    """
    
    # Neo4j schema version for migrations
    SCHEMA_VERSION = "3.0.0"
    
    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
    ):
        """Initialize Neo4j connection."""
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self._driver = None
        self._async_driver = None

        # Determinism: chunk-level extraction cache schema init (best-effort).
        self._extraction_cache_schema_ready: bool = False
        self._extraction_cache_schema_lock: asyncio.Lock = asyncio.Lock()
        
    @property
    def driver(self) -> neo4j.Driver:
        """Lazy initialization of Neo4j driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
            )
            # Verify connectivity
            self._driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {self.uri}")
        return self._driver
    
    @property
    def async_driver(self) -> neo4j.AsyncDriver:
        """Lazy initialization of async Neo4j driver."""
        if self._async_driver is None:
            self._async_driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
            )
            logger.info(f"Connected to Neo4j (async) at {self.uri}")
        return self._async_driver
    
    def close(self):
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None
    
    async def aclose(self):
        """Close the async Neo4j driver."""
        if self._async_driver:
            await self._async_driver.close()
            self._async_driver = None

        self._extraction_cache_schema_ready = False

    async def _aensure_extraction_cache_schema(self) -> None:
        """Ensure ExtractionCache schema exists (best-effort).

        Neo4j emits notifications (UnknownLabel/UnknownPropertyKey) when querying
        labels/properties that haven't been created yet. Creating the constraint
        once up-front suppresses those notifications and improves lookup speed.
        """

        if self._extraction_cache_schema_ready:
            return

        async with self._extraction_cache_schema_lock:
            if self._extraction_cache_schema_ready:
                return

            try:
                async with self.async_driver.session(database=self.database) as session:
                    await session.run(
                        "CREATE CONSTRAINT extraction_cache_key IF NOT EXISTS FOR (c:ExtractionCache) REQUIRE c.key IS UNIQUE"
                    )
                self._extraction_cache_schema_ready = True
            except Exception as e:
                # Caching is optional; never fail the indexing request because of it.
                logger.warning(f"Failed to ensure ExtractionCache schema (continuing): {e}")
    
    # ==================== Schema Management ====================
    
    def initialize_schema(self):
        """
        Create all required constraints, indexes, and vector indexes.
        
        Call this once during deployment or when schema changes.
        """
        logger.info("Initializing Neo4j schema for V3...")
        
        schema_queries = [
            # Constraints (unique IDs)
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT raptor_id IF NOT EXISTS FOR (r:RaptorNode) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (t:TextChunk) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",

            # Determinism: chunk-level extraction cache
            "CREATE CONSTRAINT extraction_cache_key IF NOT EXISTS FOR (c:ExtractionCache) REQUIRE c.key IS UNIQUE",
            
            # Regular indexes for filtering
            "CREATE INDEX entity_group IF NOT EXISTS FOR (e:Entity) ON (e.group_id)",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            "CREATE INDEX community_group IF NOT EXISTS FOR (c:Community) ON (c.group_id)",
            
            # Full-text index for hybrid search (keyword matching)
            "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]",
            "CREATE INDEX community_level IF NOT EXISTS FOR (c:Community) ON (c.level)",
            "CREATE INDEX raptor_group IF NOT EXISTS FOR (r:RaptorNode) ON (r.group_id)",
            "CREATE INDEX raptor_level IF NOT EXISTS FOR (r:RaptorNode) ON (r.level)",
            "CREATE INDEX chunk_group IF NOT EXISTS FOR (t:TextChunk) ON (t.group_id)",
            "CREATE INDEX document_group IF NOT EXISTS FOR (d:Document) ON (d.group_id)",
        ]
        
        # Vector indexes (separate because they need special syntax)
        # NOTE: Commented out drop logic to avoid timeouts during schema initialization
        # If dimensions need changing, manually drop indexes via Neo4j Browser
        # vector_indexes_to_drop = [
        #     "DROP INDEX entity_embedding IF EXISTS",
        #     "DROP INDEX raptor_embedding IF EXISTS",
        #     "DROP INDEX chunk_embedding IF EXISTS",
        # ]
        
        # Native Vector Type indexes (Neo4j 5.13+)
        # Note: If upgrading from list-based embeddings, you must:
        #   1. DROP old indexes
        #   2. Convert properties: SET e.embedding = null then use db.create.setVectorProperty
        #   3. CREATE new indexes with updated config
        vector_indexes = [
            """
            CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
            FOR (e:Entity) ON (e.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 1536,
                `vector.similarity_function`: 'cosine'
            }}
            """,
            """
            CREATE VECTOR INDEX raptor_embedding IF NOT EXISTS
            FOR (r:RaptorNode) ON (r.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 3072,
                `vector.similarity_function`: 'cosine'
            }}
            """,
            """
            CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
            FOR (t:TextChunk) ON (t.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 3072,
                `vector.similarity_function`: 'cosine'
            }}
            """,
        ]
        
        with self.driver.session(database=self.database) as session:
            for query in schema_queries:
                try:
                    session.run(Query(query))  # type: ignore[arg-type]
                    logger.debug(f"Executed: {query[:50]}...")
                except Exception as e:
                    logger.warning(f"Schema query failed (may already exist): {e}")
            
            # NOTE: Vector index drops commented out to avoid timeouts
            # If dimensions need changing, manually drop via Neo4j Browser:
            # DROP INDEX entity_embedding IF EXISTS
            # DROP INDEX raptor_embedding IF EXISTS  
            # DROP INDEX chunk_embedding IF EXISTS
            
            # Create vector indexes with correct dimensions
            for query in vector_indexes:
                try:
                    session.run(Query(query))  # type: ignore[arg-type]
                    logger.info(f"Created vector index with 3072 dimensions")
                except Exception as e:
                    logger.warning(f"Vector index creation failed: {e}")
        
        logger.info("Neo4j schema initialization complete")

    # ==================== Extraction Cache (Determinism) ====================

    async def aget_extraction_cache_batch(self, keys: List[str]) -> Dict[str, str]:
        """Fetch extraction-cache payloads by key.

        Returns a dict of key -> payload_json for the keys that exist.
        """
        if not keys:
            return {}

        await self._aensure_extraction_cache_schema()

        query = """
        UNWIND $keys AS k
        OPTIONAL MATCH (c:ExtractionCache {key: k})
        RETURN k AS key, c['payload'] AS payload
        """

        async with self.async_driver.session(database=self.database) as session:
            result = await session.run(query, keys=keys)
            out: Dict[str, str] = {}
            async for record in result:
                key = cast(str, record.get("key"))
                payload = record.get("payload")
                if key and payload:
                    out[key] = cast(str, payload)
            return out

    async def aput_extraction_cache_batch(
        self,
        items: List[Dict[str, Any]],
    ) -> int:
        """Upsert extraction-cache payloads.

        Each item should include: key, payload, model (optional), params_hash (optional).
        """
        if not items:
            return 0

        await self._aensure_extraction_cache_schema()

        query = """
        UNWIND $items AS item
        MERGE (c:ExtractionCache {key: item.key})
        ON CREATE SET
            c.payload = item.payload,
            c.model = coalesce(item.model, ''),
            c.params_hash = coalesce(item.params_hash, ''),
            c.created_at = datetime(),
            c.updated_at = datetime(),
            c.hits = 0
        ON MATCH SET
            c.model = coalesce(item.model, c.model),
            c.params_hash = coalesce(item.params_hash, c.params_hash),
            c.updated_at = datetime()
        SET c.hits = coalesce(c.hits, 0) + 1
        RETURN count(c) AS count
        """

        async with self.async_driver.session(database=self.database) as session:
            result = await session.run(query, items=items)
            record = await result.single()
            return cast(int, record["count"]) if record and record.get("count") is not None else 0
    
    # ==================== Entity Operations ====================
    
    def upsert_entity(self, group_id: str, entity: Entity) -> str:
        """Insert or update an entity using native vector storage."""
        query = """
        MERGE (e:Entity {id: $id})
        SET e.name = $name,
            e.type = $type,
            e.description = $description,
            e.group_id = $group_id,
            e.updated_at = datetime()
        WITH e
        FOREACH (_ IN CASE WHEN $embedding IS NOT NULL THEN [1] ELSE [] END |
            SET e.embedding = $embedding
        )
        RETURN e.id AS id
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                id=entity.id,
                name=entity.name,
                type=entity.type,
                description=entity.description,
                embedding=entity.embedding,
                group_id=group_id,
            )
            record = result.single()
            return cast(str, record["id"]) if record else entity.id
    
    def upsert_entities_batch(self, group_id: str, entities: List[Entity]) -> int:
        """Batch insert/update entities with native vector support."""
        
        # Diagnostic: Check embeddings before storing
        with_embeddings = sum(1 for e in entities if e.embedding and len(e.embedding) > 0)
        logger.warning(f"🔍 UPSERT CHECK: Storing {len(entities)} entities, {with_embeddings} have embeddings")
        if entities and entities[0].embedding:
            logger.warning(f"   First entity embedding dim: {len(entities[0].embedding)}")
        
        query = """
        UNWIND $entities AS e
        MERGE (entity:Entity {id: e.id})
        SET entity.name = e.name,
            entity.type = e.type,
            entity.description = e.description,
            entity.group_id = $group_id,
            entity.updated_at = datetime()
        
        WITH entity, e
        FOREACH (_ IN CASE WHEN e.embedding IS NOT NULL AND size(e.embedding) > 0 THEN [1] ELSE [] END |
            SET entity.embedding = e.embedding
        )
        
        // Create MENTIONS relationships to chunks for DRIFT
        WITH entity, e
        UNWIND e.text_unit_ids AS chunk_id
        MATCH (chunk:TextChunk {id: chunk_id, group_id: $group_id})
        MERGE (chunk)-[:MENTIONS]->(entity)
        
        RETURN count(DISTINCT entity) AS count
        """
        
        entity_data = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "embedding": e.embedding,
                "text_unit_ids": e.text_unit_ids if hasattr(e, 'text_unit_ids') else [],
            }
            for e in entities
        ]
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, entities=entity_data, group_id=group_id)
            record = result.single()
            count = cast(int, record["count"]) if record else 0
            
            # Log MENTIONS creation
            mentions_count = sum(len(e.text_unit_ids) if hasattr(e, 'text_unit_ids') else 0 for e in entities)
            logger.info(f"Created {count} entities with {mentions_count} MENTIONS relationships")
            
            return count
    
    async def aupsert_entities_batch(self, group_id: str, entities: List[Entity]) -> int:
        """Async batch insert/update entities with native vector support."""
        
        # Diagnostic: Check embeddings before storing
        with_embeddings = sum(1 for e in entities if e.embedding and len(e.embedding) > 0)
        logger.warning(f"🔍 ASYNC UPSERT CHECK: Storing {len(entities)} entities, {with_embeddings} have embeddings")
        if entities and entities[0].embedding:
            logger.warning(f"   First entity embedding dim: {len(entities[0].embedding)}")
        
        query = """
        UNWIND $entities AS e
        MERGE (entity:Entity {id: e.id})
        SET entity.name = e.name,
            entity.type = e.type,
            entity.description = e.description,
            entity.group_id = $group_id,
            entity.updated_at = datetime()
        
        WITH entity, e
        FOREACH (_ IN CASE WHEN e.embedding IS NOT NULL AND size(e.embedding) > 0 THEN [1] ELSE [] END |
            SET entity.embedding = e.embedding
        )
        
        // Create MENTIONS relationships to chunks for DRIFT
        WITH entity, e
        UNWIND e.text_unit_ids AS chunk_id
        MATCH (chunk:TextChunk {id: chunk_id, group_id: $group_id})
        MERGE (chunk)-[:MENTIONS]->(entity)
        
        RETURN count(DISTINCT entity) AS count
        """
        
        entity_data = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "embedding": e.embedding,
                "text_unit_ids": e.text_unit_ids if hasattr(e, 'text_unit_ids') else [],
            }
            for e in entities
        ]
        
        async with self.async_driver.session(database=self.database) as session:
            result = await session.run(query, entities=entity_data, group_id=group_id)
            record = await result.single()
            count = cast(int, record["count"]) if record else 0
            
            # Log MENTIONS creation
            mentions_count = sum(len(e.text_unit_ids) if hasattr(e, 'text_unit_ids') else 0 for e in entities)
            logger.info(f"Created {count} entities with {mentions_count} MENTIONS relationships (async)")
            
            return count
    
    def get_entity(self, group_id: str, entity_id: str) -> Optional[Entity]:
        """Get an entity by ID."""
        query = """
        MATCH (e:Entity {id: $id, group_id: $group_id})
        RETURN e
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, id=entity_id, group_id=group_id)
            record = result.single()
            if record:
                e = record["e"]
                return Entity(
                    id=e["id"],
                    name=e["name"],
                    type=e["type"],
                    description=e.get("description", ""),
                    embedding=e.get("embedding"),
                )
            return None
    
    def search_entities_hybrid(
        self,
        group_id: str,
        query_text: str,
        embedding: List[float],
        top_k: int = 10,
    ) -> List[Tuple[Entity, float]]:
        """
        Hybrid search combining vector similarity and keyword matching with RRF and Quality Boost.
        
        Implements "Hybrid+Boost" strategy:
        1. Vector search (semantic similarity) using native vector index/functions
        2. Full-text search (exact keyword matching)
        3. RRF Fusion
        4. Quality/RAPTOR Boost (boosting entities in high-ranking communities)
        
        Args:
            group_id: Tenant identifier
            query_text: Original query string for keyword matching
            embedding: Query embedding for vector search
            top_k: Number of final results to return
            
        Returns:
            List of (Entity, combined_score) tuples sorted by fused rank
        """
        k_constant = 60  # RRF constant
        candidate_k = max(top_k * 3, 20)  # Retrieve more for fusion
        
        query = """
        // Step 1: Vector Search (Native - using vector.similarity.cosine)
        MATCH (e:Entity {group_id: $group_id})
        WHERE e.embedding IS NOT NULL
        WITH e, vector.similarity.cosine(e.embedding, $embedding) AS vectorScore
        ORDER BY vectorScore DESC
        LIMIT $retrieval_k
        WITH collect({node: e, score: vectorScore}) AS vectorResults
        
        // Step 2: Full-text Search
        OPTIONAL CALL db.index.fulltext.queryNodes('entity_fulltext', $query_text, {limit: $retrieval_k})
        YIELD node AS fNode, score AS fScore
        WHERE fNode.group_id = $group_id
        WITH vectorResults, collect({node: fNode, score: fScore}) AS textResults
        
        // Step 3: RRF Fusion
        WITH vectorResults + textResults AS allResults
        UNWIND range(0, size(allResults)-1) AS idx
        WITH allResults[idx] AS result, idx
        WITH result.node AS node,
             sum(1.0 / ($k_constant + idx + 1)) AS rrfScore
        
        // Step 4: Quality/RAPTOR Boost
        // Boost entities that belong to high-ranking communities (RAPTOR/Leiden)
        OPTIONAL MATCH (node)-[:BELONGS_TO]->(c:Community)
        WITH node, rrfScore, coalesce(max(c.rank), 0.0) AS communityRank
        
        // Apply boost: 5% boost per rank unit to avoid over-weighting community membership
        // This ensures factual accuracy from vector search remains primary signal
        WITH node, rrfScore * (1.0 + (communityRank * 0.05)) AS finalScore
        
        RETURN node, finalScore
        ORDER BY finalScore DESC
        LIMIT $top_k
        """
        
        results = []
        with self.driver.session(database=self.database) as session:
            try:
                result = session.run(
                    query,
                    embedding=embedding,
                    query_text=query_text,
                    retrieval_k=candidate_k,
                    k_constant=k_constant,
                    top_k=top_k,
                    group_id=group_id,
                )
                for record in result:
                    e = record["node"]
                    entity = Entity(
                        id=e["id"],
                        name=e["name"],
                        type=e["type"],
                        description=e.get("description", ""),
                        embedding=e.get("embedding"),
                    )
                    results.append((entity, record["finalScore"]))
            except Exception as ex:
                logger.error(f"Hybrid search failed: {ex}")
                # Fallback to vector-only search
                logger.info("Falling back to vector-only search")
                return self.search_entities_by_embedding(group_id, embedding, top_k)
        
        return results
    
    def search_entities_by_embedding(
        self,
        group_id: str,
        embedding: List[float],
        top_k: int = 10,
    ) -> List[Tuple[Entity, float]]:
        """Vector similarity search for entities using native vector index."""
        query = """
        CALL db.index.vector.queryNodes('entity_embedding', $top_k, $embedding)
        YIELD node, score
        WHERE node.group_id = $group_id
        RETURN node, score
        ORDER BY score DESC
        """
        
        results = []
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                embedding=embedding,
                top_k=top_k,
                group_id=group_id,
            )
            for record in result:
                e = record["node"]
                entity = Entity(
                    id=e["id"],
                    name=e["name"],
                    type=e["type"],
                    description=e.get("description", ""),
                    embedding=e.get("embedding"),
                )
                results.append((entity, record["score"]))
        
        return results
    
    def search_entities_by_numeric_content(
        self,
        group_id: str,
        top_k: int = 10,
    ) -> List[Tuple[Entity, float]]:
        """
        Search for entities with numeric content (amounts, values, etc).
        
        Prioritizes entities that mention financial amounts, quantities, or dates.
        Useful for locating invoice amounts, contract values, etc.
        """
        query = """
        MATCH (e:Entity {group_id: $group_id})
        WHERE e.description CONTAINS '$' 
           OR e.description CONTAINS 'amount' 
           OR e.description CONTAINS 'invoice' 
           OR e.description CONTAINS 'cost'
           OR e.description CONTAINS 'price'
           OR e.name CONTAINS '$'
        RETURN e, 
               CASE 
                   WHEN e.description CONTAINS 'invoice' THEN 5
                   WHEN e.description CONTAINS '$' THEN 4
                   WHEN e.description CONTAINS 'amount' THEN 3
                   WHEN e.description CONTAINS 'cost' THEN 2
                   WHEN e.description CONTAINS 'price' THEN 1
                   ELSE 0
               END AS relevance_score
        ORDER BY relevance_score DESC
        LIMIT $top_k
        """
        
        results = []
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                group_id=group_id,
                top_k=top_k,
            )
            for record in result:
                e = record["e"]
                entity = Entity(
                    id=e["id"],
                    name=e["name"],
                    type=e["type"],
                    description=e.get("description", ""),
                    embedding=e.get("embedding"),
                )
                # Normalize relevance score to 0-1 range for consistency
                score = float(record["relevance_score"]) / 5.0
                results.append((entity, score))
        
        return results
    
    # ==================== Relationship Operations ====================
    
    def upsert_relationship(self, group_id: str, relationship: Relationship) -> str:
        """Insert or update a relationship."""
        query = """
        MATCH (source:Entity {id: $source_id, group_id: $group_id})
        MATCH (target:Entity {id: $target_id, group_id: $group_id})
        MERGE (source)-[r:RELATED_TO]->(target)
        SET r.id = $id,
            r.description = $description,
            r.weight = $weight,
            r.group_id = $group_id,
            r.updated_at = datetime()
        RETURN r.id AS id
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                source_id=relationship.source_id,
                target_id=relationship.target_id,
                id=relationship.id,
                description=relationship.description,
                weight=relationship.weight,
                group_id=group_id,
            )
            record = result.single()
            return cast(str, record["id"]) if record else (relationship.id or "")
    
    def upsert_relationships_batch(self, group_id: str, relationships: List[Relationship]) -> int:
        """Batch insert/update relationships."""
        query = """
        UNWIND $relationships AS rel
        MATCH (source:Entity {id: rel.source_id, group_id: $group_id})
        MATCH (target:Entity {id: rel.target_id, group_id: $group_id})
        MERGE (source)-[r:RELATED_TO]->(target)
        SET r.id = rel.id,
            r.description = rel.description,
            r.weight = rel.weight,
            r.group_id = $group_id,
            r.updated_at = datetime()
        RETURN count(r) AS count
        """
        
        rel_data = [
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "id": r.id,
                "description": r.description,
                "weight": r.weight,
            }
            for r in relationships
        ]
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, relationships=rel_data, group_id=group_id)
            record = result.single()
            return cast(int, record["count"]) if record else 0
    
    # ==================== Community Operations ====================
    
    def upsert_community(self, group_id: str, community: Community) -> str:
        """Insert or update a community."""
        query = """
        MERGE (c:Community {id: $id})
        SET c.level = $level,
            c.title = $title,
            c.summary = $summary,
            c.full_content = $full_content,
            c.rank = $rank,
            c.group_id = $group_id,
            c.updated_at = datetime()
        RETURN c.id AS id
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                id=community.id,
                level=community.level,
                title=community.title,
                summary=community.summary,
                full_content=community.full_content,
                rank=community.rank,
                group_id=group_id,
            )
            record = result.single()
            
            # Link entities to community
            if community.entity_ids:
                link_query = """
                MATCH (c:Community {id: $community_id})
                UNWIND $entity_ids AS entity_id
                MATCH (e:Entity {id: entity_id, group_id: $group_id})
                MERGE (e)-[:BELONGS_TO]->(c)
                """
                session.run(
                    link_query,
                    community_id=community.id,
                    entity_ids=community.entity_ids,
                    group_id=group_id,
                )
            
            return cast(str, record["id"]) if record else community.id
    
    def get_communities_by_level(self, group_id: str, level: int) -> List[Community]:
        """Get all communities at a specific level."""
        query = """
        MATCH (c:Community {group_id: $group_id, level: $level})
        OPTIONAL MATCH (e:Entity)-[:BELONGS_TO]->(c)
        RETURN c, collect(DISTINCT e.id) AS entity_ids
        ORDER BY c.rank DESC
        """
        
        communities = []
        with self.driver.session(database=self.database) as session:
            result = session.run(query, group_id=group_id, level=level)
            for record in result:
                c = record["c"]
                communities.append(Community(
                    id=c["id"],
                    level=c["level"],
                    title=c.get("title", ""),
                    summary=c.get("summary", ""),
                    full_content=c.get("full_content", ""),
                    rank=c.get("rank", 0.0),
                    entity_ids=record["entity_ids"],
                ))
        
        return communities

    def get_community_levels(self, group_id: str) -> List[int]:
        """Return sorted distinct community levels for a group."""
        query = """
        MATCH (c:Community {group_id: $group_id})
        RETURN DISTINCT c.level AS level
        ORDER BY level ASC
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(query, group_id=group_id)
            levels: list[int] = []
            for record in result:
                lvl = record.get("level")
                if isinstance(lvl, int):
                    levels.append(lvl)
            return levels

    def ensure_community_hierarchy(self, group_id: str) -> None:
        """Create parent-child edges between communities across adjacent levels.

        Dynamic Global Search needs a traversable community tree.
        Our indexing stores communities per level and entity membership; this method
        derives a hierarchy by assigning each child community to the parent community
        at the previous level with the highest entity overlap fraction.

        Relationship created:
            (child:Community)-[:PARENT_COMMUNITY]->(parent:Community)
        """
        levels = self.get_community_levels(group_id)
        if len(levels) < 2:
            return

        with self.driver.session(database=self.database) as session:
            # Clear existing edges for deterministic rebuild.
            session.run(
                """
                MATCH (c:Community {group_id: $group_id})-[r:PARENT_COMMUNITY]->(:Community)
                DELETE r
                """,
                group_id=group_id,
            )

            for parent_level, child_level in zip(levels, levels[1:]):
                # For each child community, pick the parent community that overlaps most.
                # Use overlap/child_size to avoid bias toward giant parents.
                session.run(
                    """
                    MATCH (child:Community {group_id: $group_id, level: $child_level})
                    OPTIONAL MATCH (ce:Entity {group_id: $group_id})-[:BELONGS_TO]->(child)
                    WITH child, collect(DISTINCT ce.id) AS child_eids
                    WHERE size(child_eids) > 0
                    MATCH (parent:Community {group_id: $group_id, level: $parent_level})
                    OPTIONAL MATCH (pe:Entity {group_id: $group_id})-[:BELONGS_TO]->(parent)
                    WITH child, child_eids, parent, collect(DISTINCT pe.id) AS parent_eids
                    WITH child, parent,
                         size([x IN child_eids WHERE x IN parent_eids]) AS overlap,
                         size(child_eids) AS child_size
                    WHERE overlap > 0
                    WITH child, parent, (overlap * 1.0 / child_size) AS frac
                    ORDER BY child.id, frac DESC
                    WITH child, collect({p: parent, f: frac})[0] AS best
                    WITH child, best.p AS parent
                    WHERE parent IS NOT NULL
                    MERGE (child)-[:PARENT_COMMUNITY]->(parent)
                    """,
                    group_id=group_id,
                    parent_level=parent_level,
                    child_level=child_level,
                )

    def get_child_communities(self, group_id: str, parent_id: str, child_level: int) -> List[Community]:
        """Fetch child communities linked to a parent community."""
        query = """
        MATCH (child:Community {group_id: $group_id, level: $child_level})-[:PARENT_COMMUNITY]->(parent:Community {id: $parent_id})
        OPTIONAL MATCH (e:Entity {group_id: $group_id})-[:BELONGS_TO]->(child)
        RETURN child AS c, collect(DISTINCT e.id) AS entity_ids
        ORDER BY child.rank DESC
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                group_id=group_id,
                parent_id=parent_id,
                child_level=child_level,
            )
            out: list[Community] = []
            for record in result:
                c = record["c"]
                out.append(
                    Community(
                        id=c["id"],
                        level=c["level"],
                        title=c.get("title", ""),
                        summary=c.get("summary", ""),
                        full_content=c.get("full_content", ""),
                        rank=c.get("rank", 0.0),
                        entity_ids=record.get("entity_ids") or [],
                    )
                )
            return out
    
    def get_entities_by_raptor_context(self, group_id: str, raptor_node_id: str, limit: int = 10) -> List[Entity]:
        """
        Get entities mentioned in the chunks summarized by a RAPTOR node.
        Used for DRIFT traversal (Summary -> Entity).
        """
        query = """
        MATCH (r:RaptorNode {id: $raptor_id})
        // Traverse down to chunks
        MATCH (r)<-[:SUMMARIZES*1..]-(c:TextChunk)
        // Find entities in these chunks
        MATCH (c)-[:MENTIONS]->(e:Entity)
        RETURN DISTINCT e
        LIMIT $limit
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(query, raptor_id=raptor_node_id, limit=limit)
            entities = []
            for record in result:
                e = record["e"]
                entities.append(Entity(
                    id=e["id"],
                    name=e["name"],
                    type=e["type"],
                    description=e.get("description", ""),
                    metadata=dict(e.get("metadata", {})),
                ))
            return entities

    def get_communities_by_raptor_context(self, group_id: str, raptor_node_ids: List[str]) -> List[Community]:
        """
        Get communities relevant to specific RAPTOR nodes.
        Used for 'Global + RAPTOR' pruning.
        """
        query = """
        MATCH (r:RaptorNode)
        WHERE r.id IN $raptor_ids
        // Traverse down to chunks
        MATCH (r)<-[:SUMMARIZES*1..]-(c:TextChunk)
        // Find entities in these chunks
        MATCH (c)-[:MENTIONS]->(e:Entity)
        // Find communities these entities belong to
        MATCH (e)-[:BELONGS_TO]->(comm:Community)
        WHERE comm.group_id = $group_id AND comm.level = 0
        OPTIONAL MATCH (e2:Entity {group_id: $group_id})-[:BELONGS_TO]->(comm)
        RETURN comm, collect(DISTINCT e2.id) AS entity_ids
        LIMIT 20
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(query, group_id=group_id, raptor_ids=raptor_node_ids)
            communities = []
            for record in result:
                c = record["comm"]
                communities.append(Community(
                    id=c["id"],
                    level=c["level"],
                    title=c.get("title", ""),
                    summary=c.get("summary", ""),
                    rank=c.get("rank", 0.0),
                    entity_ids=record.get("entity_ids") or [],
                ))
            return communities

    def get_entity_raptor_context(self, group_id: str, entity_id: str) -> Optional[RaptorNode]:
        """
        Get the parent RAPTOR node for an entity to provide thematic context.
        Traverses: Entity <- MENTIONS - TextChunk - SUMMARIZES -> RaptorNode
        """
        query = """
        MATCH (e:Entity {id: $entity_id})<-[:MENTIONS]-(c:TextChunk)-[:SUMMARIZES]->(r:RaptorNode)
        WHERE r.group_id = $group_id
        RETURN r
        ORDER BY r.level ASC
        LIMIT 1
        """
        with self.driver.session(database=self.database) as session:
            result = session.run(query, group_id=group_id, entity_id=entity_id)
            record = result.single()
            if record:
                node_data = record["r"]
                return RaptorNode(
                    id=node_data["id"],
                    text=node_data["text"],
                    level=node_data["level"],
                    metadata=dict(node_data.get("metadata", {})),
                )
        return None

    # ==================== RAPTOR Node Operations ====================
    
    def upsert_raptor_node(self, group_id: str, node: RaptorNode) -> str:
        """Insert or update a RAPTOR node using native vector storage."""
        query = """
        MERGE (r:RaptorNode {id: $id})
        SET r.text = $text,
            r.level = $level,
            r.group_id = $group_id,
            r.metadata = $metadata,
            r.child_ids = $child_ids,
            r.updated_at = datetime()
        WITH r
        FOREACH (_ IN CASE WHEN $embedding IS NOT NULL THEN [1] ELSE [] END |
            SET r.embedding = $embedding
        )
        
        WITH r
        UNWIND $child_ids AS child_id
        OPTIONAL MATCH (tc:TextChunk {id: child_id})
        FOREACH (_ IN CASE WHEN tc IS NOT NULL THEN [1] ELSE [] END | MERGE (tc)-[:SUMMARIZES]->(r))
        OPTIONAL MATCH (rn:RaptorNode {id: child_id})
        FOREACH (_ IN CASE WHEN rn IS NOT NULL THEN [1] ELSE [] END | MERGE (rn)-[:SUMMARIZES]->(r))
        
        RETURN r.id AS id
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                id=node.id,
                text=node.text,
                level=node.level,
                embedding=node.embedding,
                group_id=group_id,
                metadata=node.metadata,
                child_ids=node.child_ids,
            )
            record = result.single()
            
            # Link to parent if exists (legacy support)
            if node.parent_id:
                link_query = """
                MATCH (child:RaptorNode {id: $child_id})
                MATCH (parent:RaptorNode {id: $parent_id})
                MERGE (child)-[:SUMMARIZES]->(parent)
                """
                session.run(
                    link_query,
                    child_id=node.id,
                    parent_id=node.parent_id,
                )
            
            return cast(str, record["id"]) if record else node.id
    
    def upsert_raptor_nodes_batch(self, group_id: str, nodes: List[RaptorNode]) -> int:
        """Batch insert/update RAPTOR nodes with native vector support."""
        query = """
        UNWIND $nodes AS n
        MERGE (r:RaptorNode {id: n.id})
        SET r.text = n.text,
            r.level = n.level,
            r.group_id = $group_id,
            r.cluster_coherence = n.cluster_coherence,
            r.confidence_level = n.confidence_level,
            r.confidence_score = n.confidence_score,
            r.silhouette_score = n.silhouette_score,
            r.cluster_silhouette_avg = n.cluster_silhouette_avg,
            r.child_count = n.child_count,
            r.creation_model = n.creation_model,
            r.updated_at = datetime()
        
        WITH r, n
        FOREACH (_ IN CASE WHEN n.embedding IS NOT NULL AND size(n.embedding) > 0 THEN [1] ELSE [] END |
            SET r.embedding = n.embedding
        )
        
        RETURN count(r) AS count
        """
        
        node_data = [
            {
                "id": n.id,
                "text": n.text,
                "level": n.level,
                "embedding": n.embedding,
                "cluster_coherence": n.metadata.get("cluster_coherence", 0.0),
                "confidence_level": n.metadata.get("confidence_level", "unknown"),
                "confidence_score": n.metadata.get("confidence_score", 0.0),
                "silhouette_score": n.metadata.get("silhouette_score", 0.0),
                "cluster_silhouette_avg": n.metadata.get("cluster_silhouette_avg", 0.0),
                "child_count": n.metadata.get("child_count", 0),
                "creation_model": n.metadata.get("creation_model", ""),
            }
            for n in nodes
        ]
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, nodes=node_data, group_id=group_id)
            record = result.single()
            return cast(int, record["count"]) if record else 0
    
    def search_raptor_by_embedding(
        self,
        group_id: str,
        embedding: List[float],
        level: Optional[int] = None,
        top_k: int = 10,
    ) -> List[Tuple[RaptorNode, float]]:
        """Vector similarity search for RAPTOR nodes using native vector functions."""
        
        # Use native vector similarity for efficient calculation.
        if level is not None:
            query = """
            MATCH (r:RaptorNode {group_id: $group_id, level: $level})
            WHERE r.embedding IS NOT NULL
            WITH r, vector.similarity.cosine(r.embedding, $embedding) AS score
            ORDER BY score DESC
            LIMIT $top_k
            RETURN r, score
            """
            params = {"group_id": group_id, "level": level, "embedding": embedding, "top_k": top_k}
        else:
            query = """
            MATCH (r:RaptorNode {group_id: $group_id})
            WHERE r.embedding IS NOT NULL
            WITH r, vector.similarity.cosine(r.embedding, $embedding) AS score
            ORDER BY score DESC
            LIMIT $top_k
            RETURN r, score
            """
            params = {"group_id": group_id, "embedding": embedding, "top_k": top_k}
        
        results = []
        with self.driver.session(database=self.database) as session:
            result = session.run(query, **params)
            for record in result:
                r = record["r"]
                node = RaptorNode(
                    id=r["id"],
                    text=r["text"],
                    level=r["level"],
                    embedding=r.get("embedding"),
                )
                results.append((node, record["score"]))
        
        return results
    
    # ==================== Text Chunk Operations ====================
    
    def search_text_chunks(
        self,
        group_id: str,
        query_text: str,
        embedding: List[float],
        top_k: int = 10,
    ) -> List[Tuple[TextChunk, float]]:
        """
        Vector search for TextChunk nodes.
        Used for pure Vector RAG (finding exact quotes).
        """
        # Use native vector similarity for efficient calculation.
        # Also pull the related Document (via PART_OF) so callers can attribute
        # concrete terms (jurisdiction/amounts) per document.
        query = """
        MATCH (t:TextChunk {group_id: $group_id})
        WHERE t.embedding IS NOT NULL
        WITH t, vector.similarity.cosine(t.embedding, $embedding) AS score
        ORDER BY score DESC
        LIMIT $top_k
        OPTIONAL MATCH (t)-[:PART_OF]->(d:Document {group_id: $group_id})
        RETURN t, d, score
        """
        
        results = []
        with self.driver.session(database=self.database) as session:
            result = session.run(query, group_id=group_id, embedding=embedding, top_k=top_k)
            for record in result:
                t = record["t"]
                d = record.get("d")

                chunk_metadata: Dict[str, Any] = {}
                raw_metadata = t.get("metadata")
                if raw_metadata:
                    if isinstance(raw_metadata, str):
                        try:
                            chunk_metadata = json.loads(raw_metadata)
                        except Exception:
                            chunk_metadata = {}
                    elif isinstance(raw_metadata, dict):
                        chunk_metadata = dict(raw_metadata)

                # Always attach document attribution fields
                chunk_metadata["document_title"] = (d.get("title") if d else "")
                chunk_metadata["document_source"] = (d.get("source") if d else "")

                chunk = TextChunk(
                    id=t["id"],
                    text=t["text"],
                    chunk_index=t["chunk_index"],
                    document_id=(d.get("id") if d else ""),
                    tokens=t.get("tokens", 0),
                    embedding=t.get("embedding"),
                    metadata=chunk_metadata,
                )
                results.append((chunk, record["score"]))
        
        return results

    def search_text_chunks_by_terms(
        self,
        group_id: str,
        terms: List[str],
        top_k: int = 10,
    ) -> List[Tuple[TextChunk, float]]:
        """Lexical search for TextChunk nodes by substring terms.

        This is a lightweight complement to vector search. It is intentionally simple:
        - Matches if any term appears in the chunk text (case-insensitive)
        - Scores by number of matched terms

        Used to retrieve exact phrases like "AMOUNT DUE", "return receipt requested",
        or insurance limits that embeddings may miss.
        """
        normalized_terms: list[str] = []
        seen: set[str] = set()
        for t in terms or []:
            v = (t or "").strip().lower()
            if not v:
                continue
            if len(v) > 80:
                v = v[:80]
            if v in seen:
                continue
            seen.add(v)
            normalized_terms.append(v)

        if not normalized_terms:
            return []

        query = """
        MATCH (t:TextChunk {group_id: $group_id})
        WITH t, [term IN $terms WHERE toLower(t.text) CONTAINS term] AS hits
        WITH t, size(hits) AS score
        WHERE score > 0
        ORDER BY score DESC, t.chunk_index ASC
        LIMIT $top_k
        OPTIONAL MATCH (t)-[:PART_OF]->(d:Document {group_id: $group_id})
        RETURN t, d, score
        """

        results: list[tuple[TextChunk, float]] = []
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                group_id=group_id,
                terms=normalized_terms,
                top_k=top_k,
            )
            for record in result:
                t = record["t"]
                d = record.get("d")
                score = float(record.get("score") or 0.0)
                chunk_metadata: Dict[str, Any] = {}
                raw_metadata = t.get("metadata")
                if raw_metadata:
                    if isinstance(raw_metadata, str):
                        try:
                            chunk_metadata = json.loads(raw_metadata)
                        except Exception:
                            chunk_metadata = {}
                    elif isinstance(raw_metadata, dict):
                        chunk_metadata = dict(raw_metadata)

                # Always attach document attribution fields
                chunk_metadata["document_title"] = (d.get("title") if d else "")
                chunk_metadata["document_source"] = (d.get("source") if d else "")

                chunk = TextChunk(
                    id=t["id"],
                    text=t["text"],
                    chunk_index=t["chunk_index"],
                    document_id=(d.get("id") if d else ""),
                    tokens=t.get("tokens", 0),
                    embedding=t.get("embedding"),
                    metadata=chunk_metadata,
                )
                results.append((chunk, score))

        return results
    def upsert_text_chunks_batch(self, group_id: str, chunks: List[TextChunk]) -> int:
        """Batch insert/update text chunks with native vector support."""
        query = """
        UNWIND $chunks AS c
        MERGE (t:TextChunk {id: c.id})
        SET t.text = c.text,
            t.chunk_index = c.chunk_index,
            t.tokens = c.tokens,
            t.metadata = c.metadata,
            t.group_id = $group_id,
            t.updated_at = datetime()
        
        WITH t, c
        FOREACH (_ IN CASE WHEN c.embedding IS NOT NULL AND size(c.embedding) > 0 THEN [1] ELSE [] END |
            SET t.embedding = c.embedding
        )
        
        WITH t, c
        MATCH (d:Document {id: c.document_id, group_id: $group_id})
        MERGE (t)-[:PART_OF]->(d)
        RETURN count(t) AS count
        """
        
        chunk_data = []
        for c in chunks:
            metadata_to_store: Dict[str, Any] = {}
            if c.metadata and isinstance(c.metadata, dict):
                metadata_to_store = dict(c.metadata)

            # Prevent very large DI table payloads from being persisted in Neo4j.
            # Keep a lightweight signal instead.
            if "tables" in metadata_to_store:
                tables_val = metadata_to_store.pop("tables")
                if isinstance(tables_val, list) and tables_val:
                    metadata_to_store["table_count"] = len(tables_val)

            chunk_data.append(
                {
                    "id": c.id,
                    "text": c.text,
                    "chunk_index": c.chunk_index,
                    "document_id": c.document_id,
                    "embedding": c.embedding,
                    "tokens": c.tokens,
                    "metadata": json.dumps(metadata_to_store) if metadata_to_store else "{}",
                }
            )
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, chunks=chunk_data, group_id=group_id)
            record = result.single()
            return cast(int, record["count"]) if record else 0
    
    # ==================== Document Operations ====================
    
    def upsert_document(self, group_id: str, document: Document) -> str:
        """Insert or update a document."""
        query = """
        MERGE (d:Document {id: $id})
        SET d.title = $title,
            d.source = $source,
            d.group_id = $group_id,
            d.metadata = $metadata,
            d.updated_at = datetime()
        RETURN d.id AS id
        """
        
        # Serialize metadata to JSON string as Neo4j doesn't support nested maps
        metadata_json = json.dumps(document.metadata) if document.metadata else "{}"
        
        with self.driver.session(database=self.database) as session:
            result = session.run(
                query,
                id=document.id,
                title=document.title,
                source=document.source,
                group_id=group_id,
                metadata=metadata_json,
            )
            record = result.single()
            return cast(str, record["id"]) if record else document.id
    
    # ==================== Cleanup Operations ====================
    
    def delete_group_data(self, group_id: str) -> Dict[str, int]:
        """Delete all data for a group (for cleanup/reindexing)."""
        queries = [
            ("entities", "MATCH (e:Entity {group_id: $group_id}) DETACH DELETE e RETURN count(*) AS count"),
            ("communities", "MATCH (c:Community {group_id: $group_id}) DETACH DELETE c RETURN count(*) AS count"),
            ("raptor_nodes", "MATCH (r:RaptorNode {group_id: $group_id}) DETACH DELETE r RETURN count(*) AS count"),
            ("text_chunks", "MATCH (t:TextChunk {group_id: $group_id}) DETACH DELETE t RETURN count(*) AS count"),
            ("documents", "MATCH (d:Document {group_id: $group_id}) DETACH DELETE d RETURN count(*) AS count"),
        ]
        
        deleted: Dict[str, int] = {}
        with self.driver.session(database=self.database) as session:
            for name, query in queries:
                result = session.run(Query(query), group_id=group_id)  # type: ignore[arg-type]
                record = result.single()
                deleted[name] = cast(int, record["count"]) if record else 0
        
        logger.info(f"Deleted data for group {group_id}: {deleted}")
        return deleted
    
    def get_group_stats(self, group_id: str) -> Dict[str, int]:
        """Get statistics for a group."""
        query = """
        OPTIONAL MATCH (e:Entity {group_id: $group_id})
        WITH count(e) AS entities
        OPTIONAL MATCH (c:Community {group_id: $group_id})
        WITH entities, count(c) AS communities
        OPTIONAL MATCH (r:RaptorNode {group_id: $group_id})
        WITH entities, communities, count(r) AS raptor_nodes
        OPTIONAL MATCH (t:TextChunk {group_id: $group_id})
        WITH entities, communities, raptor_nodes, count(t) AS text_chunks
        OPTIONAL MATCH (d:Document {group_id: $group_id})
        WITH entities, communities, raptor_nodes, text_chunks, count(d) AS documents
        OPTIONAL MATCH (:Entity {group_id: $group_id})-[rel]->(:Entity {group_id: $group_id})
        RETURN entities, communities, raptor_nodes, text_chunks, documents, count(rel) AS relationships
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, group_id=group_id)
            record = result.single()
            if record:
                return {
                    "entities": record["entities"],
                    "relationships": record["relationships"],
                    "communities": record["communities"],
                    "raptor_nodes": record["raptor_nodes"],
                    "text_chunks": record["text_chunks"],
                    "documents": record["documents"],
                }
            return {"entities": 0, "relationships": 0, "communities": 0, "raptor_nodes": 0, "text_chunks": 0, "documents": 0}
