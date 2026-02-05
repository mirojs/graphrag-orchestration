#!/usr/bin/env python3
"""
KNN Benchmark v2 - Direct Neo4j testing with proper KNN configuration filtering.

This script tests the same query against different KNN configurations
by filtering SEMANTICALLY_SIMILAR edges by their knn_config property.

All configurations use the SAME baseline group (test-5pdfs-v2-enhanced-ex)
with different KNN edge sets tagged by knn_config.

Approach:
1. For baseline: Only traverse RELATED_TO edges (no SEMANTICALLY_SIMILAR)
2. For KNN configs: Also traverse SEMANTICALLY_SIMILAR edges matching knn_config
"""

import asyncio
import os
from typing import List, Dict, Any, Tuple
from neo4j import AsyncGraphDatabase
import httpx
import json
from datetime import datetime

# API endpoint (same as before)
API_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query"

# Test configurations - all use same group, different knn_config
BASELINE_GROUP = "test-5pdfs-v2-enhanced-ex"

TEST_CONFIGS = [
    {"knn_config": None, "name": "Baseline (No KNN)", "edges": 0},
    {"knn_config": "knn-1", "name": "KNN-1 (K=3, cutoff=0.80)", "edges": 348},
    {"knn_config": "knn-2", "name": "KNN-2 (K=5, cutoff=0.75)", "edges": 693},
    {"knn_config": "knn-3", "name": "KNN-3 (K=5, cutoff=0.85)", "edges": 213},
]

# Ground truth query
QUERY = """Analyze the invoice and contract documents to find all inconsistencies between invoice details (amounts, line items, quantities, payment terms) and the corresponding contract terms. Organize findings by: (1) payment schedule conflicts with evidence, (2) line item specification mismatches, and (3) billing or administrative discrepancies."""


def count_ground_truth_items(response_text: str) -> Tuple[int, List[str]]:
    """Count how many of the 16 ground truth inconsistency items were discovered."""
    text_norm = response_text.replace('‑', '-').replace('–', '-').replace('—', '-')
    text_lower = text_norm.lower()
    
    found_items = []
    
    # Category A - MAJOR (3 items)
    if any(x in text_lower for x in ["savaria", "v1504", "ascendpro", "vpx200"]) and \
       any(x in text_lower for x in ["model", "lift"]):
        found_items.append("A1_model_mismatch")
    
    if ("$20" in text_norm or "$7" in text_norm or "$2,900" in text_norm or "$2.9k" in text_lower) and \
       ("install" in text_lower or "stage" in text_lower or "milestone" in text_lower or "signing" in text_lower):
        found_items.append("A2_payment_conflict")
    
    if ("fabrikam inc" in text_lower and "fabrikam construction" in text_lower) or \
       ("customer" in text_lower and "name" in text_lower and "fabrikam" in text_lower):
        found_items.append("A3_customer_mismatch")
    
    # Category B - MEDIUM (5 items)
    if "flush" in text_lower and "mount" in text_lower and "hall" in text_lower:
        found_items.append("B1_hall_call_gap")
    
    if ('80"' in text_norm or "80-inch" in text_lower or "eighty inch" in text_lower) and \
       ("door" in text_lower or "height" in text_lower):
        found_items.append("B2_door_height")
    
    if "wr-500" in text_lower or "wr500" in text_lower:
        found_items.append("B3_lock_added")
    
    if ("outdoor" in text_lower and "fitting" in text_lower) or \
       ("outdoor" in text_lower and "configuration" in text_lower and "package" in text_lower):
        found_items.append("B4_outdoor_term")
    
    if "deposit" in text_lower and "install" in text_lower and "conflict" in text_lower:
        found_items.append("B5_invoice_contradiction")
    
    # Category C - MINOR (8 items)
    if "url" in text_lower or "http" in text_lower or "malformed" in text_lower:
        found_items.append("C1_malformed_url")
    
    if "john doe" in text_lower or "john.doe" in text_lower:
        found_items.append("C2_john_doe")
    
    if ("contoso" in text_lower and "ltd" in text_lower) and ("contoso" in text_lower and "llc" in text_lower):
        found_items.append("C3_contoso_ltd_llc")
    
    if "bayfront" in text_lower or "exhibit a" in text_lower:
        found_items.append("C4_bayfront_exhibit")
    
    if "keyless" in text_lower:
        found_items.append("C5_keyless_access")
    
    if ("change order" in text_lower or "written change" in text_lower) and \
       ("substitut" in text_lower or "product" in text_lower or "modification" in text_lower):
        found_items.append("C6_no_change_order")
    
    if "invoice #" in text_lower or "invoice number" in text_lower or "#45239" in text_norm:
        found_items.append("C7_invoice_number")
    
    if "8-10 week" in text_lower or "8 to 10 week" in text_lower or \
       ("delivery" in text_lower and "timeline" in text_lower):
        found_items.append("C8_delivery_timeline")
    
    return len(found_items), found_items


async def test_via_api(knn_config: str = None):
    """
    Test via deployed API.
    
    Note: The API currently doesn't support knn_config filtering,
    so this will use all edges. We include it for comparison.
    """
    async with httpx.AsyncClient(timeout=180.0) as client:
        payload = {
            "query": QUERY,
            "force_route": "drift_multi_hop",
            "response_type": "detailed_report"
        }
        
        # TODO: Add knn_config to API request when supported
        # if knn_config:
        #     payload["knn_config"] = knn_config
        
        response = await client.post(
            API_URL,
            headers={"X-Group-ID": BASELINE_GROUP},
            json=payload
        )
        response.raise_for_status()
        result = response.json()
    
    return result


async def main():
    print("=" * 80)
    print("KNN Benchmark v2 - Proper Configuration Testing")
    print("=" * 80)
    print(f"\nBaseline Group: {BASELINE_GROUP}")
    print(f"Query: {QUERY[:70]}...")
    print(f"\nTest Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    # Verify KNN edges exist
    print("\n" + "=" * 80)
    print("Step 1: Verifying KNN edge configurations")
    print("=" * 80)
    
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    
    async with driver.session() as session:
        result = await session.run("""
            MATCH (e1:Entity {group_id: $gid})-[r:SEMANTICALLY_SIMILAR]->(e2:Entity)
            RETURN r.knn_config AS config, count(r) AS cnt
            ORDER BY config
        """, gid=BASELINE_GROUP)
        records = await result.data()
        
        print("\nSEMANTICALLY_SIMILAR edges by knn_config:")
        for r in records:
            print(f"  {r['config']}: {r['cnt']} edges")
        
        if not records:
            print("  WARNING: No KNN edges found! Run rebuild_knn_groups_proper.py first.")
    
    await driver.close()
    
    # Test via API
    print("\n" + "=" * 80)
    print("Step 2: Testing via deployed API")
    print("=" * 80)
    
    results = []
    
    for cfg in TEST_CONFIGS:
        config_name = cfg["name"]
        knn_config = cfg["knn_config"]
        
        print(f"\n  Testing: {config_name}")
        
        try:
            result = await test_via_api(knn_config)
            
            answer = result.get("response", "")
            citations = result.get("citations", [])
            metadata = result.get("metadata", {})
            
            gt_count, gt_items = count_ground_truth_items(answer)
            
            results.append({
                "config": config_name,
                "knn_config": knn_config,
                "gt_score": f"{gt_count}/16",
                "gt_percentage": f"{(gt_count/16)*100:.1f}%",
                "gt_items": gt_items,
                "citations": len(citations),
                "seeds": len(metadata.get("all_seeds_discovered", [])),
            })
            
            print(f"    Ground Truth: {gt_count}/16 ({(gt_count/16)*100:.1f}%)")
            print(f"    Citations: {len(citations)}")
            
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({
                "config": config_name,
                "error": str(e)
            })
    
    # Summary
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    
    print("\n| Config | GT Score | Citations | Seeds |")
    print("|--------|----------|-----------|-------|")
    for r in results:
        if "error" in r:
            print(f"| {r['config'][:20]} | ERROR | - | - |")
        else:
            print(f"| {r['config'][:20]} | {r['gt_score']} ({r['gt_percentage']}) | {r['citations']} | {r['seeds']} |")
    
    print("\n" + "=" * 80)
    print("NOTE: Current API doesn't support knn_config filtering.")
    print("All tests use the full graph (baseline + all KNN edges).")
    print("")
    print("To properly test KNN configurations, we need to either:")
    print("1. Add knn_config parameter to the API endpoint")
    print("2. Or modify semantic_multihop_beam to accept edge filter")
    print("=" * 80)
    
    # Save results
    output_file = f"bench_knn_v2_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(output_file, "w") as f:
        f.write(f"KNN Benchmark v2 Results\n")
        f.write(f"Date: {datetime.utcnow().isoformat()}\n")
        f.write(f"Group: {BASELINE_GROUP}\n\n")
        f.write(json.dumps(results, indent=2))
    
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
