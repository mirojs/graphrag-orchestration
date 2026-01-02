#!/usr/bin/env python3

"""Repeatability benchmark for Route 3 (global/graph) and Route 4 (drift).

What this script does
- Reads a markdown question bank containing:
  - Q-G*: Global positives (mapped to V3 force_route="graph")
  - Q-D*: Drift positives (mapped to V3 force_route="drift")
- Runs each question N times on its dedicated route and computes:
  - normalized answer exact match rate vs first run
  - minimum normalized answer similarity vs first run
  - sources Jaccard overlap vs first run
  - latency p50/p90

Outputs
- Writes a JSON report and a Markdown summary table to ./benchmarks/

Usage
  python3 scripts/benchmark_route3_graph_vs_route4_drift.py \
    --url https://...azurecontainerapps.io \
    --group-id test-3072-clean \
    --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md \
    --repeats 10

Notes
- In the V3 API, the "global" route is represented as force_route="graph".

This script is intentionally dependency-free (stdlib only).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)


def _default_group_id() -> str:
    env = os.getenv("TEST_GROUP_ID")
    if env:
        return env

    # Prefer the most recent E2E group id captured by test_5pdfs_simple.py.
    try:
        root = Path(__file__).resolve().parents[1]
        p = root / "last_test_group_id.txt"
        if p.exists():
            gid = p.read_text(encoding="utf-8").strip()
            if gid:
                return gid
    except Exception:
        pass

    return "test-3072-clean"


DEFAULT_GROUP_ID = _default_group_id()

DEFAULT_QUESTION_BANK = (
    Path(__file__).resolve().parents[1] / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md"
)


@dataclass(frozen=True)
class BankQuestion:
    qid: str
    query: str


def _now_utc_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_answer(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    # Strip lightweight punctuation for rough comparisons.
    t = re.sub(r"[^a-z0-9 $%./:-]", "", t)
    return t


def _similarity(a: str, b: str) -> float:
    return float(difflib.SequenceMatcher(None, a or "", b or "").ratio())


def _percentile(values: List[int], p: float) -> int:
    if not values:
        return 0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    xs = sorted(values)
    k = int(round((p / 100.0) * (len(xs) - 1)))
    k = max(0, min(k, len(xs) - 1))
    return int(xs[k])


def _jaccard_ids(a: List[str], b: List[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _summarize_repeats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not runs:
        return {
            "count": 0,
            "ok_http_200": 0,
            "answer_unique": 0,
            "answer_norm_unique": 0,
            "answer_norm_exact_rate": 0.0,
            "answer_norm_min_similarity": 0.0,
            "sources_unique": 0,
            "sources_avg_jaccard_vs_first": 0.0,
            "sources_min_jaccard_vs_first": 0.0,
            "sources_count_avg": 0.0,
            "latency_ms": {"avg": 0.0, "p50": 0, "p90": 0, "min": 0, "max": 0},
        }

    first = runs[0]
    base_norm = str(first.get("answer_norm", "") or "")
    base_sources = list(first.get("sources_ids") or [])

    answers = [str(r.get("answer", "") or "") for r in runs]
    norms = [str(r.get("answer_norm", "") or "") for r in runs]
    statuses = [int(r.get("status") or 0) for r in runs]
    ms = [int(r.get("elapsed_ms") or 0) for r in runs]
    src_counts = [int(r.get("sources_count") or 0) for r in runs]

    norm_unique = len(set(norms))
    exact_norm = sum(1 for n in norms if n == base_norm)
    sim = [_similarity(base_norm, n) for n in norms]
    jacc = [_jaccard_ids(base_sources, list(r.get("sources_ids") or [])) for r in runs]
    src_sig = ["|".join(sorted(list(r.get("sources_ids") or []))) for r in runs]

    return {
        "count": len(runs),
        "ok_http_200": sum(1 for s in statuses if s == 200),
        "answer_unique": len(set(answers)),
        "answer_norm_unique": norm_unique,
        "answer_norm_exact_rate": float(exact_norm / len(runs)) if runs else 0.0,
        "answer_norm_min_similarity": float(min(sim) if sim else 0.0),
        "sources_unique": len(set(src_sig)),
        "sources_avg_jaccard_vs_first": float(sum(jacc) / len(jacc)) if jacc else 0.0,
        "sources_min_jaccard_vs_first": float(min(jacc) if jacc else 0.0),
        "sources_count_avg": float(sum(src_counts) / len(src_counts)) if src_counts else 0.0,
        "latency_ms": {
            "avg": float(sum(ms) / len(ms)) if ms else 0.0,
            "p50": _percentile(ms, 50),
            "p90": _percentile(ms, 90),
            "min": int(min(ms) if ms else 0),
            "max": int(max(ms) if ms else 0),
        },
    }


def _read_question_bank(path: Path, *, prefix: str) -> List[BankQuestion]:
    if not path.exists():
        raise FileNotFoundError(f"Question bank not found: {path}")

    pattern = re.compile(rf"\*\*({re.escape(prefix)}\d+):\*\*\s*(.+?)\s*$")
    questions: List[BankQuestion] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern.search(line)
        if not m:
            continue
        qid, qtext = m.group(1).strip(), m.group(2).strip()
        if qid and qtext:
            questions.append(BankQuestion(qid=qid, query=qtext))

    if not questions:
        raise RuntimeError(f"No {prefix}* questions found in {path}")
    return questions


def _http_post_json(
    *,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_s: float,
) -> Tuple[int, Dict[str, Any], float, Optional[str]]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            t1 = time.monotonic()
            try:
                parsed = json.loads(raw) if raw else {}
            except Exception:
                parsed = {}
            return int(getattr(resp, "status", 0) or 0), parsed, (t1 - t0), None
    except urllib.error.HTTPError as e:
        t1 = time.monotonic()
        body = ""
        try:
            body = (e.read() or b"").decode("utf-8", errors="replace")
        except Exception:
            body = ""
        parsed: Dict[str, Any] = {}
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {}
        return int(getattr(e, "code", 0) or 0), parsed, (t1 - t0), body[:2000] if body else str(e)
    except Exception as e:
        t1 = time.monotonic()
        return 0, {}, (t1 - t0), str(e)


def _v3_route_endpoint(base_url: str, route: str, *, use_dedicated: bool) -> str:
    base = base_url.rstrip("/")
    if not use_dedicated:
        return f"{base}/graphrag/v3/query"
    if route == "graph":
        return f"{base}/graphrag/v3/query/global"
    if route == "drift":
        return f"{base}/graphrag/v3/query/drift"
    # Fallback to unified endpoint for unexpected values.
    return f"{base}/graphrag/v3/query"


def _extract_sources_ids(resp_json: Dict[str, Any]) -> List[str]:
    sources = resp_json.get("sources") or []
    if not isinstance(sources, list):
        return []
    out: List[str] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if sid is None:
            continue
        out.append(str(sid))
    return out


def _sources_count(resp_json: Dict[str, Any]) -> int:
    sources = resp_json.get("sources") or []
    return len(sources) if isinstance(sources, list) else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL, help="Base URL (no trailing slash preferred)")
    parser.add_argument("--group-id", default=DEFAULT_GROUP_ID, help="X-Group-ID value")
    parser.add_argument(
        "--question-bank",
        default=str(DEFAULT_QUESTION_BANK),
        help="Path to a question bank markdown file.",
    )
    parser.add_argument("--top-k", type=int, default=10, help="top_k for retrieval")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout (seconds)")
    parser.add_argument(
        "--synthesize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Send synthesize=true/false in the request payload (server may ignore for some routes).",
    )
    parser.add_argument(
        "--use-dedicated-endpoints",
        action="store_true",
        help=(
            "Use dedicated endpoints for graph/drift: /graphrag/v3/query/global and /graphrag/v3/query/drift. "
            "If not set, uses the unified endpoint /graphrag/v3/query with force_route."
        ),
    )
    parser.add_argument("--drift-max-iterations", type=int, default=5, help="DRIFT: max_iterations")
    parser.add_argument(
        "--drift-convergence-threshold",
        type=float,
        default=0.8,
        help="DRIFT: convergence_threshold",
    )
    parser.add_argument(
        "--drift-include-reasoning-path",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="DRIFT: include_reasoning_path",
    )
    parser.add_argument("--repeats", type=int, default=10, help="Number of repeats per question")
    parser.add_argument("--sleep", type=float, default=0.3, help="Seconds to sleep between repeats/questions")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the question bank and emit report files without making HTTP calls.",
    )
    args = parser.parse_args()

    question_bank_path = Path(str(args.question_bank)).expanduser().resolve()

    base_url = args.url.rstrip("/")

    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": args.group_id,
    }

    repeats = max(1, int(args.repeats))
    qg = _read_question_bank(question_bank_path, prefix="Q-G")
    qd = _read_question_bank(question_bank_path, prefix="Q-D")

    # Each question is run only on its dedicated route.
    jobs: List[Tuple[str, BankQuestion]] = [("graph", q) for q in qg] + [("drift", q) for q in qd]

    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = _now_utc_stamp()
    out_json = out_dir / f"route3_graph_vs_route4_drift_repeat_qbank_{stamp}.json"
    out_md = out_dir / f"route3_graph_vs_route4_drift_repeat_qbank_{stamp}.md"

    repeat_rows: List[Dict[str, Any]] = []
    for route, q in jobs:
        # Payload differs depending on whether we use the unified endpoint or dedicated endpoints.
        # - Unified: POST /graphrag/v3/query with force_route
        # - Dedicated:
        #   - graph: POST /graphrag/v3/query/global (supports synthesize)
        #   - drift: POST /graphrag/v3/query/drift (supports reasoning_path)

        endpoint = _v3_route_endpoint(base_url, route, use_dedicated=bool(args.use_dedicated_endpoints))

        if args.use_dedicated_endpoints and route == "drift":
            base_payload = {
                "query": q.query,
                "max_iterations": int(args.drift_max_iterations),
                "convergence_threshold": float(args.drift_convergence_threshold),
                "include_sources": True,
                "include_reasoning_path": bool(args.drift_include_reasoning_path),
            }
        else:
            # Unified endpoint (or dedicated graph endpoint): uses V3QueryRequest
            base_payload = {
                "query": q.query,
                "top_k": int(args.top_k),
                "include_sources": True,
                "synthesize": bool(args.synthesize),
            }

        runs: List[Dict[str, Any]] = []
        if not args.dry_run:
            for i in range(repeats):
                payload = dict(base_payload)
                if not args.use_dedicated_endpoints:
                    payload["force_route"] = route

                status, resp_json, t_s, err = _http_post_json(
                    url=endpoint,
                    headers=headers,
                    payload=payload,
                    timeout_s=float(args.timeout),
                )
                ans = str(resp_json.get("answer", "") or "")
                runs.append(
                    {
                        "repeat_index": i,
                        "status": status,
                        "elapsed_ms": int(t_s * 1000),
                        "answer": ans,
                        "answer_norm": _normalize_answer(ans),
                        "sources_ids": _extract_sources_ids(resp_json),
                        "sources_count": _sources_count(resp_json),
                        "confidence": resp_json.get("confidence"),
                        "search_type": resp_json.get("search_type"),
                        "iterations": resp_json.get("iterations"),
                        "reasoning_path_len": (
                            len(resp_json.get("reasoning_path") or [])
                            if isinstance(resp_json.get("reasoning_path"), list)
                            else 0
                        ),
                        "error": err,
                    }
                )
                if args.sleep and args.sleep > 0:
                    time.sleep(float(args.sleep))

        summary = _summarize_repeats(runs)
        repeat_rows.append(
            {
                "qid": q.qid,
                "query": q.query,
                "route": route,
                "repeats": repeats,
                "runs": runs,
                "summary": summary,
            }
        )

        if args.dry_run:
            print(f"{q.qid} ({route}): dry-run", flush=True)
        else:
            print(
                f"{q.qid} ({route}): exact={float(summary.get('answer_norm_exact_rate') or 0):.2f} "
                f"min_sim={float(summary.get('answer_norm_min_similarity') or 0):.2f} "
                f"min_src_jacc={float(summary.get('sources_min_jaccard_vs_first') or 0):.2f}",
                flush=True,
            )

    report: Dict[str, Any] = {
        "generated_at_utc": stamp,
        "base_url": base_url,
        "endpoint": "/graphrag/v3/query" if not args.use_dedicated_endpoints else "(per-route dedicated endpoints)",
        "endpoint_map": (
            {
                "graph": "/graphrag/v3/query/global",
                "drift": "/graphrag/v3/query/drift",
            }
            if args.use_dedicated_endpoints
            else {"unified": "/graphrag/v3/query"}
        ),
        "group_id": args.group_id,
        "top_k": int(args.top_k),
        "synthesize": bool(args.synthesize),
        "suite": "repeat-qbank",
        "repeats": repeats,
        "dry_run": bool(args.dry_run),
        "use_dedicated_endpoints": bool(args.use_dedicated_endpoints),
        "drift": {
            "max_iterations": int(args.drift_max_iterations),
            "convergence_threshold": float(args.drift_convergence_threshold),
            "include_reasoning_path": bool(args.drift_include_reasoning_path),
        },
        "question_bank": str(question_bank_path.name),
        "question_bank_path": str(question_bank_path),
        "global_questions": [{"qid": q.qid, "query": q.query} for q in qg],
        "drift_questions": [{"qid": q.qid, "query": q.query} for q in qd],
        "results": repeat_rows,
    }

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines: List[str] = []
    md_lines.append("# Route 3 (global/graph) & Route 4 (drift) — Repeatability Benchmark (Question Bank)")
    md_lines.append("")
    md_lines.append(f"- Generated (UTC): {stamp}")
    md_lines.append(f"- Base URL: {base_url}")
    md_lines.append(f"- Group ID: {args.group_id}")
    if args.use_dedicated_endpoints:
        md_lines.append(f"- Endpoint (graph): /graphrag/v3/query/global")
        md_lines.append(f"- Endpoint (drift): /graphrag/v3/query/drift")
    else:
        md_lines.append(f"- Endpoint: /graphrag/v3/query")
    md_lines.append(f"- Question bank: {question_bank_path}")
    md_lines.append(f"- top_k: {args.top_k}")
    md_lines.append(f"- synthesize: {args.synthesize}")
    md_lines.append(f"- repeats per question: {repeats}")
    md_lines.append(f"- global set: Q-G* (forced graph)")
    md_lines.append(f"- drift set: Q-D* (forced drift)")
    md_lines.append(f"- dry-run: {args.dry_run}")
    md_lines.append(f"- use dedicated endpoints: {args.use_dedicated_endpoints}")
    if args.use_dedicated_endpoints:
        md_lines.append(
            f"- drift params: max_iterations={args.drift_max_iterations}, convergence_threshold={args.drift_convergence_threshold}, include_reasoning_path={args.drift_include_reasoning_path}"
        )
    md_lines.append("")
    md_lines.append(
        "Interpretation notes: Answer repeatability is measured on normalized answer exact-match vs the first run; "
        "source repeatability uses Jaccard overlap of source IDs vs the first run."
    )
    md_lines.append("")

    def _emit_table(title: str, route: str) -> None:
        md_lines.append(f"## {title}")
        md_lines.append("")
        md_lines.append(
            "| QID | answer exact rate | min answer similarity | unique norm answers | avg sources | min src jacc | p50 ms | p90 ms | ok/total |"
        )
        md_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in repeat_rows:
            if r.get("route") != route:
                continue
            s = r.get("summary") or {}
            lat = s.get("latency_ms") or {}
            md_lines.append(
                "| "
                + str(r.get("qid"))
                + " | "
                + f"{float(s.get('answer_norm_exact_rate') or 0):.2f}"
                + " | "
                + f"{float(s.get('answer_norm_min_similarity') or 0):.2f}"
                + " | "
                + str(int(s.get("answer_norm_unique") or 0))
                + " | "
                + f"{float(s.get('sources_count_avg') or 0):.1f}"
                + " | "
                + f"{float(s.get('sources_min_jaccard_vs_first') or 0):.2f}"
                + " | "
                + str(int(lat.get("p50") or 0))
                + " | "
                + str(int(lat.get("p90") or 0))
                + " | "
                + str(int(s.get("ok_http_200") or 0))
                + "/"
                + str(int(s.get("count") or 0))
                + " |"
            )
        md_lines.append("")

    _emit_table("Global questions (Q-G*)", "graph")
    _emit_table("Drift questions (Q-D*)", "drift")

    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"\nWrote:\n- {out_json}\n- {out_md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
