#!/usr/bin/env python3

"""Repeatability benchmark for Route 3 Global10 across LLM vs NLP variants.

This runner is meant for the Route-3 (global/thematic) *community-based* V3 endpoints:
- LLM synthesis:            POST /graphrag/v3/query/global          (answer)
- NLP audit (no LLM):       POST /graphrag/v3/query/global/audit    (audit_summary)
- NLP + sentence-connection POST /graphrag/v3/query/global/client   (extracted_summary)

Important
- The NLP endpoints (/audit and /client) operate on *community summaries*.
  Your group must have communities available in Neo4j, otherwise these endpoints
  will return "Not specified in the provided documents." for everything.

Outputs
- Writes JSON + MD into ./benchmarks/ using a structure compatible with the
  existing `repeatability_global10_synthesize_and_nlp_*.json` reports.

Usage
  python3 scripts/benchmark_route3_global10_llm_nlp_client_repeatability.py \
    --url https://...azurecontainerapps.io \
    --group-id test-3072-clean \
    --repeats 10

Optional
  --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md
  --top-k 5
  --timeout 180
  --max-questions 0
  --include-llm-rephrase   (adds /global/client with synthesize=true, compares rephrased_narrative)

Dependency-free (stdlib only).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
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

DEFAULT_QUESTION_BANK = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "archive"
    / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
)


def _default_group_id() -> str:
    env = os.getenv("TEST_GROUP_ID")
    if env:
        return env
    return "test-3072-clean"


@dataclass(frozen=True)
class BankQuestion:
    qid: str
    query: str


def _now_utc_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_text(text: str) -> str:
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


def _md5(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8", errors="ignore")).hexdigest()


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


def _extract_sources_ids(resp_json: Dict[str, Any]) -> List[str]:
    sources = resp_json.get("sources") or resp_json.get("citations") or []
    if not isinstance(sources, list):
        return []
    out: List[str] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        sid = s.get("id") or s.get("community_id")
        if sid is None:
            continue
        out.append(str(sid))
    return out


def _summarize_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not runs:
        return {
            "count": 0,
            "ok_http_200": 0,
            "text_unique": 0,
            "text_norm_unique": 0,
            "text_norm_exact_rate": 0.0,
            "text_norm_min_similarity": 0.0,
            "sources_unique": 0,
            "sources_avg_jaccard_vs_first": 0.0,
            "sources_min_jaccard_vs_first": 0.0,
            "latency_ms": {"avg": 0.0, "p50": 0, "p90": 0, "min": 0, "max": 0},
        }

    first = runs[0]
    base_norm = str(first.get("text_norm") or "")
    base_sources = list(first.get("sources_ids") or [])

    texts = [str(r.get("text") or "") for r in runs]
    norms = [str(r.get("text_norm") or "") for r in runs]
    statuses = [int(r.get("status") or 0) for r in runs]
    ms = [int(r.get("elapsed_ms") or 0) for r in runs]

    exact_norm = sum(1 for n in norms if n == base_norm)
    sims = [_similarity(base_norm, n) for n in norms]
    jacc = [_jaccard_ids(base_sources, list(r.get("sources_ids") or [])) for r in runs]
    src_sig = ["|".join(sorted(list(r.get("sources_ids") or []))) for r in runs]

    return {
        "count": len(runs),
        "ok_http_200": sum(1 for s in statuses if s == 200),
        "text_unique": len(set(texts)),
        "text_norm_unique": len(set(norms)),
        "text_norm_exact_rate": float(exact_norm / len(runs)) if runs else 0.0,
        "text_norm_min_similarity": float(min(sims) if sims else 0.0),
        "sources_unique": len(set(src_sig)),
        "sources_avg_jaccard_vs_first": float(sum(jacc) / len(jacc)) if jacc else 0.0,
        "sources_min_jaccard_vs_first": float(min(jacc) if jacc else 0.0),
        "latency_ms": {
            "avg": float(sum(ms) / len(ms)) if ms else 0.0,
            "p50": _percentile(ms, 50),
            "p90": _percentile(ms, 90),
            "min": int(min(ms) if ms else 0),
            "max": int(max(ms) if ms else 0),
        },
    }


def _read_question_bank(path: Path, *, prefix: str = "Q-G") -> List[BankQuestion]:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=_default_group_id())
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--max-questions", type=int, default=0)
    ap.add_argument("--include-llm-rephrase", action="store_true")
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()

    questions = _read_question_bank(qbank, prefix="Q-G")
    if args.max_questions and args.max_questions > 0:
        questions = questions[: int(args.max_questions)]

    scenarios = [
        {
            "name": "route3_global_synthesize_true",
            "endpoint_path": "/graphrag/v3/query/global",
            "synthesize": True,
            "result_field": "answer",
        },
        {
            "name": "nlp_audit_no_llm",
            "endpoint_path": "/graphrag/v3/query/global/audit",
            "synthesize": False,
            "result_field": "audit_summary",
        },
        {
            "name": "nlp_client_synthesize_false",
            "endpoint_path": "/graphrag/v3/query/global/client",
            "synthesize": False,
            "result_field": "audit_summary",
        },
    ]

    if bool(args.include_llm_rephrase):
        scenarios.append(
            {
                "name": "nlp_client_synthesize_true_llm_rephrase",
                "endpoint_path": "/graphrag/v3/query/global/client",
                "synthesize": True,
                "result_field": "rephrased_narrative",
            }
        )

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"repeatability_global10_llm_nlp_client_{stamp}.json"
    out_md = out_dir / f"repeatability_global10_llm_nlp_client_{stamp}.md"

    print(
        "\n".join(
            [
                "=== Global10 Repeatability: LLM vs NLP vs Client ===",
                f"url={base_url}",
                f"group_id={group_id}",
                f"repeats={int(args.repeats)} top_k={int(args.top_k)} timeout={float(args.timeout)}s",
                f"questions={len(questions)} question_bank={qbank}",
                "scenarios=" + ", ".join([sc["name"] for sc in scenarios]),
                f"out_json={out_json}",
                f"out_md={out_md}",
                "===================================================",
            ]
        ),
        flush=True,
    )

    headers = {"Content-Type": "application/json", "X-Group-ID": group_id}

    results: Dict[str, Dict[str, Any]] = {}

    for sc in scenarios:
        sc_name = sc["name"]
        endpoint = base_url + sc["endpoint_path"]
        results[sc_name] = {}

        for qi, q in enumerate(questions, 1):
            runs: List[Dict[str, Any]] = []
            for ri in range(int(args.repeats)):
                payload = {
                    "query": q.query,
                    "top_k": int(args.top_k),
                    "synthesize": bool(sc["synthesize"]),
                    "include_sources": True,
                }
                status, resp, elapsed_s, err = _http_post_json(
                    url=endpoint,
                    headers=headers,
                    payload=payload,
                    timeout_s=float(args.timeout),
                )

                text = str(resp.get(sc["result_field"]) or "") if isinstance(resp, dict) else ""
                text_norm = _normalize_text(text)

                run_row = {
                    "run": ri,
                    "status": status,
                    "elapsed_ms": int(round(elapsed_s * 1000.0)),
                    "result_field": sc["result_field"],
                    "text": text,
                    "text_norm": text_norm,
                    "md5": _md5(text),
                    "sources_ids": _extract_sources_ids(resp) if isinstance(resp, dict) else [],
                    "error": err,
                }
                runs.append(run_row)

            summary = _summarize_runs(runs)
            results[sc_name][q.qid] = {
                "question": q.query,
                "runs": runs,
                "summary": summary,
                "first_text_len": len(str(runs[0].get("text") or "")) if runs else 0,
                "first_text_preview": (str(runs[0].get("text") or "")[:240] if runs else ""),
            }

            print(
                f"[{sc_name}] [{qi}/{len(questions)}] {q.qid}: "
                f"exact={summary['text_norm_exact_rate']:.2f} min_sim={summary['text_norm_min_similarity']:.2f} "
                f"p50={summary['latency_ms']['p50']}ms"
            )

    report: Dict[str, Any] = {
        "suite": "repeatability-global10-llm-nlp-client",
        "timestamp_utc": stamp,
        "base_url": base_url,
        "group_id": group_id,
        "question_bank": qbank.name,
        "question_bank_path": str(qbank),
        "repeats": int(args.repeats),
        "top_k": int(args.top_k),
        "scenarios": scenarios,
        "questions": [{"qid": q.qid, "query": q.query} for q in questions],
        "results": results,
    }

    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Simple MD summary table
    md: List[str] = []
    md.append("# Route 3 Global10 — Repeatability (LLM vs NLP vs NLP+Client)")
    md.append("")
    md.append(f"- timestamp_utc: {stamp}")
    md.append(f"- base_url: {base_url}")
    md.append(f"- group_id: {group_id}")
    md.append(f"- repeats: {int(args.repeats)}")
    md.append(f"- top_k: {int(args.top_k)}")
    md.append(f"- question_bank: {qbank}")
    md.append("")

    for sc in scenarios:
        sc_name = sc["name"]
        md.append(f"## {sc_name}")
        md.append("")
        md.append("| QID | exact rate | min similarity | unique norm texts | avg ms | p50 | p90 | min src jacc |")
        md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for q in questions:
            s = (results.get(sc_name, {}).get(q.qid, {}) or {}).get("summary") or {}
            md.append(
                "| "
                + q.qid
                + " | "
                + f"{float(s.get('text_norm_exact_rate') or 0.0):.2f}"
                + " | "
                + f"{float(s.get('text_norm_min_similarity') or 0.0):.2f}"
                + " | "
                + str(int(s.get("text_norm_unique") or 0))
                + " | "
                + f"{float((s.get('latency_ms') or {}).get('avg') or 0.0):.1f}"
                + " | "
                + str(int((s.get("latency_ms") or {}).get("p50") or 0))
                + " | "
                + str(int((s.get("latency_ms") or {}).get("p90") or 0))
                + " | "
                + f"{float(s.get('sources_min_jaccard_vs_first') or 0.0):.2f}"
                + " |"
            )
        md.append("")

    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(str(out_json))
    print(str(out_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
