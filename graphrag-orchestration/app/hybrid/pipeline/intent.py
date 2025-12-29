"""
Stage 1: Intent Disambiguation (The "Interpreter")

Uses LazyGraphRAG's query refinement to decompose ambiguous user queries
into specific, graph-grounded entities (Seed Entities).

Model Selection:
- Entity Extraction (NER): HYBRID_NER_MODEL (gpt-4o) - High precision required
- Query Decomposition (Route 3): HYBRID_DECOMPOSITION_MODEL (gpt-4.1) - Strong reasoning
"""

from typing import List, Optional, Any
import structlog

logger = structlog.get_logger(__name__)


class IntentDisambiguator:
    """
    Decomposes ambiguous queries into specific entity seeds.
    
    Model: Uses HYBRID_NER_MODEL (gpt-4o) for entity extraction.
    High precision is critical - incorrect seeds cascade to wrong evidence paths.
    
    Example:
        Query: "What is our exposure to the main tech partner?"
        Output: ["Entity: Microsoft", "Entity: Azure_Contract_2024"]
    """
    
    def __init__(self, llm_client: Optional[Any], graph_communities: Optional[List[dict]] = None):
        """
        Args:
            llm_client: The LLM client (Azure OpenAI or OpenAI).
            graph_communities: Optional list of community summaries for context.
        """
        self.llm = llm_client
        self.communities = graph_communities or []
    
    async def disambiguate(self, query: str, top_k: int = 5) -> List[str]:
        """
        Given an ambiguous query, identify the top-k specific entities.
        
        Args:
            query: The user's natural language query.
            top_k: Number of seed entities to return.
            
        Returns:
            List of entity names/IDs to use as seeds for HippoRAG.
        """
        if self.llm is None:
            logger.warning("llm_not_configured_cannot_disambiguate")
            return []
        
        # Build context from community summaries
        community_context = self._build_community_context()
        
        prompt = f"""You are an expert at identifying specific entities in a knowledge graph.

Given the following user query and the available entity communities in our graph,
identify the top {top_k} specific entity names that this query is referring to.

User Query: "{query}"

Available Communities/Entities:
{community_context}

Return ONLY a JSON array of entity names. Example: ["Entity_A", "Entity_B", "Entity_C"]
Do not include any explanation, just the JSON array.
"""
        
        try:
            response = await self.llm.acomplete(prompt)
            # Parse the JSON response
            import json
            entities = json.loads(response.text.strip())
            
            if isinstance(entities, list):
                logger.info("intent_disambiguation_success", 
                           query=query, 
                           seed_entities=entities[:top_k])
                return entities[:top_k]
            else:
                logger.warning("intent_disambiguation_invalid_format", 
                              response=response.text)
                return []
                
        except Exception as e:
            logger.error("intent_disambiguation_failed", error=str(e))
            return []
    
    def _build_community_context(self) -> str:
        """Build a context string from community summaries."""
        if not self.communities:
            return "No community information available. Extract entities directly from the query."
        
        context_parts = []
        for i, community in enumerate(self.communities[:10]):  # Limit to top 10
            title = community.get("title", f"Community {i}")
            summary = community.get("summary", "No summary available")
            context_parts.append(f"- {title}: {summary[:200]}...")
        
        return "\n".join(context_parts)
