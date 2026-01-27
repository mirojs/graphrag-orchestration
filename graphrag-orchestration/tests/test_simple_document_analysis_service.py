"""
Tests for Simple Document Analysis Service

Tests the unified document analysis service that abstracts
backend complexity and provides a clean API.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from llama_index.core import Document

from app.services.simple_document_analysis_service import (
    SimpleDocumentAnalysisService,
    DocumentAnalysisBackend,
    DocumentAnalysisResult,
)


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch("app.services.simple_document_analysis_service.settings") as mock:
        mock.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "https://test-di.cognitiveservices.azure.com/"
        mock.AZURE_DOCUMENT_INTELLIGENCE_KEY = "test-di-key"
        mock.AZURE_CONTENT_UNDERSTANDING_ENDPOINT = "https://test-cu.cognitiveservices.azure.com/"
        mock.AZURE_CONTENT_UNDERSTANDING_API_KEY = "test-cu-key"
        yield mock


@pytest.fixture
def mock_di_service():
    """Mock Document Intelligence service."""
    with patch("app.services.simple_document_analysis_service.DocumentIntelligenceService") as mock:
        service = MagicMock()
        service.analyze_document_batch = AsyncMock(return_value=[
            Document(text="Test document 1", doc_id="doc1"),
            Document(text="Test document 2", doc_id="doc2"),
        ])
        mock.return_value = service
        yield mock


@pytest.fixture
def mock_cu_service():
    """Mock Content Understanding service."""
    with patch("app.services.simple_document_analysis_service.CUStandardIngestionServiceV2") as mock:
        service = MagicMock()
        service.ingest_from_url = AsyncMock(return_value=[
            Document(text="CU document", doc_id="cu_doc"),
        ])
        service.ingest_from_text = AsyncMock(return_value=[
            Document(text="CU text document", doc_id="cu_text"),
        ])
        mock.return_value = service
        yield mock


class TestSimpleDocumentAnalysisService:
    """Tests for SimpleDocumentAnalysisService."""
    
    def test_initialization(self, mock_settings):
        """Test service initialization."""
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.AUTO,
            max_concurrency=3,
        )
        
        assert service.backend == DocumentAnalysisBackend.AUTO
        assert service.max_concurrency == 3
        assert service._selected_backend is None
    
    def test_get_available_backends(self, mock_settings):
        """Test detection of available backends."""
        service = SimpleDocumentAnalysisService()
        available = service._get_available_backends()
        
        # Both backends should be available with mock settings
        assert DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE in available
        assert DocumentAnalysisBackend.CONTENT_UNDERSTANDING in available
    
    def test_select_backend_auto_prefers_di(self, mock_settings):
        """Test that AUTO mode prefers Document Intelligence."""
        service = SimpleDocumentAnalysisService(backend=DocumentAnalysisBackend.AUTO)
        backend = service._select_backend()
        
        assert backend == DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE
    
    def test_select_backend_specific(self, mock_settings):
        """Test selecting a specific backend."""
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.CONTENT_UNDERSTANDING
        )
        backend = service._select_backend()
        
        assert backend == DocumentAnalysisBackend.CONTENT_UNDERSTANDING
    
    def test_select_backend_no_config_raises(self):
        """Test that missing configuration raises error."""
        with patch("app.services.simple_document_analysis_service.settings") as mock:
            mock.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = None
            mock.AZURE_CONTENT_UNDERSTANDING_ENDPOINT = None
            
            service = SimpleDocumentAnalysisService()
            
            with pytest.raises(RuntimeError, match="No document analysis backend is configured"):
                service._select_backend()
    
    @pytest.mark.asyncio
    async def test_analyze_documents_with_urls_di(self, mock_settings, mock_di_service):
        """Test analyzing documents from URLs using Document Intelligence."""
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE
        )
        
        result = await service.analyze_documents(
            urls=["https://example.com/doc1.pdf", "https://example.com/doc2.pdf"]
        )
        
        assert result.success
        assert result.backend_used == DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE
        assert len(result.documents) == 2
        assert result.documents[0].doc_id == "doc1"
        assert result.metadata["documents_extracted"] == 2
    
    @pytest.mark.asyncio
    async def test_analyze_documents_with_urls_cu(self, mock_settings, mock_cu_service):
        """Test analyzing documents from URLs using Content Understanding."""
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.CONTENT_UNDERSTANDING
        )
        
        result = await service.analyze_documents(
            urls=["https://example.com/doc.pdf"]
        )
        
        assert result.success
        assert result.backend_used == DocumentAnalysisBackend.CONTENT_UNDERSTANDING
        assert len(result.documents) == 1
        assert result.documents[0].doc_id == "cu_doc"
    
    @pytest.mark.asyncio
    async def test_analyze_documents_with_text_cu(self, mock_settings, mock_cu_service):
        """Test analyzing raw text using Content Understanding."""
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.CONTENT_UNDERSTANDING
        )
        
        result = await service.analyze_documents(
            texts=["This is test text"]
        )
        
        assert result.success
        assert len(result.documents) == 1
        assert result.documents[0].doc_id == "cu_text"
    
    @pytest.mark.asyncio
    async def test_analyze_documents_no_input(self, mock_settings):
        """Test that no input returns error."""
        service = SimpleDocumentAnalysisService()
        
        result = await service.analyze_documents()
        
        assert not result.success
        assert "No URLs or texts provided" in result.error
    
    @pytest.mark.asyncio
    async def test_analyze_documents_error_handling(self, mock_settings, mock_di_service):
        """Test error handling during document analysis."""
        # Make the service raise an exception
        mock_di_service.return_value.analyze_document_batch.side_effect = Exception("Analysis failed")
        
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE
        )
        
        result = await service.analyze_documents(urls=["https://example.com/doc.pdf"])
        
        assert not result.success
        assert "Analysis failed" in result.error
    
    @pytest.mark.asyncio
    async def test_analyze_single_document(self, mock_settings, mock_di_service):
        """Test analyzing a single document (convenience method)."""
        service = SimpleDocumentAnalysisService()
        
        result = await service.analyze_single_document(
            url="https://example.com/doc.pdf"
        )
        
        assert result.success
        assert len(result.documents) == 2  # Mock returns 2 docs
    
    def test_get_backend_info(self, mock_settings):
        """Test getting backend information."""
        service = SimpleDocumentAnalysisService(
            backend=DocumentAnalysisBackend.CONTENT_UNDERSTANDING,
            max_concurrency=7,
        )
        
        info = service.get_backend_info()
        
        assert "available_backends" in info
        assert "selected_backend" in info
        assert "configuration" in info
        assert info["max_concurrency"] == 7
        assert info["requested_backend"] == DocumentAnalysisBackend.CONTENT_UNDERSTANDING
        
        # Check configuration shows both backends available
        assert info["configuration"]["di_endpoint"] is True
        assert info["configuration"]["cu_endpoint"] is True


class TestDocumentAnalysisBackend:
    """Tests for DocumentAnalysisBackend enum."""
    
    def test_backend_values(self):
        """Test that backend enum has expected values."""
        assert DocumentAnalysisBackend.DOCUMENT_INTELLIGENCE == "document_intelligence"
        assert DocumentAnalysisBackend.CONTENT_UNDERSTANDING == "content_understanding"
        assert DocumentAnalysisBackend.AUTO == "auto"


class TestDocumentAnalysisResult:
    """Tests for DocumentAnalysisResult dataclass."""
    
    def test_result_creation_success(self):
        """Test creating a successful result."""
        docs = [Document(text="Test", doc_id="1")]
        result = DocumentAnalysisResult(
            documents=docs,
            backend_used="document_intelligence",
            metadata={"count": 1},
            success=True,
        )
        
        assert result.success
        assert len(result.documents) == 1
        assert result.error is None
    
    def test_result_creation_error(self):
        """Test creating an error result."""
        result = DocumentAnalysisResult(
            documents=[],
            backend_used="unknown",
            metadata={},
            success=False,
            error="Something went wrong",
        )
        
        assert not result.success
        assert result.error == "Something went wrong"
        assert len(result.documents) == 0
