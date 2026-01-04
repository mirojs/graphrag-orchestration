#!/usr/bin/env python3
"""Route 3 Thematic Benchmark - Evaluates global search quality.

Route 3 (LazyGraphRAG) is designed for:
- Cross-document thematic synthesis
- Entity relationship discovery
- High-level pattern recognition

This benchmark evaluates:
1. Entity Discovery - Are relevant entities found?
2. Theme Coverage - Are expected themes addressed?
3. Evidence Quality - Is evidence path meaningful?
4. Response Coherence - Is synthesis well-structured?

Usage:
    python3 scripts/benchmark_route3_thematic.py \
        --url https://...azurecontainerapps.io \
        --group-id <group>
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

# Thematic questions with expected entities and themes
THEMATIC_QUESTIONS = [
    {
        "id": "T-1",
        "query": "What are the common themes across all the contracts and agreements in these documents?",
        "expected_themes": ["obligations", "payment", "termination", "liability", "dispute"],
        "expected_entity_types": ["legal", "financial", "party"],
        "min_evidence_nodes": 3,
    },
    {
        "id": "T-2", 
        "query": "How do the different parties relate to each other across the documents?",
        "expected_themes": ["relationship", "contract", "service", "client"],
        "expected_entity_types": ["organization", "person", "role"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-3",
        "query": "What patterns emerge in the financial terms and payment structures?",
        "expected_themes": ["payment", "amount", "invoice", "schedule"],
        "expected_entity_types": ["money", "date", "percentage"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-4",
        "query": "Summarize the risk management and liability provisions across all documents.",
        "expected_themes": ["liability", "indemnification", "insurance", "warranty"],
        "expected_entity_types": ["coverage", "limit", "condition"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-5",
        "query": "What dispute resolution mechanisms are mentioned across the agreements?",
        "expected_themes": ["arbitration", "mediation", "jurisdiction", "resolution"],
        "expected_entity_types": ["legal entity", "location", "procedure"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-6",
        "query": "How do the documents address confidentiality and data protection?",
        "expected_themes": ["confidential", "privacy", "disclosure", "data"],
        "expected_entity_types": ["information", "period", "exception"],
        "min_evidence_nodes": 1,
    },
    {
        "id": "T-7",
        "query": "What are the key obligations and responsibilities outlined for each party?",
        "expected_themes": ["obligation", "responsibility", "deliverable", "compliance"],
        "expected_entity_types": ["party", "deadline", "standard"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-8",
        "query": "Compare the termination and cancellation provisions across the documents.",
        "expected_themes": ["termination", "cancellation", "notice", "effect"],
        "expected_entity_types": ["period", "condition", "procedure"],
        "min_evidence_nodes": 2,
    },
]

CROSS_DOC_QUESTIONS = [
    {
        "id": "X-1",
        "query": "Which entities or concepts appear in multiple documents?",
        "expected_themes": ["common", "shared", "multiple"],
        "min_evidence_nodes": 3,
    },
    {
        "id": "X-2",
        "query": "What are the most important entities mentioned across the entire document set?",
        "expected_themes": ["key", "important", "central"],
        "min_evidence_nodes": 3,
    },
]


def _now_utc_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_group_id() -> str:
    env = os.getenv("TEST_GROUP_ID") or os.getenv("GROUP_ID")
    if env:
        return env
    p = Path(__file__).resolve().parents[1] / "last_test_group_id.txt"
    try:
        if p.exists():
            return p.read_text().strip() or "test-5pdfs-latest"
    except:
        pass
    return "test-5pdfs-latest"


def _http_post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float = 180.0,
) -> Tuple[int, Dict[str, Any], float, Optional[str]]:
    """POST JSON and return (status, json_response, elapsed_s, error)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.monotonic() - t0
            try:
                return int(resp.status), json.loads(raw), elapsed, None
            except:
                return int(resp.status), {"raw": raw}, elapsed, None
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        body = None
        try:
            body = e.read().decode("utf-8", errors="replace")
        except:
            pass
        return int(getattr(e, "code", 0) or 0), {"error": str(e), "body": body}, elapsed, str(e)
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, {"error": str(e)}, elapsed, str(e)


def evaluate_theme_coverage(response_text: str, expected_themes: List[str]) -> float:
    """Check what percentage of expected themes are mentioned in response."""
    if not response_text or not expected_themes:
        return 0.0
    
    text_lower = response_text.lower()
    found = sum(1 for theme in expected_themes if theme.lower() in text_lower)
    return found / len(expected_themes)


def evaluate_evidence_quality(metadata: Dict[str, Any], min_nodes: int) -> Dict[str, Any]:
    """Evaluate the quality of evidence returned."""
    hub_entities = metadata.get("hub_entities", [])
    num_evidence = metadata.get("num_evidence_nodes", 0)
    matched_communities = metadata.get("matched_communities", [])
    
    return {
        "hub_entity_count": len(hub_entities),
        "evidence_node_count": num_evidence,
        "community_count": len(matched_communities),
        "meets_threshold": num_evidence >= min_nodes,
        "hub_entities": hub_entities[:10],  # First 10 for display
    }


def evaluate_response_quality(response: Dict[str, Any], question: Dict[str, Any]) -> Dict[str, Any]:
    """Comprehensive evaluation of Route 3 response."""
    
    text = response.get("response", "")
    metadata = response.get("metadata", {})
    evidence_path = response.get("evidence_path", [])
    route_used = response.get("route_used", "")
    
    # Check if Route 3 was actually used
    is_route_3 = "route_3" in route_used or "global" in route_used
    
    # Theme coverage
    theme_score = evaluate_theme_coverage(text, question.get("expected_themes", []))
    
    # Evidence quality
    evidence_eval = evaluate_evidence_quality(metadata, question.get("min_evidence_nodes", 1))
    
    # Response quality indicators
    has_content = len(text) > 50
    has_structure = text.count(".") > 2  # Multiple sentences
    
    # Calculate overall score (0-100)
    score = 0
    if is_route_3:
        score += 20  # Correct route
    if evidence_eval["meets_threshold"]:
        score += 20  # Met evidence threshold
    if evidence_eval["hub_entity_count"] > 0:
        score += 15  # Found hub entities
    score += int(theme_score * 30)  # Theme coverage (up to 30)
    if has_content and has_structure:
        score += 15  # Response quality
    
    return {
        "question_id": question["id"],
        "query": question["query"],
        "route_used": route_used,
        "is_route_3": is_route_3,
        "theme_coverage": round(theme_score, 2),
        "evidence": evidence_eval,
        "response_length": len(text),
        "overall_score": score,
        "response_preview": text[:300] + "..." if len(text) > 300 else text,
        # New fields for enhanced graph retrieval
        "citations": response.get("citations", []),
        "num_citations": len(response.get("citations", [])),
        "metadata": metadata,
    }


def run_benchmark(
    base_url: str,
    group_id: str,
    timeout: float = 180.0,
) -> Dict[str, Any]:
    """Run the thematic benchmark for Route 3."""
    
    headers = {"Content-Type": "application/json", "X-Group-ID": group_id}
    endpoint = base_url.rstrip("/") + "/hybrid/query"
    
    all_questions = THEMATIC_QUESTIONS + CROSS_DOC_QUESTIONS
    results = []
    
    print(f"\n{'='*60}")
    print("Route 3 Thematic Benchmark")
    print(f"{'='*60}")
    print(f"URL: {base_url}")
    print(f"Group ID: {group_id}")
    print(f"Questions: {len(all_questions)}")
    print(f"{'='*60}\n")
    
    for i, question in enumerate(all_questions, 1):
        print(f"[{i}/{len(all_questions)}] {question['id']}: {question['query'][:60]}...")
        
        payload = {
            "query": question["query"],
            "force_route": "global_search",
            "response_type": "summary",
        }
        
        status, resp, elapsed_s, err = _http_post_json(
            endpoint, payload, headers, timeout
        )
        
        if err or status != 200:
            print(f"  ❌ Error: {err or resp.get('error', 'Unknown')}")
            results.append({
                "question_id": question["id"],
                "error": err or str(resp),
                "status": status,
            })
            continue
        
        eval_result = evaluate_response_quality(resp, question)
        eval_result["elapsed_ms"] = int(elapsed_s * 1000)
        eval_result["status"] = status
        results.append(eval_result)
        
        # Print summary
        score = eval_result["overall_score"]
        route = "✓ Route 3" if eval_result["is_route_3"] else "✗ Wrong route"
        theme = f"Theme: {eval_result['theme_coverage']:.0%}"
        evidence = f"Evidence: {eval_result['evidence']['evidence_node_count']} nodes"
        print(f"  {route} | {theme} | {evidence} | Score: {score}/100 | {eval_result['elapsed_ms']}ms")
    
    # Calculate summary statistics
    valid_results = [r for r in results if "overall_score" in r]
    
    summary = {
        "total_questions": len(all_questions),
        "successful": len(valid_results),
        "errors": len(results) - len(valid_results),
        "avg_score": sum(r["overall_score"] for r in valid_results) / len(valid_results) if valid_results else 0,
        "avg_theme_coverage": sum(r["theme_coverage"] for r in valid_results) / len(valid_results) if valid_results else 0,
        "route_3_rate": sum(1 for r in valid_results if r["is_route_3"]) / len(valid_results) if valid_results else 0,
        "evidence_threshold_met_rate": sum(1 for r in valid_results if r["evidence"]["meets_threshold"]) / len(valid_results) if valid_results else 0,
        "avg_hub_entities": sum(r["evidence"]["hub_entity_count"] for r in valid_results) / len(valid_results) if valid_results else 0,
        "avg_latency_ms": sum(r["elapsed_ms"] for r in valid_results) / len(valid_results) if valid_results else 0,
        # Citation stats
        "total_citations": sum(r.get("num_citations", 0) for r in valid_results),
        "avg_citations_per_question": sum(r.get("num_citations", 0) for r in valid_results) / len(valid_results) if valid_results else 0,
        "questions_with_citations": sum(1 for r in valid_results if r.get("num_citations", 0) > 0),
    }
    
    return {
        "meta": {
            "benchmark": "route3_thematic",
            "timestamp": _now_utc_stamp(),
            "url": base_url,
            "group_id": group_id,
        },
        "summary": summary,
        "results": results,
    }


def print_summary(data: Dict[str, Any]) -> None:
    """Print benchmark summary."""
    s = data["summary"]
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Questions: {s['successful']}/{s['total_questions']} successful")
    print(f"Average Score: {s['avg_score']:.1f}/100")
    print(f"Route 3 Usage: {s['route_3_rate']:.0%}")
    print(f"Theme Coverage: {s['avg_theme_coverage']:.0%}")
    print(f"Evidence Threshold Met: {s['evidence_threshold_met_rate']:.0%}")
    print(f"Avg Hub Entities: {s['avg_hub_entities']:.1f}")
    print(f"Avg Latency: {s['avg_latency_ms']:.0f}ms")
    # Citation stats
    print(f"Total Citations: {s.get('total_citations', 0)}")
    print(f"Avg Citations/Question: {s.get('avg_citations_per_question', 0):.1f}")
    print(f"Questions with Citations: {s.get('questions_with_citations', 0)}/{s['successful']}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Route 3 Thematic Benchmark")
    parser.add_argument("--url", default=DEFAULT_URL, help="Base URL of the API")
    parser.add_argument("--group-id", default=_default_group_id(), help="Group ID")
    parser.add_argument("--timeout", type=float, default=180.0, help="Request timeout")
    parser.add_argument("--output", help="Output JSON file path")
    args = parser.parse_args()
    
    results = run_benchmark(
        base_url=args.url,
        group_id=args.group_id,
        timeout=args.timeout,
    )
    
    print_summary(results)
    
    # Save results
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = out_dir / f"route3_thematic_{results['meta']['timestamp']}.json"
    
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
