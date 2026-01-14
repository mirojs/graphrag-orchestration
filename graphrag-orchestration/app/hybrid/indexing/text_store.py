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
        CALL {
            WITH entity_name
            OPTIONAL MATCH (e:Entity {group_id: $group_id})
            WHERE toLower(e.name) = toLower(entity_name)
            RETURN e
            UNION
            WITH entity_name
            OPTIONAL MATCH (e:`__Entity__` {group_id: $group_id})
            WHERE toLower(e.name) = toLower(entity_name)
            RETURN e
        }
        WITH entity_name, [x IN collect(e) WHERE x IS NOT NULL][0] AS e
        CALL {
            WITH e
            OPTIONAL MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            WITH e
            OPTIONAL MATCH (e)-[:MENTIONS]->(c:TextChunk {group_id: $group_id})
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            WITH e
            OPTIONAL MATCH (c:Chunk {group_id: $group_id})-[:MENTIONS]->(e)
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            WITH e
            OPTIONAL MATCH (e)-[:MENTIONS]->(c:Chunk {group_id: $group_id})
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            WITH e
            OPTIONAL MATCH (c:`__Node__` {group_id: $group_id})-[:MENTIONS]->(e)
            OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
            RETURN c AS c, d AS d
            UNION
            WITH e
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
