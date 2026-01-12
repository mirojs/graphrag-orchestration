"""Enhanced Neo4j Graph Retrieval for Route 3.

This module provides graph-aware retrieval that fully utilizes:
1. MENTIONS edges: Entity → Source TextChunks (for citations)
2. RELATED_TO edges: Entity → Entity relationships (for context)
3. Section metadata: Document structure (for organized citations)
4. Entity embeddings: Semantic entity discovery
5. Section graph: IN_SECTION edges for section-aware diversification
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
    
    def __init__(self, neo4j_driver, group_id: str):
        """
        Initialize the enhanced retriever.
        
        Args:
            neo4j_driver: Neo4j driver instance
            group_id: Document group ID for filtering
        """
        self.driver = neo4j_driver
        self.group_id = group_id

    @staticmethod
    def _doc_key(chunk: SourceChunk) -> str:
        """Stable key for per-document diversification.

        Prefer Document.id when available; fall back to source/title.
        """

        return (chunk.document_id or chunk.document_source or chunk.document_title or "unknown").strip().lower()

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
            
        Returns:
            EnhancedGraphContext with all retrieved information
        """
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
    
    async def _get_source_chunks_via_mentions(
        self,
        entity_names: List[str],
        max_per_entity: int = 3,
    ) -> List[SourceChunk]:
        """
        Get source chunks that MENTION these entities.

        Supports common schema variants:
        - Chunk labels: `TextChunk` and `Chunk`
        - Entity labels: `Entity` and `__Entity__`
        - Edge direction: (chunk)-[:MENTIONS]->(entity) and (entity)-[:MENTIONS]->(chunk)
        Also fetches section_id via IN_SECTION edge for diversification.
        This provides the source text for citations.
        """
        if not entity_names or not self.driver:
            return []
        query = """
        UNWIND $entity_names AS entity_name
        CALL {
            WITH entity_name
            MATCH (t:TextChunk)-[:MENTIONS]->(e:Entity)
            WHERE toLower(e.name) = toLower(entity_name)
              AND t.group_id = $group_id
            RETURN t
            UNION
                        WITH entity_name
                        MATCH (t:TextChunk)-[:MENTIONS]->(e:`__Entity__`)
                        WHERE toLower(e.name) = toLower(entity_name)
                            AND t.group_id = $group_id
                            AND e.group_id = $group_id
                        RETURN t
                        UNION
                        WITH entity_name
                        MATCH (e:Entity)-[:MENTIONS]->(t:TextChunk)
                        WHERE toLower(e.name) = toLower(entity_name)
                            AND t.group_id = $group_id
                        RETURN t
                        UNION
                        WITH entity_name
                        MATCH (e:`__Entity__`)-[:MENTIONS]->(t:TextChunk)
                        WHERE toLower(e.name) = toLower(entity_name)
                            AND t.group_id = $group_id
                            AND e.group_id = $group_id
                        RETURN t
                        UNION
                        WITH entity_name
                        MATCH (t:Chunk)-[:MENTIONS]->(e:Entity)
                        WHERE toLower(e.name) = toLower(entity_name)
                            AND t.group_id = $group_id
                        RETURN t
                        UNION
                        WITH entity_name
                        MATCH (t:Chunk)-[:MENTIONS]->(e:`__Entity__`)
                        WHERE toLower(e.name) = toLower(entity_name)
                            AND t.group_id = $group_id
                            AND e.group_id = $group_id
                        RETURN t
                        UNION
                        WITH entity_name
                        MATCH (e:Entity)-[:MENTIONS]->(t:Chunk)
                        WHERE toLower(e.name) = toLower(entity_name)
                            AND t.group_id = $group_id
                        RETURN t
                        UNION
                        WITH entity_name
                        MATCH (e:`__Entity__`)-[:MENTIONS]->(t:Chunk)
                        WHERE toLower(e.name) = toLower(entity_name)
                            AND t.group_id = $group_id
                            AND e.group_id = $group_id
                        RETURN t
                }
                OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
                OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
                WITH entity_name, t, s, d
                ORDER BY coalesce(t.chunk_index, 0)
                WITH entity_name, collect({
                        chunk_id: t.id,
                        text: t.text,
                        metadata: t.metadata,
                        chunk_index: coalesce(t.chunk_index, 0),
                        section_id: s.id,
                        section_path_key: s.path_key,
                        doc_id: d.id,
                        doc_title: d.title,
                        doc_source: d.source
                })[0..$max_per_entity] as chunks
                UNWIND chunks as chunk
                RETURN
                        entity_name,
                        chunk.chunk_id as chunk_id,
                        chunk.text as text,
                        chunk.metadata as metadata,
                        chunk.section_id as section_id,
                        chunk.section_path_key as section_path_key,
                        chunk.doc_id as doc_id,
                        chunk.doc_title as doc_title,
                        chunk.doc_source as doc_source
                """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        entity_names=entity_names,
                        group_id=self.group_id,
                        max_per_entity=max_per_entity,
                    )
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
            chunks = []
            for record in records:
                metadata = {}
                if record["metadata"]:
                    try:
                        metadata = json.loads(record["metadata"]) if isinstance(record["metadata"], str) else record["metadata"]
                    except:
                        pass
                
                # Use section_path from graph if available, else from metadata
                section_path = metadata.get("section_path", [])
                if record.get("section_path_key"):
                    section_path = record["section_path_key"].split(" > ")
                
                chunks.append(SourceChunk(
                    chunk_id=record["chunk_id"],
                    text=record["text"] or "",
                    entity_name=record["entity_name"],
                    section_path=section_path,
                    section_id=record.get("section_id") or "",
                    document_id=record.get("doc_id") or metadata.get("document_id", "") or "",
                    document_title=record.get("doc_title") or metadata.get("document_title", ""),
                    document_source=record.get("doc_source") or metadata.get("url", ""),
                ))
            
            logger.info("mentions_retrieval_complete",
                       num_entities=len(entity_names),
                       num_chunks=len(chunks))
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
        
        # Fetch chunks via MENTIONS edges
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
        OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
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
        from app.services.async_neo4j_service import cypher25_query
        query = cypher25_query(query)

        try:
            loop = asyncio.get_event_loop()

            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        group_id=self.group_id,
                        keyword_needles=keyword_needles,
                        min_matches=min_matches,
                        candidate_limit=candidate_limit,
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

        query = """
        MATCH (d:Document)<-[:PART_OF]-(t:TextChunk)
        WHERE d.group_id = $group_id
          AND t.group_id = $group_id
          AND t.chunk_index IN $chunk_indexes
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

            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        group_id=self.group_id,
                        chunk_indexes=candidate_chunk_indexes,
                    )
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
        OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
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
        OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
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

        # Co-mention relationships depend on chunks being linked to entities.
        # Support common schema variants:
        # - chunk labels: TextChunk/Chunk
        # - edge direction: chunk->entity or entity->chunk
        query = """
        UNWIND $entity_names_lower AS seed
                CALL {
                        WITH seed
                        MATCH (e1:Entity)
                        WHERE e1.group_id = $group_id
                            AND toLower(e1.name) = seed
                        RETURN e1
                        UNION
                        WITH seed
                        MATCH (e1:`__Entity__`)
                        WHERE e1.group_id = $group_id
                            AND toLower(e1.name) = seed
                        RETURN e1
                }

        CALL {
            WITH e1
            MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e1)
            RETURN c
            UNION
            WITH e1
            MATCH (e1)-[:MENTIONS]->(c:TextChunk {group_id: $group_id})
            RETURN c
            UNION
            WITH e1
            MATCH (c:Chunk {group_id: $group_id})-[:MENTIONS]->(e1)
            RETURN c
            UNION
            WITH e1
            MATCH (e1)-[:MENTIONS]->(c:Chunk {group_id: $group_id})
            RETURN c
        }

        CALL {
            WITH c
            MATCH (c)-[:MENTIONS]->(e2:Entity)
            WHERE e2.group_id = $group_id
            RETURN e2
            UNION
            WITH c
            MATCH (c)-[:MENTIONS]->(e2:`__Entity__`)
            WHERE e2.group_id = $group_id
            RETURN e2
            UNION
            WITH c
            MATCH (e2:Entity)-[:MENTIONS]->(c)
            WHERE e2.group_id = $group_id
            RETURN e2
            UNION
            WITH c
            MATCH (e2:`__Entity__`)-[:MENTIONS]->(c)
            WHERE e2.group_id = $group_id
            RETURN e2
        }

        WITH e1, e2, c
        WHERE e2 <> e1
        WITH e1, e2, count(DISTINCT c) AS shared_chunks, collect(DISTINCT c.id)[0..2] AS chunk_ids
        WHERE shared_chunks > 0
        WITH e1, e2, shared_chunks, chunk_ids
        WHERE id(e1) < id(e2)
        RETURN
            e1.name AS source,
            e2.name AS target,
            'Co-occur in ' + toString(shared_chunks) + ' chunk(s)' AS description,
            'CO_MENTIONED' AS rel_type
        ORDER BY shared_chunks DESC
        LIMIT $max_rels
        """
        
        try:
            loop = asyncio.get_event_loop()
            entity_names_lower = [n.lower() for n in entity_names]
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(
                        query,
                        entity_names_lower=entity_names_lower,
                        group_id=self.group_id,
                        max_rels=max_relationships,
                    )
                    return list(result)
            
            records = await loop.run_in_executor(None, _run_query)
            
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
        MATCH (e:Entity)
        WHERE toLower(e.name) = toLower(name)
        RETURN e.name as name, e.description as description
        """
        
        try:
            loop = asyncio.get_event_loop()
            
            def _run_query():
                with self.driver.session() as session:
                    result = session.run(query, entity_names=entity_names)
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
