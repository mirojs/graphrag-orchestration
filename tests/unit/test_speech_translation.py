"""Unit tests for the voice translation feature (Azure Speech SDK integration).

Tests:
- /speech/token endpoint (mocked credential)
- Config flag for speech translation
- SpeechTranslationInput component behavior (structural tests)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os


# ============================================================================
# 1. /speech/token endpoint
# ============================================================================


class TestSpeechTokenEndpoint:
    def _make_app(self, env_vars: dict | None = None):
        """Create a test FastAPI app with the speech router."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api_gateway.routers.speech import router

        app = FastAPI()
        app.include_router(router)

        # Patch env vars
        defaults = {
            "AZURE_SPEECH_SERVICE_ID": "test-speech-resource",
            "AZURE_SPEECH_SERVICE_LOCATION": "swedencentral",
        }
        if env_vars:
            defaults.update(env_vars)

        # Mock credential on app state
        mock_credential = AsyncMock()
        mock_token = MagicMock()
        mock_token.token = "fake-access-token-12345"
        mock_token.expires_on = 9999999999  # Far future
        mock_credential.get_token = AsyncMock(return_value=mock_token)
        app.state.azure_credential = mock_credential

        return TestClient(app), defaults

    def test_returns_token_and_region(self):
        client, env_vars = self._make_app()
        with patch.dict(os.environ, env_vars):
            # Clear token cache between tests
            from src.api_gateway.routers.speech import _speech_token_cache
            _speech_token_cache["token"] = None
            _speech_token_cache["expires_on"] = 0

            resp = client.get("/speech/token")

        assert resp.status_code == 200
        body = resp.json()
        assert body["token"] == "aad#test-speech-resource#fake-access-token-12345"
        assert body["region"] == "swedencentral"
        assert isinstance(body["languages"], list)
        assert len(body["languages"]) == 10
        assert "en-US" in body["languages"]
        assert "ja-JP" in body["languages"]

    def test_returns_400_when_not_configured(self):
        client, _ = self._make_app()
        with patch.dict(os.environ, {}, clear=True):
            # Ensure speech vars are missing
            for key in ["AZURE_SPEECH_SERVICE_ID", "AZURE_SPEECH_SERVICE_LOCATION"]:
                os.environ.pop(key, None)
            resp = client.get("/speech/token")

        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"]

    def test_returns_500_when_no_credential(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api_gateway.routers.speech import router

        app = FastAPI()
        app.include_router(router)
        # No credential set on app.state
        app.state.azure_credential = None

        client = TestClient(app)
        env_vars = {
            "AZURE_SPEECH_SERVICE_ID": "test-speech-resource",
            "AZURE_SPEECH_SERVICE_LOCATION": "swedencentral",
        }
        with patch.dict(os.environ, env_vars):
            resp = client.get("/speech/token")

        assert resp.status_code == 500
        assert "credential" in resp.json()["detail"].lower()

    def test_token_format_is_aad_prefixed(self):
        """The token must be in the format aad#<resourceId>#<accessToken> for the Speech SDK."""
        client, env_vars = self._make_app()
        with patch.dict(os.environ, env_vars):
            from src.api_gateway.routers.speech import _speech_token_cache
            _speech_token_cache["token"] = None
            _speech_token_cache["expires_on"] = 0

            resp = client.get("/speech/token")

        token = resp.json()["token"]
        parts = token.split("#")
        assert len(parts) == 3
        assert parts[0] == "aad"
        assert parts[1] == "test-speech-resource"
        assert parts[2] == "fake-access-token-12345"


# ============================================================================
# 2. Config flag
# ============================================================================


class TestSpeechTranslationConfigFlag:
    def _get_config(self, env_vars: dict):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api_gateway.routers.config import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch.dict(os.environ, env_vars, clear=True):
            resp = client.get("/config")
        return resp.json()

    def test_disabled_by_default(self):
        config = self._get_config({})
        assert config["showSpeechTranslation"] is False

    def test_enabled_when_all_configured(self):
        config = self._get_config({
            "ENABLE_SPEECH_TRANSLATION": "true",
            "AZURE_SPEECH_SERVICE_ID": "test-resource",
            "AZURE_SPEECH_SERVICE_LOCATION": "swedencentral",
        })
        assert config["showSpeechTranslation"] is True

    def test_disabled_without_speech_service(self):
        config = self._get_config({
            "ENABLE_SPEECH_TRANSLATION": "true",
            # Missing AZURE_SPEECH_SERVICE_ID and LOCATION
        })
        assert config["showSpeechTranslation"] is False

    def test_disabled_when_flag_false(self):
        config = self._get_config({
            "ENABLE_SPEECH_TRANSLATION": "false",
            "AZURE_SPEECH_SERVICE_ID": "test-resource",
            "AZURE_SPEECH_SERVICE_LOCATION": "swedencentral",
        })
        assert config["showSpeechTranslation"] is False


# ============================================================================
# 3. Translation language list
# ============================================================================


class TestSpeechTranslationLanguages:
    def test_all_supported_locales_present(self):
        from src.api_gateway.routers.speech import _SPEECH_TRANSLATION_LANGUAGES
        expected = {"en-US", "ja-JP", "fr-FR", "es-ES", "da-DK",
                    "nl-NL", "pt-BR", "tr-TR", "it-IT", "pl-PL"}
        assert set(_SPEECH_TRANSLATION_LANGUAGES) == expected

    def test_max_10_languages(self):
        """Azure Speech SDK auto-detect supports max 10 candidate languages."""
        from src.api_gateway.routers.speech import _SPEECH_TRANSLATION_LANGUAGES
        assert len(_SPEECH_TRANSLATION_LANGUAGES) <= 10


# ============================================================================
# 4. TTS endpoint still works (regression test)
# ============================================================================


class TestTTSEndpointRegression:
    def test_tts_returns_400_when_not_configured(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api_gateway.routers.speech import router
        from src.api_gateway.middleware.auth import get_group_id

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_group_id] = lambda: "test-group"

        client = TestClient(app)
        with patch.dict(os.environ, {}, clear=True):
            for key in ["AZURE_SPEECH_SERVICE_ID", "AZURE_SPEECH_SERVICE_LOCATION"]:
                os.environ.pop(key, None)
            resp = client.post("/speech", json={"text": "hello"})

        assert resp.status_code == 400
