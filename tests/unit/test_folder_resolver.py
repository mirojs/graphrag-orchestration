"""Tests for folder_resolver service — folder-as-Neo4j-group partition logic."""

import pytest
from unittest.mock import MagicMock, patch

# The import path for GraphService used inside folder_resolver via lazy import
GRAPH_SERVICE_PATH = "src.worker.services.GraphService"


# ---------------------------------------------------------------------------
# resolve_neo4j_group_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_returns_auth_group_id_when_no_folder():
    """When folder_id is None, should return auth_group_id unchanged."""
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    result = await resolve_neo4j_group_id("tenant-abc", None)
    assert result == "tenant-abc"


@pytest.mark.asyncio
async def test_resolve_returns_auth_group_id_when_empty_folder():
    """When folder_id is empty string, should return auth_group_id."""
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    result = await resolve_neo4j_group_id("tenant-abc", "")
    assert result == "tenant-abc"


def _mock_neo4j_session(single_return):
    """Helper to create a mock Neo4j session with a single query result."""
    mock_record = MagicMock()
    if single_return is not None:
        mock_record.__getitem__ = lambda self, key: single_return.get(key)
    
    mock_result = MagicMock()
    mock_result.single.return_value = mock_record if single_return is not None else None

    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session


@pytest.mark.asyncio
async def test_resolve_root_folder_returns_itself():
    """A root folder (no parent) should resolve to its own ID."""
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    mock_driver, mock_session = _mock_neo4j_session({"root_folder_id": "folder-root-1"})

    with patch(GRAPH_SERVICE_PATH) as MockGS:
        MockGS.return_value.driver = mock_driver
        result = await resolve_neo4j_group_id("tenant-abc", "folder-root-1")

    assert result == "folder-root-1"
    mock_session.run.assert_called_once()
    call_kwargs = mock_session.run.call_args
    assert call_kwargs.kwargs["folder_id"] == "folder-root-1"
    assert call_kwargs.kwargs["auth_gid"] == "tenant-abc"


@pytest.mark.asyncio
async def test_resolve_subfolder_returns_root():
    """A subfolder should resolve to its root folder's ID."""
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    mock_driver, _ = _mock_neo4j_session({"root_folder_id": "folder-root-1"})

    with patch(GRAPH_SERVICE_PATH) as MockGS:
        MockGS.return_value.driver = mock_driver
        result = await resolve_neo4j_group_id("tenant-abc", "subfolder-child-1")

    assert result == "folder-root-1"


@pytest.mark.asyncio
async def test_resolve_raises_on_missing_folder():
    """Should raise ValueError when folder is not found."""
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    mock_driver, _ = _mock_neo4j_session(None)

    with patch(GRAPH_SERVICE_PATH) as MockGS:
        MockGS.return_value.driver = mock_driver
        with pytest.raises(ValueError, match="not found"):
            await resolve_neo4j_group_id("tenant-abc", "nonexistent-folder")


@pytest.mark.asyncio
async def test_resolve_raises_on_no_driver():
    """Should raise ValueError when Neo4j driver is not initialized."""
    from src.api_gateway.services.folder_resolver import resolve_neo4j_group_id

    with patch(GRAPH_SERVICE_PATH) as MockGS:
        MockGS.return_value.driver = None
        with pytest.raises(ValueError, match="not initialized"):
            await resolve_neo4j_group_id("tenant-abc", "some-folder")


# ---------------------------------------------------------------------------
# get_valid_partition_ids
# ---------------------------------------------------------------------------

def _mock_neo4j_list_session(records):
    """Helper to create a mock Neo4j session with a list of records."""
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(records))

    mock_session = MagicMock()
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    return mock_driver


@pytest.mark.asyncio
async def test_valid_partition_ids_includes_auth_and_roots():
    """Should return auth_group_id + all root folder IDs."""
    from src.api_gateway.services.folder_resolver import get_valid_partition_ids

    mock_driver = _mock_neo4j_list_session([
        {"root_folder_id": "folder-A"},
        {"root_folder_id": "folder-B"},
    ])

    with patch(GRAPH_SERVICE_PATH) as MockGS:
        MockGS.return_value.driver = mock_driver
        result = await get_valid_partition_ids("tenant-abc")

    assert result == ["tenant-abc", "folder-A", "folder-B"]


@pytest.mark.asyncio
async def test_valid_partition_ids_no_driver_returns_auth_only():
    """When no driver, should return just auth_group_id."""
    from src.api_gateway.services.folder_resolver import get_valid_partition_ids

    with patch(GRAPH_SERVICE_PATH) as MockGS:
        MockGS.return_value.driver = None
        result = await get_valid_partition_ids("tenant-abc")

    assert result == ["tenant-abc"]


@pytest.mark.asyncio
async def test_valid_partition_ids_no_folders_returns_auth_only():
    """When user has no folders, should return just auth_group_id."""
    from src.api_gateway.services.folder_resolver import get_valid_partition_ids

    mock_driver = _mock_neo4j_list_session([])

    with patch(GRAPH_SERVICE_PATH) as MockGS:
        MockGS.return_value.driver = mock_driver
        result = await get_valid_partition_ids("tenant-abc")

    assert result == ["tenant-abc"]
