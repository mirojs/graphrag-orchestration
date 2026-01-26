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

from app.hybrid_v2.services.extraction_service import ExtractionService
from app.hybrid_v2.pipeline.enhanced_graph_retriever import EnhancedGraphContext

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
        
        # Step 2: Build context with citations (now groups by document for better reasoning)
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
                
                citation_map[citation_id] = {
                    "source": source,
                    "chunk_id": chunk.get("id", f"chunk_{original_idx}"),
                    "document": doc_title,
                    "document_id": document_id,  # Graph node ID for citation attribution
                    "document_title": doc_title,  # Explicit title for Route 2/3 citation format
                    "section": section_str,
                    "text_preview": text[:100] + "..." if len(text) > 100 else text
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
