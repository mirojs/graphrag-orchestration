"""Azure Translator service for auto-detecting query language and translating.

Uses Azure AI Translator REST API with DefaultAzureCredential (Managed Identity).
A single call to /translate auto-detects the source language and translates to
the target language. If the detected language already matches the target, the
original text is returned untranslated.

See: https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/reference/rest-api-guide
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp
from azure.identity.aio import DefaultAzureCredential

from src.core.config import settings

logger = logging.getLogger(__name__)

_TRANSLATOR_SCOPE = "https://cognitiveservices.azure.com/.default"
_API_VERSION = "3.0"


@dataclass
class TranslationResult:
    """Result of a detect-and-translate call."""
    original_text: str
    translated_text: str
    detected_language: str
    target_language: str
    was_translated: bool
    characters: int


class TranslatorService:
    """Azure AI Translator with Managed Identity authentication.

    Usage::

        svc = TranslatorService()
        result = await svc.detect_and_translate("契約期間は？", target_lang="en")
        # result.translated_text == "What is the contract period?"
        # result.detected_language == "ja"
        # result.was_translated == True
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        self.endpoint = (endpoint or settings.AZURE_TRANSLATOR_ENDPOINT or "").rstrip("/")
        self.region = region or settings.AZURE_TRANSLATOR_REGION or "swedencentral"
        self._credential: Optional[DefaultAzureCredential] = None
        self._session: Optional[aiohttp.ClientSession] = None
        if not self.endpoint:
            logger.warning("translator_service_disabled: AZURE_TRANSLATOR_ENDPOINT not set")

    @property
    def is_available(self) -> bool:
        return bool(self.endpoint)

    async def _get_token(self) -> str:
        """Obtain a bearer token via Managed Identity."""
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        token = await self._credential.get_token(_TRANSLATOR_SCOPE)
        return token.token

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def detect_and_translate(
        self,
        text: str,
        target_lang: str = "en",
    ) -> TranslationResult:
        """Auto-detect source language and translate to target_lang.

        If the detected language prefix matches target_lang, returns the
        original text with was_translated=False.
        """
        if not self.endpoint:
            return TranslationResult(
                original_text=text,
                translated_text=text,
                detected_language="unknown",
                target_language=target_lang,
                was_translated=False,
                characters=0,
            )

        url = f"{self.endpoint}/translate"
        params = {"api-version": _API_VERSION, "to": target_lang}
        token = await self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Ocp-Apim-Subscription-Region": self.region,
            "Content-Type": "application/json",
        }
        body = [{"Text": text}]

        session = await self._get_session()
        async with session.post(url, params=params, headers=headers, json=body) as resp:
            if resp.status != 200:
                error_body = await resp.text()
                logger.error(
                    "translator_api_error",
                    status=resp.status,
                    body=error_body[:500],
                )
                return TranslationResult(
                    original_text=text,
                    translated_text=text,
                    detected_language="unknown",
                    target_language=target_lang,
                    was_translated=False,
                    characters=0,
                )

            data = await resp.json()

        result = data[0]
        detected = result.get("detectedLanguage", {})
        detected_lang = detected.get("language", "unknown")
        translations = result.get("translations", [])
        translated_text = translations[0]["text"] if translations else text

        # Check if translation was actually needed
        target_prefix = target_lang.split("-")[0].lower()
        detected_prefix = detected_lang.split("-")[0].lower()
        same_language = detected_prefix == target_prefix

        if same_language:
            translated_text = text

        char_count = len(text)

        logger.info(
            "translator_result",
            detected=detected_lang,
            target=target_lang,
            was_translated=not same_language,
            chars=char_count,
        )

        return TranslationResult(
            original_text=text,
            translated_text=translated_text if not same_language else text,
            detected_language=detected_lang,
            target_language=target_lang,
            was_translated=not same_language,
            characters=char_count if not same_language else 0,
        )

    async def close(self) -> None:
        """Clean up resources."""
        if self._session and not self._session.closed:
            await self._session.close()
        if self._credential:
            await self._credential.close()


# Module-level singleton
_translator: Optional[TranslatorService] = None


def get_translator_service() -> TranslatorService:
    """Get or create the translator service singleton."""
    global _translator
    if _translator is None:
        _translator = TranslatorService()
    return _translator
