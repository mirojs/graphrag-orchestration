"""
Chat compatibility router for azure-search-openai-demo frontend.

Provides OpenAI-compatible chat endpoints that map to internal GraphRAG queries.
Supports both streaming and non-streaming responses.
"""

from typing import List, Optional, AsyncGenerator
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uuid
import time
import json
import logging

from src.api_gateway.middleware.auth import get_group_id, get_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ============================================================================
# Request/Response Models (OpenAI-compatible)
# ============================================================================

class ChatMessage(BaseModel):
    """Single chat message."""
    role: str = Field(..., description="Message role: system, user, or assistant")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Chat completion request (OpenAI-compatible)."""
    messages: List[ChatMessage] = Field(..., description="Conversation history")
    stream: bool = Field(default=False, description="Enable streaming response")
    temperature: Optional[float] = Field(default=0.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, description="Max tokens to generate")
    
    # GraphRAG-specific extensions
    approach: Optional[str] = Field(default="hybrid", description="Query approach: hybrid, local, global, drift")
    folder_id: Optional[str] = Field(default=None, description="Optional folder ID for scoped search")


class ChatChoice(BaseModel):
    """Single completion choice."""
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatUsage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatResponse(BaseModel):
    """Chat completion response (OpenAI-compatible)."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str = "graphrag-hybrid"
    choices: List[ChatChoice]
    usage: ChatUsage


class StreamChoice(BaseModel):
    """Streaming response choice."""
    index: int = 0
    delta: ChatMessage
    finish_reason: Optional[str] = None


class ChatStreamChunk(BaseModel):
    """Streaming response chunk (OpenAI-compatible)."""
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str = "graphrag-hybrid"
    choices: List[StreamChoice]


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/completions")
async def chat_completions(
    request: ChatRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
) -> ChatResponse:
    """
    OpenAI-compatible chat completion endpoint.
    
    Maps to internal GraphRAG hybrid query orchestration.
    Supports both streaming and non-streaming modes.
    """
    if request.stream:
        # Return streaming response
        return StreamingResponse(
            _stream_chat_response(request, group_id, user_id),
            media_type="text/event-stream",
        )
    
    # Non-streaming response
    try:
        # Extract user query (last user message)
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message found")
        
        query = user_messages[-1].content
        
        # Map approach to route
        route_map = {
            "hybrid": None,  # Let orchestrator decide
            "local": "LOCAL_SEARCH",
            "global": "GLOBAL_SEARCH",
            "drift": "DRIFT",
        }
        approach = request.approach or "hybrid"
        route_hint = route_map.get(approach, None)
        
        # Execute GraphRAG query via hybrid endpoint
        # For now, return a mock response - actual implementation will call hybrid router
        result = {
            "answer": "Chat endpoint is ready. Integration with HybridOrchestrator pending.",
            "route": approach,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        
        # Convert to OpenAI format
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        response = ChatResponse(
            id=response_id,
            created=int(time.time()),
            model=f"graphrag-{result.get('route', 'hybrid').lower()}",
            choices=[
                ChatChoice(
                    message=ChatMessage(
                        role="assistant",
                        content=result.get("answer", ""),
                    ),
                    finish_reason="stop",
                )
            ],
            usage=ChatUsage(
                prompt_tokens=result.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=result.get("usage", {}).get("completion_tokens", 0),
                total_tokens=result.get("usage", {}).get("total_tokens", 0),
            ),
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Chat completion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _stream_chat_response(
    request: ChatRequest,
    group_id: str,
    user_id: str,
) -> AsyncGenerator[str, None]:
    """
    Generate streaming chat response in SSE format.
    
    Yields Server-Sent Events compatible with OpenAI streaming API.
    """
    response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    
    try:
        # Extract user query
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if not user_messages:
            raise ValueError("No user message found")
        
        query = user_messages[-1].content
        
        # Map approach to route
        route_map = {
            "hybrid": None,
            "local": "LOCAL_SEARCH",
            "global": "GLOBAL_SEARCH",
            "drift": "DRIFT",
        }
        approach = request.approach or "hybrid"
        route_hint = route_map.get(approach, None)
        
        # Mock response for now - actual implementation will call hybrid router
        result = {
            "answer": "Streaming response ready. Integration with HybridOrchestrator pending.",
            "route": approach,
        }
        
        answer = result.get("answer", "")
        route = result.get("route", "hybrid")
        
        # Send initial chunk with role
        chunk = ChatStreamChunk(
            id=response_id,
            created=created,
            model=f"graphrag-{route.lower()}",
            choices=[
                StreamChoice(
                    delta=ChatMessage(role="assistant", content=""),
                    finish_reason=None,
                )
            ],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"
        
        # Send content chunk
        chunk = ChatStreamChunk(
            id=response_id,
            created=created,
            model=f"graphrag-{route.lower()}",
            choices=[
                StreamChoice(
                    delta=ChatMessage(role="assistant", content=answer),
                    finish_reason=None,
                )
            ],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"
        
        # Send final chunk
        chunk = ChatStreamChunk(
            id=response_id,
            created=created,
            model=f"graphrag-{route.lower()}",
            choices=[
                StreamChoice(
                    delta=ChatMessage(role="assistant", content=""),
                    finish_reason="stop",
                )
            ],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.error(f"Streaming error: {e}", exc_info=True)
        error_chunk = {
            "error": {
                "message": str(e),
                "type": "internal_error",
                "code": 500,
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"


@router.get("/models")
async def list_models():
    """
    List available chat models (OpenAI-compatible).
    
    Returns GraphRAG routes as "models" for frontend compatibility.
    """
    return {
        "object": "list",
        "data": [
            {
                "id": "graphrag-hybrid",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "graphrag",
                "permission": [],
                "root": "graphrag-hybrid",
                "parent": None,
            },
            {
                "id": "graphrag-local",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "graphrag",
                "permission": [],
                "root": "graphrag-local",
                "parent": None,
            },
            {
                "id": "graphrag-global",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "graphrag",
                "permission": [],
                "root": "graphrag-global",
                "parent": None,
            },
            {
                "id": "graphrag-drift",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "graphrag",
                "permission": [],
                "root": "graphrag-drift",
                "parent": None,
            },
        ],
    }
