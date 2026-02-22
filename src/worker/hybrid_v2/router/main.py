"""
Hybrid Pipeline Router

Routes queries between 3 distinct routes:
1. Local Search - Factual lookups and entity-focused queries (LazyGraphRAG)
2. Global Search - Cross-document thematic analysis (LazyGraphRAG + HippoRAG 2 PPR)
3. DRIFT - Multi-hop iterative reasoning for complex queries

Note: Vector RAG (formerly Route 1) was removed after comprehensive testing showed:
- Route 2 (Local Search) answers 100% of Vector RAG questions correctly
- Only 14% latency difference (not meaningful)
- Local Search provides superior answer quality with entity connections
- Simplifies routing logic and improves router accuracy
"""

from enum import Enum
from typing import Optional, Any, Dict, List, Literal, Tuple
import structlog
import json

logger = structlog.get_logger(__name__)


# =========================================================================
# Route → Weight Profile mapping for Route 5 seed weighting
# =========================================================================

# Default mapping from router classification → weight profile name.
# Profiles are defined in seed_resolver.py (WEIGHT_PROFILES dict).
_ROUTE_TO_WEIGHT_PROFILE: Dict[str, str] = {
    "local_search": "fact_extraction",        # Entity-heavy, precise lookup
    "global_search": "thematic_survey",       # Community-heavy, broad coverage
    "drift_multi_hop": "multi_hop",           # Entity-heavy, graph traversal
    "unified_search": "balanced",             # Explicit Route 5 → balanced default
    "concept_search": "thematic_survey",      # Route 6: community-driven concept search
    "hipporag2_search": "fact_extraction",    # Route 7: entity-graph PPR (entity-heavy)
}


# Route classification prompt — 3-way routing based on retrieval architecture.
#
# Core axis: ENTITY-ANCHORED vs CONCEPT-ANCHORED
#   Entity-anchored: query names specific entities. Retrieval anchors on those
#                    names and traverses the knowledge graph.
#   Concept-anchored: query asks about abstract themes/roles/clauses with no entity
#                     anchor. Community summaries (LazyGraphRAG) are the right tool.
#
# Within entity-anchored: SHALLOW (R2) vs DEEP (R7)
#   local_search (R2):      answer in one section — fast vector lookup, no graph walk
#   hipporag2_search (R7):  answer requires entity-graph traversal across chunks
#
# Route 4 (drift_multi_hop) is retired from auto-routing: benchmark shows
# Route 7 achieves 57/57 on all DRIFT-style questions via graph traversal,
# making iterative LLM decomposition redundant. Use force_route if needed.
#
# Validated by benchmark (2026-02):
#   Route 7 Q-L 57/57, Q-D 57/57 — subsumes Route 2 AND Route 4
#   Route 6 Q-G 53/57             — best on concept/theme queries
ROUTE_CLASSIFICATION_PROMPT = """You are a query router for a document retrieval system. Classify the user's query into ONE of three search strategies.

## Routes

**local_search** — Simple entity lookup (DEFAULT)
- Answer lives in one or a few document sections; vector search is sufficient
- Named entity + simple attribute: name, date, amount, party, jurisdiction, list of items
- Examples: "What is the total amount in Contract X?", "List the 3 installment dates", "Who are the parties to the NDA?", "Which contracts are governed by California law?"

**hipporag2_search** — Entity graph traversal
- Named entities present, but the answer requires tracing relationships ACROSS chunks or documents
- Multi-hop: entity A → relationship → entity B → fact
- Questions about obligations, roles, or relationships linking multiple named entities
- Examples: "What are all obligations of Company Y across documents?", "Which subsidiary handles indemnification under the master agreement?", "Find documents where Counterparty X appears alongside obligation Z"

**concept_search** — Abstract concept / theme retrieval
- NO specific named entity anchor — query is about a ROLE, CLAUSE TYPE, OBLIGATION, or THEME
- The answer could come from any document mentioning the concept
- Test: if you replaced all party names with "Party A/B", the question still makes sense
- Examples: "What are the reporting obligations?", "Summarise all termination clauses", "What compliance risks exist?", "What are the main payment obligations?", "List all insurance requirements"

## Decision (apply in order)
1. Is the query about an abstract concept/theme with no named entity anchor? → **concept_search**
2. Does the answer require connecting entities across multiple chunks/documents? → **hipporag2_search**
3. Everything else (direct lookup with a named entity) → **local_search**

Query: {query}

Respond with JSON: {{"route": "<route_name>", "reasoning": "<one sentence>"}}"""


class QueryRoute(Enum):
    """Available routing destinations (5 routes)."""
    LOCAL_SEARCH = "local_search"           # Route 2: Factual lookup & entity-focused (LazyGraphRAG)
    GLOBAL_SEARCH = "global_search"         # Route 3: Thematic (LazyGraphRAG + HippoRAG)
    DRIFT_MULTI_HOP = "drift_multi_hop"     # Route 4: Iterative multi-hop reasoning
    UNIFIED_SEARCH = "unified_search"       # Route 5: Unified hierarchical seed PPR
    CONCEPT_SEARCH = "concept_search"       # Route 6: Concept search (direct community synthesis)
    HIPPORAG2_SEARCH = "hipporag2_search"  # Route 7: True HippoRAG 2 architecture
    # Legacy alias for backward compatibility
    VECTOR_RAG = "local_search"             # Deprecated: maps to LOCAL_SEARCH


class DeploymentProfile(Enum):
    """Deployment configuration profiles."""
    GENERAL_ENTERPRISE = "general_enterprise"  # All 3 routes enabled
    HIGH_ASSURANCE = "high_assurance"          # Same as GENERAL_ENTERPRISE (no Vector RAG to exclude)


class HybridRouter:
    """
    Routes queries between 3 retrieval strategies based on the entity-vs-concept axis.

    Classification Logic:
    - No entity anchor / abstract theme/clause → concept_search  (Route 6, LazyGraphRAG communities)
    - Named entity + graph-traversal needed   → hipporag2_search (Route 7, PPR entity graph)
    - Named entity + direct section lookup    → local_search     (Route 2, fast vector)

    Routes 3 (global_search) and 4 (drift_multi_hop) are retired from auto-routing:
    - Route 7 achieves 57/57 on all DRIFT-style questions (makes Route 4 redundant).
    - Route 6 concept_search supersedes Route 3 global_search for concept queries.
    Both remain accessible via force_route for manual override.

    Model Selection:
        Uses HYBRID_ROUTER_MODEL (default: gpt-4o-mini) for classification.
    """
    
    def __init__(
        self,
        profile: DeploymentProfile = DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client: Optional[Any] = None,
        vector_threshold: float = 0.25,
        global_threshold: float = 0.5,
        drift_threshold: float = 0.75
    ):
        """
        Args:
            profile: Deployment profile (affects routing behavior).
            llm_client: Optional LLM for advanced classification.
            vector_threshold: Below this -> Route 1 (Vector RAG)
            global_threshold: Below this (but above vector) -> Route 2 (Local Search)
            drift_threshold: Above this -> Route 4 (DRIFT Multi-Hop)
            Between global and drift thresholds -> Route 3 (Global Search)
        """
        self.profile = profile
        self.llm = llm_client
        self.vector_threshold = vector_threshold
        self.global_threshold = global_threshold
        self.drift_threshold = drift_threshold
        
        logger.info("router_initialized", 
                   profile=profile.value,
                   vector_threshold=vector_threshold,
                   global_threshold=global_threshold,
                   drift_threshold=drift_threshold)
    
    async def route(self, query: str) -> QueryRoute:
        """
        Determine the appropriate route for a query.
        
        Uses LLM classification with structured output for reliable routing.
        Falls back to heuristics if LLM is unavailable.
        
        Returns:
            QueryRoute enum indicating where to send the query.
        """
        # Try LLM classification first (more accurate)
        if self.llm:
            base_route, reasoning = await self._llm_classify(query)
            logger.info("route_decision_llm",
                       query=query[:50],
                       route=base_route.value,
                       reasoning=reasoning,
                       profile=self.profile.value)
        else:
            # Fallback to heuristic-based routing
            base_route = self._heuristic_classify(query)
            logger.info("route_decision_heuristic",
                       query=query[:50],
                       route=base_route.value,
                       profile=self.profile.value)
        
        # Apply profile constraints
        final_route = self._apply_profile_constraints(base_route)
        
        if final_route != base_route:
            logger.info("route_constrained",
                       original=base_route.value,
                       final=final_route.value,
                       profile=self.profile.value)
        
        return final_route

    async def route_with_profile(self, query: str) -> Tuple[QueryRoute, str]:
        """Route a query and return the corresponding weight profile name.

        This is the primary entry point when Route 5 is active — the router
        classifies the query *and* selects the seed weight profile in one call.

        Returns:
            Tuple of (QueryRoute, weight_profile_name).
            The weight_profile_name maps to a key in
            ``seed_resolver.WEIGHT_PROFILES``.
        """
        route = await self.route(query)
        profile_name = self.get_weight_profile(route)
        logger.info(
            "route_with_profile",
            query=query[:50],
            route=route.value,
            weight_profile=profile_name,
        )
        return route, profile_name

    @staticmethod
    def get_weight_profile(route: QueryRoute) -> str:
        """Map a QueryRoute to a Route 5 weight profile name.

        Returns:
            Profile key for ``seed_resolver.WEIGHT_PROFILES``.
        """
        return _ROUTE_TO_WEIGHT_PROFILE.get(route.value, "balanced")
    
    async def _llm_classify(self, query: str) -> tuple[QueryRoute, str]:
        """
        Use LLM to classify query into appropriate route.
        
        Returns:
            Tuple of (QueryRoute, reasoning string)
        """
        prompt = ROUTE_CLASSIFICATION_PROMPT.format(query=query)
        
        try:
            # Call LLM for classification
            response = await self.llm.acomplete(prompt)
            response_text = str(response).strip()
            
            # Parse JSON response
            # Handle potential markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(response_text)
            route_str = result.get("route", "local_search")
            reasoning = result.get("reasoning", "")
            
            # Map string to enum — includes legacy aliases for backward compatibility
            route_map = {
                "local_search": QueryRoute.LOCAL_SEARCH,
                "hipporag2_search": QueryRoute.HIPPORAG2_SEARCH,
                "concept_search": QueryRoute.CONCEPT_SEARCH,
                # Legacy / force_route aliases kept for backward compatibility
                "global_search": QueryRoute.GLOBAL_SEARCH,
                "drift_multi_hop": QueryRoute.DRIFT_MULTI_HOP,
                "vector_rag": QueryRoute.LOCAL_SEARCH,
            }
            
            route = route_map.get(route_str, QueryRoute.LOCAL_SEARCH)
            return route, reasoning
            
        except Exception as e:
            logger.warning("llm_classify_failed", error=str(e), query=query[:50])
            # Fallback to heuristics
            return self._heuristic_classify(query), "LLM classification failed, using heuristics"
    
    def _heuristic_classify(self, query: str) -> QueryRoute:
        """
        Fast heuristic-based classification as fallback when LLM is unavailable.

        Mirrors the 3-way routing in ROUTE_CLASSIFICATION_PROMPT.
        Only catches high-confidence patterns to avoid false positives.
        """
        query_lower = query.lower()

        # Concept-anchored signals: abstract roles/obligations/themes with no entity anchor.
        # Checked first because these phrases override entity-lookup patterns.
        concept_keywords = [
            "reporting obligation", "compliance risk", "termination clause",
            "payment obligation", "insurance requirement", "indemnification provision",
            "what are the", "what obligations", "what requirements", "what provisions",
            "summarize all", "summarise all", "all clauses", "across all documents",
            "across documents", "main themes", "key themes",
        ]
        if any(kw in query_lower for kw in concept_keywords):
            return QueryRoute.CONCEPT_SEARCH

        # Default to Local Search — most queries are direct entity lookups.
        # LLM handles nuanced hipporag2_search vs local_search distinction.
        return QueryRoute.LOCAL_SEARCH

    def _has_explicit_entity(self, query: str) -> bool:
        """
        Check if query contains explicit entity mentions.
        
        Explicit = proper nouns, quoted terms, specific identifiers.
        """
        words = query.split()
        
        # Check for proper nouns (capitalized words not at sentence start)
        proper_nouns = sum(1 for w in words[1:] if len(w) > 1 and w[0].isupper())
        if proper_nouns >= 1:
            return True
        
        # Check for quoted terms
        if '"' in query or "'" in query:
            return True
        
        # Check for identifiers (alphanumeric patterns like TX-12345, ABC-001)
        import re
        identifier_pattern = r'\b[A-Z]{2,}-?\d+\b|\b\d+-[A-Z]+\b'
        if re.search(identifier_pattern, query):
            return True
        
        return False
    
    def _apply_profile_constraints(self, base_route: QueryRoute) -> QueryRoute:
        """
        Apply deployment profile constraints to route selection.
        
        Fallback Logic for 3-way Routing (Vector RAG removed):
        - LOCAL_SEARCH is now the default for fact-based queries
        - GLOBAL_SEARCH for thematic/summary queries
        - DRIFT_MULTI_HOP for multi-hop/comparative queries
        
        Legacy VECTOR_RAG enum values are automatically mapped to LOCAL_SEARCH.
        """
        
        # Legacy support: VECTOR_RAG maps to LOCAL_SEARCH
        if base_route == QueryRoute.VECTOR_RAG:
            return QueryRoute.LOCAL_SEARCH
        
        return base_route
    
    async def _assess_complexity(self, query: str) -> float:
        """
        Assess query complexity on a 0.0-1.0 scale.
        
        Factors:
        - Multi-hop indicators ("connected to", "relationship between")
        - Analytical requests ("why", "how", "analyze")
        - Number of entities/relationships implied
        """
        score = self._heuristic_complexity(query)
        
        # If borderline, use LLM for more accurate assessment
        if 0.3 < score < 0.7 and self.llm:
            score = await self._llm_complexity(query)
        
        return score
    
    async def _assess_ambiguity(self, query: str) -> float:
        """
        Assess query ambiguity on a 0.0-1.0 scale.
        
        High ambiguity = needs DRIFT-style decomposition
        Low ambiguity = can go directly to HippoRAG with clear seeds
        """
        query_lower = query.lower()
        score = 0.0
        
        # Vague entity references (high ambiguity)
        vague_refs = [
            "our", "the main", "primary", "key", "important",
            "significant", "top", "major", "leading"
        ]
        for ref in vague_refs:
            if ref in query_lower:
                score += 0.15
        
        # Unclear scope (high ambiguity)
        scope_indicators = [
            "all related", "everything about", "anything to do with",
            "overall", "in general", "broadly"
        ]
        for indicator in scope_indicators:
            if indicator in query_lower:
                score += 0.2
        
        # Comparative/analytical (needs decomposition)
        comparative = [
            "compare", "versus", "vs", "difference between",
            "better", "worse", "more than", "less than"
        ]
        for comp in comparative:
            if comp in query_lower:
                score += 0.2
        
        # Clear entity names reduce ambiguity
        # Check for proper nouns (simplified: capitalized words not at start)
        words = query.split()
        proper_nouns = sum(1 for w in words[1:] if w[0].isupper() if len(w) > 1)
        if proper_nouns >= 2:
            score -= 0.3
        elif proper_nouns == 1:
            score -= 0.15
        
        # Quoted terms reduce ambiguity
        if '"' in query or "'" in query:
            score -= 0.2
        
        return max(0.0, min(1.0, score))
    
    def _heuristic_complexity(self, query: str) -> float:
        """Fast rule-based complexity assessment."""
        query_lower = query.lower()
        score = 0.0
        
        # Multi-hop indicators (high complexity)
        multi_hop_keywords = [
            "connected to", "relationship between", "linked to",
            "through", "via", "chain of", "path from", "trace",
            "subsidiary", "parent company", "affiliated"
        ]
        for keyword in multi_hop_keywords:
            if keyword in query_lower:
                score += 0.25
        
        # Analytical requests (high complexity)
        analytical_keywords = [
            "why", "how does", "analyze", "explain", 
            "implications", "impact", "risk", "exposure",
            "assess", "evaluate"
        ]
        for keyword in analytical_keywords:
            if keyword in query_lower:
                score += 0.2
        
        # Entity-focused but needs graph (medium complexity)
        graph_keywords = [
            "all contracts", "list all", "every", "complete list",
            "associated with", "related to"
        ]
        for keyword in graph_keywords:
            if keyword in query_lower:
                score += 0.15
        
        # Simple fact patterns (low complexity)
        simple_patterns = [
            "what is the", "who is", "when was", "where is",
            "how much is", "how many", "address of", "phone number"
        ]
        for pattern in simple_patterns:
            if pattern in query_lower:
                score -= 0.25
        
        return max(0.0, min(1.0, score))
    
    async def _llm_complexity(self, query: str) -> float:
        """Use LLM for more nuanced complexity assessment."""
        if self.llm is None:
            return self._heuristic_complexity(query)
        
        prompt = f"""Rate the complexity of this search query on a scale of 0.0 to 1.0.

0.0-0.3 = Simple factual lookup (single document can answer, e.g., "What is X's address?")
0.3-0.7 = Entity-focused search (needs graph traversal, e.g., "List all contracts with X")  
0.7-1.0 = Complex multi-hop reasoning (needs decomposition, e.g., "Analyze risk exposure through subsidiaries")

Query: "{query}"

Return ONLY a decimal number between 0.0 and 1.0, nothing else."""

        try:
            response = await self.llm.acomplete(prompt)
            score = float(response.text.strip())
            return max(0.0, min(1.0, score))
        except Exception as e:
            logger.warning("llm_complexity_failed", error=str(e))
            return self._heuristic_complexity(query)


class QueryClassifier:
    """
    Simple classifier for query intent detection.
    
    Categories:
    - FACTUAL: Simple fact lookup -> Route 1
    - ENTITY_FOCUSED: Explicit entity, needs graph -> Route 2
    - THEMATIC: No explicit entity, thematic -> Route 3
    - MULTI_HOP: Ambiguous, needs decomposition -> Route 4
    """
    
    def classify(self, query: str) -> QueryRoute:
        """Classify query into a route category."""
        query_lower = query.lower()
        
        # Multi-hop / ambiguous patterns -> Route 4
        if any(kw in query_lower for kw in [
            "analyze", "exposure", "risk", "how are we connected",
            "through", "subsidiaries", "implications", "compare"
        ]):
            return QueryRoute.DRIFT_MULTI_HOP
        
        # Thematic patterns (no explicit entity) -> Route 3
        if any(kw in query_lower for kw in [
            "main risks", "key themes", "overall", "summarize",
            "what are the trends", "general overview"
        ]):
            return QueryRoute.GLOBAL_SEARCH
        
        # Entity-focused patterns -> Route 2
        if any(kw in query_lower for kw in [
            "all contracts", "list all", "related to", "associated with",
            "what are the", "who are the"
        ]):
            return QueryRoute.LOCAL_SEARCH
        
        # Simple fact patterns -> Route 1
        if any(kw in query_lower for kw in [
            "what is the", "who is", "when", "where", "how much",
            "address", "phone", "email"
        ]):
            return QueryRoute.VECTOR_RAG
        
        # Default to Local Search (entity-focused is most common)
        return QueryRoute.LOCAL_SEARCH
