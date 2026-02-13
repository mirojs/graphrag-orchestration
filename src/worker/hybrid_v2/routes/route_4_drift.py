"""Route 4: DRIFT Multi-Hop - Iterative reasoning for complex queries.

Best for ambiguous or multi-hop queries:
- "Analyze risk exposure across subsidiaries"
- "How are we connected through third parties?"
- "Compare timeframes across all documents"

This route uses DRIFT-style iterative reasoning:
1. Query decomposition into sub-questions
2. Iterative entity discovery per sub-question
3. Consolidated HippoRAG PPR tracing
4. Confidence check with optional re-decomposition
5. Coverage gap fill for corpus-level queries
6. Multi-source synthesis

Features:
- Agentic confidence loop (detects sparse subgraphs)
- Entity concentration detection
- Section-based exhaustive coverage for "list all" queries
- Date metadata query fast-path

Performance Mode:
- ROUTE4_WORKFLOW=1: LlamaIndex Workflow with parallel sub-questions (~700ms)
- ROUTE4_WORKFLOW=0 (default): Sequential sub-questions (~2.1s for 3 questions)
"""

import os
from typing import Dict, Any, List, Tuple, Optional, List

import structlog

from .base import BaseRouteHandler, RouteResult, Citation

logger = structlog.get_logger(__name__)


def _get_query_embedding(query: str) -> List[float]:
    """Get embedding for a query string (uses V2 Voyage if enabled)."""
    # Lazy import to avoid circular dependency
    from ..orchestrator import get_query_embedding
    return get_query_embedding(query)

# Feature flag: use PPR instead of semantic beam for graph traversal (A/B testing)
ROUTE4_USE_PPR = os.getenv("ROUTE4_USE_PPR", "0").strip().lower() in {"1", "true", "yes"}
if ROUTE4_USE_PPR:
    logger.info("route4_using_ppr_mode")

# Feature flag for LlamaIndex Workflow mode
ROUTE4_WORKFLOW = os.getenv("ROUTE4_WORKFLOW", "0").strip().lower() in {"1", "true", "yes"}
if ROUTE4_WORKFLOW:
    try:
        from ..workflows import DRIFTWorkflow
        logger.info("drift_handler_workflow_enabled")
    except ImportError as e:
        logger.warning("drift_handler_workflow_import_failed", error=str(e))
        ROUTE4_WORKFLOW = False


class DRIFTHandler(BaseRouteHandler):
    """Route 4: DRIFT-style iterative multi-hop reasoning."""

    ROUTE_NAME = "route_4_drift_multi_hop"

    async def execute(
        self,
        query: str,
        response_type: str = "summary",
        knn_config: Optional[str] = None,
        prompt_variant: Optional[str] = None,
        synthesis_model: Optional[str] = None,
        include_context: bool = False,
    ) -> RouteResult:
        """
        Execute Route 4: DRIFT for complex multi-hop queries.
        
        Stages:
        - 4.0: Check for deterministic date metadata queries (fast-path)
        - 4.1: Query decomposition (DRIFT-style)
        - 4.2: Iterative entity discovery
        - 4.3: Consolidated HippoRAG PPR tracing
        - 4.3.5: Confidence check + optional re-decomposition
        - 4.3.6: Coverage gap fill for corpus-level queries
        - 4.4: Multi-source synthesis
        
        Performance Mode:
        - ROUTE4_WORKFLOW=1: LlamaIndex Workflow with parallel sub-questions
        - ROUTE4_WORKFLOW=0 (default): Sequential sub-questions
        
        Args:
            query: The user's natural language query
            response_type: Response format ("summary", "detailed_report", etc.)
            knn_config: Optional KNN configuration for SEMANTICALLY_SIMILAR edge filtering.
            
        Returns:
            RouteResult with response, citations, and metadata
        """
        # Store knn_config for use in tracing
        self._knn_config = knn_config
        self._prompt_variant = prompt_variant
        self._synthesis_model = synthesis_model
        
        # ==================================================================
        # WORKFLOW MODE: Use LlamaIndex Workflow for parallel sub-questions
        # ==================================================================
        if ROUTE4_WORKFLOW:
            logger.info("route_4_drift_workflow_mode", query=query[:50])
            workflow = DRIFTWorkflow(
                pipeline=self.pipeline,
                timeout=120,
                max_redecompose_attempts=1,
            )
            # Run workflow - returns dict result
            from llama_index.core.workflow import StartEvent
            start_event = StartEvent(query=query, response_type=response_type)
            result = await workflow.run(start_event=start_event)
            
            # Convert dict result to RouteResult
            # Map synthesizer citation format to Citation class format
            citations = []
            for i, c in enumerate(result.get("citations", [])):
                # Extract metadata for enhanced citations
                meta = c.get("metadata") or {}
                section_path = meta.get("section_path") or meta.get("section_path_key") or c.get("section_path", "")
                if isinstance(section_path, list):
                    section_path = " > ".join(str(s) for s in section_path if s)
                citations.append(Citation(
                    index=c.get("index", i + 1),
                    chunk_id=c.get("chunk_id", ""),
                    document_id=c.get("document_id", c.get("source", "")),
                    document_title=c.get("document_title", c.get("document", "")),
                    document_url=c.get("document_url", "") or c.get("document_source", "") or meta.get("url", ""),
                    page_number=c.get("page_number") or meta.get("page_number"),
                    section_path=section_path,
                    start_offset=c.get("start_offset") or meta.get("start_offset"),
                    end_offset=c.get("end_offset") or meta.get("end_offset"),
                    score=c.get("score", 0.0),
                    text_preview=c.get("text_preview", ""),
                    # Sentence-level citation data (comprehensive_sentence mode)
                    sentences=c.get("sentences"),
                    page_dimensions=c.get("page_dimensions"),
                ))
            
            return RouteResult(
                response=result.get("response", ""),
                citations=citations,
                route_used=self.ROUTE_NAME,
                evidence_path=result.get("evidence_path", []),
                metadata={
                    **result.get("metadata", {}),
                    "workflow_mode": True,
                }
            )
        
        # ==================================================================
        # SEQUENTIAL MODE (default): Original implementation
        # ==================================================================
        logger.info("route_4_drift_start", query=query[:50], response_type=response_type)
        
        # Stage 4.0: Check for deterministic document metadata queries
        date_result = await self._check_date_metadata_query(query)
        if date_result:
            return date_result
        
        # Stage 4.1: Query Decomposition
        logger.info("stage_4.1_query_decomposition")
        sub_questions = await self._drift_decompose(query)
        logger.info("stage_4.1_complete", num_sub_questions=len(sub_questions))
        
        # Stage 4.2: Iterative Entity Discovery
        logger.info("stage_4.2_iterative_discovery")
        all_seeds, intermediate_results = await self._execute_discovery_pass(sub_questions)
        logger.info("stage_4.2_complete", 
                   total_seeds=len(all_seeds),
                   num_results=len(intermediate_results))
        
        # Stage 4.3: Consolidated HippoRAG Tracing (PPR or Semantic Beam)
        retrieval_mode = "ppr" if ROUTE4_USE_PPR else "beam"
        logger.info("stage_4.3_consolidated_tracing", mode=retrieval_mode, knn_config=knn_config)
        if ROUTE4_USE_PPR:
            complete_evidence = await self.pipeline.tracer.trace(
                query=query,
                seed_entities=all_seeds,
                top_k=30,
            )
        else:
            query_embedding = _get_query_embedding(query)
            complete_evidence = await self.pipeline.tracer.trace_semantic_beam(
                query=query,
                query_embedding=query_embedding,
                seed_entities=all_seeds,
                max_hops=3,
                beam_width=30,
                knn_config=knn_config,
            )
        logger.info("stage_4.3_complete", mode=retrieval_mode, num_evidence=len(complete_evidence))
        
        # Stage 4.3.5: Confidence Check + Re-decomposition
        confidence_metrics = self._compute_subgraph_confidence(
            sub_questions, intermediate_results, complete_evidence
        )
        confidence = confidence_metrics["score"]
        confidence_loop_triggered = False
        refined_sub_questions: List[str] = []
        
        logger.info("stage_4.3.5_confidence_check",
                   confidence_score=confidence,
                   satisfied_ratio=confidence_metrics["satisfied_ratio"],
                   entity_diversity=confidence_metrics["entity_diversity"],
                   thin_questions=len(confidence_metrics["thin_questions"]))
        
        # Trigger confidence loop if needed
        should_trigger = (
            (confidence < 0.5 and len(sub_questions) > 1) or
            (confidence_metrics["entity_diversity"] < 0.3 and len(sub_questions) > 2) or
            (len(confidence_metrics["concentrated_entities"]) > 0 and confidence < 0.7)
        )
        
        if should_trigger:
            confidence_loop_triggered = True
            thin_questions = confidence_metrics["thin_questions"]
            concentrated = confidence_metrics["concentrated_entities"]
            
            # Build context from successful sub-questions
            context_summary = "; ".join([
                f"{r['question']}: found {r.get('evidence_count', 0)} evidence"
                for r in intermediate_results if r.get("evidence_count", 0) >= 2
            ][:3])
            
            # Choose re-decomposition strategy
            if concentrated and not thin_questions:
                # Entity concentration - consolidate
                refinement_prompt = (
                    f"The entity '{concentrated[0]}' appears across many parts of the query. "
                    f"Context found: {context_summary}. "
                    f"Please generate 2-3 focused questions that consolidate information about "
                    f"'{concentrated[0]}' without counting separate document sections as distinct occurrences. "
                    f"Focus on: What distinct roles/appearances does this entity have across the corpus?"
                )
            elif thin_questions:
                # Sparse evidence - original re-decomposition
                refinement_prompt = (
                    f"Based on what we found ({context_summary}), "
                    f"please clarify these unknowns: {'; '.join(thin_questions)}"
                )
            else:
                refinement_prompt = None
            
            if refinement_prompt:
                refined_sub_questions = await self._drift_decompose(refinement_prompt)
                
                # Second pass discovery
                if refined_sub_questions:
                    additional_seeds, additional_results = await self._execute_discovery_pass(
                        refined_sub_questions
                    )
                    
                    all_seeds = list(set(all_seeds + additional_seeds))
                    intermediate_results.extend(additional_results)
                    
                    # Re-run tracing with expanded seeds (PPR or beam)
                    if additional_seeds:
                        if ROUTE4_USE_PPR:
                            additional_evidence = await self.pipeline.tracer.trace(
                                query=query,
                                seed_entities=additional_seeds,
                                top_k=15,
                            )
                        else:
                            additional_evidence = await self.pipeline.tracer.trace_semantic_beam(
                                query=query,
                                query_embedding=query_embedding,  # Reuse from Stage 4.3
                                seed_entities=additional_seeds,
                                max_hops=2,  # Shorter for refinement pass
                                beam_width=15,
                                knn_config=knn_config,
                            )
                        
                        # Deduplicate
                        existing_ids = {self._extract_evidence_id(e) for e in complete_evidence}
                        for ev in additional_evidence:
                            ev_id = self._extract_evidence_id(ev)
                            if ev_id and ev_id not in existing_ids:
                                complete_evidence.append(ev)
                                existing_ids.add(ev_id)
                    
                    logger.info("stage_4.3.5_complete",
                               additional_seeds=len(additional_seeds),
                               total_evidence=len(complete_evidence))
        
        # Stage 4.3.6: Coverage Gap Fill
        coverage_chunks, coverage_metadata = await self._apply_coverage_gap_fill(
            query, complete_evidence
        )
        
        # Stage 4.4: Multi-Source Synthesis
        logger.info("stage_4.4_synthesis")
        synthesis_result = await self.pipeline.synthesizer.synthesize(
            query=query,
            evidence_nodes=complete_evidence,
            response_type=response_type,
            sub_questions=sub_questions + refined_sub_questions,
            intermediate_context=intermediate_results,
            coverage_chunks=coverage_chunks if coverage_chunks else None,
            prompt_variant=prompt_variant,
            synthesis_model=synthesis_model,
            include_context=include_context,
        )
        logger.info("stage_4.4_complete")
        
        # Build citations
        citations = []
        for i, c in enumerate(synthesis_result.get("citations", []), 1):
            if isinstance(c, dict):
                # Extract metadata for enhanced citations
                meta = c.get("metadata") or {}
                section_path = meta.get("section_path") or meta.get("section_path_key") or c.get("section_path", "")
                if isinstance(section_path, list):
                    section_path = " > ".join(str(s) for s in section_path if s)
                citations.append(Citation(
                    index=i,
                    chunk_id=c.get("chunk_id", f"chunk_{i}"),
                    document_id=c.get("document_id", ""),
                    document_title=c.get("document_title", c.get("document", "Unknown")),
                    document_url=c.get("document_url", "") or c.get("document_source", "") or meta.get("url", ""),
                    page_number=c.get("page_number") or meta.get("page_number"),
                    section_path=section_path,
                    start_offset=c.get("start_offset") or meta.get("start_offset"),
                    end_offset=c.get("end_offset") or meta.get("end_offset"),
                    score=c.get("score", 0.0),
                    text_preview=c.get("text_preview", c.get("text", ""))[:200],
                    # Sentence-level citation data (comprehensive_sentence mode)
                    sentences=c.get("sentences"),
                    page_dimensions=c.get("page_dimensions"),
                ))
        
        return RouteResult(
            response=synthesis_result["response"],
            route_used=self.ROUTE_NAME,
            citations=citations,
            evidence_path=synthesis_result.get("evidence_path", []),
            metadata={
                "sub_questions": sub_questions,
                "refined_sub_questions": refined_sub_questions if confidence_loop_triggered else [],
                "confidence_score": confidence,
                "confidence_loop_triggered": confidence_loop_triggered,
                "all_seeds_discovered": all_seeds,
                "intermediate_results": intermediate_results,
                "num_evidence_nodes": len(complete_evidence),
                "text_chunks_used": synthesis_result.get("text_chunks_used", 0),
                "latency_estimate": "thorough",
                "precision_level": "maximum",
                "route_description": "DRIFT iterative multi-hop with confidence loop",
                **({"coverage_retrieval": coverage_metadata} if coverage_metadata else {}),
                **({"context_stats": synthesis_result["context_stats"]} if synthesis_result.get("context_stats") else {}),
                # Pass through raw_extractions from comprehensive mode (2-pass extraction)
                **({"raw_extractions": synthesis_result["raw_extractions"]} if synthesis_result.get("raw_extractions") else {}),
                **({"processing_mode": synthesis_result["processing_mode"]} if synthesis_result.get("processing_mode") else {}),
                **({"llm_context": synthesis_result["llm_context"]} if synthesis_result.get("llm_context") else {}),
            }
        )

    # ==========================================================================
    # DATE METADATA FAST-PATH
    # ==========================================================================
    
    async def _check_date_metadata_query(self, query: str) -> Optional[RouteResult]:
        """Check for deterministic document date queries and answer directly."""
        if not self.pipeline.enhanced_retriever:
            return None
        
        from src.worker.hybrid_v2.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
        date_query_type = EnhancedGraphRetriever.detect_date_metadata_query(query)
        
        if not date_query_type:
            return None
        
        logger.info("stage_4.0_date_metadata_query_detected", query_type=date_query_type)
        
        order = "desc" if date_query_type == "latest" else "asc"
        docs_by_date = await self.pipeline.enhanced_retriever.get_documents_by_date(
            order=order, limit=5
        )
        
        if not docs_by_date or not docs_by_date[0].get("doc_date"):
            return None
        
        top_doc = docs_by_date[0]
        doc_name = top_doc["doc_title"] or top_doc["doc_source"].split("/")[-1] or "Untitled"
        doc_date = top_doc["doc_date"]
        
        # Build deterministic response
        if date_query_type == "latest":
            response_text = f"The document with the latest explicit date is **{doc_name}**, dated **{doc_date}**."
        else:
            response_text = f"The document with the oldest/earliest date is **{doc_name}**, dated **{doc_date}**."
        
        # Add context about other documents
        if len(docs_by_date) > 1:
            other_docs = [
                f"{d['doc_title'] or d['doc_source'].split('/')[-1]} ({d['doc_date']})"
                for d in docs_by_date[1:] if d.get('doc_date')
            ]
            if other_docs:
                response_text += f"\n\nOther documents by date ({order}ending): " + ", ".join(other_docs)
        
        logger.info("stage_4.0_date_metadata_answered",
                   doc_name=doc_name, doc_date=doc_date)
        
        return RouteResult(
            response=response_text,
            route_used=self.ROUTE_NAME,
            citations=[Citation(
                index=1,
                chunk_id=f"{top_doc['doc_id']}_metadata",
                document_id=top_doc.get("doc_id", ""),
                document_title=doc_name,
                document_url=top_doc.get("doc_source", ""),
                score=1.0,
                text_preview=f"Document date: {doc_date}",
            )],
            evidence_path=[{"type": "document_metadata", "doc_id": top_doc["doc_id"], "date": doc_date}],
            metadata={
                "deterministic_answer": True,
                "query_type": f"date_metadata_{date_query_type}",
                "all_docs_by_date": docs_by_date,
                "route_description": "Deterministic document metadata query (date)",
            }
        )

    # ==========================================================================
    # QUERY DECOMPOSITION
    # ==========================================================================
    
    async def _drift_decompose(self, query: str) -> List[str]:
        """Decompose an ambiguous query into concrete sub-questions."""
        if not self.llm:
            return [query]
        
        prompt = f"""Break down this complex query into specific, answerable sub-questions.

Original Query: "{query}"

Guidelines:
- Each sub-question MUST be a complete, self-contained sentence that can be understood without reading any other sub-question.
  BAD: "to both documents."  (sentence fragment)
  BAD: "—and analyze these to find..."  (starts with dash/conjunction, missing context)
  GOOD: "What are the differences in product specifications between the invoice and contract?"
- Each sub-question should focus on identifying specific entities or relationships
- Questions should build on each other (entity discovery → relationship exploration → analysis)
- Generate 2-5 sub-questions depending on complexity
- CRITICAL: Preserve ALL constraints and qualifiers from the original query in EACH sub-question
  (e.g., if original asks for items "above $500", each sub-question must preserve that threshold)
  (e.g., if original asks for "California-specific" clauses, each sub-question must include that geographic constraint)

Format your response as a numbered list:
1. [First complete sub-question]
2. [Second complete sub-question]
...

Sub-questions:"""

        try:
            response = await self.llm.acomplete(prompt)
            text = response.text.strip()
            
            # --- Robust multi-line parser ---
            # LLM may wrap long sub-questions across multiple lines.
            # First, join continuation lines back onto their numbered item.
            # A "continuation line" is any line that does NOT start with a digit
            # (i.e., it's not a new numbered item).
            import re
            lines = text.split('\n')
            merged_lines: List[str] = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                # New numbered item (e.g., "1.", "2)", "3.")
                if re.match(r'^\d+[\.\)]\s', stripped):
                    merged_lines.append(stripped)
                elif merged_lines:
                    # Continuation of previous item — append with space
                    merged_lines[-1] += " " + stripped
                # else: preamble text before first numbered item — skip
            
            sub_questions = []
            for line in merged_lines:
                # Strip numbering: "1. ..." or "1) ..."
                content = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
                
                if content:
                    normalized = content.strip('"').strip("'").strip()
                    if normalized in {"?", "-", "—"} or len(normalized) < 8:
                        continue
                    sub_questions.append(normalized)
            
            # Deduplicate
            deduped = []
            seen = set()
            for q in sub_questions:
                k = q.lower()
                if k not in seen:
                    seen.add(k)
                    deduped.append(q)
            
            return deduped if deduped else [query]
            
        except Exception as e:
            logger.warning("drift_decompose_failed", error=str(e))
            return [query]

    # ==========================================================================
    # ENTITY DISCOVERY
    # ==========================================================================
    
    async def _execute_discovery_pass(
        self, sub_questions: List[str]
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Execute entity discovery for sub-questions."""
        all_seeds: List[str] = []
        intermediate_results: List[Dict[str, Any]] = []
        
        for i, sub_q in enumerate(sub_questions):
            logger.info(f"processing_sub_question_{i+1}", question=sub_q[:50])
            
            # Get entities for this sub-question
            sub_entities = await self.pipeline.disambiguator.disambiguate(sub_q)
            all_seeds.extend(sub_entities)
            
            # Run partial search for context (PPR or beam)
            evidence_count = 0
            if sub_entities:
                if ROUTE4_USE_PPR:
                    partial_evidence = await self.pipeline.tracer.trace(
                        query=sub_q,
                        seed_entities=sub_entities,
                        top_k=5,
                    )
                else:
                    sub_q_embedding = _get_query_embedding(sub_q)
                    partial_evidence = await self.pipeline.tracer.trace_semantic_beam(
                        query=sub_q,
                        query_embedding=sub_q_embedding,
                        seed_entities=sub_entities,
                        max_hops=2,  # Shorter for sub-question context
                        beam_width=5,
                        knn_config=getattr(self, '_knn_config', None),
                    )
                evidence_count = len(partial_evidence)
            
            intermediate_results.append({
                "question": sub_q,
                "entities": sub_entities,
                "evidence_count": evidence_count
            })
        
        all_seeds = list(set(all_seeds))
        return all_seeds, intermediate_results

    # ==========================================================================
    # CONFIDENCE METRICS
    # ==========================================================================
    
    def _compute_subgraph_confidence(
        self,
        sub_questions: List[str],
        intermediate_results: List[Dict[str, Any]],
        complete_evidence: Optional[List] = None
    ) -> Dict[str, Any]:
        """Compute comprehensive confidence metrics for retrieved subgraph."""
        if not sub_questions:
            return {
                "score": 1.0, "satisfied_ratio": 1.0, "entity_diversity": 1.0,
                "thin_questions": [], "concentrated_entities": []
            }
        
        # Metric 1: Evidence satisfaction ratio
        satisfied = sum(
            1 for r in intermediate_results
            if r.get("evidence_count", 0) >= 2
        )
        satisfied_ratio = satisfied / len(sub_questions)
        
        # Metric 2: Entity diversity
        all_entities: List[str] = []
        entity_to_questions: Dict[str, List[str]] = {}
        
        for r in intermediate_results:
            entities = r.get("entities", [])
            question = r.get("question", "")
            all_entities.extend(entities)
            for ent in entities:
                ent_lower = ent.lower().strip()
                if ent_lower not in entity_to_questions:
                    entity_to_questions[ent_lower] = []
                entity_to_questions[ent_lower].append(question)
        
        unique_count = len(set(e.lower().strip() for e in all_entities)) if all_entities else 1
        entity_diversity = unique_count / max(len(all_entities), 1)
        
        # Concentrated entities (>50% of sub-questions)
        concentrated_entities = [
            ent for ent, questions in entity_to_questions.items()
            if len(questions) > len(sub_questions) * 0.5
        ]
        
        # Thin questions
        thin_questions = [
            r["question"] for r in intermediate_results
            if r.get("evidence_count", 0) < 2
        ]
        
        # Overall score
        overall_score = (0.6 * satisfied_ratio) + (0.4 * entity_diversity)
        
        # Concentration penalty
        if concentrated_entities:
            penalty = min(0.2, len(concentrated_entities) * 0.05)
            overall_score = max(0.0, overall_score - penalty)
        
        return {
            "score": overall_score,
            "satisfied_ratio": satisfied_ratio,
            "entity_diversity": entity_diversity,
            "thin_questions": thin_questions,
            "concentrated_entities": concentrated_entities
        }

    # ==========================================================================
    # COVERAGE GAP FILL (with Domain Keyword Extraction + Chunks-per-Doc Scaling)
    # ==========================================================================
    
    async def _apply_coverage_gap_fill(
        self, query: str, complete_evidence: List
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """Fill coverage gaps for corpus-level queries.
        
        For queries like "What is the latest date across all documents?" or
        "Compare the terms in all contracts", entity-based retrieval may miss
        documents that don't have strong entity mentions (e.g., simple contracts).

        This stage ensures we have at least ONE chunk from every document in
        the corpus before synthesis, so the LLM can answer corpus-level questions.

        Jan 2026 Enhancement: For "list all" / "enumerate" / "compare" queries:
        1. Increase max_per_document to ensure comprehensive coverage
        2. Extract domain keywords from query for BM25 boosting
        3. Use hybrid semantic + keyword retrieval for exhaustive enumeration
        """
        coverage_chunks: List[Dict] = []
        coverage_metadata: Dict[str, Any] = {"applied": False}
        
        if not self.pipeline.enhanced_retriever:
            return coverage_chunks, coverage_metadata
        
        # Detect comprehensive enumeration queries that need more chunks per document
        def _is_comprehensive_query(q: str) -> bool:
            """Detect queries asking for exhaustive lists or comparisons."""
            q_lower = q.lower()
            # Patterns that indicate comprehensive enumeration
            comprehensive_patterns = [
                "list all", "list every", "enumerate", "compare all",
                "compare the", "all explicit", "all the", "every ",
                "what are all", "find all", "identify all", "show all",
                "across all", "across the set", "in all documents",
                "each document", "every document", "comprehensive",
            ]
            return any(pattern in q_lower for pattern in comprehensive_patterns)
        
        def _extract_domain_keywords(q: str) -> List[str]:
            """Extract domain-specific keywords for BM25 boosting in comprehensive queries."""
            q_lower = q.lower()
            keywords: List[str] = []
            
            # Time-related patterns
            if any(term in q_lower for term in ["time", "timeframe", "deadline", "period", "duration", "window"]):
                keywords.extend(["days", "business days", "calendar days", "weeks", "months", "year"])
            
            # Money/payment-related patterns
            if any(term in q_lower for term in ["payment", "price", "cost", "fee", "amount", "money"]):
                keywords.extend(["$", "dollar", "payment", "fee", "cost", "price"])
            
            # Party/entity-related patterns
            if any(term in q_lower for term in ["party", "parties", "entity", "entities", "who"]):
                keywords.extend(["buyer", "seller", "owner", "tenant", "contractor", "agent"])
            
            # Obligation-related patterns
            if any(term in q_lower for term in ["obligation", "must", "shall", "require", "responsible"]):
                keywords.extend(["shall", "must", "required", "responsible", "obligat"])
            
            return keywords
        
        is_comprehensive = _is_comprehensive_query(query)
        domain_keywords = _extract_domain_keywords(query) if is_comprehensive else []
        
        # For comprehensive queries, scale chunks based on corpus size
        # Small corpus (< 50 chunks total): get 5 per doc
        # Medium corpus (50-200 chunks): get 3 per doc  
        # Large corpus (> 200 chunks): get 2 per doc (semantic + keyword boost)
        chunks_per_doc = 5 if is_comprehensive else 1  # Will adjust below based on corpus size
        
        try:
            logger.info("stage_4.3.6_coverage_gap_fill_start",
                       is_comprehensive=is_comprehensive,
                       domain_keywords=domain_keywords[:5] if domain_keywords else [],
                       chunks_per_doc=chunks_per_doc)
            
            # 1. Build set of documents already covered by evidence
            covered_docs: set = set()
            existing_chunk_ids: set = set()
            
            for ev in complete_evidence:
                doc_key = self._extract_doc_key(ev)
                if doc_key:
                    covered_docs.add(doc_key)
                chunk_id = self._extract_evidence_id(ev)
                if chunk_id:
                    existing_chunk_ids.add(chunk_id)
            
            # 2. Get all documents in the corpus
            all_documents = await self.pipeline.enhanced_retriever.get_all_documents()
            total_docs = len(all_documents)
            
            # 3. If we already have full coverage, skip
            if total_docs > 0 and len(covered_docs) >= total_docs:
                coverage_metadata = {
                    "applied": False,
                    "reason": "already_full_coverage",
                    "docs_from_entity_retrieval": len(covered_docs),
                    "total_docs_in_corpus": total_docs,
                }
                logger.info("stage_4.3.6_skipped_full_coverage",
                           covered=len(covered_docs), total=total_docs)
                return coverage_chunks, coverage_metadata
            
            # 4. Fetch coverage chunks
            # For comprehensive "list all" queries, use SECTION-based coverage
            # to ensure we get chunks from every section (not just top-K per doc).
            # For regular queries, use semantic similarity to get relevant chunks.
            
            coverage_source_chunks: List[Any] = []
            coverage_strategy = "unknown"
            
            if is_comprehensive:
                # SECTION-BASED COVERAGE for "list all" queries
                # This ensures we don't miss section-specific info like:
                # - "Right to Cancel" section (3 business days)
                # - "Warranty Repair" section (60 days repair window)
                #
                # BUG FIX: Use max_per_section=None to get ALL chunks per section
                # Previously, max_per_section=1 only returned first chunk per section,
                # missing critical content in later chunks.
                logger.info("stage_4.3.6_using_section_based_coverage",
                           reason="comprehensive_enumeration_query")
                
                coverage_source_chunks = await self.pipeline.enhanced_retriever.get_all_sections_chunks(
                    max_per_section=None,  # Get ALL chunks per section for comprehensive coverage
                )
                coverage_strategy = "section_based_exhaustive"
                
                # HYBRID RERANKING: Semantic + Keyword (BM25-style) scoring
                # Semantic alone ranks "8-10 weeks" similar to "day-based timeframes" (both about time)
                # Keyword matching ensures "day-based" query boosts chunks with "day"/"days"
                if coverage_source_chunks:
                    try:
                        from src.worker.services.llm_service import LLMService
                        import re
                        import math
                        llm_service = LLMService()
                        
                        # Extract key terms from query for keyword matching
                        query_lower = query.lower()
                        # Extract unit qualifiers (e.g., "day-based" -> "day")
                        unit_match = re.search(r'\b(\w+)-based\b', query_lower)
                        query_unit = unit_match.group(1) if unit_match else None
                        
                        # Extract other important keywords (nouns, key terms)
                        query_keywords = set(re.findall(r'\b[a-z]{3,}\b', query_lower))
                        # Remove stop words
                        stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 
                                     'had', 'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been',
                                     'this', 'that', 'with', 'they', 'what', 'which', 'from', 'into',
                                     'each', 'list', 'across', 'compare', 'explicit', 'set'}
                        query_keywords -= stop_words
                        
                        def compute_keyword_score(text: str) -> float:
                            """Compute simple keyword match score (BM25-inspired)."""
                            if not text:
                                return 0.0
                            text_lower = text.lower()
                            score = 0.0
                            
                            # Heavy boost if query specifies a unit and chunk matches it
                            if query_unit:
                                # Count occurrences of the unit (e.g., "day", "days")
                                unit_pattern = rf'\b{re.escape(query_unit)}s?\b'
                                unit_matches = len(re.findall(unit_pattern, text_lower))
                                if unit_matches > 0:
                                    score += 2.0 * math.log(1 + unit_matches)  # Strong boost
                                else:
                                    # Penalize if chunk has OTHER time units but not the requested one
                                    other_units = ['week', 'month', 'year', 'hour', 'minute']
                                    if query_unit in ['day', 'week', 'month', 'year', 'hour', 'minute']:
                                        other_units = [u for u in other_units if u != query_unit]
                                    for other in other_units:
                                        if re.search(rf'\b{other}s?\b', text_lower):
                                            score -= 0.5  # Penalty for wrong unit
                            
                            # Standard keyword matching
                            for kw in query_keywords:
                                if kw in text_lower:
                                    score += 0.3
                            
                            return score
                        
                        # Compute hybrid scores
                        scored_chunks = []
                        for chunk in coverage_source_chunks:
                            if chunk.text:
                                keyword_score = compute_keyword_score(chunk.text)
                                
                                # Semantic score (optional - can be slow for many chunks)
                                # NOTE: Chunk embeddings are pre-computed in Neo4j, so we only embed the query here
                                semantic_score = 0.5  # Default neutral
                                if llm_service.embed_model and len(coverage_source_chunks) <= 100:
                                    from src.worker.hybrid_v2.orchestrator import get_query_embedding
                                    query_embedding = get_query_embedding(query)
                                    chunk_embedding = get_query_embedding(chunk.text[:2000])
                                    import numpy as np
                                    semantic_score = np.dot(query_embedding, chunk_embedding) / (
                                        np.linalg.norm(query_embedding) * np.linalg.norm(chunk_embedding) + 1e-9
                                    )
                                
                                # Hybrid score: 60% keyword, 40% semantic
                                # Keyword is weighted higher for qualifier-based queries
                                if query_unit:
                                    hybrid_score = 0.7 * keyword_score + 0.3 * semantic_score
                                else:
                                    hybrid_score = 0.4 * keyword_score + 0.6 * semantic_score
                                
                                scored_chunks.append((chunk, hybrid_score, keyword_score, semantic_score))
                        
                        # Sort by hybrid score
                        scored_chunks.sort(key=lambda x: x[1], reverse=True)
                        
                        # For unit-qualified queries, filter out chunks with zero/negative keyword score
                        if query_unit:
                            # Keep chunks with positive keyword score OR top 20 by hybrid
                            positive_kw = [(c, h, k, s) for c, h, k, s in scored_chunks if k > 0]
                            if len(positive_kw) >= 10:
                                filtered_chunks = [c for c, h, k, s in positive_kw]
                            else:
                                # Not enough positive matches, fall back to top by hybrid
                                min_chunks = max(20, len(scored_chunks) // 2)
                                filtered_chunks = [c for c, h, k, s in scored_chunks[:min_chunks]]
                        else:
                            # No unit qualifier - use standard filtering
                            min_chunks = max(20, len(scored_chunks) // 2)
                            filtered_chunks = [c for c, h, k, s in scored_chunks[:min_chunks]]
                        
                        logger.info("stage_4.3.6_hybrid_rerank_applied",
                                   original_count=len(coverage_source_chunks),
                                   filtered_count=len(filtered_chunks),
                                   query_unit=query_unit,
                                   top_hybrid=scored_chunks[0][1] if scored_chunks else 0,
                                   top_keyword=scored_chunks[0][2] if scored_chunks else 0)
                        
                        coverage_source_chunks = filtered_chunks
                        coverage_strategy = "section_based_hybrid_reranked"
                    except Exception as rerank_err:
                        logger.warning("stage_4.3.6_hybrid_rerank_failed", 
                                      error=str(rerank_err),
                                      falling_back_to="unranked_section_chunks")
                
                # If section-based retrieval returns nothing, fall back to semantic
                # but with MUCH higher chunks_per_doc (15-20) to simulate section coverage
                if not coverage_source_chunks:
                    logger.warning("stage_4.3.6_section_fallback",
                                  reason="no_sections_found",
                                  fallback_chunks_per_doc=15)
                    chunks_per_doc = 15  # Aggressive coverage when sections unavailable
                    # Fall through to semantic below
            
            # Standard semantic/early-chunk coverage (fallback or non-comprehensive)
            if not coverage_source_chunks:
                coverage_max = min(max(total_docs * chunks_per_doc, 0), 200)
                
                # Try to get query embedding for semantic coverage (V2 Voyage or V1 OpenAI)
                query_embedding = None
                try:
                    from src.worker.hybrid_v2.orchestrator import get_query_embedding
                    query_embedding = get_query_embedding(query)
                except Exception as emb_err:
                    logger.warning("coverage_embedding_failed", error=str(emb_err))
                
                if query_embedding:
                    # Use semantic coverage: find most relevant chunks per document
                    coverage_source_chunks = await self.pipeline.enhanced_retriever.get_coverage_chunks_semantic(
                        query_embedding=query_embedding,
                        max_per_document=chunks_per_doc,
                        max_total=coverage_max,
                    )
                    coverage_strategy = f"semantic_x{chunks_per_doc}" if is_comprehensive else "semantic"
                else:
                    # Fallback to early-chunk coverage if embedding fails
                    coverage_source_chunks = await self.pipeline.enhanced_retriever.get_coverage_chunks(
                        max_per_document=chunks_per_doc,
                        max_total=coverage_max,
                        prefer_early_chunks=True,
                    )
                    coverage_strategy = f"early_chunks_x{chunks_per_doc}_fallback" if is_comprehensive else "early_chunks_fallback"
            
            # 5. Add chunks only for documents NOT already covered
            added_count = 0
            new_docs: set = set()
            
            for chunk in coverage_source_chunks:
                doc_key = (
                    chunk.document_id or
                    chunk.document_source or
                    chunk.document_title or
                    ""
                ).strip().lower()
                
                # For section-based coverage, allow multiple chunks per document
                # (one per section). For semantic coverage, only one chunk per doc.
                skip_chunk = False
                # Support both 'section_based' and 'section_based_exhaustive' naming
                if coverage_strategy.startswith("section_based"):
                    # Section-based: Skip only if chunk already exists
                    skip_chunk = chunk.chunk_id in existing_chunk_ids
                else:
                    # Semantic/early-chunk: Skip if document already covered
                    skip_chunk = doc_key and doc_key in covered_docs
                
                # Skip if chunk already exists
                if chunk.chunk_id in existing_chunk_ids:
                    skip_chunk = True
                
                if not skip_chunk:
                    # Convert SourceChunk to dict format expected by synthesizer
                    coverage_chunk_dict = {
                        "id": chunk.chunk_id,
                        "text": chunk.text,
                        "source": chunk.document_source or chunk.document_title or "coverage",
                        "metadata": {
                            "document_id": chunk.document_id,
                            "document_title": chunk.document_title,
                            "document_source": chunk.document_source,
                            "is_coverage_chunk": True,
                            "section_path": chunk.section_path,
                        },
                    }
                    coverage_chunks.append(coverage_chunk_dict)
                    if doc_key:
                        covered_docs.add(doc_key)
                        new_docs.add(doc_key)
                    existing_chunk_ids.add(chunk.chunk_id)
                    added_count += 1
            
            coverage_metadata = {
                "applied": added_count > 0,
                "strategy": coverage_strategy,
                "is_comprehensive_query": is_comprehensive,
                "chunks_per_doc": chunks_per_doc,
                "chunks_added": added_count,
                "docs_added": len(new_docs),
                "docs_from_entity_retrieval": len(covered_docs) - len(new_docs),
                "total_docs_in_corpus": total_docs,
            }
            
            if added_count > 0:
                logger.info("stage_4.3.6_coverage_gap_fill_complete",
                           chunks_added=added_count,
                           new_docs=len(new_docs),
                           strategy=coverage_strategy,
                           total_evidence=len(complete_evidence))
                               
        except Exception as cov_err:
            logger.warning("stage_4.3.6_coverage_gap_fill_failed", error=str(cov_err))
            coverage_metadata = {"applied": False, "error": str(cov_err)}
        
        return coverage_chunks, coverage_metadata

    # ==========================================================================
    # UTILITY METHODS
    # ==========================================================================
    
    def _extract_evidence_id(self, ev) -> Optional[str]:
        """Extract chunk ID from evidence node."""
        if isinstance(ev, dict):
            return ev.get("chunk_id") or ev.get("id") or ev.get("name")
        elif isinstance(ev, tuple) and len(ev) >= 1:
            return ev[0] if ev else None
        return None

    def _extract_doc_key(self, ev) -> Optional[str]:
        """Extract document identifier from evidence node."""
        if isinstance(ev, dict):
            meta = ev.get("metadata", {})
            doc = (
                meta.get("document_id") or
                meta.get("document_title") or
                ev.get("source") or
                ""
            )
            return str(doc).strip().lower() if doc else None
        return None
