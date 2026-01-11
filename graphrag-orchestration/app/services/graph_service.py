"""
Multi-Tenant Neo4j Graph Service.

This module provides application-level tenant isolation for Neo4j Community Edition,
which lacks native Row Level Security. All nodes and relationships are tagged with
group_id and all queries enforce group_id filtering.

MIGRATION NOTE (2025-01):
Migrated from llama-index-graph-stores-neo4j to standalone implementation.
This enables neo4j driver v6.0+ compatibility for native Vector type support.
"""

from typing import List, Optional, Dict, Any, Tuple
import logging
import neo4j
from neo4j import GraphDatabase

# Use standalone store (compatible with neo4j driver v6.0+)
from app.services.neo4j_standalone_store import (
    StandaloneNeo4jStore,
    LabelledNode,
    Relation,
    EntityNode,
    ChunkNode,
    BASE_ENTITY_LABEL,
    BASE_NODE_LABEL,
    remove_empty_values,
)
from llama_index.core.vector_stores.types import (
    VectorStoreQuery,
    MetadataFilters,
    MetadataFilter,
    FilterOperator,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


class MultiTenantNeo4jStore(StandaloneNeo4jStore):
    """
    A tenant-aware Neo4j store extending StandaloneNeo4jStore.
    
    MIGRATION NOTE: Previously extended llama-index Neo4jPropertyGraphStore.
    Now extends our standalone implementation for neo4j driver v6.0+ compatibility.
    
    Security Model:
    - All nodes/edges get a `group_id` property on insert
    - All queries MUST filter by `group_id` to prevent cross-tenant data leakage
    - This is CRITICAL because Neo4j Community Edition has no native RLS
    
    Vector Query Handling:
    - Supports vector similarity search via Neo4j vector indices
    - Compatible with neo4j driver v6.0+ native Vector type
    """
    
    def __init__(
        self, 
        group_id: str,
        username: str,
        password: str,
        url: str,
        database: str = "neo4j",
        **kwargs
    ):
        super().__init__(
            group_id=group_id,
            username=username,
            password=password,
            url=url,
            database=database,
            **kwargs
        )
        # Enable vector support for Cloud Neo4j
        self._supports_vector_index = True
        logger.info(f"Initialized MultiTenantNeo4jStore for group: {group_id} (vector support enabled)")
    
    @property
    def supports_vector_queries(self) -> bool:
        """
        Enable vector queries since we confirmed Neo4j supports vector.similarity.cosine.
        """
        return True

    def vector_query_llama(
        self,
        query: VectorStoreQuery,
        **kwargs: Any,
    ) -> Tuple[List[LabelledNode], List[float]]:
        """
        Execute a vector query with mandatory group_id filtering.
        
        NOTE: This method accepts LlamaIndex VectorStoreQuery format for backward compatibility.
        It extracts the embedding and calls the parent's simpler vector_query method.
        """
        # Extract embedding from LlamaIndex query
        if query.query_embedding is None:
            raise ValueError("query_embedding is required for vector search")
        
        # Get index name from kwargs or use default
        index_name = kwargs.get("index_name", "entity_embedding")
        top_k = query.similarity_top_k or 10
        
        # Call parent's vector_query with simpler signature
        return super().vector_query(
            embedding=query.query_embedding,
            index_name=index_name,
            top_k=top_k,
        )

    async def aquery(self, query: str, params: Optional[dict] = None):
        """
        Async query method - delegates to structured_query.
        This is a convenience alias for compatibility with code expecting aquery().
        """
        return await self.astructured_query(query, param_map=params)

    def upsert_nodes(self, nodes: List[LabelledNode]) -> None:
        """
        Inject group_id into all nodes.
        """
        # EntityNode and ChunkNode already imported from neo4j_standalone_store
        
        # Separate and prepare nodes
        entity_dicts = []
        chunk_dicts = []
        
        for item in nodes:
            # Add group_id for multi-tenancy
            if item.properties is None:
                item.properties = {}
            item.properties["group_id"] = self.group_id
            
            # Convert to dict
            node_dict = {**item.dict(), "id": item.id}
            # We KEEP embeddings now because Neo4j supports them
            if item.embedding:
                logger.info(f"Node {item.id} has embedding of length {len(item.embedding)}")
            else:
                logger.warning(f"Node {item.id} has NO embedding")
            
            if isinstance(item, EntityNode):
                entity_dicts.append(node_dict)
            elif isinstance(item, ChunkNode):
                chunk_dicts.append(node_dict)
        
        # Upsert chunks (without embeddings)
        if chunk_dicts:
            CHUNK_SIZE = 1000
            for index in range(0, len(chunk_dicts), CHUNK_SIZE):
                chunked_params = chunk_dicts[index : index + CHUNK_SIZE]
                self.structured_query(
                    """
                    UNWIND $data AS row
                    MERGE (c:`__Node__` {id: row.id})
                    SET c.text = row.text, c:Chunk
                    SET c += row.properties
                    SET c.embedding = row.embedding
                    """,
                    param_map={"data": chunked_params},
                )
        
        # Upsert entities (without embeddings)
        if entity_dicts:
            CHUNK_SIZE = 1000
            for index in range(0, len(entity_dicts), CHUNK_SIZE):
                chunked_params = entity_dicts[index : index + CHUNK_SIZE]
                self.structured_query(
                    """
                    UNWIND $data AS row
                    MERGE (e:`__Entity__` {id: row.id})
                    SET e.name = row.name, e:`__Entity__`
                    SET e += row.properties
                    SET e.embedding = row.embedding
                    WITH e, row
                    CALL apoc.create.addLabels(e, [row.label])
                    YIELD node
                    WITH e, row WHERE row.properties.triplet_source_id IS NOT NULL
                    MERGE (c:Chunk {id: row.properties.triplet_source_id})
                    MERGE (e)-[:MENTIONS]->(c)
                    """,
                    param_map={"data": chunked_params},
                )
            # Update importance scores for newly upserted entities
            entity_ids = [e["id"] for e in entity_dicts]
            self._compute_entity_importance(entity_ids)
        
        logger.debug(f"Upserted {len(nodes)} nodes for group {self.group_id} (embeddings included)")

    def _compute_entity_importance(self, entity_ids: List[str]) -> None:
        """
        Compute importance scores for entities using native Cypher (no GDS required).
        
        Properties set:
        - degree: Total number of relationships (higher = more connected)
        - chunk_count: Number of chunk nodes this entity mentions
        - importance_score: Combined score (degree * 0.3 + chunk_count * 0.7)
        
        Args:
            entity_ids: List of entity IDs to update. If empty, updates all entities in group.
        """
        if not entity_ids:
            return
        
        logger.debug(f"Computing importance for {len(entity_ids)} entities in group {self.group_id}")
        
        try:
            # Use COUNT{} syntax for Neo4j 5.x compatibility (size() deprecated for patterns)
            self.structured_query(
                """
                UNWIND $entity_ids AS eid
                MATCH (e:`__Entity__` {id: eid})
                WHERE e.group_id = $group_id
                WITH e, COUNT { (e)-[]-() } AS degree
                SET e.degree = degree
                WITH e
                WITH e, COUNT { (e)<-[:MENTIONS]-(:TextChunk) } AS chunk_count
                SET e.chunk_count = chunk_count
                SET e.importance_score = coalesce(e.degree, 0) * 0.3 + chunk_count * 0.7
                """,
                param_map={"entity_ids": entity_ids, "group_id": self.group_id},
            )
            logger.debug(f"Computed importance scores for {len(entity_ids)} entities")
        except Exception as e:
            # Non-fatal: importance scoring is enhancement, not critical
            logger.warning(f"Failed to compute entity importance: {e}")

    def upsert_relations(self, relations: List[Relation]) -> None:
        """
        Inject group_id into all relations before upserting.
        """
        for relation in relations:
            if relation.properties is None:
                relation.properties = {}
            relation.properties["group_id"] = self.group_id
        
        logger.debug(f"Upserting {len(relations)} relations for group {self.group_id}")
        super().upsert_relations(relations)

    def get(
        self,
        properties: Optional[dict] = None,
        ids: Optional[List[str]] = None,
    ) -> List[LabelledNode]:
        """
        Override get to enforce group_id filtering.
        """
        # Inject group_id filter
        if properties is None:
            properties = {}
        properties["group_id"] = self.group_id
        
        return super().get(properties=properties, ids=ids)

    def get_triplets(
        self,
        entity_names: Optional[List[str]] = None,
        relation_names: Optional[List[str]] = None,
        properties: Optional[dict] = None,
        ids: Optional[List[str]] = None,
    ) -> List[Tuple[LabelledNode, Relation, LabelledNode]]:
        """
        Override get_triplets to enforce group_id filtering.
        """
        logger.info("get_triplets called")
        if properties is None:
            properties = {}
        properties["group_id"] = self.group_id
        
        # Parent uses relation_types, we accept relation_names for backward compatibility
        results = super().get_triplets(
            entity_names=entity_names,
            relation_types=relation_names,  # Map relation_names to relation_types
            properties=properties,
        )
        logger.info(f"get_triplets returned {len(results)} triplets")
        if results:
            logger.info(f"First triplet type: {type(results[0])}")
            logger.info(f"First triplet[0] type: {type(results[0][0])}")
            logger.info(f"First triplet[0]: {results[0][0]}")
            
            # Scan for bad triplets
            for i, triplet in enumerate(results):
                if not hasattr(triplet[0], 'id'):
                    logger.error(f"Triplet {i} element 0 has no id! Type: {type(triplet[0])}, Value: {triplet[0]}")
                if not hasattr(triplet[2], 'id'):
                    logger.error(f"Triplet {i} element 2 has no id! Type: {type(triplet[2])}, Value: {triplet[2]}")
                    
        return results

    def get_rel_map(
        self, 
        nodes: List[Any], 
        depth: int = 1, 
        limit: int = 30, 
        ignore_rels: Optional[List[str]] = None
    ) -> List[Tuple[LabelledNode, Relation, LabelledNode]]:
        """
        Override get_rel_map to enforce group_id filtering during graph traversal.
        Returns triplets (source, relation, target) for the given nodes, filtered by group_id.
        """
        logger.info(f"get_rel_map called with {len(nodes)} nodes, depth={depth}")
        
        if not nodes:
            return []
        
        triples = []
        ids = [node.id for node in nodes]
        
        # Query for relationships with group_id filtering
        # This is the key difference from the base implementation
        response = self.structured_query(
            f"""
            WITH $ids AS id_list
            UNWIND range(0, size(id_list) - 1) AS idx
            MATCH (e:`{BASE_ENTITY_LABEL}`)
            WHERE e.id = id_list[idx] AND e.group_id = $group_id
            MATCH p=(e)-[r*1..{depth}]-(other)
            WHERE ALL(rel in relationships(p) WHERE type(rel) <> 'MENTIONS')
              AND other.group_id = $group_id
            UNWIND relationships(p) AS rel
            WITH distinct rel, idx
            WITH startNode(rel) AS source,
                type(rel) AS type,
                rel{{.*}} AS rel_properties,
                endNode(rel) AS endNode,
                idx
            WHERE source.group_id = $group_id AND endNode.group_id = $group_id
            LIMIT toInteger($limit)
            RETURN source.id AS source_id, [l in labels(source)
                   WHERE NOT l IN ['{BASE_ENTITY_LABEL}', '{BASE_NODE_LABEL}'] | l][0] AS source_type,
                source{{.* , embedding: Null, id: Null}} AS source_properties,
                type,
                rel_properties,
                endNode.id AS target_id, [l in labels(endNode)
                   WHERE NOT l IN ['{BASE_ENTITY_LABEL}', '{BASE_NODE_LABEL}'] | l][0] AS target_type,
                endNode{{.* , embedding: Null, id: Null}} AS target_properties,
                idx
            ORDER BY idx
            """,
            param_map={"ids": ids, "limit": limit, "group_id": self.group_id},
        )
        response = response if response else []
        
        logger.info(f"get_rel_map query returned {len(response)} records")
        
        ignore_rels = ignore_rels or []
        for record in response:
            if record["type"] in ignore_rels:
                continue

            source = EntityNode(
                name=record["source_id"],
                label=record["source_type"],
                properties=remove_empty_values(record["source_properties"]) if record["source_properties"] else {},
            )
            target = EntityNode(
                name=record["target_id"],
                label=record["target_type"],
                properties=remove_empty_values(record["target_properties"]) if record["target_properties"] else {},
            )
            rel = Relation(
                source_id=record["source_id"],
                target_id=record["target_id"],
                label=record["type"],
                properties=remove_empty_values(record["rel_properties"]) if record["rel_properties"] else {},
            )
            triples.append([source, rel, target])
        
        logger.info(f"get_rel_map returning {len(triples)} triplets")
        return triples

    def structured_query(
        self,
        query: str,
        param_map: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute a raw Cypher query with mandatory group_id filtering.
        
        WARNING: This method allows raw Cypher. Callers MUST include group_id
        in their WHERE clause. This is a safety net, not a guarantee.
        """
        if param_map is None:
            param_map = {}
        
        # Always inject group_id parameter
        param_map["group_id"] = self.group_id
        
        # System-level queries that don't need group_id filtering
        system_query_keywords = [
            "SHOW CONSTRAINTS", "SHOW INDEXES", "CREATE CONSTRAINT", "DROP CONSTRAINT",
            "CREATE INDEX", "DROP INDEX", "CREATE VECTOR INDEX", "DROP VECTOR INDEX",
            "CALL apoc.", "CALL dbms.", "CALL db.", "CALL gds."
        ]
        is_system_query = any(keyword.lower() in query.lower() for keyword in system_query_keywords)
        
        # Log a warning if the query doesn't seem to filter by group_id (unless it's a system query)
        if not is_system_query and "group_id" not in query.lower():
            logger.warning(
                f"Cypher query may not filter by group_id! "
                f"Query: {query[:100]}..."
            )
        
        return super().structured_query(query, param_map)


class GraphService:
    """
    Singleton service for managing Neo4j connections and graph operations.
    
    This service:
    1. Maintains a shared Neo4j driver for connection pooling
    2. Provides tenant-aware graph stores via get_store(group_id)
    3. Handles Graph Data Science (GDS) operations for community detection
    """
    
    _instance: Optional["GraphService"] = None
    _driver: Optional[Any] = None  # neo4j.Driver when connected

    def __new__(cls) -> "GraphService":
        if cls._instance is None:
            cls._instance = super(GraphService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    @property
    def driver(self) -> Optional[Any]:
        """Get the Neo4j driver instance."""
        return self._driver

    @property
    def config(self) -> Dict[str, Any]:
        """Get the current configuration for health checks."""
        return {
            "NEO4J_URI": settings.NEO4J_URI,
            "NEO4J_USERNAME": settings.NEO4J_USERNAME,
        }

    def _initialize(self) -> None:
        """Initialize the shared Neo4j driver."""
        if settings.NEO4J_URI and settings.NEO4J_USERNAME and settings.NEO4J_PASSWORD:
            try:
                driver = GraphDatabase.driver(
                    settings.NEO4J_URI,
                    auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
                )
                # Verify connectivity
                driver.verify_connectivity()
                self._driver = driver
                logger.info(f"Connected to Neo4j at {settings.NEO4J_URI}")
                
                # Initialize vector indices for hybrid routes
                self._initialize_vector_indices()
                
                # Initialize uniqueness constraints for Cypher 25 MergeUniqueNode optimization
                self._initialize_uniqueness_constraints()
            except Exception as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
                self._driver = None
        else:
            logger.warning("NEO4J_URI not configured, graph store disabled")

    def _initialize_uniqueness_constraints(self) -> None:
        """
        Create uniqueness constraints for MergeUniqueNode optimization.
        
        Cypher 25 includes a MergeUniqueNode operator that bypasses the
        standard "check then write" overhead when MERGE is used on properties
        with uniqueness constraints. This significantly improves write performance.
        
        These constraints also ensure data integrity by preventing duplicates.
        """
        if not self._driver:
            return
        
        # Uniqueness constraints for core node types
        # These enable the MergeUniqueNode optimizer in Cypher 25
        constraint_queries = [
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:`__Entity__`) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:TextChunk) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT node_id_unique IF NOT EXISTS FOR (n:`__Node__`) REQUIRE n.id IS UNIQUE",
        ]
        
        try:
            with self._driver.session() as session:
                for query in constraint_queries:
                    try:
                        session.run(query)
                    except Exception as constraint_err:
                        # Continue if constraint already exists or fails
                        logger.debug(f"Constraint creation skipped/failed: {constraint_err}")
                logger.info("Uniqueness constraints initialized (MergeUniqueNode optimization enabled)")
        except Exception as e:
            logger.warning(f"Failed to initialize uniqueness constraints: {e}")

    def _initialize_vector_indices(self) -> None:
        """Create vector indices for TextChunk embeddings used by Route 1."""
        if not self._driver:
            return
        
        vector_index_query = """
        CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
        FOR (t:TextChunk) ON (t.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 3072,
            `vector.similarity_function`: 'cosine'
        }}
        """
        
        try:
            with self._driver.session() as session:
                session.run(vector_index_query)
                logger.info("Vector index 'chunk_embedding' created/verified for TextChunk nodes")
        except Exception as e:
            logger.warning(f"Failed to create vector index (may already exist): {e}")

    def get_store(self, group_id: str) -> MultiTenantNeo4jStore:
        """
        Get a tenant-aware graph store instance.
        
        Args:
            group_id: The tenant identifier for isolation
            
        Returns:
            MultiTenantNeo4jStore configured for the specified tenant
        """
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        if not settings.NEO4J_USERNAME or not settings.NEO4J_PASSWORD or not settings.NEO4J_URI:
            raise RuntimeError("Neo4j credentials not configured")
            
        return MultiTenantNeo4jStore(
            group_id=group_id,
            username=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
            url=settings.NEO4J_URI,
        )

    def run_community_detection(
        self, 
        group_id: str, 
        algorithm: str = "leiden"
    ) -> Dict[str, Any]:
        """
        Run community detection using Neo4j Graph Data Science (GDS).
        
        This is the core of GraphRAG's "Global Search" capability.
        Requires the GDS plugin to be installed in Neo4j.
        
        Args:
            group_id: Tenant identifier for isolation
            algorithm: Community detection algorithm (leiden, louvain)
            
        Returns:
            Dictionary with community statistics
        """
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        # Project the graph for GDS (filtered by group_id)
        project_query = """
        CALL gds.graph.project.cypher(
            $graph_name,
            'MATCH (n) WHERE n.group_id = $group_id RETURN id(n) AS id, labels(n) AS labels',
            'MATCH (n)-[r]->(m) WHERE n.group_id = $group_id AND m.group_id = $group_id 
             RETURN id(n) AS source, id(m) AS target, type(r) AS type'
        )
        YIELD graphName, nodeCount, relationshipCount
        RETURN graphName, nodeCount, relationshipCount
        """
        
        graph_name = f"graphrag_{group_id}"
        
        with self._driver.session() as session:
            # Drop existing projection if exists
            try:
                session.run("CALL gds.graph.drop($name, false)", name=graph_name)
            except Exception:
                pass  # Graph doesn't exist, that's fine
            
            # Create new projection
            result = session.run(
                project_query,
                graph_name=graph_name,
                group_id=group_id
            )
            projection_stats = result.single()
            
            # Run community detection
            if algorithm == "leiden":
                community_query = """
                CALL gds.leiden.write($graph_name, {
                    writeProperty: 'community',
                    includeIntermediateCommunities: true
                })
                YIELD communityCount, modularity
                RETURN communityCount, modularity
                """
            else:  # louvain
                community_query = """
                CALL gds.louvain.write($graph_name, {
                    writeProperty: 'community',
                    includeIntermediateCommunities: true
                })
                YIELD communityCount, modularity
                RETURN communityCount, modularity
                """
            
            result = session.run(community_query, graph_name=graph_name)
            community_stats = result.single()
            
            # Cleanup projection
            session.run("CALL gds.graph.drop($name)", name=graph_name)
            
            return {
                "graph_name": graph_name,
                "node_count": projection_stats["nodeCount"],
                "relationship_count": projection_stats["relationshipCount"],
                "community_count": community_stats["communityCount"],
                "modularity": community_stats["modularity"],
            }

    def get_community_summaries(
        self, 
        group_id: str, 
        level: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Retrieve community summaries for GraphRAG Global Search.
        
        Args:
            group_id: Tenant identifier
            level: Community hierarchy level (0 = most granular)
            
        Returns:
            List of community summaries with member counts
        """
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        query = """
        MATCH (n)
        WHERE n.group_id = $group_id AND n.community IS NOT NULL
        WITH n.community[$level] AS community_id, collect(n) AS members
        RETURN community_id, 
               size(members) AS member_count,
               [m IN members | m.name][..5] AS sample_members
        ORDER BY member_count DESC
        """
        
        with self._driver.session() as session:
            result = session.run(query, group_id=group_id, level=level)
            return [dict(record) for record in result]

    def health_check(self) -> Dict[str, Any]:
        """Check Neo4j connectivity and return status."""
        if not self._driver:
            return {"status": "disconnected", "error": "Driver not initialized"}
        
        try:
            with self._driver.session() as session:
                result = session.run("RETURN 1 AS ping")
                result.single()
            return {"status": "connected", "uri": settings.NEO4J_URI}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def list_indexed_documents(self, group_id: str) -> List[Dict[str, Any]]:
        """
        List all unique documents that have been indexed in the graph.
        
        Args:
            group_id: Tenant identifier for isolation
            
        Returns:
            List of documents with metadata:
            - url: Original source URL
            - page_count: Number of pages indexed
            - node_count: Number of nodes created from this document
            - indexed_at: Timestamp (if available)
        """
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        query = """
        MATCH (n)
        WHERE n.group_id = $group_id AND n.url IS NOT NULL
        WITH n.url AS url, 
             count(DISTINCT n) AS node_count,
             count(DISTINCT n.page_number) AS page_count,
             collect(DISTINCT n.page_number) AS pages
        RETURN url, node_count, page_count, pages
        ORDER BY url
        """
        
        with self._driver.session() as session:
            result = session.run(query, group_id=group_id)
            return [dict(record) for record in result]

    def delete_document_by_url(self, group_id: str, url: str) -> Dict[str, Any]:
        """
        Delete all nodes and relationships associated with a document URL.
        
        Args:
            group_id: Tenant identifier for isolation
            url: Document URL to delete
            
        Returns:
            Deletion statistics:
            - nodes_deleted: Number of nodes removed
            - relationships_deleted: Number of relationships removed
        """
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        query = """
        MATCH (n)
        WHERE n.group_id = $group_id AND n.url = $url
        WITH n, [(n)-[r]-() | r] AS rels
        WITH n, rels, 
             size(rels) AS rel_count,
             size(collect(n)) AS node_count
        DETACH DELETE n
        RETURN sum(node_count) AS nodes_deleted, sum(rel_count) AS relationships_deleted
        """
        
        with self._driver.session() as session:
            result = session.run(query, group_id=group_id, url=url)
            record = result.single()
            if record:
                return {
                    "url": url,
                    "nodes_deleted": record["nodes_deleted"] or 0,
                    "relationships_deleted": record["relationships_deleted"] or 0,
                }
            return {"url": url, "nodes_deleted": 0, "relationships_deleted": 0}

    def delete_all_documents(self, group_id: str) -> Dict[str, Any]:
        """
        Delete ALL nodes and relationships for a tenant (DANGEROUS).
        
        Args:
            group_id: Tenant identifier for isolation
            
        Returns:
            Deletion statistics
        """
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        query = """
        MATCH (n {group_id: $group_id})
        DETACH DELETE n
        RETURN count(n) AS nodes_deleted
        """
        
        with self._driver.session() as session:
            result = session.run(query, group_id=group_id)
            record = result.single()
            return {
                "group_id": group_id,
                "nodes_deleted": record["nodes_deleted"] if record else 0,
            }

    def get_document_stats(self, group_id: str, url: str) -> Dict[str, Any]:
        """
        Get detailed statistics for a specific document.
        
        Args:
            group_id: Tenant identifier
            url: Document URL
            
        Returns:
            Document statistics including node types, relationship counts
        """
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        query = """
        MATCH (n)
        WHERE n.group_id = $group_id AND n.url = $url
        WITH n, labels(n) AS node_labels
        RETURN 
            count(n) AS total_nodes,
            collect(DISTINCT node_labels) AS label_sets,
            collect(DISTINCT n.page_number) AS pages
        """
        
        with self._driver.session() as session:
            result = session.run(query, group_id=group_id, url=url)
            record = result.single()
            if record:
                return {
                    "url": url,
                    "total_nodes": record["total_nodes"],
                    "label_sets": record["label_sets"],
                    "pages": sorted(record["pages"]) if record["pages"] else [],
                }
            return {"url": url, "total_nodes": 0, "label_sets": [], "pages": []}

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j driver closed")
