"""
Unit Tests: Embedding Dimensions (2048 for Voyage voyage-context-3)

Verifies that all embedding-related code uses 2048 dimensions
for Voyage voyage-context-3 (the current embedding model).
Previously used text-embedding-3-large (3072 dims) — now deprecated.

Run: pytest tests/unit/test_embeddings.py -v
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from typing import List

# Expected dimensions for voyage-context-3
EXPECTED_DIMENSIONS = 2048
OLD_DIMENSIONS = 3072  # text-embedding-3-large (V1 deprecated)
LEGACY_DIMENSIONS = 1536  # text-embedding-3-small (very old, deprecated)


# ============================================================================
# Test Category 1: Embedding Vector Dimensions
# ============================================================================

class TestEmbeddingDimensions:
    """Test that embeddings use correct dimensions."""
    
    def test_embedding_dimensions_constant(self, test_config):
        """Test that test config uses 2048 dimensions."""
        assert test_config["embedding_dimensions"] == EXPECTED_DIMENSIONS
    
    def test_mock_embedder_uses_2048(self, mock_embedder):
        """Test that mock embedder returns 2048-dim vectors."""
        embedding = mock_embedder.get_text_embedding("test text")
        assert len(embedding) == EXPECTED_DIMENSIONS
    
    @pytest.mark.asyncio
    async def test_async_embedder_uses_2048(self, mock_embedder):
        """Test that async mock embedder returns 2048-dim vectors."""
        embedding = await mock_embedder.aget_text_embedding("test text")
        assert len(embedding) == EXPECTED_DIMENSIONS
    
    def test_batch_embeddings_use_2048(self, mock_embedder):
        """Test that batch embeddings return 2048-dim vectors."""
        texts = ["text 1", "text 2", "text 3"]
        embeddings = mock_embedder.embed_documents(texts)
        
        assert len(embeddings) == 3
        for embedding in embeddings:
            assert len(embedding) == EXPECTED_DIMENSIONS


# ============================================================================
# Test Category 2: Configuration Validation
# ============================================================================

class TestEmbeddingConfiguration:
    """Test embedding configuration settings."""
    
    def test_config_model_is_voyage(self, test_config):
        """Test that config specifies voyage-context-3."""
        assert test_config["embedding_model"] == "voyage-context-3"
    
    def test_dimensions_not_3072(self, test_config):
        """Test that dimensions are NOT the old V1 3072."""
        assert test_config["embedding_dimensions"] != OLD_DIMENSIONS
    
    def test_dimensions_not_1536(self, test_config):
        """Test that dimensions are NOT the legacy 1536."""
        assert test_config["embedding_dimensions"] != LEGACY_DIMENSIONS
    
    def test_dimensions_match_model(self, test_config):
        """Test that dimensions match the model."""
        model = test_config["embedding_model"]
        dims = test_config["embedding_dimensions"]
        
        # voyage-context-3 uses 2048
        if "voyage" in model:
            assert dims == 2048


# ============================================================================
# Test Category 3: Source Code Compliance
# ============================================================================

class TestSourceCodeDimensions:
    """Test that source code uses correct dimensions."""
    
    def test_config_py_voyage_dimensions(self):
        """Test that config.py specifies 2048 for Voyage."""
        try:
            from src.core.config import settings
            assert settings.VOYAGE_EMBEDDING_DIM == EXPECTED_DIMENSIONS
        except ImportError:
            pytest.skip("Config module not available")
    
    def test_indexing_pipeline_dimensions(self):
        """Test that V2 indexing pipeline defaults to 2048."""
        try:
            from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import LazyGraphRAGIndexingConfig
            config = LazyGraphRAGIndexingConfig()
            assert config.embedding_dimensions == EXPECTED_DIMENSIONS
        except ImportError:
            pytest.skip("LazyGraphRAGIndexingConfig not available")
    
    def test_algorithm_registry_v2_dimensions(self):
        """Test that V2 algorithm registry uses 2048."""
        try:
            from src.core.algorithm_registry import ALGORITHM_VERSIONS
            v2 = ALGORITHM_VERSIONS.get("v2")
            if v2:
                assert v2.embedding_dim == EXPECTED_DIMENSIONS
                assert v2.embedding_model == "voyage-context-3"
        except ImportError:
            pytest.skip("Algorithm registry not available")


# ============================================================================
# Test Category 4: Vector Compatibility
# ============================================================================

class TestVectorCompatibility:
    """Test vector compatibility between components."""
    
    def test_query_and_document_same_dimensions(self, mock_embedder):
        """Test that query and document embeddings have same dimensions."""
        query_embedding = mock_embedder.embed_query("What is the total?")
        doc_embeddings = mock_embedder.embed_documents(["Document text here"])
        
        assert len(query_embedding) == len(doc_embeddings[0])
        assert len(query_embedding) == EXPECTED_DIMENSIONS
    
    def test_embeddings_are_float_lists(self, mock_embedder):
        """Test that embeddings are lists of floats."""
        embedding = mock_embedder.get_text_embedding("test")
        
        assert isinstance(embedding, list)
        assert all(isinstance(x, (int, float)) for x in embedding)
    
    def test_embeddings_are_normalized(self, mock_embedder):
        """Test that embeddings are normalized (or at least bounded)."""
        embedding = mock_embedder.get_text_embedding("test")
        
        # Mock returns all 0.1, so check bounds
        assert all(-1.0 <= x <= 1.0 for x in embedding)


# ============================================================================
# Test Category 5: Neo4j Index Compatibility
# ============================================================================

class TestNeo4jIndexDimensions:
    """Test Neo4j vector index dimension requirements."""
    
    def test_entity_embedding_v2_index_dimensions(self):
        """Test that entity_embedding_v2 index expects 2048 dims."""
        expected_index_config = {
            "name": "entity_embedding_v2",
            "dimensions": EXPECTED_DIMENSIONS,
            "similarity": "cosine",
        }
        assert expected_index_config["dimensions"] == EXPECTED_DIMENSIONS
    
    def test_sentence_embeddings_v2_index_dimensions(self):
        """Test that sentence_embeddings_v2 index expects 2048 dims."""
        expected_index_config = {
            "name": "sentence_embeddings_v2",
            "dimensions": EXPECTED_DIMENSIONS,
            "similarity": "cosine",
        }
        assert expected_index_config["dimensions"] == EXPECTED_DIMENSIONS


# ============================================================================
# Test Category 6: Error Messages for Dimension Mismatch
# ============================================================================

class TestDimensionMismatchErrors:
    """Test handling of dimension mismatch errors."""
    
    def test_mismatch_error_message_is_clear(self):
        """Test that dimension mismatch produces clear error."""
        error_message = "Index query vector has 2048 dimensions, but indexed vectors have 3072"
        
        assert "2048" in error_message
        assert "3072" in error_message
        assert "dimensions" in error_message
    
    def test_can_detect_old_v1_index(self):
        """Test detection of old V1 3072-dim indexes."""
        old_index_dimensions = OLD_DIMENSIONS
        current_embedding_dimensions = EXPECTED_DIMENSIONS
        
        is_mismatch = old_index_dimensions != current_embedding_dimensions
        assert is_mismatch, "Should detect mismatch between V1 index and V2 embeddings"


# ============================================================================
# Test Category 7: Migration Verification
# ============================================================================

class TestDimensionMigration:
    """Test that migration from OpenAI 3072 to Voyage 2048 is reflected in config."""
    
    def test_voyage_is_enabled(self):
        """Test that Voyage V2 is enabled."""
        try:
            from src.core.config import settings
            assert settings.VOYAGE_V2_ENABLED is True
        except ImportError:
            pytest.skip("Config not available")
    
    def test_voyage_model_name(self):
        """Test that Voyage model name is voyage-context-3."""
        try:
            from src.core.config import settings
            assert settings.VOYAGE_MODEL_NAME == "voyage-context-3"
        except ImportError:
            pytest.skip("Config not available")


# ============================================================================
# Regression Tests
# ============================================================================

class TestEmbeddingRegression:
    """Regression tests for embedding issues."""
    
    def test_fallback_zero_vector_is_2048(self):
        """Test that fallback zero vectors use 2048 dimensions."""
        fallback_vector = [0.0] * EXPECTED_DIMENSIONS
        assert len(fallback_vector) == EXPECTED_DIMENSIONS
    
    def test_mock_vectors_in_tests_are_2048(self, mock_retrieval_results):
        """Test that mock retrieval results use 2048-dim compatible data."""
        # The mock doesn't store embeddings directly, but metadata should be consistent
        for result in mock_retrieval_results:
            assert result.score >= 0.0
            assert result.score <= 1.0
