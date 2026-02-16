"""
Standalone Neo4j Store - No llama-index-graph-stores-neo4j Dependency

This module provides a direct Neo4j interface without requiring llama-index-graph-stores-neo4j,
enabling compatibility with neo4j driver v6.0+ for native Vector type support.

The key difference:
- llama-index-graph-stores-neo4j: blocks neo4j driver v6.0+ (requires neo4j<6,>=5.16.0)
- llama-index-core: compatible with neo4j driver v6.0+ (no neo4j dependency conflict)

We still use llama-index-core types (LabelledNode, EntityNode, Relation, etc.) for API 
compatibility with existing code, but remove the Neo4jPropertyGraphStore inheritance.

Replaces: MultiTenantNeo4jStore (which inherited from Neo4jPropertyGraphStore)
"""

from typing import List, Optional, Dict, Any, Tuple
import logging
from neo4j import GraphDatabase

# Still use llama-index-core types for API compatibility (doesn't conflict with driver v6)
from llama_index.core.graph_stores.types import LabelledNode, Relation, EntityNode, ChunkNode
from llama_index.core.vector_stores.types import (
    VectorStoreQuery,
    MetadataFilters,
    MetadataFilter,
    FilterOperator,
)

from src.core.config import settings

logger = logging.getLogger(__name__)

# Constants matching previous Neo4j PropertyGraphStore label conventions
BASE_ENTITY_LABEL = "__Entity__"
BASE_NODE_LABEL = "__Node__"


def remove_empty_values(d: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys with None or empty values from a dictionary."""
    return {k: v for k, v in d.items() if v is not None and v != ""}


class StandaloneNeo4jStore:
    """
    A standalone, tenant-aware Neo4j store without LlamaIndex dependency.
    
    Compatible with neo4j driver v6.0+ for native Vector type support.
    
    Security Model:
    - All nodes/edges get a `group_id` property on insert
    - All queries MUST filter by `group_id` to prevent cross-tenant data leakage
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
        self.group_id = group_id
        self.database = database
        self._driver = GraphDatabase.driver(url, auth=(username, password))
        
        # Check driver version for Vector support
        try:
            import neo4j
            self._driver_version = tuple(int(x) for x in neo4j.__version__.split('.')[:2])
            self._supports_native_vector = self._driver_version >= (6, 0)
        except:
            self._driver_version = (5, 0)
            self._supports_native_vector = False
        
        logger.info(
            f"Initialized StandaloneNeo4jStore for group: {group_id} "
            f"(driver v{neo4j.__version__}, native_vector={self._supports_native_vector})"
        )
    
    def close(self):
        """Close the driver connection."""
        if self._driver:
            self._driver.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    @property
    def driver(self):
        """Get the underlying Neo4j driver."""
        return self._driver
    
    @property
    def supports_native_vector(self) -> bool:
        """Check if driver supports native Vector type (v6.0+)."""
        return self._supports_native_vector
    
    def _convert_to_vector(self, embedding: List[float]) -> Any:
        """
        Convert embedding to native Vector if supported, else return list.
        
        For neo4j driver v6.0+, uses native Vector type from neo4j.vector module.
        Uses float32 (f32) dtype which is standard for embeddings.
        For older drivers, returns List[float] which still works.
        """
        if embedding is None:
            return None
        
        if self._supports_native_vector:
            try:
                from neo4j.vector import Vector
                # Use f32 (float32) dtype for embeddings - standard format
                return Vector(embedding, 'f32')
            except ImportError:
                pass
        
        return embedding
    
    def structured_query(
        self,
        query: str,
        param_map: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a raw Cypher query with mandatory group_id filtering.
        
        Returns list of record dictionaries.
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
        
        # Log a warning if the query doesn't filter by group_id (unless system query)
        if not is_system_query and "group_id" not in query.lower():
            logger.warning(
                f"Cypher query may not filter by group_id! "
                f"Query: {query[:100]}..."
            )
        
        with self._driver.session(database=self.database) as session:
            result = session.run(query, param_map)
            return [dict(record) for record in result]
    
    async def astructured_query(
        self,
        query: str,
        param_map: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Async version of structured_query for compatibility with async code.
        
        Note: Neo4j Python driver's async session requires careful handling.
        This implementation uses run_in_executor for simplicity.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            lambda: self.structured_query(query, param_map)
        )
    
    def upsert_nodes(self, nodes: List[LabelledNode]) -> None:
        """
        Insert or update nodes with group_id tagging.
        """
        entity_dicts = []
        chunk_dicts = []
        
        for item in nodes:
            # Add group_id for multi-tenancy
            if item.properties is None:
                item.properties = {}
            item.properties["group_id"] = self.group_id
            
            # Convert to dict
            node_dict = item.dict() if hasattr(item, 'dict') else {
                "id": item.id,
                "label": item.label,
                "properties": item.properties,
                "embedding": item.embedding,
                "text": item.text,
            }
            node_dict["id"] = item.id
            
            # Convert embedding to native Vector if supported
            if node_dict.get("embedding"):
                node_dict["embedding"] = self._convert_to_vector(node_dict["embedding"])
            
            if isinstance(item, EntityNode):
                node_dict["name"] = item.name
                entity_dicts.append(node_dict)
            elif isinstance(item, ChunkNode):
                chunk_dicts.append(node_dict)
            else:
                # Generic node
                chunk_dicts.append(node_dict)
        
        # Upsert chunks
        if chunk_dicts:
            CHUNK_SIZE = 1000
            for index in range(0, len(chunk_dicts), CHUNK_SIZE):
                chunked_params = chunk_dicts[index : index + CHUNK_SIZE]
                self.structured_query(
                    """
                    UNWIND $data AS row
                    MERGE (c:`__Node__` {id: row.id, group_id: $group_id})
                    SET c.text = row.text, c:Chunk
                    SET c += row.properties
                    SET c.embedding = row.embedding
                    SET c.group_id = $group_id
                    """,
                    param_map={"data": chunked_params},
                )
        
        # Upsert entities
        if entity_dicts:
            CHUNK_SIZE = 1000
            for index in range(0, len(entity_dicts), CHUNK_SIZE):
                chunked_params = entity_dicts[index : index + CHUNK_SIZE]
                # Note: Using direct labels instead of apoc.create.addLabels
                # for broader compatibility
                self.structured_query(
                    """
                    UNWIND $data AS row
                    MERGE (e:`__Entity__` {id: row.id, group_id: $group_id})
                    SET e.name = row.name
                    SET e += row.properties
                    SET e.embedding = row.embedding
                    SET e.group_id = $group_id
                    WITH e, row
                    WHERE row.properties.triplet_source_id IS NOT NULL
                    MERGE (c:Chunk {id: row.properties.triplet_source_id, group_id: $group_id})
                    MERGE (e)-[:MENTIONS]->(c)
                    """,
                    param_map={"data": chunked_params},
                )
    
    def upsert_relations(self, relations: List[Relation]) -> None:
        """
        Insert or update relationships with group_id tagging.
        """
        if not relations:
            return
        
        rel_dicts = []
        for rel in relations:
            rel_dicts.append({
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "label": rel.label,
                "properties": {**rel.properties, "group_id": self.group_id},
            })
        
        CHUNK_SIZE = 1000
        for index in range(0, len(rel_dicts), CHUNK_SIZE):
            chunked_params = rel_dicts[index : index + CHUNK_SIZE]
            self.structured_query(
                """
                UNWIND $data AS row
                MATCH (source {id: row.source_id, group_id: $group_id})
                MATCH (target {id: row.target_id, group_id: $group_id})
                MERGE (source)-[r:RELATED_TO {label: row.label}]->(target)
                SET r += row.properties
                """,
                param_map={"data": chunked_params},
            )
    
    def get(
        self,
        properties: Optional[Dict[str, Any]] = None,
        ids: Optional[List[str]] = None,
    ) -> List[LabelledNode]:
        """
        Retrieve nodes by properties or IDs.
        """
        if ids:
            query = """
            MATCH (n)
            WHERE n.id IN $ids AND n.group_id = $group_id
            RETURN n
            """
            results = self.structured_query(query, param_map={"ids": ids})
        elif properties:
            # Build WHERE clause from properties
            where_clauses = [f"n.{k} = ${k}" for k in properties.keys()]
            where_str = " AND ".join(where_clauses)
            query = f"""
            MATCH (n)
            WHERE {where_str} AND n.group_id = $group_id
            RETURN n
            """
            results = self.structured_query(query, param_map=properties)
        else:
            return []
        
        nodes = []
        for record in results:
            n = record.get("n", {})
            if hasattr(n, 'items'):
                props = dict(n.items())
            else:
                props = dict(n) if n else {}
            
            node = LabelledNode(
                id=props.get("id", ""),
                label=props.get("label", ""),
                properties=props,
                embedding=props.get("embedding"),
                text=props.get("text"),
            )
            nodes.append(node)
        
        return nodes
    
    def vector_query(
        self,
        embedding: List[float],
        index_name: str = "entity_embedding",
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[LabelledNode], List[float]]:
        """
        Execute a vector similarity search using Neo4j's native vector index.
        
        Args:
            embedding: Query embedding vector
            index_name: Name of the vector index
            top_k: Number of results
            filters: Additional filters (must include group_id)
            
        Returns:
            Tuple of (nodes, scores)
        """
        # Convert embedding for native Vector support
        query_embedding = self._convert_to_vector(embedding)
        
        # SEARCH clause with in-index group_id filtering (Cypher 25)
        # Note: SEARCH requires literal index name, not a $parameter.
        # Infer node label from index name for the MATCH clause.
        _label_map = {
            "entity_embedding": "Entity",
            "entity_embedding_v2": "Entity",
            "entity_embedding_v2_internal": "`__Entity__`",
            "chunk_embedding": "TextChunk",
            "chunk_embeddings_v2": "TextChunk",
            "sentence_embeddings_v2": "Sentence",
            "raptor_embedding": "RaptorNode",
        }
        node_label = _label_map.get(index_name, "Entity")
        
        query = f"""CYPHER 25
        MATCH (node:{node_label})
        SEARCH node IN (VECTOR INDEX {index_name} FOR $embedding WHERE node.group_id = $group_id LIMIT $top_k)
        SCORE AS score
        RETURN node, score
        ORDER BY score DESC
        """
        
        results = self.structured_query(
            query,
            param_map={
                "top_k": top_k,
                "embedding": query_embedding,
            }
        )
        
        nodes = []
        scores = []
        for record in (results or [])[:top_k]:
            n = record.get("node", {})
            if hasattr(n, 'items'):
                props = dict(n.items())
            else:
                props = dict(n) if n else {}
            
            node = LabelledNode(
                id=props.get("id", ""),
                label=props.get("label", ""),
                properties=props,
                embedding=props.get("embedding"),
                text=props.get("text"),
            )
            nodes.append(node)
            scores.append(record.get("score", 0.0))
        
        logger.info(f"Vector query returned {len(nodes)} nodes")
        return nodes, scores
    
    def get_triplets(
        self,
        entity_names: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[LabelledNode, Relation, LabelledNode]]:
        """
        Retrieve triplets (source, relation, target) from the graph.
        """
        where_clauses = [
            "source.group_id = $group_id",
            "target.group_id = $group_id",
            "r.group_id = $group_id",
        ]
        param_map: Dict[str, Any] = {}
        
        if entity_names:
            where_clauses.append("(source.name IN $entity_names OR target.name IN $entity_names)")
            param_map["entity_names"] = entity_names
        
        if relation_types:
            where_clauses.append("type(r) IN $relation_types")
            param_map["relation_types"] = relation_types
        
        where_str = " AND ".join(where_clauses)
        
        query = f"""
        MATCH (source)-[r]->(target)
        WHERE {where_str}
        RETURN source, r, target
        LIMIT 1000
        """
        
        results = self.structured_query(query, param_map=param_map)
        
        triplets = []
        for record in (results or []):
            source_props = dict(record.get("source", {}).items()) if record.get("source") else {}
            target_props = dict(record.get("target", {}).items()) if record.get("target") else {}
            rel = record.get("r", {})
            rel_props = dict(rel.items()) if hasattr(rel, 'items') else {}
            
            source_node = LabelledNode(
                id=source_props.get("id", ""),
                properties=source_props,
                text=source_props.get("text"),
            )
            target_node = LabelledNode(
                id=target_props.get("id", ""),
                properties=target_props,
                text=target_props.get("text"),
            )
            relation = Relation(
                source_id=source_props.get("id", ""),
                target_id=target_props.get("id", ""),
                label=type(rel).__name__ if hasattr(rel, '__class__') else str(rel.type) if hasattr(rel, 'type') else "RELATED",
                properties=rel_props,
            )
            triplets.append((source_node, relation, target_node))
        
        return triplets
    
    def delete_nodes(self, ids: List[str]) -> int:
        """Delete nodes by ID (with group_id check)."""
        if not ids:
            return 0
        
        query = """
        MATCH (n)
        WHERE n.id IN $ids AND n.group_id = $group_id
        DETACH DELETE n
        RETURN count(n) as deleted
        """
        results = self.structured_query(query, param_map={"ids": ids})
        return results[0].get("deleted", 0) if results else 0
    
    def delete_all(self) -> Dict[str, int]:
        """Delete all data for the current group_id."""
        query = """
        MATCH (n {group_id: $group_id})
        WITH n, labels(n) as labels
        DETACH DELETE n
        RETURN count(n) as deleted
        """
        results = self.structured_query(query)
        return {"deleted": results[0].get("deleted", 0) if results else 0}


# For backward compatibility - alias to old name pattern
MultiTenantNeo4jStore = StandaloneNeo4jStore
