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
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

# Thematic questions with expected entities and themes
# UPDATED: 5PDF-specific questions grounded in actual document content
THEMATIC_QUESTIONS = [
    {
        "id": "T-1",
        "query": "Compare the termination and cancellation provisions across all the agreements.",
        "expected_themes": ["60 days", "written notice", "3 business days", "refund", "forfeited", "terminates"],
        "expected_entity_types": ["period", "condition", "procedure"],
        "min_evidence_nodes": 3,
    },
    {
        "id": "T-2", 
        "query": "Summarize the different payment structures and fees across the documents.",
        "expected_themes": ["29900", "installment", "commission", "25%", "10%", "$75", "$50"],
        "expected_entity_types": ["money", "percentage", "fee"],
        "min_evidence_nodes": 3,
    },
    {
        "id": "T-3",
        "query": "What jurisdictions and governing laws are referenced across the documents?",
        "expected_themes": ["idaho", "florida", "hawaii", "pocatello", "arbitration"],
        "expected_entity_types": ["state", "location", "legal"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-4",
        "query": "Summarize the liability, insurance, and indemnification provisions found in the documents.",
        "expected_themes": ["liability", "insurance", "$300,000", "$25,000", "hold harmless", "indemnify"],
        "expected_entity_types": ["coverage", "limit", "condition"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-5",
        "query": "What dispute resolution and arbitration mechanisms are described in the documents?",
        "expected_themes": ["arbitration", "binding", "small claims", "legal fees", "dispute"],
        "expected_entity_types": ["procedure", "legal", "remedy"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-6",
        "query": "Summarize all the reporting and record-keeping obligations mentioned across the documents.",
        "expected_themes": ["pumper", "county", "monthly statement", "income", "expenses", "report"],
        "expected_entity_types": ["report", "obligation", "frequency"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-7",
        "query": "What notice and delivery mechanisms are specified (written notice, certified mail, phone, filings)?",
        "expected_themes": ["60 days", "written notice", "certified mail", "10 business days", "phone"],
        "expected_entity_types": ["method", "period", "requirement"],
        "min_evidence_nodes": 2,
    },
    {
        "id": "T-8",
        "query": "What non-refundable fees and forfeiture terms are mentioned in the documents?",
        "expected_themes": ["non-refundable", "$250", "start-up fee", "deposit", "forfeited"],
        "expected_entity_types": ["fee", "condition", "penalty"],
        "min_evidence_nodes": 2,
    },
]

CROSS_DOC_QUESTIONS = [
    {
        "id": "X-1",
        "query": "List all the named parties and organizations across the documents and their roles.",
        "expected_themes": ["fabrikam", "contoso", "walt flood", "contoso lifts", "builder", "owner", "agent"],
        "min_evidence_nodes": 4,
    },
    {
        "id": "X-2",
        "query": "Summarize the main purpose and scope of each document in one sentence.",
        "expected_themes": ["warranty", "arbitration", "servicing", "management", "invoice", "purchase", "scope"],
        "min_evidence_nodes": 4,
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

    # Normalize common formatting differences so we measure content coverage,
    # not punctuation/currency/parentheses rendering.
    # Examples handled:
    # - "$29,900.00" should satisfy expected theme "29900"
    # - "three (3) business days" should satisfy "3 business days"
    # - "(10) business days" should satisfy "10 business days"
    text_lower = response_text.lower()
    normalized = (
        text_lower.replace("-", " ")
        .replace(",", "")
        .replace("$", "")
        .replace("(", "")
        .replace(")", "")
    )

    # Light punctuation-stripped view for matching common variants like
    # "attorney's fees" vs "attorneys fees".
    normalized_words = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized_words = " ".join(normalized_words.split())

    # Digit-only view for robust matching of numeric themes across formatting
    # differences such as "$300,000", "300000", "300 000", "$300,000.00".
    digits_only = re.sub(r"\D+", "", text_lower)

    found = 0
    for theme in expected_themes:
        tl = (theme or "").lower()
        if not tl:
            continue
        tnorm = (
            tl.replace("-", " ")
            .replace(",", "")
            .replace("$", "")
            .replace("(", "")
            .replace(")", "")
        )

        # Match digit-vs-word forms for small contractual numbers.
        # Examples: "10 business days" vs "ten business days", "60 days" vs "sixty days".
        def _number_word(n: int) -> Optional[str]:
            base = {
                0: "zero",
                1: "one",
                2: "two",
                3: "three",
                4: "four",
                5: "five",
                6: "six",
                7: "seven",
                8: "eight",
                9: "nine",
                10: "ten",
                11: "eleven",
                12: "twelve",
                13: "thirteen",
                14: "fourteen",
                15: "fifteen",
                16: "sixteen",
                17: "seventeen",
                18: "eighteen",
                19: "nineteen",
                20: "twenty",
                30: "thirty",
                40: "forty",
                50: "fifty",
                60: "sixty",
                70: "seventy",
                80: "eighty",
                90: "ninety",
            }
            return base.get(n)

        # If the expected theme contains a small number, accept the word form too.
        m_num = re.search(r"\b(\d{1,2})\b", tnorm)
        if m_num:
            n = int(m_num.group(1))
            w = _number_word(n)
            if w:
                # Replace only the specific number token with a digit|word alternation.
                num_pattern = re.escape(m_num.group(1))
                alt = rf"(?:{num_pattern}|{re.escape(w)})"
                theme_pattern = re.escape(tnorm)
                theme_pattern = re.sub(rf"\\b{num_pattern}\\b", alt, theme_pattern)
                if re.search(rf"\b{theme_pattern}\b", normalized_words):
                    found += 1
                    continue

        # Robust numeric match: if the expected theme is essentially a number,
        # match by digit-only substring.
        theme_digits = re.sub(r"\D+", "", tnorm)
        if theme_digits and len(theme_digits) >= 3:
            if theme_digits in digits_only:
                found += 1
                continue

        # Robust legal phrasing: "hold harmless" often appears as
        # "hold the [party] harmless" or across line breaks.
        if tnorm == "hold harmless":
            if re.search(r"\bhold\b[\s\S]{0,40}\bharmless\b", text_lower):
                found += 1
                continue

        # Common synonym variants expected in legal summaries.
        if tnorm == "legal fees":
            if re.search(r"\b(legal\s+fees?|attorney\s*'?s\s+fees?|attorneys\s+fees?)\b", text_lower):
                found += 1
                continue

        if tnorm == "phone":
            if re.search(r"\b(phone|telephone|telephonic|call)\b", text_lower):
                found += 1
                continue

        if tnorm == "certified mail":
            if re.search(r"\b(certified\s+mail|registered\s+mail)\b", normalized_words):
                found += 1
                continue

        if tnorm == "written notice":
            if re.search(r"\b(written\s+notice|notice\s+in\s+writing)\b", normalized_words):
                found += 1
                continue

        # Handle common word-form variants (avoid false negatives from legitimate phrasing).
        # Example: expected "indemnify" but the response uses "indemnification".
        if tnorm == "indemnify":
            if re.search(r"\bindemnif(y|ication|ied|ying|ies)\b", normalized):
                found += 1
                continue

        if tl in text_lower or tnorm in normalized:
            found += 1
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
