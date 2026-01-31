from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import structlog

from src.worker.services.retrieval_service import RetrievalService
from src.worker.services.llm_service import LLMService

router = APIRouter()
logger = structlog.get_logger()

# Service instances
_retrieval_service: Optional[RetrievalService] = None
_llm_service: Optional[LLMService] = None


def get_retrieval_service() -> RetrievalService:
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


class OrchestrationRequest(BaseModel):
    query: str
    mode: str = "auto"  # auto, hybrid, vector, graph, global, local
    top_k: int = 10


class OrchestrationResponse(BaseModel):
    query: str
    selected_mode: str
    answer: str
    reasoning: Optional[str] = None
    sources: List[Dict[str, Any]]


class ExtractionRequest(BaseModel):
    document_text: str
    entity_types: Optional[List[str]] = None
    relation_types: Optional[List[str]] = None


class ExtractionResponse(BaseModel):
    entities: List[Dict[str, Any]]
    relations: List[Dict[str, Any]]
    triplets: List[Dict[str, Any]]


@router.post("/analyze", response_model=OrchestrationResponse)
async def analyze_query(request: Request, payload: OrchestrationRequest):
    """
    Orchestrates the query using intelligent mode selection.
    
    When mode="auto", uses LLM to determine the best retrieval strategy:
    - global: For thematic/summary questions
    - local: For entity-focused questions
    - hybrid: For general questions needing both vector and graph
    """
    group_id = request.state.group_id
    logger.info("orchestration_analyze", group_id=group_id, mode=payload.mode)
    
    try:
        retrieval_service = get_retrieval_service()
        llm_service = get_llm_service()
        
        # Determine mode
        if payload.mode == "auto":
            selected_mode, reasoning = await _classify_query(
                llm_service, 
                payload.query
            )
        else:
            selected_mode = payload.mode
            reasoning = f"User specified mode: {payload.mode}"
        
        # Execute query with selected mode
        if selected_mode == "global":
            result = await retrieval_service.global_search(
                group_id=group_id,
                query=payload.query,
                top_k=payload.top_k,
            )
        elif selected_mode == "local":
            result = await retrieval_service.local_search(
                group_id=group_id,
                query=payload.query,
                top_k=payload.top_k,
            )
        else:  # hybrid (default)
            result = await retrieval_service.hybrid_search(
                group_id=group_id,
                query=payload.query,
                top_k=payload.top_k,
            )
        
        # Combine sources
        sources = result.get("sources", [])
        if not sources:
            sources = result.get("vector_sources", []) + result.get("graph_sources", [])
        
        return OrchestrationResponse(
            query=payload.query,
            selected_mode=selected_mode,
            answer=result["answer"],
            reasoning=reasoning,
            sources=sources,
        )
        
    except Exception as e:
        logger.error("orchestration_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract", response_model=ExtractionResponse)
async def extract_knowledge(request: Request, payload: ExtractionRequest):
    """
    Extract entities and relationships from text without storing them.
    
    Useful for previewing what would be extracted before indexing,
    or for one-off extraction tasks.
    """
    group_id = request.state.group_id
    logger.info("extraction_requested", group_id=group_id)
    
    try:
        llm_service = get_llm_service()
        
        entity_types = payload.entity_types or [
            "Person", "Organization", "Location", "Event", "Concept"
        ]
        relation_types = payload.relation_types or [
            "WORKS_FOR", "LOCATED_IN", "RELATED_TO", "PART_OF", "MENTIONS"
        ]
        
        # Use LLM to extract entities and relations
        extraction_prompt = f"""Extract entities and relationships from the following text.

Entity Types to look for: {', '.join(entity_types)}
Relationship Types to look for: {', '.join(relation_types)}

Text:
{payload.document_text}

Return a JSON object with the following structure:
{{
    "entities": [
        {{"name": "...", "type": "...", "description": "..."}}
    ],
    "relations": [
        {{"source": "...", "target": "...", "type": "...", "description": "..."}}
    ]
}}

Only include entities and relations that are clearly stated or strongly implied in the text."""

        response = llm_service.generate(extraction_prompt)
        
        # Parse JSON response
        import json
        try:
            extracted = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                extracted = json.loads(json_match.group())
            else:
                extracted = {"entities": [], "relations": []}
        
        entities = extracted.get("entities", [])
        relations = extracted.get("relations", [])
        
        # Build triplets from relations
        triplets = [
            {
                "subject": r["source"],
                "predicate": r["type"],
                "object": r["target"],
                "description": r.get("description", ""),
            }
            for r in relations
        ]
        
        return ExtractionResponse(
            entities=entities,
            relations=relations,
            triplets=triplets,
        )
        
    except Exception as e:
        logger.error("extraction_failed", group_id=group_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def _classify_query(llm_service: LLMService, query: str) -> tuple[str, str]:
    """
    Use LLM to classify query and select optimal retrieval mode.
    
    Returns:
        Tuple of (mode, reasoning)
    """
    classification_prompt = f"""Classify the following question to determine the best retrieval strategy.

Question: {query}

Classification options:
1. "global" - For broad, thematic questions that ask about overall patterns, summaries, or main themes
   Examples: "What are the main topics?", "Summarize the key findings", "What themes emerge?"

2. "local" - For specific entity-focused questions about particular people, organizations, or things
   Examples: "Who is John Smith?", "Tell me about Company X", "What is the relationship between A and B?"

3. "hybrid" - For general questions that benefit from both semantic search and knowledge graph traversal
   Examples: "How does X work?", "What happened in the meeting?", "Explain the process"

Respond with ONLY a JSON object:
{{"mode": "global|local|hybrid", "reasoning": "brief explanation"}}"""

    response = llm_service.generate(classification_prompt)
    
    import json
    try:
        result = json.loads(response)
        return result.get("mode", "hybrid"), result.get("reasoning", "")
    except json.JSONDecodeError:
        # Default to hybrid if parsing fails
        return "hybrid", "Could not classify query, defaulting to hybrid search"
