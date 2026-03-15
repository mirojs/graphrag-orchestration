"""Tests for the folder file-count endpoint."""

from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api_gateway.routers.folders import router, get_partition_id

GRAPH_SERVICE_PATH = "src.api_gateway.routers.folders.GraphService"
RESOLVE_PATH = "src.api_gateway.routers.files._resolve_folder_path"


def _build_app(blob_manager=None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    if blob_manager is not None:
        app.state.user_blob_manager = blob_manager
    return app


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_single_folder(mock_graph_cls, mock_resolve):
    """Endpoint returns blob count for a leaf folder."""
    mock_resolve.return_value = "Contracts"

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(return_value=[
        {"name": "file1.pdf"}, {"name": "file2.pdf"},
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    resp = TestClient(app).get("/folders/folder-123/file-count")

    assert resp.status_code == 200
    assert resp.json() == {"folder_id": "folder-123", "count": 2, "subfolders": []}
    blob_manager.list_blobs_recursive.assert_awaited_once_with("test-group", "Contracts")


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_parent_includes_subfolders(mock_graph_cls, mock_resolve):
    """Recursive ADLS listing on parent path includes all subfolder files."""
    mock_resolve.return_value = "insurance_claims_review"

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(return_value=[
        {"name": "accident_report.pdf"}, {"name": "repair_estimate.pdf"},
        {"name": "policy_driver_1.pdf"}, {"name": "policy_driver_2.pdf"},
        {"name": "ref3.pdf"}, {"name": "ref4.pdf"},
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    resp = TestClient(app).get("/folders/parent-id/file-count")

    assert resp.status_code == 200
    assert resp.json()["count"] == 6


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_returns_zero_for_empty_folder(mock_graph_cls, mock_resolve):
    mock_resolve.return_value = "Empty"

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(return_value=[])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    resp = TestClient(app).get("/folders/folder-empty/file-count")

    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_404_when_folder_not_found(mock_graph_cls, mock_resolve):
    mock_resolve.return_value = None

    app = _build_app(MagicMock())
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    resp = TestClient(app).get("/folders/nonexistent/file-count")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_400_when_no_blob_manager(mock_graph_cls, mock_resolve):
    mock_resolve.return_value = "SomeFolder"

    app = _build_app()  # no blob_manager
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    resp = TestClient(app).get("/folders/folder-123/file-count")

    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"].lower()
