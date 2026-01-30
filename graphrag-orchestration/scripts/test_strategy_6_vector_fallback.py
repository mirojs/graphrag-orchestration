#!/usr/bin/env python3
"""
Test Strategy 6 (Vector Fallback) in Seed Resolution

This script tests the full flow:
1. Strategies 1-5 resolve some seeds (lexical)
2. Unmatched seeds go to Strategy 6 (vector similarity)

Expected: Abstract terms like "amounts", "inconsistencies" should now
find semantically similar graph entities via vector search.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv(project_root / ".env")


async def test_with_embedding():
    """Test full Strategy 6 flow with a mock embedding model."""
    from app.services.async_neo4j_service import AsyncNeo4jService
    
    print("=" * 60)
    print("Strategy 6 Vector Fallback Test")
    print("=" * 60)
    
    # Initialize service
    service = AsyncNeo4jService.from_settings()
    await service.connect()
    
    group_id = "test-5pdfs-v2-enhanced-ex"
    
    # Test seeds - some will match lexically, some won't
    test_seeds = [
        "Invoice",           # Should match via Strategy 1 (exact)
        "payment terms",     # Should match via Strategy 2 (alias) or 4-5
        "amounts",           # Abstract - needs Strategy 6
        "inconsistencies",   # Abstract - needs Strategy 6
        "elevator equipment", # Domain-specific - needs Strategy 6
    ]
    
    print(f"\nTest seeds: {test_seeds}")
    print(f"Group ID: {group_id}")
    
    # Step 1: Run Strategies 1-5 with return_unmatched=True
    print("\n" + "-" * 40)
    print("Step 1: Strategies 1-5 (Lexical)")
    print("-" * 40)
    
    result = await service.get_entities_by_names(
        group_id=group_id,
        entity_names=test_seeds,
        return_unmatched=True,
    )
    
    if isinstance(result, tuple):
        records, unmatched = result
    else:
        records = result
        unmatched = []
    
    print(f"\nMatched by lexical strategies: {len(records)}")
    for r in records:
        print(f"  ✅ '{r['matched_seed']}' → {r['name']} (via {r.get('match_strategy', 'unknown')})")
    
    print(f"\nUnmatched (need Strategy 6): {len(unmatched)}")
    for u in unmatched:
        print(f"  ❌ '{u}'")
    
    # Step 2: Test Strategy 6 for unmatched seeds
    if unmatched:
        print("\n" + "-" * 40)
        print("Step 2: Strategy 6 (Vector Similarity)")
        print("-" * 40)
        
        # Use OpenAI embeddings (text-embedding-3-large, 3072 dims)
        # This matches the entity_embedding index in Neo4j
        try:
            import openai
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                print("\nUsing OpenAI text-embedding-3-large (3072 dims)...")
                client = openai.OpenAI(api_key=openai_key)
                
                for seed in unmatched[:3]:  # Limit to avoid rate limits
                    print(f"\n  Testing: '{seed}'")
                    
                    # Get embedding for the seed
                    response = client.embeddings.create(
                        input=seed,
                        model="text-embedding-3-large"
                    )
                    embedding = response.data[0].embedding
                    print(f"    Embedding dim: {len(embedding)}")
                    
                    # Search for similar entities
                    vector_results = await service.get_entities_by_vector_similarity(
                        group_id=group_id,
                        seed_text=seed,
                        seed_embedding=embedding,
                        top_k=3,
                    )
                    
                    if vector_results:
                        print(f"    Found {len(vector_results)} matches:")
                        for vr in vector_results:
                            sim = vr.get('similarity', 0)
                            print(f"      → {vr['name']} (similarity: {sim:.3f})")
                    else:
                        print(f"    No vector matches found")
            else:
                print("\n⚠️ OPENAI_API_KEY not set - skipping vector test")
                print("Set OPENAI_API_KEY to test Strategy 6 with real embeddings")
                
        except ImportError:
            print("\n⚠️ openai not installed - skipping vector test")
            print("Run: pip install openai")
    
    # Cleanup
    await service.close()
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
    print("""
Summary:
- Strategies 1-5: Lexical matching (graph-grounded, deterministic)
- Strategy 6: Vector similarity (semantic fallback for vocabulary mismatch)

The flow is:
1. LLM extracts entity names from query (unavoidable)
2. Strategies 1-5 validate against graph (deterministic)
3. Strategy 6 catches vocabulary mismatches (e.g., "elevator" → "Vertical Lift")
4. ALL resolved seeds feed into PPR traversal (deterministic)

This maintains "Graph as GPS" while handling semantic gaps.
""")


if __name__ == "__main__":
    asyncio.run(test_with_embedding())
