"""Tests for folder analysis status fields — progress, richer stats, error tracking.

Validates that the new folder analysis fields (analysis_files_total,
analysis_files_processed, section_count, sentence_count, relationship_count,
analysis_error) are correctly returned by the GET /folders and
GET /folders/{id} endpoints.
"""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api_gateway.routers.folders import router, get_partition_id

GRAPH_SERVICE_PATH = "src.api_gateway.routers.folders.GraphService"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_partition_id] = lambda: "test-group"
    return app


def _mock_driver_with_records(records: list[dict]):
    """Create a mock Neo4j driver that returns a list of records.

    Supports both legacy ``session.run()`` and managed transaction
    ``session.execute_read()`` / ``session.execute_write()`` paths.
    """
    mock_results = []
    for rec in records:
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key, r=rec: r[key]
        mock_record.get = lambda key, default=None, r=rec: r.get(key, default)
        mock_results.append(mock_record)

    def _make_result():
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(list(mock_results)))
        mock_result.single.return_value = mock_results[0] if mock_results else None
        return mock_result

    # tx.run() used inside execute_read/execute_write transaction functions
    mock_tx = MagicMock()
    mock_tx.run.return_value = _make_result()

    mock_session = MagicMock()
    mock_session.run.return_value = _make_result()
    # execute_read/write call the user function with a tx argument
    mock_session.execute_read.side_effect = lambda fn, *a, **kw: fn(mock_tx, *a, **kw)
    mock_session.execute_write.side_effect = lambda fn, *a, **kw: fn(mock_tx, *a, **kw)
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver


def _base_folder_record(**overrides) -> dict:
    """Return a folder record dict with sensible defaults, applying overrides."""
    rec = {
        "id": "folder-1",
        "name": "Test Folder",
        "group_id": "test-group",
        "parent_folder_id": None,
        "folder_type": "user",
        "analysis_status": "analyzed",
        "analysis_group_id": "folder-1",
        "source_folder_id": None,
        "analyzed_at": None,
        "file_count": 5,
        "entity_count": 100,
        "community_count": 10,
        "analysis_files_total": None,
        "analysis_files_processed": None,
        "section_count": 25,
        "sentence_count": 200,
        "relationship_count": 80,
        "analysis_error": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    rec.update(overrides)
    return rec


# ---------------------------------------------------------------------------
# GET /folders — list returns new fields
# ---------------------------------------------------------------------------

@patch(GRAPH_SERVICE_PATH)
def test_list_folders_includes_new_stats_fields(mock_graph_cls):
    """GET /folders returns section_count, sentence_count, relationship_count."""
    record = _base_folder_record(
        section_count=25, sentence_count=200, relationship_count=80
    )
    mock_graph_cls.return_value.driver = _mock_driver_with_records([record])
    app = _build_app()

    resp = TestClient(app).get("/folders")

    assert resp.status_code == 200
    folders = resp.json()
    assert len(folders) == 1
    f = folders[0]
    assert f["section_count"] == 25
    assert f["sentence_count"] == 200
    assert f["relationship_count"] == 80


@patch(GRAPH_SERVICE_PATH)
def test_list_folders_includes_progress_fields_during_analysis(mock_graph_cls):
    """GET /folders returns progress fields when analysis is in progress."""
    record = _base_folder_record(
        analysis_status="analyzing",
        analysis_files_total=10,
        analysis_files_processed=3,
        section_count=None,
        sentence_count=None,
        relationship_count=None,
    )
    mock_graph_cls.return_value.driver = _mock_driver_with_records([record])
    app = _build_app()

    resp = TestClient(app).get("/folders")

    assert resp.status_code == 200
    f = resp.json()[0]
    assert f["analysis_files_total"] == 10
    assert f["analysis_files_processed"] == 3
    assert f["analysis_status"] == "analyzing"


@patch(GRAPH_SERVICE_PATH)
def test_list_folders_includes_error_field(mock_graph_cls):
    """GET /folders returns analysis_error when analysis has failed."""
    record = _base_folder_record(
        analysis_status="stale",
        analysis_error="Connection refused: Neo4j unavailable",
    )
    mock_graph_cls.return_value.driver = _mock_driver_with_records([record])
    app = _build_app()

    resp = TestClient(app).get("/folders")

    assert resp.status_code == 200
    f = resp.json()[0]
    assert f["analysis_error"] == "Connection refused: Neo4j unavailable"


# ---------------------------------------------------------------------------
# GET /folders/{id} — single folder returns new fields
# ---------------------------------------------------------------------------

@patch(GRAPH_SERVICE_PATH)
def test_get_folder_includes_all_new_fields(mock_graph_cls):
    """GET /folders/{id} returns all new analysis fields."""
    record = _base_folder_record(
        section_count=30,
        sentence_count=150,
        relationship_count=60,
        analysis_error=None,
    )
    mock_graph_cls.return_value.driver = _mock_driver_with_records([record])
    app = _build_app()

    resp = TestClient(app).get("/folders/folder-1")

    assert resp.status_code == 200
    f = resp.json()
    assert f["section_count"] == 30
    assert f["sentence_count"] == 150
    assert f["relationship_count"] == 60
    assert f["analysis_error"] is None
    assert f["analysis_files_total"] is None
    assert f["analysis_files_processed"] is None


# ---------------------------------------------------------------------------
# Null handling — new fields are null when not set
# ---------------------------------------------------------------------------

@patch(GRAPH_SERVICE_PATH)
def test_new_fields_null_for_unanalyzed_folder(mock_graph_cls):
    """New fields should be null for folders that have never been analyzed."""
    record = _base_folder_record(
        analysis_status="not_analyzed",
        entity_count=None,
        community_count=None,
        section_count=None,
        sentence_count=None,
        relationship_count=None,
        analysis_files_total=None,
        analysis_files_processed=None,
        analysis_error=None,
    )
    mock_graph_cls.return_value.driver = _mock_driver_with_records([record])
    app = _build_app()

    resp = TestClient(app).get("/folders")

    assert resp.status_code == 200
    f = resp.json()[0]
    assert f["section_count"] is None
    assert f["sentence_count"] is None
    assert f["relationship_count"] is None
    assert f["analysis_files_total"] is None
    assert f["analysis_files_processed"] is None
    assert f["analysis_error"] is None
