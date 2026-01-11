"""
Neo4j Hybrid Search Service for GraphRAG Seed Node Discovery.

This implements Step 7 of the best-quality GraphRAG pipeline:
- Combines Vector Search (semantic similarity via embeddings)
- With Full-Text Search (keyword/BM25 matching on entity names)
- Uses Reciprocal Rank Fusion (RRF) to merge results

Reference: "Best quality graphrag pipeline including llamaindex, RAPTOR, 
Azure document intelligence and Azure AI search" discussion.

The hybrid search finds initial seed nodes that are then passed to 
Neo4j Cypher for multi-hop graph traversal (Step 8).
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
import logging
import asyncio

from app.services.graph_service import GraphService, MultiTenantNeo4jStore
from app.services.llm_service import LLMService
from app.core.config import settings

if TYPE_CHECKING:
    from llama_index.core.embeddings import BaseEmbedding

logger = logging.getLogger(__name__)


class Neo4jHybridSearchService:
    """
    Neo4j Hybrid Search for Seed Node Discovery (Step 7).
    
    Combines:
    1. Vector search (semantic similarity via embeddings on __Entity__ nodes)
    2. Full-text search (keyword/BM25 matching on entity names/descriptions)
    
    Uses Reciprocal Rank Fusion (RRF) to combine rankings from both methods.
    
    This is the key component that the discussion identifies as the 
    "query-time hybrid search" that happens ON Neo4j (not Azure AI Search).
    """
    
    # RRF parameter (typically 60)
    RRF_K = 60
    
    # Default weights for combining scores
    VECTOR_WEIGHT = 0.7
    FULLTEXT_WEIGHT = 0.3
    
    def __init__(self):
        self.graph_service = GraphService()
        self.llm_service = LLMService()
        
        # Index names (must match what's created in Neo4j)
        # Note: 'entity' index was created by PropertyGraphIndex; we use that name
        self.vector_index_name = "entity"
        self.fulltext_index_name = "entity_fulltext"
        self.chunk_vector_index_name = "chunk_vector"
    
    async def ensure_indexes_exist(self, group_id: str) -> Dict[str, bool]:
        """
        Ensure required indexes exist in Neo4j.
        
        Creates:
        1. Full-text index on __Entity__ nodes (name, id fields)
        2. Vector index on __Entity__ nodes (embedding field)
        
        Returns:
            Dict with status of each index creation
        """
        store = self.graph_service.get_store(group_id)
        results = {
            "fulltext_index": False,
            "vector_index": False,
            "chunk_vector_index": False,
        }
        
        # Create full-text index
        try:
            # Check if full-text index exists
            check_ft_query = """
            SHOW INDEXES
            WHERE name = $index_name
            RETURN name
            """
            existing = store.structured_query(
                check_ft_query,
                param_map={"index_name": self.fulltext_index_name}
            )
            
            if not existing:
                # Create full-text index on entity name and id
                create_ft_query = f"""
                CREATE FULLTEXT INDEX {self.fulltext_index_name} IF NOT EXISTS
                FOR (e:`__Entity__`)
                ON EACH [e.name, e.id]
                """
                store.structured_query(create_ft_query)
                logger.info(f"Created full-text index: {self.fulltext_index_name}")
            else:
                logger.info(f"Full-text index already exists: {self.fulltext_index_name}")
            
            results["fulltext_index"] = True
            
        except Exception as e:
            logger.error(f"Failed to create full-text index: {e}")
            results["fulltext_index"] = False
        
        # Create vector index
        try:
            # Check if vector index exists
            check_vec_query = """
            SHOW INDEXES
            WHERE name = $index_name
            RETURN name
            """
            existing = store.structured_query(
                check_vec_query,
                param_map={"index_name": self.vector_index_name}
            )
            
            if not existing:
                # Create vector index on entity embeddings
                # Note: dimensions should match your embedding model (3072 for text-embedding-3-large)
                create_vec_query = f"""
                CREATE VECTOR INDEX {self.vector_index_name} IF NOT EXISTS
                FOR (e:`__Entity__`)
                ON e.embedding
                OPTIONS {{
                    indexConfig: {{
                        `vector.dimensions`: 3072,
                        `vector.similarity_function`: 'cosine'
                    }}
                }}
                """
                store.structured_query(create_vec_query)
                logger.info(f"Created vector index: {self.vector_index_name}")
            else:
                logger.info(f"Vector index already exists: {self.vector_index_name}")
            
            results["vector_index"] = True
            
        except Exception as e:
            logger.error(f"Failed to create vector index: {e}")
            results["vector_index"] = False
        
        # Create chunk vector index (for Chunk/__Node__ embeddings)
        try:
            check_chunk_query = """
            SHOW INDEXES
            WHERE name = $index_name
            RETURN name
            """
            existing_chunk = store.structured_query(
                check_chunk_query,
                param_map={"index_name": self.chunk_vector_index_name}
            )
            if not existing_chunk:
                create_chunk_vec_query = f"""
                CREATE VECTOR INDEX {self.chunk_vector_index_name} IF NOT EXISTS
                FOR (c:`__Node__`)
                ON c.embedding
                OPTIONS {{
                    indexConfig: {{
                        `vector.dimensions`: 3072,
                        `vector.similarity_function`: 'cosine'
                    }}
                }}
                """
                store.structured_query(create_chunk_vec_query)
                logger.info(f"Created chunk vector index: {self.chunk_vector_index_name}")
            else:
                logger.info(f"Chunk vector index already exists: {self.chunk_vector_index_name}")
            results["chunk_vector_index"] = True
        except Exception as e:
            logger.error(f"Failed to create chunk vector index: {e}")
            results["chunk_vector_index"] = False
        
        return results
    
    async def find_seed_nodes(
        self, 
        query: str, 
        group_id: str,
        top_k: int = 10,
        use_rrf: bool = True,
        vector_weight: Optional[float] = None,
        fulltext_weight: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find seed nodes using Neo4j hybrid search (Vector + Full-Text).
        
        This is Step 7 of the GraphRAG query pipeline:
        "LlamaIndex → Neo4j Hybrid Search: Runs Vector + Full-Text search 
        on the target KG's index to find initial seed nodes"
        
        Args:
            query: User's natural language query
            group_id: Tenant identifier for multi-tenancy
            top_k: Number of seed nodes to return
            use_rrf: If True, use Reciprocal Rank Fusion; else weighted sum
            vector_weight: Weight for vector search scores (default 0.7)
            fulltext_weight: Weight for full-text search scores (default 0.3)
        
        Returns:
            List of seed node dicts with:
            - entity_id: Node ID
            - name: Entity name
            - combined_score: Hybrid score
            - vector_score: Vector similarity score
            - fulltext_score: Full-text relevance score
        """
        if vector_weight is None:
            vector_weight = self.VECTOR_WEIGHT
        if fulltext_weight is None:
            fulltext_weight = self.FULLTEXT_WEIGHT
        
        store = self.graph_service.get_store(group_id)
        
        # Generate query embedding
        if self.llm_service.embed_model is None:
            raise RuntimeError("Embedding model not initialized")
        
        query_embedding = self.llm_service.embed_model.get_text_embedding(query)
        
        if use_rrf:
            return await self._hybrid_search_rrf(
                store, query, query_embedding, group_id, top_k
            )
        else:
            return await self._hybrid_search_weighted(
                store, query, query_embedding, group_id, top_k,
                vector_weight, fulltext_weight
            )
    
    async def _hybrid_search_rrf(
        self,
        store: MultiTenantNeo4jStore,
        query: str,
        query_embedding: List[float],
        group_id: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search using Reciprocal Rank Fusion (RRF).
        
        RRF formula: score = 1 / (k + rank)
        where k is typically 60.
        
        This is the industry-standard approach used by Azure AI Search.
        """
        # Run both searches in parallel
        vector_results, fulltext_results = await asyncio.gather(
            self._vector_search(store, query_embedding, group_id, top_k * 2),
            self._fulltext_search(store, query, group_id, top_k * 2),
        )
        
        # Build RRF scores
        # Map entity_id -> {vector_rank, fulltext_rank, name, ...}
        entity_data: Dict[str, Dict[str, Any]] = {}
        
        # Process vector results
        for rank, result in enumerate(vector_results, start=1):
            entity_id = result["entity_id"]
            if entity_id not in entity_data:
                entity_data[entity_id] = {
                    "entity_id": entity_id,
                    "name": result.get("name", ""),
                    "vector_rank": None,
                    "fulltext_rank": None,
                    "vector_score": 0.0,
                    "fulltext_score": 0.0,
                }
            entity_data[entity_id]["vector_rank"] = rank
            entity_data[entity_id]["vector_score"] = result.get("score", 0.0)
        
        # Process full-text results
        for rank, result in enumerate(fulltext_results, start=1):
            entity_id = result["entity_id"]
            if entity_id not in entity_data:
                entity_data[entity_id] = {
                    "entity_id": entity_id,
                    "name": result.get("name", ""),
                    "vector_rank": None,
                    "fulltext_rank": None,
                    "vector_score": 0.0,
                    "fulltext_score": 0.0,
                }
            entity_data[entity_id]["fulltext_rank"] = rank
            entity_data[entity_id]["fulltext_score"] = result.get("score", 0.0)
        
        # Calculate RRF scores
        k = self.RRF_K
        for entity_id, data in entity_data.items():
            rrf_score = 0.0
            if data["vector_rank"] is not None:
                rrf_score += 1.0 / (k + data["vector_rank"])
            if data["fulltext_rank"] is not None:
                rrf_score += 1.0 / (k + data["fulltext_rank"])
            data["combined_score"] = rrf_score
        
        # Sort by RRF score and return top_k
        sorted_results = sorted(
            entity_data.values(),
            key=lambda x: x["combined_score"],
            reverse=True
        )[:top_k]
        
        logger.info(
            f"RRF hybrid search: {len(vector_results)} vector + "
            f"{len(fulltext_results)} fulltext → {len(sorted_results)} combined"
        )
        
        return sorted_results
    
    async def _hybrid_search_weighted(
        self,
        store: MultiTenantNeo4jStore,
        query: str,
        query_embedding: List[float],
        group_id: str,
        top_k: int,
        vector_weight: float,
        fulltext_weight: float,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search using weighted score combination.
        
        combined_score = vector_weight * vector_score + fulltext_weight * fulltext_score
        """
        # Run both searches in parallel
        vector_results, fulltext_results = await asyncio.gather(
            self._vector_search(store, query_embedding, group_id, top_k * 2),
            self._fulltext_search(store, query, group_id, top_k * 2),
        )
        
        # Normalize scores to [0, 1] range
        def normalize_scores(results: List[Dict], score_key: str = "score"):
            if not results:
                return results
            max_score = max(r.get(score_key, 0) for r in results) or 1.0
            min_score = min(r.get(score_key, 0) for r in results)
            score_range = max_score - min_score or 1.0
            for r in results:
                r["normalized_score"] = (r.get(score_key, 0) - min_score) / score_range
            return results
        
        vector_results = normalize_scores(vector_results)
        fulltext_results = normalize_scores(fulltext_results)
        
        # Combine scores
        entity_data: Dict[str, Dict[str, Any]] = {}
        
        for result in vector_results:
            entity_id = result["entity_id"]
            if entity_id not in entity_data:
                entity_data[entity_id] = {
                    "entity_id": entity_id,
                    "name": result.get("name", ""),
                    "vector_score": 0.0,
                    "fulltext_score": 0.0,
                }
            entity_data[entity_id]["vector_score"] = result.get("normalized_score", 0.0)
        
        for result in fulltext_results:
            entity_id = result["entity_id"]
            if entity_id not in entity_data:
                entity_data[entity_id] = {
                    "entity_id": entity_id,
                    "name": result.get("name", ""),
                    "vector_score": 0.0,
                    "fulltext_score": 0.0,
                }
            entity_data[entity_id]["fulltext_score"] = result.get("normalized_score", 0.0)
        
        # Calculate weighted scores
        for entity_id, data in entity_data.items():
            data["combined_score"] = (
                vector_weight * data["vector_score"] +
                fulltext_weight * data["fulltext_score"]
            )
        
        # Sort and return top_k
        sorted_results = sorted(
            entity_data.values(),
            key=lambda x: x["combined_score"],
            reverse=True
        )[:top_k]
        
        logger.info(
            f"Weighted hybrid search: {len(vector_results)} vector + "
            f"{len(fulltext_results)} fulltext → {len(sorted_results)} combined"
        )
        
        return sorted_results
    
    async def _vector_search(
        self,
        store: MultiTenantNeo4jStore,
        query_embedding: List[float],
        group_id: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """
        Execute vector similarity search on Neo4j.
        
        Searches BOTH entity_vector and chunk_vector indexes:
        - entity_vector: Entity nodes (semantic concepts)
        - chunk_vector: Chunk nodes (raw text with context)
        
        Results are merged and deduplicated by entity_id.
        """
        results = []
        
        # Search entity vector index
        try:
            entity_cypher = """
            CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
            YIELD node, score
            WHERE node.group_id = $group_id
            RETURN node.id AS entity_id, node.name AS name, node.text AS text, score, 'entity' AS source_type
            ORDER BY score DESC
            LIMIT $top_k
            """
            
            entity_result = store.structured_query(
                entity_cypher,
                param_map={
                    "index_name": self.vector_index_name,
                    "embedding": query_embedding,
                    "group_id": group_id,
                    "top_k": top_k,
                }
            )
            
            for row in (entity_result or []):
                results.append({
                    "entity_id": row["entity_id"],
                    "name": row["name"] or row["entity_id"],
                    "text": row.get("text", ""),
                    "score": row["score"],
                    "source_type": "entity",
                })
                
        except Exception as e:
            logger.warning(f"Entity vector search failed: {e}")
        
        # Search chunk vector index
        try:
            chunk_cypher = """
            CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
            YIELD node, score
            WHERE node.group_id = $group_id
            RETURN node.id AS entity_id, node.text AS text, score, 'chunk' AS source_type
            ORDER BY score DESC
            LIMIT $top_k
            """
            
            chunk_result = store.structured_query(
                chunk_cypher,
                param_map={
                    "index_name": self.chunk_vector_index_name,
                    "embedding": query_embedding,
                    "group_id": group_id,
                    "top_k": top_k,
                }
            )
            
            for row in (chunk_result or []):
                results.append({
                    "entity_id": row["entity_id"],
                    "name": f"Chunk: {row['entity_id'][:8]}...",
                    "text": row.get("text", ""),
                    "score": row["score"],
                    "source_type": "chunk",
                })
                
        except Exception as e:
            logger.warning(f"Chunk vector search failed: {e}")
        
        # Sort combined results by score and return top_k
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    async def _fulltext_search(
        self,
        store: MultiTenantNeo4jStore,
        query: str,
        group_id: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """
        Execute full-text search on Neo4j.
        """
        try:
            # Escape special Lucene characters in query
            escaped_query = self._escape_lucene_query(query)
            
            cypher = """
            CALL db.index.fulltext.queryNodes($index_name, $query_text)
            YIELD node, score
            WHERE node.group_id = $group_id
            RETURN node.id AS entity_id, node.name AS name, score
            ORDER BY score DESC
            LIMIT $top_k
            """
            
            result = store.structured_query(
                cypher,
                param_map={
                    "index_name": self.fulltext_index_name,
                    "query_text": escaped_query,
                    "group_id": group_id,
                    "top_k": top_k,
                }
            )
            
            return [
                {
                    "entity_id": row["entity_id"],
                    "name": row["name"],
                    "score": row["score"],
                }
                for row in (result or [])
            ]
            
        except Exception as e:
            logger.warning(f"Full-text search failed: {e}")
            return []
    
    def _escape_lucene_query(self, query: str) -> str:
        """
        Escape special characters for Lucene full-text search.
        
        Special characters: + - && || ! ( ) { } [ ] ^ " ~ * ? : \\ /
        """
        special_chars = [
            '\\', '+', '-', '&&', '||', '!', '(', ')', '{', '}',
            '[', ']', '^', '"', '~', '*', '?', ':', '/'
        ]
        escaped = query
        for char in special_chars:
            escaped = escaped.replace(char, f'\\{char}')
        return escaped
    
    async def get_seed_node_context(
        self,
        seed_nodes: List[Dict[str, Any]],
        group_id: str,
        depth: int = 2,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Expand seed nodes via graph traversal (Step 8).
        
        This performs the multi-hop Cypher traversal from the seed nodes
        to gather connected context.
        
        Args:
            seed_nodes: List of seed node dicts from find_seed_nodes()
            group_id: Tenant identifier
            depth: Number of hops to traverse
            limit: Maximum relationships to return
        
        Returns:
            List of triplets (source, relation, target)
        """
        if not seed_nodes:
            return []
        
        store = self.graph_service.get_store(group_id)
        
        # Get entity IDs from seed nodes
        entity_ids = [node["entity_id"] for node in seed_nodes]
        
        # Multi-hop traversal query
        cypher = """
        UNWIND $entity_ids AS start_id
        MATCH (start:`__Entity__` {id: start_id, group_id: $group_id})
        CALL (start, group_id, depth) {
            MATCH path = (start)-[r*1..depth]-(end:`__Entity__`)
            WHERE end.group_id = group_id
            UNWIND relationships(path) AS rel
            WITH startNode(rel) AS source, rel, endNode(rel) AS target
            RETURN source.name AS source_name, 
                   source.id AS source_id,
                   type(rel) AS relation_type,
                   target.name AS target_name,
                   target.id AS target_id
        }
        RETURN DISTINCT source_name, source_id, relation_type, target_name, target_id
        LIMIT $limit
        """
        
        try:
            result = store.structured_query(
                cypher,
                param_map={
                    "entity_ids": entity_ids,
                    "group_id": group_id,
                    "depth": depth,
                    "limit": limit,
                }
            )
            
            triplets = [
                {
                    "source": row["source_name"],
                    "source_id": row["source_id"],
                    "relation": row["relation_type"],
                    "target": row["target_name"],
                    "target_id": row["target_id"],
                }
                for row in (result or [])
            ]
            
            logger.info(
                f"Graph traversal from {len(entity_ids)} seed nodes: "
                f"{len(triplets)} triplets (depth={depth})"
            )
            
            return triplets
            
        except Exception as e:
            logger.error(f"Graph traversal failed: {e}")
            return []


# Singleton instance
_hybrid_search_service: Optional[Neo4jHybridSearchService] = None


def get_hybrid_search_service() -> Neo4jHybridSearchService:
    """Get singleton instance of Neo4jHybridSearchService."""
    global _hybrid_search_service
    if _hybrid_search_service is None:
        _hybrid_search_service = Neo4jHybridSearchService()
    return _hybrid_search_service
