"""
Hybrid Pipeline Orchestrator

Coordinates 4 distinct query routes:
1. Vector RAG - Fast lane for simple fact lookups
2. Local Search Equivalent - Entity-focused with LazyGraphRAG iterative deepening
3. Global Search Equivalent - Thematic queries with LazyGraphRAG + HippoRAG 2 PPR
4. DRIFT Equivalent - Multi-hop iterative reasoning for ambiguous queries

This is the main entry point for the Hybrid Architecture.

Profiles:
=========
- General Enterprise: All 4 routes (Route 1 default for simple queries)
- High Assurance: Routes 2, 3, 4 only (no Vector RAG shortcuts)

Model Selection by Route:
========================
Route 1 (Vector RAG):
  - Embeddings: text-embedding-3-large

Route 2 (Local Search):
  - Entity Extraction: NER or embedding match (deterministic)
  - LazyGraphRAG Iterative Deepening
  - Answer Synthesis: HYBRID_SYNTHESIS_MODEL (gpt-4o)

Route 3 (Global Search):
  - Community Matching: Embedding similarity (deterministic)
  - Hub Entity Extraction: Graph topology (deterministic)
  - HippoRAG PPR: Algorithmic (deterministic)
  - Answer Synthesis: HYBRID_SYNTHESIS_MODEL (gpt-5.2)

Route 4 (DRIFT Multi-Hop):
  - Query Decomposition: HYBRID_DECOMPOSITION_MODEL (gpt-4.1)
  - Entity Resolution: HYBRID_NER_MODEL (gpt-4o)
  - HippoRAG PPR: Algorithmic (deterministic)
  - Final Consolidation: HYBRID_SYNTHESIS_MODEL (gpt-5.2)

Router (all routes):
  - Query Classification: HYBRID_ROUTER_MODEL (gpt-4o-mini)
"""

from typing import Dict, Any, Optional, List, Tuple
import structlog
import asyncio
from concurrent.futures import ThreadPoolExecutor

from .pipeline.intent import IntentDisambiguator
from .pipeline.tracing import DeterministicTracer
from .pipeline.synthesis import EvidenceSynthesizer
from .pipeline.community_matcher import CommunityMatcher
from .pipeline.hub_extractor import HubExtractor
from .router.main import HybridRouter, QueryRoute, DeploymentProfile

# Import async Neo4j service for native async operations
try:
    from app.services.async_neo4j_service import AsyncNeo4jService
    ASYNC_NEO4J_AVAILABLE = True
except ImportError:
    ASYNC_NEO4J_AVAILABLE = False
    AsyncNeo4jService = None

logger = structlog.get_logger(__name__)


class HybridPipeline:
    """
    The main orchestrator for the 4-way routing system.
    
    Routes:
        1. Vector RAG - Simple fact lookups (General Enterprise only)
        2. Local Search - Entity-focused with LazyGraphRAG
        3. Global Search - Thematic with LazyGraphRAG + HippoRAG 2
        4. DRIFT Multi-Hop - Ambiguous queries with iterative decomposition
    
    Usage:
        pipeline = HybridPipeline(
            profile=DeploymentProfile.HIGH_ASSURANCE,
            llm_client=llm,
            hipporag_instance=hrag,
            ...
        )
        result = await pipeline.query("Analyze our risk exposure to tech vendors")
    """
    
    def __init__(
        self,
        profile: DeploymentProfile = DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=None,
        embedding_client=None,
        hipporag_instance=None,
        graph_store=None,
        neo4j_driver=None,
        text_unit_store=None,
        graph_communities: Optional[list] = None,
        communities_path: Optional[str] = None,
        relevance_budget: float = 0.8,
        group_id: str = "default"
    ):
        """
        Initialize the hybrid pipeline.
        
        Args:
            profile: Deployment profile (General Enterprise or High Assurance).
            llm_client: LLM client for query processing and synthesis.
            embedding_client: Embedding client for community matching.
            hipporag_instance: Initialized HippoRAG instance for tracing.
            graph_store: Graph database connection (Neo4j).
            neo4j_driver: Neo4j async driver for direct queries.
            text_unit_store: Store for raw text chunks.
            graph_communities: Community summaries for disambiguation.
            communities_path: Path to community data file.
            relevance_budget: 0.0-1.0, controls thoroughness vs speed.
            group_id: Tenant identifier.
        """
        self.profile = profile
        self.llm = llm_client
        self.relevance_budget = relevance_budget
        self.graph_communities = graph_communities
        self.group_id = group_id
        self.neo4j_driver = neo4j_driver

        # Cached one-time checks for Neo4j indexes used by Route 1
        self._textchunk_fulltext_index_checked = False
        
        # Thread pool for running sync Neo4j calls without blocking event loop
        # This is a production best practice when mixing sync I/O with async code
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="neo4j-sync")
        
        # Initialize async Neo4j service for native async operations (Route 2/3)
        self._async_neo4j: Optional[AsyncNeo4jService] = None
        if ASYNC_NEO4J_AVAILABLE:
            try:
                self._async_neo4j = AsyncNeo4jService.from_settings()
                logger.info("async_neo4j_service_configured")
            except Exception as e:
                logger.warning("async_neo4j_service_init_failed", error=str(e))
        
        # Initialize components
        self.router = HybridRouter(
            profile=profile,
            llm_client=llm_client
        )
        
        # Route 2: Entity disambiguation (for explicit entity queries)
        self.disambiguator = IntentDisambiguator(
            llm_client=llm_client,
            graph_communities=graph_communities
        )
        
        # Route 3: Community matching (for thematic queries)
        self.community_matcher = CommunityMatcher(
            embedding_client=embedding_client,
            communities_path=communities_path,
            group_id=group_id
        )
        
        # Route 3: Hub extraction (for seeding HippoRAG)
        self.hub_extractor = HubExtractor(
            graph_store=graph_store,
            neo4j_driver=neo4j_driver
        )
        
        # Routes 3 & 4: Deterministic tracing
        self.tracer = DeterministicTracer(
            hipporag_instance=hipporag_instance,
            graph_store=graph_store,
            async_neo4j=self._async_neo4j,
            group_id=group_id
        )
        
        # All routes: Synthesis
        self.synthesizer = EvidenceSynthesizer(
            llm_client=llm_client,
            text_unit_store=text_unit_store,
            relevance_budget=relevance_budget
        )
        
        logger.info("hybrid_pipeline_initialized",
                   profile=profile.value,
                   relevance_budget=relevance_budget,
                   has_hipporag=hipporag_instance is not None,
                   has_neo4j=neo4j_driver is not None,
                   has_async_neo4j=self._async_neo4j is not None,
                   has_community_matcher=embedding_client is not None,
                   group_id=group_id)
    
    async def initialize(self) -> None:
        """
        Initialize async resources (call once before queries).
        
        Connects the async Neo4j service for native async operations.
        """
        if self._async_neo4j:
            try:
                await self._async_neo4j.connect()
                logger.info("async_neo4j_connected")
            except Exception as e:
                logger.warning("async_neo4j_connection_failed", error=str(e))
                self._async_neo4j = None
    
    async def close(self) -> None:
        """
        Clean up async resources.
        
        Should be called when the pipeline is no longer needed.
        """
        if self._async_neo4j:
            try:
                await self._async_neo4j.close()
                logger.info("async_neo4j_closed")
            except Exception as e:
                logger.warning("async_neo4j_close_error", error=str(e))
        
        if self._executor:
            self._executor.shutdown(wait=False)
    
    async def __aenter__(self) -> "HybridPipeline":
        """Async context manager entry - initializes resources."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - cleans up resources."""
        await self.close()
    
    async def query(
        self,
        query: str,
        response_type: str = "detailed_report"
    ) -> Dict[str, Any]:
        """
        Execute a query through the appropriate route.
        
        Args:
            query: The user's natural language query.
            response_type: "detailed_report" | "summary" | "audit_trail"
            
        Returns:
            Dictionary containing:
            - response: The generated answer.
            - route_used: Which route was taken.
            - citations: Source citations (if Routes 2/3/4).
            - evidence_path: Entity path (if Routes 2/3/4).
            - metadata: Additional execution metadata.
        """
        # Step 0: Route the query
        route = await self.router.route(query)
        
        if route == QueryRoute.VECTOR_RAG:
            return await self._execute_route_1_vector_rag(query)
        elif route == QueryRoute.LOCAL_SEARCH:
            return await self._execute_route_2_local_search(query, response_type)
        elif route == QueryRoute.GLOBAL_SEARCH:
            return await self._execute_route_3_global_search(query, response_type)
        else:  # DRIFT_MULTI_HOP
            return await self._execute_route_4_drift(query, response_type)
    
    # =========================================================================
    # Route 1: Vector RAG (Fast Lane)
    # =========================================================================
    
    # Field intent → section/text keywords for negative detection
    # If query matches an intent and NO chunk contains these keywords,
    # we can confidently return "Not found" without LLM extraction.
    FIELD_SECTION_HINTS: Dict[str, List[str]] = {
        "vat_id": ["vat", "tax id", "tax i.d", "tax identification", "tin ", "v.a.t"],
        "payment_portal": ["payment portal", "pay online", "online payment", "pay here", "portal url"],
        "bank_routing": ["routing number", "routing #", "aba number", "aba #"],
        "iban_swift": ["iban", "swift", "bic", "international bank"],
        "bank_account": ["account number", "account #", "bank account", "acct #", "acct."],
        "wire_transfer": ["wire transfer", "wire instructions", "ach instructions", "bank transfer"],
        "license_number": ["license number", "license #", "licence no", "license no"],
        "mold_clause": ["mold", "mould", "fungus", "fungi"],
        "shipping_method": ["shipped via", "shipping method", "carrier", "delivery method"],
    }
    
    # Query patterns → field intent classification
    FIELD_INTENT_PATTERNS: Dict[str, List[str]] = {
        "vat_id": ["vat", "tax id", "tax i.d"],
        "payment_portal": ["payment portal", "pay online", "portal url"],
        "bank_routing": ["routing number", "routing #", "bank routing"],
        "iban_swift": ["iban", "swift", "bic"],
        "bank_account": ["account number", "bank account"],
        "wire_transfer": ["wire transfer", "ach instruction", "wire instruction"],
        "license_number": ["license number", "agent's license", "licence"],
        "mold_clause": ["mold damage", "mold coverage", "mould"],
        "shipping_method": ["shipping method", "shipped via"],
    }
    
    def _classify_field_intent(self, query: str) -> Optional[str]:
        """Classify query into a field intent for negative detection."""
        query_lower = query.lower()
        for intent, patterns in self.FIELD_INTENT_PATTERNS.items():
            if any(p in query_lower for p in patterns):
                return intent
        return None
    
    async def _check_field_exists_in_chunks(
        self,
        query: str,
        chunks_with_scores: List[Tuple[Dict, float]],
        doc_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Graph-based existence check: Does the document contain the requested field?
        
        This is a lightweight section-based check using existing Azure DI metadata.
        If the query asks for a specific field type (VAT, payment portal, etc.) and
        NO chunk from the target document contains relevant keywords in its text
        or section_path, we can confidently return "Not found" without LLM.
        
        Args:
            query: The user query
            chunks_with_scores: Retrieved chunks with similarity scores
            doc_id: Optional document ID to restrict check to
            
        Returns:
            (exists, intent): Whether field likely exists, and detected intent
        """
        intent = self._classify_field_intent(query)
        if not intent:
            # Unknown intent → can't do negative detection, proceed with LLM
            return (True, None)
        
        hints = self.FIELD_SECTION_HINTS.get(intent, [])
        if not hints:
            return (True, intent)
        
        # Check if ANY chunk from the target document contains the hint keywords
        for chunk, score in chunks_with_scores:
            # If doc_id specified, only check chunks from that document
            if doc_id and chunk.get("document_id") != doc_id:
                continue
            
            # Check chunk text for hint keywords
            chunk_text_lower = (chunk.get("text") or "").lower()
            if any(h in chunk_text_lower for h in hints):
                logger.info(
                    "field_existence_check_found",
                    intent=intent,
                    hint_matched=next(h for h in hints if h in chunk_text_lower),
                    chunk_id=chunk.get("id"),
                )
                return (True, intent)
            
            # Check section_path metadata if available
            section_path = chunk.get("section_path") or chunk.get("metadata", {}).get("section_path") or []
            if isinstance(section_path, list):
                section_text = " ".join(section_path).lower()
                if any(h in section_text for h in hints):
                    logger.info(
                        "field_existence_check_found_in_section",
                        intent=intent,
                        section_path=section_path,
                        chunk_id=chunk.get("id"),
                    )
                    return (True, intent)
        
        # No chunk contains the expected field keywords → field doesn't exist
        logger.info(
            "field_existence_check_not_found",
            intent=intent,
            hints_checked=hints,
            chunks_checked=len(chunks_with_scores),
            doc_id=doc_id,
        )
        return (False, intent)
    
    async def _check_field_exists_in_evidence(
        self,
        query: str,
        evidence_nodes: List[Dict[str, Any]],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a requested field exists in evidence nodes (Route 2/3 negative detection).
        
        Returns:
            (field_exists, intent):
            - (True, intent): Field found or unknown intent (proceed with LLM)
            - (False, intent): Field definitely doesn't exist (skip LLM, return "Not found")
        """
        intent = self._classify_field_intent(query)
        if not intent:
            # Unknown intent → can't do negative detection, proceed with LLM
            return (True, None)
        
        hints = self.FIELD_SECTION_HINTS.get(intent, [])
        if not hints:
            return (True, intent)
        
        # Check if ANY evidence node contains the hint keywords
        for item in evidence_nodes:
            # Handle both dict and (dict, score) tuple formats
            if isinstance(item, tuple):
                node, score = item
            else:
                node = item
            
            # Evidence nodes have 'text' field
            node_text_lower = (node.get("text") or "").lower()
            if any(h in node_text_lower for h in hints):
                logger.info(
                    "field_existence_check_found_in_evidence",
                    intent=intent,
                    hint_matched=next(h for h in hints if h in node_text_lower),
                    node_id=node.get("id"),
                )
                return (True, intent)
            
            # Also check section_path if available
            section_path = node.get("section_path") or []
            if isinstance(section_path, list):
                section_text = " ".join(section_path).lower()
                if any(h in section_text for h in hints):
                    logger.info(
                        "field_existence_check_found_in_evidence_section",
                        intent=intent,
                        section_path=section_path,
                        node_id=node.get("id"),
                    )
                    return (True, intent)
        
        # No evidence node contains the expected field keywords → field doesn't exist
        logger.info(
            "field_existence_check_not_found_in_evidence",
            intent=intent,
            hints_checked=hints,
            evidence_nodes_checked=len(evidence_nodes),
        )
        return (False, intent)
    
    async def _execute_route_1_vector_rag(self, query: str) -> Dict[str, Any]:
        """
        Route 1: Simple Vector RAG for fast fact lookups.
        
        Best for: "What is X's address?", "How much is invoice Y?"
        Profile: General Enterprise only (disabled in High Assurance)
        
        Implementation: Searches TextChunk nodes in Neo4j for exact text retrieval.
        Uses concise prompts to return direct factual answers.
        
        Enhanced with Graph-Based Negative Detection:
        - Classifies query intent (VAT, payment portal, etc.)
        - Checks if target document contains relevant section/keywords
        - If not found, returns "Not found" immediately (no LLM hallucination risk)
        
        Fallback Strategy:
        ==================
        If Neo4j or embeddings are unavailable, fall back to Route 2 (Local Search).
        """
        logger.info("route_1_vector_rag_start", query=query[:50])
        
        # Check if we have required components for vector search
        if not self.neo4j_driver:
            logger.warning("vector_rag_neo4j_unavailable_fallback_to_route_2",
                          reason="Neo4j driver not available")
            return await self._execute_route_2_local_search(query, "summary")
        
        try:
            # Get query embedding
            from app.services.llm_service import LLMService
            llm_service = LLMService()
            
            if llm_service.embed_model is None:
                logger.warning("vector_rag_embedding_unavailable",
                              reason="Embedding model not initialized, deriving from group chunks")
                # Local/dev fallback: derive an approximate embedding from in-group chunks.
                query_embedding = await self._derive_query_embedding_from_group_chunks(query)
                if query_embedding:
                    logger.info("vector_rag_derived_embedding_success", 
                               embedding_dims=len(query_embedding))
                else:
                    logger.warning("vector_rag_derived_embedding_failed",
                                  reason="Could not derive embedding from group chunks")
            else:
                try:
                    query_embedding = llm_service.embed_model.get_text_embedding(query)
                    logger.info("vector_rag_embedding_success",
                               embedding_dims=len(query_embedding) if query_embedding else 0,
                               embedding_first_3=query_embedding[:3] if query_embedding else None)
                except Exception as e:
                    logger.warning(
                        "vector_rag_embedding_failed_deriving_from_group",
                        error=str(e),
                        reason="Embedding generation failed; deriving from group chunks",
                    )
                    query_embedding = await self._derive_query_embedding_from_group_chunks(query)
                    if query_embedding:
                        logger.info("vector_rag_derived_embedding_success_after_failure",
                                   embedding_dims=len(query_embedding))
                    else:
                        logger.warning("vector_rag_derived_embedding_failed_after_failure",
                                      reason="Could not derive embedding from group chunks")
            
            # Retrieval: Hybrid RRF (vector + fulltext) for best precision
            # Fulltext catches exact keyword matches, vector catches semantic similarity
            results = []
            if query_embedding is not None:
                results = await self._search_text_chunks_hybrid_rrf(
                    query_text=query,
                    embedding=query_embedding,
                    top_k=15,
                    vector_k=25,
                    fulltext_k=25,
                )
            else:
                logger.warning(
                    "vector_rag_no_query_embedding",
                    reason="No query embedding available after derivation",
                )
                # If we cannot compute an embedding, fall back to fulltext-only search in Neo4j.
                results = await self._search_text_chunks_fulltext(
                    query_text=query,
                    top_k=15,
                )
            
            if not results:
                return {
                    "response": "No relevant text found for this query.",
                    "route_used": "route_1_vector_rag",
                    "citations": [],
                    "evidence_path": [],
                    "metadata": {
                        "num_chunks": 0,
                        "latency_estimate": "fast",
                        "precision_level": "standard",
                        "route_description": "Vector search on text chunks"
                    }
                }
            
            # Build context from text chunks
            context_parts = []
            citations = []
            
            for i, (chunk, score) in enumerate(results[:8], 1):  # Use top 8 for context
                context_parts.append(f"[{i}] (Score: {score:.2f}) {chunk['text']}")
                citations.append({
                    "index": i,
                    "chunk_id": chunk["id"],
                    "document_id": chunk.get("document_id", ""),
                    "document_title": chunk.get("document_title", ""),
                    "score": float(score),
                    "text_preview": chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"]
                })
            
            context = "\n\n".join(context_parts)
            
            # ================================================================
            # GRAPH-BASED NEGATIVE DETECTION (Pre-LLM Check)
            # ================================================================
            # Before calling LLM, check if the requested field exists in the
            # document. This prevents hallucinations for negative questions.
            # ================================================================
            top_doc_id = results[0][0].get("document_id") if results else None
            field_exists, detected_intent = await self._check_field_exists_in_chunks(
                query=query,
                chunks_with_scores=results,
                doc_id=top_doc_id,
            )
            
            if not field_exists and detected_intent:
                # Field doesn't exist in document → deterministic "Not found"
                logger.info(
                    "route_1_negative_detection_triggered",
                    intent=detected_intent,
                    doc_id=top_doc_id,
                    reason="Field keywords not found in document chunks",
                )
                return {
                    "response": "Not found in the provided documents.",
                    "route_used": "route_1_vector_rag",
                    "citations": citations,
                    "evidence_path": [],
                    "metadata": {
                        "num_chunks": len(results),
                        "chunks_used": len(context_parts),
                        "latency_estimate": "fast",
                        "precision_level": "standard",
                        "route_description": "Vector search with graph-based negative detection",
                        "negative_detection": True,
                        "detected_intent": detected_intent,
                        "debug_top_chunk_id": results[0][0]["id"] if results else None,
                        "debug_top_chunk_preview": results[0][0]["text"][:100] if results else None,
                    }
                }
            
            # ================================================================
            # Route 1 Strategy: Extract from TOP-RANKED chunk only using LLM
            # ================================================================
            # This combines the precision of "Top Chunk" focus (avoiding cross-doc pollution)
            # with the adaptability of LLM (handling synonyms, implied values, unstructured text).
            
            # Extract from top chunk only (most relevant)
            llm_answer = await self._extract_with_llm_from_top_chunk(query, results)
            
            if llm_answer:
                logger.info("route_1_llm_extraction_success", 
                           answer=llm_answer[:50],
                           from_top_chunk=True)
                answer = llm_answer
            else:
                # If LLM can't extract, return "not found"
                logger.info("route_1_llm_extraction_failed",
                           query=query[:100])
                answer = "Not found in the provided documents."
            
            return {
                "response": answer,
                "route_used": "route_1_vector_rag",
                "citations": citations,
                "evidence_path": [],
                "metadata": {
                    "num_chunks": len(results),
                    "chunks_used": len(context_parts),
                    "latency_estimate": "fast",
                    "precision_level": "standard",
                    "route_description": "Vector search on text chunks with LLM extraction",
                    "debug_top_chunk_id": results[0][0]["id"] if results else None,
                    "debug_top_chunk_preview": results[0][0]["text"][:100] if results else None
                }
            }
            
        except Exception as e:
            logger.error("route_1_failed_fallback_to_route_2",
                        error=str(e),
                        reason="Vector RAG execution failed")
            # Fallback to Route 2 (graph-based) for reliability
            result = await self._execute_route_2_local_search(query, "summary")
            # Mark that this was a fallback execution
            result["metadata"]["fallback_from"] = "route_1_vector_rag"
            result["metadata"]["fallback_reason"] = str(e)
            return result

    async def _extract_with_llm_from_top_chunk(
        self,
        query: str,
        chunks_with_scores: list
    ) -> Optional[str]:
        """
        Extract answer from TOP-RANKED chunk using LLM (Temperature 0).
        
        Strategy: 
        1. Take the highest scoring chunk (Rank 1).
        2. Feed it to LLM with a strict extraction prompt.
        3. This avoids "pollution" from lower-ranked chunks (other documents).
        4. This avoids "brittle regex" (NLP) issues by letting LLM handle language nuances.
        """
        if not chunks_with_scores:
            return None
        
        # If a candidate fails verification, discard it (never return it) and
        # optionally try the next-best chunks under the same verification gate.
        max_chunks_to_try = 3

        # Route 1 must avoid cross-document pollution. If we fall back to other
        # chunks, only consider chunks from the same document as the top-ranked
        # chunk (e.g., later chunks of the same PDF).
        primary_document_id = None
        try:
            primary_document_id = (chunks_with_scores[0][0] or {}).get("document_id")
        except Exception:
            primary_document_id = None

        def _has_marker_near_answer(
            evidence_text_lower: str,
            answer_lower: str,
            markers_lower: list[str],
            window: int = 80,
        ) -> bool:
            if not evidence_text_lower or not answer_lower or not markers_lower:
                return False
            start = 0
            while True:
                idx = evidence_text_lower.find(answer_lower, start)
                if idx == -1:
                    return False
                left = max(0, idx - window)
                right = min(len(evidence_text_lower), idx + len(answer_lower) + window)
                window_text = evidence_text_lower[left:right]
                # Ensure markers are outside of the answer itself (e.g., avoid matching
                # "portal" from inside "/portal/" in the URL).
                window_text_wo_answer = window_text.replace(answer_lower, " ")
                if any(m in window_text_wo_answer for m in markers_lower):
                    return True
                start = idx + len(answer_lower)

        def _looks_like_url_or_email(text: str) -> bool:
            lower = text.lower()
            if "http://" in lower or "https://" in lower or lower.startswith("www."):
                return True
            # lightweight email heuristic (avoid regex)
            if "@" in text and "." in text.split("@", 1)[-1]:
                return True
            return False

        try:
            from app.services.llm_service import LLMService
            import re
            llm_service = LLMService()

            stopwords = {
                "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
                "is", "are", "was", "were", "be", "been", "this", "that", "these", "those",
                "what", "which", "who", "whom", "where", "when", "why", "how",
            }
            query_keywords = []
            for token in re.findall(r"[A-Za-z0-9]+", query.lower()):
                if len(token) < 3:
                    continue
                if token in stopwords:
                    continue
                query_keywords.append(token)
            query_keywords = sorted(set(query_keywords))

            tried = 0
            for rank, (chunk, score) in enumerate(chunks_with_scores, start=1):
                if tried >= max_chunks_to_try:
                    break

                if primary_document_id:
                    if (chunk or {}).get("document_id") != primary_document_id:
                        continue

                tried += 1
                top_chunk = chunk["text"]

                logger.info(
                    "llm_extracting_from_top_chunk",
                    query=query[:50],
                    chunk_rank=rank,
                    chunk_score=float(score),
                    chunk_preview=top_chunk[:100],
                )

                prompt = f"""
You are a precise data extraction engine.
Context:
{top_chunk}

User Query: {query}

Instructions:
1. Extract the EXACT answer from the context above.
2. If the answer is a specific value (price, date, name, ID), return ONLY that value.
3. If the query asks for a total/amount and multiple exist, look for "Total", "Amount Due", or "Balance".
4. Do not generate conversational text. Just the value.
5. Do not guess or hallucinate. Only extract if explicitly stated in the text.
6. If the answer is not explicitly present in the provided context, you MUST return "Not found".
"""

                response = llm_service.generate(prompt, temperature=0.0)
                cleaned_response = response.strip()

                # If model says Not found, treat as no answer and try next chunk.
                if "not found" in cleaned_response.lower() and len(cleaned_response) < 30:
                    continue

                # Fast deterministic grounding for URLs/emails: must be exact substring.
                if _looks_like_url_or_email(cleaned_response):
                    if cleaned_response not in top_chunk:
                        logger.warning(
                            "llm_candidate_rejected_by_exact_grounding",
                            candidate=cleaned_response,
                            reason="URL/email must appear exactly in the source chunk",
                            chunk_rank=rank,
                        )
                        continue

                # ---------------------------------------------------------
                # VERIFICATION STEP (Anti-Hallucination)
                # ---------------------------------------------------------
                # If verifier says NO, discard candidate and try next chunk.
                # ---------------------------------------------------------
                verify_prompt = f"""
Verification Task.

Context:
{top_chunk[:2000]}

Question: {query}
Proposed Answer: {cleaned_response}

Your job:
1. Decide if the Proposed Answer is explicitly supported as the answer to the Question.
2. If YES, provide an exact verbatim quote from the Context that proves it.

Rules:
- The evidence quote MUST be copied exactly from the Context.
- The evidence quote MUST contain the Proposed Answer exactly.
- If the Context contains the Proposed Answer but it is NOT answering the Question (e.g., it's a different ID/URL), reply NO.

Reply in exactly two lines:
VERDICT: YES or NO
EVIDENCE: <verbatim quote from Context, or empty>
"""

                verification_raw = llm_service.generate(verify_prompt, temperature=0.0).strip()
                verdict = ""
                evidence = ""
                for line in verification_raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    upper = line.upper()
                    if upper.startswith("VERDICT:"):
                        verdict = line.split(":", 1)[-1].strip().upper()
                    elif upper.startswith("EVIDENCE:"):
                        evidence = line.split(":", 1)[-1].strip()

                if verdict != "YES":
                    logger.warning(
                        "llm_verification_failed",
                        candidate=cleaned_response,
                        reason="Verifier rejected answer",
                        chunk_rank=rank,
                    )
                    continue

                evidence_ok = True
                if not evidence:
                    evidence_ok = False
                elif evidence not in top_chunk:
                    evidence_ok = False
                elif cleaned_response not in evidence:
                    evidence_ok = False
                elif query_keywords:
                    evidence_lower = evidence.lower()
                    if not any(k in evidence_lower for k in query_keywords):
                        evidence_ok = False

                # Extra precision: ensure evidence contains an explicit label that
                # matches the question intent (not just an answer-shaped string).
                if evidence_ok:
                    query_lower = query.lower()
                    evidence_lower = evidence.lower()
                    answer_lower = cleaned_response.lower()
                    evidence_without_answer = evidence_lower.replace(answer_lower, " ")

                    required_markers: list[str] = []
                    # Payment portal URLs: require explicit "pay online"/"portal" wording outside the URL.
                    if (
                        "payment portal" in query_lower
                        or ("portal" in query_lower and "url" in query_lower)
                        or ("payment" in query_lower and "url" in query_lower)
                        or "pay online" in query_lower
                    ):
                        required_markers = [
                            "pay online",
                            "online payment",
                            "payment portal",
                            "pay here",
                            "make a payment",
                            "portal",
                        ]

                    # VAT / Tax ID: require explicit ID labeling (avoid matching generic "tax" amounts).
                    if ("vat" in query_lower) or ("tax id" in query_lower) or ("tax i.d" in query_lower):
                        required_markers = [
                            "vat",
                            "tax id",
                            "tax i.d",
                            "tax identification",
                            "tin",
                        ]

                    if required_markers:
                        # Require the marker to appear close to the answer (not merely
                        # somewhere else in a large multi-line quote).
                        if not _has_marker_near_answer(
                            evidence_text_lower=evidence_lower,
                            answer_lower=answer_lower,
                            markers_lower=required_markers,
                            window=80,
                        ):
                            evidence_ok = False

                        # Backstop: if the verifier didn't include the marker anywhere
                        # outside of the answer, also reject.
                        if evidence_ok and not any(m in evidence_without_answer for m in required_markers):
                            evidence_ok = False

                if not evidence_ok:
                    logger.warning(
                        "llm_verification_failed",
                        candidate=cleaned_response,
                        reason="Verifier did not provide valid grounded evidence",
                        chunk_rank=rank,
                    )
                    continue

                logger.info(
                    "llm_extraction_verified",
                    candidate=cleaned_response[:80],
                    chunk_rank=rank,
                    document_id=(chunk or {}).get("document_id"),
                    chunk_id=(chunk or {}).get("id"),
                )

                return cleaned_response

            return None

        except Exception as e:
            logger.error("llm_extraction_error", error=str(e))
            return None

    # Deprecated: NLP/Regex extraction (kept for reference but unused)
    def _extract_with_nlp_from_top_chunk_deprecated(
        self,
        query: str,
        chunks_with_scores: list
    ) -> Optional[str]:
        """
        Extract answer from TOP-RANKED chunk only using document-agnostic patterns.
        
        Strategy: Trust hybrid search ranking to put best chunk first.
        Extract the requested value type (date, amount, ID, name) from that chunk.
        
        This ensures:
        - Deterministic answers (same top chunk → same result)
        - No confusion from multiple documents
        - Fast extraction without LLM
        """
        import re
        
        if not chunks_with_scores:
            return None
        
        # Extract from TOP chunk only (rank 1)
        top_chunk = chunks_with_scores[0][0]["text"]
        query_lower = query.lower()
        
        logger.info("nlp_extracting_from_top_chunk",
                   query=query[:50],
                   chunk_preview=top_chunk[:100])
        
        # IMPORTANT: Check patterns in priority order based on query keywords
        # Money queries should be checked BEFORE ID patterns to avoid confusion
        
        # Pattern 1: Currency amounts - Check FIRST for money queries
        if any(kw in query_lower for kw in ["amount", "total", "price", "cost", "fee", "payment", "rate", "dollar", "$"]):
            # Strategy A: Look for explicit currency symbols ($)
            pattern_currency = r'\$\s*([\d,]+\.?\d{0,2})'
            matches_currency = re.findall(pattern_currency, top_chunk)
            
            # Strategy B: Look for numbers that look like currency (123.45) near keywords like "Total"
            # This handles tables where $ might be in the header but not the row
            pattern_implied = r'(?:Total|Amount|Price|Cost|Due)\s*[:\n]?\s*([\d,]+\.\d{2})\b'
            matches_implied = re.findall(pattern_implied, top_chunk, re.IGNORECASE)
            
            all_matches = []
            
            # Add currency matches (high confidence)
            for m in matches_currency:
                try:
                    val = float(m.replace(',', '').replace(' ', ''))
                    all_matches.append((val, "$" + m, 'currency'))
                except: continue
                
            # Add implied matches (medium confidence)
            for m in matches_implied:
                try:
                    val = float(m.replace(',', '').replace(' ', ''))
                    # Avoid duplicates
                    if not any(existing[0] == val for existing in all_matches):
                        all_matches.append((val, "$" + m, 'implied'))
                except: continue

            if all_matches:
                # If query asks for "total", prefer largest amount
                if "total" in query_lower or "amount" in query_lower:
                    # Sort by value descending
                    best_match = max(all_matches, key=lambda x: x[0])
                    logger.info("nlp_found_amount", result=best_match[1], source=best_match[2])
                    return best_match[1]
                else:
                    # Return first match found
                    logger.info("nlp_found_amount", result=all_matches[0][1])
                    return all_matches[0][1]
        
        # Pattern 2: Invoice/PO/Registration/License numbers - Only check if NOT a money query
        if any(kw in query_lower for kw in ["number", "#", "invoice", "po", "p.o.", "registration", "license"]) and not any(kw in query_lower for kw in ["amount", "total", "price", "cost", "fee", "payment"]):
            # Look for common ID patterns
            patterns = [
                r'\b\d{8}\b',  # 8 digits (like 30060204)
                r'\b[A-Z]{3,5}-\d{4,6}\b',  # REG-54321, INV-12345
                r'#\s*(\d+)',  # # followed by digits
                r'\b\d{7}\b',  # 7 digits (like 1256003)
            ]
            for pattern in patterns:
                match = re.search(pattern, top_chunk)
                if match:
                    result = match.group(1) if match.lastindex else match.group(0)
                    logger.info("nlp_found_id", pattern=pattern, result=result)
                    return result
        
        # Pattern 3: Dates - Find ANY date in standard formats (check before general number patterns)
        if any(kw in query_lower for kw in ["date", "when", "day"]) and not any(kw in query_lower for kw in ["amount", "total", "number"]):
            patterns = [
                r'\b\d{1,2}/\d{1,2}/\d{4}\b',  # MM/DD/YYYY
                r'\b\d{4}-\d{2}-\d{2}\b',      # YYYY-MM-DD
                r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b',
            ]
            for pattern in patterns:
                match = re.search(pattern, top_chunk, re.IGNORECASE)
                if match:
                    logger.info("nlp_found_date", result=match.group(0))
                    return match.group(0)
        
        # Pattern 4: Names - Find proper nouns (capitalized words)
        if any(kw in query_lower for kw in ["who", "name", "salesperson", "vendor", "agent", "client", "customer", "owner", "builder"]):
            # Look for 2-3 consecutive capitalized words (typical names)
            pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b'
            matches = re.findall(pattern, top_chunk)
            if matches:
                # Return first name found (trust top chunk ranking)
                # Filter out common non-name words
                exclude = {"The", "This", "That", "Invoice", "Contract", "Agreement", "Document", "Date", "Total", "Amount"}
                names = [m for m in matches if m not in exclude]
                if names:
                    logger.info("nlp_found_name", result=names[0])
                    return names[0]
        
        # Pattern 5: Durations/periods - Find time periods
        if any(kw in query_lower for kw in ["how long", "how many", "duration", "period", "warranty", "term", "days", "months", "years"]):
            patterns = [
                r'\b\d+\s*(?:day|month|year)s?\b',  # "90 days", "2 years"
                r'\b\d+\s*(?:hour|hr)s?\b',  # "hours"
            ]
            for pattern in patterns:
                match = re.search(pattern, top_chunk, re.IGNORECASE)
                if match:
                    logger.info("nlp_found_duration", result=match.group(0))
                    return match.group(0)
        
        # Pattern 6: Payment terms
        if "terms" in query_lower or "payment" in query_lower:
            patterns = [
                r'(?:due|payable)\s+(?:on|upon)\s+[^.]{5,40}',  # "due on contract signing"
                r'net\s+\d+',  # "Net 30"
            ]
            for pattern in patterns:
                match = re.search(pattern, top_chunk, re.IGNORECASE)
                if match:
                    logger.info("nlp_found_terms", result=match.group(0))
                    return match.group(0)
        
        logger.info("nlp_no_pattern_matched", query=query[:100])
        return None

    def _extract_with_nlp(
        self,
        query: str,
        chunks_with_scores: list
    ) -> Optional[str]:
        """
        OLD METHOD: Extract from multiple chunks (kept for backwards compatibility).
        Prefer _extract_with_nlp_from_top_chunk() for Route 1.
        """
        import re
        
        if not chunks_with_scores:
            return None
        
        # Combine top chunks for pattern matching
        combined_text = " ".join([
            chunk["text"] for chunk, _ in chunks_with_scores[:5]
        ])
        
        query_lower = query.lower()
        
        # Pattern 1: Invoice/PO/Registration numbers
        if any(keyword in query_lower for keyword in ["invoice number", "po number", "p.o. number", "registration number", "license number"]):
            patterns = [
                r'(?:invoice|po|p\.?o\.?|registration|license)\s*(?:number|#|no\.?)?\s*:?\s*([A-Z0-9\-]+)',
                r'#\s*([A-Z0-9\-]+)',
                r'REG-\d+',
            ]
            for pattern in patterns:
                match = re.search(pattern, combined_text, re.IGNORECASE)
                if match:
                    return match.group(1) if match.lastindex else match.group(0)
        
        # Pattern 2: Currency amounts (total, price, amount, payment)
        if any(keyword in query_lower for keyword in ["total", "amount", "price", "cost", "payment", "fee"]):
            # Look for $ followed by numbers with optional commas and decimals
            pattern = r'\$[\d,]+\.?\d*'
            matches = re.findall(pattern, combined_text)
            if matches:
                # If multiple matches, prefer the largest (likely the total)
                amounts = []
                for m in matches:
                    try:
                        val = float(m.replace('$', '').replace(',', ''))
                        amounts.append((val, m))
                    except:
                        continue
                if amounts:
                    if "total" in query_lower:
                        # Return largest amount for "total" queries
                        return max(amounts, key=lambda x: x[0])[1]
                    else:
                        # Return first match for other queries
                        return matches[0]
        
        # Pattern 3: Dates
        if any(keyword in query_lower for keyword in ["date", "when", "begin", "start", "due", "expir"]):
            patterns = [
                r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY
                r'\d{4}-\d{2}-\d{2}',      # YYYY-MM-DD
                r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
            ]
            for pattern in patterns:
                match = re.search(pattern, combined_text, re.IGNORECASE)
                if match:
                    return match.group(0)
        
        # Pattern 4: Names (after keywords like "salesperson:", "vendor:", "agent:")
        if any(keyword in query_lower for keyword in ["salesperson", "vendor", "agent", "builder", "owner", "issued by"]):
            patterns = [
                r'(?:salesperson|vendor|agent|builder|owner|issued by)\s*:?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            ]
            for pattern in patterns:
                match = re.search(pattern, combined_text, re.IGNORECASE)
                if match:
                    return match.group(1)
        
        # Pattern 5: Duration/period (warranty, term)
        if any(keyword in query_lower for keyword in ["warranty", "period", "duration", "term"]):
            patterns = [
                r'(\d+)\s*(?:days?|months?|years?)',
                r'(\d+)-(?:day|month|year)',
            ]
            for pattern in patterns:
                match = re.search(pattern, combined_text, re.IGNORECASE)
                if match:
                    return match.group(0)
        
        # Pattern 6: Terms/conditions
        if "terms" in query_lower or "payment terms" in query_lower:
            # Look for common payment terms
            patterns = [
                r'(?:due|payable)\s+(?:on|upon)\s+[^.]+',
                r'net\s+\d+',
                r'\d+%\s+down',
            ]
            for pattern in patterns:
                match = re.search(pattern, combined_text, re.IGNORECASE)
                if match:
                    return match.group(0)
        
        # No pattern matched
        return None

    def _sanitize_query_for_fulltext(self, query: str) -> str:
        """Sanitize query for Lucene fulltext index.

        Neo4j fulltext indexes use Lucene syntax. Certain characters are operators and
        can cause parse errors or unintended semantics.
        """
        if not query:
            return ""
        # Keep alphanumerics and whitespace; replace other characters with spaces.
        out = []
        for ch in query:
            if ch.isalnum() or ch.isspace():
                out.append(ch)
            else:
                out.append(" ")
        # Collapse repeated whitespace
        return " ".join("".join(out).split())

    async def _ensure_textchunk_fulltext_index(self) -> None:
        """Ensure the TextChunk fulltext index exists.

        Uses an index name that won't collide with other schemas (e.g., __Node__ based).
        """
        if self._textchunk_fulltext_index_checked:
            return
        self._textchunk_fulltext_index_checked = True

        if not self.neo4j_driver:
            return

        def _run_sync():
            with self.neo4j_driver.session() as session:
                session.run(
                    "CREATE FULLTEXT INDEX textchunk_fulltext IF NOT EXISTS FOR (c:TextChunk) ON EACH [c.text]"
                )

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, _run_sync)
        except Exception as e:
            # Don't fail Route 1 if index creation isn't permitted in the environment.
            logger.warning(
                "textchunk_fulltext_index_ensure_failed",
                error=str(e),
                reason="Could not ensure fulltext index; will continue with available retrieval",
            )

    async def _search_text_chunks_fulltext(self, query_text: str, top_k: int = 10) -> list:
        """Fulltext search only (Neo4j Lucene index) within the group."""
        if not self.neo4j_driver:
            return []

        await self._ensure_textchunk_fulltext_index()
        group_id = self.group_id
        sanitized = self._sanitize_query_for_fulltext(query_text)
        if not sanitized:
            return []

        def _run_sync():
            q = """
            CALL db.index.fulltext.queryNodes('textchunk_fulltext', $query_text, {limit: $top_k})
            YIELD node, score
            WHERE node.group_id = $group_id
            OPTIONAL MATCH (node)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN node.id AS id,
                   node.text AS text,
                   node.chunk_index AS chunk_index,
                   d.id AS document_id,
                   d.title AS document_title,
                   d.source AS document_source,
                   score
            ORDER BY score DESC
            LIMIT $top_k
            """
            rows = []
            with self.neo4j_driver.session() as session:
                for r in session.run(q, query_text=sanitized, group_id=group_id, top_k=top_k):
                    chunk = {
                        "id": r["id"],
                        "text": r["text"],
                        "chunk_index": r.get("chunk_index", 0),
                        "document_id": r.get("document_id", ""),
                        "document_title": r.get("document_title", ""),
                        "document_source": r.get("document_source", ""),
                    }
                    rows.append((chunk, float(r.get("score") or 0.0)))
            return rows

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _run_sync)

    async def _search_text_chunks_hybrid_rrf(
        self,
        query_text: str,
        embedding: list,
        top_k: int = 10,
        vector_k: int = 25,
        fulltext_k: int = 25,
        rrf_k: int = 60,
    ) -> list:
        """Neo4j-native hybrid retrieval + RRF fusion.

        Runs vector search (chunk_embedding) + fulltext search (textchunk_fulltext)
        and fuses them with Reciprocal Rank Fusion inside Cypher.
        """
        if not self.neo4j_driver:
            return []

        await self._ensure_textchunk_fulltext_index()
        group_id = self.group_id
        sanitized = self._sanitize_query_for_fulltext(query_text)
        
        # DEBUG: Log the vector search parameters
        logger.info("hybrid_rrf_vector_search_debug",
                   group_id=group_id,
                   embedding_dims=len(embedding) if embedding else 0,
                   embedding_first_3=embedding[:3] if embedding else None,
                   vector_k=vector_k,
                   query_text=query_text[:100])

        # Oversample vector candidates before tenant filter.
        oversample_factor = 50
        oversample_cap = 2000
        candidate_k = min(max(vector_k, vector_k * oversample_factor), oversample_cap)

        def _run_sync():
            q = """
            // Vector candidates (global topK -> tenant filter)
                        CALL () {
                            WITH $candidate_k AS candidate_k, $embedding AS embedding, $group_id AS group_id
              CALL db.index.vector.queryNodes('chunk_embedding', candidate_k, embedding)
              YIELD node, score
              WHERE node.group_id = group_id
              WITH node, score
              ORDER BY score DESC
                            LIMIT $vector_k
              WITH collect(node) AS nodes
              UNWIND range(0, size(nodes)-1) AS i
              RETURN nodes[i] AS node, (i + 1) AS rank
            }
            WITH collect({node: node, rank: rank}) AS vectorList

            // Fulltext candidates (tenant filter)
                        CALL () {
                            WITH $query_text AS query_text, $group_id AS group_id
                            CALL db.index.fulltext.queryNodes('textchunk_fulltext', query_text, {limit: $fulltext_k})
              YIELD node, score
              WHERE node.group_id = group_id
              WITH node, score
              ORDER BY score DESC
                            LIMIT $fulltext_k
              WITH collect(node) AS nodes
              UNWIND range(0, size(nodes)-1) AS i
              RETURN nodes[i] AS node, (i + 1) AS rank
            }
            WITH vectorList, collect({node: node, rank: rank}) AS lexList

            // Union + RRF fusion
            WITH vectorList, lexList,
                 [x IN vectorList | x.node] + [y IN lexList | y.node] AS allNodes
            UNWIND allNodes AS node
            WITH DISTINCT node, vectorList, lexList
            WITH node,
                 [v IN vectorList WHERE v.node = node | v.rank][0] AS vRank,
                 [l IN lexList WHERE l.node = node | l.rank][0] AS lRank
            WITH node,
                 (CASE WHEN vRank IS NULL THEN 0.0 ELSE 1.0 / ($rrf_k + vRank) END) +
                 (CASE WHEN lRank IS NULL THEN 0.0 ELSE 1.0 / ($rrf_k + lRank) END) AS rrfScore
            OPTIONAL MATCH (node)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN node.id AS id,
                   node.text AS text,
                   node.chunk_index AS chunk_index,
                   d.id AS document_id,
                   d.title AS document_title,
                   d.source AS document_source,
                   rrfScore AS score
            ORDER BY score DESC
            LIMIT $top_k
            """

            rows = []
            try:
                with self.neo4j_driver.session() as session:
                    for r in session.run(
                        q,
                        group_id=group_id,
                        embedding=embedding,
                        candidate_k=candidate_k,
                        vector_k=vector_k,
                        query_text=sanitized,
                        fulltext_k=fulltext_k,
                        rrf_k=rrf_k,
                        top_k=top_k,
                    ):
                        chunk = {
                            "id": r["id"],
                            "text": r["text"],
                            "chunk_index": r.get("chunk_index", 0),
                            "document_id": r.get("document_id", ""),
                            "document_title": r.get("document_title", ""),
                            "document_source": r.get("document_source", ""),
                        }
                        rows.append((chunk, float(r.get("score") or 0.0)))
                
                logger.info("hybrid_rrf_search_result",
                           group_id=group_id,
                           num_results=len(rows),
                           candidate_k=candidate_k,
                           vector_k=vector_k,
                           fulltext_k=fulltext_k,
                           sanitized_query=sanitized[:50] if sanitized else "")
            except Exception as e:
                logger.error("hybrid_rrf_search_failed",
                            group_id=group_id,
                            error=str(e),
                            error_type=type(e).__name__)
            return rows

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _run_sync)

    async def _derive_query_embedding_from_group_chunks(self, query_text: str) -> Optional[list]:
        """Derive an approximate query embedding from embeddings already stored in this group.

        This is a resilience path for local/dev when the external embedding service is
        misconfigured or unavailable. It selects a small set of chunks by keyword match,
        averages their embeddings, and uses that centroid for vector retrieval.
        """
        if not self.neo4j_driver:
            logger.warning("derive_embedding_no_driver")
            return None

        # Cheap keyword extraction (no extra dependencies)
        stop = {
            "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are",
            "was", "were", "be", "been", "being", "what", "when", "where", "who", "how", "why",
            "from", "by", "as", "at", "it", "this", "that", "these", "those",
            # Common low-signal query verbs that rarely appear verbatim in contracts/invoices
            "issued", "issue", "begin", "begins", "start", "starts", "created", "create",
            "happen", "happened", "make", "made", "won",
        }
        tokens = []
        current = []
        for ch in query_text.lower():
            if ch.isalnum() or ch in {"-", "_"}:
                current.append(ch)
            else:
                if current:
                    tokens.append("".join(current))
                    current = []
        if current:
            tokens.append("".join(current))

        keywords = [t for t in tokens if len(t) >= 4 and t not in stop][:8]
        if not keywords:
            logger.warning("derive_embedding_no_keywords", query=query_text[:50])
            return None

        logger.info("derive_embedding_extracted_keywords", keywords=keywords)
        group_id = self.group_id

        min_matches = 2 if len(keywords) >= 2 else 1

        def _run_sync():
            q = """
            MATCH (c:TextChunk {group_id: $group_id})
            WHERE c.embedding IS NOT NULL AND size(c.embedding) > 0
            WITH c,
                 reduce(m=0, k IN $keywords | m + CASE WHEN toLower(c.text) CONTAINS k THEN 1 ELSE 0 END) AS match_count
            WHERE match_count >= $min_matches
            RETURN c.embedding AS embedding, match_count
            ORDER BY match_count DESC
            LIMIT 50
            """
            with self.neo4j_driver.session() as session:
                return [
                    r["embedding"]
                    for r in session.run(
                        q,
                        group_id=group_id,
                        keywords=keywords,
                        min_matches=min_matches,
                    )
                ]

        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(self._executor, _run_sync)
        logger.info("derive_embedding_query_result", num_embeddings=len(embeddings), keywords=keywords, min_matches=min_matches)
        if not embeddings:
            logger.warning("derive_embedding_no_matching_chunks", keywords=keywords)
            return None

        # Average embeddings (centroid)
        dim = len(embeddings[0])
        if dim == 0:
            logger.warning("derive_embedding_empty_dimension")
            return None
        sums = [0.0] * dim
        count = 0
        for emb in embeddings:
            if not emb or len(emb) != dim:
                continue
            for i, v in enumerate(emb):
                sums[i] += float(v)
            count += 1
        if count == 0:
            logger.warning("derive_embedding_no_valid_embeddings")
            return None
        
        centroid = [v / count for v in sums]
        logger.info("derive_embedding_success", count=count, dims=len(centroid))
        return centroid

    async def _search_text_chunks_lexical(self, query_text: str, top_k: int = 10) -> list:
        """Lexical fallback retrieval within the group (no vector search).

        Intended only as a last resort when we cannot compute a query embedding.
        """
        if not self.neo4j_driver:
            return []

        stop = {
            "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are",
            "was", "were", "be", "been", "being", "what", "when", "where", "who", "how", "why",
            "from", "by", "as", "at", "it", "this", "that", "these", "those",
            # Common low-signal query verbs that rarely appear verbatim in contracts/invoices
            "issued", "issue", "begin", "begins", "start", "starts", "created", "create",
            "happen", "happened", "make", "made", "won",
        }
        tokens = []
        current = []
        for ch in query_text.lower():
            if ch.isalnum() or ch in {"-", "_"}:
                current.append(ch)
            else:
                if current:
                    tokens.append("".join(current))
                    current = []
        if current:
            tokens.append("".join(current))

        keywords = [t for t in tokens if len(t) >= 4 and t not in stop][:8]
        if not keywords:
            return []

        min_matches = 2 if len(keywords) >= 2 else 1

        group_id = self.group_id

        def _run_sync():
            q = """
            MATCH (node:TextChunk {group_id: $group_id})
            WHERE node.text IS NOT NULL
            OPTIONAL MATCH (node)-[:PART_OF]->(d:Document {group_id: $group_id})
            WITH node, d,
                 reduce(m=0, k IN $keywords | m + CASE WHEN toLower(node.text) CONTAINS k THEN 1 ELSE 0 END) AS match_count
            WHERE match_count >= $min_matches
            RETURN node.id AS id,
                   node.text AS text,
                   node.chunk_index AS chunk_index,
                   d.id AS document_id,
                   d.title AS document_title,
                   d.source AS document_source
                 , match_count AS score
            ORDER BY score DESC
            LIMIT $top_k
            """
            rows = []
            with self.neo4j_driver.session() as session:
                for r in session.run(
                    q,
                    group_id=group_id,
                    keywords=keywords,
                    min_matches=min_matches,
                    top_k=top_k,
                ):
                    chunk = {
                        "id": r["id"],
                        "text": r["text"],
                        "chunk_index": r["chunk_index"],
                        "document_id": r.get("document_id"),
                        "document_title": r.get("document_title"),
                        "document_source": r.get("document_source"),
                    }
                    rows.append((chunk, float(r.get("score") or 0.0)))
            return rows

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _run_sync)
    
    async def _search_text_chunks(
        self,
        query_text: str,
        embedding: list,
        top_k: int = 10
    ) -> list:
        """
        Search TextChunk nodes by vector similarity using Neo4j native vector index.
        
        Uses db.index.vector.queryNodes() for efficient vector search (Neo4j 5.11+).
        This is significantly faster than gds.similarity.cosine() as it uses
        proper vector indexes instead of computing similarity for all nodes.
        
        Uses ThreadPoolExecutor to run sync Neo4j call without blocking event loop.
        This is a production best practice for mixing sync I/O with async FastAPI.
        
        Returns: List of (chunk_dict, score) tuples
        """
        group_id = self.group_id

        # Neo4j's vector query returns the global topK across all TextChunk nodes.
        # If multiple groups exist, filtering by group_id after the vector query can
        # yield 0 results even when the group has embeddings.
        # Fix: oversample candidates, then filter+limit within the group.
        oversample_factor = 50
        oversample_cap = 2000
        candidate_k = min(max(top_k, top_k * oversample_factor), oversample_cap)
        
        def _run_sync_query():
            """Execute Neo4j vector search synchronously in thread pool."""
            # Use native vector index API (Neo4j 5.11+)
            # Index name: chunk_embedding (created during schema initialization)
            # This is much faster than gds.similarity.cosine()
            query = """
                 CALL db.index.vector.queryNodes('chunk_embedding', $candidate_k, $embedding)
            YIELD node, score
            WHERE node.group_id = $group_id
            OPTIONAL MATCH (node)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN node.id AS id,
                   node.text AS text,
                   node.chunk_index AS chunk_index,
                   d.id AS document_id,
                   d.title AS document_title,
                   d.source AS document_source,
                   score
            ORDER BY score DESC
                 LIMIT $top_k
            """
            
            results = []
            with self.neo4j_driver.session() as session:
                # First, check if there are ANY results from the vector search
                logger.info("vector_search_executing",
                           group_id=group_id,
                           embedding_len=len(embedding),
                           top_k=top_k,
                           candidate_k=candidate_k)
                
                result = session.run(
                    query,
                    group_id=group_id,
                    embedding=embedding,
                    top_k=top_k,
                    candidate_k=candidate_k
                )
                
                for record in result:
                    chunk_dict = {
                        "id": record["id"],
                        "text": record["text"],
                        "chunk_index": record.get("chunk_index", 0),
                        "document_id": record.get("document_id", ""),
                        "document_title": record.get("document_title", ""),
                        "document_source": record.get("document_source", "")
                    }
                    results.append((chunk_dict, record["score"]))
                
                logger.info("vector_search_results",
                           group_id=group_id,
                           num_results=len(results))
            
            return results
        
        # Run sync query in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(self._executor, _run_sync_query)
        return results
    
    # =========================================================================
    # Route 2: Local Search Equivalent (LazyGraphRAG Only)
    # =========================================================================
    
    async def _execute_route_2_local_search(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 2: LazyGraphRAG for entity-focused queries.
        
        Best for: "List all contracts with ABC Corp", "What are X's payment terms?"
        
        Stage 2.1: Extract explicit entities (NER / embedding match)
        Stage 2.2: LazyGraphRAG iterative deepening
        Stage 2.3: Synthesis with citations
        
        Note: No HippoRAG in this route - entities are explicit.
        """
        logger.info("route_2_local_search_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 2.1: Entity Extraction (explicit entities)
        logger.info("stage_2.1_entity_extraction")
        seed_entities = await self.disambiguator.disambiguate(query)
        logger.info("stage_2.1_complete", num_seeds=len(seed_entities))
        
        # Stage 2.2: LazyGraphRAG Iterative Deepening
        # For now, we use the tracer as a simplified exploration
        # TODO: Replace with true LazyGraphRAG iterative deepening
        logger.info("stage_2.2_iterative_deepening")
        evidence_nodes = await self.tracer.trace(
            query=query,
            seed_entities=seed_entities,
            top_k=15
        )
        logger.info("stage_2.2_complete", num_evidence=len(evidence_nodes))
        
        # ================================================================
        # GRAPH-BASED NEGATIVE DETECTION (Pre-LLM Check)
        # ================================================================
        # Before calling LLM synthesis, check if the requested field exists
        # in the retrieved evidence. This prevents hallucinations.
        # ================================================================
        field_exists, detected_intent = await self._check_field_exists_in_evidence(
            query=query,
            evidence_nodes=evidence_nodes
        )
        
        if not field_exists and detected_intent:
            # Field doesn't exist in evidence → deterministic "Not found"
            logger.info(
                "route_2_negative_detection_triggered",
                intent=detected_intent,
                num_evidence_nodes=len(evidence_nodes)
            )
            return {
                "response": f"The requested information ('{detected_intent}') was not found in the available documents.",
                "route_used": "route_2_local_search",
                "citations": [],
                "evidence_path": [],
                "metadata": {
                    "seed_entities": seed_entities,
                    "num_evidence_nodes": len(evidence_nodes),
                    "text_chunks_used": 0,
                    "latency_estimate": "fast",
                    "precision_level": "high",
                    "route_description": "Entity-focused with negative detection",
                    "negative_detection": True,
                    "field_intent": detected_intent
                }
            }
        
        # Stage 2.3: Synthesis with Citations
        logger.info("stage_2.3_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type
        )
        logger.info("stage_2.3_complete")
        
        return {
            "response": synthesis_result["response"],
            "route_used": "route_2_local_search",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "seed_entities": seed_entities,
                "num_evidence_nodes": len(evidence_nodes),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "moderate",
                "precision_level": "high",
                "route_description": "Entity-focused with LazyGraphRAG iterative deepening"
            }
        }
    
    # =========================================================================
    # Route 3: Global Search Equivalent (LazyGraphRAG + HippoRAG PPR)
    # =========================================================================
    
    async def _execute_route_3_global_search(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 3: LazyGraphRAG + HippoRAG for thematic queries.
        
        Best for: "What are the main compliance risks?", "Summarize key themes"
        
        Stage 3.1: Community matching (LazyGraphRAG)
        Stage 3.2: Hub entity extraction (deterministic)
        Stage 3.3: HippoRAG PPR tracing (detail recovery)
        Stage 3.4: Raw text chunk fetching
        Stage 3.5: Synthesis with citations
        """
        logger.info("route_3_global_search_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 3.1: Community Matching
        logger.info("stage_3.1_community_matching")
        matched_communities = await self.community_matcher.match_communities(query, top_k=3)
        community_data = [c for c, _ in matched_communities]
        logger.info("stage_3.1_complete", num_communities=len(community_data))
        
        # Stage 3.2: Hub Entity Extraction
        logger.info("stage_3.2_hub_extraction")
        hub_entities = await self.hub_extractor.extract_hub_entities(
            communities=community_data,
            top_k_per_community=3
        )
        logger.info("stage_3.2_complete", num_hubs=len(hub_entities))
        
        # Stage 3.3: HippoRAG PPR Tracing (DETAIL RECOVERY)
        logger.info("stage_3.3_hipporag_ppr_tracing")
        evidence_nodes = await self.tracer.trace(
            query=query,
            seed_entities=hub_entities,
            top_k=20  # Larger for global coverage
        )
        logger.info("stage_3.3_complete", num_evidence=len(evidence_nodes))
        
        # Stage 3.4 & 3.5: Synthesis with Citations
        logger.info("stage_3.4_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=evidence_nodes,
            response_type=response_type
        )
        logger.info("stage_3.4_complete")
        
        return {
            "response": synthesis_result["response"],
            "route_used": "route_3_global_search",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "matched_communities": [c.get("title", "?") for c in community_data],
                "hub_entities": hub_entities,
                "num_evidence_nodes": len(evidence_nodes),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "thorough",
                "precision_level": "high",
                "route_description": "Thematic with community matching + HippoRAG PPR detail recovery"
            }
        }
    
    # =========================================================================
    # Route 4: DRIFT Equivalent (Multi-Hop Iterative Reasoning)
    # =========================================================================
    
    async def _execute_route_4_drift(
        self,
        query: str,
        response_type: str
    ) -> Dict[str, Any]:
        """
        Route 4: DRIFT-style iterative reasoning for ambiguous queries.
        
        Best for: "Analyze risk exposure", "How are we connected through subsidiaries?"
        
        Stage 4.1: Query decomposition (DRIFT-style)
        Stage 4.2: Iterative entity discovery
        Stage 4.3: Consolidated HippoRAG tracing
        Stage 4.4: Multi-source synthesis
        """
        logger.info("route_4_drift_start", 
                   query=query[:50],
                   response_type=response_type)
        
        # Stage 4.1: Query Decomposition
        logger.info("stage_4.1_query_decomposition")
        sub_questions = await self._drift_decompose(query)
        logger.info("stage_4.1_complete", num_sub_questions=len(sub_questions))
        
        # Stage 4.2: Iterative Entity Discovery
        logger.info("stage_4.2_iterative_discovery")
        all_seeds: List[str] = []
        intermediate_results: List[Dict[str, Any]] = []
        
        for i, sub_q in enumerate(sub_questions):
            logger.info(f"processing_sub_question_{i+1}", question=sub_q[:50])
            
            # Get entities for this sub-question
            sub_entities = await self.disambiguator.disambiguate(sub_q)
            all_seeds.extend(sub_entities)
            
            # Optional: Run partial search for context building
            if len(sub_entities) > 0:
                partial_evidence = await self.tracer.trace(
                    query=sub_q,
                    seed_entities=sub_entities,
                    top_k=5  # Smaller for sub-questions
                )
                intermediate_results.append({
                    "question": sub_q,
                    "entities": sub_entities,
                    "evidence_count": len(partial_evidence)
                })
        
        # Deduplicate seeds
        all_seeds = list(set(all_seeds))
        logger.info("stage_4.2_complete", 
                   total_unique_seeds=len(all_seeds),
                   sub_question_results=len(intermediate_results))
        
        # Stage 4.3: Consolidated Tracing
        logger.info("stage_4.3_consolidated_tracing")
        complete_evidence = await self.tracer.trace(
            query=query,
            seed_entities=all_seeds,
            top_k=30  # More nodes for comprehensive coverage
        )
        logger.info("stage_4.3_complete", num_evidence=len(complete_evidence))
        
        # Stage 4.4: Multi-Source Synthesis
        logger.info("stage_4.4_synthesis")
        synthesis_result = await self.synthesizer.synthesize(
            query=query,
            evidence_nodes=complete_evidence,
            response_type=response_type,
            sub_questions=sub_questions,
            intermediate_context=intermediate_results
        )
        logger.info("stage_4.4_complete")
        
        return {
            "response": synthesis_result["response"],
            "route_used": "route_4_drift_multi_hop",
            "citations": synthesis_result["citations"],
            "evidence_path": synthesis_result["evidence_path"],
            "metadata": {
                "sub_questions": sub_questions,
                "all_seeds_discovered": all_seeds,
                "intermediate_results": intermediate_results,
                "num_evidence_nodes": len(complete_evidence),
                "text_chunks_used": synthesis_result["text_chunks_used"],
                "latency_estimate": "thorough",
                "precision_level": "maximum",
                "route_description": "DRIFT-style iterative multi-hop reasoning with HippoRAG PPR"
            }
        }
    
    async def _drift_decompose(self, query: str) -> List[str]:
        """
        Decompose an ambiguous query into concrete sub-questions.
        
        Uses DRIFT-style prompting to break down vague queries.
        """
        if not self.llm:
            # Fallback: treat as single question
            return [query]
        
        prompt = f"""Break down this complex query into specific, answerable sub-questions.

Original Query: "{query}"

Guidelines:
- Each sub-question should focus on identifying specific entities or relationships
- Questions should build on each other (entity discovery → relationship exploration → analysis)
- Generate 2-5 sub-questions depending on complexity

Format your response as a numbered list:
1. [First sub-question]
2. [Second sub-question]
...

Sub-questions:"""

        try:
            response = await self.llm.acomplete(prompt)
            text = response.text.strip()
            
            # Parse numbered list
            lines = text.split('\n')
            sub_questions = []
            for line in lines:
                line = line.strip()
                if line and line[0].isdigit():
                    # Remove numbering (e.g., "1. " or "1) ")
                    content = line.split('.', 1)[-1].strip()
                    content = content.split(')', 1)[-1].strip()
                    if content:
                        sub_questions.append(content)
            
            return sub_questions if sub_questions else [query]
            
        except Exception as e:
            logger.warning("drift_decompose_failed", error=str(e))
            return [query]
    
    # =========================================================================
    # Convenience Methods
    # =========================================================================
    
    async def query_with_audit_trail(self, query: str) -> Dict[str, Any]:
        """
        Convenience method for audit-focused queries.
        Forces audit_trail response type and uses Route 2 or 3.
        """
        return await self.query(query, response_type="audit_trail")
    
    async def force_route(
        self,
        query: str,
        route: QueryRoute,
        response_type: str = "detailed_report"
    ) -> Dict[str, Any]:
        """
        Force a specific route regardless of classification.
        
        Useful for testing or when you know the query type.
        """
        if route == QueryRoute.VECTOR_RAG:
            return await self._execute_route_1_vector_rag(query)
        elif route == QueryRoute.LOCAL_SEARCH:
            return await self._execute_route_2_local_search(query, response_type)
        elif route == QueryRoute.GLOBAL_SEARCH:
            return await self._execute_route_3_global_search(query, response_type)
        else:  # DRIFT_MULTI_HOP
            return await self._execute_route_4_drift(query, response_type)
    
    async def health_check(self) -> Dict[str, Any]:
        """Check the health of all pipeline components."""
        return {
            "router": "ok",
            "disambiguator": "ok" if self.llm else "no_llm",
            "tracer": "ok" if self.tracer._use_hipporag else "fallback_mode",
            "synthesizer": "ok" if self.llm else "no_llm",
            "vector_rag": "ok" if self.vector_rag else "not_configured",
            "profile": self.profile.value,
            "routes_available": {
                "route_1_vector_rag": self.vector_rag is not None,
                "route_2_local_search": True,
                "route_3_global_search": True,
                "route_4_drift": self.llm is not None
            }
        }
