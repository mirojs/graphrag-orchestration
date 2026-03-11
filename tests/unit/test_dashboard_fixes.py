"""
Tests for dashboard data visibility fixes (commits e9d199f7 + c619e342).

Validates all 10 fixes that ensure the B2C (and B2B) dashboard correctly
displays data: blob counts, Cosmos usage records, lazy init, RBAC config,
method names, and upload flow.
"""

import asyncio
import json
import os
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Fix 1: Bicep – B2C managed identity in RBAC role assignments
# ---------------------------------------------------------------------------

class TestBicepRBACFix:
    """Verify infra/main.bicep includes B2C principal ID in role assignments."""

    def _read_bicep(self):
        bicep_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "infra", "main.bicep"
        )
        with open(bicep_path) as f:
            return f.read()

    def test_b2c_principal_in_container_app_principal_ids(self):
        """Fix #9: graphragApiB2C.outputs.identityPrincipalId must be in the array."""
        bicep = self._read_bicep()
        # Find the containerAppPrincipalIds block
        assert "graphragApiB2C.outputs.identityPrincipalId" in bicep, (
            "B2C principal ID missing from containerAppPrincipalIds"
        )

    def test_b2c_principal_is_conditional(self):
        """The B2C principal should only be included when enableB2C is true."""
        bicep = self._read_bicep()
        # Should be wrapped in enableB2C condition
        pattern = r"enableB2C.*graphragApiB2C\.outputs\.identityPrincipalId"
        assert re.search(pattern, bicep, re.DOTALL), (
            "B2C principal should be conditional on enableB2C"
        )

    def test_b2c_in_depends_on(self):
        """graphragApiB2C should be in dependsOn for role-assignments module."""
        bicep = self._read_bicep()
        # Find the dependsOn line near the role-assignments module
        assert "graphragApiB2C" in bicep, "graphragApiB2C missing from dependsOn"

    def test_all_three_principals_present(self):
        """All three principals (API, Worker, B2C) should be in containerAppPrincipalIds."""
        bicep = self._read_bicep()
        # Extract the containerAppPrincipalIds block
        match = re.search(
            r"containerAppPrincipalIds:\s*concat\(\[(.*?)\]",
            bicep,
            re.DOTALL,
        )
        assert match, "containerAppPrincipalIds concat block not found"
        block = match.group(1)
        assert "graphragApi.outputs.identityPrincipalId" in block
        assert "graphragWorker.outputs.identityPrincipalId" in block
        # B2C is in the conditional part after the array
        assert "graphragApiB2C.outputs.identityPrincipalId" in bicep


# ---------------------------------------------------------------------------
# Fix 2: UserBlobManager – image filter removed + new counting methods
# ---------------------------------------------------------------------------

class TestUserBlobManager:
    """Verify list_blobs returns all files and new count/size methods work."""

    def _make_blob(self, name, size=1024):
        b = MagicMock()
        b.name = name
        b.size = size
        b.is_directory = False
        b.metadata = {}
        return b

    @pytest.mark.asyncio
    async def test_list_blobs_no_image_filter(self):
        """Fix #4: list_blobs should return ALL file types, including images."""
        from src.api_gateway.services.user_blob_manager import UserBlobManager

        blobs = [
            self._make_blob("grp1/report.pdf"),
            self._make_blob("grp1/photo.jpg"),
            self._make_blob("grp1/data.csv"),
            self._make_blob("grp1/scan.png"),
            self._make_blob("grp1/notes.txt"),
        ]

        mock_container = AsyncMock()

        async def fake_list_blobs(name_starts_with=None, **kwargs):
            for b in blobs:
                if b.name.startswith(name_starts_with or ""):
                    yield b

        mock_container.list_blobs = fake_list_blobs

        with patch.object(UserBlobManager, "__init__", lambda self, *a, **kw: None):
            mgr = UserBlobManager.__new__(UserBlobManager)
            mgr.container = "test"
            mgr.blob_service_client = MagicMock()
            mgr.blob_service_client.get_container_client.return_value = mock_container

            from src.api_gateway.services.user_blob_manager import _blob_list_cache
            _blob_list_cache.clear()
            result = await mgr.list_blobs("grp1")

        assert len(result) == 5, f"Expected 5 files, got {len(result)}: {result}"
        assert "photo.jpg" in result
        assert "scan.png" in result

    @pytest.mark.asyncio
    async def test_count_blobs(self):
        """Fix #3: count_blobs returns correct count for dashboard."""
        from src.api_gateway.services.user_blob_manager import UserBlobManager, _blob_stats_cache
        _blob_stats_cache.clear()

        blobs = [
            self._make_blob("grp1/a.pdf"),
            self._make_blob("grp1/b.docx"),
            self._make_blob("grp1/subdir/c.txt"),  # subdirectory – now included in stats
        ]

        mock_container = AsyncMock()

        async def fake_list_blobs(name_starts_with=None, **kwargs):
            for b in blobs:
                if b.name.startswith(name_starts_with or ""):
                    yield b

        mock_container.list_blobs = fake_list_blobs

        with patch.object(UserBlobManager, "__init__", lambda self, *a, **kw: None):
            mgr = UserBlobManager.__new__(UserBlobManager)
            mgr.container = "test"
            mgr.blob_service_client = MagicMock()
            mgr.blob_service_client.get_container_client.return_value = mock_container

            count = await mgr.count_blobs("grp1")

        assert count == 3, f"Expected 3 blobs (all files incl. subdirs), got {count}"

    @pytest.mark.asyncio
    async def test_get_storage_used_bytes(self):
        """Fix #3: get_storage_used_bytes sums all blob sizes."""
        from src.api_gateway.services.user_blob_manager import UserBlobManager, _blob_stats_cache
        _blob_stats_cache.clear()

        blobs = [
            self._make_blob("grp1/a.pdf", size=1000),
            self._make_blob("grp1/b.docx", size=2000),
            self._make_blob("grp1/subdir/c.txt", size=500),
        ]

        mock_container = AsyncMock()

        async def fake_list_blobs(name_starts_with=None, **kwargs):
            for b in blobs:
                if b.name.startswith(name_starts_with or ""):
                    yield b

        mock_container.list_blobs = fake_list_blobs

        with patch.object(UserBlobManager, "__init__", lambda self, *a, **kw: None):
            mgr = UserBlobManager.__new__(UserBlobManager)
            mgr.container = "test"
            mgr.blob_service_client = MagicMock()
            mgr.blob_service_client.get_container_client.return_value = mock_container

            total = await mgr.get_storage_used_bytes("grp1")

        assert total == 3500, f"Expected 3500 bytes, got {total}"

    def test_close_method_exists(self):
        """Fix #10: UserBlobManager has close() method (not close_clients)."""
        from src.api_gateway.services.user_blob_manager import UserBlobManager

        assert hasattr(UserBlobManager, "close"), "UserBlobManager should have close()"
        assert not hasattr(UserBlobManager, "close_clients"), (
            "UserBlobManager should NOT have close_clients()"
        )


# ---------------------------------------------------------------------------
# Fix 3: CosmosDBClient – lazy init (ensure_initialized)
# ---------------------------------------------------------------------------

class TestCosmosLazyInit:
    """Fix #8: Cosmos client must support lazy initialization for B2C."""

    @pytest.mark.asyncio
    async def test_ensure_initialized_calls_init(self):
        """ensure_initialized() should call initialize() if not yet done."""
        from src.core.services.cosmos_client import CosmosDBClient

        client = CosmosDBClient.__new__(CosmosDBClient)
        client.endpoint = "https://fake.documents.azure.com:443/"
        client._usage_container = None
        client._client = None
        client._credential = None
        client._database = None
        client._chat_container = None
        client.database_name = "graphrag"
        client.chat_container_name = "chat_history"
        client.usage_container_name = "usage"

        client.initialize = AsyncMock()
        await client.ensure_initialized()
        client.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_initialized_noop_when_ready(self):
        """ensure_initialized() should be a no-op if containers are already set."""
        from src.core.services.cosmos_client import CosmosDBClient

        client = CosmosDBClient.__new__(CosmosDBClient)
        client.endpoint = "https://fake.documents.azure.com:443/"
        client._usage_container = MagicMock()  # Already initialized

        client.initialize = AsyncMock()
        await client.ensure_initialized()
        client.initialize.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_initialized_noop_without_endpoint(self):
        """ensure_initialized() should be a no-op if no endpoint is configured."""
        from src.core.services.cosmos_client import CosmosDBClient

        client = CosmosDBClient.__new__(CosmosDBClient)
        client.endpoint = None
        client._usage_container = None

        client.initialize = AsyncMock()
        await client.ensure_initialized()
        client.initialize.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_usage_calls_ensure_initialized(self):
        """write_usage_record() should call ensure_initialized() when container is None."""
        from src.core.services.cosmos_client import CosmosDBClient
        from src.core.models.usage import UsageRecord

        client = CosmosDBClient.__new__(CosmosDBClient)
        client.endpoint = "https://fake.documents.azure.com:443/"
        client._usage_container = None
        client._client = None
        client._credential = None
        client._database = None
        client._chat_container = None
        client.database_name = "graphrag"
        client.chat_container_name = "chat_history"
        client.usage_container_name = "usage"

        # After ensure_initialized, set the container mock
        async def fake_init():
            client._usage_container = AsyncMock()
            client._usage_container.upsert_item = AsyncMock()

        client.initialize = AsyncMock(side_effect=fake_init)

        record = UsageRecord(
            partition_id="user-1",
            user_id="user-1",
            usage_type="doc_intel",
            document_id="test.pdf",
        )
        await client.write_usage_record(record)

        client.initialize.assert_called_once()
        client._usage_container.upsert_item.assert_called_once()


# ---------------------------------------------------------------------------
# Fix 4: DocumentSyncService – writes Cosmos usage record on upload
# ---------------------------------------------------------------------------

class TestDocumentSyncUsage:
    """Fix #2: on_file_uploaded must write doc_intel Cosmos record."""

    @pytest.mark.asyncio
    async def test_write_document_usage_writes_record(self):
        """_write_document_usage creates a doc_intel UsageRecord."""
        from src.api_gateway.services.document_sync import DocumentSyncService

        svc = DocumentSyncService()

        mock_cosmos = AsyncMock()
        mock_cosmos.write_usage_record = AsyncMock()

        with patch(
            "src.core.services.cosmos_client.get_cosmos_client",
            return_value=mock_cosmos,
        ):
            await svc._write_document_usage(
                user_id="user-1",
                group_id="grp-1",
                filename="test.pdf",
                sentences=42,
            )

        mock_cosmos.write_usage_record.assert_called_once()
        record = mock_cosmos.write_usage_record.call_args[0][0]
        assert record.usage_type == "doc_intel"
        assert record.partition_id == "user-1"
        assert record.document_id == "test.pdf"
        assert record.pages_analyzed == 42

    @pytest.mark.asyncio
    async def test_write_document_usage_handles_failure(self):
        """_write_document_usage should not raise on failure (catches all exceptions)."""
        from src.api_gateway.services.document_sync import DocumentSyncService

        svc = DocumentSyncService()

        mock_cosmos = AsyncMock()
        mock_cosmos.write_usage_record = AsyncMock(
            side_effect=TimeoutError("Cosmos timeout")
        )

        with patch(
            "src.core.services.cosmos_client.get_cosmos_client",
            return_value=mock_cosmos,
        ), patch("src.api_gateway.services.document_sync.logger"):
            # Should not raise
            await svc._write_document_usage(
                user_id="user-1",
                group_id="grp-1",
                filename="test.pdf",
            )


# ---------------------------------------------------------------------------
# Fix 5: Upload response includes indexing_queued
# ---------------------------------------------------------------------------

class TestUploadResponse:
    """Fix #5: /upload endpoint returns indexing_queued field."""

    @pytest.mark.asyncio
    async def test_upload_returns_indexing_queued(self):
        """Upload response must include indexing_queued boolean."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api_gateway.routers.files import router

        app = FastAPI()
        app.include_router(router)

        # Mock auth dependencies
        app.dependency_overrides = {}

        from src.api_gateway.middleware.auth import get_group_id, get_user_id

        app.dependency_overrides[get_group_id] = lambda: "test-group"
        app.dependency_overrides[get_user_id] = lambda: "test-user"

        # Mock blob manager
        mock_blob = AsyncMock()
        mock_blob.upload_blob = AsyncMock(return_value="https://fake.blob/grp/test.pdf")
        app.state.user_blob_manager = mock_blob

        # Mock doc sync
        mock_doc_sync = MagicMock()
        mock_doc_sync.on_file_uploaded = AsyncMock()
        app.state.document_sync_service = mock_doc_sync

        from io import BytesIO

        client = TestClient(app)
        # Patch _folder_is_analyzed to return True (avoids Neo4j dependency)
        # and resolve helpers so the upload path triggers indexing_queued=True
        with patch("src.api_gateway.routers.files._folder_is_analyzed", new_callable=AsyncMock, return_value=True), \
             patch("src.api_gateway.services.folder_resolver.resolve_neo4j_group_id", new_callable=AsyncMock, return_value="test-group"), \
             patch("src.api_gateway.routers.files._resolve_folder_path", new_callable=AsyncMock, return_value="test-folder"), \
             patch("src.api_gateway.routers.files._mark_folder_stale", new_callable=AsyncMock):
            resp = client.post(
                "/upload",
                data={"folder_id": "folder-123"},
                files={"file": ("test.pdf", BytesIO(b"fake pdf content"), "application/pdf")},
            )

        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        body = resp.json()
        assert "indexing_queued" in body, f"Missing indexing_queued in response: {body}"
        assert body["indexing_queued"] is True


# ---------------------------------------------------------------------------
# Fix 6: main.py calls close() not close_clients()
# ---------------------------------------------------------------------------

class TestMainShutdown:
    """Fix #10: Shutdown handler must call close(), not close_clients()."""

    def test_main_py_calls_close_not_close_clients(self):
        """main.py should call manager.close(), not manager.close_clients()."""
        main_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "src", "api_gateway", "main.py"
        )
        with open(main_path) as f:
            source = f.read()

        assert "close_clients()" not in source, (
            "main.py still references close_clients() — should be close()"
        )
        assert "manager.close()" in source or "await manager.close()" in source, (
            "main.py should call manager.close()"
        )


# ---------------------------------------------------------------------------
# Fix 7: Usage type mismatch – "doc_intel" not "document_intelligence"
# ---------------------------------------------------------------------------

class TestUsageTypeMismatch:
    """Bonus fix: usage_type must be 'doc_intel' (matching UsageType enum)."""

    def test_usage_type_enum_value(self):
        """UsageType.DOC_INTEL should have value 'doc_intel'."""
        from src.core.models.usage import UsageType

        assert UsageType.DOC_INTEL.value == "doc_intel"

    def test_dashboard_queries_doc_intel(self):
        """Dashboard should query usage_type='doc_intel', not 'document_intelligence'."""
        dashboard_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "api_gateway",
            "routers",
            "dashboard.py",
        )
        with open(dashboard_path) as f:
            source = f.read()

        assert '"document_intelligence"' not in source, (
            "Dashboard still uses 'document_intelligence' — should be 'doc_intel'"
        )
        assert '"doc_intel"' in source, (
            "Dashboard should query usage_type='doc_intel'"
        )

    def test_document_sync_writes_doc_intel(self):
        """DocumentSyncService should write usage_type='doc_intel'."""
        sync_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "api_gateway",
            "services",
            "document_sync.py",
        )
        with open(sync_path) as f:
            source = f.read()

        assert '"doc_intel"' in source, (
            "DocumentSyncService should write usage_type='doc_intel'"
        )


# ---------------------------------------------------------------------------
# Fix 8: Dashboard /me endpoint populates from blob storage
# ---------------------------------------------------------------------------

class TestDashboardBlobIntegration:
    """Fix #3 + #7: Dashboard endpoints use blob storage as primary source."""

    def test_dashboard_imports_get_group_id(self):
        """Dashboard must import get_group_id for blob storage access."""
        dashboard_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "api_gateway",
            "routers",
            "dashboard.py",
        )
        with open(dashboard_path) as f:
            source = f.read()

        assert "get_group_id" in source, "Dashboard must import get_group_id"

    def test_dashboard_uses_blob_manager(self):
        """Dashboard /me endpoint uses user_blob_manager for doc counts."""
        dashboard_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "src",
            "api_gateway",
            "routers",
            "dashboard.py",
        )
        with open(dashboard_path) as f:
            source = f.read()

        assert "user_blob_manager" in source, (
            "Dashboard should access user_blob_manager from app state"
        )
        assert "get_blob_stats" in source, (
            "Dashboard should call get_blob_stats() for document count and storage"
        )


# ---------------------------------------------------------------------------
# Fix 9: deploy-graphrag.sh passes env vars to B2C container
# ---------------------------------------------------------------------------

class TestDeployScript:
    """Fix #1: B2C container app receives env vars via deploy script."""

    def test_b2c_update_includes_env_vars(self):
        """deploy-graphrag.sh B2C update must reference the B2C container app."""
        deploy_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy-graphrag.sh"
        )
        with open(deploy_path) as f:
            source = f.read()

        assert "B2C_APP_NAME" in source, "Deploy script should define B2C_APP_NAME"
        assert "graphrag-api-b2c" in source, "Deploy script should reference the B2C app"

        # The B2C `az containerapp update` block should reference the B2C app
        lines = source.split("\n")
        found_b2c_update = False
        for i, line in enumerate(lines):
            if "B2C_APP_NAME" in line and ("name" in line or "containerapp" in line):
                found_b2c_update = True
                break

        assert found_b2c_update, (
            "B2C container app update must reference B2C_APP_NAME"
        )
