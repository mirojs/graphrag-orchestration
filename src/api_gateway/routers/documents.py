"""
Documents router — BFF-facing endpoints for document lifecycle notifications.

The Quart BFF (frontend/app/backend) calls these endpoints after blob operations
to trigger Neo4j graph synchronization via DocumentSyncService.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


class NotifyUploadRequest(BaseModel):
    document_id: str
    title: str
    source: str  # blob URL
    metadata: Dict[str, Any] = {}
    folder_id: Optional[str] = None
    trigger_indexing: bool = True


class NotifyDeleteRequest(BaseModel):
    document_id: str
    hard_delete: bool = False


def _get_doc_sync(request: Request):
    return getattr(request.app.state, "document_sync_service", None)


@router.post("/notify-upload")
async def notify_upload(
    request: Request,
    body: NotifyUploadRequest,
    background_tasks: BackgroundTasks,
    x_group_id: str = Header(..., alias="X-Group-ID"),
):
    """
    Receive upload notification from the BFF and trigger graph indexing.

    Called by GraphRAGClient.notify_document_uploaded() in the Quart BFF
    after a file has been uploaded to blob storage.
    """
    doc_sync = _get_doc_sync(request)
    if not doc_sync:
        raise HTTPException(status_code=503, detail="DocumentSyncService not available")

    background_tasks.add_task(
        doc_sync.on_file_uploaded,
        x_group_id,
        body.document_id,
        body.source,
    )

    logger.info(
        "notify_upload_accepted",
        extra={
            "group_id": x_group_id,
            "document_id": body.document_id,
            "trigger_indexing": body.trigger_indexing,
        },
    )

    return {
        "status": "accepted",
        "document_id": body.document_id,
        "message": "Indexing job queued",
    }


@router.post("/notify-delete")
async def notify_delete(
    request: Request,
    body: NotifyDeleteRequest,
    background_tasks: BackgroundTasks,
    x_group_id: str = Header(..., alias="X-Group-ID"),
):
    """
    Receive delete notification from the BFF and trigger graph cleanup.

    Called by GraphRAGClient.delete_document() in the Quart BFF
    after a file has been removed from blob storage.
    """
    doc_sync = _get_doc_sync(request)
    if not doc_sync:
        raise HTTPException(status_code=503, detail="DocumentSyncService not available")

    background_tasks.add_task(
        doc_sync.on_file_deleted,
        x_group_id,
        body.document_id,
    )

    return {
        "status": "accepted",
        "document_id": body.document_id,
        "message": "Deletion job queued",
    }
