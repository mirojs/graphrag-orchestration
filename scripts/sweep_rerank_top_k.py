#!/usr/bin/env python3
"""RERANK_TOP_K sweep — runs benchmark for each value and produces a comparison table.

Usage:
    python3 scripts/sweep_rerank_top_k.py [--url URL] [--repeats 2] [--values 5,10,15,20,25,30]

Requires the API to support config_overrides (per-request override for
ROUTE7_RERANK_TOP_K via the 'rerank_top_k' key).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_SCRIPT = SCRIPT_DIR / "benchmark_route7_hipporag2.py"
OUT_DIR = SCRIPT_DIR.parent / "benchmarks"

DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)


def run_benchmark(
    url: str,
    rerank_top_k: int,
    repeats: int,
    group_id: str | None,
    no_auth: bool,
    extra_args: list[str],
) -> Path | None:
    """Run the benchmark script for a given RERANK_TOP_K and return the JSON output path."""
    cmd = [
        sys.executable,
        str(BENCHMARK_SCRIPT),
        "--url", url,
        "--repeats", str(repeats),
        "--include-context",
        "--config-override", f"rerank_top_k={rerank_top_k}",
    ]
    if group_id:
        cmd += ["--group-id", group_id]
    if no_auth:
        cmd.append("--no-auth")
    cmd.extend(extra_args)

    print(f"\n{'=' * 70}")
    print(f"  SWEEP: rerank_top_k = {rerank_top_k}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'=' * 70}\n")

    result = subprocess.run(cmd, cwd=SCRIPT_DIR.parent)
    if result.returncode != 0:
        print(f"  ❌ Benchmark failed for rerank_top_k={rerank_top_k}")
        return None

    # Find the most recently created JSON file
    jsons = sorted(OUT_DIR.glob("route7_hipporag2_r4questions_*.json"), key=lambda p: p.stat().st_mtime)
    return jsons[-1] if jsons else None


def extract_per_question_scores(json_path: Path) -> dict:
    """Extract per-question scores from a benchmark JSON file."""
    with open(json_path) as f:
        data = json.load(f)

    scenario = data.get("scenario", {})
    results = scenario.get("results", [])
    config_overrides = data.get("config_overrides", {})
    rerank_top_k = int(config_overrides.get("rerank_top_k", "?"))

    per_q: dict = {"rerank_top_k": rerank_top_k, "questions": {}}
    total_score = 0
    total_max = 0

    for r in results:
        qid = r.get("qid", "?")
        runs = r.get("runs", [])
        if not runs:
            per_q["questions"][qid] = {"score": 0, "max": 0, "answer_snippet": ""}
            continue

        # Use first run
        run = runs[0]
        gt_score = run.get("gt_score", 0)
        gt_max = run.get("gt_max", 0)
        answer = run.get("text", "")[:120]
        per_q["questions"][qid] = {
            "score": gt_score,
            "max": gt_max,
            "answer_snippet": answer,
        }
        total_score += gt_score
        total_max += gt_max

    per_q["total_score"] = total_score
    per_q["total_max"] = total_max
    return per_q


def print_comparison_table(sweep_results: list[dict]):
    """Print a markdown comparison table across all sweep values."""
    if not sweep_results:
        return

    # Collect all question IDs
    all_qids = []
    for sr in sweep_results:
        for qid in sr.get("questions", {}):
            if qid not in all_qids:
                all_qids.append(qid)

    # Sort Q-D questions first, then Q-N
    all_qids.sort(key=lambda q: (0 if q.startswith("Q-D") else 1, q))

    # Header
    values = [str(sr["rerank_top_k"]) for sr in sweep_results]
    header = "| QID | " + " | ".join(f"top_k={v}" for v in values) + " |"
    sep = "|-----|" + "|".join("-" * (len(f"top_k={v}") + 2) for v in values) + "|"

    print(f"\n{'=' * 70}")
    print("RERANK_TOP_K Sweep Results")
    print(f"{'=' * 70}\n")
    print(header)
    print(sep)

    for qid in all_qids:
        row = f"| {qid} |"
        for sr in sweep_results:
            q_data = sr.get("questions", {}).get(qid, {})
            score = q_data.get("score", "?")
            mx = q_data.get("max", "?")
            row += f" {score}/{mx} |"
        print(row)

    # Total row
    total_row = "| **TOTAL** |"
    for sr in sweep_results:
        total_row += f" **{sr['total_score']}/{sr['total_max']}** |"
    print(total_row)
    print()


def main():
    parser = argparse.ArgumentParser(description="Sweep RERANK_TOP_K values on Route 7 benchmark")
    parser.add_argument("--url", default=DEFAULT_URL, help="API base URL")
    parser.add_argument("--repeats", type=int, default=2, help="Repeats per question per sweep value")
    parser.add_argument("--values", type=str, default="5,10,15,20,25,30",
                        help="Comma-separated RERANK_TOP_K values to sweep")
    parser.add_argument("--group-id", type=str, default=None, help="Group ID")
    parser.add_argument("--no-auth", action="store_true", help="Skip auth")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds to wait between sweep iterations (rate limit safety)")
    parser.add_argument("extra_args", nargs="*", help="Extra args passed to benchmark script")

    args = parser.parse_args()
    values = [int(v.strip()) for v in args.values.split(",")]

    print(f"Sweep RERANK_TOP_K values: {values}")
    print(f"API: {args.url}")
    print(f"Repeats: {args.repeats}")

    sweep_results = []
    json_paths = []

    for val in values:
        json_path = run_benchmark(
            url=args.url,
            rerank_top_k=val,
            repeats=args.repeats,
            group_id=args.group_id,
            no_auth=args.no_auth,
            extra_args=args.extra_args,
        )
        if json_path:
            json_paths.append(json_path)
            scores = extract_per_question_scores(json_path)
            sweep_results.append(scores)
            print(f"  ✅ rerank_top_k={val}: {scores['total_score']}/{scores['total_max']}")
        else:
            print(f"  ❌ rerank_top_k={val}: FAILED")

        if val != values[-1]:
            time.sleep(args.delay)

    # Print comparison table
    print_comparison_table(sweep_results)

    # Save sweep summary
    summary_path = OUT_DIR / f"sweep_rerank_top_k_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    with open(summary_path, "w") as f:
        json.dump({
            "sweep_type": "RERANK_TOP_K",
            "values": values,
            "results": sweep_results,
            "json_files": [str(p) for p in json_paths],
        }, f, indent=2)
    print(f"Sweep summary saved: {summary_path}")


if __name__ == "__main__":
    main()
