#!/usr/bin/env python3

"""Analyze repeatability benchmark JSON reports.

Reads a JSON report produced by the repeatability benchmark scripts and prints
(or writes) a compact summary of the most unstable questions per route.

This is dependency-free (stdlib only).

Usage
  python3 scripts/analyze_repeatability_report.py \
    --input benchmarks/route3_graph_vs_route4_drift_repeat_qbank_20260101T073137Z.json \
    --top 5

Optional
  --output benchmarks/analysis_route3_route4_20260101.md
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _snip(text: str, n: int = 240) -> str:
    t = (text or "").strip().replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    if len(t) <= n:
        return t
    return t[: n - 3] + "..."


def _similarity(a: str, b: str) -> float:
    return float(difflib.SequenceMatcher(None, a or "", b or "").ratio())


def _best_diff(a: str, b: str, *, context: int = 2) -> str:
    a_lines = (a or "").splitlines() or [a or ""]
    b_lines = (b or "").splitlines() or [b or ""]
    diff = difflib.unified_diff(a_lines, b_lines, fromfile="first", tofile="other", lineterm="", n=context)
    out = "\n".join(diff)
    return out if out.strip() else "(no textual diff)"


def _route_key(row: Dict[str, Any]) -> str:
    r = row.get("route")
    if isinstance(r, str) and r:
        return r
    # fallback for other report shapes
    for k in ("search_type", "mode"):
        v = row.get(k)
        if isinstance(v, str) and v:
            return v
    return "unknown"


def _summ_key(s: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(s.get(key) or default)
    except Exception:
        return float(default)


def _int_key(s: Dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(s.get(key) or default)
    except Exception:
        return int(default)


def analyze(report: Dict[str, Any], *, top_n: int) -> str:
    results: List[Dict[str, Any]] = list(report.get("results") or [])

    by_route: Dict[str, List[Dict[str, Any]]] = {}
    for row in results:
        by_route.setdefault(_route_key(row), []).append(row)

    md: List[str] = []
    md.append("# Repeatability Report Analysis")
    md.append("")
    md.append(f"- generated_at_utc: {report.get('generated_at_utc')}")
    md.append(f"- base_url: {report.get('base_url')}")
    md.append(f"- group_id: {report.get('group_id')}")
    md.append(f"- suite: {report.get('suite')}")
    md.append(f"- repeats: {report.get('repeats')}")
    md.append("")

    for route, rows in sorted(by_route.items(), key=lambda x: x[0]):
        md.append(f"## Route: {route}")
        md.append("")

        scored: List[Tuple[float, float, str, Dict[str, Any]]] = []
        for r in rows:
            s = r.get("summary") or {}
            exact = _summ_key(s, "answer_norm_exact_rate", 0.0)
            min_sim = _summ_key(s, "answer_norm_min_similarity", 0.0)
            qid = str(r.get("qid") or "")
            scored.append((exact, min_sim, qid, r))

        # Lowest exact, then lowest min_sim
        scored.sort(key=lambda t: (t[0], t[1], t[2]))
        worst = scored[: max(1, int(top_n))]

        md.append("### Most unstable questions")
        md.append("")
        md.append("| QID | exact rate | min similarity | unique norm answers | avg sources | min src jacc |")
        md.append("|---|---:|---:|---:|---:|---:|")
        for exact, min_sim, qid, r in worst:
            s = r.get("summary") or {}
            md.append(
                "| "
                + qid
                + " | "
                + f"{exact:.2f}"
                + " | "
                + f"{min_sim:.2f}"
                + " | "
                + str(_int_key(s, "answer_norm_unique", 0))
                + " | "
                + f"{_summ_key(s, 'sources_count_avg', 0.0):.1f}"
                + " | "
                + f"{_summ_key(s, 'sources_min_jaccard_vs_first', 0.0):.2f}"
                + " |"
            )
        md.append("")

        md.append("### Example diffs")
        md.append("")
        for exact, min_sim, qid, r in worst:
            runs = list(r.get("runs") or [])
            if not runs:
                continue
            first = runs[0]
            base_answer = str(first.get("answer") or "")
            base_norm = str(first.get("answer_norm") or "")
            base_sources = list(first.get("sources_ids") or [])

            # Find run with lowest similarity vs first (on normalized answer)
            worst_i = 0
            worst_sim = 1.0
            for i, run in enumerate(runs):
                sim = _similarity(base_norm, str(run.get("answer_norm") or ""))
                if sim < worst_sim:
                    worst_sim = sim
                    worst_i = i

            other = runs[worst_i]
            other_answer = str(other.get("answer") or "")
            other_sources = list(other.get("sources_ids") or [])

            md.append(f"#### {qid}")
            md.append("")
            md.append(f"- Query: {_snip(str(r.get('query') or ''), 300)}")
            md.append(f"- Worst run index: {worst_i} (similarity vs first: {worst_sim:.2f})")
            md.append(f"- First sources: {len(base_sources)} | Other sources: {len(other_sources)}")
            if base_sources or other_sources:
                md.append(f"- First source IDs (sample): {', '.join(base_sources[:5])}")
                md.append(f"- Other source IDs (sample): {', '.join(other_sources[:5])}")
            md.append("")
            md.append("First answer (snip):")
            md.append("")
            md.append("```")
            md.append(_snip(base_answer, 600))
            md.append("```")
            md.append("")
            md.append("Most divergent answer (snip):")
            md.append("")
            md.append("```")
            md.append(_snip(other_answer, 600))
            md.append("```")
            md.append("")
            md.append("Unified diff (context):")
            md.append("")
            md.append("```diff")
            md.append(_best_diff(base_answer, other_answer, context=2))
            md.append("```")
            md.append("")

    return "\n".join(md) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to repeatability JSON report")
    ap.add_argument("--top", type=int, default=5, help="How many unstable questions per route to show")
    ap.add_argument("--output", default="", help="Optional path to write markdown analysis")
    args = ap.parse_args()

    path = Path(args.input).expanduser().resolve()
    report = json.loads(path.read_text(encoding="utf-8"))

    md = analyze(report, top_n=max(1, int(args.top)))

    if args.output:
        out = Path(args.output).expanduser().resolve()
        out.write_text(md, encoding="utf-8")
        print(str(out))
    else:
        print(md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
