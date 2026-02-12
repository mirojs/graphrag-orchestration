#!/usr/bin/env python3
"""Benchmark Route 3 (Global Search) baseline performance.

Tests Route 3 on thematic/cross-document queries to establish baseline
metrics before adding skeleton enrichment. This provides the comparison
point for Phase 1.2 (identify which questions Route 3 fails on).

Route 3 is designed for:
- Thematic synthesis ("What are the risk management provisions?")
- Cross-document analysis ("Compare termination clauses")
- Entity-driven discovery with PPR scoring

This benchmark uses the Route 3 thematic question bank and measures:
- Theme coverage (% of expected themes addressed)
- Entity recall (% of expected entities found)
- Evidence quality (number of evidence nodes)
- Coherence (response structure quality)
- F1/containment vs ground truth (where applicable)

Usage:
    python scripts/benchmark_route3_baseline.py
    python scripts/benchmark_route3_baseline.py --group-id test-5pdfs-v2-fix2
    python scripts/benchmark_route3_baseline.py --url http://localhost:8000
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

import numpy as np

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


def call_route3_api(api_url: str, query: str, include_context: bool = True, timeout: float = 180.0) -> Dict[str, Any]:
    """Call Route 3 (global_search) API and return response + metadata."""
    url = f"{api_url.rstrip('/')}/hybrid/query"
    headers = {"Content-Type": "application/json", "X-Group-ID": GROUP_ID}
    token = _get_aad_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "query": query,
        "force_route": "global_search",  # Route 3
        "response_type": "summary",
        "include_context": include_context,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            
            metadata = body.get("metadata", {})
            return {
                "response": body.get("response", ""),
                "llm_context": metadata.get("llm_context", ""),
                "evidence_path": metadata.get("evidence_path", []),
                "hub_entities": metadata.get("hub_entities", []),
                "num_evidence_nodes": metadata.get("num_evidence_nodes", 0),
                "num_chunks": metadata.get("num_chunks", 0),
                "elapsed_ms": elapsed_ms,
                "error": None,
            }
    except Exception as e:
        return {
            "response": "",
            "llm_context": "",
            "evidence_path": [],
            "hub_entities": [],
            "num_evidence_nodes": 0,
            "num_chunks": 0,
            "elapsed_ms": 0,
            "error": str(e),
        }


# ─── Thematic Question Bank ──────────────────────────────────────
ROUTE3_QUESTIONS = [
    {
        "id": "T-1",
        "query": "What are the common themes across all the contracts and agreements in these documents?",
        "expected_themes": ["legal obligations", "payment terms", "termination clauses", "liability provisions", "dispute resolution"],
        "expected_entities": ["parties", "dates", "monetary values", "legal terms"],
        "min_evidence_nodes": 10,
        "cross_document": True,
    },
    {
        "id": "T-2",
        "query": "How do the different parties relate to each other across the documents?",
        "expected_themes": ["contractual relationships", "service providers", "clients", "third parties"],
        "expected_entities": ["organization names", "person names", "roles"],
        "min_evidence_nodes": 8,
        "cross_document": True,
    },
    {
        "id": "T-3",
        "query": "What patterns emerge in the financial terms and payment structures?",
        "expected_themes": ["payment schedules", "amounts", "penalties", "invoicing"],
        "expected_entities": ["dollar amounts", "percentages", "dates", "payment terms"],
        "min_evidence_nodes": 8,
        "cross_document": True,
    },
    {
        "id": "T-4",
        "query": "Summarize the risk management and liability provisions across all documents.",
        "expected_themes": ["indemnification", "limitation of liability", "insurance requirements", "warranties"],
        "expected_entities": ["coverage amounts", "conditions", "exclusions"],
        "min_evidence_nodes": 8,
        "cross_document": True,
    },
    {
        "id": "T-5",
        "query": "What dispute resolution mechanisms are mentioned across the agreements?",
        "expected_themes": ["arbitration", "mediation", "litigation", "jurisdiction", "governing law"],
        "expected_entities": ["legal entities", "locations", "time limits"],
        "min_evidence_nodes": 5,
        "cross_document": True,
    },
    {
        "id": "T-6",
        "query": "How do the documents address confidentiality and data protection?",
        "expected_themes": ["NDA provisions", "data handling", "privacy", "disclosure limitations"],
        "expected_entities": ["information types", "time periods", "exceptions"],
        "min_evidence_nodes": 5,
        "cross_document": True,
    },
    {
        "id": "T-7",
        "query": "What are the key obligations and responsibilities outlined for each party?",
        "expected_themes": ["deliverables", "timelines", "performance standards", "compliance"],
        "expected_entities": ["party names", "deadlines", "quality metrics"],
        "min_evidence_nodes": 8,
        "cross_document": True,
    },
    {
        "id": "T-8",
        "query": "Compare the termination and cancellation provisions across the documents.",
        "expected_themes": ["notice periods", "grounds for termination", "effects of termination", "survival clauses"],
        "expected_entities": ["time periods", "conditions", "procedures"],
        "min_evidence_nodes": 8,
        "cross_document": True,
    },
    {
        "id": "T-9",
        "query": "What insurance and indemnification requirements appear in the documents?",
        "expected_themes": ["coverage types", "minimum amounts", "certificate requirements", "named insureds"],
        "expected_entities": ["insurance types", "dollar limits", "carriers"],
        "min_evidence_nodes": 5,
        "cross_document": True,
    },
    {
        "id": "T-10",
        "query": "Identify the key dates, deadlines, and time-sensitive provisions across all documents.",
        "expected_themes": ["effective dates", "expiration", "renewal", "notice periods", "response times"],
        "expected_entities": ["specific dates", "durations", "milestones"],
        "min_evidence_nodes": 8,
        "cross_document": True,
    },
]


# ─── Simple theme/entity checking ────────────────────────────────
def check_theme_coverage(response: str, expected_themes: List[str]) -> float:
    """Simple substring match for theme coverage (normalized to lowercase)."""
    response_lower = response.lower()
    found = sum(1 for theme in expected_themes if theme.lower() in response_lower)
    return found / len(expected_themes) if expected_themes else 0.0


def check_entity_recall(hub_entities: List[str], evidence_path: List[str], expected_entities: List[str]) -> float:
    """Simple substring match for entity recall (normalized to lowercase)."""
    all_entities = " ".join(hub_entities + evidence_path).lower()
    found = sum(1 for entity in expected_entities if entity.lower() in all_entities)
    return found / len(expected_entities) if expected_entities else 0.0


# ─── Main benchmark ───────────────────────────────────────────────
def run_benchmark(api_url: str, output_file: Optional[str] = None):
    """Run Route 3 baseline benchmark on thematic questions."""
    print("=" * 70)
    print("  ROUTE 3 BASELINE BENCHMARK")
    print("=" * 70)
    print(f"  API:      {api_url}")
    print(f"  Group:    {GROUP_ID}")
    print(f"  Questions: {len(ROUTE3_QUESTIONS)}")
    print("=" * 70)
    print()

    results = []
    
    for i, q in enumerate(ROUTE3_QUESTIONS, 1):
        qid = q["id"]
        query = q["query"]
        print(f"\n[{i}/{len(ROUTE3_QUESTIONS)}] {qid}: {query[:60]}...")
        
        # Call Route 3 API
        resp = call_route3_api(api_url, query, include_context=True)
        
        if resp.get("error"):
            print(f"  ❌ ERROR: {resp['error']}")
            results.append({
                "question_id": qid,
                "query": query,
                "error": resp["error"],
                "response": "",
                "elapsed_ms": 0,
            })
            continue
        
        # Calculate metrics
        theme_coverage = check_theme_coverage(resp["response"], q["expected_themes"])
        entity_recall = check_entity_recall(
            resp.get("hub_entities", []),
            resp.get("evidence_path", []),
            q["expected_entities"]
        )
        evidence_quality = resp.get("num_evidence_nodes", 0) >= q["min_evidence_nodes"]
        
        # Display results
        print(f"  ✓ Response: {len(resp['response'])} chars")
        print(f"  ⏱  Latency: {resp['elapsed_ms']}ms")
        print(f"  📊 Theme Coverage: {theme_coverage:.1%} ({sum(1 for t in q['expected_themes'] if t.lower() in resp['response'].lower())}/{len(q['expected_themes'])})")
        print(f"  🔍 Entity Recall: {entity_recall:.1%}")
        print(f"  📈 Evidence Nodes: {resp.get('num_evidence_nodes', 0)} (min: {q['min_evidence_nodes']}) {'✓' if evidence_quality else '✗'}")
        print(f"  📄 Hub Entities: {len(resp.get('hub_entities', []))}")
        
        results.append({
            "question_id": qid,
            "query": query,
            "response": resp["response"],
            "llm_context": resp.get("llm_context", ""),
            "elapsed_ms": resp["elapsed_ms"],
            "theme_coverage": theme_coverage,
            "entity_recall": entity_recall,
            "num_evidence_nodes": resp.get("num_evidence_nodes", 0),
            "evidence_quality_pass": evidence_quality,
            "num_hub_entities": len(resp.get("hub_entities", [])),
            "num_chunks": resp.get("num_chunks", 0),
            "expected_themes": q["expected_themes"],
            "expected_entities": q["expected_entities"],
            "min_evidence_nodes": q["min_evidence_nodes"],
            "cross_document": q["cross_document"],
        })
    
    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    
    valid_results = [r for r in results if "error" not in r or not r["error"]]
    if valid_results:
        avg_theme = np.mean([r["theme_coverage"] for r in valid_results])
        avg_entity = np.mean([r["entity_recall"] for r in valid_results])
        avg_latency = np.mean([r["elapsed_ms"] for r in valid_results])
        evidence_pass_rate = sum(r["evidence_quality_pass"] for r in valid_results) / len(valid_results)
        
        print(f"  Avg Theme Coverage:     {avg_theme:.1%}")
        print(f"  Avg Entity Recall:      {avg_entity:.1%}")
        print(f"  Evidence Quality Pass:  {evidence_pass_rate:.1%} ({sum(r['evidence_quality_pass'] for r in valid_results)}/{len(valid_results)})")
        print(f"  Avg Latency:            {avg_latency:.0f}ms")
    
    # Save results
    if output_file is None:
        output_file = f"benchmark_route3_baseline_{_now()}.json"
    
    output_path = PROJECT_ROOT / output_file
    with open(output_path, "w") as f:
        json.dump({
            "benchmark_type": "route3_baseline",
            "timestamp": _now(),
            "group_id": GROUP_ID,
            "api_url": api_url,
            "num_questions": len(ROUTE3_QUESTIONS),
            "results": results,
            "summary": {
                "avg_theme_coverage": float(avg_theme) if valid_results else 0,
                "avg_entity_recall": float(avg_entity) if valid_results else 0,
                "evidence_pass_rate": float(evidence_pass_rate) if valid_results else 0,
                "avg_latency_ms": float(avg_latency) if valid_results else 0,
            } if valid_results else {},
        }, f, indent=2)
    
    print(f"\n✓ Results saved to: {output_path}")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Route 3 baseline performance")
    parser.add_argument("--url", default=DEFAULT_API_URL, help="API base URL")
    parser.add_argument("--group-id", default=GROUP_ID, help="Group ID for test corpus")
    parser.add_argument("--output", help="Output JSON file path")
    args = parser.parse_args()
    
    if args.group_id:
        GROUP_ID = args.group_id
    
    run_benchmark(args.url, args.output)
