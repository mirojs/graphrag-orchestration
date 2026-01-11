#!/usr/bin/env python3
"""
Run Cypher 25 Baseline Benchmark

This script captures baseline performance metrics before/after enabling Cypher 25:
1. Runs Route 3 benchmark (positive + negative questions)
2. Captures latency metrics (p50, p95, p99)
3. Saves results with timestamp for comparison

Usage:
    # Run baseline BEFORE enabling Cypher 25 in production
    python scripts/run_cypher25_baseline_benchmark.py --phase before
    
    # Run after enabling Cypher 25
    python scripts/run_cypher25_baseline_benchmark.py --phase after
    
    # Compare results
    python scripts/run_cypher25_baseline_benchmark.py --compare before after

Environment Variables:
    GRAPHRAG_CLOUD_URL: Endpoint URL (default: production ACA endpoint)
    TEST_GROUP_ID: Group ID for testing (default: test-5pdfs-1767429340223041632)

Outputs:
    - benchmarks/cypher25_baseline_<phase>_<timestamp>.json
    - benchmarks/cypher25_baseline_<phase>_<timestamp>.md

Reference:
    - NEO4J_CYPHER25_HANDOVER_2026-01-10.md
    - Migration script: scripts/cypher25_migration.py
"""

import argparse
import datetime
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_timestamp() -> str:
    """Get UTC timestamp string."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_benchmark_output(output: str) -> Dict[str, Any]:
    """Parse benchmark output and extract key metrics."""
    metrics = {
        "total_queries": 0,
        "successful": 0,
        "failed": 0,
        "latencies_ms": [],
        "positive_pass": 0,
        "negative_pass": 0,
        "errors": []
    }
    
    # Look for JSON output in the benchmark
    try:
        # Try to find JSON data in output
        lines = output.split('\n')
        for line in lines:
            if 'duration_ms' in line.lower() or 'latency' in line.lower():
                # Extract numeric values
                import re
                numbers = re.findall(r'\d+\.?\d*', line)
                if numbers:
                    metrics["latencies_ms"].extend([float(n) for n in numbers])
    except Exception as e:
        metrics["errors"].append(f"Parse error: {e}")
    
    return metrics


def calculate_percentiles(latencies: List[float]) -> Dict[str, float]:
    """Calculate p50, p95, p99 from latency list."""
    if not latencies:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}
    
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    
    return {
        "p50": sorted_lat[int(n * 0.50)] if n > 0 else 0.0,
        "p95": sorted_lat[int(n * 0.95)] if n > 0 else 0.0,
        "p99": sorted_lat[int(n * 0.99)] if n > 0 else 0.0,
        "mean": statistics.mean(sorted_lat),
        "min": min(sorted_lat),
        "max": max(sorted_lat),
        "count": n
    }


def run_route3_benchmark(url: str, group_id: str) -> Tuple[Dict[str, Any], str]:
    """
    Run Route 3 global search benchmark.
    
    Returns:
        (metrics_dict, raw_output)
    """
    print("=" * 60)
    print("Running Route 3 Global Search Benchmark")
    print("=" * 60)
    
    script_path = Path(__file__).parent / "benchmark_route3_global_search.py"
    
    if not script_path.exists():
        print(f"❌ Benchmark script not found: {script_path}")
        return {"error": "Script not found"}, ""
    
    try:
        # Run benchmark with minimal repeats for baseline
        cmd = [
            sys.executable,
            str(script_path),
            "--url", url,
            "--group-id", group_id,
            "--repeats", "1",  # Single run for quick baseline
        ]
        
        print(f"Running: {' '.join(cmd)}")
        print()
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1200  # 20 minute timeout (increased from 10)
        )
        
        output = result.stdout + result.stderr
        print(output)
        
        if result.returncode != 0:
            print(f"⚠️ Benchmark exited with code {result.returncode}")
        
        # Parse the output
        metrics = parse_benchmark_output(output)
        
        # Try to load JSON output if it exists
        benchmark_dir = Path("benchmarks")
        if benchmark_dir.exists():
            # Find latest JSON file
            json_files = sorted(benchmark_dir.glob("route3_global_search_*.json"))
            if json_files:
                latest = json_files[-1]
                print(f"\n📊 Loading benchmark data from: {latest}")
                with open(latest, 'r') as f:
                    benchmark_data = json.load(f)
                    
                    # Extract latencies
                    latencies = []
                    for run in benchmark_data.get("runs", []):
                        for result in run.get("results", []):
                            if "duration_ms" in result:
                                latencies.append(result["duration_ms"])
                    
                    metrics["latencies_ms"] = latencies
                    metrics["total_queries"] = len(latencies)
                    metrics["benchmark_file"] = str(latest)
        
        return metrics, output
        
    except subprocess.TimeoutExpired:
        return {"error": "Benchmark timeout"}, ""
    except Exception as e:
        return {"error": str(e)}, ""


def save_baseline_results(phase: str, metrics: Dict[str, Any], raw_output: str) -> Path:
    """Save baseline results to JSON and Markdown."""
    timestamp = get_timestamp()
    benchmark_dir = Path("benchmarks")
    benchmark_dir.mkdir(exist_ok=True)
    
    # Calculate percentiles
    percentiles = calculate_percentiles(metrics.get("latencies_ms", []))
    
    # Build result document
    result = {
        "phase": phase,
        "timestamp": timestamp,
        "metrics": metrics,
        "percentiles": percentiles,
        "cypher_25_enabled": phase == "after",
    }
    
    # Save JSON
    json_path = benchmark_dir / f"cypher25_baseline_{phase}_{timestamp}.json"
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n✅ Saved JSON: {json_path}")
    
    # Save Markdown summary
    md_path = benchmark_dir / f"cypher25_baseline_{phase}_{timestamp}.md"
    with open(md_path, 'w') as f:
        f.write(f"# Cypher 25 Baseline - {phase.upper()}\n\n")
        f.write(f"**Date:** {timestamp}\n\n")
        f.write(f"**Phase:** {phase}\n\n")
        f.write(f"**Cypher 25 Enabled:** {'Yes' if phase == 'after' else 'No'}\n\n")
        f.write("## Latency Percentiles\n\n")
        f.write("| Metric | Value (ms) |\n")
        f.write("|--------|------------|\n")
        for key, value in percentiles.items():
            f.write(f"| {key.upper()} | {value:.2f} |\n")
        f.write("\n")
        f.write(f"## Total Queries\n\n")
        f.write(f"{metrics.get('total_queries', 0)}\n\n")
        
        if metrics.get("benchmark_file"):
            f.write(f"## Benchmark File\n\n")
            f.write(f"`{metrics['benchmark_file']}`\n\n")
    
    print(f"✅ Saved Markdown: {md_path}")
    
    return json_path


def compare_baselines(before_path: str, after_path: str) -> None:
    """Compare before/after baseline results."""
    print("=" * 60)
    print("Comparing Cypher 25 Baseline Results")
    print("=" * 60)
    
    try:
        with open(before_path, 'r') as f:
            before = json.load(f)
        with open(after_path, 'r') as f:
            after = json.load(f)
    except Exception as e:
        print(f"❌ Error loading results: {e}")
        return
    
    before_p = before["percentiles"]
    after_p = after["percentiles"]
    
    print("\n## Latency Comparison\n")
    print(f"{'Metric':<10} {'Before (ms)':<15} {'After (ms)':<15} {'Change':<15} {'Improvement'}")
    print("-" * 70)
    
    for metric in ["p50", "p95", "p99", "mean"]:
        b = before_p.get(metric, 0)
        a = after_p.get(metric, 0)
        diff = a - b
        pct = ((b - a) / b * 100) if b > 0 else 0
        
        improvement = "✅" if diff < 0 else "⚠️" if diff > 0 else "→"
        
        print(f"{metric.upper():<10} {b:>12.2f}    {a:>12.2f}    {diff:>+12.2f}    {pct:>+6.1f}% {improvement}")
    
    print("\n" + "=" * 60)
    
    # Interpretation
    if after_p["p95"] < before_p["p95"]:
        improvement_pct = (before_p["p95"] - after_p["p95"]) / before_p["p95"] * 100
        print(f"✅ Cypher 25 improved p95 latency by {improvement_pct:.1f}%")
    elif after_p["p95"] > before_p["p95"]:
        regression_pct = (after_p["p95"] - before_p["p95"]) / before_p["p95"] * 100
        print(f"⚠️ Cypher 25 regressed p95 latency by {regression_pct:.1f}%")
    else:
        print("→ No significant change in p95 latency")


def main():
    parser = argparse.ArgumentParser(description="Run Cypher 25 baseline benchmark")
    parser.add_argument(
        "--phase",
        choices=["before", "after"],
        help="Benchmark phase (before or after enabling Cypher 25)"
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BEFORE_JSON", "AFTER_JSON"),
        help="Compare two baseline result files"
    )
    parser.add_argument(
        "--url",
        default=os.getenv(
            "GRAPHRAG_CLOUD_URL",
            "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
        ),
        help="GraphRAG endpoint URL"
    )
    parser.add_argument(
        "--group-id",
        default=os.getenv("TEST_GROUP_ID", "test-5pdfs-1767429340223041632"),
        help="Test group ID"
    )
    
    args = parser.parse_args()
    
    if args.compare:
        compare_baselines(args.compare[0], args.compare[1])
        return
    
    if not args.phase:
        parser.error("Either --phase or --compare must be specified")
    
    print(f"🎯 Running {args.phase.upper()} baseline benchmark")
    print(f"📡 Endpoint: {args.url}")
    print(f"🆔 Group ID: {args.group_id}")
    print()
    
    # Run Route 3 benchmark
    metrics, raw_output = run_route3_benchmark(args.url, args.group_id)
    
    if "error" in metrics:
        print(f"\n❌ Benchmark failed: {metrics['error']}")
        sys.exit(1)
    
    # Save results
    result_path = save_baseline_results(args.phase, metrics, raw_output)
    
    # Print summary
    percentiles = calculate_percentiles(metrics.get("latencies_ms", []))
    print("\n" + "=" * 60)
    print("BASELINE RESULTS")
    print("=" * 60)
    print(f"Phase: {args.phase.upper()}")
    print(f"Total queries: {metrics.get('total_queries', 0)}")
    print(f"\nLatency Percentiles:")
    for metric, value in percentiles.items():
        if metric != "count":
            print(f"  {metric.upper()}: {value:.2f} ms")
    print("\n" + "=" * 60)
    
    print(f"\n✅ Baseline captured: {result_path}")
    print("\nNext steps:")
    if args.phase == "before":
        print("1. Run: python scripts/cypher25_migration.py")
        print("2. Deploy updated code with USE_CYPHER_25 = True")
        print(f"3. Run: python scripts/run_cypher25_baseline_benchmark.py --phase after")
    else:
        print("1. Find the 'before' baseline JSON file in benchmarks/")
        print(f"2. Run: python scripts/run_cypher25_baseline_benchmark.py --compare <before.json> {result_path}")


if __name__ == "__main__":
    main()
