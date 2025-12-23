"""
Triple-Engine Retriever for Neo4j-Centric GraphRAG

Implements the "Lean Engine" architecture with intelligent query routing:
- Vector Route: Specific facts (dates, amounts, clause references)
- Graph Route: Relational reasoning (dependencies, connections)
- RAPTOR Route: Thematic summaries (portfolio risk, trends)

Model Selection:
- Current: Uses GPT-4o for both routing and synthesis (excellent reasoning, production-ready)
- Planned: Upgrade to GPT-5.2 Thinking (routing) and GPT-5.2 Pro (synthesis) when available
"""

import logging
from typing import Dict, Any, List, Tuple, Literal, Optional
from dataclasses import dataclass

from llama_index.core.llms import ChatMessage, MessageRole
from app.v3.services.neo4j_store import Neo4jStoreV3, Entity, RaptorNode
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


QueryRoute = Literal["vector", "graph", "raptor"]


@dataclass
class RetrievalResult:
    """Result from triple-engine retrieval."""
    answer: str
    confidence: float
    route: QueryRoute
    sources: List[Dict[str, Any]]
    reasoning: Optional[str] = None  # From routing decision


class TripleEngineRetriever:
    """
    Single-trip Neo4j retriever with intelligent query routing.
    
    Architecture:
    1. Router (GPT-4o): Classifies query intent [Upgrade to GPT-5.2 Thinking when available]
    2. Retrieval (Neo4j): Single-trip Hybrid+Boost query
    3. Synthesizer (GPT-4o): Contradiction resolution and answer generation [Upgrade to GPT-5.2 Pro when available]
    
    Routes:
    - Vector: "What is the contract value?" → Entity search (Hybrid+Boost)
    - Graph: "Who is connected to X?" → Community/relationship traversal
    - RAPTOR: "What are the main themes?" → Hierarchical summaries
    """
    
    def __init__(self, store: Neo4jStoreV3, llm_service: LLMService):
        """
        Initialize Triple-Engine Retriever.
        
        Args:
            store: Neo4j store for data access
            llm_service: LLM service for routing and synthesis
        """
        self.store = store
        self.llm_service = llm_service
        
    def route_query(self, query: str) -> Tuple[QueryRoute, str]:
        """
        Use LLM (currently GPT-4o) to classify query intent.
        
        Args:
            query: Natural language query
            
        Returns:
            Tuple of (route, reasoning)
        """
        routing_prompt = f"""You are a query router for a knowledge graph system. Classify the query into one of three routes:

1. **vector**: For specific fact lookups
   - Examples: "What is the contract amount?", "When is the deadline?", "Who is the vendor?"
   - Characteristics: Looking for specific values, dates, names, or amounts

2. **graph**: For relational reasoning
   - Examples: "Who is connected to Company X?", "What are the dependencies?", "Show related entities"
   - Characteristics: Exploring connections, relationships, or networks

3. **raptor**: For thematic summaries
   - Examples: "What are the main themes?", "Summarize all documents", "What are the risk factors?"
   - Characteristics: High-level overview, cross-document themes, portfolio analysis

Query: {query}

Respond with ONLY the route name (vector, graph, or raptor) on the first line, followed by a brief explanation."""

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="You are a precise query classifier."),
            ChatMessage(role=MessageRole.USER, content=routing_prompt),
        ]
        
        try:
            response = self.llm_service.llm.chat(messages)
            response_text = response.message.content.strip()
            
            # Parse response: first line is route, rest is reasoning
            lines = response_text.split('\n', 1)
            route_str = lines[0].strip().lower()
            reasoning = lines[1].strip() if len(lines) > 1 else "No reasoning provided"
            
            # Validate route
            if route_str in ["vector", "graph", "raptor"]:
                route = route_str  # type: ignore
                logger.info(f"Query routed to: {route} | Reasoning: {reasoning[:100]}")
                return route, reasoning
            else:
                # Default fallback
                logger.warning(f"Invalid route '{route_str}', defaulting to vector")
                return "vector", f"Invalid route, defaulted to vector. Original: {response_text}"
                
        except Exception as e:
            logger.error(f"Routing failed: {e}, defaulting to vector")
            return "vector", f"Routing error: {str(e)}"
    
    async def retrieve(
        self,
        query: str,
        group_id: str,
        top_k: int = 10,
        force_route: Optional[QueryRoute] = None,
    ) -> RetrievalResult:
        """
        Execute triple-engine retrieval with automatic routing.
        
        Args:
            query: Natural language query
            group_id: Tenant identifier
            top_k: Number of results to retrieve
            force_route: Optional route override (for testing/debugging)
            
        Returns:
            RetrievalResult with answer, sources, and metadata
        """
        # Step 1: Route query (or use forced route)
        if force_route:
            route = force_route
            reasoning = f"Forced route: {force_route}"
        else:
            route, reasoning = self.route_query(query)
        
        logger.info(f"[TripleEngine] Query: '{query[:60]}...' → Route: {route}")
        
        # Step 2: Execute retrieval based on route
        if route == "vector":
            return await self._retrieve_vector(query, group_id, top_k, reasoning)
        elif route == "graph":
            return await self._retrieve_graph(query, group_id, top_k, reasoning)
        elif route == "raptor":
            return await self._retrieve_raptor(query, group_id, top_k, reasoning)
        else:
            # Should never happen due to validation, but satisfy type checker
            logger.error(f"Unknown route: {route}")
            return RetrievalResult(
                answer="Error: Invalid route",
                confidence=0.0,
                route="vector",
                sources=[],
                reasoning=f"Unknown route: {route}",
            )
    
    async def _retrieve_vector(
        self,
        query: str,
        group_id: str,
        top_k: int,
        reasoning: str,
    ) -> RetrievalResult:
        """
        Vector Route: Specific fact lookups using Hybrid+Boost search.
        
        Uses Neo4j's native vector search with:
        - Vector similarity (gds.similarity.cosine)
        - Full-text search (lexical matching)
        - RRF fusion
        - Community rank boost
        """
        # Get query embedding
        query_embedding = self.llm_service.embed_model.get_text_embedding(query)
        
        # Execute Hybrid+Boost search
        results = self.store.search_entities_hybrid(
            group_id=group_id,
            query_text=query,
            embedding=query_embedding,
            top_k=top_k,
        )
        
        if not results:
            return RetrievalResult(
                answer="No relevant information found for this query.",
                confidence=0.0,
                route="vector",
                sources=[],
                reasoning=reasoning,
            )
        
        # Build context from entities
        context_parts = []
        sources = []
        
        for entity, score in results:
            context_parts.append(f"- {entity.name} ({entity.type}): {entity.description}")
            sources.append({
                "id": entity.id,
                "name": entity.name,
                "type": entity.type,
                "score": float(score),
            })
        
        context = "\n".join(context_parts)
        
        # Generate answer using LLM (currently GPT-4o)
        prompt = f"""Based on the following information, answer the question with specific details.

Information:
{context}

Question: {query}

Provide a precise answer with specific values, amounts, or dates if available.

Answer:"""
        
        response = self.llm_service.llm.complete(prompt)
        
        return RetrievalResult(
            answer=response.text,
            confidence=results[0][1] if results else 0.0,
            route="vector",
            sources=sources,
            reasoning=reasoning,
        )
    
    async def _retrieve_graph(
        self,
        query: str,
        group_id: str,
        top_k: int,
        reasoning: str,
    ) -> RetrievalResult:
        """
        Graph Route: Relational reasoning using community summaries.
        
        Uses Neo4j's community detection (Leiden algorithm) to find
        thematically related entities and their connections.
        """
        # Get top-level community summaries (level 0 = broadest)
        communities = self.store.get_communities_by_level(group_id=group_id, level=0)
        
        if not communities:
            return RetrievalResult(
                answer="No community summaries available. Please ensure documents were indexed with community detection enabled.",
                confidence=0.0,
                route="graph",
                sources=[],
                reasoning=reasoning,
            )
        
        # Build context from community summaries
        context_parts = []
        sources = []
        
        for community in communities[:top_k]:
            context_parts.append(f"## {community.title}\n{community.summary}")
            sources.append({
                "id": community.id,
                "title": community.title,
                "level": community.level,
                "rank": community.rank,
                "entity_count": len(community.entity_ids),
            })
        
        context = "\n\n".join(context_parts)
        
        # Generate answer focusing on relationships
        prompt = f"""Based on the following community summaries, answer the question about relationships and connections.

Community Summaries:
{context}

Question: {query}

Focus on explaining connections, dependencies, and how different entities relate to each other.

Answer:"""
        
        response = self.llm_service.llm.complete(prompt)
        
        return RetrievalResult(
            answer=response.text,
            confidence=communities[0].rank if communities else 0.0,
            route="graph",
            sources=sources,
            reasoning=reasoning,
        )
    
    async def _retrieve_raptor(
        self,
        query: str,
        group_id: str,
        top_k: int,
        reasoning: str,
    ) -> RetrievalResult:
        """
        RAPTOR Route: Thematic summaries using hierarchical clustering.
        
        Uses RAPTOR's hierarchical summarization to provide high-level
        themes and cross-document insights.
        """
        # Get query embedding
        query_embedding = self.llm_service.embed_model.get_text_embedding(query)
        
        # Search RAPTOR nodes by vector similarity
        results = self.store.search_raptor_by_embedding(
            group_id=group_id,
            embedding=query_embedding,
            top_k=top_k,
        )
        
        if not results:
            return RetrievalResult(
                answer="No RAPTOR nodes found. Ensure documents were indexed with run_raptor=true.",
                confidence=0.0,
                route="raptor",
                sources=[],
                reasoning=reasoning,
            )
        
        # Build context from RAPTOR node texts
        context_parts = []
        sources = []
        
        for node, score in results:
            context_parts.append(f"## Content (Level {node.level}):\n{node.text}\n")
            sources.append({
                "id": node.id,
                "level": node.level,
                "score": float(score),
                "text_preview": node.text[:200] + "..." if len(node.text) > 200 else node.text,
            })
        
        context = "\n\n".join(context_parts)
        
        # Generate answer focusing on themes
        prompt = f"""Based on the following hierarchical summaries, answer the question about themes and patterns.

Document Content:
{context}

Question: {query}

Provide a comprehensive answer highlighting main themes, patterns, and cross-document insights.

Answer:"""
        
        response = self.llm_service.llm.complete(prompt)
        
        return RetrievalResult(
            answer=response.text,
            confidence=results[0][1] if results else 0.0,
            route="raptor",
            sources=sources,
            reasoning=reasoning,
        )
