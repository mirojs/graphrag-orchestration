"""
LLM Service for Azure OpenAI integration.

Provides a centralized LLM and Embedding service for all GraphRAG operations.
"""

from typing import Optional, Dict, Any, Callable
import logging
import os

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """
    Singleton service for LLM and Embedding operations.
    
    Configures LlamaIndex to use Azure OpenAI for all operations.
    """
    
    _instance: Optional["LLMService"] = None
    _llm: Optional[Any] = None  # AzureOpenAI when initialized
    _embed_model: Optional[Any] = None  # AzureOpenAIEmbedding when initialized

    def __new__(cls) -> "LLMService":
        if cls._instance is None:
            cls._instance = super(LLMService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    @property
    def config(self) -> Dict[str, Any]:
        """Get the current configuration for health checks."""
        return {
            "AZURE_OPENAI_DEPLOYMENT_NAME": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            "AZURE_OPENAI_ENDPOINT": settings.AZURE_OPENAI_ENDPOINT,
        }

    def _initialize(self) -> None:
        """Initialize Azure OpenAI LLM and Embedding models."""
        if not settings.AZURE_OPENAI_ENDPOINT:
            logger.warning("Azure OpenAI endpoint not configured, LLM features disabled")
            return
            
        try:
            from llama_index.llms.azure_openai import AzureOpenAI
            from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
            from llama_index.core import Settings as LlamaSettings
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            
            # Monkey-patch llama_index to support gpt-5.2 (our deployment name is gpt-5-2)
            # Need to patch multiple validation lists for both LLM and embedding operations
            try:
                # Patch context size mapping
                from llama_index.llms.openai import utils as openai_utils
                if hasattr(openai_utils, 'modelname_to_contextsize'):
                    openai_utils.modelname_to_contextsize["gpt-5.2"] = 128000
                    logger.info("✅ Patched modelname_to_contextsize for gpt-5.2")
                
                # Patch ALL_AVAILABLE_MODELS if it exists (can be dict or tuple)
                if hasattr(openai_utils, 'ALL_AVAILABLE_MODELS'):
                    if "gpt-5.2" not in openai_utils.ALL_AVAILABLE_MODELS:
                        if isinstance(openai_utils.ALL_AVAILABLE_MODELS, dict):
                            openai_utils.ALL_AVAILABLE_MODELS["gpt-5.2"] = True
                        else:
                            openai_utils.ALL_AVAILABLE_MODELS = openai_utils.ALL_AVAILABLE_MODELS + ("gpt-5.2",)
                        logger.info("✅ Patched ALL_AVAILABLE_MODELS for gpt-5.2")
                
                # Patch CHAT_MODELS if it exists (can be dict or tuple)
                if hasattr(openai_utils, 'CHAT_MODELS'):
                    if "gpt-5.2" not in openai_utils.CHAT_MODELS:
                        if isinstance(openai_utils.CHAT_MODELS, dict):
                            openai_utils.CHAT_MODELS["gpt-5.2"] = True
                        else:
                            openai_utils.CHAT_MODELS = openai_utils.CHAT_MODELS + ("gpt-5.2",)
                        logger.info("✅ Patched CHAT_MODELS for gpt-5.2")
                        
            except (ImportError, AttributeError) as e:
                logger.warning(f"⚠️ Could not patch gpt-5.2 support: {e}. Using gpt-4o as fallback.")
                # Fallback: use gpt-4o deployment instead
                settings.AZURE_OPENAI_DEPLOYMENT_NAME = "gpt-4o"
            
            # Use Azure AD authentication if no API key is provided
            if not settings.AZURE_OPENAI_API_KEY:
                logger.info("Using Azure AD authentication for OpenAI")
                env_token = os.getenv("AZURE_OPENAI_BEARER_TOKEN")
                token_provider: Callable[[], str]
                if env_token:
                    logger.info("Using static bearer token from AZURE_OPENAI_BEARER_TOKEN for OpenAI (dev-only)")
                    def token_provider() -> str:
                        return env_token
                else:
                    logger.info("Initializing DefaultAzureCredential for managed identity")
                    credential = DefaultAzureCredential()
                    token_provider = get_bearer_token_provider(
                        credential,
                        "https://cognitiveservices.azure.com/.default"
                    )
                    logger.info("Token provider created successfully")
                
                # Initialize LLM with token provider
                try:
                    logger.info(f"Creating AzureOpenAI LLM with endpoint: {settings.AZURE_OPENAI_ENDPOINT}")
                    
                    # Map deployment name to model name for validation
                    # Deployment "gpt-5-2" maps to model "gpt-5.2" for validation (replace last hyphen only)
                    deployment_name = settings.AZURE_OPENAI_DEPLOYMENT_NAME
                    if "-" in deployment_name:
                        parts = deployment_name.rsplit("-", 1)
                        model_name = f"{parts[0]}.{parts[1]}"
                    else:
                        model_name = deployment_name
                    
                    # Configure reasoning effort if applicable (o1/o3/o4 models)
                    llm_kwargs = {
                        "engine": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                        "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
                        "api_version": settings.AZURE_OPENAI_API_VERSION,
                        "use_azure_ad": True,
                        "azure_ad_token_provider": token_provider,
                        "temperature": 0.0,  # Deterministic outputs for repeatability
                    }
                    
                    # Add reasoning_effort for o-series models
                    if settings.AZURE_OPENAI_DEPLOYMENT_NAME.startswith(("o1", "o3", "o4")):
                        llm_kwargs["additional_kwargs"] = {
                            "reasoning_effort": settings.AZURE_OPENAI_REASONING_EFFORT
                        }
                        logger.info(f"Using reasoning_effort={settings.AZURE_OPENAI_REASONING_EFFORT} for {settings.AZURE_OPENAI_DEPLOYMENT_NAME}")

                    self._llm = AzureOpenAI(**llm_kwargs)
                    logger.info("LLM initialized successfully with managed identity")
                except Exception as e:
                    logger.error(f"Failed to initialize LLM: {e}")
                    raise
                
                # Initialize Embedding Model with token provider
                try:
                    logger.info("Initializing embedding model with managed identity...")
                    logger.info(f"Embedding deployment: {settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT}")
                    logger.info(f"Embedding dimensions: {settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS}")
                    
                    # Use separate endpoint for embeddings if configured (Switzerland North)
                    embedding_endpoint = settings.AZURE_OPENAI_EMBEDDING_ENDPOINT or settings.AZURE_OPENAI_ENDPOINT
                    embedding_token_provider = token_provider
                    
                    logger.info(f"Embedding endpoint: {embedding_endpoint}")
                    
                    # If using separate embedding endpoint, create new token provider
                    if settings.AZURE_OPENAI_EMBEDDING_ENDPOINT and settings.AZURE_OPENAI_EMBEDDING_ENDPOINT != settings.AZURE_OPENAI_ENDPOINT:
                        logger.info(f"Using separate embedding endpoint: {settings.AZURE_OPENAI_EMBEDDING_ENDPOINT}")
                        if not settings.AZURE_OPENAI_EMBEDDING_API_KEY:
                            embedding_credential = DefaultAzureCredential()
                            embedding_token_provider = get_bearer_token_provider(
                                embedding_credential,
                                "https://cognitiveservices.azure.com/.default"
                            )
                    
                    # LlamaIndex's AzureOpenAIEmbedding + AAD can incorrectly behave as if the token is an api-key.
                    # Use the official OpenAI Azure client with `azure_ad_token_provider` instead.
                    from app.services.azure_ad_openai_embedding import AzureADOpenAIEmbedding

                    logger.info("Creating AzureADOpenAIEmbedding instance...")
                    self._embed_model = AzureADOpenAIEmbedding(
                        deployment_name=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                        azure_endpoint=embedding_endpoint,
                        api_version=settings.AZURE_OPENAI_API_VERSION,
                        azure_ad_token_provider=embedding_token_provider,
                        # Keep dimensions unset by default; text-embedding-3-small defaults to 1536.
                        dimensions=None,
                    )
                    logger.info(f"✅ Embedding model initialized successfully: {settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT}")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize embedding model: {e}", exc_info=True)
                    logger.error(f"Embedding config: deployment={settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT}, endpoint={embedding_endpoint}")
                    raise
            else:
                logger.info("Using API key authentication for OpenAI")
                # Initialize LLM with API key
                self._llm = AzureOpenAI(
                    engine=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                    api_key=settings.AZURE_OPENAI_API_KEY,
                    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                    api_version=settings.AZURE_OPENAI_API_VERSION,
                    temperature=0.0,  # Deterministic outputs for repeatability
                )
                
                # Initialize Embedding Model with API key
                # Only pass dimensions if using embedding-3 models (ada-002 doesn't support it)
                embed_kwargs = {
                    "engine": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                    "api_key": settings.AZURE_OPENAI_API_KEY,
                    "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
                    "api_version": settings.AZURE_OPENAI_API_VERSION,
                }
                # text-embedding-3-* models support dimensions parameter, ada-002 does not
                if "embedding-3" in settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT:
                    embed_kwargs["dimensions"] = settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS
                
                self._embed_model = AzureOpenAIEmbedding(**embed_kwargs)
            
            # Configure LlamaIndex global settings
            LlamaSettings.llm = self._llm
            LlamaSettings.embed_model = self._embed_model
            
            logger.info(
                f"Initialized Azure OpenAI: LLM={settings.AZURE_OPENAI_DEPLOYMENT_NAME}, "
                f"Embeddings={settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT}"
            )
        except ImportError as e:
            logger.error(f"LlamaIndex Azure OpenAI packages not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI: {e}", exc_info=True)
            raise

    @property
    def llm(self) -> Optional[Any]:
        """Get the LLM instance."""
        return self._llm

    @property
    def embed_model(self) -> Optional[Any]:
        """Get the Embedding model instance."""
        return self._embed_model
    
    def get_routing_llm(self) -> Any:
        """Get the specialized routing LLM (o4-mini)."""
        deployment = settings.AZURE_OPENAI_ROUTING_DEPLOYMENT or "o4-mini"
        effort = settings.AZURE_OPENAI_ROUTING_REASONING_EFFORT or "medium"
        return self._create_llm_client(deployment, reasoning_effort=effort)

    def get_indexing_llm(self) -> Any:
        """Get the specialized indexing LLM (GPT-4.1)."""
        deployment = settings.AZURE_OPENAI_INDEXING_DEPLOYMENT or "gpt-4.1"
        return self._create_llm_client(deployment)

    def _create_llm_client(self, deployment_name: str, reasoning_effort: Optional[str] = None) -> Any:
        """Helper to create LLM instance with correct auth and settings."""
        from llama_index.llms.azure_openai import AzureOpenAI
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        
        # Auth logic (simplified from _initialize)
        if not settings.AZURE_OPENAI_API_KEY:
            env_token = os.getenv("AZURE_OPENAI_BEARER_TOKEN")
            if env_token:
                def token_provider() -> str:
                    return env_token
            else:
                credential = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(
                    credential, "https://cognitiveservices.azure.com/.default"
                )
            
            llm_kwargs = {
                "engine": deployment_name,
                "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
                "api_version": settings.AZURE_OPENAI_API_VERSION,
                "use_azure_ad": True,
                "azure_ad_token_provider": token_provider,
            }
        else:
            llm_kwargs = {
                "engine": deployment_name,
                "api_key": settings.AZURE_OPENAI_API_KEY,
                "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
                "api_version": settings.AZURE_OPENAI_API_VERSION,
            }
            
        # Add reasoning_effort if specified and model supports it
        if reasoning_effort and deployment_name.startswith(("o1", "o3", "o4")):
            llm_kwargs["additional_kwargs"] = {"reasoning_effort": reasoning_effort}
            
        return AzureOpenAI(**llm_kwargs)

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate a response from the LLM."""
        if not self._llm:
            raise RuntimeError("LLM not initialized")
        response = self._llm.complete(prompt, **kwargs)
        return str(response)

    def embed(self, text: str) -> list:
        """Generate embeddings for text."""
        if not self._embed_model:
            raise RuntimeError("Embedding model not initialized")
        return self._embed_model.get_text_embedding(text)

    def embed_batch(self, texts: list) -> list:
        """Generate embeddings for a batch of texts."""
        if not self._embed_model:
            raise RuntimeError("Embedding model not initialized")
        return self._embed_model.get_text_embedding_batch(texts)

    def health_check(self) -> Dict[str, Any]:
        """Check LLM connectivity."""
        if not self._llm:
            return {"status": "not_configured", "error": "LLM not initialized"}
        try:
            # Simple ping to verify connectivity
            response = self._llm.complete("Say 'OK'")
            return {
                "status": "connected",
                "llm_model": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                "embedding_model": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
