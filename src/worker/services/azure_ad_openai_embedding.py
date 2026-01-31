from __future__ import annotations

from typing import Any, Callable, List, Optional, Awaitable

from pydantic import Field, PrivateAttr

from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.base.embeddings.base import Embedding

from openai import AzureOpenAI, AsyncAzureOpenAI


class AzureADOpenAIEmbedding(BaseEmbedding):
    """Embedding adapter that uses the official OpenAI Azure clients with AAD tokens.

    This avoids a known incompatibility in LlamaIndex's `AzureOpenAIEmbedding` path
    where AAD tokens can be treated as API keys.

    `deployment_name` must be the Azure OpenAI *deployment* name.
    """

    deployment_name: str = Field(description="Azure OpenAI deployment name for embeddings")
    azure_endpoint: str = Field(description="Azure OpenAI endpoint, e.g. https://<name>.openai.azure.com/")
    api_version: str = Field(description="Azure OpenAI API version")
    dimensions: Optional[int] = Field(default=None, description="Optional embedding dimensions")

    _token_provider: Callable[[], str] = PrivateAttr()
    _client: AzureOpenAI = PrivateAttr()
    _aclient: AsyncAzureOpenAI = PrivateAttr()

    def __init__(
        self,
        *,
        deployment_name: str,
        azure_endpoint: str,
        api_version: str,
        azure_ad_token_provider: Callable[[], str],
        dimensions: Optional[int] = None,
        model_name: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(
            deployment_name=deployment_name,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            dimensions=dimensions,
            model_name=model_name or deployment_name,
            **kwargs,
        )

        self._token_provider = azure_ad_token_provider

        async def _async_tp() -> str:
            return azure_ad_token_provider()

        # Use the OpenAI SDK's native AAD token provider support.
        self._client = AzureOpenAI(
            azure_endpoint=self.azure_endpoint,
            api_version=self.api_version,
            azure_ad_token_provider=azure_ad_token_provider,
        )
        self._aclient = AsyncAzureOpenAI(
            azure_endpoint=self.azure_endpoint,
            api_version=self.api_version,
            azure_ad_token_provider=_async_tp,
        )

    def close(self) -> None:
        # Best-effort; OpenAI SDK uses httpx under the hood.
        try:
            self._client.close()
        except Exception:
            pass

    async def aclose(self) -> None:
        try:
            await self._aclient.close()
        except Exception:
            pass
        self.close()

    def _get_text_embedding(self, text: str) -> Embedding:
        resp = self._client.embeddings.create(
            model=self.deployment_name,
            input=[text],
            **({"dimensions": self.dimensions} if self.dimensions is not None else {}),
        )
        return resp.data[0].embedding

    async def _aget_text_embedding(self, text: str) -> Embedding:
        resp = await self._aclient.embeddings.create(
            model=self.deployment_name,
            input=[text],
            **({"dimensions": self.dimensions} if self.dimensions is not None else {}),
        )
        return resp.data[0].embedding

    def _get_text_embeddings(self, texts: List[str]) -> List[Embedding]:
        resp = self._client.embeddings.create(
            model=self.deployment_name,
            input=texts,
            **({"dimensions": self.dimensions} if self.dimensions is not None else {}),
        )
        # Preserve order.
        return [item.embedding for item in resp.data]

    async def _aget_text_embeddings(self, texts: List[str]) -> List[Embedding]:
        resp = await self._aclient.embeddings.create(
            model=self.deployment_name,
            input=texts,
            **({"dimensions": self.dimensions} if self.dimensions is not None else {}),
        )
        return [item.embedding for item in resp.data]

    def _get_query_embedding(self, query: str) -> Embedding:
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query: str) -> Embedding:
        return await self._aget_text_embedding(query)
