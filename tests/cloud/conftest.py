"""Pytest configuration for cloud tests.

Provides:
- --cloud marker to run only cloud tests
- Skip cloud tests if GRAPHRAG_CLOUD_URL not set
- Shared fixtures for cloud testing
"""

import os
import pytest


def pytest_addoption(parser):
    """Add --cloud option to run cloud tests."""
    parser.addoption(
        "--cloud",
        action="store_true",
        default=False,
        help="Run cloud/deployed tests (requires GRAPHRAG_CLOUD_URL)",
    )


def pytest_configure(config):
    """Register cloud marker."""
    config.addinivalue_line(
        "markers", "cloud: mark test as requiring deployed cloud service"
    )


def pytest_collection_modifyitems(config, items):
    """Skip cloud tests unless --cloud is passed."""
    if not config.getoption("--cloud"):
        skip_cloud = pytest.mark.skip(reason="need --cloud option to run cloud tests")
        for item in items:
            if "cloud" in item.keywords or "cloud" in str(item.fspath):
                item.add_marker(skip_cloud)
    else:
        # If --cloud is passed, check that URL is set
        cloud_url = os.getenv("GRAPHRAG_CLOUD_URL")
        if not cloud_url:
            skip_no_url = pytest.mark.skip(reason="GRAPHRAG_CLOUD_URL environment variable not set")
            for item in items:
                if "cloud" in item.keywords or "cloud" in str(item.fspath):
                    item.add_marker(skip_no_url)


@pytest.fixture(scope="session")
def cloud_url():
    """Return the cloud URL from environment."""
    return os.getenv(
        "GRAPHRAG_CLOUD_URL",
        "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
    )


@pytest.fixture(scope="session")
def test_group_id():
    """Return the test group ID from environment."""
    return os.getenv("TEST_GROUP_ID", "invoice-contract-verification")
