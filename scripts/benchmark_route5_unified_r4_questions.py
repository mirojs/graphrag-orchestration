#!/usr/bin/env python3

"""Route 4 benchmark questions executed against Route 5 (Unified HippoRAG).

This benchmark runs the same Q-D (drift/multi-hop) positive questions and
Q-N (negative) questions from the Route 4 benchmark against Route 5's
unified_search route, enabling a direct head-to-head comparison.

Route 5 uses a single PPR pass with 3-tier weighted seeds instead of
Route 4's decomposition + iterative drift pipeline.

Endpoint:
  POST /hybrid/query  (force_route=unified_search)

Scenario
- Uses response_type=summary (default, configurable)
- Tests Q-D1–Q-D10 (positive: drift/multi-hop reasoning questions)
- Tests Q-N1–Q-N10 (negative: should return "not found")

Outputs
- Writes JSON + MD into ./benchmarks/

Usage
  python3 scripts/benchmark_route5_unified_r4_questions.py \\
    --url https://...azurecontainerapps.io \\
    --group-id <group> \\
    --repeats 3

  # With specific weight profile
  python3 scripts/benchmark_route5_unified_r4_questions.py \\
    --weight-profile multi_hop \\
    --repeats 3

  # Single question
  python3 scripts/benchmark_route5_unified_r4_questions.py \\
    --filter-qid Q-D3 \\
    --repeats 5

Dependency-free (stdlib only).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from benchmark_accuracy_utils import (
    BankQuestion,
    GroundTruth,
    calculate_accuracy_metrics,
    extract_ground_truth,
    read_question_bank,
)

FORCE_ROUTE = "unified_search"   # Route 5
ROUTE_LABEL = "route5_unified"

DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
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
    return (
        _read_text_maybe(Path(__file__).resolve().parents[1] / "last_test_group_id.txt")
        or "test-5pdfs-latest"
    )


def _read_text_maybe(p: Path) -> Optional[str]:
    try:
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            return s or None
    except Exception:
        return None
    return None


def _get_aad_token() -> Optional[str]:
    """Get Azure AD access token for API authentication.
    
    Priority:
      1. GRAPHRAG_API_TOKEN env var (manual token)
      2. az CLI (if installed)
    """
    # 1. Check for manual token
    manual = os.getenv("GRAPHRAG_API_TOKEN")
    if manual:
        print("Using token from GRAPHRAG_API_TOKEN env var")
        return manual.strip()

    # 2. Fall back to az CLI
    try:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--scope",
                "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default",
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Failed to get AAD token: {e}")
        return None


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
            for key in ("id", "source_id", "doc_id", "document_id", "source", "uri", "url", "chunk_id"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    ids.append(v.strip())
                    break
            else:
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
        "evidence_path_unique": len({json.dumps(x, sort_keys=True) for x in path_sigs}),
        "citations_jaccard_min": float(min(citations_jacc) if citations_jacc else 1.0),
        "evidence_path_jaccard_min": float(min(evidence_jacc) if evidence_jacc else 1.0),
        "latency_ms_p50": _percentile(ms, 50),
        "latency_ms_p95": _percentile(ms, 95),
        "latency_ms_min": int(min(ms) if ms else 0),
        "latency_ms_max": int(max(ms) if ms else 0),
    }


def benchmark_scenario(
    *,
    api_base_url: str,
    group_id: str,
    questions: List[BankQuestion],
    scenario_name: str,
    response_type: str,
    repeats: int,
    timeout_s: float,
    ground_truth: Dict[str, GroundTruth],
    weight_profile: Optional[str] = None,
    synthesis_model: Optional[str] = None,
    include_context: bool = False,
) -> Dict[str, Any]:
    print(f"\n{'=' * 70}")
    print(f"Scenario: {scenario_name} (response_type={response_type})")
    print(f"Force route: {FORCE_ROUTE}")
    if weight_profile:
        print(f"Weight profile: {weight_profile}")
    print(f"Questions: {len(questions)}, Repeats: {repeats}")
    print(f"{'=' * 70}\n")

    url = f"{api_base_url.rstrip('/')}/hybrid/query"
    headers: Dict[str, str] = {"Content-Type": "application/json", "X-Group-ID": group_id}

    # Add Azure AD authentication if available
    token = _get_aad_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        print("✓ Using Azure AD authentication\n")
    else:
        print("⚠ No authentication token available\n")

    results: List[Dict[str, Any]] = []

    for q_obj in questions:
        qid, query = q_obj.qid, q_obj.query
        print(f"[{qid}] {query}")

        runs: List[Dict[str, Any]] = []
        for rep in range(1, repeats + 1):
            payload: Dict[str, Any] = {
                "group_id": group_id,
                "query": query,
                "force_route": FORCE_ROUTE,
                "response_type": response_type,
            }
            if weight_profile:
                payload["weight_profile"] = weight_profile
            if synthesis_model:
                payload["synthesis_model"] = synthesis_model
            if include_context:
                payload["include_context"] = True

            status, resp, elapsed, err = _http_post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_s=timeout_s,
            )

            # Retry once on 500 (transient Neo4j SSL timeouts)
            if status == 500:
                print(f"  [{rep}/{repeats}] HTTP 500 — retrying in 5s...")
                time.sleep(5)
                status, resp, elapsed, err = _http_post_json(
                    url=url,
                    headers=headers,
                    payload=payload,
                    timeout_s=timeout_s,
                )

            if status != 200:
                print(f"  [{rep}/{repeats}] HTTP {status} - {err or resp.get('error', 'unknown')}")
                continue

            answer = resp.get("response", "") or resp.get("answer", "")
            text_norm = _normalize_text(answer)
            citations_sig = _extract_citation_ids(resp)
            evidence_path_sig = _extract_evidence_path(resp)
            elapsed_ms = int(elapsed * 1000)

            print(f"  [{rep}/{repeats}] {elapsed_ms}ms - {len(answer)} chars")

            run_row: Dict[str, Any] = {
                "run": rep,
                "text": answer,
                "text_norm": text_norm,
                "citations_sig": citations_sig,
                "evidence_path_sig": evidence_path_sig,
                "elapsed_ms": elapsed_ms,
                "full_response": resp,
            }
            if include_context and isinstance(resp, dict):
                llm_ctx = (resp.get("metadata") or {}).get("llm_context")
                if llm_ctx:
                    run_row["llm_context"] = llm_ctx
            runs.append(run_row)

        summary = _summarize_runs(runs) if runs else {}

        # Calculate accuracy metrics
        accuracy_metrics: Dict[str, Any] = {}
        if qid in ground_truth and runs:
            gt = ground_truth[qid]
            actual_answer = runs[0].get("text", "")
            accuracy_metrics = calculate_accuracy_metrics(
                expected=gt.expected,
                actual=actual_answer,
                is_negative=gt.is_negative,
            )

            if gt.is_negative:
                passed = accuracy_metrics.get("negative_test_pass", False)
                print(f"  Accuracy: NEGATIVE_TEST {'PASS' if passed else 'FAIL'}")
            else:
                containment = accuracy_metrics.get("containment", 0.0)
                f1 = accuracy_metrics.get("f1_score", 0.0)
                print(f"  Accuracy: containment={containment:.2f}, f1={f1:.2f}")

        results.append(
            {
                "qid": qid,
                "query": query,
                "runs": runs,
                "summary": summary,
                "accuracy": accuracy_metrics,
            }
        )

        if summary:
            print(
                f"  Summary: exact={summary['text_norm_exact_rate']:.2f}, "
                f"min_sim={summary['text_norm_min_similarity']:.2f}, "
                f"latency_p50={summary['latency_ms_p50']}ms"
            )

    return {
        "scenario": scenario_name,
        "response_type": response_type,
        "questions": results,
    }


def _write_analysis_md(
    out_md: Path,
    timestamp: str,
    api_base_url: str,
    group_id: str,
    weight_profile: Optional[str],
    scenario_results: List[Dict[str, Any]],
):
    with out_md.open("w", encoding="utf-8") as f:
        f.write("# Route 5 (Unified HippoRAG) — Route 4 Question Benchmark\n\n")
        f.write(f"**Timestamp:** {timestamp}\n\n")
        f.write(f"**API Base URL:** `{api_base_url}`\n\n")
        f.write(f"**Group ID:** `{group_id}`\n\n")
        f.write(f"**Force Route:** `{FORCE_ROUTE}`\n\n")
        if weight_profile:
            f.write(f"**Weight Profile:** `{weight_profile}`\n\n")
        f.write(
            "**Purpose:** Run the same Q-D (drift/multi-hop) and Q-N (negative) "
            "question sets used for Route 4 benchmarks against Route 5 for "
            "head-to-head comparison.\n\n"
        )
        f.write("---\n\n")

        for sc in scenario_results:
            f.write(f"## Scenario: {sc['scenario']}\n\n")
            f.write(f"**Response Type:** `{sc['response_type']}`\n\n")

            questions = sc["questions"]

            # ── Summary table ──────────────────────────────────────
            f.write("### Summary Table\n\n")
            f.write(
                "| QID | Containment | F1 | Neg Pass | "
                "Exact Rate | Min Sim | P50 ms | P95 ms |\n"
            )
            f.write(
                "|-----|-------------|-----|----------|"
                "------------|---------|--------|--------|\n"
            )
            for q in questions:
                qid = q["qid"]
                acc = q.get("accuracy", {})
                sm = q.get("summary", {})
                if acc.get("is_negative"):
                    neg = "✅" if acc.get("negative_test_pass") else "❌"
                    f.write(
                        f"| {qid} | — | — | {neg} | "
                        f"{sm.get('text_norm_exact_rate', 0):.2f} | "
                        f"{sm.get('text_norm_min_similarity', 0):.2f} | "
                        f"{sm.get('latency_ms_p50', 0)} | "
                        f"{sm.get('latency_ms_p95', 0)} |\n"
                    )
                else:
                    f.write(
                        f"| {qid} | {acc.get('containment', 0):.2f} | "
                        f"{acc.get('f1_score', 0):.2f} | — | "
                        f"{sm.get('text_norm_exact_rate', 0):.2f} | "
                        f"{sm.get('text_norm_min_similarity', 0):.2f} | "
                        f"{sm.get('latency_ms_p50', 0)} | "
                        f"{sm.get('latency_ms_p95', 0)} |\n"
                    )
            f.write("\n")

            # ── Aggregate accuracy ─────────────────────────────────
            pos_qs = [q for q in questions if not q.get("accuracy", {}).get("is_negative")]
            neg_qs = [q for q in questions if q.get("accuracy", {}).get("is_negative")]

            if pos_qs:
                avg_cont = sum(q["accuracy"].get("containment", 0) for q in pos_qs) / len(pos_qs)
                avg_f1 = sum(q["accuracy"].get("f1_score", 0) for q in pos_qs) / len(pos_qs)
                f.write(f"**Positive questions avg containment:** {avg_cont:.2f}  \n")
                f.write(f"**Positive questions avg F1:** {avg_f1:.2f}  \n\n")

            if neg_qs:
                neg_pass = sum(1 for q in neg_qs if q["accuracy"].get("negative_test_pass"))
                f.write(f"**Negative tests passed:** {neg_pass}/{len(neg_qs)}  \n\n")

            # ── Per-question detail ────────────────────────────────
            f.write("### Per-Question Detail\n\n")
            for q in questions:
                qid = q["qid"]
                query = q["query"]
                summary = q.get("summary", {})
                accuracy = q.get("accuracy", {})
                runs = q.get("runs", [])

                f.write(f"#### {qid}: {query}\n\n")

                if not runs:
                    f.write("**No successful runs.**\n\n")
                    continue

                f.write(f"**Runs:** {len(runs)}\n\n")

                # Accuracy Metrics
                if accuracy:
                    f.write("**Accuracy Metrics:**\n\n")
                    f.write("| Metric | Value |\n")
                    f.write("|--------|-------|\n")

                    if accuracy.get("is_negative", False):
                        passed = accuracy.get("negative_test_pass", False)
                        f.write(f"| Negative Test | {'✅ PASS' if passed else '❌ FAIL'} |\n")
                    else:
                        f.write(f"| Exact Match | {'✅' if accuracy.get('exact_match', False) else '❌'} |\n")
                        f.write(f"| Fuzzy Score | {accuracy.get('fuzzy_score', 0):.2f} |\n")
                        f.write(f"| Containment | {accuracy.get('containment', 0):.2f} |\n")
                        f.write(f"| Precision | {accuracy.get('precision', 0):.2f} |\n")
                        f.write(f"| Recall | {accuracy.get('recall', 0):.2f} |\n")
                        f.write(f"| F1 Score | {accuracy.get('f1_score', 0):.2f} |\n")
                    f.write("\n")

                # Repeatability Metrics
                f.write("**Repeatability Metrics:**\n\n")
                f.write("| Metric | Value |\n")
                f.write("|--------|-------|\n")
                f.write(f"| Exact Match Rate | {summary.get('text_norm_exact_rate', 0):.2f} |\n")
                f.write(f"| Min Similarity | {summary.get('text_norm_min_similarity', 0):.2f} |\n")
                f.write(f"| Citations (Unique) | {summary.get('citations_unique', 0)} |\n")
                f.write(f"| Evidence Path (Unique) | {summary.get('evidence_path_unique', 0)} |\n")
                f.write(f"| Citations Jaccard (Min) | {summary.get('citations_jaccard_min', 0):.2f} |\n")
                f.write(f"| Evidence Path Jaccard (Min) | {summary.get('evidence_path_jaccard_min', 0):.2f} |\n")
                f.write(f"| Latency P50 (ms) | {summary.get('latency_ms_p50', 0)} |\n")
                f.write(f"| Latency P95 (ms) | {summary.get('latency_ms_p95', 0)} |\n")
                f.write(f"| Latency Min (ms) | {summary.get('latency_ms_min', 0)} |\n")
                f.write(f"| Latency Max (ms) | {summary.get('latency_ms_max', 0)} |\n")
                f.write("\n")

                # Show first two answers
                for r in runs[:2]:
                    ans = r.get("text", "")
                    f.write(f"**Run {r['run']} ({r.get('elapsed_ms', 0)}ms):**\n\n")
                    f.write(f"```\n{ans[:500]}{'...' if len(ans) > 500 else ''}\n```\n\n")

            f.write("---\n\n")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run Route 4 benchmark questions (Q-D + Q-N) against "
            "Route 5 (Unified HippoRAG) for head-to-head comparison."
        )
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="API base URL (default: env GRAPHRAG_CLOUD_URL or internal default)",
    )
    parser.add_argument(
        "--group-id",
        default=_default_group_id(),
        help="The group_id to query (default: from env or last_test_group_id.txt)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of times to repeat each question (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="HTTP request timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--qbank",
        type=Path,
        default=DEFAULT_QUESTION_BANK,
        help="Path to question bank MD file (default: QUESTION_BANK_5PDFS_2025-12-24.md)",
    )
    parser.add_argument(
        "--filter-qid",
        type=str,
        default=None,
        help="Run only a specific question ID (e.g., Q-D3)",
    )
    parser.add_argument(
        "--response-type",
        type=str,
        default="summary",
        choices=["summary", "detailed_report", "nlp_audit", "nlp_connected"],
        help="Response type for synthesis (default: summary)",
    )
    parser.add_argument(
        "--weight-profile",
        type=str,
        default=None,
        choices=["fact_extraction", "thematic_survey", "multi_hop", "balanced"],
        help="Route 5 weight profile (default: server picks based on query)",
    )
    parser.add_argument(
        "--synthesis-model",
        type=str,
        default=None,
        help="Override synthesis LLM deployment name (e.g. 'gpt-4.1'). If None, uses server default.",
    )
    parser.add_argument(
        "--include-context",
        action="store_true",
        default=False,
        help="Include full LLM context in benchmark output for debugging/replay",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Azure AD Bearer token (alternative to az CLI). Also accepts GRAPHRAG_API_TOKEN env var.",
    )

    args = parser.parse_args()

    # Allow --token to set the env var so _get_aad_token() picks it up
    if args.token:
        os.environ["GRAPHRAG_API_TOKEN"] = args.token

    qbank_path: Path = args.qbank
    if not qbank_path.exists():
        raise FileNotFoundError(f"Question bank not found: {qbank_path}")

    # Read questions — same sets as Route 4 benchmark (Q-D + Q-N)
    questions = read_question_bank(qbank_path, positive_prefix="Q-D", negative_prefix="Q-N")

    # Apply filter if specified
    if args.filter_qid:
        questions = [q for q in questions if q.qid == args.filter_qid]
        if not questions:
            print(f"No question found with ID: {args.filter_qid}")
            return
        print(f"Filtered to single question: {args.filter_qid}")
    else:
        print(f"Loaded {len(questions)} questions from {qbank_path.name}")

    positive_count = sum(1 for q in questions if q.qid.startswith("Q-D"))
    negative_count = sum(1 for q in questions if q.qid.startswith("Q-N"))
    print(f"  Positive tests (Q-D): {positive_count}")
    print(f"  Negative tests (Q-N): {negative_count}")

    # Load ground truth
    ground_truth = extract_ground_truth(qbank_path)
    print(f"Loaded {len(ground_truth)} ground truth answers")

    # Scenario
    wp_tag = f"_{args.weight_profile}" if args.weight_profile else ""
    scenario_name = f"{ROUTE_LABEL}_r4questions{wp_tag}_{args.response_type}"

    timestamp = _now_utc_stamp()

    if args.synthesis_model:
        print(f"Synthesis model override: {args.synthesis_model}")
    if args.weight_profile:
        print(f"Weight profile: {args.weight_profile}")
    if args.include_context:
        print("Including LLM context in output")

    result = benchmark_scenario(
        api_base_url=args.url,
        group_id=args.group_id,
        questions=questions,
        scenario_name=scenario_name,
        response_type=args.response_type,
        repeats=args.repeats,
        timeout_s=args.timeout,
        ground_truth=ground_truth,
        weight_profile=args.weight_profile,
        synthesis_model=args.synthesis_model,
        include_context=args.include_context,
    )

    # Write outputs
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = f"_wp-{args.weight_profile}" if args.weight_profile else ""
    out_json = out_dir / f"{ROUTE_LABEL}_r4questions{suffix}_{timestamp}.json"
    out_md = out_dir / f"{ROUTE_LABEL}_r4questions{suffix}_{timestamp}.md"

    with out_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "api_base_url": args.url,
                "group_id": args.group_id,
                "force_route": FORCE_ROUTE,
                "weight_profile": args.weight_profile or "auto",
                "response_type": args.response_type,
                "synthesis_model": args.synthesis_model or "default (gpt-5.1)",
                "comparison_baseline": "route4_drift_multi_hop",
                "scenario": result,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    _write_analysis_md(
        out_md=out_md,
        timestamp=timestamp,
        api_base_url=args.url,
        group_id=args.group_id,
        weight_profile=args.weight_profile,
        scenario_results=[result],
    )

    print(f"\n{'=' * 70}")
    print("✅ Route 5 benchmark (R4 questions) complete!")
    print(f"   JSON: {out_json}")
    print(f"   MD:   {out_md}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
