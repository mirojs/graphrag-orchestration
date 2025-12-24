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
import structlog
import traceback
import uuid

from app.core.config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/v3", tags=["GraphRAG V3"])


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
        
        # Always use background tasks to avoid gateway timeouts
        # Entity extraction + RAPTOR + community detection can take >4 minutes for even small batches
        async def run_indexing():
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
        
        background_tasks.add_task(run_indexing)
        
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
        adapter = get_drift_adapter()
        
        # Use hybrid search (vector + full-text with RRF fusion)
        # get_drift_adapter() guarantees embedder is non-None
        query_embedding = adapter.embedder.embed_query(payload.query)
        
        store = get_neo4j_store()
        
        # Hybrid search: combines vector similarity with keyword matching
        # This solves the "missing facts" problem where specific values
        # (like "$25,000" or "Invoice #123") have weak embeddings
        try:
            results = store.search_entities_hybrid(
                group_id=group_id,
                query_text=payload.query,
                embedding=query_embedding,
                top_k=payload.top_k,
            )
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
        
        # Generate answer
        prompt = f"""Based on the following information, answer the question.

Information:
{context}

Question: {payload.query}

Answer:"""
        
        response = adapter.llm.complete(prompt)
        
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
    
    Uses community summaries from Neo4j.
    """
    group_id = get_group_id(request)
    logger.info("v3_global_search", group_id=group_id, query=payload.query[:50])
    
    try:
        store = get_neo4j_store()
        adapter = get_drift_adapter()
        
        # Get top-level community summaries
        communities = store.get_communities_by_level(group_id=group_id, level=0)
        
        if not communities:
            return V3QueryResponse(
                answer="No community summaries available. Please index documents first.",
                confidence=0.0,
                sources=[],
                entities_used=[],
                search_type="global",
            )
        
        # Build context from community summaries
        context_parts = []
        sources = []
        
        for community in communities[:payload.top_k]:
            context_parts.append(f"## {community.title}\n{community.summary}")
            sources.append({
                "id": community.id,
                "title": community.title,
                "level": community.level,
                "entity_count": len(community.entity_ids),
            })
        
        context = "\n\n".join(context_parts)
        
        # Generate answer using map-reduce style
        prompt = f"""Based on the following community summaries, answer the question.

Community Summaries:
{context}

Question: {payload.query}

Provide a comprehensive answer that synthesizes information across all relevant communities.

Answer:"""
        
        response = adapter.llm.complete(prompt)
        
        return V3QueryResponse(
            answer=response.text,
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
        store = get_neo4j_store()
        
        # Get embedder from LLMService (must match indexing dimensions; text-embedding-3-small defaults to 1536)
        from app.services.llm_service import LLMService
        llm_service = LLMService()
        if llm_service.embed_model is None:
            raise HTTPException(status_code=500, detail="Embedding model not initialized")

        query_embedding = llm_service.embed_model.get_text_embedding(payload.query)
        
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
        results = store.search_raptor_by_embedding(
            group_id=group_id,
            embedding=query_embedding,
            top_k=payload.top_k,
        )
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
        
        # Generate answer with full document context
        prompt = f"""Based on the following detailed document content, answer the question comprehensively.

Document Content:
{context}

Question: {payload.query}

Provide a detailed answer with specific values, amounts, dates, and references from the documents.

Answer:"""
        
        # Get LLM for generating answer
        llm_service = LLMService()
        response = llm_service.llm.complete(prompt)
        
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
        logger.error("v3_get_stats_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


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
