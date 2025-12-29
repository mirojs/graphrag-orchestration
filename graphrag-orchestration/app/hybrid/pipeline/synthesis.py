"""
Stage 3: Synthesis & Evidence Validation (The "Analyst")

Uses LazyGraphRAG's Iterative Deepening to fetch raw text chunks
based on the evidence nodes from Stage 2, then synthesizes a
comprehensive, cited response.
"""

from typing import List, Tuple, Optional, Dict, Any, TYPE_CHECKING
import structlog

logger = structlog.get_logger(__name__)


class EvidenceSynthesizer:
    """
    Takes evidence nodes from HippoRAG and generates a comprehensive
    response with citations using LazyGraphRAG's text retrieval.
    
    Key Features:
    - Fetches RAW text chunks (not summaries) for full detail retention.
    - Enforces citation requirements for auditability.
    - Uses configurable "relevance budget" for precision control.
    """
    
    def __init__(
        self, 
        llm_client: Optional[Any],
        text_unit_store: Optional[Any] = None,
        relevance_budget: float = 0.8
    ):
        """
        Args:
            llm_client: The LLM client for synthesis.
            text_unit_store: Store containing raw text chunks.
            relevance_budget: 0.0-1.0, higher = more thorough (slower).
        """
        self.llm = llm_client
        self.text_store = text_unit_store
        self.relevance_budget = relevance_budget
    
    async def synthesize(
        self,
        query: str,
        evidence_nodes: List[Tuple[str, float]],
        response_type: str = "detailed_report"
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive response with evidence citations.
        
        Args:
            query: The original user query.
            evidence_nodes: List of (entity_name, score) from Stage 2.
            response_type: "detailed_report" | "summary" | "audit_trail"
            
        Returns:
            Dictionary containing:
            - response: The generated text response.
            - citations: List of source citations.
            - evidence_path: The nodes used to generate the response.
        """
        # Step 1: Retrieve raw text chunks for evidence nodes
        text_chunks = await self._retrieve_text_chunks(evidence_nodes)
        
        # Step 2: Build context with citations
        context, citation_map = self._build_cited_context(text_chunks)
        
        # Step 3: Generate response with citation requirements
        response = await self._generate_response(
            query=query,
            context=context,
            response_type=response_type
        )
        
        # Step 4: Extract and validate citations
        citations = self._extract_citations(response, citation_map)
        
        logger.info("synthesis_complete",
                   query=query,
                   num_citations=len(citations),
                   response_length=len(response))
        
        return {
            "response": response,
            "citations": citations,
            "evidence_path": [node for node, _ in evidence_nodes],
            "text_chunks_used": len(text_chunks)
        }
    
    async def _retrieve_text_chunks(
        self, 
        evidence_nodes: List[Tuple[str, float]]
    ) -> List[Dict[str, Any]]:
        """Retrieve raw text chunks for the evidence nodes."""
        if not self.text_store:
            logger.warning("no_text_store_available")
            return []
        
        chunks = []
        entity_names = [name for name, _ in evidence_nodes]
        
        try:
            # Query text units associated with evidence entities
            for entity_name in entity_names[:int(len(entity_names) * self.relevance_budget) + 1]:
                entity_chunks = await self.text_store.get_chunks_for_entity(entity_name)
                chunks.extend(entity_chunks)
            
            logger.info("text_chunks_retrieved", num_chunks=len(chunks))
            return chunks
            
        except Exception as e:
            logger.error("text_chunk_retrieval_failed", error=str(e))
            return []
    
    def _build_cited_context(
        self, 
        text_chunks: List[Dict[str, Any]]
    ) -> Tuple[str, Dict[str, Dict[str, str]]]:
        """
        Build a context string with citation markers.
        
        Returns:
            Tuple of (context_string, citation_map)
        """
        citation_map: Dict[str, Dict[str, str]] = {}
        context_parts = []
        
        for i, chunk in enumerate(text_chunks):
            citation_id = f"[{i+1}]"
            source = chunk.get("source", "Unknown")
            text = chunk.get("text", "")
            
            citation_map[citation_id] = {
                "source": source,
                "chunk_id": chunk.get("id", f"chunk_{i}"),
                "text_preview": text[:100] + "..." if len(text) > 100 else text
            }
            
            context_parts.append(f"{citation_id} {text}")
        
        return "\n\n".join(context_parts), citation_map
    
    async def _generate_response(
        self,
        query: str,
        context: str,
        response_type: str
    ) -> str:
        """Generate the final response with citation requirements."""
        
        if self.llm is None:
            logger.error("llm_not_configured_cannot_generate_response")
            return "Error: LLM client not configured"
        
        # Different prompts for different response types
        prompts = {
            "detailed_report": self._get_detailed_report_prompt(query, context),
            "summary": self._get_summary_prompt(query, context),
            "audit_trail": self._get_audit_trail_prompt(query, context)
        }
        
        prompt = prompts.get(response_type, prompts["detailed_report"])
        
        try:
            response = await self.llm.acomplete(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error("response_generation_failed", error=str(e))
            return f"Error generating response: {str(e)}"
    
    def _get_detailed_report_prompt(self, query: str, context: str) -> str:
        return f"""You are an expert analyst generating a detailed report.

CRITICAL REQUIREMENT: You MUST cite your sources using the citation markers (e.g., [1], [2]) 
for EVERY factual claim you make. Uncited claims are not acceptable for audit purposes.

Question: {query}

Evidence Context:
{context}

Generate a comprehensive, detailed response that:
1. Directly answers the question
2. Cites specific sources for every claim using [N] notation
3. Explains the connections between entities
4. Highlights any important details from the source documents

Response:"""

    def _get_summary_prompt(self, query: str, context: str) -> str:
        return f"""You are an expert analyst generating a concise summary.

Question: {query}

Evidence Context:
{context}

Provide a brief summary (2-3 paragraphs) with key citations [N].

Summary:"""

    def _get_audit_trail_prompt(self, query: str, context: str) -> str:
        return f"""You are generating an audit trail for compliance purposes.

CRITICAL: Every statement MUST be cited. This is for legal/compliance review.

Question: {query}

Evidence Context:
{context}

Generate an audit trail that:
1. Lists each relevant finding with its exact source citation [N]
2. Shows the logical chain of evidence
3. Notes any gaps or uncertainties
4. Provides a confidence assessment

Audit Trail:"""

    def _extract_citations(
        self, 
        response: str, 
        citation_map: Dict[str, Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """Extract and validate citations from the response."""
        import re
        
        # Find all citation markers in the response
        citation_pattern = r'\[(\d+)\]'
        used_citations = set(re.findall(citation_pattern, response))
        
        citations = []
        for cite_num in sorted(used_citations, key=int):
            cite_key = f"[{cite_num}]"
            if cite_key in citation_map:
                citations.append({
                    "citation": cite_key,
                    **citation_map[cite_key]
                })
        
        return citations
