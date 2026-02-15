"""DRIFT Workflow: Parallel sub-question processing with confidence loop.

This workflow implements Route 4 (DRIFT multi-hop reasoning) using LlamaIndex
Workflows for parallel execution of sub-questions.

Key improvements over sequential implementation:
1. Sub-questions processed in PARALLEL (~700ms vs ~2.1s for 3 questions)
2. Clean event-driven confidence loop
3. Automatic observability via LlamaIndex instrumentation

Flow:
    StartEvent → decompose → [SubQuestionEvent...] (parallel) → collect_results
    → check_confidence → synthesize | redecompose → StopEvent
"""

import asyncio
import os
import re
import time
from typing import Dict, Any, List, Optional, Tuple

import structlog
from llama_index.core.workflow import (
    Workflow, 
    step, 
    Context, 
    StartEvent, 
    StopEvent,
)

# Import sentence search env vars from route handler
ROUTE4_SENTENCE_SEARCH = os.getenv("ROUTE4_SENTENCE_SEARCH", "1").strip().lower() in {"1", "true", "yes"}
ROUTE4_SENTENCE_TOP_K = int(os.getenv("ROUTE4_SENTENCE_TOP_K", "30"))
ROUTE4_SENTENCE_RERANK = os.getenv("ROUTE4_SENTENCE_RERANK", "1").strip().lower() in {"1", "true", "yes"}

from .events import (
    DecomposeEvent,
    SubQuestionEvent,
    SubQuestionResultEvent,
    ConfidenceCheckEvent,
    ReDecomposeEvent,
    SynthesizeEvent,
)

logger = structlog.get_logger(__name__)


class DRIFTWorkflow(Workflow):
    """DRIFT-style iterative reasoning workflow with parallel sub-question processing.
    
    This workflow implements Route 4's multi-hop reasoning pattern:
    1. Decompose complex query into sub-questions
    2. Process each sub-question IN PARALLEL (entity discovery + evidence retrieval)
    3. Collect results and compute confidence
    4. If confidence low: re-decompose and repeat
    5. Final synthesis with all evidence
    
    Args:
        pipeline: The HybridSearchPipeline instance for accessing services
        timeout: Maximum execution time in seconds (default: 120)
        max_redecompose_attempts: Maximum re-decomposition attempts (default: 1)
    
    Example:
        workflow = DRIFTWorkflow(pipeline=pipeline, timeout=60)
        result = await workflow.run(
            query="What are the payment terms across all agreements?",
            response_type="detailed_report"
        )
    """
    
    def __init__(
        self, 
        pipeline: Any,  # HybridSearchPipeline
        timeout: int = 120,
        max_redecompose_attempts: int = 1,
        **kwargs
    ):
        super().__init__(timeout=timeout, **kwargs)
        self.pipeline = pipeline
        self.max_redecompose_attempts = max_redecompose_attempts
    
    # =========================================================================
    # Step 1: Decompose Query
    # =========================================================================
    
    @step
    async def decompose(self, ctx: Context, ev: StartEvent) -> DecomposeEvent:
        """Stage 4.1: Decompose query into sub-questions.
        
        Also handles Stage 4.0: Check for deterministic date metadata queries.
        """
        query = ev.query
        response_type = getattr(ev, 'response_type', 'detailed_report')
        
        logger.info("drift_workflow_start", query=query[:50])
        
        # Store context for later steps
        await ctx.store.set("original_query", query)
        await ctx.store.set("response_type", response_type)
        await ctx.store.set("redecompose_count", 0)
        await ctx.store.set("timings_ms", {})
        
        t0 = time.perf_counter()
        
        # Stage 4.0: Check for deterministic date metadata queries
        if self.pipeline.enhanced_retriever:
            from src.worker.hybrid_v2.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
            date_query_type = EnhancedGraphRetriever.detect_date_metadata_query(query)
            
            if date_query_type:
                logger.info("drift_workflow_date_metadata_detected", query_type=date_query_type)
                # Handle deterministically - return StopEvent directly
                result = await self._handle_date_metadata_query(query, date_query_type)
                # Store result and short-circuit
                await ctx.store.set("deterministic_result", result)
                return DecomposeEvent(query=query, response_type=response_type)
        
        # Decompose query
        sub_questions = await self.pipeline._drift_decompose(query)
        
        timings = await ctx.store.get("timings_ms", {})
        timings["stage_4.1_ms"] = int((time.perf_counter() - t0) * 1000)
        await ctx.store.set("timings_ms", timings)
        
        logger.info("drift_decompose_complete", num_sub_questions=len(sub_questions))
        
        # Store sub-questions count for collection
        await ctx.store.set("num_sub_questions", len(sub_questions))
        await ctx.store.set("sub_questions", sub_questions)
        
        return DecomposeEvent(query=query, response_type=response_type)
    
    # =========================================================================
    # Step 2: Fan-out to Sub-Questions (PARALLEL)
    # =========================================================================
    
    @step
    async def fan_out_sub_questions(
        self, ctx: Context, ev: DecomposeEvent
    ) -> SubQuestionEvent | SynthesizeEvent | None:
        """Stage 4.2 Setup: Create parallel sub-question events.
        
        Uses ctx.send_event() to emit multiple events for parallel processing.
        Returns SynthesizeEvent only for deterministic short-circuit case.
        Returns None otherwise (events already sent via ctx.send_event()).
        
        NOTE: Return type includes SubQuestionEvent to indicate this step
        produces SubQuestionEvents (via send_event), even though we return None.
        """
        # Check for deterministic result short-circuit
        deterministic_result = await ctx.store.get("deterministic_result", None)
        if deterministic_result:
            # Skip to synthesis with deterministic result
            return SynthesizeEvent(
                results=[],
                all_seeds=[],
                original_query=ev.query,
                response_type=ev.response_type,
            )
        
        sub_questions = await ctx.store.get("sub_questions", [])
        
        logger.info("drift_fan_out", num_sub_questions=len(sub_questions))
        
        # Send each sub-question event - they will be processed in PARALLEL
        for i, sq in enumerate(sub_questions):
            ctx.send_event(SubQuestionEvent(
                sub_question=sq,
                index=i,
                original_query=ev.query,
            ))
        
        return None  # Events already sent
    
    # =========================================================================
    # Step 3: Process Single Sub-Question (runs in parallel for each)
    # =========================================================================
    
    @step(num_workers=4)  # Process up to 4 sub-questions in parallel
    async def process_sub_question(
        self, ctx: Context, ev: SubQuestionEvent
    ) -> SubQuestionResultEvent:
        """Stage 4.2: Process a single sub-question.
        
        This step runs IN PARALLEL for each SubQuestionEvent (num_workers=4).
        Each instance:
        1. Disambiguates entities for this sub-question
        2. Retrieves evidence via PPR tracing
        """
        t0 = time.perf_counter()
        
        logger.info(f"drift_sub_question_{ev.index + 1}", 
                   question=ev.sub_question[:50])
        
        # Entity disambiguation
        entities = await self.pipeline.disambiguator.disambiguate(ev.sub_question)
        
        # Evidence retrieval (partial - for this sub-question only)
        evidence: List[Tuple[str, float]] = []
        evidence_count = 0
        
        if entities:
            evidence = await self.pipeline.tracer.trace(
                query=ev.sub_question,
                seed_entities=entities,
                top_k=5  # Smaller for sub-questions
            )
            evidence_count = len(evidence)
        
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(f"drift_sub_question_{ev.index + 1}_complete",
                   entities=len(entities),
                   evidence=evidence_count,
                   elapsed_ms=elapsed_ms)
        
        return SubQuestionResultEvent(
            question=ev.sub_question,
            entities=entities,
            evidence=evidence,
            evidence_count=evidence_count,
            index=ev.index,
        )
    
    # =========================================================================
    # Step 4: Collect Results & Check Confidence
    # =========================================================================
    
    @step
    async def collect_and_check(
        self, ctx: Context, ev: SubQuestionResultEvent
    ) -> ConfidenceCheckEvent | None:
        """Stage 4.3 + 4.3.5: Collect results and compute confidence.
        
        This step collects all SubQuestionResultEvents and, once all are
        received, computes confidence metrics to decide next action.
        """
        num_expected = await ctx.store.get("num_sub_questions", 1)
        
        # Collect events - returns None until all are received
        results = ctx.collect_events(ev, [SubQuestionResultEvent] * num_expected)
        if results is None:
            return None  # Still waiting for more results
        
        logger.info("drift_results_collected", count=len(results))
        
        # Sort by index to maintain order
        sorted_results = sorted(results, key=lambda r: r.index)
        
        # Aggregate all seeds
        all_seeds: List[str] = []
        intermediate_results: List[Dict[str, Any]] = []
        
        for r in sorted_results:
            all_seeds.extend(r.entities)
            intermediate_results.append({
                "question": r.question,
                "entities": r.entities,
                "evidence_count": r.evidence_count,
            })
        
        # Deduplicate seeds
        all_seeds = list(set(all_seeds))

        # NER Union: extract entities from original query (pre-decomposition)
        # to catch exact entity names that DRIFT decomposition may mutate.
        original_query = await ctx.store.get("original_query", "")
        try:
            original_entities = await self.pipeline.disambiguator.disambiguate(original_query)
            if original_entities:
                existing = set(all_seeds)
                new_seeds = [e for e in original_entities if e not in existing]
                all_seeds = all_seeds + new_seeds
                logger.info("drift_ner_union",
                           original_entities=original_entities,
                           new_from_original=len(new_seeds),
                           total_seeds=len(all_seeds))
        except Exception as e:
            logger.warning("drift_ner_union_failed", error=str(e))

        await ctx.store.set("all_seeds", all_seeds)
        await ctx.store.set("intermediate_results", intermediate_results)
        
        response_type = await ctx.store.get("response_type", "detailed_report")
        
        return ConfidenceCheckEvent(
            results=sorted_results,
            original_query=original_query,
            response_type=response_type,
        )
    
    # =========================================================================
    # Step 5: Confidence Decision
    # =========================================================================
    
    @step
    async def check_confidence(
        self, ctx: Context, ev: ConfidenceCheckEvent
    ) -> SynthesizeEvent | ReDecomposeEvent:
        """Stage 4.3.5: Evaluate confidence and decide next action.
        
        If confidence is low and we haven't exceeded redecompose attempts,
        trigger re-decomposition. Otherwise, proceed to synthesis.
        """
        t0 = time.perf_counter()
        
        sub_questions = await ctx.store.get("sub_questions", [])
        intermediate_results = await ctx.store.get("intermediate_results", [])
        all_seeds = await ctx.store.get("all_seeds", [])
        redecompose_count = await ctx.store.get("redecompose_count", 0)
        
        # Launch sentence search in parallel with consolidated trace
        sentence_task = None
        if ROUTE4_SENTENCE_SEARCH:
            sentence_task = asyncio.ensure_future(
                self._retrieve_sentence_evidence(
                    ev.original_query, top_k=ROUTE4_SENTENCE_TOP_K
                )
            )

        # Stage 4.3: Consolidated tracing with all seeds
        logger.info("drift_consolidated_tracing", num_seeds=len(all_seeds))
        complete_evidence = await self.pipeline.tracer.trace(
            query=ev.original_query,
            seed_entities=all_seeds,
            top_k=30
        )
        await ctx.store.set("complete_evidence", complete_evidence)

        # Collect sentence search results
        sentence_evidence: List[Dict[str, Any]] = []
        if sentence_task:
            try:
                sentence_evidence = await sentence_task
            except Exception as e:
                logger.warning("drift_sentence_search_failed", error=str(e))
                sentence_evidence = []
            if sentence_evidence:
                sentence_evidence = self._denoise_sentences(sentence_evidence)
                if sentence_evidence and ROUTE4_SENTENCE_RERANK:
                    try:
                        sentence_evidence = await self._rerank_sentences(
                            ev.original_query, sentence_evidence
                        )
                    except Exception as e:
                        logger.warning("drift_sentence_rerank_failed", error=str(e))
            logger.info("drift_sentence_search_complete",
                       num_sentences=len(sentence_evidence))
        await ctx.store.set("sentence_evidence", sentence_evidence)
        
        timings = await ctx.store.get("timings_ms", {})
        timings["stage_4.3_ms"] = int((time.perf_counter() - t0) * 1000)
        await ctx.store.set("timings_ms", timings)
        
        # Compute confidence
        confidence_metrics = self.pipeline._compute_subgraph_confidence(
            sub_questions, intermediate_results, complete_evidence
        )
        confidence = confidence_metrics["score"]
        
        logger.info("drift_confidence_check",
                   confidence=confidence,
                   satisfied_ratio=confidence_metrics["satisfied_ratio"],
                   entity_diversity=confidence_metrics["entity_diversity"],
                   redecompose_count=redecompose_count)
        
        # Decide: redecompose or synthesize
        should_redecompose = (
            redecompose_count < self.max_redecompose_attempts and
            (
                (confidence < 0.5 and len(sub_questions) > 1) or
                (confidence_metrics["entity_diversity"] < 0.3 and len(sub_questions) > 2) or
                (len(confidence_metrics["concentrated_entities"]) > 0 and confidence < 0.7)
            )
        )
        
        if should_redecompose:
            thin_questions = confidence_metrics["thin_questions"]
            concentrated = confidence_metrics["concentrated_entities"]
            
            logger.info("drift_redecompose_triggered",
                       thin_questions=len(thin_questions),
                       concentrated=concentrated[:3])
            
            # Build refinement prompt
            context_summary = "; ".join([
                f"{r['question']}: found {r.get('evidence_count', 0)} evidence"
                for r in intermediate_results if r.get("evidence_count", 0) >= 2
            ][:3])
            
            if concentrated and not thin_questions:
                refinement_prompt = (
                    f"The entity '{concentrated[0]}' appears across many parts. "
                    f"Context: {context_summary}. "
                    f"Generate 2-3 focused questions consolidating information about "
                    f"'{concentrated[0]}' without counting sections as distinct occurrences."
                )
            else:
                refinement_prompt = (
                    f"Based on ({context_summary}), clarify: {'; '.join(thin_questions)}"
                )
            
            return ReDecomposeEvent(
                refinement_prompt=refinement_prompt,
                previous_results=ev.results,
                original_query=ev.original_query,
                response_type=ev.response_type,
            )
        
        # Proceed to synthesis
        return SynthesizeEvent(
            results=ev.results,
            all_seeds=all_seeds,
            original_query=ev.original_query,
            response_type=ev.response_type,
        )
    
    # =========================================================================
    # Step 6: Re-decompose (Confidence Loop)
    # =========================================================================
    
    @step
    async def redecompose(
        self, ctx: Context, ev: ReDecomposeEvent
    ) -> SubQuestionEvent | None:
        """Stage 4.3.5 (retry): Generate refined sub-questions.
        
        Increments redecompose counter and generates new sub-questions
        for another parallel processing pass. Uses ctx.send_event() for fan-out.
        
        NOTE: Return type includes SubQuestionEvent to indicate this step
        produces SubQuestionEvents (via send_event), even though we return None.
        """
        redecompose_count = await ctx.store.get("redecompose_count", 0)
        await ctx.store.set("redecompose_count", redecompose_count + 1)
        
        logger.info("drift_redecompose", attempt=redecompose_count + 1)
        
        # Generate refined sub-questions
        refined_questions = await self.pipeline._drift_decompose(ev.refinement_prompt)
        
        # Update context
        existing_questions = await ctx.store.get("sub_questions", [])
        await ctx.store.set("sub_questions", existing_questions + refined_questions)
        await ctx.store.set("num_sub_questions", len(refined_questions))
        
        logger.info("drift_redecompose_complete", 
                   new_questions=len(refined_questions))
        
        # Fan out again for parallel processing using send_event
        for i, sq in enumerate(refined_questions):
            ctx.send_event(SubQuestionEvent(
                sub_question=sq,
                index=i,
                original_query=ev.original_query,
            ))
        
        return None  # Events already sent via ctx.send_event()
    
    # =========================================================================
    # Step 7: Final Synthesis
    # =========================================================================
    
    @step
    async def synthesize(self, ctx: Context, ev: SynthesizeEvent) -> StopEvent:
        """Stage 4.3.6 + 4.4: Coverage gap fill and final synthesis."""
        t0 = time.perf_counter()
        
        # Check for deterministic result
        deterministic_result = await ctx.store.get("deterministic_result", None)
        if deterministic_result:
            logger.info("drift_returning_deterministic_result")
            return StopEvent(result=deterministic_result)
        
        original_query = ev.original_query
        response_type = ev.response_type
        sub_questions = await ctx.store.get("sub_questions", [])
        intermediate_results = await ctx.store.get("intermediate_results", [])
        complete_evidence = await ctx.store.get("complete_evidence", [])
        
        # Stage 4.3.6: Coverage Gap Fill
        coverage_chunks = await self._apply_coverage_gap_fill(
            original_query, complete_evidence
        )

        # Stage 4.S: Merge sentence evidence into coverage chunks
        sentence_evidence = await ctx.store.get("sentence_evidence", [])
        sentence_chunks_added = 0
        if sentence_evidence:
            sentence_as_chunks = []
            for ev_item in sentence_evidence:
                sentence_as_chunks.append({
                    "text": ev_item.get("text", ""),
                    "document_title": ev_item.get("document_title", "Unknown"),
                    "document_id": ev_item.get("document_id", ""),
                    "section_path": ev_item.get("section_path", ""),
                    "page_number": ev_item.get("page"),
                    "_entity_score": ev_item.get("rerank_score", ev_item.get("score", 0.5)),
                    "_source_entity": "__sentence_search__",
                })
            sentence_chunks_added = len(sentence_as_chunks)
            # Prepend sentence chunks (higher quality) before coverage gap-fill chunks
            coverage_chunks = sentence_as_chunks + (coverage_chunks or [])
            logger.info("drift_sentence_chunks_merged",
                       sentence_chunks=sentence_chunks_added,
                       total_coverage=len(coverage_chunks))
        
        # Stage 4.4: Synthesis
        logger.info("drift_synthesis_start")
        synthesis_result = await self.pipeline.synthesizer.synthesize(
            query=original_query,
            evidence_nodes=complete_evidence,
            response_type=response_type,
            sub_questions=sub_questions,
            intermediate_context=intermediate_results,
            coverage_chunks=coverage_chunks if coverage_chunks else None,
        )
        
        timings = await ctx.store.get("timings_ms", {})
        timings["stage_4.4_ms"] = int((time.perf_counter() - t0) * 1000)
        
        logger.info("drift_workflow_complete", timings=timings)
        
        # Build final result
        result = {
            "response": synthesis_result["response"],
            "route_used": "route_4_drift_workflow",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "sub_questions": sub_questions,
                "workflow": True,
                "parallel_sub_questions": True,
                "timings_ms": timings,
                "redecompose_attempts": await ctx.store.get("redecompose_count", 0),
                "sentence_evidence_count": len(sentence_evidence),
                "sentence_chunks_merged": sentence_chunks_added,
            }
        }
        
        return StopEvent(result=result)
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    async def _handle_date_metadata_query(
        self, query: str, date_query_type: str
    ) -> Dict[str, Any]:
        """Handle deterministic date metadata queries without LLM reasoning."""
        order = "desc" if date_query_type == "latest" else "asc"
        docs_by_date = await self.pipeline.enhanced_retriever.get_documents_by_date(
            order=order, limit=5
        )
        
        if docs_by_date and docs_by_date[0].get("doc_date"):
            top_doc = docs_by_date[0]
            doc_name = top_doc["doc_title"] or top_doc["doc_source"].split("/")[-1] or "Untitled"
            doc_date = top_doc["doc_date"]
            
            if date_query_type == "latest":
                response_text = f"The document with the latest explicit date is **{doc_name}**, dated **{doc_date}**."
            else:
                response_text = f"The document with the oldest/earliest date is **{doc_name}**, dated **{doc_date}**."
            
            if len(docs_by_date) > 1:
                other_docs = [
                    f"{d['doc_title'] or d['doc_source'].split('/')[-1]} ({d['doc_date']})" 
                    for d in docs_by_date[1:] if d.get('doc_date')
                ]
                if other_docs:
                    response_text += f"\n\nOther documents by date ({order}ending): " + ", ".join(other_docs)
            
            return {
                "response": response_text,
                "route_used": "route_4_drift_workflow",
                "citations": [{
                    "index": 1,
                    "document_id": top_doc["doc_id"],
                    "chunk_id": f"{top_doc['doc_id']}_metadata",
                    "document_title": doc_name,
                    "score": 1.0,
                    "text_preview": f"Document date: {doc_date}",
                }],
                "evidence_path": [{"type": "document_metadata", "doc_id": top_doc["doc_id"], "date": doc_date}],
                "metadata": {
                    "deterministic_answer": True,
                    "query_type": f"date_metadata_{date_query_type}",
                    "workflow": True,
                }
            }
        
        # No date metadata found - return empty to trigger normal flow
        return {}
    
    # =========================================================================
    # Sentence Search (ported from DRIFTHandler)
    # =========================================================================

    async def _retrieve_sentence_evidence(
        self,
        query: str,
        top_k: int = 30,
    ) -> List[Dict[str, Any]]:
        """Retrieve sentence-level evidence via Voyage vector search.

        Provides a direct query->source evidence path that bypasses entity
        resolution and graph traversal.
        """
        from ..routes.route_4_drift import _get_voyage_service

        voyage_service = _get_voyage_service()
        if not voyage_service:
            logger.warning("drift_wf_sentence_search_no_voyage_service")
            return []

        neo4j_driver = getattr(self.pipeline, "neo4j_driver", None)
        if not neo4j_driver:
            logger.warning("drift_wf_sentence_search_no_neo4j_driver")
            return []

        try:
            query_embedding = voyage_service.embed_query(query)
        except Exception as e:
            logger.warning("drift_wf_sentence_embed_failed", error=str(e))
            return []

        threshold = float(os.getenv("ROUTE4_SENTENCE_THRESHOLD", "0.2"))
        group_id = getattr(self.pipeline, "group_id", "")

        cypher = """
        CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
        YIELD node AS sent, score
        WHERE sent.group_id = $group_id AND score >= $threshold

        OPTIONAL MATCH (sent)-[:PART_OF]->(chunk:TextChunk)
        OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
        OPTIONAL MATCH (sent)-[:NEXT]->(next_sent:Sentence)
        OPTIONAL MATCH (prev_sent:Sentence)-[:NEXT]->(sent)

        RETURN sent.id AS sentence_id,
               sent.text AS text,
               sent.source AS source,
               sent.section_path AS section_path,
               sent.page AS page,
               chunk.text AS chunk_text,
               doc.title AS document_title,
               doc.id AS document_id,
               score,
               prev_sent.text AS prev_text,
               next_sent.text AS next_text
        ORDER BY score DESC
        """

        try:
            loop = asyncio.get_event_loop()
            executor = getattr(self.pipeline, "_executor", None)

            def _run_search():
                with neo4j_driver.session() as session:
                    records = session.run(
                        cypher,
                        embedding=query_embedding,
                        group_id=group_id,
                        top_k=top_k,
                        threshold=threshold,
                    )
                    return [dict(r) for r in records]

            results = await loop.run_in_executor(executor, _run_search)
        except Exception as e:
            logger.warning("drift_wf_sentence_search_failed", error=str(e))
            return []

        if not results:
            return []

        seen_sentences: set = set()
        evidence: List[Dict[str, Any]] = []

        for r in results:
            sid = r.get("sentence_id", "")
            if sid in seen_sentences:
                continue
            seen_sentences.add(sid)

            parts = []
            if r.get("prev_text"):
                parts.append(r["prev_text"].strip())
            parts.append(r.get("text", "").strip())
            if r.get("next_text"):
                parts.append(r["next_text"].strip())
            passage = " ".join(parts)

            evidence.append({
                "text": passage,
                "sentence_text": r.get("text", ""),
                "score": r.get("score", 0),
                "document_title": r.get("document_title", "Unknown"),
                "document_id": r.get("document_id", ""),
                "section_path": r.get("section_path", ""),
                "page": r.get("page"),
                "sentence_id": sid,
            })

        logger.info(
            "drift_wf_sentence_search_complete",
            query=query[:50],
            results_raw=len(results),
            evidence_deduped=len(evidence),
        )
        return evidence

    @staticmethod
    def _denoise_sentences(
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove noisy, non-informative sentences. Same logic as DRIFTHandler."""
        cleaned: List[Dict[str, Any]] = []

        for ev_item in evidence:
            text = (ev_item.get("sentence_text") or ev_item.get("text", "")).strip()
            passage = (ev_item.get("text", "")).strip()

            if len(re.findall(r"<[^>]+>", text)) >= 2:
                continue
            if len(text) < 25:
                continue
            if re.search(
                r"(?i)(signature|signed this|print\)|registration number"
                r"|authorized representative)",
                text,
            ):
                continue
            if len(text) < 60 and text.endswith(":"):
                continue
            if len(text) < 50 and not re.search(r"[.?!]", text):
                continue

            if "<" in passage:
                passage = re.sub(r"<[^>]+>", "", passage).strip()
                ev_item = {**ev_item, "text": passage}

            cleaned.append(ev_item)

        logger.info(
            "drift_wf_denoise_sentences",
            before=len(evidence),
            after=len(cleaned),
        )
        return cleaned

    async def _rerank_sentences(
        self,
        query: str,
        evidence: List[Dict[str, Any]],
        top_k: int = 15,
    ) -> List[Dict[str, Any]]:
        """Rerank denoised sentences using voyage-rerank-2.5."""
        rerank_model = os.getenv("ROUTE4_RERANK_MODEL", "rerank-2.5")

        try:
            import voyageai
            from src.core.config import settings

            vc = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
            documents = [ev_item.get("sentence_text") or ev_item.get("text", "") for ev_item in evidence]

            loop = asyncio.get_event_loop()
            executor = getattr(self.pipeline, "_executor", None)
            rr_result = await loop.run_in_executor(
                executor,
                lambda: vc.rerank(
                    query=query,
                    documents=documents,
                    model=rerank_model,
                    top_k=min(top_k, len(documents)),
                ),
            )

            reranked: List[Dict[str, Any]] = []
            for rr in rr_result.results:
                ev_item = {**evidence[rr.index], "rerank_score": rr.relevance_score}
                reranked.append(ev_item)

            logger.info(
                "drift_wf_rerank_complete",
                model=rerank_model,
                input_count=len(evidence),
                output_count=len(reranked),
            )
            return reranked

        except Exception:
            logger.exception("drift_wf_rerank_failed")
            raise

    async def _apply_coverage_gap_fill(
        self, query: str, evidence: List[Any]
    ) -> List[Dict[str, Any]]:
        """Stage 4.3.6: Ensure coverage of all documents in corpus."""
        if not self.pipeline.enhanced_retriever:
            return []
        
        try:
            # Build set of covered documents
            covered_docs: set = set()
            existing_chunk_ids: set = set()
            
            for ev in evidence:
                if isinstance(ev, dict):
                    meta = ev.get("metadata", {})
                    doc = meta.get("document_id") or meta.get("document_title") or ev.get("source")
                    if doc:
                        covered_docs.add(str(doc).strip().lower())
                    chunk_id = ev.get("id") or ev.get("chunk_id")
                    if chunk_id:
                        existing_chunk_ids.add(chunk_id)
            
            # Get all documents
            all_documents = await self.pipeline.enhanced_retriever.get_all_documents()
            total_docs = len(all_documents)
            
            if total_docs > 0 and len(covered_docs) >= total_docs:
                return []  # Already have full coverage
            
            # Get coverage chunks
            coverage_chunks = await self.pipeline.enhanced_retriever.get_coverage_chunks(
                max_per_document=1,
                max_total=min(total_docs * 2, 50),
                prefer_early_chunks=True,
            )
            
            # Filter to uncovered documents
            result: List[Dict[str, Any]] = []
            for chunk in coverage_chunks:
                doc_key = (chunk.document_id or chunk.document_source or "").strip().lower()
                if doc_key and doc_key in covered_docs:
                    continue
                if chunk.chunk_id in existing_chunk_ids:
                    continue
                
                result.append({
                    "id": chunk.chunk_id,
                    "text": chunk.text,
                    "source": chunk.document_source or chunk.document_title or "coverage",
                    "metadata": {
                        "document_id": chunk.document_id,
                        "document_title": chunk.document_title,
                        "is_coverage_chunk": True,
                    },
                })
                covered_docs.add(doc_key)
                existing_chunk_ids.add(chunk.chunk_id)
            
            if result:
                logger.info("drift_coverage_gap_fill", chunks_added=len(result))
            
            return result
            
        except Exception as e:
            logger.warning("drift_coverage_gap_fill_failed", error=str(e))
            return []
