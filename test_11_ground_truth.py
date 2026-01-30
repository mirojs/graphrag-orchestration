#!/usr/bin/env python3
"""
Focused test for 11 ground-truth inconsistencies between Invoice and Contract/Exhibit A.

Ground Truth (from V1 analysis):
1. Lift model: Savaria V1504 (invoice) vs AscendPro VPX200 (contract)
2. Cab wording: "Custom cab" (contract) vs "Special Size" (invoice)
3. Door specs: 80" high, WR-500 lock (invoice only, not in contract)
4. Flush-mount hall calls: In Exhibit A, not in invoice
5. Keyless access: In Exhibit A, not in invoice
6. Payment terms: $29,900 lump sum (invoice) vs staged milestones (contract)
7. Customer name: Fabrikam Inc. (contract) vs Fabrikam Construction (invoice)
8. Bayfront Animal Clinic: Job reference in Exhibit A
9. Malformed URL: http://www.contoso.com/... in invoice
10. Tax ambiguity: "N/A" on invoice
11. Change order requirement: In contract, not reflected in invoice
"""

import asyncio
import json
import os
import sys
import re
from datetime import datetime

# Add the app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "graphrag-orchestration"))

# Ground truth inconsistencies to check
GROUND_TRUTH = {
    "1_lift_model": {
        "description": "Lift model mismatch: Savaria V1504 (invoice) vs AscendPro VPX200 (contract)",
        "keywords": ["savaria", "v1504", "ascendpro", "vpx200", "lift model", "model mismatch"],
        "found": False,
    },
    "2_cab_wording": {
        "description": "Cab wording: 'Custom cab' (contract) vs 'Special Size' (invoice)",
        "keywords": ["custom cab", "special size", "42.*62", "cab size"],
        "found": False,
    },
    "3_door_specs": {
        "description": "Door specs: 80\" high, WR-500 lock (invoice details not in contract)",
        "keywords": ["80.*high", "wr-500", "wr500", "door.*lock", "plexi-glass", "plexiglass"],
        "found": False,
    },
    "4_flush_mount": {
        "description": "Flush-mount hall call stations in Exhibit A, not in invoice",
        "keywords": ["flush-mount", "flush mount", "hall call station", "exhibit a"],
        "found": False,
    },
    "5_keyless_access": {
        "description": "Keyless access mentioned in Exhibit A, not in invoice",
        "keywords": ["keyless", "keyless access"],
        "found": False,
    },
    "6_payment_terms": {
        "description": "Payment: $29,900 lump (invoice) vs staged $20k/$7k/$2.9k (contract)",
        "keywords": ["20,000", "20000", "7,000", "7000", "2,900", "2900", "staged", "milestone", "upon signing", "upon delivery", "upon completion"],
        "found": False,
    },
    "7_customer_name": {
        "description": "Customer: Fabrikam Inc. (contract) vs Fabrikam Construction (invoice)",
        "keywords": ["fabrikam inc", "fabrikam construction", "customer name", "name mismatch"],
        "found": False,
    },
    "8_bayfront_clinic": {
        "description": "Bayfront Animal Clinic job reference in Exhibit A",
        "keywords": ["bayfront", "animal clinic", "job reference"],
        "found": False,
    },
    "9_malformed_url": {
        "description": "Malformed URL in invoice: http://www.contoso.com/...",
        "keywords": ["contoso.com", "malformed", "url", "remittance"],
        "found": False,
    },
    "10_tax_ambiguity": {
        "description": "Tax shown as N/A on invoice",
        "keywords": ["tax.*n/a", "tax ambiguit", "n/a"],
        "found": False,
    },
    "11_change_order": {
        "description": "Change order requirement in contract not reflected in invoice",
        "keywords": ["change order", "written approval", "modification"],
        "found": False,
    },
}


def check_ground_truth(response_text: str) -> dict:
    """Check which ground truth items are found in the response."""
    response_lower = response_text.lower()
    results = {}
    
    for key, item in GROUND_TRUTH.items():
        found = False
        matched_keyword = None
        for keyword in item["keywords"]:
            if re.search(keyword.lower(), response_lower):
                found = True
                matched_keyword = keyword
                break
        results[key] = {
            "description": item["description"],
            "found": found,
            "matched_keyword": matched_keyword,
        }
    
    return results


async def run_focused_test():
    """Run V2 query focused on finding all inconsistencies."""
    
    from app.hybrid_v2.pipeline.enhanced_pipeline import EnhancedHybridPipeline
    from app.services.async_neo4j_service import AsyncNeo4jService
    from llama_index.embeddings.voyageai import VoyageEmbedding
    
    # V2 configuration
    V2_GROUP = "test-5pdfs-v2-enhanced-ex"
    
    print("=" * 80)
    print("🎯 FOCUSED TEST: 11 Ground-Truth Inconsistencies")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y%m%d_%H%M%S')}")
    print(f"V2 Group: {V2_GROUP}")
    print("=" * 80)
    
    # Initialize Voyage embedder for V2
    voyage_embed = VoyageEmbedding(
        voyage_api_key=os.environ.get("VOYAGE_API_KEY"),
        model_name="voyage-3",
    )
    print("✅ Voyage embedding client initialized")
    
    # Initialize V2 pipeline
    async_neo4j = AsyncNeo4jService()
    await async_neo4j.connect()
    
    v2_pipeline = EnhancedHybridPipeline(
        group_id=V2_GROUP,
        async_neo4j_service=async_neo4j,
        embedding_client=voyage_embed,
    )
    print(f"✅ V2 pipeline initialized for {V2_GROUP}")
    
    # The focused query - designed to find ALL inconsistencies
    query = """
    Perform a comprehensive comparison between Invoice #1256003 and the Purchase Contract 
    (including Exhibit A - Scope of Work). List ALL inconsistencies, discrepancies, and 
    differences you can find, including:
    
    1. Equipment model numbers and specifications
    2. Cab dimensions and descriptions  
    3. Door specifications (height, locks, materials)
    4. Hall call station details (flush-mount, keyless access)
    5. Payment terms and schedules
    6. Customer/party names
    7. Any job references or prior work mentioned
    8. URLs or contact information
    9. Tax treatment
    10. Change order or modification requirements
    
    Be thorough - identify every single difference between invoice details and contract terms.
    """
    
    print("\n" + "=" * 80)
    print("📝 QUERY")
    print("=" * 80)
    print(query.strip())
    print("=" * 80)
    
    print("\n⏳ Running V2 query...")
    
    try:
        result = await v2_pipeline.query(
            query=query,
            response_type="summary",
        )
        
        response_text = result.response if hasattr(result, 'response') else str(result)
        citations = result.citations if hasattr(result, 'citations') else []
        
        print("\n" + "=" * 80)
        print("📊 V2 RESPONSE")
        print("=" * 80)
        print(response_text)
        print("=" * 80)
        print(f"\n📚 Citations: {len(citations)}")
        
        # Check ground truth
        print("\n" + "=" * 80)
        print("🎯 GROUND TRUTH SCORECARD")
        print("=" * 80)
        
        gt_results = check_ground_truth(response_text)
        
        found_count = 0
        missed_items = []
        
        for key, result in gt_results.items():
            status = "✅" if result["found"] else "❌"
            found_count += 1 if result["found"] else 0
            
            if result["found"]:
                print(f"{status} {key}: {result['description']}")
                print(f"   └─ Matched: '{result['matched_keyword']}'")
            else:
                print(f"{status} {key}: {result['description']}")
                missed_items.append(key)
        
        print("\n" + "-" * 80)
        print(f"📈 SCORE: {found_count}/11 ({found_count/11*100:.1f}%)")
        print("-" * 80)
        
        if missed_items:
            print(f"\n⚠️  MISSED ITEMS ({len(missed_items)}):")
            for item in missed_items:
                print(f"   - {item}: {GROUND_TRUTH[item]['description']}")
        
        # Save results
        output = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "response": response_text,
            "citations_count": len(citations),
            "ground_truth_results": gt_results,
            "score": f"{found_count}/11",
            "score_pct": found_count/11*100,
            "missed_items": missed_items,
        }
        
        output_file = f"ground_truth_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n💾 Results saved to: {output_file}")
        
    finally:
        await async_neo4j.close()
    
    print("\n✅ Test Complete")


if __name__ == "__main__":
    asyncio.run(run_focused_test())
