"""
Chat History Router (Azure Blob Storage)

Stores chat sessions as JSON blobs in Azure Blob Storage.
Layout:  chat-history/{user_id}/index.json       — session list
         chat-history/{user_id}/{session_id}.json — full conversation

Cheaper and simpler than Cosmos DB for this append-heavy, read-occasional pattern.
"""

import json
import logging
import time
from typing import Any, List, Optional

from azure.storage.blob import ContentSettings
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from src.api_gateway.middleware.auth import get_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat_history", tags=["chat-history"])

_CONTAINER_NAME = "chat-history"


# ==================== Request Models ====================

class ChatHistoryItem(BaseModel):
    id: str
    answers: List[Any]  # List of [question, ChatAppResponse] pairs


# ==================== Blob Helpers ====================

def _get_blob_service(request: Request):
    """Get the BlobServiceClient from app state."""
    svc = getattr(request.app.state, "chat_history_blob_service", None)
    if not svc:
        raise HTTPException(status_code=400, detail="Chat history not enabled")
    return svc


def _container_client(request: Request):
    return _get_blob_service(request).get_container_client(_CONTAINER_NAME)


async def _read_json(container, blob_path: str, default=None):
    """Read and parse a JSON blob. Returns default if not found."""
    try:
        blob = container.get_blob_client(blob_path)
        data = await blob.download_blob()
        content = await data.readall()
        return json.loads(content)
    except Exception:
        return default


async def _write_json(container, blob_path: str, data):
    """Write a JSON blob (overwrite)."""
    blob = container.get_blob_client(blob_path)
    await blob.upload_blob(
        json.dumps(data, ensure_ascii=False),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


async def _delete_blob(container, blob_path: str):
    """Delete a blob if it exists."""
    try:
        blob = container.get_blob_client(blob_path)
        await blob.delete_blob()
    except Exception:
        pass


async def _get_index(container, user_id: str) -> list:
    """Get the session index for a user."""
    return await _read_json(container, f"{user_id}/index.json", default=[])


async def _put_index(container, user_id: str, sessions: list):
    """Write the session index for a user."""
    await _write_json(container, f"{user_id}/index.json", sessions)


# ==================== Endpoints ====================

@router.post("")
async def post_chat_history(
    request: Request,
    body: ChatHistoryItem,
    user_id: str = Depends(get_user_id),
):
    """Save or update a chat session."""
    container = _container_client(request)

    try:
        first_question = body.answers[0][0] if body.answers else ""
        title = (first_question[:50] + "...") if len(first_question) > 50 else first_question
        timestamp = int(time.time() * 1000)

        # Write session blob
        session_data = {
            "id": body.id,
            "entra_oid": user_id,
            "title": title,
            "timestamp": timestamp,
            "answers": body.answers,
        }
        await _write_json(container, f"{user_id}/{body.id}.json", session_data)

        # Update index (insert or update entry, keep sorted by timestamp desc)
        index = await _get_index(container, user_id)
        index = [s for s in index if s["id"] != body.id]
        index.insert(0, {
            "id": body.id,
            "entra_oid": user_id,
            "title": title,
            "timestamp": timestamp,
        })
        await _put_index(container, user_id, index)

        return JSONResponse({}, status_code=201)
    except Exception as e:
        logger.exception("Error saving chat history")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sessions")
async def get_chat_history_sessions(
    request: Request,
    count: int = Query(default=10),
    continuation_token: Optional[str] = Query(default=None, alias="continuationToken"),
    user_id: str = Depends(get_user_id),
):
    """List chat sessions for the current user, paginated."""
    container = _container_client(request)

    try:
        index = await _get_index(container, user_id)

        # Simple offset-based pagination via continuation token
        offset = int(continuation_token) if continuation_token else 0
        page = index[offset : offset + count]
        next_offset = offset + count
        next_token = str(next_offset) if next_offset < len(index) else None

        return {"sessions": page, "continuation_token": next_token}
    except Exception as e:
        logger.exception("Error listing chat sessions")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sessions/{session_id}")
async def get_chat_history_session(
    request: Request,
    session_id: str,
    user_id: str = Depends(get_user_id),
):
    """Get a specific chat session with all message pairs."""
    container = _container_client(request)

    try:
        data = await _read_json(container, f"{user_id}/{session_id}.json")
        if not data or data.get("entra_oid") != user_id:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "id": session_id,
            "entra_oid": user_id,
            "answers": data.get("answers", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting chat session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/sessions/{session_id}")
async def delete_chat_history_session(
    request: Request,
    session_id: str,
    user_id: str = Depends(get_user_id),
):
    """Delete a chat session."""
    container = _container_client(request)

    try:
        # Remove session blob
        await _delete_blob(container, f"{user_id}/{session_id}.json")

        # Update index
        index = await _get_index(container, user_id)
        index = [s for s in index if s["id"] != session_id]
        await _put_index(container, user_id, index)

        return Response(status_code=204)
    except Exception as e:
        logger.exception("Error deleting chat session %s", session_id)
        raise HTTPException(status_code=500, detail="Internal server error")
