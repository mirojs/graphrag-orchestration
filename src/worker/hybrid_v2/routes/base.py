"""Base route handler with shared utilities for Neo4j retrieval operations.

All route handlers inherit from BaseRouteHandler to access:
- Neo4j drivers (sync and async)
- LLM/embedding clients
- Common retrieval utilities (fulltext search, hybrid RRF, etc.)

This module provides dependency injection: route handlers receive a reference
to the main HybridPipeline and access its services through that reference.
"""

from __future__ import annotations

import json
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import structlog

from ..services.neo4j_retry import retry_session

if TYPE_CHECKING:
    from ..orchestrator import HybridPipeline

logger = structlog.get_logger(__name__)


# =============================================================================
# Response Data Classes
# =============================================================================

@dataclass
class Citation:
    """A citation reference to source content with location metadata.
    
    Provides complete traceability from query results back to source documents:
    - Document identification (id, title, url)
    - Location within document (page, section, character offsets)
    - Relevance scoring and text preview
    - Pixel-accurate highlighting via polygon geometry (when available)
    
    Character offsets (start_offset, end_offset) are from Azure Document Intelligence
    and represent positions in the original document content.
    
    For pixel-accurate highlighting:
    - sentences: List of sentence spans with polygons for frontend overlay
    - page_dimensions: Page sizes for normalized→pixel coordinate transformation
    """
    index: int
    chunk_id: str
    document_id: str
    document_title: str
    score: float
    text_preview: str
    # New fields for document source linking and location
    document_url: str = ""  # Blob storage URL for clickable links
    page_number: Optional[int] = None  # Page number from Azure DI
    section_path: str = ""  # Section hierarchy (e.g., "Terms > Payment")
    start_offset: Optional[int] = None  # Character offset in document (from DI spans)
    end_offset: Optional[int] = None  # End character offset in document
    # Polygon geometry for pixel-accurate highlighting
    sentences: Optional[List[Dict[str, Any]]] = None  # List of sentence spans with polygons
    page_dimensions: Optional[List[Dict[str, Any]]] = None  # Page sizes for coordinate transformation
    # Sentence-level match (narrowed from chunk by post-synthesis matching)
    sentence_text: Optional[str] = None  # The specific sentence within the chunk
    sentence_offset: Optional[int] = None  # Character offset of sentence within chunk
    sentence_length: Optional[int] = None  # Character length of the matched sentence

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "index": self.index,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "document_url": self.document_url,
            "score": self.score,
            "text_preview": self.text_preview,
        }
        # Include optional location fields only if present
        if self.page_number is not None:
            result["page_number"] = self.page_number
        if self.section_path:
            result["section_path"] = self.section_path
        if self.start_offset is not None:
            result["start_offset"] = self.start_offset
        if self.end_offset is not None:
            result["end_offset"] = self.end_offset
        # Include polygon geometry for pixel-accurate highlighting
        if self.sentences:
            result["sentences"] = self.sentences
        if self.page_dimensions:
            result["page_dimensions"] = self.page_dimensions
        # Include sentence-level match for precise citation
        if self.sentence_text:
            result["sentence_text"] = self.sentence_text
        if self.sentence_offset is not None:
            result["sentence_offset"] = self.sentence_offset
        if self.sentence_length is not None:
            result["sentence_length"] = self.sentence_length
        return result


@dataclass
class RouteResult:
    """Unified response schema for all routes.
    
    All route handlers return a RouteResult, ensuring consistent API responses
    regardless of which route processed the query.
    """
    response: str
    route_used: str
    citations: List[Citation] = field(default_factory=list)
    evidence_path: List[Any] = field(default_factory=list)  # Can be str or dict
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Top-level API fields for telemetry
    usage: Optional[Dict[str, Any]] = None  # {prompt_tokens, completion_tokens, total_tokens, model}
    timing: Optional[Dict[str, Any]] = None  # {retrieval_ms, synthesis_ms, total_ms}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "response": self.response,
            "route_used": self.route_used,
            "citations": [c.to_dict() for c in self.citations],
            "evidence_path": self.evidence_path,
            "metadata": self.metadata,
        }
        # Extract raw_extractions to top-level for comprehensive mode (API expects it there)
        if self.metadata.get("raw_extractions"):
            result["raw_extractions"] = self.metadata["raw_extractions"]
        # Include telemetry fields if present
        if self.usage:
            result["usage"] = self.usage
        if self.timing:
            result["timing"] = self.timing
        return result


# =============================================================================
# Base Route Handler
# =============================================================================

class BaseRouteHandler:
    """Base class for route handlers with shared Neo4j utilities.
    
    Provides access to pipeline services via dependency injection.
    All shared retrieval methods are defined here.
    
    Subclasses must implement:
        async def execute(self, query: str, response_type: str = "summary", knn_config: Optional[str] = None, prompt_variant: Optional[str] = None, synthesis_model: Optional[str] = None, include_context: bool = False) -> RouteResult
    """

    # Route identifier (override in subclasses)
    ROUTE_NAME: str = "base"
    
    def __init__(self, pipeline: "HybridPipeline"):
        """Initialize with reference to the main pipeline.
        
        Args:
            pipeline: The HybridPipeline instance containing all services.
        """
        self.pipeline = pipeline
        
        # Convenience references to frequently-used services
        self.llm = pipeline.llm
        self.neo4j_driver = pipeline.neo4j_driver
        self.group_id = pipeline.group_id
        self.folder_id = pipeline.folder_id  # Optional folder scope (None = all)
        self.synthesizer = pipeline.synthesizer
        self._executor = pipeline._executor
        self._async_neo4j = pipeline._async_neo4j

    def _build_folder_filter(self, node_alias: str = "node", doc_alias: str = "d") -> str:
        """Build Cypher WHERE clause for optional folder filtering.
        
        If folder_id is None, returns empty string (no filter).
        If folder_id is set, returns a WHERE clause that filters documents in that folder.
        
        Args:
            node_alias: Alias for the chunk/node being filtered
            doc_alias: Alias for the document node
            
        Returns:
            Cypher WHERE clause string (empty if no folder filter)
        """
        if self.folder_id is None:
            return ""
        # Filter documents that are in the specified folder
        return f"AND ({doc_alias})-[:IN_FOLDER]->(:Folder {{id: $folder_id, group_id: $group_id}})"
    
    def _get_folder_params(self) -> dict:
        """Get folder_id parameter dict for Cypher queries.
        
        Returns:
            Dict with folder_id if set, empty dict otherwise
        """
        if self.folder_id is not None:
            return {"folder_id": self.folder_id}
        return {}

    async def _fetch_language_spans(
        self, doc_ids: List[str]
    ) -> Dict[str, List[Dict]]:
        """Fetch language_spans from Document nodes for sentence-level citations.

        Azure DI LANGUAGES feature provides ML-detected sentence boundaries
        stored as JSON on Document.language_spans. These are used to segment
        chunk text into individually-citable sentences.

        Args:
            doc_ids: List of document IDs to fetch spans for

        Returns:
            Dict mapping doc_id -> list of span groups
            [{locale, confidence, spans: [{offset, length}]}]
        """
        if not doc_ids:
            return {}

        query = """
        MATCH (d:Document {group_id: $group_id})
        WHERE d.id IN $doc_ids AND d.language_spans IS NOT NULL
        RETURN d.id AS doc_id, d.language_spans AS spans
        """

        try:
            loop = asyncio.get_running_loop()
            driver = self.neo4j_driver
            group_id = self.group_id

            def _run():
                with retry_session(driver, read_only=True) as session:
                    result = session.run(query, group_id=group_id, doc_ids=doc_ids)
                    return list(result)

            records = await loop.run_in_executor(None, _run)

            spans_map: Dict[str, List[Dict]] = {}
            for record in records:
                doc_id = record.get("doc_id") or ""
                raw = record.get("spans") or "[]"
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, list):
                        spans_map[doc_id] = parsed
                    elif isinstance(parsed, dict):
                        spans_map[doc_id] = [parsed]
                    else:
                        spans_map[doc_id] = []
                except (json.JSONDecodeError, TypeError):
                    spans_map[doc_id] = []

            logger.info(
                "language_spans_fetched",
                requested_docs=len(doc_ids),
                docs_with_spans=len(spans_map),
                total_span_groups=sum(len(v) for v in spans_map.values()),
            )
            return spans_map

        except Exception as e:
            logger.warning("language_spans_fetch_failed", error=str(e))
            return {}

    async def execute(self, query: str, response_type: str = "summary", knn_config: Optional[str] = None, prompt_variant: Optional[str] = None, synthesis_model: Optional[str] = None, include_context: bool = False) -> RouteResult:
        """Execute the route on a query.
        
        Args:
            query: The user's natural language query
            response_type: Response format ("summary", "detailed_report", etc.)
            knn_config: Optional KNN configuration for SEMANTICALLY_SIMILAR edge filtering.
            include_context: If True, include the full LLM context in response metadata.
            
        Returns:
            RouteResult with response, citations, and metadata
        """
        raise NotImplementedError("Subclasses must implement execute()")

    # =========================================================================
    # Shared Text Sanitization & Query Building
    # =========================================================================

    def _sanitize_query_for_fulltext(self, query: str) -> str:
        """Sanitize query for Lucene fulltext index.

        Neo4j fulltext indexes use Lucene syntax. Certain characters are operators
        and can cause parse errors or unintended semantics.
        
        Args:
            query: Raw query string
            
        Returns:
            Sanitized string safe for Lucene fulltext search
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

    def _build_phrase_aware_fulltext_query(self, query: str) -> str:
        """Build a Lucene query that prioritizes exact phrase matches.
        
        This addresses the theme coverage gap where specific phrases like
        "60 days", "written notice", "3 business days" exist in documents but
        aren't being retrieved because standard fulltext treats them as OR queries.
        
        Strategy:
        1. Extract common contractual/legal phrase patterns (N days, written X, etc.)
        2. Wrap detected phrases in quotes for exact matching
        3. Boost phrase matches with ^2.0
        4. Include individual words as fallback (lower priority)
        
        Example:
            Input:  "What are the termination rules including 60 days written notice?"
            Output: '"60 days"^2.0 "written notice"^2.0 termination rules'
            
        Args:
            query: Raw query string
            
        Returns:
            Lucene query string with phrase boosting
        """
        if not query:
            return ""
        
        q = query.strip()
        
        # Patterns for phrases that should be matched exactly
        PHRASE_PATTERNS = [
            # Time periods: "N days", "N business days", etc.
            r'\b(\d+\s+(?:business\s+)?(?:days?|months?|years?|weeks?|hours?))\b',
            # Dollar amounts
            r'\b(\$[\d,]+(?:\.\d{2})?)\b',
            r'\b([\d,]+\s+dollars?)\b',
            # Percentages
            r'\b(\d+(?:\.\d+)?\s*%)\b',
            r'\b(\d+(?:\.\d+)?\s+percent)\b',
            # Legal/formal phrases (2-3 word compounds)
            r'\b(written\s+notice)\b',
            r'\b(certified\s+mail)\b',
            r'\b(good\s+faith)\b',
            r'\b(due\s+diligence)\b',
            r'\b(force\s+majeure)\b',
            r'\b(intellectual\s+property)\b',
            r'\b(confidential\s+information)\b',
            r'\b(material\s+breach)\b',
            r'\b(prior\s+written\s+consent)\b',
            r'\b(sole\s+discretion)\b',
            r'\b(binding\s+arbitration)\b',
            r'\b(liquidated\s+damages)\b',
            r'\b(indemnify\s+and\s+hold\s+harmless)\b',
            r'\b(termination\s+for\s+cause)\b',
            r'\b(termination\s+for\s+convenience)\b',
        ]
        
        extracted_phrases = []
        remaining_query = q
        
        for pattern in PHRASE_PATTERNS:
            matches = re.findall(pattern, remaining_query, re.IGNORECASE)
            for match in matches:
                phrase = match.strip()
                if phrase and len(phrase) > 2:
                    extracted_phrases.append(phrase.lower())
                    remaining_query = re.sub(
                        re.escape(match), ' ', remaining_query, flags=re.IGNORECASE
                    )
        
        # Sanitize remaining query (individual words)
        remaining_sanitized = self._sanitize_query_for_fulltext(remaining_query)
        remaining_words = [w for w in remaining_sanitized.split() if len(w) >= 3]
        
        # Remove stopwords
        STOPWORDS = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
            'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been', 'were', 'they',
            'this', 'that', 'with', 'from', 'what', 'which', 'their', 'will', 'would',
            'there', 'could', 'other', 'into', 'more', 'some', 'such', 'than', 'then',
            'these', 'when', 'where', 'who', 'how', 'does', 'about', 'each', 'she',
        }
        remaining_words = [w for w in remaining_words if w.lower() not in STOPWORDS]
        
        # Build final Lucene query
        query_parts = []
        
        # Add boosted phrase queries
        for phrase in extracted_phrases:
            safe_phrase = re.sub(r'([+\-&|!(){}[\]^"~*?:\\])', r'\\\1', phrase)
            query_parts.append(f'"{safe_phrase}"^2.0')
        
        # Add remaining individual words
        for word in remaining_words[:10]:
            safe_word = re.sub(r'([+\-&|!(){}[\]^"~*?:\\])', r'\\\1', word)
            query_parts.append(safe_word)
        
        result = ' '.join(query_parts)
        
        if extracted_phrases:
            logger.debug(
                "phrase_aware_fulltext_query_built",
                original_query=query[:100],
                extracted_phrases=extracted_phrases,
                final_query=result[:200],
            )
        
        return result if result.strip() else self._sanitize_query_for_fulltext(query)

    # =========================================================================
    # Shared Neo4j Index Management
    # =========================================================================

    async def _ensure_textchunk_fulltext_index(self) -> None:
        """Ensure the TextChunk fulltext index exists.

        Uses an index name that won't collide with other schemas.
        """
        if self.pipeline._textchunk_fulltext_index_checked:
            return
        self.pipeline._textchunk_fulltext_index_checked = True

        if not self.neo4j_driver:
            return

        driver = self.neo4j_driver  # Local ref for closure

        def _run_sync():
            with retry_session(driver) as session:
                session.run(
                    "CREATE FULLTEXT INDEX textchunk_fulltext IF NOT EXISTS "
                    "FOR (c:TextChunk) ON EACH [c.text]"
                )

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, _run_sync)
        except Exception as e:
            logger.warning(
                "textchunk_fulltext_index_ensure_failed",
                error=str(e),
                reason="Could not ensure fulltext index; will continue with available retrieval",
            )

    # =========================================================================
    # Shared Search Methods
    # =========================================================================

    async def _search_text_chunks_fulltext(
        self,
        query_text: str,
        top_k: int = 10,
        use_phrase_boost: bool = True
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Fulltext search only (Neo4j Lucene index) within the group.
        
        Returns chunks with section metadata for integration with Route 3's
        section-aware evidence collection.
        
        Supports optional folder filtering via self.folder_id.
        
        Args:
            query_text: The user query to search for.
            top_k: Maximum number of results to return.
            use_phrase_boost: If True, use phrase-aware query building.
            
        Returns:
            List of (chunk_dict, score) tuples
        """
        if not self.neo4j_driver:
            return []

        await self._ensure_textchunk_fulltext_index()
        group_id = self.group_id
        folder_id = self.folder_id
        driver = self.neo4j_driver  # Local ref for closure
        
        if use_phrase_boost:
            search_query = self._build_phrase_aware_fulltext_query(query_text)
        else:
            search_query = self._sanitize_query_for_fulltext(query_text)
        
        if not search_query:
            return []

        def _run_sync():
            # Build folder filter clause - applied after document join
            folder_filter = ""
            if folder_id:
                folder_filter = "AND (d)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})"
            
            q = f"""
            CALL db.index.fulltext.queryNodes('textchunk_fulltext', $query_text, {{limit: $candidate_k}})
            YIELD node, score
            WHERE node.group_id = $group_id
            OPTIONAL MATCH (node)-[:IN_DOCUMENT]->(d:Document {{group_id: $group_id}})
            WITH node, d, score
            WHERE d IS NULL OR d IS NOT NULL {folder_filter}
            OPTIONAL MATCH (node)-[:IN_SECTION]->(s:Section)
            RETURN node.id AS id,
                   node.text AS text,
                   node.chunk_index AS chunk_index,
                   d.id AS document_id,
                   d.title AS document_title,
                   d.source AS document_source,
                   s.id AS section_id,
                   s.path_key AS section_path_key,
                   score
            ORDER BY score DESC
            LIMIT $top_k
            """
            rows = []
            params = {
                "query_text": search_query,
                "group_id": group_id,
                "top_k": top_k,
                "candidate_k": top_k * 5,  # Oversample for folder filtering
            }
            if folder_id:
                params["folder_id"] = folder_id
                
            with retry_session(driver, read_only=True) as session:
                for r in session.run(q, **params):
                    chunk = {
                        "id": r["id"],
                        "text": r["text"],
                        "chunk_index": r.get("chunk_index", 0),
                        "document_id": r.get("document_id", ""),
                        "document_title": r.get("document_title", ""),
                        "document_source": r.get("document_source", ""),
                        "section_id": r.get("section_id", ""),
                        "section_path_key": r.get("section_path_key", ""),
                    }
                    rows.append((chunk, float(r.get("score") or 0.0)))
            return rows

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _run_sync)

    # =========================================================================
    # Hybrid RRF Search (BM25 + Vector)
    # =========================================================================

    async def _search_chunks_cypher25_hybrid_rrf(
        self,
        query_text: str,
        embedding: list,
        top_k: int = 20,
        vector_k: int = 30,
        bm25_k: int = 30,
        rrf_k: int = 60,
        use_phrase_boost: bool = True,
    ) -> List[Tuple[Dict[str, Any], float, bool]]:
        """Cypher 25 hybrid search with native BM25 + Vector RRF fusion.

        Uses the correct vector index based on V2 mode (chunk_embeddings_v2 vs
        chunk_embedding) via ``get_vector_index_name()``.

        Returns:
            List of (chunk_dict, rrf_score, is_anchor) tuples.
        """
        if not self.neo4j_driver:
            return []

        await self._ensure_textchunk_fulltext_index()
        group_id = self.group_id
        folder_id = self.folder_id

        if use_phrase_boost:
            bm25_query = self._build_phrase_aware_fulltext_query(query_text)
        else:
            bm25_query = self._sanitize_query_for_fulltext(query_text)

        if not bm25_query:
            bm25_query = query_text

        from src.worker.hybrid_v2.orchestrator import get_vector_index_name
        vector_index = get_vector_index_name()
        driver = self.neo4j_driver

        def _run_sync():
            # Build folder filter clause - applied after document join
            folder_filter = ""
            if folder_id:
                folder_filter = (
                    "\n            WITH node, rrfScore, hasBM25, hasVector, d, top_k"
                    "\n            WHERE d IS NULL OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})"
                )

            cypher = f"""
            CYPHER 25
            WITH $bm25_query AS bm25_query, $group_id AS group_id,
                 $bm25_k AS bm25_k, $embedding AS embedding,
                 $vector_k AS vector_k, $rrf_k AS rrf_k, $top_k AS top_k

            CALL (bm25_query, group_id) {{
                CALL db.index.fulltext.queryNodes('textchunk_fulltext', bm25_query)
                YIELD node, score
                WHERE node.group_id = group_id
                WITH node, score ORDER BY score DESC LIMIT $bm25_k
                WITH collect(node) AS nodes
                UNWIND range(0, size(nodes)-1) AS i
                RETURN nodes[i] AS node, (i + 1) AS rank
            }}
            WITH collect({{node: node, rank: rank}}) AS bm25List,
                 embedding, group_id, vector_k, rrf_k, top_k

            CALL (embedding, group_id) {{
                MATCH (node:TextChunk)
                SEARCH node IN (VECTOR INDEX {vector_index} FOR embedding WHERE node.group_id = group_id LIMIT $vector_k)
                SCORE AS score
                WITH collect(node) AS nodes
                UNWIND range(0, size(nodes)-1) AS i
                RETURN nodes[i] AS node, (i + 1) AS rank
            }}
            WITH bm25List, collect({{node: node, rank: rank}}) AS vectorList,
                 group_id, rrf_k, top_k

            WITH bm25List, vectorList, group_id, rrf_k, top_k,
                 [x IN bm25List | x.node] + [y IN vectorList | y.node] AS allNodes
            UNWIND allNodes AS node
            WITH DISTINCT node, bm25List, vectorList, group_id, rrf_k, top_k
            WITH node, group_id, rrf_k, top_k,
                 [b IN bm25List WHERE b.node = node | b.rank][0] AS bm25Rank,
                 [v IN vectorList WHERE v.node = node | v.rank][0] AS vectorRank
            WITH node, group_id, top_k,
                 (CASE WHEN bm25Rank IS NULL THEN 0.0
                       ELSE 1.0 / (rrf_k + bm25Rank) END) +
                 (CASE WHEN vectorRank IS NULL THEN 0.0
                       ELSE 1.0 / (rrf_k + vectorRank) END) AS rrfScore,
                 bm25Rank IS NOT NULL AS hasBM25,
                 vectorRank IS NOT NULL AS hasVector

            OPTIONAL MATCH (node)-[:IN_DOCUMENT]->(d:Document {{group_id: group_id}})
            {folder_filter}
            OPTIONAL MATCH (node)-[:IN_SECTION]->(s:Section)

            RETURN node.id AS id, node.text AS text,
                   node.chunk_index AS chunk_index,
                   d.id AS document_id, d.title AS document_title,
                   d.source AS document_source,
                   s.id AS section_id, s.path_key AS section_path_key,
                   rrfScore AS score, hasBM25, hasVector
            ORDER BY rrfScore DESC
            LIMIT $top_k
            """

            rows = []
            try:
                with retry_session(driver, read_only=True) as session:
                    params = dict(
                        bm25_query=bm25_query,
                        embedding=embedding,
                        group_id=group_id,
                        vector_k=vector_k,
                        bm25_k=bm25_k,
                        rrf_k=rrf_k,
                        top_k=top_k,
                    )
                    if folder_id:
                        params["folder_id"] = folder_id
                    result = session.run(cypher, **params)
                    for r in result:
                        chunk = {
                            "id": r["id"],
                            "text": r["text"],
                            "chunk_index": r.get("chunk_index", 0),
                            "document_id": r.get("document_id", ""),
                            "document_title": r.get("document_title", ""),
                            "document_source": r.get("document_source", ""),
                            "section_id": r.get("section_id", ""),
                            "section_path_key": r.get("section_path_key", ""),
                        }
                        is_anchor = bool(r.get("hasBM25")) and bool(r.get("hasVector"))
                        rows.append((chunk, float(r.get("score") or 0.0), is_anchor))
            except Exception as e:
                logger.error("cypher25_hybrid_rrf_failed", error=str(e), error_type=type(e).__name__)

            return rows

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(self._executor, _run_sync)

        logger.info(
            "cypher25_hybrid_rrf_complete",
            query=query_text[:80],
            bm25_query=bm25_query[:100],
            total_results=len(results),
            anchors=sum(1 for _, _, a in results if a),
            vector_index=vector_index,
        )

        return results

    async def _search_chunks_graph_native_bm25(
        self,
        query_text: str,
        top_k: int = 15,
        anchor_limit: int = 15,
        graph_decay: float = 0.5,
        use_phrase_boost: bool = True,
    ) -> List[Tuple[Dict[str, Any], float, bool]]:
        """Pure BM25 retrieval with phrase-aware queries (no vector search).

        Returns:
            List of (chunk_dict, score, is_anchor) tuples.
        """
        if not self.neo4j_driver:
            return []

        await self._ensure_textchunk_fulltext_index()
        group_id = self.group_id
        folder_id = self.folder_id
        driver = self.neo4j_driver

        if use_phrase_boost:
            search_query = self._build_phrase_aware_fulltext_query(query_text)
        else:
            search_query = self._sanitize_query_for_fulltext(query_text)

        if not search_query:
            return []

        def _run_sync():
            # Build folder filter clause
            folder_filter = ""
            if folder_id:
                folder_filter = "AND (d)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})"

            cypher = f"""
            CALL db.index.fulltext.queryNodes('textchunk_fulltext', $search_query)
            YIELD node AS chunk, score AS bm25_score
            WHERE chunk.group_id = $group_id

            OPTIONAL MATCH (chunk)-[:IN_DOCUMENT]->(d:Document {{group_id: $group_id}})
            WITH chunk, d, bm25_score
            WHERE d IS NULL OR d IS NOT NULL {folder_filter}
            OPTIONAL MATCH (chunk)-[:IN_SECTION]->(s:Section)

            RETURN chunk.id AS id, chunk.text AS text,
                   chunk.chunk_index AS chunk_index,
                   d.id AS document_id, d.title AS document_title,
                   d.source AS document_source,
                   s.id AS section_id, s.path_key AS section_path_key,
                   bm25_score AS score, true AS is_anchor
            ORDER BY score DESC
            LIMIT $top_k
            """

            rows = []
            try:
                with retry_session(driver, read_only=True) as session:
                    params = dict(
                        search_query=search_query,
                        group_id=group_id,
                        top_k=top_k,
                    )
                    if folder_id:
                        params["folder_id"] = folder_id
                    result = session.run(cypher, **params)
                    for r in result:
                        chunk = {
                            "id": r["id"],
                            "text": r["text"],
                            "chunk_index": r.get("chunk_index", 0),
                            "document_id": r.get("document_id", ""),
                            "document_title": r.get("document_title", ""),
                            "document_source": r.get("document_source", ""),
                            "section_id": r.get("section_id", ""),
                            "section_path_key": r.get("section_path_key", ""),
                        }
                        rows.append((chunk, float(r.get("score") or 0.0), True))
            except Exception as e:
                logger.error("graph_native_bm25_query_failed", error=str(e))

            return rows

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(self._executor, _run_sync)

        logger.info(
            "pure_bm25_phrase_search_complete",
            query=query_text[:80],
            search_query=search_query[:100],
            total_results=len(results),
        )

        return results

    async def _search_via_entity_graph(
        self,
        query: str,
        top_k: int = 8,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Graph-based retrieval via Entity nodes when hybrid search fails.
        
        This fallback uses the entity graph structure:
        1. Extract key terms from query
        2. Search Entity nodes by name/aliases
        3. Follow MENTIONS edges to get TextChunks
        4. Use IN_SECTION to get sibling chunks for context
        
        Supports optional folder filtering via self.folder_id.
        
        Args:
            query: User query string
            top_k: Maximum chunks to return
            
        Returns:
            List of (chunk_dict, score) tuples
        """
        if not self.neo4j_driver:
            return []
        
        # Extract meaningful terms from query
        STOPWORDS = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
            'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been', 'were', 'they',
            'this', 'that', 'with', 'from', 'what', 'which', 'their', 'will', 'would',
            'there', 'could', 'other', 'into', 'more', 'some', 'such', 'than', 'then',
            'these', 'when', 'where', 'who', 'how', 'does', 'about', 'each', 'she',
            'is', 'it', 'an', 'a', 'of', 'in', 'to', 'on', 'at', 'by', 'as', 'or',
        }
        
        words = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())
        search_terms = [w for w in words if w not in STOPWORDS]
        
        if not search_terms:
            return []
        
        term_pattern = '|'.join(re.escape(t) for t in search_terms)
        group_id = self.group_id
        folder_id = self.folder_id
        driver = self.neo4j_driver  # Local ref for closure
        
        def _run_sync():
            # Build folder filter clause
            folder_filter = ""
            if folder_id:
                folder_filter = "AND (d)-[:IN_FOLDER]->(:Folder {id: $folder_id, group_id: $group_id})"
            
            cypher = f"""
            CYPHER 25
            MATCH (e:Entity {{group_id: $group_id}})
            WHERE e.name =~ $pattern
               OR any(a IN coalesce(e.aliases, []) WHERE a =~ $pattern)
            
            // Route 2: Use direct TextChunk MENTIONS (propagated from Sentences at index time)
            MATCH (t:TextChunk)-[:MENTIONS]->(e)
            WHERE t.group_id = $group_id
            OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document {{group_id: $group_id}})
            WITH t, d, e
            WHERE d IS NULL OR d IS NOT NULL {folder_filter}
            OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
            
            WITH t, d, s, count(DISTINCT e) AS entityMatches
            
            RETURN t.id AS id,
                   t.text AS text,
                   t.chunk_index AS chunk_index,
                   d.id AS document_id,
                   d.title AS document_title,
                   d.source AS document_source,
                   s.id AS section_id,
                   s.path_key AS section_path_key,
                   entityMatches AS score
            ORDER BY entityMatches DESC, t.chunk_index ASC
            LIMIT $top_k
            """
            
            rows = []
            try:
                with retry_session(driver, read_only=True) as session:
                    regex_pattern = f'(?i).*({term_pattern}).*'
                    
                    params = {
                        "group_id": group_id,
                        "pattern": regex_pattern,
                        "top_k": top_k,
                    }
                    if folder_id:
                        params["folder_id"] = folder_id
                    
                    result = session.run(cypher, **params)
                    
                    for r in result:
                        chunk = {
                            "id": r["id"],
                            "text": r["text"],
                            "chunk_index": r.get("chunk_index", 0),
                            "document_id": r.get("document_id", ""),
                            "document_title": r.get("document_title", ""),
                            "document_source": r.get("document_source", ""),
                            "section_id": r.get("section_id", ""),
                            "section_path_key": r.get("section_path_key", ""),
                        }
                        normalized_score = float(r.get("score", 0)) / top_k
                        rows.append((chunk, normalized_score))
                        
                    logger.info("entity_graph_search_complete",
                               query=query[:50],
                               search_terms=search_terms[:5],
                               num_results=len(rows),
                               folder_id=folder_id)
                               
            except Exception as e:
                logger.error("entity_graph_search_failed",
                            error=str(e),
                            query=query[:50])
            
            return rows
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _run_sync)

    # =========================================================================
    # Citation Helpers
    # =========================================================================

    def _build_citations(
        self,
        chunks: List[Tuple[Dict[str, Any], float]],
        max_preview_len: int = 200,
    ) -> List[Citation]:
        """Build citation list from chunk results.
        
        Args:
            chunks: List of (chunk_dict, score) tuples
            max_preview_len: Maximum length for text preview
            
        Returns:
            List of Citation objects with full location metadata
        """
        citations = []
        for i, (chunk, score) in enumerate(chunks, start=1):
            text = chunk.get("text", "")
            preview = text[:max_preview_len] + "..." if len(text) > max_preview_len else text
            
            # Extract metadata for enhanced citations
            meta = chunk.get("metadata") or {}
            section_path = meta.get("section_path") or meta.get("section_path_key") or chunk.get("section_path", "")
            if isinstance(section_path, list):
                section_path = " > ".join(str(s) for s in section_path if s)
            
            citations.append(Citation(
                index=i,
                chunk_id=chunk.get("id", f"chunk_{i}"),
                document_id=chunk.get("document_id", ""),
                document_title=chunk.get("document_title", "Unknown"),
                document_url=chunk.get("document_source", "") or chunk.get("document_url", "") or meta.get("url", ""),
                page_number=chunk.get("page_number") or meta.get("page_number"),
                section_path=section_path,
                start_offset=chunk.get("start_offset") or meta.get("start_offset"),
                end_offset=chunk.get("end_offset") or meta.get("end_offset"),
                score=float(score),
                text_preview=preview,
            ))
        
        self._enrich_citations_with_geometry(citations)
        return citations

    def _enrich_citations_with_geometry(self, citations: List[Citation]) -> None:
        """Enrich citations with polygon geometry from Neo4j chunk metadata.

        After citations are built (typically 5-15 items), fetches the metadata
        JSON blob for each cited TextChunk in a single batch query. Attaches
        ``page_number``, ``sentences`` (polygon coords), and
        ``page_dimensions`` so the frontend can render click-to-highlight
        overlays on source PDFs.

        Community-report citations (``community_*``) are skipped since they
        have no document geometry.  Sentence-level citations
        (``*_sent_N``) are mapped to their parent TextChunk.
        """
        if not citations or not self.neo4j_driver:
            return

        # Collect chunk IDs, skipping community reports
        chunk_ids_to_enrich = [
            c.chunk_id for c in citations
            if c.chunk_id and not c.chunk_id.startswith("community_")
        ]
        if not chunk_ids_to_enrich:
            return

        # Separate sentence IDs from TextChunk IDs
        text_chunk_ids: set = set()
        sentence_parent_map: Dict[str, str] = {}  # sent_chunk_id -> parent_chunk_id
        for cid in chunk_ids_to_enrich:
            m = re.match(r"^(.+)_sent_(\d+)$", cid)
            if m:
                parent_id = m.group(1)
                sentence_parent_map[cid] = parent_id
                text_chunk_ids.add(parent_id)
            else:
                text_chunk_ids.add(cid)

        if not text_chunk_ids:
            return

        # Batch fetch metadata from Neo4j
        query = (
            "MATCH (t:TextChunk) "
            "WHERE t.id IN $ids AND t.group_id = $group_id "
            "RETURN t.id AS id, t.metadata AS metadata"
        )
        metadata_map: Dict[str, Dict[str, Any]] = {}
        try:
            with retry_session(self.neo4j_driver, read_only=True) as session:
                result = session.run(query, ids=list(text_chunk_ids), group_id=self.group_id)
                for record in result:
                    raw = record["metadata"]
                    meta: Dict[str, Any] = {}
                    if isinstance(raw, str):
                        try:
                            meta = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    elif isinstance(raw, dict):
                        meta = raw
                    if meta:
                        metadata_map[record["id"]] = meta
        except Exception as e:
            logger.warning("citation_geometry_enrichment_failed", error=str(e))
            return

        if not metadata_map:
            return

        # Attach geometry to each citation
        for citation in citations:
            cid = citation.chunk_id
            if not cid or cid.startswith("community_"):
                continue
            # For sentence citations, use parent chunk's metadata
            if cid in sentence_parent_map:
                meta = metadata_map.get(sentence_parent_map[cid], {})
            else:
                meta = metadata_map.get(cid, {})
            if not meta:
                continue

            if citation.page_number is None and meta.get("page_number") is not None:
                citation.page_number = meta["page_number"]
            if citation.start_offset is None and meta.get("start_offset") is not None:
                citation.start_offset = meta["start_offset"]
            if citation.end_offset is None and meta.get("end_offset") is not None:
                citation.end_offset = meta["end_offset"]
            if not citation.sentences and meta.get("sentences"):
                citation.sentences = meta["sentences"]
            if not citation.page_dimensions and meta.get("page_dimensions"):
                citation.page_dimensions = meta["page_dimensions"]

    @staticmethod
    def _match_sentence_to_claim(
        chunk_index: int,
        response: str,
        sentence_map: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Find the sentence within a chunk that best matches the LLM's claim.

        Extracts ~150 chars of text surrounding the ``[N]`` marker in the
        response, then computes word-overlap (Jaccard) against each sentence
        entry ``[Na]``, ``[Nb]``, … in *sentence_map*.

        Returns the best-matching entry dict, or ``None`` if no match found.
        """
        # Extract claim text surrounding [N] in the response
        marker = f"[{chunk_index}]"
        pos = response.find(marker)
        if pos < 0:
            return None

        # Window: 100 chars before marker, 50 chars after
        start = max(0, pos - 100)
        end = min(len(response), pos + len(marker) + 50)
        claim_text = response[start:end]

        # Tokenize claim into word set
        claim_words = set(re.findall(r"[a-z0-9]+", claim_text.lower()))
        if not claim_words:
            return None

        # Find all sentence entries for this chunk: [Na], [Nb], [Nc] ...
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for key, entry in sentence_map.items():
            # Keys are like "[1a]", "[1b]" — check if the number matches
            m = re.match(r"^\[(\d+)[a-z]\]$", key)
            if not m or int(m.group(1)) != chunk_index:
                continue

            sent_text = entry.get("sentence_text", "")
            if not sent_text:
                continue

            sent_words = set(re.findall(r"[a-z0-9]+", sent_text.lower()))
            if not sent_words:
                continue

            # Jaccard similarity
            inter = len(claim_words & sent_words)
            union = len(claim_words | sent_words)
            score = inter / union if union > 0 else 0.0

            if score > best_score:
                best_score = score
                best_match = entry

        # Require minimum overlap to avoid false matches
        return best_match if best_score >= 0.15 else None

    def _narrow_citations_to_sentences(
        self,
        citations: List[Citation],
        response: str,
        sentence_map: Dict[str, Dict[str, Any]],
    ) -> None:
        """Narrow chunk-level citations to specific sentences.

        For each citation ``[N]``, finds the sentence within that chunk
        that best matches the LLM's claim text near the ``[N]`` marker.
        Sets ``sentence_text``, ``sentence_offset``, and ``sentence_length``
        on the Citation object.

        Does not alter the LLM prompt — this is purely post-synthesis
        processing using the preserved sentence lookup table.
        """
        if not citations or not sentence_map or not response:
            return

        for citation in citations:
            if citation.sentence_text:
                # Already has sentence-level data
                continue

            match = self._match_sentence_to_claim(
                citation.index, response, sentence_map
            )
            if match:
                citation.sentence_text = match.get("sentence_text")
                citation.sentence_offset = match.get("sentence_offset")
                citation.sentence_length = match.get("sentence_length")

    def _diversify_chunks_by_section(
        self,
        chunks: List[Tuple[Dict[str, Any], float]],
        max_per_section: int = 3,
        total_limit: int = 10,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Diversify chunk results by section to avoid over-representation.
        
        Ensures no single section dominates the results, improving
        cross-document coverage.
        
        Args:
            chunks: List of (chunk_dict, score) tuples, already sorted by score
            max_per_section: Maximum chunks from any single section
            total_limit: Total maximum chunks to return
            
        Returns:
            Diversified list of (chunk_dict, score) tuples
        """
        section_counts: Dict[str, int] = {}
        diversified = []
        
        for chunk, score in chunks:
            section_key = (
                chunk.get("section_id") 
                or chunk.get("section_path_key") 
                or chunk.get("document_title") 
                or "unknown"
            )
            count = section_counts.get(section_key, 0)
            
            if count < max_per_section:
                diversified.append((chunk, score))
                section_counts[section_key] = count + 1
                
                if len(diversified) >= total_limit:
                    break
        
        return diversified
