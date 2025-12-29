"""
Hybrid Pipeline Router

Routes queries between 3 distinct routes:
1. Vector RAG - Fast lane for simple fact lookups
2. Local/Global Equivalent - Entity-focused with LazyGraphRAG + HippoRAG 2
3. DRIFT Equivalent - Multi-hop iterative reasoning for ambiguous queries

Profiles:
- Profile A (General Enterprise): All 3 routes enabled
- Profile B (High-Assurance Audit): Routes 2 + 3 only (no Vector RAG)
- Profile C (Speed-Critical): Routes 1 + 2 only (no DRIFT)
"""

from enum import Enum
from typing import Optional, Any, List
import structlog

logger = structlog.get_logger(__name__)


class QueryRoute(Enum):
    """Available routing destinations."""
    VECTOR_RAG = "vector_rag"               # Route 1: Fast lane for simple queries
    LOCAL_GLOBAL = "local_global"           # Route 2: Entity-focused hybrid
    DRIFT_MULTI_HOP = "drift_multi_hop"     # Route 3: Iterative multi-hop reasoning


class DeploymentProfile(Enum):
    """Deployment configuration profiles."""
    GENERAL_ENTERPRISE = "general_enterprise"  # Profile A: All 3 routes
    HIGH_ASSURANCE_AUDIT = "high_assurance"    # Profile B: Routes 2+3 only
    SPEED_CRITICAL = "speed_critical"          # Profile C: Routes 1+2 only


class HybridRouter:
    """
    Routes queries based on complexity, clarity, and deployment profile.
    
    Classification Logic:
    - Simple fact + clear entity -> Route 1 (Vector RAG)
    - Clear entity + needs graph -> Route 2 (Local/Global)
    - Ambiguous + multi-hop -> Route 3 (DRIFT)
    
    Profile A (General Enterprise):
        - All 3 routes enabled
    
    Profile B (High-Assurance Audit):
        - Routes 2 + 3 only (no Vector RAG shortcuts)
    
    Profile C (Speed-Critical):
        - Routes 1 + 2 only (no slow DRIFT)
    """
    
    def __init__(
        self,
        profile: DeploymentProfile = DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client: Optional[Any] = None,
        vector_threshold: float = 0.3,
        drift_threshold: float = 0.7
    ):
        """
        Args:
            profile: Deployment profile (affects routing behavior).
            llm_client: Optional LLM for advanced classification.
            vector_threshold: Below this -> Route 1 (Vector RAG)
            drift_threshold: Above this -> Route 3 (DRIFT Multi-Hop)
            Between thresholds -> Route 2 (Local/Global)
        """
        self.profile = profile
        self.llm = llm_client
        self.vector_threshold = vector_threshold
        self.drift_threshold = drift_threshold
        
        logger.info("router_initialized", 
                   profile=profile.value,
                   vector_threshold=vector_threshold,
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
        
        # Combined score: complexity + ambiguity
        combined_score = (complexity * 0.6) + (ambiguity * 0.4)
        
        # Determine base route from score
        if combined_score < self.vector_threshold:
            base_route = QueryRoute.VECTOR_RAG
        elif combined_score >= self.drift_threshold:
            base_route = QueryRoute.DRIFT_MULTI_HOP
        else:
            base_route = QueryRoute.LOCAL_GLOBAL
        
        # Apply profile constraints
        final_route = self._apply_profile_constraints(base_route)
        
        logger.info("route_decision",
                   query=query[:50],
                   route=final_route.value,
                   complexity=f"{complexity:.2f}",
                   ambiguity=f"{ambiguity:.2f}",
                   combined=f"{combined_score:.2f}",
                   profile=self.profile.value)
        
        return final_route
    
    def _apply_profile_constraints(self, base_route: QueryRoute) -> QueryRoute:
        """Apply deployment profile constraints to route selection."""
        
        # Profile B: No Vector RAG allowed
        if self.profile == DeploymentProfile.HIGH_ASSURANCE_AUDIT:
            if base_route == QueryRoute.VECTOR_RAG:
                return QueryRoute.LOCAL_GLOBAL
        
        # Profile C: No DRIFT allowed
        if self.profile == DeploymentProfile.SPEED_CRITICAL:
            if base_route == QueryRoute.DRIFT_MULTI_HOP:
                return QueryRoute.LOCAL_GLOBAL
        
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
    - ENTITY_FOCUSED: Clear entity, needs graph -> Route 2
    - MULTI_HOP: Ambiguous, needs decomposition -> Route 3
    """
    
    def classify(self, query: str) -> QueryRoute:
        """Classify query into a route category."""
        query_lower = query.lower()
        
        # Multi-hop / ambiguous patterns -> Route 3
        if any(kw in query_lower for kw in [
            "analyze", "exposure", "risk", "how are we connected",
            "through", "subsidiaries", "implications"
        ]):
            return QueryRoute.DRIFT_MULTI_HOP
        
        # Entity-focused patterns -> Route 2
        if any(kw in query_lower for kw in [
            "all contracts", "list all", "related to", "associated with",
            "what are the", "who are the"
        ]):
            return QueryRoute.LOCAL_GLOBAL
        
        # Simple fact patterns -> Route 1
        if any(kw in query_lower for kw in [
            "what is the", "who is", "when", "where", "how much",
            "address", "phone", "email"
        ]):
            return QueryRoute.VECTOR_RAG
        
        # Default to Local/Global (middle ground)
        return QueryRoute.LOCAL_GLOBAL
