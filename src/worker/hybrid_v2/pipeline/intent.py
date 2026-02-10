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

import re

logger = structlog.get_logger(__name__)


_GENERIC_SEED_PHRASES = {
    # Common finance/payment abbreviations that are rarely graph entities in this corpus.
    "ach",
    "wire",
    "wire transfer",
    "swift",
    "swift code",
    "swift codes",
    "iban",
    "bic",
    "vat",
    "tax id",
    "tax id number",
    "routing number",
    "routing numbers",
    "bank routing number",
    "bank routing numbers",
    "bank account number",
}


def _normalize_seed_phrase(s: str) -> str:
    s = (s or "").strip().casefold()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_generic_non_entity_seed(s: str) -> bool:
    ns = _normalize_seed_phrase(s)
    if not ns:
        return True
    if ns in _GENERIC_SEED_PHRASES:
        return True
    # Catch patterns like "SWIFT codes", "ACH payments", etc.
    if any(phrase in ns for phrase in ("swift", "iban", "bic", "ach")) and len(ns) <= 20:
        return True
    return False


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
    
    async def disambiguate(self, query: str, top_k: int = 3) -> List[str]:
        """
        Given an ambiguous query, identify the top-k specific entities.
        
        Args:
            query: The user's natural language query.
            top_k: Number of seed entities to return (default 3, reduced from 5
                   to prevent synonym flooding — most effective extractions use 2-3).
            
        Returns:
            List of entity names/IDs to use as seeds for HippoRAG.
        """
        if self.llm is None:
            logger.warning("llm_not_configured_cannot_disambiguate")
            return []
        
        # Build context from community summaries
        community_context = self._build_community_context()
        
        prompt = f"""You are an expert at identifying specific entities in a knowledge graph to answer user queries.

Step 1 — Understand the intent: What specific information is the user seeking?
Step 2 — Select entities: Pick the fewest entities needed to locate the answer in the graph.

User Query: "{query}"

Available Communities/Entities:
{community_context}

Rules:
- Return the MINIMUM number of entities needed (1-{top_k}). Fewer is better.
- Each entity must target a DIFFERENT concept. Do NOT include synonyms, paraphrases, or alternative phrasings of the same idea.
  BAD:  "Initial Term", "Term Start Date", "Commencement Date" (3 ways to say "start date")
  GOOD: "Initial Term" (one entity for that concept)
- Prefer entity names that appear in the community titles/summaries above.
- Include the document or agreement name ONLY if the query spans multiple documents and disambiguation is needed.
- Return specific entity-like strings (proper nouns, organizations, document titles, named clauses) likely to exist in the graph.
- Do NOT return generic keywords (e.g., "licensed", "state", "jurisdiction", "payment", "instructions").

Return ONLY a markdown list of entity names, one per line. Example:
- Agent fee
- Short-term rentals

Do not include any explanation, just the list.
"""

        try:
            response = await self.llm.acomplete(prompt)
            # Parse markdown list response
            raw_text = response.text.strip()
            entities = []
            for line in raw_text.split('\n'):
                line = line.strip()
                if line.startswith('- '):
                    entities.append(line[2:].strip())
                elif line.startswith('* '):
                    entities.append(line[2:].strip())

            if not entities:
                # Fallback: try JSON parsing for backward compatibility
                import json
                try:
                    parsed = json.loads(raw_text)
                    if isinstance(parsed, list):
                        entities = [str(x).strip() for x in parsed if isinstance(x, str)]
                except (json.JSONDecodeError, ValueError):
                    pass
            
            if isinstance(entities, list):
                def _clean(name: str) -> str:
                    cleaned = (name or "").strip()
                    while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'", "`"):
                        cleaned = cleaned[1:-1].strip()
                    return cleaned

                # Heuristic filter: keep entity-like strings (usually contain uppercase letters/digits)
                cleaned = [_clean(x) for x in entities if isinstance(x, str)]
                cleaned = [x for x in cleaned if x]

                filtered: List[str] = []
                for x in cleaned:
                    if _is_generic_non_entity_seed(x):
                        continue
                    has_upper = any(ch.isupper() for ch in x)
                    has_digit = any(ch.isdigit() for ch in x)
                    # Keep if it looks like a proper noun/document title.
                    if has_upper or has_digit:
                        filtered.append(x)
                
                selected = (filtered or [])[:top_k]
                logger.info(
                    "intent_disambiguation_success",
                    query=query,
                    seed_entities=selected,
                    dropped_count=max(0, len(cleaned) - len(filtered)),
                )
                return selected
            else:
                logger.warning("intent_disambiguation_invalid_format", 
                              response=response.text)
                return []
                
        except Exception as e:
            logger.error("intent_disambiguation_failed", error_msg=str(e))
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
