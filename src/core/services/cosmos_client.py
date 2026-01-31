"""Cosmos DB client for chat history and usage tracking."""

from typing import List, Optional, Dict, Any
import os
import structlog
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey
from azure.identity.aio import DefaultAzureCredential

from src.core.models.usage import UsageRecord
from src.core.models.chat import ChatSession

logger = structlog.get_logger(__name__)


class CosmosDBClient:
    """Async Cosmos DB client for GraphRAG."""
    
    def __init__(self):
        """Initialize Cosmos DB client."""
        self.endpoint = os.getenv("COSMOS_DB_ENDPOINT")
        self.database_name = os.getenv("COSMOS_DB_DATABASE_NAME", "graphrag")
        self.chat_container_name = os.getenv("COSMOS_DB_CHAT_HISTORY_CONTAINER", "chat_history")
        self.usage_container_name = os.getenv("COSMOS_DB_USAGE_CONTAINER", "usage")
        
        self._client: Optional[CosmosClient] = None
        self._credential: Optional[DefaultAzureCredential] = None
        self._database = None
        self._chat_container = None
        self._usage_container = None
        
        if not self.endpoint:
            logger.warning("cosmos_db_not_configured", reason="COSMOS_DB_ENDPOINT not set")
    
    async def initialize(self) -> None:
        """Initialize Cosmos DB connection."""
        if not self.endpoint:
            logger.warning("cosmos_db_initialization_skipped", reason="No endpoint configured")
            return
        
        try:
            # Use managed identity for authentication
            self._credential = DefaultAzureCredential()
            self._client = CosmosClient(self.endpoint, credential=self._credential)
            
            # Get database and containers
            if self._client:
                self._database = self._client.get_database_client(self.database_name)
                self._chat_container = self._database.get_container_client(self.chat_container_name)
                self._usage_container = self._database.get_container_client(self.usage_container_name)
            
            logger.info("cosmos_db_initialized",
                       endpoint=self.endpoint,
                       database=self.database_name)
        except Exception as e:
            logger.error("cosmos_db_init_failed", error=str(e))
            raise
    
    async def close(self) -> None:
        """Close Cosmos DB connection."""
        if self._client:
            await self._client.close()
        if self._credential:
            await self._credential.close()
    
    # ========================================================================
    # Usage Tracking Methods
    # ========================================================================
    
    async def write_usage_record(self, record: UsageRecord) -> None:
        """Write a single usage record to Cosmos DB."""
        if not self._usage_container:
            logger.warning("usage_write_skipped", reason="Cosmos not initialized")
            return
        
        try:
            await self._usage_container.upsert_item(record.model_dump(mode="json"))
            logger.debug("usage_record_written", 
                        partition_id=record.partition_id,
                        usage_type=record.usage_type)
        except Exception as e:
            logger.warning("usage_write_failed", error=str(e), record_id=record.id)
            # Don't raise - fire-and-forget pattern
    
    async def write_usage_batch(self, records: List[UsageRecord]) -> None:
        """Write multiple usage records in batch."""
        if not self._usage_container:
            logger.warning("usage_batch_write_skipped", reason="Cosmos not initialized")
            return
        
        try:
            for record in records:
                await self.write_usage_record(record)
            logger.info("usage_batch_written", count=len(records))
        except Exception as e:
            logger.warning("usage_batch_write_failed", error=str(e), count=len(records))
    
    async def query_usage(
        self,
        partition_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        usage_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query usage records by partition and time range."""
        if not self._usage_container:
            logger.warning("usage_query_skipped", reason="Cosmos not initialized")
            return []
        
        try:
            query = "SELECT * FROM c WHERE c.partition_id = @partition_id"
            parameters = [{"name": "@partition_id", "value": partition_id}]
            
            if start_time:
                query += " AND c.timestamp >= @start_time"
                parameters.append({"name": "@start_time", "value": start_time})
            
            if end_time:
                query += " AND c.timestamp <= @end_time"
                parameters.append({"name": "@end_time", "value": end_time})
            
            if usage_type:
                query += " AND c.usage_type = @usage_type"
                parameters.append({"name": "@usage_type", "value": usage_type})
            
            items = []
            async for item in self._usage_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=partition_id
            ):
                items.append(item)
            
            return items
        except Exception as e:
            logger.error("usage_query_failed", error=str(e), partition_id=partition_id)
            return []
    
    # ========================================================================
    # Chat History Methods
    # ========================================================================
    
    async def write_chat_session(self, session: ChatSession) -> None:
        """Write or update a chat session."""
        if not self._chat_container:
            logger.warning("chat_write_skipped", reason="Cosmos not initialized")
            return
        
        try:
            await self._chat_container.upsert_item(session.model_dump(mode="json"))
            logger.debug("chat_session_written",
                        user_id=session.user_id,
                        conversation_id=session.conversation_id)
        except Exception as e:
            logger.warning("chat_write_failed", error=str(e), session_id=session.id)
    
    async def get_chat_session(
        self,
        user_id: str,
        conversation_id: str
    ) -> Optional[ChatSession]:
        """Retrieve a chat session by user and conversation ID."""
        if not self._chat_container:
            logger.warning("chat_read_skipped", reason="Cosmos not initialized")
            return None
        
        try:
            query = """
                SELECT * FROM c 
                WHERE c.user_id = @user_id 
                AND c.conversation_id = @conversation_id
            """
            parameters = [
                {"name": "@user_id", "value": user_id},
                {"name": "@conversation_id", "value": conversation_id}
            ]
            
            items = []
            async for item in self._chat_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=user_id
            ):
                items.append(item)
            
            if items:
                return ChatSession(**items[0])
            return None
        except Exception as e:
            logger.error("chat_read_failed", error=str(e), user_id=user_id)
            return None
    
    async def list_chat_sessions(self, user_id: str, limit: int = 20) -> List[ChatSession]:
        """List recent chat sessions for a user."""
        if not self._chat_container:
            logger.warning("chat_list_skipped", reason="Cosmos not initialized")
            return []
        
        try:
            query = f"""
                SELECT * FROM c 
                WHERE c.user_id = @user_id 
                ORDER BY c.updated_at DESC
                OFFSET 0 LIMIT {limit}
            """
            parameters = [{"name": "@user_id", "value": user_id}]
            
            sessions = []
            async for item in self._chat_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=user_id
            ):
                sessions.append(ChatSession(**item))
            
            return sessions
        except Exception as e:
            logger.error("chat_list_failed", error=str(e), user_id=user_id)
            return []


# Singleton instance
_cosmos_client: Optional[CosmosDBClient] = None


def get_cosmos_client() -> CosmosDBClient:
    """Get or create the singleton Cosmos DB client."""
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosDBClient()
    return _cosmos_client
