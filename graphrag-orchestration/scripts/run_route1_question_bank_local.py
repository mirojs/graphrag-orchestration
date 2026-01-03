#!/usr/bin/env python3
"""Run Route 1 question bank locally (no HTTP).

- Extracts the Route 1 (Vector) questions from ../test_5pdfs_simple.py without executing it.
- Uses the last indexed group id from ../../last_test_group_id.txt by default.
- Runs questions through HybridPipeline Route 1.

Usage:
  set -a && source ../.env && set +a
  python scripts/run_route1_question_bank_local.py

Optional:
  python scripts/run_route1_question_bank_local.py --group-id test-5pdfs-... --out route1_results.json
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure the service root is importable so `import app.*` works reliably.
SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.services import GraphService, LLMService
from app.hybrid.orchestrator import HybridPipeline
from app.hybrid.router.main import DeploymentProfile


NOT_SPECIFIED = "Not specified in the provided documents."
NO_RELEVANT = "No relevant text found for this query."


def _extract_questions_from_test_file(test_file: Path) -> Dict[str, Any]:
    module = ast.parse(test_file.read_text())
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "QUESTIONS":
                    return ast.literal_eval(node.value)
    raise RuntimeError(f"Could not find QUESTIONS in {test_file}")


def _load_default_group_id(repo_root: Path) -> str:
    p = repo_root / "last_test_group_id.txt"
    return p.read_text().strip()


async def _run_one(pipeline: HybridPipeline, q: str) -> Dict[str, Any]:
    res = await pipeline._execute_route_1_vector_rag(q)
    resp = (res.get("response") or "").strip()
    meta = res.get("metadata") or {}
    return {
        "question": q,
        "route_used": res.get("route_used"),
        "num_chunks": meta.get("num_chunks"),
        "citations": res.get("citations") or [],
        "response": resp,
        "response_preview": resp.replace("\n", " ")[:200],
        "rejected": (resp.startswith(NOT_SPECIFIED) or resp.startswith(NO_RELEVANT)),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run Route 1 question bank locally")
    parser.add_argument("--group-id", default=None, help="Group id to query (default: last_test_group_id.txt)")
    parser.add_argument(
        "--out",
        default=None,
        help="Optional JSON output path (writes a machine-readable result file)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    group_id = args.group_id or _load_default_group_id(repo_root)

    test_file = repo_root / "test_5pdfs_simple.py"
    questions_obj = _extract_questions_from_test_file(test_file)

    route1_key = "Route 1 - Vector (Local)"
    route1 = questions_obj[route1_key]
    positive: List[str] = route1["positive"]
    negative: List[str] = route1["negative"]

    print("group_id:", group_id)
    print("questions:", {"positive": len(positive), "negative": len(negative)})

    graph_service = GraphService()
    llm_service = LLMService()

    pipeline = HybridPipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_service.llm,
        neo4j_driver=graph_service.driver,
        group_id=group_id,
    )

    results: Dict[str, Any] = {
        "group_id": group_id,
        "positive": [],
        "negative": [],
        "summary": {},
    }

    for q in positive:
        results["positive"].append(await _run_one(pipeline, q))

    for q in negative:
        results["negative"].append(await _run_one(pipeline, q))

    # Basic summary (heuristic):
    # - Positive: consider "answered" if not rejected
    # - Negative: consider "correctly rejected" if rejected
    pos_answered = sum(1 for r in results["positive"] if not r["rejected"])
    neg_rejected = sum(1 for r in results["negative"] if r["rejected"])

    results["summary"] = {
        "positive_answered": f"{pos_answered}/{len(results['positive'])}",
        "negative_rejected": f"{neg_rejected}/{len(results['negative'])}",
    }

    print("\n=== Summary ===")
    print("positive answered:", results["summary"]["positive_answered"])
    print("negative rejected:", results["summary"]["negative_rejected"])

    print("\n-- Positive --")
    for r in results["positive"]:
        print(f"- {r['question']} | chunks={r['num_chunks']} cits={len(r['citations'])} | {r['response_preview']}")

    print("\n-- Negative --")
    for r in results["negative"]:
        print(f"- {r['question']} | chunks={r['num_chunks']} cits={len(r['citations'])} | {r['response_preview']}")

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(results, indent=2))
        print("\nwrote:", str(out_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
