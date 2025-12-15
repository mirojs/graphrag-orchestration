from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "GraphRAG Orchestration Service"
    
    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_BEARER_TOKEN: Optional[str] = None  # For local dev
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-4o"
    # Optional override only for DRIFT to allow faster model like gpt-4o-mini
    AZURE_OPENAI_DRIFT_DEPLOYMENT_NAME: Optional[str] = None
    AZURE_OPENAI_MODEL_VERSION: str = "2024-11-20"  # gpt-4o (2024-11-20)
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-large"
    AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = 3072  # High precision for RAPTOR
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"  # Data Zone Standard max supported version
    
    # Vector Store for RAPTOR nodes
    # Options: azure_search (recommended for RAPTOR), lancedb (local dev), neo4j (legacy)
    # Note: Neo4j is still used for entity/relationship storage and hybrid search on KG
    VECTOR_STORE_TYPE: str = "azure_search"
    LANCEDB_PATH: str = "/app/data/lancedb"
    AZURE_SEARCH_ENDPOINT: Optional[str] = None
    AZURE_SEARCH_API_KEY: Optional[str] = None
    AZURE_SEARCH_INDEX_NAME: str = "graphrag-raptor"
    
    # Graph Store (Neo4j)
    NEO4J_URI: Optional[str] = None
    NEO4J_USERNAME: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: Optional[str] = None
    AURA_INSTANCEID: Optional[str] = None
    AURA_INSTANCENAME: Optional[str] = None
    
    # Cosmos DB (Schema Vault)
    COSMOS_ENDPOINT: Optional[str] = None
    COSMOS_KEY: Optional[str] = None
    COSMOS_DATABASE_NAME: str = "content-processor"
    
    # Azure Content Understanding (for ingestion) - DEPRECATED, use Document Intelligence
    AZURE_CONTENT_UNDERSTANDING_ENDPOINT: Optional[str] = None
    AZURE_CONTENT_UNDERSTANDING_API_KEY: Optional[str] = None
    AZURE_CU_API_VERSION: str = "2025-11-01"
    
    # Azure Document Intelligence (recommended for layout extraction)
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: Optional[str] = None
    AZURE_DOCUMENT_INTELLIGENCE_KEY: Optional[str] = None
    AZURE_DOC_INTELLIGENCE_API_VERSION: str = "2024-11-30"
    
    # LlamaParse (for layout-aware document parsing)
    LLAMA_CLOUD_API_KEY: Optional[str] = None
    
    # GraphRAG Data Directories
    GRAPHRAG_DATA_DIR: str = "/app/data/graphrag"
    GRAPHRAG_CACHE_DIR: str = "/app/data/cache"
    
    # Multi-tenancy
    ENABLE_GROUP_ISOLATION: bool = True
    
    # Performance & Rate Limiting
    # Set to 1 for serial processing (10K TPM), 4 for parallel (50K+ TPM)
    GRAPHRAG_NUM_WORKERS: int = 1
    
    # Community Detection (GraphRAG Global Search)
    GRAPHRAG_MAX_CLUSTER_SIZE: int = 10  # Max nodes per community cluster
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
