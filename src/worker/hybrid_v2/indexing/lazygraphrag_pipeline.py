"""LazyGraphRAG indexing pipeline (hybrid-owned).

This exists to avoid coupling `/hybrid/index/documents` to the V3 router or the V3
indexing pipeline implementation. The hybrid system needs a stable, dedicated
indexing entrypoint that populates the Neo4j schema used by:
- Route 2/3/4/5/6/7 (LazyGraphRAG + HippoRAG over :Entity / :Sentence / :MENTIONS)

Sentence-direct indexing: DI units → spaCy → Sentence nodes.

Phase 2 Migration: Added optional neo4j-graphrag LLMEntityRelationExtractor support.
Set use_native_extractor=True in config to use the native extractor.

Design goals:
- No imports from `app.archive.v3.routers.*` (archived)
- Minimal surface area: one async `index_documents` method
- Best-effort behavior when LLM/embeddings are not configured (skip that stage)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast
from urllib.parse import unquote

from llama_index.core.indices.property_graph import SchemaLLMPathExtractor
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument
from llama_index.core.schema import TextNode

# neo4j-graphrag native extractor (Phase 2 migration - optional)
try:
    from neo4j_graphrag.experimental.components.entity_relation_extractor import LLMEntityRelationExtractor
    from neo4j_graphrag.experimental.components.types import TextChunk as NativeTextChunk, TextChunks
    from neo4j_graphrag.experimental.components.schema import (
        NodeType as SchemaEntity,
        PropertyType as SchemaProperty,
        RelationshipType as SchemaRelation,
        GraphSchema as SchemaConfig,
    )
    from neo4j_graphrag.llm import AzureOpenAILLM
    NATIVE_EXTRACTOR_AVAILABLE = True
except ImportError:
    NATIVE_EXTRACTOR_AVAILABLE = False

from src.worker.services.document_intelligence_service import DocumentIntelligenceService
from src.worker.hybrid_v2.services.entity_deduplication import EntityDeduplicationService
from src.worker.hybrid_v2.services.neo4j_store import Document, Entity, Neo4jStoreV3, Relationship
from src.worker.hybrid_v2.utils.language import canonical_key_for_entity, is_cjk, detect_cjk_from_text
from src.core.config import settings

# GDS client - works with Aura Serverless Graph Analytics via GdsSessions API
try:
    from graphdatascience.session import (
        GdsSessions,
        AuraAPICredentials,
        DbmsConnectionInfo,
        SessionMemory,
    )
    GDS_SESSIONS_AVAILABLE = True
except ImportError:
    GDS_SESSIONS_AVAILABLE = False

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
    
    # Pattern 3: Month DD, YYYY (e.g., "June 15, 2024") — English + German month names
    months = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        # German month names
        'januar': 1, 'februar': 2, 'märz': 3, 'april': 4, 'mai': 5, 'juni': 6,
        'juli': 7, 'august': 8, 'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12,
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
    
    # Pattern 4: DD Month YYYY (e.g., "15 June 2024", "15. Juni 2024")
    for match in re.finditer(r'\b(\d{1,2})\.?\s+([A-Za-zÄäÖöÜüß]+)\s+(\d{4})\b', content):
        try:
            month_name = match.group(2).lower()
            if month_name in months:
                month = months[month_name]
                day, year = int(match.group(1)), int(match.group(3))
                if 1 <= day <= 31 and 1900 <= year <= 2100:
                    dates_found.append(datetime(year, month, day))
        except (ValueError, OverflowError):
            continue
    
    # Pattern 5: DD.MM.YYYY (German/European format — uses dots as separator)
    for match in re.finditer(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b', content):
        try:
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
                dates_found.append(datetime(year, month, day))
        except (ValueError, OverflowError):
            continue
    
    if not dates_found:
        return None
    
    # Return the latest (most recent) date - this represents the document's effective date
    latest = max(dates_found)
    return latest.strftime("%Y-%m-%d")


def _entity_mentioned_in_text(name: str, aliases: List[str], text: str) -> bool:
    """Check if an entity is mentioned in text using fuzzy matching.

    Checks (in order):
    1. Exact substring match on entity name
    2. Exact substring match on each alias
    3. Contiguous word-subsequence match (length >= 2 words, >= 4 chars)
       to catch partial names like "Contoso Lifts" inside "Contoso Lifts LLC"
    """
    text_lower = text.lower()

    # 1. Exact substring on canonical name
    name_lower = name.lower().strip()
    if name_lower and name_lower in text_lower:
        return True

    # 2. Alias matching
    for alias in aliases:
        alias_lower = alias.strip().lower()
        if alias_lower and alias_lower in text_lower:
            return True

    # 3. Contiguous word-subsequence matching for multi-word entity names
    words = name_lower.split()
    if len(words) >= 2:
        for start in range(len(words)):
            for end in range(start + 2, len(words) + 1):
                if end - start == len(words):
                    continue  # skip full name (already checked)
                subseq = " ".join(words[start:end])
                if len(subseq) >= 4 and subseq in text_lower:
                    return True

    return False


@dataclass
class LazyGraphRAGIndexingConfig:
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_dimensions: int = 2048  # voyage-context-3
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
        section_embed_model: Optional[Any],
        voyage_service: Optional[Any] = None,
        config: Optional[LazyGraphRAGIndexingConfig] = None,
    ):
        self.neo4j_store = neo4j_store
        self.llm = llm
        self.section_embed_model = section_embed_model  # LlamaIndex wrapper for sections, communities, KVP
        self.voyage_service = voyage_service  # VoyageEmbedService for entity + passage embedding
        self.config = config or LazyGraphRAGIndexingConfig()

        # Limit concurrent Neo4j write operations to prevent Aura write storms.
        # Parallel steps (section enrichment, foundation edges) each acquire
        # this semaphore before writing, keeping max concurrent writes bounded.
        self._neo4j_write_sem = asyncio.Semaphore(settings.NEO4J_WRITE_CONCURRENCY)

        self._splitter = SentenceSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )

        # Chunking strategy: "section_aware" (default) or "sliding_3sentence"
        self._chunk_strategy = os.getenv("CHUNK_STRATEGY", "section_aware")

        # OpenIE batching: "section" (group by section + title prefix) or "sequential" (legacy 5-sentence)
        self._openie_batching = os.getenv("OPENIE_BATCHING", "section")
        # Structured extraction: "deterministic" (rules for sig/letterhead) or "llm" (send to OpenIE)
        self._structured_extraction = os.getenv("STRUCTURED_EXTRACTION", "deterministic")
        # Two-step NER→Triple extraction (upstream HippoRAG 2 alignment)
        # Default true: two-step scores 56/57 after entity embedding bleed fix (commit 72fde278)
        self._openie_two_step = os.getenv("OPENIE_TWO_STEP", "true").strip().lower() in {"1", "true", "yes"}
        # NER scope: "broad" (includes abstract concepts) or "narrow" (proper nouns only, HippoRAG 2 style)
        self._ner_scope = os.getenv("OPENIE_NER_SCOPE", "broad").strip().lower()

    async def _achat_with_retry(self, messages, *, timeout: Optional[int] = None) -> Any:
        """Call self.llm.achat() with retry + timeout.

        Retries on transient LLM errors (rate limits, server errors).
        Wraps with asyncio.wait_for to prevent indefinite hangs.
        """
        if timeout is None:
            timeout = settings.LLM_TIMEOUT_SECONDS
        max_retries = settings.LLM_MAX_RETRIES
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(
                    self.llm.achat(messages), timeout=timeout,
                )
            except asyncio.TimeoutError:
                last_exc = TimeoutError(f"LLM achat timed out after {timeout}s")
                if attempt >= max_retries - 1:
                    raise last_exc
                delay = 2 ** attempt
                logger.warning("LLM timeout (attempt %d/%d), retrying in %ds", attempt + 1, max_retries, delay)
                await asyncio.sleep(delay)
            except Exception as e:
                last_exc = e
                err_msg = str(e).lower()
                is_retryable = any(k in err_msg for k in (
                    "rate limit", "429", "500", "502", "503", "504",
                    "timeout", "connection", "server error", "throttl",
                ))
                if not is_retryable or attempt >= max_retries - 1:
                    raise
                delay = 2 ** attempt
                logger.warning("LLM transient error (attempt %d/%d), retrying in %ds: %s", attempt + 1, max_retries, delay, e)
                await asyncio.sleep(delay)
        raise last_exc  # pragma: no cover

    async def index_documents(
        self,
        *,
        group_id: str,
        documents: List[Dict[str, Any]],
        reindex: bool = False,
        reextract_entities: bool = False,
        ingestion: str = "none",
        # These parameters exist on the hybrid endpoint; LazyGraphRAG prefers on-demand
        # community/raptor work, so we ignore them but keep signature compatibility.
        run_community_detection: bool = False,
        run_raptor: bool = False,
        dry_run: bool = False,
        # KNN tuning parameters
        knn_enabled: bool = True,
        knn_top_k: int = 5,
        knn_similarity_cutoff: float = 0.60,
        knn_config: Optional[str] = None,  # Tag for KNN edges (e.g., "knn-1", "knn-2") for A/B testing
        # Entity synonymy parameters (cross-doc bridging via embedding similarity)
        entity_synonymy_threshold: float = 0.65,
        # When True, skip steps 7.5-9 (triple embeddings, synonymy edges, GDS,
        # communities).  Used for multi-doc folder indexing: run extraction for
        # each doc, then run graph algorithms once at the end on the full graph.
        extraction_only: bool = False,
        # User identifier for per-user usage tracking (Cosmos DB partition key)
        user_id: Optional[str] = None,
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
            self.neo4j_store.clear_pipeline_checkpoint(group_id)

        # ── Re-extract entities only (skip parse/chunk/embed) ──────
        # When reextract_entities=True, we keep existing Sentences,
        # TextChunks, Documents, and Sections.  Only Entity nodes,
        # Community nodes, and MENTIONS edges are deleted and rebuilt.
        if reextract_entities and not reindex:
            logger.info("reextract_entities_mode: deleting entities/mentions only")
            del_stats = self.neo4j_store.delete_entities_only(group_id)
            stats["reextract_deleted"] = del_stats

            # Fetch existing sentences for entity extraction
            existing_sentences = self.neo4j_store.get_sentences_by_group(group_id)
            if not existing_sentences:
                stats["skipped"].append("no_sentences_for_reextraction")
                stats["elapsed_s"] = round(time.time() - start_time, 2)
                return stats

            # Jump to step 5: entity extraction on existing sentences
            entities: List[Entity] = []
            relationships: List[Relationship] = []
            if self.llm is None:
                stats["skipped"].append("no_llm_entity_extraction")
            else:
                entities, relationships = await self._extract_entities_and_relationships(
                    group_id=group_id,
                )
                logger.info(
                    f"reextract_entity_extraction_complete: "
                    f"{len(entities)} entities, {len(relationships)} relationships"
                )

            # Steps 6-7: dedup + validate + commit
            if entities:
                # Offload CPU-heavy dedup (O(n²) pairwise cosine) to thread
                # pool so the main event loop stays responsive for health probes.
                entities, relationships, dedup_stats = await asyncio.to_thread(
                    self._deduplicate_entities,
                    group_id=group_id,
                    entities=entities,
                    relationships=relationships,
                )
                stats["deduplication"] = dedup_stats

            commit_result = await self._validate_and_commit_entities(
                group_id=group_id,
                entities=entities,
                relationships=relationships,
                dry_run=dry_run,
            )
            stats["validation_passed"] = commit_result.get("passed", False)
            stats["entities"] = len(entities)
            stats["relationships"] = len(relationships)

            # Step 8: GDS algorithms
            try:
                gds_stats = await self._run_gds_graph_algorithms(
                    group_id=group_id,
                    knn_top_k=knn_top_k,
                    knn_similarity_cutoff=knn_similarity_cutoff,
                    knn_config=knn_config,
                )
                stats["gds_knn_edges"] = gds_stats.get("knn_edges", 0)
                stats["gds_communities"] = gds_stats.get("communities", 0)
            except Exception as e:
                logger.warning(f"reextract_gds_failed: {e}")

            stats["elapsed_s"] = round(time.time() - start_time, 2)
            logger.info(f"reextract_entities_complete: {stats}")
            return stats

        # Initialize GroupMeta node for lifecycle tracking.
        # This creates or updates the GroupMeta node to track GDS staleness, etc.
        self.neo4j_store.initialize_group_meta(group_id)

        # ── Resume support: read last checkpoint ───────────────────────────
        # In extraction_only mode (parallel doc processing), skip checkpointing
        # since the checkpoint is group-level and would conflict between docs.
        # File-level resume (analysis_files_processed) handles crash recovery.
        if extraction_only:
            checkpoint = None
        else:
            checkpoint = self.neo4j_store.get_pipeline_checkpoint(group_id)
            if checkpoint:
                logger.info(
                    "pipeline_resuming_from_checkpoint",
                    extra={"group_id": group_id, "checkpoint": checkpoint},
                )

        # Pre-load wtpsplit model synchronously BEFORE DI extraction so its
        # ~816 MB allocation happens while memory is still plentiful.
        # Must NOT run concurrently with DI — on a 1 Gi container the combined
        # peak would OOM and crash the process.
        from src.worker.services.sentence_extraction_service import _get_sat
        _get_sat()

        # ── Steps 1-3: DI extraction → sentences ──────────────────────────
        if not self.neo4j_store._step_done(checkpoint, "sentences"):
            # 1) Normalize + (optional) extract with Document Intelligence.
            t_step = time.perf_counter()
            expanded_docs = await self._prepare_documents(group_id, documents, ingestion)
            logger.info("⏱️ Step 1 (_prepare_documents): %.2fs", time.perf_counter() - t_step)

            # 2) Upsert Document nodes (batched) + clean stale children.
            t_step = time.perf_counter()
            chunk_to_doc_id: Dict[str, str] = {}  # kept for _process_di_metadata_to_graph compat

            # Build Document objects and extract dates in one pass
            doc_objects = []
            for doc in expanded_docs:
                doc_id = doc["id"]
                doc_title = doc.get("title", "Untitled")
                logger.info(f"Preparing document: id={doc_id}, title='{doc_title}', has_di={bool(doc.get('di_extracted_docs'))}")

                doc_content_for_date = ""
                di_docs = doc.get("di_extracted_docs") or []
                if di_docs:
                    doc_content_for_date = " ".join(str(d.text) for d in di_docs if hasattr(d, 'text'))
                else:
                    doc_content_for_date = doc.get("content") or doc.get("text") or ""

                document_date = extract_document_date(doc_content_for_date) if doc_content_for_date else None
                if document_date:
                    logger.info(f"Extracted document date: doc_id={doc_id}, date={document_date}")

                doc_objects.append(Document(
                    id=doc_id,
                    title=doc_title,
                    source=doc.get("source", ""),
                    metadata=doc.get("metadata", {}) or {},
                    document_date=document_date,
                ))

            # Single UNWIND batch upsert (1 round-trip instead of N)
            self.neo4j_store.upsert_documents_batch(group_id, doc_objects)

            # Clean stale children before creating new ones (per-doc, only on fresh index).
            if not reindex:
                for doc in expanded_docs:
                    self.neo4j_store.delete_document_chunks(group_id, doc["id"])

            logger.info("⏱️ Step 2 (doc upsert): %.2fs", time.perf_counter() - t_step)

            # 3) Direct sentence indexing: DI units → spaCy → Sentence nodes.
            #    Bypasses the old TextChunk pipeline.
            t_step = time.perf_counter()
            import sys as _sys
            logger.info("Step 3 starting — entering _index_sentences_direct")
            _sys.stderr.flush(); _sys.stdout.flush()
            try:
                sentence_stats = await self._index_sentences_direct(
                    group_id=group_id,
                    expanded_docs=expanded_docs,
                )
            except BaseException as _exc:
                logger.error("Step 3 CRASHED: %s: %s", type(_exc).__name__, _exc, exc_info=True)
                _sys.stderr.flush(); _sys.stdout.flush()
                raise
            logger.info("⏱️ Step 3 (_index_sentences_direct): %.2fs", time.perf_counter() - t_step)
            stats["sentences"] = sentence_stats.get("sentences_created", 0)
            stats["sentences_embedded"] = sentence_stats.get("sentences_embedded", 0)

            if stats["sentences"] == 0:
                stats["skipped"].append("no_sentences")
                stats["elapsed_s"] = round(time.time() - start_time, 2)
                return stats

            if not extraction_only:
                self.neo4j_store.set_pipeline_checkpoint(group_id, "sentences")
        else:
            logger.info("pipeline_skip_sentences (checkpoint >= sentences)")
            # We still need expanded_docs for later steps — re-prepare them
            expanded_docs = await self._prepare_documents(group_id, documents, ingestion)
            chunk_to_doc_id = {}
            # Recover sentence count from Neo4j
            existing = self.neo4j_store.get_sentences_by_group(group_id)
            stats["sentences"] = len(existing)
            stats["sentences_embedded"] = len(existing)

        # ── Steps 4.2-4.9 ‖ Steps 5-7: Section graph + Entity extraction ──
        # These two blocks have NO data dependencies (section steps write to
        # Section/IN_SECTION/KVP nodes; entity steps write to Entity/RELATED_TO).
        # Both read Sentence nodes (committed in Steps 1-3) but don't modify them.
        # Running them in parallel saves ~30-60s on a typical pipeline run.
        section_needed = not self.neo4j_store._step_done(checkpoint, "section_graph")
        entities_needed = not self.neo4j_store._step_done(checkpoint, "entities_committed")

        if section_needed or entities_needed:
            parallel_tasks = []

            # ── Section block helper ──────────────────────────────────────
            async def _run_section_block() -> None:
                t_section_start = time.perf_counter()

                # 4.2 and 4.5 have no data dependencies — run them in parallel.
                async def _step_4_2():
                    if stats["sentences"] > 1:
                        try:
                            knn_stats = await self._build_sentence_knn_edges(group_id)
                            return knn_stats.get("edges_created", 0)
                        except Exception as e:
                            logger.warning(f"step_4.2_sentence_knn_failed: {e}")
                            return 0
                    return 0

                async def _step_4_5():
                    return await self._build_section_graph_from_docs(group_id, expanded_docs)

                knn_edge_count, section_stats = await asyncio.gather(
                    _step_4_2(), _step_4_5(),
                )
                stats["skeleton_related_to_edges"] = knn_edge_count
                if knn_edge_count:
                    logger.info("step_4.2_sentence_knn_complete", extra={"edges": knn_edge_count})
                stats["sections"] = section_stats.get("sections_created", 0)
                stats["section_edges"] = section_stats.get("in_section_edges", 0)

                # 4.5.1 and 4.5.2 both depend on 4.5 but are independent of each other.
                h_id_stats, total_stats = await asyncio.gather(
                    self._assign_sentence_hierarchical_ids(group_id),
                    self._backfill_section_total_sentences(group_id),
                )
                stats["hierarchical_ids_assigned"] = h_id_stats.get("assigned", 0)
                stats["section_totals_backfilled"] = total_stats.get("updated", 0)

                # 4.6–4.8) Section enrichment + KVP embedding.
                # Wave 1: Run 4.6, 4.7, 4.8 concurrently — no data deps between them.
                async def _gated_embed_sections():
                    async with self._neo4j_write_sem:
                        return await self._embed_section_nodes(group_id)

                async def _gated_section_summaries():
                    async with self._neo4j_write_sem:
                        return await self._generate_section_summaries(group_id)

                async def _gated_embed_kvp():
                    async with self._neo4j_write_sem:
                        return await self._embed_keyvalue_keys(group_id)

                section_embed_stats, section_summary_stats, kvp_embed_stats = await asyncio.gather(
                    _gated_embed_sections(),
                    _gated_section_summaries(),
                    _gated_embed_kvp(),
                )
                stats["sections_embedded"] = section_embed_stats.get("sections_embedded", 0)
                stats["sections_summarised"] = section_summary_stats.get("sections_summarised", 0)
                stats["key_values"] = kvp_embed_stats.get("kvps_total", 0)
                stats["key_values_embedded"] = kvp_embed_stats.get("keys_embedded", 0)

                # Wave 2: structural embedding depends on wave 1 summaries, but
                # similarity edges read section_embedding (wave 1) — independent.
                structural_embed_stats, similarity_stats = await asyncio.gather(
                    self._embed_section_structural(group_id),
                    self._build_section_similarity_edges(group_id),
                )
                stats["sections_structural_embedded"] = structural_embed_stats.get("sections_embedded", 0)
                stats["semantic_similarity_edges"] = similarity_stats.get("edges_created", 0)

                # 4.9) Process DI metadata: barcodes, figures, languages → graph.
                di_metadata_stats = await self._process_di_metadata_to_graph(
                    group_id=group_id,
                    expanded_docs=expanded_docs,
                    chunk_to_doc_id=chunk_to_doc_id,
                )
                stats["di_barcodes"] = di_metadata_stats.get("barcodes_created", 0)
                stats["di_languages"] = di_metadata_stats.get("languages_updated", 0)

                # Checkpoint: section block complete. Safe to set here because
                # "section_graph" < "entities_committed" in the checkpoint order.
                if not extraction_only:
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "section_graph")
                logger.info("⏱️ Steps 4.2-4.9 (section graph): %.2fs", time.perf_counter() - t_section_start)

            # ── Entity block helper ───────────────────────────────────────
            async def _run_entity_block() -> bool:
                """Returns True if entities passed validation, False otherwise."""
                t_entity_start = time.perf_counter()
                entities: List[Entity] = []
                relationships: List[Relationship] = []
                if self.llm is None:
                    stats["skipped"].append("no_llm_entity_extraction")
                else:
                    entities, relationships = await self._extract_entities_and_relationships(
                        group_id=group_id,
                    )
                    logger.info(f"entity_extraction_complete: {len(entities)} entities, {len(relationships)} relationships")
                    if len(relationships) < self.config.min_mentions:
                        logger.warning(
                            f"low_relationship_count: {len(relationships)} relationships "
                            f"(min_mentions={self.config.min_mentions}), entities={len(entities)}"
                        )

                # 6) Entity deduplication
                if entities:
                    entities, relationships, dedup_stats = await asyncio.to_thread(
                        self._deduplicate_entities,
                        group_id=group_id,
                        entities=entities,
                        relationships=relationships,
                    )
                    stats["deduplication"] = dedup_stats

                # 7) Validate and persist entities + relationships.
                commit_result = await self._validate_and_commit_entities(
                    group_id=group_id,
                    entities=entities,
                    relationships=relationships,
                    dry_run=dry_run,
                )
                stats["validation_passed"] = commit_result.get("passed", False)
                stats["validation_details"] = commit_result.get("details", {})
                stats["entities"] = len(entities)
                stats["relationships"] = len(relationships)
                stats["foundation_edges"] = commit_result.get("details", {}).get("foundation_edges", {})

                logger.info("⏱️ Steps 5-7 (entity extraction+commit): %.2fs", time.perf_counter() - t_entity_start)
                return commit_result.get("passed", False) or dry_run

            # Dispatch: run both in parallel if both needed, or just the one needed.
            if section_needed and entities_needed:
                logger.info("🚀 Running Steps 4.x ‖ Steps 5-7 in parallel (no data dependencies)")
                section_result, entity_passed = await asyncio.gather(
                    _run_section_block(),
                    _run_entity_block(),
                )
                # Set "entities_committed" only after BOTH complete.
                # "section_graph" was already set inside _run_section_block().
                if not entity_passed and not dry_run:
                    stats["skipped"].append("entity_validation_failed")
                    stats["elapsed_s"] = round(time.time() - start_time, 2)
                    return stats
                if not extraction_only:
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "entities_committed")
            elif section_needed:
                await _run_section_block()
            elif entities_needed:
                entity_passed = await _run_entity_block()
                if not entity_passed and not dry_run:
                    stats["skipped"].append("entity_validation_failed")
                    stats["elapsed_s"] = round(time.time() - start_time, 2)
                    return stats
                if not extraction_only:
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "entities_committed")
        else:
            logger.info("pipeline_skip_section_and_entities (checkpoint >= entities_committed)")

        # ── extraction_only: skip graph-wide steps (7.5-9) ─────────────────
        if extraction_only:
            logger.info("extraction_only=True — skipping steps 7.5-9 (will run once after all docs)")
            stats["elapsed_s"] = round(time.time() - start_time, 2)
            return stats

        # ── Steps 7.5 ‖ 7.6: Triple embeddings + Entity synonymy (parallel)
        # These are independent: 7.5 reads RELATED_TO triples → writes triple_embedding;
        # 7.6 reads entity_embedding → writes SEMANTICALLY_SIMILAR edges.
        t_post_entity_start = time.perf_counter()
        triple_needed = not self.neo4j_store._step_done(checkpoint, "triple_embeddings")
        synonymy_needed = not self.neo4j_store._step_done(checkpoint, "synonymy_edges")

        if triple_needed or synonymy_needed:
            async def _run_triple_embeddings() -> None:
                try:
                    triple_embed_stats = await self._precompute_triple_embeddings(group_id)
                    stats["triple_embeddings_stored"] = triple_embed_stats.get("stored", 0)
                    logger.info(
                        f"✅ Step 7.5: Pre-computed {stats['triple_embeddings_stored']} triple embeddings"
                    )
                    # Safe to set checkpoint here: "triple_embeddings" < "synonymy_edges"
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "triple_embeddings")
                except Exception as e:
                    logger.warning(f"⚠️  Triple embedding pre-computation failed: {e}")
                    stats["triple_embeddings_stored"] = 0

            async def _run_entity_synonymy() -> None:
                try:
                    synonymy_stats = await self._compute_entity_synonymy_edges(
                        group_id=group_id,
                        threshold=entity_synonymy_threshold,
                    )
                    stats["entity_synonymy_edges"] = synonymy_stats.get("edges_created", 0)
                    stats["entity_synonymy_cross_community"] = synonymy_stats.get("cross_community", 0)
                    logger.info(
                        "✅ Step 7.6: %d entity synonymy edges (%d cross-community) at threshold %.2f",
                        stats["entity_synonymy_edges"],
                        stats["entity_synonymy_cross_community"],
                        entity_synonymy_threshold,
                    )
                except Exception as e:
                    logger.warning(f"⚠️  Entity synonymy computation failed: {e}")
                    stats["entity_synonymy_edges"] = 0

            parallel_75_76 = []
            if triple_needed:
                parallel_75_76.append(_run_triple_embeddings())
            else:
                logger.info("pipeline_skip_triple_embeddings (checkpoint >= triple_embeddings)")
            if synonymy_needed:
                parallel_75_76.append(_run_entity_synonymy())
            else:
                logger.info("pipeline_skip_synonymy_edges (checkpoint >= synonymy_edges)")

            if len(parallel_75_76) == 2:
                logger.info("🚀 Running Steps 7.5 ‖ 7.6 in parallel")
            await asyncio.gather(*parallel_75_76)

            # Set "synonymy_edges" only after both complete successfully.
            # "triple_embeddings" was already set inside _run_triple_embeddings().
            if synonymy_needed and stats.get("entity_synonymy_edges", 0) > 0:
                self.neo4j_store.set_pipeline_checkpoint(group_id, "synonymy_edges")
        else:
            logger.info("pipeline_skip_triple_and_synonymy (checkpoint >= synonymy_edges)")

        # ── Step 8: GDS algorithms ─────────────────────────────────────────
        if not self.neo4j_store._step_done(checkpoint, "gds_complete"):
            gds_max_retries = 3
            gds_base_delay = 15  # seconds
            gds_stats: Dict[str, int] = {}
            for gds_attempt in range(gds_max_retries):
                try:
                    if knn_enabled:
                        logger.info(f"🔬 Running GDS algorithms (KNN k={knn_top_k}, cutoff={knn_similarity_cutoff}, config={knn_config}, community detection, PageRank)...")
                        gds_stats = await self._run_gds_graph_algorithms(
                            group_id=group_id,
                            knn_top_k=knn_top_k,
                            knn_similarity_cutoff=knn_similarity_cutoff,
                            knn_config=knn_config,
                        )
                    else:
                        logger.info("🔬 KNN disabled - running community detection and PageRank only...")
                        gds_stats = await self._run_gds_graph_algorithms(
                            group_id=group_id,
                            knn_top_k=0,
                            knn_similarity_cutoff=1.0,
                            knn_config=None,
                        )
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    is_transient = any(k in err_msg for k in (
                        "no data", "connection closed", "defunct connection",
                        "service unavailable", "timed out", "reset by peer",
                        "incomplete handshake",
                    ))
                    if is_transient and gds_attempt < gds_max_retries - 1:
                        delay = gds_base_delay * (2 ** gds_attempt)
                        logger.warning(
                            f"⏳ GDS transient failure (attempt {gds_attempt + 1}/{gds_max_retries}), "
                            f"retrying in {delay}s: {e}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.warning(f"⚠️  GDS algorithms failed after {gds_attempt + 1} attempt(s): {e}")
                    logger.warning("⚠️  Continuing indexing without GDS algorithms")
                    gds_stats = {}
                    break

            stats["gds_knn_edges"] = gds_stats.get("knn_edges", 0)
            stats["gds_entity_edges"] = gds_stats.get("entity_edges", 0)
            stats["gds_communities"] = gds_stats.get("communities", 0)
            stats["gds_pagerank_nodes"] = gds_stats.get("pagerank_nodes", 0)
            stats["knn_config"] = {
                "enabled": knn_enabled,
                "top_k": knn_top_k if knn_enabled else 0,
                "similarity_cutoff": knn_similarity_cutoff if knn_enabled else None,
                "config_tag": knn_config,
            }
            if gds_stats:
                logger.info(f"✅ GDS complete: {stats['gds_knn_edges']} KNN edges, {stats['gds_communities']} communities, {stats['gds_pagerank_nodes']} nodes scored")
                self.neo4j_store.set_pipeline_checkpoint(group_id, "gds_complete")
            else:
                # GDS failed or produced no results — do NOT set checkpoint so it
                # can be retried on the next run.
                logger.warning("⚠️  GDS produced no results — checkpoint NOT set (will retry on resume)")
        else:
            logger.info("pipeline_skip_gds (checkpoint >= gds_complete)")

        # ── Step 9: Materialize communities ────────────────────────
        if not self.neo4j_store._step_done(checkpoint, "communities"):
            if stats.get("gds_communities", 0) > 0:
                try:
                    logger.info("📦 Step 9: Materializing communities with LLM summaries...")
                    community_stats = await self._materialize_communities(
                        group_id=group_id,
                        min_community_size=2,
                    )
                    stats["communities_created"] = community_stats.get("communities_created", 0)
                    stats["summaries_generated"] = community_stats.get("summaries_generated", 0)
                    stats["embeddings_stored"] = community_stats.get("embeddings_stored", 0)
                    logger.info(
                        "✅ Step 9 complete: %d communities, %d summaries, %d embeddings",
                        stats["communities_created"],
                        stats["summaries_generated"],
                        stats["embeddings_stored"],
                    )
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "communities")
                except Exception as e:
                    logger.warning(f"⚠️  Community materialization failed: {e}")
                    stats["communities_created"] = 0
                    stats["summaries_generated"] = 0
                    stats["embeddings_stored"] = 0
                    # Do NOT set checkpoint on failure — allows retry on next run
            else:
                # No communities to materialize (GDS produced 0) — mark done
                self.neo4j_store.set_pipeline_checkpoint(group_id, "communities")
        else:
            logger.info("pipeline_skip_communities (checkpoint >= communities)")
        logger.info("⏱️ Steps 7.5-9 (triples+synonymy+GDS+communities): %.2fs", time.perf_counter() - t_post_entity_start)

        # Clear checkpoint — pipeline complete
        self.neo4j_store.clear_pipeline_checkpoint(group_id)
        
        stats["elapsed_s"] = round(time.time() - start_time, 2)
        return stats

    async def run_graph_algorithms_only(
        self,
        *,
        group_id: str,
        knn_enabled: bool = True,
        knn_top_k: int = 5,
        knn_similarity_cutoff: float = 0.60,
        knn_config: Optional[str] = None,
        entity_synonymy_threshold: float = 0.65,
    ) -> Dict[str, Any]:
        """Run only the graph-wide steps (7.5-9) after all docs have been extracted.

        This is the second phase of a two-phase folder indexing:
        Phase 1: index_documents(extraction_only=True) per doc
        Phase 2: run_graph_algorithms_only() once on the full graph

        Returns a dict with step stats plus:
          - ``errors``: list of ``{"step": ..., "error": ...}`` for failed steps
          - ``success``: True only if no critical step failed
        Critical steps: triple_embeddings, gds (KNN/Leiden/PageRank).
        Non-critical: synonymy_edges, communities (degrade quality but not fatal).
        """
        import time
        start_time = time.time()
        stats: Dict[str, Any] = {}
        errors: list[Dict[str, str]] = []

        logger.info(f"🔬 Running graph algorithms on full graph for group {group_id}")

        # ── Resume from checkpoint (skip already-completed steps) ──
        checkpoint = self.neo4j_store.get_pipeline_checkpoint(group_id)
        if checkpoint:
            logger.info(f"📌 Resuming graph algorithms from checkpoint: {checkpoint}")

        # Step 7.5: Triple embeddings (CRITICAL) — with retry
        _te_max_retries = 3
        _te_base_delay = 15
        if not self.neo4j_store._step_done(checkpoint, "triple_embeddings"):
            for _te_attempt in range(_te_max_retries):
                try:
                    triple_embed_stats = await self._precompute_triple_embeddings(group_id)
                    stats["triple_embeddings_stored"] = triple_embed_stats.get("stored", 0)
                    logger.info(f"✅ Step 7.5: Pre-computed {stats['triple_embeddings_stored']} triple embeddings")
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "triple_embeddings")
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    is_transient = any(k in err_msg for k in (
                        "connection", "timeout", "timed out", "rate limit",
                        "service unavailable", "reset by peer", "429",
                    ))
                    if is_transient and _te_attempt < _te_max_retries - 1:
                        delay = _te_base_delay * (2 ** _te_attempt)
                        logger.warning(
                            f"⏳ Triple embedding transient failure (attempt {_te_attempt + 1}/{_te_max_retries}), "
                            f"retrying in {delay}s: {e}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.warning(f"⚠️  Triple embedding failed after {_te_attempt + 1} attempt(s): {e}")
                    stats["triple_embeddings_stored"] = 0
                    errors.append({"step": "triple_embeddings", "error": str(e)[:500]})
                    break
        else:
            logger.info("⏭️  Step 7.5: Triple embeddings already checkpointed, skipping")

        # Step 7.6: Entity synonymy edges (non-critical)
        if not self.neo4j_store._step_done(checkpoint, "synonymy_edges"):
            try:
                synonymy_stats = await self._compute_entity_synonymy_edges(
                    group_id=group_id,
                    threshold=entity_synonymy_threshold,
                )
                stats["entity_synonymy_edges"] = synonymy_stats.get("edges_created", 0)
                logger.info(
                    "✅ Step 7.6: %d entity synonymy edges at threshold %.2f",
                    stats["entity_synonymy_edges"], entity_synonymy_threshold,
                )
                self.neo4j_store.set_pipeline_checkpoint(group_id, "synonymy_edges")
            except Exception as e:
                logger.warning(f"⚠️  Entity synonymy computation failed: {e}")
                stats["entity_synonymy_edges"] = 0
                errors.append({"step": "synonymy_edges", "error": str(e)[:500]})
        else:
            logger.info("⏭️  Step 7.6: Synonymy edges already checkpointed, skipping")

        # Step 8: GDS algorithms with retry (CRITICAL)
        if not self.neo4j_store._step_done(checkpoint, "gds_complete"):
            gds_max_retries = 3
            gds_base_delay = 15
            gds_stats: Dict[str, int] = {}
            for gds_attempt in range(gds_max_retries):
                try:
                    if knn_enabled:
                        logger.info(
                            f"🔬 Running GDS algorithms (KNN k={knn_top_k}, "
                            f"cutoff={knn_similarity_cutoff}, community detection, PageRank)..."
                        )
                        gds_stats = await self._run_gds_graph_algorithms(
                            group_id=group_id,
                            knn_top_k=knn_top_k,
                            knn_similarity_cutoff=knn_similarity_cutoff,
                            knn_config=knn_config,
                        )
                    else:
                        gds_stats = await self._run_gds_graph_algorithms(
                            group_id=group_id, knn_top_k=0,
                            knn_similarity_cutoff=1.0, knn_config=None,
                        )
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "gds_complete")
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    is_transient = any(k in err_msg for k in (
                        "no data", "connection closed", "defunct connection",
                        "service unavailable", "timed out", "reset by peer",
                        "incomplete handshake",
                    ))
                    if is_transient and gds_attempt < gds_max_retries - 1:
                        delay = gds_base_delay * (2 ** gds_attempt)
                        logger.warning(
                            f"⏳ GDS transient failure (attempt {gds_attempt + 1}/{gds_max_retries}), "
                            f"retrying in {delay}s: {e}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.warning(f"⚠️  GDS algorithms failed after {gds_attempt + 1} attempt(s): {e}")
                    errors.append({"step": "gds", "error": str(e)[:500]})
                    gds_stats = {}
                    break
        else:
            logger.info("⏭️  Step 8: GDS algorithms already checkpointed, skipping")
            gds_stats = {}

        stats["gds_knn_edges"] = gds_stats.get("knn_edges", 0)
        stats["gds_communities"] = gds_stats.get("communities", 0)
        stats["gds_pagerank_nodes"] = gds_stats.get("pagerank_nodes", 0)
        if gds_stats:
            logger.info(f"✅ GDS complete: {stats['gds_knn_edges']} KNN edges, {stats['gds_communities']} communities")

        # Step 9: Materialize communities (non-critical)
        if not self.neo4j_store._step_done(checkpoint, "communities"):
            if stats.get("gds_communities", 0) > 0:
                try:
                    logger.info("📦 Step 9: Materializing communities with LLM summaries...")
                    community_stats = await self._materialize_communities(
                        group_id=group_id,
                        min_community_size=2,
                    )
                    stats["communities_created"] = community_stats.get("communities_created", 0)
                    stats["summaries_generated"] = community_stats.get("summaries_generated", 0)
                    logger.info(
                        "✅ Step 9 complete: %d communities, %d summaries",
                        stats["communities_created"], stats["summaries_generated"],
                    )
                    self.neo4j_store.set_pipeline_checkpoint(group_id, "communities")
                except Exception as e:
                    logger.warning(f"⚠️  Community materialization failed: {e}")
                    errors.append({"step": "communities", "error": str(e)[:500]})
        else:
            logger.info("⏭️  Step 9: Communities already checkpointed, skipping")

        # ── Integrity validation ──
        try:
            validation = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._validate_graph_integrity(group_id)
            )
            stats["validation"] = validation
            if validation.get("warnings"):
                for w in validation["warnings"]:
                    logger.warning(f"⚠️  Integrity: {w}")
                    errors.append({"step": "validation", "error": w})
        except Exception as e:
            logger.warning(f"⚠️  Integrity validation failed: {e}")

        # Determine overall success: critical steps must not have failed
        critical_failures = [e for e in errors if e["step"] in ("triple_embeddings", "gds")]
        stats["errors"] = errors
        stats["success"] = len(critical_failures) == 0
        stats["elapsed_s"] = round(time.time() - start_time, 2)

        if critical_failures:
            failed_steps = ", ".join(e["step"] for e in critical_failures)
            logger.error(
                f"❌ Graph algorithms finished with critical failures: {failed_steps} "
                f"({stats['elapsed_s']}s)"
            )
        else:
            logger.info(f"✅ Graph algorithms complete in {stats['elapsed_s']}s")
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
            # URL-decode title to fix KVP section_path matching
            # (e.g., "BUILDERS%20LIMITED%20WARRANTY" -> "BUILDERS LIMITED WARRANTY")
            if isinstance(title, str):
                title = unquote(title)

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

        # ── Pair .result.json sidecars with their parent documents ────
        # When both "X.pdf" and "X.pdf.result.json" are uploaded, use the
        # pre-analyzed result for the PDF and drop the .result.json from
        # standalone processing to avoid duplicate content.
        all_url_set = set(url_inputs)

        # Detect .result.json sidecars (processed via DI deserializer)
        result_json_urls = {u for u in url_inputs if u.endswith(".result.json")}
        paired_redirects: Dict[str, str] = {}  # pdf_url -> result_json_url
        for rj_url in result_json_urls:
            parent_url = rj_url.removesuffix(".result.json")
            if parent_url in all_url_set:
                paired_redirects[parent_url] = rj_url
                logger.info(f"Paired .result.json sidecar: {rj_url.split('/')[-1]} → {parent_url.split('/')[-1]}")

        # Build effective URL list: replace paired PDFs with their .result.json,
        # drop .result.json entries that were paired (they'll run via the PDF entry)
        effective_urls: List[str] = []
        for u in url_inputs:
            if u in paired_redirects:
                effective_urls.append(paired_redirects[u])  # use .result.json for this PDF
            elif u in result_json_urls and u.removesuffix(".result.json") in paired_redirects:
                continue  # skip — already consumed as sidecar
            else:
                effective_urls.append(u)

        # Update normalized docs: rewrite source for paired PDFs so results map back
        source_remap: Dict[str, str] = {}  # result_json_url -> original_pdf_url
        for pdf_url, rj_url in paired_redirects.items():
            source_remap[rj_url] = pdf_url
        for doc in normalized:
            if doc.get("source") in result_json_urls and doc["source"].removesuffix(".result.json") in paired_redirects:
                # Mark paired .result.json docs as skip (they're sidecars, not standalone)
                doc["_skip_sidecar"] = True

        if ingestion != "document-intelligence" or not effective_urls:
            return normalized

        di_service = DocumentIntelligenceService()

        # F1: Share a single DI client across all URLs instead of creating
        # one client per URL via extract_documents(). Saves ~0.5-1s per doc
        # in HTTP client setup and Managed Identity token acquisition.
        by_source: Dict[str, List[LlamaDocument]] = {}

        t_di_start = time.perf_counter()
        async with di_service._create_client() as client:
            async def _analyze_one(url: str) -> None:
                max_di_retries = 2
                for attempt in range(max_di_retries):
                    try:
                        _result_url, docs, error = await di_service._analyze_single_document(
                            client, url, group_id, default_model="prebuilt-layout",
                            user_id=user_id,
                        )
                        if error:
                            if attempt < max_di_retries - 1:
                                logger.warning("DI extraction error for %s (attempt %d), retrying: %s", url.split("/")[-1], attempt + 1, error)
                                await asyncio.sleep(2 ** attempt)
                                continue
                            logger.warning("DI extraction failed for %s after %d attempts: %s", url.split("/")[-1], max_di_retries, error)
                        else:
                            target_url = source_remap.get(url, url)
                            by_source[target_url] = docs
                            logger.info("DI extracted %d units for %s", len(docs), url.split("/")[-1])
                        return
                    except Exception as exc:
                        if attempt < max_di_retries - 1:
                            logger.warning("DI extraction exception for %s (attempt %d), retrying: %s", url.split("/")[-1], attempt + 1, exc)
                            await asyncio.sleep(2 ** attempt)
                        else:
                            logger.warning("DI extraction failed for %s after %d attempts: %s", url.split("/")[-1], max_di_retries, exc)

            await asyncio.gather(*[_analyze_one(url) for url in effective_urls])
        await di_service.close()
        logger.info("⏱️ DI extraction: %.2fs for %d documents", time.perf_counter() - t_di_start, len(effective_urls))

        out: List[Dict[str, Any]] = []
        for doc in normalized:
            if doc.get("_skip_sidecar"):
                continue  # drop paired .result.json from output
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






    # ------------------------------------------------------------------
    # Direct sentence indexing
    # ------------------------------------------------------------------

    async def _index_sentences_direct(
        self,
        *,
        group_id: str,
        expanded_docs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract, embed, and persist Sentence nodes directly from documents.

        Replaces the old chunk pipeline (_chunk_document → _embed_chunks →
        upsert_text_chunks_batch → _build_sentence_skeleton) with a single
        step that goes DI units → spaCy → Sentence nodes.

        Returns stats dict with sentences_created, sentences_embedded, etc.
        """
        import sys as _sys
        logger.info("_index_sentences_direct: ENTERED (docs=%d)", len(expanded_docs))
        _sys.stderr.flush(); _sys.stdout.flush()

        from src.worker.services.sentence_extraction_service import (
            extract_sentences_from_di_units,
            extract_sentences_from_raw_text,
            _is_noise_sentence,
        )
        from src.worker.hybrid_v2.services.neo4j_store import Sentence

        logger.info("_index_sentences_direct: imports OK")
        _sys.stderr.flush(); _sys.stdout.flush()

        stats: Dict[str, Any] = {
            "sentences_created": 0,
            "sentences_embedded": 0,
            "documents_processed": 0,
        }

        all_raw_sentences: List[Dict[str, Any]] = []
        doc_title_map: Dict[str, str] = {}

        for doc in expanded_docs:
            doc_id = doc["id"]
            doc_title = doc.get("title", "Untitled")
            doc_source = doc.get("source", "")
            doc_title_map[doc_id] = doc_title

            di_units = doc.get("di_extracted_docs") or []
            if di_units:
                logger.info("_index_sentences_direct: extracting sentences doc=%s units=%d", doc_title, len(di_units))
                _sys.stderr.flush(); _sys.stdout.flush()
                raw = extract_sentences_from_di_units(
                    di_units, doc_id=doc_id,
                    doc_title=doc_title, doc_source=doc_source,
                )
            else:
                content = (doc.get("content") or doc.get("text") or "").strip()
                if not content:
                    continue
                raw = extract_sentences_from_raw_text(
                    content, doc_id=doc_id,
                    doc_title=doc_title, doc_source=doc_source,
                )

            all_raw_sentences.extend(raw)
            stats["documents_processed"] += 1

        if not all_raw_sentences:
            logger.info("index_sentences_direct: no sentences extracted")
            return stats

        # ── Optional LLM sentence-boundary review (bundled) ──────
        if settings.SKELETON_LLM_SENTENCE_REVIEW:
            from src.worker.services.sentence_extraction_service import (
                llm_review_sections_bundled,
            )
            # Group sentences by their section_path for bundled review
            section_order: List[str] = []
            section_sents: Dict[str, List[str]] = {}
            section_indices: Dict[str, List[int]] = {}
            for i, s in enumerate(all_raw_sentences):
                if s.get("source") != "paragraph":
                    continue
                key = f"{s['document_id']}|{s.get('section_path', '')}"
                if key not in section_sents:
                    section_order.append(key)
                    section_sents[key] = []
                    section_indices[key] = []
                section_sents[key].append(s["text"])
                section_indices[key].append(i)

            if section_sents:
                sections_input = [(k, section_sents[k]) for k in section_order]
                reviewed = llm_review_sections_bundled(sections_input)
                # Apply reviewed sentences back
                for key in section_order:
                    new_sents = reviewed.get(key, section_sents[key])
                    old_indices = section_indices[key]
                    if len(new_sents) == len(old_indices):
                        # Same count — update texts in place
                        for idx, new_text in zip(old_indices, new_sents):
                            all_raw_sentences[idx]["text"] = new_text
                    else:
                        # Count changed — rebuild section sentences
                        doc_id_sec = all_raw_sentences[old_indices[0]]["document_id"]
                        base = all_raw_sentences[old_indices[0]].copy()
                        new_entries = []
                        for j, new_text in enumerate(new_sents):
                            entry = base.copy()
                            entry["text"] = new_text
                            entry["id"] = f"{doc_id_sec}_sent_llm_{old_indices[0]}_{j}"
                            new_entries.append(entry)
                        # Replace old entries with new (mark old for removal, append new)
                        for idx in old_indices:
                            all_raw_sentences[idx] = None  # type: ignore[assignment]
                        all_raw_sentences.extend(new_entries)
                # Remove None entries from count-changed sections
                all_raw_sentences = [s for s in all_raw_sentences if s is not None]
                # Re-index index_in_doc
                for i, s in enumerate(all_raw_sentences):
                    s["index_in_doc"] = i
                logger.info(
                    "index_sentences_direct: LLM review applied to %d sections",
                    len(section_sents),
                )

        logger.info(
            "index_sentences_direct: extracted %d sentences from %d documents",
            len(all_raw_sentences), stats["documents_processed"],
        )

        # ── Post-LLM noise filter (paragraph sentences only) ──────────
        pre_filter_count = len(all_raw_sentences)
        all_raw_sentences = [
            s for s in all_raw_sentences
            if s.get("source") != "paragraph" or not _is_noise_sentence(s["text"])
        ]
        if len(all_raw_sentences) < pre_filter_count:
            # Re-index after filtering
            for i, s in enumerate(all_raw_sentences):
                s["index_in_doc"] = i
            logger.info(
                "index_sentences_direct: noise filter removed %d sentences (post-LLM)",
                pre_filter_count - len(all_raw_sentences),
            )

        # ── Embed with Voyage contextualized (per-document grouping) ──
        sentence_embeddings: List[Optional[List[float]]] = [None] * len(all_raw_sentences)

        def _build_label_prefix(s: Dict[str, Any]) -> str:
            title = doc_title_map.get(s.get("document_id", ""), "")
            sp = s.get("section_path", "")
            source = s.get("source", "paragraph")
            idx_sec = s.get("index_in_section", 0)
            total_sec = s.get("total_in_section", 0)
            parts: List[str] = []
            if title:
                parts.append(f"Document: {title}")
            if source == "signature_party":
                parts.append("Signature Block")
            elif source == "letterhead":
                parts.append("Letterhead")
            elif source == "page_header":
                parts.append("Page Header")
            elif source == "page_footer":
                parts.append("Page Footer")
            elif source == "table_row":
                parts.append(f"Table: {sp}" if sp else "Table")
            elif source == "table_caption":
                parts.append(f"Table Caption: {sp}" if sp else "Table Caption")
            elif source == "figure_caption":
                parts.append(f"Figure: {sp}" if sp else "Figure")
            elif sp:
                parts.append(f"Section: {sp}")
            if total_sec > 0:
                parts.append(f"Position: {idx_sec + 1}/{total_sec}")
            return f"[{' | '.join(parts)}] " if parts else ""

        try:
            from collections import OrderedDict
            doc_groups: OrderedDict[str, List[int]] = OrderedDict()
            for idx, s in enumerate(all_raw_sentences):
                doc_groups.setdefault(s.get("document_id", "unknown"), []).append(idx)

            document_chunks: List[List[str]] = []
            index_maps: List[List[int]] = []
            for did, indices in doc_groups.items():
                doc_texts = [
                    _build_label_prefix(all_raw_sentences[i]) + all_raw_sentences[i]["text"]
                    for i in indices
                ]
                document_chunks.append(doc_texts)
                index_maps.append(indices)

            logger.info(
                "index_sentences_direct: embedding %d documents, sentences=%s",
                len(document_chunks),
                [len(dc) for dc in document_chunks],
            )

            import asyncio
            from src.worker.hybrid_v2.embeddings.voyage_embed import get_voyage_embed_service
            voyage_svc = get_voyage_embed_service()
            loop = asyncio.get_event_loop()
            all_doc_embeddings = await loop.run_in_executor(
                None,
                lambda: voyage_svc.embed_documents_contextualized(document_chunks),
            )

            for doc_embs, orig_indices in zip(all_doc_embeddings, index_maps):
                for chunk_idx, orig_idx in enumerate(orig_indices):
                    emb = doc_embs[chunk_idx]
                    if emb and isinstance(emb, list) and len(emb) > 0:
                        sentence_embeddings[orig_idx] = emb

            stats["sentences_embedded"] = sum(1 for e in sentence_embeddings if e is not None)
            logger.info(
                "index_sentences_direct: embedded %d/%d sentences",
                stats["sentences_embedded"], len(all_raw_sentences),
            )
        except Exception as e:
            logger.exception("index_sentences_direct: embedding failed: %s", e)
            raise

        # ── Build Sentence dataclass instances ──
        sentence_objects: List[Sentence] = []
        for raw, emb in zip(all_raw_sentences, sentence_embeddings):
            # Build metadata dict with polygon geometry (if available from DI)
            sent_meta: Dict[str, Any] = {}
            if raw.get("polygons"):
                sent_meta["sentences"] = [{
                    "text": raw["text"],
                    "polygons": raw["polygons"],
                    "page": raw.get("page", 1),
                    "confidence": raw.get("confidence", 1.0),
                }]
            if raw.get("page_dimensions"):
                sent_meta["page_dimensions"] = raw["page_dimensions"]

            sentence_objects.append(Sentence(
                id=raw["id"],
                text=raw["text"],
                document_id=raw["document_id"],
                source=raw["source"],
                index_in_doc=raw.get("index_in_doc", 0),
                section_path=raw.get("section_path", ""),
                page=raw.get("page"),
                confidence=raw.get("confidence", 1.0),
                sentence_embedding=emb,
                tokens=raw.get("tokens", 0),
                parent_text=raw.get("parent_text"),
                index_in_section=raw.get("index_in_section", 0),
                total_in_section=raw.get("total_in_section", 0),
                metadata=sent_meta,
            ))

        # ── Persist in Neo4j ──
        count = self.neo4j_store.upsert_sentences_batch(group_id, sentence_objects)
        stats["sentences_created"] = count

        logger.info(
            "index_sentences_direct: persisted %d sentences",
            count,
        )
        return stats

    async def _build_section_graph_from_docs(
        self,
        group_id: str,
        expanded_docs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build Section graph directly from DI unit metadata.

        Replaces the chunk-based ``_build_section_graph`` for the new
        sentence-direct pipeline.  Creates the same Section node hierarchy
        and links Sentences (not TextChunks) to their leaf sections.
        """
        DEFAULT_ROOT_SECTION = "[Document Root]"
        all_sections: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for doc in expanded_docs:
            doc_id = doc["id"]
            di_units = doc.get("di_extracted_docs") or []
            if not di_units:
                # non-DI document — single root section
                key = (doc_id, DEFAULT_ROOT_SECTION)
                if key not in all_sections:
                    all_sections[key] = {
                        "id": self._stable_section_id(group_id, doc_id, DEFAULT_ROOT_SECTION),
                        "group_id": group_id,
                        "doc_id": doc_id,
                        "path_key": DEFAULT_ROOT_SECTION,
                        "title": DEFAULT_ROOT_SECTION,
                        "depth": 0,
                        "parent_path_key": None,
                    }
                continue

            for unit in di_units:
                meta = getattr(unit, "metadata", None) or {}
                section_path = self._parse_section_path(meta)
                if not section_path:
                    section_path = [DEFAULT_ROOT_SECTION]

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
                            "_first_seen_order": len(all_sections),
                        }

        if not all_sections:
            return {"sections_created": 0, "in_section_edges": 0}

        # Compute section_ordinal and hierarchical_id
        from collections import defaultdict as _defaultdict
        sibling_groups: Dict[tuple, list] = _defaultdict(list)
        for section in all_sections.values():
            parent = section.get("parent_path_key") or "__root__"
            sib_key = (section["doc_id"], parent)
            sibling_groups[sib_key].append(section)

        for siblings in sibling_groups.values():
            siblings.sort(key=lambda s: s.get("_first_seen_order", 0))
            for ordinal, section in enumerate(siblings, 1):
                section["section_ordinal"] = ordinal

        def _assign_h_ids(doc_id_val, parent_path_key=None, prefix=""):
            parent_key = parent_path_key or "__root__"
            children = sibling_groups.get((doc_id_val, parent_key), [])
            for child in children:
                h_id = str(child["section_ordinal"]) if not prefix else f"{prefix}.{child['section_ordinal']}"
                child["hierarchical_id"] = h_id
                _assign_h_ids(doc_id_val, child["path_key"], h_id)

        for did in set(s["doc_id"] for s in all_sections.values()):
            _assign_h_ids(did)

        for s in all_sections.values():
            s.pop("_first_seen_order", None)

        section_data = list(all_sections.values())

        def _write(session):
            # Create Section nodes
            result = session.run(
                """
                UNWIND $sections AS s
                MERGE (sec:Section {id: s.id, group_id: s.group_id})
                SET sec.group_id = s.group_id,
                    sec.doc_id = s.doc_id,
                    sec.path_key = s.path_key,
                    sec.section_path = s.path_key,
                    sec.title = s.title,
                    sec.depth = s.depth,
                    sec.section_ordinal = s.section_ordinal,
                    sec.hierarchical_id = s.hierarchical_id,
                    sec.updated_at = datetime()
                RETURN count(sec) AS count
                """,
                sections=section_data,
            )
            sections_created = result.single()["count"]

            # HAS_SECTION edges (Document → top-level Section)
            top_level = [
                {"doc_id": s["doc_id"], "section_id": s["id"]}
                for s in section_data if s["depth"] == 0
            ]
            if top_level:
                session.run(
                    """
                    UNWIND $edges AS e
                    MATCH (d:Document {id: e.doc_id, group_id: $group_id})
                    MATCH (s:Section {id: e.section_id, group_id: $group_id})
                    MERGE (d)-[:HAS_SECTION]->(s)
                    """,
                    edges=top_level, group_id=group_id,
                )

            # SUBSECTION_OF edges
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

            return sections_created

        sections_created = await self.neo4j_store.arun_in_session(_write)

        # Backfill IN_SECTION edges: upsert_sentences_batch (Step 3) runs
        # before Section nodes exist (Step 4), so it can't create them.
        # Create them now that both Sentence and Section nodes are committed.
        in_section_result = await self.neo4j_store.arun_query(
            """
            MATCH (sent:Sentence {group_id: $group_id})
            WHERE sent.section_path IS NOT NULL AND sent.section_path <> ''
            AND NOT (sent)-[:IN_SECTION]->(:Section)
            MATCH (sec:Section {group_id: $group_id})
            WHERE sec.doc_id = sent.document_id AND sec.section_path = sent.section_path
            MERGE (sent)-[:IN_SECTION]->(sec)
            RETURN count(*) AS created
            """,
            group_id=group_id,
        )
        in_section_edges = in_section_result[0]["created"] if in_section_result else 0

        logger.info(
            "section_graph_from_docs_built",
            extra={"group_id": group_id, "sections_created": sections_created, "in_section_edges": in_section_edges},
        )
        return {"sections_created": sections_created, "in_section_edges": in_section_edges}

    async def _assign_sentence_hierarchical_ids(self, group_id: str) -> Dict[str, Any]:
        """Post-processing: assign hierarchical_id to Sentence nodes.

        Computes full address (e.g., "2.1.3-S5") from Section.hierarchical_id
        and Sentence.index_in_section. Must run after both sentence upsert
        and section graph creation.
        """
        # Sentences linked to a section
        result = await self.neo4j_store.arun_query(
            """
            MATCH (sent:Sentence {group_id: $group_id})-[:IN_SECTION]->(sec:Section {group_id: $group_id})
            WHERE sec.hierarchical_id IS NOT NULL
            SET sent.hierarchical_id = sec.hierarchical_id + '-S' + toString(sent.index_in_section + 1)
            RETURN count(sent) AS updated
            """,
            group_id=group_id,
        )
        count = result[0]["updated"] if result else 0

        # Sentences with no section get a root-prefixed ID
        result2 = await self.neo4j_store.arun_query(
            """
            MATCH (sent:Sentence {group_id: $group_id})
            WHERE sent.hierarchical_id IS NULL OR sent.hierarchical_id = ''
            SET sent.hierarchical_id = '0-S' + toString(sent.index_in_section + 1)
            RETURN count(sent) AS updated
            """,
            group_id=group_id,
        )
        root_count = result2[0]["updated"] if result2 else 0

        logger.info(
            "sentence_hierarchical_ids_assigned",
            extra={"group_id": group_id, "assigned": count, "root_assigned": root_count},
        )
        return {"assigned": count + root_count}

    async def _backfill_section_total_sentences(self, group_id: str) -> Dict[str, Any]:
        """Backfill Section.total_sentences from IN_SECTION edge count."""
        result = await self.neo4j_store.arun_query(
            """
            MATCH (sec:Section {group_id: $group_id})
            OPTIONAL MATCH (s:Sentence)-[:IN_SECTION]->(sec)
            WITH sec, count(s) AS total
            SET sec.total_sentences = total
            RETURN count(sec) AS updated
            """,
            group_id=group_id,
        )
        count = result[0]["updated"] if result else 0
        logger.info(
            "section_total_sentences_backfilled",
            extra={"group_id": group_id, "updated": count},
        )
        return {"updated": count}

    async def _build_sentence_knn_edges(
        self,
        group_id: str,
    ) -> Dict[str, Any]:
        """Step 4.2: Build sparse RELATED_TO edges between sentence nodes.
        
        Phase 2 of skeleton enrichment. For each :Sentence with an embedding,
        finds its nearest cross-chunk neighbours via the vector index and creates
        RELATED_TO edges with strict thresholds:
          - similarity >= SKELETON_KNN_THRESHOLD (default 0.90)
          - max k = SKELETON_KNN_MAX_K (default 2) per sentence
          - cross-chunk only (same-chunk pairs already linked via NEXT)
        
        This is SEPARATE from GDS KNN (step 8), which operates on
        Entity/Figure/KVP/Chunk at a much lower threshold (0.60, k=5).
        Sentence k-NN is bounded to avoid graph pollution.
        """
        import numpy as np
        from collections import defaultdict
        
        from src.core.config import Settings
        settings = Settings()
        
        threshold = settings.SKELETON_KNN_THRESHOLD
        max_k = settings.SKELETON_KNN_MAX_K
        
        # Clean up stale RELATED_TO and SEMANTICALLY_SIMILAR edges from previous runs.
        # This ensures re-indexing doesn't leave orphan edges from changed/deleted sentences.
        result = await self.neo4j_store.arun_query(
            """
                MATCH (:Sentence {group_id: $group_id})-[r:RELATED_TO]->(:Sentence)
                WHERE r.source = 'knn_sentence' OR r.method = 'knn_sentence'
                DELETE r
                RETURN count(r) AS deleted
                """,
            group_id=group_id,
        )
        deleted = result.single()["deleted"]
        if deleted > 0:
            logger.info(f"step_4.2_cleanup: deleted {deleted} stale RELATED_TO edges")
        
        result = await self.neo4j_store.arun_query(
            """
                MATCH (:Sentence {group_id: $group_id})-[r:SEMANTICALLY_SIMILAR]->(:Sentence)
                WHERE r.method = 'knn_sentence'
                DELETE r
                RETURN count(r) AS deleted
                """,
            group_id=group_id,
        )
        sim_deleted = result.single()["deleted"]
        if sim_deleted > 0:
            logger.info(f"step_4.2_cleanup: deleted {sim_deleted} stale SEMANTICALLY_SIMILAR edges")
        
        # Fetch all sentences with embeddings for this group
        result = await self.neo4j_store.arun_query(
            """
                MATCH (s:Sentence {group_id: $group_id})
                WHERE s.sentence_embedding IS NOT NULL
                RETURN s.id AS id,
                       s.document_id AS document_id,
                       s.index_in_doc AS index_in_doc,
                       s.sentence_embedding AS embedding
                """,
            read_only=True,
            group_id=group_id,
        )
        sentences = [
            {
                "id": record["id"],
                "document_id": record["document_id"] or "",
                "index_in_doc": record["index_in_doc"] or 0,
                "embedding": record["embedding"],
            }
            for record in result
        ]
        
        if len(sentences) < 2:
            return {"edges_created": 0, "reason": "insufficient_sentences"}
        
        # Filter to consistent embedding dimensions (defensive: mixed dims crash np.array)
        if sentences:
            target_dim = len(sentences[0]["embedding"])
            filtered = [s for s in sentences if len(s["embedding"]) == target_dim]
            if len(filtered) < len(sentences):
                logger.warning(
                    f"step_4.2_sentence_knn: filtered {len(sentences) - len(filtered)} sentences "
                    f"with mismatched embedding dim (expected {target_dim})"
                )
                sentences = filtered
        
        if len(sentences) < 2:
            return {"edges_created": 0, "reason": "insufficient_sentences_after_dim_filter"}
        
        logger.info(f"step_4.2_sentence_knn: computing pairwise similarities for {len(sentences)} sentences "
                     f"(threshold={threshold}, max_k={max_k})")
        
        # Compute pairwise cosine similarities (cross-chunk only)
        # Use numpy for efficiency. With 181 sentences this is instant;
        # for larger corpora we'd switch to vector index queries.
        embeddings = np.array([s["embedding"] for s in sentences])
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        normalized = embeddings / norms
        sim_matrix = normalized @ normalized.T
        
        # Build edge candidates: cross-context, above threshold, max-k per node.
        # Skip adjacent sentences in same doc (already linked via NEXT edges).
        edge_count: Dict[str, int] = defaultdict(int)
        
        def _is_same_context(a: dict, b: dict) -> bool:
            """True when two sentences are too close to need a RELATED_TO edge."""
            if a["document_id"] == b["document_id"]:
                return abs(a["index_in_doc"] - b["index_in_doc"]) <= 1
            return False

        # For each sentence, find its top-k non-adjacent neighbours
        # Process by descending similarity to ensure we keep the best edges
        candidates = []
        for i in range(len(sentences)):
            row_candidates = []
            for j in range(len(sentences)):
                if i == j:
                    continue
                if _is_same_context(sentences[i], sentences[j]):
                    continue  # Too close — already linked via NEXT
                sim = float(sim_matrix[i, j])
                if sim >= threshold:
                    row_candidates.append((j, sim))
            
            # Sort by similarity descending, take top max_k
            row_candidates.sort(key=lambda x: x[1], reverse=True)
            for j, sim in row_candidates[:max_k]:
                candidates.append((i, j, sim))
        
        # Deduplicate: (i→j) and (j→i) are the same edge, keep highest sim
        seen_pairs: Dict[tuple, float] = {}
        for i, j, sim in candidates:
            key = (min(i, j), max(i, j))
            if key not in seen_pairs or sim > seen_pairs[key]:
                seen_pairs[key] = sim
        
        # Also enforce max_k from the target side
        # Build final edge list respecting max_k budget for both endpoints
        edge_count_final: Dict[str, int] = defaultdict(int)
        edges_to_create = []
        
        for (i, j), sim in sorted(seen_pairs.items(), key=lambda x: x[1], reverse=True):
            sid_i = sentences[i]["id"]
            sid_j = sentences[j]["id"]
            if edge_count_final[sid_i] >= max_k or edge_count_final[sid_j] >= max_k:
                continue
            edges_to_create.append({
                "source_id": sid_i,
                "target_id": sid_j,
                "similarity": round(sim, 4),
            })
            edge_count_final[sid_i] += 1
            edge_count_final[sid_j] += 1
        
        if not edges_to_create:
            logger.info(f"step_4.2_sentence_knn: no edges above threshold {threshold}")
            return {"edges_created": 0, "threshold": threshold}
        
        # Persist RELATED_TO edges in Neo4j (legacy, used by step 4.2 consumers)
        count = self.neo4j_store.create_sentence_related_to_edges(group_id, edges_to_create)
        
        # Also create SEMANTICALLY_SIMILAR edges so PPR can traverse them
        # (PPR loads SEMANTICALLY_SIMILAR for cross-document sentence connectivity)
        sim_count = self.neo4j_store.create_sentence_semantically_similar_edges(group_id, edges_to_create)
        
        logger.info(
            "step_4.2_sentence_knn_edges_created",
            extra={
                "group_id": group_id,
                "related_to_edges": count,
                "semantically_similar_edges": sim_count,
                "threshold": threshold,
                "max_k": max_k,
                "sentences_connected": len(edge_count_final),
                "total_sentences": len(sentences),
            },
        )
        
        return {
            "edges_created": count,
            "semantically_similar_edges": sim_count,
            "threshold": threshold,
            "max_k": max_k,
            "sentences_connected": len(edge_count_final),
            "total_sentences": len(sentences),
        }

    async def _extract_entities_and_relationships(
        self,
        *,
        group_id: str,
        chunks: Optional[list] = None,
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract entities and relationships from Sentence nodes.

        Pipeline (HippoRAG 2 aligned — OpenIE as primary extraction):
        1. Fetch all :Sentence nodes for this group_id from Neo4j.
        2. Classify each sentence (content / metadata / noise).
        3. Run OpenIE triple extraction — surface forms become Entity nodes.
        4. Build deterministic co-occurrence edges: if 2+ entities appear in the
           same sentence, create a RELATED_TO edge with the sentence as provenance.
        """
        if self.llm is None:
            return [], []

        # ── Step 1: Fetch sentences from Neo4j ──────────────────────────────
        raw_sentences = self.neo4j_store.get_sentences_by_group(group_id)
        if not raw_sentences:
            logger.warning("no Sentence nodes found for entity extraction, returning empty")
            return [], []

        # ── Step 2: Classify and filter ──────────────────────────────────────
        content_sentences = []
        classification_counts = {"content": 0, "metadata": 0, "noise": 0}
        for s in raw_sentences:
            cls = self._classify_sentence(s)
            classification_counts[cls] += 1
            if cls == "content":
                content_sentences.append(s)
        logger.info(
            "sentence_classification_complete",
            extra={
                "group_id": group_id,
                "total": len(raw_sentences),
                **classification_counts,
            },
        )
        if not content_sentences:
            logger.warning("sentence_extraction_no_content: all sentences filtered out")
            return [], []

        # ── Step 3: OpenIE triple extraction (HippoRAG 2 primary path) ──────
        # Surface forms from triples become Entity nodes (untyped, no descriptions).
        # Replaces schema-guided NER (native/LlamaIndex extractors).
        entities, relationships = await self._extract_openie_triples(
            group_id=group_id,
            content_sentences=content_sentences,
        )

        # ── Step 3b: Embed entities (name-only, for synonym detection) ────────
        # CRITICAL: Use aembed_independent_texts() so each entity name is embedded
        # as its own document. The default aget_text_embedding_batch() wraps all
        # names as chunks of ONE document, causing contextual bleed that destroys
        # pairwise similarity (e.g., cos drops from 0.93→0.54 with 252 entities).
        if entities and self.voyage_service:
            texts = [e.name for e in entities]
            for attempt in range(3):
                try:
                    embs = await self.voyage_service.aembed_independent_texts(texts)
                    for ent, emb in zip(entities, embs):
                        ent.entity_embedding = emb
                    logger.info(f"openie_entity_embeddings: {len(embs)} entities embedded (independent)")
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.warning("openie_entity_embedding attempt %d failed, retrying: %s", attempt + 1, e)
                        await asyncio.sleep(2 ** attempt)
                    else:
                        logger.error("openie_entity_embedding_failed after 3 attempts — entities committed without embeddings: %s", e)

        # Build a lookup of entities by canonical key for co-occurrence step
        entities_by_key: Dict[str, Entity] = {}
        for ent in entities:
            key = self._canonical_entity_key(ent.name)
            if key:
                entities_by_key[key] = ent

        # ── Step 4: Deterministic sentence-scoped co-occurrence edges ────────
        cooccurrence_rels: List[Relationship] = []
        for s in content_sentences:
            sid = s["id"]
            # Find entities that mention this sentence
            ents_in_sentence = [e for e in entities if sid in e.text_unit_ids]
            if len(ents_in_sentence) >= 2:
                for i, e1 in enumerate(ents_in_sentence):
                    for e2 in ents_in_sentence[i + 1:]:
                        cooccurrence_rels.append(
                            Relationship(
                                source_id=e1.id,
                                target_id=e2.id,
                                type="RELATED_TO",
                                description=s["text"][:200],
                                weight=1.0,
                            )
                        )
        # Merge: OpenIE relationships first (they have predicate descriptions),
        # then ALL co-occurrence edges. Neo4j's ON MATCH accumulates co-occurrence
        # counts so duplicate (source, target) pairs are intentional — they increase
        # edge weight for PPR signal strength.
        seen_pairs: set[tuple[str, str]] = set()
        merged_rels: List[Relationship] = []
        # OpenIE edges first — deduplicated to keep only the first edge per pair
        for r in relationships:
            pair = (r.source_id, r.target_id)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                merged_rels.append(r)
        # Co-occurrence edges: pass ALL through (even duplicates of OpenIE edges)
        merged_rels.extend(cooccurrence_rels)

        logger.info(
            "sentence_entity_extraction_complete",
            extra={
                "group_id": group_id,
                "entities": len(entities),
                "openie_relationships": len(relationships),
                "cooccurrence_relationships": len(cooccurrence_rels),
                "merged_relationships": len(merged_rels),
                "content_sentences": len(content_sentences),
            },
        )
        return entities, merged_rels

    # ────────────────────────────────────────────────────────────────────
    # Step 5b: Open-domain triple extraction (HippoRAG 2 alignment)
    # ────────────────────────────────────────────────────────────────────

    # Single-step prompt (fallback when OPENIE_TWO_STEP=false)
    _OPENIE_PROMPT = """Extract knowledge graph triples from the sentences below.

Rules:
1. Process EACH sentence [ID] independently — extract 2-5 triples per sentence.
2. Predicates MUST be short verb phrases (1-5 words). Examples: "warrants for", "is not transferable", "holds risk until", "disclaims", "shall indemnify".
3. Do NOT use the full sentence as a predicate.
4. Subjects and objects are named entities, key concepts, legal terms, dates, time periods, durations, or amounts.
5. Include abstract concepts as entities when present: warranties, liabilities, rights, obligations, limitations, conditions.
6. Extract ALL factual relationships from each sentence, not just the most obvious one.
7. Entity names MUST come from the sentence text — do NOT invent or hallucinate names not present in the source.

{sentences}

Return ONLY valid JSON (no markdown fences):
{{"triples": [
  {{"sid": "<sentence_id>", "s": "<subject>", "p": "<predicate>", "o": "<object>"}},
  ...
]}}"""

    # ── Two-step prompts (upstream HippoRAG 2 alignment) ────────────
    # Step 1: NER — "broad" includes abstract concepts, "narrow" matches upstream HippoRAG 2
    _NER_PROMPT_BROAD = """Your task is to extract named entities from the given sentences.
Extract: proper nouns, organizations, people, dates, time periods, deadlines, durations (e.g., "10 business days", "90-day period"), amounts, legal terms, AND abstract concepts (warranties, liabilities, rights, obligations, limitations, conditions, terms).
Respond with a JSON list of entities.

{sentences}

Return ONLY valid JSON (no markdown fences):
{{"named_entities": [...]}}"""

    _NER_PROMPT_NARROW = """Your task is to extract named entities from the given sentences.
Extract: proper nouns, organizations, people, locations, dates, time periods, deadlines, durations (e.g., "10 business days", "90-day period"), amounts, legal terms.
Respond with a JSON list of entities.

{sentences}

Return ONLY valid JSON (no markdown fences):
{{"named_entities": [...]}}"""

    # Step 2: NER-conditioned triple extraction — upstream constraint + our proven rules
    _TRIPLE_PROMPT = """Construct an RDF knowledge graph from the sentences below using the provided named entities.

Rules:
1. Process EACH sentence [ID] independently — extract 2-5 triples per sentence.
2. Each triple MUST contain at least one, preferably two, of the named entities.
3. Predicates MUST be short verb phrases (1-5 words). Examples: "warrants for", "is not transferable", "holds risk until", "disclaims", "shall indemnify".
4. Do NOT use the full sentence as a predicate.
5. Clearly resolve pronouns to their specific names to maintain clarity.
6. Extract ALL factual relationships from each sentence, not just the most obvious one.

Named entities: {named_entities}

{sentences}

Return ONLY valid JSON (no markdown fences):
{{"triples": [
  {{"sid": "<sentence_id>", "s": "<subject>", "p": "<predicate>", "o": "<object>"}},
  ...
]}}"""

    @staticmethod
    def _leaf_section_title(section_path: str) -> str:
        """Extract the leaf section title from a ' > ' delimited path."""
        if not section_path:
            return ""
        return section_path.split(" > ")[-1].strip()

    @staticmethod
    def _section_context_prefix(section_path: str) -> str:
        """Build a context prefix line for an OpenIE batch."""
        if not section_path:
            return ""
        if section_path == "[Signature Block]":
            return "Signature Block:\n\n"
        if section_path == "[Letterhead]":
            return "Letterhead:\n\n"
        if section_path in ("[Page Footer]", "[Page Header]"):
            return ""
        title = section_path.split(" > ")[-1].strip()
        return f"Section: {title}\n\n" if title else ""

    # ── Deterministic triple extraction for structured elements ──────

    _SIG_ROLE_PATTERN = re.compile(
        r'\b(CEO|CFO|COO|CTO|CIO|CMO|President|Vice\s*President|VP|'
        r'Director|Manager|Officer|Partner|Attorney|Counsel|'
        r'Secretary|Treasurer|Representative|Agent|Broker|'
        r'Supervisor|Superintendent|Inspector|Engineer|Architect|'
        r'Authorized\s+(?:Signatory|Representative|Agent)|'
        # German titles
        r'Geschäftsführer(?:in)?|Vorstand(?:svorsitzende[r]?)?|Prokurist(?:in)?|'
        r'Bevollmächtigte[r]?|Handlungsbevollmächtigte[r]?|'
        r'Aufsichtsratsvorsitzende[r]?|Gesellschafter(?:in)?)\b',
        re.IGNORECASE,
    )
    _DATE_PATTERN = re.compile(
        r'\b(?:'
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December'
        r'|Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)'
        r'\s+\d{1,2},?\s+\d{4}'
        r'|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
        r'|\d{4}[/-]\d{1,2}[/-]\d{1,2}'
        r'|\d{1,2}\.\d{1,2}\.\d{4}'
        r')\b',
        re.IGNORECASE,
    )

    def _extract_deterministic_triples(
        self,
        sentences: List[Dict[str, Any]],
        group_id: str,
    ) -> Tuple[List[Dict[str, str]], int]:
        """Extract triples from structured elements (signature, letterhead) using rules.

        Returns (raw_triples, count) in the same format as LLM triples:
        [{"sid": ..., "s": ..., "p": ..., "o": ...}, ...]

        All subject/object names in returned triples carry a "_det" flag
        so the caller can mark them as dedup-protected.
        """
        triples: List[Dict[str, str]] = []

        for s in sentences:
            sid = s["id"]
            text = s.get("text", "")
            source = s.get("source", "")

            if source == "signature_party":
                triples.extend(self._deterministic_signature_triples(sid, text))
            elif source == "letterhead":
                triples.extend(self._deterministic_letterhead_triples(sid, text))
            elif source == "signature_block":
                triples.extend(self._deterministic_signature_block_triples(sid, text))

        # Tag all deterministic triples so entities from them are dedup-protected
        for t in triples:
            t["_det"] = "1"

        return triples, len(triples)

    def _deterministic_signature_triples(
        self, sid: str, text: str
    ) -> List[Dict[str, str]]:
        """Parse joined signature text into triples.

        Input example: "John Smith. CEO. December 15, 2025"
        Output: [{"sid": ..., "s": "john smith", "p": "signed as", "o": "ceo"}, ...]
        """
        parts = [p.strip() for p in text.split(". ") if p.strip()]
        if not parts:
            return []

        triples: List[Dict[str, str]] = []
        name = None
        role = None
        date = None

        for part in parts:
            if self._DATE_PATTERN.search(part):
                date = part
            elif self._SIG_ROLE_PATTERN.search(part):
                role = part
            elif name is None:
                name = part
            # Additional name-like parts after first are ignored

        if not name:
            return []

        if role:
            triples.append({"sid": sid, "s": name, "p": "signed as", "o": role})
        if date:
            triples.append({"sid": sid, "s": name, "p": "signed on", "o": date})
        if not role and not date:
            # Fallback: at least record the signer
            triples.append({"sid": sid, "s": name, "p": "is", "o": "signatory"})

        return triples

    # Regex for organization suffixes in signature blocks
    _ORG_SUFFIX_RE = re.compile(
        r'\b(?:Inc|LLC|Ltd|Corp|Co|LP|LLP|Association|Foundation|Group|Partners'
        r'|GmbH|AG|KG|OHG|GbR|eG|e\.V|SE|UG|KGaA)'
        r'\.?\s*$',
        re.IGNORECASE,
    )

    def _deterministic_signature_block_triples(
        self, sid: str, text: str
    ) -> List[Dict[str, str]]:
        """Parse multiline signature block into triples.

        Signature blocks contain party names (orgs), roles, and dates on
        separate lines.  We extract organization names deterministically
        so that entities like "Fabrikam Inc." are never missed due to LLM
        non-determinism.

        Lines are classified as:
        - org: matches _ORG_SUFFIX_RE (possibly after stripping prefixes)
        - date: matches _DATE_PATTERN
        - skip: parenthesized roles like (Buyer/Owner), labels like "Date:"
        """
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            return []

        triples: List[Dict[str, str]] = []
        orgs_seen: set = set()
        orgs: List[str] = []
        dates: List[str] = []

        for line in lines:
            # Skip pure labels like "Date:", "By:", "(Buyer/Owner)", "Title"
            if re.match(r'^\(.*\)$', line):
                continue
            if re.match(r'^(?:Date|Title|By)\s*:\s*$', line, re.IGNORECASE):
                continue

            # Strip common prefixes to expose org name
            remainder = re.sub(
                r'^(?:By\s*:?\s*|Authorized\s+Representative\s+|'
                r"(?:Pumper's|Owner's|Owner\(s\))\s+\S+(?:\s+\(\S+\))?\s+|"
                r'AGENT\s*:\s*)',
                '', line, flags=re.IGNORECASE,
            ).strip()

            if self._ORG_SUFFIX_RE.search(remainder):
                norm = remainder.lower()
                if norm not in orgs_seen:
                    orgs_seen.add(norm)
                    orgs.append(remainder)
            elif self._DATE_PATTERN.search(line):
                # Extract just the date portion
                m = self._DATE_PATTERN.search(line)
                if m:
                    dates.append(m.group(0))

        # Deduplicate dates
        dates = list(dict.fromkeys(dates))

        # Emit triples: each org "signed" the document
        for org in orgs:
            triples.append({"sid": sid, "s": org, "p": "signed", "o": "document"})
            for date in dates:
                triples.append({"sid": sid, "s": org, "p": "signed on", "o": date})

        # Cross-link organizations as co-signatories
        for i, org_a in enumerate(orgs):
            for org_b in orgs[i + 1:]:
                triples.append({"sid": sid, "s": org_a, "p": "co signed with", "o": org_b})

        return triples

    def _deterministic_letterhead_triples(
        self, sid: str, text: str
    ) -> List[Dict[str, str]]:
        """Parse joined letterhead text into triples.

        Input example: "SolarTech Inc. 123 Main Street. San Francisco, CA 94102. (800) 555-0100"
        Output: [{"sid": ..., "s": "solartech inc", "p": "located at", "o": "123 main street ..."}, ...]
        """
        parts = [p.strip() for p in text.split(". ") if p.strip()]
        if not parts:
            return []

        triples: List[Dict[str, str]] = []
        company = parts[0]  # First part is typically the company name

        # Collect address parts, phone, email
        address_parts: List[str] = []
        phone = None
        email = None
        website = None

        for part in parts[1:]:
            if re.match(r'[\(\+]?\d[\d\s\-\(\)]{6,}', part):
                phone = part
            elif '@' in part:
                email = part
            elif re.match(r'(?:www\.|https?://)', part, re.IGNORECASE):
                website = part
            else:
                address_parts.append(part)

        if address_parts:
            addr = ", ".join(address_parts)
            triples.append({"sid": sid, "s": company, "p": "located at", "o": addr})
        if phone:
            triples.append({"sid": sid, "s": company, "p": "has phone", "o": phone})
        if email:
            triples.append({"sid": sid, "s": company, "p": "has email", "o": email})
        if website:
            triples.append({"sid": sid, "s": company, "p": "has website", "o": website})
        if not triples:
            # Fallback: at least record the company as an entity
            triples.append({"sid": sid, "s": company, "p": "is", "o": "organization"})

        return triples

    # ── Main OpenIE extraction method ────────────────────────────────

    async def _extract_openie_triples(
        self,
        *,
        group_id: str,
        content_sentences: Optional[List[Dict[str, Any]]] = None,
        existing_entities: Optional[List[Entity]] = None,
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Primary OpenIE extraction (HippoRAG 2 alignment).

        Extracts (subject, predicate, object) triples from each sentence.
        Subjects and objects become Entity nodes (untyped surface forms).
        Predicates become RELATED_TO edge descriptions.

        Supports two batching modes (env OPENIE_BATCHING):
        - "section": group by (document_id, section_path) with title prefix
        - "sequential": legacy 5-sentence sequential batches

        Supports two structured extraction modes (env STRUCTURED_EXTRACTION):
        - "deterministic": rules for signature_party / letterhead sentences
        - "llm": send all content sentences to OpenIE LLM

        Returns entities and relationships to merge before dedup (step 6).
        """
        import asyncio
        import json as json_mod
        from llama_index.core.llms import ChatMessage

        if content_sentences is None:
            raw_sentences = self.neo4j_store.get_sentences_by_group(group_id)
            content_sentences = [
                s for s in raw_sentences if self._classify_sentence(s) == "content"
            ]
        if not content_sentences:
            return [], []

        all_raw_triples: List[Dict[str, str]] = []
        deterministic_count = 0

        # ── Route structured sentences to deterministic or LLM path ──
        _STRUCTURED_SOURCES = {"signature_party", "letterhead", "signature_block"}
        if self._structured_extraction == "deterministic":
            structured = [s for s in content_sentences if s.get("source") in _STRUCTURED_SOURCES]
            llm_sentences = [s for s in content_sentences if s.get("source") not in _STRUCTURED_SOURCES]
            if structured:
                det_triples, deterministic_count = self._extract_deterministic_triples(structured, group_id)
                all_raw_triples.extend(det_triples)
                logger.info(
                    "deterministic_extraction_done",
                    extra={
                        "group_id": group_id,
                        "structured_sentences": len(structured),
                        "deterministic_triples": deterministic_count,
                    },
                )
        else:
            llm_sentences = content_sentences

        # ── Build batches for LLM OpenIE ─────────────────────────────
        if self._openie_batching == "section":
            batches = self._build_section_batches(llm_sentences)
        else:
            # Legacy sequential batching
            BATCH_SIZE = 5
            batches = [
                (llm_sentences[i : i + BATCH_SIZE], "")
                for i in range(0, len(llm_sentences), BATCH_SIZE)
            ]

        logger.info(
            "openie_batching",
            extra={
                "group_id": group_id,
                "mode": self._openie_batching,
                "structured_mode": self._structured_extraction,
                "two_step": self._openie_two_step,
                "llm_sentences": len(llm_sentences),
                "batches": len(batches),
                "deterministic_triples": deterministic_count,
            },
        )

        sem = asyncio.Semaphore(settings.OPENIE_LLM_CONCURRENCY)

        def _strip_json_fences(text: str) -> str:
            """Remove markdown code fences from LLM JSON response."""
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[: -3].rstrip()
            if text.startswith("json"):
                text = text[4:].lstrip()
            return text

        async def _extract_batch(batch: List[Dict[str, Any]], context: str) -> List[Dict[str, str]]:
            """Single-step OpenIE extraction (fallback)."""
            sentence_block = context + "\n".join(
                f"[{s['id']}]: {s['text']}" for s in batch
            )
            prompt = self._OPENIE_PROMPT.format(sentences=sentence_block)
            async with sem:
                try:
                    response = await self._achat_with_retry(
                        [ChatMessage(role="user", content=prompt)]
                    )
                    text = _strip_json_fences(response.message.content)
                    parsed = json_mod.loads(text)
                    return parsed.get("triples", [])
                except Exception as e:
                    logger.warning("OpenIE batch failed (triples lost): %s", e)
                    return []

        async def _extract_batch_two_step(batch: List[Dict[str, Any]], context: str) -> List[Dict[str, str]]:
            """Two-step NER→Triple extraction (upstream HippoRAG 2 alignment).

            Step 1: NER — extract named entities from the sentence batch.
            Step 2: Triple extraction — conditioned on the NER entity list.

            Both steps share a single semaphore slot to avoid double-booking.
            """
            sentence_block = context + "\n".join(
                f"[{s['id']}]: {s['text']}" for s in batch
            )

            async with sem:
                # Step 1: NER (scope-dependent prompt)
                ner_template = self._NER_PROMPT_NARROW if self._ner_scope == "narrow" else self._NER_PROMPT_BROAD
                ner_prompt = ner_template.format(sentences=sentence_block)
                try:
                    ner_response = await self._achat_with_retry(
                        [ChatMessage(role="user", content=ner_prompt)]
                    )
                    ner_text = _strip_json_fences(ner_response.message.content)
                    ner_parsed = json_mod.loads(ner_text)
                    named_entities = ner_parsed.get("named_entities", [])
                except Exception as e:
                    logger.warning("NER step failed (falling back to single-step): %s", e)
                    named_entities = []

                if not named_entities:
                    # Fallback to single-step if NER produces nothing
                    # (release this slot, _extract_batch will re-acquire)
                    pass
                else:
                    # Step 2: NER-conditioned triple extraction (same semaphore slot)
                    entities_str = json_mod.dumps(named_entities)
                    triple_prompt = self._TRIPLE_PROMPT.format(
                        named_entities=entities_str, sentences=sentence_block
                    )
                    try:
                        triple_response = await self._achat_with_retry(
                            [ChatMessage(role="user", content=triple_prompt)]
                        )
                        triple_text = _strip_json_fences(triple_response.message.content)
                        parsed = json_mod.loads(triple_text)
                        return parsed.get("triples", [])
                    except Exception as e:
                        logger.warning("Triple extraction step failed (triples lost): %s", e)
                        return []

            # NER produced nothing — fall back to single-step (outside the sem block)
            if not named_entities:
                return await _extract_batch(batch, context)

        # Choose extraction function based on two-step flag
        extract_fn = _extract_batch_two_step if self._openie_two_step else _extract_batch

        if batches:
            results = await asyncio.gather(*[extract_fn(b, ctx) for b, ctx in batches])
            for batch_triples in results:
                all_raw_triples.extend(batch_triples)

        if not all_raw_triples:
            return [], []

        # ── Build entities from triple surface forms ──────────────────
        # Each unique subject/object becomes an Entity node (untyped).
        # Track which sentences mention each entity (for MENTIONS edges).
        #
        # Upstream HippoRAG 2 applies text_processing() to all entity text:
        #   re.sub('[^A-Za-z0-9 ]', ' ', text.lower()).strip()
        # and filters entities where alphanumeric length ≤ 2.
        import re as _re

        def _text_processing(text: str) -> str:
            """Upstream HippoRAG 2 text normalization (with multi-space collapse).
            Uses Unicode-aware \\w to preserve extended Latin chars (ä, ö, ü, ß, etc.)."""
            cleaned = _re.sub(r'[^\w ]', ' ', text.lower())
            return _re.sub(r' +', ' ', cleaned).strip()

        def _is_valid_entity(name: str) -> bool:
            """Filter garbage entities (upstream: len(alphanumeric) > 2).
            Uses Unicode-aware matching so 'Müller' counts all letters."""
            return len(_re.sub(r'[^\w]', '', name)) > 2

        entity_map: Dict[str, Entity] = {}       # canonical_key → Entity
        entity_sids: Dict[str, set] = {}          # canonical_key → set of sentence IDs
        deterministic_keys: set = set()            # keys from deterministic extraction (dedup-protected)

        openie_rels: List[Relationship] = []
        skipped_garbage = 0

        for t in all_raw_triples:
            subj = _text_processing((t.get("s") or "").strip())
            pred = (t.get("p") or "").strip()
            obj = _text_processing((t.get("o") or "").strip())
            sid = (t.get("sid") or "").strip()
            is_det = t.get("_det") == "1"

            if not subj or not pred or not obj:
                continue
            # Filter garbage entities (≤2 alphanumeric chars)
            if not _is_valid_entity(subj) or not _is_valid_entity(obj):
                skipped_garbage += 1
                continue

            subj_key = self._canonical_entity_key(subj)
            obj_key = self._canonical_entity_key(obj)
            if not subj_key or not obj_key or subj_key == obj_key:
                continue

            # Track deterministic entity keys (protected from dedup merge-away)
            if is_det:
                deterministic_keys.add(subj_key)
                deterministic_keys.add(obj_key)

            # Create or update subject entity
            if subj_key not in entity_map:
                entity_map[subj_key] = Entity(
                    id=self._stable_entity_id(group_id, subj_key),
                    name=subj,
                    type="CONCEPT",
                    description=None,
                    text_unit_ids=[],
                )
                entity_sids[subj_key] = set()
            if sid:
                entity_sids[subj_key].add(sid)

            # Create or update object entity
            if obj_key not in entity_map:
                entity_map[obj_key] = Entity(
                    id=self._stable_entity_id(group_id, obj_key),
                    name=obj,
                    type="CONCEPT",
                    description=None,
                    text_unit_ids=[],
                )
                entity_sids[obj_key] = set()
            if sid:
                entity_sids[obj_key].add(sid)

            # Create RELATED_TO edge
            openie_rels.append(
                Relationship(
                    source_id=entity_map[subj_key].id,
                    target_id=entity_map[obj_key].id,
                    type="RELATED_TO",
                    description=pred,
                    weight=1.0,
                )
            )

        # Assign sentence IDs to entities for MENTIONS edges.
        # Upstream HippoRAG 2 add_passage_edges() links each passage ONLY to
        # entities from its OWN triples — no cross-passage text matching.
        for key, ent in entity_map.items():
            ent.text_unit_ids = list(entity_sids.get(key, set()))
            # Mark deterministic entities for dedup protection
            if key in deterministic_keys:
                if not ent.metadata:
                    ent.metadata = {}
                ent.metadata["deterministic"] = True

        entities = list(entity_map.values())

        logger.info(
            "openie_extraction_done",
            extra={
                "group_id": group_id,
                "sentences_processed": len(content_sentences),
                "llm_sentences": len(llm_sentences),
                "raw_triples": len(all_raw_triples),
                "deterministic_triples": deterministic_count,
                "entities_created": len(entities),
                "relationships_created": len(openie_rels),
                "mentions_from_triples": sum(len(entity_sids.get(k, set())) for k in entity_map),
                "skipped_garbage_entities": skipped_garbage,
                "batching_mode": self._openie_batching,
                "structured_mode": self._structured_extraction,
                "two_step": self._openie_two_step,
            },
        )
        return entities, openie_rels

    def _build_section_batches(
        self, sentences: List[Dict[str, Any]]
    ) -> List[Tuple[List[Dict[str, Any]], str]]:
        """Group sentences by (document_id, section_path) with context prefix.

        Ported from the native extractor's section-aware batching pattern
        (see _extract_with_native_extractor_sentences).

        Large sections (>MAX_SECTION_BATCH) are split into sub-batches.
        """
        from itertools import groupby as _groupby

        MAX_SECTION_BATCH = 15

        def _section_key(s: Dict[str, Any]) -> Tuple[str, str]:
            return (s.get("document_id", ""), s.get("section_path", ""))

        batches: List[Tuple[List[Dict[str, Any]], str]] = []
        for (_doc_id, _sec_path), grp in _groupby(sentences, key=_section_key):
            section_sents = list(grp)
            context = self._section_context_prefix(_sec_path)

            # Split into MAX_SECTION_BATCH-sized sub-batches
            for i in range(0, len(section_sents), MAX_SECTION_BATCH):
                batches.append((section_sents[i:i + MAX_SECTION_BATCH], context))

        return batches


    async def _extract_with_native_extractor_sentences(
        self,
        group_id: str,
        sentences: List[Dict[str, Any]],
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract entities from Sentence nodes using native neo4j-graphrag extractor.

        Batches sentences into groups of 6, respecting section boundaries so
        that sentences from different document sections are never mixed in the
        same batch.  The first sentence of every non-first batch gets a
        [Context] prefix with the previous sentence for anaphora resolution.

        Entity text_unit_ids point to Sentence IDs.
        """
        from itertools import groupby
        from src.core.config import settings

        BATCH_SIZE = 6
        logger.info(f"Using native extractor on {len(sentences)} content sentences (batch_size={BATCH_SIZE})")

        # Create neo4j-graphrag LLM
        llm_kwargs = {
            "model_name": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
            "api_version": settings.AZURE_OPENAI_API_VERSION or "2024-02-01",
        }
        if settings.AZURE_OPENAI_API_KEY:
            llm_kwargs["api_key"] = settings.AZURE_OPENAI_API_KEY
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential,
                "https://cognitiveservices.azure.com/.default"
            )
            llm_kwargs["azure_ad_token_provider"] = token_provider

        native_llm = AzureOpenAILLM(**llm_kwargs)
        extractor = LLMEntityRelationExtractor(
            llm=native_llm,
            create_lexical_graph=True,
            max_concurrency=4,
        )
        entity_schema = self._build_extraction_schema()

        # ── Section-boundary-aware batching with anaphora context ────
        # Group sentences by (document_id, section_path) so that batches
        # never cross section boundaries.  For the first sentence of each
        # non-first batch within a section, prepend the previous sentence
        # as [Context] to help the LLM resolve pronouns / anaphora.
        def _section_key(s: Dict[str, Any]) -> Tuple[str, str]:
            return (s["document_id"], s.get("section_path", ""))

        section_groups: List[Tuple[Tuple[str, str], List[Dict[str, Any]]]] = []
        for key, grp in groupby(sentences, key=_section_key):
            section_groups.append((key, list(grp)))

        # Build batches within each section group
        batches: List[Tuple[List[Dict], str, str]] = []  # (sentence_list, batch_uid, batch_text)
        context_sentence_map: Dict[str, Optional[Dict]] = {}  # batch_uid → context sentence (if any)
        for (_doc_id, _sec_path), section_sents in section_groups:
            for i in range(0, len(section_sents), BATCH_SIZE):
                batch = section_sents[i:i + BATCH_SIZE]
                batch_uid = "|".join(s["id"] for s in batch)

                # Cross-batch anaphora: prepend previous sentence as context
                context_sent: Optional[Dict] = None
                if i > 0:
                    context_sent = section_sents[i - 1]
                    context_prefix = f"[Context] {context_sent['text']}\n"
                else:
                    context_prefix = ""

                batch_text = context_prefix + "\n".join(
                    s["text"] for s in batch
                )
                batches.append((batch, batch_uid, batch_text))
                context_sentence_map[batch_uid] = context_sent

        logger.info(
            f"Section-aware batching: {len(section_groups)} section groups "
            f"→ {len(batches)} batches"
        )

        native_chunks = []
        batch_sentence_map: Dict[str, List[Dict]] = {}  # batch_uid → sentence list
        for batch, batch_uid, batch_text in batches:
            native_chunks.append(NativeTextChunk(
                text=batch_text,
                index=len(native_chunks),
                metadata={"sentence_ids": [s["id"] for s in batch]},
                uid=batch_uid,
            ))
            batch_sentence_map[batch_uid] = batch

        text_chunks = TextChunks(chunks=native_chunks)

        # Run extraction
        graph = await extractor.run(
            chunks=text_chunks,
            schema=entity_schema,
            examples=self._get_extraction_examples(),
        )

        logger.info(f"Native extractor produced {len(graph.nodes)} nodes, {len(graph.relationships)} relationships from sentences")

        # Convert graph nodes → Entity objects with sentence-based text_unit_ids
        batch_uids: set[str] = {uid for _, uid, _ in batches}
        entity_id_map: Dict[str, str] = {}  # native_node_id → stable entity id
        entities_by_id: Dict[str, Entity] = {}

        def _normalize_labels(n: Any) -> List[str]:
            labels = getattr(n, "labels", None)
            if labels:
                return [str(x) for x in labels if x]
            label = getattr(n, "label", None)
            return [str(label)] if label else []

        for node in graph.nodes:
            node_labels = _normalize_labels(node)
            if not node_labels or any(l in ("Chunk", "TextChunk", "Sentence") for l in node_labels):
                continue

            props = getattr(node, "properties", None) or {}
            if not isinstance(props, dict):
                props = {}

            name = (props.get("name") or getattr(node, "name", "") or "").strip()
            native_id = str(getattr(node, "id", None) or getattr(node, "node_id", None) or "").strip()
            if not name:
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
                raw_aliases = props.get("aliases", [])
                if isinstance(raw_aliases, str):
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
                    entity_embedding=None,
                    metadata=props,
                    text_unit_ids=[],
                    aliases=aliases_list,
                )

        # Recover mentions → map to Sentence IDs (not chunk IDs)
        # Uses fuzzy matching (name + aliases + word subsequences) instead
        # of naive substring to avoid sparse MENTIONS edges that break PPR.
        mentions_total = 0
        # Track which batches each entity was extracted from, so we can
        # fall back to batch-level attribution if fuzzy matching still misses.
        entity_source_batches: Dict[str, List[str]] = {}  # ent_id → [batch_uid, ...]
        for rel in graph.relationships:
            start_id = str(getattr(rel, "start_node_id", "") or "")
            end_id = str(getattr(rel, "end_node_id", "") or "")
            if not start_id or not end_id:
                continue

            # batch_uid → entity (lexical graph creates chunk→entity links)
            batch_uid: Optional[str] = None
            ent: Optional[Entity] = None
            if start_id in batch_uids and end_id in entity_id_map:
                batch_uid = start_id
                ent = entities_by_id.get(entity_id_map[end_id])
            elif end_id in batch_uids and start_id in entity_id_map:
                batch_uid = end_id
                ent = entities_by_id.get(entity_id_map[start_id])

            if batch_uid is None or ent is None:
                continue

            entity_source_batches.setdefault(ent.id, [])
            if batch_uid not in entity_source_batches[ent.id]:
                entity_source_batches[ent.id].append(batch_uid)

            for s in batch_sentence_map.get(batch_uid, []):
                if s["id"] not in ent.text_unit_ids and _entity_mentioned_in_text(ent.name, ent.aliases, s["text"]):
                    ent.text_unit_ids.append(s["id"])
                    mentions_total += 1

        # Batch-level attribution fallback: if an entity was extracted from
        # a batch but fuzzy matching found zero sentence-level mentions,
        # check whether the entity came from the [Context] prefix.  If so,
        # attribute it to the context sentence instead of blindly assigning
        # all batch sentences (which would create wrong MENTIONS edges).
        batch_fallback_count = 0
        context_redirect_count = 0
        for ent in entities_by_id.values():
            if ent.text_unit_ids:
                continue
            source_batches = entity_source_batches.get(ent.id, [])
            for b_uid in source_batches:
                # Check if entity came from the [Context] prefix
                ctx_sent = context_sentence_map.get(b_uid)
                if ctx_sent and _entity_mentioned_in_text(ent.name, getattr(ent, "aliases", []) or [], ctx_sent["text"]):
                    if ctx_sent["id"] not in ent.text_unit_ids:
                        ent.text_unit_ids.append(ctx_sent["id"])
                        context_redirect_count += 1
                else:
                    # True batch fallback — entity not from context
                    for s in batch_sentence_map.get(b_uid, []):
                        if s["id"] not in ent.text_unit_ids:
                            ent.text_unit_ids.append(s["id"])
                            batch_fallback_count += 1

        # Global fallback: for entities never found in any batch relationship,
        # do a fuzzy text match across all content sentences
        global_fallback_count = 0
        for ent in entities_by_id.values():
            if not ent.text_unit_ids:
                for s in sentences:
                    if _entity_mentioned_in_text(ent.name, ent.aliases, s["text"]):
                        ent.text_unit_ids.append(s["id"])
                        global_fallback_count += 1

        total_mentions = mentions_total + batch_fallback_count + context_redirect_count + global_fallback_count
        if total_mentions == 0:
            logger.warning("native_sentence_extractor_no_mentions_recovered",
                           extra={"group_id": group_id, "sentences": len(sentences), "entities": len(entities_by_id)})
        else:
            logger.info(
                f"MENTIONS recovery: {mentions_total} fuzzy-matched, "
                f"{context_redirect_count} context-redirected, "
                f"{batch_fallback_count} batch-fallback, "
                f"{global_fallback_count} global-fallback"
            )

        # Convert entity→entity relationships
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

        entities = list(entities_by_id.values())

        # Embeddings for entities — name-only, independently embedded (HippoRAG 2)
        if entities and self.voyage_service:
            texts = [e.name for e in entities]
            for attempt in range(3):
                try:
                    embs = await self.voyage_service.aembed_independent_texts(texts)
                    for ent, emb in zip(entities, embs):
                        ent.entity_embedding = emb
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.warning("sentence_entity_embedding attempt %d failed, retrying: %s", attempt + 1, e)
                        await asyncio.sleep(2 ** attempt)
                    else:
                        logger.error("sentence_entity_embedding_failed after 3 attempts: %s", e)

        logger.info(f"Sentence-based native extraction: {len(entities)} entities, {len(relationships)} relationships, {mentions_total} mention links")
        return entities, relationships

    async def _extract_with_llamaindex_sentences(
        self,
        group_id: str,
        sentences: List[Dict[str, Any]],
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Fallback: extract entities from sentence batches using LlamaIndex."""
        BATCH_SIZE = 6
        logger.warning(f"Using LlamaIndex fallback extractor on {len(sentences)} sentences")

        extractor = SchemaLLMPathExtractor(
            llm=cast(Any, self.llm),
            possible_entities=None,
            possible_relations=None,
            strict=False,
            num_workers=4,
            max_triplets_per_chunk=12,
        )

        # Create TextNode per batch of sentences
        nodes: List[TextNode] = []
        batch_map: Dict[str, List[Dict]] = {}  # node_id → sentence list
        for i in range(0, len(sentences), BATCH_SIZE):
            batch = sentences[i:i + BATCH_SIZE]
            batch_id = f"sbatch_{i}"
            batch_text = "\n".join(s["text"] for s in batch)
            nodes.append(TextNode(id_=batch_id, text=batch_text, metadata={}))
            batch_map[batch_id] = batch

        extracted_nodes = await extractor.acall(nodes)

        entities_by_key: Dict[str, Entity] = {}
        rel_keys: set[tuple[str, str, str]] = set()
        relationships: List[Relationship] = []

        for n in extracted_nodes:
            batch_id = getattr(n, "id_", None) or getattr(n, "id", None) or ""
            batch_sents = batch_map.get(batch_id, [])
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
                    ent_id = self._stable_entity_id(group_id, key)
                    ent = Entity(
                        id=ent_id,
                        name=name,
                        type=getattr(kn, "label", None) or (kn.get("label") if isinstance(kn, dict) else None) or "CONCEPT",
                        description="",
                        entity_embedding=None,
                        metadata={},
                        text_unit_ids=[],
                    )
                    entities_by_key[key] = ent

                # Map entity to sentence IDs (not batch ID)
                for s in batch_sents:
                    if name.lower() in s["text"].lower() and s["id"] not in ent.text_unit_ids:
                        ent.text_unit_ids.append(s["id"])

            for kr in kg_rels:
                subj = getattr(kr, "source_id", None) or getattr(kr, "source", None) or getattr(kr, "subject", None)
                obj = getattr(kr, "target_id", None) or getattr(kr, "target", None) or getattr(kr, "object", None)
                label = getattr(kr, "label", None) or getattr(kr, "relation", None)
                if isinstance(kr, dict):
                    subj = subj or kr.get("source_id") or kr.get("source") or kr.get("subject")
                    obj = obj or kr.get("target_id") or kr.get("target") or kr.get("object")
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
                relationships.append(Relationship(
                    source_id=sid, target_id=tid, type="RELATED_TO",
                    description=rel_desc, weight=1.0,
                ))

        entities = list(entities_by_key.values())
        if entities and self.voyage_service:
            texts = [e.name for e in entities]  # name-only, independently embedded
            for attempt in range(3):
                try:
                    embs = await self.voyage_service.aembed_independent_texts(texts)
                    for ent, emb in zip(entities, embs):
                        ent.entity_embedding = emb
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.warning("llamaindex_entity_embedding attempt %d failed, retrying: %s", attempt + 1, e)
                        await asyncio.sleep(2 ** attempt)
                    else:
                        logger.error("llamaindex_sentence_embedding_failed after 3 attempts: %s", e)

        return entities, relationships

    def _get_extraction_examples(self) -> str:
        """Return few-shot examples for native entity extraction."""
        return '''
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

Example 3:
Text: "QUANTITY: 1 | DESCRIPTION: Savaria V1504 Telecab residential elevator with automatic doors | UNIT PRICE: $11,200.00"
Output:
{"nodes": [
  {"id": "0", "label": "CONCEPT", "properties": {"name": "Savaria V1504 Telecab", "aliases": ["V1504", "Telecab", "Savaria elevator"], "description": "Residential elevator with automatic doors"}},
  {"id": "1", "label": "CONCEPT", "properties": {"name": "$11,200.00", "aliases": ["11200"], "description": "Unit price for Savaria V1504 Telecab"}}
], "relationships": [
  {"type": "RELATED_TO", "start_node_id": "0", "end_node_id": "1", "properties": {"context": "unit price"}}
]}

Example 4 (scope-of-work list items — ALWAYS extract each product/service as a CONCEPT):
Text: "Contractor agrees to furnish and install the following:
1 Vertical Platform Lift (Model XR-500).
1 Power system: 220 VAC 50 Hz.
1 Outdoor weatherproofing package.
1 Aluminum door with inserts & automatic opener."
Output:
{"nodes": [
  {"id": "0", "label": "CONCEPT", "properties": {"name": "Vertical Platform Lift (Model XR-500)", "aliases": ["XR-500", "platform lift", "VPL"], "description": "Vertical platform lift model XR-500"}},
  {"id": "1", "label": "CONCEPT", "properties": {"name": "Power system 220 VAC 50 Hz", "aliases": ["power system", "220 VAC", "electrical system"], "description": "Electrical power system specification"}},
  {"id": "2", "label": "CONCEPT", "properties": {"name": "Outdoor weatherproofing package", "aliases": ["weatherproofing", "outdoor package"], "description": "Outdoor weather protection accessory"}},
  {"id": "3", "label": "CONCEPT", "properties": {"name": "Aluminum door with inserts & automatic opener", "aliases": ["aluminum door", "automatic opener", "door with inserts"], "description": "Aluminum entry door with glass inserts and auto opener"}}
], "relationships": [
  {"type": "RELATED_TO", "start_node_id": "0", "end_node_id": "1", "properties": {"context": "lift power specification"}}
]}

Example 5 (payment terms and financial amounts):
Text: "Total contract price is $45,000.00, payable in 3 installments: $25,000.00 upon signing. $15,000.00 upon delivery. $5,000.00 upon completion."
Output:
{"nodes": [
  {"id": "0", "label": "CONCEPT", "properties": {"name": "$45,000.00 total contract price", "aliases": ["total price", "contract price", "45000"], "description": "Total contract price payable in installments"}},
  {"id": "1", "label": "CONCEPT", "properties": {"name": "3-installment payment plan", "aliases": ["payment terms", "installment plan", "payment schedule"], "description": "Payment in 3 stages: signing, delivery, completion"}}
], "relationships": [
  {"type": "RELATED_TO", "start_node_id": "0", "end_node_id": "1", "properties": {"context": "payment structure"}}
]}
'''



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
            # Offload sync Neo4j writes to thread pool to keep event loop responsive
            await asyncio.to_thread(
                self.neo4j_store.upsert_relationships_batch, group_id, relationships
            )
            details["relationships_committed"] = len(relationships)

        # Foundation and connectivity edges are independent — run in parallel.
        # compute_entity_importance must run AFTER these because it counts
        # all Entity relationships (including the APPEARS_IN_* edges created here).
        foundation_stats, connectivity_stats = await asyncio.gather(
            self._create_foundation_edges(group_id),
            self._create_connectivity_edges(group_id),
        )
        details["foundation_edges"] = foundation_stats
        details["connectivity_edges"] = connectivity_stats

        # Best-effort: compute ranking fields (degree, chunk_count, importance_score)
        # after all edges exist so counts are accurate.
        await asyncio.to_thread(self.neo4j_store.compute_entity_importance, group_id)
        
        # NOTE: Semantic edges (SIMILAR_TO) are now created by GDS KNN in Step 8 (index_documents)
        # as SEMANTICALLY_SIMILAR edges. The legacy _create_semantic_edges() method is kept
        # as fallback but no longer called here to avoid redundant Entity↔Entity edges.
        # GDS KNN is more comprehensive: covers Entity, KVP, Chunk, Figure nodes.
        
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
        
        2. **Languages** → Updates Document nodes with detected_languages property
           - Primary language stored as metadata
           - Enables multilingual corpus queries
        
        3. **Selection Marks** → logged for analysis (future enhancement)
        
        Note: Figure captions, table captions, and table rows are handled as
        Sentence nodes (source="figure_caption" / "table_caption" / "table_row")
        during sentence extraction, which is the path all retrieval routes use.
        
        Args:
            group_id: Group identifier for multi-tenancy
            expanded_docs: List of document dicts with di_extracted_docs containing LlamaIndex Documents
            chunk_to_doc_id: Mapping from chunk ID to document ID
            
        Returns:
            Statistics dictionary with counts of created entities/edges
        """
        stats: Dict[str, Any] = {
            "barcodes_created": 0,
            "kvps_created": 0,
            "languages_updated": 0,
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
            languages = first_meta.get("languages") or []
            selection_marks = first_meta.get("selection_marks") or []
            
            # Collect KVPs from ALL DI units (they're distributed per-section)
            all_kvps: List[Dict[str, Any]] = []
            for di_unit in di_units:
                unit_meta = getattr(di_unit, "metadata", None) or {}
                unit_kvps = unit_meta.get("key_value_pairs") or []
                all_kvps.extend(unit_kvps)
            
            if not any([barcodes, languages, all_kvps]):
                continue
            
            logger.info(
                "processing_di_metadata_for_doc",
                extra={
                    "group_id": group_id,
                    "doc_id": doc_id,
                    "barcodes": len(barcodes),
                    "languages": len(languages),
                    "selection_marks": len(selection_marks),
                    "kvps": len(all_kvps),
                }
            )
            
            def _write_di_metadata(session, *, _barcodes=barcodes,
                                   _doc_id=doc_id, _languages=languages,
                                   _selection_marks=selection_marks, _all_kvps=all_kvps):
                # 1. Create Barcode nodes and FOUND_IN edges
                if _barcodes:
                    barcode_data = []
                    for bc in _barcodes:
                        bc_id = self._stable_barcode_id(group_id, bc.get("value", ""))
                        barcode_data.append({
                            "id": bc_id,
                            "group_id": group_id,
                            "kind": bc.get("kind", "UNKNOWN"),
                            "value": bc.get("value", ""),
                            "confidence": bc.get("confidence", 0.0),
                            "page_number": bc.get("page_number", 1),
                            "entity_type": bc.get("entity_type", "BARCODE"),
                            "doc_id": _doc_id,
                        })

                    result = session.run(
                        """
                        UNWIND $barcodes AS bc
                        MERGE (b:Barcode {id: bc.id, group_id: bc.group_id})
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
                    logger.info(f"📊 Created {result.single()['count'] if result else 0} Barcode nodes for {_doc_id}")
                
                # 2. Update Document nodes with detected languages (including spans for sentence-level extraction)
                if _languages:
                    import json as json_module
                    # Find primary language (most spans)
                    primary_lang = max(_languages, key=lambda x: x.get("span_count", 0))
                    all_locales = [lang.get("locale", "") for lang in _languages if lang.get("locale")]
                    # Store full language data with spans for sentence-level context extraction
                    language_spans_json = json_module.dumps(_languages)
                    
                    result = session.run(
                        """
                        MATCH (d:Document {id: $doc_id, group_id: $group_id})
                        SET d.primary_language = $primary_lang,
                            d.detected_languages = $all_langs,
                            d.language_spans = $language_spans,
                            d.language_updated_at = datetime()
                        RETURN count(d) AS count
                        """,
                        doc_id=_doc_id,
                        group_id=group_id,
                        primary_lang=primary_lang.get("locale", ""),
                        all_langs=all_locales,
                        language_spans=language_spans_json,
                    )
                    stats["languages_updated"] += result.single()["count"]
                    total_spans = sum(lang.get("span_count", 0) for lang in _languages)
                    logger.info(f"🌐 Updated language metadata for {_doc_id}: primary={primary_lang.get('locale')}, locales={all_locales}, total_spans={total_spans}")
                
                # 3. Log selection marks for future enhancement
                if _selection_marks:
                    selected = sum(1 for m in _selection_marks if m.get("state") == "selected")
                    logger.info(
                        f"☑️ Selection marks detected in {_doc_id}: {len(_selection_marks)} total, {selected} selected",
                        extra={"doc_id": _doc_id, "total": len(_selection_marks), "selected": selected}
                    )
                
                # 4. Create KeyValuePair nodes with FOUND_IN edges
                if _all_kvps:
                    kvp_data = []
                    for kvp in _all_kvps:
                        key_text = kvp.get("key", "")
                        value_text = kvp.get("value", "")
                        if not key_text:
                            continue
                        kvp_id = self._stable_kvp_id(group_id, _doc_id, key_text, value_text)
                        kvp_data.append({
                            "id": kvp_id,
                            "group_id": group_id,
                            "key": key_text,
                            "value": value_text,
                            "confidence": kvp.get("confidence", 0.0),
                            "page_number": kvp.get("page_number", 1),
                            "section_id": kvp.get("section_id", ""),
                            "section_path": kvp.get("section_path", []),
                            "searchable_text": f"{key_text}: {value_text}",
                            "doc_id": _doc_id,
                        })
                    
                    if kvp_data:
                        result = session.run(
                            """
                            UNWIND $kvps AS kvp
                            MERGE (k:KeyValuePair {id: kvp.id, group_id: kvp.group_id})
                            SET k.group_id = kvp.group_id,
                                k.key = kvp.key,
                                k.value = kvp.value,
                                k.confidence = kvp.confidence,
                                k.page_number = kvp.page_number,
                                k.section_id = kvp.section_id,
                                k.section_path = kvp.section_path,
                                k.searchable_text = kvp.searchable_text,
                                k.key_embedding = coalesce(k.key_embedding, null),
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
                        logger.info(f"🔑 Created {count} KeyValuePair nodes for {_doc_id}")
                
            await self.neo4j_store.arun_in_session(_write_di_metadata)

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

    def _stable_kvp_id(self, group_id: str, doc_id: str, key: str, value: str) -> str:
        """Generate stable ID for key-value pair entity."""
        # Include doc_id to allow same key in different documents
        composite_key = f"kvp:{group_id}:{doc_id}:{key}:{value}"
        return f"kvp_{hashlib.md5(composite_key.encode()).hexdigest()[:16]}"

    # ==================== Step 8 (local): In-Process Graph Algorithms ====================

    async def _run_local_graph_algorithms(
        self,
        *,
        group_id: str,
        knn_top_k: int = 5,
        knn_similarity_cutoff: float = 0.60,
        knn_config: Optional[str] = None,
    ) -> Dict[str, int]:
        """Run KNN/Leiden/PageRank in-process using numpy + networkx.

        This replaces the remote Aura GDS session for small graphs (< GDS_LOCAL_THRESHOLD
        entities), eliminating the 60-120s provisioning overhead. For 50-500 entities the
        computation takes < 1s; the bottleneck is only Neo4j read/write I/O (~2-5s total).

        The algorithms are mathematically equivalent to the GDS versions:
        - KNN: cosine similarity via numpy, same top-k + cutoff semantics
        - Leiden: leidenalg community detection (resolution=1.0 matches GDS default)
        - PageRank: networkx pagerank (damping=0.85, tol=1e-6 matches GDS defaults)

        Returns same stats dict as _run_gds_graph_algorithms for drop-in compatibility.
        """
        import numpy as np
        import networkx as nx
        import igraph as ig
        import leidenalg

        stats = {"knn_edges": 0, "entity_edges": 0, "communities": 0, "pagerank_nodes": 0}
        algo_start = time.time()

        # ── 1. Fetch entity embeddings from Neo4j ──────────────────────────
        logger.info("📊 [local] Fetching entity embeddings from Neo4j...")

        def _fetch_entities(session):
            result = session.run("""
                MATCH (n:Entity)
                WHERE n.group_id IN $group_ids
                  AND NOT coalesce(n.deprecated, false)
                  AND n.entity_embedding IS NOT NULL
                RETURN elementId(n) AS eid, n.entity_embedding AS emb
            """, group_ids=[group_id, settings.GLOBAL_GROUP_ID])
            return [(r["eid"], r["emb"]) for r in result]

        entity_rows = await self.neo4j_store.arun_in_session(_fetch_entities, read_only=True)

        if not entity_rows:
            logger.warning("⚠️  [local] No entities with embeddings — skipping graph algorithms")
            return stats

        entity_ids = [r[0] for r in entity_rows]
        n_entities = len(entity_ids)
        logger.info(f"📊 [local] Loaded {n_entities} entity embeddings")

        # Build normalized embedding matrix (n × d) for cosine similarity
        embeddings = np.array([r[1] for r in entity_rows], dtype=np.float32)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)  # avoid division by zero
        embeddings_normed = embeddings / norms

        # ── 2. KNN via cosine similarity matrix ────────────────────────────
        knn_edge_batch: List[Dict[str, Any]] = []
        if knn_top_k > 0:
            logger.info(f"🔗 [local] Computing KNN (k={knn_top_k}, cutoff={knn_similarity_cutoff})...")
            # Cosine similarity = dot product of L2-normed vectors
            sim_matrix = await asyncio.to_thread(
                lambda: embeddings_normed @ embeddings_normed.T
            )
            # Zero out self-similarity
            np.fill_diagonal(sim_matrix, 0.0)

            # For each entity, pick top-k neighbors above cutoff
            seen_pairs: set = set()
            for i in range(n_entities):
                row = sim_matrix[i]
                # Get indices sorted by descending similarity
                candidates = np.argsort(row)[::-1][:knn_top_k]
                for j_idx in candidates:
                    j = int(j_idx)
                    sim_val = float(row[j])
                    if sim_val < knn_similarity_cutoff:
                        break  # sorted desc, so rest will be lower
                    pair = (min(i, j), max(i, j))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        knn_edge_batch.append({
                            "eid1": entity_ids[pair[0]],
                            "eid2": entity_ids[pair[1]],
                            "similarity": sim_val,
                        })

            logger.info(f"🔗 [local] KNN found {len(knn_edge_batch)} edges")

        # ── 3. Write KNN edges to Neo4j ────────────────────────────────────
        if knn_edge_batch:
            def _write_knn_edges(session):
                BATCH = 500
                edges_created = 0
                for start in range(0, len(knn_edge_batch), BATCH):
                    chunk = knn_edge_batch[start:start + BATCH]
                    if knn_config:
                        result = session.run("""
                            UNWIND $edges AS e
                            MATCH (n1) WHERE elementId(n1) = e.eid1
                            MATCH (n2) WHERE elementId(n2) = e.eid2
                            MERGE (n1)-[r:SEMANTICALLY_SIMILAR {knn_config: $knn_config}]->(n2)
                            SET r.score = e.similarity, r.similarity = e.similarity,
                                r.method = 'local_knn', r.group_id = $group_id,
                                r.knn_k = $knn_k, r.knn_cutoff = $knn_cutoff,
                                r.created_at = datetime()
                            RETURN count(r) AS cnt
                        """, edges=chunk, knn_config=knn_config, group_id=group_id,
                            knn_k=knn_top_k, knn_cutoff=knn_similarity_cutoff)
                    else:
                        result = session.run("""
                            UNWIND $edges AS e
                            MATCH (n1) WHERE elementId(n1) = e.eid1
                            MATCH (n2) WHERE elementId(n2) = e.eid2
                            MERGE (n1)-[r:SEMANTICALLY_SIMILAR]->(n2)
                            SET r.score = e.similarity, r.similarity = e.similarity,
                                r.method = 'local_knn', r.group_id = $group_id,
                                r.knn_k = $knn_k, r.knn_cutoff = $knn_cutoff,
                                r.created_at = datetime()
                            RETURN count(r) AS cnt
                        """, edges=chunk, group_id=group_id,
                            knn_k=knn_top_k, knn_cutoff=knn_similarity_cutoff)
                    edges_created += result.single()["cnt"]
                return edges_created

            stats["knn_edges"] = await self.neo4j_store.arun_in_session(_write_knn_edges)
            logger.info(f"🔗 [local] KNN: {stats['knn_edges']} SEMANTICALLY_SIMILAR edges written")

        # ── 4. Build networkx graph for Leiden + PageRank ─────────────────
        # Include KNN edges + existing relationships between entities
        logger.info("🏘️ [local] Building graph for Leiden + PageRank...")

        def _fetch_relationships(session):
            result = session.run("""
                MATCH (n:Entity)-[r]->(m:Entity)
                WHERE n.group_id IN $group_ids
                  AND m.group_id IN $group_ids
                  AND NOT coalesce(n.deprecated, false) AND NOT coalesce(m.deprecated, false)
                  AND n.entity_embedding IS NOT NULL
                  AND m.entity_embedding IS NOT NULL
                RETURN DISTINCT elementId(n) AS src, elementId(m) AS tgt
            """, group_ids=[group_id, settings.GLOBAL_GROUP_ID])
            return [(r["src"], r["tgt"]) for r in result]

        rel_rows = await self.neo4j_store.arun_in_session(_fetch_relationships, read_only=True)

        G = nx.Graph()
        G.add_nodes_from(entity_ids)
        # Add existing relationships
        for src, tgt in rel_rows:
            if src in G and tgt in G:
                G.add_edge(src, tgt, weight=1.0)
        # Add KNN edges (with similarity as weight)
        for e in knn_edge_batch:
            G.add_edge(e["eid1"], e["eid2"], weight=e["similarity"])

        # ── 5. Leiden community detection ──────────────────────────────────
        logger.info("🏘️ [local] Running Leiden community detection...")

        def _run_leiden():
            # Convert networkx graph to igraph for leidenalg
            node_list = list(G.nodes())
            node_idx = {n: i for i, n in enumerate(node_list)}
            ig_edges = [(node_idx[u], node_idx[v]) for u, v in G.edges()]
            weights = [G[u][v].get("weight", 1.0) for u, v in G.edges()]
            ig_graph = ig.Graph(n=len(node_list), edges=ig_edges, directed=False)
            ig_graph.es["weight"] = weights
            partition = leidenalg.find_partition(
                ig_graph, leidenalg.RBConfigurationVertexPartition,
                weights=weights, resolution_parameter=1.0, seed=42,
            )
            # Convert back: list of sets (same format as louvain_communities output)
            return [
                {node_list[idx] for idx in comm}
                for comm in partition
            ]

        communities_list = await asyncio.to_thread(_run_leiden)

        # Assign community IDs (match GDS convention: integer IDs)
        leiden_updates: List[Dict[str, Any]] = []
        community_ids_set: set = set()
        for comm_idx, comm_members in enumerate(communities_list):
            community_ids_set.add(comm_idx)
            for eid in comm_members:
                leiden_updates.append({"eid": eid, "communityId": comm_idx})

        if leiden_updates:
            def _write_leiden(session):
                BATCH = 500
                for start in range(0, len(leiden_updates), BATCH):
                    chunk = leiden_updates[start:start + BATCH]
                    session.run("""
                        UNWIND $updates AS u
                        MATCH (n) WHERE elementId(n) = u.eid AND n.group_id IN $group_ids
                        SET n.community_id = u.communityId
                    """, updates=chunk, group_ids=[group_id, settings.GLOBAL_GROUP_ID])

            await self.neo4j_store.arun_in_session(_write_leiden)

        stats["communities"] = len(community_ids_set)
        logger.info(f"🏘️ [local] Leiden: {stats['communities']} communities detected")

        # ── 6. PageRank ────────────────────────────────────────────────────
        logger.info("📈 [local] Running PageRank...")
        pr_scores = await asyncio.to_thread(
            lambda: nx.pagerank(G, alpha=0.85, max_iter=100, tol=1e-6)
        )

        pr_updates = [
            {"eid": eid, "score": float(score)}
            for eid, score in pr_scores.items()
        ]

        if pr_updates:
            def _write_pagerank(session):
                BATCH = 500
                for start in range(0, len(pr_updates), BATCH):
                    chunk = pr_updates[start:start + BATCH]
                    session.run("""
                        UNWIND $updates AS u
                        MATCH (n) WHERE elementId(n) = u.eid AND n.group_id IN $group_ids
                        SET n.pagerank = u.score
                    """, updates=chunk, group_ids=[group_id, settings.GLOBAL_GROUP_ID])

            await self.neo4j_store.arun_in_session(_write_pagerank)

        stats["pagerank_nodes"] = len(pr_updates)
        logger.info(f"📈 [local] PageRank: scored {stats['pagerank_nodes']} nodes")

        # Mark GDS as freshly computed
        self.neo4j_store.clear_gds_stale(group_id)

        elapsed = round(time.time() - algo_start, 2)
        logger.info(
            f"✅ [local] Graph algorithms complete in {elapsed}s: "
            f"{stats['knn_edges']} KNN edges, {stats['communities']} communities, "
            f"{stats['pagerank_nodes']} nodes scored"
        )
        return stats

    # ==================== Step 8 (GDS): Remote Aura GDS Session ====================

    async def _run_gds_graph_algorithms(
        self,
        *,
        group_id: str,
        knn_top_k: int = 5,
        knn_similarity_cutoff: float = 0.60,
        knn_config: Optional[str] = None,
    ) -> Dict[str, int]:
        """Run GDS algorithms to enhance the graph with computed properties.
        
        Routes to in-process computation (numpy + networkx) for small graphs
        when entity count < GDS_LOCAL_THRESHOLD, or falls back to Aura Serverless
        GDS sessions for large graphs.
        
        Algorithms run:
        1. **KNN** - Creates similarity edges:
           - Figure/KVP → Entity (SIMILAR_TO)
           - Entity ↔ Entity (SEMANTICALLY_SIMILAR)
        2. **Leiden** - Detects communities and assigns community_id to nodes
        3. **PageRank** - Computes importance scores for all nodes
        
        Args:
            group_id: Group identifier for multi-tenancy
            knn_top_k: Number of nearest neighbors for KNN (default: 5)
            knn_similarity_cutoff: Minimum similarity for KNN edges (default: 0.60)
            knn_config: Optional tag for KNN edges (e.g., "knn-1") for A/B testing
            
        Returns:
            Statistics dictionary with algorithm results
        """
        stats = {"knn_edges": 0, "entity_edges": 0, "communities": 0, "pagerank_nodes": 0}

        # ── Dispatch: local vs GDS ─────────────────────────────────────────
        threshold = settings.GDS_LOCAL_THRESHOLD
        if threshold > 0:
            def _count_entities(session):
                result = session.run("""
                    MATCH (n:Entity)
                    WHERE n.group_id IN $group_ids
                      AND NOT coalesce(n.deprecated, false)
                      AND n.entity_embedding IS NOT NULL
                    RETURN count(n) AS cnt
                """, group_ids=[group_id, settings.GLOBAL_GROUP_ID])
                return result.single()["cnt"]

            entity_count = await self.neo4j_store.arun_in_session(
                _count_entities, read_only=True,
            )
            if entity_count < threshold:
                logger.info(
                    f"📊 Entity count ({entity_count}) < GDS_LOCAL_THRESHOLD ({threshold}) "
                    f"→ using in-process graph algorithms (numpy + networkx)"
                )
                return await self._run_local_graph_algorithms(
                    group_id=group_id,
                    knn_top_k=knn_top_k,
                    knn_similarity_cutoff=knn_similarity_cutoff,
                    knn_config=knn_config,
                )
            else:
                logger.info(
                    f"📊 Entity count ({entity_count}) >= GDS_LOCAL_THRESHOLD ({threshold}) "
                    f"→ using Aura GDS session"
                )

        if not GDS_SESSIONS_AVAILABLE:
            logger.warning("⚠️  GDS sessions not available - skipping graph algorithms. Install: pip install graphdatascience")
            return stats
        
        if not settings.NEO4J_URI or not settings.AURA_DS_CLIENT_ID or not settings.AURA_DS_CLIENT_SECRET:
            logger.warning("⚠️  GDS configuration incomplete - skipping graph algorithms. Need: NEO4J_URI, AURA_DS_CLIENT_ID, AURA_DS_CLIENT_SECRET")
            return stats
        
        # Use timestamp + random to make projection name unique (avoids job ID collisions in Aura GDS)
        import time
        import random
        import re
        timestamp = int(time.time() * 1000)  # milliseconds for more uniqueness
        random_suffix = random.randint(1000, 9999)
        # Sanitize group_id for use in GDS projection names (alphanumeric + underscore only)
        safe_group_id = re.sub(r'[^a-zA-Z0-9_]', '_', group_id)
        projection_name = f"graphrag_{safe_group_id}_{timestamp}_{random_suffix}"
        session_name = f"graphrag_session_{timestamp}_{random_suffix}"  # Unique session per call
        
        try:
            # 1. Setup GDS session (Aura Serverless Graph Analytics)
            logger.info(f"📊 Connecting to Aura GDS session: {session_name}")
            session_start = time.time()
            api_creds = AuraAPICredentials(
                client_id=settings.AURA_DS_CLIENT_ID,
                client_secret=settings.AURA_DS_CLIENT_SECRET
            )
            sessions = GdsSessions(api_credentials=api_creds)
            
            # Pre-cleanup: delete any expired/orphaned/stuck sessions to free resources
            # AuraDB has a single-job concurrency limit — a stuck Running session
            # blocks ALL subsequent GDS operations until cleaned up.
            try:
                for stale in sessions.list():
                    if stale.status in ('Expired', 'Failed'):
                        sessions.delete(session_name=stale.name)
                        logger.info(f"🧹 Cleaned up stale GDS session: {stale.name} ({stale.status})")
                    elif stale.status == 'Ready' and stale.name != session_name:
                        # Ready sessions from prior runs that were never cleaned up
                        # (they hold the single-job slot even though idle)
                        try:
                            sessions.delete(session_name=stale.name)
                            logger.info(f"🧹 Cleaned up idle GDS session: {stale.name} ({stale.status})")
                        except Exception as idle_err:
                            logger.warning("Could not delete idle GDS session %s: %s", stale.name, idle_err)
            except Exception as cleanup_err:
                logger.warning("GDS pre-cleanup check failed: %s", cleanup_err)
            
            # Extract Aura instance ID from URI (e.g., neo4j+s://abc123.databases.neo4j.io -> abc123)
            import re
            aura_match = re.search(r'neo4j\+s://([^.]+)\.databases\.neo4j\.io', settings.NEO4J_URI)
            if not aura_match:
                raise ValueError(f"Could not extract Aura instance ID from URI: {settings.NEO4J_URI}")
            aura_instance_id = aura_match.group(1)
            
            db_connection = DbmsConnectionInfo(
                uri=settings.NEO4J_URI,
                username=settings.NEO4J_USERNAME or "neo4j",
                password=settings.NEO4J_PASSWORD
            )
            
            # Get or create GDS session (2GB minimum for Aura Serverless)
            # Retry session creation: Aura Serverless sometimes returns transient
            # HTTP/connection errors while provisioning the session container.
            gds = None
            for sess_attempt in range(3):
                try:
                    gds = sessions.get_or_create(
                        session_name=session_name,
                        memory=SessionMemory.m_2GB,
                        db_connection=db_connection
                    )
                    logger.info(f"✅ GDS session ready: version {gds.version()}")
                    break
                except Exception as sess_err:
                    if sess_attempt < 2:
                        delay = 15 * (2 ** sess_attempt)
                        logger.warning(
                            f"⏳ GDS session creation failed (attempt {sess_attempt + 1}/3), "
                            f"retrying in {delay}s: {sess_err}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise
            
            if gds is None:
                raise RuntimeError("GDS session creation failed after all retries")
            
            # 2. Project graph using gds.graph.project.remote() - the correct Aura Serverless approach
            logger.info(f"📊 Creating GDS projection: {projection_name}")
            
            # Drop existing graph if present (handles both SUCCESS and FAILED states)
            try:
                existing_graphs = gds.graph.list()
                for g in existing_graphs.itertuples():
                    if g.graphName == projection_name:
                        try:
                            gds.graph.drop(projection_name)
                            logger.info(f"🧹 Dropped existing projection: {projection_name}")
                        except Exception as drop_err:
                            # If drop fails, try via low-level query (handles FAILED jobs)
                            logger.warning(f"Standard drop failed, trying direct cleanup: {drop_err}")
                            try:
                                gds.run_cypher(
                                    "CALL gds.graph.drop($name, false)",
                                    params={"name": projection_name}
                                )
                                logger.info(f"🧹 Force-dropped projection via query: {projection_name}")
                            except Exception as force_err:
                                logger.warning(f"Could not force-drop projection: {force_err}")
            except Exception as e:
                logger.warning("GDS graph list/drop check failed: %s", e)
            
            # Escape group_id for Cypher (handle both backslash and double quotes)
            escaped_group_id = group_id.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
            
            # Note: GDS remote projection queries do not support $param syntax,
            # so we use escaped string interpolation. group_id is sourced from
            # authenticated JWT claims, limiting injection risk.
            
            # Single Cypher query with gds.graph.project.remote() - required for Aura Serverless
            # Add timestamp+random to query to avoid job ID collisions (Aura GDS uses query string as job ID)
            # This projects nodes with their embeddings and relationships in one call
            projection_query = f'''
                // Timestamp: {timestamp}_{random_suffix} - Ensures unique job ID in Aura GDS
                CALL () {{
                    // Project Entity nodes only - KVP/Figure/Chunk add noise to KNN & communities
                    MATCH (n:Entity)
                    WHERE n.group_id = "{escaped_group_id}"
                      AND NOT coalesce(n.deprecated, false)
                      AND n.entity_embedding IS NOT NULL
                    OPTIONAL MATCH (n)-[r]->(m:Entity)
                    WHERE m.group_id = "{escaped_group_id}"
                      AND NOT coalesce(m.deprecated, false)
                      AND m.entity_embedding IS NOT NULL
                    RETURN 
                      n AS source, r AS rel, m AS target,
                      n {{ .entity_embedding }} AS sourceNodeProperties,
                      m {{ .entity_embedding }} AS targetNodeProperties
                }}
                RETURN gds.graph.project.remote(source, target, {{
                    sourceNodeProperties: sourceNodeProperties,
                    targetNodeProperties: targetNodeProperties,
                    sourceNodeLabels: labels(source),
                    targetNodeLabels: labels(target),
                    relationshipType: type(rel)
                }})
            '''
            
            # Project the graph — with retry for AuraDB single-job concurrency limit.
            # AuraDB GDS allows only one job at a time. If another job is running
            # (from a prior session or concurrent indexing), the projection call
            # fails with "There's already a job running". We retry with exponential
            # backoff to wait for the blocking job to finish.
            max_retries = 5
            base_delay = 10  # seconds
            G = None
            for attempt in range(max_retries + 1):
                try:
                    G, result = gds.graph.project(projection_name, projection_query)
                    logger.info(f"✅ GDS projection created: {G.name()} ({G.node_count()} nodes, {G.relationship_count()} rels)")
                    break
                except Exception as proj_err:
                    err_msg = str(proj_err)
                    is_concurrent = "already a job running" in err_msg.lower()
                    if is_concurrent and attempt < max_retries:
                        delay = base_delay * (2 ** attempt)  # 10, 20, 40, 80, 160s
                        logger.warning(
                            f"⏳ GDS concurrent job detected (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {delay}s... Error: {err_msg[:120]}"
                        )
                        await asyncio.sleep(delay)
                        # Re-generate unique names to avoid job ID collision on retry
                        timestamp = int(time.time() * 1000)
                        random_suffix = random.randint(1000, 9999)
                        projection_name = f"graphrag_{safe_group_id}_{timestamp}_{random_suffix}"
                        # Re-build projection query with new timestamp for unique job ID
                        projection_query = projection_query.replace(
                            projection_query.split('// Timestamp: ')[1].split(' - ')[0],
                            f"{timestamp}_{random_suffix}"
                        )
                    else:
                        raise  # Non-concurrent error or retries exhausted
            
            if G is None:
                raise RuntimeError("GDS projection failed after all retries")
            
            if G.node_count() == 0:
                logger.warning(f"⚠️  No nodes in projection - skipping algorithms (check entity_embedding exists)")
                gds.graph.drop(projection_name)
                return stats
            
            # 3. Run KNN algorithm (skip if knn_top_k is 0)
            # Helper: retry GDS algorithm calls on transient connection errors.
            # Aura Serverless can drop the session→Neo4j link mid-algorithm;
            # a single retry typically succeeds once the link re-establishes.
            async def _run_gds_algo(name: str, fn, *args, **kwargs):
                for algo_attempt in range(2):
                    try:
                        return fn(*args, **kwargs)
                    except Exception as algo_err:
                        err_lower = str(algo_err).lower()
                        is_transient = any(k in err_lower for k in (
                            "no data", "connection closed", "defunct",
                            "service unavailable", "timed out", "reset by peer",
                        ))
                        if is_transient and algo_attempt == 0:
                            logger.warning(
                                f"⏳ GDS {name} transient error, retrying in 10s: {algo_err}"
                            )
                            await asyncio.sleep(10)
                            continue
                        raise

            if knn_top_k > 0:
                logger.info(f"🔗 Running GDS KNN (k={knn_top_k}, cutoff={knn_similarity_cutoff})...")
                knn_df = await _run_gds_algo(
                    "KNN", gds.knn.stream,
                    G,
                    nodeProperties=["entity_embedding"],
                    topK=knn_top_k,
                    similarityCutoff=knn_similarity_cutoff,
                    concurrency=4
                )
            else:
                logger.info(f"🔗 KNN disabled (knn_top_k=0) - skipping SEMANTICALLY_SIMILAR edge creation")
                import pandas as pd
                knn_df = pd.DataFrame(columns=["node1", "node2", "similarity"])
            
            # Process KNN results and create edges in Neo4j via UNWIND batch
            # Use SEMANTICALLY_SIMILAR for ALL KNN edges (consistency with GDS)
            # Only create one edge per pair (n1 < n2) to avoid bidirectional duplicates
            edge_batch = []
            for _, row in knn_df.iterrows():
                n1, n2 = int(row["node1"]), int(row["node2"])
                if n1 < n2:  # Pre-filter dedup (symmetric similarity)
                    edge_batch.append({"node1": n1, "node2": n2, "similarity": float(row["similarity"])})
            
            def _write_knn_edges(session):
                import time
                BATCH = 100
                edges_created = 0
                if edge_batch:
                    for start in range(0, len(edge_batch), BATCH):
                        chunk = edge_batch[start : start + BATCH]
                        if knn_config:
                            result = session.run("""
                                UNWIND $edges AS e
                                MATCH (n1), (n2)
                                WHERE id(n1) = e.node1 AND id(n2) = e.node2
                                  AND n1.group_id = $group_id AND n2.group_id = $group_id
                                MERGE (n1)-[r:SEMANTICALLY_SIMILAR {knn_config: $knn_config}]->(n2)
                                SET r.score = e.similarity, r.similarity = e.similarity,
                                    r.method = 'gds_knn', r.group_id = $group_id,
                                    r.knn_k = $knn_k, r.knn_cutoff = $knn_cutoff, r.created_at = datetime()
                                RETURN count(r) AS cnt
                            """, edges=chunk, knn_config=knn_config, group_id=group_id,
                                knn_k=knn_top_k, knn_cutoff=knn_similarity_cutoff)
                        else:
                            result = session.run("""
                                UNWIND $edges AS e
                                MATCH (n1), (n2)
                                WHERE id(n1) = e.node1 AND id(n2) = e.node2
                                  AND n1.group_id = $group_id AND n2.group_id = $group_id
                                MERGE (n1)-[r:SEMANTICALLY_SIMILAR]->(n2)
                                SET r.score = e.similarity, r.similarity = e.similarity,
                                    r.method = 'gds_knn', r.group_id = $group_id,
                                    r.knn_k = $knn_k, r.knn_cutoff = $knn_cutoff, r.created_at = datetime()
                                RETURN count(r) AS cnt
                            """, edges=chunk, group_id=group_id,
                                knn_k=knn_top_k, knn_cutoff=knn_similarity_cutoff)
                        edges_created += result.single()["cnt"]

                stats["knn_edges"] = edges_created
                config_msg = f" (config={knn_config})" if knn_config else ""
                logger.info(f"🔗 GDS KNN: {stats['knn_edges']} SEMANTICALLY_SIMILAR edges created{config_msg}")

            await self.neo4j_store.arun_in_session(_write_knn_edges)
            
            # 4. Run Leiden community detection
            logger.info(f"🏘️ Running GDS Leiden community detection...")
            leiden_df = await _run_gds_algo(
                "Leiden", gds.leiden.stream,
                G, includeIntermediateCommunities=False, concurrency=4
            )
            
            updates = []
            community_ids = set()
            for _, row in leiden_df.iterrows():
                node_id = int(row["nodeId"])
                community_id = int(row["communityId"])
                updates.append({"nodeId": node_id, "communityId": community_id})
                community_ids.add(community_id)
            
            def _write_leiden(session):
                BATCH = 100
                if updates:
                    for start in range(0, len(updates), BATCH):
                        chunk = updates[start : start + BATCH]
                        session.run("""
                            UNWIND $updates AS u
                            MATCH (n) WHERE id(n) = u.nodeId AND n.group_id = $group_id
                            SET n.community_id = u.communityId
                        """, updates=chunk, group_id=group_id)

                stats["communities"] = len(community_ids)
                logger.info(f"🏘️ GDS Leiden: {stats['communities']} communities")

            await self.neo4j_store.arun_in_session(_write_leiden)
            
            # 5. Run PageRank
            logger.info(f"📈 Running GDS PageRank...")
            pagerank_df = await _run_gds_algo(
                "PageRank", gds.pageRank.stream,
                G, dampingFactor=0.85, maxIterations=20, concurrency=4
            )
            
            pr_updates = [
                {"nodeId": int(row["nodeId"]), "score": float(row["score"])}
                for _, row in pagerank_df.iterrows()
            ]
            
            def _write_pagerank(session):
                BATCH = 100
                if pr_updates:
                    for start in range(0, len(pr_updates), BATCH):
                        chunk = pr_updates[start : start + BATCH]
                        session.run("""
                            UNWIND $updates AS u
                            MATCH (n) WHERE id(n) = u.nodeId AND n.group_id = $group_id
                            SET n.pagerank = u.score
                        """, updates=chunk, group_id=group_id)

                stats["pagerank_nodes"] = len(pr_updates)
                logger.info(f"📈 GDS PageRank: scored {stats['pagerank_nodes']} nodes")

            await self.neo4j_store.arun_in_session(_write_pagerank)
            
            # 6. Cleanup
            gds.graph.drop(projection_name)
            logger.info(f"🧹 Cleaned up GDS projection: {projection_name}")
            
            # Delete the GDS session to free resources
            try:
                sessions.delete(session_name=session_name)
                logger.info(f"🧹 Deleted GDS session: {session_name}")
            except Exception as cleanup_err:
                logger.warning(f"⚠️  Could not delete session {session_name}: {cleanup_err}")
            
            # Track GDS usage (billed by memory-hours)
            session_duration = int(time.time() - session_start)
            algorithms_run = [a for a, v in [
                ("knn", stats["knn_edges"]), ("leiden", stats["communities"]),
                ("pagerank", stats["pagerank_nodes"]),
            ] if v > 0]
            try:
                from src.core.services.usage_tracker import get_usage_tracker
                from src.core.services.credit_schedule import compute_gds_credits
                tracker = get_usage_tracker()
                gds_credits = compute_gds_credits(memory_gb=2, duration_seconds=session_duration)
                await tracker.log_gds_usage(
                    partition_id=user_id if user_id else group_id,
                    memory_gb=2,
                    duration_seconds=session_duration,
                    nodes_processed=stats.get("pagerank_nodes", 0),
                    algorithms_run=algorithms_run,
                    cost_estimate_usd=gds_credits * 0.001,
                    user_id=user_id,
                )
            except Exception as track_err:
                logger.warning(f"⚠️  GDS usage tracking failed: {track_err}")
            
            # Mark GDS as freshly computed for this group
            self.neo4j_store.clear_gds_stale(group_id)
            
        except Exception as e:
            logger.error(f"⚠️  GDS graph algorithms failed: {e}", extra={"error": str(e)})
            # Try to cleanup session even on failure
            try:
                if 'sessions' in locals() and 'session_name' in locals():
                    sessions.delete(session_name=session_name)
                    logger.info(f"🧹 Cleaned up failed session: {session_name}")
            except Exception:
                pass
            # Re-raise so pipeline-level retry can handle transient errors
            raise
        
        return stats

    # ==================== Step 9: Community Materialization ====================

    async def _materialize_communities(
        self,
        *,
        group_id: str,
        min_community_size: int = 2,
    ) -> Dict[str, int]:
        """Materialize Leiden clusters into Community nodes with LLM summaries.

        Bridges Leiden (structural clustering) with LazyGraphRAG (semantic
        summarization):
        1. Read community_id assignments from Step 8 (already on Entity nodes)
        2. Create :Community nodes and :BELONGS_TO edges via neo4j_store
        3. Generate LLM summary for each community from entity/relationship context
        4. Embed summaries and store on Community nodes for semantic matching

        Args:
            group_id: Tenant group identifier
            min_community_size: Skip communities with fewer than this many entities

        Returns:
            Stats dict with communities_created, summaries_generated, embeddings_stored
        """
        from src.worker.hybrid_v2.services.neo4j_store import Community

        stats = {"communities_created": 0, "summaries_generated": 0, "embeddings_stored": 0}

        # Guard: skip if LLM or section_embed_model unavailable (both are Optional in pipeline)
        if not self.llm or not self.section_embed_model:
            logger.warning(
                "⏭️  Skipping community materialization: llm=%s, section_embed_model=%s",
                bool(self.llm), bool(self.section_embed_model),
            )
            return stats

        # 9a) Group entities by community_id
        logger.info("📋 Step 9a: Grouping entities by Leiden community_id...")
        community_query = """
        MATCH (e:Entity {group_id: $group_id})
        WHERE e.community_id IS NOT NULL
        WITH e.community_id AS cid,
             collect({
                 name: e.name,
                 id: e.id,
                 description: coalesce(e.description, ''),
                 degree: coalesce(e.degree, 0),
                 pagerank: coalesce(e.pagerank, 0.0)
             }) AS members
        WHERE size(members) >= $min_size
        RETURN cid, members
        ORDER BY size(members) DESC
        """
        result = await self.neo4j_store.arun_query(community_query, read_only=True, group_id=group_id, min_size=min_community_size)
        community_groups = [(record["cid"], record["members"]) for record in result]

        if not community_groups:
            logger.info("⏭️  No Leiden communities with >= %d members found", min_community_size)
            return stats

        logger.info("📋 Found %d Leiden communities (>= %d members)", len(community_groups), min_community_size)

        # 9b) Delete stale communities from prior runs, then create fresh ones
        logger.info("🧹 Step 9b: Cleaning stale Community nodes...")
        await self.neo4j_store.arun_query(
            "MATCH (c:Community {group_id: $group_id}) DETACH DELETE c",
            group_id=group_id,
        )
        logger.info("🏗️ Step 9b: Creating Community nodes...")
        community_params = []
        link_params = []
        for cid, members in community_groups:
            avg_pagerank = sum(m["pagerank"] for m in members) / len(members)
            c_id = f"leiden_{group_id}_{cid}"
            community_params.append({
                "id": c_id, "level": 0, "title": "", "summary": "",
                "full_content": "", "rank": avg_pagerank,
            })
            for m in members:
                link_params.append({"community_id": c_id, "entity_id": m["id"]})

        await self.neo4j_store.arun_query(
            """
            UNWIND $communities AS c
            MERGE (comm:Community {id: c.id, group_id: $group_id})
            SET comm.level = c.level, comm.title = c.title, comm.summary = c.summary,
                comm.full_content = c.full_content, comm.rank = c.rank,
                comm.group_id = $group_id, comm.updated_at = datetime()
            """,
            communities=community_params, group_id=group_id,
        )
        if link_params:
            await self.neo4j_store.arun_query(
                """
                UNWIND $links AS l
                MATCH (c:Community {id: l.community_id, group_id: $group_id})
                MATCH (e:Entity {id: l.entity_id, group_id: $group_id})
                MERGE (e)-[r:BELONGS_TO]->(c)
                SET r.group_id = $group_id
                """,
                links=link_params, group_id=group_id,
            )
        stats["communities_created"] = len(community_params)

        # 9c) Pre-fetch ALL intra-community relationships in a single batch query
        # (replaces N+1 individual queries — one per community).
        logger.info("📝 Step 9c: Fetching intra-community relationships (batch)...")
        all_community_ids = [cid for cid, _ in community_groups]
        batch_rel_query = """
        MATCH (e1:Entity {group_id: $group_id})-[r]->(e2:Entity {group_id: $group_id})
        WHERE e1.community_id IN $community_ids
          AND e1.community_id = e2.community_id
          AND NOT type(r) IN ['MENTIONS', 'SEMANTICALLY_SIMILAR', 'BELONGS_TO', 'APPEARS_IN_SECTION', 'APPEARS_IN_DOCUMENT']
        RETURN e1.community_id AS cid, e1.name AS source, type(r) AS rel_type,
               e2.name AS target, coalesce(r.description, '') AS description
        """
        batch_rel_result = await self.neo4j_store.arun_query(
            batch_rel_query, read_only=True, group_id=group_id, community_ids=all_community_ids,
        )
        # Group relationships by community_id
        community_rels: Dict[int, List[Dict]] = {cid: [] for cid in all_community_ids}
        for record in batch_rel_result:
            cid = record["cid"]
            if cid in community_rels and len(community_rels[cid]) < 50:
                community_rels[cid].append({
                    "source": record["source"],
                    "rel_type": record["rel_type"],
                    "target": record["target"],
                    "description": record["description"],
                })

        # Generate LLM summaries (bounded parallelism)
        logger.info("📝 Step 9c: Generating LLM summaries for %d communities...", len(community_groups))
        sem = asyncio.Semaphore(settings.COMMUNITY_LLM_CONCURRENCY)

        async def _summarize_one(cid: int, members: List[Dict]) -> Optional[Tuple[str, str]]:
            async with sem:
                rels = community_rels.get(cid, [])
                return await self._summarize_community(group_id, cid, members, relationships=rels)

        tasks = [_summarize_one(cid, members) for cid, members in community_groups]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        summaries_cache: Dict[str, Tuple[str, str]] = {}  # community_id -> (title, summary)
        for (cid, _), result in zip(community_groups, results):
            if isinstance(result, Exception):
                logger.warning("⚠️  Community %d summarization failed: %s", cid, result)
                continue
            if result is None:
                continue
            title, summary = result
            community_id = f"leiden_{group_id}_{cid}"
            summaries_cache[community_id] = (title, summary)
            stats["summaries_generated"] += 1

        # Batch write all community summaries in a single UNWIND query
        if summaries_cache:
            summary_updates = [
                {"id": cid, "title": title, "summary": summary}
                for cid, (title, summary) in summaries_cache.items()
            ]
            await self.neo4j_store.arun_query(
                """
                UNWIND $updates AS u
                MATCH (c:Community {id: u.id, group_id: $group_id})
                SET c.title = u.title, c.summary = u.summary, c.full_content = u.summary
                """,
                updates=summary_updates, group_id=group_id,
            )

        # 9d-9e) Embed summaries and store on Community nodes (batched)
        if summaries_cache and self.section_embed_model:
            logger.info("🔢 Step 9d: Embedding %d community summaries...", len(summaries_cache))
            community_ids_ordered = list(summaries_cache.keys())
            summary_texts = [
                f"{summaries_cache[cid][0]}. {summaries_cache[cid][1]}"
                for cid in community_ids_ordered
            ]
            try:
                embeddings = await self.section_embed_model.aget_text_embedding_batch(summary_texts)
                embed_updates = [
                    {"id": cid, "community_embedding": emb}
                    for cid, emb in zip(community_ids_ordered, embeddings)
                    if emb is not None
                ]
                if embed_updates:
                    await self.neo4j_store.arun_query(
                        """
                        UNWIND $updates AS u
                        MATCH (c:Community {id: u.id, group_id: $group_id})
                        SET c.community_embedding = u.community_embedding
                        """,
                        updates=embed_updates, group_id=group_id,
                    )
                stats["embeddings_stored"] = len(embed_updates)
                logger.info("✅ Step 9e: Stored %d community embeddings", stats["embeddings_stored"])
            except Exception as e:
                logger.warning("⚠️  Community embedding failed: %s", e)

        return stats

    async def _summarize_community(
        self,
        group_id: str,
        community_id: int,
        members: List[Dict],
        relationships: Optional[List[Dict]] = None,
    ) -> Optional[Tuple[str, str]]:
        """Generate title + summary for one Leiden community via LLM.

        Args:
            group_id: Tenant group identifier
            community_id: Leiden community integer ID
            members: List of entity dicts with name, description, pagerank, etc.
            relationships: Pre-fetched intra-community relationships (avoids N+1 query).
                If None, falls back to per-community Neo4j query.

        Returns:
            (title, summary) tuple or None on failure.
        """
        # Use pre-fetched relationships if provided, otherwise query (fallback)
        if relationships is None:
            rel_query = """
            MATCH (e1:Entity {group_id: $group_id})-[r]->(e2:Entity {group_id: $group_id})
            WHERE e1.community_id = $community_id
              AND e2.community_id = $community_id
              AND NOT type(r) IN ['MENTIONS', 'SEMANTICALLY_SIMILAR', 'BELONGS_TO', 'APPEARS_IN_SECTION', 'APPEARS_IN_DOCUMENT']
            RETURN e1.name AS source, type(r) AS rel_type, e2.name AS target,
                   coalesce(r.description, '') AS description
            LIMIT 50
            """
            result = await self.neo4j_store.arun_query(rel_query, read_only=True, group_id=group_id, community_id=community_id)
            relationships = [dict(record) for record in result]

        # Build entity list (sorted by pagerank descending)
        entity_lines = []
        for m in sorted(members, key=lambda x: x["pagerank"], reverse=True)[:30]:
            desc = f" — {m['description']}" if m["description"] else ""
            entity_lines.append(f"- {m['name']}{desc}")

        # Build relationship list
        rel_lines = []
        for r in relationships[:30]:
            desc = f" ({r['description']})" if r.get("description") else ""
            rel_lines.append(f"- {r['source']} → {r['rel_type']} → {r['target']}{desc}")

        prompt = f"""You are analyzing a group of related entities from a knowledge graph of legal/business documents.

ENTITIES IN THIS CLUSTER ({len(members)} entities):
{chr(10).join(entity_lines)}

RELATIONSHIPS BETWEEN THEM ({len(relationships)} relationships):
{chr(10).join(rel_lines) if rel_lines else '(No explicit relationships extracted)'}

Based on these entities and their relationships, provide:
1. TITLE: A short descriptive title for this cluster (5-10 words)
2. SUMMARY: A 2-3 sentence summary describing what this group of entities represents, what topics or themes it covers, and what types of questions it could help answer. Be specific about the domain terms and party names.

Format your response exactly as:
TITLE: <title>
SUMMARY: <summary>"""

        try:
            from llama_index.core.llms import ChatMessage
            response = await self._achat_with_retry([ChatMessage(role="user", content=prompt)])
            text = response.message.content.strip()
            return self._parse_community_summary(text)
        except Exception as e:
            logger.warning("⚠️  LLM summarization failed for community %d: %s", community_id, e)
            return None

    @staticmethod
    def _parse_community_summary(text: str) -> Tuple[str, str]:
        """Parse TITLE: / SUMMARY: from LLM response text."""
        title = ""
        summary = ""
        lines = text.split("\n")
        summary_start = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.upper().startswith("TITLE:"):
                title = stripped[6:].strip()
            elif stripped.upper().startswith("SUMMARY:"):
                # Capture rest of this line + all subsequent lines
                first_part = stripped[8:].strip()
                remaining = "\n".join(l.strip() for l in lines[i + 1:]).strip()
                summary = f"{first_part}\n{remaining}".strip() if first_part else remaining
                break
        # If parsing fails, use the whole text as summary
        if not summary:
            summary = text[:500]
        if not title:
            title = summary[:50] + ("..." if len(summary) > 50 else "")
        return title, summary

    def _deduplicate_entities(
        self,
        *,
        group_id: str,
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> Tuple[List[Entity], List[Relationship], Dict[str, Any]]:
        dedup_service = EntityDeduplicationService(
            similarity_threshold=0.8,  # upstream HippoRAG 2 synonym merging threshold
            min_entities_for_dedup=10,
        )

        # Use entity_embedding (Voyage) for entity deduplication
        entity_dicts = []
        for e in entities:
            emb = e.entity_embedding if hasattr(e, 'entity_embedding') else None
            if emb is None:
                continue  # Skip entities without embeddings
            entity_dicts.append({
                "name": e.name,
                "embedding": emb,
                "type": e.type,
                "description": e.description,
                "properties": (e.metadata or {}),
            })

        dedup_result = dedup_service.deduplicate_entities(entity_dicts, group_id=group_id)
        if not dedup_result.merge_map:
            return entities, relationships, {
                "entities_before": len(entities),
                "entities_after": len(entities),
                "entities_merged": 0,
            }

        merge_map = dedup_result.merge_map

        # Protect deterministic entities from being merged away.
        # They can still be merge TARGETS (other entities → them), but never
        # lose their identity in a transitive chain.
        deterministic_names = {
            e.name for e in entities
            if (e.metadata or {}).get("deterministic")
        }
        protected_removed = 0
        for name in list(merge_map.keys()):
            if name in deterministic_names:
                del merge_map[name]
                protected_removed += 1
        if protected_removed:
            logger.info(
                "dedup_protected_deterministic",
                extra={"protected": protected_removed, "names": sorted(deterministic_names)},
            )

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
            merged_emb_v2 = None

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
                # Only keep embedding from the member whose name matches the
                # canonical name.  Inheriting an embedding computed for a
                # different (pre-rename) surface form would be stale.
                if m.name == canon_name and hasattr(m, 'entity_embedding') and m.entity_embedding is not None:
                    merged_emb = m.entity_embedding

            canonical_entities[canon_id] = Entity(
                id=canon_id,
                name=canon_name,
                type=merged_type,
                description=merged_desc,
                entity_embedding=merged_emb,
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

    def _build_extraction_schema(self) -> "SchemaConfig":
        """
        Build a schema that instructs the LLM to extract aliases alongside entities.
        
        This enables matching user queries like "Fabrikam Inc." to entities stored as
        "Fabrikam Construction" by including common variations in the aliases property.
        """
        # Entity types with alias properties for fuzzy matching
        entities = [
            SchemaEntity(
                label="ORGANIZATION",
                description="A company, corporation, business entity, or legal organization",
                properties=[
                    SchemaProperty(name="name", type="STRING", description="Official/legal name as it appears in the document"),
                    SchemaProperty(name="aliases", type="LIST", description="Common alternative names, abbreviations, short forms, or variations users might use (e.g., 'Fabrikam' for 'Fabrikam Construction Inc.')"),
                    SchemaProperty(name="description", type="STRING", description="Brief description of the organization"),
                ],
            ),
            SchemaEntity(
                label="PERSON",
                description="A named individual or person",
                properties=[
                    SchemaProperty(name="name", type="STRING", description="Full name as it appears in the document"),
                    SchemaProperty(name="aliases", type="LIST", description="Nicknames, maiden names, titles, or common variations"),
                    SchemaProperty(name="description", type="STRING", description="Role or brief description"),
                ],
            ),
            SchemaEntity(
                label="DOCUMENT",
                description="A legal document, contract, agreement, or formal document",
                properties=[
                    SchemaProperty(name="name", type="STRING", description="Document title or name"),
                    SchemaProperty(name="aliases", type="LIST", description="Short names or common references (e.g., 'the contract' for 'Purchase Contract Agreement')"),
                    SchemaProperty(name="description", type="STRING", description="Brief description of document purpose"),
                ],
            ),
            SchemaEntity(
                label="LOCATION",
                description="A geographic location, address, or place",
                properties=[
                    SchemaProperty(name="name", type="STRING", description="Location name or address"),
                    SchemaProperty(name="aliases", type="LIST", description="Abbreviated forms or common references"),
                ],
            ),
            SchemaEntity(
                label="CONCEPT",
                description="A product, equipment, model, service, specification, monetary amount, abstract concept, term, clause, or named section",
                properties=[
                    SchemaProperty(name="name", type="STRING", description="Concept or term name"),
                    SchemaProperty(name="aliases", type="LIST", description="Alternative phrasings or abbreviations"),
                    SchemaProperty(name="description", type="STRING", description="Brief explanation"),
                ],
            ),
        ]
        
        # Relationship types
        relations = [
            SchemaRelation(label="RELATED_TO", description="General relationship between entities"),
            SchemaRelation(label="PARTY_TO", description="Entity is a party to a document/agreement"),
            SchemaRelation(label="LOCATED_IN", description="Entity is located in a place"),
            SchemaRelation(label="MENTIONS", description="Document mentions an entity"),
            SchemaRelation(label="DEFINES", description="Document defines a term or concept"),
            SchemaRelation(label="FOUND_IN", description="Barcode or Figure found in a Document"),
            SchemaRelation(label="REFERENCES", description="Figure references another element (paragraph, table, section)"),
        ]
        
        # Define plausible schema triples for guided extraction
        potential_schema = [
            ("ORGANIZATION", "PARTY_TO", "DOCUMENT"),
            ("PERSON", "PARTY_TO", "DOCUMENT"),
            ("ORGANIZATION", "LOCATED_IN", "LOCATION"),
            ("PERSON", "LOCATED_IN", "LOCATION"),
            ("DOCUMENT", "MENTIONS", "ORGANIZATION"),
            ("DOCUMENT", "MENTIONS", "PERSON"),
            ("DOCUMENT", "MENTIONS", "LOCATION"),
            ("DOCUMENT", "DEFINES", "CONCEPT"),
            ("ORGANIZATION", "RELATED_TO", "ORGANIZATION"),
            ("PERSON", "RELATED_TO", "ORGANIZATION"),
            ("CONCEPT", "RELATED_TO", "CONCEPT"),
            ("CONCEPT", "RELATED_TO", "ORGANIZATION"),
            ("ORGANIZATION", "RELATED_TO", "CONCEPT"),
        ]
        
        return SchemaConfig(node_types=entities, relationship_types=relations, patterns=potential_schema)

    @staticmethod
    def _classify_sentence(sentence) -> str:
        """Classify a sentence as 'content', 'metadata', or 'noise'.

        content  — extract entities from this
        metadata — store as structured data, skip entity extraction
        noise    — skip entirely (form labels, empty fields)

        Accepts a sentence dict (with 'text', 'source', 'section_path')
        or a plain text string.  When DI metadata is available the
        classifier trusts it: a paragraph placed by DI in a real section
        is always 'content' regardless of text heuristics.
        """
        if isinstance(sentence, dict):
            t = (sentence.get("text") or "").strip()
            source = sentence.get("source") or ""
            section = sentence.get("section_path") or ""
        else:
            t = str(sentence).strip()
            source = ""
            section = ""

        # ── Absolute noise: too short to contain any entity ──
        if len(t) < 15:
            return "noise"

        # ── DI trust: paragraph or table_row in a real section → content ──
        has_section = bool(section) and section not in ("[Signature Block]", "[Page Footer]", "[Page Header]")
        if has_section and source in ("paragraph", "table_row"):
            return "content"

        # ── Heuristics for items without DI section context ──
        if len(t) < 40 and t.endswith(':'):
            return "noise"  # blank form labels, e.g. "Pumper's Name:"
        if re.match(r'^[\d\$,.%\s]+$', t):
            return "metadata"  # pure numeric/currency, e.g. "$29,900.00"

        return "content"

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


    async def _embed_section_nodes(self, group_id: str) -> Dict[str, Any]:
        """Embed Section nodes for semantic similarity computation (content-rich).
        
        Creates content-rich embeddings for Section nodes by concatenating:
        - Section title
        - Aggregated text from linked Sentences (first 500 chars each, max 5)
        
        These embeddings capture what the section *contains* and are used for
        SEMANTICALLY_SIMILAR edge creation ("soft" thematic hops in PPR).
        
        Stored in: Section.section_embedding (2048-dim Voyage via self.section_embed_model)
        
        NOTE: This is distinct from structural_embedding (title + path only)
        which is used for Source 2 header matching. See _embed_section_structural().
        
        Args:
            group_id: Tenant identifier
            
        Returns:
            Stats dict with sections_embedded count
        """
        if self.section_embed_model is None:
            logger.warning("section_embedding_skipped_no_embedder")
            return {"sections_embedded": 0, "skipped": "no_embedder"}
        
        # Fetch sections with their linked chunk texts
        result = await self.neo4j_store.arun_query(
            """
                MATCH (s:Section {group_id: $group_id})
                WHERE s.section_embedding IS NULL
                OPTIONAL MATCH (t:Sentence)-[:IN_SECTION]->(s)
                WITH s, collect(t.text)[0..5] AS sent_texts
                RETURN s.id AS section_id, s.title AS title, s.path_key AS path_key, sent_texts AS chunk_texts
                """,
            read_only=True,
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
            embeddings = await self.section_embed_model.aget_text_embedding_batch(texts_to_embed)
        except Exception as e:
            logger.warning("section_embedding_failed", extra={"error": str(e)})
            return {"sections_embedded": 0, "error": str(e)}
        
        # Update Section nodes with embeddings — batched to avoid overwhelming Neo4j
        # with a single transaction containing many 2048-dim vectors
        updates = [
            {"id": sec["id"], "section_embedding": emb}
            for sec, emb in zip(sections_to_embed, embeddings)
            if emb is not None
        ]
        
        BATCH = 20  # ~20 × 2048 floats ≈ 320 KB per batch
        for start in range(0, len(updates), BATCH):
            chunk = updates[start : start + BATCH]
            await self.neo4j_store.arun_query(
                """
                UNWIND $updates AS u
                MATCH (s:Section {id: u.id, group_id: $group_id})
                SET s.section_embedding = u.section_embedding
                """,
                updates=chunk,
                group_id=group_id,
            )
        
        logger.info(
            "section_nodes_embedded",
            extra={"group_id": group_id, "sections_embedded": len(updates)},
        )
        
        return {"sections_embedded": len(updates)}

    async def _generate_section_summaries(self, group_id: str) -> Dict[str, Any]:
        """Generate LLM summaries for Section nodes.

        Each summary is a concise 1-2 sentence description of the section's
        content derived from its linked TextChunks.  Summaries are stored on
        ``Section.summary`` and used by:
        - ``_embed_section_structural()`` — richer embedding signal
        - ``match_sections_by_llm()`` — LLM sees content context, not bare titles

        Summaries are only generated for sections that have linked chunks and
        do not already have a summary (idempotent).

        Args:
            group_id: Tenant identifier

        Returns:
            Stats dict with sections_summarised count
        """
        if self.llm is None:
            logger.warning("section_summary_skipped_no_llm")
            return {"sections_summarised": 0, "skipped": "no_llm"}

        # Fetch sections without summaries, with their chunk text
        result = await self.neo4j_store.arun_query(
            """
            MATCH (s:Section {group_id: $group_id})
            WHERE s.summary IS NULL
            OPTIONAL MATCH (t:Sentence)-[:IN_SECTION]->(s)
            WITH s, collect(t.text)[0..8] AS sent_texts
            WHERE size(sent_texts) > 0
            RETURN s.id AS section_id,
                   s.title AS title,
                   s.path_key AS path_key,
                   sent_texts AS chunk_texts
            """,
            read_only=True,
            group_id=group_id,
        )
        sections = [
            {
                "id": record["section_id"],
                "title": record["title"] or "",
                "path_key": record["path_key"] or "",
                "chunk_texts": record["chunk_texts"] or [],
            }
            for record in result
        ]

        if not sections:
            return {"sections_summarised": 0}

        logger.info(
            "section_summary_starting",
            extra={"group_id": group_id, "sections_to_summarise": len(sections)},
        )

        from llama_index.core.llms import ChatMessage

        _summary_sem = asyncio.Semaphore(settings.SECTION_LLM_CONCURRENCY)

        async def _summarize_section(sec: dict) -> Optional[dict]:
            content_sample = "\n---\n".join(
                ct[:600] for ct in sec["chunk_texts"] if ct
            )[:3000]
            prompt = (
                f"You are summarising a document section for a retrieval index.\n\n"
                f"Section title: {sec['title']}\n"
                f"Section path:  {sec['path_key']}\n\n"
                f"Content sample from this section:\n{content_sample}\n\n"
                f"Write a concise 1-2 sentence summary describing what this "
                f"section covers, including the key topics, terms, parties, "
                f"time periods, and obligations mentioned.  Focus on details "
                f"that would help a search system decide whether this section "
                f"is relevant to a user query.  Return ONLY the summary text."
            )
            try:
                async with _summary_sem:
                    response = await self._achat_with_retry(
                        [ChatMessage(role="user", content=prompt)]
                    )
                summary = response.message.content.strip()
                if summary:
                    return {"id": sec["id"], "summary": summary}
            except Exception as e:
                logger.warning(
                    "section_summary_llm_failed",
                    extra={"section_id": sec["id"], "error": str(e)},
                )
            return None

        results = await asyncio.gather(
            *[_summarize_section(sec) for sec in sections],
            return_exceptions=True,
        )
        updates: list[dict] = [
            r for r in results
            if r is not None and not isinstance(r, Exception)
        ]

        if not updates:
            return {"sections_summarised": 0}

        # Persist summaries
        BATCH = 200
        for i in range(0, len(updates), BATCH):
            batch = updates[i : i + BATCH]
            await self.neo4j_store.arun_query(
                    """
                    UNWIND $updates AS u
                    MATCH (s:Section {id: u.id, group_id: $group_id})
                    SET s.summary = u.summary
                    """,
                    updates=batch,
                    group_id=group_id,
                )

        logger.info(
            "section_summaries_generated",
            extra={"group_id": group_id, "sections_summarised": len(updates)},
        )
        return {"sections_summarised": len(updates)}

    async def _embed_section_structural(self, group_id: str) -> Dict[str, Any]:
        """Embed Section nodes structurally (title + path_key + summary) for Source 2.
        
        Creates structural embeddings that capture what the section *is about*
        using its header hierarchy and an LLM-generated summary (if available).
        This enables Source 2 (structural seed) to match queries against document
        structure independently of Source 1 (content sentence search).
        
        Why separate from Section.section_embedding:
        - Section.section_embedding includes raw chunk text → behaves like content search.
          Using it for Source 2 would return the same sections as Source 1 sentence
          search, providing no additive signal.
        - structural_embedding uses title + path_key + *summary* → captures the
          document author's heading AND a concise distillation of the section's
          content.  A query about "cancellation window deadlines" would match a
          Purchase Contract section whose summary mentions "3 business day
          cancellation window" even though the title is just "PURCHASE CONTRACT".
        
        If no summary exists (e.g., section has no linked chunks), falls back
        to title + path_key only.
        
        Stored in: Section.structural_embedding (2048-dim Voyage)
        Used by: match_sections_by_embedding() for Route 5 Source 2 structural seeds.
        
        Args:
            group_id: Tenant identifier
            
        Returns:
            Stats dict with sections_embedded count
        """
        if self.section_embed_model is None:
            logger.warning("section_structural_embedding_skipped_no_embedder")
            return {"sections_embedded": 0, "skipped": "no_embedder"}
        
        # Fetch sections without structural embeddings (include summary if present)
        result = await self.neo4j_store.arun_query(
            """
            MATCH (s:Section {group_id: $group_id})
            WHERE s.structural_embedding IS NULL
            RETURN s.id AS section_id, s.title AS title,
                   s.path_key AS path_key, s.summary AS summary,
                   s.hierarchical_id AS hierarchical_id
            """,
            read_only=True,
            group_id=group_id,
        )
        sections_to_embed = [
            {
                "id": record["section_id"],
                "title": record["title"] or "",
                "path_key": record["path_key"] or "",
                "summary": record["summary"] or "",
                "hierarchical_id": record["hierarchical_id"] or "",
            }
            for record in result
        ]
        
        if not sections_to_embed:
            return {"sections_embedded": 0}
        
        # Build structural texts: §-prefixed title + path_key + summary
        texts_to_embed = []
        for sec in sections_to_embed:
            parts = [p for p in [sec["title"], sec["path_key"]] if p]
            # Deduplicate: if title == last segment of path_key, use path_key only
            if sec["path_key"] and sec["title"] and sec["path_key"].endswith(sec["title"]):
                header_text = sec["path_key"]
            else:
                header_text = " | ".join(parts) if parts else "[Untitled Section]"
            # Prepend hierarchical ID for structural positioning context
            h_id = sec.get("hierarchical_id", "")
            if h_id:
                header_text = f"§{h_id} {header_text}"
            # Append summary for richer semantic signal
            if sec["summary"]:
                combined = f"{header_text} — {sec['summary']}"
            else:
                combined = header_text
            texts_to_embed.append(combined[:600])  # Cap for embedding model
        
        # Generate embeddings via Voyage (self.section_embed_model is VoyageEmbedding in V2)
        try:
            embeddings = await self.section_embed_model.aget_text_embedding_batch(texts_to_embed)
        except Exception as e:
            logger.warning("section_structural_embedding_failed", extra={"error": str(e)})
            return {"sections_embedded": 0, "error": str(e)}
        
        # Update Section nodes with structural_embedding
        updates = [
            {"id": sec["id"], "embedding": emb}
            for sec, emb in zip(sections_to_embed, embeddings)
            if emb is not None
        ]
        
        await self.neo4j_store.arun_query(
            """
            UNWIND $updates AS u
            MATCH (s:Section {id: u.id, group_id: $group_id})
            SET s.structural_embedding = u.embedding
            """,
            updates=updates,
            group_id=group_id,
        )
        
        logger.info(
            "section_structural_nodes_embedded",
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
        result = await self.neo4j_store.arun_query(
            """
            MATCH (s:Section {group_id: $group_id})
            WHERE s.section_embedding IS NOT NULL
            RETURN s.id AS id, s.doc_id AS doc_id, s.section_embedding AS embedding
            """,
            read_only=True,
            group_id=group_id,
        )
        sections = [
            {"id": record["id"], "doc_id": record["doc_id"], "embedding": record["embedding"]}
            for record in result
        ]
        
        if len(sections) < 2:
            return {"edges_created": 0, "reason": "insufficient_sections"}
        
        # Offload O(n²) pairwise cosine computation to thread pool
        # so the main event loop stays responsive for health probes.
        def _compute_edges():
            import numpy as np
            edges = []
            edge_count_per_section: Dict[str, int] = {}
            for i, s1 in enumerate(sections):
                if s1["embedding"] is None:
                    continue
                emb1 = np.array(s1["embedding"])
                norm1 = np.linalg.norm(emb1)
                if norm1 == 0:
                    continue
                for j, s2 in enumerate(sections):
                    if j <= i:
                        continue
                    if s1["doc_id"] == s2["doc_id"]:
                        continue
                    if s2["embedding"] is None:
                        continue
                    if edge_count_per_section.get(s1["id"], 0) >= max_edges_per_section:
                        continue
                    if edge_count_per_section.get(s2["id"], 0) >= max_edges_per_section:
                        continue
                    emb2 = np.array(s2["embedding"])
                    norm2 = np.linalg.norm(emb2)
                    if norm2 == 0:
                        continue
                    similarity = float(np.dot(emb1, emb2) / (norm1 * norm2))
                    if similarity >= similarity_threshold:
                        edges.append({
                            "source_id": s1["id"],
                            "target_id": s2["id"],
                            "similarity": round(similarity, 4),
                        })
                        edge_count_per_section[s1["id"]] = edge_count_per_section.get(s1["id"], 0) + 1
                        edge_count_per_section[s2["id"]] = edge_count_per_section.get(s2["id"], 0) + 1
            return edges

        edges_to_create = await asyncio.to_thread(_compute_edges)
        
        if not edges_to_create:
            return {"edges_created": 0}
        
        # Create SEMANTICALLY_SIMILAR edges in Neo4j
        result = await self.neo4j_store.arun_query(
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
        """Embed KeyValuePair keys for semantic matching at query time.
        
        Creates embeddings for unique KVP keys to enable semantic key matching.
        Uses batch deduplication to avoid re-embedding identical keys.
        
        This enables queries like "What is the policy number?" to match 
        keys like "Policy #", "Policy Number", "Policy ID" via semantic similarity.
        
        Args:
            group_id: Tenant identifier
            
        Returns:
            Stats dict with kvps_total, unique_keys, keys_embedded counts
        """
        if self.section_embed_model is None:
            logger.warning("keyvalue_embedding_skipped_no_embedder")
            return {"kvps_total": 0, "unique_keys": 0, "keys_embedded": 0, "skipped": "no_embedder"}
        
        # Fetch all KeyValuePair nodes without embeddings
        result = await self.neo4j_store.arun_query(
            """
            MATCH (kv:KeyValuePair {group_id: $group_id})
            WHERE kv.key_embedding IS NULL
            RETURN kv.id AS id, kv.key AS key
            """,
            read_only=True,
            group_id=group_id,
        )
        kvps_to_embed = [{"id": record["id"], "key": record["key"]} for record in result]

        if not kvps_to_embed:
            # Count total KVPs for stats
            result = await self.neo4j_store.arun_query(
                "MATCH (kv:KeyValuePair {group_id: $group_id}) RETURN count(kv) AS count",
                read_only=True,
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
            embeddings = await self.section_embed_model.aget_text_embedding_batch(unique_keys)
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
        
        # Update KeyValuePair nodes with embeddings
        await self.neo4j_store.arun_query(
            """
            UNWIND $updates AS u
            MATCH (kv:KeyValuePair {id: u.id, group_id: $group_id})
            SET kv.key_embedding = u.key_embedding
            """,
            updates=updates,
            group_id=group_id,
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

    def _validate_graph_integrity(self, group_id: str) -> Dict[str, Any]:
        """Post-pipeline integrity check: verify critical data was written.

        Returns dict with counts and a ``warnings`` list for gaps.
        This runs synchronously (called via run_in_executor).
        """
        warnings: list[str] = []
        counts: Dict[str, int] = {}

        with self.neo4j_store._resilient_session(read_only=True) as session:
            row = session.run("""
                MATCH (e:Entity) WHERE e.group_id = $gid
                WITH count(e) AS total_entities,
                     sum(CASE WHEN e.entity_embedding IS NOT NULL THEN 1 ELSE 0 END) AS entities_with_emb
                OPTIONAL MATCH ()-[r:RELATED_TO]->()
                    WHERE r.group_id = $gid AND r.description IS NOT NULL AND r.description <> ''
                WITH total_entities, entities_with_emb,
                     count(r) AS triples_with_desc,
                     sum(CASE WHEN r.triple_embedding IS NOT NULL THEN 1 ELSE 0 END) AS triples_with_emb
                OPTIONAL MATCH (c:Community {group_id: $gid})
                RETURN total_entities, entities_with_emb,
                       triples_with_desc, triples_with_emb,
                       count(c) AS community_count
            """, gid=group_id).single()

            if row:
                counts = dict(row)
                ent_total = row["total_entities"]
                ent_emb = row["entities_with_emb"]
                tri_desc = row["triples_with_desc"]
                tri_emb = row["triples_with_emb"]
                comm = row["community_count"]

                if ent_total > 0 and ent_emb < ent_total * 0.8:
                    warnings.append(
                        f"Only {ent_emb}/{ent_total} entities have embeddings "
                        f"({ent_emb * 100 // max(ent_total, 1)}%)"
                    )
                if tri_desc > 0 and tri_emb < tri_desc * 0.8:
                    warnings.append(
                        f"Only {tri_emb}/{tri_desc} triples have embeddings "
                        f"({tri_emb * 100 // max(tri_desc, 1)}%)"
                    )
                if ent_total >= 10 and comm == 0:
                    warnings.append(
                        f"{ent_total} entities but 0 communities — "
                        f"GDS/Leiden may have failed"
                    )

        return {"counts": counts, "warnings": warnings}

    async def _precompute_triple_embeddings(self, group_id: str) -> Dict[str, Any]:
        """Pre-compute Voyage embeddings for all RELATED_TO triples (Step 7.5).

        Builds the text ``source | description | target`` for each triple,
        optionally prefixed with ``[Document: title]`` and grouped per-document
        via ``embed_documents_contextualized()`` for proper Voyage contextual
        awareness — matching the sentence embedding architecture.

        Controlled by ROUTE7_TRIPLE_CONTEXTUALIZE (default: true).
        When true, triples are grouped by document and embedded contextually.
        When false, all triples are embedded as a flat list (legacy behavior).
        """
        import asyncio
        from src.worker.hybrid_v2.embeddings.voyage_embed import get_voyage_embed_service

        contextualize = os.getenv("ROUTE7_TRIPLE_CONTEXTUALIZE", "true").lower() in ("true", "1", "yes")

        triples = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.neo4j_store.fetch_all_triples(group_id)
        )
        if not triples:
            logger.info("No RELATED_TO triples found — skipping triple embedding.")
            return {"stored": 0}

        voyage_svc = get_voyage_embed_service()

        if contextualize:
            # Group triples by document title for per-document contextual embedding
            from collections import defaultdict
            doc_groups: Dict[str, List[int]] = defaultdict(list)
            for i, t in enumerate(triples):
                doc_key = t.get("document_title") or ""
                doc_groups[doc_key].append(i)

            # Build per-document chunk lists with [Document: title] prefix
            document_chunks: List[List[str]] = []
            index_map: List[List[int]] = []  # maps doc_idx → list of original indices
            for doc_title, indices in doc_groups.items():
                chunks = []
                for idx in indices:
                    t = triples[idx]
                    text = f"{t['source_name']} {t['description']} {t['target_name']}"
                    if doc_title:
                        text = f"[Document: {doc_title}] {text}"
                    chunks.append(text)
                document_chunks.append(chunks)
                index_map.append(indices)

            logger.info(
                f"triple_embedding_contextualized total={len(triples)} "
                f"documents={len(document_chunks)} "
                f"triples_with_doc={sum(1 for t in triples if t.get('document_title'))}"
            )

            nested_embeddings = await asyncio.get_event_loop().run_in_executor(
                None, lambda: voyage_svc.embed_documents_contextualized(document_chunks)
            )

            # Flatten back to original triple order
            embeddings: list[list[float]] = [None] * len(triples)  # type: ignore
            for doc_idx, indices in enumerate(index_map):
                doc_embeds = nested_embeddings[doc_idx]
                for chunk_idx, orig_idx in enumerate(indices):
                    embeddings[orig_idx] = doc_embeds[chunk_idx]
        else:
            # Legacy: flat list, no document context
            texts = [
                f"{t['source_name']} {t['description']} {t['target_name']}"
                for t in triples
            ]
            embeddings = await asyncio.get_event_loop().run_in_executor(
                None, lambda: voyage_svc.embed_documents(texts)
            )

        stored = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.neo4j_store.store_triple_embeddings_batch(
                group_id, triples, embeddings
            ),
        )
        logger.info(
            f"Pre-computed {stored}/{len(triples)} triple embeddings for group {group_id}"
            + (" (contextualized)" if contextualize else " (flat)")
        )
        return {"stored": stored, "total": len(triples), "contextualized": contextualize}

    async def _compute_entity_synonymy_edges(
        self,
        group_id: str,
        threshold: float = 0.70,
    ) -> Dict[str, Any]:
        """Compute entity-entity synonymy edges from embedding similarity (Step 7.6).

        After entity dedup merges near-identical entities (≥0.8 cosine), the
        remaining entity pairs in the threshold–0.79 range are semantically
        related but distinct.  Connecting them with SEMANTICALLY_SIMILAR edges
        creates cross-document bridges for PPR traversal.

        This replaces the upstream HippoRAG 2 entity KNN (topk=2047, @0.8)
        mechanism, adapted for our post-dedup entity landscape where max
        pairwise similarity is <0.80.  See architecture doc §47.
        """
        import numpy as np

        def _compute_and_write(session) -> Dict[str, Any]:
            # Load entity embeddings
            result = session.run(
                "MATCH (e:Entity {group_id: $gid}) "
                "WHERE e.entity_embedding IS NOT NULL "
                "RETURN e.id AS id, e.name AS name, "
                "e.entity_embedding AS emb, e.community_id AS comm",
                gid=group_id,
            )
            entities = [(r["id"], r["name"], np.array(r["emb"]), r["comm"])
                        for r in result]
            if len(entities) < 2:
                return {"edges_created": 0, "cross_community": 0, "entities": len(entities)}

            # All-pairs cosine similarity
            embs = np.array([e[2] for e in entities])
            norms = np.linalg.norm(embs, axis=1, keepdims=True)
            embs_normed = embs / (norms + 1e-10)
            sim_matrix = embs_normed @ embs_normed.T

            # Find pairs above threshold
            edges = []
            cross_community = 0
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    if sim_matrix[i, j] >= threshold:
                        edges.append({
                            "src_id": entities[i][0],
                            "tgt_id": entities[j][0],
                            "similarity": float(sim_matrix[i, j]),
                        })
                        if entities[i][3] != entities[j][3]:
                            cross_community += 1

            if not edges:
                return {"edges_created": 0, "cross_community": 0, "entities": len(entities)}

            # Clear old entity synonymy edges
            session.run(
                "MATCH (e1:Entity {group_id: $gid})"
                "-[r:SEMANTICALLY_SIMILAR]->(e2:Entity {group_id: $gid}) "
                "WHERE r.method = 'entity_synonymy' DELETE r",
                gid=group_id,
            )

            # Write bidirectional edges in batches
            batch_size = 50
            for start in range(0, len(edges), batch_size):
                batch = edges[start : start + batch_size]
                session.run(
                    "UNWIND $edges AS edge "
                    "MATCH (e1:Entity {id: edge.src_id, group_id: $gid}) "
                    "MATCH (e2:Entity {id: edge.tgt_id, group_id: $gid}) "
                    "CREATE (e1)-[:SEMANTICALLY_SIMILAR {"
                    "  similarity: edge.similarity,"
                    "  method: 'entity_synonymy',"
                    "  group_id: $gid,"
                    "  threshold: $thresh"
                    "}]->(e2) "
                    "CREATE (e2)-[:SEMANTICALLY_SIMILAR {"
                    "  similarity: edge.similarity,"
                    "  method: 'entity_synonymy',"
                    "  group_id: $gid,"
                    "  threshold: $thresh"
                    "}]->(e1)",
                    edges=batch, gid=group_id, thresh=threshold,
                )

            return {
                "edges_created": len(edges),
                "cross_community": cross_community,
                "entities": len(entities),
                "threshold": threshold,
            }

        return await self.neo4j_store.arun_in_session(_compute_and_write)

    async def _create_foundation_edges(self, group_id: str) -> Dict[str, int]:
        """Create foundation edges for graph schema enhancement.
        
        Creates three types of pre-computed edges in parallel:
        1. APPEARS_IN_SECTION: Entity → Section (replaces 2-hop Entity-Chunk-Section)
        2. APPEARS_IN_DOCUMENT: Entity → Document (replaces 3-hop Entity-Chunk-Section-Doc)
        3. HAS_HUB_ENTITY: Section → Entity (top-3 most connected entities per section)
        """
        logger.info("creating_foundation_edges", extra={"group_id": group_id})
        
        stats = {
            "appears_in_section": 0,
            "appears_in_document": 0,
            "has_hub_entity": 0,
        }
        
        async def _create_appears_in_section():
            try:
                result = await self.neo4j_store.arun_query(
                    """
                    MATCH (src:Sentence)-[:MENTIONS]->(e:Entity)
                    WHERE e.group_id = $group_id AND src.group_id = $group_id
                    MATCH (src)-[:IN_SECTION]->(s:Section {group_id: $group_id})
                    WITH e, s
                    WHERE s IS NOT NULL
                    MERGE (e)-[r:APPEARS_IN_SECTION]->(s)
                    SET r.group_id = $group_id
                    RETURN count(DISTINCT r) AS count
                    """,
                    group_id=group_id,
                )
                stats["appears_in_section"] = result.single()["count"]
            except Exception as e:
                logger.warning(f"APPEARS_IN_SECTION failed (continuing): {e}")

        async def _create_appears_in_document():
            try:
                result = await self.neo4j_store.arun_query(
                    """
                    MATCH (src:Sentence)-[:MENTIONS]->(e:Entity)
                    WHERE e.group_id = $group_id AND src.group_id = $group_id
                    MATCH (src)-[:IN_SECTION]->(s:Section {group_id: $group_id})
                    With e, s
                    WHERE s IS NOT NULL
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
            except Exception as e:
                logger.warning(f"APPEARS_IN_DOCUMENT failed (continuing): {e}")

        async def _create_has_hub_entity():
            try:
                result = await self.neo4j_store.arun_query(
                    """
                    MATCH (src:Sentence)-[:MENTIONS]->(e:Entity)
                    WHERE e.group_id = $group_id AND src.group_id = $group_id
                    MATCH (src)-[:IN_SECTION]->(s:Section {group_id: $group_id})
                    WITH e, s, src
                    WHERE s IS NOT NULL
                    WITH s, e, count(DISTINCT src) AS mention_count
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
            except Exception as e:
                logger.warning(f"HAS_HUB_ENTITY failed (continuing): {e}")

        # Run all 3 edge types concurrently — gated by _neo4j_write_sem
        # to prevent write storms on Aura Professional tier.
        async def _gated(fn):
            async with self._neo4j_write_sem:
                return await fn()

        await asyncio.gather(
            _gated(_create_appears_in_section),
            _gated(_create_appears_in_document),
            _gated(_create_has_hub_entity),
        )
        
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
        
        # Create SHARES_ENTITY edges (Section ↔ Section)
        # Connects sections that discuss the same entities across documents
        # Threshold: at least 2 shared entities to reduce noise
        result = await self.neo4j_store.arun_query(
            """
            MATCH (src1:Sentence)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(src2:Sentence)
            WHERE e.group_id = $group_id
            MATCH (src1)-[:IN_SECTION]->(s1:Section {group_id: $group_id})
            MATCH (src2)-[:IN_SECTION]->(s2:Section {group_id: $group_id})
            WITH s1, s2, e
            WHERE s1 IS NOT NULL AND s2 IS NOT NULL
              AND s1 <> s2
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
