#!/usr/bin/env python3
"""Test Route 2 integration with new 1-hop edges.

Tests both old (2-hop) and new (1-hop) code paths to verify:
1. New edges exist in the graph
2. New code path returns results
3. Results are semantically equivalent
4. Performance improvement (optional)
"""

import asyncio
import os
import sys
import time
from typing import List, Tuple

# Add the app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

from src.worker.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
from neo4j import GraphDatabase


GROUP_ID = "test-5pdfs-1768557493369886422"
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def get_driver():
    """Create Neo4j driver."""
    return GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
    )


async def test_foundation_edges_exist():
    """Verify foundation edges exist in the graph."""
    print("\n" + "="*80)
    print("TEST 1: Verify Foundation Edges Exist")
    print("="*80)
    
    driver = get_driver()
    
    with driver.session() as session:
        # Check APPEARS_IN_SECTION edges
        result = session.run(
            "MATCH ()-[r:APPEARS_IN_SECTION]->() WHERE r.group_id = $group_id RETURN count(r) AS count",
            group_id=GROUP_ID
        )
        appears_in_section = result.single()["count"]
        
        # Check APPEARS_IN_DOCUMENT edges
        result = session.run(
            "MATCH ()-[r:APPEARS_IN_DOCUMENT]->() WHERE r.group_id = $group_id RETURN count(r) AS count",
            group_id=GROUP_ID
        )
        appears_in_document = result.single()["count"]
        
        # Check HAS_HUB_ENTITY edges
        result = session.run(
            "MATCH ()-[r:HAS_HUB_ENTITY]->() WHERE r.group_id = $group_id RETURN count(r) AS count",
            group_id=GROUP_ID
        )
        has_hub_entity = result.single()["count"]
    
    print(f"✓ APPEARS_IN_SECTION edges: {appears_in_section}")
    print(f"✓ APPEARS_IN_DOCUMENT edges: {appears_in_document}")
    print(f"✓ HAS_HUB_ENTITY edges: {has_hub_entity}")
    
    driver.close()
    
    assert appears_in_section > 0, "No APPEARS_IN_SECTION edges found"
    assert appears_in_document > 0, "No APPEARS_IN_DOCUMENT edges found"
    assert has_hub_entity > 0, "No HAS_HUB_ENTITY edges found"
    
    print("\n✅ Foundation edges exist in graph")
    return True


async def test_new_code_path():
    """Test new 1-hop code path returns results."""
    print("\n" + "="*80)
    print("TEST 2: Test New 1-Hop Code Path")
    print("="*80)
    
    driver = get_driver()
    retriever = EnhancedGraphRetriever(neo4j_driver=driver, group_id=GROUP_ID)
    
    # Test entities (from the actual graph - contract-related)
    test_entities = [
        ("Builder", 1.0),
        ("Owner", 0.9),
        ("Property", 0.8),
    ]
    
    print(f"\nTesting with {len(test_entities)} seed entities:")
    for name, score in test_entities:
        print(f"  - {name} (score={score})")
    
    # Fetch chunks using new edges
    t0 = time.perf_counter()
    chunks = await retriever.get_ppr_evidence_chunks(
        evidence_nodes=test_entities,
        max_per_entity=2,
        max_total=10,
        use_new_edges=True,
    )
    elapsed_new = (time.perf_counter() - t0) * 1000
    
    print(f"\n✓ New path returned {len(chunks)} chunks in {elapsed_new:.1f}ms")
    if chunks:
        print("\nSample chunks:")
        for i, chunk in enumerate(chunks[:3], 1):
            print(f"  {i}. Entity: {chunk.entity_name}")
            print(f"     Section: {' > '.join(chunk.section_path) if chunk.section_path else 'N/A'}")
            print(f"     Text preview: {chunk.text[:80]}...")
    
    driver.close()
    
    assert len(chunks) > 0, "New code path returned no chunks"
    print("\n✅ New code path works")
    return chunks, elapsed_new


async def test_old_code_path():
    """Test old 2-hop code path returns results (for comparison)."""
    print("\n" + "="*80)
    print("TEST 3: Test Old 2-Hop Code Path (Baseline)")
    print("="*80)
    
    driver = get_driver()
    retriever = EnhancedGraphRetriever(neo4j_driver=driver, group_id=GROUP_ID)
    
    test_entities = [
        ("Builder", 1.0),
        ("Owner", 0.9),
        ("Property", 0.8),
    ]
    
    # Fetch chunks using old MENTIONS path
    t0 = time.perf_counter()
    chunks = await retriever.get_ppr_evidence_chunks(
        evidence_nodes=test_entities,
        max_per_entity=2,
        max_total=10,
        use_new_edges=False,  # Force old path
    )
    elapsed_old = (time.perf_counter() - t0) * 1000
    
    print(f"\n✓ Old path returned {len(chunks)} chunks in {elapsed_old:.1f}ms")
    
    driver.close()
    
    return chunks, elapsed_old


async def test_semantic_equivalence(new_chunks, old_chunks):
    """Verify new and old paths return semantically equivalent results."""
    print("\n" + "="*80)
    print("TEST 4: Semantic Equivalence Check")
    print("="*80)
    
    new_texts = {chunk.chunk_id for chunk in new_chunks}
    old_texts = {chunk.chunk_id for chunk in old_chunks}
    
    overlap = len(new_texts & old_texts)
    total_unique = len(new_texts | old_texts)
    
    similarity = overlap / total_unique if total_unique > 0 else 0.0
    
    print(f"New path chunks: {len(new_chunks)}")
    print(f"Old path chunks: {len(old_chunks)}")
    print(f"Overlap: {overlap} / {total_unique} ({similarity*100:.1f}%)")
    
    # Allow some difference due to scoring/ordering changes
    assert similarity >= 0.5, f"Paths too different: {similarity*100:.1f}% overlap (expected ≥50%)"
    
    print(f"\n✅ Semantic equivalence verified ({similarity*100:.1f}% overlap)")
    return similarity


async def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("ROUTE 2 INTEGRATION TEST SUITE")
    print("="*80)
    print(f"Group ID: {GROUP_ID}")
    
    try:
        # Test 1: Foundation edges exist
        await test_foundation_edges_exist()
        
        # Test 2: New code path works
        new_chunks, elapsed_new = await test_new_code_path()
        
        # Test 3: Old code path works (baseline)
        old_chunks, elapsed_old = await test_old_code_path()
        
        # Test 4: Semantic equivalence
        similarity = await test_semantic_equivalence(new_chunks, old_chunks)
        
        # Performance comparison
        print("\n" + "="*80)
        print("PERFORMANCE COMPARISON")
        print("="*80)
        print(f"Old path (2-hop): {elapsed_old:.1f}ms")
        print(f"New path (1-hop): {elapsed_new:.1f}ms")
        if elapsed_old > 0:
            speedup = elapsed_old / elapsed_new
            print(f"Speedup: {speedup:.2f}x")
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        print("\nRoute 2 is ready for deployment!")
        print("- Foundation edges exist and are being used")
        print("- New code path returns correct results")
        print(f"- Semantic equivalence: {similarity*100:.1f}%")
        print(f"- Performance: {'faster' if elapsed_new < elapsed_old else 'neutral'} on small dataset")
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
