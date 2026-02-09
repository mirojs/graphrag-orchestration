"""
Chat History Router (Cosmos DB)

Provides CRUD endpoints for chat session history stored in Azure Cosmos DB.
Replaces the Quart chat_history_cosmosdb_bp blueprint.
"""

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from src.api_gateway.middleware.auth import get_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat_history", tags=["chat-history"])


# ==================== Request Models ====================

class ChatHistoryItem(BaseModel):
    id: str
    answers: List[List[str]]  # List of [question, response] pairs


# ==================== Service Access ====================

def _get_history_container(request: Request):
    """Get the Cosmos DB container from app state."""
    container = getattr(request.app.state, "cosmos_history_container", None)
    if not container:
        raise HTTPException(status_code=400, detail="Chat history not enabled")
    return container


def _get_history_version(request: Request) -> str:
    return getattr(request.app.state, "cosmos_history_version", "1")


# ==================== Endpoints ====================

@router.post("")
async def post_chat_history(
    request: Request,
    body: ChatHistoryItem,
    user_id: str = Depends(get_user_id),
):
    """Save or update a chat session with message pairs."""
    container = _get_history_container(request)
    version = _get_history_version(request)

    try:
        first_question = body.answers[0][0]
        title = (first_question[:50] + "...") if len(first_question) > 50 else first_question
        timestamp = int(time.time() * 1000)

        session_item = {
            "id": body.id,
            "version": version,
            "session_id": body.id,
            "entra_oid": user_id,
            "type": "session",
            "title": title,
            "timestamp": timestamp,
        }

        message_pair_items = []
        for ind, pair in enumerate(body.answers):
            message_pair_items.append({
                "id": f"{body.id}-{ind}",
                "version": version,
                "session_id": body.id,
                "entra_oid": user_id,
                "type": "message_pair",
                "question": pair[0],
                "response": pair[1],
            })

        batch_operations = [("upsert", (session_item,))] + [
            ("upsert", (item,)) for item in message_pair_items
        ]
        await container.execute_item_batch(
            batch_operations=batch_operations,
            partition_key=[user_id, body.id],
        )
        return JSONResponse({}, status_code=201)
    except Exception as e:
        logger.exception("Error saving chat history")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def get_chat_history_sessions(
    request: Request,
    count: int = Query(default=10),
    continuation_token: Optional[str] = Query(default=None, alias="continuationToken"),
    user_id: str = Depends(get_user_id),
):
    """List chat sessions for the current user, paginated."""
    container = _get_history_container(request)

    try:
        res = container.query_items(
            query=(
                "SELECT c.id, c.entra_oid, c.title, c.timestamp "
                "FROM c WHERE c.entra_oid = @entra_oid AND c.type = @type "
                "ORDER BY c.timestamp DESC"
            ),
            parameters=[
                {"name": "@entra_oid", "value": user_id},
                {"name": "@type", "value": "session"},
            ],
            partition_key=[user_id],
            max_item_count=count,
        )

        pager = res.by_page(continuation_token)
        sessions = []
        next_token = None
        try:
            page = await pager.__anext__()
            next_token = pager.continuation_token
            async for item in page:
                sessions.append({
                    "id": item.get("id"),
                    "entra_oid": item.get("entra_oid"),
                    "title": item.get("title", "untitled"),
                    "timestamp": item.get("timestamp"),
                })
        except StopAsyncIteration:
            next_token = None

        return {"sessions": sessions, "continuation_token": next_token}
    except Exception as e:
        logger.exception("Error listing chat sessions")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_chat_history_session(
    request: Request,
    session_id: str,
    user_id: str = Depends(get_user_id),
):
    """Get a specific chat session with all message pairs."""
    container = _get_history_container(request)

    try:
        res = container.query_items(
            query="SELECT * FROM c WHERE c.session_id = @session_id AND c.type = @type",
            parameters=[
                {"name": "@session_id", "value": session_id},
                {"name": "@type", "value": "message_pair"},
            ],
            partition_key=[user_id, session_id],
        )

        message_pairs = []
        async for page in res.by_page():
            async for item in page:
                message_pairs.append([item["question"], item["response"]])

        return {
            "id": session_id,
            "entra_oid": user_id,
            "answers": message_pairs,
        }
    except Exception as e:
        logger.exception("Error getting chat session %s", session_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_chat_history_session(
    request: Request,
    session_id: str,
    user_id: str = Depends(get_user_id),
):
    """Delete a chat session and all its message pairs."""
    container = _get_history_container(request)

    try:
        res = container.query_items(
            query="SELECT c.id FROM c WHERE c.session_id = @session_id",
            parameters=[{"name": "@session_id", "value": session_id}],
            partition_key=[user_id, session_id],
        )

        ids_to_delete = []
        async for page in res.by_page():
            async for item in page:
                ids_to_delete.append(item["id"])

        batch_operations = [("delete", (id_,)) for id_ in ids_to_delete]
        await container.execute_item_batch(
            batch_operations=batch_operations,
            partition_key=[user_id, session_id],
        )
        return Response(status_code=204)
    except Exception as e:
        logger.exception("Error deleting chat session %s", session_id)
        raise HTTPException(status_code=500, detail=str(e))
