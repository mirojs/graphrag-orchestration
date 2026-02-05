#!/usr/bin/env python3

"""Benchmark the 4-route architecture using a question bank.

What this script does
- Reads an "old" markdown question bank with these sections:
  - Q-V*: Vector positives (10)
  - Q-L*: Local positives (10)
  - Q-G*: Global positives (10)  -> mapped to force_route="graph" in V3
  - Q-D*: Drift positives (10)
  - Q-N*: Negative questions (10) -> applied to EACH route as negatives

- Runs each route's own 10 positives + 10 negatives (20 total per route)
  against the V3 unified endpoint:
    POST /graphrag/v3/query

- Writes a JSON report + Markdown summary table to ./benchmarks/

This script is intentionally dependency-free (stdlib only).

Usage
  python3 scripts/benchmark_all4_routes_posneg_qbank.py \
    --url https://...azurecontainerapps.io \
    --group-id phase1-5docs-1766595043 \
    --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md

Notes
- In the V3 API, the "global" route is represented as force_route="graph".
"""

from __future__ import annotations

import argparse
import datetime as _dt
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
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)
DEFAULT_GROUP_ID = os.getenv("TEST_GROUP_ID", "test-3072-clean")

DEFAULT_QUESTION_BANK = Path(__file__).resolve().parents[1] / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md"


@dataclass(frozen=True)
class BankQuestion:
    qid: str
    query: str


def _now_utc_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_answer(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^a-z0-9 $%./:-]", "", t)
    return t


def _is_no_info_answer(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    phrases = [
        "no relevant information",
        "no data has been indexed",
        "not specified in the provided documents",
        "not specified",
        "not provided",
        "not explicitly",
        "not found",
        "cannot find",
        "no relevant text found",
        "no relevant",
        "does not include",
        "does not mention",
        "does not explicitly mention",
        "is not included",
        "is not present",
    ]
    return any(p in t for p in phrases)


def _sources_count(resp_json: Dict[str, Any]) -> int:
    sources = resp_json.get("sources") or []
    return len(sources) if isinstance(sources, list) else 0


def _extract_sources_ids(resp_json: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    sources = resp_json.get("sources")
    if not isinstance(sources, list):
        return out
    for s in sources:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if sid is None:
            continue
        out.append(str(sid))
    return out


def _percentile(values: List[int], p: int) -> int:
    if not values:
        return 0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    p = max(0, min(100, int(p)))
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    d0 = xs[f] * (c - k)
    d1 = xs[c] * (k - f)
    return int(round(d0 + d1))


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


def _summarize_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    ms = [int(r.get("elapsed_ms") or 0) for r in runs]
    ans_chars = [int(r.get("answer_chars") or 0) for r in runs]
    src_counts = [int(r.get("sources_count") or 0) for r in runs]
    ok = sum(1 for r in runs if int(r.get("status") or 0) == 200)
    return {
        "count": len(runs),
        "ok_http_200": ok,
        "latency_ms": {
            "avg": float(sum(ms) / len(ms)) if ms else 0.0,
            "p50": _percentile(ms, 50),
            "p90": _percentile(ms, 90),
            "min": int(min(ms) if ms else 0),
            "max": int(max(ms) if ms else 0),
        },
        "answer_chars": {
            "avg": float(sum(ans_chars) / len(ans_chars)) if ans_chars else 0.0,
            "min": int(min(ans_chars) if ans_chars else 0),
            "max": int(max(ans_chars) if ans_chars else 0),
        },
        "sources_count": {
            "avg": float(sum(src_counts) / len(src_counts)) if src_counts else 0.0,
            "min": int(min(src_counts) if src_counts else 0),
            "max": int(max(src_counts) if src_counts else 0),
        },
    }


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
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout (seconds)")
    parser.add_argument("--sleep", type=float, default=0.3, help="Seconds to sleep between questions")
    parser.add_argument(
        "--synthesize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Send synthesize=true/false in the request payload (server may ignore for some routes).",
    )
    args = parser.parse_args()

    question_bank_path = Path(str(args.question_bank)).expanduser().resolve()

    base_url = args.url.rstrip("/")
    endpoint = f"{base_url}/graphrag/v3/query"

    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": args.group_id,
    }

    # Map the 4-route naming to actual V3 force_route values.
    # - "global" in the question bank corresponds to force_route="graph" in V3.
    route_sets = [
        ("vector", "Q-V"),
        ("local", "Q-L"),
        ("graph", "Q-G"),
        ("drift", "Q-D"),
    ]

    negatives = _read_question_bank(question_bank_path, prefix="Q-N")

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"all4_routes_posneg_qbank_{stamp}.json"
    out_md = out_dir / f"all4_routes_posneg_qbank_{stamp}.md"

    results: Dict[str, Any] = {
        "generated_at_utc": stamp,
        "base_url": base_url,
        "endpoint": "/graphrag/v3/query",
        "group_id": args.group_id,
        "top_k": int(args.top_k),
        "synthesize": bool(args.synthesize),
        "question_bank": str(question_bank_path.name),
        "question_bank_path": str(question_bank_path),
        "routes": [],
    }

    for force_route, prefix in route_sets:
        positives = _read_question_bank(question_bank_path, prefix=prefix)
        jobs: List[Tuple[str, BankQuestion]] = [("positive", q) for q in positives] + [("negative", q) for q in negatives]

        route_runs: List[Dict[str, Any]] = []
        for label, q in jobs:
            payload = {
                "query": q.query,
                "top_k": int(args.top_k),
                "include_sources": True,
                "synthesize": bool(args.synthesize),
                "force_route": force_route,
            }

            status, resp_json, t_s, err = _http_post_json(
                url=endpoint,
                headers=headers,
                payload=payload,
                timeout_s=float(args.timeout),
            )

            ans = str(resp_json.get("answer", "") or "")
            run = {
                "label": label,
                "qid": q.qid,
                "query": q.query,
                "status": status,
                "elapsed_ms": int(t_s * 1000),
                "answer": ans,
                "answer_norm": _normalize_answer(ans),
                "answer_chars": len(ans),
                "sources_count": _sources_count(resp_json),
                "sources_ids": _extract_sources_ids(resp_json),
                "confidence": resp_json.get("confidence"),
                "error": err,
                "negative_pass": bool(_is_no_info_answer(ans)) if label == "negative" else None,
            }
            route_runs.append(run)

            if args.sleep and args.sleep > 0:
                time.sleep(float(args.sleep))

        pos_runs = [r for r in route_runs if r.get("label") == "positive"]
        neg_runs = [r for r in route_runs if r.get("label") == "negative"]
        neg_pass = sum(1 for r in neg_runs if r.get("negative_pass") is True)

        route_summary = {
            "route": force_route,
            "question_prefix": prefix,
            "positive": _summarize_runs(pos_runs),
            "negative": {
                **_summarize_runs(neg_runs),
                "pass": int(neg_pass),
                "fail": int(len(neg_runs) - neg_pass),
            },
        }

        results["routes"].append(
            {
                "route": force_route,
                "question_prefix": prefix,
                "positives": [{"qid": q.qid, "query": q.query} for q in positives],
                "negatives": [{"qid": q.qid, "query": q.query} for q in negatives],
                "runs": route_runs,
                "summary": route_summary,
            }
        )

        print(
            f"{force_route}: pos_ok={route_summary['positive']['ok_http_200']}/{route_summary['positive']['count']} "
            f"neg_pass={route_summary['negative']['pass']}/{route_summary['negative']['count']}"
        )

    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    md: List[str] = []
    md.append("# 4-Route Basic Test — 10 Positive + 10 Negative (Question Bank)")
    md.append("")
    md.append(f"- Generated (UTC): {stamp}")
    md.append(f"- Base URL: {base_url}")
    md.append(f"- Group ID: {args.group_id}")
    md.append(f"- Endpoint: /graphrag/v3/query")
    md.append(f"- Question bank: {question_bank_path}")
    md.append(f"- top_k: {args.top_k}")
    md.append(f"- synthesize: {args.synthesize}")
    md.append("")
    md.append("Route mapping used:")
    md.append("- Q-V* → force_route=vector")
    md.append("- Q-L* → force_route=local")
    md.append("- Q-G* → force_route=graph (global)")
    md.append("- Q-D* → force_route=drift")
    md.append("- Q-N* negatives are applied to each route")
    md.append("")

    # Overall ranking (fastest to slowest) by positive p50 latency.
    def _pos_p50(route_entry: Dict[str, Any]) -> int:
        summ = (route_entry.get("summary") or {})
        pos = summ.get("positive") or {}
        lat = pos.get("latency_ms") or {}
        return int(lat.get("p50") or 0)

    ranked = sorted(list(results["routes"]), key=_pos_p50)
    md.append("## Overall ranking (positives p50 latency)")
    md.append("")
    for r in ranked:
        summ = (r.get("summary") or {})
        pos = summ.get("positive") or {}
        neg = summ.get("negative") or {}
        pos_lat = pos.get("latency_ms") or {}
        neg_lat = neg.get("latency_ms") or {}
        pos_src = (pos.get("sources_count") or {})
        neg_src = (neg.get("sources_count") or {})
        md.append(
            "- "
            + str(r.get("route"))
            + f": pos p50/p90 {int(pos_lat.get('p50') or 0)}/{int(pos_lat.get('p90') or 0)} ms, avg src {float(pos_src.get('avg') or 0):.1f}; "
            + f"neg p50/p90 {int(neg_lat.get('p50') or 0)}/{int(neg_lat.get('p90') or 0)} ms, avg src {float(neg_src.get('avg') or 0):.1f}"
        )
    md.append("")

    md.append(
        "| route | positives ok/total | positives p50 ms | positives p90 ms | positives avg sources | "
        "negatives pass/total | negatives p50 ms | negatives p90 ms | negatives avg sources |"
    )
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    for r in results["routes"]:
        summ = (r.get("summary") or {})
        pos = summ.get("positive") or {}
        neg = summ.get("negative") or {}
        pos_lat = pos.get("latency_ms") or {}
        neg_lat = neg.get("latency_ms") or {}
        pos_src = (pos.get("sources_count") or {})
        neg_src = (neg.get("sources_count") or {})
        md.append(
            "| "
            + str(r.get("route"))
            + " | "
            + f"{int(pos.get('ok_http_200') or 0)}/{int(pos.get('count') or 0)}"
            + " | "
            + str(int(pos_lat.get("p50") or 0))
            + " | "
            + str(int(pos_lat.get("p90") or 0))
            + " | "
            + f"{float(pos_src.get('avg') or 0):.1f}"
            + " | "
            + f"{int(neg.get('pass') or 0)}/{int(neg.get('count') or 0)}"
            + " | "
            + str(int(neg_lat.get("p50") or 0))
            + " | "
            + str(int(neg_lat.get("p90") or 0))
            + " | "
            + f"{float(neg_src.get('avg') or 0):.1f}"
            + " |"
        )

    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\nWrote:\n- {out_json}\n- {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
