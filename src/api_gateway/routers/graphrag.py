from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union, Literal
import structlog
import traceback
from src.core.config import settings

from src.worker.services.indexing_service import IndexingService
from src.worker.services.retrieval_service import RetrievalService

router = APIRouter()
logger = structlog.get_logger()

# Service instances (initialized on first use)
_indexing_service: Optional[IndexingService] = None
_retrieval_service: Optional[RetrievalService] = None


def get_indexing_service() -> IndexingService:
    global _indexing_service
    if _indexing_service is None:
        _indexing_service = IndexingService()
    return _indexing_service


def get_retrieval_service() -> RetrievalService:
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service


class IndexingRequest(BaseModel):
    documents: List[Union[str, Dict[str, Any]]]  # text strings, {text,metadata}, or URLs
    entity_types: Optional[List[str]] = None
    relation_types: Optional[List[str]] = None
    extraction_mode: str = "schema"  # schema, simple, dynamic
    run_community_detection: bool = True
    ingestion: Literal["document-intelligence", "llamaparse", "cu-standard", "none"] = "document-intelligence"  # default to Document Intelligence


class SchemaIndexingRequest(BaseModel):
    """Request to index documents using a schema from Schema Vault."""
    schema_id: str  # Schema ID from Cosmos DB Schema Vault
    documents: List[Union[str, Dict[str, Any]]]  # text strings, {text,metadata}, or URLs
    extraction_mode: str = "schema"  # schema, simple, dynamic
    run_community_detection: bool = True
    ingestion: Literal["document-intelligence", "llamaparse", "cu-standard", "none"] = "document-intelligence"


class SchemaPromptIndexingRequest(BaseModel):
    """Request to index documents using a natural-language schema prompt."""
    schema_prompt: str
    documents: List[Union[str, Dict[str, Any]]]  # text strings, {text,metadata}, or URLs
    extraction_mode: str = "schema"  # schema, simple, dynamic
    run_community_detection: bool = True
    ingestion: Literal["document-intelligence", "llamaparse", "cu-standard", "none"] = "document-intelligence"

@router.get("/debug/lancedb")
async def debug_lancedb(request: Request):
    """Debug LanceDB connectivity and TextNode API."""
    group_id = request.state.group_id
    try:
        import lancedb
        from llama_index.core.schema import TextNode, Document
        
        db = lancedb.connect(settings.LANCEDB_PATH)
        
        # Test TextNode creation
        test_doc = Document(text="test", metadata={"key": "value"})
        try:
            node = TextNode(text=test_doc.text, metadata=test_doc.metadata)
            node_status = "ok"
            node_repr = str(node)
        except Exception as e:
            node_status = "error"
            node_repr = f"{type(e).__name__}: {e}"
        
        return {
            "status": "ok",
            "path": settings.LANCEDB_PATH,
            "connection_type": type(db).__name__,
            "repr": str(db),
            "textnode_from_document": node_status,
            "textnode_repr": node_repr,
            "group_id": group_id,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc(), "group_id": group_id}


async def _to_documents(input_items: List[Union[str, Dict[str, Any]]], ingestion_mode: str = "document-intelligence", group_id: str = ""):
    """
    Normalize to LlamaIndex Documents.
    
    Supported ingestion modes:
    - "none": Raw text only (no URLs, no files)
    - "document-intelligence": Azure Document Intelligence (RECOMMENDED - stable, mature SDK)
    - "llamaparse": LlamaParse (alternative layout-aware parser)
    - "cu-standard": Azure Content Understanding (legacy, less stable)
    """
    from llama_index.core import Document
    print(f"🔧 _to_documents called: {len(input_items)} items, mode={ingestion_mode}")
    try:
        if ingestion_mode == "none":
            # Only accept raw text inputs
            docs: List[Document] = []
            for item in input_items:
                if isinstance(item, dict) and "text" in item:
                    docs.append(Document(text=item["text"], metadata=item.get("metadata") or {}))
                elif isinstance(item, str) and not (item.startswith("http://") or item.startswith("https://")):
                    docs.append(Document(text=item))
                else:
                    raise HTTPException(status_code=400, detail="Ingestion mode 'none' does not allow URLs; provide text only.")
            return docs
        
        elif ingestion_mode == "document-intelligence":
            # Document Intelligence: Azure's mature layout extraction service (RECOMMENDED)
            print(f"📄 Using Document Intelligence for {len(input_items)} items")
            from src.worker.services.document_intelligence_service import DocumentIntelligenceService
            doc_intel = DocumentIntelligenceService()
            docs = await doc_intel.extract_documents(group_id, input_items)
            print(f"✅ Document Intelligence returned {len(docs)} documents")
            return docs
        
        elif ingestion_mode == "llamaparse":
            # LlamaParse: Layout-aware parsing (alternative)
            from src.worker.services.llamaparse_ingestion_service import LlamaParseIngestionService
            llamaparse = LlamaParseIngestionService()
            
            # Filter to only string URLs/paths for LlamaParse
            file_paths: List[str] = []
            for item in input_items:
                if isinstance(item, str):
                    file_paths.append(item)
                elif isinstance(item, dict) and "url" in item:
                    file_paths.append(item["url"])
            
            if not file_paths:
                raise ValueError("LlamaParse requires file paths or URLs. Provide string URLs or dicts with 'url' key.")
            
            docs = await llamaparse.parse_documents(file_paths, group_id)
            return docs
        
        elif ingestion_mode == "cu-standard":
            # cu-standard is now an alias for document-intelligence (SDK-based)
            # The manual REST API implementation was removed in favor of the SDK
            print(f"📄 cu-standard mode: Using Document Intelligence SDK for {len(input_items)} items")
            from src.worker.services.document_intelligence_service import DocumentIntelligenceService
            doc_intel = DocumentIntelligenceService()
            docs = await doc_intel.extract_documents(group_id, input_items)
            print(f"✅ Document Intelligence returned {len(docs)} documents")
            return docs
        
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Unknown ingestion mode: {ingestion_mode}. Use 'document-intelligence', 'llamaparse', 'cu-standard', or 'none'"
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ingestion_failed", error=str(e))
        raise HTTPException(status_code=400, detail=f"Failed to ingest documents: {e}")



class IndexingResponse(BaseModel):
    status: str
    job_id: Optional[str] = None
    message: str
    stats: Optional[Dict[str, Any]] = None


class QueryRequest(BaseModel):
    query: str
    community_level: int = 0
    top_k: int = 10
    max_depth: int = 2
    conversation_history: Optional[List[Dict[str, str]]] = None
    reduce: bool = True


class StructuredQueryRequest(BaseModel):
    """
    Request for schema-guided structured retrieval.
    
    This is the PRIMARY use case for schemas - extracting structured data
    from the Knowledge Graph at QUERY time, not indexing time.
    """
    query: str  # Natural language query (e.g., "Extract invoice details from uploaded documents")
    output_schema: Dict[str, Any]  # JSON schema defining expected output structure
    schema_name: Optional[str] = None  # Optional name for the schema (for logging/debugging)
    top_k: int = 10  # Number of nodes to retrieve from the knowledge graph
    

class StructuredQueryResponse(BaseModel):
    """Response from schema-guided structured retrieval."""
    query: str
    mode: str = "structured-extraction"
    answer: Dict[str, Any]  # The structured JSON matching the output_schema
    sources: List[Dict[str, Any]]  # Source nodes used for extraction
    metadata: Optional[Dict[str, Any]] = None  # Confidence, validation errors, etc.


class SchemaVaultQueryRequest(BaseModel):
    """
    Request for schema-guided structured retrieval using a schema from Schema Vault.
    
    Instead of providing the full JSON schema inline, reference a schema by ID
    from the Schema Vault (Cosmos DB).
    """
    query: str  # Natural language query
    schema_id: str  # Schema ID from Schema Vault
    top_k: int = 10  # Number of nodes to retrieve


class QueryResponse(BaseModel):
    query: str
    mode: str
    answer: str
    sources: List[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]] = None


@router.post("/index", response_model=IndexingResponse, deprecated=True)
async def trigger_indexing(
    request: Request, 
    payload: IndexingRequest,
    background_tasks: BackgroundTasks
):
    """
    **DEPRECATED:** Use /v3/index instead. This V1/V2 endpoint will be removed in a future release.
    
    Trigger GraphRAG indexing for a specific group.
    
    Uses LlamaIndex PropertyGraphIndex to extract entities and relationships,
    storing them in Neo4j with group_id for tenant isolation.
    
    Rate limits: 100 documents/hour per tenant (configurable)
    """
    group_id = request.state.group_id
    logger.info("indexing_triggered", group_id=group_id, doc_count=len(payload.documents))
    
    # Check rate limits and quotas
    from src.worker.services.quota_manager import get_quota_manager
    quota_manager = get_quota_manager()
    await quota_manager.check_indexing_rate_limit(group_id, len(payload.documents))
    
    try:
        service = get_indexing_service()
        
        # Normalize documents from strings/objects/URLs
        documents = await _to_documents(payload.documents, payload.ingestion, group_id)
        
        # Run indexing
        stats = await service.index_documents(
            group_id=group_id,
            documents=documents,
            entity_types=payload.entity_types,
            relation_types=payload.relation_types,
            extraction_mode=payload.extraction_mode,
        )
        
        # Optionally run community detection in background
        if payload.run_community_detection:
            background_tasks.add_task(
                service.run_community_detection,
                group_id=group_id,
                algorithm="leiden",
            )
            background_tasks.add_task(
                service.generate_community_summaries,
                group_id=group_id,
                level=0,
            )
        
        # Invalidate node count cache after indexing
        quota_manager.invalidate_node_count_cache(group_id)
        
        return IndexingResponse(
            status="completed",
            message=f"Indexed {len(documents)} documents",
            stats=stats,
        )
        
    except Exception as e:
        logger.error("indexing_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/index-from-schema", response_model=IndexingResponse)
async def trigger_schema_indexing(
    request: Request,
    payload: SchemaIndexingRequest,
    background_tasks: BackgroundTasks
):
    """
    Index documents using a schema from the Schema Vault.
    
    This endpoint fetches a Content Understanding schema from Cosmos DB,
    converts it to GraphRAG entity/relation types automatically, and
    uses it for knowledge graph extraction.
    
    Benefits:
    - Reuse existing schemas from Schema Vault
    - Consistent schema across Content Understanding and GraphRAG
    - Automatic conversion from JSON Schema to graph schema
    """
    group_id = request.state.group_id
    logger.info(
        "schema_indexing_triggered",
        group_id=group_id,
        schema_id=payload.schema_id,
        doc_count=len(payload.documents)
    )
    
    try:
        service = get_indexing_service()
        
        # Normalize documents from strings/objects/URLs
        documents = await _to_documents(payload.documents, payload.ingestion, group_id)
        
        # Index using schema from Schema Vault
        stats = await service.index_from_schema(
            group_id=group_id,
            schema_id=payload.schema_id,
            documents=documents,
            extraction_mode=payload.extraction_mode,
        )
        
        # Run community detection in background if requested
        if payload.run_community_detection:
            background_tasks.add_task(
                service.run_community_detection,
                group_id=group_id,
                algorithm="leiden",
            )
            background_tasks.add_task(
                service.generate_community_summaries,
                group_id=group_id,
                level=0,
            )
        
        return IndexingResponse(
            status="completed",
            message=f"Indexed {len(documents)} documents using schema '{stats.get('schema_name')}'",
            stats=stats,
        )
        
    except ValueError as e:
        # Schema not found or invalid
        logger.error("schema_not_found", group_id=group_id, schema_id=payload.schema_id, error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(
            "schema_indexing_failed",
            group_id=group_id,
            schema_id=payload.schema_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/index-from-prompt", response_model=IndexingResponse)
async def trigger_prompt_schema_indexing(
    request: Request,
    payload: SchemaPromptIndexingRequest,
    background_tasks: BackgroundTasks
):
    """
    Index documents using a schema derived from a natural-language prompt.

    Mirrors the "quick query" approach where a user-provided description
    guides schema creation for graph extraction.
    """
    group_id = request.state.group_id
    print(f"🚀 ENDPOINT HIT: /index-from-prompt with {len(payload.documents)} docs, ingestion={payload.ingestion}")
    logger.info(
        "prompt_schema_indexing_triggered",
        group_id=group_id,
        doc_count=len(payload.documents)
    )

    try:
        service = get_indexing_service()

        # Normalize documents from strings/objects/URLs
        logger.info(f"📥 Calling _to_documents with {len(payload.documents)} items, ingestion mode: {payload.ingestion}")
        documents = await _to_documents(payload.documents, payload.ingestion, group_id)
        logger.info(f"📤 _to_documents returned {len(documents)} documents")

        # Index using schema derived from prompt
        stats = await service.index_from_schema_prompt(
            group_id=group_id,
            schema_prompt=payload.schema_prompt,
            documents=documents,
            extraction_mode=payload.extraction_mode,
        )

        # Run community detection in background if requested
        if payload.run_community_detection:
            background_tasks.add_task(
                service.run_community_detection,
                group_id=group_id,
                algorithm="leiden",
            )
            background_tasks.add_task(
                service.generate_community_summaries,
                group_id=group_id,
                level=0,
            )

        return IndexingResponse(
            status="completed",
            message=f"Indexed {len(documents)} documents using derived schema '{stats.get('schema_name')}'",
            stats=stats,
        )

    except Exception as e:
        logger.error(
            "prompt_schema_indexing_failed",
            group_id=group_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/global", response_model=QueryResponse, deprecated=True)
async def query_global(request: Request, payload: QueryRequest):
    """
    Perform a Global Search using GraphRAG community summaries.
    
    Best for high-level, thematic questions like:
    - "What are the main themes in this document collection?"
    - "Summarize the key topics discussed"
    """
    group_id = request.state.group_id
    logger.info("global_query", group_id=group_id, query=payload.query[:50])
    
    try:
        service = get_retrieval_service()
        result = await service.global_search(
            group_id=group_id,
            query=payload.query,
            community_level=payload.community_level,
            top_k=payload.top_k,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata={"community_count": result.get("community_count", 0)},
        )
        
    except Exception as e:
        logger.error("global_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/local", response_model=QueryResponse, deprecated=True)
async def query_local(request: Request, payload: QueryRequest):
    """
    Perform a Local Search focused on specific entities.
    
    Best for entity-focused questions like:
    - "Tell me about [Person/Company/Product]"
    - "What is the relationship between X and Y?"
    
    Rate limits: 60 queries/minute per tenant (configurable)
    """
    group_id = request.state.group_id
    logger.info("local_query", group_id=group_id, query=payload.query[:50])
    
    # Check query rate limit
    from src.worker.services.quota_manager import get_quota_manager
    await get_quota_manager().check_query_rate_limit(group_id)
    
    try:
        service = get_retrieval_service()
        result = await service.local_search(
            group_id=group_id,
            query=payload.query,
            max_depth=payload.max_depth,
            top_k=payload.top_k,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata={"entity_count": result.get("entity_count", 0)},
        )
        
    except Exception as e:
        logger.error("local_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/hybrid", response_model=QueryResponse)
async def query_hybrid(request: Request, payload: QueryRequest):
    """
    Perform a Hybrid Search combining vector and graph retrieval.
    
    Best for general questions that benefit from both semantic similarity
    and structural knowledge.
    """
    group_id = request.state.group_id
    logger.info("hybrid_query", group_id=group_id, query=payload.query[:50])
    
    try:
        service = get_retrieval_service()
        result = await service.hybrid_search(
            group_id=group_id,
            query=payload.query,
            top_k=payload.top_k,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("vector_sources", []) + result.get("graph_sources", []),
            metadata={"vector_weight": result.get("vector_weight", 0.5)},
        )
        
    except Exception as e:
        logger.error("hybrid_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/drift", response_model=QueryResponse, deprecated=True)
async def query_drift(request: Request, payload: QueryRequest):
    """
    Perform DRIFT Search with multi-step iterative reasoning.
    
    DRIFT (Dynamic Reasoning with Iterative Facts and Templates) is best for:
    - Complex questions requiring multiple reasoning steps
    - Queries that need synthesis across different parts of the knowledge graph
    - Questions that benefit from iterative refinement
    
    Examples:
    - "Compare the payment terms across all contracts and identify outliers"
    - "What are the key differences between vendor A and vendor B's proposals?"
    - "Analyze the warranty claims and identify common failure patterns"
    """
    group_id = request.state.group_id
    logger.info("drift_query", group_id=group_id, query=payload.query[:50])
    
    try:
        service = get_retrieval_service()
        result = await service.drift_search(
            group_id=group_id,
            query=payload.query,
            conversation_history=payload.conversation_history,
            reduce=payload.reduce,
            top_k=payload.top_k,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata=result.get("metadata", {}),
        )
        
        
    except Exception as e:
        logger.error("drift_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


class BuildCommunitiesRequest(BaseModel):
    """Request to build community summaries for global search."""
    force_rebuild: bool = False  # If True, rebuild even if communities already exist


class BuildCommunitiesResponse(BaseModel):
    """Response from community building."""
    status: str
    community_count: int
    node_count: int
    relationship_count: int
    summaries_generated: int
    message: str


@router.post("/communities/build", response_model=BuildCommunitiesResponse)
async def build_communities(request: Request, payload: BuildCommunitiesRequest = BuildCommunitiesRequest()):
    """
    Build community summaries for GraphRAG Global Search.
    
    This endpoint runs the hierarchical Leiden algorithm to detect communities
    in your knowledge graph, then generates LLM summaries for each community.
    
    Required before using /query/global for thematic questions.
    
    The process:
    1. Fetches all entities and relationships for the group
    2. Applies hierarchical Leiden algorithm for community detection
    3. Generates LLM summaries for each community
    4. Stores communities and summaries in Neo4j
    
    Note: This can take a while for large graphs. Results are cached.
    """
    group_id = request.state.group_id
    logger.info("build_communities", group_id=group_id, force_rebuild=payload.force_rebuild)
    
    try:
        from src.worker.services.community_service import CommunityService
        
        community_service = CommunityService()
        
        # Check if communities already exist (unless force rebuild)
        if not payload.force_rebuild:
            existing = community_service.get_community_summaries(group_id)
            if existing:
                return BuildCommunitiesResponse(
                    status="already_exists",
                    community_count=len(existing),
                    node_count=0,  # Unknown without re-running
                    relationship_count=0,
                    summaries_generated=len(existing),
                    message=f"Communities already exist. Use force_rebuild=true to regenerate."
                )
        
        # Build communities
        result = await community_service.build_communities(group_id)
        
        return BuildCommunitiesResponse(
            status="success",
            community_count=result.get("community_count", 0),
            node_count=result.get("node_count", 0),
            relationship_count=result.get("relationship_count", 0),
            summaries_generated=result.get("summaries_generated", 0),
            message=f"Successfully built {result.get('community_count', 0)} communities with summaries."
        )
        
    except Exception as e:
        logger.error("build_communities_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/communities/summaries")
async def get_community_summaries(request: Request):
    """
    Get all community summaries for a group.
    
    Returns the cached community summaries. Use /communities/build first
    if no summaries exist.
    """
    group_id = request.state.group_id
    logger.info("get_community_summaries", group_id=group_id)
    
    try:
        from src.worker.services.community_service import CommunityService
        
        community_service = CommunityService()
        summaries = community_service.get_community_summaries(group_id)
        
        return {
            "group_id": group_id,
            "community_count": len(summaries),
            "summaries": [
                {"community_id": cid, "summary": summary}
                for cid, summary in summaries.items()
            ]
        }
        
    except Exception as e:
        logger.error("get_summaries_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/comparison", response_model=QueryResponse)
async def query_comparison(request: Request, payload: QueryRequest):
    """
    Perform a Comparison Search to find inconsistencies across documents.
    
    This endpoint analyzes community summaries to identify discrepancies,
    contradictions, and differences across your indexed documents.
    
    Best for:
    - Finding inconsistencies between contracts and invoices
    - Comparing terms across vendor proposals
    - Identifying discrepancies in financial documents
    - Auditing document consistency
    
    Examples:
    - "Compare the payment terms across all contracts"
    - "Find inconsistencies between the purchase order and invoice"
    - "What are the differences between vendor A and vendor B's proposals?"
    - "Identify any pricing discrepancies across documents"
    
    Note: Requires community detection to have been run (run_community_detection=True during indexing).
    """
    group_id = request.state.group_id
    logger.info("comparison_query", group_id=group_id, query=payload.query[:50])
    
    try:
        service = get_retrieval_service()
        result = await service.comparison_search(
            group_id=group_id,
            query=payload.query,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata={
                "community_count": result.get("community_count", 0),
                "inconsistencies_found": result.get("inconsistencies_found", 0),
            },
        )
        
    except Exception as e:
        logger.error("comparison_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/text-to-cypher", response_model=QueryResponse)
async def query_text_to_cypher(request: Request, payload: QueryRequest):
    """
    Perform Text-to-Cypher Search with native graph-level multi-hop reasoning.
    
    This endpoint solves GitHub issue microsoft/graphrag#2039 by enabling
    complex graph queries without manual Cypher writing. The LLM automatically
    analyzes your graph schema and generates optimized Cypher queries.
    
    Best for:
    - Multi-hop relationship queries requiring complex graph traversal
    - Queries that need native graph database capabilities
    - Questions that are difficult to express without graph query language
    
    Examples:
    - "Find contracts where the vendor is in the same city as warranty claimant"
    - "Which employees attended the same university as their hiring manager?"
    - "Show me all payment delays where the vendor had previous quality issues"
    - "Compare contract terms for vendors that share the same parent company"
    
    How it works:
    1. LLM analyzes your Neo4j graph schema (nodes, relationships, properties)
    2. LLM generates Cypher query from natural language
    3. Query executes with automatic group_id filtering for security
    4. Returns results with the generated Cypher for transparency
    
    Note: This is more advanced than Microsoft GraphRAG's native capabilities.
    """
    group_id = request.state.group_id
    logger.info("text_to_cypher_query", group_id=group_id, query=payload.query[:50])
    
    try:
        service = get_retrieval_service()
        result = await service.text_to_cypher_search(
            group_id=group_id,
            query=payload.query,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=[],  # Cypher results are in metadata
            metadata={
                "cypher_query": result.get("cypher_query"),
                "results": result.get("results", []),
                **result.get("metadata", {}),
            },
        )
        
    except Exception as e:
        logger.error("text_to_cypher_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/structured", response_model=StructuredQueryResponse)
async def query_structured(request: Request, payload: StructuredQueryRequest):
    """
    PRIMARY SCHEMA USE CASE: Schema-Guided Structured Retrieval.
    
    This endpoint extracts structured data from the Knowledge Graph at QUERY time
    using a user-provided JSON schema. This is similar to Azure Content Understanding
    but operates on the local Knowledge Graph instead of raw documents.
    
    **When to use:**
    - Extract specific fields from indexed documents (vendor, amount, date, etc.)
    - Get structured JSON output instead of natural language answers
    - Enforce output format for downstream processing
    
    **Examples:**
    
    1. Extract invoice details:
    ```json
    {
        "query": "Extract invoice details from the uploaded documents",
        "output_schema": {
            "type": "object",
            "properties": {
                "vendor_name": {"type": "string", "description": "Name of the vendor/supplier"},
                "invoice_number": {"type": "string"},
                "total_amount": {"type": "number"},
                "due_date": {"type": "string", "description": "Payment due date"}
            },
            "required": ["vendor_name", "total_amount"]
        },
        "schema_name": "InvoiceExtraction"
    }
    ```
    
    2. Extract contract parties:
    ```json
    {
        "query": "Who are the parties in the purchase agreement?",
        "output_schema": {
            "type": "object",
            "properties": {
                "buyer": {"type": "object", "properties": {"name": {"type": "string"}, "address": {"type": "string"}}},
                "seller": {"type": "object", "properties": {"name": {"type": "string"}, "address": {"type": "string"}}},
                "effective_date": {"type": "string"}
            }
        }
    }
    ```
    
    **Flow:**
    1. GraphRAG retrieves relevant context (vector search + graph traversal)
    2. LLM extracts structured data from context using the schema
    3. Output is validated against the provided schema
    4. Returns structured JSON with confidence score and provenance
    
    **Response:**
    - `answer`: The extracted structured JSON matching output_schema
    - `sources`: List of source nodes used for extraction (provenance)
    - `metadata.confidence`: Confidence score (0-1) based on field completeness
    - `metadata.validation_errors`: Any schema validation errors
    """
    group_id = request.state.group_id
    logger.info(
        "structured_query", 
        group_id=group_id, 
        query=payload.query[:50],
        schema_name=payload.schema_name
    )
    
    try:
        service = get_retrieval_service()
        result = await service.structured_search(
            group_id=group_id,
            query=payload.query,
            output_schema=payload.output_schema,
            schema_name=payload.schema_name,
            top_k=payload.top_k,
        )
        
        return StructuredQueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],  # Structured JSON
            sources=result.get("sources", []),
            metadata=result.get("metadata", {}),
        )
        
    except Exception as e:
        logger.error("structured_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/structured-from-vault", response_model=StructuredQueryResponse)
async def query_structured_from_vault(request: Request, payload: SchemaVaultQueryRequest):
    """
    Schema-Guided Structured Retrieval using a schema from Schema Vault.
    
    Same as /query/structured but references a schema by ID from Schema Vault
    instead of providing the full JSON schema inline.
    
    **When to use:**
    - You have a pre-defined schema stored in Schema Vault
    - You want to reuse the same extraction schema across multiple queries
    - You want to avoid sending large schemas in each request
    
    **Example:**
    ```json
    {
        "query": "Extract vendor and payment details from the invoice",
        "schema_id": "invoice-extraction-v1"
    }
    ```
    
    **Flow:**
    1. Fetch schema from Schema Vault using schema_id
    2. GraphRAG retrieves relevant context
    3. LLM extracts structured data using the schema
    4. Returns structured JSON with provenance
    """
    group_id = request.state.group_id
    logger.info(
        "structured_query_from_vault", 
        group_id=group_id, 
        query=payload.query[:50],
        schema_id=payload.schema_id
    )
    
    try:
        # Fetch schema from Schema Vault
        from src.worker.services.schema_service import SchemaService
        schema_service = SchemaService()
        
        schema_doc = await schema_service.get_schema(group_id, payload.schema_id)
        if not schema_doc:
            raise HTTPException(
                status_code=404, 
                detail=f"Schema '{payload.schema_id}' not found in Schema Vault"
            )
        
        # Extract the JSON schema from the schema document
        output_schema = schema_service.extract_json_schema(schema_doc)
        schema_name = schema_doc.get("name", payload.schema_id)
        
        # Perform structured search
        service = get_retrieval_service()
        result = await service.structured_search(
            group_id=group_id,
            query=payload.query,
            output_schema=output_schema,
            schema_name=schema_name,
            top_k=payload.top_k,
        )
        
        return StructuredQueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata={
                **result.get("metadata", {}),
                "schema_id": payload.schema_id,
            },
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("structured_query_from_vault_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DOCUMENT LIFECYCLE MANAGEMENT ENDPOINTS
# ============================================================================

class DocumentListResponse(BaseModel):
    """Response for listing indexed documents."""
    group_id: str
    documents: List[Dict[str, Any]]
    total_count: int


class DocumentDeleteRequest(BaseModel):
    """Request to delete a document by URL."""
    url: str


class BatchDeleteRequest(BaseModel):
    """Request to delete multiple documents by URLs."""
    urls: List[str]


class BatchDeleteResponse(BaseModel):
    """Response for batch document deletion."""
    status: str
    total_requested: int
    successful_deletions: int
    failed_deletions: int
    results: List[Dict[str, Any]]


class DocumentDeleteResponse(BaseModel):
    """Response for document deletion."""
    status: str
    url: str
    neo4j_stats: Dict[str, Any]
    vector_stats: Dict[str, int]
    message: str


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(request: Request):
    """
    List all indexed documents for a tenant.
    
    Returns document metadata including:
    - url: Original source URL
    - page_count: Number of pages indexed
    - node_count: Number of graph nodes created
    """
    group_id = request.state.group_id
    logger.info("list_documents", group_id=group_id)
    
    try:
        from src.worker.services.graph_service import GraphService
        graph_service = GraphService()
        
        documents = graph_service.list_indexed_documents(group_id)
        
        return DocumentListResponse(
            group_id=group_id,
            documents=documents,
            total_count=len(documents),
        )
        
    except Exception as e:
        logger.error("list_documents_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/delete", response_model=DocumentDeleteResponse)
async def delete_document(request: Request, payload: DocumentDeleteRequest):
    """
    Delete a document and all associated nodes/edges from the knowledge graph.
    
    This removes:
    - All Neo4j nodes with matching URL
    - All relationships connected to those nodes
    - All vector embeddings in LanceDB/Azure Search
    
    Args:
        url: The document URL to delete (must match exactly)
        
    Returns:
        Deletion statistics for Neo4j and vector store
    """
    group_id = request.state.group_id
    logger.info("delete_document", group_id=group_id, url=payload.url[:80])
    
    try:
        from src.worker.services.graph_service import GraphService
        
        graph_service = GraphService()
        
        # Delete from Neo4j (vectors are stored in Neo4j natively)
        neo4j_stats = graph_service.delete_document_by_url(group_id, payload.url)
        
        return DocumentDeleteResponse(
            status="completed",
            url=payload.url,
            neo4j_stats=neo4j_stats,
            vector_stats={"vectors_deleted": neo4j_stats.get('nodes_deleted', 0)},  # Vectors deleted with nodes
            message=f"Deleted {neo4j_stats['nodes_deleted']} nodes, {neo4j_stats['relationships_deleted']} relationships (vectors embedded in nodes)",
        )
        
    except Exception as e:
        logger.error("delete_document_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/batch-delete", response_model=BatchDeleteResponse)
async def batch_delete_documents(request: Request, payload: BatchDeleteRequest):
    """
    Delete multiple documents in a single request.
    
    This is more efficient than calling /documents/delete multiple times.
    Each document deletion is independent - failures don't stop the batch.
    
    Args:
        urls: List of document URLs to delete
        
    Returns:
        Batch deletion statistics with per-document results
    """
    group_id = request.state.group_id
    logger.info("batch_delete_documents", group_id=group_id, count=len(payload.urls))
    
    try:
        from src.worker.services.graph_service import GraphService
        
        graph_service = GraphService()
        
        results = []
        successful = 0
        failed = 0
        
        for url in payload.urls:
            try:
                # Delete from Neo4j (vectors are stored in Neo4j natively)
                neo4j_stats = graph_service.delete_document_by_url(group_id, url)
                
                results.append({
                    "url": url,
                    "status": "success",
                    "nodes_deleted": neo4j_stats["nodes_deleted"],
                    "relationships_deleted": neo4j_stats["relationships_deleted"],
                    "vectors_deleted": neo4j_stats.get("nodes_deleted", 0),  # Vectors embedded in nodes
                })
                successful += 1
                
            except Exception as e:
                logger.error("batch_delete_item_failed", url=url[:80], error=str(e))
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": str(e),
                })
                failed += 1
        
        return BatchDeleteResponse(
            status="completed",
            total_requested=len(payload.urls),
            successful_deletions=successful,
            failed_deletions=failed,
            results=results,
        )
        
    except Exception as e:
        logger.error("batch_delete_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/stats")
async def get_document_stats(request: Request, url: str):
    """
    Get detailed statistics for a specific document.
    
    Query params:
        url: Document URL
        
    Returns:
        Node counts, label distributions, page numbers
    """
    group_id = request.state.group_id
    logger.info("document_stats", group_id=group_id, url=url[:80])
    
    try:
        from src.worker.services.graph_service import GraphService
        graph_service = GraphService()
        
        stats = graph_service.get_document_stats(group_id, url)
        
        return {
            "group_id": group_id,
            "url": url,
            **stats,
        }
        
    except Exception as e:
        logger.error("document_stats_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Neo4j Hybrid Search Endpoints (Step 7 of Best-Quality Pipeline)
# =============================================================================

class HybridSearchRequest(BaseModel):
    """Request for Neo4j hybrid search."""
    query: str
    top_k: int = 10
    use_rrf: bool = True  # Use Reciprocal Rank Fusion
    vector_weight: float = 0.7
    fulltext_weight: float = 0.3
    include_graph_context: bool = True  # Also run graph traversal (Step 8)
    traversal_depth: int = 2


class SeedNodeResponse(BaseModel):
    """Response with seed nodes from hybrid search."""
    query: str
    seed_nodes: List[Dict[str, Any]]
    graph_context: Optional[List[Dict[str, Any]]] = None
    stats: Dict[str, Any]


@router.get("/debug/neo4j")
async def debug_neo4j(request: Request):
    """
    Debug endpoint to inspect Neo4j structure.
    
    Returns:
    - All node labels in the database
    - Node counts per label
    - All indexes
    - Sample of node properties for each label
    
    Use this to understand what LlamaIndex PropertyGraphIndex creates.
    """
    group_id = request.state.group_id
    logger.info("debug_neo4j", group_id=group_id)
    
    try:
        from src.worker.services.graph_service import GraphService
        
        graph_service = GraphService()
        store = graph_service.get_store(group_id)
        
        # Get all node labels and counts
        labels_simple = """
        MATCH (n)
        WITH labels(n) AS labelList, n
        UNWIND labelList AS label
        RETURN label, count(DISTINCT n) AS count
        ORDER BY count DESC
        """
        
        try:
            labels_result = store.structured_query(labels_simple)
        except Exception as e:
            labels_result = [{"error": str(e)}]
        
        # Get all indexes
        indexes_query = """
        SHOW INDEXES
        YIELD name, type, labelsOrTypes, properties, state
        RETURN name, type, labelsOrTypes, properties, state
        """
        
        try:
            indexes_result = store.structured_query(indexes_query)
        except Exception as e:
            indexes_result = [{"error": str(e)}]
        
        # Get sample node properties for key labels
        sample_properties = {}
        key_labels = ["__Entity__", "__Node__", "Chunk", "Document", "Entity"]
        
        for label in key_labels:
            try:
                sample_query = f"""
                MATCH (n:`{label}`)
                RETURN keys(n) AS properties, n.id AS id, n.name AS name
                LIMIT 3
                """
                sample_result = store.structured_query(sample_query)
                if sample_result:
                    sample_properties[label] = sample_result
            except Exception as e:
                sample_properties[label] = {"error": str(e)}
        
        # Check for nodes with embeddings
        embedding_query = """
        MATCH (n)
        WHERE n.embedding IS NOT NULL
        WITH labels(n) AS labelList, n
        UNWIND labelList AS label
        RETURN label, count(n) AS nodes_with_embedding
        ORDER BY nodes_with_embedding DESC
        """
        
        try:
            embedding_result = store.structured_query(embedding_query)
        except Exception as e:
            embedding_result = [{"error": str(e)}]
        
        return {
            "status": "ok",
            "group_id": group_id,
            "labels_and_counts": labels_result,
            "indexes": indexes_result,
            "sample_properties": sample_properties,
            "nodes_with_embeddings": embedding_result,
        }
        
    except Exception as e:
        logger.error("debug_neo4j_failed", group_id=group_id, error=str(e))
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc()
        }


@router.post("/indexes/setup-hybrid")
async def setup_hybrid_indexes(request: Request):
    """
    Set up Neo4j indexes required for hybrid search.
    
    Creates:
    1. Full-text index on __Entity__ nodes (name, id fields)
    2. Vector index on __Entity__ nodes (embedding field)
    
    This is a one-time setup required before using hybrid search.
    Run this after initial document indexing.
    """
    group_id = request.state.group_id
    logger.info("setup_hybrid_indexes", group_id=group_id)
    
    try:
        from src.worker.services.neo4j_hybrid_search import get_hybrid_search_service
        
        service = get_hybrid_search_service()
        result = await service.ensure_indexes_exist(group_id)
        
        return {
            "status": "completed",
            "group_id": group_id,
            "indexes": result,
            "message": "Neo4j hybrid search indexes are ready",
        }
        
    except Exception as e:
        logger.error("setup_hybrid_indexes_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/seed-nodes", response_model=SeedNodeResponse)
async def find_seed_nodes(request: Request, payload: HybridSearchRequest):
    """
    Find seed nodes using Neo4j Hybrid Search (Step 7).
    
    This implements the critical Step 7 of the best-quality GraphRAG pipeline:
    "LlamaIndex → Neo4j Hybrid Search: Runs Vector + Full-Text search 
    on the target KG's index to find initial seed nodes"
    
    The hybrid search combines:
    - Vector search (semantic similarity via embeddings)
    - Full-text search (keyword/BM25 matching on entity names)
    
    Results are merged using Reciprocal Rank Fusion (RRF) by default.
    
    If include_graph_context=True, also performs Step 8 (graph traversal)
    to expand the seed nodes to their connected neighbors.
    """
    group_id = request.state.group_id
    logger.info("find_seed_nodes", group_id=group_id, query=payload.query[:50])
    
    try:
        from src.worker.services.neo4j_hybrid_search import get_hybrid_search_service
        
        service = get_hybrid_search_service()
        
        # Step 7: Hybrid search for seed nodes
        seed_nodes = await service.find_seed_nodes(
            query=payload.query,
            group_id=group_id,
            top_k=payload.top_k,
            use_rrf=payload.use_rrf,
            vector_weight=payload.vector_weight,
            fulltext_weight=payload.fulltext_weight,
        )
        
        # Step 8: Optional graph traversal
        graph_context = None
        if payload.include_graph_context and seed_nodes:
            graph_context = await service.get_seed_node_context(
                seed_nodes=seed_nodes,
                group_id=group_id,
                depth=payload.traversal_depth,
            )
        
        return SeedNodeResponse(
            query=payload.query,
            seed_nodes=seed_nodes,
            graph_context=graph_context,
            stats={
                "seed_node_count": len(seed_nodes),
                "triplet_count": len(graph_context) if graph_context else 0,
                "use_rrf": payload.use_rrf,
                "traversal_depth": payload.traversal_depth if payload.include_graph_context else 0,
            },
        )
        
    except Exception as e:
        logger.error("find_seed_nodes_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/all")
async def delete_all_documents(request: Request):
    """
    Delete ALL documents for a tenant (DANGEROUS - use with caution).
    
    This removes the entire knowledge graph and all vectors for the tenant.
    Use this to reset a tenant's data or clean up test data.
    
    Returns:
        Deletion statistics
    """
    group_id = request.state.group_id
    logger.warning("delete_all_documents", group_id=group_id)
    
    try:
        from src.worker.services.graph_service import GraphService
        
        graph_service = GraphService()
        
        # Delete from Neo4j (vectors are stored in Neo4j natively)
        neo4j_stats = graph_service.delete_all_documents(group_id)
        
        return {
            "status": "completed",
            "group_id": group_id,
            "neo4j_stats": neo4j_stats,
            "vector_stats": {"vectors_deleted": neo4j_stats.get('nodes_deleted', 0)},  # Vectors embedded in nodes
            "message": f"Deleted all data for group {group_id}",
        }
        
    except Exception as e:
        logger.error("delete_all_documents_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# V2 ENDPOINTS: Using neo4j-graphrag-python Package
# ============================================================
# These endpoints use the simplified neo4j-graphrag-python package
# which replaces ~1,600 lines of custom code with official Neo4j components.
#
# Benefits:
# - 70% code reduction
# - Official Neo4j package (maintained by Neo4j team)
# - Built-in entity resolution
# - Production-grade error handling
# - VectorRetriever, HybridRetriever, Text2CypherRetriever
# ============================================================


class V2QueryRequest(BaseModel):
    """Request for v2 endpoints using neo4j-graphrag package."""
    query: str
    top_k: int = 10


class V2IndexRequest(BaseModel):
    """Request for v2 indexing using SimpleKGPipeline + RAPTOR."""
    text: str
    document_name: Optional[str] = None
    entity_types: Optional[List[str]] = None
    relation_types: Optional[List[str]] = None
    use_raptor: bool = True  # Enable RAPTOR hierarchical indexing by default


class V2IndexFileRequest(BaseModel):
    """Request for v2 file indexing - downloads PDFs, extracts with Azure DI, then RAPTOR + Neo4j."""
    file_urls: List[str]  # URLs to PDF files (can include SAS tokens)
    ingestion_mode: str = "document-intelligence"  # document-intelligence, llamaparse
    entity_types: Optional[List[str]] = None
    relation_types: Optional[List[str]] = None
    use_raptor: bool = True  # Enable RAPTOR hierarchical indexing by default


@router.post("/v2/index/file")
async def index_file_v2(request: Request, payload: V2IndexFileRequest):
    """
    V2 File Indexing - Full pipeline: Azure DI → RAPTOR → Neo4j.
    
    This endpoint processes PDF files through:
    1. Download from URL (supports SAS tokens)
    2. Azure Document Intelligence - Extract text/tables as markdown
    3. RAPTOR - Create hierarchical summaries → Azure AI Search
    4. SimpleKGPipeline - Extract entities/relationships → Neo4j
    
    Args:
        file_urls: List of URLs to PDF files (can include SAS tokens)
        ingestion_mode: "document-intelligence" (default) or "llamaparse"
        entity_types: Optional list of entity types to extract
        relation_types: Optional list of relationship types
        use_raptor: Enable RAPTOR hierarchical indexing (default: True)
    
    Flow:
        PDF → Azure DI (text extraction) → {
            Text → RAPTOR → Azure AI Search (semantic ranking)
            Text → SimpleKGPipeline → Neo4j (entity graph)
        }
    """
    group_id = request.state.group_id
    logger.info("v2_index_file", group_id=group_id, file_count=len(payload.file_urls), use_raptor=payload.use_raptor)
    
    try:
        # Step 1: Extract text from files using Azure Document Intelligence
        documents = await _to_documents(
            input_items=payload.file_urls,
            ingestion_mode=payload.ingestion_mode,
            group_id=group_id
        )
        
        if not documents:
            return {
                "status": "error",
                "message": "No documents extracted from files",
                "files_processed": 0,
            }
        
        logger.info(f"Extracted {len(documents)} documents from {len(payload.file_urls)} files")
        
        # Step 2: Index each document through RAPTOR + Neo4j
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        service = get_neo4j_graphrag_service()
        
        results = []
        total_raptor_nodes = 0
        total_neo4j_nodes = 0
        
        for i, doc in enumerate(documents):
            # Extract document name from metadata or URL
            doc_name = doc.metadata.get("file_name") or doc.metadata.get("source") or f"document_{i+1}"
            
            result = await service.index_text(
                group_id=group_id,
                text=doc.text,
                document_name=doc_name,
                entity_types=payload.entity_types,
                relation_types=payload.relation_types,
                use_raptor=payload.use_raptor,
            )
            
            results.append({
                "document_name": doc_name,
                "status": result.get("status"),
                "text_length": len(doc.text),
                "raptor": result.get("raptor"),
                "neo4j": result.get("neo4j"),
            })
            
            # Aggregate stats
            if result.get("raptor"):
                total_raptor_nodes += result["raptor"].get("raptor_nodes", 0)
            if result.get("neo4j"):
                total_neo4j_nodes += result["neo4j"].get("nodes_updated", 0)
        
        return {
            "status": "success",
            "group_id": group_id,
            "files_processed": len(payload.file_urls),
            "documents_indexed": len(documents),
            "total_raptor_nodes": total_raptor_nodes,
            "total_neo4j_nodes": total_neo4j_nodes,
            "pipeline": "Azure DI → RAPTOR → Azure AI Search + Neo4j" if payload.use_raptor else "Azure DI → Neo4j",
            "results": results,
        }
        
    except Exception as e:
        logger.error("v2_index_file_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/query/local", response_model=QueryResponse)
async def query_local_v2(request: Request, payload: V2QueryRequest):
    """
    V2 Local Search using neo4j-graphrag VectorRetriever.
    
    This is a simplified implementation using the official neo4j-graphrag-python
    package. It provides the same functionality with less code and better
    maintainability.
    
    Improvements over v1:
    - Uses official Neo4j VectorRetriever (battle-tested)
    - Integrated with GraphRAG for response generation
    - Cleaner multi-tenant filtering
    """
    group_id = request.state.group_id
    logger.info("v2_local_query", group_id=group_id, query=payload.query[:50])
    
    try:
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        
        service = get_neo4j_graphrag_service()
        result = await service.local_search(
            group_id=group_id,
            query=payload.query,
            top_k=payload.top_k,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata=result.get("metadata", {}),
        )
        
    except Exception as e:
        logger.error("v2_local_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/query/hybrid", response_model=QueryResponse)
async def query_hybrid_v2(request: Request, payload: V2QueryRequest):
    """
    V2 Hybrid Search using neo4j-graphrag HybridRetriever.
    
    Combines vector similarity + fulltext search using the official
    neo4j-graphrag-python package.
    
    Improvements over v1:
    - Uses official Neo4j HybridRetriever
    - Better BM25 + vector fusion
    - Simpler implementation
    """
    group_id = request.state.group_id
    logger.info("v2_hybrid_query", group_id=group_id, query=payload.query[:50])
    
    try:
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        
        service = get_neo4j_graphrag_service()
        result = await service.hybrid_search(
            group_id=group_id,
            query=payload.query,
            top_k=payload.top_k,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata=result.get("metadata", {}),
        )
        
    except Exception as e:
        logger.error("v2_hybrid_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/query/structured", response_model=QueryResponse)
async def query_structured_v2(request: Request, payload: V2QueryRequest):
    """
    V2 Structured Search using neo4j-graphrag Text2CypherRetriever.
    
    Converts natural language to Cypher queries using the official
    neo4j-graphrag-python package.
    
    Improvements over v1:
    - Uses official Neo4j Text2CypherRetriever
    - Better schema-aware Cypher generation
    - Automatic group_id filtering in generated queries
    """
    group_id = request.state.group_id
    logger.info("v2_structured_query", group_id=group_id, query=payload.query[:50])
    
    try:
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        
        service = get_neo4j_graphrag_service()
        result = await service.structured_search(
            group_id=group_id,
            query=payload.query,
            top_k=payload.top_k,
        )
        
        return QueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata=result.get("metadata", {}),
        )
        
    except Exception as e:
        logger.error("v2_structured_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


class V2SchemaGuidedRequest(BaseModel):
    """Request for V2 schema-guided structured extraction."""
    query: str  # Natural language query describing what to extract
    output_schema: Dict[str, Any]  # JSON schema defining expected output structure
    schema_name: Optional[str] = None  # Optional name for logging
    top_k: int = 20  # Number of chunks to retrieve for context
    temperature: float = 0.7  # LLM temperature (0.0 = deterministic, 1.0 = creative)


@router.post("/v2/query/schema-guided", response_model=StructuredQueryResponse)
async def query_schema_guided_v2(request: Request, payload: V2SchemaGuidedRequest):
    """
    V2 Schema-Guided Structured Extraction (Multi-Step Reasoning).
    
    This is the "multi-step reasoning with schema and single prompt" capability:
    
    **Step 1 (Automatic):** Hybrid retrieval from Neo4j graph
    - Vector similarity search on chunk embeddings
    - Fulltext search on chunk text
    - Group-based isolation (multi-tenancy)
    
    **Step 2 (Automatic):** LLM-based structured extraction
    - Uses the provided JSON schema to guide extraction
    - Returns structured JSON matching the schema
    - Includes confidence score and validation
    
    **When to use:**
    - Extract specific fields from indexed documents (vendor, amount, date)
    - Get structured JSON output instead of natural language answers
    - Enforce output format for downstream processing
    - Summarize multiple documents into a structured format
    
    **Example Request:**
    ```json
    {
        "query": "Summarize each document with key parties, dates, and amounts",
        "output_schema": {
            "type": "object",
            "properties": {
                "documents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "summary": {"type": "string"},
                            "key_parties": {"type": "array", "items": {"type": "string"}},
                            "key_dates": {"type": "array", "items": {"type": "string"}},
                            "key_amounts": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                }
            }
        },
        "schema_name": "DocumentSummarization",
        "top_k": 30
    }
    ```
    
    **Response:**
    - `answer`: Structured JSON matching output_schema
    - `sources`: Retrieved chunks used for extraction (provenance)
    - `metadata.confidence`: Field completeness score (0-1)
    - `metadata.validation_errors`: Schema validation issues
    """
    group_id = request.state.group_id
    logger.info(
        "v2_schema_guided_query", 
        group_id=group_id, 
        query=payload.query[:50],
        schema_name=payload.schema_name
    )
    
    try:
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        
        service = get_neo4j_graphrag_service()
        result = await service.schema_guided_extraction(
            group_id=group_id,
            query=payload.query,
            output_schema=payload.output_schema,
            schema_name=payload.schema_name,
            top_k=payload.top_k,
            temperature=payload.temperature,
        )
        
        return StructuredQueryResponse(
            query=result["query"],
            mode=result["mode"],
            answer=result["answer"],
            sources=result.get("sources", []),
            metadata=result.get("metadata", {}),
        )
        
    except Exception as e:
        logger.error("v2_schema_guided_query_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/index/text")
async def index_text_v2(request: Request, payload: V2IndexRequest):
    """
    V2 Text Indexing using RAPTOR + SimpleKGPipeline.
    
    This endpoint combines:
    1. RAPTOR (hierarchical summaries) → Azure AI Search (semantic ranking)
    2. SimpleKGPipeline → Neo4j (entity/relationship graph)
    
    Benefits:
    - RAPTOR provides rich hierarchical context for better retrieval quality
    - Azure AI Search enables semantic re-ranking for accuracy
    - Neo4j provides entity/relationship traversal for graph queries
    - Entity resolution (deduplication) from SimpleKGPipeline
    
    Args:
        text: The text content to index
        document_name: Optional name for the document
        entity_types: Optional list of entity types to extract
        relation_types: Optional list of relationship types
        use_raptor: Enable RAPTOR hierarchical indexing (default: True)
    """
    group_id = request.state.group_id
    logger.info("v2_index_text", group_id=group_id, text_length=len(payload.text), use_raptor=payload.use_raptor)
    
    try:
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        
        service = get_neo4j_graphrag_service()
        result = await service.index_text(
            group_id=group_id,
            text=payload.text,
            document_name=payload.document_name,
            entity_types=payload.entity_types,
            relation_types=payload.relation_types,
            use_raptor=payload.use_raptor,
        )
        
        return result
        
    except Exception as e:
        logger.error("v2_index_text_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v2/debug/neo4j")
async def debug_neo4j_v2(request: Request):
    """
    V2 Debug endpoint to inspect Neo4j structure.
    
    Uses neo4j-graphrag driver to query:
    - All node labels and counts
    - All indexes (vector, fulltext, etc.)
    - Sample node properties for key labels
    - Nodes with embeddings
    
    Use this to understand what SimpleKGPipeline creates.
    """
    group_id = request.state.group_id
    logger.info("v2_debug_neo4j", group_id=group_id)
    
    try:
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        
        service = get_neo4j_graphrag_service()
        driver = service.driver
        
        with driver.session() as session:
            # Get all node labels and counts
            labels_result = session.run("""
                MATCH (n)
                WITH labels(n) AS labelList, n
                UNWIND labelList AS label
                RETURN label, count(DISTINCT n) AS count
                ORDER BY count DESC
            """).data()
            
            # Get all indexes
            indexes_result = session.run("""
                SHOW INDEXES
                YIELD name, type, labelsOrTypes, properties, state
                RETURN name, type, labelsOrTypes, properties, state
            """).data()
            
            # Get sample node properties for key labels
            sample_properties = {}
            key_labels = ["__Entity__", "__Node__", "Chunk", "Document", "Entity", "__Chunk__"]
            
            for label in key_labels:
                try:
                    result = session.run(f"""
                        MATCH (n:`{label}`)
                        RETURN keys(n) AS properties, n.id AS id, n.name AS name, n.text AS text
                        LIMIT 3
                    """).data()
                    if result:
                        sample_properties[label] = result
                except Exception as e:
                    sample_properties[label] = {"error": str(e)}
            
            # Check for nodes with embeddings
            embedding_result = session.run("""
                MATCH (n)
                WHERE n.embedding IS NOT NULL
                WITH labels(n) AS labelList, n
                UNWIND labelList AS label
                RETURN label, count(n) AS nodes_with_embedding
                ORDER BY nodes_with_embedding DESC
            """).data()
            
            # Get nodes for this group
            group_nodes = session.run("""
                MATCH (n {group_id: $group_id})
                WITH labels(n) AS labelList, n
                UNWIND labelList AS label
                RETURN label, count(DISTINCT n) AS count
                ORDER BY count DESC
            """, group_id=group_id).data()
        
        return {
            "status": "ok",
            "group_id": group_id,
            "all_labels_and_counts": labels_result,
            "indexes": indexes_result,
            "sample_properties": sample_properties,
            "nodes_with_embeddings": embedding_result,
            "group_specific_nodes": group_nodes,
        }
        
    except Exception as e:
        logger.error("v2_debug_neo4j_failed", group_id=group_id, error=str(e))
        import traceback
        return {
            "status": "error",
            "group_id": group_id,
            "error": str(e),
            "trace": traceback.format_exc()
        }


@router.post("/v2/indexes/setup")
async def setup_v2_indexes(request: Request):
    """
    Create V2-compatible Neo4j indexes for vector and fulltext search.
    
    Creates:
    - chunk_vector: Vector index on __Node__ nodes (for chunk text embeddings)
    - chunk_fulltext: Fulltext index on __Node__ text property
    - entity_vector: Vector index on __Entity__ nodes
    - entity_fulltext: Fulltext index on __Entity__ name/id
    
    Run this once after indexing documents to enable V2 queries.
    """
    group_id = request.state.group_id
    logger.info("v2_setup_indexes", group_id=group_id)
    
    try:
        from src.worker.services.neo4j_graphrag_service import get_neo4j_graphrag_service
        
        service = get_neo4j_graphrag_service()
        result = service.setup_indexes()
        
        return {
            "status": "completed",
            "group_id": group_id,
            "indexes": result,
            "message": "V2 Neo4j indexes created successfully",
        }
        
    except Exception as e:
        logger.error("v2_setup_indexes_failed", group_id=group_id, error=str(e))
        import traceback
        return {
            "status": "error",
            "group_id": group_id,
            "error": str(e),
            "trace": traceback.format_exc()
        }
