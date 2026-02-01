#!/usr/bin/env python3
"""
Test all 4 KNN configurations via deployed API.
Based on handover requirements from 2026-01-31.

Tests comprehensive inconsistency query on all 4 KNN groups:
- knn-disabled (baseline, 0 KNN edges)
- knn-1 (K=3, cutoff=0.80, 361 edges)
- knn-2 (K=5, cutoff=0.75, 613 edges)
- knn-3 (K=5, cutoff=0.85, 525 edges)
"""

import asyncio
import httpx
import json
from datetime import datetime

# API endpoint
API_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query"

# Test groups from handover (corrected to use enhanced-ex as baseline)
TEST_GROUPS = [
    {"group_id": "test-5pdfs-v2-enhanced-ex", "name": "Baseline (No KNN)", "k": 0, "cutoff": 1.0, "edges": 0},
    {"group_id": "test-5pdfs-v2-knn-1", "name": "KNN-1 (Conservative)", "k": 3, "cutoff": 0.80, "edges": 408},
    {"group_id": "test-5pdfs-v2-knn-2", "name": "KNN-2 (Relaxed)", "k": 5, "cutoff": 0.75, "edges": 679},
    {"group_id": "test-5pdfs-v2-knn-3", "name": "KNN-3 (Strict)", "k": 5, "cutoff": 0.85, "edges": 590},
]

# Single comprehensive query for ground truth scoring
# This is the "3 deep questions" query from ANALYSIS_ROUTE4_V1_VS_V2_INVOICE_CONSISTENCY_2026-01-29.md
# Route 4 DRIFT automatically decomposes this into sub-questions (Q1, Q2, Q3) and formats responses with numbered points
#
# IMPORTANT: Query must explicitly mention document types (invoice, contract) for
# entity extraction to work. Generic queries like "all inconsistencies" fail to
# extract seed entities, causing the pipeline to fall back to sparse retrieval.
QUERY_GROUND_TRUTH = """Analyze the invoice and contract documents to find all inconsistencies between invoice details (amounts, line items, quantities, payment terms) and the corresponding contract terms. Organize findings by: (1) payment schedule conflicts with evidence, (2) line item specification mismatches, and (3) billing or administrative discrepancies."""


def count_ground_truth_items(response_text):
    """
    Count how many of the 16 ground truth inconsistency items were discovered.
    Based on GROUND_TRUTH_EXPANDED_16_ITEMS.md.
    
    Categories:
    - A (MAJOR): 3 items - model mismatch, payment conflict, customer mismatch
    - B (MEDIUM): 5 items - hall call, door height, lock, outdoor term, invoice contradiction  
    - C (MINOR): 8 items - URL, John Doe, Contoso Ltd/LLC, Bayfront, keyless, change order, invoice #, delivery
    """
    # Normalize Unicode hyphens (V2 uses non-breaking hyphen U+2011)
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
    
    if ("initial payment" in text_lower and "$29,900" in text_norm) or \
       ("invoice" in text_lower and "contradic" in text_lower):
        found_items.append("B5_invoice_contradiction")
    
    # Category C - MINOR (8 items)
    if "ww.contoso" in text_lower or ("malformed" in text_lower and "url" in text_lower):
        found_items.append("C1_url_malformed")
    
    if "john doe" in text_lower:
        found_items.append("C2_john_doe")
    
    if ("contoso ltd" in text_lower and "contoso lifts llc" in text_lower) or \
       ("contoso ltd" in text_lower and "llc" in text_lower):
        found_items.append("C3_contoso_ltd_llc")
    
    if "bayfront" in text_lower and ("animal clinic" in text_lower or "site" in text_lower or "61 s 34th" in text_lower):
        found_items.append("C4_bayfront_site")
    
    if "keyless" in text_lower:
        found_items.append("C5_keyless_access")
    
    if ("change order" in text_lower or "written change" in text_lower) and \
       ("substitut" in text_lower or "product" in text_lower or "modification" in text_lower):
        found_items.append("C6_no_change_order")
    
    # C7 - Invoice number #1256003 (corrected from invalid #45239)
    if "#1256003" in text_norm or "1256003" in text_lower or "invoice number" in text_lower:
        found_items.append("C7_invoice_number")
    
    if ("8-10 week" in text_lower or "8 to 10 week" in text_lower or "delivery" in text_lower and "timeline" in text_lower):
        found_items.append("C8_delivery_timeline")
    
    return len(found_items), found_items


async def test_group(group_id: str, group_name: str, k: int, cutoff: float, edges: int):
    """Test single comprehensive query on a KNN group for ground truth scoring."""
    print(f"\n{'='*80}")
    print(f"🔬 Testing: {group_name}")
    print(f"{'='*80}")
    print(f"  Group ID:         {group_id}")
    print(f"  K (neighbors):    {k}")
    print(f"  Similarity Cutoff: {cutoff}")
    print(f"  KNN Edges:        {edges}")
    print()
    
    # Run the single comprehensive query (DRIFT auto-decomposes into sub-questions)
    print(f"\n📝 Running Ground Truth Query...")
    print(f"   Query: {QUERY_GROUND_TRUTH[:70]}...")
    gt_count = 0
    gt_items = []
    total_citations = 0
    answer = ""
    route = "unknown"
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                API_URL,
                headers={"X-Group-ID": group_id},
                json={
                    "query": QUERY_GROUND_TRUTH,
                    "force_route": "drift_multi_hop",  # Force Route 4 (DRIFT) for multi-hop reasoning
                    "response_type": "detailed_report"
                }
            )
            response.raise_for_status()
            result = response.json()
        
        answer = result.get("response", "")
        route = result.get("route_used", "unknown")
        citations = result.get("citations", [])
        
        gt_count, gt_items = count_ground_truth_items(answer)
        total_citations = len(citations)
        
        print(f"   ✅ Route: {route}")
        print(f"   ✅ Ground Truth: {gt_count}/16 items detected")
        print(f"   📚 Citations: {total_citations}")
        print(f"   📄 Response length: {len(answer)} chars")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {
            "group_id": group_id,
            "name": group_name,
            "k": k,
            "cutoff": cutoff,
            "edges": edges,
            "error": str(e)
        }
    
    # Extract metadata for analysis
    metadata = result.get("metadata", {})
    all_seeds = metadata.get("all_seeds_discovered", [])
    text_chunks_used = metadata.get("text_chunks_used", 0)
    num_evidence = metadata.get("num_evidence_nodes", 0)
    
    print(f"\n{'='*80}")
    print(f"📊 {group_name} SUMMARY")
    print(f"{'='*80}")
    print(f"  Ground Truth (16 items):   {gt_count}/16 ({100*gt_count/16:.1f}%)")
    print(f"  Seeds Discovered:          {len(all_seeds)}")
    print(f"  Text Chunks Used:          {text_chunks_used}")
    print(f"  Items Found: {', '.join(gt_items[:8])}")
    if len(gt_items) > 8:
        print(f"               {', '.join(gt_items[8:])}")
    
    return {
        "group_id": group_id,
        "name": group_name,
        "k": k,
        "cutoff": cutoff,
        "edges": edges,
        "ground_truth_count": gt_count,
        "ground_truth_percentage": 100*gt_count/16,
        "ground_truth_items": gt_items,
        "total_citations": total_citations,
        "response_length": len(answer),
        "route": route,
        "response": answer,  # Store full response for later analysis
        "metadata": metadata  # Store full metadata for debugging
    }


async def main():
    print("="*80)
    print("🧪 KNN Benchmark Test - Invoice/Contract Inconsistency Detection")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API: {API_URL}")
    print(f"Route: DRIFT Multi-Hop (Route 4)")
    print(f"Query: Single comprehensive query (DRIFT auto-decomposes into sub-questions)")
    print(f"Groups: {len(TEST_GROUPS)}")
    print()
    
    results = []
    for group in TEST_GROUPS:
        result = await test_group(
            group_id=group["group_id"],
            group_name=group["name"],
            k=group["k"],
            cutoff=group["cutoff"],
            edges=group["edges"]
        )
        results.append(result)
        await asyncio.sleep(3)  # Brief pause between requests
    
    # Summary Table
    print("\n" + "="*80)
    print("📊 BENCHMARK RESULTS SUMMARY")
    print("="*80)
    print(f"{'Configuration':<25s} | {'Edges':>5s} | {'GT/16':>5s} | {'GT%':>5s} | {'Cites':>5s}")
    print("-" * 80)
    
    for r in results:
        if "error" in r:
            print(f"{r['name']:<25s} | {r.get('edges', 0):>5d} | {'ERR':>5s} | {'-':>5s} | {'-':>5s}")
        else:
            print(f"{r['name']:<25s} | "
                  f"{r['edges']:>5d} | "
                  f"{r['ground_truth_count']:>5d} | "
                  f"{r['ground_truth_percentage']:>4.0f}% | "
                  f"{r['total_citations']:>5d}")
    
    print("="*80)
    
    # Analysis
    print("\n📈 ANALYSIS")
    print("-" * 80)
    
    successful_results = [r for r in results if "error" not in r]
    if successful_results:
        best_gt = max(successful_results, key=lambda x: x['ground_truth_count'])
        
        print(f"Best Ground Truth Coverage: {best_gt['name']} ({best_gt['ground_truth_count']}/16 = {best_gt['ground_truth_percentage']:.1f}%)")
        
        # Compare KNN vs baseline
        baseline = next((r for r in successful_results if r['group_id'] == 'test-5pdfs-v2-enhanced-ex'), None)
        if baseline:
            print(f"\nBaseline (V2 No KNN):       GT={baseline['ground_truth_count']}/16 ({baseline['ground_truth_percentage']:.1f}%)")
            for r in successful_results:
                if r['group_id'] != 'test-5pdfs-v2-enhanced-ex':
                    gt_diff = r['ground_truth_count'] - baseline['ground_truth_count']
                    gt_sign = "+" if gt_diff > 0 else ""
                    print(f"  vs {r['name']:<20s}: GT {gt_sign}{gt_diff} ({r['ground_truth_count']}/16)")
    
    # Recommendation
    print("\n🎯 RECOMMENDATION")
    print("-" * 80)
    if successful_results:
        best = max(successful_results, key=lambda x: x['ground_truth_count'])
        baseline = next((r for r in successful_results if r['group_id'] == 'test-5pdfs-v2-enhanced-ex'), None)
        
        if baseline and best['ground_truth_count'] > baseline['ground_truth_count']:
            print(f"KNN HELPS: {best['name']} improves ground truth by {best['ground_truth_count'] - baseline['ground_truth_count']} items over baseline")
            print(f"  → Use K={best['k']}, cutoff={best['cutoff']}")
        elif baseline and best['ground_truth_count'] == baseline['ground_truth_count']:
            print(f"KNN NEUTRAL: No improvement over baseline ({baseline['ground_truth_count']}/16)")
            print(f"  → KNN adds complexity without benefit for this query type")
        else:
            print(f"KNN HURTS: Best KNN ({best['name']}) scores lower than baseline")
            print(f"  → Keep KNN disabled for this use case")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"bench_knn_results_{timestamp}.json"
    
    # Don't save full responses to keep file small
    results_to_save = []
    for r in results:
        r_copy = r.copy()
        if "response" in r_copy:
            r_copy["response_preview"] = r_copy["response"][:500] + "..."
            del r_copy["response"]
        results_to_save.append(r_copy)
    
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "api_url": API_URL,
            "query": QUERY_GROUND_TRUTH,
            "results": results_to_save
        }, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to: {output_file}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
