#!/usr/bin/env python3
"""Test Route 4 (drift_multi_hop) with comprehensive_sentence response type.

Tests the newly deployed comprehensive_sentence mode which uses:
- Single LLM call (not 2-pass like comprehensive)
- Azure Document Intelligence sentence spans for precise text boundaries
- Raw evidence approach (sentences + tables + HippoRAG chunks)

Evaluates against 16 ground truth items for invoice/contract inconsistency detection.
(Originally 14 items, expanded to 15 after confirming B6 opener/door-operator,
then 16 after confirming B7 power-system/operation-parts from Neo4j Table data.)
"""

import json
import time
import urllib.request
import urllib.error
import subprocess
from typing import Any, Dict, List, Tuple

# Cloud API configuration
CLOUD_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-v2-fix2"  # Indexed on Feb 2, 2026 at 14:11

# Invoice/Contract inconsistency query
QUERY = """Analyze the invoice and contract documents to find all inconsistencies, discrepancies, or conflicts between them. 

Look for differences in:
1. Major items: Product/service specifications, payment terms, customer/vendor names
2. Medium items: Feature specifications, terminology differences, payment structure contradictions
3. Minor items: Contact details, URLs, entity name variations, site references

Provide a detailed analysis with specific references to both documents."""

# 16 Ground Truth Items (3 major + 7 medium + 6 minor)
# History: 14 → 15 (B6 opener) → 16 (B7 power system / operation parts)
GROUND_TRUTH = {
    "major": [
        "A1: Lift model mismatch (Savaria V1504 vs AscendPro VPX200)",
        "A2: Payment structure conflict (Full $29,900 vs 3-stage)",
        "A3: Customer entity mismatch (Fabrikam Construction vs Fabrikam Inc.)",
    ],
    "medium": [
        "B1: Hall call spec gap (flush-mount vs not specified)",
        "B2: Door height added (80\" High vs not specified)",
        "B3: WR-500 lock added vs not specified",
        "B4: Outdoor terminology (fitting vs configuration package)",
        "B5: Invoice self-contradiction (initial payment vs full $29,900)",
        "B6: Automatic opener vs door operator terminology",
        "B7: Power system (contract) vs operation parts (invoice)",
    ],
    "minor": [
        "C1: URL malformed (ww.contosolifts.com)",
        "C2: John Doe contact (listed vs not in contract)",
        "C3: Contoso Ltd vs LLC (Exhibit A vs Contract)",
        "C4: Bayfront site mismatch (61 S 34th Street vs Bayfront Animal Clinic)",
        "C5: Address number (61 vs 62 S 34th Street)",
        "C6: Price decimal inconsistency ($29,900.00 vs $29,900)",
    ],
}


def make_request(query: str, group_id: str, response_type: str, force_route: str) -> Tuple[int, Any, float, str]:
    """Make HTTP POST request to cloud API."""
    try:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--scope",
                "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default",
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        token = result.stdout.strip()
    except Exception as e:
        return 0, {"error": f"Failed to get AAD token: {e}"}, 0.0, ""

    url = f"{CLOUD_URL}/hybrid/query"
    payload = {
        "query": query,
        "group_id": group_id,
        "response_type": response_type,
        "force_route": force_route,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Group-ID": group_id,
        "Authorization": f"Bearer {token}",
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.monotonic() - t0
            data = json.loads(raw)
            return int(resp.status), data, elapsed, raw
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        body = e.read().decode("utf-8", errors="replace") if e else None
        return int(e.code or 0), {"error": str(e), "body": body}, elapsed, body or ""
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, {"error": str(e)}, elapsed, str(e)


def score_response(response_text: str) -> Dict[str, Any]:
    """Score response against 16 ground truth items."""
    text_lower = response_text.lower()
    
    def check_item(keywords: List[str]) -> bool:
        """Check if any keyword is present in response."""
        return any(kw.lower() in text_lower for kw in keywords)
    
    scores = {
        "major": {
            "A1": check_item(["savaria", "v1504", "ascendpro", "vpx200", "lift model"]),
            "A2": check_item(["29900", "29,900", "payment", "stage", "20000", "7000", "2900"]),
            "A3": check_item(["fabrikam construction", "fabrikam inc", "customer", "entity"]),
        },
        "medium": {
            "B1": check_item(["hall call", "flush-mount", "flush mount"]),
            "B2": check_item(["door", "80", "height", "high"]),
            "B3": check_item(["wr-500", "wr500", "lock"]),
            "B4": check_item(["outdoor", "fitting", "configuration package"]),
            "B5": check_item(["initial payment", "contradiction", "29900", "full"]),
            "B6": check_item(["automatic opener", "door operator", "opener omit", "opener missing"]),
            "B7": check_item(["power system", "operation parts", "110 vac", "12 vac"]),
        },
        "minor": {
            "C1": check_item(["ww.contoso", "url", "malformed"]),
            "C2": check_item(["john doe", "contact"]),
            "C3": check_item(["contoso ltd", "contoso llc", "exhibit"]),
            "C4": check_item(["bayfront", "34th street", "site"]),
            "C5": check_item(["61", "62", "34th", "address"]),
            "C6": check_item(["decimal", "29900.00", "29,900.00"]),
        },
    }
    
    found_major = sum(1 for v in scores["major"].values() if v)
    found_medium = sum(1 for v in scores["medium"].values() if v)
    found_minor = sum(1 for v in scores["minor"].values() if v)
    found_total = found_major + found_medium + found_minor
    
    return {
        "scores": scores,
        "found": {
            "major": f"{found_major}/3",
            "medium": f"{found_medium}/7",
            "minor": f"{found_minor}/6",
            "total": f"{found_total}/16",
        },
        "percentage": f"{(found_total/16)*100:.1f}%",
    }


def main():
    print("=" * 80)
    print("ROUTE 4 + COMPREHENSIVE_SENTENCE TEST")
    print("=" * 80)
    print(f"Cloud API: {CLOUD_URL}")
    print(f"Group ID: {GROUP_ID}")
    print(f"Response Type: comprehensive_sentence")
    print(f"Force Route: drift_multi_hop")
    print(f"Query: {QUERY[:100]}...")
    print("=" * 80)
    print()
    
    print("Sending request...")
    status, data, elapsed, raw = make_request(
        query=QUERY,
        group_id=GROUP_ID,
        response_type="comprehensive_sentence",
        force_route="drift_multi_hop",
    )
    
    print(f"Status: {status}")
    print(f"Latency: {elapsed:.2f}s")
    print()
    
    if status != 200:
        print("ERROR:", json.dumps(data, indent=2))
        return
    
    # Debug: print raw response
    print("DEBUG - Raw response keys:", list(data.keys()) if isinstance(data, dict) else type(data))
    print("DEBUG - Raw response:", json.dumps(data, indent=2)[:500])
    print()
    
    # Extract response details
    response_text = data.get("response", "") if isinstance(data, dict) else ""
    raw_extractions = data.get("raw_extractions", []) if isinstance(data, dict) else []
    citations = data.get("citations", []) if isinstance(data, dict) else []
    evidence_path = data.get("evidence_path", []) if isinstance(data, dict) else []
    text_chunks_used = data.get("text_chunks_used", 0) if isinstance(data, dict) else 0
    processing_mode = data.get("processing_mode", "") if isinstance(data, dict) else ""
    sentence_based = data.get("sentence_based", False) if isinstance(data, dict) else False
    
    print("RESPONSE METADATA:")
    print(f"  Response length: {len(response_text):,} characters")
    print(f"  Processing mode: {processing_mode}")
    print(f"  Sentence-based: {sentence_based}")
    print(f"  Text chunks used: {text_chunks_used}")
    print(f"  Raw extractions: {len(raw_extractions)}")
    print(f"  Citations: {len(citations)}")
    print(f"  Evidence path: {len(evidence_path)} entities")
    print()
    
    # Show sentence extraction details
    if raw_extractions:
        print("SENTENCE EXTRACTION DETAILS:")
        for ext in raw_extractions:
            doc_title = ext.get("document_title", "Unknown")
            sentences = ext.get("sentences", [])
            total_spans = ext.get("total_spans", 0)
            print(f"  {doc_title}: {len(sentences)} sentences (from {total_spans} spans)")
        print()
    
    # Score against ground truth
    print("SCORING AGAINST 16 GROUND TRUTH ITEMS:")
    print("-" * 80)
    scoring = score_response(response_text)
    
    print(f"\nRESULTS:")
    print(f"  Major (A1-A3): {scoring['found']['major']}")
    print(f"  Medium (B1-B7): {scoring['found']['medium']}")
    print(f"  Minor (C1-C6): {scoring['found']['minor']}")
    print(f"  TOTAL: {scoring['found']['total']} = {scoring['percentage']}")
    print()
    
    # Detailed breakdown
    print("DETAILED BREAKDOWN:")
    for category, items in scoring["scores"].items():
        print(f"\n{category.upper()}:")
        for item_id, found in items.items():
            status_symbol = "✓" if found else "✗"
            print(f"  {status_symbol} {item_id}: {GROUND_TRUTH[category][list(items.keys()).index(item_id)]}")
    print()
    
    # Save full response
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = f"bench_route4_comprehensive_sentence_{timestamp}.json"
    with open(output_file, "w") as f:
        json.dump({
            "metadata": {
                "timestamp": timestamp,
                "cloud_url": CLOUD_URL,
                "group_id": GROUP_ID,
                "response_type": "comprehensive_sentence",
                "force_route": "drift_multi_hop",
                "latency_seconds": elapsed,
                "query": QUERY,
            },
            "response": data,
            "scoring": scoring,
            "raw_response": raw,
        }, f, indent=2)
    
    print(f"Full response saved to: {output_file}")
    print()
    
    # Show first 2000 chars of response
    print("RESPONSE TEXT (first 2000 chars):")
    print("-" * 80)
    print(response_text[:2000])
    if len(response_text) > 2000:
        print(f"\n... ({len(response_text) - 2000:,} more characters)")
    print()


if __name__ == "__main__":
    main()
