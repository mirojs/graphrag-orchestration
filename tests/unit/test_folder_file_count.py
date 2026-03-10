"""Tests for the folder file-count endpoint."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api_gateway.routers.folders import router, get_partition_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app(blob_manager=None) -> FastAPI:
    """Create a minimal FastAPI app with the folders router and mocked deps."""
    app = FastAPI()
    app.include_router(router)
    if blob_manager is not None:
        app.state.user_blob_manager = blob_manager
    return app


def _mock_neo4j_session(single_return):
    """Create a mock Neo4j session context manager returning a single record."""
    mock_record = MagicMock()
    if single_return is not None:
        mock_record.__getitem__ = lambda self, key: single_return.get(key)
    mock_result = MagicMock()
    mock_result.single.return_value = mock_record if single_return is not None else None
    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    return mock_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

GRAPH_SERVICE_PATH = "src.api_gateway.routers.folders.GraphService"


@patch(GRAPH_SERVICE_PATH)
def test_file_count_single_folder(mock_graph_cls):
    """Endpoint returns blob count for a leaf folder with no subfolders."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        {"folder_names": ["Contracts"]}
    )
    mock_graph_cls.return_value.driver = mock_driver

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(return_value=[
        {"name": "file1.pdf", "url": "u", "full_path": "g/Contracts/file1.pdf"},
        {"name": "file2.pdf", "url": "u", "full_path": "g/Contracts/file2.pdf"},
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/folder-123/file-count")

    assert resp.status_code == 200
    body = resp.json()
    assert body["folder_id"] == "folder-123"
    assert body["count"] == 2
    blob_manager.list_blobs_recursive.assert_awaited_once_with("test-group", "Contracts")


@patch(GRAPH_SERVICE_PATH)
def test_file_count_aggregates_across_subfolders(mock_graph_cls):
    """Endpoint sums blob counts across parent + all descendant subfolders."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        {"folder_names": ["Parent", "Child", "Grandchild"]}
    )
    mock_graph_cls.return_value.driver = mock_driver

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(side_effect=[
        [{"name": "a.pdf", "url": "u", "full_path": "g/Parent/a.pdf"}],
        [{"name": "b.pdf", "url": "u", "full_path": "g/Child/b.pdf"},
         {"name": "c.pdf", "url": "u", "full_path": "g/Child/c.pdf"}],
        [],
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/parent-id/file-count")

    assert resp.status_code == 200
    assert resp.json()["count"] == 3  # 1 + 2 + 0
    assert blob_manager.list_blobs_recursive.await_count == 3


@patch(GRAPH_SERVICE_PATH)
def test_file_count_parent_empty_subfolders_have_files(mock_graph_cls):
    """The exact CTA bug scenario: parent has 0 files, children have files."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        {"folder_names": ["insurance_claims_review", "input_docs", "reference_docs"]}
    )
    mock_graph_cls.return_value.driver = mock_driver

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(side_effect=[
        [],                                                                      # parent: 0
        [{"name": "claim1.pdf", "url": "u", "full_path": "g/input_docs/claim1.pdf"},
         {"name": "claim2.pdf", "url": "u", "full_path": "g/input_docs/claim2.pdf"}],  # 2
        [{"name": "ref1.pdf", "url": "u", "full_path": "g/reference_docs/ref1.pdf"},
         {"name": "ref2.pdf", "url": "u", "full_path": "g/reference_docs/ref2.pdf"},
         {"name": "ref3.pdf", "url": "u", "full_path": "g/reference_docs/ref3.pdf"},
         {"name": "ref4.pdf", "url": "u", "full_path": "g/reference_docs/ref4.pdf"}],  # 4
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/parent-id/file-count")

    assert resp.status_code == 200
    assert resp.json()["count"] == 6  # 0 + 2 + 4 — CTA should show!


@patch(GRAPH_SERVICE_PATH)
def test_file_count_returns_zero_for_empty_tree(mock_graph_cls):
    """Endpoint returns count=0 when folder and all subfolders have no blobs."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        {"folder_names": ["Empty"]}
    )
    mock_graph_cls.return_value.driver = mock_driver

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(return_value=[])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/folder-empty/file-count")

    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@patch(GRAPH_SERVICE_PATH)
def test_file_count_404_when_folder_not_found(mock_graph_cls):
    """Endpoint returns 404 when folder doesn't exist in Neo4j."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session({"folder_names": []})
    mock_graph_cls.return_value.driver = mock_driver

    app = _build_app(MagicMock())
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/nonexistent/file-count")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@patch(GRAPH_SERVICE_PATH)
def test_file_count_400_when_no_blob_manager(mock_graph_cls):
    """Endpoint returns 400 when blob storage is not configured."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        {"folder_names": ["SomeFolder"]}
    )
    mock_graph_cls.return_value.driver = mock_driver

    app = _build_app()  # no blob_manager
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/folder-123/file-count")

    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"].lower()
