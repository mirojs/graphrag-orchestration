#!/usr/bin/env python3

"""Repeatability benchmark for Route 3 (global/graph) only.

Why this exists
- The existing script `scripts/benchmark_route3_graph_vs_route4_drift.py` benchmarks
  Route 3 vs Route 4 together.
- This runner is Route-3-only (global/graph), useful when you just want to
  validate repeatability for the thematic route.

What this script does
- Reads a markdown question bank containing Q-G* questions
- Runs each question N times against V3 force_route="graph" (Route 3)
- Computes:
  - normalized answer exact match rate vs first run
  - minimum normalized answer similarity vs first run
  - sources Jaccard overlap vs first run
  - latency p50/p90

Outputs
- Writes a JSON report and a Markdown summary table to ./benchmarks/

Usage
  python3 scripts/benchmark_route3_global_repeatability.py \
    --url https://...azurecontainerapps.io \
    --group-id test-3072-clean \
    --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md \
    --repeats 10

Notes
- In the V3 API, the "global" route is represented as force_route="graph".
- Dependency-free (stdlib only).
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
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
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
    Path(__file__).resolve().parents[1]
    / "docs"
    / "archive"
    / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
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

    exact_norm = sum(1 for n in norms if n == base_norm)
    sim = [_similarity(base_norm, n) for n in norms]
    jacc = [_jaccard_ids(base_sources, list(r.get("sources_ids") or [])) for r in runs]
    src_sig = ["|".join(sorted(list(r.get("sources_ids") or []))) for r in runs]

    return {
        "count": len(runs),
        "ok_http_200": sum(1 for s in statuses if s == 200),
        "answer_unique": len(set(answers)),
        "answer_norm_unique": len(set(norms)),
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


def _v3_query_endpoint(base_url: str) -> str:
    # Use hybrid endpoint (correct) instead of deprecated v3
    return f"{base_url.rstrip('/')}/hybrid/query"


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
        help="Path to a question bank markdown file (expects Q-G* questions).",
    )
    parser.add_argument("--top-k", type=int, default=10, help="top_k for retrieval")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout (seconds)")
    parser.add_argument("--repeats", type=int, default=10, help="How many times per question")
    parser.add_argument("--max-questions", type=int, default=0, help="Optional cap on number of questions")
    args = parser.parse_args()

    base_url = str(args.url)
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()

    questions = _read_question_bank(qbank, prefix="Q-G")
    if args.max_questions and args.max_questions > 0:
        questions = questions[: int(args.max_questions)]

    endpoint = _v3_query_endpoint(base_url)

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"route3_graph_repeat_qbank_{stamp}.json"
    out_md = out_dir / f"route3_graph_repeat_qbank_{stamp}.md"

    results: List[Dict[str, Any]] = []

    for qi, q in enumerate(questions, 1):
        runs: List[Dict[str, Any]] = []
        for ri in range(int(args.repeats)):
            payload = {
                "query": q.query,
                "group_id": group_id,
                "force_route": "global_search",
                "profile": "general_enterprise",
            }
            headers = {"Content-Type": "application/json", "X-Group-ID": group_id}
            status, resp, elapsed_s, err = _http_post_json(
                url=endpoint, headers=headers, payload=payload, timeout_s=float(args.timeout)
            )

            answer = str(resp.get("answer") or resp.get("response") or "")
            answer_norm = _normalize_answer(answer)
            src_ids = _extract_sources_ids(resp)

            runs.append(
                {
                    "run": ri,
                    "status": status,
                    "elapsed_ms": int(round(elapsed_s * 1000.0)),
                    "error": err,
                    "answer": answer,
                    "answer_norm": answer_norm,
                    "sources_ids": src_ids,
                    "sources_count": _sources_count(resp),
                }
            )

        results.append(
            {
                "route": "graph",
                "qid": q.qid,
                "query": q.query,
                "summary": _summarize_repeats(runs),
                "runs": runs,
            }
        )

        print(f"[{qi}/{len(questions)}] {q.qid}: repeats={args.repeats} exact={results[-1]['summary']['answer_norm_exact_rate']:.2f}")

    report: Dict[str, Any] = {
        "generated_at_utc": stamp,
        "base_url": base_url,
        "group_id": group_id,
        "suite": "route3_graph_repeat_qbank",
        "repeats": int(args.repeats),
        "question_bank": str(qbank),
        "results": results,
    }

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Minimal MD summary (aligned with analyze_repeatability_report.py expectations)
    md_lines: List[str] = []
    md_lines.append("# Route 3 (global/graph) — Repeatability Benchmark (Question Bank)")
    md_lines.append("")
    md_lines.append(f"- generated_at_utc: {stamp}")
    md_lines.append(f"- base_url: {base_url}")
    md_lines.append(f"- group_id: {group_id}")
    md_lines.append(f"- question_bank: {qbank}")
    md_lines.append(f"- repeats: {int(args.repeats)}")
    md_lines.append("")
    md_lines.append("| QID | exact rate | min similarity | unique norm answers | avg sources | min src jacc | p50 ms | p90 ms |")
    md_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")

    for row in results:
        s = row.get("summary") or {}
        md_lines.append(
            "| "
            + str(row.get("qid") or "")
            + " | "
            + f"{float(s.get('answer_norm_exact_rate') or 0.0):.2f}"
            + " | "
            + f"{float(s.get('answer_norm_min_similarity') or 0.0):.2f}"
            + " | "
            + str(int(s.get("answer_norm_unique") or 0))
            + " | "
            + f"{float(s.get('sources_count_avg') or 0.0):.1f}"
            + " | "
            + f"{float(s.get('sources_min_jaccard_vs_first') or 0.0):.2f}"
            + " | "
            + str(int((s.get("latency_ms") or {}).get("p50") or 0))
            + " | "
            + str(int((s.get("latency_ms") or {}).get("p90") or 0))
            + " |"
        )

    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(str(out_json))
    print(str(out_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
