"""
Stage 3: Synthesis & Evidence Validation (The "Analyst")

Uses LazyGraphRAG's Iterative Deepening to fetch raw text chunks
based on the evidence nodes from Stage 2, then synthesizes a
comprehensive, cited response.

Model Selection:
- Final Synthesis (Route 2/3): HYBRID_SYNTHESIS_MODEL (gpt-5.2) - Best coherence
- Intermediate Synthesis (Route 3): HYBRID_INTERMEDIATE_MODEL (gpt-4o) - Speed/quality balance
"""

from typing import List, Tuple, Optional, Dict, Any, TYPE_CHECKING
import structlog

from app.hybrid.services.extraction_service import ExtractionService
from app.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphContext

logger = structlog.get_logger(__name__)


class EvidenceSynthesizer:
    """
    Takes evidence nodes from HippoRAG and generates a comprehensive
    response with citations using LazyGraphRAG's text retrieval.
    
    Model Selection:
    - Final answers: HYBRID_SYNTHESIS_MODEL (gpt-5.2) for maximum coherence
    - Route 3 intermediate steps: HYBRID_INTERMEDIATE_MODEL (gpt-4o) for speed
    
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
        response_type: str = "detailed_report",
        sub_questions: Optional[List[str]] = None,
        intermediate_context: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive response with evidence citations.
        
        Args:
            query: The original user query.
            evidence_nodes: List of (entity_name, score) from Stage 2.
            response_type: "detailed_report" | "summary" | "audit_trail" | "nlp_audit" | "nlp_connected"
            sub_questions: Optional list of sub-questions (Route 3 DRIFT).
            intermediate_context: Optional intermediate results from sub-questions.
            
        Returns:
            Dictionary containing:
            - response: The generated text response.
            - citations: List of source citations.
            - evidence_path: The nodes used to generate the response.
        """
        # Step 1: Retrieve raw text chunks for evidence nodes
        text_chunks = await self._retrieve_text_chunks(evidence_nodes)
        
        # nlp_audit mode: deterministic extraction only, no LLM synthesis
        if response_type == "nlp_audit":
            return await self._nlp_audit_extract(query, text_chunks, evidence_nodes)
        
        # nlp_connected mode: deterministic extraction + rephrasing with temperature=0
        if response_type == "nlp_connected":
            return await self._nlp_connected_extract(query, text_chunks, evidence_nodes)
        
        # Step 2: Build context with citations
        context, citation_map = self._build_cited_context(text_chunks)
        
        # Step 3: For Route 3, add sub-question context
        if sub_questions and intermediate_context:
            context = self._enrich_context_for_drift(
                context, sub_questions, intermediate_context
            )
        
        # Step 4: Generate response with citation requirements
        response = await self._generate_response(
            query=query,
            context=context,
            response_type=response_type,
            sub_questions=sub_questions
        )
        
        # Step 5: Extract and validate citations
        citations = self._extract_citations(response, citation_map)
        
        logger.info("synthesis_complete",
                   query=query,
                   num_citations=len(citations),
                   response_length=len(response),
                   response_type=response_type,
                   is_drift_mode=sub_questions is not None)
        
        return {
            "response": response,
            "citations": citations,
            "evidence_path": [node for node, _ in evidence_nodes],
            "text_chunks_used": len(text_chunks),
            "sub_questions_addressed": sub_questions or []
        }
    
    async def synthesize_with_graph_context(
        self,
        query: str,
        evidence_nodes: List[Tuple[str, float]],
        graph_context: EnhancedGraphContext,
        response_type: str = "detailed_report",
    ) -> Dict[str, Any]:
        """
        Enhanced synthesis using full graph context (Route 3 v2.0).
        
        This method uses:
        1. Source chunks from MENTIONS edges (real citations!)
        2. Relationship context from RELATED_TO edges
        3. Entity descriptions for richer understanding
        
        Args:
            query: The original user query.
            evidence_nodes: List of (entity_name, score) from PPR.
            graph_context: EnhancedGraphContext with chunks, relationships.
            response_type: "detailed_report" | "summary" | "audit_trail"
            
        Returns:
            Dictionary with response, citations, and evidence path.
        """
        # nlp_audit mode: deterministic extraction only, no LLM synthesis.
        # IMPORTANT: Route 3 uses synthesize_with_graph_context(), so we must
        # handle this here (not only in synthesize()).
        if response_type in {"nlp_audit", "nlp_connected"}:
            text_chunks: List[Dict[str, Any]] = []
            for i, chunk in enumerate(graph_context.source_chunks or []):
                section_str = " > ".join(chunk.section_path) if chunk.section_path else "General"
                source = chunk.document_source or chunk.document_title or "Unknown"
                text_chunks.append(
                    {
                        "id": chunk.chunk_id or f"chunk_{i}",
                        "source": source,
                        "section": section_str,
                        "entity": chunk.entity_name,
                        "text": chunk.text or "",
                    }
                )

            if response_type == "nlp_audit":
                result = await self._nlp_audit_extract(query, text_chunks, evidence_nodes)
            else:
                result = await self._nlp_connected_extract(query, text_chunks, evidence_nodes)

            # Preserve graph context flags for downstream consumers.
            result.setdefault("graph_context_used", True)
            result.setdefault("relationships_used", len(graph_context.relationships))
            return result

        # Step 1: Build citation context from source chunks (MENTIONS-derived)
        context_parts = []
        citation_map: Dict[str, Dict[str, Any]] = {}
        
        # Add source chunks as citations
        for i, chunk in enumerate(graph_context.source_chunks):
            citation_id = f"[{i+1}]"
            section_str = " > ".join(chunk.section_path) if chunk.section_path else "General"
            
            citation_map[citation_id] = {
                "source": chunk.document_source or chunk.document_title,
                "chunk_id": chunk.chunk_id,
                "section": section_str,
                "entity": chunk.entity_name,
                "text_preview": chunk.text[:150] + "..." if len(chunk.text) > 150 else chunk.text
            }
            
            # Build context entry with section metadata
            entry = f"{citation_id} [Section: {section_str}] [Entity: {chunk.entity_name}]\n{chunk.text}"
            context_parts.append(entry)
        
        # Step 2: Add relationship context
        relationship_context = graph_context.get_relationship_context()
        
        # Step 3: Add entity descriptions
        entity_context = ""
        if graph_context.entity_descriptions:
            entity_lines = ["## Entity Descriptions:"]
            for name, desc in list(graph_context.entity_descriptions.items())[:10]:
                if desc:
                    entity_lines.append(f"- **{name}**: {desc[:200]}")
            entity_context = "\n".join(entity_lines)
        
        # Step 4: Combine all context
        full_context = "\n\n".join(context_parts)
        if relationship_context:
            full_context = relationship_context + "\n\n" + full_context
        if entity_context:
            full_context = entity_context + "\n\n" + full_context
        
        # Validate that we have source chunks from MENTIONS edges
        if not graph_context.source_chunks:
            logger.error("no_source_chunks_from_mentions",
                        hub_entities=graph_context.hub_entities,
                        num_relationships=len(graph_context.relationships))
            raise RuntimeError(
                f"No source chunks found via MENTIONS edges for hub entities: {graph_context.hub_entities}. "
                "This indicates the group may not have been properly indexed with entity extraction, "
                "or the entities don't have MENTIONS relationships to TextChunks."
            )
        
        # Step 5: Generate response
        response = await self._generate_graph_response(
            query=query,
            context=full_context,
            hub_entities=graph_context.hub_entities,
            response_type=response_type
        )
        
        # Step 6: Extract citations from response
        citations = self._extract_citations(response, citation_map)
        
        logger.info("synthesis_with_graph_context_complete",
                   query=query[:50],
                   num_source_chunks=len(graph_context.source_chunks),
                   num_relationships=len(graph_context.relationships),
                   num_citations=len(citations),
                   response_length=len(response))
        
        return {
            "response": response,
            "citations": citations,
            "evidence_path": [node for node, _ in evidence_nodes],
            "text_chunks_used": len(graph_context.source_chunks),
            "graph_context_used": True,
            "relationships_used": len(graph_context.relationships),
        }
    
    async def _generate_graph_response(
        self,
        query: str,
        context: str,
        hub_entities: List[str],
        response_type: str
    ) -> str:
        """Generate response with graph-aware prompting."""
        if self.llm is None:
            logger.error("llm_not_configured")
            return "Error: LLM client not configured"
        
        hub_str = ", ".join(hub_entities[:5]) if hub_entities else "various"

        ql = (query or "").lower()
        reporting_hint = ""
        if any(k in ql for k in ["reporting", "record-keeping", "record keeping", "recordkeeping"]):
            reporting_hint = """

    Additional requirements for reporting/record-keeping questions:
    - Enumerate distinct reporting/record-keeping obligations as bullet points.
    - For each bullet, cite at least one source chunk that explicitly states it.
    - If the evidence uses specific wording (e.g., periodic statements, income/expenses, volumes/pumper/county), quote those phrases verbatim and cite them.
    """
        
        prompt = f"""You are an expert analyst generating a response using knowledge graph evidence.

CRITICAL REQUIREMENT: You MUST cite your sources using the citation markers (e.g., [1], [2])
for EVERY factual claim. Citations link to source documents via entity relationships.

Query: {query}

Hub Entities (Key Topics): {hub_str}

Evidence Context (organized by entity relationships and document sections):
{context}

{reporting_hint}

Generate a comprehensive {response_type.replace('_', ' ')} that:
1. Directly answers the query
2. Cites specific sources for EVERY claim using [N] notation
3. Leverages the entity relationships to explain connections
4. Organizes information by document sections where relevant
5. Highlights cross-references between different sources
6. Includes any explicit numeric values found in evidence (e.g., dollar amounts, time periods/deadlines, percentages, counts) verbatim

Response:"""

        try:
            response = await self.llm.acomplete(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error("graph_response_generation_failed", error=str(e))
            return f"Error generating response: {str(e)}"
    
    def _enrich_context_for_drift(
        self,
        base_context: str,
        sub_questions: List[str],
        intermediate_context: List[Dict[str, Any]]
    ) -> str:
        """Add structured sub-question context for DRIFT-style synthesis."""
        drift_section = "\n\n## Sub-Question Analysis:\n"
        
        for i, (sub_q, result) in enumerate(zip(sub_questions, intermediate_context), 1):
            drift_section += f"\n### Q{i}: {sub_q}\n"
            drift_section += f"- Entities identified: {', '.join(result.get('entities', []))}\n"
            drift_section += f"- Evidence points: {result.get('evidence_count', 0)}\n"
        
        return base_context + drift_section
    
    async def _retrieve_text_chunks(
        self, 
        evidence_nodes: List[Tuple[str, float]]
    ) -> List[Dict[str, Any]]:
        """Retrieve raw text chunks for the evidence nodes.
        
        Performance optimization: Uses batched Neo4j query to fetch all entities
        in a single round-trip instead of sequential queries (4-10x faster).
        """
        if not self.text_store:
            logger.warning("no_text_store_available")
            return []
        
        chunks = []
        entity_names = [name for name, _ in evidence_nodes]
        
        # Apply relevance budget (limit entities processed)
        budget_limit = int(len(entity_names) * self.relevance_budget) + 1
        selected_entities = entity_names[:budget_limit]
        
        try:
            # Batch query: fetch all entities in one round-trip (major performance gain)
            if hasattr(self.text_store, 'get_chunks_for_entities'):
                entity_chunks_map = await self.text_store.get_chunks_for_entities(selected_entities)
                for entity_name in selected_entities:
                    chunks.extend(entity_chunks_map.get(entity_name, []))
            else:
                # Fallback to sequential queries (for HippoRAGTextUnitStore or old implementations)
                for entity_name in selected_entities:
                    entity_chunks = await self.text_store.get_chunks_for_entity(entity_name)
                    chunks.extend(entity_chunks)
            
            logger.info("text_chunks_retrieved", 
                       num_chunks=len(chunks),
                       num_entities=len(selected_entities),
                       batched=hasattr(self.text_store, 'get_chunks_for_entities'))
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
        response_type: str,
        sub_questions: Optional[List[str]] = None
    ) -> str:
        """Generate the final response with citation requirements."""
        
        if self.llm is None:
            logger.error("llm_not_configured_cannot_generate_response")
            return "Error: LLM client not configured"
        
        # Different prompts for different response types
        if sub_questions:
            # DRIFT mode: Use multi-question synthesis prompt
            prompt = self._get_drift_synthesis_prompt(query, context, sub_questions)
        else:
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
    
    def _get_drift_synthesis_prompt(
        self, 
        query: str, 
        context: str,
        sub_questions: List[str]
    ) -> str:
        """Prompt for DRIFT-style multi-question synthesis."""
        sub_q_list = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(sub_questions))
        
        return f"""You are analyzing a complex query that was decomposed into multiple sub-questions.

Original Query: {query}

Sub-questions explored:
{sub_q_list}

Evidence Context (with citation markers):
{context}

Instructions:
1. Synthesize findings from ALL sub-questions into a coherent analysis
2. Show how the answers connect to address the original query
3. EVERY factual claim must include a citation [n] to the evidence
4. Structure your response to follow the logical flow of the sub-questions
5. Include a final synthesis section that ties everything together

Format:
## Analysis

[Your comprehensive analysis addressing each sub-question]

## Key Connections

[How the findings relate to each other]

## Conclusion

[Final answer to the original query]

Your response:"""
    
    def _get_detailed_report_prompt(self, query: str, context: str) -> str:
        return f"""You are an expert analyst generating a detailed report.

CRITICAL REQUIREMENTS:
1. First, carefully evaluate if the Evidence Context contains the SPECIFIC information requested in the question.
2. If the EXACT information is NOT present in the evidence context, respond ONLY with this exact phrase: "The requested information is not found in the provided documents."
3. Do NOT provide related information, tangential facts, or workarounds when the specific requested information is missing.
4. ONLY if relevant information IS present, you MUST cite your sources using the citation markers (e.g., [1], [2]) for EVERY factual claim you make. Uncited claims are not acceptable for audit purposes.

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

Instructions:
1. CRITICAL: First, carefully evaluate if the Evidence Context contains the SPECIFIC information requested in the question.
2. If the EXACT information is NOT present (e.g., the question asks for a routing number and no routing number exists in the evidence), you MUST respond with ONLY this exact phrase: "The requested information is not found in the provided documents."
3. Do NOT provide related information, tangential facts, or workarounds when the specific requested information is missing.
4. ONLY if the evidence DOES contain the specific requested information, provide a brief summary (2-3 paragraphs).
5. Include citations [N] for factual claims (aim for every sentence that states a fact).
6. If the evidence contains explicit numeric values (e.g., dollar amounts, time periods/deadlines, percentages, counts), include them verbatim.
7. Prefer concrete obligations/thresholds over general paraphrases.
8. If the question is asking for obligations, reporting/record-keeping, remedies, default/breach, or dispute-resolution: enumerate each distinct obligation/mechanism that is explicitly present in the Evidence Context; do not omit items just because another item is more prominent.

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

    async def _nlp_connected_extract(
        self,
        query: str,
        text_chunks: List[Dict[str, Any]],
        evidence_nodes: List[Tuple[str, float]]
    ) -> Dict[str, Any]:
        """
        Deterministic extraction + sentence connection (rephrasing with temperature=0).
        
        Uses ExtractionService from V3 for sentence extraction and optional rephrasing.
        Deterministic: same input produces consistent output (minor LLM variance possible).
        """
        extraction = ExtractionService(llm=self.llm)
        
        # Prepare communities (treat each text chunk as a "community")
        communities = [
            {
                "id": chunk.get("id", f"chunk_{i}"),
                "title": chunk.get("source", "Unknown"),
                "summary": chunk.get("text", ""),
            }
            for i, chunk in enumerate(text_chunks[:20])  # Limit to avoid excessive tokens
        ]
        
        # Extract and rephrase
        result = extraction.audit_summary(
            communities=communities,
            query=query,
            top_k=5,
            include_rephrased=True,  # Enable sentence connection
        )
        
        # Build citations from extracted sentences
        citations = []
        for sent in result.get("extracted_sentences", []):
            citations.append({
                "text": sent["text"],
                "source": sent.get("source_community_title", "Unknown"),
                "rank_score": sent.get("rank_score", 0.0),
            })
        
        return {
            "response": result.get("rephrased_narrative", result.get("audit_summary", "")),
            "citations": citations,
            "evidence_path": [node for node, _ in evidence_nodes],
            "text_chunks_used": len(text_chunks),
            "processing_deterministic": True,
            "extraction_mode": "nlp_connected",
        }

    async def _nlp_audit_extract(
        self,
        query: str,
        text_chunks: List[Dict[str, Any]],
        evidence_nodes: List[Tuple[str, float]]
    ) -> Dict[str, Any]:
        """
        Deterministic NLP extraction (no LLM) for 100% repeatability.
        
        Uses simple regex-based sentence extraction from text chunks.
        Same algorithm as V3 ExtractionService but on LazyGraphRAG context.
        """
        import re
        
        # Combine all text chunks
        combined_text = " ".join([
            chunk.get("text", "")
            for chunk in text_chunks
            if isinstance(chunk.get("text"), str)
        ])
        
        if not combined_text.strip():
            return {
                "response": "Not specified in the provided documents.",
                "citations": [],
                "evidence_path": [node[0] for node in evidence_nodes],
                "text_chunks_used": 0,
                "processing_deterministic": True,
            }
        
        # Extract top sentences deterministically
        raw_sentences = re.split(r'(?<=[.!?])\s+', combined_text.strip())
        
        sentences = []
        for i, sent in enumerate(raw_sentences):
            sent = sent.strip()
            if len(sent) < 10:  # min length
                continue
            
            # Deterministic scoring: position + length
            position_score = 1.0 / (i + 1)
            length_penalty = min(1.0, len(sent) / 100.0)
            rank = position_score * length_penalty
            
            sentences.append({
                "text": sent,
                "rank_score": float(rank),
                "sentence_idx": i,
            })
        
        # Sort and take top 5
        sentences.sort(key=lambda x: (-x["rank_score"], x["sentence_idx"]))
        top_sentences = sentences[:5]
        
        audit_summary = " ".join([s["text"] for s in top_sentences])
        
        # Build citations from text chunks
        citations = []
        for i, chunk in enumerate(text_chunks[:10], 1):
            citations.append({
                "citation": f"[{i}]",
                "source": chunk.get("source", "unknown"),
                "text_preview": (chunk.get("text", "") or "")[:200],
            })
        
        logger.info(
            "nlp_audit_extraction_complete",
            query=query[:50],
            sentences_extracted=len(top_sentences),
            processing_deterministic=True,
        )
        
        return {
            "response": audit_summary,
            "citations": citations,
            "evidence_path": [node[0] for node in evidence_nodes],
            "text_chunks_used": len(text_chunks),
            "processing_deterministic": True,
            "extracted_sentences": top_sentences,
        }

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
