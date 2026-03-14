"""
Speech Router

Provides Azure Text-to-Speech endpoint and Speech auth token endpoint
for client-side TranslationRecognizer (voice input with auto language detection).
"""

import asyncio
import logging
import os
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional

from src.api_gateway.middleware.auth import get_group_id, get_user_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speech"])

# Strong references for fire-and-forget background tasks (prevent GC)
_background_tasks: set = set()


class SpeechRequest(BaseModel):
    text: str


class SpeechUsageReport(BaseModel):
    """Client-side STT usage report."""
    characters: int = Field(..., description="Characters recognized by STT")
    detected_language: Optional[str] = Field(None, description="Language detected by STT")


async def _write_speech_usage(user_id: str, usage_type: str, characters: int,
                              detected_language: str | None = None) -> None:
    """Fire-and-forget: write a speech usage record to Cosmos."""
    try:
        from src.core.services.cosmos_client import get_cosmos_client
        from src.core.models.usage import UsageRecord
        cosmos = get_cosmos_client()
        if cosmos.endpoint and not cosmos._usage_container:
            await asyncio.wait_for(cosmos.initialize(), timeout=10)
        extra = {}
        if usage_type == "tts":
            extra["tts_characters"] = characters
        else:
            extra["stt_characters"] = characters
        record = UsageRecord(
            partition_id=user_id,
            user_id=user_id,
            usage_type="llm_completion",
            model=f"azure-speech-{usage_type}",
            total_tokens=0,
            route=usage_type,
            query_id=str(uuid.uuid4()),
            detected_language=detected_language,
            **extra,
        )
        await asyncio.wait_for(cosmos.write_usage_record(record), timeout=10)
    except Exception as e:
        logger.warning("speech_cosmos_usage_write_skipped: %s", repr(e))


# Cache for speech token
_speech_token_cache: dict = {"token": None, "expires_on": 0}
_speech_token_lock = asyncio.Lock()

# Supported source languages for TranslationRecognizer auto-detect (max 10)
_SPEECH_TRANSLATION_LANGUAGES = [
    "en-US", "ja-JP", "fr-FR", "es-ES", "da-DK",
    "nl-NL", "pt-BR", "tr-TR", "it-IT", "de-DE",
    "ko-KR", "pl-PL", "zh-CN", "zh-TW", "th-TH",
]


async def _get_speech_token(credential) -> dict:
    """Get a cached speech auth token, refreshing if expired."""
    async with _speech_token_lock:
        if _speech_token_cache["token"] is None or _speech_token_cache["expires_on"] < time.time() + 60:
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
            _speech_token_cache["token"] = token.token
            _speech_token_cache["expires_on"] = token.expires_on
    return _speech_token_cache


@router.get("/speech/token")
async def speech_token(request: Request):
    """Return a short-lived auth token for client-side Azure Speech SDK.

    The token is formatted as ``aad#<resourceId>#<accessToken>`` for use with
    ``SpeechTranslationConfig.fromAuthorizationToken()``.
    """
    speech_service_id = os.getenv("AZURE_SPEECH_SERVICE_ID")
    speech_location = os.getenv("AZURE_SPEECH_SERVICE_LOCATION")

    if not speech_service_id or not speech_location:
        raise HTTPException(status_code=400, detail="Speech service is not configured")

    credential = getattr(request.app.state, "azure_credential", None)
    if not credential:
        raise HTTPException(status_code=500, detail="Azure credential not initialized")

    try:
        cache = await _get_speech_token(credential)
        auth_token = f"aad#{speech_service_id}#{cache['token']}"
        return {
            "token": auth_token,
            "region": speech_location,
            "languages": _SPEECH_TRANSLATION_LANGUAGES,
        }
    except Exception as e:
        logger.exception("Failed to get speech token")
        raise HTTPException(status_code=500, detail="Failed to get speech token")


@router.post("/speech")
async def speech(
    request: Request,
    body: SpeechRequest,
    group_id: str = Depends(get_group_id),
    user_id: str = Depends(get_user_id),
):
    """Synthesize text to speech using Azure Speech Service."""
    speech_service_id = os.getenv("AZURE_SPEECH_SERVICE_ID")
    speech_location = os.getenv("AZURE_SPEECH_SERVICE_LOCATION")
    speech_voice = os.getenv("AZURE_SPEECH_SERVICE_VOICE", "en-US-AndrewMultilingualNeural")

    if not speech_service_id or not speech_location:
        raise HTTPException(status_code=400, detail="Speech synthesis is not enabled")

    credential = getattr(request.app.state, "azure_credential", None)
    if not credential:
        raise HTTPException(status_code=500, detail="Azure credential not initialized")

    try:
        cache = await _get_speech_token(credential)

        from azure.cognitiveservices.speech import (
            ResultReason,
            SpeechConfig,
            SpeechSynthesisOutputFormat,
            SpeechSynthesizer,
        )

        auth_token = f"aad#{speech_service_id}#{cache['token']}"
        speech_config = SpeechConfig(auth_token=auth_token, region=speech_location)
        speech_config.speech_synthesis_voice_name = speech_voice
        speech_config.set_speech_synthesis_output_format(
            SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(body.text).get()

        if result.reason == ResultReason.SynthesizingAudioCompleted:
            # Fire-and-forget: track TTS characters for dashboard
            task = asyncio.create_task(_write_speech_usage(user_id, "tts", len(body.text)))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            return Response(content=result.audio_data, media_type="audio/mp3")
        elif result.reason == ResultReason.Canceled:
            details = result.cancellation_details
            logger.error("Speech synthesis canceled: %s %s", details.reason, details.error_details)
            raise HTTPException(status_code=500, detail="Speech synthesis canceled")
        else:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Exception in /speech")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/speech/usage")
async def report_speech_usage(
    body: SpeechUsageReport,
    user_id: str = Depends(get_user_id),
):
    """Report client-side STT usage for dashboard tracking.

    Called by the frontend after speech recognition completes.
    """
    task = asyncio.create_task(
        _write_speech_usage(user_id, "stt", body.characters, body.detected_language)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "ok"}
