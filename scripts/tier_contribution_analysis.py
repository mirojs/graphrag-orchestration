#!/usr/bin/env python3
"""Extract tier_contribution metadata from Route 5 for benchmark questions.

Calls the deployed Route 5 API for each question and prints a summary table
showing per-tier seed counts, weight mass, per-seed weight, and overlap.

Usage:
    python scripts/tier_contribution_analysis.py
    python scripts/tier_contribution_analysis.py --filter-qid Q-D3
    python scripts/tier_contribution_analysis.py --prefixes Q-D
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent

if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from benchmark_accuracy_utils import read_question_bank

# ---------------------------------------------------------------------------
DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)
DEFAULT_GROUP_ID = "test-5pdfs-v2-fix2"
DEFAULT_QUESTION_BANK = (
    PROJECT_ROOT / "docs" / "archive" / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
)
FORCE_ROUTE = "unified_search"


def get_aad_token() -> Optional[str]:
    manual = os.getenv("GRAPHRAG_API_TOKEN")
    if manual:
        return manual.strip()
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--scope", "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Failed to get AAD token: {e}")
        return None


def http_post(url: str, headers: Dict, payload: Dict,
              timeout_s: float = 120) -> Tuple[int, Any, float]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), json.loads(raw), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return int(getattr(e, "code", 0)), {"error": str(e), "body": body}, time.monotonic() - t0
    except Exception as e:
        return 0, {"error": str(e)}, time.monotonic() - t0


def main():
    parser = argparse.ArgumentParser(description="Tier contribution analysis")
    parser.add_argument("--api-url", default=DEFAULT_URL)
    parser.add_argument("--group-id", default=DEFAULT_GROUP_ID)
    parser.add_argument("--qbank", type=Path, default=DEFAULT_QUESTION_BANK)
    parser.add_argument("--prefixes", default="Q-D,Q-G")
    parser.add_argument("--filter-qid", default=None)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    prefixes = [p.strip() for p in args.prefixes.split(",")]
    questions = []
    for prefix in prefixes:
        qs = read_question_bank(
            args.qbank, positive_prefix=prefix, negative_prefix="Q-NONE",
        )
        questions.extend(qs)
    if args.filter_qid:
        questions = [q for q in questions if q.qid == args.filter_qid]
    if not questions:
        print("No questions loaded")
        sys.exit(1)

    print(f"Questions: {len(questions)}")
    print(f"API: {args.api_url}")
    print(f"Group: {args.group_id}")

    url = f"{args.api_url.rstrip('/')}/hybrid/query"
    headers = {"Content-Type": "application/json", "X-Group-ID": args.group_id}
    token = get_aad_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        print("Auth: Azure AD token\n")
    else:
        print("Auth: NONE\n")

    results: List[Dict[str, Any]] = []

    for q in questions:
        payload = {
            "group_id": args.group_id,
            "query": q.query,
            "force_route": FORCE_ROUTE,
            "response_type": "summary",
        }

        print(f"[{q.qid}] {q.query[:70]}...")
        status, resp, elapsed = http_post(url, headers, payload, args.timeout)

        if status != 200:
            err = resp.get("error", "") if isinstance(resp, dict) else str(resp)
            print(f"  ERROR: HTTP {status} — {err[:100]}")
            continue

        metadata = resp.get("metadata", {}) if isinstance(resp, dict) else {}
        tc = metadata.get("tier_contribution", {})
        profile = metadata.get("profile", "?")
        ner_entities = metadata.get("ner_entities", [])
        elapsed_ms = int(elapsed * 1000)

        t1 = tc.get("tier1_entity", {})
        t2 = tc.get("tier2_structural", {})
        t3 = tc.get("tier3_thematic", {})
        eff = tc.get("effective_weights", {})
        overlap = tc.get("overlap", {})

        print(f"  {elapsed_ms}ms | profile={profile} | NER={ner_entities}")
        print(f"  Tier1(NER):        count={t1.get('count','-'):>3}  mass={t1.get('weight_mass','-')}  per_seed={t1.get('per_seed_weight','-')}")
        print(f"  Tier2(Structural): count={t2.get('count','-'):>3}  mass={t2.get('weight_mass','-')}  per_seed={t2.get('per_seed_weight','-')}")
        print(f"  Tier3(Thematic):   count={t3.get('count','-'):>3}  mass={t3.get('weight_mass','-')}  per_seed={t3.get('per_seed_weight','-')}")
        print(f"  Effective w: w1={eff.get('w1','-')} w2={eff.get('w2','-')} w3={eff.get('w3','-')}")
        print(f"  Overlap: t1∩t2={overlap.get('tier1_tier2','-')} t1∩t3={overlap.get('tier1_tier3','-')} t2∩t3={overlap.get('tier2_tier3','-')} all={overlap.get('all_three','-')}")
        print()

        results.append({
            "qid": q.qid,
            "query": q.query,
            "profile": profile,
            "ner_entities": ner_entities,
            "elapsed_ms": elapsed_ms,
            "tier_contribution": tc,
        })

    if not results:
        print("No results collected")
        sys.exit(1)

    # ---------------------------------------------------------------------------
    # Summary table
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 110)
    print("TIER CONTRIBUTION SUMMARY")
    print("=" * 110)
    print(f"{'QID':<7} {'Profile':<22} {'T1 cnt':>6} {'T1 mass':>8} {'T2 cnt':>6} {'T2 mass':>8} {'T3 cnt':>6} {'T3 mass':>8} {'Overlap':>8}")
    print("-" * 110)

    t1_counts, t2_counts, t3_counts = [], [], []
    t1_masses, t2_masses, t3_masses = [], [], []

    for r in results:
        tc = r["tier_contribution"]
        t1 = tc.get("tier1_entity", {})
        t2 = tc.get("tier2_structural", {})
        t3 = tc.get("tier3_thematic", {})
        overlap = tc.get("overlap", {})
        total_overlap = overlap.get("tier1_tier2", 0) + overlap.get("tier1_tier3", 0) + overlap.get("tier2_tier3", 0)

        t1c = t1.get("count", 0)
        t2c = t2.get("count", 0)
        t3c = t3.get("count", 0)
        t1m = t1.get("weight_mass", 0)
        t2m = t2.get("weight_mass", 0)
        t3m = t3.get("weight_mass", 0)

        t1_counts.append(t1c); t2_counts.append(t2c); t3_counts.append(t3c)
        t1_masses.append(t1m); t2_masses.append(t2m); t3_masses.append(t3m)

        print(f"{r['qid']:<7} {r['profile']:<22} {t1c:>6} {t1m:>8.4f} {t2c:>6} {t2m:>8.4f} {t3c:>6} {t3m:>8.4f} {total_overlap:>8}")

    print("-" * 110)
    n = len(results)
    print(f"{'AVG':<7} {'':22} {sum(t1_counts)/n:>6.1f} {sum(t1_masses)/n:>8.4f} {sum(t2_counts)/n:>6.1f} {sum(t2_masses)/n:>8.4f} {sum(t3_counts)/n:>6.1f} {sum(t3_masses)/n:>8.4f}")

    # Per-seed weight analysis
    print("\n" + "=" * 110)
    print("PER-SEED WEIGHT ANALYSIS (weight dilution)")
    print("=" * 110)
    print(f"{'QID':<7} {'T1 per_seed':>12} {'T2 per_seed':>12} {'T3 per_seed':>12} {'T1:T2 ratio':>12} {'T1:T3 ratio':>12}")
    print("-" * 110)
    for r in results:
        tc = r["tier_contribution"]
        t1ps = tc.get("tier1_entity", {}).get("per_seed_weight", 0)
        t2ps = tc.get("tier2_structural", {}).get("per_seed_weight", 0)
        t3ps = tc.get("tier3_thematic", {}).get("per_seed_weight", 0)
        ratio12 = f"{t1ps/t2ps:.1f}x" if t2ps > 0 else "inf"
        ratio13 = f"{t1ps/t3ps:.1f}x" if t3ps > 0 else "inf"
        print(f"{r['qid']:<7} {t1ps:>12.5f} {t2ps:>12.5f} {t3ps:>12.5f} {ratio12:>12} {ratio13:>12}")

    # Save JSON
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"tier_contribution_{timestamp}.json"
    with open(out_path, "w") as f:
        json.dump({"timestamp": timestamp, "group_id": args.group_id, "results": results}, f, indent=2)
    print(f"\nJSON saved: {out_path}")


if __name__ == "__main__":
    main()
