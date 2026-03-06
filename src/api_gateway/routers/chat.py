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

from typing import List, Optional, AsyncGenerator, Dict, Any, Tuple
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
from src.core.services.quota_enforcer import enforce_plan_limits, quota_response_headers
from src.core.config import settings

logger = structlog.get_logger(__name__)

# Strong references for fire-and-forget background tasks (prevent GC)
_background_tasks: set = set()

# Routes that should use async pattern (typically >5s execution time)
ASYNC_ROUTES = {"global", "drift"}


async def _write_cosmos_usage(user_id: str, route: str, query_id: str, tokens: int, model: str) -> None:
    """Fire-and-forget: write a UsageRecord to Cosmos for dashboard recent_queries."""
    try:
        from src.core.services.cosmos_client import get_cosmos_client
        from src.core.models.usage import UsageRecord
        cosmos = get_cosmos_client()
        if cosmos.endpoint and not cosmos._usage_container:
            await asyncio.wait_for(cosmos.initialize(), timeout=10)
        record = UsageRecord(
            partition_id=user_id,
            user_id=user_id,
            usage_type="llm_completion",
            model=model,
            total_tokens=tokens,
            route=route,
            query_id=query_id,
        )
        await asyncio.wait_for(cosmos.write_usage_record(record), timeout=10)
    except Exception as e:
        logger.warning("chat_cosmos_usage_write_skipped", error=repr(e))

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
        self._store_lock = asyncio.Lock()
    
    async def _get_store(self):
        """Lazy-init Redis connection (double-check lock)."""
        if self._redis_service is not None:
            return self._redis_service.operations
        async with self._store_lock:
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
    rerank_tokens: int = 0
    embed_tokens: int = 0
    credits_used: int = 0
    credits_remaining: Optional[int] = None
    credits_limit: Optional[int] = None


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
    """Get or create HybridPipeline instance for the given group.

    Delegates to the hybrid router's cached pipeline factory which wires up
    all required services (LLM, Neo4j, HippoRAG, embeddings, text stores,
    communities) and calls ``pipeline.initialize()``.
    """
    from src.api_gateway.routers.hybrid import _get_or_create_pipeline  # noqa: E402
    return await _get_or_create_pipeline(group_id)


async def _execute_query(
    query: str,
    approach: str,
    group_id: str,
    folder_id: Optional[str] = None,
    response_type: str = "detailed_report",
    force_route: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a GraphRAG query via HybridPipeline.

    Args:
        query: User question
        approach: Query approach (hybrid, local, global, drift)
        group_id: Tenant group ID
        folder_id: Optional folder scope
        response_type: Response format
        force_route: Direct route string (e.g. "local_search", "unified_search").
                     When provided, bypasses approach→route mapping and uses
                     pipeline.force_route with the corresponding QueryRoute enum.

    Returns dict with: answer, route_used, usage, thoughts
    """
    from src.worker.hybrid_v2.router.main import QueryRoute

    pipeline = await _get_hybrid_pipeline(group_id, folder_id)

    # Resolve route: direct force_route string takes priority over approach mapping
    route = None
    if force_route:
        # Map force_route string to QueryRoute enum
        route_str_map = {r.value: r for r in QueryRoute}
        route = route_str_map.get(force_route)
        if route is None:
            logger.warning("unknown_force_route", force_route=force_route, available=list(route_str_map.keys()))

    if route is None and not force_route:
        # Fall back to approach-based mapping
        approach_map = {
            "hybrid": None,  # Let orchestrator decide
            "local": QueryRoute.LOCAL_SEARCH,
            "global": QueryRoute.GLOBAL_SEARCH,
            "drift": QueryRoute.DRIFT_MULTI_HOP,
        }
        route = approach_map.get(approach)
    
    try:
        if route:
            result = await pipeline.force_route(
                query=query,
                route=route,
                response_type=response_type,
                folder_id=folder_id,
            )
        else:
            result = await pipeline.query(query, response_type, folder_id=folder_id)
        
        # Extract thoughts from result
        thoughts = _extract_thoughts(result)
        
        usage_raw = result.get("usage") or {}
        return {
            "answer": result.get("response", ""),
            "route_used": result.get("route_used", approach),
            "usage": {
                "prompt_tokens": usage_raw.get("prompt_tokens", 0),
                "completion_tokens": usage_raw.get("completion_tokens", 0),
                "total_tokens": usage_raw.get("total_tokens", 0),
                "rerank_tokens": usage_raw.get("rerank_tokens", 0),
                "embed_tokens": usage_raw.get("embed_tokens", 0),
                "credits_used": usage_raw.get("credits_used", 0),
                "credits_remaining": usage_raw.get("credits_remaining"),
                "credits_limit": usage_raw.get("credits_limit"),
            },
            "thoughts": thoughts,
            "context": result.get("context", {}),
            "citations": result.get("citations", []),
        }
    except Exception as e:
        logger.error("query_execution_failed", error=str(e), approach=approach)
        raise


_ROUTE_DISPLAY_NAMES: Dict[str, str] = {
    "route_2_local_search": "Document Search",
    "route_3_global_search": "Global Analysis",
    "route_4_drift_multi_hop": "Deep Reasoning",
    "route_4_drift_workflow": "Deep Reasoning",
    "route_5_unified": "Unified Search",
    "route_6_concept_search": "Concept Search",
    "route_7_hipporag2": "Knowledge Graph Search",
}


def _friendly_route_name(internal_name: str) -> str:
    """Map internal route identifier to a user-friendly display name."""
    return _ROUTE_DISPLAY_NAMES.get(internal_name, "Hybrid Search")


def _extract_thoughts(result: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract thoughts from HybridPipeline result for frontend display.
    
    Maps internal GraphRAG data to frontend-compatible thoughts format.
    """
    thoughts = []
    
    # Route selection
    route = result.get("route_used", "unknown")
    thoughts.append({
        "title": "Route Selection",
        "description": f"Using {_friendly_route_name(route)} for this query",
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
    quota: dict = Depends(enforce_plan_limits),
):
    """
    OpenAI-compatible chat completion endpoint.
    
    Maps to internal GraphRAG hybrid query orchestration.
    Supports multiple modes:
    - Streaming: Returns SSE stream with progressive thoughts + content
    - Sync (local): Returns immediately for fast routes (<5s)
    - Async (global/drift): Returns 202 Accepted with job_id for polling
    
    Set `stream=true` for streaming mode (recommended for Routes 3/4).
    
    Rate limited by plan tier — returns 429 with Retry-After when quota exhausted.
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
            headers=quota_response_headers(quota),
        )
    
    # Non-streaming: check if route should be async
    if approach in ASYNC_ROUTES:
        # Routes 3/4 (Global/DRIFT) - use async pattern
        return await _submit_async_job(query, approach, group_id, user_id, request, body.folder_id)
    
    # Sync route (local/hybrid) - execute immediately
    try:
        result = await _execute_query(query, approach, group_id, body.folder_id)
        
        response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        route_used = result.get("route_used", approach)
        result_usage = result.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        chat_resp = ChatResponse(
            id=response_id,
            created=int(time.time()),
            model=f"graphrag-{route_used.lower()}",
            choices=[
                ChatChoice(
                    message=ChatMessage(
                        role="assistant",
                        content=result.get("answer", ""),
                    ),
                    finish_reason="stop",
                )
            ],
            usage=ChatUsage(**result_usage),
        )

        # Fire-and-forget: write usage to Cosmos for dashboard
        task = asyncio.create_task(_write_cosmos_usage(
            user_id=user_id,
            route=route_used,
            query_id=response_id,
            tokens=result_usage.get("total_tokens", 0),
            model=f"graphrag-{route_used.lower()}",
        ))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return JSONResponse(
            content=chat_resp.model_dump(),
            headers=quota_response_headers(quota),
        )
        
    except Exception as e:
        logger.error("chat_completion_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


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
    task = asyncio.create_task(_execute_async_job(job_id, query, approach, group_id, user_id, folder_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    
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
    user_id: str,
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

        # Fire-and-forget: write usage to Cosmos for dashboard
        result_usage = result.get("usage", {})
        route_used = result.get("route_used", approach)
        cosmos_task = asyncio.create_task(_write_cosmos_usage(
            user_id=user_id,
            route=route_used,
            query_id=job_id,
            tokens=result_usage.get("total_tokens", 0) if result_usage else 0,
            model=f"graphrag-{route_used.lower()}",
        ))
        _background_tasks.add(cosmos_task)
        cosmos_task.add_done_callback(_background_tasks.discard)
        
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
        initial_thoughts = [{"title": "Starting Query", "description": f"Processing with {_friendly_route_name(approach)} approach..."}]
        yield _format_stream_chunk(response_id, created, approach, "", initial_thoughts, role="assistant")
        
        # Add route selection thought
        await asyncio.sleep(0.1)  # Small delay for progressive feel
        thoughts = initial_thoughts + [{"title": "Route Selection", "description": f"Using {_friendly_route_name(approach)} route"}]
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

            # Fire-and-forget: write usage to Cosmos for dashboard
            result_usage = result.get("usage", {})
            task = asyncio.create_task(_write_cosmos_usage(
                user_id=user_id,
                route=route_used,
                query_id=response_id,
                tokens=result_usage.get("total_tokens", 0),
                model=f"graphrag-{route_used.lower()}",
            ))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            
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
        "model": f"graphrag-{_friendly_route_name(model).lower().replace(' ', '-') if model else 'hybrid'}",
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
    force_route: Optional[str] = Field(
        default=None,
        description="Force a specific route: local_search, global_search, "
                    "drift_multi_hop, unified_search, concept_search, hipporag2_search",
    )
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
    folder_id: Optional[str] = Field(default=None, description="Folder ID to scope query within the group")


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
    structured_citations: Optional[List[Dict[str, Any]]] = None


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


def _strip_citation_markers(answer: str) -> str:
    """Remove numeric [N] and [Na] citation markers from the answer text.

    The citation list is rendered separately by the frontend from
    ``context.data_points``, so inline markers are unnecessary clutter.
    """
    import re

    # Sentence-level [Na] (e.g. [1a], [2b])
    answer = re.sub(r'\s*\[\d+[a-z]\]', '', answer)
    # Chunk-level [N] (negative lookahead to avoid [1] inside e.g. [10])
    answer = re.sub(r'\s*\[\d+\](?![0-9a-z])', '', answer)
    return answer.strip()


def _build_frontend_citations(
    raw_citations: List[Dict[str, Any]],
    max_citations: int = 15,
) -> Tuple[List[str], List[str], Optional[List[Dict[str, Any]]]]:
    """Build frontend citation data from pipeline citation dicts.

    Returns:
        (flat_citations, text_points, structured_citations)
        - flat_citations: simple string list for backward compat
        - text_points: text preview snippets
        - structured_citations: rich metadata with polygon geometry
    """
    flat_citations: List[str] = []
    text_points: List[str] = []
    structured: List[Dict[str, Any]] = []

    for cit in raw_citations[:max_citations]:
        if not isinstance(cit, dict):
            continue

        doc_title = cit.get("document_title", "")
        doc_url = cit.get("document_url", "")
        if doc_url:
            flat_citations.append(doc_url)
        elif doc_title:
            flat_citations.append(doc_title)

        preview = cit.get("text_preview", "")
        if preview:
            text_points.append(preview[:500])

        sc: Dict[str, Any] = {
            "source": doc_title,
            "document_id": cit.get("document_id", ""),
            "document_title": doc_title,
            "document_url": doc_url,
            "chunk_id": cit.get("chunk_id", ""),
            "text_preview": preview,
            "score": cit.get("score", 0.0),
        }
        if cit.get("citation"):
            sc["citation"] = cit["citation"]
        if cit.get("section_path"):
            sc["section_path"] = cit["section_path"]
        if cit.get("page_number") is not None:
            sc["page_number"] = cit["page_number"]
        if cit.get("start_offset") is not None:
            sc["start_offset"] = cit["start_offset"]
        if cit.get("end_offset") is not None:
            sc["end_offset"] = cit["end_offset"]
        if cit.get("sentences"):
            sc["sentences"] = cit["sentences"]
        if cit.get("page_dimensions"):
            sc["page_dimensions"] = cit["page_dimensions"]
        if cit.get("sentence_text"):
            sc["sentence_text"] = cit["sentence_text"]
        if cit.get("sentence_offset") is not None:
            sc["sentence_offset"] = cit["sentence_offset"]
        if cit.get("sentence_length") is not None:
            sc["sentence_length"] = cit["sentence_length"]
        if cit.get("citation_type"):
            sc["citation_type"] = cit["citation_type"]

        structured.append(sc)

    return flat_citations, text_points, structured if structured else None


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
    force_route_str: Optional[str] = None
    if overrides:
        if overrides.force_route:
            # Direct route override — pass through to _execute_query
            force_route_str = overrides.force_route
            approach = overrides.force_route
        elif overrides.retrieval_mode:
            mode_map = {"vectors": "local", "text": "global", "hybrid": "hybrid"}
            approach = mode_map.get(overrides.retrieval_mode, "hybrid")

    logger.info(
        "frontend_chat_request",
        group_id=group_id,
        user_id=user_id,
        approach=approach,
        force_route=force_route_str,
        query_preview=query[:50],
    )

    try:
        folder_id = overrides.folder_id if overrides else None
        result = await _execute_query(query, approach, group_id, folder_id=folder_id, force_route=force_route_str)
        
        # Build frontend-compatible response
        thoughts = [
            FrontendThought(title=t.get("title", ""), description=t.get("description", ""))
            for t in result.get("thoughts", [])
        ]
        
        # Build citations from pipeline result
        raw_citations = result.get("citations", [])
        flat_citations, text_points, structured_citations = _build_frontend_citations(
            raw_citations
        )

        # Keep inline [N] citation markers so the frontend parser can render
        # them as clickable superscript badges linked to structured_citations.
        answer_text = result.get("answer", "")

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
                content=answer_text,
            ),
            context=FrontendResponseContext(
                data_points=FrontendDataPoints(
                    text=text_points,
                    citations=flat_citations,
                    structured_citations=structured_citations,
                ),
                followup_questions=followup_questions,
                thoughts=thoughts,
            ),
            session_state=body.session_state,
        )
        
    except Exception as e:
        logger.error("frontend_chat_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


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
    force_route_str: Optional[str] = None
    if overrides:
        if overrides.force_route:
            force_route_str = overrides.force_route
            approach = overrides.force_route
        elif overrides.retrieval_mode:
            mode_map = {"vectors": "local", "text": "global", "hybrid": "hybrid"}
            approach = mode_map.get(overrides.retrieval_mode, "hybrid")

    logger.info(
        "frontend_chat_stream_request",
        group_id=group_id,
        user_id=user_id,
        approach=approach,
        force_route=force_route_str,
        query_preview=query[:50],
    )

    return StreamingResponse(
        _frontend_stream_response(query, approach, group_id, body.session_state, overrides, force_route_str),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


async def _frontend_stream_response(
    query: str,
    approach: str,
    group_id: str,
    session_state: Optional[Any],
    overrides: Optional[FrontendChatOverrides],
    force_route: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Generate streaming response in azure-search-openai-demo format.
    
    NDJSON format:
    {"delta": {"role": "assistant"}, "context": {"thoughts": [...]}}
    {"delta": {"content": "Hello"}, "context": {...}}

    Uses ``except BaseException`` so that ``CancelledError`` (raised by
    ``asyncio.timeout`` / ``asyncio.wait_for``) and ``GeneratorExit`` are
    caught instead of silently producing an empty body.
    """
    query_task: Optional[asyncio.Task] = None
    try:
        # Initial chunk with role and starting thought
        initial_thoughts = [
            {"title": "Processing", "description": f"Analyzing query with {_friendly_route_name(approach)} approach..."}
        ]
        yield json.dumps({
            "delta": {"role": "assistant"},
            "context": {
                "data_points": {"text": [], "images": [], "citations": []},
                "thoughts": initial_thoughts,
            },
            "session_state": session_state,
        }) + "\n"
        
        # Execute query in background while sending keepalive pings
        folder_id = overrides.folder_id if overrides else None
        query_task = asyncio.create_task(
            _execute_query(query, approach, group_id, folder_id=folder_id, force_route=force_route)
        )
        while not query_task.done():
            await asyncio.sleep(2)
            if not query_task.done():
                yield json.dumps({"delta": {}, "session_state": session_state}) + "\n"
        result = query_task.result()
        
        # Extract context data
        thoughts = result.get("thoughts", [])

        # Build citations from pipeline result
        raw_citations = result.get("citations", [])
        flat_citations, text_points, structured_citations = _build_frontend_citations(
            raw_citations
        )

        # Build context for streaming
        stream_context = {
            "data_points": {
                "text": text_points,
                "images": [],
                "citations": flat_citations,
                "structured_citations": structured_citations,
            },
            "thoughts": thoughts,
            "followup_questions": [
                "Can you elaborate on the key findings?",
                "What are the supporting documents for this answer?",
            ] if overrides and overrides.suggest_followup_questions else None,
        }
        
        # Keep inline [N] citation markers for frontend rendering
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

    except BaseException as e:
        # BaseException catches CancelledError and GeneratorExit — without
        # this the generator silently produces zero bytes on timeout/cancel.
        if isinstance(e, GeneratorExit):
            # Client disconnected; nothing to yield — just clean up.
            return
        error_type = type(e).__name__
        logger.error("frontend_stream_failed", error=str(e), error_type=error_type, exc_info=True)
        try:
            yield json.dumps({
                "error": f"{error_type}: {e}",
            }) + "\n"
        except GeneratorExit:
            pass
    finally:
        if query_task and not query_task.done():
            query_task.cancel()
