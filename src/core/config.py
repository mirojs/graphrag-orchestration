from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import Field
import logging
import os

logger = logging.getLogger(__name__)


def _load_keyvault_secrets(vault_url: str) -> dict[str, str]:
    """Load secrets from Azure Key Vault using DefaultAzureCredential.

    Key Vault secret names use hyphens (e.g. NEO4J-PASSWORD) which are
    mapped to the env-var style underscores (NEO4J_PASSWORD) that
    Pydantic BaseSettings expects.
    """
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)

        secrets: dict[str, str] = {}
        for prop in client.list_properties_of_secrets():
            if not prop.enabled:
                continue
            secret = client.get_secret(prop.name)
            if secret.value is not None:
                env_key = prop.name.replace("-", "_").upper()
                secrets[env_key] = secret.value
        logger.info("keyvault_secrets_loaded count=%d vault=%s", len(secrets), vault_url)
        return secrets
    except Exception as exc:
        logger.warning("keyvault_load_failed vault=%s error=%s", vault_url, exc)
        return {}


# If AZURE_KEY_VAULT_URL is set, pre-populate env vars from Key Vault
# so that Pydantic BaseSettings picks them up automatically.
_vault_url = os.environ.get("AZURE_KEY_VAULT_URL")
if _vault_url:
    for key, value in _load_keyvault_secrets(_vault_url).items():
        os.environ.setdefault(key, value)


class Settings(BaseSettings):
    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "GraphRAG Orchestration Service"
    
    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR")
    LOG_REQUEST_BODY: bool = Field(default=False, description="Log full request body (verbose)")
    
    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_BEARER_TOKEN: Optional[str] = None  # For local dev
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-5.1"  # Primary model for synthesis
    AZURE_OPENAI_REASONING_EFFORT: str = "medium"  # Reasoning effort for synthesis
    # Optional override only for DRIFT to allow faster model like gpt-4o-mini
    AZURE_OPENAI_DRIFT_DEPLOYMENT_NAME: Optional[str] = "gpt-5.1"
    # Indexing operations (entity/relationship extraction, RAPTOR clustering)
    AZURE_OPENAI_INDEXING_DEPLOYMENT: Optional[str] = "gpt-4.1"
    # Query routing (intent classification: Vector vs Graph vs RAPTOR)
    AZURE_OPENAI_ROUTING_DEPLOYMENT: Optional[str] = "gpt-4o-mini"
    AZURE_OPENAI_ROUTING_REASONING_EFFORT: str = "medium"  # Reasoning effort for routing
    
    # ========================================================================
    # Hybrid Pipeline Model Selection (LazyGraphRAG + HippoRAG 2)
    # See ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md Section 8.2 for rationale
    # ========================================================================
    # Router: Query classification (simple vs complex vs ambiguous)
    HYBRID_ROUTER_MODEL: str = "gpt-4o-mini"  # Fast, low cost, sufficient for classification
    # Route 2: Entity extraction (NER) - needs high precision
    HYBRID_NER_MODEL: str = "gpt-5.1"  # High precision for seed entity identification
    # Route 2/3: Final answer synthesis - best available model
    HYBRID_SYNTHESIS_MODEL: str = "gpt-4.1"  # Less verbose, higher benchmark score than gpt-5.1
    # Route 3: Query decomposition - needs strong reasoning
    HYBRID_DECOMPOSITION_MODEL: str = "gpt-4.1"  # Strong reasoning for breaking down ambiguity
    # Route 3: Sub-question intermediate synthesis
    HYBRID_INTERMEDIATE_MODEL: str = "gpt-5.1"  # Good balance of speed/quality
    AZURE_OPENAI_MODEL_VERSION: str = "2025-11-13"  # gpt-5.1 (2025-11-13)
    
    # Embeddings — V1 Legacy (DEPRECATED — no longer initialized, kept for reference only)
    # All embeddings now use Voyage voyage-context-3 (see below).
    AZURE_OPENAI_EMBEDDING_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_EMBEDDING_API_KEY: Optional[str] = None
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-large"  # DEPRECATED
    AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = 3072  # DEPRECATED
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"  # Latest stable version
    
    # ========================================================================
    # Voyage AI V2 Embeddings (Section-Aware Contextual Chunking)
    # See VOYAGE_V2_CONTEXTUAL_CHUNKING_PLAN_2026-01-25.md for rationale
    # Docs: https://docs.voyageai.com/docs/contextualized-chunk-embeddings
    # ========================================================================
    VOYAGE_API_KEY: Optional[str] = None
    VOYAGE_V2_ENABLED: bool = True  # Legacy flag — always True (Voyage is the only embedder since Feb 14 2026)
    VOYAGE_MODEL_NAME: str = "voyage-context-3"  # Contextual embedding model
    VOYAGE_EMBEDDING_DIM: int = 2048  # voyage-context-3 with output_dimension=2048
    VOYAGE_V2_SIMILARITY_THRESHOLD: float = 0.87  # SIMILAR_TO edge threshold (raised from 0.85 for V2)
    
    # ========================================================================
    # Skeleton Sentence Enrichment (Strategy A)
    # See ARCHITECTURE_HYBRID_SKELETON_2026-02-11.md for design
    # Extracts sentence-level nodes from chunks, embeds with Voyage, stores in Neo4j.
    # Route 2 queries the sentence index and injects top-k matches as supplementary
    # evidence into the synthesis prompt.  Benchmark: +289% F1, +36% containment.
    # ========================================================================
    SKELETON_ENRICHMENT_ENABLED: bool = True  # Master switch for sentence extraction + injection
    SKELETON_SENTENCE_TOP_K: int = 8  # Top-k sentence matches to inject into Route 2 prompt
    SKELETON_SIMILARITY_THRESHOLD: float = 0.45  # Min cosine similarity for sentence retrieval
    SKELETON_MIN_SENTENCE_CHARS: int = 20  # Minimum characters for a valid sentence (lowered from 30 — was dropping informative KVP lines like "Phone: (813) 902-4455")
    SKELETON_MIN_SENTENCE_WORDS: int = 2  # Minimum words for a valid sentence (lowered from 3 — was dropping 2-word KVP lines like "Email: user@example.com")
    SKELETON_LLM_SENTENCE_REVIEW: bool = True  # Enable bundled LLM post-review of sentence boundaries (gpt-4.1, zero-risk verified)
    
    # Phase 2: Sparse sentence-to-sentence RELATED_TO edges
    # Separate from GDS KNN (Entity/Figure/KVP/Chunk). Bounded: threshold 0.86, max k=2.
    # Only cross-chunk pairs (same-chunk sentences already linked via NEXT edges).
    # See ARCHITECTURE_HYBRID_SKELETON_2026-02-11.md Phase 2.
    # 2026-03-01: Lowered from 0.90→0.86. At 0.90, 26% of sentences were KNN-isolated
    # (zero SEMANTICALLY_SIMILAR edges) because their best non-adjacent match fell below
    # threshold. With max_k=2 the graph stays sparse (+59 edges, 120→179 total).
    # Isolated drops from 67 (31%) to 15 (7%). All new edges are same-document.
    SKELETON_KNN_THRESHOLD: float = 0.86  # Min cosine similarity for sentence RELATED_TO edges
    SKELETON_KNN_MAX_K: int = 2  # Max RELATED_TO edges per sentence (keeps graph sparse)
    
    # Strategy B: Graph traversal retrieval (replaces flat vector search with graph expansion)
    # When enabled, Stage 2.2.6 traverses RELATED_TO + NEXT edges from seed sentences
    # to discover coherent multi-sentence clusters across chunks/documents.
    SKELETON_GRAPH_TRAVERSAL_ENABLED: bool = True  # Use graph traversal (B) instead of flat search (A)
    SKELETON_TRAVERSAL_NEXT_HOPS: int = 1  # NEXT/PREV expansion window (sentences in each direction)
    SKELETON_TRAVERSAL_RELATED_HOPS: int = 1  # Max RELATED_TO hops from seed sentence

    # Synthesis model override for Route 2 skeleton path.
    # Sentence-level context is precise (answer at rank #1), so a smaller/faster model
    # can extract answers without the reasoning overhead of gpt-5.1.
    # Empty string = use HYBRID_SYNTHESIS_MODEL (default, no override).
    # Recommended: "gpt-4.1-mini" for ~3x speed, ~10x cost reduction on extraction tasks.
    SKELETON_SYNTHESIS_MODEL: str = "gpt-4.1-mini"  # Override synthesis model when skeleton enrichment is active
    
    # ========================================================================
    # Algorithm Version Control
    # See ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md Section 26 for details
    # ========================================================================
    DEFAULT_ALGORITHM_VERSION: str = "v2"  # Default when client doesn't specify
    ALGORITHM_V1_ENABLED: bool = True   # Deprecated but available for backward compat
    ALGORITHM_V2_ENABLED: bool = True   # Current stable version
    ALGORITHM_V3_PREVIEW_ENABLED: bool = False  # Preview/beta features
    ALGORITHM_V3_CANARY_PERCENT: int = 0  # Canary rollout percentage (0-100)
    
    # Preview Worker (for testing v3 before production)
    # When set, X-Algorithm-Version: v3 requests route to this worker
    # Set to "http://graphrag-worker-preview" when preview worker is deployed
    WORKER_PREVIEW_URL: Optional[str] = None  # None = use same process (no HTTP routing)
    
    # Admin API Key (for version management endpoints)
    ADMIN_API_KEY: Optional[str] = None  # Set to enable /admin/* endpoints
    
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
    
    # Aura Graph Analytics (serverless GDS)
    # Required for KNN, Louvain, PageRank on AuraDB Professional
    # Get from Aura Console > API Credentials
    AURA_DS_CLIENT_ID: Optional[str] = None
    AURA_DS_CLIENT_SECRET: Optional[str] = None
    
    # Local graph algorithms threshold: when entity count is below this value,
    # run KNN/Louvain/PageRank in-process (numpy + networkx) instead of
    # provisioning an Aura GDS session. Eliminates 60-120s GDS overhead for
    # small graphs. Set to 0 to always use GDS sessions.
    GDS_LOCAL_THRESHOLD: int = 2000
    
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
    AZURE_DI_TIMEOUT: int = 120  # Per-document timeout in seconds (increase if DI is slow)
    
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
    
    # Azure Translator (query translation for multilingual chat)
    AZURE_TRANSLATOR_ENDPOINT: Optional[str] = None
    AZURE_TRANSLATOR_REGION: str = "swedencentral"

    # Azure Key Vault (optional — secrets auto-loaded at module import when set)
    AZURE_KEY_VAULT_URL: Optional[str] = None

    # Authentication & Security
    AUTH_TYPE: str = "B2B"  # B2B (Azure AD with groups) or B2C (Azure AD B2C with oid)
    REQUIRE_AUTH: bool = True  # Fail closed. Set to False for local dev without Easy Auth.
    ALLOW_LEGACY_GROUP_HEADER: bool = False  # Allow X-Group-ID header (deprecated, only for local dev)
    GROUP_ID_OVERRIDE: Optional[str] = Field(default=None)  # Optional fixed group_id override for auth testing
    GLOBAL_GROUP_ID: str = "__global__"  # Sentinel group_id for shared/public documents
    
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
        extra = "ignore"

settings = Settings()


def build_group_ids(group_id: str) -> List[str]:
    """Build two-tier group ID list: [user_group, global_group].

    Deduplicates when group_id IS the global group to avoid duplicate
    entries in Cypher IN-list queries.
    """
    g = settings.GLOBAL_GROUP_ID
    return [group_id, g] if group_id != g else [g]
