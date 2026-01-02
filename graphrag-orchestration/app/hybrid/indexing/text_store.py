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
        name = (entity_name or "").strip()
        if not name:
            return []

        # Neo4j python driver is sync; run in a thread to avoid blocking the event loop.
        return await asyncio.to_thread(self._get_chunks_for_entity_sync, name)

    def _get_chunks_for_entity_sync(self, entity_name: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (e:Entity {group_id: $group_id})
        WHERE toLower(e.name) = toLower($entity_name)
        MATCH (c:TextChunk {group_id: $group_id})-[:MENTIONS]->(e)
        OPTIONAL MATCH (c)-[:PART_OF]->(d:Document {group_id: $group_id})
        RETURN c, d
        ORDER BY coalesce(c.chunk_index, 0) ASC
        LIMIT $limit
        """

        rows: List[Dict[str, Any]] = []
        with self._driver.session() as session:
            result = session.run(
                query,
                group_id=self._group_id,
                entity_name=entity_name,
                limit=self._limit,
            )
            for record in result:
                c = record.get("c")
                d = record.get("d")
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
                        "id": c.get("id") or "",
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

        if not rows:
            logger.debug("neo4j_text_store_no_chunks", entity=entity_name)

        return rows
