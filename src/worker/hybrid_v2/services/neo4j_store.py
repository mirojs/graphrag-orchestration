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
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, cast
from dataclasses import dataclass, field

import neo4j
from neo4j import GraphDatabase

from src.worker.hybrid_v2.services.neo4j_retry import retry_session

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Entity node data."""
    id: str
    name: str
    type: str
    description: str = ""
    embedding_v2: Optional[List[float]] = None  # Voyage 2048-dim
    metadata: Dict[str, Any] = field(default_factory=dict)
    text_unit_ids: List[str] = field(default_factory=list)  # For DRIFT MENTIONS relationships
    aliases: List[str] = field(default_factory=list)  # Alternative names/variations for entity lookup


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
class Sentence:
    """Sentence-level node — the primary retrieval and extraction unit.
    
    Extracted from document text via spaCy (body text) or DI metadata (table
    rows, figure captions).  Embedded with Voyage voyage-context-3 for
    sentence-level semantic search.  Used by all active routes (2-7).
    
    Graph edges created during indexing:
      - IN_DOCUMENT → Document
      - IN_SECTION  → Section
      - MENTIONS    → Entity  (created during entity extraction)
      - NEXT        → Sentence (sequential ordering)
      - RELATED_TO  → Sentence (KNN similarity)
    """
    id: str
    text: str
    chunk_id: Optional[str] = None  # Legacy: parent chunk ID (deprecated)
    document_id: str = ""
    source: str = "paragraph"  # "paragraph" | "table_row" | "table_caption" | "figure_caption" | "signature_party" | "page_header" | "page_footer" | "letterhead"
    index_in_chunk: int = 0  # Position within parent chunk (legacy)
    index_in_doc: int = 0  # Global ordinal position within document
    section_path: str = ""  # Section hierarchy path
    page: Optional[int] = None
    confidence: float = 1.0
    embedding_v2: Optional[List[float]] = None  # Voyage 2048-dim
    tokens: int = 0
    parent_text: Optional[str] = None  # Parent paragraph for "sentence search, paragraph display"
    metadata: Dict[str, Any] = field(default_factory=dict)  # KVPs, tables, source URL, title
    # Hierarchical content indexing (thesis-style §1.2.3-S5 addressing)
    index_in_section: int = 0          # 0-based ordinal within parent section
    total_in_section: int = 0          # Total sentences in the same section
    hierarchical_id: str = ""          # Full address, e.g., "2.1.3-S5"


@dataclass
class Document:
    """Document metadata."""
    id: str
    title: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    document_date: Optional[str] = None  # ISO date (YYYY-MM-DD) extracted from content


@dataclass
class KeyValue:
    """Key-value pair extracted from document (form fields, labels, etc.).
    
    KeyValue nodes are section-aware, aligning with the core architecture principle
    that sections are the foundation for ground truth verification.
    """
    id: str
    key: str
    value: str
    confidence: float = 0.0
    page_number: int = 1
    section_path: List[str] = field(default_factory=list)
    key_embedding: Optional[List[float]] = None  # For semantic key matching
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

        self._driver_lock = threading.Lock()
        
    @property
    def driver(self) -> neo4j.Driver:
        """Lazy initialization of Neo4j driver (thread-safe)."""
        if self._driver is not None:
            return self._driver
        with self._driver_lock:
            if self._driver is None:
                self._driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.username, self.password),
                )
                # Verify connectivity
                self._driver.verify_connectivity()
                logger.info(f"Connected to Neo4j at {self.uri}")
        return self._driver
    
    def get_retry_session(self, read_only: bool = False):
        """Return a context manager that yields a retry-enabled sync session.

        Drop-in replacement for ``with self.driver.session(database=...) as s:``.
        Retries on TransientError, ServiceUnavailable, SessionExpired with
        exponential backoff (3 attempts, 1-30 s).
        """
        return retry_session(self.driver, database=self.database, read_only=read_only)

    async def arun_query(self, query, *, read_only: bool = False, **params):
        """Run a single Cypher query off the event loop via thread pool.

        Returns an ``_EagerResult`` supporting ``.single()``, iteration, etc.
        Use ``read_only=True`` for pure-read queries to enable read-replica routing.
        """
        def _sync():
            with self.get_retry_session(read_only=read_only) as session:
                return session.run(query, **params)
        return await asyncio.to_thread(_sync)

    async def arun_in_session(self, func, *, read_only: bool = False):
        """Run ``func(session)`` off the event loop via thread pool.

        Use for multi-query operations that need to share a single session.
        ``func`` receives a ``RetrySession`` and should return any result.
        """
        def _sync():
            with self.get_retry_session(read_only=read_only) as session:
                return func(session)
        return await asyncio.to_thread(_sync)

    def close(self):
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None
    
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
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",

            # Section graph (section-aware retrieval)
            "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE",
            "CREATE INDEX section_group IF NOT EXISTS FOR (s:Section) ON (s.group_id)",
            "CREATE INDEX section_doc IF NOT EXISTS FOR (s:Section) ON (s.doc_id)",
            
            # KeyValue nodes (high-precision field extraction)
            "CREATE CONSTRAINT keyvalue_id IF NOT EXISTS FOR (kv:KeyValue) REQUIRE kv.id IS UNIQUE",
            "CREATE INDEX keyvalue_group IF NOT EXISTS FOR (kv:KeyValue) ON (kv.group_id)",
            "CREATE INDEX keyvalue_key IF NOT EXISTS FOR (kv:KeyValue) ON (kv.key)",
            
            # Sentence nodes (skeleton enrichment Strategy A)
            "CREATE CONSTRAINT sentence_id IF NOT EXISTS FOR (s:Sentence) REQUIRE s.id IS UNIQUE",
            "CREATE INDEX sentence_group IF NOT EXISTS FOR (s:Sentence) ON (s.group_id)",
            "CREATE INDEX sentence_chunk IF NOT EXISTS FOR (s:Sentence) ON (s.chunk_id)",
            "CREATE INDEX sentence_doc IF NOT EXISTS FOR (s:Sentence) ON (s.document_id)",
            
            # Regular indexes for filtering
            "CREATE INDEX entity_group IF NOT EXISTS FOR (e:Entity) ON (e.group_id)",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
            "CREATE INDEX rel_rel_type IF NOT EXISTS FOR ()-[r:RELATED_TO]-() ON (r.rel_type)",
            "CREATE INDEX community_group IF NOT EXISTS FOR (c:Community) ON (c.group_id)",
            
            # Document lifecycle indexes (deprecation queries)
            "CREATE INDEX document_deprecated_at IF NOT EXISTS FOR (d:Document) ON (d.deprecated_at)",
            "CREATE INDEX entity_deprecated_at IF NOT EXISTS FOR (e:Entity) ON (e.deprecated_at)",
            "CREATE INDEX groupmeta_gds_stale IF NOT EXISTS FOR (g:GroupMeta) ON (g.gds_stale)",
            
            # Full-text index for hybrid search (keyword matching)
            "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]",
            "CREATE INDEX community_level IF NOT EXISTS FOR (c:Community) ON (c.level)",
            "CREATE INDEX document_group IF NOT EXISTS FOR (d:Document) ON (d.group_id)",
        ]
        
        # Vector indexes
        # NOTE: If upgrading from list-based embeddings, you must:
        #   1. DROP old indexes
        #   2. Convert properties: SET e.embedding = null then use db.create.setVectorProperty
        #   3. CREATE new indexes with updated config
        #
        # V2 indexes include WITH [group_id] for in-index pre-filtering.
        vector_indexes = [
            # Entity embeddings with Voyage (2048-dim)
            """
            CREATE VECTOR INDEX entity_embedding_v2 IF NOT EXISTS
            FOR (e:Entity) ON (e.embedding_v2)
            WITH [e.group_id]
            OPTIONS {indexConfig: {
                `vector.dimensions`: 2048,
                `vector.similarity_function`: 'cosine'
            }}
            """,
            # Sentence-level embeddings with Voyage (2048-dim)
            """
            CREATE VECTOR INDEX sentence_embeddings_v2 IF NOT EXISTS
            FOR (s:Sentence) ON (s.embedding_v2)
            WITH [s.group_id]
            OPTIONS {indexConfig: {
                `vector.dimensions`: 2048,
                `vector.similarity_function`: 'cosine'
            }}
            """,
        ]
        
        # DDL statements (CREATE INDEX/CONSTRAINT) require auto-commit transactions.
        # They CANNOT run inside managed transactions (execute_write), so we use
        # a raw session.run() here instead of the retry wrapper.
        with self.driver.session(database=self.database) as session:
            for query in schema_queries:
                try:
                    session.run(query)
                    logger.debug(f"Executed: {query[:50]}...")
                except Exception as e:
                    logger.warning(f"Schema query failed (may already exist): {e}")
            
            # Create vector indexes
            for query in vector_indexes:
                try:
                    session.run(query)
                    logger.info("Created vector index with 2048 dimensions (voyage-context-3)")
                except Exception as e:
                    logger.warning(f"Vector index creation failed: {e}")
        
        logger.info("Neo4j schema initialization complete")

    # ==================== Entity Operations ====================
    
    def upsert_entity(self, group_id: str, entity: Entity) -> str:
        """Insert or update an entity using native vector storage."""
        query = """
        MERGE (e:Entity {id: $id, group_id: $group_id})
        SET e.name = $name,
            e.type = $type,
            e.description = $description,
            e.group_id = $group_id,
            e.updated_at = datetime()
        With e
        FOREACH (_ IN CASE WHEN $embedding_v2 IS NOT NULL THEN [1] ELSE [] END |
            SET e.embedding_v2 = $embedding_v2
        )
        RETURN e.id AS id
        """
        
        with self.get_retry_session() as session:
            result = session.run(
                query,
                id=entity.id,
                name=entity.name,
                type=entity.type,
                description=entity.description,
                embedding_v2=entity.embedding_v2 if hasattr(entity, 'embedding_v2') else None,
                group_id=group_id,
            )
            record = result.single()
            return cast(str, record["id"]) if record else entity.id
    
    def upsert_entities_batch(self, group_id: str, entities: List[Entity]) -> int:
        """Batch insert/update entities with native vector support."""
        
        # Diagnostic: Check embeddings before storing
        with_v2 = sum(1 for e in entities if getattr(e, "embedding_v2", None))
        logger.info(f"upsert_entities_batch: {len(entities)} entities, {with_v2} with embedding_v2")
        
        query = """
        UNWIND $entities AS e
        MERGE (entity:Entity {id: e.id, group_id: $group_id})
        SET entity.name = e.name,
            entity.type = e.type,
            entity.description = e.description,
            entity.aliases = coalesce(e.aliases, []),
            entity.group_id = $group_id,
            entity.updated_at = datetime()
        
        WITH entity, e
        // Store embeddings in embedding_v2 property (Voyage 2048-dim)
        FOREACH (_ IN CASE WHEN e.embedding_v2 IS NOT NULL AND size(e.embedding_v2) > 0 THEN [1] ELSE [] END |
            SET entity.embedding_v2 = e.embedding_v2
        )

        
        // Create MENTIONS relationships from Sentence nodes
        WITH entity, e
        UNWIND e.text_unit_ids AS unit_id
        MATCH (sent:Sentence {id: unit_id, group_id: $group_id})
        MERGE (sent)-[m:MENTIONS]->(entity)
        SET m.group_id = $group_id
        
        RETURN count(DISTINCT entity) AS count
        """
        
        entity_data = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "embedding_v2": e.embedding_v2 if hasattr(e, 'embedding_v2') else None,
                "text_unit_ids": e.text_unit_ids if hasattr(e, 'text_unit_ids') else [],
                "aliases": e.aliases if hasattr(e, 'aliases') else [],
            }
            for e in entities
        ]
        
        with self.get_retry_session() as session:
            result = session.run(query, entities=entity_data, group_id=group_id)
            record = result.single()
            count = cast(int, record["count"]) if record else 0
            
            mentions_count = sum(len(e.text_unit_ids) if hasattr(e, 'text_unit_ids') else 0 for e in entities)
            logger.info(f"Created {count} entities with {mentions_count} Sentence MENTIONS")
            
            return count

    def compute_entity_importance(self, group_id: str) -> None:
        """Compute and persist entity importance fields for a group.

        This creates/updates the following properties on entity nodes:
        - `degree`: number of relationships
        - `chunk_count`: number of Sentences that mention the entity
        - `importance_score`: weighted score used for ranking

        Note: This is best-effort and should not fail indexing.
        """

        query = """
        MATCH (e)
        WHERE e.group_id = $group_id AND (e:Entity)
        WITH e, COUNT { (e)-[]-() } AS degree
        SET e.degree = degree
        WITH e
        // Count MENTIONS from Sentence nodes
        WITH e, COUNT { (src)-[:MENTIONS]->(e) WHERE src.group_id = $group_id } AS chunk_count
        SET e.chunk_count = chunk_count
        SET e.importance_score = coalesce(e.degree, 0) * 0.3 + chunk_count * 0.7
        RETURN count(e) AS updated
        """

        try:
            with self.get_retry_session() as session:
                session.run(query, group_id=group_id).consume()
        except Exception as e:
            logger.warning(f"Failed to compute entity importance (continuing): {e}")
    
    async def aupsert_entities_batch(self, group_id: str, entities: List[Entity]) -> int:
        """Async batch insert/update entities with native vector support."""
        
        # Diagnostic: Check embeddings before storing
        with_v2 = sum(1 for e in entities if getattr(e, "embedding_v2", None))
        logger.info(f"aupsert_entities_batch: {len(entities)} entities, {with_v2} with embedding_v2")
        
        query = """
        UNWIND $entities AS e
        MERGE (entity:Entity {id: e.id, group_id: $group_id})
        SET entity.name = e.name,
            entity.type = e.type,
            entity.description = e.description,
            entity.aliases = coalesce(e.aliases, []),
            entity.updated_at = datetime()
        
        WITH entity, e
        // Store embeddings in embedding_v2 property (Voyage 2048-dim)
        FOREACH (_ IN CASE WHEN e.embedding_v2 IS NOT NULL AND size(e.embedding_v2) > 0 THEN [1] ELSE [] END |
            SET entity.embedding_v2 = e.embedding_v2
        )

        
        // Create MENTIONS relationships from Sentence nodes
        WITH entity, e
        UNWIND e.text_unit_ids AS unit_id
        MATCH (sent:Sentence {id: unit_id, group_id: $group_id})
        MERGE (sent)-[m:MENTIONS]->(entity)
        SET m.group_id = $group_id
        RETURN count(DISTINCT entity) AS count
        """
        
        entity_data = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "embedding_v2": e.embedding_v2 if hasattr(e, 'embedding_v2') else None,
                "text_unit_ids": e.text_unit_ids if hasattr(e, 'text_unit_ids') else [],
                "aliases": e.aliases if hasattr(e, 'aliases') else [],
            }
            for e in entities
        ]
        
        # Debug: Check if embedding_v2 is actually populated
        if entity_data:
            sample = entity_data[0]
            has_v2 = sample['embedding_v2'] is not None and len(sample['embedding_v2']) > 0 if sample['embedding_v2'] else False
            logger.warning(f"   Sample entity_data: has embedding_v2={has_v2}")
            if sample['embedding_v2']:
                logger.warning(f"   embedding_v2 dim: {len(sample['embedding_v2'])}")
        
        def _sync_upsert():
            with self.get_retry_session() as session:
                result = session.run(query, entities=entity_data, group_id=group_id)
                record = result.single()
                count = cast(int, record["count"]) if record else 0

                mentions_count = sum(len(e.text_unit_ids) if hasattr(e, 'text_unit_ids') else 0 for e in entities)
                logger.info(f"Created {count} entities with {mentions_count} Sentence MENTIONS (async)")

                return count

        return await asyncio.to_thread(_sync_upsert)
    
    def get_entity(self, group_id: str, entity_id: str) -> Optional[Entity]:
        """Get an entity by ID."""
        query = """
        MATCH (e:Entity {id: $id, group_id: $group_id})
        RETURN e
        """
        
        with self.get_retry_session() as session:
            result = session.run(query, id=entity_id, group_id=group_id)
            record = result.single()
            if record:
                e = record["e"]
                return Entity(
                    id=e["id"],
                    name=e["name"],
                    type=e["type"],
                    description=e.get("description", ""),
                    embedding_v2=e.get("embedding_v2"),
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
        WHERE e.embedding_v2 IS NOT NULL
        WITH e, vector.similarity.cosine(e.embedding_v2, $embedding) AS vectorScore
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
        OPTIONAL MATCH (node)-[:BELONGS_TO]->(c:Community {group_id: $group_id})
        WITH node, rrfScore, coalesce(max(c.rank), 0.0) AS communityRank
        
        // Apply boost: 5% boost per rank unit to avoid over-weighting community membership
        // This ensures factual accuracy from vector search remains primary signal
        WITH node, rrfScore * (1.0 + (communityRank * 0.05)) AS finalScore
        
        RETURN node, finalScore
        ORDER BY finalScore DESC
        LIMIT $top_k
        """
        
        results = []
        with self.get_retry_session() as session:
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
                        embedding_v2=e.get("embedding_v2"),
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
        """Vector similarity search for entities using native vector index.
        
        Uses SEARCH clause with in-index group_id pre-filtering (Cypher 25).
        """
        query = """CYPHER 25
        MATCH (node:Entity)
        SEARCH node IN (VECTOR INDEX entity_embedding_v2 FOR $embedding WHERE node.group_id = $group_id LIMIT $top_k)
        SCORE AS score
        RETURN node, score
        ORDER BY score DESC
        """
        
        results = []
        with self.get_retry_session() as session:
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
                    embedding_v2=e.get("embedding_v2"),
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
        with self.get_retry_session() as session:
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
                    embedding_v2=e.get("embedding_v2"),
                )
                # Normalize relevance score to 0-1 range for consistency
                score = float(record["relevance_score"]) / 5.0
                results.append((entity, score))
        
        return results
    
    # ==================== Relationship Operations ====================
    
    def upsert_relationship(self, group_id: str, relationship: Relationship) -> str:
        """Insert or update a relationship with co-occurrence counting."""
        query = """
        MATCH (source:Entity {id: $source_id, group_id: $group_id})
        MATCH (target:Entity {id: $target_id, group_id: $group_id})
        MERGE (source)-[r:RELATED_TO]->(target)
        ON CREATE SET r.id = $id,
            r.description = $description,
            r.rel_type = $rel_type,
            r.weight = $weight,
            r.cooccurrence_count = 1,
            r.group_id = $group_id,
            r.created_at = datetime(),
            r.updated_at = datetime()
        ON MATCH SET r.cooccurrence_count = coalesce(r.cooccurrence_count, 1) + 1,
            r.weight = coalesce(r.cooccurrence_count, 1) + 1,
            r.updated_at = datetime()
        RETURN r.id AS id
        """

        with self.get_retry_session() as session:
            result = session.run(
                query,
                source_id=relationship.source_id,
                target_id=relationship.target_id,
                id=relationship.id,
                description=relationship.description,
                rel_type=relationship.description or "RELATED_TO",
                weight=relationship.weight,
                group_id=group_id,
            )
            record = result.single()
            return cast(str, record["id"]) if record else (relationship.id or "")
    
    def upsert_relationships_batch(self, group_id: str, relationships: List[Relationship]) -> int:
        """Batch insert/update relationships with co-occurrence counting.

        When the same (source, target) pair is seen multiple times (e.g. two
        entities co-occurring across several sentences), the co-occurrence count
        and weight are accumulated via ON MATCH, giving PPR stronger signal for
        frequently co-occurring entity pairs.
        """
        query = """
        UNWIND $relationships AS rel
        MATCH (source:Entity {id: rel.source_id, group_id: $group_id})
        MATCH (target:Entity {id: rel.target_id, group_id: $group_id})
        MERGE (source)-[r:RELATED_TO]->(target)
        ON CREATE SET r.id = rel.id,
            r.description = rel.description,
            r.rel_type = rel.rel_type,
            r.weight = rel.weight,
            r.cooccurrence_count = 1,
            r.group_id = $group_id,
            r.created_at = datetime(),
            r.updated_at = datetime()
        ON MATCH SET r.cooccurrence_count = coalesce(r.cooccurrence_count, 1) + 1,
            r.weight = coalesce(r.cooccurrence_count, 1) + 1,
            r.updated_at = datetime()
        RETURN count(r) AS count
        """

        rel_data = [
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "id": r.id,
                "description": r.description,
                "rel_type": r.description or "RELATED_TO",
                "weight": r.weight,
            }
            for r in relationships
        ]
        
        with self.get_retry_session() as session:
            result = session.run(query, relationships=rel_data, group_id=group_id)
            record = result.single()
            return cast(int, record["count"]) if record else 0

    def backfill_rel_type(self, group_id: str) -> int:
        """Stamp rel_type on pre-existing RELATED_TO edges that predate this property.

        Safe to call multiple times — only updates edges where rel_type IS NULL.
        Sources the value from r.description, which has always stored the semantic
        relationship type string (e.g. "PARTY_TO", "LOCATED_IN") for all extraction
        paths.  Run once after deploying the rel_type persistence fix.
        """
        cypher = """
        MATCH (e1:Entity {group_id: $group_id})-[r:RELATED_TO]->(e2:Entity {group_id: $group_id})
        WHERE r.rel_type IS NULL
        SET r.rel_type = coalesce(r.description, 'RELATED_TO')
        RETURN count(r) AS updated
        """
        with self.get_retry_session() as session:
            result = session.run(cypher, group_id=group_id)
            record = result.single()
            return cast(int, record["updated"]) if record else 0

    # ==================== Triple Embedding Operations ====================

    def fetch_all_triples(self, group_id: str) -> List[Dict[str, Any]]:
        """Fetch all RELATED_TO triples for pre-computing embeddings."""
        cypher = """
        MATCH (e1:Entity {group_id: $group_id})-[r:RELATED_TO]->(e2:Entity {group_id: $group_id})
        WHERE r.description IS NOT NULL AND r.description <> ''
        RETURN e1.id AS source_id, e1.name AS source_name,
               r.description AS description,
               e2.id AS target_id, e2.name AS target_name
        """
        triples: List[Dict[str, Any]] = []
        with self.get_retry_session() as session:
            result = session.run(cypher, group_id=group_id)
            for record in result:
                triples.append({
                    "source_id": record["source_id"],
                    "source_name": record["source_name"] or "",
                    "description": record["description"] or "",
                    "target_id": record["target_id"],
                    "target_name": record["target_name"] or "",
                })
        return triples

    def store_triple_embeddings_batch(
        self, group_id: str, triples: List[Dict[str, Any]], embeddings: List[List[float]]
    ) -> int:
        """Store pre-computed embeddings on RELATED_TO edges.

        Each triple dict must have source_id and target_id to match the edge.
        """
        cypher = """
        UNWIND $items AS item
        MATCH (e1:Entity {id: item.source_id, group_id: $group_id})
              -[r:RELATED_TO]->
              (e2:Entity {id: item.target_id, group_id: $group_id})
        SET r.embedding_v2 = item.embedding
        RETURN count(r) AS count
        """
        items = [
            {
                "source_id": t["source_id"],
                "target_id": t["target_id"],
                "embedding": emb,
            }
            for t, emb in zip(triples, embeddings)
        ]
        # Batch in groups of 100 to avoid transaction size limits
        total = 0
        batch_size = 100
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            with self.get_retry_session() as session:
                result = session.run(cypher, items=batch, group_id=group_id)
                record = result.single()
                total += cast(int, record["count"]) if record else 0
        return total

    # ==================== Community Operations ====================
    
    def upsert_community(self, group_id: str, community: Community) -> str:
        """Insert or update a community."""
        query = """
        MERGE (c:Community {id: $id, group_id: $group_id})
        SET c.level = $level,
            c.title = $title,
            c.summary = $summary,
            c.full_content = $full_content,
            c.rank = $rank,
            c.group_id = $group_id,
            c.updated_at = datetime()
        RETURN c.id AS id
        """
        
        with self.get_retry_session() as session:
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
                MATCH (c:Community {id: $community_id, group_id: $group_id})
                UNWIND $entity_ids AS entity_id
                MATCH (e:Entity {id: entity_id, group_id: $group_id})
                MERGE (e)-[r:BELONGS_TO]->(c)
                SET r.group_id = $group_id
                """
                session.run(
                    link_query,
                    community_id=community.id,
                    entity_ids=community.entity_ids,
                    group_id=group_id,
                )
            
            return cast(str, record["id"]) if record else community.id
    
    def update_community_summary(self, group_id: str, community_id: str, title: str, summary: str) -> None:
        """Update Community node with LLM-generated title and summary."""
        query = """
        MATCH (c:Community {id: $community_id, group_id: $group_id})
        SET c.title = $title, c.summary = $summary, c.updated_at = datetime()
        """
        with self.get_retry_session() as session:
            session.run(query, community_id=community_id, group_id=group_id, title=title, summary=summary)

    def update_community_embedding(self, group_id: str, community_id: str, embedding: List[float]) -> None:
        """Store embedding vector on a Community node for semantic matching."""
        query = """
        MATCH (c:Community {id: $community_id, group_id: $group_id})
        SET c.embedding = $embedding
        """
        with self.get_retry_session() as session:
            session.run(query, community_id=community_id, group_id=group_id, embedding=embedding)

    def get_communities_by_level(self, group_id: str, level: int) -> List[Community]:
        """Get all communities at a specific level."""
        query = """
        MATCH (c:Community {group_id: $group_id, level: $level})
        OPTIONAL MATCH (e:Entity {group_id: $group_id})-[r:BELONGS_TO]->(c)
        WHERE r.group_id = $group_id
        RETURN c, collect(DISTINCT e.id) AS entity_ids
        ORDER BY c.rank DESC
        """
        
        communities = []
        with self.get_retry_session() as session:
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
        with self.get_retry_session() as session:
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

        with self.get_retry_session() as session:
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
        MATCH (child:Community {group_id: $group_id, level: $child_level})-[:PARENT_COMMUNITY]->(parent:Community {id: $parent_id, group_id: $group_id})
        OPTIONAL MATCH (e:Entity {group_id: $group_id})-[:BELONGS_TO]->(child)
        RETURN child AS c, collect(DISTINCT e.id) AS entity_ids
        ORDER BY child.rank DESC
        """
        with self.get_retry_session() as session:
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
    



    # ==================== RAPTOR Node Operations ====================
    
    
    
    # ==================== Sentence Operations (Skeleton Enrichment) ====================

    def get_sentences_by_group(self, group_id: str) -> List[Dict[str, Any]]:
        """Fetch all Sentence nodes for a group_id.

        Returns list of dicts with keys: id, text, chunk_id, document_id,
        source, section_path.
        Used by Phase B sentence-based entity extraction.
        """
        query = """
        MATCH (s:Sentence {group_id: $group_id})
        RETURN s.id AS id, s.text AS text, s.chunk_id AS chunk_id,
               s.document_id AS document_id, s.source AS source,
               s.section_path AS section_path
        ORDER BY s.document_id, s.chunk_id, s.index_in_chunk
        """
        with self.get_retry_session() as session:
            result = session.run(query, group_id=group_id)
            sentences = [
                {
                    "id": record["id"],
                    "text": record["text"],
                    "chunk_id": record["chunk_id"],
                    "document_id": record["document_id"],
                    "source": record["source"],
                    "section_path": record["section_path"] or "",
                }
                for record in result
            ]
            logger.info(f"Fetched {len(sentences)} Sentence nodes for group {group_id}")
            return sentences

    def upsert_sentences_batch(self, group_id: str, sentences: List["Sentence"]) -> int:
        """Batch insert/update Sentence nodes with embeddings and structural edges.
        
        Creates :Sentence nodes with direct IN_DOCUMENT and IN_SECTION edges.
        Optionally creates PART_OF→parent chunk if chunk_id is present (legacy).
        Creates NEXT edges between sequential sentences within the same document.
        """
        if not sentences:
            return 0
        
        query = """
        UNWIND $sentences AS s
        MERGE (sent:Sentence {id: s.id, group_id: $group_id})
        SET sent.text = s.text,
            sent.chunk_id = s.chunk_id,
            sent.document_id = s.document_id,
            sent.source = s.source,
            sent.index_in_chunk = s.index_in_chunk,
            sent.index_in_doc = s.index_in_doc,
            sent.section_path = s.section_path,
            sent.page = s.page,
            sent.confidence = s.confidence,
            sent.tokens = s.tokens,
            sent.parent_text = s.parent_text,
            sent.metadata = s.metadata,
            sent.index_in_section = s.index_in_section,
            sent.total_in_section = s.total_in_section,
            sent.hierarchical_id = s.hierarchical_id,
            sent.group_id = $group_id,
            sent.updated_at = datetime()
        
        // Store Voyage embedding (2048-dim)
        WITH sent, s
        FOREACH (_ IN CASE WHEN s.embedding_v2 IS NOT NULL AND size(s.embedding_v2) > 0 THEN [1] ELSE [] END |
            SET sent.embedding_v2 = s.embedding_v2
        )
        
        // IN_DOCUMENT edge
        WITH sent, s
        OPTIONAL MATCH (d:Document {id: s.document_id, group_id: $group_id})
        FOREACH (_ IN CASE WHEN d IS NOT NULL THEN [1] ELSE [] END |
            MERGE (sent)-[:IN_DOCUMENT]->(d)
        )
        
        // IN_SECTION edge
        WITH sent, s
        OPTIONAL MATCH (sec:Section {group_id: $group_id})
        WHERE sec.doc_id = s.document_id AND s.section_path <> '' AND sec.section_path = s.section_path
        FOREACH (_ IN CASE WHEN sec IS NOT NULL THEN [1] ELSE [] END |
            MERGE (sent)-[:IN_SECTION]->(sec)
        )
        
        RETURN count(sent) AS count
        """
        
        sentence_data = []
        for s in sentences:
            # Serialize metadata dict to JSON string for Neo4j storage
            meta_str = ""
            if s.metadata:
                import json as _json
                try:
                    meta_str = _json.dumps(s.metadata, default=str)
                except (TypeError, ValueError):
                    meta_str = ""
            sentence_data.append({
                "id": s.id,
                "text": s.text,
                "chunk_id": s.chunk_id or "",
                "document_id": s.document_id,
                "source": s.source,
                "index_in_chunk": s.index_in_chunk,
                "index_in_doc": s.index_in_doc,
                "section_path": s.section_path,
                "page": s.page,
                "confidence": s.confidence,
                "tokens": s.tokens,
                "parent_text": s.parent_text or "",
                "embedding_v2": s.embedding_v2,
                "metadata": meta_str,
                "index_in_section": s.index_in_section,
                "total_in_section": s.total_in_section,
                "hierarchical_id": s.hierarchical_id,
            })
        
        with self.get_retry_session() as session:
            result = session.run(query, sentences=sentence_data, group_id=group_id)
            record = result.single()
            count = cast(int, record["count"]) if record else 0
            
            # Build NEXT edges between sequential sentences within each chunk
            self._create_sentence_next_edges(group_id, sentences)
            
            logger.info(f"Upserted {count} Sentence nodes for group {group_id}")
            return count
    
    def _create_sentence_next_edges(self, group_id: str, sentences: List["Sentence"]) -> None:
        """Create NEXT and NEXT_IN_SECTION edges between sequential sentences."""
        from collections import defaultdict

        doc_sentences: Dict[str, List["Sentence"]] = defaultdict(list)
        for s in sentences:
            doc_sentences[s.document_id].append(s)

        next_pairs = []
        next_in_section_pairs = []
        for doc_id, doc_sents in doc_sentences.items():
            sorted_sents = sorted(doc_sents, key=lambda s: s.index_in_doc)
            for i in range(len(sorted_sents) - 1):
                curr = sorted_sents[i]
                nxt = sorted_sents[i + 1]
                next_pairs.append({
                    "from_id": curr.id,
                    "to_id": nxt.id,
                })
                # NEXT_IN_SECTION: only between consecutive sentences in same section
                if curr.section_path and curr.section_path == nxt.section_path:
                    next_in_section_pairs.append({
                        "from_id": curr.id,
                        "to_id": nxt.id,
                    })
        
        if not next_pairs:
            return
        
        query = """
        UNWIND $pairs AS p
        MATCH (a:Sentence {id: p.from_id, group_id: $group_id})
        MATCH (b:Sentence {id: p.to_id, group_id: $group_id})
        MERGE (a)-[:NEXT]->(b)
        """
        
        with self.get_retry_session() as session:
            session.run(query, pairs=next_pairs, group_id=group_id)

        if next_in_section_pairs:
            query_section = """
            UNWIND $pairs AS p
            MATCH (a:Sentence {id: p.from_id, group_id: $group_id})
            MATCH (b:Sentence {id: p.to_id, group_id: $group_id})
            MERGE (a)-[:NEXT_IN_SECTION]->(b)
            """
            with self.get_retry_session() as session:
                session.run(query_section, pairs=next_in_section_pairs, group_id=group_id)
    
    def link_sentences_to_extra_chunks(
        self,
        group_id: str,
        extra_chunk_map: Dict[str, List[str]],
    ) -> int:
        """Create additional PART_OF edges for sentences in duplicate chunks.

        When section-aware chunking produces overlapping chunks, the same
        sentence text exists in multiple chunks.  Sentence dedup keeps one
        node per unique text, but we need PART_OF edges to *every* parent
        chunk so that ``_focused_text()`` denoising works on all chunks.

        Args:
            group_id: Group identifier.
            extra_chunk_map: sentence_id → list of additional chunk_ids.

        Returns:
            Number of PART_OF edges created.
        """
        if not extra_chunk_map:
            return 0

        pairs = []
        for sent_id, chunk_ids in extra_chunk_map.items():
            for cid in chunk_ids:
                pairs.append({"sent_id": sent_id, "chunk_id": cid})

        query = """
        UNWIND $pairs AS p
        MATCH (sent:Sentence {id: p.sent_id, group_id: $group_id})
        MATCH (chunk:TextChunk {id: p.chunk_id, group_id: $group_id})
        MERGE (sent)-[:PART_OF]->(chunk)
        RETURN count(*) AS cnt
        """

        with self.get_retry_session() as session:
            result = session.run(query, pairs=pairs, group_id=group_id)
            record = result.single()
            return cast(int, record["cnt"]) if record else 0

    def create_sentence_related_to_edges(
        self,
        group_id: str,
        edges: List[Dict[str, Any]],
    ) -> int:
        """Create RELATED_TO edges between semantically similar sentences.
        
        Phase 2 of skeleton enrichment: sparse cross-chunk sentence links.
        Each edge dict must have: source_id, target_id, similarity.
        
        Edge properties:
          - similarity: cosine score
          - source: 'knn_sentence'
          - group_id: tenant isolation
          - created_at: timestamp
        """
        if not edges:
            return 0
        
        query = """
        UNWIND $edges AS e
        MATCH (s1:Sentence {id: e.source_id, group_id: $group_id})
        MATCH (s2:Sentence {id: e.target_id, group_id: $group_id})
        MERGE (s1)-[r:RELATED_TO]->(s2)
        SET r.similarity = e.similarity,
            r.source = 'knn_sentence',
            r.method = 'knn_sentence',
            r.group_id = $group_id,
            r.created_at = datetime()
        RETURN count(r) AS count
        """
        
        with self.get_retry_session() as session:
            result = session.run(query, edges=edges, group_id=group_id)
            count = result.single()["count"]
        
        logger.info(f"Created {count} sentence RELATED_TO edges for group {group_id}")
        return count

    def create_sentence_semantically_similar_edges(
        self,
        group_id: str,
        edges: List[Dict[str, Any]],
    ) -> int:
        """Create SEMANTICALLY_SIMILAR edges between sentence nodes for PPR traversal.

        Mirrors create_sentence_related_to_edges but uses the SEMANTICALLY_SIMILAR
        relationship type that the PPR graph builder loads.
        """
        if not edges:
            return 0

        query = """
        UNWIND $edges AS e
        MATCH (s1:Sentence {id: e.source_id, group_id: $group_id})
        MATCH (s2:Sentence {id: e.target_id, group_id: $group_id})
        MERGE (s1)-[r:SEMANTICALLY_SIMILAR]->(s2)
        SET r.score = e.similarity,
            r.similarity = e.similarity,
            r.method = 'knn_sentence',
            r.group_id = $group_id,
            r.created_at = datetime()
        RETURN count(r) AS count
        """

        with self.get_retry_session() as session:
            result = session.run(query, edges=edges, group_id=group_id)
            count = result.single()["count"]

        logger.info(f"Created {count} sentence SEMANTICALLY_SIMILAR edges for group {group_id}")
        return count
    
    def query_sentences_by_vector(
        self,
        query_embedding: List[float],
        group_id: str,
        top_k: int = 8,
        similarity_threshold: float = 0.45,
    ) -> List[Dict[str, Any]]:
        """Query Sentence nodes by vector similarity for skeleton enrichment.
        
        Returns sentence text + parent chunk context for LLM prompt injection.
        Uses the sentence_embeddings_v2 vector index.
        """
        query = """CYPHER 25
        CALL () {
            MATCH (sent:Sentence)
            SEARCH sent IN (VECTOR INDEX sentence_embeddings_v2 FOR $embedding WHERE sent.group_id = $group_id LIMIT $top_k)
            SCORE AS score
            WHERE score >= $threshold
            RETURN sent, score
        }
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
        
        results = []
        with self.get_retry_session() as session:
            records = session.run(
                query,
                embedding=query_embedding,
                group_id=group_id,
                top_k=top_k,
                threshold=similarity_threshold,
            )
            for record in records:
                results.append({
                    "sentence_id": record["sentence_id"],
                    "text": record["text"],
                    "source": record["source"],
                    "section_path": record["section_path"],
                    "parent_text": record["parent_text"],
                    "page": record["page"],
                    "chunk_id": record["chunk_id"],
                    "document_id": record["document_id"],
                    "chunk_text": record["chunk_text"],
                    "document_title": record["document_title"],
                    "section_key": record["section_key"],
                    "score": record["score"],
                })
        
        return results
    
    # ==================== Document Operations ====================
    
    def upsert_document(self, group_id: str, document: Document) -> str:
        """Insert or update a document with lifecycle metadata."""
        query = """
        MERGE (d:Document {id: $id, group_id: $group_id})
        SET d.title = $title,
            d.source = $source,
            d.group_id = $group_id,
            d.metadata = $metadata,
            d.date = $document_date,
            d.updated_at = datetime(),
            d.created_at = coalesce(d.created_at, datetime())
        RETURN d.id AS id
        """
        
        # Serialize metadata to JSON string as Neo4j doesn't support nested maps
        metadata_json = json.dumps(document.metadata) if document.metadata else "{}"
        
        with self.get_retry_session() as session:
            result = session.run(
                query,
                id=document.id,
                title=document.title,
                source=document.source,
                group_id=group_id,
                metadata=metadata_json,
                document_date=document.document_date,
            )
            record = result.single()
            return cast(str, record["id"]) if record else document.id
    
    def initialize_group_meta(self, group_id: str) -> None:
        """Initialize or update GroupMeta node for lifecycle tracking.
        
        Call this at the start of indexing to ensure the group metadata
        node exists for lifecycle management.
        """
        query = """
        MERGE (g:GroupMeta {group_id: $group_id})
        ON CREATE SET 
            g.created_at = datetime(),
            g.gds_stale = true,
            g.gds_stale_since = datetime()
        SET g.last_indexing_at = datetime()
        RETURN g.group_id AS group_id
        """
        
        with self.get_retry_session() as session:
            session.run(query, group_id=group_id)
            logger.info(f"Initialized GroupMeta for {group_id}")
    
    def mark_gds_stale(self, group_id: str, reason: str = None) -> None:
        """Mark a group as needing GDS recomputation.
        
        Call this after any lifecycle changes (deprecation, deletion, etc.)
        """
        query = """
        MERGE (g:GroupMeta {group_id: $group_id})
        SET g.gds_stale = true,
            g.gds_stale_since = datetime(),
            g.gds_stale_reason = $reason
        """
        
        with self.get_retry_session() as session:
            session.run(query, group_id=group_id, reason=reason)
    
    def clear_gds_stale(self, group_id: str) -> None:
        """Mark GDS as freshly computed."""
        query = """
        MERGE (g:GroupMeta {group_id: $group_id})
        SET g.gds_stale = false,
            g.gds_last_computed = datetime(),
            g.gds_stale_reason = null
        """
        
        with self.get_retry_session() as session:
            session.run(query, group_id=group_id)
    
    # ==================== Cleanup Operations ====================

    def delete_document_chunks(self, group_id: str, document_id: str) -> Dict[str, int]:
        """Delete all child nodes for a specific document before re-chunking.

        Removes Sentence, TextChunk (legacy), Chunk (legacy), Section, Table,
        Figure, KeyValue, KeyValuePair, and SignatureBlock nodes linked to the
        document.  The Document node itself is kept (it will be upserted
        separately).  Orphan Entity cleanup is NOT done here — entities may be
        shared across documents and are handled by maintenance GC.
        """
        query = """
        MATCH (d:Document {id: $doc_id, group_id: $group_id})

        // Collect legacy TextChunk / Chunk nodes
        OPTIONAL MATCH (c:TextChunk)-[:PART_OF|IN_DOCUMENT]->(d)
        WITH d, collect(DISTINCT c) AS tc_chunks
        OPTIONAL MATCH (c2:Chunk)-[:PART_OF|IN_DOCUMENT]->(d)
        WITH d, tc_chunks, collect(DISTINCT c2) AS native_chunks
        WITH d, tc_chunks + native_chunks AS chunks

        // Collect sentences — new path (IN_DOCUMENT) and legacy path (PART_OF→TextChunk)
        OPTIONAL MATCH (sent:Sentence)-[:IN_DOCUMENT]->(d)
        WITH d, chunks, collect(DISTINCT sent) AS direct_sentences
        OPTIONAL MATCH (sent2:Sentence)-[:PART_OF]->(ch)
        WHERE ch IN chunks
        WITH d, chunks, direct_sentences, collect(DISTINCT sent2) AS legacy_sentences
        WITH d, chunks, direct_sentences + legacy_sentences AS sentences

        // Collect sections
        OPTIONAL MATCH (s:Section {doc_id: $doc_id, group_id: $group_id})
        WITH d, chunks, sentences, collect(DISTINCT s) AS sections

        // Collect tables, figures, KVPs, KVPairs, signature blocks
        OPTIONAL MATCH (t:Table)-[:IN_DOCUMENT]->(d)
        OPTIONAL MATCH (f:Figure)-[:IN_DOCUMENT]->(d)
        OPTIONAL MATCH (kv:KeyValue)-[:IN_DOCUMENT]->(d)
        OPTIONAL MATCH (kvp:KeyValuePair)-[:IN_DOCUMENT]->(d)
        OPTIONAL MATCH (sb:SignatureBlock)-[:IN_DOCUMENT]->(d)
        WITH d, chunks, sentences, sections,
             collect(DISTINCT t) AS tables,
             collect(DISTINCT f) AS figures,
             collect(DISTINCT kv) AS kvs,
             collect(DISTINCT kvp) AS kvps,
             collect(DISTINCT sb) AS sbs

        // Delete all children (DETACH removes their edges too)
        FOREACH (x IN chunks    | DETACH DELETE x)
        FOREACH (x IN sentences | DETACH DELETE x)
        FOREACH (x IN sections  | DETACH DELETE x)
        FOREACH (x IN tables    | DETACH DELETE x)
        FOREACH (x IN figures   | DETACH DELETE x)
        FOREACH (x IN kvs       | DETACH DELETE x)
        FOREACH (x IN kvps      | DETACH DELETE x)
        FOREACH (x IN sbs       | DETACH DELETE x)

        RETURN size(chunks) AS chunks_deleted,
               size(sentences) AS sentences_deleted,
               size(sections) AS sections_deleted,
               size(tables) + size(figures) + size(kvs) + size(kvps) + size(sbs) AS extras_deleted
        """
        deleted: Dict[str, int] = {}
        with self.get_retry_session() as session:
            result = session.run(query, doc_id=document_id, group_id=group_id)
            record = result.single()
            if record:
                deleted = {
                    "chunks": record["chunks_deleted"],
                    "sentences": record["sentences_deleted"],
                    "sections": record["sections_deleted"],
                    "extras": record["extras_deleted"],
                }
            else:
                deleted = {"chunks": 0, "sentences": 0, "sections": 0, "extras": 0}

        total = sum(deleted.values())
        if total > 0:
            logger.info(
                f"Cleaned stale children for doc {document_id} in group {group_id}: {deleted}"
            )
        return deleted

    def delete_group_data(self, group_id: str) -> Dict[str, int]:
        """Delete all data for a group (for cleanup/reindexing).

        Includes legacy TextChunk and Chunk (neo4j_graphrag native label) nodes
        that may remain from pre-Sentence-migration indexing runs.
        """
        queries = [
            ("entities", "MATCH (e:Entity {group_id: $group_id}) DETACH DELETE e RETURN count(*) AS count"),
            ("communities", "MATCH (c:Community {group_id: $group_id}) DETACH DELETE c RETURN count(*) AS count"),
            ("key_values", "MATCH (kv:KeyValue {group_id: $group_id}) DETACH DELETE kv RETURN count(*) AS count"),
            ("key_value_pairs", "MATCH (kvp:KeyValuePair {group_id: $group_id}) DETACH DELETE kvp RETURN count(*) AS count"),
            ("tables", "MATCH (t:Table {group_id: $group_id}) DETACH DELETE t RETURN count(*) AS count"),
            ("signature_blocks", "MATCH (sb:SignatureBlock {group_id: $group_id}) DETACH DELETE sb RETURN count(*) AS count"),
            ("sections", "MATCH (s:Section {group_id: $group_id}) DETACH DELETE s RETURN count(*) AS count"),
            ("sentences", "MATCH (s:Sentence {group_id: $group_id}) DETACH DELETE s RETURN count(*) AS count"),
            ("figures", "MATCH (f:Figure {group_id: $group_id}) DETACH DELETE f RETURN count(*) AS count"),
            # Legacy node labels from pre-Sentence migration
            ("text_chunks", "MATCH (c:TextChunk {group_id: $group_id}) DETACH DELETE c RETURN count(*) AS count"),
            ("chunks", "MATCH (c:Chunk {group_id: $group_id}) DETACH DELETE c RETURN count(*) AS count"),
            # Documents last — other nodes may reference them
            ("documents", "MATCH (d:Document {group_id: $group_id}) DETACH DELETE d RETURN count(*) AS count"),
        ]
        
        deleted: Dict[str, int] = {}
        with self.get_retry_session() as session:
            for name, query in queries:
                result = session.run(query, group_id=group_id)
                record = result.single()
                deleted[name] = cast(int, record["count"]) if record else 0
        
        logger.info(f"Deleted data for group {group_id}: {deleted}")
        return deleted

    def delete_entities_only(self, group_id: str) -> Dict[str, int]:
        """Delete Entity/Community nodes and MENTIONS edges for re-extraction.

        Keeps Sentences, TextChunks, Documents, Sections intact so that
        entity extraction can be re-run without re-chunking/embedding.
        """
        queries = [
            ("entities", "MATCH (e:Entity {group_id: $group_id}) DETACH DELETE e RETURN count(*) AS count"),
            ("communities", "MATCH (c:Community {group_id: $group_id}) DETACH DELETE c RETURN count(*) AS count"),
            # Remove propagated MENTIONS from TextChunks (will be re-created)
            ("chunk_mentions", """
                MATCH (:TextChunk {group_id: $group_id})-[m:MENTIONS]->()
                DELETE m RETURN count(m) AS count
            """),
            # Remove Sentence MENTIONS edges too
            ("sentence_mentions", """
                MATCH (:Sentence {group_id: $group_id})-[m:MENTIONS]->()
                DELETE m RETURN count(m) AS count
            """),
        ]

        deleted: Dict[str, int] = {}
        with self.get_retry_session() as session:
            for name, query in queries:
                result = session.run(query, group_id=group_id)
                record = result.single()
                deleted[name] = cast(int, record["count"]) if record else 0

        logger.info(f"Deleted entities/mentions for group {group_id} (re-extraction): {deleted}")
        return deleted
    
    def get_group_stats(self, group_id: str) -> Dict[str, int]:
        """Get statistics for a group."""
        query = """
        OPTIONAL MATCH (e:Entity {group_id: $group_id})
        WITH count(e) AS entities
        OPTIONAL MATCH (c:Community {group_id: $group_id})
        WITH entities, count(c) AS communities
        OPTIONAL MATCH (s:Sentence {group_id: $group_id})
        WITH entities, communities, count(s) AS sentences
        OPTIONAL MATCH (d:Document {group_id: $group_id})
        WITH entities, communities, sentences, count(d) AS documents
        OPTIONAL MATCH (:Entity {group_id: $group_id})-[rel]->(:Entity {group_id: $group_id})
        RETURN entities, communities, sentences, documents, count(rel) AS relationships
        """
        
        with self.get_retry_session() as session:
            result = session.run(query, group_id=group_id)
            record = result.single()
            if record:
                return {
                    "entities": record["entities"],
                    "relationships": record["relationships"],
                    "communities": record["communities"],
                    "sentences": record["sentences"],
                    "documents": record["documents"],
                }
            return {"entities": 0, "relationships": 0, "communities": 0, "sentences": 0, "documents": 0}
