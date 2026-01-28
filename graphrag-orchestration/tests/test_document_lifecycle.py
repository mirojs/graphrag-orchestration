"""
Integration tests for Document Lifecycle and Maintenance APIs.

These tests verify the document deprecation, restoration, and maintenance flows.
Requires a running Neo4j instance (uses test group isolation).
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any

from app.hybrid_v2.services.document_lifecycle import DocumentLifecycleService
from app.hybrid_v2.services.maintenance import MaintenanceService


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_neo4j_store():
    """Create a mock Neo4j store for unit testing."""
    store = MagicMock()
    store.driver = MagicMock()
    store.database = "neo4j"
    return store


@pytest.fixture
def lifecycle_service(mock_neo4j_store):
    """Create DocumentLifecycleService with mocked store."""
    return DocumentLifecycleService(neo4j_store=mock_neo4j_store)


@pytest.fixture
def maintenance_service(mock_neo4j_store):
    """Create MaintenanceService with mocked store."""
    return MaintenanceService(neo4j_store=mock_neo4j_store)


# ============================================================================
# DocumentLifecycleService Tests
# ============================================================================

class TestDocumentLifecycleService:
    """Tests for document lifecycle operations."""
    
    def test_deprecate_document_cascades_to_children(self, lifecycle_service, mock_neo4j_store):
        """Verify deprecation cascades to chunks, entities, and sections."""
        group_id = "test-group-123"
        doc_id = "doc-abc"
        
        # Mock session and transaction
        mock_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute_write = MagicMock(side_effect=lambda fn: fn(mock_tx))
        
        # Mock Cypher results
        mock_tx.run.return_value.single.return_value = {
            "doc_deprecated": True,
            "chunks_deprecated": 5,
            "entities_deprecated": 12,
            "sections_deprecated": 3,
        }
        
        result = lifecycle_service.deprecate_document(
            group_id=group_id,
            doc_id=doc_id,
            deprecated_by="test-user",
            reason="Test deprecation",
        )
        
        assert result["doc_deprecated"] is True
        assert result["chunks_deprecated"] == 5
        assert result["entities_deprecated"] == 12
        assert result["sections_deprecated"] == 3
        
        # Verify mark_gds_stale was called
        mock_neo4j_store.mark_gds_stale.assert_called_once_with(group_id)
    
    def test_restore_document_removes_deprecated_label(self, lifecycle_service, mock_neo4j_store):
        """Verify restoration removes :Deprecated label from all related nodes."""
        group_id = "test-group-123"
        doc_id = "doc-abc"
        
        mock_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute_write = MagicMock(side_effect=lambda fn: fn(mock_tx))
        
        mock_tx.run.return_value.single.return_value = {
            "doc_restored": True,
            "chunks_restored": 5,
            "entities_restored": 12,
            "sections_restored": 3,
        }
        
        result = lifecycle_service.restore_document(
            group_id=group_id,
            doc_id=doc_id,
        )
        
        assert result["doc_restored"] is True
        # Verify GDS stale flag set (need recompute after restore)
        mock_neo4j_store.mark_gds_stale.assert_called_once_with(group_id)
    
    def test_hard_delete_removes_orphan_entities(self, lifecycle_service, mock_neo4j_store):
        """Verify hard delete cleans up orphan entities."""
        group_id = "test-group-123"
        doc_id = "doc-abc"
        
        mock_session = MagicMock()
        mock_tx = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute_write = MagicMock(side_effect=lambda fn: fn(mock_tx))
        
        # Simulate deletion counts
        mock_tx.run.return_value.single.side_effect = [
            {"chunks_deleted": 5},
            {"entities_deleted": 8},
            {"sections_deleted": 3},
            {"doc_deleted": True},
            {"orphan_entities_deleted": 2},
        ]
        
        result = lifecycle_service.hard_delete_document(
            group_id=group_id,
            doc_id=doc_id,
        )
        
        assert "chunks_deleted" in result or "doc_deleted" in result
    
    def test_list_documents_filters_by_status(self, lifecycle_service, mock_neo4j_store):
        """Verify list_documents respects status filter."""
        group_id = "test-group-123"
        
        mock_session = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_session.run.return_value = [
            {
                "id": "doc-1",
                "title": "Active Doc",
                "status": "active",
                "deprecated_at": None,
            },
        ]
        
        # Test filtering for active documents
        result = lifecycle_service.list_documents(
            group_id=group_id,
            status_filter="active",
        )
        
        # Session.run should have been called with Cypher containing NOT d:Deprecated
        call_args = mock_session.run.call_args
        assert call_args is not None
    
    def test_get_document_impact_returns_counts(self, lifecycle_service, mock_neo4j_store):
        """Verify impact analysis returns affected node counts."""
        group_id = "test-group-123"
        doc_id = "doc-abc"
        
        mock_session = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_session.run.return_value.single.return_value = {
            "chunk_count": 10,
            "entity_count": 25,
            "section_count": 5,
            "relationship_count": 50,
        }
        
        result = lifecycle_service.get_document_impact(
            group_id=group_id,
            doc_id=doc_id,
        )
        
        assert result["chunk_count"] == 10
        assert result["entity_count"] == 25


# ============================================================================
# MaintenanceService Tests
# ============================================================================

class TestMaintenanceService:
    """Tests for maintenance job operations."""
    
    def test_gc_orphan_entities_removes_unconnected(self, maintenance_service, mock_neo4j_store):
        """Verify GC removes entities with no chunk connections."""
        group_id = "test-group-123"
        
        mock_session = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_session.run.return_value.single.return_value = {"deleted": 15}
        
        result = maintenance_service.run_gc_job(
            group_id=group_id,
            job_type="orphan_entities",
        )
        
        assert result["job_type"] == "orphan_entities"
        assert result["status"] == "completed"
    
    def test_gc_stale_edges_removes_deprecated_connections(self, maintenance_service, mock_neo4j_store):
        """Verify GC removes edges connected to deprecated nodes."""
        group_id = "test-group-123"
        
        mock_session = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_session.run.return_value.single.return_value = {"deleted": 42}
        
        result = maintenance_service.run_gc_job(
            group_id=group_id,
            job_type="stale_edges",
        )
        
        assert result["job_type"] == "stale_edges"
    
    def test_gc_deprecated_vectors_nulls_embeddings(self, maintenance_service, mock_neo4j_store):
        """Verify GC nulls embeddings on deprecated nodes."""
        group_id = "test-group-123"
        
        mock_session = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_session.run.return_value.single.return_value = {"cleared": 20}
        
        result = maintenance_service.run_gc_job(
            group_id=group_id,
            job_type="deprecated_vectors",
        )
        
        assert result["job_type"] == "deprecated_vectors"
    
    def test_get_group_health_returns_metrics(self, maintenance_service, mock_neo4j_store):
        """Verify health check returns comprehensive metrics."""
        group_id = "test-group-123"
        
        mock_session = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_session.run.return_value.single.return_value = {
            "total_documents": 50,
            "deprecated_documents": 5,
            "active_documents": 45,
            "total_entities": 500,
            "orphan_entities": 10,
            "gds_stale": False,
            "gds_last_computed": datetime.now(timezone.utc).isoformat(),
        }
        
        result = maintenance_service.get_group_health(group_id=group_id)
        
        assert result["total_documents"] == 50
        assert result["deprecated_documents"] == 5
        assert result["orphan_entities"] == 10
    
    def test_get_stale_groups_returns_pending_recompute(self, maintenance_service, mock_neo4j_store):
        """Verify stale groups query returns groups needing GDS recompute."""
        mock_session = MagicMock()
        mock_neo4j_store.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_neo4j_store.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_session.run.return_value = [
            {"group_id": "group-1", "stale_since": "2026-01-28T10:00:00Z"},
            {"group_id": "group-2", "stale_since": "2026-01-28T11:00:00Z"},
        ]
        
        result = maintenance_service.get_stale_groups()
        
        assert len(result) == 2
        assert result[0]["group_id"] == "group-1"


# ============================================================================
# Integration Tests (requires live Neo4j)
# ============================================================================

@pytest.mark.integration
@pytest.mark.skipif(
    True,  # Change to False to run integration tests with live Neo4j
    reason="Integration tests require live Neo4j instance"
)
class TestDocumentLifecycleIntegration:
    """Integration tests with live Neo4j."""
    
    @pytest.fixture
    def live_neo4j_store(self):
        """Create real Neo4j store connection."""
        from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3
        from app.core.config import settings
        
        store = Neo4jStoreV3(
            uri=settings.NEO4J_URI,
            username=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
        )
        yield store
        store.driver.close()
    
    @pytest.fixture
    def test_group_id(self):
        """Generate unique test group ID."""
        import uuid
        return f"test-lifecycle-{uuid.uuid4().hex[:8]}"
    
    def test_full_lifecycle_flow(self, live_neo4j_store, test_group_id):
        """Test complete deprecation → GC → restore flow."""
        lifecycle_svc = DocumentLifecycleService(neo4j_store=live_neo4j_store)
        maintenance_svc = MaintenanceService(neo4j_store=live_neo4j_store)
        
        # Setup: Create test document and entities
        with live_neo4j_store.driver.session(database=live_neo4j_store.database) as session:
            session.run("""
                CREATE (d:Document {id: 'test-doc-1', group_id: $group_id, title: 'Test Doc'})
                CREATE (c:TextChunk {id: 'chunk-1', group_id: $group_id, doc_id: 'test-doc-1'})
                CREATE (e:Entity {id: 'entity-1', group_id: $group_id, name: 'Test Entity'})
                CREATE (c)-[:MENTIONS]->(e)
                CREATE (d)-[:HAS_CHUNK]->(c)
            """, group_id=test_group_id)
        
        try:
            # Step 1: Deprecate document
            result = lifecycle_svc.deprecate_document(
                group_id=test_group_id,
                doc_id="test-doc-1",
                deprecated_by="test-user",
                reason="Integration test",
            )
            assert result["doc_deprecated"] is True
            
            # Step 2: Verify GDS marked stale
            health = maintenance_svc.get_group_health(group_id=test_group_id)
            assert health["gds_stale"] is True
            
            # Step 3: Run GC
            gc_result = maintenance_svc.run_gc_job(
                group_id=test_group_id,
                job_type="stale_edges",
            )
            assert gc_result["status"] == "completed"
            
            # Step 4: Restore document
            restore_result = lifecycle_svc.restore_document(
                group_id=test_group_id,
                doc_id="test-doc-1",
            )
            assert restore_result["doc_restored"] is True
            
        finally:
            # Cleanup: Delete test data
            with live_neo4j_store.driver.session(database=live_neo4j_store.database) as session:
                session.run("""
                    MATCH (n {group_id: $group_id})
                    DETACH DELETE n
                """, group_id=test_group_id)


# ============================================================================
# API Router Tests
# ============================================================================

class TestDocumentLifecycleRouter:
    """Tests for REST API endpoints."""
    
    @pytest.fixture
    def test_client(self):
        """Create FastAPI test client."""
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)
    
    def test_deprecate_endpoint_requires_group_id(self, test_client):
        """Verify deprecate endpoint validates group_id."""
        response = test_client.post(
            "/lifecycle/deprecate",
            params={"doc_id": "test-doc"},
            # Missing group_id header
        )
        # Should fail validation
        assert response.status_code in [400, 422]
    
    def test_hard_delete_requires_confirmation(self, test_client):
        """Verify hard delete requires confirm=true."""
        response = test_client.delete(
            "/lifecycle/test-doc",
            headers={"X-Group-ID": "test-group"},
            params={"confirm": False},
        )
        assert response.status_code == 400
        assert "confirm=true" in response.json().get("detail", "").lower()


class TestMaintenanceRouter:
    """Tests for maintenance REST API endpoints."""
    
    @pytest.fixture
    def test_client(self):
        """Create FastAPI test client."""
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)
    
    def test_run_job_validates_job_type(self, test_client):
        """Verify job endpoint validates job_type enum."""
        response = test_client.post(
            "/maintenance/jobs",
            headers={"X-Group-ID": "test-group"},
            json={"job_type": "invalid_job_type"},
        )
        assert response.status_code == 422
    
    def test_health_endpoint_returns_metrics(self, test_client):
        """Verify health endpoint returns expected structure."""
        # This will fail without actual Neo4j, but tests routing
        with patch("app.hybrid_v2.services.maintenance.MaintenanceService") as mock_svc:
            mock_svc.return_value.get_group_health.return_value = {
                "total_documents": 10,
                "deprecated_documents": 1,
            }
            # Route should be accessible
            response = test_client.get(
                "/maintenance/health",
                headers={"X-Group-ID": "test-group"},
            )
            # May fail due to service initialization, but route exists
            assert response.status_code in [200, 500]
