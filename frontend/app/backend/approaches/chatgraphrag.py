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
        2. First group from auth claims (B2B)
        3. User OID (B2C fallback)
        4. Default "anonymous"
        """
        # Check overrides first (admin/testing)
        if "group_id" in overrides:
            return overrides["group_id"]
        
        # B2B: Use first group from claims
        groups = auth_claims.get("groups", [])
        if groups:
            return groups[0]
        
        # B2C: Use user OID
        if "oid" in auth_claims:
            return auth_claims["oid"]
        
        # Fallback
        return "anonymous"
    
    def _format_citations(self, citations: list[dict]) -> Optional[DataPoints]:
        """
        Format GraphRAG citations into DataPoints format.
        
        Args:
            citations: List of citation dicts from GraphRAG
            
        Returns:
            DataPoints object with formatted citations
        """
        if not citations:
            return None
        
        text_sources = []
        
        for citation in citations:
            # Extract text content
            text = citation.get("text", citation.get("content", ""))
            source = citation.get("source", citation.get("document", ""))
            
            # Format as "source: text"
            if source:
                text_sources.append(f"{source}: {text}")
            else:
                text_sources.append(text)
        
        return DataPoints(text=text_sources)
