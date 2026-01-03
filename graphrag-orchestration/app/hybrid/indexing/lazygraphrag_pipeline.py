"""LazyGraphRAG indexing pipeline (hybrid-owned).

This exists to avoid coupling `/hybrid/index/documents` to the V3 router or the V3
indexing pipeline implementation. The hybrid system needs a stable, dedicated
indexing entrypoint that populates the Neo4j schema used by:
- Route 1 (Neo4j vector search over :TextChunk.embedding)
- Route 2/3 (LazyGraphRAG + HippoRAG over :Entity / :TextChunk / :MENTIONS)

Design goals:
- No imports from `app.v3.routers.*`
- Minimal surface area: one async `index_documents` method
- Best-effort behavior when LLM/embeddings are not configured (skip that stage)
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument
from llama_index.core.schema import TextNode

from app.services.document_intelligence_service import DocumentIntelligenceService
from app.v3.services.entity_deduplication import EntityDeduplicationService
from app.v3.services.neo4j_store import Document, Entity, Neo4jStoreV3, Relationship, TextChunk

logger = logging.getLogger(__name__)


@dataclass
class LazyGraphRAGIndexingConfig:
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_dimensions: int = 3072


class LazyGraphRAGIndexingPipeline:
    def __init__(
        self,
        *,
        neo4j_store: Neo4jStoreV3,
        llm: Optional[Any],
        embedder: Optional[Any],
        config: Optional[LazyGraphRAGIndexingConfig] = None,
    ):
        self.neo4j_store = neo4j_store
        self.llm = llm
        self.embedder = embedder
        self.config = config or LazyGraphRAGIndexingConfig()

        self._splitter = SentenceSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )

    async def index_documents(
        self,
        *,
        group_id: str,
        documents: List[Dict[str, Any]],
        reindex: bool = False,
        ingestion: str = "none",
        # These parameters exist on the hybrid endpoint; LazyGraphRAG prefers on-demand
        # community/raptor work, so we ignore them but keep signature compatibility.
        run_community_detection: bool = False,
        run_raptor: bool = False,
    ) -> Dict[str, Any]:
        start_time = time.time()
        logger.info(
            "lazy_index_start",
            extra={
                "group_id": group_id,
                "documents": len(documents),
                "reindex": reindex,
                "ingestion": ingestion,
            },
        )

        stats: Dict[str, Any] = {
            "group_id": group_id,
            "documents": len(documents),
            "chunks": 0,
            "entities": 0,
            "relationships": 0,
            "deduplication": None,
            "skipped": [],
        }

        if reindex:
            self.neo4j_store.delete_group_data(group_id)

        # 1) Normalize + (optional) extract with Document Intelligence.
        expanded_docs = await self._prepare_documents(group_id, documents, ingestion)

        # 2) Upsert Documents + chunk text units.
        all_chunks: List[TextChunk] = []
        chunk_to_doc_id: Dict[str, str] = {}
        for doc in expanded_docs:
            doc_id = doc["id"]
            self.neo4j_store.upsert_document(
                group_id,
                Document(
                    id=doc_id,
                    title=doc.get("title", "Untitled"),
                    source=doc.get("source", ""),
                    metadata=doc.get("metadata", {}) or {},
                ),
            )

            chunks = await self._chunk_document(doc, doc_id)
            for c in chunks:
                chunk_to_doc_id[c.id] = doc_id
            all_chunks.extend(chunks)

        if not all_chunks:
            stats["skipped"].append("no_chunks")
            stats["elapsed_s"] = round(time.time() - start_time, 2)
            return stats

        # 3) Embeddings for chunks (best-effort).
        await self._embed_chunks_best_effort(all_chunks)

        # 4) Persist chunks.
        self.neo4j_store.upsert_text_chunks_batch(group_id, all_chunks)
        stats["chunks"] = len(all_chunks)

        # 5) Entity/relationship extraction (best-effort, but recommended).
        entities: List[Entity] = []
        relationships: List[Relationship] = []
        if self.llm is None:
            stats["skipped"].append("no_llm_entity_extraction")
        else:
            entities, relationships = await self._extract_entities_and_relationships(
                group_id=group_id,
                chunks=all_chunks,
            )

        # 6) Entity deduplication (optional; only if we have enough entities).
        if entities:
            entities, relationships, dedup_stats = self._deduplicate_entities(
                group_id=group_id,
                entities=entities,
                relationships=relationships,
            )
            stats["deduplication"] = dedup_stats

        # 7) Persist entities + relationships.
        if entities:
            await self.neo4j_store.aupsert_entities_batch(group_id, entities)
        if relationships:
            self.neo4j_store.upsert_relationships_batch(group_id, relationships)

        stats["entities"] = len(entities)
        stats["relationships"] = len(relationships)
        stats["elapsed_s"] = round(time.time() - start_time, 2)
        return stats

    async def _prepare_documents(
        self,
        group_id: str,
        documents: List[Dict[str, Any]],
        ingestion: str,
    ) -> List[Dict[str, Any]]:
        # Assign stable IDs and normalize fields.
        normalized: List[Dict[str, Any]] = []
        url_inputs: List[str] = []

        for doc in documents:
            content = doc.get("content") or doc.get("text") or ""
            source = doc.get("source") or doc.get("url") or ""
            title = doc.get("title") or (source.split("/")[-1] if source else "Untitled")

            # If content is itself a URL, treat it as source.
            if isinstance(content, str) and content.strip().startswith(("http://", "https://")):
                source = content.strip()
                content = ""

            doc_id = doc.get("id") or f"doc_{uuid.uuid4().hex}"
            normalized.append(
                {
                    "id": doc_id,
                    "title": title,
                    "source": source,
                    "content": content,
                    "metadata": doc.get("metadata", {}) or {},
                }
            )

            if ingestion == "document-intelligence" and not str(content).strip() and str(source).startswith("http"):
                url_inputs.append(str(source))

        if ingestion != "document-intelligence" or not url_inputs:
            return normalized

        di_service = DocumentIntelligenceService()
        extracted = await di_service.extract_documents(
            group_id=group_id,
            input_items=cast(List[str | Dict[str, Any]], url_inputs),
            fail_fast=True,
            model_strategy="auto",
        )

        # Build per-source DI units.
        by_source: Dict[str, List[LlamaDocument]] = {}
        for d in extracted:
            src = (d.metadata or {}).get("url", "")
            by_source.setdefault(src, []).append(d)

        out: List[Dict[str, Any]] = []
        for doc in normalized:
            src = doc.get("source", "")
            if src and src in by_source:
                # Keep the top-level document, but chunk from DI units.
                meta = dict(doc.get("metadata", {}) or {})
                meta["di_units"] = len(by_source[src])
                doc2 = dict(doc)
                doc2["metadata"] = meta
                doc2["di_extracted_docs"] = by_source[src]
                out.append(doc2)
            else:
                out.append(doc)

        return out

    async def _chunk_document(self, document: Dict[str, Any], doc_id: str) -> List[TextChunk]:
        di_units: Sequence[LlamaDocument] = document.get("di_extracted_docs") or []
        if di_units:
            return await self._chunk_di_units(di_units=di_units, doc_id=doc_id)

        content = (document.get("content") or "").strip()
        if not content:
            return []

        llama_doc = LlamaDocument(text=content, id_=doc_id, metadata={"source": document.get("source", "")})
        nodes = self._splitter.get_nodes_from_documents([llama_doc])
        chunks: List[TextChunk] = []
        for idx, node in enumerate(nodes):
            text = node.get_content().strip()
            if not text:
                continue
            chunks.append(
                TextChunk(
                    id=f"{doc_id}_chunk_{idx}",
                    text=text,
                    chunk_index=idx,
                    document_id=doc_id,
                    embedding=None,
                    tokens=len(text.split()),
                    metadata={"source": document.get("source", "")},
                )
            )
        return chunks

    async def _chunk_di_units(self, *, di_units: Sequence[LlamaDocument], doc_id: str) -> List[TextChunk]:
        chunks: List[TextChunk] = []
        chunk_index = 0
        for unit_i, unit in enumerate(di_units):
            # IMPORTANT: Document Intelligence metadata can be very large (tables/layout).
            # LlamaIndex's SentenceSplitter is metadata-aware by default and can raise
            # when metadata alone exceeds the chunk budget.
            #
            # To keep indexing robust, chunk using a text-only wrapper document and
            # attach only a small allowlist of DI fields to our stored chunk metadata.
            unit_text = getattr(unit, "text", "") or ""
            unit_meta = getattr(unit, "metadata", None) or {}

            safe_doc = LlamaDocument(
                text=unit_text,
                id_=f"{doc_id}_di_{unit_i}",
                metadata={},
            )
            nodes = self._splitter.get_nodes_from_documents([safe_doc])
            for node in nodes:
                text = node.get_content().strip()
                if not text:
                    continue
                md: Dict[str, Any] = {}

                # Preserve the same DI fields as V3 (matching _chunk_di_extracted_docs).
                # Cap tables to avoid exploding metadata size.
                tables_meta = unit_meta.get("tables")
                if isinstance(tables_meta, list) and len(tables_meta) > 6:
                    tables_meta = tables_meta[:6]

                for k in (
                    "chunk_type",
                    "page_number",
                    "section_path",
                    "di_section_path",
                    "di_section_part",
                    "url",
                    "table_count",
                    "paragraph_count",
                ):
                    if k in unit_meta and unit_meta.get(k) is not None:
                        md[k] = unit_meta.get(k)
                if tables_meta:
                    md["tables"] = tables_meta
                if unit_meta.get("url"):
                    md["source"] = unit_meta.get("url")

                chunks.append(
                    TextChunk(
                        id=f"{doc_id}_chunk_{chunk_index}",
                        text=text,
                        chunk_index=chunk_index,
                        document_id=doc_id,
                        embedding=None,
                        tokens=len(text.split()),
                        metadata=md,
                    )
                )
                chunk_index += 1
        return chunks

    async def _embed_chunks_best_effort(self, chunks: List[TextChunk]) -> None:
        if self.embedder is None:
            logger.warning("lazy_index_no_embedder", extra={"chunks": len(chunks)})
            return

        texts = [c.text for c in chunks]
        try:
            embeddings = await self.embedder.aget_text_embedding_batch(texts)
            logger.info(f"lazy_index_embeddings_generated", extra={"chunks": len(chunks), "embeddings": len(embeddings)})
        except Exception as e:
            logger.error(f"❌ EMBEDDING FAILED: {e}", exc_info=True, extra={"error": str(e), "chunks": len(chunks)})
            # Don't silently fail - this is critical for vector search
            raise RuntimeError(f"Embedding generation failed: {e}") from e

        success_count = 0
        for chunk, emb in zip(chunks, embeddings):
            try:
                if emb and isinstance(emb, list) and len(emb) == self.config.embedding_dimensions:
                    chunk.embedding = emb
                    success_count += 1
                else:
                    chunk.embedding = emb
                    if emb:
                        success_count += 1
            except Exception as e:
                logger.warning(f"lazy_index_chunk_embedding_assign_failed", extra={"error": str(e)})
                continue
        
        logger.info(f"lazy_index_embeddings_assigned", extra={"success": success_count, "total": len(chunks)})

    async def _extract_entities_and_relationships(
        self,
        *,
        group_id: str,
        chunks: List[TextChunk],
    ) -> Tuple[List[Entity], List[Relationship]]:
        # Use LlamaIndex extractor to produce KG nodes/relations per chunk.
        if self.llm is None:
            return [], []

        extractor = SchemaLLMPathExtractor(
            llm=cast(Any, self.llm),
            possible_entities=None,
            possible_relations=None,
            strict=False,
            num_workers=1,
            max_triplets_per_chunk=12,
        )

        nodes: List[TextNode] = []
        for c in chunks:
            nodes.append(
                TextNode(
                    id_=c.id,
                    text=c.text,
                    metadata={"chunk_index": c.chunk_index, "document_id": c.document_id},
                )
            )

        extracted_nodes = await extractor.acall(nodes)

        # Collect entities/relations and link to originating chunk via text_unit_ids.
        entities_by_key: Dict[str, Entity] = {}
        rel_keys: set[tuple[str, str, str]] = set()
        relationships: List[Relationship] = []

        for n in extracted_nodes:
            chunk_id = getattr(n, "id_", None) or getattr(n, "id", None) or ""
            meta = getattr(n, "metadata", {}) or {}
            kg_nodes = meta.get("kg_nodes") or []
            kg_rels = meta.get("kg_relations") or meta.get("kg_relations", []) or []

            for kn in kg_nodes:
                name = getattr(kn, "name", None)
                if name is None and isinstance(kn, dict):
                    name = kn.get("name")
                name = (str(name) if name is not None else "").strip()
                if not name:
                    continue

                key = self._canonical_entity_key(name)
                if not key:
                    continue

                ent = entities_by_key.get(key)
                if ent is None:
                    ent_id = self._stable_entity_id(group_id, key)
                    ent = Entity(
                        id=ent_id,
                        name=name,
                        type=getattr(kn, "label", None) or (kn.get("label") if isinstance(kn, dict) else None) or "CONCEPT",
                        description="",
                        embedding=None,
                        metadata={},
                        text_unit_ids=[],
                    )
                    entities_by_key[key] = ent

                if chunk_id and chunk_id not in ent.text_unit_ids:
                    ent.text_unit_ids.append(chunk_id)

            for kr in kg_rels:
                # Best-effort parsing of relation objects/dicts.
                subj = getattr(kr, "source", None) or getattr(kr, "subject", None)
                obj = getattr(kr, "target", None) or getattr(kr, "object", None)
                label = getattr(kr, "label", None) or getattr(kr, "relation", None)

                if isinstance(kr, dict):
                    subj = subj or kr.get("source") or kr.get("subject")
                    obj = obj or kr.get("target") or kr.get("object")
                    label = label or kr.get("label") or kr.get("relation")

                subj_name = (str(subj) if subj is not None else "").strip()
                obj_name = (str(obj) if obj is not None else "").strip()
                if not subj_name or not obj_name:
                    continue

                skey = self._canonical_entity_key(subj_name)
                okey = self._canonical_entity_key(obj_name)
                if not skey or not okey:
                    continue

                sid = self._stable_entity_id(group_id, skey)
                tid = self._stable_entity_id(group_id, okey)

                rel_desc = (str(label) if label is not None else "RELATED_TO").strip() or "RELATED_TO"
                rel_key = (sid, tid, rel_desc)
                if rel_key in rel_keys:
                    continue
                rel_keys.add(rel_key)

                relationships.append(
                    Relationship(
                        source_id=sid,
                        target_id=tid,
                        type="RELATED_TO",
                        description=rel_desc,
                        weight=1.0,
                    )
                )

        # Embeddings for entities (best-effort).
        entities = list(entities_by_key.values())
        if entities and self.embedder is not None:
            texts = [f"{e.name}: {e.description}" if e.description else e.name for e in entities]
            try:
                embs = await self.embedder.aget_text_embedding_batch(texts)
                for ent, emb in zip(entities, embs):
                    ent.embedding = emb
            except Exception as e:
                logger.warning("lazy_index_entity_embedding_failed", extra={"error": str(e)})

        return entities, relationships

    def _deduplicate_entities(
        self,
        *,
        group_id: str,
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> Tuple[List[Entity], List[Relationship], Dict[str, Any]]:
        dedup_service = EntityDeduplicationService(
            similarity_threshold=0.95,
            min_entities_for_dedup=10,
        )

        entity_dicts = [
            {
                "name": e.name,
                "embedding": e.embedding,
                "type": e.type,
                "description": e.description,
                "properties": (e.metadata or {}),
            }
            for e in entities
        ]

        dedup_result = dedup_service.deduplicate_entities(entity_dicts, group_id=group_id)
        if not dedup_result.merge_map:
            return entities, relationships, {
                "entities_before": len(entities),
                "entities_after": len(entities),
                "entities_merged": 0,
            }

        merge_map = dedup_result.merge_map

        # Rebuild entities keyed by canonical name, keep deterministic IDs.
        by_canonical: Dict[str, List[Entity]] = {}
        for e in entities:
            canon = merge_map.get(e.name, e.name)
            by_canonical.setdefault(canon, []).append(e)

        canonical_entities: Dict[str, Entity] = {}
        id_remap: Dict[str, str] = {}
        for canon_name, members in by_canonical.items():
            key = self._canonical_entity_key(canon_name)
            canon_id = self._stable_entity_id(group_id, key)
            merged_text_units: set[str] = set()
            merged_desc = ""
            merged_type = "CONCEPT"
            merged_meta: Dict[str, Any] = {}
            merged_emb = None

            for m in members:
                id_remap[m.id] = canon_id
                merged_text_units.update(m.text_unit_ids or [])
                if not merged_desc and m.description:
                    merged_desc = m.description
                merged_type = m.type or merged_type
                merged_meta.update(m.metadata or {})
                if merged_emb is None and m.embedding:
                    merged_emb = m.embedding

            canonical_entities[canon_id] = Entity(
                id=canon_id,
                name=canon_name,
                type=merged_type,
                description=merged_desc,
                embedding=merged_emb,
                metadata=merged_meta,
                text_unit_ids=sorted(merged_text_units),
            )

        # Remap relationships.
        out_rels: List[Relationship] = []
        seen: set[tuple[str, str, str]] = set()
        for r in relationships:
            sid = id_remap.get(r.source_id, r.source_id)
            tid = id_remap.get(r.target_id, r.target_id)
            desc = r.description or "RELATED_TO"
            k = (sid, tid, desc)
            if k in seen:
                continue
            remember = (sid, tid, desc)
            seen.add(remember)
            out_rels.append(
                Relationship(
                    source_id=sid,
                    target_id=tid,
                    type="RELATED_TO",
                    description=desc,
                    weight=r.weight,
                )
            )

        dedup_stats = {
            "entities_before": dedup_result.total_entities,
            "entities_after": dedup_result.unique_after_merge,
            "entities_merged": len(dedup_result.merge_map),
            "embedding_merges": dedup_result.embedding_merges,
            "rule_merges": dedup_result.rule_merges,
        }
        return list(canonical_entities.values()), out_rels, dedup_stats

    @staticmethod
    def _canonical_entity_key(name: str) -> str:
        s = (name or "").strip().lower()
        if not s:
            return ""
        s = s.replace("\u00a0", " ")
        s = re.sub(r"[^a-z0-9_&\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def _stable_entity_id(group_id: str, canonical_key: str) -> str:
        h = hashlib.sha256()
        h.update(group_id.encode("utf-8", errors="ignore"))
        h.update(b"\n")
        h.update(canonical_key.encode("utf-8", errors="ignore"))
        return f"entity_{h.hexdigest()[:12]}"
