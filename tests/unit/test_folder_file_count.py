"""Tests for the folder file-count endpoint."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api_gateway.routers.folders import router, get_partition_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GRAPH_SERVICE_PATH = "src.api_gateway.routers.folders.GraphService"
RESOLVE_PATH = "src.api_gateway.routers.files._resolve_folder_path"


def _build_app(blob_manager=None) -> FastAPI:
    """Create a minimal FastAPI app with the folders router and mocked deps."""
    app = FastAPI()
    app.include_router(router)
    if blob_manager is not None:
        app.state.user_blob_manager = blob_manager
    return app


def _mock_neo4j_session(items):
    """Create a mock Neo4j session that returns ``items`` for the tree query.

    ``items`` should be a list of {id, name} dicts, or None for 404 case.
    """
    mock_record = MagicMock()
    if items is not None:
        mock_record.__getitem__ = lambda self, key: items if key == "items" else None
        mock_record.get = lambda key, default=None: items if key == "items" else default
    else:
        mock_record = None

    mock_result = MagicMock()
    mock_result.single.return_value = mock_record

    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    return mock_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_single_folder(mock_graph_cls, mock_resolve):
    """Endpoint returns blob count for a leaf folder with no subfolders."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        [{"id": "folder-123", "name": "Contracts"}]
    )
    mock_graph_cls.return_value.driver = mock_driver

    mock_resolve.return_value = "Contracts"

    blob_manager = MagicMock()
    blob_manager.list_blobs_recursive = AsyncMock(return_value=[
        {"name": "file1.pdf"}, {"name": "file2.pdf"},
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/folder-123/file-count")

    assert resp.status_code == 200
    body = resp.json()
    assert body["folder_id"] == "folder-123"
    assert body["count"] == 2


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_aggregates_across_subfolders(mock_graph_cls, mock_resolve):
    """Endpoint sums blob counts across parent + all descendant subfolders."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session([
        {"id": "parent-id", "name": "Parent"},
        {"id": "child-id", "name": "Child"},
        {"id": "grandchild-id", "name": "Grandchild"},
    ])
    mock_graph_cls.return_value.driver = mock_driver

    mock_resolve.side_effect = ["Parent", "Parent/Child", "Parent/Child/Grandchild"]

    blob_manager = MagicMock()
    # Hierarchical paths find blobs directly (no fallback needed)
    blob_manager.list_blobs_recursive = AsyncMock(side_effect=[
        [{"name": "a.pdf"}],                            # Parent (hierarchical) → 1
        [{"name": "b.pdf"}, {"name": "c.pdf"}],         # Parent/Child (hierarchical) → 2
        [],                                              # Parent/Child/Grandchild (hierarchical) → 0
        [],                                              # Grandchild (flat fallback) → 0
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/parent-id/file-count")

    assert resp.status_code == 200
    assert resp.json()["count"] == 3  # 1 + 2 + 0


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_parent_empty_subfolders_have_files(mock_graph_cls, mock_resolve):
    """The exact CTA bug scenario: parent has 0 files, children have files.

    Uses legacy fallback — hierarchical path returns 0, flat name finds blobs.
    """
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session([
        {"id": "parent-id", "name": "insurance_claims_review"},
        {"id": "input-id", "name": "input_docs"},
        {"id": "ref-id", "name": "reference_docs"},
    ])
    mock_graph_cls.return_value.driver = mock_driver

    mock_resolve.side_effect = [
        "insurance_claims_review",
        "insurance_claims_review/input_docs",
        "insurance_claims_review/reference_docs",
    ]

    blob_manager = MagicMock()
    # Hierarchical paths return 0, flat names find blobs (legacy fallback)
    blob_manager.list_blobs_recursive = AsyncMock(side_effect=[
        [],  # insurance_claims_review (hierarchical) → 0
        [],  # insurance_claims_review (flat fallback, same name) → 0
        [],  # insurance_claims_review/input_docs (hierarchical) → 0
        [{"name": "claim1.pdf"}, {"name": "claim2.pdf"}],  # input_docs (flat fallback) → 2
        [],  # insurance_claims_review/reference_docs (hierarchical) → 0
        [{"name": "ref1.pdf"}, {"name": "ref2.pdf"}, {"name": "ref3.pdf"}, {"name": "ref4.pdf"}],  # reference_docs (flat fallback) → 4
    ])

    app = _build_app(blob_manager)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/parent-id/file-count")

    assert resp.status_code == 200
    assert resp.json()["count"] == 6  # 0 + 2 + 4 — CTA should show!


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_returns_zero_for_empty_tree(mock_graph_cls, mock_resolve):
    """Endpoint returns count=0 when folder and all subfolders have no blobs."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        [{"id": "folder-empty", "name": "Empty"}]
    )
    mock_graph_cls.return_value.driver = mock_driver

    mock_resolve.return_value = "Empty"

    blob_manager = MagicMock()
    # Hierarchical returns [], flat fallback also returns []
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
    mock_driver.session.return_value = _mock_neo4j_session(None)
    mock_graph_cls.return_value.driver = mock_driver

    app = _build_app(MagicMock())
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/nonexistent/file-count")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@patch(RESOLVE_PATH, new_callable=AsyncMock)
@patch(GRAPH_SERVICE_PATH)
def test_file_count_400_when_no_blob_manager(mock_graph_cls, mock_resolve):
    """Endpoint returns 400 when blob storage is not configured."""
    mock_driver = MagicMock()
    mock_driver.session.return_value = _mock_neo4j_session(
        [{"id": "folder-123", "name": "SomeFolder"}]
    )
    mock_graph_cls.return_value.driver = mock_driver

    app = _build_app()  # no blob_manager
    app.dependency_overrides[get_partition_id] = lambda: "test-group"

    client = TestClient(app)
    resp = client.get("/folders/folder-123/file-count")

    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"].lower()
