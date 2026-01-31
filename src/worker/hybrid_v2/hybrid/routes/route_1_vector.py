"""Route 1: Vector RAG - Fast fact lookups with high precision.

Best for simple fact lookups:
- "What is X's address?"
- "How much is invoice Y?"
- "What is the policy number?"

This route uses a KVP → Table → LLM precision cascade:
1. KeyValue nodes (highest precision, exact field matches)
2. Table extraction (structured data)  
3. LLM extraction from top chunk (handles nuance)

Features:
- Hybrid RRF search (vector + fulltext)
- Phrase-aware query boosting
- Entity graph fallback when hybrid fails
- Grounding verification to prevent hallucination
"""

import re
import json
import asyncio
from collections import defaultdict
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor

import structlog

from .base import BaseRouteHandler, RouteResult, Citation

logger = structlog.get_logger(__name__)


class VectorRAGHandler(BaseRouteHandler):
    """Route 1: Simple Vector RAG for fast fact lookups."""

    ROUTE_NAME = "route_1_vector_rag"

    async def execute(
        self,
        query: str,
        response_type: str = "summary"
    ) -> RouteResult:
        """
        Execute Route 1: Vector RAG for fast fact lookups.
        
        Strategy: KVP → Table → LLM extraction (precision cascade)
        - Step 1: Try KVP extraction (highest precision)
        - Step 2: Try Table extraction (structured data)
        - Step 3: Fall back to LLM extraction (handles nuance)
        
        Args:
            query: The user's natural language query
            response_type: Response format (not used for Route 1)
            
        Returns:
            RouteResult with response, citations, and metadata
        """
        logger.info("route_1_vector_rag_start", query=query[:50])
        
        # Validate required components
        if not self.neo4j_driver:
            logger.error("vector_rag_neo4j_unavailable")
            raise RuntimeError("Route 1 requires Neo4j driver. Neo4j is not configured.")
        
        try:
            # Get query embedding
            from src.worker.services.llm_service import LLMService
            llm_service = LLMService()
            
            if llm_service.embed_model is None:
                logger.error("vector_rag_embedding_unavailable")
                raise RuntimeError("Route 1 requires embedding model. Embeddings are not configured.")
            
            try:
                query_embedding = llm_service.embed_model.get_text_embedding(query)
                logger.info("vector_rag_embedding_success",
                           embedding_dims=len(query_embedding) if query_embedding else 0)
            except Exception as e:
                logger.error("vector_rag_embedding_failed", error=str(e))
                raise RuntimeError(f"Failed to generate query embedding: {str(e)}") from e
            
            if query_embedding is None:
                raise RuntimeError("Query embedding is None after generation")
            
            # Retrieval: Hybrid RRF (vector + fulltext) for best precision
            # Note: Using pipeline's hybrid search method
            results = await self.pipeline._search_text_chunks_hybrid_rrf(
                query_text=query,
                embedding=query_embedding,
                top_k=15,
                vector_k=25,
                fulltext_k=25,
            )
            
            if not results:
                # GRAPH-BASED FALLBACK: Use Entity + Section nodes
                logger.info("route_1_hybrid_empty_trying_entity_fallback")
                entity_results = await self.pipeline._search_via_entity_graph(query, top_k=8)
                
                if entity_results:
                    logger.info("route_1_entity_fallback_success", 
                               num_chunks=len(entity_results))
                    results = entity_results
                else:
                    return RouteResult(
                        response="No relevant text found for this query.",
                        route_used=self.ROUTE_NAME,
                        citations=[],
                        evidence_path=[],
                        metadata={
                            "num_chunks": 0,
                            "latency_estimate": "fast",
                            "precision_level": "standard",
                            "route_description": "Vector search on text chunks"
                        }
                    )
            
            # Build context grouped by document
            doc_groups: Dict[str, List[Tuple[int, Dict[str, Any], float]]] = defaultdict(list)
            
            for i, (chunk, score) in enumerate(results[:8], 1):
                doc_key = chunk.get("document_id") or chunk.get("document_title") or "Unknown"
                doc_groups[doc_key].append((i, chunk, score))
            
            context_parts = []
            citations = []
            
            for doc_key, chunks_with_idx in doc_groups.items():
                first_chunk = chunks_with_idx[0][1]
                doc_title = first_chunk.get("document_title") or doc_key
                context_parts.append(f"=== DOCUMENT: {doc_title} ===")
                
                for i, chunk, score in chunks_with_idx:
                    context_parts.append(f"[{i}] (Score: {score:.2f}) {chunk['text']}")
                    citations.append(Citation(
                        index=i,
                        chunk_id=chunk["id"],
                        document_id=chunk.get("document_id", ""),
                        document_title=chunk.get("document_title", ""),
                        score=float(score),
                        text_preview=chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"]
                    ))
                context_parts.append("")
            
            # ================================================================
            # Route 1 Strategy: KVP → Table → LLM (precision cascade)
            # ================================================================
            
            # Step 1: Try KVP extraction first (highest precision)
            kvp_answer = await self._extract_from_keyvalue_nodes(query, results)
            
            if kvp_answer:
                logger.info("route_1_kvp_extraction_success", answer=kvp_answer[:50])
                answer = kvp_answer
            else:
                # Step 2: Try table-based extraction
                table_answer = await self._extract_from_tables(query, results)
                
                if table_answer:
                    logger.info("route_1_table_extraction_success", answer=table_answer[:50])
                    answer = table_answer
                else:
                    # Step 3: Fall back to LLM extraction
                    llm_answer = await self._extract_with_llm_from_top_chunk(query, results)
                    
                    if llm_answer:
                        logger.info("route_1_llm_extraction_success", answer=llm_answer[:50])
                        answer = llm_answer
                    else:
                        answer = "Not found in the provided documents."
            
            return RouteResult(
                response=answer,
                route_used=self.ROUTE_NAME,
                citations=citations,
                evidence_path=[],
                metadata={
                    "num_chunks": len(results),
                    "chunks_used": len(context_parts),
                    "latency_estimate": "fast",
                    "precision_level": "standard",
                    "route_description": "Vector search on text chunks with LLM extraction",
                    "debug_top_chunk_id": results[0][0]["id"] if results else None,
                    "debug_top_chunk_preview": results[0][0]["text"][:100] if results else None
                }
            )
            
        except Exception as e:
            # Fallback to Route 2 (graph-based) for reliability
            logger.error("route_1_failed_fallback_to_route_2",
                        error=str(e),
                        reason="Vector RAG execution failed")
            
            # Import LocalSearchHandler for fallback
            from .route_2_local import LocalSearchHandler
            
            route_2_handler = LocalSearchHandler(self.pipeline)
            result = await route_2_handler.execute(query, "summary")
            
            # Mark that this was a fallback execution
            result.metadata["fallback_from"] = "route_1_vector_rag"
            result.metadata["fallback_reason"] = str(e)
            return result

    # ==========================================================================
    # KVP EXTRACTION (Highest Precision)
    # ==========================================================================
    
    async def _extract_from_keyvalue_nodes(
        self,
        query: str,
        chunks_with_scores: list
    ) -> Optional[str]:
        """
        Extract answer from KeyValue nodes via semantic key matching.
        
        This is the HIGHEST PRECISION extraction method:
        - Queries KeyValue nodes linked to the same sections as retrieved chunks
        - Uses semantic similarity (cosine > 0.85) to match query to key embeddings
        - Returns value directly if a high-confidence match is found
        """
        if not chunks_with_scores or not self._async_neo4j:
            return None
        
        chunk_ids = [chunk["id"] for chunk, _ in chunks_with_scores[:8]]
        
        # Generate query embedding for semantic key matching
        try:
            from src.worker.services.llm_service import LLMService
            llm_service = LLMService()
            
            if llm_service.embed_model is None:
                return None
            
            query_embedding = llm_service.embed_model.get_text_embedding(query)
            if not query_embedding:
                return None
        except Exception as e:
            logger.warning("route_1_kvp_embedding_failed", error=str(e))
            return None
        
        try:
            q = """
            MATCH (c:TextChunk)-[:IN_SECTION]->(s:Section)<-[:IN_SECTION]-(kv:KeyValue)
            WHERE c.id IN $chunk_ids AND c.group_id = $group_id
              AND kv.key_embedding IS NOT NULL
            WITH DISTINCT kv, 
                 vector.similarity.cosine(kv.key_embedding, $query_embedding) AS similarity
            WHERE similarity > 0.85
            RETURN kv.key AS key, kv.value AS value, kv.confidence AS confidence, similarity
            ORDER BY similarity DESC, confidence DESC
            LIMIT 5
            """
            
            records = await self._async_neo4j.execute_read(q, {
                "chunk_ids": chunk_ids,
                "group_id": self.group_id,
                "query_embedding": query_embedding,
            })
            
            if not records:
                return None
            
            best_match = records[0]
            value = best_match.get("value", "")
            
            if value:
                logger.info("route_1_kvp_match_found",
                           key=best_match.get("key", ""),
                           similarity=round(best_match.get("similarity", 0.0), 3))
                return value.strip()
            
            return None
            
        except Exception as e:
            logger.warning("route_1_kvp_extraction_failed", error=str(e))
            return None

    # ==========================================================================
    # TABLE EXTRACTION (Structured Data)
    # ==========================================================================
    
    async def _extract_from_tables(
        self,
        query: str,
        chunks_with_scores: list
    ) -> Optional[str]:
        """
        Extract answer from structured Table nodes.
        
        Avoids LLM confusion with adjacent columns (e.g., asking for "due date"
        but LLM extracting from "terms" column).
        """
        if not chunks_with_scores or not self._async_neo4j:
            return None
        
        # Strip markdown formatting and extract field name
        query_clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', query)
        query_lower = query_clean.lower()
        
        # Common field patterns
        FIELD_PATTERNS = [
            r"what(?:'s| is).*?(?:invoice|contract|warranty)?\s+([a-z]+(?:\s+[a-z]+)?)\s*\??$",
            r"the\s+([a-z]+(?:\s+[a-z]+)?)\s+(?:for|in|on|of|from)",
            r"([a-z]+(?:\s+[a-z]+)?)\s*\?$",
        ]
        
        potential_field = None
        for pattern in FIELD_PATTERNS:
            match = re.search(pattern, query_lower)
            if match:
                potential_field = match.group(1).strip()
                if potential_field.startswith("the "):
                    potential_field = potential_field[4:]
                if potential_field not in ["the", "a", "an", "this", "that", "it"]:
                    break
                else:
                    potential_field = None
        
        if not potential_field:
            return None
        
        chunk_ids = [chunk["id"] for chunk, _ in chunks_with_scores[:8]]
        
        try:
            q = """
            MATCH (t:Table)-[:IN_CHUNK]->(c:TextChunk)
            WHERE c.id IN $chunk_ids AND c.group_id = $group_id
            RETURN t.headers AS headers, t.rows AS rows
            """
            
            records = await self._async_neo4j.execute_read(q, {
                "chunk_ids": chunk_ids,
                "group_id": self.group_id
            })
            
            if not records:
                return None
            
            # Parse tables
            parsed_tables = []
            for record in records:
                headers = record.get("headers", [])
                rows_json = record.get("rows", "[]")
                if not headers:
                    continue
                try:
                    rows = json.loads(rows_json) if isinstance(rows_json, str) else rows_json
                except:
                    continue
                parsed_tables.append({"headers": headers, "rows": rows})
            
            # For TOTAL/AMOUNT queries, prioritize summary tables
            if potential_field in ["total", "amount", "subtotal", "total amount", "amount due"]:
                for table in parsed_tables:
                    headers = table["headers"]
                    rows = table["rows"]
                    headers_lower = [h.lower() for h in headers]
                    
                    if headers_lower and ("subtotal" in headers_lower[0] or "total" in headers_lower[0]):
                        for row in rows:
                            label_key = headers[0] if headers else None
                            label = row.get(label_key, "").lower().strip() if label_key else ""
                            
                            if "total" in label and "sub" not in label:
                                if len(headers) > 1:
                                    value = row.get(headers[1], "").strip()
                                    if value:
                                        logger.info("route_1_table_summary_match", value=value)
                                        return value
            
            # Standard header matching
            for table in parsed_tables:
                headers = table["headers"]
                rows = table["rows"]
                
                matched_header = None
                for header in headers:
                    header_lower = header.lower()
                    if (potential_field in header_lower or 
                        header_lower in potential_field or
                        (potential_field in ["due date", "date due"] and "due" in header_lower and "date" in header_lower)):
                        matched_header = header
                        break
                
                if matched_header and rows:
                    for row in rows:
                        value = row.get(matched_header, "").strip()
                        if value:
                            logger.info("route_1_table_field_match", header=matched_header, value=value)
                            return value
            
            # Cell-content search for merged cells
            for table in parsed_tables:
                rows = table["rows"]
                for row in rows:
                    for cell_key, cell_value in row.items():
                        cell_text = str(cell_value).lower() if cell_value else ""
                        if potential_field in cell_text:
                            pattern = rf"{re.escape(potential_field)}[:\s\-]*([A-Z0-9][\w\-]*)"
                            match = re.search(pattern, cell_text, re.IGNORECASE)
                            if match:
                                extracted = match.group(1).strip()
                                if extracted:
                                    logger.info("route_1_table_cell_match", value=extracted)
                                    return extracted
            
            return None
            
        except Exception as e:
            logger.warning("route_1_table_extraction_failed", error=str(e))
            return None

    # ==========================================================================
    # LLM EXTRACTION (Handles Nuance)
    # ==========================================================================
    
    async def _extract_with_llm_from_top_chunk(
        self,
        query: str,
        chunks_with_scores: list
    ) -> Optional[str]:
        """
        Extract answer from TOP-RANKED chunk using LLM (Temperature 0).
        
        Features:
        - Document-aware chunk selection (respects query hints)
        - Grounding verification to prevent hallucination
        - Multiple chunk fallback if verification fails
        """
        if not chunks_with_scores:
            return None
        
        max_chunks_to_try = 3
        
        # Document-aware chunk selection
        query_lower = query.lower()
        
        doc_patterns = [
            (r'(?:in|from|on)\s+(?:the\s+)?purchase\s+contract', 'purchase_contract'),
            (r'(?:in|from|on)\s+(?:the\s+)?invoice', 'invoice'),
            (r'(?:in|from|on)\s+(?:the\s+)?warranty', 'warranty'),
            (r'(?:in|from|on)\s+(?:the\s+)?property\s+management', 'property_management'),
            (r'(?:in|from|on)\s+(?:the\s+)?holding\s+tank', 'holding_tank'),
        ]
        
        target_doc_hint = None
        for pattern, hint in doc_patterns:
            if re.search(pattern, query_lower):
                target_doc_hint = hint
                break
        
        # Find best document_id
        primary_document_id = None
        
        if target_doc_hint:
            target_doc_hint_spaced = target_doc_hint.replace("_", " ")
            
            for chunk, score in chunks_with_scores:
                doc_title = (chunk.get("document_title") or "").lower()
                doc_id = chunk.get("document_id") or ""
                
                if (target_doc_hint in doc_title or 
                    target_doc_hint_spaced in doc_title or 
                    target_doc_hint in doc_id.lower()):
                    primary_document_id = chunk.get("document_id")
                    logger.info("llm_using_query_document_hint",
                               target=target_doc_hint, matched_doc=doc_title[:50])
                    break
        
        if not primary_document_id:
            try:
                primary_document_id = (chunks_with_scores[0][0] or {}).get("document_id")
            except Exception:
                primary_document_id = None

        try:
            from src.worker.services.llm_service import LLMService
            llm_service = LLMService()

            tried = 0
            for rank, (chunk, score) in enumerate(chunks_with_scores, start=1):
                if tried >= max_chunks_to_try:
                    break

                if primary_document_id:
                    if (chunk or {}).get("document_id") != primary_document_id:
                        continue

                tried += 1
                top_chunk = chunk["text"]

                logger.info("llm_extracting_from_chunk",
                           rank=rank, score=float(score), preview=top_chunk[:100])

                prompt = f"""You are a precise data extraction engine.
Context:
{top_chunk}

User Query: {query}

Instructions:
1. Extract the EXACT answer from the context above.
2. If the answer is a specific value (price, date, name, ID), return ONLY that value WITH any qualifying phrases (e.g., "in excess of", "greater than", "at least", "up to", "maximum").
3. If the query asks for a total/amount and multiple exist, look for "Total", "Amount Due", or "Balance".
4. Do not generate conversational text. Just the value with its qualifiers.
5. Do not guess or hallucinate. Only extract if explicitly stated in the text.
6. If the answer is not explicitly present in the provided context, you MUST return "Not found".
"""

                response = llm_service.generate(prompt, temperature=0.0)
                cleaned_response = response.strip()

                # If model says "Not found", try next chunk
                if "not found" in cleaned_response.lower() and len(cleaned_response) < 30:
                    continue

                # Exact grounding check for URLs/emails
                if self._looks_like_url_or_email(cleaned_response):
                    if cleaned_response not in top_chunk:
                        logger.warning("llm_candidate_rejected_url_grounding",
                                      candidate=cleaned_response)
                        continue

                # Relaxed grounding validation
                if not self._is_answer_grounded_in_chunk(cleaned_response, top_chunk):
                    logger.warning("llm_candidate_rejected_grounding",
                                  candidate=cleaned_response[:80])
                    continue

                logger.info("llm_extraction_verified",
                           candidate=cleaned_response[:80], rank=rank)
                return cleaned_response

            return None

        except Exception as e:
            logger.error("llm_extraction_error", error=str(e))
            return None

    def _looks_like_url_or_email(self, text: str) -> bool:
        """Check if text looks like a URL or email address."""
        lower = text.lower()
        if "http://" in lower or "https://" in lower or lower.startswith("www."):
            return True
        if "@" in text and "." in text.split("@", 1)[-1]:
            return True
        return False

    def _is_answer_grounded_in_chunk(
        self,
        answer: str,
        chunk_text: str,
    ) -> bool:
        """
        Check if an LLM-extracted answer is grounded in the source chunk.
        
        Uses relaxed token-based matching:
        1. Extract value tokens (numbers, codes, names)
        2. Check if tokens appear in chunk
        3. Allow format variations
        """
        if not answer or not chunk_text:
            return False
        
        answer_lower = answer.lower().strip()
        chunk_lower = chunk_text.lower()
        
        # Quick exact match
        if answer_lower in chunk_lower:
            return True
        
        # Extract grounding tokens
        numbers = re.findall(r'\d+(?:[.,/\-]\d+)*', answer)
        codes = re.findall(r'[A-Z]{2,}[\-\s]?\d+|\d+[\-\s]?[A-Z]{2,}', answer, re.IGNORECASE)
        proper_nouns = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', answer)
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', answer)
        quoted_flat = [q for pair in quoted for q in pair if q]
        
        grounding_tokens = set()
        
        for num in numbers:
            core_digits = re.sub(r'[.,/\-]', '', num)
            if len(core_digits) >= 2:
                grounding_tokens.add(core_digits)
        
        for code in codes:
            normalized = re.sub(r'[\s\-]', '', code).lower()
            if len(normalized) >= 3:
                grounding_tokens.add(normalized)
        
        for noun in proper_nouns:
            if len(noun) >= 3 and noun.lower() not in {'the', 'and', 'for', 'not', 'found'}:
                grounding_tokens.add(noun.lower())
        
        for q in quoted_flat:
            if len(q) >= 3:
                grounding_tokens.add(q.lower())
        
        # Fallback to significant words
        if not grounding_tokens:
            stopwords = {'this', 'that', 'with', 'from', 'have', 'been', 'were', 'what', 'when',
                        'where', 'which', 'there', 'their', 'about', 'would', 'could', 'should',
                        'found', 'document', 'provided', 'documents'}
            words = re.findall(r'[a-z]{4,}', answer_lower)
            grounding_tokens = {w for w in words if w not in stopwords}
        
        if not grounding_tokens:
            return False
        
        # Check token matches
        chunk_normalized = re.sub(r'[\s\-.,/]', '', chunk_lower)
        
        matched_tokens = 0
        for token in grounding_tokens:
            token_normalized = re.sub(r'[\s\-.,/]', '', token)
            if token_normalized in chunk_normalized or token in chunk_lower:
                matched_tokens += 1
        
        min_matches = max(1, len(grounding_tokens) // 2)
        return matched_tokens >= min_matches
