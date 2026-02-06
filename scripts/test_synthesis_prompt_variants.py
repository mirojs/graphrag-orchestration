#!/usr/bin/env python3
"""
A/B test synthesis prompt variants for Route 4 output conciseness.

Calls the live API with different `prompt_variant` values.
Each call runs the FULL pipeline (retrieval + synthesis) so the evidence
is identical to production — only the synthesis prompt differs.

Usage:
  # Test all variants on Q-D3 (the worst case: 20K chars baseline)
  python3 scripts/test_synthesis_prompt_variants.py --query-id Q-D3

  # Test a subset of variants
  python3 scripts/test_synthesis_prompt_variants.py --query-id Q-D3 --variants v0,v1_concise

  # Test all queries across all variants (full matrix)
  python3 scripts/test_synthesis_prompt_variants.py --all-queries

  # Custom query
  python3 scripts/test_synthesis_prompt_variants.py --query "Compare time windows across all documents"
"""

import argparse
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Any, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

VARIANTS = ["v0", "v1_concise", "v2_adaptive", "v3_budget"]

# ---------------------------------------------------------------------------
# Question bank (matching bench_route4_* questions)
# ---------------------------------------------------------------------------
TEST_QUERIES = {
    "Q-D3": 'Compare "time windows" across the set: list all explicit day-based timeframes.',
    "Q-D5": 'In the warranty, explain how the "coverage start" is defined and what must happen before coverage ends.',
    "Q-D9": 'Compare the "fees" concepts: which doc has a percentage-based fee, which has a flat fee, and which has a deposit?',
    "Q-D10": 'List the three different "risk allocation" statements and explain how each shifts liability.',
    "Q-D1": "If an emergency defect occurs under the warranty (e.g., burst pipe), what notification channel is required?",
    "Q-DR1": "Identify the vendor responsible for the vertical platform lift maintenance. Does their invoice's payment schedule match the terms in the original Purchase Agreement?",
    "Q-DR5": 'Compare the strictness of the "financial penalties" for early termination in the Property Management Agreement versus the Holding Tank Servicing Contract.',
}


def _get_aad_token() -> Optional[str]:
    """Get Azure AD access token for API authentication."""
    try:
        result = subprocess.run(
            [
                "az", "account", "get-access-token",
                "--scope", "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default",
                "--query", "accessToken",
                "-o", "tsv",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Failed to get AAD token: {e}")
        return None


def _get_group_id() -> str:
    """Read group_id from last_test_group_id.txt or env."""
    try:
        gid_file = Path(__file__).resolve().parents[1] / "last_test_group_id.txt"
        return gid_file.read_text().strip()
    except Exception:
        return os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")


def call_api(
    url: str,
    query: str,
    group_id: str,
    prompt_variant: Optional[str] = None,
    response_type: str = "summary",
    synthesis_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Call the hybrid query API with a specific prompt variant and/or model."""
    body: Dict[str, Any] = {
        "query": query,
        "force_route": "drift_multi_hop",
        "response_type": response_type,
    }
    if prompt_variant is not None:
        body["prompt_variant"] = prompt_variant
    if synthesis_model is not None:
        body["synthesis_model"] = synthesis_model

    payload = json.dumps(body).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": group_id,
    }
    token = _get_aad_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{url}/hybrid/query",
        data=payload,
        headers=headers,
        method="POST",
    )

    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode())
    elapsed = time.time() - t0
    data["_latency"] = elapsed
    data["_variant"] = prompt_variant or "v0"
    return data


def run_variant_test(
    url: str,
    query: str,
    query_id: str,
    group_id: str,
    variants: List[str],
    response_type: str = "summary",
    synthesis_model: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Test a single query across all variants. Returns {variant: result_dict}."""
    results = {}

    for variant in variants:
        label = variant
        if synthesis_model:
            label = f"{variant}@{synthesis_model}"
        print(f"\n  [{label}] Calling API...")
        try:
            data = call_api(url, query, group_id, prompt_variant=variant, response_type=response_type, synthesis_model=synthesis_model)
            resp_text = data.get("response", "")
            latency = data["_latency"]
            citations = data.get("citations", [])
            meta = data.get("metadata", {})
            sub_qs = meta.get("sub_questions", [])

            results[variant] = {
                "response": resp_text,
                "length": len(resp_text),
                "latency": latency,
                "citations": len(citations),
                "sub_questions": len(sub_qs),
            }
            print(f"         length={len(resp_text)} chars, latency={latency:.1f}s, citations={len(citations)}")
            print(f"         preview: {resp_text[:120]}...")
        except Exception as e:
            print(f"         ERROR: {e}")
            results[variant] = {"error": str(e), "length": 0, "latency": 0, "citations": 0}

        # Avoid rate-limiting
        time.sleep(2)

    return results


def print_comparison(query_id: str, query: str, results: Dict[str, Dict[str, Any]]):
    """Print a comparison table for one query across variants."""
    baseline_len = results.get("v0", {}).get("length", 1) or 1

    print(f"\n{'─' * 90}")
    print(f"  {query_id}: {query[:70]}...")
    print(f"{'─' * 90}")
    print(f"  {'Variant':<15} │ {'Chars':>7} │ {'vs v0':>7} │ {'Latency':>8} │ {'Cites':>5} │ Preview")
    print(f"  {'─' * 15}─┼─{'─' * 7}─┼─{'─' * 7}─┼─{'─' * 8}─┼─{'─' * 5}─┼─{'─' * 30}")

    for variant in VARIANTS:
        r = results.get(variant, {})
        if "error" in r:
            print(f"  {variant:<15} │ {'ERR':>7} │ {'ERR':>7} │ {'ERR':>8} │ {'ERR':>5} │ {r['error'][:30]}")
        elif variant in results:
            pct = r["length"] / baseline_len * 100
            pct_str = f"{pct:.0f}%" if variant != "v0" else "  base"
            print(
                f"  {variant:<15} │ {r['length']:>7} │ {pct_str:>7} │ "
                f"{r['latency']:>7.1f}s │ {r['citations']:>5} │ "
                f"{r.get('response', '')[:30]}..."
            )


def main():
    parser = argparse.ArgumentParser(description="A/B test Route 4 synthesis prompt variants")
    parser.add_argument("--url", default=DEFAULT_URL, help="API base URL")
    parser.add_argument("--group-id", default=None, help="Group ID override")
    parser.add_argument("--query", default=None, help="Custom query text")
    parser.add_argument("--query-id", default="Q-D3", help="Question bank ID (default: Q-D3)")
    parser.add_argument("--all-queries", action="store_true", help="Test ALL question bank queries")
    parser.add_argument("--variants", default="all", help="Comma-separated variant names or 'all'")
    parser.add_argument("--response-type", default="summary", help="Response type (default: summary)")
    parser.add_argument("--synthesis-model", default=None, help="Override synthesis model (e.g. 'gpt-4.1'). Tests this model vs default.")
    args = parser.parse_args()

    group_id = args.group_id or _get_group_id()
    variants = VARIANTS if args.variants == "all" else [v.strip() for v in args.variants.split(",")]

    if args.all_queries:
        queries = TEST_QUERIES
    elif args.query:
        queries = {"custom": args.query}
    else:
        queries = {args.query_id: TEST_QUERIES.get(args.query_id, args.query_id)}

    print("=" * 90)
    print("  ROUTE 4 SYNTHESIS PROMPT VARIANT A/B TEST")
    print("=" * 90)
    print(f"  API:       {args.url}")
    print(f"  Group:     {group_id}")
    print(f"  Variants:  {', '.join(variants)}")
    print(f"  Queries:   {len(queries)}")
    print(f"  Resp type: {args.response_type}")
    if args.synthesis_model:
        print(f"  Model:     {args.synthesis_model} (override)")
    print()

    all_results = {}
    for qid, query in queries.items():
        print(f"\n{'━' * 90}")
        print(f"  Testing {qid}: {query[:70]}...")
        print(f"{'━' * 90}")

        results = run_variant_test(
            args.url, query, qid, group_id, variants, response_type=args.response_type,
            synthesis_model=args.synthesis_model,
        )
        all_results[qid] = {"query": query, "results": results}
        print_comparison(qid, query, results)

    # ---- Final summary across all queries ----
    if len(queries) > 1:
        print(f"\n\n{'━' * 90}")
        print("  AGGREGATE SUMMARY (avg across all queries)")
        print(f"{'━' * 90}")
        for variant in variants:
            lengths = [
                all_results[qid]["results"].get(variant, {}).get("length", 0)
                for qid in all_results
                if "error" not in all_results[qid]["results"].get(variant, {})
            ]
            latencies = [
                all_results[qid]["results"].get(variant, {}).get("latency", 0)
                for qid in all_results
                if "error" not in all_results[qid]["results"].get(variant, {})
            ]
            if lengths:
                avg_len = sum(lengths) / len(lengths)
                avg_lat = sum(latencies) / len(latencies)
                print(f"  {variant:<15}: avg {avg_len:.0f} chars, avg {avg_lat:.1f}s  (n={len(lengths)})")

    # ---- Save full results ----
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = f"bench_prompt_variants_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "timestamp": ts,
            "api_url": args.url,
            "group_id": group_id,
            "response_type": args.response_type,
            "variants_tested": variants,
            "results": {
                qid: {
                    "query": data["query"],
                    "variants": {
                        variant: {
                            "length": r.get("length", 0),
                            "latency": r.get("latency", 0),
                            "citations": r.get("citations", 0),
                            "response": r.get("response", ""),
                            "error": r.get("error"),
                        }
                        for variant, r in data["results"].items()
                    },
                }
                for qid, data in all_results.items()
            },
        }, f, indent=2)
    print(f"\n  Full results saved to: {out_path}")


if __name__ == "__main__":
    main()
