"""Base route handler with shared utilities for Neo4j retrieval operations.

All route handlers inherit from BaseRouteHandler to access:
- Neo4j drivers (sync and async)
- LLM/embedding clients
- Common retrieval utilities (fulltext search, hybrid RRF, etc.)

This module provides dependency injection: route handlers receive a reference
to the main HybridPipeline and access its services through that reference.
"""

from __future__ import annotations

import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import structlog

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
        async def execute(self, query: str, response_type: str = "summary", knn_config: Optional[str] = None, prompt_variant: Optional[str] = None, synthesis_model: Optional[str] = None) -> RouteResult
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

    async def execute(self, query: str, response_type: str = "summary", knn_config: Optional[str] = None, prompt_variant: Optional[str] = None, synthesis_model: Optional[str] = None) -> RouteResult:
        """Execute the route on a query.
        
        Args:
            query: The user's natural language query
            response_type: Response format ("summary", "detailed_report", etc.)
            knn_config: Optional KNN configuration for SEMANTICALLY_SIMILAR edge filtering.
            
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
            with driver.session() as session:
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
                
            with driver.session() as session:
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
            
            MATCH (t:TextChunk {{group_id: $group_id}})-[:MENTIONS]->(e)
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
                with driver.session() as session:
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
        
        return citations

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
