from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class HippoRAGTextUnitStore:
    """Minimal text-unit store backed by the HippoRAG on-disk index.

    The hybrid synthesizer expects an async `get_chunks_for_entity(entity_name)` that returns
    a list of dicts containing at least: {id, source, text}.

    We source text from HippoRAG's `entity_texts.json` and metadata from `entity_index.json`.
    """

    def __init__(self, hipporag_service: Any):
        self._hipporag_service = hipporag_service

    async def get_chunks_for_entity(self, entity_name: str) -> List[Dict[str, Any]]:
        ctx = await self._hipporag_service.get_entity_context(entity_name)
        texts: List[str] = ctx.get("source_texts") or []
        metadata: Dict[str, Any] = ctx.get("metadata") or {}

        # Best-effort source label: prefer url/source fields if present.
        source = (
            metadata.get("source")
            or metadata.get("url")
            or metadata.get("document")
            or metadata.get("document_id")
            or "hipporag_index"
        )

        chunks: List[Dict[str, Any]] = []
        for idx, text in enumerate(texts):
            if not text:
                continue
            chunks.append(
                {
                    "id": f"{entity_name}:{idx}",
                    "source": str(source),
                    "text": str(text),
                    "entity": entity_name,
                }
            )

        if not chunks:
            logger.debug("hipporag_text_store_no_chunks", entity=entity_name)

        return chunks


class Neo4jTextUnitStore:
    """Text-unit store backed by Neo4j TextChunk nodes.

    This store preserves Document Intelligence metadata that is persisted on
    TextChunk.metadata (e.g., section_path, di_section_path, page_number).

    It is intentionally read-only and returns dicts shaped for `EvidenceSynthesizer`.
    """

    def __init__(self, neo4j_driver: Any, *, group_id: str, limit_per_entity: int = 12):
        self._driver = neo4j_driver
        self._group_id = group_id
        self._limit = int(limit_per_entity)

    async def get_chunks_for_entity(self, entity_name: str) -> List[Dict[str, Any]]:
        """Get chunks for a single entity (backward compatibility wrapper)."""
        results = await self.get_chunks_for_entities([entity_name])
        return results.get(entity_name, [])

    async def get_chunks_for_query(self, query: str, *, limit: int = 24) -> List[Dict[str, Any]]:
        """Fallback: retrieve chunks by keyword overlap with the user query.

        This is used when Route 4 produces evidence strings that don't resolve to
        real graph entities (e.g., generic terms), so entity-based chunk lookup yields 0.
        """
        q = (query or "").strip()
        if not q:
            return []

        # Lightweight keyword extraction (mirrors benchmark stopwording philosophy).
        import re

        stopwords = {
            "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "should", "could", "may", "might", "must",
            "can", "what", "which", "who", "when", "where", "why", "how", "this", "that", "these", "those", "all",
            "any", "our", "your", "their", "on", "for", "with", "by", "as", "at", "from",
        }

        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", q) if len(t) >= 3]
        keywords = [t for t in tokens if t not in stopwords]
        if not keywords:
            return []

        # Neo4j python driver is sync; run in a thread to avoid blocking the event loop.
        return await asyncio.to_thread(self._get_chunks_for_query_sync, keywords, int(limit))

    def _get_chunks_for_query_sync(self, keywords: List[str], limit: int) -> List[Dict[str, Any]]:
        # Enhanced query: also fetch document-level date for corpus-level reasoning
        query = """
        MATCH (c)
        WHERE c.group_id = $group_id AND (c:TextChunk OR c:Chunk OR c:`__Node__`)
        WITH c, [kw IN $keywords WHERE toLower(coalesce(c.text, '')) CONTAINS kw] AS matched
        WITH c, size(matched) AS score
        WHERE score > 0
        OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
        WITH c, d, score
        ORDER BY score DESC, coalesce(c.chunk_index, 0) ASC
        RETURN c AS chunk, d AS doc, score,
               coalesce(d.date, '') AS doc_date,
               coalesce(d.id, '') AS doc_id
        LIMIT $limit
        """

        rows: List[Dict[str, Any]] = []
        with self._driver.session() as session:
            result = session.run(
                query,
                group_id=self._group_id,
                keywords=keywords,
                limit=int(limit),
            )
            for record in result:
                c = record.get("chunk")
                d = record.get("doc")
                if not c:
                    continue

                raw_meta = c.get("metadata")
                meta: Dict[str, Any] = {}
                if raw_meta:
                    if isinstance(raw_meta, str):
                        try:
                            meta = json.loads(raw_meta)
                        except Exception:
                            meta = {}
                    elif isinstance(raw_meta, dict):
                        meta = dict(raw_meta)

                for prop_key in ("page_number", "section_path", "di_section_path", "document_id", "url"):
                    if prop_key not in meta:
                        try:
                            v = c.get(prop_key)
                        except Exception:
                            v = None
                        if v is not None and v != "":
                            meta[prop_key] = v

                doc_title = (d.get("title") if d else "") or meta.get("document_title") or ""
                doc_source = (d.get("source") if d else "") or meta.get("document_source") or ""
                url = meta.get("url") or doc_source or ""

                section_path = meta.get("section_path")
                section_label = ""
                if isinstance(section_path, list) and section_path:
                    section_label = " > ".join(str(x) for x in section_path if x)
                elif isinstance(section_path, str) and section_path:
                    section_label = section_path

                source_label = doc_title or doc_source or url or "neo4j"
                if section_label:
                    source_label = f"{source_label} — {section_label}"

                rows.append(
                    {
                        "id": str(c.get("id") or ""),
                        "source": str(source_label),
                        "text": str(c.get("text") or ""),
                        "entity": "__query__",
                        "metadata": {
                            **meta,
                            "document_title": str(doc_title),
                            "document_source": str(doc_source),
                            "document_id": str(record.get("doc_id") or ""),
                            "document_date": str(record.get("doc_date") or ""),
                            "keyword_score": int(record.get("score") or 0),
                        },
                    }
                )

        return rows
    
    async def get_entity_communities(self, entity_names: List[str]) -> Dict[str, Optional[int]]:
        """Batch-fetch Louvain community_id for a list of entity names.

        Returns a dict mapping entity_name → community_id (or None if missing).
        Used by community-aware filtering in synthesis to penalise off-topic entities.
        """
        if not entity_names:
            return {}

        query = """
            UNWIND $names AS ename
            MATCH (e)
            WHERE e.group_id = $group_id
              AND (e:Entity OR e:`__Entity__`)
              AND e.name = ename
            RETURN e.name AS name, e.community_id AS community_id
        """
        result: Dict[str, Optional[int]] = {}
        try:
            with self._driver.session() as session:
                records = session.run(
                    query,
                    names=entity_names,
                    group_id=self._group_id,
                ).data()
            for r in records:
                result[r["name"]] = r.get("community_id")
        except Exception as e:
            logger.warning("get_entity_communities_failed error=%s", str(e))
        return result

    async def get_chunks_for_entities(self, entity_names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Get chunks for multiple entities in a single batched query (performance optimization)."""
        if not entity_names:
            return {}
        
        def _clean_entity_name(name: str) -> str:
            cleaned = (name or "").strip()
            # Remove wrapping quotes/backticks (common when entities are serialized from logs/prompts)
            while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'", "`"):
                cleaned = cleaned[1:-1].strip()
            return cleaned

        # Filter out empty names and normalize
        names = [_clean_entity_name(n) for n in entity_names if (n or "").strip()]
        names = [n for n in names if n]
        if not names:
            return {}
        
        # Neo4j python driver is sync; run in a thread to avoid blocking the event loop.
        return await asyncio.to_thread(self._get_chunks_for_entities_batch_sync, names)

    def _get_chunks_for_entities_batch_sync(
        self,
        entity_names: List[str],
        max_per_section: int = 3,
        max_per_document: int = 6,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch query to fetch chunks for multiple entities in a single round-trip.
        
        Enhanced with section-aware diversification (Jan 2026):
        - Fetches section_id via IN_SECTION edge
        - Applies max_per_section and max_per_document caps for better coverage
        """
        import os
        
        # Check if section diversification is enabled
        section_graph_enabled = os.getenv("SECTION_GRAPH_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
        
        # Enhanced query: also fetch section info via IN_SECTION edge
        # FIX: Support both Entity and __Entity__ labels (different indexing pipelines use different labels)
        query = """
        UNWIND $entity_names AS entity_name
        MATCH (e {group_id: $group_id})
        WHERE (e:Entity OR e:`__Entity__`)
          AND (toLower(e.name) = toLower(entity_name)
               OR ANY(alias IN coalesce(e.aliases, []) WHERE toLower(alias) = toLower(entity_name)))
        MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
        OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
        OPTIONAL MATCH (c)-[:IN_SECTION]->(s:Section)
        WITH entity_name, c, d, s
        ORDER BY entity_name, coalesce(c.chunk_index, 0) ASC
        WITH entity_name, collect({chunk: c, doc: d, section: s})[0..$limit] AS items
        RETURN entity_name, items
        """
        
        results: Dict[str, List[Dict[str, Any]]] = {name: [] for name in entity_names}
        
        with self._driver.session() as session:
            result = session.run(
                query,
                group_id=self._group_id,
                entity_names=entity_names,
                limit=self._limit,
            )
            
            for record in result:
                entity_name = record.get("entity_name")
                items = record.get("items") or []
                
                if not entity_name:
                    continue
                
                # Track per-section and per-document counts for diversification
                per_section_counts: Dict[str, int] = {}
                per_doc_counts: Dict[str, int] = {}
                
                rows: List[Dict[str, Any]] = []
                seen_chunk_ids: set[str] = set()
                for item in items:
                    c = (item or {}).get("chunk")
                    d = (item or {}).get("doc")
                    s = (item or {}).get("section")
                    if not c:
                        continue

                    chunk_id = str(c.get("id") or "")
                    if chunk_id and chunk_id in seen_chunk_ids:
                        continue
                    if chunk_id:
                        seen_chunk_ids.add(chunk_id)
                    
                    raw_meta = c.get("metadata")
                    meta: Dict[str, Any] = {}
                    if raw_meta:
                        if isinstance(raw_meta, str):
                            try:
                                meta = json.loads(raw_meta)
                            except Exception:
                                meta = {}
                        elif isinstance(raw_meta, dict):
                            meta = dict(raw_meta)

                    # Some chunk types store common fields as top-level props.
                    for prop_key in ("page_number", "section_path", "di_section_path", "document_id", "url"):
                        if prop_key not in meta:
                            try:
                                v = c.get(prop_key)
                            except Exception:
                                v = None
                            if v is not None and v != "":
                                meta[prop_key] = v
                    
                    # Prefer Document attribution when available.
                    # document_id from the graph is the authoritative grouping key
                    doc_id = (d.get("id") if d else "") or meta.get("document_id") or ""
                    doc_title = (d.get("title") if d else "") or meta.get("document_title") or ""
                    doc_source = (d.get("source") if d else "") or meta.get("document_source") or ""
                    url = meta.get("url") or doc_source or ""
                    
                    # Extract section info from IN_SECTION edge (preferred) or metadata
                    section_id = (s.get("id") if s else "") or ""
                    section_path_key = (s.get("path_key") if s else "") or ""
                    
                    # Build a readable section label for citations.
                    section_path = meta.get("section_path")
                    section_label = ""
                    if section_path_key:
                        section_label = section_path_key
                    elif isinstance(section_path, list) and section_path:
                        section_label = " > ".join(str(x) for x in section_path if x)
                    elif isinstance(section_path, str) and section_path:
                        section_label = section_path
                    
                    # Apply section-aware diversification (if enabled)
                    if section_graph_enabled:
                        # Use section_id for diversification key (stable), fallback to path_key
                        section_key = section_id or section_label or "[unknown]"
                        doc_key = doc_id or doc_title or doc_source or "[unknown]"
                        
                        # Check section cap
                        if per_section_counts.get(section_key, 0) >= max_per_section:
                            logger.debug(
                                "route2_section_cap_reached",
                                entity=entity_name,
                                section=section_key,
                                count=per_section_counts.get(section_key, 0),
                            )
                            continue
                        
                        # Check document cap
                        if per_doc_counts.get(doc_key, 0) >= max_per_document:
                            logger.debug(
                                "route2_document_cap_reached",
                                entity=entity_name,
                                document=doc_key,
                                count=per_doc_counts.get(doc_key, 0),
                            )
                            continue
                        
                        # Update counts
                        per_section_counts[section_key] = per_section_counts.get(section_key, 0) + 1
                        per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
                    
                    source_label = doc_title or doc_source or url or "neo4j"
                    if section_label:
                        source_label = f"{source_label} — {section_label}"
                    
                    rows.append(
                        {
                            "id": chunk_id,
                            "source": str(source_label),
                            "text": str(c.get("text") or ""),
                            "entity": entity_name,
                            "metadata": {
                                **meta,
                                "document_id": str(doc_id),  # Graph node ID - authoritative grouping key
                                "document_title": str(doc_title),
                                "document_source": str(doc_source),
                                "section_id": str(section_id),  # Section node ID for diversification
                                "section_path_key": str(section_path_key),
                            },
                        }
                    )
                
                results[entity_name] = rows
                
                if not rows:
                    logger.debug("neo4j_text_store_no_chunks", entity=entity_name)
                elif section_graph_enabled:
                    logger.debug(
                        "route2_section_diversification_applied",
                        entity=entity_name,
                        chunks_returned=len(rows),
                        unique_sections=len(per_section_counts),
                        unique_docs=len(per_doc_counts),
                    )
        
        # Summary log for Route 2 chunk retrieval
        total_chunks = sum(len(v) for v in results.values())
        entities_with_chunks = sum(1 for v in results.values() if v)
        logger.info(
            "route2_chunks_retrieved",
            num_entities=len(entity_names),
            entities_with_chunks=entities_with_chunks,
            total_chunks=total_chunks,
            section_diversification=section_graph_enabled,
            max_per_section=max_per_section if section_graph_enabled else None,
            max_per_document=max_per_document if section_graph_enabled else None,
        )
        
        return results

    # ------------------------------------------------------------------
    # Improvement #5: Vector chunk safety net
    # ------------------------------------------------------------------

    async def search_chunks_by_vector(
        self,
        embedding: list,
        *,
        top_k: int = 3,
        index_name: str = "chunk_embeddings_v2",
    ) -> list:
        """Vector-search text chunks as a safety-net for NER/PPR misses.

        Uses the Neo4j vector index on TextChunk to find the top-k most
        similar chunks regardless of entity linkage.  Returns dicts in the
        same shape as ``get_chunks_for_entities`` so callers can merge them
        directly into the raw_chunks pool.

        Returns:
            List of (chunk_dict, similarity_score) tuples.
        """
        if not embedding:
            return []
        return await asyncio.to_thread(
            self._search_chunks_by_vector_sync, embedding, top_k, index_name,
        )

    def _search_chunks_by_vector_sync(
        self,
        embedding: list,
        top_k: int,
        index_name: str,
    ) -> list:
        # Over-fetch to compensate for the group_id filter (index has all groups).
        fetch_k = top_k * 5

        query = """
        CALL db.index.vector.queryNodes($index_name, $fetch_k, $embedding)
        YIELD node AS t, score
        WHERE t.group_id = $group_id
        WITH t, score
        ORDER BY score DESC
        LIMIT $top_k
        OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
        RETURN t, d, score
        """

        results: list = []
        try:
            with self._driver.session() as session:
                records = session.run(
                    query,
                    index_name=index_name,
                    fetch_k=int(fetch_k),
                    embedding=embedding,
                    group_id=self._group_id,
                    top_k=int(top_k),
                )
                for record in records:
                    t = record["t"]
                    d = record.get("d")
                    sim = float(record.get("score", 0.0))
                    if not t:
                        continue

                    raw_meta = t.get("metadata")
                    meta: dict = {}
                    if raw_meta:
                        if isinstance(raw_meta, str):
                            try:
                                meta = json.loads(raw_meta)
                            except Exception:
                                meta = {}
                        elif isinstance(raw_meta, dict):
                            meta = dict(raw_meta)

                    doc_title = (d.get("title") if d else "") or meta.get("document_title", "")
                    doc_source = (d.get("source") if d else "") or meta.get("document_source", "")
                    doc_id = (d.get("id") if d else "") or meta.get("document_id", "")

                    section_path = meta.get("section_path")
                    section_label = ""
                    if isinstance(section_path, list) and section_path:
                        section_label = " > ".join(str(x) for x in section_path if x)
                    elif isinstance(section_path, str) and section_path:
                        section_label = section_path

                    source_label = doc_title or doc_source or "neo4j"
                    if section_label:
                        source_label = f"{source_label} — {section_label}"

                    chunk_dict = {
                        "id": str(t.get("id") or ""),
                        "source": str(source_label),
                        "text": str(t.get("text") or ""),
                        "entity": "__vector_fallback__",
                        "metadata": {
                            **meta,
                            "document_id": str(doc_id),
                            "document_title": str(doc_title),
                            "document_source": str(doc_source),
                            "vector_similarity": sim,
                        },
                    }
                    results.append((chunk_dict, sim))

            logger.info(
                "vector_safety_net_search",
                group_id=self._group_id,
                index=index_name,
                top_k=top_k,
                results=len(results),
            )
        except Exception as exc:
            logger.warning("vector_safety_net_failed", error=str(exc))

        return results

    async def get_all_chunks_for_comprehensive(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve all text chunks for the group - used by comprehensive mode fallback.
        
        This provides a robust fallback when keyword-based query retrieval returns empty.
        Returns chunks grouped by document for comprehensive extraction.
        """
        return await asyncio.to_thread(self._get_all_chunks_sync, int(limit))

    def _get_all_chunks_sync(self, limit: int) -> List[Dict[str, Any]]:
        """Sync implementation: fetch all chunks for the group."""
        query = """
        MATCH (c)
        WHERE c.group_id = $group_id AND (c:TextChunk OR c:Chunk OR c:`__Node__`)
        OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
        WITH c, d
        ORDER BY coalesce(d.title, d.source, '') ASC, coalesce(c.chunk_index, 0) ASC
        RETURN c AS chunk, d AS doc
        LIMIT $limit
        """
        
        rows: List[Dict[str, Any]] = []
        try:
            with self._driver.session() as session:
                result = session.run(query, group_id=self._group_id, limit=limit)
                for record in result:
                    c = record.get("chunk")
                    d = record.get("doc")
                    if not c:
                        continue
                    
                    raw_meta = c.get("metadata")
                    meta: Dict[str, Any] = {}
                    if raw_meta:
                        if isinstance(raw_meta, str):
                            try:
                                meta = json.loads(raw_meta)
                            except Exception:
                                meta = {}
                        elif isinstance(raw_meta, dict):
                            meta = dict(raw_meta)
                    
                    doc_title = (d.get("title") if d else "") or meta.get("document_title") or ""
                    doc_source = (d.get("source") if d else "") or meta.get("document_source") or ""
                    doc_id = (d.get("id") if d else "") or meta.get("document_id") or ""
                    
                    rows.append({
                        "id": str(c.get("id") or ""),
                        "source": doc_title or doc_source or "unknown",
                        "text": str(c.get("text") or ""),
                        "entity": "__comprehensive__",
                        "metadata": {
                            **meta,
                            "document_id": str(doc_id),
                            "document_title": str(doc_title),
                            "document_source": str(doc_source),
                        }
                    })
            
            logger.info("get_all_chunks_comprehensive", num_chunks=len(rows), group_id=self._group_id)
        except Exception as e:
            logger.error("get_all_chunks_comprehensive_failed", error=str(e), group_id=self._group_id)
        
        return rows

    async def get_workspace_document_overviews(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve high-level overview of all documents in the workspace.
        
        This addresses corpus-level questions (e.g., 'latest date', 'compare documents')
        where entity-based PPR traversal fails because the query is too abstract.
        
        Returns:
            List of dicts with document metadata: id, title, date, summary, source.
        """
        return await asyncio.to_thread(self._get_workspace_document_overviews_sync, int(limit))

    async def get_chunks_with_graph_structure(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve chunks WITH related graph structure (KVPs, Tables, Entities).
        
        This is the KEY method for graph-aware comprehensive mode. Instead of just
        returning flat text, we traverse edges to get:
        - KVPs in the same section
        - Tables in the same section  
        - Entities mentioned in the chunk
        
        This gives the LLM STRUCTURED context for comparison instead of re-extracting.
        """
        return await asyncio.to_thread(self._get_chunks_with_graph_structure_sync, int(limit))

    def _get_chunks_with_graph_structure_sync(self, limit: int) -> List[Dict[str, Any]]:
        """Sync implementation: fetch chunks with graph context."""
        
        # Query 1: Get all chunks with document info
        chunks_query = """
        MATCH (c:TextChunk {group_id: $group_id})
        OPTIONAL MATCH (c)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
        OPTIONAL MATCH (c)-[:IN_SECTION]->(s:Section {group_id: $group_id})
        WITH c, d, s
        ORDER BY coalesce(d.title, d.source, '') ASC, coalesce(c.chunk_index, 0) ASC
        RETURN 
            c.id AS chunk_id,
            c.text AS text,
            coalesce(d.title, d.source, 'Unknown') AS doc_title,
            d.id AS doc_id,
            s.id AS section_id,
            s.title AS section_title,
            s.path AS section_path
        LIMIT $limit
        """
        
        # Query 2: Get all KVPs - join to Document via section_path[0] fuzzy match
        # Note: KVPs don't have document_id populated, but section_path[0] contains
        # the document title (e.g. "BUILDERS LIMITED WARRANTY WITH ARBITRATION")
        # which we fuzzy-match to Document.title (URL-decoded, e.g. "BUILDERS LIMITED WARRANTY")
        # Use bidirectional CONTAINS: either doc.title contains section start OR section contains doc.title
        kvps_query = """
        MATCH (kvp:KeyValuePair {group_id: $group_id})
        WHERE kvp.section_path IS NOT NULL AND size(kvp.section_path) > 0
        WITH kvp, toUpper(kvp.section_path[0]) AS doc_section_upper
        OPTIONAL MATCH (d:Document {group_id: $group_id})
        WITH kvp, doc_section_upper, d, toUpper(d.title) AS doc_title_upper
        WHERE doc_title_upper CONTAINS substring(doc_section_upper, 0, 20)
           OR doc_section_upper CONTAINS doc_title_upper
        RETURN 
            kvp.key AS key,
            kvp.value AS value,
            kvp.confidence AS confidence,
            kvp.section_path AS section_path,
            kvp.page_number AS page_number,
            coalesce(d.title, kvp.section_path[0], 'Unknown') AS doc_title,
            d.id AS doc_id
        """
        
        # Query 3: Get Tables WITH document association via IN_DOCUMENT edge
        # Tables have structured data (headers + JSON rows) linked to documents
        tables_query = """
        MATCH (t:Table {group_id: $group_id})-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
        RETURN 
            t.id AS table_id,
            t.headers AS headers,
            t.rows AS rows,
            t.row_count AS row_count,
            t.column_count AS column_count,
            coalesce(d.title, d.source, 'Unknown') AS doc_title,
            d.id AS doc_id
        """
        
        # Query 4: Get Entities linked to documents
        # Entities use APPEARS_IN_DOCUMENT relationship (direct) or MENTIONS->TextChunk->IN_DOCUMENT (indirect)
        entities_query = """
        MATCH (e:Entity {group_id: $group_id})-[:APPEARS_IN_DOCUMENT]->(d:Document {group_id: $group_id})
        RETURN 
            e.id AS entity_id,
            e.name AS name,
            e.type AS type,
            e.description AS description,
            coalesce(d.title, d.source, 'Unknown') AS doc_title,
            d.id AS doc_id
        """
        
        chunks_by_doc: Dict[str, Dict[str, Any]] = {}
        
        try:
            with self._driver.session() as session:
                # Fetch chunks
                result = session.run(chunks_query, group_id=self._group_id, limit=limit)
                for record in result:
                    doc_title = record.get("doc_title") or "Unknown"
                    doc_id = record.get("doc_id") or ""
                    
                    if doc_title not in chunks_by_doc:
                        chunks_by_doc[doc_title] = {
                            "document_title": doc_title,
                            "document_id": doc_id,
                            "chunks": [],
                            "kvps": [],
                            "tables": [],
                            "entities": [],
                            "combined_text": ""
                        }
                    
                    chunks_by_doc[doc_title]["chunks"].append({
                        "chunk_id": record.get("chunk_id"),
                        "text": record.get("text") or "",
                        "section_id": record.get("section_id"),
                        "section_title": record.get("section_title"),
                        "section_path": record.get("section_path"),
                    })
                
                # Fetch KVPs - using fuzzy-matched doc_title from section_path
                result = session.run(kvps_query, group_id=self._group_id)
                for record in result:
                    doc_title = record.get("doc_title") or "Unknown"
                    if doc_title in chunks_by_doc:
                        chunks_by_doc[doc_title]["kvps"].append({
                            "key": record.get("key") or "",
                            "value": record.get("value") or "",
                            "confidence": record.get("confidence") or 0.0,
                            "section_path": record.get("section_path"),
                            "page_number": record.get("page_number"),
                        })
                
                # Fetch Tables WITH document association via IN_DOCUMENT edge
                result = session.run(tables_query, group_id=self._group_id)
                for record in result:
                    doc_title = record.get("doc_title") or "Unknown"
                    rows_raw = record.get("rows") or "[]"
                    
                    # Parse rows - stored as JSON string
                    import json
                    try:
                        rows = json.loads(rows_raw) if isinstance(rows_raw, str) else rows_raw
                    except (json.JSONDecodeError, TypeError):
                        rows = []
                    
                    table_data = {
                        "table_id": record.get("table_id"),
                        "headers": record.get("headers") or [],
                        "rows": rows,
                        "row_count": record.get("row_count") or 0,
                    }
                    
                    # Associate table with its document
                    if doc_title in chunks_by_doc:
                        chunks_by_doc[doc_title]["tables"].append(table_data)
                    else:
                        # Create doc entry if not exists (table-only doc)
                        chunks_by_doc[doc_title] = {
                            "document_title": doc_title,
                            "document_id": record.get("doc_id") or "",
                            "chunks": [],
                            "kvps": [],
                            "tables": [table_data],
                            "entities": [],
                            "combined_text": ""
                        }
                
                # Fetch Entities - linked via TextChunk -> Document
                result = session.run(entities_query, group_id=self._group_id)
                for record in result:
                    doc_title = record.get("doc_title") or "Unknown"
                    if doc_title in chunks_by_doc:
                        chunks_by_doc[doc_title]["entities"].append({
                            "entity_id": record.get("entity_id"),
                            "name": record.get("name") or "",
                            "type": record.get("type") or "",
                            "description": record.get("description") or "",
                        })
            
            # Combine text for each document
            for doc_data in chunks_by_doc.values():
                doc_data["combined_text"] = "\n\n".join(
                    c.get("text", "") for c in doc_data["chunks"]
                )
            
            logger.info("get_chunks_with_graph_structure",
                       num_docs=len(chunks_by_doc),
                       total_chunks=sum(len(d["chunks"]) for d in chunks_by_doc.values()),
                       total_kvps=sum(len(d["kvps"]) for d in chunks_by_doc.values()),
                       total_tables=sum(len(d["tables"]) for d in chunks_by_doc.values()),
                       total_entities=sum(len(d["entities"]) for d in chunks_by_doc.values()),
                       group_id=self._group_id)
                       
        except Exception as e:
            logger.error("get_chunks_with_graph_structure_failed", error=str(e), group_id=self._group_id)
        
        return list(chunks_by_doc.values())

    async def get_sentence_level_context(
        self,
        entity_ids: List[str],
        *,
        top_k_docs: int = 5,
        max_sentences_per_doc: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Get sentence-level context from documents using Azure DI language spans.
        
        This is the KEY method for sentence-level retrieval. Instead of returning
        full chunks, we use Azure DI's language_spans (sentence boundaries) to
        extract individual sentences from documents.
        
        Traversal path:
        1. Entity (from HippoRAG evidence) → APPEARS_IN_DOCUMENT → Document
        2. Document has language_spans (JSON with {locale, confidence, spans: [{offset, length}]})
        3. Reconstruct full document content from TextChunks (ordered by chunk_index)
        4. Extract sentences using span offsets/lengths
        
        Args:
            entity_ids: List of Entity node IDs from HippoRAG PPR
            top_k_docs: Max number of documents to process
            max_sentences_per_doc: Max sentences to extract per document
            
        Returns:
            List of dicts with:
            - document_title: Document title
            - document_id: Document ID
            - sentences: List of {text, offset, length, confidence, locale}
            - full_content: Reconstructed full document content (for reference)
        """
        return await asyncio.to_thread(
            self._get_sentence_level_context_sync,
            entity_ids,
            top_k_docs,
            max_sentences_per_doc,
        )

    def _get_sentence_level_context_sync(
        self,
        entity_ids: List[str],
        top_k_docs: int,
        max_sentences_per_doc: int,
    ) -> List[Dict[str, Any]]:
        """Sync implementation of sentence-level context retrieval."""
        if not entity_ids:
            return []
        
        # Step 1: Find documents linked to these entities via APPEARS_IN_DOCUMENT
        # Also get language_spans from Document nodes
        doc_query = """
        UNWIND $entity_ids AS entity_id
        MATCH (e:Entity {group_id: $group_id})-[:APPEARS_IN_DOCUMENT]->(d:Document {group_id: $group_id})
        WHERE e.id = entity_id OR e.name = entity_id
        WITH DISTINCT d
        LIMIT $top_k_docs
        RETURN 
            d.id AS doc_id,
            coalesce(d.title, d.source, 'Unknown') AS doc_title,
            d.language_spans AS language_spans
        """
        
        docs_with_spans: List[Dict[str, Any]] = []
        
        try:
            with self._driver.session() as session:
                result = session.run(
                    doc_query,
                    group_id=self._group_id,
                    entity_ids=entity_ids,
                    top_k_docs=top_k_docs,
                )
                for record in result:
                    docs_with_spans.append({
                        "doc_id": record.get("doc_id") or "",
                        "doc_title": record.get("doc_title") or "Unknown",
                        "language_spans": record.get("language_spans") or "[]",
                    })
                
                if not docs_with_spans:
                    logger.debug(
                        "sentence_level_no_docs_from_entities",
                        entity_ids=entity_ids[:5],
                        group_id=self._group_id,
                    )
                    return []
                
                # Step 2: For each document, get full content from TextChunks
                results: List[Dict[str, Any]] = []
                
                for doc_info in docs_with_spans:
                    doc_id = doc_info["doc_id"]
                    doc_title = doc_info["doc_title"]
                    spans_json = doc_info["language_spans"]
                    
                    # Parse language spans
                    try:
                        all_spans = json.loads(spans_json) if spans_json else []
                    except (json.JSONDecodeError, TypeError):
                        all_spans = []
                    
                    if not all_spans:
                        continue
                    
                    # Get all chunks for this document, ordered by chunk_index
                    chunks_query = """
                    MATCH (tc:TextChunk {group_id: $group_id})-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
                    WHERE d.id = $doc_id
                    RETURN tc.text AS text, tc.chunk_index AS idx
                    ORDER BY coalesce(tc.chunk_index, 0) ASC
                    """
                    
                    chunks_result = session.run(
                        chunks_query,
                        group_id=self._group_id,
                        doc_id=doc_id,
                    )
                    
                    # Reconstruct full document content
                    # Note: We concatenate chunks without newlines to match Azure DI's
                    # original span offsets which are relative to the full document
                    full_content_parts = []
                    for chunk_record in chunks_result:
                        text = chunk_record.get("text") or ""
                        full_content_parts.append(text)
                    
                    # Azure DI spans are relative to original document content
                    # The chunks were created from that content, so concatenating
                    # should restore the original offsets
                    full_content = "".join(full_content_parts)
                    
                    if not full_content:
                        continue
                    
                    # Step 3: Extract sentences using language spans
                    sentences: List[Dict[str, Any]] = []
                    
                    # Sort all language groups by confidence (highest first)
                    sorted_langs = sorted(
                        all_spans,
                        key=lambda x: x.get("confidence", 0.0),
                        reverse=True,
                    )
                    
                    # Extract sentences from highest-confidence language spans
                    for lang_group in sorted_langs:
                        locale = lang_group.get("locale", "")
                        confidence = lang_group.get("confidence", 0.0)
                        spans = lang_group.get("spans", [])
                        
                        for span in spans:
                            if len(sentences) >= max_sentences_per_doc:
                                break
                            
                            offset = span.get("offset", 0)
                            length = span.get("length", 0)
                            
                            # Extract sentence text using offset/length
                            if offset >= 0 and length > 0 and offset + length <= len(full_content):
                                sentence_text = full_content[offset:offset + length]
                                
                                # Skip very short or empty sentences
                                if len(sentence_text.strip()) < 3:
                                    continue
                                
                                sentences.append({
                                    "text": sentence_text,
                                    "offset": offset,
                                    "length": length,
                                    "confidence": confidence,
                                    "locale": locale,
                                })
                        
                        if len(sentences) >= max_sentences_per_doc:
                            break
                    
                    if sentences:
                        results.append({
                            "document_title": doc_title,
                            "document_id": doc_id,
                            "sentences": sentences,
                            "full_content": full_content,
                            "total_spans": sum(
                                len(lg.get("spans", [])) for lg in all_spans
                            ),
                        })
                
                logger.info(
                    "sentence_level_context_retrieved",
                    num_entities=len(entity_ids),
                    num_docs_processed=len(results),
                    total_sentences=sum(len(r["sentences"]) for r in results),
                    group_id=self._group_id,
                )
                
                return results
                
        except Exception as e:
            logger.error(
                "sentence_level_context_failed",
                error=str(e),
                entity_ids=entity_ids[:5],
                group_id=self._group_id,
            )
            return []

    async def get_all_documents_with_sentences(
        self,
        *,
        top_k_docs: int = 10,
        max_sentences_per_doc: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get ALL documents with sentence-level context (no entity filtering).
        
        This is a FALLBACK when entity-based traversal fails (e.g., when evidence_nodes
        contains generic terms like "Contract" that don't match real Entity.name values).
        
        Args:
            top_k_docs: Max number of documents to process
            max_sentences_per_doc: Max sentences to extract per document
            
        Returns:
            List of dicts with document_title, document_id, sentences, full_content
        """
        return await asyncio.to_thread(
            self._get_all_documents_with_sentences_sync,
            top_k_docs,
            max_sentences_per_doc,
        )

    def _get_all_documents_with_sentences_sync(
        self,
        top_k_docs: int,
        max_sentences_per_doc: int,
    ) -> List[Dict[str, Any]]:
        """Sync implementation: get all documents with sentence spans."""
        import json
        
        # Get all documents with language_spans
        doc_query = """
        MATCH (d:Document {group_id: $group_id})
        WHERE d.language_spans IS NOT NULL
        RETURN 
            d.id AS doc_id,
            coalesce(d.title, d.source, 'Unknown') AS doc_title,
            d.language_spans AS language_spans
        LIMIT $top_k_docs
        """
        
        results: List[Dict[str, Any]] = []
        
        try:
            with self._driver.session() as session:
                doc_result = session.run(
                    doc_query,
                    group_id=self._group_id,
                    top_k_docs=top_k_docs,
                )
                docs_with_spans = list(doc_result)
                
                if not docs_with_spans:
                    logger.debug(
                        "get_all_documents_no_language_spans",
                        group_id=self._group_id,
                    )
                    return []
                
                for doc_record in docs_with_spans:
                    doc_id = doc_record.get("doc_id") or ""
                    doc_title = doc_record.get("doc_title") or "Unknown"
                    language_spans_raw = doc_record.get("language_spans") or "[]"
                    
                    # Get full content from TextChunks
                    content_query = """
                    MATCH (c:TextChunk {group_id: $group_id})-[:IN_DOCUMENT]->(d:Document {id: $doc_id, group_id: $group_id})
                    RETURN c.text AS text, c.chunk_index AS idx
                    ORDER BY coalesce(c.chunk_index, 0) ASC
                    """
                    content_result = session.run(
                        content_query,
                        group_id=self._group_id,
                        doc_id=doc_id,
                    )
                    
                    # Reconstruct full document content
                    # Azure DI spans are relative to original document content.
                    # Concatenate chunks WITHOUT newlines to match original offsets.
                    full_content = "".join(
                        r.get("text") or "" for r in content_result
                    )
                    
                    if not full_content.strip():
                        continue
                    
                    # Parse language spans
                    sentences = []
                    try:
                        spans_data = json.loads(language_spans_raw) if isinstance(language_spans_raw, str) else language_spans_raw
                        
                        # Handle various formats:
                        # 1. List with single dict: [{"locale": "en", "spans": [...]}]
                        # 2. Direct dict: {"locale": "en", "spans": [...]}
                        # 3. Direct list of spans: [{"offset": 0, "length": 10}, ...]
                        if isinstance(spans_data, list) and len(spans_data) > 0:
                            first_item = spans_data[0]
                            if isinstance(first_item, dict) and "spans" in first_item:
                                # Format 1: List with single dict containing spans
                                spans_list = first_item.get("spans", [])
                                locale = first_item.get("locale", "en")
                                confidence = first_item.get("confidence", 1.0)
                            elif isinstance(first_item, dict) and "offset" in first_item:
                                # Format 3: Direct list of span objects
                                spans_list = spans_data
                                locale = "en"
                                confidence = 1.0
                            else:
                                spans_list = []
                                locale = "en"
                                confidence = 1.0
                        elif isinstance(spans_data, dict):
                            # Format 2: Direct dict with spans
                            spans_list = spans_data.get("spans", [])
                            locale = spans_data.get("locale", "en")
                            confidence = spans_data.get("confidence", 1.0)
                        else:
                            spans_list = []
                            locale = "en"
                            confidence = 1.0
                        
                        for span in spans_list[:max_sentences_per_doc]:
                            offset = span.get("offset", 0)
                            length = span.get("length", 0)
                            
                            if offset >= 0 and length > 0 and offset + length <= len(full_content):
                                text = full_content[offset:offset + length]
                                sentences.append({
                                    "text": text,
                                    "offset": offset,
                                    "length": length,
                                    "confidence": confidence,
                                    "locale": locale,
                                })
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug("language_spans_parse_error", doc_id=doc_id, error=str(e))
                    
                    results.append({
                        "document_title": doc_title,
                        "document_id": doc_id,
                        "sentences": sentences,
                        "full_content": full_content[:5000],  # Truncate for memory
                    })
                
                logger.info(
                    "get_all_documents_with_sentences",
                    num_docs=len(results),
                    total_sentences=sum(len(d.get("sentences", [])) for d in results),
                    group_id=self._group_id,
                )
                
        except Exception as e:
            logger.error("get_all_documents_with_sentences_failed", error=str(e), group_id=self._group_id)
        
        return results

    def _get_workspace_document_overviews_sync(self, limit: int) -> List[Dict[str, Any]]:
        """Sync implementation of document overview retrieval."""
        query = """
        MATCH (d:Document)
        WHERE d.group_id = $group_id
        OPTIONAL MATCH (d)<-[:IN_DOCUMENT]-(c)
        WITH d, count(c) AS chunk_count
        RETURN 
            d.id AS id,
            coalesce(d.title, d.name, d.source, 'Untitled') AS title,
            d.summary AS summary,
            d.source AS source,
            d.url AS url,
            d.date AS date,
            chunk_count
        ORDER BY coalesce(d.date, '') DESC
        LIMIT $limit
        """
        
        docs: List[Dict[str, Any]] = []
        try:
            with self._driver.session() as session:
                result = session.run(query, group_id=self._group_id, limit=limit)
                for record in result:
                    doc = {
                        "id": record.get("id") or "",
                        "title": record.get("title") or "Untitled",
                        "summary": record.get("summary") or "",
                        "source": record.get("source") or "",
                        "url": record.get("url") or "",
                        "date": record.get("date") or "",
                        "chunk_count": record.get("chunk_count") or 0,
                    }
                    docs.append(doc)
        except Exception as e:
            logger.error("get_workspace_document_overviews_failed", error=str(e))
        
        return docs
# Force rebuild Mon Feb  2 11:05:12 UTC 2026
