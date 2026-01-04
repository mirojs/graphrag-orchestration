#!/usr/bin/env python3

"""Repeatability benchmark for LazyGraphRAG Route-3 via the Hybrid API.

This benchmark targets the *LazyGraphRAG* "Route 3" implementation exposed through:
  POST /hybrid/query  (force_route=global_search)

It intentionally does NOT use the GraphRAG V3 global community endpoints:
  /graphrag/v3/query/global*

Important nuance
- The Hybrid pipeline's Route-3 answer is still synthesized by an LLM.
- What we can measure here is:
  - Response text repeatability (LLM variance)
  - Evidence stability (citations / evidence_path), which is often more deterministic

Scenario
- Uses response_type=summary (LLM synthesis, concise mode)
- Tests Q-G1-Q-G10 (positive: global/cross-section questions)
- Tests Q-N1-Q-N10 (negative: should return "not found")
- hybrid_global_nlp_audit:       response_type=nlp_audit (NLP extraction, 100% deterministic, no LLM)
- hybrid_global_nlp_connected:   response_type=nlp_connected (NLP extraction + temperature=0 rephrasing)

Outputs
- Writes JSON + MD into ./benchmarks/

Usage
  python3 scripts/benchmark_hybrid_global10_repeatability.py \
    --url https://...azurecontainerapps.io \
    --group-id <group> \
    --repeats 10

Dependency-free (stdlib only).
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

from benchmark_accuracy_utils import GroundTruth, extract_ground_truth, calculate_accuracy_metrics

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
    env = os.getenv("TEST_GROUP_ID") or os.getenv("GROUP_ID")
    if env:
        return env
    return "".join(
        [
            # prefer last_test_group_id.txt if available
            _read_text_maybe(Path(__file__).resolve().parents[1] / "last_test_group_id.txt")
            or ""
        ]
    ).strip() or "test-5pdfs-latest"


def _read_text_maybe(p: Path) -> Optional[str]:
    try:
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            return s or None
    except Exception:
        return None
    return None


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


def _jaccard(a: List[str], b: List[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return float(len(sa & sb) / len(sa | sb))


def _http_post_json(
    *,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_s: float,
) -> Tuple[int, Any, float, Optional[str]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.monotonic() - t0
            try:
                return int(resp.status), json.loads(raw), elapsed, None
            except Exception:
                return int(resp.status), {"raw": raw}, elapsed, None
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        body = None
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = None
        return int(getattr(e, "code", 0) or 0), {"error": str(e), "body": body}, elapsed, str(e)
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, {"error": str(e)}, elapsed, str(e)


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


def _extract_citation_ids(resp: Any) -> List[str]:
    if not isinstance(resp, dict):
        return []
    citations = resp.get("citations")
    if not isinstance(citations, list):
        return []
    ids: List[str] = []
    for c in citations:
        if isinstance(c, str):
            ids.append(c)
        elif isinstance(c, dict):
            # Prefer stable identifiers if present.
            for key in ("id", "source_id", "doc_id", "document_id", "source", "uri", "url", "chunk_id"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    ids.append(v.strip())
                    break
            else:
                # Fall back to a compact normalized string of the dict.
                try:
                    ids.append(json.dumps(c, sort_keys=True)[:200])
                except Exception:
                    pass
    return ids


def _extract_evidence_path(resp: Any) -> List[str]:
    if not isinstance(resp, dict):
        return []
    path = resp.get("evidence_path")
    if not isinstance(path, list):
        return []
    out: List[str] = []
    for item in path:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            v = item.get("entity") or item.get("name") or item.get("id")
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
    return out


def _summarize_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [r.get("text", "") for r in runs]
    texts_norm = [r.get("text_norm", "") for r in runs]
    ms = [int(r.get("elapsed_ms", 0)) for r in runs if isinstance(r.get("elapsed_ms"), int)]

    first_norm = texts_norm[0] if texts_norm else ""
    sims = [_similarity(first_norm, t) for t in texts_norm] if texts_norm else []

    exact_norm = sum(1 for t in texts_norm if t == first_norm)

    cite_sigs = [r.get("citations_sig", []) for r in runs]
    path_sigs = [r.get("evidence_path_sig", []) for r in runs]

    citations_jacc = []
    evidence_jacc = []
    if cite_sigs:
        base = cite_sigs[0]
        citations_jacc = [_jaccard(base, x) for x in cite_sigs[1:]]
    if path_sigs:
        base = path_sigs[0]
        evidence_jacc = [_jaccard(base, x) for x in path_sigs[1:]]

    return {
        "text_norm_exact_rate": float(exact_norm / len(runs)) if runs else 0.0,
        "text_norm_min_similarity": float(min(sims) if sims else 0.0),
        "citations_unique": len({json.dumps(x, sort_keys=True) for x in cite_sigs}),
        "citations_avg_jaccard_vs_first": float(sum(citations_jacc) / len(citations_jacc)) if citations_jacc else 0.0,
        "citations_min_jaccard_vs_first": float(min(citations_jacc) if citations_jacc else 0.0),
        "evidence_path_unique": len({json.dumps(x, sort_keys=True) for x in path_sigs}),
        "evidence_path_avg_jaccard_vs_first": float(sum(evidence_jacc) / len(evidence_jacc)) if evidence_jacc else 0.0,
        "evidence_path_min_jaccard_vs_first": float(min(evidence_jacc) if evidence_jacc else 0.0),
        "latency_ms": {
            "avg": float(sum(ms) / len(ms)) if ms else 0.0,
            "p50": _percentile(ms, 50),
            "p90": _percentile(ms, 90),
            "min": int(min(ms) if ms else 0),
            "max": int(max(ms) if ms else 0),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=_default_group_id())
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--top-k", type=int, default=5)  # hybrid currently ignores; kept for compatibility
    ap.add_argument("--max-questions", type=int, default=0)
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()

    # Load positive questions (Q-G*)
    positive_questions = _read_question_bank(qbank, prefix="Q-G")
    
    # Load negative questions (Q-N*) - handle gracefully if not found
    negative_questions = []
    try:
        negative_questions = _read_question_bank(qbank, prefix="Q-N")
    except RuntimeError:
        print("No Q-N* negative questions found in question bank")
    
    questions = positive_questions + negative_questions
    
    if args.max_questions and args.max_questions > 0:
        questions = questions[: int(args.max_questions)]
    
    positive_count = sum(1 for q in questions if q.qid.startswith("Q-G"))
    negative_count = sum(1 for q in questions if q.qid.startswith("Q-N"))
    print(f"Loaded {len(questions)} questions: {positive_count} positive (Q-G), {negative_count} negative (Q-N)")
    
    # Load ground truth
    ground_truth = extract_ground_truth(qbank)
    print(f"Loaded {len(ground_truth)} ground truth answers")

    # Single scenario: summary mode
    scenario_name = "hybrid_global_summary"
    response_type = "summary"

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"route3_global_search_{stamp}.json"
    out_md = out_dir / f"route3_global_search_{stamp}.md"

    print(
        "\n".join(
            [
                "=== Route 3: Global Search (LazyGraphRAG) ===",
                f"url={base_url}",
                f"group_id={group_id}",
                f"repeats={int(args.repeats)} timeout={float(args.timeout)}s",
                f"questions={len(questions)} question_bank={qbank}",
                f"scenario={scenario_name} response_type={response_type}",
                f"out_json={out_json}",
                f"out_md={out_md}",
                "==============================================",
            ]
        ),
        flush=True,
    )

    headers = {"Content-Type": "application/json", "X-Group-ID": group_id}

    results: Dict[str, Dict[str, Any]] = {}
    endpoint = base_url + "/hybrid/query"

    results[scenario_name] = {}

    for qi, q in enumerate(questions, 1):
        runs: List[Dict[str, Any]] = []
        for ri in range(int(args.repeats)):
            payload = {
                "query": q.query,
                "force_route": "global_search",
                "response_type": response_type,
            }

            status, resp, elapsed_s, err = _http_post_json(
                url=endpoint,
                headers=headers,
                payload=payload,
                timeout_s=float(args.timeout),
            )

            if isinstance(resp, dict):
                text = str(resp.get("response") or "")
            else:
                text = ""

            citations_sig = _extract_citation_ids(resp)
            evidence_path_sig = _extract_evidence_path(resp)

            run_row = {
                "run": ri,
                "status": status,
                "elapsed_ms": int(round(elapsed_s * 1000.0)),
                "text": text,
                "text_norm": _normalize_text(text),
                "citations_sig": citations_sig,
                "evidence_path_sig": evidence_path_sig,
                "error": err,
            }
            runs.append(run_row)

        summary = _summarize_runs(runs)
        
        # Calculate accuracy metrics
        accuracy_metrics = {}
        if q.qid in ground_truth and runs:
            gt = ground_truth[q.qid]
            # Use first run for accuracy check (all repeats should be similar)
            actual_answer = runs[0].get("text", "")
            accuracy_metrics = calculate_accuracy_metrics(
                expected=gt.expected,
                actual=actual_answer,
                is_negative=gt.is_negative
            )
        
        results[scenario_name][q.qid] = {
            "qid": q.qid,
            "query": q.query,
            "runs": runs,
            "summary": summary,
            "accuracy": accuracy_metrics,
        }

        # Console output with accuracy
        acc_str = ""
        if accuracy_metrics:
            if accuracy_metrics.get("is_negative", False):
                passed = accuracy_metrics.get("negative_test_pass", False)
                acc_str = f" | NEGATIVE_TEST {'PASS' if passed else 'FAIL'}"
            else:
                containment = accuracy_metrics.get("containment", 0.0)
                f1 = accuracy_metrics.get("f1_score", 0.0)
                acc_str = f" | acc: contain={containment:.2f} f1={f1:.2f}"
        
        print(
            f"[{scenario_name}] [{qi}/{len(questions)}] {q.qid}: "
            f"exact={summary['text_norm_exact_rate']:.2f} "
            f"min_sim={summary['text_norm_min_similarity']:.2f} "
            f"cite_jacc_min={summary['citations_min_jaccard_vs_first']:.2f} "
            f"path_jacc_min={summary['evidence_path_min_jaccard_vs_first']:.2f} "
            f"p50={summary['latency_ms']['p50']}ms{acc_str}",
            flush=True,
        )

    out_payload = {
        "meta": {
            "created_utc": stamp,
            "url": base_url,
            "group_id": group_id,
            "endpoint": "/hybrid/query",
            "question_bank": str(qbank),
            "repeats": int(args.repeats),
            "timeout_s": float(args.timeout),
            "note": "Hybrid global_search uses LLM synthesis; evidence stability is also reported.",
        },
        "results": results,
    }

    out_json.write_text(json.dumps(out_payload, indent=2, sort_keys=True), encoding="utf-8")

    # Minimal MD report
    lines: List[str] = []
    lines.append(f"# Hybrid (LazyGraphRAG) Global10 Repeatability ({stamp})\n")
    lines.append(f"- url: `{base_url}`\n")
    lines.append(f"- group_id: `{group_id}`\n")
    lines.append(f"- endpoint: `/hybrid/query` (force_route=`global_search`)\n")
    lines.append(f"- repeats: `{int(args.repeats)}`\n")
    lines.append("\n")

    for sc_name, qmap in results.items():
        lines.append(f"## {sc_name}\n")
        for qid, obj in qmap.items():
            summ = obj.get("summary", {})
            acc = obj.get("accuracy", {})
            lat = summ.get("latency_ms", {})
            
            # Build accuracy string
            acc_info = ""
            if acc:
                if acc.get("is_negative", False):
                    passed = acc.get("negative_test_pass", False)
                    acc_info = f", NEG_TEST={'PASS' if passed else 'FAIL'}"
                else:
                    acc_info = f", contain={acc.get('containment', 0):.2f}, f1={acc.get('f1_score', 0):.2f}"
            
            lines.append(
                f"- {qid}: exact={summ.get('text_norm_exact_rate', 0):.2f}, "
                f"min_sim={summ.get('text_norm_min_similarity', 0):.2f}, "
                f"cite_min_jacc={summ.get('citations_min_jaccard_vs_first', 0):.2f}, "
                f"path_min_jacc={summ.get('evidence_path_min_jaccard_vs_first', 0):.2f}, "
                f"p50={lat.get('p50', 0)}ms{acc_info}\n"
            )
        lines.append("\n")

    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(str(out_json))
    print(str(out_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
