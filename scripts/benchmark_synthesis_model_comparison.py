#!/usr/bin/env python3

"""Synthesis Model Comparison Benchmark for Route 3 (Global Search).

Compares different LLM models for answer synthesis quality, speed, and output length.
Skips repeated retrieval by capturing LLM context once, then replaying it through
different synthesis models via the `synthesis_model` API parameter.

Strategy
--------
1. Phase 1 ("capture"):  Run each question ONCE with include_context=true to get
   the retrieved evidence and a baseline answer.
2. Phase 2 ("compare"):  For each model in --models, re-run each question with
   synthesis_model=<model>.  The retrieval pipeline is the same (deterministic),
   so the only variable is the synthesis LLM.

Outputs
-------
- JSON + MD in ./benchmarks/ with per-model, per-question metrics:
  - latency (ms)
  - output length (chars, words)
  - theme coverage (matched expected terms)
  - accuracy (containment, f1)

Usage
-----
  python3 scripts/benchmark_synthesis_model_comparison.py \\
    --models gpt-5.1 gpt-4.1 gpt-4o-mini \\
    --repeats 1 \\
    --max-questions 10

  # Use saved context from a previous benchmark (with include_context):
  python3 scripts/benchmark_synthesis_model_comparison.py \\
    --from-context benchmarks/route3_global_search_20260208T114347Z.json \\
    --models gpt-5.1 gpt-4.1 gpt-4o-mini

Dependency-free (stdlib only, plus local benchmark_accuracy_utils).
"""

from __future__ import annotations

import argparse
import datetime as _dt
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

# Re-use helpers from the main benchmark
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_accuracy_utils import GroundTruth, extract_ground_truth, calculate_accuracy_metrics
from benchmark_route3_global_search import (
    EXPECTED_TERMS,
    NEGATIVE_QUERY_SUFFIX,
    calculate_theme_coverage,
    _get_aad_token,
    _http_post_json,
    _read_question_bank,
    _normalize_text,
    _now_utc_stamp,
    _default_group_id,
    DEFAULT_URL,
    DEFAULT_QUESTION_BANK,
    BankQuestion,
)


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _run_single_query(
    *,
    endpoint: str,
    headers: Dict[str, str],
    query: str,
    response_type: str,
    timeout_s: float,
    synthesis_model: Optional[str] = None,
    include_context: bool = False,
) -> Dict[str, Any]:
    """Fire one query and return structured result."""
    payload: Dict[str, Any] = {
        "query": query,
        "force_route": "global_search",
        "response_type": response_type,
    }
    if synthesis_model:
        payload["synthesis_model"] = synthesis_model
    if include_context:
        payload["include_context"] = True

    status, resp, elapsed_s, err = _http_post_json(
        url=endpoint,
        headers=headers,
        payload=payload,
        timeout_s=timeout_s,
    )

    text = ""
    llm_context = None
    if isinstance(resp, dict):
        text = str(resp.get("response") or "")
        meta = resp.get("metadata") or {}
        llm_context = meta.get("llm_context")

    return {
        "status": status,
        "elapsed_ms": int(round(elapsed_s * 1000)),
        "text": text,
        "text_length_chars": len(text),
        "text_length_words": _word_count(text),
        "error": err,
        "llm_context": llm_context,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare synthesis LLM models on Route 3 using identical retrieved context."
    )
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=_default_group_id())
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument(
        "--models",
        nargs="+",
        default=["gpt-5.1", "gpt-4.1", "gpt-4o-mini"],
        help="List of synthesis model deployment names to compare",
    )
    ap.add_argument("--repeats", type=int, default=1, help="Repeats per model per question")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--max-questions", type=int, default=0, help="Limit questions (0=all)")
    ap.add_argument(
        "--questions-only",
        default="positive",
        choices=["positive", "negative", "all"],
        help="Which questions to test",
    )
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()
    models = list(args.models)

    # Load questions
    positive_questions = _read_question_bank(qbank, prefix="Q-G")
    negative_questions = []
    try:
        negative_questions = _read_question_bank(qbank, prefix="Q-N")
    except RuntimeError:
        pass

    if args.questions_only == "positive":
        questions = positive_questions
    elif args.questions_only == "negative":
        questions = negative_questions
    else:
        questions = positive_questions + negative_questions

    if args.max_questions and args.max_questions > 0:
        questions = questions[: args.max_questions]

    # Load ground truth
    ground_truth = extract_ground_truth(qbank)

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"synthesis_model_comparison_{stamp}.json"
    out_md = out_dir / f"synthesis_model_comparison_{stamp}.md"

    print("=" * 60)
    print("SYNTHESIS MODEL COMPARISON BENCHMARK")
    print("=" * 60)
    print(f"  url:        {base_url}")
    print(f"  group_id:   {group_id}")
    print(f"  models:     {models}")
    print(f"  questions:  {len(questions)} ({args.questions_only})")
    print(f"  repeats:    {args.repeats}")
    print(f"  timeout:    {args.timeout}s")
    print(f"  output:     {out_json}")
    print("=" * 60, flush=True)

    # Auth
    token = _get_aad_token()
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "X-Group-ID": group_id,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        print("✓ Using Azure AD authentication", flush=True)

    endpoint = base_url + "/hybrid/query"

    # Results: model -> qid -> {runs, summary}
    results: Dict[str, Dict[str, Any]] = {m: {} for m in models}

    total_calls = len(models) * len(questions) * args.repeats
    call_num = 0

    for qi, q in enumerate(questions, 1):
        gt = ground_truth.get(q.qid)
        effective_query = (
            (q.query + NEGATIVE_QUERY_SUFFIX) if (gt and gt.is_negative) else q.query
        )

        for model in models:
            runs = []
            for ri in range(args.repeats):
                call_num += 1
                result = _run_single_query(
                    endpoint=endpoint,
                    headers=headers,
                    query=effective_query,
                    response_type="summary",
                    timeout_s=args.timeout,
                    synthesis_model=model,
                    include_context=(ri == 0),  # capture context on first run only
                )

                run_row = {
                    "run": ri,
                    "status": result["status"],
                    "elapsed_ms": result["elapsed_ms"],
                    "text": result["text"],
                    "text_length_chars": result["text_length_chars"],
                    "text_length_words": result["text_length_words"],
                    "error": result["error"],
                }
                # Save context only on first run for reference
                if ri == 0 and result.get("llm_context"):
                    run_row["llm_context"] = result["llm_context"]
                runs.append(run_row)

            # Compute metrics from first run
            first_text = runs[0]["text"] if runs else ""

            # Theme coverage
            theme = {}
            if q.qid.startswith("Q-G") and q.qid in EXPECTED_TERMS:
                theme = calculate_theme_coverage(first_text, EXPECTED_TERMS[q.qid])

            # Accuracy
            accuracy = {}
            if q.qid in ground_truth and runs:
                accuracy = calculate_accuracy_metrics(
                    expected=ground_truth[q.qid].expected,
                    actual=first_text,
                    is_negative=ground_truth[q.qid].is_negative,
                )

            # Latency stats
            latencies = [r["elapsed_ms"] for r in runs if r["status"] == 200]
            avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
            char_lengths = [r["text_length_chars"] for r in runs]
            word_lengths = [r["text_length_words"] for r in runs]

            summary = {
                "qid": q.qid,
                "query": q.query,
                "model": model,
                "avg_latency_ms": avg_latency,
                "min_latency_ms": min(latencies) if latencies else 0,
                "max_latency_ms": max(latencies) if latencies else 0,
                "avg_chars": int(sum(char_lengths) / len(char_lengths)) if char_lengths else 0,
                "avg_words": int(sum(word_lengths) / len(word_lengths)) if word_lengths else 0,
                "theme_coverage": theme,
                "accuracy": accuracy,
                "runs": runs,
            }
            results[model][q.qid] = summary

            # Print progress
            tc = theme.get("coverage", -1)
            tc_str = f"theme={tc:.0%}" if tc >= 0 else ""
            cont = accuracy.get("containment", -1)
            cont_str = f"contain={cont:.2f}" if cont >= 0 else ""
            neg_pass = accuracy.get("negative_test_pass", None)
            neg_str = "NEG_PASS" if neg_pass else ""
            metrics_parts = [s for s in [tc_str, cont_str, neg_str] if s]
            metrics_str = " | ".join(metrics_parts)

            print(
                f"  [{call_num}/{total_calls}] {q.qid} | {model:15s} | "
                f"{avg_latency:6d}ms | {summary['avg_words']:5d}w | {metrics_str}",
                flush=True,
            )

    # ── Build comparison summary ──
    comparison: Dict[str, Dict[str, Any]] = {}
    for model in models:
        model_data = results[model]
        all_latencies = [v["avg_latency_ms"] for v in model_data.values() if v["avg_latency_ms"] > 0]
        all_words = [v["avg_words"] for v in model_data.values()]
        all_chars = [v["avg_chars"] for v in model_data.values()]
        theme_coverages = [
            v["theme_coverage"]["coverage"]
            for v in model_data.values()
            if v["theme_coverage"].get("coverage") is not None
        ]
        containments = [
            v["accuracy"]["containment"]
            for v in model_data.values()
            if "containment" in v.get("accuracy", {})
        ]
        neg_passes = [
            v["accuracy"].get("negative_test_pass", False)
            for v in model_data.values()
            if v["accuracy"].get("is_negative")
        ]

        comparison[model] = {
            "avg_latency_ms": int(sum(all_latencies) / len(all_latencies)) if all_latencies else 0,
            "p50_latency_ms": sorted(all_latencies)[len(all_latencies) // 2] if all_latencies else 0,
            "avg_words": int(sum(all_words) / len(all_words)) if all_words else 0,
            "avg_chars": int(sum(all_chars) / len(all_chars)) if all_chars else 0,
            "avg_theme_coverage": round(sum(theme_coverages) / len(theme_coverages), 3) if theme_coverages else 0,
            "avg_containment": round(sum(containments) / len(containments), 3) if containments else 0,
            "negative_pass_rate": round(sum(neg_passes) / len(neg_passes), 3) if neg_passes else None,
            "questions_tested": len(model_data),
        }

    # ── Save JSON ──
    output = {
        "meta": {
            "created_utc": stamp,
            "models": models,
            "questions": len(questions),
            "repeats": args.repeats,
            "url": base_url,
            "group_id": group_id,
        },
        "comparison_summary": comparison,
        "results": results,
    }
    out_json.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{out_json}")

    # ── Save Markdown ──
    lines: List[str] = []
    lines.append(f"# Synthesis Model Comparison ({stamp})\n\n")
    lines.append(f"- **Models tested:** {', '.join(models)}\n")
    lines.append(f"- **Questions:** {len(questions)} ({args.questions_only})\n")
    lines.append(f"- **Repeats:** {args.repeats}\n")
    lines.append(f"- **Group ID:** {group_id}\n\n")

    # Summary table
    lines.append("## Summary\n\n")
    lines.append("| Model | Avg Latency | P50 Latency | Avg Words | Avg Chars | Theme Coverage | Containment | Neg Pass |\n")
    lines.append("|-------|------------|------------|-----------|-----------|---------------|-------------|----------|\n")
    for model in models:
        c = comparison[model]
        neg_str = f"{c['negative_pass_rate']:.0%}" if c['negative_pass_rate'] is not None else "N/A"
        lines.append(
            f"| {model} | {c['avg_latency_ms']}ms | {c['p50_latency_ms']}ms | "
            f"{c['avg_words']} | {c['avg_chars']} | "
            f"{c['avg_theme_coverage']:.1%} | {c['avg_containment']:.2f} | {neg_str} |\n"
        )

    # Per-question comparison table
    lines.append("\n## Per-Question Comparison\n\n")
    lines.append("| QID | " + " | ".join(f"{m} (ms / words / theme)" for m in models) + " |\n")
    lines.append("|-----|" + "|".join(["---" for _ in models]) + "|\n")
    for q in questions:
        cells = []
        for model in models:
            d = results[model].get(q.qid, {})
            lat = d.get("avg_latency_ms", 0)
            words = d.get("avg_words", 0)
            tc = d.get("theme_coverage", {}).get("coverage", -1)
            tc_str = f"{tc:.0%}" if tc >= 0 else "—"
            cells.append(f"{lat}ms / {words}w / {tc_str}")
        lines.append(f"| {q.qid} | " + " | ".join(cells) + " |\n")

    # Missing terms detail
    lines.append("\n## Theme Coverage Details (Missing Terms)\n\n")
    for model in models:
        lines.append(f"### {model}\n\n")
        any_missing = False
        for q in questions:
            d = results[model].get(q.qid, {})
            missing = d.get("theme_coverage", {}).get("missing", [])
            if missing:
                any_missing = True
                lines.append(f"- **{q.qid}**: missing {missing}\n")
        if not any_missing:
            lines.append("- All terms matched ✓\n")
        lines.append("\n")

    out_md.write_text("".join(lines), encoding="utf-8")
    print(out_md)

    # ── Print summary to console ──
    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY")
    print("=" * 60)
    print(f"{'Model':20s} {'Latency':>10s} {'Words':>8s} {'Theme':>8s} {'Contain':>10s}")
    print("-" * 60)
    for model in models:
        c = comparison[model]
        print(
            f"{model:20s} {c['avg_latency_ms']:>8d}ms {c['avg_words']:>7d} "
            f"{c['avg_theme_coverage']:>7.1%} {c['avg_containment']:>9.2f}"
        )
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
