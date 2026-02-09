"""
Speech Synthesis Router

Provides Azure Text-to-Speech endpoint.
Replaces the Quart /speech endpoint.
"""

import logging
import os
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speech"])


class SpeechRequest(BaseModel):
    text: str


# Cache for speech token
_speech_token_cache: dict = {"token": None, "expires_on": 0}


@router.post("/speech")
async def speech(
    request: Request,
    body: SpeechRequest,
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
        # Refresh token if expired or expiring soon
        if _speech_token_cache["token"] is None or _speech_token_cache["expires_on"] < time.time() + 60:
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
            _speech_token_cache["token"] = token.token
            _speech_token_cache["expires_on"] = token.expires_on

        from azure.cognitiveservices.speech import (
            ResultReason,
            SpeechConfig,
            SpeechSynthesisOutputFormat,
            SpeechSynthesizer,
        )

        auth_token = f"aad#{speech_service_id}#{_speech_token_cache['token']}"
        speech_config = SpeechConfig(auth_token=auth_token, region=speech_location)
        speech_config.speech_synthesis_voice_name = speech_voice
        speech_config.set_speech_synthesis_output_format(
            SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(body.text).get()

        if result.reason == ResultReason.SynthesizingAudioCompleted:
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
        raise HTTPException(status_code=500, detail=str(e))
