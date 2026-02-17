#!/usr/bin/env python3

"""Repeatability benchmark for Route 5 (Unified HippoRAG Search) via the Hybrid API.

This benchmark targets the *Unified Search* "Route 5" implementation exposed through:
  POST /hybrid/query  (force_route=unified_search)

Route 5 combines global and multi-hop search into a single PPR pass using
three-tier weighted seeds (NER, structural, thematic).

Scenario
- Uses response_type=summary (LLM synthesis, concise mode)
- Tests Q-G1-Q-G10 (global/thematic questions)
- Tests Q-D1-Q-D10 (multi-hop reasoning questions)
- Tests Q-N1-Q-N10 (negative: should return "not found")

Route 5 Improvements over Routes 3/4:
- 2 LLM calls (NER + synthesis) vs 12-15 in Route 3/4
- Single weighted PPR pass instead of multiple traversals
- Eliminates 38% decomposition hallucination rate
- Dynamic damping adapts to query type
- Parallel sentence search + seed resolution

Outputs
- Writes JSON + MD into ./benchmarks/

Usage
  python3 scripts/benchmark_route5_unified_search.py \
    --url https://...azurecontainerapps.io \
    --group-id test-5pdfs-v2-fix2 \
    --repeats 3

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
    GroundTruth,
    extract_ground_truth,
    calculate_accuracy_metrics,
    BankQuestion,
    read_question_bank,
)

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
    return "".join(
        [
            # prefer last_test_group_id.txt if available
            _read_text_maybe(
                Path(__file__).resolve().parents[1] / "last_test_group_id.txt"
            )
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


def _get_aad_token() -> Optional[str]:
    """Get Azure AD access token for API authentication."""
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
        return (
            int(getattr(e, "code", 0) or 0),
            {"error": str(e), "body": body},
            elapsed,
            str(e),
        )
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, {"error": str(e)}, elapsed, str(e)


def _read_question_bank(
    path: Path, *, positive_prefixes: List[str] = None, negative_prefix: str = "Q-N"
) -> List[BankQuestion]:
    """Read questions from question bank for Route 5 (both Q-G and Q-D questions)."""
    if positive_prefixes is None:
        positive_prefixes = ["Q-G", "Q-D"]  # Route 5 handles both global and multi-hop
    
    all_questions = []
    for prefix in positive_prefixes:
        questions = read_question_bank(path, positive_prefix=prefix, negative_prefix=negative_prefix)
        all_questions.extend(questions)
    
    # Also add negative questions
    negative_questions = read_question_bank(path, positive_prefix=negative_prefix, negative_prefix="NONE")
    all_questions.extend(negative_questions)
    
    return all_questions


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
            for key in (
                "id",
                "source_id",
                "doc_id",
                "document_id",
                "source",
                "uri",
                "url",
                "chunk_id",
            ):
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


def _extract_seed_tiers(resp: Any) -> Dict[str, int]:
    """Extract Route 5 specific seed tier information."""
    if not isinstance(resp, dict):
        return {}
    
    context_data = resp.get("context_data", {})
    if not isinstance(context_data, dict):
        return {}
    
    return {
        "tier1_seeds": context_data.get("tier1_seeds", 0),
        "tier2_seeds": context_data.get("tier2_seeds", 0),
        "tier3_seeds": context_data.get("tier3_seeds", 0),
        "ppr_nodes": context_data.get("ppr_nodes", 0),
        "sentence_evidence": context_data.get("sentence_evidence", 0),
    }


def _summarize_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [r.get("text", "") for r in runs]
    texts_norm = [r.get("text_norm", "") for r in runs]
    ms = [
        int(r.get("elapsed_ms", 0))
        for r in runs
        if isinstance(r.get("elapsed_ms"), int)
    ]

    first_norm = texts_norm[0] if texts_norm else ""
    sims = [_similarity(first_norm, t) for t in texts_norm] if texts_norm else []

    exact_norm = sum(1 for t in texts_norm if t == first_norm)

    cite_sigs = [r.get("citations_sig", []) for r in runs]

    citations_jacc = []
    if cite_sigs:
        base = cite_sigs[0]
        citations_jacc = [_jaccard(base, x) for x in cite_sigs[1:]]

    # Collect seed tier stats from Route 5
    seed_stats = [r.get("seed_tiers", {}) for r in runs]
    avg_tier1 = sum(s.get("tier1_seeds", 0) for s in seed_stats) / len(seed_stats) if seed_stats else 0
    avg_tier2 = sum(s.get("tier2_seeds", 0) for s in seed_stats) / len(seed_stats) if seed_stats else 0
    avg_tier3 = sum(s.get("tier3_seeds", 0) for s in seed_stats) / len(seed_stats) if seed_stats else 0
    avg_ppr = sum(s.get("ppr_nodes", 0) for s in seed_stats) / len(seed_stats) if seed_stats else 0

    return {
        "text_norm_exact_rate": float(exact_norm / len(runs)) if runs else 0.0,
        "text_norm_min_similarity": float(min(sims) if sims else 0.0),
        "citations_unique": len({json.dumps(x, sort_keys=True) for x in cite_sigs}),
        "citations_jaccard_min": float(min(citations_jacc) if citations_jacc else 1.0),
        "latency_ms_p50": _percentile(ms, 50),
        "latency_ms_p95": _percentile(ms, 95),
        "latency_ms_min": int(min(ms) if ms else 0),
        "latency_ms_max": int(max(ms) if ms else 0),
        "avg_tier1_seeds": round(avg_tier1, 1),
        "avg_tier2_seeds": round(avg_tier2, 1),
        "avg_tier3_seeds": round(avg_tier3, 1),
        "avg_ppr_nodes": round(avg_ppr, 1),
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
    synthesis_model: Optional[str] = None,
    include_context: bool = False,
    weight_profile: Optional[str] = None,
) -> Dict[str, Any]:
    print(f"\n{'=' * 70}")
    print(f"Scenario: {scenario_name} (response_type={response_type})")
    print(f"Questions: {len(questions)}, Repeats: {repeats}")
    if weight_profile:
        print(f"Weight Profile: {weight_profile}")
    print(f"{'=' * 70}\n")

    url = f"{api_base_url.rstrip('/')}/hybrid/query"
    headers = {"Content-Type": "application/json", "X-Group-ID": group_id}

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
            payload = {
                "group_id": group_id,
                "query": query,
                "force_route": "unified_search",  # Route 5
                "response_type": response_type,
            }
            if synthesis_model:
                payload["synthesis_model"] = synthesis_model
            if include_context:
                payload["include_context"] = True
            if weight_profile:
                payload["weight_profile"] = weight_profile

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
                print(
                    f"  [{rep}/{repeats}] HTTP {status} - {err or resp.get('error', 'unknown')}"
                )
                continue

            answer = resp.get("response", "") or resp.get("answer", "")
            text_norm = _normalize_text(answer)
            citations_sig = _extract_citation_ids(resp)
            seed_tiers = _extract_seed_tiers(resp)
            elapsed_ms = int(elapsed * 1000)

            print(f"  [{rep}/{repeats}] {elapsed_ms}ms - {len(answer)} chars")
            if seed_tiers:
                print(
                    f"    Seeds: T1={seed_tiers.get('tier1_seeds', 0)}, "
                    f"T2={seed_tiers.get('tier2_seeds', 0)}, "
                    f"T3={seed_tiers.get('tier3_seeds', 0)}, "
                    f"PPR={seed_tiers.get('ppr_nodes', 0)}"
                )

            run_row = {
                "run": rep,
                "text": answer,
                "text_norm": text_norm,
                "citations_sig": citations_sig,
                "seed_tiers": seed_tiers,
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
        accuracy_metrics = {}
        if qid in ground_truth and runs:
            gt = ground_truth[qid]
            # Use first run for accuracy check (all repeats should be similar)
            actual_answer = runs[0].get("text", "")
            accuracy_metrics = calculate_accuracy_metrics(
                expected=gt.expected, actual=actual_answer, is_negative=gt.is_negative
            )

            # Add to console output
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
        "weight_profile": weight_profile,
        "questions": results,
    }


def _write_analysis_md(
    out_md: Path,
    timestamp: str,
    api_base_url: str,
    group_id: str,
    scenario_results: List[Dict[str, Any]],
):
    with out_md.open("w", encoding="utf-8") as f:
        f.write(f"# Route 5 (Unified HippoRAG Search) Repeatability Benchmark\n\n")
        f.write(f"**Timestamp:** {timestamp}\n\n")
        f.write(f"**API Base URL:** `{api_base_url}`\n\n")
        f.write(f"**Group ID:** `{group_id}`\n\n")
        f.write(f"**Force Route:** `unified_search`\n\n")
        f.write("---\n\n")
        
        f.write("## Route 5 Architecture\n\n")
        f.write("Route 5 combines global and multi-hop search into a single PPR pass:\n\n")
        f.write("- **Three-tier weighted seeds**: NER entities (T1), structural seeds from sentences (T2), thematic seeds from communities (T3)\n")
        f.write("- **Single weighted PPR traversal** with dynamic damping\n")
        f.write("- **Parallel sentence vector search** (independent of PPR)\n")
        f.write("- **2 LLM calls total**: 1 NER + 1 synthesis (vs 12-15 in Routes 3/4)\n")
        f.write("- **Eliminates decomposition hallucination** (38% rate in Route 4)\n\n")
        f.write("---\n\n")

        for sc in scenario_results:
            f.write(f"## Scenario: {sc['scenario']}\n\n")
            f.write(f"**Response Type:** `{sc['response_type']}`\n\n")
            if sc.get("weight_profile"):
                f.write(f"**Weight Profile:** `{sc['weight_profile']}`\n\n")

            questions = sc["questions"]
            for q in questions:
                qid = q["qid"]
                query = q["query"]
                summary = q.get("summary", {})
                accuracy = q.get("accuracy", {})
                runs = q.get("runs", [])

                f.write(f"### {qid}: {query}\n\n")

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
                        f.write(
                            f"| Negative Test | {'✅ PASS' if passed else '❌ FAIL'} |\n"
                        )
                    else:
                        f.write(
                            f"| Exact Match | {'✅' if accuracy.get('exact_match', False) else '❌'} |\n"
                        )
                        f.write(f"| Fuzzy Score | {accuracy.get('fuzzy_score', 0):.2f} |\n")
                        f.write(f"| Containment | {accuracy.get('containment', 0):.2f} |\n")
                        f.write(f"| Precision | {accuracy.get('precision', 0):.2f} |\n")
                        f.write(f"| Recall | {accuracy.get('recall', 0):.2f} |\n")
                        f.write(f"| F1 Score | {accuracy.get('f1_score', 0):.2f} |\n")
                    f.write("\n")

                # Route 5 Specific Metrics
                f.write("**Route 5 Seed Metrics:**\n\n")
                f.write("| Metric | Value |\n")
                f.write("|--------|-------|\n")
                f.write(f"| Avg Tier 1 Seeds (NER) | {summary.get('avg_tier1_seeds', 0):.1f} |\n")
                f.write(f"| Avg Tier 2 Seeds (Structural) | {summary.get('avg_tier2_seeds', 0):.1f} |\n")
                f.write(f"| Avg Tier 3 Seeds (Thematic) | {summary.get('avg_tier3_seeds', 0):.1f} |\n")
                f.write(f"| Avg PPR Nodes Retrieved | {summary.get('avg_ppr_nodes', 0):.1f} |\n")
                f.write("\n")

                # Repeatability Metrics
                f.write("**Repeatability Metrics:**\n\n")
                f.write("| Metric | Value |\n")
                f.write("|--------|-------|\n")
                f.write(
                    f"| Exact Match Rate | {summary.get('text_norm_exact_rate', 0):.2f} |\n"
                )
                f.write(
                    f"| Min Similarity | {summary.get('text_norm_min_similarity', 0):.2f} |\n"
                )
                f.write(f"| Citations (Unique) | {summary.get('citations_unique', 0)} |\n")
                f.write(
                    f"| Citations Jaccard (Min) | {summary.get('citations_jaccard_min', 0):.2f} |\n"
                )
                f.write(f"| Latency P50 (ms) | {summary.get('latency_ms_p50', 0)} |\n")
                f.write(f"| Latency P95 (ms) | {summary.get('latency_ms_p95', 0)} |\n")
                f.write(f"| Latency Min (ms) | {summary.get('latency_ms_min', 0)} |\n")
                f.write(f"| Latency Max (ms) | {summary.get('latency_ms_max', 0)} |\n")
                f.write("\n")

                # Show first two answers for comparison
                for r in runs[:2]:
                    ans = r.get("text", "")
                    f.write(f"**Run {r['run']} ({r.get('elapsed_ms', 0)}ms):**\n\n")
                    f.write(
                        f"```\n{ans[:500]}{'...' if len(ans) > 500 else ''}\n```\n\n"
                    )

            f.write("---\n\n")


def main():
    parser = argparse.ArgumentParser(
        description="Route 5 (Unified HippoRAG Search) repeatability benchmark via Hybrid API."
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
        help="Number of times to repeat each query (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="HTTP timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--question-bank",
        type=Path,
        default=DEFAULT_QUESTION_BANK,
        help="Path to question bank markdown file",
    )
    parser.add_argument(
        "--synthesis-model",
        type=str,
        default=None,
        help="Override synthesis model (e.g., gpt-4o, gpt-4.1)",
    )
    parser.add_argument(
        "--weight-profile",
        type=str,
        default=None,
        choices=["balanced", "fact_extraction", "thematic_survey"],
        help="Weight profile for seed tiers (default: balanced)",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=None,
        help="Limit number of questions to test (for quick validation)",
    )

    args = parser.parse_args()

    timestamp = _now_utc_stamp()
    benchmarks_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    benchmarks_dir.mkdir(exist_ok=True)

    out_json = benchmarks_dir / f"route5_unified_search_{timestamp}.json"
    out_md = benchmarks_dir / f"route5_unified_search_{timestamp}.md"

    # Read question bank
    questions = _read_question_bank(
        args.question_bank,
        positive_prefixes=["Q-G", "Q-D"],  # Route 5 handles both
        negative_prefix="Q-N",
    )
    
    if args.max_questions:
        questions = questions[:args.max_questions]

    print(f"Loaded {len(questions)} questions from {args.question_bank}")

    # Extract ground truth
    ground_truth = extract_ground_truth(args.question_bank)
    print(f"Loaded ground truth for {len(ground_truth)} questions\n")

    # Run benchmark
    scenario_results = []

    scenario_result = benchmark_scenario(
        api_base_url=args.url,
        group_id=args.group_id,
        questions=questions,
        scenario_name="Route 5 Unified Search - Summary",
        response_type="summary",
        repeats=args.repeats,
        timeout_s=args.timeout,
        ground_truth=ground_truth,
        synthesis_model=args.synthesis_model,
        include_context=False,
        weight_profile=args.weight_profile,
    )
    scenario_results.append(scenario_result)

    # Write results
    output_data = {
        "benchmark": "route5_unified_search",
        "timestamp": timestamp,
        "api_base_url": args.url,
        "group_id": args.group_id,
        "repeats": args.repeats,
        "synthesis_model": args.synthesis_model,
        "weight_profile": args.weight_profile,
        "scenarios": scenario_results,
    }

    with out_json.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Wrote JSON: {out_json}")

    _write_analysis_md(
        out_md=out_md,
        timestamp=timestamp,
        api_base_url=args.url,
        group_id=args.group_id,
        scenario_results=scenario_results,
    )

    print(f"✅ Wrote MD: {out_md}")
    print("\nDone!")


if __name__ == "__main__":
    main()
