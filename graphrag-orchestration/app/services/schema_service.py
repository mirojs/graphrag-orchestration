"""
Schema Service for fetching schemas from Content Understanding Schema Vault.

Connects to the existing Cosmos DB Schema Vault collection to retrieve
schemas for GraphRAG indexing.
"""

from typing import Optional, Dict, Any, List
import logging
import os

logger = logging.getLogger(__name__)


class SchemaService:
    """
    Service for fetching schemas from Content Understanding Schema Vault.
    
    Connects to the same Cosmos DB used by ContentProcessorAPI to access
    the schemas collection.
    """
    
    def __init__(self):
        """Initialize connection to Cosmos DB Schema Vault."""
        self._cosmos_client = None
        self._database = None
        self._container = None
        self._initialize_cosmos()
    
    def _initialize_cosmos(self):
        """Set up Cosmos DB connection."""
        try:
            from azure.cosmos import CosmosClient
            from azure.identity import DefaultAzureCredential
            
            cosmos_endpoint = os.getenv("COSMOS_ENDPOINT")
            cosmos_key = os.getenv("COSMOS_KEY")
            database_name = os.getenv("COSMOS_DATABASE_NAME", "content-processor")
            
            if not cosmos_endpoint:
                logger.warning("COSMOS_ENDPOINT not configured, schema fetching disabled")
                return
            
            # Use managed identity or API key
            if cosmos_key:
                self._cosmos_client = CosmosClient(cosmos_endpoint, credential=cosmos_key)
            else:
                credential = DefaultAzureCredential()
                self._cosmos_client = CosmosClient(cosmos_endpoint, credential=credential)
            
            self._database = self._cosmos_client.get_database_client(database_name)
            self._container = self._database.get_container_client("schemas")
            
            logger.info(f"Connected to Cosmos DB schema vault: {database_name}/schemas")
            
        except Exception as e:
            logger.error(f"Failed to initialize Cosmos DB connection: {e}")
            self._cosmos_client = None
    
    def get_schema(self, schema_id: str, group_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a schema by ID for a specific group.
        
        Args:
            schema_id: Unique schema identifier
            group_id: Tenant group ID for isolation
            
        Returns:
            Schema document or None if not found
        """
        if not self._container:
            raise RuntimeError("Cosmos DB not initialized")
        
        try:
            # Query with partition key for multi-tenancy
            query = """
                SELECT * FROM c 
                WHERE c.id = @schema_id 
                AND c.group_id = @group_id
            """
            
            items = list(self._container.query_items(
                query=query,
                parameters=[
                    {"name": "@schema_id", "value": schema_id},
                    {"name": "@group_id", "value": group_id}
                ],
                partition_key=group_id,
                enable_cross_partition_query=False
            ))
            
            if not items:
                logger.warning(f"Schema not found: {schema_id} for group {group_id}")
                return None
            
            schema_doc = items[0]
            logger.info(f"Fetched schema: {schema_doc.get('name', schema_id)}")
            return schema_doc
            
        except Exception as e:
            logger.error(f"Failed to fetch schema {schema_id}: {e}")
            return None
    
    def list_schemas(self, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List all schemas for a group.
        
        Args:
            group_id: Tenant group ID
            limit: Maximum number of schemas to return
            
        Returns:
            List of schema documents
        """
        if not self._container:
            raise RuntimeError("Cosmos DB not initialized")
        
        try:
            query = """
                SELECT c.id, c.name, c.description, c.created_at, c.group_id
                FROM c 
                WHERE c.group_id = @group_id
                ORDER BY c.created_at DESC
                OFFSET 0 LIMIT @limit
            """
            
            items = list(self._container.query_items(
                query=query,
                parameters=[
                    {"name": "@group_id", "value": group_id},
                    {"name": "@limit", "value": limit}
                ],
                partition_key=group_id,
                enable_cross_partition_query=False
            ))
            
            logger.info(f"Listed {len(items)} schemas for group {group_id}")
            return items
            
        except Exception as e:
            logger.error(f"Failed to list schemas: {e}")
            return []
    
    def extract_json_schema(self, schema_doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract the JSON Schema portion from a schema document.
        
        Schema documents in Cosmos have metadata wrapper. This extracts
        just the JSON Schema portion needed for conversion.
        
        Args:
            schema_doc: Full schema document from Cosmos DB
            
        Returns:
            JSON Schema object
        """
        # Schema Vault stores the schema in 'schema' or 'schema_json' field
        json_schema = schema_doc.get("schema") or schema_doc.get("schema_json")
        
        if not json_schema:
            # Fallback: treat the whole document as schema if no wrapper
            logger.warning(f"No 'schema' field found, using full document")
            json_schema = {
                "type": "object",
                "properties": schema_doc.get("properties", {}),
                "title": schema_doc.get("name", "Unknown")
            }
        
        return json_schema
