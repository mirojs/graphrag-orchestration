"""
GraphRAG Chat Approach

A chat approach that uses the GraphRAG backend for retrieval instead of Azure AI Search.
This provides graph-based retrieval with support for local search, global search, and DRIFT.
"""

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import Any, Optional

from openai import AsyncOpenAI

from approaches.approach import Approach, DataPoints, ExtraInfo, ThoughtStep
from core.authentication import get_group_id
from graphrag.client import GraphRAGClient, GraphRAGConfig

logger = logging.getLogger(__name__)


class ChatGraphRAGApproach(Approach):
    """
    Chat approach using GraphRAG for retrieval.
    
    This approach:
    1. Sends the conversation to the GraphRAG backend
    2. GraphRAG performs route selection (Local/Global/DRIFT)
    3. Retrieves relevant context from Neo4j graph
    4. Generates response with citations
    
    Supports streaming responses via the GraphRAG streaming API.
    """
    
    def __init__(
        self,
        *,
        graphrag_client: GraphRAGClient,
        openai_client: AsyncOpenAI,
        chatgpt_model: str,
        chatgpt_deployment: Optional[str] = None,
        default_route: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ):
        """
        Initialize GraphRAG chat approach.
        
        Args:
            graphrag_client: GraphRAG API client
            openai_client: OpenAI client (for fallback or additional processing)
            chatgpt_model: Model name for chat completion
            chatgpt_deployment: Azure OpenAI deployment name (optional)
            default_route: Default route to use (2=Local, 3=Global, 4=DRIFT)
            reasoning_effort: Reasoning effort level for o1 models
        """
        self.graphrag_client = graphrag_client
        self.openai_client = openai_client
        self.chatgpt_model = chatgpt_model
        self.chatgpt_deployment = chatgpt_deployment
        self.default_route = default_route
        self.reasoning_effort = reasoning_effort
    
    async def run(
        self,
        messages: list[dict],
        context: dict[str, Any] = {},
        session_state: Any = None,
    ) -> dict[str, Any]:
        """
        Run a non-streaming chat query via GraphRAG.
        
        Args:
            messages: Conversation history
            context: Additional context (includes auth_claims, overrides)
            session_state: Session state for history tracking
            
        Returns:
            Response dict with message, citations, and thought steps
        """
        overrides = context.get("overrides", {})
        auth_claims = context.get("auth_claims", {})
        
        # Extract group_id from auth claims or overrides
        group_id = self._get_group_id(auth_claims, overrides)
        folder_id = overrides.get("folder_id")
        route = overrides.get("route", self.default_route)
        
        # Get response type (supports comprehensive_sentence mode)
        response_type = overrides.get("response_type", "detailed_report")
        force_route = overrides.get("force_route")  # e.g., "drift_multi_hop"
        
        # Call GraphRAG backend
        result = await self.graphrag_client.chat(
            group_id=group_id,
            messages=messages,
            route=route,
            folder_id=folder_id,
            response_type=response_type,
            force_route=force_route,
        )
        
        # Convert citations to the expected format
        data_points = self._format_citations(result.citations)
        
        # Build thought steps
        thoughts = []
        if result.route_used:
            thoughts.append(
                ThoughtStep(
                    title="Route Selection",
                    description=f"Used Route {result.route_used}",
                    props={"route": result.route_used},
                )
            )
        
        for step in result.thought_steps:
            thoughts.append(
                ThoughtStep(
                    title="Retrieval",
                    description=step,
                )
            )
        
        return {
            "message": {
                "role": "assistant",
                "content": result.answer,
            },
            "context": {
                "data_points": asdict(data_points) if data_points else None,
                "thoughts": [asdict(t) for t in thoughts],
            },
            "session_state": session_state,
        }
    
    async def run_stream(
        self,
        messages: list[dict],
        context: dict[str, Any] = {},
        session_state: Any = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Run a streaming chat query via GraphRAG.
        
        Args:
            messages: Conversation history
            context: Additional context (includes auth_claims, overrides)
            session_state: Session state for history tracking
            
        Yields:
            Streaming response chunks
        """
        overrides = context.get("overrides", {})
        auth_claims = context.get("auth_claims", {})
        
        group_id = self._get_group_id(auth_claims, overrides)
        folder_id = overrides.get("folder_id")
        route = overrides.get("route", self.default_route)
        
        # Get response type (supports comprehensive_sentence mode)
        response_type = overrides.get("response_type", "detailed_report")
        force_route = overrides.get("force_route")  # e.g., "drift_multi_hop"
        
        accumulated_content = ""
        citations = []
        thoughts = []
        
        try:
            async for chunk in self.graphrag_client.chat_stream(
                group_id=group_id,
                messages=messages,
                route=route,
                folder_id=folder_id,
                response_type=response_type,
                force_route=force_route,
            ):
                # Handle different chunk types
                if "content" in chunk:
                    # Content chunk - stream the text
                    content = chunk["content"]
                    accumulated_content += content
                    
                    yield {
                        "delta": {"content": content, "role": "assistant"},
                        "context": {},
                        "session_state": session_state,
                    }
                
                elif "citations" in chunk:
                    # Citations chunk - store for final response
                    citations.extend(chunk["citations"])
                
                elif "thought" in chunk:
                    # Thought step - store for final response
                    thoughts.append(chunk["thought"])
                
                elif "route_used" in chunk:
                    # Route info - add to thoughts
                    thoughts.insert(0, f"Route {chunk['route_used']} selected")
                
                elif "error" in chunk:
                    # Error - yield error message
                    yield {
                        "error": chunk["error"],
                    }
                    return
            
            # Final chunk with complete context
            data_points = self._format_citations(citations)
            thought_steps = [
                ThoughtStep(title="GraphRAG", description=t)
                for t in thoughts
            ]
            
            yield {
                "delta": {"content": "", "role": "assistant"},
                "context": {
                    "data_points": asdict(data_points) if data_points else None,
                    "thoughts": [asdict(t) for t in thought_steps],
                },
                "session_state": session_state,
            }
            
        except Exception as e:
            logger.error(f"GraphRAG streaming error: {e}")
            yield {
                "error": f"GraphRAG error: {str(e)}",
            }
    
    def _get_group_id(
        self,
        auth_claims: dict[str, Any],
        overrides: dict[str, Any],
    ) -> str:
        """
        Extract group_id from auth claims or overrides.
        
        Priority:
        1. Override group_id (for testing/admin)
        2. Shared get_group_id logic (B2B groups -> B2C oid)
        3. Default "anonymous"
        """
        # Check overrides first (admin/testing)
        if "group_id" in overrides:
            return overrides["group_id"]
        
        # Use shared get_group_id for B2B/B2C logic
        try:
            return get_group_id(auth_claims)
        except ValueError:
            # Fallback for unauthenticated requests
            return "anonymous"

    def _format_citations(self, citations: list[dict]) -> Optional[DataPoints]:
        """
        Format GraphRAG citations into DataPoints format.
        
        Produces both:
        - text: legacy "source: text" strings for backward compatibility
        - structured_citations: rich citation dicts with document_id, page_number,
          section_path, sentence_text, polygons, etc. for frontend rendering
        
        Citation names are built so the frontend AnswerParser can match inline
        [citation] markers in the answer text.  The LLM generates markers like
        ``[1]``, ``[1a]``, ``[2b]`` whose inner text (``1``, ``1a``, ``2b``)
        maps to an entry in ``citation_names``.  For chunk-level citations we
        also keep the document source name to support ``[filename.pdf]`` style
        markers.
        
        Args:
            citations: List of citation dicts from GraphRAG backend
            
        Returns:
            DataPoints object with formatted citations and structured metadata
        """
        if not citations:
            return None
        
        text_sources = []
        citation_names = []  # For inline [citation] matching
        structured = []  # Rich citation metadata
        
        for citation in citations:
            # Extract text — backend sends "text_preview", fall back to "text"/"content"
            text = (
                citation.get("text_preview")
                or citation.get("sentence_text")
                or citation.get("text")
                or citation.get("content")
                or ""
            )
            source = citation.get("source", citation.get("document", ""))
            
            # Legacy format: "source: text"
            if source:
                text_sources.append(f"{source}: {text}")
            else:
                text_sources.append(text)
            
            # Build citation name for inline matching.
            # Priority:
            #   1. Raw citation key (e.g. "1a" from "[1a]") — matches LLM-generated markers
            #   2. Source / document title — matches [filename.pdf] markers
            #   3. Truncated text preview as last resort
            raw_key = citation.get("citation", "").strip("[]").strip()
            if raw_key:
                citation_names.append(raw_key)
            elif source:
                citation_names.append(source)
            else:
                citation_names.append(text[:80] if text else "unknown")
            
            # Also add the source name if it differs from raw_key so both
            # "[1a]" and "[filename.pdf]" can resolve to this citation.
            if raw_key and source and source != raw_key and source not in citation_names:
                citation_names.append(source)
            
            # Build structured citation with all available metadata
            structured_citation: dict = {
                "citation": citation.get("citation", ""),
                "citation_type": citation.get("citation_type", "chunk"),
                "source": source,
                "document_id": citation.get("document_id", ""),
                "document_title": citation.get("document_title", citation.get("document", "")),
                "document_url": citation.get("document_url", ""),
                "chunk_id": citation.get("chunk_id", ""),
                "section_path": citation.get("section_path", citation.get("section", "")),
                "text_preview": text,
                "score": citation.get("score", 0.0),
            }
            
            # Optional location fields
            if citation.get("page_number") is not None:
                structured_citation["page_number"] = citation["page_number"]
            if citation.get("start_offset") is not None:
                structured_citation["start_offset"] = citation["start_offset"]
            if citation.get("end_offset") is not None:
                structured_citation["end_offset"] = citation["end_offset"]
            
            # Sentence-level fields
            if citation.get("sentence_text"):
                structured_citation["sentence_text"] = citation["sentence_text"]
            if citation.get("sentence_offset") is not None:
                structured_citation["sentence_offset"] = citation["sentence_offset"]
            if citation.get("sentence_length") is not None:
                structured_citation["sentence_length"] = citation["sentence_length"]
            if citation.get("sentence_confidence") is not None:
                structured_citation["sentence_confidence"] = citation["sentence_confidence"]
            
            # Polygon geometry for pixel-accurate highlighting
            if citation.get("sentences"):
                structured_citation["sentences"] = citation["sentences"]
            if citation.get("page_dimensions"):
                structured_citation["page_dimensions"] = citation["page_dimensions"]
            
            structured.append(structured_citation)
        
        return DataPoints(
            text=text_sources,
            citations=citation_names if citation_names else None,
            structured_citations=structured,
        )
