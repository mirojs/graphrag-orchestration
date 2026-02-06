"""Enhanced Neo4j Graph Retrieval for Route 3.

This module provides graph-aware retrieval that fully utilizes:
1. MENTIONS edges: Entity → Source TextChunks (for citations)
2. RELATED_TO edges: Entity → Entity relationships (for context)
3. Section metadata: Document structure (for organized citations)
4. Entity embeddings: Semantic entity discovery
5. Section graph: IN_SECTION edges for section-aware diversification

V2 Mode (VOYAGE_V2_ENABLED=True):
- Chunks ARE sections (section-aware chunking)
- Section diversification skipped for normal queries (chunks already represent complete sections)
- Uses Voyage embeddings (2048 dim) for semantic search
- See VOYAGE_V2_IMPLEMENTATION_PLAN_2026-01-25.md Phase 3

Large Document Handling (January 26, 2026 Update):
- Documents exceeding Voyage's 32K token context window are bin-packed during embedding
- No overlap needed between bins - knowledge graph provides cross-bin connections:
  * Entities span bins via MENTIONS_ENTITY edges
  * PPR traversal hops across bins naturally
  * SHARES_ENTITY edges connect related chunks
- RETAINED: get_coverage_chunks() for coverage-style queries (ensures all sections covered)
- RETAINED: get_all_sections_chunks() for comprehensive queries (handles bin-packed docs)
- See PROPOSED_NEO4J_DOC_TITLE_FIX_2026-01-26.md for details
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import structlog
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = structlog.get_logger(__name__)

# Regex pattern to detect internal chunk-ID shaped entity names
# These are artifacts from ingestion and should not be used as hub entities
_CHUNK_ID_PATTERN = re.compile(r"^doc_[a-f0-9]{20,}_chunk_\d+", re.IGNORECASE)

# Regex patterns for detecting coverage-intent queries
_COVERAGE_INTENT_PATTERNS = [
    re.compile(r"\beach\s+(document|file|agreement|contract)\b", re.IGNORECASE),
    re.compile(r"\bevery\s+(document|file|agreement|contract)\b", re.IGNORECASE),
    re.compile(r"\ball\s+(the\s+)?(document|file|agreement|contract)s?\b", re.IGNORECASE),
    re.compile(r"\bsummarize\s+(each|every|all)\b", re.IGNORECASE),
    re.compile(r"\bfor\s+each\s+(document|file)\b", re.IGNORECASE),
    re.compile(r"\bacross\s+(all|the)\s+(document|file|agreement)s?\b", re.IGNORECASE),
]

# Regex patterns for detecting date metadata queries (deterministic answer from graph)
_DATE_METADATA_PATTERNS = [
    # Latest/newest/most recent date
    re.compile(r"\b(latest|newest|most\s+recent)\s+(explicit\s+)?(date|dated)\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(document|file|contract|agreement).*(latest|newest|most\s+recent)\s+(date|dated)\b", re.IGNORECASE),
    re.compile(r"\b(document|file|contract|agreement)\s+.*(latest|newest|most\s+recent)\s+(date|dated)\b", re.IGNORECASE),
    # Oldest/earliest date
    re.compile(r"\b(oldest|earliest|first)\s+(explicit\s+)?(date|dated)\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+(document|file|contract|agreement).*(oldest|earliest)\s+(date|dated)\b", re.IGNORECASE),
]


@dataclass
class SourceChunk:
    """A source text chunk with metadata."""
    chunk_id: str
    text: str
    entity_name: str  # Which entity this was retrieved via
    section_path: List[str] = field(default_factory=list)
    section_id: str = ""  # Section node ID from IN_SECTION edge
    document_id: str = ""  # Document node ID (stable per doc)
    document_title: str = ""
    document_source: str = ""
    relevance_score: float = 0.0
    # Location metadata from Azure DI (for sentence-level citations)
    page_number: Optional[int] = None
    start_offset: Optional[int] = None  # Character offset in original document
    end_offset: Optional[int] = None  # End character offset in original document


@dataclass
class EntityRelationship:
    """A relationship between two entities."""
    source_entity: str
    target_entity: str
    relationship_type: str
    description: str


@dataclass 
class EnhancedGraphContext:
    """Complete graph context for synthesis."""
    hub_entities: List[str]
    related_entities: List[str]
    relationships: List[EntityRelationship]
    source_chunks: List[SourceChunk]
    entity_descriptions: Dict[str, str]
    
    def get_citations(self) -> List[Dict[str, Any]]:
        """Format source chunks as citations."""
        citations = []
        for chunk in self.source_chunks:
            citations.append({
                "id": chunk.chunk_id,
                "text": chunk.text[:500],
                "entity": chunk.entity_name,
                "section": " > ".join(chunk.section_path) if chunk.section_path else None,
                "document": chunk.document_title or chunk.document_source,
                "score": chunk.relevance_score,
            })
        return citations
    
    def get_relationship_context(self) -> str:
        """Format relationships as context for LLM."""
        if not self.relationships:
            return ""
        
        lines = ["## Entity Relationships:"]
        for rel in self.relationships[:20]:  # Limit to top 20
            lines.append(f"- {rel.source_entity} → {rel.target_entity}: {rel.description[:100]}")
        return "\n".join(lines)


class EnhancedGraphRetriever:
    """
    Enhanced graph retrieval that fully utilizes Neo4j's power.
    
    Capabilities:
    1. MENTIONS traversal: Get source TextChunks for entities
    2. RELATED_TO traversal: Expand entity context via relationships
    3. Section-aware retrieval: Use document structure metadata
    4. Semantic entity search: Find entities by embedding similarity
    """
    
    def __init__(self, neo4j_driver, group_id: str, folder_id: Optional[str] = None):
        """
        Initialize the enhanced retriever.
        
        Args:
            neo4j_driver: Neo4j driver instance
            group_id: Document group ID for filtering
            folder_id: Optional folder ID for scoped search (None = all folders)
        """
        self.driver = neo4j_driver
        self.group_id = group_id
        self.folder_id = folder_id
    
    def _get_folder_filter_clause(self, doc_alias: str = "d") -> str:
        """Build Cypher WHERE clause for folder filtering.
        
        Returns empty string if folder_id is None (no filter).
        """
        if self.folder_id is None:
            return ""
        return f"AND ({doc_alias})-[:IN_FOLDER]->(:Folder {{id: $folder_id, group_id: $group_id}})"
    
    def _get_folder_params(self) -> dict:
        """Get folder_id parameter dict for Cypher queries."""
        if self.folder_id is not None:
            return {"folder_id": self.folder_id}
        return {}

    @staticmethod
    def _sanitize_query_for_fulltext(query: str) -> str:
        """Sanitize input for Neo4j Lucene fulltext index.

        Mirrors the basic approach in the hybrid orchestrator: keep alphanumerics
        and whitespace only, replacing other characters with spaces.
        """

        if not query:
            return ""
        out: List[str] = []
        for ch in query:
            if ch.isalnum() or ch.isspace():
                out.append(ch)
            else:
                out.append(" ")
        return " ".join("".join(out).split())

    @staticmethod
    def _doc_key(chunk: SourceChunk) -> str:
        """Stable key for per-document diversification.

        Prefer Document.id when available; fall back to source/title.
        """

        return (chunk.document_id or chunk.document_source or chunk.document_title or "unknown").strip().lower()

    @staticmethod
    def is_chunk_id_entity(name: str) -> bool:
        """Check if an entity name looks like an internal chunk ID.
        
        These are artifacts from ingestion (e.g., 'doc_6dee3910d6ae4a68b24788dc718d30c4_chunk_37')
        and should be filtered out from hub entity selection as they don't represent
        meaningful concepts and pollute graph expansion.
        """
        if not name:
            return False
        return bool(_CHUNK_ID_PATTERN.match(name.strip()))
    
    @staticmethod
    def filter_chunk_id_entities(entities: List[str]) -> List[str]:
        """Filter out chunk-ID shaped entities from a list.
        
        Returns only entities that represent meaningful concepts.
        """
        filtered = [e for e in entities if not EnhancedGraphRetriever.is_chunk_id_entity(e)]
        if len(filtered) < len(entities):
            logger.info(
                "chunk_id_entities_filtered",
                original_count=len(entities),
                filtered_count=len(filtered),
                removed_count=len(entities) - len(filtered),
            )
        return filtered
    
    @staticmethod
    def detect_coverage_intent(query: str) -> bool:
        """Detect if a query requires cross-document coverage.
        
        Returns True for queries like:
        - "Summarize each document"
        - "What is in every agreement?"
        - "Compare across all contracts"
        """
        if not query:
            return False
        for pattern in _COVERAGE_INTENT_PATTERNS:
            if pattern.search(query):
                return True
        return False

    @staticmethod
    def detect_date_metadata_query(query: str) -> Optional[str]:
        """Detect if a query is asking about document dates (deterministic answer).
        
        Returns:
            "latest" if asking for latest/newest/most recent date
            "oldest" if asking for oldest/earliest date
            None if not a date metadata query
            
        Examples:
        - "Which document has the latest date?" -> "latest"
        - "What is the oldest dated document?" -> "oldest"
        - "Tell me about insurance" -> None
        """
        if not query:
            return None
        query_lower = query.lower()
        
        # Check for latest/newest patterns
        if any(word in query_lower for word in ["latest", "newest", "most recent"]):
            if any(word in query_lower for word in ["date", "dated"]):
                return "latest"
        
        # Check for oldest/earliest patterns
        if any(word in query_lower for word in ["oldest", "earliest", "first"]):
            if any(word in query_lower for word in ["date", "dated"]):
                return "oldest"
        
        # Double-check with regex patterns for more complex phrasing
        for pattern in _DATE_METADATA_PATTERNS:
            if pattern.search(query):
                if any(word in query_lower for word in ["oldest", "earliest"]):
                    return "oldest"
                return "latest"
        
        return None

    @staticmethod
    def _keyword_to_regex(keyword: str) -> str:
        """Convert a keyword/phrase into a whitespace-robust Neo4j regex.

        Neo4j's `=~` matches the *entire* string, so we wrap with a leading/trailing
        match-all. To be robust to embedded newlines (common in PDF text), we use
        `[\s\S]*` instead of relying on DOTALL flags.

        Example: "monthly statement" -> (?i)[\s\S]*monthly\s+statement[\s\S]*
        """

        cleaned = (keyword or "").strip()
        if not cleaned:
            return ""

        parts = [p for p in re.split(r"\s+", cleaned) if p]
        if not parts:
            return ""

        # IMPORTANT: Neo4j regex patterns are values, not Python string literals.
        # Use single backslashes so Java regex receives patterns like \s and \S.
        joined = r"\s+".join(re.escape(p) for p in parts)
        return rf"(?i)[\s\S]*{joined}[\s\S]*"

    # =========================================================================
    # NEW 1-HOP METHODS (Phase 1 Week 2 - Graph Schema Enhancement)
    # These methods use the new foundation edges for faster traversal:
    # - APPEARS_IN_SECTION: Entity → Section (1-hop vs 2-hop)
    # - APPEARS_IN_DOCUMENT: Entity → Document (1-hop vs 3-hop)
    # - HAS_HUB_ENTITY: Section → Entity (for DRIFT bridge)
    # =========================================================================

    async def get_sections_for_entities(
        self,
        entity_names: List[str],
        use_new_edges: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get sections where entities appear (1-hop via APPEARS_IN_SECTION).
        
        This is a 2x speedup over the old 2-hop traversal:
        Old: Entity ← MENTIONS ← TextChunk → IN_SECTION → Section
        New: Entity → APPEARS_IN_SECTION → Section
        
        Args:
            entity_names: List of entity names to look up
            use_new_edges: If True, use APPEARS_IN_SECTION (1-hop). If False, fallback to 2-hop.
            
        Returns:
            List of dicts with section_id, section_title, mention_count, entity_name
        """
        if not entity_names or not self.driver:
            return []
        
        if use_new_edges:
            query = """
            UNWIND $entity_names AS entity_name
            // Find entity first (uses entity_name index, with alias support)
            MATCH (e:Entity)
            WHERE (toLower(e.name) = toLower(entity_name) OR e.id = entity_name
                   OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
              AND e.group_id = $group_id
            // Then traverse to sections via APPEARS_IN_SECTION
            MATCH (e)-[r:APPEARS_IN_SECTION]->(s:Section)
            WHERE r.group_id = $group_id
            RETURN 
                entity_name,
                s.id AS section_id,
                s.title AS section_title,
                s.path_key AS section_path_key,
                r.mention_count AS mention_count
            ORDER BY r.mention_count DESC
            """
        else:
            # Fallback to 2-hop traversal
            query = """
            UNWIND $entity_names AS entity_name
            MATCH (e:Entity)<-[:MENTIONS]-(c:TextChunk)-[:IN_SECTION]->(s:Section)
            WHERE (toLower(e.name) = toLower(entity_name) OR e.id = entity_name
                   OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
              AND c.group_id = $group_id
            WITH entity_name, s, count(c) AS mention_count
            RETURN 
                entity_name,
                s.id AS section_id,
                s.title AS section_title,
                s.path_key AS section_path_key,
                mention_count
            ORDER BY mention_count DESC
            """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        entity_names=entity_names,
                        group_id=self.group_id,
                    )
                    return [dict(record) for record in result]
            
            records = await loop.run_in_executor(None, _run_query)
            
            logger.info("get_sections_for_entities",
                       num_entities=len(entity_names),
                       num_sections=len(records),
                       use_new_edges=use_new_edges)
            
            return records
            
        except Exception as e:
            logger.error("get_sections_for_entities_error", error=str(e))
            return []

    async def get_documents_for_entities(
        self,
        entity_names: List[str],
        use_new_edges: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get documents where entities appear (1-hop via APPEARS_IN_DOCUMENT).
        
        This is a 5x speedup over the old 3-hop traversal:
        Old: Entity ← MENTIONS ← TextChunk → IN_DOCUMENT → Document
        New: Entity → APPEARS_IN_DOCUMENT → Document
        
        Args:
            entity_names: List of entity names to look up
            use_new_edges: If True, use APPEARS_IN_DOCUMENT (1-hop). If False, fallback to 3-hop.
            
        Returns:
            List of dicts with doc_id, doc_title, mention_count, section_count, entity_name
        """
        if not entity_names or not self.driver:
            return []
        
        folder_filter = self._get_folder_filter_clause("d")
        
        if use_new_edges:
            query = f"""
            UNWIND $entity_names AS entity_name
            // Find entity first (uses entity_name index, with alias support)
            MATCH (e:Entity)
            WHERE (toLower(e.name) = toLower(entity_name) OR e.id = entity_name
                   OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
              AND e.group_id = $group_id
            // Then traverse to documents via APPEARS_IN_DOCUMENT
            MATCH (e)-[r:APPEARS_IN_DOCUMENT]->(d:Document)
            WHERE r.group_id = $group_id
            {folder_filter}
            RETURN 
                entity_name,
                d.id AS doc_id,
                d.title AS doc_title,
                d.source AS doc_source,
                r.mention_count AS mention_count,
                r.section_count AS section_count
            ORDER BY r.mention_count DESC
            """
        else:
            # Fallback to 3-hop traversal
            query = f"""
            UNWIND $entity_names AS entity_name
            MATCH (e:Entity)<-[:MENTIONS]-(c:TextChunk)-[:IN_DOCUMENT]->(d:Document)
            WHERE (toLower(e.name) = toLower(entity_name) OR e.id = entity_name
                   OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
              AND c.group_id = $group_id
            {folder_filter}
            OPTIONAL MATCH (c)-[:IN_SECTION]->(s:Section)
            WITH entity_name, d, count(DISTINCT c) AS mention_count, count(DISTINCT s) AS section_count
            RETURN 
                entity_name,
                d.id AS doc_id,
                d.title AS doc_title,
                d.source AS doc_source,
                mention_count,
                section_count
            ORDER BY mention_count DESC
            """
        
        try:
            loop = asyncio.get_event_loop()
            params = {"entity_names": entity_names, "group_id": self.group_id}
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return [dict(record) for record in result]
            
            records = await loop.run_in_executor(None, _run_query)
            
            logger.info("get_documents_for_entities",
                       num_entities=len(entity_names),
                       num_documents=len(records),
                       use_new_edges=use_new_edges)
            
            return records
            
        except Exception as e:
            logger.error("get_documents_for_entities_error", error=str(e))
            return []

    async def get_hub_entities_for_sections(
        self,
        section_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Get hub entities for sections (via HAS_HUB_ENTITY edge).
        
        This is the LazyGraphRAG → HippoRAG bridge:
        Section → HAS_HUB_ENTITY → Entity
        
        Used by Route 4 (DRIFT) to seed PPR from section-based retrieval results.
        
        Args:
            section_ids: List of section IDs to look up
            
        Returns:
            List of dicts with section_id, entity_name, rank, mention_count
        """
        if not section_ids or not self.driver:
            return []
        
        query = """
        UNWIND $section_ids AS section_id
        MATCH (s:Section)-[r:HAS_HUB_ENTITY]->(e:Entity)
        WHERE s.id = section_id
          AND r.group_id = $group_id
        RETURN 
            section_id,
            s.title AS section_title,
            e.name AS entity_name,
            e.id AS entity_id,
            r.rank AS rank,
            r.mention_count AS mention_count
        ORDER BY section_id, r.rank
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        section_ids=section_ids,
                        group_id=self.group_id,
                    )
                    return [dict(record) for record in result]
            
            records = await loop.run_in_executor(None, _run_query)
            
            logger.info("get_hub_entities_for_sections",
                       num_sections=len(section_ids),
                       num_hub_entities=len(records))
            
            return records
            
        except Exception as e:
            logger.error("get_hub_entities_for_sections_error", error=str(e))
            return []

    async def get_entity_cross_doc_summary(
        self,
        entity_names: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get cross-document summary for entities using APPEARS_IN_DOCUMENT.
        
        This provides O(1) lookups for:
        - How many documents mention this entity?
        - How many sections mention this entity?
        - Total mention count across corpus
        
        Args:
            entity_names: List of entity names to summarize
            
        Returns:
            Dict mapping entity_name -> {doc_count, section_count, total_mentions, doc_titles}
        """
        if not entity_names or not self.driver:
            return {}
        
        folder_filter = self._get_folder_filter_clause("d")
        
        query = f"""
        UNWIND $entity_names AS entity_name
        MATCH (e:Entity)-[r:APPEARS_IN_DOCUMENT]->(d:Document)
        WHERE (toLower(e.name) = toLower(entity_name) OR e.id = entity_name
               OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
          AND r.group_id = $group_id
        {folder_filter}
        WITH entity_name, 
             count(d) AS doc_count,
             sum(r.section_count) AS section_count,
             sum(r.mention_count) AS total_mentions,
             collect(d.title)[0..5] AS doc_titles
        RETURN entity_name, doc_count, section_count, total_mentions, doc_titles
        """
        
        try:
            loop = asyncio.get_event_loop()
            params = {"entity_names": entity_names, "group_id": self.group_id}
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            summary = {}
            for record in records:
                summary[record["entity_name"]] = {
                    "doc_count": record["doc_count"],
                    "section_count": record["section_count"],
                    "total_mentions": record["total_mentions"],
                    "doc_titles": record["doc_titles"],
                }
            
            logger.info("get_entity_cross_doc_summary",
                       num_entities=len(entity_names),
                       entities_found=len(summary))
            
            return summary
            
        except Exception as e:
            logger.error("get_entity_cross_doc_summary_error", error=str(e))
            return {}

    async def get_related_sections_via_shared_entities(
        self,
        section_ids: List[str],
        cross_doc_only: bool = True,
        min_shared_count: int = 2,
        max_per_section: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Get related sections via SHARES_ENTITY edges (Phase 2 Week 3).
        
        This enables cross-document section discovery for Route 3 (Global Search):
        - Section1 → SHARES_ENTITY → Section2 (when they share entities)
        - Enables "find related sections discussing similar topics across documents"
        
        Args:
            section_ids: List of seed section IDs
            cross_doc_only: If True, only return sections from different documents
            min_shared_count: Minimum shared entities required
            max_per_section: Maximum related sections to return per seed section
            
        Returns:
            List of dicts with source_section_id, related_section_id, shared_count, 
            shared_entities, doc_id, doc_title, section_title
        """
        if not section_ids or not self.driver:
            return []
        
        # Build filter for cross-doc vs any
        cross_doc_filter = "AND s1.doc_id <> s2.doc_id" if cross_doc_only else ""
        
        # Build folder filter for related document - only allow sections from same folder
        folder_filter_clause = ""
        if self.folder_id:
            folder_filter_clause = "WHERE d IS NULL OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id})"
        
        query = f"""
        UNWIND $section_ids AS source_section_id
        MATCH (s1:Section {{id: source_section_id, group_id: $group_id}})
        MATCH (s1)-[r:SHARES_ENTITY]->(s2:Section)
        WHERE r.group_id = $group_id
          AND r.shared_count >= $min_shared_count
          {cross_doc_filter}
        WITH source_section_id, s1, s2, r
        ORDER BY r.shared_count DESC
        WITH source_section_id, 
             collect({{
                 related_section_id: s2.id,
                 related_section_title: s2.title,
                 related_doc_id: s2.doc_id,
                 shared_count: r.shared_count,
                 shared_entities: r.shared_entities
             }})[0..$max_per_section] AS related_sections
        UNWIND related_sections AS rel
        OPTIONAL MATCH (d:Document {{id: rel.related_doc_id, group_id: $group_id}})
        {folder_filter_clause}
        RETURN 
            source_section_id,
            rel.related_section_id AS related_section_id,
            rel.related_section_title AS related_section_title,
            rel.related_doc_id AS related_doc_id,
            d.title AS related_doc_title,
            rel.shared_count AS shared_count,
            rel.shared_entities AS shared_entities
        """
        
        try:
            loop = asyncio.get_event_loop()
            params = {
                "section_ids": section_ids,
                "group_id": self.group_id,
                "min_shared_count": min_shared_count,
                "max_per_section": max_per_section,
            }
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return [dict(record) for record in result]
            
            records = await loop.run_in_executor(None, _run_query)
            
            # Count unique source and related sections
            unique_sources = len(set(r["source_section_id"] for r in records))
            unique_related = len(set(r["related_section_id"] for r in records))
            cross_doc_count = len(set(r["related_doc_id"] for r in records if r.get("related_doc_id")))
            
            logger.info("get_related_sections_via_shared_entities",
                       num_seed_sections=len(section_ids),
                       sections_with_relations=unique_sources,
                       total_related_sections=unique_related,
                       cross_doc_relations=cross_doc_count,
                       cross_doc_only=cross_doc_only)
            
            return records
            
        except Exception as e:
            logger.error("get_related_sections_via_shared_entities_error", error=str(e))
            return []

    # =========================================================================
    # END NEW 1-HOP METHODS
    # =========================================================================
    
    async def get_full_context(
        self,
        hub_entities: List[str],
        expand_relationships: bool = True,
        get_source_chunks: bool = True,
        max_chunks_per_entity: int = 3,
        max_relationships: int = 30,
        section_diversify: bool = True,
        max_per_section: int = 3,
        max_per_document: int = 6,
        use_v2_mode: bool = False,
    ) -> EnhancedGraphContext:
        """
        Get complete graph context for the given hub entities.
        
        This is the main entry point that combines all retrieval strategies.
        
        Args:
            hub_entities: Initial hub entities from community matching
            expand_relationships: Whether to traverse RELATED_TO edges
            get_source_chunks: Whether to retrieve source TextChunks via MENTIONS
            max_chunks_per_entity: Max chunks to retrieve per entity
            max_relationships: Max relationships to retrieve
            section_diversify: Whether to diversify chunks across sections
            max_per_section: Max chunks per section (when section_diversify=True)
            max_per_document: Max chunks per document (when section_diversify=True)
            use_v2_mode: V2 mode - skip section diversification (chunks ARE sections)
            
        Returns:
            EnhancedGraphContext with all retrieved information
            
        Note on V2 Mode and Large Documents:
            In V2 mode, section diversification is skipped because chunks ARE sections.
            However, for large documents that required bin-packing during embedding,
            section coverage retrieval (`get_coverage_chunks()`) is still retained
            as a fallback to ensure cross-bin coverage. The knowledge graph provides
            cross-bin connections via entity edges, but explicit section coverage
            ensures no sections are missed in coverage-style queries.
        """
        # V2 mode: skip section diversification (chunks are already complete sections)
        # In V2 section-aware chunking, each chunk represents a semantic section
        # so per-section caps don't make sense - the chunk IS the section
        # NOTE: get_coverage_chunks() is still retained for coverage-style queries
        # to handle large bin-packed documents (see bin-packing in voyage_embed.py)
        if use_v2_mode:
            section_diversify = False
            logger.info("get_full_context_v2_mode", 
                       message="V2 mode: skipping section diversification (chunks ARE sections). "
                               "Note: get_coverage_chunks() retained for large document coverage.")
        
        # Check if section graph is enabled via environment variable
        section_graph_enabled = os.getenv("SECTION_GRAPH_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
        section_diversify = section_diversify and section_graph_enabled
        
        if not hub_entities:
            return EnhancedGraphContext(
                hub_entities=[],
                related_entities=[],
                relationships=[],
                source_chunks=[],
                entity_descriptions={},
            )
        
        # Helper for empty results
        async def empty_list():
            return []
        
        async def empty_dict():
            return {}
        
        # Run retrievals in parallel
        tasks = []
        
        if expand_relationships:
            tasks.append(self._get_relationships(hub_entities, max_relationships))
        else:
            tasks.append(empty_list())
        
        if get_source_chunks:
            tasks.append(self._get_source_chunks_via_mentions(hub_entities, max_chunks_per_entity))
        else:
            tasks.append(empty_list())
        
        tasks.append(self._get_entity_descriptions(hub_entities))
        
        relationships, source_chunks, entity_descriptions = await asyncio.gather(*tasks)
        
        # Apply section-aware diversification if enabled
        if section_diversify and source_chunks:
            source_chunks = await self._diversify_chunks_by_section(
                chunks=source_chunks,
                max_per_section=max_per_section,
                max_per_document=max_per_document,
            )
        
        # Extract related entities from relationships
        related_entities = set()
        for rel in relationships:
            if rel.source_entity not in hub_entities:
                related_entities.add(rel.source_entity)
            if rel.target_entity not in hub_entities:
                related_entities.add(rel.target_entity)
        
        return EnhancedGraphContext(
            hub_entities=hub_entities,
            related_entities=list(related_entities),
            relationships=relationships,
            source_chunks=source_chunks,
            entity_descriptions=entity_descriptions,
        )
    
    async def _get_source_chunks_via_new_edges(
        self,
        entity_names: List[str],
        max_per_entity: int = 3,
    ) -> List[SourceChunk]:
        """
        Get source chunks for entities using 1-hop APPEARS_IN_SECTION edges.
        
        This is the optimized path that uses pre-computed foundation edges:
        - Entity → APPEARS_IN_SECTION → Section
        - Then fetch chunks from those sections via IN_SECTION edges
        
        Much faster than 2-hop Entity → MENTIONS → Chunk → IN_SECTION → Section
        because we skip the intermediate chunk traversal.
        
        Args:
            entity_names: List of entity names to retrieve chunks for
            max_per_entity: Maximum chunks to return per entity
            
        Returns:
            List of SourceChunk objects with section and document metadata
        """
        if not entity_names:
            return []
        
        # Build folder filter for document optional match
        folder_filter_clause = ""
        if self.folder_id:
            folder_filter_clause = "WHERE d IS NULL OR (d.group_id = $group_id AND (d)-[:IN_FOLDER]->(:Folder {id: $folder_id}))"
        
        # Query: Use new 1-hop edges to get sections, then fetch chunks from those sections
        query = f"""
                UNWIND $entity_names AS entity_name
                MATCH (e:Entity)
                WHERE (toLower(e.name) = toLower(entity_name)
                       OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
                  AND e.group_id = $group_id
                // Use 1-hop APPEARS_IN_SECTION edge
                MATCH (e)-[:APPEARS_IN_SECTION]->(s:Section)
                WHERE s.group_id = $group_id
                // Get chunks from this section
                MATCH (c:TextChunk)-[:IN_SECTION]->(s)
                WHERE c.group_id = $group_id
                // Get document info
                OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document)
                {folder_filter_clause}
                WITH entity_name, c, s, d, 
                     // Prioritize chunks that mention the entity (if MENTIONS edge exists)
                     CASE WHEN exists((e)-[:MENTIONS]->(c)) THEN 1.0 ELSE 0.5 END AS score
                ORDER BY score DESC, coalesce(c.chunk_index, 0)
                WITH entity_name, collect({{
                    chunk_id: c.id,
                    text: c.text,
                    metadata: c.metadata,
                    chunk_index: coalesce(c.chunk_index, 0),
                    section_id: s.id,
                    section_path_key: s.path_key,
                    doc_id: d.id,
                    doc_title: d.title,
                    doc_source: d.source,
                    score: score
                }})[0..$max_per_entity] AS chunks
                UNWIND chunks AS chunk
                RETURN
                    entity_name,
                    chunk.chunk_id AS chunk_id,
                    chunk.text AS text,
                    chunk.metadata AS metadata,
                    chunk.section_id AS section_id,
                    chunk.section_path_key AS section_path_key,
                    chunk.doc_id AS doc_id,
                    chunk.doc_title AS doc_title,
                    chunk.doc_source AS doc_source,
                    chunk.score AS score
                """
        
        try:
            loop = asyncio.get_event_loop()
            params = {
                "entity_names": entity_names,
                "group_id": self.group_id,
                "max_per_entity": max_per_entity,
            }
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)

            chunks: List[SourceChunk] = []
            for record in records:
                metadata: Dict[str, Any] = {}
                if record.get("metadata"):
                    try:
                        metadata = (
                            json.loads(record["metadata"]) if isinstance(record["metadata"], str) else record["metadata"]
                        )
                    except Exception:
                        metadata = {}

                section_path = metadata.get("section_path", [])
                if record.get("section_path_key"):
                    section_path = (record["section_path_key"] or "").split(" > ")

                chunks.append(
                    SourceChunk(
                        chunk_id=record.get("chunk_id") or "",
                        text=record.get("text") or "",
                        entity_name=record.get("entity_name") or "",
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=record.get("doc_id") or metadata.get("document_id", "") or "",
                        document_title=record.get("doc_title") or metadata.get("document_title", ""),
                        document_source=record.get("doc_source") or metadata.get("url", ""),
                        relevance_score=float(record.get("score") or 0.0),
                        # Location metadata from Azure DI (for sentence-level citations)
                        page_number=metadata.get("page_number"),
                        start_offset=metadata.get("start_offset"),
                        end_offset=metadata.get("end_offset"),
                    )
                )
            
            logger.info(
                "chunks_via_new_edges_retrieved",
                num_entities=len(entity_names),
                chunks_found=len(chunks),
                top_entities=entity_names[:5],
            )
            
            return chunks
        
        except Exception as e:
            logger.error(
                "chunks_via_new_edges_error",
                error=str(e),
                num_entities=len(entity_names),
            )
            return []
    
    async def _get_source_chunks_via_mentions(
        self,
        entity_names: List[str],
        max_per_entity: int = 3,
    ) -> List[SourceChunk]:
        """
        Get source chunks that MENTION these entities.

        Current hybrid pipeline schema (as of Jan 2026):
        - Chunk label: `TextChunk`
        - Entity label: `__Entity__`
        - Edge direction: (TextChunk)-[:MENTIONS]->(__Entity__)
        - Alias support: matches entity.name OR any alias in entity.aliases[]
        
        Also fetches section_id via IN_SECTION edge for diversification.
        This provides the source text for citations.
        """
        if not entity_names or not self.driver:
            return []
        
        # Build folder filter for document optional match
        folder_filter_clause = ""
        if self.folder_id:
            folder_filter_clause = "WHERE d IS NULL OR (d.group_id = $group_id AND (d)-[:IN_FOLDER]->(:Folder {id: $folder_id}))"
        
        # Simplified query for current hybrid pipeline schema
        # Includes alias support for flexible entity matching
        query = f"""
                UNWIND $entity_names AS entity_name
                MATCH (t:TextChunk)-[:MENTIONS]->(e)
                WHERE (e:Entity OR e:`__Entity__`)
                  AND (toLower(e.name) = toLower(entity_name)
                       OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
                    AND t.group_id = $group_id
                    AND e.group_id = $group_id
                OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
                OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
                {folder_filter_clause}
                WITH entity_name, t, s, d
                ORDER BY coalesce(t.chunk_index, 0)
                WITH entity_name, collect({{
                        chunk_id: t.id,
                        text: t.text,
                        metadata: t.metadata,
                        chunk_index: coalesce(t.chunk_index, 0),
                        section_id: s.id,
                        section_path_key: s.path_key,
                        doc_id: d.id,
                        doc_title: d.title,
                        doc_source: d.source
                }})[0..$max_per_entity] AS chunks
                UNWIND chunks AS chunk
                RETURN
                        entity_name,
                        chunk.chunk_id AS chunk_id,
                        chunk.text AS text,
                        chunk.metadata AS metadata,
                        chunk.section_id AS section_id,
                        chunk.section_path_key AS section_path_key,
                        chunk.doc_id AS doc_id,
                        chunk.doc_title AS doc_title,
                        chunk.doc_source AS doc_source
                """

        # Build folder filter for fallback query
        fallback_folder_filter = "WHERE d IS NULL OR (d.group_id = $group_id"
        if self.folder_id:
            fallback_folder_filter += " AND (d)-[:IN_FOLDER]->(:Folder {id: $folder_id}))"
        else:
            fallback_folder_filter += ")"
        
        fallback_query = f"""
                UNWIND $entity_names AS entity_name
                WITH entity_name, $group_id AS group_id, $max_per_entity AS max_per_entity, $probe_limit AS probe_limit
                CALL db.index.fulltext.queryNodes('textchunk_fulltext', entity_name, {{limit: probe_limit}})
                    YIELD node AS t, score
                WHERE t.group_id = group_id
                OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
                OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
                {fallback_folder_filter}
                WITH
                    entity_name,
                    max_per_entity,
                    t,
                    score,
                    s,
                    d
                ORDER BY score DESC
                WITH entity_name, max_per_entity, collect({{
                    chunk_id: t.id,
                    text: t.text,
                    metadata: t.metadata,
                    section_id: s.id,
                    section_path_key: s.path_key,
                    doc_id: d.id,
                    doc_title: d.title,
                    doc_source: d.source,
                    score: score
                }})[0..max_per_entity] AS chunks
                UNWIND chunks AS chunk
                RETURN
                    entity_name,
                    chunk.chunk_id AS chunk_id,
                    chunk.text AS text,
                    chunk.metadata AS metadata,
                    chunk.section_id AS section_id,
                    chunk.section_path_key AS section_path_key,
                    chunk.doc_id AS doc_id,
                    chunk.doc_title AS doc_title,
                    chunk.doc_source AS doc_source,
                    chunk.score AS score
                """
        
        try:
            loop = asyncio.get_event_loop()
            params = {
                "entity_names": entity_names,
                "group_id": self.group_id,
                "max_per_entity": max_per_entity,
            }
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)

            chunks: List[SourceChunk] = []
            for record in records:
                metadata: Dict[str, Any] = {}
                if record.get("metadata"):
                    try:
                        metadata = (
                            json.loads(record["metadata"]) if isinstance(record["metadata"], str) else record["metadata"]
                        )
                    except Exception:
                        metadata = {}

                section_path = metadata.get("section_path", [])
                if record.get("section_path_key"):
                    section_path = (record["section_path_key"] or "").split(" > ")

                chunks.append(
                    SourceChunk(
                        chunk_id=record.get("chunk_id") or "",
                        text=record.get("text") or "",
                        entity_name=record.get("entity_name") or "",
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=record.get("doc_id") or metadata.get("document_id", "") or "",
                        document_title=record.get("doc_title") or metadata.get("document_title", ""),
                        document_source=record.get("doc_source") or metadata.get("url", ""),
                        relevance_score=float(record.get("score") or 0.0),
                        page_number=metadata.get("page_number"),
                        start_offset=metadata.get("start_offset"),
                        end_offset=metadata.get("end_offset"),
                    )
                )

            # Fallback: if the graph has no MENTIONS links, try fulltext retrieval for entity strings.
            fallback_used = False
            if not chunks:
                sanitized = [self._sanitize_query_for_fulltext(n) for n in entity_names]
                sanitized = [n for n in sanitized if n]
                if sanitized:
                    fallback_used = True
                    probe_limit = min(max_per_entity * 50, 500)

                    def _run_fallback():
                        fallback_params = {
                            "entity_names": sanitized,
                            "group_id": self.group_id,
                            "max_per_entity": max_per_entity,
                            "probe_limit": probe_limit,
                        }
                        fallback_params.update(self._get_folder_params())
                        with self.driver.session() as session:
                            result = session.run(fallback_query, **fallback_params)
                            return list(result)

                    records = await loop.run_in_executor(None, _run_fallback)
                    for record in records:
                        metadata: Dict[str, Any] = {}
                        if record.get("metadata"):
                            try:
                                metadata = (
                                    json.loads(record["metadata"])
                                    if isinstance(record["metadata"], str)
                                    else record["metadata"]
                                )
                            except Exception:
                                metadata = {}

                        section_path = metadata.get("section_path", [])
                        if record.get("section_path_key"):
                            section_path = (record["section_path_key"] or "").split(" > ")

                        chunks.append(
                            SourceChunk(
                                chunk_id=record.get("chunk_id") or "",
                                text=record.get("text") or "",
                                entity_name=record.get("entity_name") or "",
                                section_path=section_path,
                                section_id=record.get("section_id") or "",
                                document_id=record.get("doc_id") or metadata.get("document_id", "") or "",
                                document_title=record.get("doc_title") or metadata.get("document_title", ""),
                                document_source=record.get("doc_source") or metadata.get("url", ""),
                                relevance_score=float(record.get("score") or 0.0),
                                page_number=metadata.get("page_number"),
                                start_offset=metadata.get("start_offset"),
                                end_offset=metadata.get("end_offset"),
                            )
                        )

            logger.info(
                "mentions_retrieval_complete",
                num_entities=len(entity_names),
                num_chunks=len(chunks),
                used_fulltext_fallback=fallback_used,
            )
            return chunks
            
        except Exception as e:
            logger.error("mentions_retrieval_failed", error=str(e))
            return []

    async def get_ppr_evidence_chunks(
        self,
        evidence_nodes: List[Tuple[str, float]],
        max_per_entity: int = 2,
        max_per_section: int = 3,
        max_per_document: int = 5,
        max_total: int = 25,
        use_new_edges: bool = False,  # MENTIONS path is faster for chunk retrieval
    ) -> List[SourceChunk]:
        """
        Fetch text chunks for HippoRAG PPR evidence nodes (DETAIL RECOVERY).
        
        This is the critical "Stage 3.5" from the architecture:
        - PPR gives us ranked entities that are mathematically connected to the query
        - We fetch the raw text chunks that MENTION those entities
        - These chunks provide the fine-grained detail that community summaries would lose
        
        The PPR score determines entity priority - higher-scored entities get their
        chunks fetched first, ensuring the most relevant details are captured.
        
        Args:
            evidence_nodes: List of (entity_name, ppr_score) from HippoRAG PPR tracing
            max_per_entity: Max chunks to fetch per PPR entity
            max_per_section: Max chunks from any single section (diversification)
            max_per_document: Max chunks from any single document (diversification)
            max_total: Total cap on returned chunks
            
        Returns:
            List of SourceChunks with section metadata, ordered by PPR relevance then diversified
        """
        if not evidence_nodes:
            return []
        
        # Sort by PPR score descending (should already be sorted, but ensure)
        sorted_nodes = sorted(evidence_nodes, key=lambda x: x[1], reverse=True)
        entity_names = [name for name, _ in sorted_nodes]
        
        # Fetch chunks: use new 1-hop edges if available, otherwise fall back to 2-hop
        if use_new_edges:
            all_chunks = await self._get_source_chunks_via_new_edges(
                entity_names=entity_names,
                max_per_entity=max_per_entity,
            )
        else:
            all_chunks = await self._get_source_chunks_via_mentions(
                entity_names=entity_names,
                max_per_entity=max_per_entity,
            )
        
        if not all_chunks:
            logger.warning("ppr_evidence_no_chunks_found",
                          num_entities=len(entity_names),
                          top_entities=entity_names[:5])
            return []
        
        # Assign PPR scores to chunks based on their source entity
        entity_scores = {name: score for name, score in sorted_nodes}
        for chunk in all_chunks:
            chunk.relevance_score = entity_scores.get(chunk.entity_name, 0.0)
        
        # Sort by PPR score (entity-level relevance)
        all_chunks.sort(key=lambda c: c.relevance_score, reverse=True)
        
        # Diversify across sections and documents
        diversified = await self._diversify_chunks_by_section(
            chunks=all_chunks,
            max_per_section=max_per_section,
            max_per_document=max_per_document,
        )
        
        # Apply total cap
        result = diversified[:max_total]
        
        logger.info("ppr_evidence_chunks_retrieved",
                   num_ppr_entities=len(entity_names),
                   raw_chunks=len(all_chunks),
                   diversified_chunks=len(diversified),
                   final_chunks=len(result),
                   top_entities=entity_names[:5],
                   top_ppr_scores=[round(s, 4) for _, s in sorted_nodes[:5]])
        
        return result

    async def _diversify_chunks_by_section(
        self,
        chunks: List[SourceChunk],
        max_per_section: int = 3,
        max_per_document: int = 6,
    ) -> List[SourceChunk]:
        """Diversify chunks across sections and documents.
        
        Uses a greedy selection algorithm that respects per-section and per-document caps
        while preserving the original ordering (which reflects entity relevance).
        
        Args:
            chunks: List of SourceChunks (already ordered by relevance)
            max_per_section: Maximum chunks to take from any single section
            max_per_document: Maximum chunks to take from any single document
            
        Returns:
            Diversified list of chunks
        """
        if not chunks:
            return []
        
        per_section_counts: Dict[str, int] = {}
        per_doc_counts: Dict[str, int] = {}
        diversified: List[SourceChunk] = []
        skipped_section = 0
        skipped_doc = 0
        
        for chunk in chunks:
            # Get section key (use section_id if available, else path_key, else "[unknown]")
            section_key = chunk.section_id or " > ".join(chunk.section_path) if chunk.section_path else "[unknown]"
            doc_key = self._doc_key(chunk)
            
            # Check section cap
            if per_section_counts.get(section_key, 0) >= max_per_section:
                skipped_section += 1
                continue
            
            # Check document cap
            if per_doc_counts.get(doc_key, 0) >= max_per_document:
                skipped_doc += 1
                continue
            
            # Accept this chunk
            diversified.append(chunk)
            per_section_counts[section_key] = per_section_counts.get(section_key, 0) + 1
            per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
        
        logger.info(
            "section_diversification_complete",
            input_chunks=len(chunks),
            output_chunks=len(diversified),
            skipped_section_cap=skipped_section,
            skipped_doc_cap=skipped_doc,
            unique_sections=len(per_section_counts),
            unique_docs=len(per_doc_counts),
        )
        
        return diversified

    async def get_keyword_boost_chunks(
        self,
        keywords: List[str],
        max_per_document: int = 2,
        max_total: int = 10,
        min_matches: int = 1,
    ) -> List[SourceChunk]:
        """Retrieve chunks by lexical keyword matching for evidence boosting.

        Intended as a small additive boost to improve cross-document coverage
        for queries where important facts may not map cleanly to hub entities.
        """
        if not keywords or not self.driver:
            return []

        # Neo4j regex matching (`=~`) proved brittle across versions/configs and
        # tends to miss phrases split by newlines/punctuation from PDF extraction.
        # Instead, normalize both chunk text and keywords by removing whitespace
        # and a small punctuation set, then use CONTAINS.
        cleaned_keywords = [k.strip() for k in keywords if k and k.strip()]
        keyword_needles = [re.sub(r"[\s\-\.,:;()\[\]{}]", "", k.lower()) for k in cleaned_keywords]
        keyword_needles = [k for k in keyword_needles if k]
        if not keyword_needles:
            return []

        # Pull a moderate candidate set, then diversify by document in Python.
        candidate_limit = max(50, max_total * 10)

        query = """
        MATCH (t:TextChunk)
        WHERE t.group_id = $group_id
        WITH t,
             replace(
                 replace(
                     replace(
                         replace(
                             replace(
                                 replace(
                                     replace(
                                         replace(
                                             replace(
                                                 replace(
                                                     replace(
                                                         replace(
                                                             replace(toLower(coalesce(t.text, "")), " ", ""),
                                                         "\\n", ""),
                                                     "\\r", ""),
                                                 "\\t", ""),
                                             "-", ""),
                                         ".", ""),
                                     ",", ""),
                                 ":", ""),
                             ";", ""),
                         "(", ""),
                     ")", ""),
                 "[", ""),
             "]", "") AS t_norm
        WITH t, t_norm,
             reduce(cnt = 0, k IN $keyword_needles |
                 cnt + CASE WHEN t_norm CONTAINS k THEN 1 ELSE 0 END
             ) AS match_count
        WHERE match_count >= $min_matches
        OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
        OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
        WHERE d IS NULL OR (d.group_id = $group_id AND ($folder_id IS NULL OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id})))
        RETURN
            t.id AS chunk_id,
            t.text AS text,
            t.metadata AS metadata,
            t.chunk_index AS chunk_index,
            match_count AS match_count,
            s.id AS section_id,
            s.path_key AS section_path_key,
            d.id AS doc_id,
            d.title AS doc_title,
            d.source AS doc_source
        ORDER BY match_count DESC, chunk_index ASC
        LIMIT $candidate_limit
        """
        
        # Use Cypher 25 for optimized CASE expression handling
        from src.worker.services.async_neo4j_service import cypher25_query
        query = cypher25_query(query)

        try:
            loop = asyncio.get_event_loop()

            def _run_query():
                with self.driver.session() as session:
                    params = {
                        "group_id": self.group_id,
                        "keyword_needles": keyword_needles,
                        "min_matches": min_matches,
                        "candidate_limit": candidate_limit,
                        "folder_id": self.folder_id,
                    }
                    result = session.run(query, **params)
                    return list(result)

            records = await loop.run_in_executor(None, _run_query)

            candidates: List[SourceChunk] = []
            for record in records:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}

                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key:
                    section_path = section_path_key.split(" > ")

                candidates.append(
                    SourceChunk(
                        chunk_id=record["chunk_id"],
                        text=record.get("text") or "",
                        entity_name="keyword_boost",
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=record.get("doc_id") or metadata.get("document_id", "") or "",
                        document_title=record.get("doc_title") or metadata.get("document_title", "") or "",
                        document_source=record.get("doc_source") or metadata.get("url", "") or "",
                        relevance_score=float(record.get("match_count") or 0.0),
                    )
                )

            # Diversify while preserving relevance:
            # candidates are already sorted by match_count DESC, then chunk order.
            # Greedily take the best remaining chunk, respecting per-document caps.
            per_doc_counts: Dict[str, int] = {}
            diversified: List[SourceChunk] = []
            for chunk in candidates:
                doc_key = self._doc_key(chunk)
                if per_doc_counts.get(doc_key, 0) >= max_per_document:
                    continue
                diversified.append(chunk)
                per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
                if len(diversified) >= max_total:
                    break

            logger.info(
                "keyword_boost_chunks_complete",
                num_keywords=len(keyword_needles),
                num_candidates=len(candidates),
                num_chunks=len(diversified),
                max_per_document=max_per_document,
                max_total=max_total,
            )

            return diversified

        except Exception as e:
            logger.error("keyword_boost_chunks_failed", error=str(e))
            return []

    async def get_document_lead_chunks(
        self,
        *,
        max_total: int = 8,
        candidate_chunk_indexes: Optional[List[int]] = None,
        min_text_chars: int = 20,
    ) -> List[SourceChunk]:
        """Return one early ("lead") chunk per document.

        Strategy: For each document, pick the **earliest** chunk (lowest
        chunk_index) among candidates that meets the minimum length threshold.

        Note: This feature is experimental and disabled by default. The BM25 +
        graph section search approach is more scalable for cross-document queries.
        """
        if not self.driver:
            return []

        if candidate_chunk_indexes is None:
            candidate_chunk_indexes = [0, 1, 2, 3, 4, 5]

        if max_total <= 0:
            return []

        folder_filter = self._get_folder_filter_clause("d")

        query = f"""
        MATCH (d:Document)<-[:IN_DOCUMENT]-(t:TextChunk)
        WHERE d.group_id = $group_id
          AND t.group_id = $group_id
          AND t.chunk_index IN $chunk_indexes
        {folder_filter}
        OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
        RETURN
            t.id AS chunk_id,
            t.text AS text,
            t.metadata AS metadata,
            t.chunk_index AS chunk_index,
            s.id AS section_id,
            s.path_key AS section_path_key,
            d.id AS doc_id,
            d.title AS doc_title,
            d.source AS doc_source
        ORDER BY doc_id ASC, chunk_index ASC
        """

        try:
            loop = asyncio.get_event_loop()
            params = {
                "group_id": self.group_id,
                "chunk_indexes": candidate_chunk_indexes,
            }
            params.update(self._get_folder_params())

            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)

            records = await loop.run_in_executor(None, _run_query)

            def _make_chunk(record: Any, *, text: str) -> SourceChunk:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}

                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key:
                    section_path = section_path_key.split(" > ")

                doc_id = (record.get("doc_id") or "").strip()
                return SourceChunk(
                    chunk_id=record["chunk_id"],
                    text=text,
                    entity_name="doc_lead",
                    section_path=section_path,
                    section_id=record.get("section_id") or "",
                    document_id=doc_id,
                    document_title=record.get("doc_title") or metadata.get("document_title", "") or "",
                    document_source=record.get("doc_source") or metadata.get("url", "") or "",
                    relevance_score=1.0,
                )

            # Collect all candidate chunks per document, then pick the earliest.
            candidates_by_doc: Dict[str, List[Tuple[int, Any]]] = {}
            for record in records:
                doc_id = (record.get("doc_id") or "").strip()
                if not doc_id:
                    continue
                text = (record.get("text") or "").strip()
                if len(text) < int(min_text_chars):
                    continue
                if doc_id not in candidates_by_doc:
                    candidates_by_doc[doc_id] = []
                candidates_by_doc[doc_id].append((len(text), record))

            # Pick the "Lead" chunk per doc.
            # Strategy: Prefer the EARLIEST chunk (lowest index) that meets the length threshold.
            choices: List[SourceChunk] = []

            for doc_id, cands in candidates_by_doc.items():
                if len(choices) >= max_total:
                    break
                
                # Sort by chunk_index ASC (primary) to get the true "lead" chunk.
                # cands is List[Tuple[int, Record]] -> x[1] is the record.
                cands.sort(key=lambda x: x[1].get("chunk_index", 999))
                
                best_len, best_record = cands[0]
                text = (best_record.get("text") or "").strip()
                choices.append(_make_chunk(best_record, text=text))

            logger.info(
                "document_lead_chunks_complete",
                num_docs=len(choices),
                total_docs_in_group=len(candidates_by_doc),
                max_total=max_total,
                chunk_indexes=candidate_chunk_indexes,
                min_text_chars=min_text_chars,
            )

            return choices

        except Exception as e:
            logger.error("document_lead_chunks_failed", error=str(e))
            return []

    async def get_section_boost_chunks(
        self,
        section_keywords: List[str],
        max_per_section: int = 3,
        max_per_document: int = 3,
        max_total: int = 12,
        min_matches: int = 1,
    ) -> List[SourceChunk]:
        """Retrieve chunks from sections whose path_key matches section keywords.

        This is meant as a Route-1-like alternative to brittle keyword matching over
        raw chunk text. It uses the Section graph (IN_SECTION edges) and section
        path metadata to pull likely-relevant clauses, then diversifies across
        sections and documents.
        """
        if not section_keywords or not self.driver:
            return []

        lowered = [k.strip().lower() for k in section_keywords if k and k.strip()]
        if not lowered:
            return []

        candidate_limit = max(60, max_total * 10)

        query = """
        MATCH (s:Section)<-[:IN_SECTION]-(t:TextChunk)
        WHERE t.group_id = $group_id
          AND s.group_id = $group_id
        WITH t, s,
             reduce(cnt = 0, k IN $section_keywords |
                cnt + CASE WHEN toLower(coalesce(s.path_key, "")) CONTAINS k THEN 1 ELSE 0 END
             ) AS match_count
        WHERE match_count >= $min_matches
        OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
        WHERE d IS NULL OR (d.group_id = $group_id AND ($folder_id IS NULL OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id})))
        RETURN
            t.id AS chunk_id,
            t.text AS text,
            t.metadata AS metadata,
            t.chunk_index AS chunk_index,
            match_count AS match_count,
            s.id AS section_id,
            s.path_key AS section_path_key,
            d.id AS doc_id,
            d.title AS doc_title,
            d.source AS doc_source
        ORDER BY match_count DESC, chunk_index ASC
        LIMIT $candidate_limit
        """

        try:
            loop = asyncio.get_event_loop()

            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        group_id=self.group_id,
                        section_keywords=lowered,
                        min_matches=min_matches,
                        candidate_limit=candidate_limit,
                        folder_id=self.folder_id,
                    )
                    return list(result)

            records = await loop.run_in_executor(None, _run_query)

            candidates: List[SourceChunk] = []
            for record in records:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}

                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key:
                    section_path = section_path_key.split(" > ")

                candidates.append(
                    SourceChunk(
                        chunk_id=record["chunk_id"],
                        text=record.get("text") or "",
                        entity_name="section_boost",
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=record.get("doc_id") or metadata.get("document_id", "") or "",
                        document_title=record.get("doc_title") or metadata.get("document_title", "") or "",
                        document_source=record.get("doc_source") or metadata.get("url", "") or "",
                        relevance_score=float(record.get("match_count") or 0.0),
                    )
                )

            # Diversify across sections + documents, preserving match_count/chunk order.
            per_section_counts: Dict[str, int] = {}
            per_doc_counts: Dict[str, int] = {}
            diversified: List[SourceChunk] = []
            for chunk in candidates:
                section_key = chunk.section_id or (" > ".join(chunk.section_path) if chunk.section_path else "[unknown]")
                doc_key = self._doc_key(chunk)

                if per_section_counts.get(section_key, 0) >= max_per_section:
                    continue
                if per_doc_counts.get(doc_key, 0) >= max_per_document:
                    continue

                diversified.append(chunk)
                per_section_counts[section_key] = per_section_counts.get(section_key, 0) + 1
                per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
                if len(diversified) >= max_total:
                    break

            logger.info(
                "section_boost_chunks_complete",
                num_keywords=len(lowered),
                num_candidates=len(candidates),
                num_chunks=len(diversified),
                max_per_section=max_per_section,
                max_per_document=max_per_document,
                max_total=max_total,
            )

            return diversified

        except Exception as e:
            logger.error("section_boost_chunks_failed", error=str(e))
            return []

    async def get_section_id_boost_chunks(
        self,
        section_ids: List[str],
        max_per_section: int = 3,
        max_per_document: int = 3,
        max_total: int = 12,
        spread_within_section: bool = False,
    ) -> List[SourceChunk]:
        """Retrieve chunks from explicitly selected section IDs.

        This is used by Route 3 "semantic section discovery": we first find the
        most relevant sections for a user query (via vector/fulltext chunk search),
        then expand within those sections using the section graph.
        """
        if not section_ids or not self.driver:
            return []

        normalized = [s.strip() for s in section_ids if s and s.strip()]
        if not normalized:
            return []

        candidate_limit = max(60, max_total * 10)

        query = """
        MATCH (s:Section)<-[:IN_SECTION]-(t:TextChunk)
        WHERE t.group_id = $group_id
          AND s.group_id = $group_id
          AND s.id IN $section_ids
        OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
        WHERE d IS NULL OR (d.group_id = $group_id AND ($folder_id IS NULL OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id})))
        RETURN
            t.id AS chunk_id,
            t.text AS text,
            t.metadata AS metadata,
            t.chunk_index AS chunk_index,
            s.id AS section_id,
            s.path_key AS section_path_key,
            d.id AS doc_id,
            d.title AS doc_title,
            d.source AS doc_source
        ORDER BY chunk_index ASC
        LIMIT $candidate_limit
        """

        try:
            loop = asyncio.get_event_loop()

            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        group_id=self.group_id,
                        section_ids=normalized,
                        candidate_limit=candidate_limit,
                        folder_id=self.folder_id,
                    )
                    return list(result)

            records = await loop.run_in_executor(None, _run_query)

            candidates: List[SourceChunk] = []
            for record in records:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}

                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key:
                    section_path = section_path_key.split(" > ")

                candidates.append(
                    SourceChunk(
                        chunk_id=record["chunk_id"],
                        text=record.get("text") or "",
                        entity_name="section_boost",
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=record.get("doc_id") or metadata.get("document_id", "") or "",
                        document_title=record.get("doc_title") or metadata.get("document_title", "") or "",
                        document_source=record.get("doc_source") or metadata.get("url", "") or "",
                        relevance_score=1.0,
                    )
                )

            # Diversify across sections + documents.
            #
            # Default behavior historically preserved: take earliest chunks (chunk_index ASC)
            # per section/doc. For long agreements, key clauses (e.g., "monthly statement of
            # income and expenses") may appear later; `spread_within_section=True` samples
            # across each section (head+tail) to improve clause recall.

            per_section_counts: Dict[str, int] = {}
            per_doc_counts: Dict[str, int] = {}
            diversified: List[SourceChunk] = []
            seen_chunk_ids: set[str] = set()

            if not spread_within_section:
                for chunk in candidates:
                    section_key = chunk.section_id or (" > ".join(chunk.section_path) if chunk.section_path else "[unknown]")
                    doc_key = self._doc_key(chunk)

                    if per_section_counts.get(section_key, 0) >= max_per_section:
                        continue
                    if per_doc_counts.get(doc_key, 0) >= max_per_document:
                        continue

                    diversified.append(chunk)
                    seen_chunk_ids.add(chunk.chunk_id)
                    per_section_counts[section_key] = per_section_counts.get(section_key, 0) + 1
                    per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
                    if len(diversified) >= max_total:
                        break
            else:
                from collections import defaultdict, deque

                by_section: Dict[str, List[SourceChunk]] = defaultdict(list)
                for chunk in candidates:
                    section_key = chunk.section_id or (" > ".join(chunk.section_path) if chunk.section_path else "[unknown]")
                    by_section[section_key].append(chunk)

                def _spread_indices(n: int, first_pass: int) -> List[int]:
                    if n <= 0:
                        return []
                    if n == 1:
                        return [0]

                    m = max(1, min(n, first_pass))
                    if m == 1:
                        return [0]

                    out: List[int] = []
                    seen: set[int] = set()

                    # Evenly spaced coverage first (hits the middle for large sections).
                    for i in range(m):
                        pos = int(round(i * (n - 1) / (m - 1)))
                        if pos not in seen:
                            out.append(pos)
                            seen.add(pos)

                    # Fill remaining indices with a head/tail zigzag.
                    left, right = 0, n - 1
                    while left <= right:
                        if left not in seen:
                            out.append(left)
                            seen.add(left)
                        if right != left and right not in seen:
                            out.append(right)
                            seen.add(right)
                        left += 1
                        right -= 1

                    return out

                section_iters: Dict[str, deque[int]] = {
                    sk: deque(_spread_indices(len(lst), max_per_section * 4))
                    for sk, lst in by_section.items()
                    if lst
                }
                section_keys = list(section_iters.keys())

                made_progress = True
                while made_progress and len(diversified) < max_total and section_keys:
                    made_progress = False
                    for section_key in section_keys:
                        if len(diversified) >= max_total:
                            break
                        if per_section_counts.get(section_key, 0) >= max_per_section:
                            continue

                        idxs = section_iters.get(section_key)
                        if not idxs:
                            continue

                        # Advance until we either add something or run out.
                        while idxs and per_section_counts.get(section_key, 0) < max_per_section and len(diversified) < max_total:
                            idx = idxs.popleft()
                            lst = by_section.get(section_key) or []
                            if idx < 0 or idx >= len(lst):
                                continue
                            chunk = lst[idx]
                            if chunk.chunk_id in seen_chunk_ids:
                                continue
                            doc_key = self._doc_key(chunk)
                            if per_doc_counts.get(doc_key, 0) >= max_per_document:
                                continue

                            diversified.append(chunk)
                            seen_chunk_ids.add(chunk.chunk_id)
                            per_section_counts[section_key] = per_section_counts.get(section_key, 0) + 1
                            per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
                            made_progress = True
                            break

            logger.info(
                "section_id_boost_chunks_complete",
                num_sections=len(normalized),
                num_candidates=len(candidates),
                num_chunks=len(diversified),
                max_per_section=max_per_section,
                max_per_document=max_per_document,
                max_total=max_total,
                spread_within_section=spread_within_section,
            )

            return diversified

        except Exception as e:
            logger.error("section_id_boost_chunks_failed", error=str(e))
            return []
    
    async def _get_relationships(
        self,
        entity_names: List[str],
        max_relationships: int = 30,
    ) -> List[EntityRelationship]:
        """Get co-mentioned entity relationships via shared TextChunks.

        Finds entities that appear together in the same chunks (via MENTIONS edges).
        """
        if not entity_names or not self.driver:
            return []

        # Support both Entity and __Entity__ labels for compatibility
        query = """
        UNWIND $entity_inputs AS seed
        MATCH (e1)
        WHERE (e1:Entity OR e1:`__Entity__`)
          AND e1.group_id = $group_id
            AND (toLower(e1.name) = toLower(seed) OR coalesce(e1.id, '') = seed OR elementId(e1) = seed
                 OR ANY(alias IN coalesce(e1.aliases, []) WHERE toLower(alias) = toLower(seed)))
        
        MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e1)
        MATCH (c)-[:MENTIONS]->(e2)
        WHERE (e2:Entity OR e2:`__Entity__`)
          AND e2.group_id = $group_id AND e2 <> e1
        
        WITH e1, e2, count(DISTINCT c) AS shared_chunks, collect(DISTINCT c.id)[0..2] AS chunk_ids
        WHERE shared_chunks > 0
        WITH e1, e2, shared_chunks, chunk_ids
        WHERE elementId(e1) < elementId(e2)
        RETURN
            e1.name AS source,
            e2.name AS target,
            'Co-occur in ' + toString(shared_chunks) + ' chunk(s)' AS description,
            'CO_MENTIONED' AS rel_type
        ORDER BY shared_chunks DESC
        LIMIT $max_rels
        """

        # Support both Entity and __Entity__ labels for compatibility
        fallback_query = """
        UNWIND $entity_inputs AS seed
        MATCH (e1)
        WHERE (e1:Entity OR e1:`__Entity__`)
          AND e1.group_id = $group_id
          AND (toLower(e1.name) = toLower(seed) OR coalesce(e1.id, '') = seed OR elementId(e1) = seed
               OR ANY(alias IN coalesce(e1.aliases, []) WHERE toLower(alias) = toLower(seed)))
        MATCH (e1)-[r:RELATED_TO]-(e2)
        WHERE (e2:Entity OR e2:`__Entity__`)
          AND e2.group_id = $group_id AND e2 <> e1
        WITH e1, e2, r
        WHERE elementId(e1) < elementId(e2)
        RETURN
            e1.name AS source,
            e2.name AS target,
            coalesce(r.description, 'RELATED_TO') AS description,
            'RELATED_TO' AS rel_type
                LIMIT $max_rels
                """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        entity_inputs=entity_names,
                        group_id=self.group_id,
                        max_rels=max_relationships,
                    )
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)

            if not records:
                def _run_fallback():
                    with self.driver.session() as session:
                        result = session.run(
                            fallback_query,
                            entity_inputs=entity_names,
                            group_id=self.group_id,
                            max_rels=max_relationships,
                        )
                        return list(result)

                records = await loop.run_in_executor(None, _run_fallback)
            
            relationships = []
            for record in records:
                relationships.append(EntityRelationship(
                    source_entity=record["source"],
                    target_entity=record["target"],
                    relationship_type=record["rel_type"],
                    description=record["description"] or "",
                ))
            
            logger.info("relationship_retrieval_complete",
                       num_entities=len(entity_names),
                       num_relationships=len(relationships))
            return relationships
            
        except Exception as e:
            logger.error("relationship_retrieval_failed", error=str(e), num_entities=len(entity_names))
            return []
    
    async def _get_entity_descriptions(
        self,
        entity_names: List[str],
    ) -> Dict[str, str]:
        """Get entity descriptions from Neo4j."""
        if not entity_names or not self.driver:
            return {}
        
        query = """
        UNWIND $entity_names AS name
        MATCH (e)
        WHERE (e:Entity OR e:`__Entity__`)
          AND e.group_id = $group_id
                    AND (toLower(e.name) = toLower(name) OR e.id = name OR elementId(e) = name)
        RETURN e.name as name, e.description as description
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, entity_names=entity_names, group_id=self.group_id)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            return {r["name"]: r["description"] or "" for r in records}
            
        except Exception as e:
            logger.error("entity_description_retrieval_failed", error=str(e))
            return {}
    
    async def get_top_entities_by_degree(
        self,
        top_k: int = 10,
    ) -> List[Tuple[str, int]]:
        """
        Get the most connected entities in the graph.
        
        Useful as a fallback when keyword matching fails.
        """
        if not self.driver:
            return []
        
        query = """
        MATCH (e:Entity)-[r]-()
        WHERE e.group_id = $group_id
        WITH e, count(r) as degree
        ORDER BY degree DESC
        LIMIT $top_k
        RETURN e.name as name, degree
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, group_id=self.group_id, top_k=top_k)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            return [(r["name"], r["degree"]) for r in records]
            
        except Exception as e:
            logger.error("degree_query_failed", error=str(e))
            return []
    
    async def search_entities_by_embedding(
        self,
        query_embedding: List[float],
        top_k: int = 10,
    ) -> List[Tuple[str, float]]:
        """
        Find entities semantically similar to the query.
        
        Uses entity embeddings for semantic search.
        """
        if not self.driver or not query_embedding:
            return []
        
        query = """
        MATCH (e:Entity)
        WHERE e.group_id = $group_id
          AND e.embedding IS NOT NULL
                WITH e, vector.similarity.cosine(e.embedding, $query_embedding) as score
        ORDER BY score DESC
        LIMIT $top_k
        RETURN e.name as name, score
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        group_id=self.group_id,
                        query_embedding=query_embedding,
                        top_k=top_k,
                    )
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            return [(r["name"], r["score"]) for r in records]
            
        except Exception as e:
            logger.error("embedding_search_failed", error=str(e))
            return []
    
    async def get_all_documents(
        self,
        max_docs: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get all documents in the group.
        
        Used for coverage-guaranteed queries that need to touch every document.
        
        Returns:
            List of document metadata dicts with id, title, source.
        """
        if not self.driver:
            return []
        
        folder_filter = self._get_folder_filter_clause("d")
        
        query = f"""
        MATCH (d:Document)
        WHERE d.group_id = $group_id
        {folder_filter}
        RETURN 
            d.id AS doc_id,
            d.title AS doc_title,
            d.source AS doc_source
        ORDER BY d.title ASC
        LIMIT $max_docs
        """
        
        try:
            loop = asyncio.get_event_loop()
            params = {"group_id": self.group_id, "max_docs": max_docs}
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            docs = [
                {
                    "doc_id": r["doc_id"] or "",
                    "doc_title": r["doc_title"] or "",
                    "doc_source": r["doc_source"] or "",
                }
                for r in records
            ]
            
            logger.info(
                "all_documents_retrieved",
                num_docs=len(docs),
                group_id=self.group_id,
            )
            return docs
            
        except Exception as e:
            logger.error("all_documents_retrieval_failed", error=str(e))
            return []
    
    async def get_documents_by_date(
        self,
        order: str = "desc",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get documents ordered by their date property.
        
        This provides deterministic answers for date-related metadata queries
        like "Which document has the latest date?" without relying on LLM
        date parsing from chunk text.
        
        Args:
            order: "desc" for latest first, "asc" for oldest first
            limit: Maximum documents to return
            
        Returns:
            List of document dicts with id, title, source, date
        """
        if not self.driver:
            return []
        
        order_clause = "DESC" if order.lower() == "desc" else "ASC"
        folder_filter = self._get_folder_filter_clause("d")
        
        query = f"""
        MATCH (d:Document)
        WHERE d.group_id = $group_id AND d.date IS NOT NULL
        {folder_filter}
        RETURN 
            d.id AS doc_id,
            d.title AS doc_title,
            d.source AS doc_source,
            d.date AS doc_date
        ORDER BY d.date {order_clause}
        LIMIT $limit
        """
        
        try:
            loop = asyncio.get_event_loop()
            params = {"group_id": self.group_id, "limit": limit}
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            docs = [
                {
                    "doc_id": r["doc_id"] or "",
                    "doc_title": r["doc_title"] or "Untitled",
                    "doc_source": r["doc_source"] or "",
                    "doc_date": r["doc_date"] or "",
                }
                for r in records
            ]
            
            logger.info(
                "documents_by_date_retrieved",
                num_docs=len(docs),
                order=order,
                group_id=self.group_id,
            )
            return docs
            
        except Exception as e:
            logger.error("documents_by_date_retrieval_failed", error=str(e))
            return []
    
    async def get_coverage_chunks(
        self,
        max_per_document: int = 2,
        max_total: int = 20,
        prefer_early_chunks: bool = True,
    ) -> List[SourceChunk]:
        """Get representative chunks from (ideally) every document for coverage-style queries.
        
        This is the key method for solving the "summarize each document" problem.
        Instead of relying on BM25/vector relevance (which biases toward some docs),
        this explicitly enumerates all documents and gets chunks from each.
        
        Strategy:
        1. Get all Document nodes in the group
        2. For each document, get 1-2 representative chunks (preferring early chunks)
        3. Return a diversified set intended to cover every document.

        Note: if `max_total` is smaller than the number of documents in the group,
        full coverage is impossible; in that case this method returns a best-effort
        subset that maximizes unique-document coverage.
        
        Args:
            max_per_document: Max chunks to take per document (default: 2)
            max_total: Total cap on returned chunks (default: 20)
            prefer_early_chunks: If True, prefer chunks with low chunk_index (introductions)
            
        Returns:
            List of SourceChunks with guaranteed document coverage
        """
        if not self.driver:
            return []
        
                # Query gets the first N chunks per document (ordered by chunk_index).
                # IMPORTANT: Do not apply a global LIMIT here; it can truncate later
                # documents and break the intended “every document” coverage behavior.
        query = """
        MATCH (d:Document)<-[:IN_DOCUMENT]-(t:TextChunk)
        WHERE d.group_id = $group_id
          AND t.group_id = $group_id
        OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
        WITH d, t, s
                ORDER BY d.id,
                                 CASE
                                     WHEN $prefer_early_chunks THEN t.chunk_index
                                     ELSE -t.chunk_index
                                 END ASC
        WITH d, collect({
            chunk_id: t.id,
            text: t.text,
            metadata: t.metadata,
            chunk_index: t.chunk_index,
            section_id: s.id,
            section_path_key: s.path_key,
            doc_id: d.id,
            doc_title: d.title,
            doc_source: d.source
        })[0..$max_per_document] AS chunks
        UNWIND chunks AS chunk
        RETURN
            chunk.chunk_id AS chunk_id,
            chunk.text AS text,
            chunk.metadata AS metadata,
            chunk.chunk_index AS chunk_index,
            chunk.section_id AS section_id,
            chunk.section_path_key AS section_path_key,
            chunk.doc_id AS doc_id,
            chunk.doc_title AS doc_title,
            chunk.doc_source AS doc_source
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            params = {
                "group_id": self.group_id,
                "max_per_document": max_per_document,
                "prefer_early_chunks": prefer_early_chunks,
            }
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            per_doc: Dict[str, List[SourceChunk]] = {}
            
            for record in records:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}
                
                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key:
                    section_path = section_path_key.split(" > ")
                
                doc_id = (record.get("doc_id") or "").strip()

                doc_key = (doc_id or record.get("doc_source") or record.get("doc_title") or "").strip()
                if not doc_key:
                    continue
                doc_key_norm = doc_key.lower()

                per_doc.setdefault(doc_key_norm, []).append(
                    SourceChunk(
                        chunk_id=record.get("chunk_id") or "",
                        text=record.get("text") or "",
                        entity_name="coverage_retrieval",  # Mark source for traceability
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=doc_id,
                        document_title=record.get("doc_title") or metadata.get("document_title", "") or "",
                        document_source=record.get("doc_source") or metadata.get("url", "") or "",
                        relevance_score=1.0,  # All coverage chunks are equally "relevant"
                    )
                )

            # Deterministic selection: sort docs, then add chunks in a round-robin
            # across documents to maximize unique-document coverage under `max_total`.
            doc_keys_sorted = sorted(per_doc.keys())
            chunks: List[SourceChunk] = []
            max_per_document = max(0, max_per_document)

            for i in range(max_per_document):
                for k in doc_keys_sorted:
                    doc_chunks = per_doc.get(k) or []
                    if i < len(doc_chunks):
                        chunks.append(doc_chunks[i])
                        if max_total > 0 and len(chunks) >= max_total:
                            break
                if max_total > 0 and len(chunks) >= max_total:
                    break

            truncated = max_total > 0 and len(chunks) >= max_total and sum(
                min(len(per_doc.get(k) or []), max_per_document) for k in doc_keys_sorted
            ) > max_total
            
            logger.info(
                "coverage_chunks_retrieved",
                num_chunks=len(chunks),
                num_unique_docs=len(doc_keys_sorted),
                max_per_document=max_per_document,
                max_total=max_total,
                prefer_early_chunks=prefer_early_chunks,
                group_id=self.group_id,
                truncated=truncated,
            )
            
            return chunks
            
        except Exception as e:
            logger.error("coverage_chunks_retrieval_failed", error=str(e))
            return []

    async def get_coverage_chunks_semantic(
        self,
        query_embedding: List[float],
        max_per_document: int = 1,
        max_total: int = 20,
    ) -> List[SourceChunk]:
        """Get the most query-relevant chunk from each document for coverage-style queries.
        
        Unlike get_coverage_chunks() which prefers early chunks (chunk_index=0),
        this method uses vector similarity to find the chunk within each document
        that is most relevant to the query. This solves the problem where important
        information (like insurance clauses or dates) appears later in documents.
        
        Strategy:
        1. For each document, find all chunks with embeddings
        2. Compute vector similarity between query and each chunk
        3. Return the top-scoring chunk per document
        
        Args:
            query_embedding: The query embedding vector
            max_per_document: Max chunks per document (default: 1)
            max_total: Total cap on returned chunks (default: 20)
            
        Returns:
            List of SourceChunks - one (most relevant) per document
        """
        if not self.driver or not query_embedding:
            return []
        
        folder_filter = self._get_folder_filter_clause("d")
        
        # Use native vector similarity to find the best chunk per document
        query = f"""
        MATCH (d:Document)<-[:IN_DOCUMENT]-(t:TextChunk)
        WHERE d.group_id = $group_id
          AND t.group_id = $group_id
          AND t.embedding IS NOT NULL
        {folder_filter}
        OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
        WITH d, t, s, vector.similarity.cosine(t.embedding, $query_embedding) AS score
        ORDER BY d.id, score DESC
        WITH d, collect({{
            chunk_id: t.id,
            text: t.text,
            metadata: t.metadata,
            chunk_index: t.chunk_index,
            section_id: s.id,
            section_path_key: s.path_key,
            doc_id: d.id,
            doc_title: d.title,
            doc_source: d.source,
            similarity_score: score
        }})[0..$max_per_document] AS chunks
        UNWIND chunks AS chunk
        RETURN
            chunk.chunk_id AS chunk_id,
            chunk.text AS text,
            chunk.metadata AS metadata,
            chunk.chunk_index AS chunk_index,
            chunk.section_id AS section_id,
            chunk.section_path_key AS section_path_key,
            chunk.doc_id AS doc_id,
            chunk.doc_title AS doc_title,
            chunk.doc_source AS doc_source,
            chunk.similarity_score AS similarity_score
        """
        
        try:
            loop = asyncio.get_event_loop()
            params = {
                "group_id": self.group_id,
                "query_embedding": query_embedding,
                "max_per_document": max_per_document,
            }
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            per_doc: Dict[str, List[SourceChunk]] = {}
            
            for record in records:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}
                
                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key:
                    section_path = section_path_key.split(" > ")
                
                doc_id = (record.get("doc_id") or "").strip()
                doc_key = (doc_id or record.get("doc_source") or record.get("doc_title") or "").strip()
                if not doc_key:
                    continue
                doc_key_norm = doc_key.lower()
                
                similarity_score = record.get("similarity_score") or 0.0

                per_doc.setdefault(doc_key_norm, []).append(
                    SourceChunk(
                        chunk_id=record.get("chunk_id") or "",
                        text=record.get("text") or "",
                        entity_name="semantic_coverage",  # Mark source for traceability
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=doc_id,
                        document_title=record.get("doc_title") or metadata.get("document_title", "") or "",
                        document_source=record.get("doc_source") or metadata.get("url", "") or "",
                        relevance_score=similarity_score,  # Use actual similarity score
                    )
                )

            # Build final list: round-robin across documents for fairness
            doc_keys_sorted = sorted(per_doc.keys())
            chunks: List[SourceChunk] = []
            max_per_document = max(0, max_per_document)

            for i in range(max_per_document):
                for k in doc_keys_sorted:
                    doc_chunks = per_doc.get(k) or []
                    if i < len(doc_chunks):
                        chunks.append(doc_chunks[i])
                        if max_total > 0 and len(chunks) >= max_total:
                            break
                if max_total > 0 and len(chunks) >= max_total:
                    break
            
            logger.info(
                "semantic_coverage_chunks_retrieved",
                num_chunks=len(chunks),
                num_unique_docs=len(doc_keys_sorted),
                max_per_document=max_per_document,
                max_total=max_total,
                group_id=self.group_id,
            )
            
            return chunks
            
        except Exception as e:
            logger.error("semantic_coverage_chunks_retrieval_failed", error=str(e))
            return []

    async def get_all_sections_chunks(
        self,
        max_per_section: Optional[int] = None,
    ) -> List[SourceChunk]:
        """Get chunks from all sections across all documents.
        
        This is ideal for "list ALL X" queries where comprehensive section 
        coverage is needed. Unlike get_coverage_chunks_semantic which returns
        one chunk per document, this returns chunks from all sections.
        
        For a document with sections like:
        - "1. Introduction" 
        - "2. Warranty Terms"
        - "3. Right to Cancel"
        - "4. Payment Terms"
        
        With max_per_section=None: Returns ALL chunks from ALL sections (exhaustive)
        With max_per_section=1: Returns first chunk from each section (sampling)
        
        Args:
            max_per_section: Max chunks per unique section. 
                            None = ALL chunks per section (recommended for comprehensive queries)
                            1 = First chunk only (may miss content in later chunks)
            
        Returns:
            List of SourceChunks from all sections in corpus
        """
        if not self.driver:
            return []
        
        folder_filter = self._get_folder_filter_clause("d")
        
        # Different queries based on whether we want all chunks or sampling
        if max_per_section is None:
            # COMPREHENSIVE: Return ALL chunks from all sections
            # No slicing - just collect and unwind all chunks per section
            query = f"""
            MATCH (t:TextChunk)-[:IN_SECTION]->(s:Section)
            WHERE t.group_id = $group_id
              AND s.group_id = $group_id
            OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
            WHERE d IS NULL OR (d.group_id = $group_id {folder_filter.replace('AND ', 'AND ')})
            WITH s, t, d
            ORDER BY s.path_key, t.chunk_index ASC
            RETURN
                t.id AS chunk_id,
                t.text AS text,
                t.metadata AS metadata,
                t.chunk_index AS chunk_index,
                s.id AS section_id,
                s.path_key AS section_path_key,
                s.title AS section_title,
                coalesce(d.id, '') AS doc_id,
                coalesce(d.title, '') AS doc_title,
                coalesce(d.source, '') AS doc_source
            """
        else:
            # SAMPLING: Return max_per_section chunks from each section
            query = f"""
            MATCH (t:TextChunk)-[:IN_SECTION]->(s:Section)
            WHERE t.group_id = $group_id
              AND s.group_id = $group_id
            OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
            WHERE d IS NULL OR (d.group_id = $group_id {folder_filter.replace('AND ', 'AND ')})
            WITH s, t, d
            ORDER BY s.path_key, t.chunk_index ASC
            WITH s, collect({{
                chunk_id: t.id,
                text: t.text,
                metadata: t.metadata,
                chunk_index: t.chunk_index,
                section_id: s.id,
                section_path_key: s.path_key,
                section_title: s.title,
                doc_id: coalesce(d.id, ''),
                doc_title: coalesce(d.title, ''),
                doc_source: coalesce(d.source, '')
            }})[0..$max_per_section] AS section_chunks
            UNWIND section_chunks AS chunk
            RETURN
                chunk.chunk_id AS chunk_id,
                chunk.text AS text,
                chunk.metadata AS metadata,
                chunk.chunk_index AS chunk_index,
                chunk.section_id AS section_id,
                chunk.section_path_key AS section_path_key,
                chunk.section_title AS section_title,
                chunk.doc_id AS doc_id,
                chunk.doc_title AS doc_title,
                chunk.doc_source AS doc_source
            """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    # Only pass max_per_section when using sampling mode
                    params = {"group_id": self.group_id}
                    params.update(self._get_folder_params())
                    if max_per_section is not None:
                        params["max_per_section"] = max_per_section
                    
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            logger.info("section_chunks_query_executed",
                       group_id=self.group_id,
                       records_returned=len(records),
                       max_per_section=max_per_section)
            
            chunks = []
            for record in records:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}
                
                section_path_key = (record.get("section_path_key") or "").strip()
                section_path = section_path_key.split(" > ") if section_path_key else []
                
                chunks.append(SourceChunk(
                    chunk_id=record["chunk_id"],
                    text=record["text"] or "",
                    entity_name="",  # Section-based retrieval
                    section_path=section_path,
                    section_id=record.get("section_id") or "",
                    document_id=record.get("doc_id") or "",
                    document_title=record.get("doc_title") or "",
                    document_source=record.get("doc_source") or "",
                ))
            
            logger.info("all_sections_chunks_retrieved",
                       group_id=self.group_id,
                       num_sections=len(chunks))
            
            return chunks
            
        except Exception as e:
            logger.error("all_sections_chunks_retrieval_failed", 
                        error=str(e),
                        error_type=type(e).__name__,
                        group_id=self.group_id)
            return []

    async def search_sections_by_vector(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        score_threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Vector search against Section embeddings for direct section-level retrieval.
        
        This method searches the existing Section.embedding vectors (created during indexing)
        to find sections semantically related to the query. It returns section metadata
        without fetching chunks, allowing for hierarchical retrieval patterns:
        
        1. Find relevant sections via vector search
        2. Fetch chunks from those sections
        3. Optionally traverse SEMANTICALLY_SIMILAR edges for expansion
        
        Use cases:
        - Structural queries: "Show me all methodology sections"
        - Coarse-to-fine retrieval: Fast section filter → chunk refinement
        - Hierarchical navigation: Browse by section, drill into chunks
        
        Args:
            query_embedding: Query vector (3072-dim for text-embedding-3-large)
            top_k: Maximum number of sections to return
            score_threshold: Minimum cosine similarity (0-1). Default 0.7 for high precision.
            
        Returns:
            List of section dicts with:
                - section_id: Section node ID
                - title: Section title
                - path_key: Hierarchical path (e.g., "1. Introduction > 1.2 Scope")
                - document_id: Parent document ID
                - document_title: Parent document title
                - score: Cosine similarity score (0-1)
        """
        if not self.driver:
            logger.warning("search_sections_by_vector_no_driver")
            return []
        
        # Build folder filter for document join
        folder_filter_clause = ""
        if self.folder_id:
            folder_filter_clause = "AND (d IS NULL OR (d)-[:IN_FOLDER]->(:Folder {id: $folder_id}))"
        
        query = f"""
        MATCH (s:Section {{group_id: $group_id}})
        WHERE s.embedding IS NOT NULL
        OPTIONAL MATCH (s)<-[:IN_SECTION]-(t:TextChunk)-[:IN_DOCUMENT]->(d:Document)
        WITH s, d, vector.similarity.cosine(s.embedding, $query_embedding) AS score
        WHERE score >= $score_threshold {folder_filter_clause}
        WITH s, d, score
        ORDER BY score DESC
        LIMIT $top_k
        RETURN DISTINCT
            s.id AS section_id,
            s.title AS title,
            s.path_key AS path_key,
            s.depth AS depth,
            coalesce(d.id, '') AS document_id,
            coalesce(d.title, '') AS document_title,
            score
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            params = {
                "group_id": self.group_id,
                "query_embedding": query_embedding,
                "top_k": top_k,
                "score_threshold": score_threshold,
            }
            params.update(self._get_folder_params())
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            sections = []
            for record in records:
                sections.append({
                    "section_id": record["section_id"],
                    "title": record.get("title") or "",
                    "path_key": record.get("path_key") or "",
                    "depth": record.get("depth", 0),
                    "document_id": record.get("document_id") or "",
                    "document_title": record.get("document_title") or "",
                    "score": record["score"],
                })
            
            logger.info("section_vector_search_complete",
                       group_id=self.group_id,
                       top_k=top_k,
                       threshold=score_threshold,
                       sections_found=len(sections))
            
            return sections
            
        except Exception as e:
            logger.error("section_vector_search_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        group_id=self.group_id)
            return []

    async def get_summary_chunks_by_section(
        self,
        max_per_document: int = 1,
        max_total: int = 200,
    ) -> List[SourceChunk]:
        """Get one (or a few) summary-like chunks per document using section metadata.

        This is intended for coverage-style queries ("summarize each document").
        It prefers chunks marked as summary sections by the section-aware chunker,
        falling back to chunk_index=0 if summary markers are absent.

        Requires APOC (uses apoc.convert.fromJsonMap on TextChunk.metadata).
        """

        if not self.driver:
            return []

        max_per_document = max(0, max_per_document)
        folder_filter = self._get_folder_filter_clause("d")

        query = f"""
        MATCH (d:Document)<-[:IN_DOCUMENT]-(t:TextChunk)
        WHERE d.group_id = $group_id
          AND t.group_id = $group_id
          AND t.metadata IS NOT NULL
        {folder_filter}
        WITH d, t, apoc.convert.fromJsonMap(t.metadata) AS meta
        WHERE coalesce(meta.is_summary_section, false) = true OR t.chunk_index = 0
        OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
        WITH d, t, meta, s
        ORDER BY d.id,
                 CASE WHEN coalesce(meta.is_summary_section, false) = true THEN 0 ELSE 1 END ASC,
                 t.chunk_index ASC
        WITH d, collect({{
            chunk_id: t.id,
            text: t.text,
            metadata: t.metadata,
            chunk_index: t.chunk_index,
            section_id: s.id,
            section_path_key: s.path_key,
            doc_id: d.id,
            doc_title: d.title,
            doc_source: d.source
        }})[0..$max_per_document] AS chunks
        UNWIND chunks AS chunk
        RETURN
            chunk.chunk_id AS chunk_id,
            chunk.text AS text,
            chunk.metadata AS metadata,
            chunk.chunk_index AS chunk_index,
            chunk.section_id AS section_id,
            chunk.section_path_key AS section_path_key,
            chunk.doc_id AS doc_id,
            chunk.doc_title AS doc_title,
            chunk.doc_source AS doc_source
        """

        try:
            loop = asyncio.get_event_loop()
            params = {
                "group_id": self.group_id,
                "max_per_document": max_per_document,
            }
            params.update(self._get_folder_params())

            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, **params)
                    return list(result)

            records = await loop.run_in_executor(None, _run_query)

            per_doc: Dict[str, List[SourceChunk]] = {}
            for record in records:
                metadata: Dict[str, Any] = {}
                raw_meta = record.get("metadata")
                if raw_meta:
                    try:
                        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        metadata = {}

                section_path = metadata.get("section_path", []) or []
                section_path_key = (record.get("section_path_key") or "").strip()
                if section_path_key:
                    section_path = section_path_key.split(" > ")

                doc_id = (record.get("doc_id") or "").strip()
                doc_key = (doc_id or record.get("doc_source") or record.get("doc_title") or "").strip()
                if not doc_key:
                    continue
                doc_key_norm = doc_key.lower()

                per_doc.setdefault(doc_key_norm, []).append(
                    SourceChunk(
                        chunk_id=record.get("chunk_id") or "",
                        text=record.get("text") or "",
                        entity_name="summary_section_retrieval",
                        section_path=section_path,
                        section_id=record.get("section_id") or "",
                        document_id=doc_id,
                        document_title=record.get("doc_title") or metadata.get("document_title", "") or "",
                        document_source=record.get("doc_source") or metadata.get("url", "") or "",
                        relevance_score=1.0,
                    )
                )

            # Deterministic selection: round-robin across docs (same as coverage chunks).
            doc_keys_sorted = sorted(per_doc.keys())
            chunks: List[SourceChunk] = []
            for i in range(max_per_document):
                for k in doc_keys_sorted:
                    doc_chunks = per_doc.get(k) or []
                    if i < len(doc_chunks):
                        chunks.append(doc_chunks[i])
                        if max_total > 0 and len(chunks) >= max_total:
                            break
                if max_total > 0 and len(chunks) >= max_total:
                    break

            logger.info(
                "summary_section_chunks_retrieved",
                num_chunks=len(chunks),
                num_unique_docs=len(doc_keys_sorted),
                max_per_document=max_per_document,
                max_total=max_total,
                group_id=self.group_id,
            )
            return chunks

        except Exception as e:
            logger.warning("summary_section_retrieval_failed", error=str(e))
            return []

    async def get_chunks_by_section(
        self,
        section_keywords: List[str],
        top_k: int = 10,
    ) -> List[SourceChunk]:
        """
        Get TextChunks from sections matching keywords.
        
        Uses section_path metadata for structured retrieval.
        """
        if not self.driver or not section_keywords:
            return []
        
        # Build case-insensitive section matching
        conditions = " OR ".join([
            f"any(section IN sections WHERE toLower(section) CONTAINS toLower('{kw}'))"
            for kw in section_keywords[:5]
        ])
        
        query = f"""
        MATCH (t:TextChunk)
        WHERE t.group_id = $group_id
          AND t.metadata IS NOT NULL
        WITH t, 
             apoc.convert.fromJsonMap(t.metadata).section_path as sections
        WHERE sections IS NOT NULL
          AND ({conditions})
        RETURN 
            t.id as chunk_id,
            t.text as text,
            t.metadata as metadata,
            sections as section_path
        LIMIT $top_k
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        group_id=self.group_id,
                        top_k=top_k,
                    )
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            chunks = []
            for record in records:
                chunks.append(SourceChunk(
                    chunk_id=record["chunk_id"],
                    text=record["text"] or "",
                    entity_name="",  # Retrieved by section, not entity
                    section_path=record["section_path"] or [],
                ))
            
            return chunks
            
        except Exception as e:
            logger.error("section_retrieval_failed", error=str(e))
            return []
