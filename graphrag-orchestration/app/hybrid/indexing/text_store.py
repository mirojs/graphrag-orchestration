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
        OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
        WITH c, d, score
        ORDER BY score DESC, coalesce(c.chunk_index, 0) ASC
        RETURN c AS chunk, d AS doc, score,
               coalesce(d.create_date, d.date, '') AS doc_date,
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

    def _get_chunks_for_entities_batch_sync(self, entity_names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Batch query to fetch chunks for multiple entities in a single round-trip."""
        query = """
        UNWIND $entity_names AS entity_name
        WITH entity_name
        CALL (entity_name) {
            OPTIONAL MATCH (e:Entity {group_id: $group_id})
            WHERE toLower(e.name) = toLower(entity_name)
            RETURN e
            UNION
            OPTIONAL MATCH (e:`__Entity__` {group_id: $group_id})
            WHERE toLower(e.name) = toLower(entity_name)
            RETURN e
        }
        WITH entity_name, [x IN collect(e) WHERE x IS NOT NULL][0] AS e
        CALL (e) {
            OPTIONAL MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            OPTIONAL MATCH (e)-[:MENTIONS]->(c:TextChunk {group_id: $group_id})
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            OPTIONAL MATCH (c:Chunk {group_id: $group_id})-[:MENTIONS]->(e)
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            OPTIONAL MATCH (e)-[:MENTIONS]->(c:Chunk {group_id: $group_id})
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            OPTIONAL MATCH (c:`__Node__` {group_id: $group_id})-[:MENTIONS]->(e)
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            OPTIONAL MATCH (e)-[:MENTIONS]->(c:`__Node__` {group_id: $group_id})
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
        }
        WITH entity_name, collect({chunk: c, doc: d}) AS items
        WITH entity_name, [i IN items WHERE i.chunk IS NOT NULL] AS items
        UNWIND items AS item
        WITH entity_name, item.chunk AS c, item.doc AS d
        ORDER BY entity_name, coalesce(c.chunk_index, 0) ASC
        WITH entity_name, collect({chunk: c, doc: d})[0..$limit] AS items
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
                
                rows: List[Dict[str, Any]] = []
                seen_chunk_ids: set[str] = set()
                for item in items:
                    c = (item or {}).get("chunk")
                    d = (item or {}).get("doc")
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
                    doc_title = (d.get("title") if d else "") or meta.get("document_title") or ""
                    doc_source = (d.get("source") if d else "") or meta.get("document_source") or ""
                    url = meta.get("url") or doc_source or ""
                    
                    # Build a readable section label for citations.
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
                            "id": chunk_id,
                            "source": str(source_label),
                            "text": str(c.get("text") or ""),
                            "entity": entity_name,
                            "metadata": {
                                **meta,
                                "document_title": str(doc_title),
                                "document_source": str(doc_source),
                            },
                        }
                    )
                
                results[entity_name] = rows
                
                if not rows:
                    logger.debug("neo4j_text_store_no_chunks", entity=entity_name)
        
        return results

    async def get_workspace_document_overviews(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve high-level overview of all documents in the workspace.
        
        This addresses corpus-level questions (e.g., 'latest date', 'compare documents')
        where entity-based PPR traversal fails because the query is too abstract.
        
        Returns:
            List of dicts with document metadata: id, title, date, summary, source.
        """
        return await asyncio.to_thread(self._get_workspace_document_overviews_sync, int(limit))

    def _get_workspace_document_overviews_sync(self, limit: int) -> List[Dict[str, Any]]:
        """Sync implementation of document overview retrieval."""
        query = """
        MATCH (d:Document)
        WHERE d.group_id = $group_id
        OPTIONAL MATCH (d)<-[:PART_OF]-(c)
        WITH d, count(c) AS chunk_count
        RETURN 
            d.id AS id,
            coalesce(d.title, d.name, d.source, 'Untitled') AS title,
            d.summary AS summary,
            d.source AS source,
            d.url AS url,
            d.create_date AS create_date,
            d.date AS date,
            chunk_count
        ORDER BY coalesce(d.create_date, d.date, '') DESC
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
                        "date": record.get("create_date") or record.get("date") or "",
                        "chunk_count": record.get("chunk_count") or 0,
                    }
                    docs.append(doc)
        except Exception as e:
            logger.error("get_workspace_document_overviews_failed", error=str(e))
        
        return docs
