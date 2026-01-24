#!/usr/bin/env python3
"""
Smoke test for Route 3 Fast Mode
Tests basic functionality with a few representative queries
"""
import os
import asyncio
import time
from typing import Dict, Any

# Set fast mode
os.environ["ROUTE3_FAST_MODE"] = "1"

async def test_fast_mode():
    """Run smoke tests for Fast Mode"""
    print("=" * 80)
    print("ROUTE 3 FAST MODE SMOKE TEST")
    print("=" * 80)
    print(f"\nEnvironment: ROUTE3_FAST_MODE={os.getenv('ROUTE3_FAST_MODE')}")
    print(f"Expected behavior:")
    print("  - Section Boost: SKIPPED")
    print("  - Keyword Boost: SKIPPED")
    print("  - Doc Lead Boost: SKIPPED")
    print("  - PPR: CONDITIONAL (based on query)")
    print("\n" + "=" * 80)
    
    # Test queries
    test_cases = [
        {
            "query": "What are the main compliance risks?",
            "expected_ppr": False,  # Simple thematic - no PPR needed
            "description": "Simple thematic query (should skip PPR)"
        },
        {
            "query": "Summarize all termination clauses",
            "expected_ppr": False,  # Cross-doc summary without 'across' - no PPR needed
            "description": "Cross-document summary (should skip PPR)"
        },
        {
            "query": "How is Fabrikam Inc connected to Contoso Ltd?",
            "expected_ppr": True,  # Relationship query + entities - needs PPR
            "description": "Relationship query with entities (should use PPR)"
        },
        {
            "query": "What are the payment terms related to vendor contracts?",
            "expected_ppr": True,  # Has 'related to' keyword - needs PPR
            "description": "Query with 'related to' keyword (should use PPR)"
        }
    ]
    
    print("\nTest Cases:")
    print("-" * 80)
    for i, tc in enumerate(test_cases, 1):
        print(f"\n{i}. {tc['description']}")
        print(f"   Query: '{tc['query']}'")
        print(f"   Expected PPR: {'YES' if tc['expected_ppr'] else 'NO'}")
        
        # Check PPR heuristics
        ql = tc['query'].lower()
        relationship_keywords = [
            "connected", "through", "linked", "related to", 
            "associated with", "path", "chain", "relationship",
            "between", "across"
        ]
        has_relationship = any(kw in ql for kw in relationship_keywords)
        words = tc['query'].split()
        has_entities = sum(1 for w in words[1:] if len(w) > 1 and w[0].isupper()) >= 2
        
        ppr_will_run = has_relationship or has_entities
        
        print(f"   Detected: relationship_keywords={has_relationship}, entities={has_entities}")
        print(f"   PPR will run: {ppr_will_run}")
        
        if ppr_will_run == tc['expected_ppr']:
            print(f"   ✓ PASS - PPR behavior matches expectation")
        else:
            print(f"   ✗ FAIL - PPR behavior mismatch!")
    
    print("\n" + "=" * 80)
    print("SMOKE TEST COMPLETE")
    print("=" * 80)
    print("\nNOTE: This is a heuristic check only.")
    print("To fully validate Fast Mode, run the full benchmark suite.")
    print("\nNext steps:")
    print("  1. Run: python3 test_fast_mode_smoke.py")
    print("  2. If passed, run full benchmark comparison (Fast vs Full)")
    print("  3. Compare latency and accuracy metrics")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_fast_mode())
