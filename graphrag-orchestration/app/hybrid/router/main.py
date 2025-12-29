"""
Hybrid Pipeline Router

Routes queries between:
- Profile A (Speed-Optimized): Vector RAG + Hybrid Pipeline
- Profile B (Precision-Optimized): Hybrid Pipeline ONLY

The router uses a simple binary classifier to determine query complexity.
"""

from enum import Enum
from typing import Optional, Any
import structlog

logger = structlog.get_logger(__name__)


class QueryRoute(Enum):
    """Available routing destinations."""
    VECTOR_RAG = "vector_rag"           # Fast lane for simple queries
    HYBRID_PIPELINE = "hybrid_pipeline"  # Full LazyGraphRAG + HippoRAG


class DeploymentProfile(Enum):
    """Deployment configuration profiles."""
    GENERAL_ENTERPRISE = "general_enterprise"  # Profile A: Speed-optimized
    HIGH_ASSURANCE_AUDIT = "high_assurance"    # Profile B: Precision-optimized


class HybridRouter:
    """
    Routes queries based on complexity and deployment profile.
    
    Profile A (General Enterprise):
        - Simple queries -> Vector RAG (fast)
        - Complex queries -> Hybrid Pipeline
    
    Profile B (High-Assurance Audit):
        - ALL queries -> Hybrid Pipeline (no shortcuts)
    """
    
    def __init__(
        self,
        profile: DeploymentProfile = DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client: Optional[Any] = None,
        complexity_threshold: float = 0.5
    ):
        """
        Args:
            profile: Deployment profile (affects routing behavior).
            llm_client: Optional LLM for advanced classification.
            complexity_threshold: 0.0-1.0, queries above this go to hybrid.
        """
        self.profile = profile
        self.llm = llm_client
        self.complexity_threshold = complexity_threshold
        
        logger.info("router_initialized", 
                   profile=profile.value,
                   complexity_threshold=complexity_threshold)
    
    async def route(self, query: str) -> QueryRoute:
        """
        Determine the appropriate route for a query.
        
        Args:
            query: The user's natural language query.
            
        Returns:
            QueryRoute enum indicating where to send the query.
        """
        # Profile B: Always use hybrid pipeline (no fast lane)
        if self.profile == DeploymentProfile.HIGH_ASSURANCE_AUDIT:
            logger.info("route_decision",
                       query=query[:50],
                       route="hybrid_pipeline",
                       reason="high_assurance_profile")
            return QueryRoute.HYBRID_PIPELINE
        
        # Profile A: Classify and route
        complexity = await self._assess_complexity(query)
        
        if complexity >= self.complexity_threshold:
            route = QueryRoute.HYBRID_PIPELINE
            reason = f"complexity_score_{complexity:.2f}"
        else:
            route = QueryRoute.VECTOR_RAG
            reason = f"simple_query_{complexity:.2f}"
        
        logger.info("route_decision",
                   query=query[:50],
                   route=route.value,
                   reason=reason)
        
        return route
    
    async def _assess_complexity(self, query: str) -> float:
        """
        Assess query complexity on a 0.0-1.0 scale.
        
        Factors:
        - Multi-hop indicators ("connected to", "relationship between")
        - Ambiguity indicators ("main", "primary", "related")
        - Analytical requests ("why", "how", "analyze")
        """
        # Fast heuristic check
        complexity_score = self._heuristic_complexity(query)
        
        # If borderline, use LLM for more accurate assessment
        if 0.3 < complexity_score < 0.7 and self.llm:
            complexity_score = await self._llm_complexity(query)
        
        return complexity_score
    
    def _heuristic_complexity(self, query: str) -> float:
        """Fast rule-based complexity assessment."""
        query_lower = query.lower()
        score = 0.0
        
        # Multi-hop indicators (high complexity)
        multi_hop_keywords = [
            "connected to", "relationship between", "linked to",
            "through", "via", "chain of", "path from", "trace"
        ]
        for keyword in multi_hop_keywords:
            if keyword in query_lower:
                score += 0.3
        
        # Ambiguity indicators (medium complexity)
        ambiguity_keywords = [
            "main", "primary", "key", "important", "significant",
            "our", "the", "this"  # Pronouns often indicate context-dependence
        ]
        for keyword in ambiguity_keywords:
            if keyword in query_lower:
                score += 0.1
        
        # Analytical requests (high complexity)
        analytical_keywords = [
            "why", "how", "analyze", "explain", "compare",
            "implications", "impact", "risk", "exposure"
        ]
        for keyword in analytical_keywords:
            if keyword in query_lower:
                score += 0.2
        
        # Simple fact patterns (low complexity)
        simple_patterns = [
            "what is the", "who is", "when was", "where is",
            "how much", "how many", "list the"
        ]
        for pattern in simple_patterns:
            if pattern in query_lower:
                score -= 0.2
        
        # Clamp to 0.0-1.0
        return max(0.0, min(1.0, score))
    
    async def _llm_complexity(self, query: str) -> float:
        """Use LLM for more nuanced complexity assessment."""
        if self.llm is None:
            logger.warning("llm_not_configured_using_heuristic")
            return self._heuristic_complexity(query)
        
        prompt = f"""Rate the complexity of this search query on a scale of 0.0 to 1.0.

0.0 = Simple factual lookup (single document can answer)
0.5 = Moderate complexity (may need multiple sources)
1.0 = Complex multi-hop reasoning (needs to trace connections across many entities)

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
    - FACTUAL: Simple fact lookup
    - THEMATIC: Broad theme/summary questions  
    - MULTI_HOP: Connection/path questions
    - ANALYTICAL: Why/how/implications questions
    """
    
    def classify(self, query: str) -> str:
        """Classify query into a category."""
        query_lower = query.lower()
        
        # Multi-hop patterns
        if any(kw in query_lower for kw in ["connection", "path", "link", "trace", "between"]):
            return "MULTI_HOP"
        
        # Analytical patterns
        if any(kw in query_lower for kw in ["why", "how", "analyze", "explain", "impact"]):
            return "ANALYTICAL"
        
        # Thematic patterns
        if any(kw in query_lower for kw in ["overview", "summary", "trends", "themes"]):
            return "THEMATIC"
        
        # Default to factual
        return "FACTUAL"
