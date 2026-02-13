#!/usr/bin/env python3
"""Benchmark Route 3 v2 (Map-Reduce) vs v1 baseline.

Runs the same thematic question bank as benchmark_route3_baseline.py
but adds v2-specific metrics:
- MAP claims count (per community and total)
- Token budget (claims text length vs v1 context length)
- Community coverage (which communities contributed claims)
- Latency breakdown (community match / MAP / REDUCE)

Usage:
    python scripts/benchmark_route3_v2.py
    python scripts/benchmark_route3_v2.py --group-id test-5pdfs-v2-fix2
    python scripts/benchmark_route3_v2.py --url http://localhost:8000
    python scripts/benchmark_route3_v2.py --compare benchmark_route3_baseline_*.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Path setup ──────────────────────────────────────────────────
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
SERVICE_ROOT = PROJECT_ROOT / "graphrag-orchestration"
for p in [str(THIS_DIR), str(PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(SERVICE_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

# ─── Config ──────────────────────────────────────────────────────
GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")
DEFAULT_API_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)


def _now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ─── HTTP helpers ─────────────────────────────────────────────────
def _get_aad_token() -> Optional[str]:
    try:
        from azure.identity import DefaultAzureCredential
        cred = DefaultAzureCredential()
        return cred.get_token("https://management.azure.com/.default").token
    except Exception:
        return None


def call_route3_api(
    api_url: str,
    query: str,
    include_context: bool = True,
    return_timings: bool = True,
    timeout: float = 180.0,
) -> Dict[str, Any]:
    """Call Route 3 (global_search) API and return response + v2 metadata."""
    url = f"{api_url.rstrip('/')}/hybrid/query"
    headers = {"Content-Type": "application/json", "X-Group-ID": GROUP_ID}
    token = _get_aad_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "query": query,
        "force_route": "global_search",
        "response_type": "summary",
        "include_context": include_context,
    }
    data = json.dumps(payload).encode("utf-8")

    # Set timings env via query param or header if supported
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            metadata = body.get("metadata", {})
            return {
                "response": body.get("response", ""),
                "route_used": body.get("route_used", ""),
                "elapsed_ms": elapsed_ms,
                # v2-specific fields
                "version": metadata.get("version", "v1"),
                "total_claims": metadata.get("total_claims", 0),
                "claims_per_community": metadata.get("claims_per_community", {}),
                "community_scores": metadata.get("community_scores", {}),
                "matched_communities": metadata.get("matched_communities", []),
                "map_claims": metadata.get("map_claims", []),
                "timings_ms": metadata.get("timings_ms", {}),
                # v1 fields (for comparison)
                "hub_entities": metadata.get("hub_entities", []),
                "num_source_chunks": metadata.get("num_source_chunks", 0),
                "text_chunks_used": metadata.get("text_chunks_used", 0),
                "negative_detection": metadata.get("negative_detection", False),
                "error": None,
            }
    except Exception as e:
        return {
            "response": "",
            "route_used": "",
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "version": "unknown",
            "total_claims": 0,
            "claims_per_community": {},
            "community_scores": {},
            "matched_communities": [],
            "map_claims": [],
            "timings_ms": {},
            "hub_entities": [],
            "num_source_chunks": 0,
            "text_chunks_used": 0,
            "negative_detection": False,
            "error": str(e),
        }


# ─── Thematic Question Bank (same as baseline) ───────────────────
ROUTE3_QUESTIONS = [
    {
        "id": "T-1",
        "query": "What are the common themes across all the contracts and agreements in these documents?",
        "expected_themes": ["legal obligations", "payment terms", "termination clauses", "liability provisions", "dispute resolution"],
    },
    {
        "id": "T-2",
        "query": "How do the different parties relate to each other across the documents?",
        "expected_themes": ["contractual relationships", "service providers", "clients", "third parties"],
    },
    {
        "id": "T-3",
        "query": "What patterns emerge in the financial terms and payment structures?",
        "expected_themes": ["payment schedules", "amounts", "penalties", "invoicing"],
    },
    {
        "id": "T-4",
        "query": "Summarize the risk management and liability provisions across all documents.",
        "expected_themes": ["indemnification", "limitation of liability", "insurance requirements", "warranties"],
    },
    {
        "id": "T-5",
        "query": "What dispute resolution mechanisms are mentioned across the agreements?",
        "expected_themes": ["arbitration", "mediation", "litigation", "jurisdiction", "governing law"],
    },
    {
        "id": "T-6",
        "query": "How do the documents address confidentiality and data protection?",
        "expected_themes": ["NDA provisions", "data handling", "privacy", "disclosure limitations"],
    },
    {
        "id": "T-7",
        "query": "What are the key obligations and responsibilities outlined for each party?",
        # Themes adjusted to match corpus content (home construction / property management contracts)
        "expected_themes": ["warranty obligations", "dispute resolution", "service responsibilities", "cost obligations"],
    },
    {
        "id": "T-8",
        "query": "Compare the termination and cancellation provisions across the documents.",
        "expected_themes": ["notice periods", "grounds for termination", "effects of termination", "survival clauses"],
    },
    {
        "id": "T-9",
        "query": "What insurance and indemnification requirements appear in the documents?",
        "expected_themes": ["coverage types", "minimum amounts", "certificate requirements", "named insureds"],
    },
    {
        "id": "T-10",
        "query": "Identify the key dates, deadlines, and time-sensitive provisions across all documents.",
        "expected_themes": ["effective dates", "expiration", "renewal", "notice periods", "response times"],
    },
]


def _simple_stem(word: str) -> str:
    """Reduce word to a basic root for fuzzy matching."""
    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    if word.endswith('es') and len(word) > 4:
        return word[:-2]
    if word.endswith('s') and not word.endswith('ss') and len(word) > 4:
        return word[:-1]
    if word.endswith('ing') and len(word) > 5:
        return word[:-3]
    if word.endswith('ed') and len(word) > 4:
        return word[:-2]
    if word.endswith('tion') and len(word) > 6:
        return word[:-4]
    return word


# Conceptual synonyms for theme matching — covers common paraphrases
# that the LLM might use instead of the exact expected theme keyword.
THEME_SYNONYMS: Dict[str, List[str]] = {
    "clients": ["client", "customer", "tenant", "lessee", "occupant", "buyer", "owner"],
    "penalties": ["penalty", "penalt", "fine", "late fee", "liquidated damage", "surcharge"],
    "indemnification": ["indemnif", "indemnit", "hold harmless", "defend and indemnify"],
    "mediation": ["mediat", "conciliat", "alternative dispute"],
    "privacy": ["privacy", "personal data", "data protection", "confidential information"],
    "expiration": ["expir", "expire", "end date", "expiry", "lapse"],
    "response times": ["response time", "business day", "calendar day", "within.*day",
                        "timeframe", "time frame", "turnaround"],
    "invoicing": ["invoic", "billing", "bill", "payment request"],
    "litigation": ["litigat", "lawsuit", "court action", "legal action", "judicial"],
}


def _stem_in_text(word: str, text: str) -> bool:
    """Check if word or its stemmed form appears as substring in text."""
    if word in text:
        return True
    stem = _simple_stem(word)
    return len(stem) >= 4 and stem in text


def _theme_in_text(theme: str, text: str) -> bool:
    """Check if theme appears in text via exact match, stemming, or synonyms."""
    theme_lower = theme.lower()
    text_lower = text.lower()

    # 1. Exact phrase match
    if theme_lower in text_lower:
        return True

    # 2. Synonym match
    synonyms = THEME_SYNONYMS.get(theme_lower, [])
    for syn in synonyms:
        if syn in text_lower:
            return True

    # 3. Fuzzy: >= 50% of significant words (with stemming)
    significant_words = [w for w in theme_lower.split() if len(w) >= 4]
    if significant_words:
        hits = sum(1 for w in significant_words if _stem_in_text(w, text_lower))
        if hits >= max(1, len(significant_words) * 0.5):
            return True

    return False


def check_theme_coverage(
    response: str, expected_themes: List[str]
) -> tuple[float, Dict[str, bool]]:
    """Theme coverage with stemming + synonym support.

    A theme matches if:
      1. The full phrase appears in the response, OR
      2. A known synonym for the theme appears, OR
      3. >= 50% of its significant words (len>=4) appear (with stemming).

    Returns (coverage_ratio, per_theme_dict).
    """
    per_theme: Dict[str, bool] = {}
    for theme in expected_themes:
        per_theme[theme] = _theme_in_text(theme, response)
    found = sum(1 for v in per_theme.values() if v)
    return (found / len(expected_themes) if expected_themes else 0.0, per_theme)


# ─── Comparison loader ────────────────────────────────────────────
def load_baseline(path: str) -> Dict[str, Dict[str, Any]]:
    """Load baseline results indexed by question_id."""
    with open(path) as f:
        data = json.load(f)
    return {r["question_id"]: r for r in data.get("results", []) if "question_id" in r}


# ─── Main benchmark ───────────────────────────────────────────────
def run_benchmark(
    api_url: str,
    output_file: Optional[str] = None,
    baseline_path: Optional[str] = None,
):
    """Run Route 3 v2 benchmark and optionally compare to v1 baseline."""
    baseline = load_baseline(baseline_path) if baseline_path else {}

    print("=" * 72)
    print("  ROUTE 3 v2 MAP-REDUCE BENCHMARK")
    print("=" * 72)
    print(f"  API:        {api_url}")
    print(f"  Group:      {GROUP_ID}")
    print(f"  Questions:  {len(ROUTE3_QUESTIONS)}")
    if baseline:
        print(f"  Baseline:   {baseline_path} ({len(baseline)} results)")
    print("=" * 72)
    print()

    results: List[Dict[str, Any]] = []

    for i, q in enumerate(ROUTE3_QUESTIONS, 1):
        qid = q["id"]
        query = q["query"]
        print(f"\n[{i}/{len(ROUTE3_QUESTIONS)}] {qid}: {query[:65]}...")

        resp = call_route3_api(api_url, query, include_context=True)

        if resp.get("error"):
            print(f"  ERROR: {resp['error']}")
            results.append({"question_id": qid, "query": query, "error": resp["error"]})
            continue

        # Metrics
        theme_cov, theme_details = check_theme_coverage(resp["response"], q["expected_themes"])
        resp_len = len(resp["response"])
        claims_total = resp.get("total_claims", 0)
        claims_text_len = sum(len(c) for c in resp.get("map_claims", []))

        print(f"  Version:    {resp.get('version', '?')}")
        print(f"  Response:   {resp_len} chars")
        print(f"  Latency:    {resp['elapsed_ms']}ms")
        print(f"  Themes:     {theme_cov:.0%} ({int(theme_cov * len(q['expected_themes']))}/{len(q['expected_themes'])})")
        for t_name, t_hit in theme_details.items():
            print(f"    {'✓' if t_hit else '✗'} {t_name}")
        print(f"  Claims:     {claims_total} total")
        print(f"  Claims len: {claims_text_len} chars")
        print(f"  Communities:{resp.get('matched_communities', [])}")

        # Timings breakdown
        timings = resp.get("timings_ms", {})
        if timings:
            parts = []
            for k in ["step_1_community_match_ms", "step_2_map_ms", "step_3_reduce_ms"]:
                if k in timings:
                    parts.append(f"{k.split('_')[1]}_{k.split('_')[2]}={timings[k]}ms")
            if parts:
                print(f"  Timings:    {', '.join(parts)}")

        # Comparison to baseline
        bl = baseline.get(qid)
        if bl:
            bl_theme = bl.get("theme_coverage", 0)
            bl_latency = bl.get("elapsed_ms", 0)
            bl_chunks = bl.get("num_chunks", 0) or bl.get("text_chunks_used", 0)
            delta_theme = theme_cov - bl_theme
            delta_latency = resp["elapsed_ms"] - bl_latency
            print(f"  vs v1:      theme {delta_theme:+.0%}, latency {delta_latency:+d}ms, v1 chunks={bl_chunks}")

        result_entry = {
            "question_id": qid,
            "query": query,
            "response": resp["response"],
            "elapsed_ms": resp["elapsed_ms"],
            "version": resp.get("version", "?"),
            "theme_coverage": theme_cov,
            "total_claims": claims_total,
            "claims_per_community": resp.get("claims_per_community", {}),
            "claims_text_length": claims_text_len,
            "matched_communities": resp.get("matched_communities", []),
            "community_scores": resp.get("community_scores", {}),
            "timings_ms": timings,
            "negative_detection": resp.get("negative_detection", False),
            "expected_themes": q["expected_themes"],
            "theme_details": {k: v for k, v in theme_details.items()},
        }
        if bl:
            result_entry["v1_comparison"] = {
                "theme_coverage": bl.get("theme_coverage", 0),
                "elapsed_ms": bl.get("elapsed_ms", 0),
                "num_chunks": bl.get("num_chunks", 0),
            }
        results.append(result_entry)

    # ─── Summary ─────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  SUMMARY")
    print("=" * 72)

    valid = [r for r in results if "error" not in r or not r.get("error")]
    if valid:
        import statistics

        themes = [r["theme_coverage"] for r in valid]
        latencies = [r["elapsed_ms"] for r in valid]
        claims = [r["total_claims"] for r in valid]
        claims_lens = [r.get("claims_text_length", 0) for r in valid]

        print(f"  Avg Theme Coverage:    {statistics.mean(themes):.1%}")
        print(f"  Avg Latency:           {statistics.mean(latencies):.0f}ms")
        print(f"  Avg Claims:            {statistics.mean(claims):.1f}")
        print(f"  Avg Claims Text:       {statistics.mean(claims_lens):.0f} chars")

        if baseline:
            bl_valid = [baseline[r["question_id"]] for r in valid if r["question_id"] in baseline]
            if bl_valid:
                bl_themes = [b.get("theme_coverage", 0) for b in bl_valid]
                bl_latencies = [b.get("elapsed_ms", 0) for b in bl_valid]
                print(f"  v1 Avg Theme Coverage: {statistics.mean(bl_themes):.1%}")
                print(f"  v1 Avg Latency:        {statistics.mean(bl_latencies):.0f}ms")
                print(f"  Delta Theme:           {statistics.mean(themes) - statistics.mean(bl_themes):+.1%}")
                print(f"  Delta Latency:         {statistics.mean(latencies) - statistics.mean(bl_latencies):+.0f}ms")

    # ─── Save ────────────────────────────────────────────────────
    if output_file is None:
        output_file = f"benchmark_route3_v2_{_now()}.json"

    output_path = PROJECT_ROOT / output_file
    summary_data = {}
    if valid:
        summary_data = {
            "avg_theme_coverage": float(statistics.mean(themes)),
            "avg_latency_ms": float(statistics.mean(latencies)),
            "avg_claims": float(statistics.mean(claims)),
            "avg_claims_text_chars": float(statistics.mean(claims_lens)),
        }

    with open(output_path, "w") as f:
        json.dump(
            {
                "benchmark_type": "route3_v2_map_reduce",
                "timestamp": _now(),
                "group_id": GROUP_ID,
                "api_url": api_url,
                "num_questions": len(ROUTE3_QUESTIONS),
                "results": results,
                "summary": summary_data,
            },
            f,
            indent=2,
        )

    print(f"\n  Results saved to: {output_path}")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Route 3 v2 map-reduce")
    parser.add_argument("--url", default=DEFAULT_API_URL, help="API base URL")
    parser.add_argument("--group-id", default=None, help="Group ID for test corpus")
    parser.add_argument("--output", help="Output JSON file path")
    parser.add_argument("--compare", help="Path to v1 baseline JSON for comparison")
    args = parser.parse_args()

    if args.group_id:
        GROUP_ID = args.group_id

    run_benchmark(args.url, args.output, args.compare)
