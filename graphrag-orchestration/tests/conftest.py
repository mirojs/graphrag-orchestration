"""Test configuration for graphrag-orchestration tests.

This conftest.py overrides the root conftest.py to provide
appropriate fixtures for GraphRAG V3 tests.
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure the graphrag-orchestration app is importable
GRAPHRAG_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if GRAPHRAG_SRC not in sys.path:
    sys.path.insert(0, GRAPHRAG_SRC)

# Set testing environment
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("APP_ENV", "dev")

# Register pytest plugins
pytest_plugins = ["pytest_mock", "pytest_asyncio"]


@pytest.fixture
def mock_neo4j_driver():
    """Mock Neo4j driver for tests."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


@pytest.fixture
def mock_settings():
    """Mock settings for GraphRAG V3 tests."""
    settings = MagicMock()
    settings.neo4j_uri = "bolt://localhost:7687"
    settings.neo4j_user = "neo4j"
    settings.neo4j_password = "password"
    settings.azure_openai_endpoint = "https://test.openai.azure.com"
    settings.azure_openai_api_key = "test-key"
    settings.azure_openai_embedding_deployment = "text-embedding-ada-002"
    settings.azure_openai_chat_deployment = "gpt-4"
    return settings


@pytest.fixture
def mock_embedder():
    """Mock embedder for tests."""
    embedder = AsyncMock()
    embedder.aembed.return_value = [0.1] * 1536
    return embedder


@pytest.fixture
def mock_llm():
    """Mock LLM for tests."""
    llm = AsyncMock()
    response = MagicMock()
    response.content = "Test response"
    llm.achat.return_value = response
    return llm
