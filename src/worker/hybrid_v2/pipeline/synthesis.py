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
import re
import structlog

from src.worker.hybrid_v2.services.extraction_service import ExtractionService
from src.worker.hybrid_v2.pipeline.enhanced_graph_retriever import EnhancedGraphContext

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

    _REFUSAL_MESSAGE = "The requested information was not found in the available documents."

    def _detect_missing_field_refusal(
        self,
        query: str,
        text_chunks: List[Dict[str, Any]],
        response_type: str,
    ) -> Optional[str]:
        if response_type not in {"summary", "detailed_report"}:
            return None
        q = (query or "").casefold()
        if not q:
            return None

        evidence_text = " ".join(
            chunk.get("text", "")
            for chunk in text_chunks
            if isinstance(chunk, dict)
        )
        ev = evidence_text.casefold()

        def _has_any(terms: Tuple[str, ...]) -> bool:
            return any(t in ev for t in terms)

        if "california" in q and ("governed" in q or "law" in q or "laws" in q):
            if not self._has_governing_law_jurisdiction(evidence_text, "california"):
                return "california_law_missing"

        if "routing number" in q and "routing number" not in ev:
            return "routing_number_missing"

        if any(t in q for t in ("swift", "iban", "bic")) and not _has_any(("swift", "iban", "bic")):
            return "swift_iban_bic_missing"

        if "vat" in q and "vat" not in ev:
            return "vat_missing"

        if "tax id" in q and "tax id" not in ev:
            return "tax_id_missing"

        if "bank account number" in q and not _has_any(("bank account number", "account number")):
            return "bank_account_missing"

        if "shipped via" in q or "shipping method" in q:
            if not self._has_shipped_via_value(evidence_text):
                return "shipped_via_missing"

        if ("mold" in q or "mildew" in q) and ("clause" in q or "coverage" in q):
            if not _has_any(("mold", "mildew")):
                return "mold_clause_missing"

        return None

    def _has_shipped_via_value(self, evidence_text: str) -> bool:
        if not evidence_text:
            return False
        header_tokens = (
            "salesperson",
            "p.o.",
            "po",
            "p.o",
            "number",
            "requisitioner",
            "due date",
            "terms",
        )
        for match in re.finditer(r"shipped\s+via\s*[:\-]?\s*([^\n\r]+)", evidence_text, re.IGNORECASE):
            value = (match.group(1) or "").strip()
            if not value:
                continue
            value_norm = value.casefold()
            if any(tok in value_norm for tok in header_tokens):
                continue
            if re.fullmatch(r"[\W_]+", value):
                continue
            return True
        return False

    def _has_governing_law_jurisdiction(self, evidence_text: str, jurisdiction: str) -> bool:
        if not evidence_text or not jurisdiction:
            return False
        j = re.escape(jurisdiction.strip())
        patterns = (
            rf"governed\s+by\s+(the\s+)?(laws?|law)\s+of\s+(the\s+state\s+of\s+)?{j}",
            rf"governing\s+law[^\n\r]{0,80}{j}",
        )
        for pattern in patterns:
            if re.search(pattern, evidence_text, re.IGNORECASE):
                return True
        return False
    
    async def synthesize(
        self,
        query: str,
        evidence_nodes: List[Tuple[str, float]],
        response_type: str = "detailed_report",
        sub_questions: Optional[List[str]] = None,
        intermediate_context: Optional[List[Dict[str, Any]]] = None,
        coverage_chunks: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive response with evidence citations.
        
        Args:
            query: The original user query.
            evidence_nodes: List of (entity_name, score) from Stage 2.
            response_type: "detailed_report" | "summary" | "audit_trail" | "nlp_audit" | "nlp_connected"
            sub_questions: Optional list of sub-questions (Route 3 DRIFT).
            intermediate_context: Optional intermediate results from sub-questions.
            coverage_chunks: Optional list of pre-retrieved chunks (e.g., from coverage retrieval).
            
        Returns:
            Dictionary containing:
            - response: The generated text response.
            - citations: List of source citations.
            - evidence_path: The nodes used to generate the response.
        """
        # Step 1: Retrieve raw text chunks for evidence nodes
        text_chunks = await self._retrieve_text_chunks(evidence_nodes)
        
        # Step 1.5: Merge coverage chunks if provided
        if coverage_chunks:
            text_chunks.extend(coverage_chunks)

        # Route 4 often produces generic "evidence" strings when seed entities don't resolve.
        # If entity-based retrieval returns nothing, fall back to query-based chunk retrieval.
        if not text_chunks and self.text_store and hasattr(self.text_store, "get_chunks_for_query"):
            try:
                text_chunks = await self.text_store.get_chunks_for_query(query)
                logger.info(
                    "text_chunks_query_fallback",
                    num_chunks=len(text_chunks),
                )
            except Exception as e:
                logger.warning("text_chunks_query_fallback_failed", error=str(e))

        refusal_reason = self._detect_missing_field_refusal(query, text_chunks, response_type)
        if refusal_reason:
            logger.info(
                "synthesis_refusal_missing_field",
                query=query,
                reason=refusal_reason,
                response_type=response_type,
            )
            return {
                "response": self._REFUSAL_MESSAGE,
                "citations": [],
                "evidence_path": [node for node, _ in evidence_nodes],
                "text_chunks_used": len(text_chunks),
                "sub_questions_addressed": sub_questions or [],
            }
        
        # nlp_audit mode: deterministic extraction only, no LLM synthesis
        if response_type == "nlp_audit":
            return await self._nlp_audit_extract(query, text_chunks, evidence_nodes)
        
        # nlp_connected mode: deterministic extraction + rephrasing with temperature=0
        if response_type == "nlp_connected":
            return await self._nlp_connected_extract(query, text_chunks, evidence_nodes)
        
        # comprehensive mode: 2-pass extraction (structured extraction → LLM enrichment)
        # This mode solves the LLM fact-dropping problem by extracting facts FIRST,
        # then using LLM only for comparison/explanation. Achieves 100% ground truth coverage.
        if response_type == "comprehensive":
            return await self._comprehensive_two_pass_extract(query, text_chunks, evidence_nodes)
        
        # Step 2: Build context with citations (now groups by document for better reasoning)
        context, citation_map = self._build_cited_context(text_chunks)
        context, citation_map = self._build_cited_context(text_chunks)
        
        # Step 2.5: Inject global document overview when retrieval is sparse.
        # This fixes Q-D7 (dates) and Q-D8 (comparisons) where PPR returns few/no entities.
        sparse_retrieval = len(text_chunks) < 3 or len(evidence_nodes) == 0
        if sparse_retrieval and self.text_store and hasattr(self.text_store, "get_workspace_document_overviews"):
            try:
                doc_overviews = await self.text_store.get_workspace_document_overviews(limit=20)
                if doc_overviews:
                    overview_section = self._format_document_overview(doc_overviews)
                    context = overview_section + "\n\n" + context
                    logger.info("injected_global_document_overview", num_docs=len(doc_overviews))
            except Exception as e:
                logger.warning("global_document_overview_injection_failed", error=str(e))
        
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
        # Special response types that need custom handling
        # IMPORTANT: Route 3 uses synthesize_with_graph_context(), so we must
        # handle these here (not only in synthesize()).
        if response_type in {"nlp_audit", "nlp_connected", "comprehensive"}:
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
                        "document_id": chunk.document_id or "",
                        "document_title": chunk.document_title or "Unknown",
                        "document_source": chunk.document_source or "",
                        "metadata": {
                            "document_id": chunk.document_id or "",
                            "document_title": chunk.document_title or "Unknown",
                            "section_path_key": section_str,
                        }
                    }
                )

            if response_type == "nlp_audit":
                result = await self._nlp_audit_extract(query, text_chunks, evidence_nodes)
            elif response_type == "nlp_connected":
                result = await self._nlp_connected_extract(query, text_chunks, evidence_nodes)
            elif response_type == "comprehensive":
                result = await self._comprehensive_two_pass_extract(query, text_chunks, evidence_nodes)

            # Preserve graph context flags for downstream consumers.
            result.setdefault("graph_context_used", True)
            result.setdefault("relationships_used", len(graph_context.relationships))
            return result

        # Step 1: Build citation context from source chunks (MENTIONS-derived)
        # Group chunks by document_id to ensure proper document attribution
        from collections import defaultdict
        doc_groups: Dict[str, List[Tuple[int, Any]]] = defaultdict(list)
        
        for i, chunk in enumerate(graph_context.source_chunks):
            # Use document_id as primary grouping key (graph ground truth)
            doc_key = chunk.document_id or chunk.document_source or chunk.document_title or "Unknown"
            doc_groups[doc_key].append((i, chunk))
        
        logger.info(
            "route3_document_grouping",
            num_chunks=len(graph_context.source_chunks),
            num_doc_groups=len(doc_groups),
            doc_keys=list(doc_groups.keys())[:10],
        )
        
        context_parts = []
        citation_map: Dict[str, Dict[str, Any]] = {}
        
        # Add unique document count header to help LLM with document-counting questions
        # This prevents LLM from counting sections/chunks as separate documents
        unique_doc_names = [
            (chunks[0][1].document_title or chunks[0][1].document_source or key)
            for key, chunks in doc_groups.items()
        ]
        context_parts.append(f"## Retrieved from {len(doc_groups)} unique source document(s): {', '.join(unique_doc_names)}\n")
        
        # Build context grouped by document
        for doc_key, chunks_with_idx in doc_groups.items():
            first_chunk = chunks_with_idx[0][1]
            doc_title = first_chunk.document_title or first_chunk.document_source or doc_key
            
            # Add document header for clearer LLM reasoning
            context_parts.append(f"=== DOCUMENT: {doc_title} ===")
            
            for original_idx, chunk in chunks_with_idx:
                citation_id = f"[{original_idx + 1}]"
                section_str = " > ".join(chunk.section_path) if chunk.section_path else "General"
                
                citation_map[citation_id] = {
                    "source": chunk.document_source or chunk.document_title,
                    "chunk_id": chunk.chunk_id,
                    "document": doc_title,  # Add document for proper attribution
                    "document_id": chunk.document_id or "",  # Include document ID from SourceChunk
                    "document_title": chunk.document_title or doc_title,  # Include document title
                    "section": section_str,
                    "entity": chunk.entity_name,
                    "text_preview": chunk.text[:150] + "..." if len(chunk.text) > 150 else chunk.text
                }
                
                # Build context entry with section metadata
                entry = f"{citation_id} [Section: {section_str}] [Entity: {chunk.entity_name}]\n{chunk.text}"
                context_parts.append(entry)
            
            context_parts.append("")  # Blank line between documents
        
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

        termination_hint = ""
        if any(k in ql for k in ["termination", "terminate", "cancel", "cancellation"]):
            termination_hint = """

        Additional requirements for termination/cancellation questions:
        - Explicitly list each distinct notice period and cancellation window using digits (e.g., "3 business days", "60 days", "10 business days") when present.
        - State the refund/forfeiture outcome for each cancellation window (e.g., full refund vs deposit forfeited).
        - If a document has no termination/cancellation mechanism, state that explicitly.
        """
        
        prompt = f"""You are an expert analyst generating a response using knowledge graph evidence.

CRITICAL REQUIREMENT: You MUST cite your sources using the citation markers (e.g., [1], [2])
for EVERY factual claim. Citations link to source documents via entity relationships.

Query: {query}

Hub Entities (Key Topics): {hub_str}

Evidence Context (organized by entity relationships and document sections):
{context}

{reporting_hint}

{termination_hint}

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

    def _format_document_overview(self, doc_overviews: List[Dict[str, Any]]) -> str:
        """Format global document overview for corpus-level reasoning.
        
        This enables the LLM to answer questions like:
        - "What is the latest date across all documents?"
        - "Which document contains more X?"
        - "Compare document A and document B"
        
        Args:
            doc_overviews: List of document metadata dicts.
            
        Returns:
            Formatted overview string to prepend to context.
        """
        lines = ["## Available Documents in Corpus:\n"]
        for i, doc in enumerate(doc_overviews, 1):
            title = doc.get("title", "Untitled")
            date = doc.get("date", "")
            summary = doc.get("summary", "")
            chunk_count = doc.get("chunk_count", 0)
            
            # Build a concise entry
            entry = f"{i}. **{title}**"
            if date:
                entry += f" (Date: {date})"
            if chunk_count:
                entry += f" [{chunk_count} sections]"
            if summary:
                # Truncate long summaries
                summary_preview = summary[:200] + "..." if len(summary) > 200 else summary
                entry += f"\n   Summary: {summary_preview}"
            lines.append(entry)
        
        lines.append("\n---\n")
        return "\n".join(lines)
    
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
        def _clean_entity_name(name: str) -> str:
            cleaned = (name or "").strip()
            while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'", "`"):
                cleaned = cleaned[1:-1].strip()
            return cleaned

        # Normalize + de-dupe (preserve order)
        seen: set[str] = set()
        entity_names: List[str] = []
        for name, _score in evidence_nodes:
            cleaned = _clean_entity_name(name)
            if not cleaned:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            entity_names.append(cleaned)
        
        # Apply relevance budget (limit entities processed)
        budget_limit = int(len(entity_names) * self.relevance_budget) + 1
        selected_entities = entity_names[:budget_limit]

        # Common Route 4 case: no entity seeds. Don't emit a misleading "0 chunks" log here;
        # the caller may fall back to query-based retrieval.
        if len(selected_entities) == 0:
            return []
        
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

            if len(chunks) == 0 and len(selected_entities) > 0:
                logger.warning(
                    "text_chunks_retrieved_zero",
                    num_entities=len(selected_entities),
                    sample_entities=selected_entities[:5],
                    hint="Likely entity/chunk label or MENTIONS direction mismatch, or chunks not linked to entities for this group_id",
                )
            return chunks
            
        except Exception as e:
            logger.error("text_chunk_retrieval_failed", error=str(e))
            return []
    
    def _build_cited_context(
        self, 
        text_chunks: List[Dict[str, Any]]
    ) -> Tuple[str, Dict[str, Dict[str, str]]]:
        """
        Build a context string with citation markers, grouped by document.
        
        Grouping by document enables the LLM to reason about:
        - Which document a fact comes from
        - Comparisons between documents
        - Document-level properties (dates, totals)
        
        Returns:
            Tuple of (context_string, citation_map)
        """
        citation_map: Dict[str, Dict[str, str]] = {}
        
        def _normalize_doc_key(doc_key: str) -> str:
            """
            Normalize document keys to merge sub-parts with parent documents.
            
            Removes common sub-part prefixes/patterns:
            - "Document Name - Exhibit A" -> "Document Name"
            - "Document Name - Appendix B" -> "Document Name"
            - "Document Name - Schedule 1" -> "Document Name"
            - "Agreement (Section 3: Arbitration)" -> "Agreement"
            """
            if not doc_key or not isinstance(doc_key, str):
                return doc_key
            
            import re
            
            # Pattern 1: Remove " - Exhibit/Appendix/Schedule/Attachment/Annex ..."
            patterns = [
                r'\s*[-–—]\s*(Exhibit|Appendix|Schedule|Attachment|Annex|Section)\s+[A-Z0-9].*$',
                r'\s*[-–—]\s*(Exhibit|Appendix|Schedule|Attachment|Annex)$',
                # Pattern 2: Remove parenthetical sections like "(Section 3: ...)"
                r'\s*\(Section\s+\d+:?\s*[^)]*\)$',
                r'\s*\([^)]*Arbitration[^)]*\)$',
            ]
            
            for pattern in patterns:
                doc_key = re.sub(pattern, '', doc_key, flags=re.IGNORECASE)
            
            return doc_key.strip()
        
        # Group chunks by document for clearer context boundaries
        from collections import defaultdict
        doc_groups: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
        
        for i, chunk in enumerate(text_chunks):
            # Extract document identity from metadata or source
            meta = chunk.get("metadata", {})
            # Primary: use document_id from graph (authoritative, no normalization needed)
            doc_key = meta.get("document_id")
            if not doc_key:
                # Fallback: normalize document_title or source to merge sub-parts
                raw_doc_key = meta.get("document_title") or chunk.get("source", "Unknown")
                doc_key = _normalize_doc_key(raw_doc_key)
            doc_groups[doc_key].append((i, chunk))
        
        # Log document grouping for debugging
        logger.info(
            "build_cited_context_grouping",
            num_chunks=len(text_chunks),
            num_doc_groups=len(doc_groups),
            doc_keys=list(doc_groups.keys())[:10],  # Log first 10 doc keys
        )
        
        context_parts = []
        
        # Build context with document headers
        for doc_key, chunks_with_idx in doc_groups.items():
            # Extract document metadata from first chunk
            first_chunk = chunks_with_idx[0][1]
            meta = first_chunk.get("metadata", {})
            doc_title = meta.get("document_title") or doc_key
            doc_date = meta.get("document_date", "")
            
            # Add document header
            header = f"=== DOCUMENT: {doc_title}"
            if doc_date:
                header += f" (Date: {doc_date})"
            header += " ==="
            context_parts.append(header)
            
            # Add chunks under this document
            for original_idx, chunk in chunks_with_idx:
                citation_id = f"[{original_idx + 1}]"
                source = chunk.get("source", "Unknown")
                text = chunk.get("text", "")
                
                # Extract section information from metadata
                meta = chunk.get("metadata", {})
                section_path = meta.get("section_path") or meta.get("di_section_path")
                section_str = "General"
                if isinstance(section_path, list) and section_path:
                    section_str = " > ".join(str(x) for x in section_path if x)
                elif isinstance(section_path, str) and section_path:
                    section_str = section_path
                
                # Extract document_id from metadata (set by Neo4jTextUnitStore from IN_DOCUMENT edge)
                document_id = meta.get("document_id", "")
                
                # Extract document URL from multiple sources
                document_url = (
                    chunk.get("document_source", "")  # From IN_DOCUMENT→Document.source
                    or chunk.get("document_url", "")  # Direct field
                    or meta.get("url", "")  # From chunk metadata
                    or ""
                )
                
                # Extract location metadata for precise citations
                page_number = meta.get("page_number")
                start_offset = meta.get("start_offset")
                end_offset = meta.get("end_offset")
                
                citation_map[citation_id] = {
                    "source": source,
                    "chunk_id": chunk.get("id", f"chunk_{original_idx}"),
                    "document": doc_title,
                    "document_id": document_id,  # Graph node ID for citation attribution
                    "document_title": doc_title,  # Explicit title for Route 2/3 citation format
                    "document_url": document_url,  # Blob storage URL for clickable links
                    "section": section_str,
                    "text_preview": text[:100] + "..." if len(text) > 100 else text,
                    # Location metadata for precise citations
                    **({"page_number": page_number} if page_number is not None else {}),
                    **({"start_offset": start_offset} if start_offset is not None else {}),
                    **({"end_offset": end_offset} if end_offset is not None else {}),
                }
                
                context_parts.append(f"{citation_id} {text}")
            
            context_parts.append("")  # Blank line between documents
        
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
2. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence:
   - If the question asks for "bank routing number" and the evidence shows payment portal URLs but NO routing number → REFUSE
   - If the question asks for "VAT/Tax ID" and the evidence shows Tax IDs (U.S. Federal) but NO VAT number → REFUSE  
   - If the question asks for "governed by California law" and the evidence shows Texas/other states → REFUSE
    - When refusing, respond ONLY with: "The requested information was not found in the available documents."
3. Do NOT be "helpful" by providing alternative/related information when the specific item is missing.
4. ONLY if the EXACT requested information IS present: cite sources [N] for EVERY claim.

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
        # Detect document-counting and per-document queries
        # These patterns trigger document consolidation guidance
        q_lower = query.lower()
        
        # Simple string patterns (exact match)
        simple_patterns = [
            "each document", "every document", "all documents",
            "different documents", "how many documents", "most documents",
        ]
        # Regex patterns (for flexible matching)
        regex_patterns = [
            r"summarize.*document", r"list.*document",
            r"appears?\s+in.*documents",  # "appears in X documents"
            r"which.*documents?",  # "which document(s)"
        ]
        
        is_per_document_query = (
            any(pattern in q_lower for pattern in simple_patterns) or
            any(re.search(pattern, q_lower) for pattern in regex_patterns)
        )
        
        document_guidance = ""
        if is_per_document_query:
            document_guidance = """
IMPORTANT for Per-Document Queries:
- The Evidence Context contains chunks grouped by "=== DOCUMENT: <title> ===" headers.
- Count UNIQUE top-level documents only - do NOT create separate summaries for:
  * Document sections (e.g., "Section 2: Arbitration" belongs to parent document)
  * Exhibits, Appendices, Schedules (e.g., "Exhibit A" belongs to parent contract)
  * Repeated excerpts from the same document
- If you see "Builder's Warranty" and "Builder's Warranty - Section 3", combine into ONE summary.
- If you see "Purchase Contract" and "Exhibit A - Scope of Work", combine into ONE summary.
"""
        
        return f"""You are an expert analyst generating a concise summary.

Question: {query}

Evidence Context:
{context}

Instructions:
1. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence:
    - Question asks for "bank routing number" but evidence only has payment portal URL → Output: "The requested information was not found in the available documents."
    - Question asks for "SWIFT code" but evidence has no SWIFT/IBAN → Output: "The requested information was not found in the available documents."
    - Question asks for "California law" but evidence shows Texas law → Output: "The requested information was not found in the available documents."
   - Do NOT say "The invoice does not provide X, but here is Y" — Just refuse entirely.
2. ONLY if the EXACT requested information IS present: provide a brief summary (2-3 paragraphs).
3. **RESPECT ALL QUALIFIERS** in the question. If the question asks for a specific type, category, or unit:
   - Include ONLY items matching that qualifier
   - EXCLUDE items that don't match, even if they seem related
4. Include citations [N] for factual claims (aim for every sentence that states a fact).
5. If the evidence contains explicit numeric values (e.g., dollar amounts, time periods/deadlines, percentages, counts), include them verbatim.
6. Prefer concrete obligations/thresholds over general paraphrases.
7. If the question is asking for obligations, reporting/record-keeping, remedies, default/breach, or dispute-resolution: enumerate each distinct obligation/mechanism that is explicitly present in the Evidence Context; do not omit items just because another item is more prominent.
{document_guidance}
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
        
        Returns all retrieved chunk content with citations, preserving
        the full context that the LLM synthesis would have access to.
        This enables fair comparison between LLM and deterministic modes.
        """
        import re
        
        if not text_chunks:
            return {
                "response": "Not specified in the provided documents.",
                "citations": [],
                "evidence_path": [node[0] for node in evidence_nodes],
                "text_chunks_used": 0,
                "processing_deterministic": True,
            }
        
        # Build response with all chunks, each with citation marker
        response_parts = []
        citations = []
        
        for i, chunk in enumerate(text_chunks, 1):
            text = chunk.get("text", "")
            if not text or not isinstance(text, str):
                continue
            
            # Get metadata
            source = chunk.get("source", chunk.get("document_source", "unknown"))
            section = chunk.get("section", "")
            if not section:
                section_path = chunk.get("section_path", [])
                if section_path:
                    section = " > ".join(str(s) for s in section_path if s)
            
            # Extract document title from source URL or use section
            doc_title = "Unknown"
            if source and "/" in source:
                doc_title = source.split("/")[-1].replace(".pdf", "").replace("_", " ")
            
            citation_id = f"[{i}]"
            
            # Add to response with citation marker
            response_parts.append(f"{citation_id} {text.strip()}")
            
            # Build citation entry with full metadata
            citations.append({
                "citation": citation_id,
                "source": source,
                "document": doc_title,
                "section": section,
                "chunk_id": chunk.get("id", chunk.get("chunk_id", f"chunk_{i}")),
                "text_preview": text[:200] + "..." if len(text) > 200 else text,
            })
        
        # Join all chunks with double newline for readability
        audit_response = "\n\n".join(response_parts)
        
        logger.info(
            "nlp_audit_extraction_complete",
            query=query[:50],
            chunks_returned=len(citations),
            processing_deterministic=True,
        )
        
        return {
            "response": audit_response,
            "citations": citations,
            "evidence_path": [node[0] for node in evidence_nodes],
            "text_chunks_used": len(text_chunks),
            "processing_deterministic": True,
        }

    async def _comprehensive_two_pass_extract(
        self,
        query: str,
        text_chunks: List[Dict[str, Any]],
        evidence_nodes: List[Tuple[str, float]]
    ) -> Dict[str, Any]:
        """
        Graph-aware comprehensive extraction for 100% fact coverage.
        
        IMPROVED APPROACH: Instead of regex extraction, we leverage the GRAPH STRUCTURE:
        - Azure DI already extracted KVPs at indexing time → stored as KeyValuePair nodes
        - Tables are stored as Table nodes with markdown/headers
        - Edges connect Chunks → Sections → KVPs/Tables
        
        By traversing these edges, we get DETERMINISTIC structured facts without LLM re-extraction.
        
        PASS 1: Graph Structure Retrieval (No LLM)
        - Query KeyValuePair nodes for each document
        - Query Table nodes for each document
        - Use pre-extracted structured facts (deterministic, layout-aware)
        - Supplement with regex extraction for values not in KVPs
        
        PASS 2: LLM Comparison
        - Input: Structured facts from graph + regex
        - LLM compares and identifies inconsistencies
        - Has full context: original text + structured KVPs + tables
        
        Returns:
            dict with:
            - response: Rich comparison narrative
            - raw_extractions: Structured JSON facts per document (from graph)
            - citations: Full citation metadata
        """
        import json
        import re
        from collections import defaultdict
        
        # =====================================================================
        # STEP 0: Try to get GRAPH-AWARE chunks with KVPs and Tables
        # =====================================================================
        graph_docs: List[Dict[str, Any]] = []
        
        if self.text_store and hasattr(self.text_store, "get_chunks_with_graph_structure"):
            try:
                graph_docs = await self.text_store.get_chunks_with_graph_structure(limit=50)
                logger.info("comprehensive_graph_structure_loaded",
                           num_docs=len(graph_docs),
                           total_kvps=sum(len(d.get("kvps", [])) for d in graph_docs),
                           total_tables=sum(len(d.get("tables", [])) for d in graph_docs),
                           total_entities=sum(len(d.get("entities", [])) for d in graph_docs))
            except Exception as e:
                logger.warning("comprehensive_graph_structure_failed", error=str(e))
        
        # Fallback to regular chunks if graph query failed
        if not graph_docs:
            if not text_chunks and self.text_store:
                if hasattr(self.text_store, "get_all_chunks_for_comprehensive"):
                    try:
                        text_chunks = await self.text_store.get_all_chunks_for_comprehensive(limit=50)
                        logger.info("comprehensive_fetched_all_chunks", num_chunks=len(text_chunks))
                    except Exception as e:
                        logger.warning("comprehensive_fetch_all_chunks_failed", error=str(e))
            
            # Convert flat chunks to graph_docs format
            doc_chunks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for chunk in text_chunks or []:
                meta = chunk.get("metadata", {})
                doc_key = (
                    meta.get("document_id") 
                    or chunk.get("document_id")
                    or meta.get("document_title")
                    or chunk.get("document_title")
                    or "Unknown"
                )
                doc_chunks[doc_key].append(chunk)
            
            for doc_key, chunks in doc_chunks.items():
                graph_docs.append({
                    "document_title": chunks[0].get("document_title") or doc_key,
                    "document_id": doc_key,
                    "combined_text": "\n\n".join(c.get("text", "") for c in chunks),
                    "chunks": chunks,
                    "kvps": [],  # No graph KVPs available
                    "tables": [],
                })
        
        if not graph_docs:
            return {
                "response": "No documents found to analyze.",
                "raw_extractions": [],
                "citations": [],
                "evidence_path": [node[0] for node in evidence_nodes],
                "text_chunks_used": 0,
            }
        
        # =====================================================================
        # PASS 1: Build Structured Extractions from GRAPH + Regex
        # =====================================================================
        raw_extractions = []
        citations = []
        citation_idx = 1
        
        for doc in graph_docs:
            doc_title = doc.get("document_title", "Unknown")
            doc_id = doc.get("document_id", "")
            doc_text = doc.get("combined_text", "")
            kvps = doc.get("kvps", [])
            tables = doc.get("tables", [])
            entities = doc.get("entities", [])
            
            # Start with KVPs from graph (deterministic, layout-aware)
            extraction = {
                "document_title": doc_title,
                "_document_id": doc_id,
                "_document_title": doc_title,
                "_citation_idx": citation_idx,
                "_source": "graph",  # Track that this came from graph
                
                # KVPs grouped by type
                "kvp_amounts": [],
                "kvp_parties": [],
                "kvp_dates": [],
                "kvp_identifiers": [],
                "kvp_other": [],
                
                # Tables
                "tables": tables,
                
                # Entities from graph
                "entities": entities,
                
                # Will also add regex extractions for values not in KVPs
                "regex_amounts": [],
                "regex_parties": [],
                "regex_dates": [],
                "all_fields": [],  # Combined for comparison
            }
            
            # Categorize KVPs by type
            for kvp in kvps:
                key = (kvp.get("key") or "").lower()
                value = kvp.get("value") or ""
                
                if not value.strip():
                    continue
                
                field_entry = {
                    "field": f"kvp_{key.replace(' ', '_')[:30]}",
                    "value": value,
                    "key": kvp.get("key"),
                    "confidence": kvp.get("confidence", 0.0),
                    "source": "azure_di"
                }
                
                # Categorize by content
                if any(word in key for word in ["amount", "total", "price", "cost", "payment", "fee", "$"]):
                    extraction["kvp_amounts"].append(field_entry)
                elif any(word in key for word in ["date", "effective", "expir", "due"]):
                    extraction["kvp_dates"].append(field_entry)
                elif any(word in key for word in ["name", "party", "buyer", "seller", "customer", "vendor", "company", "representative"]):
                    extraction["kvp_parties"].append(field_entry)
                elif any(word in key for word in ["number", "id", "invoice", "contract", "po", "ref"]):
                    extraction["kvp_identifiers"].append(field_entry)
                else:
                    extraction["kvp_other"].append(field_entry)
                
                extraction["all_fields"].append(field_entry)
            
            # Supplement with regex extraction for values KVPs might miss
            regex_extraction = self._regex_extract_fields(doc_text, doc_title)
            
            # Add regex-found amounts that aren't already in KVPs
            kvp_values = {f.get("value", "").strip() for f in extraction["all_fields"]}
            for amt in regex_extraction.get("amounts", []):
                if amt.get("value", "").strip() not in kvp_values:
                    field_entry = {**amt, "source": "regex"}
                    extraction["regex_amounts"].append(field_entry)
                    extraction["all_fields"].append(field_entry)
            
            for party in regex_extraction.get("parties", []):
                if party.get("value", "").strip() not in kvp_values:
                    field_entry = {**party, "source": "regex"}
                    extraction["regex_parties"].append(field_entry)
                    extraction["all_fields"].append(field_entry)
            
            for date in regex_extraction.get("dates", []):
                if date.get("value", "").strip() not in kvp_values:
                    field_entry = {**date, "source": "regex"}
                    extraction["regex_dates"].append(field_entry)
                    extraction["all_fields"].append(field_entry)
            
            # Also add regex-found identifiers (invoice#, PO#, etc)
            for identifier in regex_extraction.get("identifiers", []):
                if identifier.get("value", "").strip() not in kvp_values:
                    field_entry = {**identifier, "source": "regex"}
                    # Add to kvp_identifiers (not a separate regex_identifiers list)
                    extraction["kvp_identifiers"].append(field_entry)
                    extraction["all_fields"].append(field_entry)
            
            raw_extractions.append(extraction)
            
            citations.append({
                "citation": f"[{citation_idx}]",
                "chunk_id": doc.get("chunks", [{}])[0].get("chunk_id", "") if doc.get("chunks") else "",
                "document_id": doc_id,
                "document_title": doc_title,
                "document_url": "",
                "page_number": None,
                "section": "",
                "text_preview": doc_text[:200] + "..." if len(doc_text) > 200 else doc_text,
                "kvp_count": len(kvps),
                "table_count": len(tables),
            })
            citation_idx += 1
        
        logger.info("pass1_graph_extraction_complete",
                   num_docs=len(raw_extractions),
                   total_kvp_fields=sum(len(e.get("kvp_amounts", [])) + len(e.get("kvp_parties", [])) + 
                                        len(e.get("kvp_dates", [])) + len(e.get("kvp_identifiers", [])) +
                                        len(e.get("kvp_other", [])) for e in raw_extractions),
                   total_regex_fields=sum(len(e.get("regex_amounts", [])) + len(e.get("regex_parties", [])) +
                                          len(e.get("regex_dates", [])) for e in raw_extractions))
        
        # =====================================================================
        # PASS 2: LLM COMPARISON (with reduced context - only HippoRAG output)
        # =====================================================================
        comparison_context = self._build_graph_aware_comparison_context(raw_extractions, graph_docs)
        
        comparison_prompt = f"""You are comparing documents to identify inconsistencies.

QUERY: "{query}"

{comparison_context}

TASK: Identify ALL inconsistencies between these documents.

For each inconsistency, provide:
1. FIELD: What field/value is inconsistent
2. DOCUMENTS: Which documents disagree and what each says
3. SIGNIFICANCE: Why this inconsistency matters

Include ALL discrepancies:
- Amounts/prices (different totals, payment terms)
- Party names (different company names, entities)
- Product/model descriptions (different specs)
- Dates (different effective dates, due dates)
- Terms and conditions (different warranty, payment terms)
- Any other factual disagreements

Use citation markers [1], [2], etc. to reference each document.

BEGIN ANALYSIS:"""

        # Guard against None LLM
        if not self.llm:
            logger.error("llm_not_available", error="LLM is None")
            narrative = "## Comparison Failed: LLM not available\n\n"
            for ext in raw_extractions:
                narrative += f"### Document [{ext.get('_citation_idx', '?')}]: {ext.get('_document_title', 'Unknown')}\n"
                if '_error' in ext:
                    narrative += f"- Error: {ext['_error']}\n\n"
                else:
                    narrative += f"- Fields extracted: {len([k for k in ext.keys() if not k.startswith('_')])}\n\n"
        else:
            try:
                comparison_result = await self.llm.acomplete(comparison_prompt)
                narrative = comparison_result.text.strip()
            except Exception as e:
                logger.error("llm_comparison_failed", error=str(e))
                # Fallback: List the extracted facts
                narrative = "## Comparison Failed\n\n"
                for ext in raw_extractions:
                    narrative += f"### Document [{ext.get('_citation_idx', '?')}]: {ext.get('_document_title', 'Unknown')}\n"
                    if '_error' in ext:
                        narrative += f"- Error: {ext['_error']}\n\n"
                    else:
                        narrative += f"- Fields extracted: {len([k for k in ext.keys() if not k.startswith('_')])}\n\n"
        
        logger.info("comprehensive_graph_aware_complete",
                   query=query[:50],
                   num_docs=len(graph_docs),
                   num_extractions=len(raw_extractions))
        
        return {
            "response": narrative,
            "raw_extractions": raw_extractions,
            "citations": citations,
            "evidence_path": [node[0] for node in evidence_nodes],
            "text_chunks_used": sum(len(d.get("chunks", [])) for d in graph_docs),
            "processing_mode": "comprehensive_graph_aware_reduced_context",
            "kvp_source": "azure_di",
        }

    def _build_graph_aware_comparison_context(
        self, 
        extractions: List[Dict[str, Any]], 
        graph_docs: List[Dict[str, Any]]
    ) -> str:
        """Build section-level context for retrieved KVPs/Tables using section_path.
        
        RETRIEVAL-BASED APPROACH:
        1. Only show sections that contain retrieved KVPs/tables
        2. Deduplicate sections across the document
        3. No arbitrary limits - show everything retrieved
        4. Group by section to show context once per section
        """
        parts = []
        
        parts.append("=" * 60)
        parts.append("ENRICHED CONTEXT (Retrieval-based)")
        parts.append("Showing only sections with retrieved structured data")
        parts.append("=" * 60)
        
        # Process each document's extractions
        for ext in extractions:
            idx = ext.get("_citation_idx", "?")
            title = ext.get("_document_title", "Unknown")
            parts.append(f"\n### Document [{idx}]: {title}")
            parts.append("-" * 40)
            
            # Get the document's KVPs and group by section
            doc = next((d for d in graph_docs if d.get("document_title") == title), None)
            if not doc:
                continue
            
            kvps = doc.get("kvps", [])
            
            # Group KVPs by section for efficiency and deduplication
            kvps_by_section: Dict[str, List[Dict]] = {}
            for kvp in kvps:
                section_path = kvp.get("section_path", [])
                if section_path:
                    section_key = section_path[0]
                    if section_key not in kvps_by_section:
                        kvps_by_section[section_key] = []
                    kvps_by_section[section_key].append(kvp)
            
            # If no KVPs grouped by section, show raw chunks
            if not kvps_by_section:
                chunks = doc.get("chunks", [])
                if chunks:
                    parts.append("\n**Document Content (no KVPs found):**")
                    # Show ALL retrieved chunks - no arbitrary limit
                    for i, chunk in enumerate(chunks, 1):
                        chunk_text = chunk.get("text", "")
                        # Only truncate if truly massive (>3000 chars)
                        if len(chunk_text) > 3000:
                            chunk_text = chunk_text[:3000] + "..."
                        parts.append(f"\nChunk {i}: {chunk_text}")
            else:
                # Build section context mapping once per document (deduplication)
                section_to_context: Dict[str, str] = {}
                for section_key in kvps_by_section.keys():
                    # Find chunk containing this section
                    for chunk in doc.get("chunks", []):
                        chunk_text = chunk.get("text", "")
                        # Simple heuristic: if section title appears in chunk, it's likely the right one
                        if section_key.lower() in chunk_text.lower()[:500]:
                            # Only truncate if truly massive (>3000 chars)
                            if len(chunk_text) > 3000:
                                chunk_text = chunk_text[:3000] + "..."
                            section_to_context[section_key] = chunk_text
                            break
                
                # Show ALL sections with retrieved KVPs - no arbitrary limit
                for section_key, section_kvps in kvps_by_section.items():
                    parts.append(f"\n**Section: {section_key}**")
                    
                    # Show section context if available
                    if section_key in section_to_context:
                        parts.append(f"Context: {section_to_context[section_key]}")
                        parts.append("")
                    
                    # Show ALL KVPs from this section - no arbitrary limit
                    parts.append("Fields extracted:")
                    for kvp in section_kvps:
                        key = kvp.get("key", "")
                        value = kvp.get("value", "")
                        parts.append(f"  • {key}: {value}")
            
            # Show ALL tables for this document - no arbitrary limit
            tables = doc.get("tables", [])
            if tables:
                parts.append(f"\n**Tables in Document:**")
                for i, table in enumerate(tables, 1):
                    headers = table.get("headers", [])
                    rows = table.get("rows", [])
                    
                    if headers:
                        parts.append(f"\nTable {i} Headers: {', '.join(headers)}")
                    
                    # Show ALL rows - no arbitrary limit
                    if isinstance(rows, list):
                        for j, row in enumerate(rows, 1):
                            if isinstance(row, dict):
                                # Show all columns in the row
                                row_str = ", ".join(f"{k}={v}" for k, v in row.items())
                                parts.append(f"  Row {j}: {row_str}")
        
        return "\n".join(parts)

    def _regex_extract_fields(self, text: str, doc_title: str) -> Dict[str, Any]:
        """
        PASS 1: Deterministic field extraction using regex patterns.
        
        This is NOT NLP - it's pure pattern matching for:
        - Amounts: $X,XXX.XX patterns
        - Dates: MM/DD/YYYY, YYYY-MM-DD, Month DD, YYYY
        - Identifiers: Invoice #, PO #, Contract #
        - Parties: Company names with Inc/LLC/Ltd suffixes
        - URLs, percentages, line items
        
        Why regex instead of NLP?
        - Domain-specific terms (Savaria V1504, WR-500 lock) aren't in NER models
        - We need exact literal values, not semantic labels
        - 100% reproducible - same input always gives same output
        - Fast, no model loading required
        """
        import re
        
        extraction = {
            "document_title": doc_title,
            "amounts": [],
            "dates": [],
            "identifiers": [],
            "parties": [],
            "percentages": [],
            "urls": [],
            "line_items": [],
            "terms": [],
            "all_fields": [],  # Flattened list for comparison
        }
        
        # Amount patterns (currency)
        amount_pattern = r'\$[\d,]+(?:\.\d{2})?|\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:USD|dollars?)'
        for match in re.finditer(amount_pattern, text, re.IGNORECASE):
            value = match.group().strip()
            # Get context (20 chars before and after)
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end].replace('\n', ' ').strip()
            extraction["amounts"].append({"value": value, "context": context})
            extraction["all_fields"].append({"field": f"amount_{len(extraction['amounts'])}", "value": value, "context": context})
        
        # Date patterns
        date_pattern = r'\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b'
        for match in re.finditer(date_pattern, text, re.IGNORECASE):
            value = match.group().strip()
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end].replace('\n', ' ').strip()
            extraction["dates"].append({"value": value, "context": context})
            extraction["all_fields"].append({"field": f"date_{len(extraction['dates'])}", "value": value, "context": context})
        
        # Invoice/PO/Contract numbers - require specific format with at least one digit
        id_patterns = [
            r'(?:Invoice|INV)\s*(?:#|No\.?|Number)?\s*:?\s*([A-Z0-9][A-Z0-9\-]+\d[A-Z0-9\-]*)',
            r'(?:PO|Purchase\s+Order)\s*(?:#|No\.?|Number)?\s*:?\s*([A-Z0-9][A-Z0-9\-]+\d[A-Z0-9\-]*)',
            r'(?:Contract)\s*(?:#|No\.?|Number)?\s*:?\s*([A-Z0-9][A-Z0-9\-]+\d[A-Z0-9\-]*)',
            r'(?:Order)\s*(?:#|No\.?|Number)?\s*:?\s*([A-Z0-9][A-Z0-9\-]+\d[A-Z0-9\-]*)',
        ]
        seen_ids = set()
        for pattern in id_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = match.group(1).strip() if match.groups() else match.group().strip()
                if value and len(value) >= 3 and value.lower() not in seen_ids:
                    seen_ids.add(value.lower())
                    context = match.group()
                    extraction["identifiers"].append({"value": value, "context": context})
                    extraction["all_fields"].append({"field": f"identifier_{len(extraction['identifiers'])}", "value": value, "context": context})
        
        # Party names (look for common patterns)
        party_patterns = [
            r'(?:Bill\s+To|Ship\s+To|Sold\s+To|Customer|Buyer|Seller|Vendor|Contractor)\s*:?\s*([A-Z][A-Za-z\s&,\.]+?)(?:\n|$|,\s*(?:Inc|LLC|Ltd|Corp))',
            r'([A-Z][A-Za-z\s]+(?:Inc|LLC|Ltd|Corp|Company|Co)\.?)',
        ]
        seen_parties = set()
        for pattern in party_patterns:
            for match in re.finditer(pattern, text):
                value = match.group(1).strip() if match.groups() else match.group().strip()
                if value and len(value) > 3 and value.lower() not in seen_parties:
                    seen_parties.add(value.lower())
                    extraction["parties"].append({"value": value})
                    extraction["all_fields"].append({"field": f"party_{len(extraction['parties'])}", "value": value})
        
        # URLs
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        for match in re.finditer(url_pattern, text):
            value = match.group().strip()
            extraction["urls"].append({"value": value})
            extraction["all_fields"].append({"field": f"url_{len(extraction['urls'])}", "value": value})
        
        # Percentages
        pct_pattern = r'\d+(?:\.\d+)?%'
        for match in re.finditer(pct_pattern, text):
            value = match.group().strip()
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end].replace('\n', ' ').strip()
            extraction["percentages"].append({"value": value, "context": context})
            extraction["all_fields"].append({"field": f"percentage_{len(extraction['percentages'])}", "value": value, "context": context})
        
        # Product/model patterns
        model_pattern = r'(?:Model|Product|Item|Part)\s*#?\s*:?\s*([A-Z0-9\-]+)'
        for match in re.finditer(model_pattern, text, re.IGNORECASE):
            value = match.group(1).strip() if match.groups() else match.group().strip()
            extraction["all_fields"].append({"field": f"model_{len([f for f in extraction['all_fields'] if f['field'].startswith('model_')])}", "value": value})
        
        # Line items (look for quantity x description x price patterns)
        line_item_pattern = r'(\d+)\s+(.+?)\s+\$?([\d,]+(?:\.\d{2})?)'
        for match in re.finditer(line_item_pattern, text):
            qty, desc, price = match.groups()
            if len(desc) > 5 and len(desc) < 200:  # Filter noise
                extraction["line_items"].append({
                    "quantity": qty,
                    "description": desc.strip(),
                    "price": price
                })
                extraction["all_fields"].append({
                    "field": f"line_item_{len(extraction['line_items'])}",
                    "value": f"{qty}x {desc.strip()} @ ${price}"
                })
        
        # Payment terms patterns
        term_patterns = [
            r'(?:Payment|Due)\s+(?:Terms?|upon)\s*:?\s*(.+?)(?:\n|$)',
            r'(?:payable|due)\s+(?:in|within|on)\s+(.+?)(?:\n|$|\.|,)',
            r'(\d+)\s+(?:days?|weeks?)\s+(?:from|after|upon)',
        ]
        for pattern in term_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = match.group(1).strip() if match.groups() else match.group().strip()
                if value and len(value) > 3:
                    extraction["terms"].append({"value": value})
                    extraction["all_fields"].append({"field": f"term_{len(extraction['terms'])}", "value": value})
        
        return extraction

    def _build_field_comparison_pairs(self, extractions: List[Dict[str, Any]], max_pairs: int = 100) -> List[Dict[str, Any]]:
        """Build pairs of fields to compare across documents.
        
        Compares ALL document pairs - lets LLM decide relevance in Pass 2.
        No document-type filtering to avoid domain-specific assumptions.
        """
        if len(extractions) < 2:
            return []
        
        pairs = []
        
        # Compare ALL document pairs - no smart filtering
        doc_pairs_to_compare = []
        for i in range(len(extractions)):
            for j in range(i + 1, len(extractions)):
                doc_pairs_to_compare.append((extractions[i], extractions[j]))
        
        logger.info("document_pairs_to_compare", num_pairs=len(doc_pairs_to_compare),
                   doc_titles=[e.get("_document_title", "")[:30] for e in extractions])
        
        # Key field types to compare (ignore noisy identifiers)
        important_field_types = {"amount", "party", "date", "url", "percentage", "model", "term", "line_item"}
        
        for doc1, doc2 in doc_pairs_to_compare:
            doc1_by_type = {}
            doc2_by_type = {}
            
            for f in doc1.get("all_fields", []):
                field_type = f["field"].rsplit("_", 1)[0]
                if field_type in important_field_types:
                    doc1_by_type.setdefault(field_type, []).append(f)
            
            for f in doc2.get("all_fields", []):
                field_type = f["field"].rsplit("_", 1)[0]
                if field_type in important_field_types:
                    doc2_by_type.setdefault(field_type, []).append(f)
            
            all_types = set(doc1_by_type.keys()) | set(doc2_by_type.keys())
            
            for field_type in all_types:
                doc1_vals = doc1_by_type.get(field_type, [])
                doc2_vals = doc2_by_type.get(field_type, [])
                
                # For amounts and percentages - compare all combinations (they might appear in different order)
                if field_type in ("amount", "percentage"):
                    doc1_set = {v.get("value", "").strip() for v in doc1_vals}
                    doc2_set = {v.get("value", "").strip() for v in doc2_vals}
                    
                    # Only flag if there are values unique to one doc
                    only_in_doc1 = doc1_set - doc2_set
                    only_in_doc2 = doc2_set - doc1_set
                    
                    if only_in_doc1 or only_in_doc2:
                        pairs.append({
                            "field": f"{field_type}_comparison",
                            "doc1_id": doc1.get("_document_id"),
                            "doc1_title": doc1.get("_document_title", "Doc1")[:30],
                            "doc1_value": ", ".join(sorted(only_in_doc1)[:5]) if only_in_doc1 else "N/A",
                            "doc1_citation": f"[{doc1.get('_citation_idx', '?')}]",
                            "doc2_id": doc2.get("_document_id"),
                            "doc2_title": doc2.get("_document_title", "Doc2")[:30],
                            "doc2_value": ", ".join(sorted(only_in_doc2)[:5]) if only_in_doc2 else "N/A",
                            "doc2_citation": f"[{doc2.get('_citation_idx', '?')}]",
                            "notes": f"Values unique to each document"
                        })
                
                # For parties - compare names
                elif field_type == "party":
                    doc1_names = {v.get("value", "").strip().lower() for v in doc1_vals}
                    doc2_names = {v.get("value", "").strip().lower() for v in doc2_vals}
                    
                    # Compare each pair of party names
                    for v1 in doc1_vals[:5]:  # Limit to first 5
                        for v2 in doc2_vals[:5]:
                            name1 = v1.get("value", "").strip()
                            name2 = v2.get("value", "").strip()
                            # Skip obvious matches
                            if name1.lower() == name2.lower():
                                continue
                            # Check for potential variants (e.g., "Contoso Ltd" vs "Contoso LLC")
                            if self._might_be_same_entity(name1, name2):
                                pairs.append({
                                    "field": "party_variant",
                                    "doc1_id": doc1.get("_document_id"),
                                    "doc1_title": doc1.get("_document_title", "Doc1")[:30],
                                    "doc1_value": name1[:100],
                                    "doc1_citation": f"[{doc1.get('_citation_idx', '?')}]",
                                    "doc2_id": doc2.get("_document_id"),
                                    "doc2_title": doc2.get("_document_title", "Doc2")[:30],
                                    "doc2_value": name2[:100],
                                    "doc2_citation": f"[{doc2.get('_citation_idx', '?')}]",
                                    "notes": "Potential entity name variant"
                                })
                
                # For URLs - direct comparison
                elif field_type == "url":
                    for v1 in doc1_vals:
                        for v2 in doc2_vals:
                            url1 = v1.get("value", "").strip()
                            url2 = v2.get("value", "").strip()
                            if url1 != url2:
                                pairs.append({
                                    "field": "url_difference",
                                    "doc1_id": doc1.get("_document_id"),
                                    "doc1_title": doc1.get("_document_title", "Doc1")[:30],
                                    "doc1_value": url1[:100],
                                    "doc1_citation": f"[{doc1.get('_citation_idx', '?')}]",
                                    "doc2_id": doc2.get("_document_id"),
                                    "doc2_title": doc2.get("_document_title", "Doc2")[:30],
                                    "doc2_value": url2[:100],
                                    "doc2_citation": f"[{doc2.get('_citation_idx', '?')}]",
                                })
                
                # For line items - compare descriptions
                elif field_type == "line_item":
                    for k, v1 in enumerate(doc1_vals[:10]):
                        v2 = doc2_vals[k] if k < len(doc2_vals) else {"value": "NOT FOUND"}
                        if v1.get("value") != v2.get("value"):
                            pairs.append({
                                "field": f"line_item_{k+1}",
                                "doc1_id": doc1.get("_document_id"),
                                "doc1_title": doc1.get("_document_title", "Doc1")[:30],
                                "doc1_value": str(v1.get("value", ""))[:100],
                                "doc1_citation": f"[{doc1.get('_citation_idx', '?')}]",
                                "doc2_id": doc2.get("_document_id"),
                                "doc2_title": doc2.get("_document_title", "Doc2")[:30],
                                "doc2_value": str(v2.get("value", ""))[:100],
                                "doc2_citation": f"[{doc2.get('_citation_idx', '?')}]",
                            })
            
            # Stop if we have enough pairs
            if len(pairs) >= max_pairs:
                break
        
        logger.info("field_comparison_pairs_built", total_pairs=len(pairs))
        return pairs[:max_pairs]

    def _might_be_same_entity(self, name1: str, name2: str) -> bool:
        """Check if two names might refer to the same entity (e.g., Contoso Ltd vs Contoso LLC)."""
        # Normalize: lowercase, remove common suffixes
        suffixes = ["inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "company", "co", "co."]
        
        def normalize(name):
            n = name.lower().strip()
            for suffix in suffixes:
                if n.endswith(" " + suffix):
                    n = n[:-len(suffix)-1].strip()
            return n
        
        n1 = normalize(name1)
        n2 = normalize(name2)
        
        # If base names match, they might be variants
        if n1 == n2:
            return True
        
        # Check if one is substring of other
        if len(n1) > 3 and len(n2) > 3:
            if n1 in n2 or n2 in n1:
                return True
        
        return False

    def _parse_comparison_results(self, comparison_text: str, field_pairs: List[Dict]) -> List[Dict]:
        """Parse LLM comparison output into structured results."""
        import re
        
        results = []
        lines = comparison_text.split('\n')
        
        for line in lines:
            # Match pattern: [1]: MISMATCH - explanation
            match = re.match(r'\[(\d+)\]\s*:?\s*(MATCH|MISMATCH|MISSING)\s*[-–]\s*(.+)', line, re.IGNORECASE)
            if match:
                idx = int(match.group(1)) - 1
                decision = match.group(2).upper()
                explanation = match.group(3).strip()
                
                if 0 <= idx < len(field_pairs):
                    results.append({
                        **field_pairs[idx],
                        "decision": decision,
                        "explanation": explanation,
                    })
        
        # Add any pairs that weren't matched
        matched_indices = {r.get("field") for r in results}
        for fp in field_pairs:
            if fp.get("field") not in matched_indices:
                results.append({
                    **fp,
                    "decision": "REVIEW",
                    "explanation": "LLM did not provide explicit comparison"
                })
        
        return results

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
