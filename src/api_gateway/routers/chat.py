"""
Chat compatibility router for azure-search-openai-demo frontend.

Provides OpenAI-compatible chat endpoints that map to internal GraphRAG queries.
Supports both streaming and non-streaming responses.

Phase 4 Implementation:
- Job status endpoint for async polling pattern
- Async job submission for Routes 3/4 (Global/DRIFT)
- NDJSON streaming thoughts for progressive updates
- Integration with HybridPipeline orchestrator
"""

from typing import List, Optional, AsyncGenerator, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette import status
import uuid
import time
import json
import structlog
import asyncio

from src.api_gateway.middleware.auth import get_group_id, get_user_id
from src.core.services.redis_service import (
    get_redis_service,
    RedisService,
    OperationStatus,
)
from src.core.config import settings

logger = structlog.get_logger(__name__)

# Routes that should use async pattern (typically >5s execution time)
ASYNC_ROUTES = {"global", "drift"}

router = APIRouter(prefix="/chat", tags=["chat"])


# ============================================================================
# Redis-backed Chat Job Tracker
# ============================================================================

class ChatJobTracker:
    """
    Redis-backed tracker for async chat jobs.
    
    Used for Routes 3/4 (Global/DRIFT) which can take >5s to complete.
    Enables polling pattern for clients that don't support streaming.
    """
    
    def __init__(self):
        self._redis_service: Optional[RedisService] = None
    
    async def _get_store(self):
        """Lazy-init Redis connection."""
        if self._redis_service is None:
            self._redis_service = await get_redis_service()
        return self._redis_service.operations
    
    async def create(
        self,
        job_id: str,
        group_id: str,
        user_id: str,
        query: str,
        approach: str,
        folder_id: Optional[str] = None,
    ) -> None:
        """Create a new chat job."""
        store = await self._get_store()
        await store.create(
            operation_id=job_id,
            tenant_id=group_id,
            operation_type="chat_query",
            metadata={
                "user_id": user_id,
                "query": query,
                "approach": approach,
                "folder_id": folder_id,
                "created_at": time.time(),
                "thoughts": [],  # Progressive updates
            }
        )
    
    async def update(
        self,
        job_id: str,
        status_str: str,
        answer: Optional[str] = None,
        thoughts: Optional[List[Dict[str, str]]] = None,
        route_used: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update job status and results."""
        store = await self._get_store()
        
        status_map = {
            "pending": OperationStatus.PENDING,
            "running": OperationStatus.IN_PROGRESS,
            "completed": OperationStatus.COMPLETED,
            "failed": OperationStatus.FAILED,
        }
        
        metadata_update = {}
        if answer is not None:
            metadata_update["answer"] = answer
        if thoughts is not None:
            metadata_update["thoughts"] = thoughts
        if route_used is not None:
            metadata_update["route_used"] = route_used
        if usage is not None:
            metadata_update["usage"] = usage
        if status_str in ("completed", "failed"):
            metadata_update["completed_at"] = time.time()
        
        await store.update(
            operation_id=job_id,
            status=status_map.get(status_str, OperationStatus.IN_PROGRESS),
            error=error,
            metadata_update=metadata_update,
        )
    
    async def append_thought(self, job_id: str, thought: Dict[str, str]) -> None:
        """Append a thought to the job's thoughts list."""
        store = await self._get_store()
        op = await store.get(job_id)
        if op:
            thoughts = op.metadata.get("thoughts", [])
            thoughts.append(thought)
            await store.update(
                operation_id=job_id,
                status=op.status,
                metadata_update={"thoughts": thoughts},
            )
    
    async def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job by ID."""
        store = await self._get_store()
        op = await store.get(job_id)
        
        if not op:
            return None
        
        status_map = {
            OperationStatus.PENDING: "pending",
            OperationStatus.IN_PROGRESS: "running",
            OperationStatus.COMPLETED: "completed",
            OperationStatus.FAILED: "failed",
        }
        
        return {
            "job_id": op.id,
            "status": status_map.get(op.status, "pending"),
            "group_id": op.tenant_id,
            "user_id": op.metadata.get("user_id"),
            "query": op.metadata.get("query"),
            "approach": op.metadata.get("approach"),
            "answer": op.metadata.get("answer"),
            "thoughts": op.metadata.get("thoughts", []),
            "route_used": op.metadata.get("route_used"),
            "usage": op.metadata.get("usage"),
            "error": op.error,
            "created_at": op.metadata.get("created_at"),
            "completed_at": op.metadata.get("completed_at"),
        }


# Global job tracker (Redis-backed)
_chat_jobs = ChatJobTracker()


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


class ThoughtItem(BaseModel):
    """Single thought item for progressive updates."""
    title: str = Field(..., description="Thought title/category")
    description: str = Field(..., description="Thought content")


class ChatJobResponse(BaseModel):
    """Response for async job submission (202 Accepted)."""
    job_id: str = Field(..., description="Unique job identifier for polling")
    status: str = Field(default="pending", description="Job status: pending, running, completed, failed")
    poll_url: str = Field(..., description="URL to poll for job status")


class ChatJobStatusResponse(BaseModel):
    """Full job status response."""
    job_id: str
    status: str = Field(..., description="Job status: pending, running, completed, failed")
    query: Optional[str] = None
    approach: Optional[str] = None
    answer: Optional[str] = None
    thoughts: List[ThoughtItem] = Field(default_factory=list)
    route_used: Optional[str] = None
    usage: Optional[ChatUsage] = None
    error: Optional[str] = None
    created_at: Optional[float] = None
    completed_at: Optional[float] = None


# ============================================================================
# Pipeline Integration
# ============================================================================

async def _get_hybrid_pipeline(group_id: str, folder_id: Optional[str] = None):
    """Get or create HybridPipeline instance for the given group and folder."""
    # Import here to avoid circular imports
    from src.worker.hybrid_v2.orchestrator import HybridPipeline
    from src.worker.hybrid_v2.router.main import DeploymentProfile
    
    # Simple singleton pattern - pipelines are stateless
    pipeline = HybridPipeline(
        group_id=group_id,
        folder_id=folder_id,  # Optional folder scope
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
    )
    return pipeline


async def _execute_query(
    query: str,
    approach: str,
    group_id: str,
    folder_id: Optional[str] = None,
    response_type: str = "detailed_report",
) -> Dict[str, Any]:
    """
    Execute a GraphRAG query via HybridPipeline.
    
    Returns dict with: answer, route_used, usage, thoughts
    """
    from src.worker.hybrid_v2.router.main import QueryRoute
    
    pipeline = await _get_hybrid_pipeline(group_id, folder_id)
    
    # Map approach to route
    route_map = {
        "hybrid": None,  # Let orchestrator decide
        "local": QueryRoute.LOCAL_SEARCH,
        "global": QueryRoute.GLOBAL_SEARCH,
        "drift": QueryRoute.DRIFT_MULTI_HOP,
    }
    
    route = route_map.get(approach)
    
    try:
        if route:
            result = await pipeline.force_route(
                query=query,
                route=route,
                response_type=response_type,
            )
        else:
            result = await pipeline.query(query, response_type)
        
        # Extract thoughts from result
        thoughts = _extract_thoughts(result)
        
        return {
            "answer": result.get("answer", ""),
            "route_used": result.get("route_selected", approach),
            "usage": {
                "prompt_tokens": result.get("token_usage", {}).get("prompt_tokens", 0),
                "completion_tokens": result.get("token_usage", {}).get("completion_tokens", 0),
                "total_tokens": result.get("token_usage", {}).get("total_tokens", 0),
            },
            "thoughts": thoughts,
            "context": result.get("context", {}),
        }
    except Exception as e:
        logger.error("query_execution_failed", error=str(e), approach=approach)
        raise


def _extract_thoughts(result: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract thoughts from HybridPipeline result for frontend display.
    
    Maps internal GraphRAG data to frontend-compatible thoughts format.
    """
    thoughts = []
    
    # Route selection
    route = result.get("route_selected", "unknown")
    thoughts.append({
        "title": "Route Selection",
        "description": f"Using {route} for this query",
    })
    
    # Entities found
    entities = result.get("context", {}).get("entities", [])
    if entities:
        entity_names = [e.get("name", str(e)) if isinstance(e, dict) else str(e) for e in entities[:10]]
        thoughts.append({
            "title": "Entities Found",
            "description": ", ".join(entity_names) + ("..." if len(entities) > 10 else ""),
        })
    
    # Communities matched (for global search)
    communities = result.get("context", {}).get("communities", [])
    if communities:
        community_count = len(communities)
        thoughts.append({
            "title": "Communities Matched",
            "description": f"Found {community_count} relevant communities",
        })
    
    # Retrieval info
    chunks = result.get("context", {}).get("chunks", [])
    if chunks:
        thoughts.append({
            "title": "Evidence Retrieved",
            "description": f"Retrieved {len(chunks)} text chunks as supporting evidence",
        })
    
    return thoughts


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/status/{job_id}", response_model=ChatJobStatusResponse)
async def get_chat_job_status(
    job_id: str,
    group_id: str = Depends(get_group_id),
):
    """
    Get the status of an async chat job.
    
    Use this endpoint to poll for completion when using async mode
    (Routes 3/4 which may take >5 seconds).
    
    Returns:
        - 200: Job found with current status
        - 404: Job not found
    """
    job = await _chat_jobs.get(job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    # Verify ownership (job belongs to this group)
    if job.get("group_id") != group_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    # Convert thoughts to ThoughtItem format
    thoughts = [
        ThoughtItem(title=t.get("title", ""), description=t.get("description", ""))
        for t in job.get("thoughts", [])
    ]
    
    # Build usage if available
    usage = None
    if job.get("usage"):
        usage = ChatUsage(**job["usage"])
    
    return ChatJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        query=job.get("query"),
        approach=job.get("approach"),
        answer=job.get("answer"),
        thoughts=thoughts,
        route_used=job.get("route_used"),
        usage=usage,
        error=job.get("error"),
        created_at=job.get("created_at"),
        completed_at=job.get("completed_at"),
    )


@router.post("/completions")
async def chat_completions(
    request: Request,
    body: ChatRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """
    OpenAI-compatible chat completion endpoint.
    
    Maps to internal GraphRAG hybrid query orchestration.
    Supports multiple modes:
    - Streaming: Returns SSE stream with progressive thoughts + content
    - Sync (local): Returns immediately for fast routes (<5s)
    - Async (global/drift): Returns 202 Accepted with job_id for polling
    
    Set `stream=true` for streaming mode (recommended for Routes 3/4).
    """
    # Extract user query
    user_messages = [msg for msg in body.messages if msg.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")
    
    query = user_messages[-1].content
    approach = body.approach or "hybrid"
    
    logger.info(
        "chat_completion_request",
        group_id=group_id,
        user_id=user_id,
        approach=approach,
        stream=body.stream,
        query_preview=query[:50],
    )
    
    if body.stream:
        # Return streaming response with NDJSON thoughts
        return StreamingResponse(
            _stream_chat_response(body, group_id, user_id),
            media_type="text/event-stream",
        )
    
    # Non-streaming: check if route should be async
    if approach in ASYNC_ROUTES:
        # Routes 3/4 (Global/DRIFT) - use async pattern
        return await _submit_async_job(query, approach, group_id, user_id, request, body.folder_id)
    
    # Sync route (local/hybrid) - execute immediately
    try:
        result = await _execute_query(query, approach, group_id, body.folder_id)
        
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        return ChatResponse(
            id=response_id,
            created=int(time.time()),
            model=f"graphrag-{result.get('route_used', approach).lower()}",
            choices=[
                ChatChoice(
                    message=ChatMessage(
                        role="assistant",
                        content=result.get("answer", ""),
                    ),
                    finish_reason="stop",
                )
            ],
            usage=ChatUsage(**result.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})),
        )
        
    except Exception as e:
        logger.error("chat_completion_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _submit_async_job(
    query: str,
    approach: str,
    group_id: str,
    user_id: str,
    request: Request,
    folder_id: Optional[str] = None,
) -> JSONResponse:
    """
    Submit an async job for long-running queries (Routes 3/4).
    
    Returns 202 Accepted with job_id for polling.
    """
    job_id = f"chat-{uuid.uuid4().hex[:16]}"
    
    # Create job in Redis
    await _chat_jobs.create(
        job_id=job_id,
        group_id=group_id,
        user_id=user_id,
        query=query,
        approach=approach,
        folder_id=folder_id,
    )
    
    # Start background execution
    asyncio.create_task(_execute_async_job(job_id, query, approach, group_id, folder_id))
    
    # Build poll URL
    base_url = str(request.base_url).rstrip("/")
    poll_url = f"{base_url}/chat/status/{job_id}"
    
    logger.info(
        "async_job_submitted",
        job_id=job_id,
        approach=approach,
        group_id=group_id,
    )
    
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=ChatJobResponse(
            job_id=job_id,
            status="pending",
            poll_url=poll_url,
        ).model_dump(),
    )


async def _execute_async_job(
    job_id: str,
    query: str,
    approach: str,
    group_id: str,
    folder_id: Optional[str] = None,
) -> None:
    """
    Background task to execute async job.
    
    Updates job status in Redis as it progresses.
    """
    try:
        # Mark as running
        await _chat_jobs.update(job_id, "running")
        await _chat_jobs.append_thought(job_id, {
            "title": "Starting Query",
            "description": f"Processing with {approach} approach...",
        })
        
        # Execute query
        result = await _execute_query(query, approach, group_id, folder_id)
        
        # Update with results
        await _chat_jobs.update(
            job_id=job_id,
            status_str="completed",
            answer=result.get("answer"),
            thoughts=result.get("thoughts", []),
            route_used=result.get("route_used"),
            usage=result.get("usage"),
        )
        
        logger.info("async_job_completed", job_id=job_id)
        
    except Exception as e:
        logger.error("async_job_failed", job_id=job_id, error=str(e))
        await _chat_jobs.update(
            job_id=job_id,
            status_str="failed",
            error=str(e),
        )


async def _stream_chat_response(
    request: ChatRequest,
    group_id: str,
    user_id: str,
) -> AsyncGenerator[str, None]:
    """
    Generate streaming chat response with NDJSON thoughts.
    
    Yields Server-Sent Events compatible with OpenAI streaming API,
    with progressive thought updates for long-running Routes 3/4.
    
    Format (per azure-search-openai-demo spec):
    ```
    {"delta": {"role": "assistant", "content": ""}, "context": {"thoughts": [...]}}
    {"delta": {"role": "assistant", "content": "partial"}, "context": {...}}
    {"delta": {"role": "assistant", "content": " answer"}, "context": {...}}
    ```
    """
    response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    
    try:
        # Extract user query
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if not user_messages:
            raise ValueError("No user message found")
        
        query = user_messages[-1].content
        approach = request.approach or "hybrid"
        
        logger.info(
            "streaming_chat_started",
            response_id=response_id,
            approach=approach,
            query_preview=query[:50],
        )
        
        # Send initial chunk with role and first thought
        initial_thoughts = [{"title": "Starting Query", "description": f"Processing with {approach} approach..."}]
        yield _format_stream_chunk(response_id, created, approach, "", initial_thoughts, role="assistant")
        
        # Add route selection thought
        await asyncio.sleep(0.1)  # Small delay for progressive feel
        thoughts = initial_thoughts + [{"title": "Route Selection", "description": f"Using {approach} route"}]
        yield _format_stream_chunk(response_id, created, approach, "", thoughts)
        
        # Execute the actual query (with optional folder scope)
        try:
            result = await _execute_query(query, approach, group_id, request.folder_id)
            
            # Add result thoughts
            thoughts = result.get("thoughts", [])
            
            # Stream the answer progressively
            answer = result.get("answer", "")
            route_used = result.get("route_used", approach)
            
            # For better UX, stream answer in chunks (simulate word-by-word)
            words = answer.split()
            buffer = ""
            chunk_size = 5  # Words per chunk
            
            for i, word in enumerate(words):
                buffer += word + " "
                if (i + 1) % chunk_size == 0 or i == len(words) - 1:
                    yield _format_stream_chunk(
                        response_id, created, route_used, buffer.strip() + " ", thoughts
                    )
                    buffer = ""
                    await asyncio.sleep(0.02)  # Natural typing feel
            
            # Send final chunk with finish_reason
            yield _format_stream_chunk(
                response_id, created, route_used, "", thoughts, finish_reason="stop"
            )
            
        except Exception as e:
            logger.error("streaming_query_failed", error=str(e))
            error_thoughts = thoughts if 'thoughts' in dir() else initial_thoughts
            error_thoughts.append({"title": "Error", "description": str(e)})
            yield _format_stream_chunk(
                response_id, created, approach, f"Error: {str(e)}", error_thoughts, finish_reason="error"
            )
        
        # Signal stream end
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.error("streaming_setup_failed", error=str(e), exc_info=True)
        error_chunk = {
            "error": {
                "message": str(e),
                "type": "internal_error",
                "code": 500,
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"


def _format_stream_chunk(
    response_id: str,
    created: int,
    model: str,
    content: str,
    thoughts: List[Dict[str, str]],
    role: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> str:
    """
    Format a streaming chunk in NDJSON format with thoughts context.
    
    Compatible with azure-search-openai-demo frontend expectations.
    """
    # Build delta
    delta: Dict[str, Any] = {}
    if role:
        delta["role"] = role
    if content:
        delta["content"] = content
    
    # Build context with thoughts
    context = {
        "thoughts": thoughts,
    }
    
    # Full chunk payload
    chunk = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": f"graphrag-{model.lower() if model else 'hybrid'}",
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
        "context": context,
    }
    
    return f"data: {json.dumps(chunk)}\n\n"


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


# ============================================================================
# azure-search-openai-demo Compatible Endpoints
# ============================================================================

class FrontendChatOverrides(BaseModel):
    """Override options from frontend context."""
    retrieval_mode: Optional[str] = None
    semantic_ranker: Optional[bool] = None
    semantic_captions: Optional[bool] = None
    query_rewriting: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    temperature: Optional[float] = None
    top: Optional[int] = None
    suggest_followup_questions: Optional[bool] = True
    send_text_sources: Optional[bool] = True
    send_image_sources: Optional[bool] = False
    search_text_embeddings: Optional[bool] = True
    search_image_embeddings: Optional[bool] = False
    language: Optional[str] = "en"
    use_agentic_knowledgebase: Optional[bool] = False


class FrontendChatContext(BaseModel):
    """Context from frontend request."""
    overrides: Optional[FrontendChatOverrides] = None


class FrontendChatRequest(BaseModel):
    """
    Request model matching azure-search-openai-demo frontend.
    
    Example:
    {
        "messages": [{"role": "user", "content": "What is..."}],
        "context": {"overrides": {"retrieval_mode": "hybrid"}},
        "session_state": null
    }
    """
    messages: List[ChatMessage]
    context: Optional[FrontendChatContext] = None
    session_state: Optional[Any] = None


class FrontendDataPoints(BaseModel):
    """Data points in response context."""
    text: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)


class FrontendThought(BaseModel):
    """Thought item for frontend display."""
    title: str
    description: Any  # Can be string or object
    props: Optional[Dict[str, Any]] = None


class FrontendResponseContext(BaseModel):
    """Context in response matching frontend expectations."""
    data_points: FrontendDataPoints = Field(default_factory=FrontendDataPoints)
    followup_questions: Optional[List[str]] = None
    thoughts: List[FrontendThought] = Field(default_factory=list)


class FrontendChatResponse(BaseModel):
    """
    Response model matching azure-search-openai-demo frontend.
    
    Used for non-streaming /chat endpoint.
    """
    message: ChatMessage
    context: FrontendResponseContext
    session_state: Optional[Any] = None


@router.post("", response_model=FrontendChatResponse)
async def frontend_chat(
    request: Request,
    body: FrontendChatRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """
    Non-streaming chat endpoint for azure-search-openai-demo frontend.
    
    POST /chat
    
    Maps frontend request to GraphRAG hybrid query and returns
    response in frontend-expected format.
    """
    # Extract user query
    user_messages = [msg for msg in body.messages if msg.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")
    
    query = user_messages[-1].content
    
    # Map frontend overrides to approach
    overrides = body.context.overrides if body.context else None
    approach = "hybrid"  # Default
    if overrides and overrides.retrieval_mode:
        mode_map = {"vectors": "local", "text": "global", "hybrid": "hybrid"}
        approach = mode_map.get(overrides.retrieval_mode, "hybrid")
    
    logger.info(
        "frontend_chat_request",
        group_id=group_id,
        user_id=user_id,
        approach=approach,
        query_preview=query[:50],
    )
    
    try:
        result = await _execute_query(query, approach, group_id)
        
        # Build frontend-compatible response
        thoughts = [
            FrontendThought(title=t.get("title", ""), description=t.get("description", ""))
            for t in result.get("thoughts", [])
        ]
        
        # Extract citations from context
        context_data = result.get("context", {})
        chunks = context_data.get("chunks", [])
        citations = []
        text_points = []
        for chunk in chunks[:10]:  # Limit to 10 citations
            if isinstance(chunk, dict):
                source = chunk.get("source", chunk.get("file_name", ""))
                content = chunk.get("content", chunk.get("text", ""))
                if source:
                    citations.append(source)
                if content:
                    text_points.append(content[:500])  # Truncate long content
        
        # Generate followup questions if requested
        followup_questions = None
        if overrides and overrides.suggest_followup_questions:
            # Simple followup generation based on route
            route_used = result.get("route_used", "hybrid")
            followup_questions = [
                f"Can you elaborate on the key findings?",
                f"What are the supporting documents for this answer?",
                f"Are there any related topics I should explore?",
            ]
        
        return FrontendChatResponse(
            message=ChatMessage(
                role="assistant",
                content=result.get("answer", ""),
            ),
            context=FrontendResponseContext(
                data_points=FrontendDataPoints(
                    text=text_points,
                    citations=citations,
                ),
                followup_questions=followup_questions,
                thoughts=thoughts,
            ),
            session_state=body.session_state,
        )
        
    except Exception as e:
        logger.error("frontend_chat_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def frontend_chat_stream(
    request: Request,
    body: FrontendChatRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """
    Streaming chat endpoint for azure-search-openai-demo frontend.
    
    POST /chat/stream
    
    Returns NDJSON stream with progressive updates:
    - {"delta": {"role": "assistant"}, "context": {...}}
    - {"delta": {"content": "partial"}, "context": {...}}
    - {"delta": {"content": " answer"}, "context": {...}}
    """
    # Extract user query
    user_messages = [msg for msg in body.messages if msg.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")
    
    query = user_messages[-1].content
    
    # Map frontend overrides to approach
    overrides = body.context.overrides if body.context else None
    approach = "hybrid"
    if overrides and overrides.retrieval_mode:
        mode_map = {"vectors": "local", "text": "global", "hybrid": "hybrid"}
        approach = mode_map.get(overrides.retrieval_mode, "hybrid")
    
    logger.info(
        "frontend_chat_stream_request",
        group_id=group_id,
        user_id=user_id,
        approach=approach,
        query_preview=query[:50],
    )
    
    return StreamingResponse(
        _frontend_stream_response(query, approach, group_id, body.session_state, overrides),
        media_type="application/x-ndjson",
    )


async def _frontend_stream_response(
    query: str,
    approach: str,
    group_id: str,
    session_state: Optional[Any],
    overrides: Optional[FrontendChatOverrides],
) -> AsyncGenerator[str, None]:
    """
    Generate streaming response in azure-search-openai-demo format.
    
    NDJSON format:
    {"delta": {"role": "assistant"}, "context": {"thoughts": [...]}}
    {"delta": {"content": "Hello"}, "context": {...}}
    """
    try:
        # Initial chunk with role and starting thought
        initial_thoughts = [
            {"title": "Processing", "description": f"Analyzing query with {approach} approach..."}
        ]
        yield json.dumps({
            "delta": {"role": "assistant"},
            "context": {
                "data_points": {"text": [], "images": [], "citations": []},
                "thoughts": initial_thoughts,
            },
            "session_state": session_state,
        }) + "\n"
        
        # Execute query
        result = await _execute_query(query, approach, group_id)
        
        # Extract context data
        thoughts = result.get("thoughts", [])
        context_data = result.get("context", {})
        chunks = context_data.get("chunks", [])
        
        # Build citations and text points
        citations = []
        text_points = []
        for chunk in chunks[:10]:
            if isinstance(chunk, dict):
                source = chunk.get("source", chunk.get("file_name", ""))
                content = chunk.get("content", chunk.get("text", ""))
                if source:
                    citations.append(source)
                if content:
                    text_points.append(content[:500])
        
        # Build context for streaming
        stream_context = {
            "data_points": {
                "text": text_points,
                "images": [],
                "citations": citations,
            },
            "thoughts": thoughts,
            "followup_questions": [
                "Can you elaborate on the key findings?",
                "What are the supporting documents for this answer?",
            ] if overrides and overrides.suggest_followup_questions else None,
        }
        
        # Stream answer progressively
        answer = result.get("answer", "")
        words = answer.split()
        chunk_size = 3  # Words per chunk for natural feel
        
        for i in range(0, len(words), chunk_size):
            chunk_words = words[i:i + chunk_size]
            content = " ".join(chunk_words)
            if i + chunk_size < len(words):
                content += " "
            
            yield json.dumps({
                "delta": {"content": content},
                "context": stream_context,
                "session_state": session_state,
            }) + "\n"
            
            await asyncio.sleep(0.03)  # Natural typing feel
        
        # Final chunk
        yield json.dumps({
            "delta": {},
            "context": stream_context,
            "session_state": session_state,
        }) + "\n"
        
    except Exception as e:
        logger.error("frontend_stream_failed", error=str(e), exc_info=True)
        yield json.dumps({
            "error": str(e),
        }) + "\n"
