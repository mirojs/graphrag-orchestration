"""LazyGraphRAG indexing pipeline (hybrid-owned).

This exists to avoid coupling `/hybrid/index/documents` to the V3 router or the V3
indexing pipeline implementation. The hybrid system needs a stable, dedicated
indexing entrypoint that populates the Neo4j schema used by:
- Route 1 (Neo4j vector search over :TextChunk.embedding)
- Route 2/3 (LazyGraphRAG + HippoRAG over :Entity / :TextChunk / :MENTIONS)

Phase 2 Migration: Added optional neo4j-graphrag LLMEntityRelationExtractor support.
Set use_native_extractor=True in config to use the native extractor.

Design goals:
- No imports from `app.archive.v3.routers.*` (archived)
- Minimal surface area: one async `index_documents` method
- Best-effort behavior when LLM/embeddings are not configured (skip that stage)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument
from llama_index.core.schema import TextNode

# neo4j-graphrag native extractor (Phase 2 migration - optional)
try:
    from neo4j_graphrag.experimental.components.entity_relation_extractor import LLMEntityRelationExtractor
    from neo4j_graphrag.experimental.components.types import TextChunk as NativeTextChunk, TextChunks
    from neo4j_graphrag.experimental.components.schema import NodeType, PropertyType, RelationshipType, GraphSchema
    from neo4j_graphrag.llm import AzureOpenAILLM
    NATIVE_EXTRACTOR_AVAILABLE = True
except ImportError:
    NATIVE_EXTRACTOR_AVAILABLE = False

from app.services.document_intelligence_service import DocumentIntelligenceService
from app.hybrid_v2.services.entity_deduplication import EntityDeduplicationService
from app.hybrid_v2.services.neo4j_store import Document, Entity, Neo4jStoreV3, Relationship, TextChunk
from app.hybrid_v2.utils.language import canonical_key_for_entity, is_cjk, detect_cjk_from_text
from app.core.config import settings

logger = logging.getLogger(__name__)


def extract_document_date(content: str) -> Optional[str]:
    """Extract the most prominent date from document content.
    
    Scans for common date formats and returns the latest (most recent) date found.
    This enables corpus-level date queries like "Which document has the latest date?"
    
    Returns: ISO date string (YYYY-MM-DD) or None if no dates found.
    """
    from datetime import datetime
    
    dates_found: List[datetime] = []
    
    # Pattern 1: MM/DD/YYYY or M/D/YYYY (US format - common in contracts)
    for match in re.finditer(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', content):
        try:
            month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
                dates_found.append(datetime(year, month, day))
        except (ValueError, OverflowError):
            continue
    
    # Pattern 2: YYYY-MM-DD (ISO format)
    for match in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b', content):
        try:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
                dates_found.append(datetime(year, month, day))
        except (ValueError, OverflowError):
            continue
    
    # Pattern 3: Month DD, YYYY (e.g., "June 15, 2024")
    months = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
    }
    for match in re.finditer(r'\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b', content):
        try:
            month_name = match.group(1).lower()
            if month_name in months:
                month = months[month_name]
                day, year = int(match.group(2)), int(match.group(3))
                if 1 <= day <= 31 and 1900 <= year <= 2100:
                    dates_found.append(datetime(year, month, day))
        except (ValueError, OverflowError):
            continue
    
    # Pattern 4: DD Month YYYY (e.g., "15 June 2024")
    for match in re.finditer(r'\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b', content):
        try:
            month_name = match.group(2).lower()
            if month_name in months:
                month = months[month_name]
                day, year = int(match.group(1)), int(match.group(3))
                if 1 <= day <= 31 and 1900 <= year <= 2100:
                    dates_found.append(datetime(year, month, day))
        except (ValueError, OverflowError):
            continue
    
    if not dates_found:
        return None
    
    # Return the latest (most recent) date - this represents the document's effective date
    latest = max(dates_found)
    return latest.strftime("%Y-%m-%d")


@dataclass
class LazyGraphRAGIndexingConfig:
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_dimensions: int = 3072
    # Phase 2: neo4j-graphrag LLMEntityRelationExtractor (DEFAULT for easy re-indexing)
    use_native_extractor: bool = True
    # Validation thresholds for reliable indexing (Option 2)
    min_entities: int = 3
    min_mentions: int = 5


class LazyGraphRAGIndexingPipeline:
    def __init__(
        self,
        *,
        neo4j_store: Neo4jStoreV3,
        llm: Optional[Any],
        embedder: Optional[Any],
        config: Optional[LazyGraphRAGIndexingConfig] = None,
        use_v2_embedding_property: bool = False,  # V2: store in embedding_v2
    ):
        self.neo4j_store = neo4j_store
        self.llm = llm
        self.embedder = embedder
        self.config = config or LazyGraphRAGIndexingConfig()
        self.use_v2_embedding_property = use_v2_embedding_property  # V2 flag

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
        dry_run: bool = False,
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

        # Initialize GroupMeta node for lifecycle tracking.
        # This creates or updates the GroupMeta node to track GDS staleness, etc.
        self.neo4j_store.initialize_group_meta(group_id)

        # 1) Normalize + (optional) extract with Document Intelligence.
        expanded_docs = await self._prepare_documents(group_id, documents, ingestion)

        # 2) Upsert Documents + chunk text units.
        all_chunks: List[TextChunk] = []
        chunk_to_doc_id: Dict[str, str] = {}
        for doc in expanded_docs:
            doc_id = doc["id"]
            doc_title = doc.get("title", "Untitled")
            logger.info(f"Upserting document: id={doc_id}, title='{doc_title}', has_di={bool(doc.get('di_extracted_docs'))}")
            
            # Extract document date from content (for corpus-level date queries)
            # Collect all text content for date extraction
            doc_content_for_date = ""
            di_docs = doc.get("di_extracted_docs") or []
            if di_docs:
                # DI-extracted content: concatenate all DI unit texts
                doc_content_for_date = " ".join(str(d.text) for d in di_docs if hasattr(d, 'text'))
            else:
                # Direct content
                doc_content_for_date = doc.get("content") or doc.get("text") or ""
            
            # Extract the latest date from document content
            document_date = extract_document_date(doc_content_for_date) if doc_content_for_date else None
            if document_date:
                logger.info(f"Extracted document date: doc_id={doc_id}, date={document_date}")
            
            self.neo4j_store.upsert_document(
                group_id,
                Document(
                    id=doc_id,
                    title=doc_title,
                    source=doc.get("source", ""),
                    metadata=doc.get("metadata", {}) or {},
                    document_date=document_date,
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

        # 4.5) Build Section graph from chunk metadata.
        section_stats = await self._build_section_graph(group_id, all_chunks, chunk_to_doc_id)
        stats["sections"] = section_stats.get("sections_created", 0)
        stats["section_edges"] = section_stats.get("in_section_edges", 0)
        
        # 4.6) Embed Section nodes (required for semantic similarity edges).
        section_embed_stats = await self._embed_section_nodes(group_id)
        stats["sections_embedded"] = section_embed_stats.get("sections_embedded", 0)
        
        # 4.7) Build SEMANTICALLY_SIMILAR edges between Sections (HippoRAG 2 improvement).
        similarity_stats = await self._build_section_similarity_edges(group_id)
        stats["semantic_similarity_edges"] = similarity_stats.get("edges_created", 0)

        # 4.8) Embed KeyValue keys for semantic matching.
        kvp_embed_stats = await self._embed_keyvalue_keys(group_id)
        stats["key_values"] = kvp_embed_stats.get("kvps_total", 0)
        stats["key_values_embedded"] = kvp_embed_stats.get("keys_embedded", 0)

        # 4.9) Process DI metadata: extract barcodes, figures, languages → graph entities/edges.
        # This leverages Azure DI FREE add-ons that are already extracted but not yet in the graph.
        # Note: DI metadata is stored in di_extracted_docs (LlamaIndex Documents), not in TextChunks.
        di_metadata_stats = await self._process_di_metadata_to_graph(
            group_id=group_id,
            expanded_docs=expanded_docs,
            chunk_to_doc_id=chunk_to_doc_id,
        )
        stats["di_barcodes"] = di_metadata_stats.get("barcodes_created", 0)
        stats["di_figures"] = di_metadata_stats.get("figures_created", 0)
        stats["di_figure_refs"] = di_metadata_stats.get("figure_ref_edges", 0)
        stats["di_languages"] = di_metadata_stats.get("languages_updated", 0)

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
            logger.info(f"entity_extraction_complete: {len(entities)} entities, {len(relationships)} relationships")

        # 6) Entity deduplication (optional; only if we have enough entities).
        if entities:
            entities, relationships, dedup_stats = self._deduplicate_entities(
                group_id=group_id,
                entities=entities,
                relationships=relationships,
            )
            stats["deduplication"] = dedup_stats

        # 7) Validate and (conditionally) persist entities + relationships.
        commit_result = await self._validate_and_commit_entities(
            group_id=group_id,
            entities=entities,
            relationships=relationships,
            dry_run=dry_run,
        )
        stats["validation_passed"] = commit_result.get("passed", False)
        stats["validation_details"] = commit_result.get("details", {})
        if not commit_result.get("passed", False) and not dry_run:
            stats["skipped"].append("entity_validation_failed")
            stats["elapsed_s"] = round(time.time() - start_time, 2)
            return stats

        stats["entities"] = len(entities)
        stats["relationships"] = len(relationships)
        stats["foundation_edges"] = commit_result.get("details", {}).get("foundation_edges", {})
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
            meta = doc.get("metadata") or {}
            meta = meta if isinstance(meta, dict) else {}

            content = doc.get("content") or doc.get("text") or ""
            source = (
                doc.get("source")
                or doc.get("url")
                or meta.get("source")
                or meta.get("url")
                or meta.get("file_name")
                or meta.get("file_path")
                or ""
            )
            title = (
                doc.get("title")
                or meta.get("title")
                or meta.get("file_name")
                or (source.split("/")[-1] if source else "")
                or "Untitled"
            )
            if isinstance(title, str) and title.lower().endswith(".pdf"):
                title = title[:-4]

            # If content is itself a URL, treat it as source.
            if isinstance(content, str) and content.strip().startswith(("http://", "https://")):
                source = content.strip()
                content = ""

            doc_id = doc.get("id") or f"doc_{uuid.uuid4().hex}"
            
            logger.info(f"Document normalization: id={doc_id}, title='{title}', source={source[:50] if source else 'None'}")
            
            normalized.append(
                {
                    "id": doc_id,
                    "title": title,
                    "source": source,
                    "content": content,
                    "metadata": meta,
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
        """Chunk a document into TextChunks using section-aware chunking."""
        di_units: Sequence[LlamaDocument] = document.get("di_extracted_docs") or []
        if di_units:
            return await self._chunk_di_units_section_aware(di_units=di_units, doc_id=doc_id)

        # Fallback for non-DI documents
        content = (document.get("content") or document.get("text") or "").strip()
        if not content:
            return []

        src = document.get("source", "")
        title = document.get("title", "Untitled")
        llama_doc = LlamaDocument(text=content, id_=doc_id, metadata={"source": src, "title": title})
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
                    metadata={"source": src, "title": title, "key_value_pairs": [], "kvp_count": 0},
                )
            )
        return chunks

    async def _chunk_di_units_section_aware(self, *, di_units: Sequence[LlamaDocument], doc_id: str) -> List[TextChunk]:
        """Chunk DI units using section-aware strategy."""
        from app.hybrid_v2.indexing.section_chunking.integration import chunk_di_units_section_aware

        doc_source = ""
        doc_title = ""
        if di_units:
            first_meta = getattr(di_units[0], "metadata", None) or {}
            doc_source = first_meta.get("url", "") or first_meta.get("source", "") or ""
            doc_title = first_meta.get("title", "") or ""

        return await chunk_di_units_section_aware(
            di_units=di_units,
            doc_id=doc_id,
            doc_source=doc_source,
            doc_title=doc_title,
        )

    async def _embed_chunks_best_effort(self, chunks: List[TextChunk]) -> None:
        if self.embedder is None:
            logger.error(
                f"❌ CRITICAL: Embedder is None - vector search will not work!",
                extra={"chunks": len(chunks), "embedder_configured": self.embedder is not None}
            )
            raise RuntimeError(
                f"Embedder not configured - cannot generate embeddings for {len(chunks)} chunks. "
                "Check LLMService initialization and AZURE_OPENAI_EMBEDDING_DEPLOYMENT settings."
            )

        texts = [c.text for c in chunks]
        try:
            logger.info(f"Calling embedder.aget_text_embedding_batch with {len(texts)} texts...")
            embeddings = await self.embedder.aget_text_embedding_batch(texts)
            # Determine which property to use based on V2 flag
            property_name = "embedding_v2" if self.use_v2_embedding_property else "embedding"
            logger.info(f"✅ Embeddings generated: {len(embeddings)} embeddings received (storing in {property_name})", extra={
                "chunks": len(chunks), 
                "embeddings": len(embeddings),
                "first_embedding_length": len(embeddings[0]) if embeddings and len(embeddings) > 0 else 0,
                "use_v2": self.use_v2_embedding_property,
            })
        except Exception as e:
            logger.error(f"❌ EMBEDDING FAILED: {e}", exc_info=True, extra={"error": str(e), "chunks": len(chunks)})
            # Don't silently fail - this is critical for vector search
            raise RuntimeError(f"Embedding generation failed: {e}") from e

        success_count = 0
        null_count = 0
        wrong_dim_count = 0
        for chunk, emb in zip(chunks, embeddings):
            try:
                if emb and isinstance(emb, list) and len(emb) == self.config.embedding_dimensions:
                    # V2: Store in embedding_v2 property if flag is set
                    if self.use_v2_embedding_property:
                        chunk.embedding_v2 = emb
                    else:
                        chunk.embedding = emb
                    success_count += 1
                elif emb and isinstance(emb, list):
                    # Wrong dimensions but still store
                    if self.use_v2_embedding_property:
                        chunk.embedding_v2 = emb
                    else:
                        chunk.embedding = emb
                    success_count += 1
                    wrong_dim_count += 1
                    logger.warning(f"Embedding dimension mismatch: got {len(emb)}, expected {self.config.embedding_dimensions}")
                else:
                    null_count += 1
                    logger.warning(f"Null or invalid embedding received for chunk: emb type={type(emb)}, is_list={isinstance(emb, list)}")
            except Exception as e:
                logger.warning(f"lazy_index_chunk_embedding_assign_failed", extra={"error": str(e)})
                null_count += 1
                continue
        
        logger.info(f"✅ Embeddings assigned: {success_count} success, {null_count} null, {wrong_dim_count} wrong dimensions", extra={
            "success": success_count, 
            "total": len(chunks),
            "null": null_count,
            "wrong_dim": wrong_dim_count,
            "property": "embedding_v2" if self.use_v2_embedding_property else "embedding",
        })

    async def _extract_entities_and_relationships(
        self,
        *,
        group_id: str,
        chunks: List[TextChunk],
    ) -> Tuple[List[Entity], List[Relationship]]:
        # Use LlamaIndex extractor to produce KG nodes/relations per chunk.
        if self.llm is None:
            return [], []

        # Phase 2: Use native neo4j-graphrag extractor (DEFAULT)
        # Fallback to LlamaIndex only if native unavailable or explicitly disabled
        if self.config.use_native_extractor and NATIVE_EXTRACTOR_AVAILABLE:
            entities, relationships = await self._extract_with_native_extractor(group_id, chunks)
            # If native extractor produced too few entities or no relationships, run fallback
            if len(entities) < self.config.min_entities or len(relationships) < self.config.min_mentions:
                logger.warning("native extractor produced insufficient entities/relationships; running fallback LlamaIndex extractor")
                llm_entities, llm_relationships = await self._extract_with_llamaindex_extractor(chunks)
                entities, relationships = self._merge_entity_relationships(entities, relationships, llm_entities, llm_relationships)
                # If still insufficient, run a lightweight NLP seeding pass
                if len(entities) < self.config.min_entities:
                    seeded = self._nlp_seed_entities(group_id, chunks)
                    entities.extend(seeded)
            return entities, relationships

        # Fallback: Use LlamaIndex SchemaLLMPathExtractor (if native disabled)
        logger.warning(f"Using LlamaIndex fallback extractor (use_native_extractor={self.config.use_native_extractor}, available={NATIVE_EXTRACTOR_AVAILABLE})")
        extractor = SchemaLLMPathExtractor(
            llm=cast(Any, self.llm),
            possible_entities=None,
            possible_relations=None,
            strict=False,
            num_workers=4,  # Parallel processing: 4 workers (was 1)
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
        logger.info(f"extractor_complete: {len(extracted_nodes)} nodes extracted")

        # Collect entities/relations and link to originating chunk via text_unit_ids.
        entities_by_key: Dict[str, Entity] = {}
        rel_keys: set[tuple[str, str, str]] = set()
        relationships: List[Relationship] = []

        for n in extracted_nodes:
            chunk_id = getattr(n, "id_", None) or getattr(n, "id", None) or ""
            meta = getattr(n, "metadata", {}) or {}
            # LlamaIndex SchemaLLMPathExtractor uses 'nodes' and 'relations' (not 'kg_nodes'/'kg_relations')
            kg_nodes = meta.get("nodes") or meta.get("kg_nodes") or []
            kg_rels = meta.get("relations") or meta.get("kg_relations") or []

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

    async def _extract_with_native_extractor(
        self,
        group_id: str,
        chunks: List[TextChunk],
    ) -> Tuple[List[Entity], List[Relationship]]:
        """
        Phase 2: Extract entities/relationships using neo4j-graphrag LLMEntityRelationExtractor.
        
        This provides an alternative to SchemaLLMPathExtractor using the official
        neo4j-graphrag package, potentially providing better extraction quality
        and tighter Neo4j integration.
        """
        from app.core.config import settings
        
        logger.info(f"Using native LLMEntityRelationExtractor for {len(chunks)} chunks")
        
        # Create neo4j-graphrag LLM (separate from LlamaIndex LLM)
        # Support managed identity when no API key is present
        llm_kwargs = {
            "model_name": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
            "api_version": settings.AZURE_OPENAI_API_VERSION or "2024-02-01",
        }
        
        if settings.AZURE_OPENAI_API_KEY:
            llm_kwargs["api_key"] = settings.AZURE_OPENAI_API_KEY
        else:
            # Use managed identity via DefaultAzureCredential
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            logger.info("Using DefaultAzureCredential for neo4j-graphrag LLM")
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential,
                "https://cognitiveservices.azure.com/.default"
            )
            llm_kwargs["azure_ad_token_provider"] = token_provider
        
        native_llm = AzureOpenAILLM(**llm_kwargs)
        
        # Create native extractor
        extractor = LLMEntityRelationExtractor(
            llm=native_llm,
            # IMPORTANT: enable lexical graph so we can recover chunk↔entity mention links.
            # We do NOT persist chunk nodes from the extractor; we only use the returned
            # relationships to populate Entity.text_unit_ids for downstream MENTIONS edges.
            create_lexical_graph=True,
            max_concurrency=4,  # Parallel processing: 4 chunks at a time (was 1)
        )
        
        # Define schema with aliases property for improved entity lookup
        # This enables matching "Fabrikam Inc." to "Fabrikam Construction" via aliases
        entity_schema = self._build_extraction_schema()
        
        # Convert to neo4j-graphrag TextChunks
        # Include document context in metadata to help extractor understand provenance
        native_chunks = []
        for c in chunks:
            chunk_meta = {
                "chunk_id": c.id,
                "document_id": c.document_id,
            }
            # Add document-level context if available in chunk metadata
            if c.metadata:
                if "source" in c.metadata:
                    chunk_meta["document_source"] = c.metadata["source"]
                if "title" in c.metadata:
                    chunk_meta["document_title"] = c.metadata["title"]
                if "section_path" in c.metadata:
                    chunk_meta["section_path"] = c.metadata["section_path"]
            
            native_chunks.append(NativeTextChunk(
                text=c.text,
                index=c.chunk_index,
                metadata=chunk_meta,
                uid=c.id,
            ))
        text_chunks = TextChunks(chunks=native_chunks)
        
        # Few-shot examples demonstrating alias extraction
        # This is critical: the LLM follows examples more than schema definitions
        extraction_examples = '''
Example 1:
Text: "Fabrikam Construction Inc. signed a contract with Contoso Lifts LLC for elevator maintenance."
Output:
{"nodes": [
  {"id": "0", "label": "ORGANIZATION", "properties": {"name": "Fabrikam Construction Inc.", "aliases": ["Fabrikam", "Fabrikam Inc.", "Fabrikam Construction"], "description": "Construction company"}},
  {"id": "1", "label": "ORGANIZATION", "properties": {"name": "Contoso Lifts LLC", "aliases": ["Contoso", "Contoso Lifts", "Contoso Ltd."], "description": "Elevator maintenance company"}}
], "relationships": [
  {"type": "PARTY_TO", "start_node_id": "0", "end_node_id": "1", "properties": {"context": "contract for elevator maintenance"}}
]}

Example 2:
Text: "The Property Management Agreement between ABC Realty Corp and 123 Main Street LLC covers maintenance services."
Output:
{"nodes": [
  {"id": "0", "label": "DOCUMENT", "properties": {"name": "Property Management Agreement", "aliases": ["PMA", "the Agreement", "management agreement"], "description": "Agreement for property management services"}},
  {"id": "1", "label": "ORGANIZATION", "properties": {"name": "ABC Realty Corp", "aliases": ["ABC Realty", "ABC"], "description": "Real estate company"}},
  {"id": "2", "label": "ORGANIZATION", "properties": {"name": "123 Main Street LLC", "aliases": ["123 Main Street", "Main Street LLC"], "description": "Property owner"}}
], "relationships": [
  {"type": "PARTY_TO", "start_node_id": "1", "end_node_id": "0", "properties": {}},
  {"type": "PARTY_TO", "start_node_id": "2", "end_node_id": "0", "properties": {}}
]}
'''
        
        # Run extraction with schema AND examples for alias extraction
        graph = await extractor.run(
            chunks=text_chunks, 
            schema=entity_schema,
            examples=extraction_examples,
        )
        
        logger.info(f"Native extractor produced {len(graph.nodes)} nodes, {len(graph.relationships)} relationships")
        
        # Convert to our Entity/Relationship format.
        # Also recover chunk↔entity mention links and store them into Entity.text_unit_ids.
        chunk_ids: set[str] = {str(c.id) for c in chunks if c.id}
        entity_id_map: Dict[str, str] = {}  # native_node_id -> stable entity id
        entities_by_id: Dict[str, Entity] = {}

        def _normalize_labels(n: Any) -> List[str]:
            labels = getattr(n, "labels", None)
            if labels:
                return [str(x) for x in labels if x]
            label = getattr(n, "label", None)
            return [str(label)] if label else []

        for node in graph.nodes:
            node_labels = _normalize_labels(node)
            # Skip chunk/text-chunk nodes; we already persist our own TextChunk nodes.
            if not node_labels or any(l in ("Chunk", "TextChunk") for l in node_labels):
                continue

            props = getattr(node, "properties", None) or {}
            if not isinstance(props, dict):
                props = {}

            name = (props.get("name") or getattr(node, "name", "") or "").strip()
            native_id = str(getattr(node, "id", None) or getattr(node, "node_id", None) or "").strip()
            if not name:
                # Fall back to native id if name missing.
                name = native_id
            if not name:
                continue

            key = self._canonical_entity_key(name)
            if not key:
                continue

            ent_id = self._stable_entity_id(group_id, key)
            if native_id:
                entity_id_map[native_id] = ent_id

            if ent_id not in entities_by_id:
                # Extract aliases from LLM extraction (may be list or string)
                raw_aliases = props.get("aliases", [])
                if isinstance(raw_aliases, str):
                    # Handle comma-separated string format
                    aliases_list = [a.strip() for a in raw_aliases.split(",") if a.strip()]
                elif isinstance(raw_aliases, list):
                    aliases_list = [str(a).strip() for a in raw_aliases if a]
                else:
                    aliases_list = []
                
                entities_by_id[ent_id] = Entity(
                    id=ent_id,
                    name=name,
                    type=node_labels[0] if node_labels else "CONCEPT",
                    description=str(props.get("description", "") or ""),
                    embedding=None,
                    metadata=props,
                    text_unit_ids=[],
                    aliases=aliases_list,
                )

        # Recover mentions from lexical graph relationships: (chunk) -[...]→ (entity)
        # We do not assume a specific relationship type name; we just detect chunk↔entity endpoints.
        mentions_total = 0
        for rel in graph.relationships:
            start_id = str(getattr(rel, "start_node_id", "") or "")
            end_id = str(getattr(rel, "end_node_id", "") or "")
            if not start_id or not end_id:
                continue

            # chunk -> entity
            if start_id in chunk_ids and end_id in entity_id_map:
                ent_id = entity_id_map[end_id]
                ent = entities_by_id.get(ent_id)
                if ent is not None and start_id not in ent.text_unit_ids:
                    ent.text_unit_ids.append(start_id)
                    mentions_total += 1
                continue

            # entity -> chunk
            if end_id in chunk_ids and start_id in entity_id_map:
                ent_id = entity_id_map[start_id]
                ent = entities_by_id.get(ent_id)
                if ent is not None and end_id not in ent.text_unit_ids:
                    ent.text_unit_ids.append(end_id)
                    mentions_total += 1

        entities = list(entities_by_id.values())
        if mentions_total == 0:
            logger.warning(
                "native_extractor_no_mentions_recovered",
                extra={"group_id": group_id, "chunks": len(chunks), "entities": len(entities)},
            )
        
        # Convert relationships (entity↔entity only; chunk endpoints are ignored).
        relationships: List[Relationship] = []
        for rel in graph.relationships:
            source_id = entity_id_map.get(str(getattr(rel, "start_node_id", "") or ""))
            target_id = entity_id_map.get(str(getattr(rel, "end_node_id", "") or ""))
            
            if not source_id or not target_id:
                continue
            
            relationships.append(Relationship(
                source_id=source_id,
                target_id=target_id,
                type=rel.type or "RELATED_TO",
                description=rel.type or "RELATED_TO",
                weight=1.0,
            ))
        
        # Embeddings for entities (best-effort)
        if entities and self.embedder is not None:
            texts = [f"{e.name}: {e.description}" if e.description else e.name for e in entities]
            try:
                embs = await self.embedder.aget_text_embedding_batch(texts)
                for ent, emb in zip(entities, embs):
                    ent.embedding = emb
            except Exception as e:
                logger.warning("native_extractor_entity_embedding_failed", extra={"error": str(e)})
        
        logger.info(f"Native extraction complete: {len(entities)} entities, {len(relationships)} relationships")
        return entities, relationships

    async def _extract_with_llamaindex_extractor(self, chunks: List[TextChunk]) -> Tuple[List[Entity], List[Relationship]]:
        """Fallback extractor using LlamaIndex SchemaLLMPathExtractor."""
        logger.warning("Using LlamaIndex fallback extractor")
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
        logger.info(f"llamaindex_extractor_complete: {len(extracted_nodes)} nodes extracted")

        entities_by_key: Dict[str, Entity] = {}
        rel_keys: set[tuple[str, str, str]] = set()
        relationships: List[Relationship] = []

        for n in extracted_nodes:
            chunk_id = getattr(n, "id_", None) or getattr(n, "id", None) or ""
            meta = getattr(n, "metadata", {}) or {}
            kg_nodes = meta.get("nodes") or meta.get("kg_nodes") or []
            kg_rels = meta.get("relations") or meta.get("kg_relations") or []

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
                    ent_id = self._stable_entity_id("fallback", key)
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

                sid = self._stable_entity_id("fallback", skey)
                tid = self._stable_entity_id("fallback", okey)

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

        entities = list(entities_by_key.values())
        # Note: embedding assignment skipped for fallback to keep it lightweight
        return entities, relationships

    def _nlp_seed_entities(self, group_id: str, chunks: List[TextChunk]) -> List[Entity]:
        """Lightweight NER seeding from chunk text (heuristic)."""
        candidates = {}
        import re
        pattern = re.compile(r"([A-Z][a-z]{1,}\s(?:[A-Z][a-z]{1,}\s?){0,3})")
        for c in chunks:
            for m in pattern.findall(c.text or ""):
                name = m.strip()
                key = self._canonical_entity_key(name)
                if not key or key in candidates:
                    continue
                ent_id = self._stable_entity_id(group_id, key)
                candidates[key] = Entity(
                    id=ent_id,
                    name=name,
                    type="CONCEPT",
                    description="",
                    embedding=None,
                    metadata={},
                    text_unit_ids=[c.id],
                )
        return list(candidates.values())

    async def _validate_and_commit_entities(
        self,
        *,
        group_id: str,
        entities: List[Entity],
        relationships: List[Relationship],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Validate entity graph and commit if thresholds are met. In dry-run mode, only return diagnostics."""
        details: Dict[str, Any] = {
            "entities_found": len(entities),
            "relationships_found": len(relationships),
        }
        passed = True
        if len(entities) < self.config.min_entities or len(relationships) < self.config.min_mentions:
            passed = False
            details["reason"] = "insufficient_entities_or_relationships"
        # Dry-run: return diagnostics only.
        if dry_run or not passed:
            return {"passed": passed, "details": details, "stats": {}}
        # Commit to DB
        if entities:
            await self.neo4j_store.aupsert_entities_batch(group_id, entities)
            details["entities_committed"] = len(entities)
        if relationships:
            self.neo4j_store.upsert_relationships_batch(group_id, relationships)
            details["relationships_committed"] = len(relationships)

        # Best-effort: compute ranking fields so query-time Cypher can use them
        # without property-key warnings (importance_score/degree/chunk_count).
        self.neo4j_store.compute_entity_importance(group_id)
        
        # Create foundation edges for graph schema enhancement (Phase 1 Week 1-2)
        # These edges enable O(1) retrieval and provide LazyGraphRAG→HippoRAG bridge
        foundation_stats = await self._create_foundation_edges(group_id)
        details["foundation_edges"] = foundation_stats
        
        # Create connectivity edges (Phase 2 Week 3-4)
        # SHARES_ENTITY edges connect sections that discuss the same entities across documents
        connectivity_stats = await self._create_connectivity_edges(group_id)
        details["connectivity_edges"] = connectivity_stats
        
        # Create semantic enhancement edges (Phase 3 Week 5-6)
        # SIMILAR_TO edges connect semantically similar entities via embeddings
        semantic_stats = await self._create_semantic_edges(group_id)
        details["semantic_edges"] = semantic_stats
        
        return {"passed": True, "details": details, "stats": {"entities": len(entities), "relationships": len(relationships)}}

    def _merge_entity_relationships(self, ents_a: List[Entity], rels_a: List[Relationship], ents_b: List[Entity], rels_b: List[Relationship]) -> Tuple[List[Entity], List[Relationship]]:
        """Merge two entity/relationship lists deduplicating by canonical key."""
        by_key: Dict[str, Entity] = {}
        for e in ents_a + ents_b:
            key = self._canonical_entity_key(e.name)
            if key in by_key:
                # merge text_unit_ids
                exist = by_key[key]
                exist.text_unit_ids = sorted(set(exist.text_unit_ids + (e.text_unit_ids or [])))
            else:
                by_key[key] = e
        # dedup relationships by (src,target,desc)
        seen = set()
        out_rels = []
        for r in rels_a + rels_b:
            k = (r.source_id, r.target_id, r.description or r.type or "RELATED_TO")
            if k in seen:
                continue
            seen.add(k)
            out_rels.append(r)
        return list(by_key.values()), out_rels

    async def _process_di_metadata_to_graph(
        self,
        *,
        group_id: str,
        expanded_docs: List[Dict[str, Any]],
        chunk_to_doc_id: Dict[str, str],
    ) -> Dict[str, Any]:
        """Process Azure Document Intelligence metadata and create graph nodes/edges.
        
        This method extracts FREE Azure DI add-on data from the original DI documents
        (LlamaIndex Documents stored in di_extracted_docs) and converts it into proper
        graph entities and relationships:
        
        1. **Barcodes** → :Barcode nodes with FOUND_IN edges to Documents
           - Entity types: PRODUCT_CODE, TRACKING_NUMBER, QR_DATA, URL, BARCODE
           - Enables queries like "find documents with tracking number 1Z..."
        
        2. **Figures** → :Figure nodes with REFERENCES edges to elements + embedding_v2
           - Captures cross-section relationships without LLM extraction
           - Figure captions create searchable content with V2 embeddings
        
        3. **Key-Value Pairs** → :KeyValuePair nodes with FOUND_IN edges + embedding_v2
           - Deterministic field lookups from Azure DI
           - Enables queries like "find documents where 'Invoice Number' = '12345'"
        
        4. **Languages** → Updates Document nodes with detected_languages property
           - Primary language stored as metadata
           - Enables multilingual corpus queries
        
        5. **Selection Marks** → :ChecklistItem nodes (future enhancement)
           - Currently logged for analysis
        
        After creating nodes, embeddings are generated for Figure captions and KVP text
        to enable GDS KNN similarity matching with Entity nodes.
        
        Args:
            group_id: Group identifier for multi-tenancy
            expanded_docs: List of document dicts with di_extracted_docs containing LlamaIndex Documents
            chunk_to_doc_id: Mapping from chunk ID to document ID
            
        Returns:
            Statistics dictionary with counts of created entities/edges
        """
        stats: Dict[str, Any] = {
            "barcodes_created": 0,
            "figures_created": 0,
            "figure_ref_edges": 0,
            "kvps_created": 0,
            "languages_updated": 0,
            "embeddings_generated": 0,
            "knn_edges_created": 0,
            "entity_similarity_edges": 0,
            "communities_detected": 0,
            "pagerank_scored": 0,
        }
        
        # Collect DI metadata from the first DI unit's metadata for each document
        # (DI stores document-level metadata like barcodes, figures, languages in first unit)
        for doc in expanded_docs:
            doc_id = doc.get("id", "")
            di_units = doc.get("di_extracted_docs") or []
            
            if not di_units:
                continue
            
            # Get metadata from first DI unit (document-level metadata)
            first_unit = di_units[0]
            first_meta = getattr(first_unit, "metadata", None) or {}
            
            barcodes = first_meta.get("barcodes") or []
            figures = first_meta.get("figures") or []
            languages = first_meta.get("languages") or []
            selection_marks = first_meta.get("selection_marks") or []
            
            # Collect KVPs from ALL DI units (they're distributed per-section)
            all_kvps: List[Dict[str, Any]] = []
            for di_unit in di_units:
                unit_meta = getattr(di_unit, "metadata", None) or {}
                unit_kvps = unit_meta.get("key_value_pairs") or []
                all_kvps.extend(unit_kvps)
            
            if not any([barcodes, figures, languages, all_kvps]):
                continue
            
            logger.info(
                "processing_di_metadata_for_doc",
                extra={
                    "group_id": group_id,
                    "doc_id": doc_id,
                    "barcodes": len(barcodes),
                    "figures": len(figures),
                    "languages": len(languages),
                    "selection_marks": len(selection_marks),
                    "kvps": len(all_kvps),
                }
            )
            
            with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
                # 1. Create Barcode nodes and FOUND_IN edges
                if barcodes:
                    barcode_data = []
                    for bc in barcodes:
                        bc_id = self._stable_barcode_id(group_id, bc.get("value", ""))
                        barcode_data.append({
                            "id": bc_id,
                            "group_id": group_id,
                            "kind": bc.get("kind", "UNKNOWN"),
                            "value": bc.get("value", ""),
                            "confidence": bc.get("confidence", 0.0),
                            "page_number": bc.get("page_number", 1),
                            "entity_type": bc.get("entity_type", "BARCODE"),
                            "doc_id": doc_id,
                        })
                    
                    result = session.run(
                        """
                        UNWIND $barcodes AS bc
                        MERGE (b:Barcode {id: bc.id})
                        SET b.group_id = bc.group_id,
                            b.kind = bc.kind,
                            b.value = bc.value,
                            b.confidence = bc.confidence,
                            b.page_number = bc.page_number,
                            b.entity_type = bc.entity_type,
                            b.updated_at = datetime()
                        WITH b, bc
                        MATCH (d:Document {id: bc.doc_id, group_id: bc.group_id})
                        MERGE (b)-[:FOUND_IN]->(d)
                        RETURN count(DISTINCT b) AS count
                        """,
                        barcodes=barcode_data,
                    )
                    stats["barcodes_created"] += result.single()["count"]
                    logger.info(f"📊 Created {result.single()['count'] if result else 0} Barcode nodes for {doc_id}")
                
                # 2. Create Figure nodes with captions (cross-references captured via element_refs)
                if figures:
                    figure_data = []
                    for fig in figures:
                        fig_id = self._stable_figure_id(group_id, fig.get("id", ""))
                        figure_data.append({
                            "id": fig_id,
                            "group_id": group_id,
                            "di_id": fig.get("id", ""),
                            "caption": fig.get("caption", ""),
                            "footnotes": fig.get("footnotes", []),
                            "element_count": fig.get("element_count", 0),
                            "doc_id": doc_id,
                        })
                    
                    result = session.run(
                        """
                        UNWIND $figures AS fig
                        MERGE (f:Figure {id: fig.id})
                        SET f.group_id = fig.group_id,
                            f.di_id = fig.di_id,
                            f.caption = fig.caption,
                            f.footnotes = fig.footnotes,
                            f.element_count = fig.element_count,
                            f.updated_at = datetime()
                        WITH f, fig
                        MATCH (d:Document {id: fig.doc_id, group_id: fig.group_id})
                        MERGE (f)-[:FOUND_IN]->(d)
                        RETURN count(DISTINCT f) AS count
                        """,
                        figures=figure_data,
                    )
                    count = result.single()["count"]
                    stats["figures_created"] += count
                    
                    # Create REFERENCES edges from figures to elements (cross-section graph edges!)
                    ref_edges = []
                    for fig in figures:
                        fig_id = self._stable_figure_id(group_id, fig.get("id", ""))
                        for ref in fig.get("element_refs", []):
                            # refs are like {"kind": "paragraphs", "index": 42, "ref": "/paragraphs/42"}
                            ref_edges.append({
                                "figure_id": fig_id,
                                "ref_kind": ref.get("kind", ""),
                                "ref_index": ref.get("index", -1),
                                "ref_path": ref.get("ref", ""),
                            })
                    
                    if ref_edges:
                        # Store reference metadata on the Figure node for later retrieval
                        session.run(
                            """
                            UNWIND $refs AS r
                            MATCH (f:Figure {id: r.figure_id})
                            SET f.element_refs = coalesce(f.element_refs, []) + [r.ref_path]
                            """,
                            refs=ref_edges,
                        )
                        stats["figure_ref_edges"] += len(ref_edges)
                    
                    logger.info(f"📈 Created {count} Figure nodes with {len(ref_edges)} element references for {doc_id}")
                
                # 3. Update Document nodes with detected languages
                if languages:
                    # Find primary language (most spans)
                    primary_lang = max(languages, key=lambda x: x.get("span_count", 0))
                    all_locales = [lang.get("locale", "") for lang in languages if lang.get("locale")]
                    
                    result = session.run(
                        """
                        MATCH (d:Document {id: $doc_id, group_id: $group_id})
                        SET d.primary_language = $primary_lang,
                            d.detected_languages = $all_langs,
                            d.language_updated_at = datetime()
                        RETURN count(d) AS count
                        """,
                        doc_id=doc_id,
                        group_id=group_id,
                        primary_lang=primary_lang.get("locale", ""),
                        all_langs=all_locales,
                    )
                    stats["languages_updated"] += result.single()["count"]
                    logger.info(f"🌐 Updated language metadata for {doc_id}: primary={primary_lang.get('locale')}, all={all_locales}")
                
                # 4. Log selection marks for future enhancement
                if selection_marks:
                    selected = sum(1 for m in selection_marks if m.get("state") == "selected")
                    logger.info(
                        f"☑️ Selection marks detected in {doc_id}: {len(selection_marks)} total, {selected} selected",
                        extra={"doc_id": doc_id, "total": len(selection_marks), "selected": selected}
                    )
                
                # 5. Create KeyValuePair nodes with FOUND_IN edges
                if all_kvps:
                    kvp_data = []
                    for kvp in all_kvps:
                        key_text = kvp.get("key", "")
                        value_text = kvp.get("value", "")
                        if not key_text:
                            continue
                        kvp_id = self._stable_kvp_id(group_id, doc_id, key_text, value_text)
                        kvp_data.append({
                            "id": kvp_id,
                            "group_id": group_id,
                            "key": key_text,
                            "value": value_text,
                            "confidence": kvp.get("confidence", 0.0),
                            "page_number": kvp.get("page_number", 1),
                            "section_id": kvp.get("section_id", ""),
                            "section_path": kvp.get("section_path", []),
                            "searchable_text": f"{key_text}: {value_text}",  # For embedding
                            "doc_id": doc_id,
                        })
                    
                    if kvp_data:
                        result = session.run(
                            """
                            UNWIND $kvps AS kvp
                            MERGE (k:KeyValuePair {id: kvp.id})
                            SET k.group_id = kvp.group_id,
                                k.key = kvp.key,
                                k.value = kvp.value,
                                k.confidence = kvp.confidence,
                                k.page_number = kvp.page_number,
                                k.section_id = kvp.section_id,
                                k.section_path = kvp.section_path,
                                k.searchable_text = kvp.searchable_text,
                                k.updated_at = datetime()
                            WITH k, kvp
                            MATCH (d:Document {id: kvp.doc_id, group_id: kvp.group_id})
                            MERGE (k)-[:FOUND_IN]->(d)
                            RETURN count(DISTINCT k) AS count
                            """,
                            kvps=kvp_data,
                        )
                        count = result.single()["count"]
                        stats["kvps_created"] += count
                        logger.info(f"🔑 Created {count} KeyValuePair nodes for {doc_id}")
        
        # 6. Generate embeddings for Figure captions and KVP searchable text
        # Then use GDS KNN to create SIMILAR_TO edges with Entity nodes
        embedding_stats = await self._generate_di_node_embeddings_and_knn(group_id=group_id)
        stats["embeddings_generated"] = embedding_stats.get("embeddings_created", 0)
        stats["knn_edges_created"] = embedding_stats.get("knn_edges_created", 0)
        
        logger.info(
            "di_metadata_processing_complete",
            extra={
                "group_id": group_id,
                **stats,
            }
        )
        
        return stats

    def _stable_barcode_id(self, group_id: str, value: str) -> str:
        """Generate stable ID for barcode entity."""
        key = f"barcode:{group_id}:{value}"
        return f"barcode_{hashlib.md5(key.encode()).hexdigest()[:16]}"

    def _stable_figure_id(self, group_id: str, fig_id: str) -> str:
        """Generate stable ID for figure entity."""
        key = f"figure:{group_id}:{fig_id}"
        return f"figure_{hashlib.md5(key.encode()).hexdigest()[:16]}"

    def _stable_kvp_id(self, group_id: str, doc_id: str, key: str, value: str) -> str:
        """Generate stable ID for key-value pair entity."""
        # Include doc_id to allow same key in different documents
        composite_key = f"kvp:{group_id}:{doc_id}:{key}:{value}"
        return f"kvp_{hashlib.md5(composite_key.encode()).hexdigest()[:16]}"

    async def _generate_di_node_embeddings_and_knn(
        self,
        *,
        group_id: str,
    ) -> Dict[str, Any]:
        """Generate V2 embeddings for Figure/KVP nodes and create SIMILAR_TO edges via GDS KNN.
        
        This method:
        1. Finds Figure nodes with captions but no embeddings
        2. Finds KeyValuePair nodes with searchable_text but no embeddings
        3. Generates V2 (Voyage voyage-3) embeddings for these nodes
        4. Uses GDS KNN algorithm to find similar Entity nodes
        5. Creates SIMILAR_TO edges between DI nodes and Entities
        
        Args:
            group_id: Group identifier for multi-tenancy
            
        Returns:
            Statistics dictionary with embedding and edge counts
        """
        stats = {
            "embeddings_created": 0,
            "knn_edges_created": 0,
            "figures_processed": 0,
            "kvps_processed": 0,
        }
        
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            # 1. Get Figure nodes needing embeddings (have caption, no embedding_v2)
            figure_result = session.run(
                """
                MATCH (f:Figure {group_id: $group_id})
                WHERE f.caption IS NOT NULL AND f.caption <> '' AND f.embedding_v2 IS NULL
                RETURN f.id AS id, f.caption AS text
                LIMIT 500
                """,
                group_id=group_id,
            )
            figures_to_embed = [{"id": r["id"], "text": r["text"]} for r in figure_result]
            
            # 2. Get KVP nodes needing embeddings
            kvp_result = session.run(
                """
                MATCH (k:KeyValuePair {group_id: $group_id})
                WHERE k.searchable_text IS NOT NULL AND k.embedding_v2 IS NULL
                RETURN k.id AS id, k.searchable_text AS text
                LIMIT 500
                """,
                group_id=group_id,
            )
            kvps_to_embed = [{"id": r["id"], "text": r["text"]} for r in kvp_result]
        
        # 3. Generate embeddings for all nodes
        all_nodes = figures_to_embed + kvps_to_embed
        if not all_nodes:
            logger.info("No DI nodes need embeddings")
            return stats
        
        logger.info(f"🔢 Generating embeddings for {len(figures_to_embed)} Figures and {len(kvps_to_embed)} KVPs")
        
        texts = [n["text"] for n in all_nodes]
        try:
            embeddings = await self.embedding_service.embed_batch(texts)
        except Exception as e:
            logger.error(f"Failed to generate DI node embeddings: {e}")
            return stats
        
        # 4. Update nodes with embeddings
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            # Update Figure embeddings
            for i, fig in enumerate(figures_to_embed):
                if i < len(embeddings) and embeddings[i]:
                    session.run(
                        """
                        MATCH (f:Figure {id: $id})
                        SET f.embedding_v2 = $embedding
                        """,
                        id=fig["id"],
                        embedding=embeddings[i],
                    )
                    stats["embeddings_created"] += 1
                    stats["figures_processed"] += 1
            
            # Update KVP embeddings
            kvp_start_idx = len(figures_to_embed)
            for i, kvp in enumerate(kvps_to_embed):
                emb_idx = kvp_start_idx + i
                if emb_idx < len(embeddings) and embeddings[emb_idx]:
                    session.run(
                        """
                        MATCH (k:KeyValuePair {id: $id})
                        SET k.embedding_v2 = $embedding
                        """,
                        id=kvp["id"],
                        embedding=embeddings[emb_idx],
                    )
                    stats["embeddings_created"] += 1
                    stats["kvps_processed"] += 1
        
        logger.info(f"✅ Generated {stats['embeddings_created']} embeddings")
        
        # 5. Run GDS algorithms: KNN for similarity, Louvain for communities, PageRank for importance
        gds_stats = await self._run_gds_graph_algorithms(group_id=group_id)
        stats["knn_edges_created"] = gds_stats.get("knn_edges", 0)
        stats["entity_similarity_edges"] = gds_stats.get("entity_edges", 0)
        stats["communities_detected"] = gds_stats.get("communities", 0)
        stats["pagerank_scored"] = gds_stats.get("pagerank_nodes", 0)
        
        return stats

    async def _run_gds_graph_algorithms(
        self,
        *,
        group_id: str,
        knn_top_k: int = 5,
        knn_similarity_cutoff: float = 0.60,
    ) -> Dict[str, int]:
        """Run GDS algorithms to enhance the graph with computed properties.
        
        Algorithms run:
        1. **KNN** - Creates similarity edges:
           - Figure/KVP → Entity (SIMILAR_TO)
           - Entity ↔ Entity (SEMANTICALLY_SIMILAR)
        2. **Louvain** - Detects communities and assigns community_id to nodes
        3. **PageRank** - Computes importance scores for all nodes
        
        Args:
            group_id: Group identifier for multi-tenancy
            knn_top_k: Number of nearest neighbors for KNN (default: 5)
            knn_similarity_cutoff: Minimum similarity for KNN edges (default: 0.60)
            
        Returns:
            Statistics dictionary with algorithm results
        """
        stats = {"knn_edges": 0, "entity_edges": 0, "communities": 0, "pagerank_nodes": 0}
        projection_name = f"graphrag_{group_id.replace('-', '_')}"
        
        try:
            with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
                # Drop existing projection if exists
                session.run("CALL gds.graph.drop($name, false)", name=projection_name)
                
                # Create comprehensive projection for all algorithms
                # Include Entity, Figure, KeyValuePair, Chunk nodes
                # Exclude :Deprecated nodes from GDS computation
                session.run(
                    """
                    CALL gds.graph.project.cypher(
                        $name,
                        'MATCH (n) WHERE n.group_id = $group_id 
                         AND (n:Entity OR n:Figure OR n:KeyValuePair OR n:Chunk)
                         AND NOT n:Deprecated
                         RETURN id(n) AS id, labels(n) AS labels,
                        'MATCH (n)-[r]->(m) WHERE n.group_id = $group_id AND m.group_id = $group_id
                         AND (n:Entity OR n:Figure OR n:KeyValuePair OR n:Chunk)
                         AND (m:Entity OR m:Figure OR m:KeyValuePair OR m:Chunk)
                         AND NOT n:Deprecated AND NOT m:Deprecated
                         RETURN id(n) AS source, id(m) AS target, type(r) AS type',
                        {parameters: {group_id: $group_id}}
                    )
                    """,
                    name=projection_name,
                    group_id=group_id,
                )
                logger.info(f"📊 Created GDS projection: {projection_name}")
                
                # ============================================
                # 1a. KNN - DI nodes (Figure/KVP) → Entity
                # ============================================
                try:
                    result = session.run(
                        """
                        CALL gds.knn.stream($name, {
                            nodeProperties: ['embedding_v2'],
                            topK: $topK,
                            similarityCutoff: $cutoff,
                            concurrency: 4
                        })
                        YIELD node1, node2, similarity
                        WITH gds.util.asNode(node1) AS n1, gds.util.asNode(node2) AS n2, similarity
                        WHERE (n1:Figure OR n1:KeyValuePair) AND n2:Entity
                        MERGE (n1)-[r:SIMILAR_TO]->(n2)
                        SET r.score = similarity, r.method = 'gds_knn', r.group_id = $group_id, r.created_at = datetime()
                        RETURN count(r) AS edges_created
                        """,
                        name=projection_name,
                        topK=knn_top_k,
                        cutoff=knn_similarity_cutoff,
                    )
                    stats["knn_edges"] = result.single()["edges_created"]
                    logger.info(f"🔗 GDS KNN (DI→Entity): {stats['knn_edges']} SIMILAR_TO edges")
                except Exception as e:
                    logger.warning(f"KNN (DI→Entity) failed: {e}")
                
                # ============================================
                # 1b. KNN - Entity ↔ Entity (semantic similarity)
                # ============================================
                try:
                    result = session.run(
                        """
                        CALL gds.knn.stream($name, {
                            nodeProperties: ['embedding_v2'],
                            topK: $topK,
                            similarityCutoff: $cutoff,
                            concurrency: 4
                        })
                        YIELD node1, node2, similarity
                        WITH gds.util.asNode(node1) AS n1, gds.util.asNode(node2) AS n2, similarity
                        WHERE n1:Entity AND n2:Entity AND id(n1) < id(n2)  // Avoid duplicates
                        MERGE (n1)-[r:SEMANTICALLY_SIMILAR]->(n2)
                        SET r.score = similarity, r.method = 'gds_knn', r.group_id = $group_id, r.created_at = datetime()
                        RETURN count(r) AS edges_created
                        """,
                        name=projection_name,
                        topK=knn_top_k,
                        cutoff=knn_similarity_cutoff,
                    )
                    stats["entity_edges"] = result.single()["edges_created"]
                    logger.info(f"🔗 GDS KNN (Entity↔Entity): {stats['entity_edges']} SEMANTICALLY_SIMILAR edges")
                except Exception as e:
                    logger.warning(f"KNN (Entity↔Entity) failed: {e}")
                
                # ============================================
                # 2. Louvain - Community Detection
                # ============================================
                # Creates community_id property on nodes - essential for GraphRAG community summaries
                try:
                    result = session.run(
                        """
                        CALL gds.louvain.write($name, {
                            writeProperty: 'community_id',
                            includeIntermediateCommunities: false,
                            concurrency: 4
                        })
                        YIELD communityCount, modularity
                        RETURN communityCount, modularity
                        """,
                        name=projection_name,
                    )
                    record = result.single()
                    stats["communities"] = record["communityCount"]
                    modularity = record["modularity"]
                    logger.info(f"🏘️ Louvain: {stats['communities']} communities (modularity: {modularity:.3f})")
                except Exception as e:
                    logger.warning(f"Louvain community detection failed: {e}")
                
                # ============================================
                # 3. PageRank - Node Importance
                # ============================================
                # Computes pagerank score for retrieval ranking
                try:
                    result = session.run(
                        """
                        CALL gds.pageRank.write($name, {
                            writeProperty: 'pagerank',
                            dampingFactor: 0.85,
                            maxIterations: 20,
                            concurrency: 4
                        })
                        YIELD nodePropertiesWritten, ranIterations
                        RETURN nodePropertiesWritten, ranIterations
                        """,
                        name=projection_name,
                    )
                    record = result.single()
                    stats["pagerank_nodes"] = record["nodePropertiesWritten"]
                    logger.info(f"📈 PageRank: scored {stats['pagerank_nodes']} nodes ({record['ranIterations']} iterations)")
                except Exception as e:
                    logger.warning(f"PageRank failed: {e}")
                
                # Clean up projection
                session.run("CALL gds.graph.drop($name, false)", name=projection_name)
                logger.info(f"🧹 Cleaned up GDS projection: {projection_name}")
                
                # Mark GDS as freshly computed for this group
                self.neo4j_store.clear_gds_stale(group_id)
                
        except Exception as e:
            logger.error(f"GDS graph algorithms failed: {e}", extra={"error": str(e)})
        
        return stats

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
            merged_aliases: set[str] = set()  # Merge aliases from all members
            merged_desc = ""
            merged_type = "CONCEPT"
            merged_meta: Dict[str, Any] = {}
            merged_emb = None

            for m in members:
                id_remap[m.id] = canon_id
                merged_text_units.update(m.text_unit_ids or [])
                # Merge aliases from all members
                if hasattr(m, 'aliases') and m.aliases:
                    merged_aliases.update(m.aliases)
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
                aliases=sorted(merged_aliases),  # Include merged aliases
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

    def _build_extraction_schema(self) -> "GraphSchema":
        """
        Build a schema that instructs the LLM to extract aliases alongside entities.
        
        This enables matching user queries like "Fabrikam Inc." to entities stored as
        "Fabrikam Construction" by including common variations in the aliases property.
        """
        # Common entity types with aliases property
        entity_types = [
            NodeType(
                label="ORGANIZATION",
                description="A company, corporation, business entity, or legal organization",
                properties=[
                    PropertyType(name="name", type="STRING", description="Official/legal name as it appears in the document", required=True),
                    PropertyType(name="aliases", type="LIST", description="Common alternative names, abbreviations, short forms, or variations users might use (e.g., 'Fabrikam' for 'Fabrikam Construction Inc.')", required=False),
                    PropertyType(name="description", type="STRING", description="Brief description of the organization", required=False),
                ],
            ),
            NodeType(
                label="PERSON",
                description="A named individual or person",
                properties=[
                    PropertyType(name="name", type="STRING", description="Full name as it appears in the document", required=True),
                    PropertyType(name="aliases", type="LIST", description="Nicknames, maiden names, titles, or common variations", required=False),
                    PropertyType(name="description", type="STRING", description="Role or brief description", required=False),
                ],
            ),
            NodeType(
                label="DOCUMENT",
                description="A legal document, contract, agreement, or formal document",
                properties=[
                    PropertyType(name="name", type="STRING", description="Document title or name", required=True),
                    PropertyType(name="aliases", type="LIST", description="Short names or common references (e.g., 'the contract' for 'Purchase Contract Agreement')", required=False),
                    PropertyType(name="description", type="STRING", description="Brief description of document purpose", required=False),
                ],
            ),
            NodeType(
                label="LOCATION",
                description="A geographic location, address, or place",
                properties=[
                    PropertyType(name="name", type="STRING", description="Location name or address", required=True),
                    PropertyType(name="aliases", type="LIST", description="Abbreviated forms or common references", required=False),
                ],
            ),
            NodeType(
                label="CONCEPT",
                description="An abstract concept, term, clause, or named section",
                properties=[
                    PropertyType(name="name", type="STRING", description="Concept or term name", required=True),
                    PropertyType(name="aliases", type="LIST", description="Alternative phrasings or abbreviations", required=False),
                    PropertyType(name="description", type="STRING", description="Brief explanation", required=False),
                ],
            ),
        ]
        
        # Common relationship types
        relationship_types = [
            RelationshipType(label="RELATED_TO", description="General relationship between entities"),
            RelationshipType(label="PARTY_TO", description="Entity is a party to a document/agreement"),
            RelationshipType(label="LOCATED_IN", description="Entity is located in a place"),
            RelationshipType(label="MENTIONS", description="Document mentions an entity"),
            RelationshipType(label="DEFINES", description="Document defines a term or concept"),
            # Azure DI-extracted relationships (FREE add-ons)
            RelationshipType(label="FOUND_IN", description="Barcode or Figure found in a Document"),
            RelationshipType(label="REFERENCES", description="Figure references another element (paragraph, table, section)"),
        ]
        
        return GraphSchema(node_types=entity_types, relationship_types=relationship_types)

    @staticmethod
    def _canonical_entity_key(name: str, locale: Optional[str] = None) -> str:
        """Generate canonical key for entity matching.
        
        Handles both Latin and CJK scripts appropriately:
        - Latin: Lowercase, strip punctuation, normalize whitespace
        - CJK: Preserve characters, apply NFKC normalization
        
        Args:
            name: Entity name to canonicalize
            locale: Optional language hint (e.g., "zh-Hans", "ja", "ko")
                    If None, auto-detects CJK from text content.
        
        Returns:
            Canonical key for entity matching
        """
        return canonical_key_for_entity(name, locale)

    @staticmethod
    def _stable_entity_id(group_id: str, canonical_key: str) -> str:
        h = hashlib.sha256()
        h.update(group_id.encode("utf-8", errors="ignore"))
        h.update(b"\n")
        h.update(canonical_key.encode("utf-8", errors="ignore"))
        return f"entity_{h.hexdigest()[:12]}"

    @staticmethod
    def _stable_section_id(group_id: str, doc_id: str, path_key: str) -> str:
        """Generate a stable hash-based section ID."""
        h = hashlib.sha256()
        h.update(group_id.encode("utf-8", errors="ignore"))
        h.update(b"\n")
        h.update(doc_id.encode("utf-8", errors="ignore"))
        h.update(b"\n")
        h.update(path_key.encode("utf-8", errors="ignore"))
        return f"section_{h.hexdigest()[:12]}"

    @staticmethod
    def _parse_section_path(metadata: Dict[str, Any]) -> List[str]:
        """Extract section path from chunk metadata.
        
        Handles multiple formats:
        - section_path: List[str] (preferred)
        - di_section_path: str (fallback, may be " > " joined)
        - di_section_part: str (fallback, single section name)
        """
        # Preferred: section_path as list
        section_path = metadata.get("section_path")
        if isinstance(section_path, list) and section_path:
            return [str(s).strip() for s in section_path if str(s).strip()]
        
        # Fallback: di_section_path as string
        di_section_path = metadata.get("di_section_path")
        if isinstance(di_section_path, str) and di_section_path.strip():
            if " > " in di_section_path:
                return [s.strip() for s in di_section_path.split(" > ") if s.strip()]
            return [di_section_path.strip()]
        
        # Fallback: di_section_part as single section
        di_section_part = metadata.get("di_section_part")
        if isinstance(di_section_part, str) and di_section_part.strip():
            return [di_section_part.strip()]
        
        return []

    async def _build_section_graph(
        self,
        group_id: str,
        chunks: List[TextChunk],
        chunk_to_doc_id: Dict[str, str],
    ) -> Dict[str, Any]:
        """Build Section graph from chunk metadata.
        
        Creates:
        - (:Section) nodes with id, group_id, doc_id, path_key, title, depth
        - (:Document)-[:HAS_SECTION]->(:Section) for top-level sections
        - (:Section)-[:SUBSECTION_OF]->(:Section) for hierarchy
        - (:TextChunk)-[:IN_SECTION]->(:Section) for leaf linkage
        """
        DEFAULT_ROOT_SECTION = "[Document Root]"
        
        # Collect all unique sections
        all_sections: Dict[Tuple[str, str], Dict[str, Any]] = {}  # (doc_id, path_key) -> section_info
        chunk_to_leaf_section: Dict[str, str] = {}  # chunk_id -> section_id
        
        for chunk in chunks:
            doc_id = chunk_to_doc_id.get(chunk.id, chunk.document_id or "unknown_doc")
            metadata = chunk.metadata or {}
            section_path = self._parse_section_path(metadata)
            
            if not section_path:
                section_path = [DEFAULT_ROOT_SECTION]
            
            # Build hierarchy
            for depth, title in enumerate(section_path):
                path_key = " > ".join(section_path[: depth + 1])
                parent_path_key = " > ".join(section_path[:depth]) if depth > 0 else None
                
                key = (doc_id, path_key)
                if key not in all_sections:
                    all_sections[key] = {
                        "id": self._stable_section_id(group_id, doc_id, path_key),
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "path_key": path_key,
                        "title": title,
                        "depth": depth,
                        "parent_path_key": parent_path_key,
                    }
            
            # Map chunk to leaf section
            leaf_path_key = " > ".join(section_path)
            leaf_key = (doc_id, leaf_path_key)
            if leaf_key in all_sections:
                chunk_to_leaf_section[chunk.id] = all_sections[leaf_key]["id"]
            else:
                # This should never happen if hierarchy loop works correctly
                # Log to investigate why some chunks aren't mapped
                logger.warning(
                    "chunk_leaf_section_not_found",
                    extra={
                        "chunk_id": chunk.id,
                        "doc_id": doc_id,
                        "leaf_path_key": leaf_path_key,
                        "section_path": section_path,
                        "all_sections_count": len(all_sections)
                    }
                )
        
        logger.info(
            "chunk_to_section_mapping_complete",
            extra={
                "total_chunks": len(chunks),
                "chunks_mapped": len(chunk_to_leaf_section),
                "chunks_unmapped": len(chunks) - len(chunk_to_leaf_section),
                "sections_created": len(all_sections)
            }
        )
        if not all_sections:
            return {"sections_created": 0, "in_section_edges": 0}
        
        # Create Section nodes via Neo4j
        section_data = list(all_sections.values())
        
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            # Create sections
            result = session.run(
                """
                UNWIND $sections AS s
                MERGE (sec:Section {id: s.id})
                SET sec.group_id = s.group_id,
                    sec.doc_id = s.doc_id,
                    sec.path_key = s.path_key,
                    sec.title = s.title,
                    sec.depth = s.depth,
                    sec.updated_at = datetime()
                RETURN count(sec) AS count
                """,
                sections=section_data,
            )
            sections_created = result.single()["count"]
            
            # Create HAS_SECTION edges (Document -> top-level Section)
            top_level = [
                {"doc_id": s["doc_id"], "section_id": s["id"]}
                for s in section_data
                if s["depth"] == 0
            ]
            if top_level:
                session.run(
                    """
                    UNWIND $edges AS e
                    MATCH (d:Document {id: e.doc_id, group_id: $group_id})
                    MATCH (s:Section {id: e.section_id})
                    MERGE (d)-[:HAS_SECTION]->(s)
                    """,
                    edges=top_level,
                    group_id=group_id,
                )
            
            # Create SUBSECTION_OF edges (child -> parent)
            subsection_edges = []
            for s in section_data:
                if s["parent_path_key"]:
                    parent_key = (s["doc_id"], s["parent_path_key"])
                    parent = all_sections.get(parent_key)
                    if parent:
                        subsection_edges.append({
                            "child_id": s["id"],
                            "parent_id": parent["id"],
                        })
            
            if subsection_edges:
                session.run(
                    """
                    UNWIND $edges AS e
                    MATCH (child:Section {id: e.child_id})
                    MATCH (parent:Section {id: e.parent_id})
                    MERGE (child)-[:SUBSECTION_OF]->(parent)
                    """,
                    edges=subsection_edges,
                )
            
            # Create IN_SECTION edges (TextChunk -> leaf Section)
            in_section_edges = [
                {"chunk_id": chunk_id, "section_id": section_id}
                for chunk_id, section_id in chunk_to_leaf_section.items()
            ]
            
            in_section_count = 0
            batch_size = 1000
            for i in range(0, len(in_section_edges), batch_size):
                batch = in_section_edges[i : i + batch_size]
                result = session.run(
                    """
                    UNWIND $edges AS e
                    MATCH (t:TextChunk {id: e.chunk_id})
                    MATCH (s:Section {id: e.section_id})
                    MERGE (t)-[:IN_SECTION]->(s)
                    RETURN count(*) AS count
                    """,
                    edges=batch,
                )
                in_section_count += result.single()["count"]
        
        logger.info(
            "section_graph_built",
            extra={
                "group_id": group_id,
                "sections_created": sections_created,
                "in_section_edges": in_section_count,
            },
        )
        
        return {
            "sections_created": sections_created,
            "in_section_edges": in_section_count,
        }

    async def _embed_section_nodes(self, group_id: str) -> Dict[str, Any]:
        """Embed Section nodes for semantic similarity computation.
        
        Creates embeddings for Section nodes by concatenating:
        - Section title
        - Aggregated text from linked TextChunks (first 500 chars each, max 3 chunks)
        
        This enables SEMANTICALLY_SIMILAR edge creation for "soft" thematic hops.
        
        Args:
            group_id: Tenant identifier
            
        Returns:
            Stats dict with sections_embedded count
        """
        if self.embedder is None:
            logger.warning("section_embedding_skipped_no_embedder")
            return {"sections_embedded": 0, "skipped": "no_embedder"}
        
        # Fetch sections with their linked chunk texts
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            result = session.run(
                """
                MATCH (s:Section {group_id: $group_id})
                WHERE s.embedding IS NULL
                OPTIONAL MATCH (t:TextChunk)-[:IN_SECTION]->(s)
                WITH s, collect(t.text)[0..3] AS chunk_texts
                RETURN s.id AS section_id, s.title AS title, s.path_key AS path_key, chunk_texts
                """,
                group_id=group_id,
            )
            sections_to_embed = [
                {
                    "id": record["section_id"],
                    "title": record["title"] or "",
                    "path_key": record["path_key"] or "",
                    "chunk_texts": record["chunk_texts"] or [],
                }
                for record in result
            ]
        
        if not sections_to_embed:
            return {"sections_embedded": 0}
        
        # Build embedding texts
        texts_to_embed = []
        for sec in sections_to_embed:
            # Combine section title + path + sample chunk content
            parts = [sec["title"], sec["path_key"]]
            for chunk_text in sec["chunk_texts"]:
                if chunk_text:
                    parts.append(chunk_text[:500])  # First 500 chars of each chunk
            combined = " | ".join(p for p in parts if p)
            texts_to_embed.append(combined[:2000])  # Cap total length
        
        # Generate embeddings
        try:
            embeddings = await self.embedder.aget_text_embedding_batch(texts_to_embed)
        except Exception as e:
            logger.warning("section_embedding_failed", extra={"error": str(e)})
            return {"sections_embedded": 0, "error": str(e)}
        
        # Update Section nodes with embeddings
        updates = [
            {"id": sec["id"], "embedding": emb}
            for sec, emb in zip(sections_to_embed, embeddings)
            if emb is not None
        ]
        
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            session.run(
                """
                UNWIND $updates AS u
                MATCH (s:Section {id: u.id})
                SET s.embedding = u.embedding
                """,
                updates=updates,
            )
        
        logger.info(
            "section_nodes_embedded",
            extra={"group_id": group_id, "sections_embedded": len(updates)},
        )
        
        return {"sections_embedded": len(updates)}

    async def _build_section_similarity_edges(
        self,
        group_id: str,
        similarity_threshold: float = 0.43,
        max_edges_per_section: int = 5,
    ) -> Dict[str, Any]:
        """Create SEMANTICALLY_SIMILAR edges between Section nodes.
        
        This enables "soft" thematic hops in PPR traversal, solving HippoRAG 2's
        "Latent Transition" weakness where two sections are conceptually related
        but share no explicit entities.
        
        Only creates cross-document edges (same-document sections are already
        connected via SUBSECTION_OF hierarchy).
        
        Args:
            group_id: Tenant identifier
            similarity_threshold: Minimum cosine similarity to create edge.
                                  Default 0.43 was empirically determined - 0.80 was too high
                                  and produced zero edges on heterogeneous corpora.
                                  PPR applies additional 0.50 filter at query time.
            max_edges_per_section: Cap edges per section to avoid graph bloat
            
        Returns:
            Stats dict with edges_created count
        """
        # Fetch all sections with embeddings
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            result = session.run(
                """
                MATCH (s:Section {group_id: $group_id})
                WHERE s.embedding IS NOT NULL
                RETURN s.id AS id, s.doc_id AS doc_id, s.embedding AS embedding
                """,
                group_id=group_id,
            )
            sections = [
                {"id": record["id"], "doc_id": record["doc_id"], "embedding": record["embedding"]}
                for record in result
            ]
        
        if len(sections) < 2:
            return {"edges_created": 0, "reason": "insufficient_sections"}
        
        # Compute pairwise similarities for cross-document sections
        import numpy as np
        
        edges_to_create = []
        edge_count_per_section: Dict[str, int] = {}
        
        for i, s1 in enumerate(sections):
            if s1["embedding"] is None:
                continue
            emb1 = np.array(s1["embedding"])
            norm1 = np.linalg.norm(emb1)
            if norm1 == 0:
                continue
            
            for j, s2 in enumerate(sections):
                if j <= i:  # Avoid duplicates and self-comparison
                    continue
                if s1["doc_id"] == s2["doc_id"]:  # Only cross-document
                    continue
                if s2["embedding"] is None:
                    continue
                
                # Check edge count limits
                if edge_count_per_section.get(s1["id"], 0) >= max_edges_per_section:
                    continue
                if edge_count_per_section.get(s2["id"], 0) >= max_edges_per_section:
                    continue
                
                emb2 = np.array(s2["embedding"])
                norm2 = np.linalg.norm(emb2)
                if norm2 == 0:
                    continue
                
                # Cosine similarity
                similarity = float(np.dot(emb1, emb2) / (norm1 * norm2))
                
                if similarity >= similarity_threshold:
                    edges_to_create.append({
                        "source_id": s1["id"],
                        "target_id": s2["id"],
                        "similarity": round(similarity, 4),
                    })
                    edge_count_per_section[s1["id"]] = edge_count_per_section.get(s1["id"], 0) + 1
                    edge_count_per_section[s2["id"]] = edge_count_per_section.get(s2["id"], 0) + 1
        
        if not edges_to_create:
            return {"edges_created": 0}
        
        # Create SEMANTICALLY_SIMILAR edges in Neo4j
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            result = session.run(
                """
                UNWIND $edges AS e
                MATCH (s1:Section {id: e.source_id, group_id: $group_id})
                MATCH (s2:Section {id: e.target_id, group_id: $group_id})
                MERGE (s1)-[r:SEMANTICALLY_SIMILAR]->(s2)
                SET r.similarity = e.similarity, r.group_id = $group_id, r.created_at = datetime()
                RETURN count(r) AS count
                """,
                edges=edges_to_create,
                group_id=group_id,
            )
            edges_created = result.single()["count"]
        
        logger.info(
            "section_similarity_edges_created",
            extra={
                "group_id": group_id,
                "edges_created": edges_created,
                "threshold": similarity_threshold,
            },
        )
        
        return {"edges_created": edges_created}

    async def _embed_keyvalue_keys(self, group_id: str) -> Dict[str, Any]:
        """Embed KeyValue keys for semantic matching at query time.
        
        Creates embeddings for unique KVP keys to enable semantic key matching.
        Uses batch deduplication to avoid re-embedding identical keys.
        
        This enables queries like "What is the policy number?" to match 
        keys like "Policy #", "Policy Number", "Policy ID" via semantic similarity.
        
        Args:
            group_id: Tenant identifier
            
        Returns:
            Stats dict with kvps_total, unique_keys, keys_embedded counts
        """
        if self.embedder is None:
            logger.warning("keyvalue_embedding_skipped_no_embedder")
            return {"kvps_total": 0, "unique_keys": 0, "keys_embedded": 0, "skipped": "no_embedder"}
        
        # Fetch all KeyValue nodes without embeddings
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            result = session.run(
                """
                MATCH (kv:KeyValue {group_id: $group_id})
                WHERE kv.key_embedding IS NULL
                RETURN kv.id AS id, kv.key AS key
                """,
                group_id=group_id,
            )
            kvps_to_embed = [{"id": record["id"], "key": record["key"]} for record in result]
        
        if not kvps_to_embed:
            # Count total KVPs for stats
            with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
                result = session.run(
                    "MATCH (kv:KeyValue {group_id: $group_id}) RETURN count(kv) AS count",
                    group_id=group_id,
                )
                total = result.single()["count"]
            return {"kvps_total": total, "unique_keys": 0, "keys_embedded": 0}
        
        # Deduplicate keys (case-insensitive) for efficient batch embedding
        key_to_ids: Dict[str, List[str]] = {}
        for kvp in kvps_to_embed:
            normalized_key = (kvp["key"] or "").strip().lower()
            if normalized_key:
                key_to_ids.setdefault(normalized_key, []).append(kvp["id"])
        
        if not key_to_ids:
            return {"kvps_total": len(kvps_to_embed), "unique_keys": 0, "keys_embedded": 0}
        
        # Embed unique keys
        unique_keys = list(key_to_ids.keys())
        try:
            embeddings = await self.embedder.aget_text_embedding_batch(unique_keys)
        except Exception as e:
            logger.warning("keyvalue_embedding_failed", extra={"error": str(e)})
            return {"kvps_total": len(kvps_to_embed), "unique_keys": len(unique_keys), "keys_embedded": 0, "error": str(e)}
        
        # Build updates: map embedding back to all KVP nodes with same normalized key
        updates = []
        for key, embedding in zip(unique_keys, embeddings):
            if embedding is None:
                continue
            for kvp_id in key_to_ids[key]:
                updates.append({"id": kvp_id, "key_embedding": embedding})
        
        if not updates:
            return {"kvps_total": len(kvps_to_embed), "unique_keys": len(unique_keys), "keys_embedded": 0}
        
        # Update KeyValue nodes with embeddings
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            session.run(
                """
                UNWIND $updates AS u
                MATCH (kv:KeyValue {id: u.id})
                SET kv.key_embedding = u.key_embedding
                """,
                updates=updates,
            )
        
        logger.info(
            "keyvalue_keys_embedded",
            extra={
                "group_id": group_id,
                "kvps_total": len(kvps_to_embed),
                "unique_keys": len(unique_keys),
                "keys_embedded": len(updates),
            },
        )
        
        return {
            "kvps_total": len(kvps_to_embed),
            "unique_keys": len(unique_keys),
            "keys_embedded": len(updates),
        }

    async def _create_foundation_edges(self, group_id: str) -> Dict[str, int]:
        """Create foundation edges for graph schema enhancement.
        
        Creates three types of pre-computed edges:
        1. APPEARS_IN_SECTION: Entity → Section (replaces 2-hop Entity-Chunk-Section)
        2. APPEARS_IN_DOCUMENT: Entity → Document (replaces 3-hop Entity-Chunk-Section-Doc)
        3. HAS_HUB_ENTITY: Section → Entity (top-3 most connected entities per section)
        
        These edges enable O(1) retrieval for Route 2 (Local Search) and provide
        the LazyGraphRAG→HippoRAG bridge for Route 4 (DRIFT).
        
        Args:
            group_id: Group identifier for multi-tenancy
            
        Returns:
            Dictionary with edge counts: {"appears_in_section": N, "appears_in_document": M, "has_hub_entity": K}
        """
        logger.info("creating_foundation_edges", extra={"group_id": group_id})
        
        stats = {
            "appears_in_section": 0,
            "appears_in_document": 0,
            "has_hub_entity": 0,
        }
        
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            # 1. Create APPEARS_IN_SECTION edges (Entity → Section)
            result = session.run(
                """
                MATCH (c:TextChunk)-[:MENTIONS]->(e:Entity), (c)-[:IN_SECTION]->(s:Section)
                WHERE e.group_id = $group_id AND c.group_id = $group_id AND s.group_id = $group_id
                WITH e, s
                MERGE (e)-[r:APPEARS_IN_SECTION]->(s)
                SET r.group_id = $group_id
                RETURN count(DISTINCT r) AS count
                """,
                group_id=group_id,
            )
            stats["appears_in_section"] = result.single()["count"]
            
            # 2. Create APPEARS_IN_DOCUMENT edges (Entity → Document)
            result = session.run(
                """
                MATCH (c:TextChunk)-[:MENTIONS]->(e:Entity), (c)-[:IN_SECTION]->(s:Section)
                WHERE e.group_id = $group_id AND c.group_id = $group_id AND s.group_id = $group_id
                WITH e, s.doc_id AS doc_id
                MATCH (d:Document {id: doc_id})
                WHERE d.group_id = $group_id
                WITH e, d
                MERGE (e)-[r:APPEARS_IN_DOCUMENT]->(d)
                SET r.group_id = $group_id
                RETURN count(DISTINCT r) AS count
                """,
                group_id=group_id,
            )
            stats["appears_in_document"] = result.single()["count"]
            
            # 3. Create HAS_HUB_ENTITY edges (Section → top-3 entities)
            result = session.run(
                """
                MATCH (s:Section {group_id: $group_id})<-[:IN_SECTION]-(c:TextChunk)-[:MENTIONS]->(e:Entity)
                WHERE c.group_id = $group_id
                WITH s, e, count(DISTINCT c) AS mention_count
                ORDER BY s.id, mention_count DESC
                WITH s, collect({entity: e, count: mention_count})[..3] AS top_entities
                UNWIND top_entities AS te
                WITH s, te.entity AS e, te.count AS mention_count
                MERGE (s)-[r:HAS_HUB_ENTITY]->(e)
                SET r.group_id = $group_id, r.mention_count = mention_count
                RETURN count(r) AS count
                """,
                group_id=group_id,
            )
            stats["has_hub_entity"] = result.single()["count"]
        
        logger.info(
            "foundation_edges_created",
            extra={
                "group_id": group_id,
                "appears_in_section": stats["appears_in_section"],
                "appears_in_document": stats["appears_in_document"],
                "has_hub_entity": stats["has_hub_entity"],
            },
        )
        
        return stats

    async def _create_connectivity_edges(self, group_id: str) -> Dict[str, int]:
        """Create Phase 2 connectivity edges for cross-document section linking.
        
        Creates:
        1. SHARES_ENTITY: Section ↔ Section (when sections share 2+ entities)
        
        These edges enable:
        - Cross-document traversal ("Find related sections across docs")
        - PPR probability flow across document boundaries
        - Route 3/4 global search improvements
        
        Returns:
            Dictionary with edge counts: {"shares_entity": N}
        """
        stats = {
            "shares_entity": 0,
        }
        
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            # Create SHARES_ENTITY edges (Section ↔ Section)
            # Connects sections that discuss the same entities across documents
            # Threshold: at least 2 shared entities to reduce noise
            result = session.run(
                """
                MATCH (s1:Section {group_id: $group_id})<-[:IN_SECTION]-(c1:TextChunk)
                      -[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(c2:TextChunk)
                      -[:IN_SECTION]->(s2:Section {group_id: $group_id})
                WHERE s1 <> s2
                  AND s1.doc_id <> s2.doc_id  // Cross-document only
                WITH s1, s2, collect(DISTINCT e.name) AS shared_entities, count(DISTINCT e) AS shared_count
                WHERE shared_count >= 2  // Threshold: at least 2 shared entities
                MERGE (s1)-[r:SHARES_ENTITY]->(s2)
                SET r.shared_entities = shared_entities[0..10],
                    r.shared_count = shared_count,
                    r.similarity_boost = shared_count * 0.1,
                    r.group_id = $group_id,
                    r.created_at = datetime()
                RETURN count(r) AS count
                """,
                group_id=group_id,
            )
            stats["shares_entity"] = result.single()["count"]
        
        logger.info(
            "connectivity_edges_created",
            extra={
                "group_id": group_id,
                "shares_entity": stats["shares_entity"],
            },
        )
        
        return stats

    async def _create_semantic_edges(self, group_id: str) -> Dict[str, int]:
        """Create Phase 3 semantic enhancement edges.
        
        Creates:
        1. SIMILAR_TO: Entity ↔ Entity (via embedding similarity)
        
        These edges enable:
        - Fuzzy entity matching ("warranty period" ↔ "coverage duration")
        - Alternative PPR paths for entity disambiguation
        - Cross-document entity bridging without explicit RELATED_TO
        
        Args:
            group_id: Group identifier for multi-tenancy
            
        Returns:
            Dictionary with edge counts: {"similar_to": N}
        """
        logger.info("creating_semantic_edges", extra={"group_id": group_id})
        
        stats = {
            "similar_to": 0,
        }
        
        with self.neo4j_store.driver.session(database=self.neo4j_store.database) as session:
            # Create SIMILAR_TO edges (Entity ↔ Entity)
            # Connects entities with high embedding similarity
            # V2 uses 0.87 threshold (voyage-context-3 clusters tighter than OpenAI)
            # V1 used 0.85 threshold (text-embedding-3-large)
            # Skips entities that already have explicit RELATED_TO relationships
            similarity_threshold = getattr(settings, 'VOYAGE_V2_SIMILARITY_THRESHOLD', 0.87)
            result = session.run(
                """
                MATCH (e1:Entity {group_id: $group_id}), (e2:Entity {group_id: $group_id})
                WHERE e1 <> e2
                  AND e1.embedding IS NOT NULL
                  AND e2.embedding IS NOT NULL
                  AND id(e1) < id(e2)  // Avoid duplicates (create undirected edges once)
                  AND NOT (e1)-[:RELATED_TO]-(e2)  // Skip explicit relationships
                WITH e1, e2, 
                     vector.similarity.cosine(e1.embedding, e2.embedding) AS score
                WHERE score > $threshold
                MERGE (e1)-[r:SIMILAR_TO]-(e2)
                SET r.score = score,
                    r.group_id = $group_id,
                    r.created_at = datetime()
                RETURN count(r) AS count
                """,
                group_id=group_id,
                threshold=similarity_threshold,
            )
            stats["similar_to"] = result.single()["count"]
        
        logger.info(
            "semantic_edges_created",
            extra={
                "group_id": group_id,
                "similar_to": stats["similar_to"],
            },
        )
        
        return stats
