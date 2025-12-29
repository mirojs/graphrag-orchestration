"""
Hybrid Pipeline Router

Routes queries between 4 distinct routes:
1. Vector RAG - Fast lane for simple fact lookups
2. Local Search Equivalent - Entity-focused with LazyGraphRAG iterative deepening
3. Global Search Equivalent - Thematic queries with LazyGraphRAG + HippoRAG 2 PPR
4. DRIFT Equivalent - Multi-hop iterative reasoning for ambiguous queries

Profiles:
- General Enterprise: All 4 routes enabled (Route 1 is default for simple queries)
- High Assurance: Routes 2, 3, 4 only (no Vector RAG shortcuts)
"""

from enum import Enum
from typing import Optional, Any, List
import structlog

logger = structlog.get_logger(__name__)


class QueryRoute(Enum):
    """Available routing destinations."""
    VECTOR_RAG = "vector_rag"               # Route 1: Fast lane for simple queries
    LOCAL_SEARCH = "local_search"           # Route 2: Entity-focused (LazyGraphRAG only)
    GLOBAL_SEARCH = "global_search"         # Route 3: Thematic (LazyGraphRAG + HippoRAG)
    DRIFT_MULTI_HOP = "drift_multi_hop"     # Route 4: Iterative multi-hop reasoning


class DeploymentProfile(Enum):
    """Deployment configuration profiles."""
    GENERAL_ENTERPRISE = "general_enterprise"  # All 4 routes, Route 1 default
    HIGH_ASSURANCE = "high_assurance"          # Routes 2, 3, 4 only (no Vector RAG)


class HybridRouter:
    """
    Routes queries based on complexity, entity clarity, and deployment profile.
    
    Classification Logic:
    - Simple fact + clear entity -> Route 1 (Vector RAG) [General Enterprise only]
    - Explicit entity + needs graph -> Route 2 (Local Search - LazyGraphRAG)
    - Thematic / no explicit entity -> Route 3 (Global Search - LazyGraphRAG + HippoRAG)
    - Ambiguous + multi-hop -> Route 4 (DRIFT)
    
    General Enterprise Profile:
        - All 4 routes enabled
        - Route 1 handles ~80% of simple queries for speed
    
    High Assurance Profile:
        - Routes 2, 3, 4 only (no Vector RAG shortcuts)
        - Every query gets graph-based retrieval for auditability
    
    Model Selection:
        Uses HYBRID_ROUTER_MODEL (default: gpt-4o-mini) for classification.
        Fast and cost-effective for simple routing decisions.
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
        
        Returns:
            QueryRoute enum indicating where to send the query.
        """
        # Assess query characteristics
        complexity = await self._assess_complexity(query)
        ambiguity = await self._assess_ambiguity(query)
        has_explicit_entity = self._has_explicit_entity(query)
        
        # Combined score: complexity + ambiguity
        combined_score = (complexity * 0.6) + (ambiguity * 0.4)
        
        # Determine base route from score and entity clarity
        if combined_score < self.vector_threshold:
            base_route = QueryRoute.VECTOR_RAG
        elif combined_score >= self.drift_threshold:
            base_route = QueryRoute.DRIFT_MULTI_HOP
        elif has_explicit_entity:
            # Explicit entity -> Local Search (LazyGraphRAG only)
            base_route = QueryRoute.LOCAL_SEARCH
        else:
            # Thematic, no explicit entity -> Global Search (LazyGraphRAG + HippoRAG)
            base_route = QueryRoute.GLOBAL_SEARCH
        
        # Apply profile constraints
        final_route = self._apply_profile_constraints(base_route)
        
        logger.info("route_decision",
                   query=query[:50],
                   route=final_route.value,
                   complexity=f"{complexity:.2f}",
                   ambiguity=f"{ambiguity:.2f}",
                   combined=f"{combined_score:.2f}",
                   has_explicit_entity=has_explicit_entity,
                   profile=self.profile.value)
        
        return final_route
    
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
        """Apply deployment profile constraints to route selection."""
        
        # High Assurance: No Vector RAG allowed
        if self.profile == DeploymentProfile.HIGH_ASSURANCE:
            if base_route == QueryRoute.VECTOR_RAG:
                # Fall through to Local Search (simplest graph route)
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
