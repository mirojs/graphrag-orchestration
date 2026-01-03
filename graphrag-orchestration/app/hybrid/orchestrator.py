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

from typing import Dict, Any, Optional, List
import structlog
import asyncio
from concurrent.futures import ThreadPoolExecutor

from .pipeline.intent import IntentDisambiguator
from .pipeline.tracing import DeterministicTracer
from .pipeline.synthesis import EvidenceSynthesizer
from .pipeline.community_matcher import CommunityMatcher
from .pipeline.hub_extractor import HubExtractor
from .router.main import HybridRouter, QueryRoute, DeploymentProfile

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
            graph_store=graph_store
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
                   has_community_matcher=embedding_client is not None,
                   group_id=group_id)
    
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
    
    async def _execute_route_1_vector_rag(self, query: str) -> Dict[str, Any]:
        """
        Route 1: Simple Vector RAG for fast fact lookups.
        
        Best for: "What is X's address?", "How much is invoice Y?"
        Profile: General Enterprise only (disabled in High Assurance)
        
        Implementation: Searches TextChunk nodes in Neo4j for exact text retrieval.
        Uses concise prompts to return direct factual answers.
        
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
            
            # Retrieval: vector (if we have a query embedding) + lexical (always), then merge.
            results = []
            if query_embedding is not None:
                # Future-proof path: Neo4j-native hybrid + RRF (vector + fulltext + fusion).
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
            
            # Try NLP extraction first (fast, deterministic, no hallucination)
            nlp_answer = self._extract_with_nlp(query, results)
            
            if nlp_answer:
                logger.info("route_1_nlp_extraction_success", 
                           answer_length=len(nlp_answer))
                answer = nlp_answer
            else:
                # Fallback to LLM synthesis with temperature=0 for determinism
                logger.info("route_1_fallback_to_llm_synthesis")
                prompt = f"""Based on the following text excerpts, answer the question.
Provide a direct, concise answer. If the user asked for a specific value (date, amount, name), provide just that value.
Only use the provided excerpts. If the answer is not present, respond with: "Not specified in the provided documents."

Excerpts:
{context}

Question: {query}

Answer:"""
                
                response = self.llm.complete(prompt, temperature=0.0)
                answer = response.text if hasattr(response, 'text') else str(response)
            
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
                    "route_description": "Vector search on text chunks"
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

    def _extract_with_nlp(
        self,
        query: str,
        chunks_with_scores: list
    ) -> Optional[str]:
        """
        Try to extract answer using deterministic NLP patterns.
        Returns None if no pattern matches (triggers LLM fallback).
        
        Patterns optimized for invoice/contract factual extraction:
        - Invoice numbers, PO numbers
        - Currency amounts (total, price)
        - Dates (due date, start date)
        - Names (salesperson, vendor, agent)
        - Registration numbers, codes
        - Durations (warranty period, term)
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
