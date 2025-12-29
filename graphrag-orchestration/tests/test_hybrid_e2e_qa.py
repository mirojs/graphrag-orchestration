import os
from functools import lru_cache
from typing import Any, Dict, AsyncGenerator

import httpx
import pytest

from app.main import app


@lru_cache(maxsize=1)
def _group_id() -> str:
    """Pick a tenant group_id that actually has data.

    Priority:
    1) Explicit E2E_GROUP_ID env var
    2) Auto-detect the most-populated group_id in Neo4j (if reachable)
    """

    explicit = os.getenv("E2E_GROUP_ID")
    if explicit:
        return explicit

    try:
        from app.services.graph_service import GraphService

        svc = GraphService()
        if not svc.driver:
            return "e2e"

        with svc.driver.session() as session:
            row = session.run(
                "MATCH (n) WHERE n.group_id IS NOT NULL "
                "RETURN n.group_id as gid, count(*) as cnt "
                "ORDER BY cnt DESC LIMIT 1"
            ).single()
        if row and row.get("gid"):
            return row["gid"]
    except Exception:
        pass

    return "e2e"


def _headers() -> Dict[str, str]:
    return {"X-Group-ID": _group_id()}


async def _assert_infra_ready(client: httpx.AsyncClient) -> None:
    # 1) HippoRAG index status
    status = await client.get("/hybrid/index/status", headers=_headers())
    assert status.status_code == 200, status.text
    payload: Dict[str, Any] = status.json()

    hippo = payload.get("hipporag") or {}
    # Accept either upstream hipporag OR llamaindex-native implementation
    hippo_available = hippo.get("available") or hippo.get("llamaindex_available")
    if not hippo_available:
        pytest.fail(
            "E2E-real requires HippoRAG (upstream or LlamaIndex-native). "
            "Either install `hipporag` or ensure LlamaIndex HippoRAG retriever is available."
        )

    # entity_texts.json is required for cited synthesis
    files = payload.get("files") or {}
    entity_texts = files.get("entity_texts.json") or {}
    if not entity_texts.get("exists") or (entity_texts.get("count") or 0) <= 0:
        # Attempt a real sync (still E2E-real). If Neo4j isn't configured or
        # the tenant has no indexed docs, this will fail with a clear reason.
        sync = await client.post(
            "/hybrid/index/sync",
            json={"output_dir": "./hipporag_index", "dry_run": False},
            headers=_headers(),
        )
        if sync.status_code != 200:
            pytest.fail(
                "E2E-real requires a synced HippoRAG index with entity texts, and auto-sync failed. "
                f"Status={sync.status_code}. Body={sync.text}"
            )
        sync_payload: Dict[str, Any] = sync.json()
        if sync_payload.get("status") != "success":
            pytest.fail(
                "E2E-real requires a synced HippoRAG index with entity texts, and auto-sync returned error. "
                f"Body={sync.text}"
            )

        # Re-check index status after syncing
        status = await client.get("/hybrid/index/status", headers=_headers())
        assert status.status_code == 200, status.text
        payload = status.json()
        files = payload.get("files") or {}
        entity_texts = files.get("entity_texts.json") or {}
        if not entity_texts.get("exists") or (entity_texts.get("count") or 0) <= 0:
            pytest.fail(
                "E2E-real requires a synced HippoRAG index with entity texts, but entity_texts.json is still missing/empty "
                "after sync. Ensure this group has documents indexed in Neo4j and rerun."
            )

    # 2) Ensure HippoRAG is initialized in-memory
    init = await client.post("/hybrid/index/initialize-hipporag", headers=_headers())
    assert init.status_code == 200, init.text

    # 3) Health should show LLM + HippoRAG tracer available
    health = await client.get("/hybrid/health", headers=_headers())
    assert health.status_code == 200, health.text
    h = health.json()
    components = (h.get("components") or {})

    # These are MUSTs for E2E-real Q/A.
    if components.get("disambiguator") != "ok" or components.get("synthesizer") != "ok":
        pytest.fail(
            "E2E-real requires Azure OpenAI LLM configured (disambiguator/synthesizer must be ok). "
            "Set AZURE_OPENAI_ENDPOINT + auth (AZURE_OPENAI_API_KEY or managed identity) and deployment names."
        )

    if components.get("tracer") != "ok":
        pytest.fail(
            "E2E-real requires HippoRAG tracer enabled (tracer must be ok). "
            "Ensure HippoRAG index exists and was initialized successfully."
        )


@pytest.fixture(scope="session")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _assert_response_is_grounded(result: Dict[str, Any]) -> None:
    assert isinstance(result.get("response"), str)
    assert result["response"].strip(), "Empty response"

    # Synthesis returns structured citations extracted from [n] markers.
    citations = result.get("citations")
    assert isinstance(citations, list), "citations must be a list"
    assert len(citations) > 0, "Expected at least one citation"

    # Basic sanity: response should contain at least one citation marker
    assert "[" in result["response"] and "]" in result["response"], "Response missing citation markers"


@pytest.mark.asyncio
async def test_e2e_real_route_2_local_global(client: httpx.AsyncClient) -> None:
    await _assert_infra_ready(client)

    body = {
        "query": "Provide a concise, cited summary of the key facts in the indexed documents.",
        "response_type": "detailed_report",
        "force_route": "local_search",  # Route 2: Entity-focused with LazyGraphRAG
    }
    resp = await client.post("/hybrid/query", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    result = resp.json()

    # Route 2 is local_search in the new 4-route system
    assert result.get("route_used") in {"route_2_local_search", "route_3_global_search", "route_4_drift_multi_hop", "route_1_vector_rag"}
    # We force route_2; if the backend overrides, that's a bug.
    assert result.get("route_used") == "route_2_local_search"
    _assert_response_is_grounded(result)


@pytest.mark.asyncio
async def test_e2e_real_route_3_drift(client: httpx.AsyncClient) -> None:
    await _assert_infra_ready(client)

    body = {
        "query": "Analyze the main relationships and implications described in the documents, and explain your reasoning with citations.",
        "response_type": "detailed_report",
    }
    resp = await client.post("/hybrid/query/drift", json=body, headers=_headers())
    assert resp.status_code == 200, resp.text
    result = resp.json()

    # Route 4 is drift_multi_hop
    assert result.get("route_used") == "route_4_drift_multi_hop"
    _assert_response_is_grounded(result)
