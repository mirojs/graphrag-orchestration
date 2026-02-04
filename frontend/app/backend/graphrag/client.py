"""
GraphRAG API Client

Provides async HTTP client for communicating with the GraphRAG orchestration backend.
Handles document upload, deletion, and chat queries.
"""

import logging
import json
from typing import Any, AsyncGenerator, Dict, List, Optional
from dataclasses import dataclass, field

import httpx

from .config import GraphRAGConfig

logger = logging.getLogger(__name__)


@dataclass
class GraphRAGDocument:
    """Document metadata for GraphRAG operations."""
    id: str
    title: str
    source: str  # Blob URL
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphRAGQueryResult:
    """Result from a GraphRAG query."""
    answer: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    route_used: Optional[int] = None
    confidence: Optional[float] = None
    thought_steps: List[str] = field(default_factory=list)


class GraphRAGClient:
    """
    Async HTTP client for the GraphRAG orchestration backend.
    
    Provides methods for:
    - Document upload notification (after blob upload)
    - Document deletion
    - Chat/query operations
    - Folder management
    """
    
    def __init__(self, config: GraphRAGConfig):
        """
        Initialize GraphRAG client.
        
        Args:
            config: GraphRAGConfig with backend URL and settings
        """
        self.config = config
        self.base_url = config.api_base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.config.timeout),
                headers=headers,
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    # ==================== Document Operations ====================
    
    async def notify_document_uploaded(
        self,
        group_id: str,
        document: GraphRAGDocument,
        folder_id: Optional[str] = None,
        trigger_indexing: bool = True,
    ) -> Dict[str, Any]:
        """
        Notify GraphRAG backend that a document has been uploaded to blob storage.
        
        This triggers the indexing pipeline to process the document.
        
        Args:
            group_id: Tenant/user identifier
            document: Document metadata
            folder_id: Optional folder to place document in
            trigger_indexing: If True, immediately start indexing
            
        Returns:
            Response with job_id if indexing was triggered
        """
        client = await self._get_client()
        
        payload = {
            "document_id": document.id,
            "title": document.title,
            "source": document.source,
            "metadata": document.metadata,
            "trigger_indexing": trigger_indexing,
        }
        
        if folder_id:
            payload["folder_id"] = folder_id
        
        try:
            response = await client.post(
                f"/documents/notify-upload",
                json=payload,
                headers={"X-Group-ID": group_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to notify document upload: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to notify document upload: {e}")
            raise
    
    async def delete_document(
        self,
        group_id: str,
        document_id: str,
        hard_delete: bool = False,
    ) -> Dict[str, Any]:
        """
        Delete a document from GraphRAG.
        
        Args:
            group_id: Tenant/user identifier
            document_id: Document to delete
            hard_delete: If True, permanently delete. If False, soft-delete (deprecate).
            
        Returns:
            Deletion result with statistics
        """
        client = await self._get_client()
        
        endpoint = f"/documents/{document_id}"
        if hard_delete:
            endpoint += "?hard_delete=true"
        
        try:
            response = await client.delete(
                endpoint,
                headers={"X-Group-ID": group_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to delete document: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to delete document: {e}")
            raise
    
    async def assign_document_to_folder(
        self,
        group_id: str,
        document_id: str,
        folder_id: str,
    ) -> Dict[str, Any]:
        """
        Assign a document to a folder.
        
        Args:
            group_id: Tenant/user identifier
            document_id: Document to assign
            folder_id: Target folder
            
        Returns:
            Assignment result
        """
        client = await self._get_client()
        
        try:
            response = await client.post(
                f"/folders/{folder_id}/documents",
                json={"document_id": document_id},
                headers={"X-Group-ID": group_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to assign document to folder: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to assign document to folder: {e}")
            raise
    
    # ==================== Query Operations ====================
    
    async def chat(
        self,
        group_id: str,
        messages: List[Dict[str, str]],
        route: Optional[int] = None,
        folder_id: Optional[str] = None,
        response_type: str = "detailed_report",
        force_route: Optional[str] = None,
        **kwargs,
    ) -> GraphRAGQueryResult:
        """
        Send a chat query to GraphRAG.
        
        Args:
            group_id: Tenant/user identifier
            messages: Conversation history in OpenAI format
            route: Specific route to use (2/3/4), or None for auto-routing (DEPRECATED - use force_route)
            folder_id: Optional folder to scope search to
            response_type: Type of response - "detailed_report", "summary", "audit_trail", 
                          "comprehensive", "comprehensive_sentence"
            force_route: Force specific route - "local_search", "global_search", "drift_multi_hop"
            
        Returns:
            GraphRAGQueryResult with answer and citations
        """
        client = await self._get_client()
        
        # Extract the last user message as the query
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if not user_messages:
            raise ValueError("No user message found in messages array")
        query = user_messages[-1].get("content", "")
        
        # Build payload matching backend API contract
        payload = {
            "query": query,
            "response_type": response_type,
        }
        
        # Handle routing (prefer force_route over deprecated route parameter)
        if force_route:
            payload["force_route"] = force_route
        elif route:
            # Map old numeric route to new string-based force_route
            route_map = {
                2: "local_search",
                3: "global_search",
                4: "drift_multi_hop",
            }
            if route in route_map:
                payload["force_route"] = route_map[route]
        
        if folder_id:
            payload["folder_id"] = folder_id
        
        # Merge any additional kwargs (e.g., knn_config, relevance_budget)
        payload.update(kwargs)
        
        try:
            response = await client.post(
                "/hybrid/query",
                json=payload,
                headers={"X-Group-ID": group_id},
            )
            response.raise_for_status()
            data = response.json()
            
            return GraphRAGQueryResult(
                answer=data.get("response", data.get("answer", "")),  # Backend uses "response"
                citations=data.get("citations", []),
                route_used=data.get("route_used"),
                confidence=data.get("confidence"),
                thought_steps=data.get("thought_steps", []),
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to query GraphRAG: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to query GraphRAG: {e}")
            raise
    
    async def chat_stream(
        self,
        group_id: str,
        messages: List[Dict[str, str]],
        route: Optional[int] = None,
        folder_id: Optional[str] = None,
        response_type: str = "detailed_report",
        force_route: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Send a streaming chat query to GraphRAG.
        
        Args:
            group_id: Tenant/user identifier
            messages: Conversation history in OpenAI format
            route: Specific route to use (2/3/4), or None for auto-routing (DEPRECATED - use force_route)
            folder_id: Optional folder to scope search to
            response_type: Type of response - "detailed_report", "summary", "audit_trail", 
                          "comprehensive", "comprehensive_sentence"
            force_route: Force specific route - "local_search", "global_search", "drift_multi_hop"
            
        Yields:
            Streaming response chunks
        """
        client = await self._get_client()
        
        # Extract the last user message as the query
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if not user_messages:
            raise ValueError("No user message found in messages array")
        query = user_messages[-1].get("content", "")
        
        # Build payload matching backend API contract
        payload = {
            "query": query,
            "response_type": response_type,
            "stream": True,
        }
        
        # Handle routing (prefer force_route over deprecated route parameter)
        if force_route:
            payload["force_route"] = force_route
        elif route:
            # Map old numeric route to new string-based force_route
            route_map = {
                2: "local_search",
                3: "global_search",
                4: "drift_multi_hop",
            }
            if route in route_map:
                payload["force_route"] = route_map[route]
        
        if folder_id:
            payload["folder_id"] = folder_id
        
        payload.update(kwargs)
        
        try:
            async with client.stream(
                "POST",
                "/hybrid/query",
                json=payload,
                headers={"X-Group-ID": group_id},
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            # Skip non-JSON lines (like SSE prefixes)
                            continue
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to stream from GraphRAG: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to stream from GraphRAG: {e}")
            raise
    
    # ==================== Folder Operations ====================
    
    async def list_folders(
        self,
        group_id: str,
        parent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List folders for a group.
        
        Args:
            group_id: Tenant/user identifier
            parent_id: Optional parent folder ID (None for root folders)
            
        Returns:
            List of folder metadata
        """
        client = await self._get_client()
        
        params = {}
        if parent_id:
            params["parent_id"] = parent_id
        
        try:
            response = await client.get(
                "/folders",
                params=params,
                headers={"X-Group-ID": group_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to list folders: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to list folders: {e}")
            raise
    
    async def create_folder(
        self,
        group_id: str,
        name: str,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new folder.
        
        Args:
            group_id: Tenant/user identifier
            name: Folder name
            parent_id: Optional parent folder (None for root)
            
        Returns:
            Created folder metadata
        """
        client = await self._get_client()
        
        payload = {"name": name}
        if parent_id:
            payload["parent_id"] = parent_id
        
        try:
            response = await client.post(
                "/folders",
                json=payload,
                headers={"X-Group-ID": group_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create folder: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to create folder: {e}")
            raise
    
    async def delete_folder(
        self,
        group_id: str,
        folder_id: str,
        cascade: bool = False,
    ) -> Dict[str, Any]:
        """
        Delete a folder.
        
        Args:
            group_id: Tenant/user identifier
            folder_id: Folder to delete
            cascade: If True, delete subfolders too
            
        Returns:
            Deletion result
        """
        client = await self._get_client()
        
        params = {"cascade": str(cascade).lower()}
        
        try:
            response = await client.delete(
                f"/folders/{folder_id}",
                params=params,
                headers={"X-Group-ID": group_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to delete folder: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Failed to delete folder: {e}")
            raise
    
    # ==================== Health Check ====================
    
    async def health_check(self) -> bool:
        """
        Check if GraphRAG backend is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False
