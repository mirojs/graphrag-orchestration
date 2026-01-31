#!/usr/bin/env python3
"""
Test script to verify the enhanced 5-strategy seed resolution in AsyncNeo4jService.

Tests:
1. Exact name match
2. Alias match  
3. KVP key match
4. Substring match
5. Token overlap

Usage:
    python scripts/test_async_neo4j_seed_resolution.py --group-id test-5pdfs-v2-enhanced-ex
"""

import asyncio
import os
import sys
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

from dotenv import load_dotenv

# Load .env from graphrag-orchestration subdirectory
env_path = os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration', '.env')
load_dotenv(env_path)


async def test_seed_resolution(group_id: str):
    """Test all seed resolution strategies."""
    
    from src.worker.services.async_neo4j_service import AsyncNeo4jService
    
    # Initialize service
    service = AsyncNeo4jService.from_settings()
    await service.connect()
    
    print(f"\n{'='*60}")
    print(f"Testing AsyncNeo4jService Seed Resolution")
    print(f"Group ID: {group_id}")
    print(f"{'='*60}\n")
    
    # Test cases for different strategies
    test_cases = [
        {
            "name": "Strategy 1 - Exact Name",
            "seeds": ["Builders Limited Warranty with Arbitration"],
            "expected": "Should match entity by exact name",
        },
        {
            "name": "Strategy 2 - Alias Match",
            "seeds": ["invoice", "warranty", "contract"],
            "expected": "Should match via aliases (common generic terms)",
        },
        {
            "name": "Strategy 3 - KVP Key Match", 
            "seeds": ["representative", "address"],
            "expected": "Should match KeyValuePair nodes by key",
        },
        {
            "name": "Strategy 4 - Substring Match",
            "seeds": ["Savaria", "Contoso", "Fabrik"],
            "expected": "Should match entities containing these substrings",
        },
        {
            "name": "Strategy 5 - Token Overlap",
            "seeds": ["vertical platform", "limited warranty"],
            "expected": "Should match entities sharing word tokens",
        },
        {
            "name": "Combined - Invoice Consistency Query",
            "seeds": ["Invoice", "invoice", "contract", "payment", "inconsistencies"],
            "expected": "Mixed strategies - typical LLM extraction result",
        },
    ]
    
    try:
        for tc in test_cases:
            print(f"\n📋 {tc['name']}")
            print(f"   Seeds: {tc['seeds']}")
            print(f"   Expected: {tc['expected']}")
            
            records = await service.get_entities_by_names(
                group_id=group_id,
                entity_names=tc['seeds'],
                use_extended_matching=True,
            )
            
            if records:
                print(f"   ✅ Found {len(records)} entities:")
                # Group by strategy
                by_strategy: Dict[str, List[str]] = {}
                for r in records:
                    strat = r.get("match_strategy", "unknown")
                    if strat not in by_strategy:
                        by_strategy[strat] = []
                    by_strategy[strat].append(r["name"][:40])
                
                for strat, names in by_strategy.items():
                    print(f"      [{strat}]: {names[:3]}{'...' if len(names) > 3 else ''}")
            else:
                print(f"   ❌ No entities found!")
        
        # Summary
        print(f"\n{'='*60}")
        print("Summary")
        print(f"{'='*60}")
        
        # Test the full "invoice consistency" query flow
        print("\n🧪 Full Invoice Consistency Test:")
        typical_llm_seeds = ["Invoice", "contract", "payment", "terms", "amounts", "inconsistencies"]
        print(f"   LLM-extracted seeds: {typical_llm_seeds}")
        
        records = await service.get_entities_by_names(
            group_id=group_id,
            entity_names=typical_llm_seeds,
            use_extended_matching=True,
        )
        
        print(f"   Resolved to {len(records)} entities")
        
        matched_seeds = {r.get("matched_seed", "").lower() for r in records}
        unmatched = [s for s in typical_llm_seeds if s.lower() not in matched_seeds]
        
        if unmatched:
            print(f"   ⚠️  Unmatched seeds (need vector fallback): {unmatched}")
        else:
            print(f"   ✅ All seeds resolved!")
        
        # Show unique entities
        unique_entities = list({r["name"] for r in records})
        print(f"   Unique entities: {unique_entities[:5]}{'...' if len(unique_entities) > 5 else ''}")
        
    finally:
        await service.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test seed resolution strategies")
    parser.add_argument("--group-id", default="test-5pdfs-v2-enhanced-ex",
                       help="Group ID to test (default: test-5pdfs-v2-enhanced-ex)")
    args = parser.parse_args()
    
    asyncio.run(test_seed_resolution(args.group_id))


if __name__ == "__main__":
    main()
