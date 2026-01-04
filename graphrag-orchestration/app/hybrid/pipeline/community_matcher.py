"""
Stage 3.1: Community Matching for Global Search

Matches thematic queries to relevant graph communities using embedding similarity.
This is the LazyGraphRAG component that identifies "which shelf to look at"
before HippoRAG PPR finds "every relevant page on that shelf."

Used in: Route 3 (Global Search Equivalent)
"""

from typing import List, Dict, Any, Optional, Tuple
import structlog
import json
from pathlib import Path

logger = structlog.get_logger(__name__)


class CommunityMatcher:
    """
    Matches queries to graph communities using embedding similarity.
    
    Communities are pre-computed clusters of related entities with summaries.
    This module finds which communities are most relevant to a thematic query.
    
    Example:
        Query: "What are the main compliance risks?"
        Output: [("Compliance", 0.92), ("Risk Management", 0.87)]
    """
    
    def __init__(
        self,
        embedding_client: Optional[Any] = None,
        communities_path: Optional[str] = None,
        group_id: str = "default"
    ):
        """
        Args:
            embedding_client: LlamaIndex or OpenAI embedding client.
            communities_path: Path to pre-computed community data.
            group_id: Tenant identifier.
        """
        self.embedding_client = embedding_client
        self.group_id = group_id
        self.communities_path = Path(communities_path) if communities_path else None
        
        self._communities: List[Dict[str, Any]] = []
        self._community_embeddings: Dict[str, List[float]] = {}
        self._loaded = False
        
        logger.info("community_matcher_created",
                   group_id=group_id,
                   has_embedding_client=embedding_client is not None)
    
    async def load_communities(self) -> bool:
        """Load community data and embeddings."""
        if self._loaded:
            return True
        
        if self.communities_path and self.communities_path.exists():
            try:
                with open(self.communities_path) as f:
                    data = json.load(f)
                
                self._communities = data.get("communities", [])
                self._community_embeddings = data.get("embeddings", {})
                self._loaded = True
                
                logger.info("communities_loaded",
                           num_communities=len(self._communities))
                return True
                
            except Exception as e:
                logger.error("community_load_failed", error=str(e))
                return False
        
        logger.warning("no_community_data_found",
                      path=str(self.communities_path))
        return False
    
    async def match_communities(
        self,
        query: str,
        top_k: int = 3
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Find communities most relevant to the query.
        
        LazyGraphRAG approach: Generate communities on-the-fly from Neo4j graph.
        If pre-computed communities exist, use them. Otherwise, dynamically cluster entities.
        
        Args:
            query: The user's thematic query.
            top_k: Number of communities to return.
            
        Returns:
            List of (community_data, similarity_score) tuples.
        """
        # Try to load pre-computed communities first (for compatibility)
        if not self._loaded:
            await self.load_communities()
        
        # If we have pre-computed communities, use traditional matching
        if self._communities:
            if self.embedding_client and self._community_embeddings:
                return await self._semantic_match(query, top_k)
            return self._keyword_match(query, top_k)
        
        # LazyGraphRAG: Generate communities on-the-fly from Neo4j
        logger.info("lazygraphrag_on_the_fly_community_generation", query=query[:50])
        return await self._generate_communities_from_query(query, top_k)
    
    async def _semantic_match(
        self,
        query: str,
        top_k: int
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Match using embedding similarity."""
        try:
            # Embed the query
            query_embedding = await self._get_embedding(query)
            if not query_embedding:
                return self._keyword_match(query, top_k)
            
            # Calculate similarities
            scored: List[Tuple[Dict[str, Any], float]] = []
            for community in self._communities:
                community_id = community.get("id", community.get("title", ""))
                community_emb = self._community_embeddings.get(community_id)
                
                if community_emb:
                    similarity = self._cosine_similarity(query_embedding, community_emb)
                    scored.append((community, similarity))
            
            # Sort by similarity
            scored.sort(key=lambda x: x[1], reverse=True)
            
            logger.info("semantic_community_match",
                       query=query[:50],
                       top_matches=[c.get("title", c.get("id", "?"))[:30] for c, _ in scored[:top_k]])
            
            return scored[:top_k]
            
        except Exception as e:
            logger.error("semantic_match_failed", error=str(e))
            return self._keyword_match(query, top_k)
    
    def _keyword_match(
        self,
        query: str,
        top_k: int
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Fallback keyword-based matching."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored: List[Tuple[Dict[str, Any], float]] = []
        
        for community in self._communities:
            title = community.get("title", "").lower()
            summary = community.get("summary", "").lower()
            
            # Calculate word overlap
            community_words = set(title.split()) | set(summary.split())
            overlap = len(query_words & community_words)
            
            if overlap > 0:
                score = overlap / max(len(query_words), 1)
                scored.append((community, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        
        logger.info("keyword_community_match",
                   query=query[:50],
                   num_matches=len(scored))
        
        return scored[:top_k]
    
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding for text."""
        if not self.embedding_client:
            return None
        
        try:
            # Handle different embedding client interfaces
            if hasattr(self.embedding_client, 'aget_text_embedding'):
                # LlamaIndex style
                return await self.embedding_client.aget_text_embedding(text)
            elif hasattr(self.embedding_client, 'embed_query'):
                # LangChain style
                return self.embedding_client.embed_query(text)
            elif hasattr(self.embedding_client, 'create'):
                # OpenAI style
                response = await self.embedding_client.create(input=text)
                return response.data[0].embedding
            else:
                logger.warning("unknown_embedding_client_interface")
                return None
        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            return None
    
    async def _generate_communities_from_query(
        self,
        query: str,
        top_k: int
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        LazyGraphRAG: Generate communities on-the-fly from Neo4j graph.
        
        Strategy:
        1. Extract query keywords
        2. Find entities matching keywords in Neo4j
        3. Group entities by their connected components (1-hop neighborhood)
        4. Return top-k clusters as "communities"
        """
        import re
        
        # Extract keywords from query
        stopwords = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "should", "could", "may", "might", "must", "can", "what", "which", "who", "when", "where", "why", "how", "this", "that", "these", "those", "all", "any"}
        
        query_keywords = [
            token.lower() for token in re.findall(r"[A-Za-z0-9]+", query.lower())
            if len(token) >= 3 and token.lower() not in stopwords
        ]
        
        if not query_keywords:
            logger.warning("no_keywords_extracted_from_query", query=query[:50])
            return []
        
        logger.info("extracted_query_keywords", keywords=query_keywords[:5])
        
        # For now, create a single synthetic community containing all relevant entities
        # This is a simplified LazyGraphRAG - in production, you'd do proper clustering
        community = {
            "id": f"dynamic_community_{self.group_id}",
            "title": f"Query-relevant entities: {' '.join(query_keywords[:3])}",
            "summary": f"Dynamically generated community for query: {query[:100]}",
            "keywords": query_keywords,
            "entities": []  # Will be populated by hub_extractor from Neo4j
        }
        
        # Score is 1.0 since this is dynamically generated for this specific query
        return [(community, 1.0)]
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_community_summaries(self) -> List[Dict[str, str]]:
        """Get summaries of all communities for context."""
        return [
            {
                "title": c.get("title", f"Community {i}"),
                "summary": c.get("summary", "No summary available")[:500]
            }
            for i, c in enumerate(self._communities)
        ]
