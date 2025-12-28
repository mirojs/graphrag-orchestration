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
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-5-2"  # Primary model for synthesis (GPT-5.2)
    AZURE_OPENAI_REASONING_EFFORT: str = "medium"  # Reasoning effort for synthesis
    # Optional override only for DRIFT to allow faster model like gpt-4o-mini
    AZURE_OPENAI_DRIFT_DEPLOYMENT_NAME: Optional[str] = "gpt-5-2"
    # Indexing operations (entity/relationship extraction, RAPTOR clustering)
    AZURE_OPENAI_INDEXING_DEPLOYMENT: Optional[str] = "gpt-4.1"  # Will use gpt-4.1 when deployed
    # Query routing (intent classification: Vector vs Graph vs RAPTOR)
    AZURE_OPENAI_ROUTING_DEPLOYMENT: Optional[str] = "o4-mini"  # Will use o4-mini when deployed
    AZURE_OPENAI_ROUTING_REASONING_EFFORT: str = "medium"  # Reasoning effort for routing
    AZURE_OPENAI_MODEL_VERSION: str = "2024-11-20"  # gpt-4o (2024-11-20)
    
    # Embeddings (Switzerland North - Separate resource)
    AZURE_OPENAI_EMBEDDING_ENDPOINT: Optional[str] = None  # Switzerland North endpoint
    AZURE_OPENAI_EMBEDDING_API_KEY: Optional[str] = None  # Separate key for embedding resource
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = 1536  # text-embedding-3-small dimensions
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"  # Latest stable version
    
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

    # Determinism: extraction caching (Neo4j-backed)
    GRAPHRAG_ENABLE_EXTRACTION_CACHE: bool = Field(default=False)
    GRAPHRAG_EXTRACTION_CACHE_VERSION: str = Field(default="v1")
    
    # Multi-tenancy
    ENABLE_GROUP_ISOLATION: bool = True
    
    # Performance & Rate Limiting
    # Set to 1 for serial processing (10K TPM), 4 for parallel (50K+ TPM)
    GRAPHRAG_NUM_WORKERS: int = 1
    
    # Community Detection (GraphRAG Global Search)
    GRAPHRAG_MAX_CLUSTER_SIZE: int = 10  # Max nodes per community cluster

    # DRIFT debugging
    # If true, DRIFT will fall back to a simpler retrieval path when the graph is
    # missing prerequisites (e.g., communities/relationships). Keep false in prod.
    V3_DRIFT_DEBUG_FALLBACK: bool = Field(default=False)
    
    # DRIFT detailed logging for debugging text unit retrieval, sources, and chunk content
    # Enable to trace text unit loading, chunk content, and source extraction
    # Note: Can be verbose; use only for specific groups with V3_DRIFT_DEBUG_GROUP_ID
    V3_DRIFT_DEBUG_LOGGING: bool = Field(default=False)
    
    # Specific group ID to trace DRIFT processing (only logs for this group when V3_DRIFT_DEBUG_LOGGING=true)
    # Example: "drift-ok-1766862426"
    V3_DRIFT_DEBUG_GROUP_ID: Optional[str] = Field(default=None)

    # When enabled (and debug group matches), scan loaded text units + extracted sources
    # for key phrases/timeframe patterns to debug missing grounding.
    V3_DRIFT_DEBUG_TERM_SCAN: bool = Field(default=False)

    # DRIFT prompt guardrails
    # GraphRAG may pass very large history/context messages (especially during reduce).
    # These caps bound how much history we serialize into a single prompt.
    V3_DRIFT_MAX_HISTORY_CHARS: int = Field(default=120_000)
    V3_DRIFT_MAX_HISTORY_MESSAGE_CHARS: int = Field(default=40_000)
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
