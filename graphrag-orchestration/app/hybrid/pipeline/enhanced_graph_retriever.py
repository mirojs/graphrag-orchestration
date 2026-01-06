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
        Get source TextChunks that MENTION these entities.
        
        Uses the MENTIONS edge: (TextChunk)-[:MENTIONS]->(Entity)
        Also fetches section_id via IN_SECTION edge for diversification.
        This provides the source text for citations.
        """
        if not entity_names or not self.driver:
            return []
        
        query = """
        UNWIND $entity_names AS entity_name
        MATCH (t:TextChunk)-[:MENTIONS]->(e:Entity)
        WHERE toLower(e.name) = toLower(entity_name)
          AND t.group_id = $group_id
        OPTIONAL MATCH (t)-[:IN_SECTION]->(s:Section)
        OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
        WITH entity_name, t, e, s, d
        ORDER BY t.chunk_index
        WITH entity_name, collect({
            chunk_id: t.id,
            text: t.text,
            metadata: t.metadata,
            chunk_index: t.chunk_index,
            section_id: s.id,
            section_path_key: s.path_key,
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
            doc_key = (chunk.document_title or chunk.document_source or "[unknown]").strip().lower()
            
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

        lowered_keywords = [k.lower().strip() for k in keywords if k and k.strip()]
        if not lowered_keywords:
            return []

        # Pull a moderate candidate set, then diversify by document in Python.
        candidate_limit = max(50, max_total * 10)

        query = """
        MATCH (t:TextChunk)
        WHERE t.group_id = $group_id
        WITH t,
             reduce(cnt = 0, k IN $keywords |
                cnt + CASE WHEN toLower(t.text) CONTAINS k THEN 1 ELSE 0 END
             ) AS match_count
        WHERE match_count >= $min_matches
        RETURN
            t.id AS chunk_id,
            t.text AS text,
            t.metadata AS metadata,
            t.chunk_index AS chunk_index,
            match_count AS match_count
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
                        keywords=lowered_keywords,
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

                candidates.append(
                    SourceChunk(
                        chunk_id=record["chunk_id"],
                        text=record.get("text") or "",
                        entity_name="keyword_boost",
                        section_path=metadata.get("section_path", []) or [],
                        document_title=metadata.get("document_title", "") or "",
                        document_source=metadata.get("url", "") or "",
                        relevance_score=float(record.get("match_count") or 0.0),
                    )
                )

            # Diversify while preserving relevance:
            # candidates are already sorted by match_count DESC, then chunk order.
            # Greedily take the best remaining chunk, respecting per-document caps.
            per_doc_counts: Dict[str, int] = {}
            diversified: List[SourceChunk] = []
            for chunk in candidates:
                doc_key = (chunk.document_title or chunk.document_source or "unknown").strip().lower()
                if per_doc_counts.get(doc_key, 0) >= max_per_document:
                    continue
                diversified.append(chunk)
                per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
                if len(diversified) >= max_total:
                    break

            logger.info(
                "keyword_boost_chunks_complete",
                num_keywords=len(lowered_keywords),
                num_candidates=len(candidates),
                num_chunks=len(diversified),
                max_per_document=max_per_document,
                max_total=max_total,
            )

            return diversified

        except Exception as e:
            logger.error("keyword_boost_chunks_failed", error=str(e))
            return []
    
    async def _get_relationships(
        self,
        entity_names: List[str],
        max_relationships: int = 30,
    ) -> List[EntityRelationship]:
        """
        Get RELATED_TO relationships for the given entities.
        
        Expands entity context by traversing relationship edges.
        """
        if not entity_names or not self.driver:
            return []
        
        query = """
        MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
        WHERE toLower(e1.name) IN $entity_names_lower
           OR toLower(e2.name) IN $entity_names_lower
        RETURN 
            e1.name as source,
            e2.name as target,
            r.description as description,
            type(r) as rel_type
        ORDER BY size(r.description) DESC
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
            logger.error("relationship_retrieval_failed", error=str(e))
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
        WITH e, gds.similarity.cosine(e.embedding, $query_embedding) as score
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
