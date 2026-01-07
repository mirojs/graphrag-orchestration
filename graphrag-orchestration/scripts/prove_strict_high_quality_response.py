"""Proof that strict-high-quality failures return a structured 503 JSON payload.

This is a local, dependency-free test (no Neo4j, no Azure) that stubs the
pipeline to raise HighQualityError and asserts the API response shape.

Run:
  cd graphrag-orchestration
  python3 scripts/prove_strict_high_quality_response.py
"""

from __future__ import annotations

import os
import sys
import asyncio

# When running as a script, Python puts this file's directory (scripts/) on sys.path,
# but not necessarily the repo root. Add the repo root so `import app` works.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.hybrid.orchestrator import HighQualityError
from app.hybrid.router.main import QueryRoute
from app.routers import hybrid as hybrid_router


class StubPipeline:
    async def force_route(self, query: str, route: QueryRoute, response_type: str):
        raise HighQualityError(
            "Semantic section boost added no evidence chunks (boost_added=0)",
            details={"section_boost": {"boost_added": 0, "strategy": "semantic_section_discovery"}},
        )


async def _stub_get_or_create_pipeline(group_id: str, **kwargs):
    return StubPipeline()


def main() -> None:
    # Monkeypatch the router's pipeline factory.
    hybrid_router._get_or_create_pipeline = _stub_get_or_create_pipeline  # type: ignore[attr-defined]

    async def _run() -> None:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/hybrid/query",
            "headers": [(b"x-group-id", b"test-group")],
        }

        async def _receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(scope, _receive)
        request.state.group_id = "test-group"

        body = hybrid_router.HybridQueryRequest(
            query="What reporting obligations exist?",
            response_type="detailed_report",
            force_route=hybrid_router.RouteEnum.GLOBAL_SEARCH,
        )

        resp = await hybrid_router.hybrid_query(request, body)

        assert isinstance(resp, JSONResponse), type(resp)
        assert resp.status_code == 503, resp.body
        payload = resp.body.decode("utf-8")

        assert '"error"' in payload, payload
        assert '"ROUTE3_STRICT_HIGH_QUALITY"' in payload, payload

        print("PASS")
        print("status:", resp.status_code)
        print("body:", payload)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
