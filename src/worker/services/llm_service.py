"""
LLM Service for Azure OpenAI integration.

Provides a centralized LLM and Embedding service for all GraphRAG operations.
"""

from typing import Optional, Dict, Any, Callable
import asyncio
import logging
import os

from src.core.config import settings
from src.core.services.usage_tracker import UsageTracker
from src.core.services.tracked_llm import TrackedLLM
from src.core.models.usage import UsageType

logger = logging.getLogger(__name__)

# Strong references for fire-and-forget background tasks (prevent GC)
_background_tasks: set = set()


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
            "AZURE_OPENAI_ENDPOINT": settings.AZURE_OPENAI_ENDPOINT,
            "VOYAGE_MODEL_NAME": settings.VOYAGE_MODEL_NAME,
            "VOYAGE_EMBEDDING_DIM": settings.VOYAGE_EMBEDDING_DIM,
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
            
            # Note: gpt-4o and gpt-4o-mini are natively supported by llama_index
            # No monkey-patching required for these standard models
            
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

                    self._llm = TrackedLLM(
                        AzureOpenAI(**llm_kwargs),
                        deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                    )
                    logger.info("LLM initialized successfully with managed identity (tracked)")
                except Exception as e:
                    logger.error(f"Failed to initialize LLM: {e}")
                    raise
                
                # V1 OpenAI embedding removed — all embeddings use Voyage V2 (voyage-context-3, 2048D)
                logger.info(f"Embeddings: {settings.VOYAGE_MODEL_NAME} ({settings.VOYAGE_EMBEDDING_DIM}D) — V1 OpenAI fallback removed")
            else:
                logger.info("Using API key authentication for OpenAI")
                # Initialize LLM with API key
                self._llm = TrackedLLM(
                    AzureOpenAI(
                        engine=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                        api_key=settings.AZURE_OPENAI_API_KEY,
                        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                        api_version=settings.AZURE_OPENAI_API_VERSION,
                        temperature=0.0,
                    ),
                    deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                )
                # V1 OpenAI embedding removed — all embeddings use Voyage V2
                logger.info(f"Embeddings: {settings.VOYAGE_MODEL_NAME} ({settings.VOYAGE_EMBEDDING_DIM}D) — V1 OpenAI fallback removed")
            
            # Configure LlamaIndex global settings (embed_model not set — use Voyage V2 directly)
            # LlamaSettings needs the raw LlamaIndex LLM; TrackedLLM is for our pipeline calls.
            LlamaSettings.llm = self._llm._llm if isinstance(self._llm, TrackedLLM) else self._llm
            
            logger.info(
                f"Initialized Azure OpenAI: LLM={settings.AZURE_OPENAI_DEPLOYMENT_NAME}, "
                f"Embeddings={settings.VOYAGE_MODEL_NAME} ({settings.VOYAGE_EMBEDDING_DIM}D)"
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
        """Get the specialized routing LLM (default: gpt-4.1-mini).

        Uses AZURE_OPENAI_ROUTING_DEPLOYMENT from settings.
        Only applies reasoning_effort for o-series models.
        """
        deployment = settings.AZURE_OPENAI_ROUTING_DEPLOYMENT or "gpt-4o-mini"

        # Only use reasoning_effort for o-series models
        if deployment.startswith(("o1", "o3", "o4")):
            effort = settings.AZURE_OPENAI_ROUTING_REASONING_EFFORT or "medium"
            return self._create_llm_client(deployment, reasoning_effort=effort)
        else:
            return self._create_llm_client(deployment)

    def get_indexing_llm(self) -> Any:
        """Get the specialized indexing LLM (GPT-4.1)."""
        deployment = settings.AZURE_OPENAI_INDEXING_DEPLOYMENT or "gpt-4.1"
        return self._create_llm_client(deployment)
    
    def get_synthesis_llm(self) -> Any:
        """Get the specialized synthesis LLM for Route 2/3 final answers.
        
        Uses HYBRID_SYNTHESIS_MODEL (gpt-5.1) for maximum coherence in final synthesis.
        """
        return self._create_llm_client(settings.HYBRID_SYNTHESIS_MODEL)

    def _create_llm_client(self, deployment_name: str, reasoning_effort: Optional[str] = None, group_id: Optional[str] = None, user_id: Optional[str] = None) -> Any:
        """Helper to create LLM instance with correct auth, settings, and token tracking.
        
        Returns a TrackedLLM wrapper that automatically records token usage
        from every acomplete()/complete() call to both a per-request
        TokenAccumulator (for RouteResult.usage) and Cosmos DB (for dashboards).
        """
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
            
        # Models that do NOT support a custom temperature (only default=1)
        no_temperature_models = ("gpt-5-mini", "gpt-5-nano", "o1", "o3", "o4")
        if not deployment_name.startswith(no_temperature_models):
            llm_kwargs["temperature"] = 0.0  # Deterministic outputs for repeatability

        # Add reasoning_effort if specified and model supports it
        if reasoning_effort and deployment_name.startswith(("o1", "o3", "o4")):
            llm_kwargs["additional_kwargs"] = {"reasoning_effort": reasoning_effort}
            
        raw_llm = AzureOpenAI(**llm_kwargs)
        return TrackedLLM(
            raw_llm,
            deployment_name=deployment_name,
            group_id=group_id or "unknown",
            user_id=user_id,
        )

    def generate(self, prompt: str, group_id: Optional[str] = None, user_id: Optional[str] = None, **kwargs) -> str:
        """Generate a response from the LLM with usage tracking.
        
        Token tracking is handled automatically by the TrackedLLM wrapper.
        group_id/user_id are set on the wrapper for Cosmos DB partitioning.
        """
        if not self._llm:
            raise RuntimeError("LLM not initialized")
        # Update tracking context on the wrapper
        if group_id and hasattr(self._llm, '_group_id'):
            object.__setattr__(self._llm, '_group_id', group_id)
        if user_id and hasattr(self._llm, '_user_id'):
            object.__setattr__(self._llm, '_user_id', user_id)
        response = self._llm.complete(prompt, **kwargs)
        return str(response)

    def embed(self, text: str, group_id: Optional[str] = None, user_id: Optional[str] = None) -> list:
        """Generate embeddings for text with usage tracking."""
        if not self._embed_model:
            raise RuntimeError("Embedding model not initialized")
        
        # Estimate tokens (rough approximation: 1 token ≈ 4 chars)
        estimated_tokens = len(text) // 4
        
        result = self._embed_model.get_text_embedding(text)
        
        # Track usage
        if group_id or user_id:
            try:
                loop = asyncio.get_event_loop()
                task = loop.create_task(UsageTracker().log_embedding_usage(
                    partition_id=user_id or group_id or "unknown",
                    user_id=user_id,
                    model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                    total_tokens=estimated_tokens,
                    dimensions=settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS
                ))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            except Exception:
                pass  # Fire-and-forget: ignore failures
        
        return result

    def embed_batch(self, texts: list, group_id: Optional[str] = None, user_id: Optional[str] = None) -> list:
        """Generate embeddings for a batch of texts with usage tracking."""
        if not self._embed_model:
            raise RuntimeError("Embedding model not initialized")
        
        # Estimate tokens for batch
        estimated_tokens = sum(len(text) // 4 for text in texts)
        
        result = self._embed_model.get_text_embedding_batch(texts)
        
        # Track usage
        if group_id or user_id:
            try:
                loop = asyncio.get_event_loop()
                task = loop.create_task(UsageTracker().log_embedding_usage(
                    partition_id=user_id or group_id or "unknown",
                    user_id=user_id,
                    model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                    total_tokens=estimated_tokens,
                    dimensions=settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS,
                    chunk_count=len(texts)
                ))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            except Exception:
                pass  # Fire-and-forget: ignore failures
        
        return result

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
                "embedding_model": settings.VOYAGE_MODEL_NAME,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
