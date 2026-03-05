"""
Document Sync Service

Orchestrates Neo4j graph synchronization after file operations in blob storage.
Translates file events (upload, delete, rename, move, copy) into graph operations
using DocumentLifecycleService and LazyGraphRAGIndexingPipeline.

All methods are fire-and-forget safe: they log errors but never raise,
so file operations in files.py are never blocked by Neo4j failures.
"""

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)


class DocumentSyncService:
    """Thin orchestration layer between blob file ops and Neo4j graph state."""

    def __init__(self):
        self._neo4j_store = None
        self._lifecycle = None
        self._pipeline = None
        self._prop_lock = threading.Lock()

    @property
    def neo4j_store(self):
        if self._neo4j_store is not None:
            return self._neo4j_store
        with self._prop_lock:
            if self._neo4j_store is None:
                from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3

                self._neo4j_store = Neo4jStoreV3(
                    uri=settings.NEO4J_URI,
                    username=settings.NEO4J_USERNAME,
                    password=settings.NEO4J_PASSWORD,
                    database=settings.NEO4J_DATABASE,
                )
        return self._neo4j_store

    @property
    def lifecycle(self):
        if self._lifecycle is not None:
            return self._lifecycle
        with self._prop_lock:
            if self._lifecycle is None:
                from src.worker.hybrid_v2.services.document_lifecycle import (
                    DocumentLifecycleService,
                )

                self._lifecycle = DocumentLifecycleService(self.neo4j_store)
        return self._lifecycle

    @property
    def pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        with self._prop_lock:
            if self._pipeline is None:
                from src.worker.hybrid_v2.indexing.pipeline_factory import (
                    get_lazygraphrag_indexing_pipeline_v2,
                )

                self._pipeline = get_lazygraphrag_indexing_pipeline_v2()
        return self._pipeline

    async def _delete_existing_document(
        self, group_id: str, blob_url: str
    ) -> Optional[str]:
        """Delete any existing document with the same source URL (handles overwrites).

        Returns the deleted document ID, or None if no prior version existed.
        """
        try:
            def _find_and_delete():
                with self.neo4j_store.driver.session(
                    database=self.neo4j_store.database
                ) as session:
                    result = session.run(
                        "MATCH (d:Document {group_id: $gid}) "
                        "WHERE d.source = $url "
                        "RETURN d.id AS doc_id LIMIT 1",
                        gid=group_id,
                        url=blob_url,
                    )
                    record = result.single()
                    return record["doc_id"] if record else None

            existing_id = await asyncio.to_thread(_find_and_delete)
            if existing_id:
                await self.lifecycle.hard_delete_document(group_id, existing_id)
                logger.info(
                    "doc_sync_overwrite_cleaned",
                    extra={
                        "group_id": group_id,
                        "old_doc_id": existing_id,
                        "source": blob_url,
                    },
                )
            return existing_id
        except Exception as e:
            logger.warning(
                "doc_sync_overwrite_cleanup_failed",
                extra={"group_id": group_id, "error": str(e)},
            )
            return None

    async def _write_document_usage(
        self,
        user_id: str,
        group_id: str,
        filename: str,
        sentences: int = 0,
    ) -> None:
        """Write a document_intelligence usage record to Cosmos for dashboard tracking."""
        try:
            from src.core.services.cosmos_client import get_cosmos_client
            from src.core.models.usage import UsageRecord

            cosmos = get_cosmos_client()
            record = UsageRecord(
                partition_id=user_id,
                user_id=user_id,
                usage_type="doc_intel",
                document_id=filename,
                pages_analyzed=sentences,
                model="document-intelligence",
                route="upload",
                query_id=f"upload-{group_id}-{filename}",
            )
            await asyncio.wait_for(cosmos.write_usage_record(record), timeout=10)
            logger.info(
                "doc_sync_cosmos_usage_written",
                extra={"user_id": user_id, "filename": filename},
            )
        except Exception as e:
            logger.warning(
                "doc_sync_cosmos_usage_failed",
                extra={"user_id": user_id, "filename": filename, "error": str(e)},
            )

    async def on_file_uploaded(
        self, group_id: str, filename: str, blob_url: str, user_id: str = ""
    ) -> None:
        """Trigger indexing for a newly uploaded file.

        If a document with the same source URL already exists (overwrite),
        hard-deletes it first to prevent orphan entities.
        """
        try:
            # Clean previous version if this is an overwrite
            await self._delete_existing_document(group_id, blob_url)

            docs = [
                {
                    "content": "",
                    "title": filename,
                    "source": blob_url,
                    "metadata": {},
                }
            ]
            stats = await self.pipeline.index_documents(
                group_id=group_id,
                documents=docs,
                ingestion="document-intelligence",
            )
            logger.info(
                "doc_sync_upload_indexed",
                extra={
                    "group_id": group_id,
                    "filename": filename,
                    "stats": stats,
                },
            )

            # Write document_intelligence usage record to Cosmos for dashboard
            await self._write_document_usage(
                user_id=user_id or group_id,
                group_id=group_id,
                filename=filename,
                sentences=stats.get("sentences", 0),
            )
        except Exception as e:
            logger.error(
                "doc_sync_upload_failed",
                extra={
                    "group_id": group_id,
                    "filename": filename,
                    "error": str(e),
                },
            )

    async def on_file_deleted(self, group_id: str, filename: str) -> None:
        """Hard-delete document and all children from Neo4j.

        Sets gds_stale=true on GroupMeta. The next index_documents() call
        (e.g., on next upload) will recompute GDS for the whole group.
        Manual recompute: POST /api/v2/maintenance/groups/{group_id}/recompute-gds
        """
        try:
            # hard_delete_document is async def but uses sync driver internally
            result = await self.lifecycle.hard_delete_document(group_id, filename)
            logger.info(
                "doc_sync_delete_complete",
                extra={
                    "group_id": group_id,
                    "filename": filename,
                    "success": result.success,
                    "chunks_deleted": result.chunks_deleted,
                },
            )
        except Exception as e:
            logger.error(
                "doc_sync_delete_failed",
                extra={
                    "group_id": group_id,
                    "filename": filename,
                    "error": str(e),
                },
            )

    async def on_file_deleted_bulk(
        self, group_id: str, filenames: List[str]
    ) -> None:
        """Hard-delete multiple documents from Neo4j (parallel)."""
        await asyncio.gather(
            *[self.on_file_deleted(group_id, f) for f in filenames]
        )

    async def on_file_renamed(
        self,
        group_id: str,
        old_filename: str,
        new_filename: str,
        new_blob_url: str,
    ) -> Optional[Dict[str, Any]]:
        """Rename document in Neo4j. Returns rename result or None on failure."""
        try:
            # rename_document is async def but uses sync driver internally
            result = await self.lifecycle.rename_document(
                group_id=group_id,
                old_document_id=old_filename,
                new_document_id=new_filename,
                new_title=new_filename,
                new_source=new_blob_url,
                keep_alias=True,
            )
            logger.info(
                "doc_sync_rename_complete",
                extra={
                    "group_id": group_id,
                    "old_filename": old_filename,
                    "new_filename": new_filename,
                    "result": result,
                },
            )
            return result
        except Exception as e:
            logger.error(
                "doc_sync_rename_failed",
                extra={
                    "group_id": group_id,
                    "old_filename": old_filename,
                    "new_filename": new_filename,
                    "error": str(e),
                },
            )
            return None

    async def on_file_moved(
        self, group_id: str, filename: str, new_blob_url: str
    ) -> None:
        """Update Document.source URL in Neo4j after a blob move."""
        try:
            def _update_source():
                with self.neo4j_store.driver.session(
                    database=self.neo4j_store.database
                ) as session:
                    session.run(
                        """
                        MATCH (d:Document {id: $doc_id, group_id: $group_id})
                        SET d.source = $new_source, d.updated_at = datetime()
                        """,
                        doc_id=filename,
                        group_id=group_id,
                        new_source=new_blob_url,
                    )

            await asyncio.to_thread(_update_source)
            logger.info(
                "doc_sync_move_complete",
                extra={
                    "group_id": group_id,
                    "filename": filename,
                    "new_source": new_blob_url,
                },
            )
        except Exception as e:
            logger.error(
                "doc_sync_move_failed",
                extra={
                    "group_id": group_id,
                    "filename": filename,
                    "error": str(e),
                },
            )

    async def on_file_copied(
        self, group_id: str, new_filename: str, new_blob_url: str
    ) -> None:
        """Trigger indexing for a copied file (same as upload)."""
        await self.on_file_uploaded(group_id, new_filename, new_blob_url)
