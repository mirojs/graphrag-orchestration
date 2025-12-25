"""
GraphRAG V3 API Router

This router provides V3 endpoints that are completely separate from V1/V2.
All V3 endpoints use:
- Neo4j as the ONLY query-time data store
- LlamaIndex for indexing
- MS GraphRAG DRIFT for multi-step reasoning
- RAPTOR for hierarchical summaries

Endpoints:
- POST /v3/index - Index documents
- POST /v3/query/local - Local search (entity-focused)
- POST /v3/query/global - Global search (community summaries)
- POST /v3/query/drift - DRIFT multi-step reasoning
- GET /v3/stats/{group_id} - Get indexing statistics
"""

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union, Literal
import asyncio
import json
import math
import os
import re
import structlog
import traceback
import uuid

from app.core.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/v3", tags=["GraphRAG V3"])


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na) * math.sqrt(nb)
    return (dot / denom) if denom else 0.0


def _normalize_for_grounding(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_value_like_spans(answer: str) -> List[str]:
    """Extract spans that look like concrete values.

    We only validate these against context to reduce hallucinations:
    - URLs
    - long digit sequences (IDs, amounts, routing/account numbers)
    - alnum identifiers like REG-54321 / RB-21106
    """
    a = answer or ""
    spans: list[str] = []
    spans.extend(re.findall(r"https?://\S+", a, flags=re.IGNORECASE))
    spans.extend(re.findall(r"\b\d{4,}\b", a))
    spans.extend(re.findall(r"\b[A-Za-z]{1,6}[-_]\d{2,}\b", a))
    # Deduplicate while preserving order
    seen = set()
    out: list[str] = []
    for s in spans:
        key = re.sub(r"[^a-z0-9]", "", s.lower())
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _value_spans_grounded(answer: str, context: str) -> bool:
    ctx = _normalize_for_grounding(context)
    if not ctx:
        return False
    for span in _extract_value_like_spans(answer):
        span_key = re.sub(r"[^a-z0-9]", "", span.lower())
        if not span_key:
            continue
        ctx_key = re.sub(r"[^a-z0-9]", "", ctx)
        if span_key not in ctx_key:
            return False
    return True


def _strengthen_global_prompt(context: str, query: str) -> str:
    return f"""You are answering strictly from the provided community summaries.

Rules (must follow):
- Only use facts explicitly present in the summaries.
- Never invent or guess numbers, IDs, URLs, names, locations, dates, or clauses.
- If a specific value is not explicitly present, respond with exactly: Not specified in the provided documents.

Community Summaries:
{context}

Question: {query}

Answer:"""


def _global_map_prompt(community_report: str, query: str) -> str:
    return f"""You are given ONE community report from a GraphRAG system.

Task:
- Extract ONLY the information from this report that directly helps answer the user question.

Rules (must follow):
- Use ONLY the provided report content.
- Do not invent or guess numbers, IDs, URLs, names, locations, dates, or clauses.
- If the report does not contain relevant information for the question, respond with exactly: Not specified in the provided documents.
- Do NOT mention system state or workflow (no: indexing, community reports, summaries available, "please index", etc.).
- If the question asks for concrete terms (amounts, notice periods, jurisdictions), prefer quoting exact phrases from the report's chunk snippets.

Community Report:
{community_report}

Question: {query}

Relevant answer (or Not specified in the provided documents.):"""


def _global_reduce_prompt(map_answers: str, query: str) -> str:
    return f"""You are given evidence extracted from indexed documents.

Task:
- Produce a single final answer to the user question using ONLY the evidence.

Rules (must follow):
- Use ONLY the provided evidence.
- Do not invent or guess numbers, IDs, URLs, names, locations, dates, or clauses.
- If the evidence does not contain the information needed, respond with exactly: Not specified in the provided documents.
- Do NOT mention system state or workflow (no: indexing, community reports, "no community summaries", "please index", etc.).
- When listing values like jurisdictions, fees/amounts, or notice periods, quote the exact phrase from evidence and (when available) attribute it to the document shown in the header.
- If some evidence sections say "Not specified" but other evidence contains relevant clauses, include the relevant clauses and ignore the "Not specified" sections.

Evidence:
{map_answers}

Question: {query}

Final answer:"""


def _lexical_terms_for_global_query(query: str) -> list[str]:
    """Heuristic terms to pull exact-phrase chunks for common Global QA intents."""
    q = (query or "").lower()
    terms: list[str] = []

    if any(k in q for k in ["jurisdiction", "governing law", "venue", "laws of", "governed by"]):
        terms.extend([
            "governing law",
            "governed by",
            "laws of",
            "jurisdiction",
            "venue",
            "state of",
            "county",
        ])

    if any(k in q for k in ["notice", "delivery", "certified mail", "return receipt", "written notice"]):
        terms.extend([
            "certified mail",
            "return receipt",
            "return receipt requested",
            "written notice",
            "by mail",
        ])

    if any(k in q for k in ["pay", "fee", "fees", "charge", "charges", "tax", "invoice", "amount", "amount due", "balance due", "total"]):
        terms.extend([
            "amount due",
            "balance due",
            "total",
            "subtotal",
            "tax",
            "invoice",
        ])

    if any(k in q for k in ["party", "parties", "organization", "organizations", "named parties", "named party"]):
        terms.extend([
            "hereinafter",
            "llc",
            "inc",
            "ltd",
            "corporation",
            "agent:",
            "owner",
        ])

    if any(k in q for k in ["insurance", "indemnity", "hold harmless", "liability", "coverage"]):
        terms.extend([
            "insurance",
            "liability",
            "coverage",
            "indemnify",
            "hold harmless",
            "300,000",
            "25,000",
        ])

    # De-dup while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        v = (t or "").strip().lower()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(t)
    return out


def _is_empty_or_unhelpful_global_answer(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in {
        "not specified in the provided documents.",
        "not specified in the provided documents",
        "not specified",
        "n/a",
        "none",
        "no",
    }:
        return True
    # Common "no info" phrasings
    if "not specified in the provided documents" in t:
        return True
    if "no relevant" in t and "information" in t:
        return True
    # Avoid leaking internal indexing guidance into answers.
    if "please index" in t and "document" in t:
        return True
    if "no community" in t and "available" in t:
        return True
    return False


def _get_env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _community_text_for_embedding(c: Any) -> str:
    text = f"{getattr(c, 'title', '')}\n{getattr(c, 'summary', '')}".strip()
    if len(text) > 8000:
        text = text[:8000]
    return text


def _rank_communities_for_query(adapter: Any, query: str, communities: list[Any]) -> list[Any]:
    """Rank communities by embedding similarity to query when possible."""
    try:
        if getattr(adapter, "embedder", None) is None:
            return sorted(communities, key=lambda c: getattr(c, "rank", 0.0), reverse=True)
        q_emb = adapter.embedder.get_text_embedding(query)
        scored: list[tuple[float, Any]] = []
        for c in communities:
            c_emb = adapter.embedder.get_text_embedding(_community_text_for_embedding(c))
            scored.append((_cosine_similarity(q_emb, c_emb), c))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [c for _, c in scored]
    except Exception:
        return sorted(communities, key=lambda c: getattr(c, "rank", 0.0), reverse=True)


def _safe_json_loads(text: str) -> Any:
    """Parse JSON returned by LLM, tolerating fenced code blocks."""
    t = (text or "").strip()
    if not t:
        return None
    # Strip ```json ... ``` fences if present
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
        t = t.strip()
    return json.loads(t)


def _llm_rate_communities(
    adapter: Any,
    query: str,
    communities: list[Any],
    batch_size: int,
) -> dict[str, int]:
    """Rate community relevance using an LLM (0-100).

    This is the core of Microsoft-style dynamic selection: top-down rating followed by pruning.
    Returns a mapping of community_id -> score.
    """
    llm = getattr(adapter, "llm", None)
    if llm is None:
        return {getattr(c, "id", ""): 0 for c in communities if getattr(c, "id", "")}

    scores: dict[str, int] = {}
    # Chunk to keep prompts bounded.
    for i in range(0, len(communities), max(1, batch_size)):
        batch = communities[i : i + max(1, batch_size)]
        items: list[dict[str, str]] = []
        for c in batch:
            cid = getattr(c, "id", "")
            if not cid:
                continue
            items.append(
                {
                    "id": cid,
                    "title": (getattr(c, "title", "") or "")[:200],
                    "summary": (getattr(c, "summary", "") or "")[:2000],
                }
            )

        if not items:
            continue

        prompt = (
            "You are a relevance rater for Microsoft GraphRAG Global Search dynamic community selection.\n"
            "Given a user question and a list of community reports (summaries), assign each report a relevance score from 0 to 100.\n\n"
            "Scoring rubric:\n"
            "- 0: completely irrelevant to answering the question\n"
            "- 30: tangential / might provide minor context\n"
            "- 60: relevant and likely contains supporting facts\n"
            "- 90-100: directly answers or is critical evidence\n\n"
            "Important rules:\n"
            "- Use ONLY the provided title+summary; do not assume missing details.\n"
            "- Return ONLY valid JSON (no markdown) as an object mapping community id to integer score.\n\n"
            f"Question: {query}\n\n"
            f"Communities: {json.dumps(items, ensure_ascii=False)}\n\n"
            "JSON:" 
        )

        try:
            resp = llm.complete(prompt)
            data = _safe_json_loads(getattr(resp, "text", "") or "")
            if isinstance(data, dict):
                for k, v in data.items():
                    if not isinstance(k, str):
                        continue
                    try:
                        iv = int(v)
                    except Exception:
                        continue
                    if iv < 0:
                        iv = 0
                    if iv > 100:
                        iv = 100
                    scores[k] = iv
        except Exception:
            # If rating fails, default to 0 and let pruning/ranking fallback handle it.
            continue

    # Fill any missing ids with 0 to keep downstream deterministic.
    for c in communities:
        cid = getattr(c, "id", "")
        if cid and cid not in scores:
            scores[cid] = 0
    return scores


def _dynamic_select_communities_microsoft(
    store: Any,
    adapter: Any,
    group_id: str,
    query: str,
    final_top_k: int,
    max_depth: int,
    candidate_budget: int,
    keep_per_level: int,
    score_threshold: int,
    rating_batch_size: int,
) -> tuple[list[Any], dict[str, int]]:
    """Microsoft-style dynamic community selection (top-down LLM rating + hierarchical pruning).

    Returns:
        (selected_communities, scores_by_id)
    """
    levels = store.get_community_levels(group_id)
    if not levels:
        return ([], {})

    # Start at top level (smallest).
    current_level_idx = 0
    current_level = levels[current_level_idx]
    candidates = store.get_communities_by_level(group_id=group_id, level=current_level)

    scores_by_id: dict[str, int] = {}
    selected: list[Any] = []

    depth_used = 0
    while True:
        # Bound candidates to keep prompt cost/latency controlled.
        if candidate_budget > 0 and len(candidates) > candidate_budget:
            # Prefilter by embeddings (if available), else by stored rank.
            candidates = _rank_communities_for_query(adapter, query, candidates)[:candidate_budget]

        level_scores = _llm_rate_communities(
            adapter=adapter,
            query=query,
            communities=candidates,
            batch_size=rating_batch_size,
        )
        scores_by_id.update(level_scores)

        def _score(c: Any) -> int:
            return level_scores.get(getattr(c, "id", ""), 0)

        ranked = sorted(candidates, key=_score, reverse=True)
        kept = [c for c in ranked if _score(c) >= score_threshold]
        if keep_per_level > 0:
            kept = kept[:keep_per_level]
        if final_top_k > 0:
            kept = kept[: max(final_top_k, 1)]

        selected = kept

        # Drill down
        if current_level_idx + 1 >= len(levels):
            break
        if depth_used >= max_depth:
            break
        if not kept:
            break

        next_level_idx = current_level_idx + 1
        next_level = levels[next_level_idx]
        children: list[Any] = []
        for parent in kept:
            try:
                children.extend(
                    store.get_child_communities(
                        group_id=group_id,
                        parent_id=parent.id,
                        child_level=next_level,
                    )
                )
            except Exception:
                continue

        if not children:
            break

        candidates = children
        current_level_idx = next_level_idx
        current_level = next_level
        depth_used += 1

    # Return only up to final_top_k communities for context.
    if final_top_k > 0 and len(selected) > final_top_k:
        selected = selected[:final_top_k]
    return (selected, scores_by_id)


# ==================== Request/Response Models ====================

class V3IndexRequest(BaseModel):
    """Request to index documents using V3 pipeline."""
    documents: List[Union[str, Dict[str, Any]]] = Field(
        ...,
        description="List of documents (text strings, {text, metadata} objects, or URLs)"
    )
    run_raptor: bool = Field(
        default=True,
        description="Whether to run RAPTOR hierarchical summarization"
    )
    run_community_detection: bool = Field(
        default=True,
        description="Whether to run community detection (hierarchical_leiden)"
    )
    ingestion: Literal["document-intelligence", "llamaparse", "none"] = Field(
        default="document-intelligence",
        description="Document ingestion method for PDFs/images"
    )


class V3QueryRequest(BaseModel):
    """Request for V3 queries."""
    query: str = Field(..., description="Natural language query")
    top_k: int = Field(default=10, description="Number of results to return")
    include_sources: bool = Field(default=True, description="Include source references")
    force_route: Optional[Literal["vector", "local", "graph", "raptor", "drift"]] = Field(
        default=None,
        description="Optional route override for testing/debugging (bypasses routing LLM)",
    )
    synthesize: bool = Field(
        default=True,
        description="If false, return retrieval results without LLM synthesis (faster; for debugging/testing).",
    )


class V3DriftRequest(BaseModel):
    """Request for DRIFT multi-step reasoning."""
    query: str = Field(..., description="Natural language query")
    max_iterations: int = Field(default=5, description="Maximum DRIFT iterations")
    convergence_threshold: float = Field(default=0.8, description="Stop when confidence reaches this")
    include_reasoning_path: bool = Field(default=True, description="Include step-by-step reasoning")


class V3IndexResponse(BaseModel):
    """Response from V3 indexing."""
    status: str
    group_id: str
    documents_processed: int
    entities_created: int
    relationships_created: int
    communities_created: int
    raptor_nodes_created: int
    message: str


class V3QueryResponse(BaseModel):
    """Response from V3 queries."""
    answer: str
    confidence: float
    sources: List[Dict[str, Any]] = []
    entities_used: List[str] = []
    search_type: str


class V3DriftResponse(BaseModel):
    """Response from DRIFT search."""
    answer: str
    confidence: float
    iterations: int
    sources: List[Dict[str, Any]] = []
    reasoning_path: List[Dict[str, Any]] = []
    search_type: str = "drift"


class V3StatsResponse(BaseModel):
    """Statistics for a group."""
    group_id: str
    entities: int
    relationships: int
    communities: int
    raptor_nodes: int
    text_chunks: int
    documents: int


# ==================== Service Initialization ====================

# Lazy initialization to avoid import errors
_neo4j_store = None
_drift_adapter = None
_indexing_pipeline = None
_triple_engine_retriever = None


def get_neo4j_store():
    """Get or create Neo4j store instance."""
    global _neo4j_store
    if _neo4j_store is None:
        from app.v3.services.neo4j_store import Neo4jStoreV3
        _neo4j_store = Neo4jStoreV3(
            uri=settings.NEO4J_URI or "",
            username=settings.NEO4J_USERNAME or "",
            password=settings.NEO4J_PASSWORD or "",
        )
    return _neo4j_store


def get_drift_adapter():
    """Get or create DRIFT adapter instance."""
    global _drift_adapter
    if _drift_adapter is None:
        from app.v3.services.drift_adapter import DRIFTAdapter
        from app.services.llm_service import LLMService
        
        store = get_neo4j_store()
        llm_service = LLMService()
        
        embedder = llm_service.embed_model
        
        _drift_adapter = DRIFTAdapter(
            neo4j_driver=store.driver,
            llm=llm_service.llm,
            embedder=embedder,
        )
    return _drift_adapter


def get_indexing_pipeline():
    """Get or create indexing pipeline instance."""
    global _indexing_pipeline
    if _indexing_pipeline is None:
        from app.v3.services.indexing_pipeline import IndexingPipelineV3, IndexingConfig
        from app.services.llm_service import LLMService
        
        store = get_neo4j_store()
        llm_service = LLMService()
        
        # Validate LLM service initialization
        if llm_service.llm is None:
            raise RuntimeError("LLM not initialized - check Azure OpenAI configuration and credentials")
        if llm_service.embed_model is None:
            raise RuntimeError("Embedding model not initialized - check Azure OpenAI embedding configuration and credentials")
        
        # Use indexing deployment (gpt-4.1) for RAPTOR and entity extraction
        deployment_name = settings.AZURE_OPENAI_INDEXING_DEPLOYMENT or settings.AZURE_OPENAI_DEPLOYMENT_NAME or "gpt-4o"
        
        config = IndexingConfig(
            embedding_model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT or "text-embedding-3-small",
            embedding_dimensions=1536,  # Neo4j 5.x supports up to 4096
            llm_model=deployment_name,  # Store deployment name as-is (e.g., "gpt-4.1")
        )
        
        _indexing_pipeline = IndexingPipelineV3(
            neo4j_store=store,
            llm=llm_service.get_indexing_llm(),  # Use gpt-4.1 for indexing operations
            embedder=llm_service.embed_model,
            config=config,
            llm_service=llm_service,  # Pass service for specialized model selection
        )
    return _indexing_pipeline


def get_triple_engine_retriever():
    """Get or create Triple-Engine Retriever instance."""
    global _triple_engine_retriever
    if _triple_engine_retriever is None:
        from app.v3.services.triple_engine_retriever import TripleEngineRetriever
        from app.services.llm_service import LLMService
        
        store = get_neo4j_store()
        llm_service = LLMService()
        
        _triple_engine_retriever = TripleEngineRetriever(
            store=store,
            llm_service=llm_service,
        )
    return _triple_engine_retriever


# ==================== Helper Functions ====================

def get_group_id(request: Request) -> str:
    """Extract group_id from request headers."""
    group_id = request.headers.get("X-Group-ID")
    if not group_id:
        raise HTTPException(status_code=400, detail="X-Group-ID header is required")
    return group_id


# ==================== Endpoints ====================

@router.post("/index", response_model=V3IndexResponse)
async def index_documents(
    request: Request,
    payload: V3IndexRequest,
    background_tasks: BackgroundTasks,
):
    """
    Index documents using V3 pipeline.
    
    This endpoint:
    1. Extracts entities and relationships (LlamaIndex)
    2. Computes embeddings (Azure OpenAI)
    3. Runs RAPTOR hierarchical summarization (optional)
    4. Runs community detection with hierarchical_leiden (optional)
    5. Stores everything in Neo4j
    
    All data is stored in Neo4j.
    RAPTOR nodes are also indexed in Azure AI Search for legacy compatibility.
    """
    group_id = get_group_id(request)
    logger.info("v3_index_start", group_id=group_id, num_documents=len(payload.documents))
    
    try:
        pipeline = get_indexing_pipeline()
        
        # Convert documents to the format expected by the pipeline
        docs_for_pipeline = []
        for doc in payload.documents:
            if isinstance(doc, str):
                # Check if it's a URL (for DI extraction) or plain text
                if doc.startswith(("http://", "https://")):
                    # URL - let DI extract it
                    docs_for_pipeline.append({
                        "content": "",  # Empty content triggers DI extraction
                        "title": doc.split("/")[-1] if "/" in doc else "Untitled",
                        "source": doc,  # URL in source field
                        "metadata": {},
                    })
                else:
                    # Plain text document
                    docs_for_pipeline.append({
                        "content": doc,
                        "title": "Untitled",
                        "source": "",
                        "metadata": {},
                    })
            elif isinstance(doc, dict):
                # Structured document
                docs_for_pipeline.append({
                    "content": doc.get("text", doc.get("content", "")),
                    "title": doc.get("title", "Untitled"),
                    "source": doc.get("source", doc.get("url", "")),
                    "metadata": doc.get("metadata", {}),
                })
        
        # Run indexing asynchronously after returning to avoid gateway timeouts.
        # In some deployments, relying on BackgroundTasks for long async workloads can be unreliable;
        # scheduling via asyncio.create_task ensures the coroutine is actually started.
        async def _run_indexing_async():
            try:
                stats = await pipeline.index_documents(
                    group_id=group_id,
                    documents=docs_for_pipeline,
                    reindex=False,
                    ingestion=payload.ingestion,
                )
                logger.info("v3_index_complete", group_id=group_id, stats=stats)
            except Exception as e:
                logger.error("v3_index_background_failed", group_id=group_id, error=str(e))

        try:
            asyncio.create_task(_run_indexing_async())
        except RuntimeError:
            # Extremely defensive fallback (e.g., if called without a running loop).
            background_tasks.add_task(_run_indexing_async)
        
        return V3IndexResponse(
            status="accepted",
            group_id=group_id,
            documents_processed=len(docs_for_pipeline),
            entities_created=0,  # Will be updated by background task
            relationships_created=0,
            communities_created=0,
            raptor_nodes_created=0,
            message="Indexing started in background. Check logs or query to verify completion.",
        )
        
    except Exception as e:
        logger.error("v3_index_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")


@router.post("/query", response_model=V3QueryResponse)
async def query_unified(request: Request, payload: V3QueryRequest):
    """
    Unified query endpoint with automatic route selection (Triple-Engine).
    
    Uses GPT-5.2 Thinking to route queries to the optimal engine:
    - Vector: Specific facts (dates, amounts, clause references)
    - Graph: Relational reasoning (dependencies, connections)
    - RAPTOR: Thematic summaries (portfolio risk, trends)
    
    This is the RECOMMENDED endpoint for general queries.
    Use specific endpoints (/query/local, /query/global, /query/raptor) 
    only when you need explicit control over routing.
    """
    group_id = get_group_id(request)
    logger.info("v3_unified_query", group_id=group_id, query=payload.query[:50])
    
    try:
        retriever = get_triple_engine_retriever()
        
        # Execute triple-engine retrieval with automatic routing
        result = await retriever.retrieve(
            query=payload.query,
            group_id=group_id,
            top_k=payload.top_k,
            force_route=payload.force_route,
        )
        
        return V3QueryResponse(
            answer=result.answer,
            confidence=result.confidence,
            sources=result.sources if payload.include_sources else [],
            entities_used=[s.get("name", "") for s in result.sources if "name" in s],
            search_type=result.route,
        )
        
    except Exception as e:
        logger.error("v3_unified_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.post("/query/local", response_model=V3QueryResponse)
async def query_local(request: Request, payload: V3QueryRequest):
    """
    Local search - entity-focused queries.
    
    Best for:
    - "What is X?"
    - "Tell me about entity Y"
    - Specific fact lookups
    
    Uses Neo4j vector search + graph expansion.
    
    NOTE: Consider using /v3/query (unified endpoint) instead,
    which automatically routes to the optimal search method.
    """
    group_id = get_group_id(request)
    logger.info("v3_local_search", group_id=group_id, query=payload.query[:50])
    
    try:
        import time
        t0 = time.monotonic()
        adapter = get_drift_adapter()
        
        # Use hybrid search (vector + full-text with RRF fusion)
        # get_drift_adapter() guarantees embedder is non-None
        t_embed0 = time.monotonic()
        query_embedding = adapter.embedder.embed_query(payload.query)
        t_embed1 = time.monotonic()
        
        store = get_neo4j_store()
        
        # Hybrid search: combines vector similarity with keyword matching
        # This solves the "missing facts" problem where specific values
        # (like "$25,000" or "Invoice #123") have weak embeddings
        try:
            t_db0 = time.monotonic()
            results = store.search_entities_hybrid(
                group_id=group_id,
                query_text=payload.query,
                embedding=query_embedding,
                top_k=payload.top_k,
            )
            t_db1 = time.monotonic()
        except Exception as e:
            logger.error(f"Entity vector search failed: {e}")
            # Check if entities exist at all
            with store.driver.session(database=store.database) as session:
                count_result = session.run(
                    "MATCH (e:Entity {group_id: $group_id}) RETURN count(e) as count",
                    group_id=group_id
                )
                record = count_result.single()
                count = record["count"] if record else 0
                
                if count == 0:
                    return V3QueryResponse(
                        answer="No data has been indexed for this group yet. Please index documents first.",
                        confidence=0.0,
                        sources=[],
                        entities_used=[],
                        search_type="local",
                    )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Vector search failed. Index may be missing or have wrong dimensions. Error: {str(e)}"
                    )
        
        if not results:
            return V3QueryResponse(
                answer="No relevant information found for this query.",
                confidence=0.0,
                sources=[],
                entities_used=[],
                search_type="local",
            )
        
        # Build context from entities
        context_parts = []
        entities_used = []
        sources = []
        
        for entity, score in results:
            context_parts.append(f"- {entity.name} ({entity.type}): {entity.description}")
            entities_used.append(entity.name)
            sources.append({
                "id": entity.id,
                "name": entity.name,
                "type": entity.type,
                "score": score,
            })
        
        context = "\n".join(context_parts)

        # Optional fast path: retrieval-only (no LLM call)
        if not payload.synthesize:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "v3_local_search_timing",
                group_id=group_id,
                total_ms=elapsed_ms,
                embed_ms=int((t_embed1 - t_embed0) * 1000),
                neo4j_ms=int((t_db1 - t_db0) * 1000),
                llm_ms=0,
                top_k=payload.top_k,
            )
            return V3QueryResponse(
                answer=context,
                confidence=results[0][1] if results else 0.0,
                sources=sources if payload.include_sources else [],
                entities_used=entities_used,
                search_type="local",
            )
        
        # Generate answer
        prompt = f"""Based on the following information, answer the question.
    Only use the provided information. If the answer is not present, respond with: "Not specified in the provided documents.".

Information:
{context}

Question: {payload.query}

Answer:"""
        
        t_llm0 = time.monotonic()
        response = adapter.llm.complete(prompt)
        t_llm1 = time.monotonic()

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "v3_local_search_timing",
            group_id=group_id,
            total_ms=elapsed_ms,
            embed_ms=int((t_embed1 - t_embed0) * 1000),
            neo4j_ms=int((t_db1 - t_db0) * 1000),
            llm_ms=int((t_llm1 - t_llm0) * 1000),
            top_k=payload.top_k,
        )
        
        return V3QueryResponse(
            answer=response.text,
            confidence=results[0][1] if results else 0.0,
            sources=sources if payload.include_sources else [],
            entities_used=entities_used,
            search_type="local",
        )
        
    except Exception as e:
        logger.error("v3_local_search_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Local search failed: {str(e)}")


@router.post("/query/global", response_model=V3QueryResponse)
async def query_global(request: Request, payload: V3QueryRequest):
    """
    Global search - broad thematic queries.
    
    Best for:
    - "What are the main themes?"
    - "Summarize all documents"
    - Cross-document questions
    
    Uses community reports from Neo4j (Microsoft-style map-reduce synthesis).
    """
    group_id = get_group_id(request)
    logger.info("v3_global_search", group_id=group_id, query=payload.query[:50])
    
    try:
        import time
        t0 = time.monotonic()
        store = get_neo4j_store()
        adapter = get_drift_adapter()

        use_dynamic = _get_env_bool("V3_GLOBAL_DYNAMIC_SELECTION", default=False)
        dynamic_max_depth = _get_env_int("V3_GLOBAL_DYNAMIC_MAX_DEPTH", default=2)
        dynamic_candidate_budget = _get_env_int("V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET", default=30)
        dynamic_keep_per_level = _get_env_int("V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL", default=max(5, min(12, payload.top_k)))
        dynamic_score_threshold = _get_env_int("V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD", default=25)
        dynamic_rating_batch_size = _get_env_int("V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE", default=8)
        build_hierarchy_on_query = _get_env_bool("V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY", default=True)

        scores_by_id: dict[str, int] = {}

        # Get community summaries
        if use_dynamic:
            if build_hierarchy_on_query:
                try:
                    store.ensure_community_hierarchy(group_id)
                except Exception as e:
                    logger.warning("v3_global_dynamic_build_hierarchy_failed", group_id=group_id, error=str(e))

            communities, scores_by_id = _dynamic_select_communities_microsoft(
                store=store,
                adapter=adapter,
                group_id=group_id,
                query=payload.query,
                final_top_k=payload.top_k,
                max_depth=max(0, dynamic_max_depth),
                candidate_budget=max(0, dynamic_candidate_budget),
                keep_per_level=max(0, dynamic_keep_per_level),
                score_threshold=max(0, min(100, dynamic_score_threshold)),
                rating_batch_size=max(1, dynamic_rating_batch_size),
            )
        else:
            communities = store.get_communities_by_level(group_id=group_id, level=0)
        
        if not communities:
            return V3QueryResponse(
                answer="Not specified in the provided documents.",
                confidence=0.85,
                sources=[],
                entities_used=[],
                search_type="global",
            )

        # Rank communities by relevance (embedding similarity) when possible.
        # For dynamic selection we keep LLM rating as the selector; this final ranking
        # is a stable ordering step.
        try:
            communities = _rank_communities_for_query(adapter, payload.query, communities)
        except Exception as e:
            logger.warning("v3_global_search_ranking_failed", group_id=group_id, error=str(e))

        # Build context from top-ranked community summaries
        context_parts: list[str] = []
        sources: list[dict[str, Any]] = []

        for community in communities[:payload.top_k]:
            context_parts.append(f"## {community.title}\n{community.summary}")
            sources.append({
                "id": community.id,
                "title": community.title,
                "level": community.level,
                "entity_count": len(community.entity_ids),
                "score": scores_by_id.get(community.id, None) if use_dynamic else None,
            })

        context = "\n\n".join(context_parts)

        if not payload.synthesize:
            logger.info(
                "v3_global_search_timing",
                group_id=group_id,
                total_ms=int((time.monotonic() - t0) * 1000),
                llm_ms=0,
                top_k=payload.top_k,
            )
            return V3QueryResponse(
                answer=context,
                confidence=0.85,
                sources=sources if payload.include_sources else [],
                entities_used=[],
                search_type="global",
            )

        # Microsoft-style Map-Reduce over community reports.
        # We also add a small amount of direct TextChunk evidence for this query,
        # because some concrete terms (amounts, notice periods, jurisdictions)
        # are present in chunks but may not be reflected in any single community report.
        t_llm0 = time.monotonic()

        map_answers: list[dict[str, Any]] = []
        for community in communities[:payload.top_k]:
            report = (community.summary or "").strip()
            if not report:
                continue
            map_prompt = _global_map_prompt(report, payload.query)
            map_resp = adapter.llm.complete(map_prompt)
            map_text = (map_resp.text or "").strip()
            if _is_empty_or_unhelpful_global_answer(map_text):
                continue
            # Guard value-like spans for map output against the community report itself
            if map_text and not _value_spans_grounded(map_text, report):
                continue
            map_answers.append(
                {
                    "community_id": community.id,
                    "community_title": community.title,
                    "text": map_text,
                }
            )

        # Query-targeted chunk evidence (vector retrieval)
        chunk_evidence_parts: list[str] = []
        try:
            embedder = getattr(adapter, "embedder", None)
            if embedder is None:
                raise RuntimeError("No embedder available")

            # Base retrieval
            base_queries: list[str] = [payload.query]

            # Lightweight query expansion to improve retrieval of concrete terms.
            ql = (payload.query or "").lower()
            if any(k in ql for k in ["pay", "fee", "fees", "amount", "amount due", "invoice", "charges", "tax"]):
                base_queries.append(payload.query + "\nFocus: invoice total, amount due, deposits, non-refundable fees")
            if any(k in ql for k in ["jurisdiction", "governing law", "venue", "state of", "laws of"]):
                base_queries.append(payload.query + "\nFocus: governing law, jurisdiction, venue, state")
            if any(k in ql for k in ["notice", "delivery", "certified mail", "return receipt", "business days"]):
                base_queries.append(payload.query + "\nFocus: notice, certified mail, return receipt, deadlines")

            seen_chunk_ids: set[str] = set()
            merged_chunks: list[tuple[Any, float]] = []
            per_query_top_k = max(6, min(12, payload.top_k * 2))

            for q in base_queries[:3]:
                try:
                    query_embedding = embedder.embed_query(q)
                except Exception:
                    query_embedding = embedder.get_text_embedding(q)

                chunk_results = store.search_text_chunks(
                    group_id=group_id,
                    query_text=q,
                    embedding=query_embedding,
                    top_k=per_query_top_k,
                )
                for ch, sc in chunk_results:
                    cid = getattr(ch, "id", "")
                    if cid and cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        merged_chunks.append((ch, sc))

            # Intent-driven lexical retrieval to capture exact phrases that embeddings may miss.
            lex_terms = _lexical_terms_for_global_query(payload.query)
            if lex_terms:
                lex_top_k = max(10, min(30, payload.top_k * 6))
                for ch, hit_score in store.search_text_chunks_by_terms(
                    group_id=group_id,
                    terms=lex_terms,
                    top_k=lex_top_k,
                ):
                    cid = getattr(ch, "id", "")
                    if cid and cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        # Boost lexical hits above cosine similarities (0..1 range)
                        merged_chunks.append((ch, 10.0 + float(hit_score)))

            # Keep the best-scoring chunks overall.
            merged_chunks.sort(key=lambda t: float(t[1]), reverse=True)
            for chunk, score in merged_chunks[: max(10, min(24, payload.top_k * 6))]:
                text = (getattr(chunk, "text", "") or "").strip()
                if not text:
                    continue
                if len(text) > 1400:
                    text = text[:1400] + "..."

                meta = getattr(chunk, "metadata", {}) or {}
                doc_title = (meta.get("document_title") or "").strip()
                doc_source = (meta.get("document_source") or "").strip()
                doc_id = (getattr(chunk, "document_id", "") or "").strip()
                doc_label_bits = []
                if doc_title:
                    doc_label_bits.append(doc_title)
                if doc_id:
                    doc_label_bits.append(f"doc_id={doc_id}")
                if doc_source:
                    doc_label_bits.append(f"source={doc_source}")
                doc_label = (" | ".join(doc_label_bits)) if doc_label_bits else "(unknown document)"

                chunk_evidence_parts.append(
                    f"[TextChunk {chunk.id} | {doc_label} | chunk_index={chunk.chunk_index} | score={score:.3f}]\n{text}"
                )
                sources.append(
                    {
                        "id": chunk.id,
                        "type": "text_chunk",
                        "chunk_index": chunk.chunk_index,
                        "document_id": doc_id,
                        "document_title": doc_title,
                        "score": float(score),
                    }
                )
        except Exception as e:
            logger.warning("v3_global_search_chunk_evidence_failed", group_id=group_id, error=str(e))

        reduce_context_parts: list[str] = []
        for a in map_answers:
            reduce_context_parts.append(f"## {a['community_title']}\n{a['text']}")
        if chunk_evidence_parts:
            reduce_context_parts.append("## Retrieved Text Chunks\n" + "\n\n".join(chunk_evidence_parts))

        if not reduce_context_parts:
            t_llm1 = time.monotonic()
            logger.info(
                "v3_global_search_timing",
                group_id=group_id,
                total_ms=int((time.monotonic() - t0) * 1000),
                llm_ms=int((t_llm1 - t_llm0) * 1000),
                top_k=payload.top_k,
            )
            return V3QueryResponse(
                answer="Not specified in the provided documents.",
                confidence=0.85,
                sources=sources if payload.include_sources else [],
                entities_used=[],
                search_type="global",
            )

        reduce_context = "\n\n".join(reduce_context_parts)
        reduce_prompt = _global_reduce_prompt(reduce_context, payload.query)

        response = adapter.llm.complete(reduce_prompt)
        t_llm1 = time.monotonic()

        logger.info(
            "v3_global_search_timing",
            group_id=group_id,
            total_ms=int((time.monotonic() - t0) * 1000),
            llm_ms=int((t_llm1 - t_llm0) * 1000),
            top_k=payload.top_k,
        )
        
        answer_text = (response.text or "").strip()
        if _is_empty_or_unhelpful_global_answer(answer_text):
            answer_text = "Not specified in the provided documents."
        # Ground value-like spans against the reduce context (extracted map answers)
        if answer_text and not _value_spans_grounded(answer_text, reduce_context):
            answer_text = "Not specified in the provided documents."

        return V3QueryResponse(
            answer=answer_text,
            confidence=0.85,  # Global search has moderate confidence
            sources=sources if payload.include_sources else [],
            entities_used=[],
            search_type="global",
        )
        
    except Exception as e:
        logger.error("v3_global_search_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Global search failed: {str(e)}")


@router.post("/query/drift", response_model=V3DriftResponse)
async def query_drift(request: Request, payload: V3DriftRequest):
    """
    DRIFT search - multi-step reasoning.
    
    Best for:
    - "How is A connected to B through C?"
    - Complex relationship queries
    - Multi-hop reasoning
    
    Uses MS GraphRAG DRIFT algorithm with Neo4j data.
    This is the V3 flagship feature for multi-step reasoning.
    """
    import time
    group_id = get_group_id(request)
    start_time = time.time()
    logger.info("v3_drift_search_start", group_id=group_id, query=payload.query[:50])
    
    try:
        adapter = get_drift_adapter()
        
        result = await adapter.drift_search(
            group_id=group_id,
            query=payload.query,
            max_iterations=payload.max_iterations,
            convergence_threshold=payload.convergence_threshold,
        )
        
        elapsed = time.time() - start_time
        logger.info("v3_drift_search_complete", group_id=group_id, elapsed_seconds=f"{elapsed:.2f}")
        
        return V3DriftResponse(
            answer=result["answer"],
            confidence=result["confidence"],
            iterations=result["iterations"],
            sources=result["sources"] if payload.include_reasoning_path else [],
            reasoning_path=result["reasoning_path"] if payload.include_reasoning_path else [],
            search_type="drift",
        )
        
    except Exception as e:
        logger.error("v3_drift_search_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"DRIFT search failed: {str(e)}")


@router.post("/query/raptor", response_model=V3QueryResponse)
async def query_raptor(request: Request, payload: V3QueryRequest):
    """
    RAPTOR search - detailed document content queries.
    
    Best for:
    - Extracting specific fields from documents
    - Detailed comparisons (invoices vs contracts)
    - Questions requiring exact values, dates, amounts
    
    Uses RAPTOR nodes which contain the actual document text with full details.
    """
    group_id = get_group_id(request)
    logger.info("v3_raptor_search", group_id=group_id, query=payload.query[:50])
    
    try:
        import time
        t0 = time.monotonic()
        store = get_neo4j_store()
        
        # Get embedder from LLMService (must match indexing dimensions; text-embedding-3-small defaults to 1536)
        from app.services.llm_service import LLMService
        llm_service = LLMService()
        if llm_service.embed_model is None:
            raise HTTPException(status_code=500, detail="Embedding model not initialized")

        t_embed0 = time.monotonic()
        query_embedding = llm_service.embed_model.get_text_embedding(payload.query)
        t_embed1 = time.monotonic()
        
        # First, check if RAPTOR nodes exist
        with store.driver.session(database=store.database) as session:
            count_result = session.run(
                "MATCH (r:RaptorNode {group_id: $group_id}) RETURN count(r) as count",
                group_id=group_id
            )
            record = count_result.single()
            raptor_node_count = record["count"] if record else 0
            logger.info(f"RAPTOR nodes found in Neo4j: {raptor_node_count}")
        
        if raptor_node_count == 0:
            return V3QueryResponse(
                answer="No RAPTOR nodes found. Ensure documents were indexed with run_raptor=true.",
                confidence=0.0,
                sources=[],
                entities_used=[],
                search_type="raptor",
            )
        
        # Search RAPTOR nodes by vector similarity
        t_db0 = time.monotonic()
        results = store.search_raptor_by_embedding(
            group_id=group_id,
            embedding=query_embedding,
            top_k=payload.top_k,
        )
        t_db1 = time.monotonic()
        logger.info(f"RAPTOR vector search returned {len(results)} results")
        
        if not results:
            return V3QueryResponse(
                answer="No relevant RAPTOR nodes found for this query.",
                confidence=0.0,
                sources=[],
                entities_used=[],
                search_type="raptor",
            )
        
        # Build context from RAPTOR node texts
        context_parts = []
        sources = []
        
        for node, score in results:
            # Handle both RaptorNode objects and Neo4j node dicts
            if isinstance(node, dict):
                text = node.get("text", "")
                level = node.get("level", 0)
                node_id = node.get("id", "")
            else:
                text = node.text if hasattr(node, 'text') else str(node)
                level = node.level if hasattr(node, 'level') else 0
                node_id = node.id if hasattr(node, 'id') else ""
            
            context_parts.append(f"## Content (Level {level}):\n{text}\n")
            sources.append({
                "id": node_id,
                "level": level,
                "score": float(score) if score else 0.0,
                "text_preview": text[:200] + "..." if len(text) > 200 else text,
            })
        
        context = "\n\n".join(context_parts)

        if not payload.synthesize:
            logger.info(
                "v3_raptor_search_timing",
                group_id=group_id,
                total_ms=int((time.monotonic() - t0) * 1000),
                embed_ms=int((t_embed1 - t_embed0) * 1000),
                neo4j_ms=int((t_db1 - t_db0) * 1000),
                llm_ms=0,
                top_k=payload.top_k,
            )
            return V3QueryResponse(
                answer=context,
                confidence=results[0][1] if results else 0.0,
                sources=sources if payload.include_sources else [],
                entities_used=[],
                search_type="raptor",
            )
        
        # Generate answer with full document context
        prompt = f"""Based on the following detailed document content, answer the question comprehensively.
    Only use the provided content. If the answer is not present, respond with: "Not specified in the provided documents.".

Document Content:
{context}

Question: {payload.query}

Provide a detailed answer with specific values, amounts, dates, and references from the documents.

Answer:"""
        
        # Get LLM for generating answer
        llm_service = LLMService()
        t_llm0 = time.monotonic()
        response = llm_service.llm.complete(prompt)
        t_llm1 = time.monotonic()

        logger.info(
            "v3_raptor_search_timing",
            group_id=group_id,
            total_ms=int((time.monotonic() - t0) * 1000),
            embed_ms=int((t_embed1 - t_embed0) * 1000),
            neo4j_ms=int((t_db1 - t_db0) * 1000),
            llm_ms=int((t_llm1 - t_llm0) * 1000),
            top_k=payload.top_k,
        )
        
        return V3QueryResponse(
            answer=response.text,
            confidence=results[0][1] if results else 0.0,
            sources=sources if payload.include_sources else [],
            entities_used=[],
            search_type="raptor",
        )
        
    except Exception as e:
        logger.error("v3_raptor_search_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"RAPTOR search failed: {str(e)}")


@router.get("/stats/{group_id}", response_model=V3StatsResponse)
async def get_stats(group_id: str):
    """
    Get indexing statistics for a group.
    
    Returns counts of all indexed data types in Neo4j.
    """
    logger.info("v3_get_stats", group_id=group_id)
    
    try:
        store = get_neo4j_store()
        stats = store.get_group_stats(group_id)
        
        return V3StatsResponse(
            group_id=group_id,
            entities=stats["entities"],
            relationships=stats["relationships"],
            communities=stats["communities"],
            raptor_nodes=stats["raptor_nodes"],
            text_chunks=stats["text_chunks"],
            documents=stats["documents"],
        )
        
    except Exception as e:
        # Stats should never block progress; treat transient DB issues as "not ready".
        logger.warning("v3_get_stats_failed", group_id=group_id, error=str(e))
        return V3StatsResponse(
            group_id=group_id,
            entities=0,
            relationships=0,
            communities=0,
            raptor_nodes=0,
            text_chunks=0,
            documents=0,
        )


@router.post("/schema/init")
async def initialize_schema():
    """
    Initialize Neo4j schema for V3.
    
    Creates all required constraints, indexes, and vector indexes.
    Call this once during deployment or schema updates.
    """
    logger.info("v3_schema_init")
    
    try:
        store = get_neo4j_store()
        store.initialize_schema()
        
        return {
            "status": "success",
            "message": "Neo4j schema initialized for V3",
            "schema_version": store.SCHEMA_VERSION,
        }
        
    except Exception as e:
        logger.error("v3_schema_init_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Schema initialization failed: {str(e)}")


@router.delete("/data/{group_id}")
async def delete_group_data(group_id: str):
    """
    Delete all indexed data for a group.
    
    Use with caution - this removes all entities, communities, RAPTOR nodes, etc.
    Useful for reindexing from scratch.
    """
    logger.info("v3_delete_group_data", group_id=group_id)
    
    try:
        store = get_neo4j_store()
        deleted = store.delete_group_data(group_id)
        
        return {
            "status": "success",
            "group_id": group_id,
            "deleted": deleted,
        }
        
    except Exception as e:
        logger.error("v3_delete_group_data_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@router.get("/health")
async def health_check():
    """V3 health check - verifies Neo4j connectivity."""
    try:
        store = get_neo4j_store()
        store.driver.verify_connectivity()
        
        return {
            "status": "healthy",
            "version": "3.0.0",
            "neo4j": "connected",
            "message": "V3 GraphRAG is operational",
        }
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "version": "3.0.0",
            "neo4j": "disconnected",
            "error": str(e),
        }
