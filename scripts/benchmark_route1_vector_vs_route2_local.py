#!/usr/bin/env python3

"""Benchmark Route 1 (vector) questions against Route 2 (local).

Goal
- Use the Route 1 question bank questions (Q-V*) as inputs.
- Run each question twice against the V3 unified endpoint:
    - force_route="vector" (Route 1 behavior)
    - force_route="local"  (Route 2 behavior)
- Capture wall-clock latency + response details so we can evaluate
  whether Route 1 is necessary.

This script is intentionally dependency-free (stdlib only).

Usage
  python3 scripts/benchmark_route1_vector_vs_route2_local.py \
    --url https://...azurecontainerapps.io \
    --group-id test-3072-clean

Environment variables (optional)
  GRAPHRAG_CLOUD_URL  default base URL
  TEST_GROUP_ID       default group id

Outputs
- Writes a JSON report and a Markdown summary table to ./benchmarks/
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
DEFAULT_GROUP_ID = os.getenv("TEST_GROUP_ID", "test-3072-clean")

QUESTION_BANK_MD = Path(__file__).resolve().parents[1] / "QUESTION_BANK_HYBRID_ROUTER_2025-12-29.md"


# 10 positive + 10 negative questions used in historical route validation.
# These are intentionally kept dependency-free (we don't import the old test file
# because it depends on httpx which may not be installed in all environments).
POS_NEG_SUITE_VECTOR_POSITIVE: List[str] = [
    "What is the invoice total amount?",
    "What is the invoice number?",
    "Who issued the invoice?",
    "What is the payment method?",
    "What is the tax amount?",
    "What services are listed on the invoice?",
    "What is the vendor name?",
    "What items are on the invoice?",
    "What is the due date mentioned?",
    "What is the subtotal before tax?",
]

POS_NEG_SUITE_VECTOR_NEGATIVE: List[str] = [
    "What is the GDP of France?",
    "Who won the Nobel Prize?",
    "What is quantum entanglement?",
    "How do you make pizza?",
    "What is the capital of Mars?",
    "Who wrote Hamlet?",
    "What is photosynthesis?",
    "How tall is the Eiffel Tower?",
    "What is machine learning?",
    "When did dinosaurs exist?",
]


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


def _snip(text: str, n: int = 120) -> str:
    t = (text or "").strip().replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    if len(t) <= n:
        return t
    return t[: n - 3] + "..."


def _is_no_info_answer(text: str) -> bool:
    """Heuristic: treat these as correct 'negative' responses."""
    t = (text or "").strip().lower()
    if not t:
        return True
    phrases = [
        "no relevant information",
        "no data has been indexed",
        "not specified in the provided documents",
        "not specified",
        "not found",
        "cannot find",
        "no relevant text",
    ]
    return any(p in t for p in phrases)


def _avg_ms(values: List[int]) -> float:
    return (sum(values) / len(values)) if values else 0.0


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


def _similarity(a: str, b: str) -> float:
    return float(difflib.SequenceMatcher(None, a or "", b or "").ratio())


def _summarize_repeats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize per-route repeatability for one question.

    runs: list of {status, elapsed_ms, answer, answer_norm, sources_ids, sources_count, confidence}
    """
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


def _read_vector_questions(path: Path) -> List[BankQuestion]:
    return _read_question_bank(path, prefix="Q-V")


def _read_local_questions(path: Path) -> List[BankQuestion]:
    return _read_question_bank(path, prefix="Q-L")


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
    """Return (status_code, json_data_or_empty, elapsed_s, error_text)."""

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


def _sources_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    a_ids = set(_extract_sources_ids(a))
    b_ids = set(_extract_sources_ids(b))
    if not a_ids and not b_ids:
        return 1.0
    if not a_ids or not b_ids:
        return 0.0
    inter = len(a_ids & b_ids)
    union = len(a_ids | b_ids)
    return inter / union if union else 0.0


def _sources_count(resp_json: Dict[str, Any]) -> int:
    sources = resp_json.get("sources") or []
    return len(sources) if isinstance(sources, list) else 0


def _extract_retrieval_context_size(resp_json: Dict[str, Any]) -> int:
    """Best-effort measure of retrieval-only payload size.

    When /graphrag/v3/query/local is called with synthesize=false, its "answer"
    is a context string (bulleted entity descriptions). We approximate "detail"
    by counting characters.
    """
    ans = resp_json.get("answer")
    if not isinstance(ans, str):
        return 0
    return len(ans)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL, help="Base URL (no trailing slash preferred)")
    parser.add_argument(
        "--question-bank",
        default=str(QUESTION_BANK_MD),
        help="Path to a question bank markdown file (used by qv and repeat-qbank suites).",
    )
    parser.add_argument("--group-id", default=DEFAULT_GROUP_ID, help="X-Group-ID value")
    parser.add_argument("--top-k", type=int, default=10, help="top_k for retrieval")
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-request timeout (seconds)",
    )
    parser.add_argument(
        "--synthesize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Send synthesize=true/false in the request payload. Note: /graphrag/v3/query currently still synthesizes "
            "for vector/local routes (the server ignores this flag for that endpoint), but /graphrag/v3/query/local "
            "does honor it."
        ),
    )
    parser.add_argument(
        "--suite",
        choices=["qv", "posneg", "repeat-pos", "repeat-qbank"],
        default="qv",
        help=(
            "Which question suite to run: qv (Q-V* from question bank), posneg (10 positive + 10 negative), "
            "repeat-pos (10 positive questions repeated N times for repeatability), or repeat-qbank (repeat Q-V* on vector and Q-L* on local)."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=10,
        help="For repeat-pos: number of repeats per question per route.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.3,
        help="Seconds to sleep between questions (rate limiting / smoother cloud runs).",
    )
    parser.add_argument(
        "--include-local-retrieval-only",
        action="store_true",
        help=(
            "Also run Route 2 in retrieval-only mode by calling /graphrag/v3/query/local with synthesize=false. "
            "This isolates Route 2 retrieval latency from LLM synthesis."
        ),
    )
    args = parser.parse_args()

    question_bank_path = Path(str(args.question_bank)).expanduser().resolve()

    base_url = args.url.rstrip("/")
    endpoint = f"{base_url}/hybrid/query"
    endpoint_local = f"{base_url}/hybrid/query"

    if args.suite == "qv":
        questions = [BankQuestion(qid=q.qid, query=q.query) for q in _read_vector_questions(question_bank_path)]
        labeled: List[Tuple[str, BankQuestion]] = [("positive", q) for q in questions]
    elif args.suite == "posneg":
        pos = [BankQuestion(qid=f"P{i:02d}", query=q) for i, q in enumerate(POS_NEG_SUITE_VECTOR_POSITIVE, 1)]
        neg = [BankQuestion(qid=f"N{i:02d}", query=q) for i, q in enumerate(POS_NEG_SUITE_VECTOR_NEGATIVE, 1)]
        labeled = [("positive", q) for q in pos] + [("negative", q) for q in neg]
        questions = [q for _, q in labeled]
    else:  # repeat-pos
        pos = [BankQuestion(qid=f"P{i:02d}", query=q) for i, q in enumerate(POS_NEG_SUITE_VECTOR_POSITIVE, 1)]
        labeled = [("positive", q) for q in pos]
        questions = [q for _, q in labeled]

    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = _now_utc_stamp()
    suffix = (
        "qv"
        if args.suite == "qv"
        else ("posneg" if args.suite == "posneg" else ("repeat_pos" if args.suite == "repeat-pos" else "repeat_qbank"))
    )
    out_json = out_dir / f"route1_vector_vs_route2_local_{suffix}_{stamp}.json"
    out_md = out_dir / f"route1_vector_vs_route2_local_{suffix}_{stamp}.md"

    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": args.group_id,
    }

    results: List[Dict[str, Any]] = []

    # Repeatability mode: run N times per question per route and compute deviation.
    if args.suite == "repeat-pos":
        repeats = max(1, int(args.repeats))
        repeat_rows: List[Dict[str, Any]] = []

        for _, q in labeled:
            base_payload = {
                "query": q.query,
                "top_k": int(args.top_k),
                "include_sources": True,
                "synthesize": bool(args.synthesize),
            }

            per_route: Dict[str, Any] = {}
            for route in ("vector_rag", "local_search"):
                runs: List[Dict[str, Any]] = []
                for i in range(repeats):
                    status, resp_json, t_s, err = _http_post_json(
                        url=endpoint,
                        headers=headers,
                        payload={**base_payload, "force_route": route},
                        timeout_s=float(args.timeout),
                    )
                    ans = str(resp_json.get("answer", "") or "")
                    run = {
                        "repeat_index": i,
                        "status": status,
                        "elapsed_ms": int(t_s * 1000),
                        "answer": ans,
                        "answer_norm": _normalize_answer(ans),
                        "sources_ids": _extract_sources_ids(resp_json),
                        "sources_count": _sources_count(resp_json),
                        "confidence": resp_json.get("confidence"),
                        "error": err,
                    }
                    runs.append(run)
                    if args.sleep and args.sleep > 0:
                        time.sleep(float(args.sleep))

                per_route[route] = {
                    "runs": runs,
                    "summary": _summarize_repeats(runs),
                }

            row = {
                "qid": q.qid,
                "query": q.query,
                "label": "positive",
                "repeats": repeats,
                "vector": per_route.get("vector"),
                "local": per_route.get("local"),
            }
            repeat_rows.append(row)

            vsum = (per_route.get("vector") or {}).get("summary", {})
            lsum = (per_route.get("local") or {}).get("summary", {})
            print(
                f"{q.qid}: v_exact={float(vsum.get('answer_norm_exact_rate') or 0):.2f} "
                f"l_exact={float(lsum.get('answer_norm_exact_rate') or 0):.2f} "
                f"| v_src_jacc_min={float(vsum.get('sources_min_jaccard_vs_first') or 0):.2f} "
                f"l_src_jacc_min={float(lsum.get('sources_min_jaccard_vs_first') or 0):.2f}"
            )

        report: Dict[str, Any] = {
            "generated_at_utc": stamp,
            "base_url": base_url,
            "endpoint": "/graphrag/v3/query",
            "group_id": args.group_id,
            "top_k": int(args.top_k),
            "synthesize": bool(args.synthesize),
            "suite": args.suite,
            "repeats": repeats,
            "questions": [{"qid": q.qid, "query": q.query} for q in questions],
            "results": repeat_rows,
        }

        out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        # Markdown summary
        md_lines: List[str] = []
        md_lines.append("# Route 1 (vector) vs Route 2 (local) — Repeatability Benchmark (10 positives)")
        md_lines.append("")
        md_lines.append(f"- Generated (UTC): {stamp}")
        md_lines.append(f"- Base URL: {base_url}")
        md_lines.append(f"- Group ID: {args.group_id}")
        md_lines.append(f"- Endpoint: /graphrag/v3/query")
        md_lines.append(f"- top_k: {args.top_k}")
        md_lines.append(f"- synthesize: {args.synthesize}")
        md_lines.append(f"- repeats per question per route: {repeats}")
        md_lines.append("")
        md_lines.append(
            "Interpretation notes: Answer repeatability is measured on normalized answer exact-match vs the first run; "
            "source repeatability uses Jaccard overlap of source IDs vs the first run. "
            "Non-determinism can come from LLM synthesis and from retrieval tie-breaking/updates."
        )
        md_lines.append("")

        md_lines.append(
            "| QID | vector answer exact rate | local answer exact rate | vector min answer sim | local min answer sim | "
            "vector avg src | local avg src | vector min src jacc | local min src jacc | vector p50 ms | local p50 ms | vector p90 ms | local p90 ms |"
        )
        md_lines.append(
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
        )
        for r in repeat_rows:
            vs = ((r.get("vector") or {}).get("summary") or {})
            ls = ((r.get("local") or {}).get("summary") or {})
            vlat = vs.get("latency_ms") or {}
            llat = ls.get("latency_ms") or {}
            md_lines.append(
                "| "
                + str(r.get("qid"))
                + " | "
                + f"{float(vs.get('answer_norm_exact_rate') or 0):.2f}"
                + " | "
                + f"{float(ls.get('answer_norm_exact_rate') or 0):.2f}"
                + " | "
                + f"{float(vs.get('answer_norm_min_similarity') or 0):.2f}"
                + " | "
                + f"{float(ls.get('answer_norm_min_similarity') or 0):.2f}"
                + " | "
                + f"{float(vs.get('sources_count_avg') or 0):.1f}"
                + " | "
                + f"{float(ls.get('sources_count_avg') or 0):.1f}"
                + " | "
                + f"{float(vs.get('sources_min_jaccard_vs_first') or 0):.2f}"
                + " | "
                + f"{float(ls.get('sources_min_jaccard_vs_first') or 0):.2f}"
                + " | "
                + str(int(vlat.get("p50") or 0))
                + " | "
                + str(int(llat.get("p50") or 0))
                + " | "
                + str(int(vlat.get("p90") or 0))
                + " | "
                + str(int(llat.get("p90") or 0))
                + " |"
            )

        out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        print(f"\nWrote:\n- {out_json}\n- {out_md}")
        return 0

    if args.suite == "repeat-qbank":
        repeats = max(1, int(args.repeats))

        qv = _read_vector_questions(question_bank_path)
        ql = _read_local_questions(question_bank_path)

        # Each question is run only on its dedicated route.
        jobs: List[Tuple[str, BankQuestion]] = [("vector_rag", q) for q in qv] + [("local_search", q) for q in ql]

        repeat_rows: List[Dict[str, Any]] = []
        for route, q in jobs:
            base_payload = {
                "query": q.query,
                "top_k": int(args.top_k),
                "include_sources": True,
                "synthesize": bool(args.synthesize),
            }

            runs: List[Dict[str, Any]] = []
            for i in range(repeats):
                status, resp_json, t_s, err = _http_post_json(
                    url=endpoint,
                    headers=headers,
                    payload={**base_payload, "force_route": route},
                    timeout_s=float(args.timeout),
                )
                ans = str(resp_json.get("answer", "") or "")
                run = {
                    "repeat_index": i,
                    "status": status,
                    "elapsed_ms": int(t_s * 1000),
                    "answer": ans,
                    "answer_norm": _normalize_answer(ans),
                    "sources_ids": _extract_sources_ids(resp_json),
                    "sources_count": _sources_count(resp_json),
                    "confidence": resp_json.get("confidence"),
                    "error": err,
                }
                runs.append(run)
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
            print(
                f"{q.qid} ({route}): exact={float(summary.get('answer_norm_exact_rate') or 0):.2f} "
                f"min_sim={float(summary.get('answer_norm_min_similarity') or 0):.2f} "
                f"min_src_jacc={float(summary.get('sources_min_jaccard_vs_first') or 0):.2f}"
            )

        report = {
            "generated_at_utc": stamp,
            "base_url": base_url,
            "endpoint": "/graphrag/v3/query",
            "group_id": args.group_id,
            "top_k": int(args.top_k),
            "synthesize": bool(args.synthesize),
            "suite": args.suite,
            "repeats": repeats,
            "question_bank": str(question_bank_path.name),
            "question_bank_path": str(question_bank_path),
            "vector_questions": [{"qid": q.qid, "query": q.query} for q in qv],
            "local_questions": [{"qid": q.qid, "query": q.query} for q in ql],
            "results": repeat_rows,
        }

        out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        md_lines: List[str] = []
        md_lines.append("# Route 1 (vector) & Route 2 (local) — Repeatability Benchmark (Question Bank)")
        md_lines.append("")
        md_lines.append(f"- Generated (UTC): {stamp}")
        md_lines.append(f"- Base URL: {base_url}")
        md_lines.append(f"- Group ID: {args.group_id}")
        md_lines.append(f"- Endpoint: /graphrag/v3/query")
        md_lines.append(f"- Question bank: {question_bank_path}")
        md_lines.append(f"- top_k: {args.top_k}")
        md_lines.append(f"- synthesize: {args.synthesize}")
        md_lines.append(f"- repeats per question: {repeats}")
        md_lines.append(f"- vector set: Q-V* (forced vector)")
        md_lines.append(f"- local set: Q-L* (forced local)")
        md_lines.append("")
        md_lines.append(
            "Note: The earlier '10 positive + 10 negative' comparison uses a separate hardcoded suite (POS_NEG_*). "
            "This repeat-qbank mode uses the dedicated question bank sets (Q-V* vs Q-L*)."
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

        _emit_table("Vector questions (Q-V*)", "vector")
        _emit_table("Local questions (Q-L*)", "local")

        out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        print(f"\nWrote:\n- {out_json}\n- {out_md}")
        return 0

    pos_vector_ms: List[int] = []
    pos_local_ms: List[int] = []
    pos_local_ro_ms: List[int] = []
    neg_local_ro_ms: List[int] = []
    pos_local_ro_sources: List[int] = []
    neg_local_ro_sources: List[int] = []
    pos_local_ro_ctx_chars: List[int] = []
    neg_local_ro_ctx_chars: List[int] = []
    pos_local_ro_pass = 0
    neg_local_ro_pass = 0
    neg_vector_ms: List[int] = []
    neg_local_ms: List[int] = []
    pos_vector_sources: List[int] = []
    pos_local_sources: List[int] = []
    neg_vector_sources: List[int] = []
    neg_local_sources: List[int] = []
    pos_vector_ans_len: List[int] = []
    pos_local_ans_len: List[int] = []
    neg_vector_ans_len: List[int] = []
    neg_local_ans_len: List[int] = []
    pos_vector_pass = 0
    pos_local_pass = 0
    neg_vector_pass = 0
    neg_local_pass = 0

    for label, q in labeled:
        base_payload = {
            "query": q.query,
            "top_k": int(args.top_k),
            "include_sources": True,
            "synthesize": bool(args.synthesize),
        }

        status_v, json_v, t_v, err_v = _http_post_json(
            url=endpoint,
            headers=headers,
            payload={**base_payload, "force_route": "vector_rag"},
            timeout_s=float(args.timeout),
        )

        status_l, json_l, t_l, err_l = _http_post_json(
            url=endpoint,
            headers=headers,
            payload={**base_payload, "force_route": "local_search"},
            timeout_s=float(args.timeout),
        )

        status_lro = None
        json_lro: Dict[str, Any] = {}
        t_lro = 0.0
        err_lro: Optional[str] = None
        if args.include_local_retrieval_only:
            # Force local route and explicitly disable synthesis.
            payload_ro = {
                "query": q.query,
                "top_k": int(args.top_k),
                "include_sources": True,
                "force_route": "local_search",
                "synthesize": False,
            }
            status_lro, json_lro, t_lro, err_lro = _http_post_json(
                url=endpoint_local,
                headers=headers,
                payload=payload_ro,
                timeout_s=float(args.timeout),
            )

        answer_v = str(json_v.get("answer", "") or "")
        answer_l = str(json_l.get("answer", "") or "")
        answer_lro = str(json_lro.get("answer", "") or "") if args.include_local_retrieval_only else ""

        norm_v = _normalize_answer(answer_v)
        norm_l = _normalize_answer(answer_l)

        sources_overlap = _sources_overlap(json_v, json_l)
        v_sources = _sources_count(json_v)
        l_sources = _sources_count(json_l)
        lro_sources = _sources_count(json_lro) if args.include_local_retrieval_only else 0

        row: Dict[str, Any] = {
            "qid": q.qid,
            "query": q.query,
            "label": label,
            "vector": {
                "status": status_v,
                "elapsed_ms": int(t_v * 1000),
                "response": json_v,
                "error": err_v,
            },
            "local": {
                "status": status_l,
                "elapsed_ms": int(t_l * 1000),
                "response": json_l,
                "error": err_l,
            },
            "compare": {
                "same_answer_normalized": bool(norm_v and norm_l and norm_v == norm_l),
                "vector_minus_local_confidence": None,
                "sources_jaccard": sources_overlap,
                "vector_ms": int(t_v * 1000),
                "local_ms": int(t_l * 1000),
            },
        }

        # Fix confidence delta only when both are numeric
        try:
            cv_raw = json_v.get("confidence")
            cl_raw = json_l.get("confidence")
            if cv_raw is None or cl_raw is None:
                raise ValueError("missing confidence")
            cv = float(cv_raw)
            cl = float(cl_raw)
            row["compare"]["vector_minus_local_confidence"] = cv - cl
        except Exception:
            row["compare"]["vector_minus_local_confidence"] = None

        # Quality checks (very lightweight heuristics)
        vector_ok = False
        local_ok = False
        if label == "negative":
            vector_ok = _is_no_info_answer(answer_v)
            local_ok = _is_no_info_answer(answer_l)
        else:  # positive
            vector_ok = (not _is_no_info_answer(answer_v)) and (len(answer_v.strip()) > 3)
            local_ok = (not _is_no_info_answer(answer_l)) and (len(answer_l.strip()) > 3)

        row["quality"] = {
            "vector_pass": bool(vector_ok),
            "local_pass": bool(local_ok),
            "vector_answer_len": len(answer_v.strip()),
            "local_answer_len": len(answer_l.strip()),
            "vector_sources": v_sources,
            "local_sources": l_sources,
        }

        if label == "negative":
            neg_vector_ms.append(int(t_v * 1000))
            neg_local_ms.append(int(t_l * 1000))
            neg_vector_pass += 1 if vector_ok else 0
            neg_local_pass += 1 if local_ok else 0
            neg_vector_sources.append(v_sources)
            neg_local_sources.append(l_sources)
            neg_vector_ans_len.append(len(answer_v.strip()))
            neg_local_ans_len.append(len(answer_l.strip()))

            if args.include_local_retrieval_only:
                # Retrieval-only has no synthesized answer; treat "pass" as successful retrieval.
                lro_ok = (status_lro == 200)
                neg_local_ro_pass += 1 if lro_ok else 0
                neg_local_ro_ms.append(int(t_lro * 1000))
                neg_local_ro_sources.append(lro_sources)
                neg_local_ro_ctx_chars.append(_extract_retrieval_context_size(json_lro))
        else:
            pos_vector_ms.append(int(t_v * 1000))
            pos_local_ms.append(int(t_l * 1000))
            pos_vector_pass += 1 if vector_ok else 0
            pos_local_pass += 1 if local_ok else 0
            pos_vector_sources.append(v_sources)
            pos_local_sources.append(l_sources)
            pos_vector_ans_len.append(len(answer_v.strip()))
            pos_local_ans_len.append(len(answer_l.strip()))

            if args.include_local_retrieval_only:
                # Retrieval-only has no synthesized answer; treat "pass" as successful retrieval.
                lro_ok = (status_lro == 200)
                pos_local_ro_pass += 1 if lro_ok else 0
                pos_local_ro_ms.append(int(t_lro * 1000))
                pos_local_ro_sources.append(lro_sources)
                pos_local_ro_ctx_chars.append(_extract_retrieval_context_size(json_lro))
        results.append(row)

        print(
            f"{q.qid} ({label}): vector={row['compare']['vector_ms']}ms local={row['compare']['local_ms']}ms "
            f"| v_ok={row['quality']['vector_pass']} l_ok={row['quality']['local_pass']} | overlap={sources_overlap:.2f}"
        )

        if args.sleep and args.sleep > 0:
            time.sleep(float(args.sleep))

    report: Dict[str, Any] = {
        "generated_at_utc": stamp,
        "base_url": base_url,
        "endpoint": "/graphrag/v3/query",
        "group_id": args.group_id,
        "top_k": int(args.top_k),
        "synthesize": bool(args.synthesize),
        "suite": args.suite,
        "questions": [{"qid": q.qid, "query": q.query} for q in questions],
        "results": results,
        "summary": {
            "positive": {
                "count": len(pos_vector_ms),
                "vector_pass": pos_vector_pass,
                "local_pass": pos_local_pass,
                "vector_avg_ms": _avg_ms(pos_vector_ms),
                "local_avg_ms": _avg_ms(pos_local_ms),
                "vector_avg_answer_chars": _avg_ms(pos_vector_ans_len),
                "local_avg_answer_chars": _avg_ms(pos_local_ans_len),
                "vector_avg_sources": _avg_ms(pos_vector_sources),
                "local_avg_sources": _avg_ms(pos_local_sources),
            },
            "negative": {
                "count": len(neg_vector_ms),
                "vector_pass": neg_vector_pass,
                "local_pass": neg_local_pass,
                "vector_avg_ms": _avg_ms(neg_vector_ms),
                "local_avg_ms": _avg_ms(neg_local_ms),
                "vector_avg_answer_chars": _avg_ms(neg_vector_ans_len),
                "local_avg_answer_chars": _avg_ms(neg_local_ans_len),
                "vector_avg_sources": _avg_ms(neg_vector_sources),
                "local_avg_sources": _avg_ms(neg_local_sources),
            },
            "local_retrieval_only": {
                "enabled": bool(args.include_local_retrieval_only),
                "positive": {
                    "count": len(pos_local_ro_ms),
                    "pass": pos_local_ro_pass,
                    "avg_ms": _avg_ms(pos_local_ro_ms),
                    "avg_sources": _avg_ms(pos_local_ro_sources),
                    "avg_context_chars": _avg_ms(pos_local_ro_ctx_chars),
                },
                "negative": {
                    "count": len(neg_local_ro_ms),
                    "pass": neg_local_ro_pass,
                    "avg_ms": _avg_ms(neg_local_ro_ms),
                    "avg_sources": _avg_ms(neg_local_ro_sources),
                    "avg_context_chars": _avg_ms(neg_local_ro_ctx_chars),
                },
            },
        },
    }

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown summary
    md_lines: List[str] = []
    title_suffix = "Q-V*" if args.suite == "qv" else "10 positive + 10 negative"
    md_lines.append(f"# Route 1 (vector) vs Route 2 (local) — {title_suffix} Benchmark")
    md_lines.append("")
    md_lines.append(f"- Generated (UTC): {stamp}")
    md_lines.append(f"- Base URL: {base_url}")
    md_lines.append(f"- Group ID: {args.group_id}")
    md_lines.append(f"- Endpoint: /graphrag/v3/query")
    md_lines.append(f"- top_k: {args.top_k}")
    md_lines.append(f"- synthesize: {args.synthesize}")
    md_lines.append(f"- suite: {args.suite}")
    md_lines.append("")

    # Summary block
    summ = report.get("summary", {}) if isinstance(report, dict) else {}
    pos = summ.get("positive", {}) if isinstance(summ, dict) else {}
    neg = summ.get("negative", {}) if isinstance(summ, dict) else {}
    if args.suite == "posneg":
        md_lines.append("## Summary")
        md_lines.append("")
        md_lines.append(
            f"- Positive pass: vector {pos.get('vector_pass')}/{pos.get('count')} | local {pos.get('local_pass')}/{pos.get('count')}"
        )
        md_lines.append(
            f"- Positive avg latency (ms): vector {pos.get('vector_avg_ms'):.1f} | local {pos.get('local_avg_ms'):.1f}"
        )
        md_lines.append(
            f"- Positive avg details: vector {pos.get('vector_avg_answer_chars'):.1f} chars / {pos.get('vector_avg_sources'):.1f} sources | "
            f"local {pos.get('local_avg_answer_chars'):.1f} chars / {pos.get('local_avg_sources'):.1f} sources"
        )
        md_lines.append(
            f"- Negative pass: vector {neg.get('vector_pass')}/{neg.get('count')} | local {neg.get('local_pass')}/{neg.get('count')}"
        )
        md_lines.append(
            f"- Negative avg latency (ms): vector {neg.get('vector_avg_ms'):.1f} | local {neg.get('local_avg_ms'):.1f}"
        )
        md_lines.append(
            f"- Negative avg details: vector {neg.get('vector_avg_answer_chars'):.1f} chars / {neg.get('vector_avg_sources'):.1f} sources | "
            f"local {neg.get('local_avg_answer_chars'):.1f} chars / {neg.get('local_avg_sources'):.1f} sources"
        )

        lro = summ.get("local_retrieval_only", {}) if isinstance(summ, dict) else {}
        if isinstance(lro, dict) and lro.get("enabled"):
            lro_pos = lro.get("positive", {}) if isinstance(lro.get("positive"), dict) else {}
            lro_neg = lro.get("negative", {}) if isinstance(lro.get("negative"), dict) else {}
            md_lines.append(
                f"- Local retrieval-only (no LLM): pos {lro_pos.get('pass')}/{lro_pos.get('count')} avg {float(lro_pos.get('avg_ms') or 0):.1f}ms, "
                f"avg {float(lro_pos.get('avg_sources') or 0):.1f} sources, avg {float(lro_pos.get('avg_context_chars') or 0):.1f} ctx chars"
            )
            md_lines.append(
                f"- Local retrieval-only (no LLM): neg {lro_neg.get('pass')}/{lro_neg.get('count')} avg {float(lro_neg.get('avg_ms') or 0):.1f}ms, "
                f"avg {float(lro_neg.get('avg_sources') or 0):.1f} sources, avg {float(lro_neg.get('avg_context_chars') or 0):.1f} ctx chars"
            )
        md_lines.append("")

    md_lines.append("| QID | label | v ms | l ms | v ok | l ok | v chars | l chars | v src | l src | Δconf (v-l) | sources Jaccard | vector answer | local answer |")
    md_lines.append("|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|")

    for r in results:
        v = r["vector"]["response"] if isinstance(r.get("vector"), dict) else {}
        l = r["local"]["response"] if isinstance(r.get("local"), dict) else {}
        v_ms = r["compare"].get("vector_ms")
        l_ms = r["compare"].get("local_ms")
        dconf = r["compare"].get("vector_minus_local_confidence")
        jacc = r["compare"].get("sources_jaccard")
        label = r.get("label", "")
        qv = r.get("quality", {}) if isinstance(r.get("quality"), dict) else {}
        vok = qv.get("vector_pass")
        lok = qv.get("local_pass")
        vchars = qv.get("vector_answer_len")
        lchars = qv.get("local_answer_len")
        vsrc = qv.get("vector_sources")
        lsrc = qv.get("local_sources")

        v_ans = _snip(str(v.get("answer", "") or ""), 90)
        l_ans = _snip(str(l.get("answer", "") or ""), 90)

        dconf_s = "" if dconf is None else f"{dconf:.3f}"
        jacc_s = "" if jacc is None else f"{float(jacc):.2f}"

        md_lines.append(
            f"| {r['qid']} | {label} | {v_ms} | {l_ms} | {vok} | {lok} | {vchars} | {lchars} | {vsrc} | {lsrc} | {dconf_s} | {jacc_s} | {v_ans} | {l_ans} |"
        )

    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"\nWrote:\n- {out_json}\n- {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
