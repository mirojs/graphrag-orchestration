"""
Triple-Engine Retriever for Neo4j-Centric GraphRAG

Implements the "Lean Engine" architecture with intelligent query routing:
- Vector Route: Specific facts (dates, amounts, clause references)
- Graph Route: Relational reasoning (dependencies, connections)
- RAPTOR Route: Thematic summaries (portfolio risk, trends)

Model Selection:
- Current: Uses GPT-5.2 for both routing and synthesis (deployed)
- Planned: Use GPT-4.1 for indexing when available (1M context window)
"""

import logging
from typing import Dict, Any, List, Tuple, Literal, Optional
from dataclasses import dataclass

from llama_index.core.llms import ChatMessage, MessageRole
from app.v3.services.neo4j_store import Neo4jStoreV3, Entity, RaptorNode
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


QueryRoute = Literal["vector", "graph", "raptor", "drift"]


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
    1. Router (GPT-5.2): Classifies query intent with advanced reasoning
    2. Retrieval (Neo4j): Single-trip Hybrid+Boost query
    3. Synthesizer (GPT-5.2): Contradiction resolution and answer generation with agentic verification
    
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
        routing_prompt = f"""You are a query router for a knowledge graph system. Classify the query into one of four routes:

1. **vector**: For specific fact lookups
   - Examples: "What is the contract amount?", "When is the deadline?", "Who is the vendor?"
   - Characteristics: Looking for specific values, dates, names, or amounts

2. **graph**: For relational reasoning
   - Examples: "Who is connected to Company X?", "What are the dependencies?", "Show related entities"
   - Characteristics: Exploring connections, relationships, or networks

3. **raptor**: For thematic summaries
   - Examples: "What are the main themes?", "Summarize all documents", "What are the risk factors?"
   - Characteristics: High-level overview, cross-document themes, portfolio analysis

4. **drift**: For complex multi-hop reasoning
   - Examples: "How did the incident in Part A lead to the change in Part B?", "What is the relationship between the CEO's vision and the Q3 budget?"
   - Characteristics: Connecting distant concepts, "how" or "why" questions across topics

Query: {query}

Respond with ONLY the route name (vector, graph, raptor, or drift) on the first line, followed by a brief explanation."""

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="You are a precise query classifier."),
            ChatMessage(role=MessageRole.USER, content=routing_prompt),
        ]
        
        try:
            # Use specialized routing LLM if available (GPT-5.2 for advanced reasoning)
            routing_llm = self.llm_service.get_routing_llm()
            response = routing_llm.chat(messages)
            response_text = response.message.content.strip()
            
            # Parse response: first line is route, rest is reasoning
            lines = response_text.split('\n', 1)
            route_str = lines[0].strip().lower()
            reasoning = lines[1].strip() if len(lines) > 1 else "No reasoning provided"
            
            # Validate route
            if route_str in ["vector", "graph", "raptor", "drift"]:
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
        elif route == "drift":
            return await self._retrieve_drift(query, group_id, top_k, reasoning)
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
        if self.llm_service.embed_model is None:
            raise RuntimeError("Embedding model not initialized")
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
        
        # RAPTOR Context (Elevator Strategy: Local + RAPTOR)
        # Fetch parent RAPTOR node for the top entity to provide thematic context
        if results:
            top_entity = results[0][0]
            raptor_context = self.store.get_entity_raptor_context(group_id, top_entity.id)
            if raptor_context:
                context_parts.append(f"## Context (RAPTOR Summary):\n{raptor_context.text}\n")
                logger.info(f"Added RAPTOR context for entity {top_entity.name}")
        
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
        
        if self.llm_service.llm is None:
            raise RuntimeError("LLM not initialized")
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
        
        Uses RAPTOR to prune the graph (Elevator Strategy: Global + RAPTOR), 
        then retrieves relevant community summaries.
        """
        # Step 1: RAPTOR Pruning (Elevator Strategy)
        # Search RAPTOR nodes first to find relevant themes
        if self.llm_service.embed_model is None:
             raise RuntimeError("Embedding model not initialized")
        query_embedding = self.llm_service.embed_model.get_text_embedding(query)
        
        raptor_nodes = self.store.search_raptor_by_embedding(
            group_id=group_id,
            embedding=query_embedding,
            top_k=3, # Top 3 themes
        )
        
        communities = []
        if raptor_nodes:
            raptor_ids = [node.id for node, _ in raptor_nodes]
            communities = self.store.get_communities_by_raptor_context(group_id, raptor_ids)
            logger.info(f"RAPTOR Pruning: Found {len(communities)} communities via {len(raptor_nodes)} RAPTOR nodes")
            
        # Fallback if RAPTOR didn't find anything (or no RAPTOR index)
        if not communities:
            logger.info("RAPTOR Pruning: No results, falling back to full community scan")
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
        
        if self.llm_service.llm is None:
            raise RuntimeError("LLM not initialized")
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
        if self.llm_service.embed_model is None:
            raise RuntimeError("Embedding model not initialized")
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
        
        if self.llm_service.llm is None:
            raise RuntimeError("LLM not initialized")
        response = self.llm_service.llm.complete(prompt)
        
        return RetrievalResult(
            answer=response.text,
            confidence=results[0][1] if results else 0.0,
            route="raptor",
            sources=sources,
            reasoning=reasoning,
        )

    async def _retrieve_drift(
        self,
        query: str,
        group_id: str,
        top_k: int,
        reasoning: str,
    ) -> RetrievalResult:
        """
        DRIFT Route: Multi-hop traversal using RAPTOR nodes as 'teleporters'.
        
        Uses RAPTOR summaries to jump between disconnected parts of the graph
        when standard entity traversal fails or is too slow.
        """
        # Step 1: Start with high-level RAPTOR summaries (The "Highway")
        if self.llm_service.embed_model is None:
             raise RuntimeError("Embedding model not initialized")
        query_embedding = self.llm_service.embed_model.get_text_embedding(query)
        
        # Find entry points (RAPTOR nodes)
        raptor_nodes = self.store.search_raptor_by_embedding(
            group_id=group_id,
            embedding=query_embedding,
            top_k=3,
        )
        
        if not raptor_nodes:
             # Fallback to vector search if no RAPTOR nodes found
             return await self._retrieve_vector(query, group_id, top_k, reasoning)

        context_parts = []
        sources = []
        
        # Step 2: Drill down from RAPTOR to Entities (The "Off-Ramp")
        for node, score in raptor_nodes:
            context_parts.append(f"## Theme: {node.text[:200]}...")
            
            # Find entities mentioned in this RAPTOR cluster
            # This is the "DRIFT" part - moving from Summary -> Entity
            entities = self.store.get_entities_by_raptor_context(group_id, node.id, limit=5)
            
            for entity in entities:
                context_parts.append(f"- Related Fact: {entity.name} ({entity.type}): {entity.description}")
                sources.append({
                    "id": entity.id,
                    "name": entity.name,
                    "type": "drift_entity",
                    "via_raptor": node.id
                })
                
        context = "\n".join(context_parts)
        
        # Generate answer
        prompt = f"""Answer the following complex question by synthesizing high-level themes and specific facts.

Context:
{context}

Question: {query}

Explain the connections between the themes and the specific facts.

Answer:"""

        if self.llm_service.llm is None:
            raise RuntimeError("LLM not initialized")
        response = self.llm_service.llm.complete(prompt)
        
        return RetrievalResult(
            answer=response.text,
            confidence=raptor_nodes[0][1] if raptor_nodes else 0.0,
            route="drift", # Note: We need to add 'drift' to QueryRoute type definition
            sources=sources,
            reasoning=reasoning,
        )
