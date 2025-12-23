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
                    
                    # Configure reasoning effort if applicable (o1/o3/o4 models)
                    llm_kwargs = {
                        "model": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                        "deployment_name": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                        "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
                        "api_version": settings.AZURE_OPENAI_API_VERSION,
                        "use_azure_ad": True,
                        "azure_ad_token_provider": token_provider,
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
                    # Only pass dimensions if using embedding-3 models (ada-002 doesn't support it)
                    embed_kwargs = {
                        "model": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                        "deployment_name": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                        "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
                        "api_version": settings.AZURE_OPENAI_API_VERSION,
                        "api_key": "",  # Empty string required even with use_azure_ad
                        "use_azure_ad": True,
                        "azure_ad_token_provider": token_provider,
                    }
                    # text-embedding-3-* models support dimensions parameter, ada-002 does not
                    if "embedding-3" in settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT:
                        embed_kwargs["dimensions"] = settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS
                        logger.info(f"Using dimensions: {settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS}")
                    
                    self._embed_model = AzureOpenAIEmbedding(**embed_kwargs)
                    logger.info("Embedding model initialized successfully with managed identity")
                except Exception as e:
                    logger.error(f"Failed to initialize embedding model: {e}", exc_info=True)
                    raise
            else:
                logger.info("Using API key authentication for OpenAI")
                # Initialize LLM with API key
                self._llm = AzureOpenAI(
                    model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                    deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                    api_key=settings.AZURE_OPENAI_API_KEY,
                    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                    api_version=settings.AZURE_OPENAI_API_VERSION,
                )
                
                # Initialize Embedding Model with API key
                # Only pass dimensions if using embedding-3 models (ada-002 doesn't support it)
                embed_kwargs = {
                    "model": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                    "deployment_name": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
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
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI: {e}")

    @property
    def llm(self) -> Optional[Any]:
        """Get the LLM instance."""
        return self._llm

    @property
    def embed_model(self) -> Optional[Any]:
        """Get the Embedding model instance."""
        return self._embed_model
    
    def get_indexing_llm(self) -> Any:
        """
        Get LLM for indexing operations (entity extraction, RAPTOR clustering).
        
        Uses AZURE_OPENAI_INDEXING_DEPLOYMENT if set, otherwise uses primary LLM.
        Recommended: gpt-4.1 (1M context window for bulk document reading)
        """
        if not settings.AZURE_OPENAI_INDEXING_DEPLOYMENT:
            return self._llm
        
        return self._create_llm_instance(settings.AZURE_OPENAI_INDEXING_DEPLOYMENT)
    
    def get_routing_llm(self) -> Any:
        """
        Get LLM for query routing (intent classification: Vector vs Graph vs RAPTOR).
        
        Uses AZURE_OPENAI_ROUTING_DEPLOYMENT if set, otherwise uses primary LLM.
        Recommended: gpt-5.2-thinking-standard (System 2 reasoning for 95%+ accuracy)
        """
        if not settings.AZURE_OPENAI_ROUTING_DEPLOYMENT:
            return self._llm
        
        return self._create_llm_instance(settings.AZURE_OPENAI_ROUTING_DEPLOYMENT)
    
    def _create_llm_instance(self, deployment_name: str) -> Any:
        """Create an LLM instance for a specific deployment."""
        from llama_index.llms.azure_openai import AzureOpenAI
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        
        if not settings.AZURE_OPENAI_API_KEY:
            # Use managed identity
            env_token = os.getenv("AZURE_OPENAI_BEARER_TOKEN")
            if env_token:
                def token_provider() -> str:
                    return env_token
            else:
                credential = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(
                    credential,
                    "https://cognitiveservices.azure.com/.default"
                )
            
            return AzureOpenAI(
                model=deployment_name,
                deployment_name=deployment_name,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version=settings.AZURE_OPENAI_API_VERSION,
                use_azure_ad=True,
                azure_ad_token_provider=token_provider,
            )
        else:
            # Use API key
            return AzureOpenAI(
                model=deployment_name,
                deployment_name=deployment_name,
                api_key=settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )

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
                "model": deployment_name,
                "deployment_name": deployment_name,
                "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
                "api_version": settings.AZURE_OPENAI_API_VERSION,
                "use_azure_ad": True,
                "azure_ad_token_provider": token_provider,
            }
        else:
            llm_kwargs = {
                "model": deployment_name,
                "deployment_name": deployment_name,
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
