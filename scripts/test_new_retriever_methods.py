#!/usr/bin/env python3
"""
Phase 1 Week 2: Test new 1-hop retrieval methods.

This script tests the new methods added to EnhancedGraphRetriever:
- get_sections_for_entities() - 1-hop via APPEARS_IN_SECTION
- get_documents_for_entities() - 1-hop via APPEARS_IN_DOCUMENT
- get_hub_entities_for_sections() - via HAS_HUB_ENTITY
- get_entity_cross_doc_summary() - O(1) cross-doc stats

Usage:
    python scripts/test_new_retriever_methods.py
"""

import asyncio
import os
import sys
import time

# Add the app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

from neo4j import GraphDatabase


# Neo4j connection settings
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
GROUP_ID = "test-5pdfs-1768557493369886422"


async def test_get_sections_for_entities():
    """Test get_sections_for_entities with both old and new edges."""
    print("\n" + "="*60)
    print("TEST: get_sections_for_entities")
    print("="*60)
    
    from app.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    retriever = EnhancedGraphRetriever(neo4j_driver=driver, group_id=GROUP_ID)
    
    test_entities = ["Builder", "Buyer/Owner", "Warranty"]
    
    # Test with new 1-hop edges
    print(f"\n📍 Testing with APPEARS_IN_SECTION (1-hop):")
    start = time.time()
    results_new = await retriever.get_sections_for_entities(test_entities, use_new_edges=True)
    time_new = time.time() - start
    print(f"   Time: {time_new*1000:.1f}ms")
    print(f"   Results: {len(results_new)} section-entity pairs")
    for r in results_new[:5]:
        print(f"      {r['entity_name']} → {r['section_title'][:40]}... ({r['mention_count']} mentions)")
    
    # Test with old 2-hop edges
    print(f"\n📍 Testing with 2-hop traversal (fallback):")
    start = time.time()
    results_old = await retriever.get_sections_for_entities(test_entities, use_new_edges=False)
    time_old = time.time() - start
    print(f"   Time: {time_old*1000:.1f}ms")
    print(f"   Results: {len(results_old)} section-entity pairs")
    
    # Compare
    speedup = time_old / time_new if time_new > 0 else 0
    print(f"\n   ⚡ Speedup: {speedup:.1f}x")
    
    driver.close()
    return len(results_new) > 0


async def test_get_documents_for_entities():
    """Test get_documents_for_entities with both old and new edges."""
    print("\n" + "="*60)
    print("TEST: get_documents_for_entities")
    print("="*60)
    
    from app.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    retriever = EnhancedGraphRetriever(neo4j_driver=driver, group_id=GROUP_ID)
    
    test_entities = ["Builder", "Fabrikam Inc.", "Contoso Ltd."]
    
    # Test with new 1-hop edges
    print(f"\n📄 Testing with APPEARS_IN_DOCUMENT (1-hop):")
    start = time.time()
    results_new = await retriever.get_documents_for_entities(test_entities, use_new_edges=True)
    time_new = time.time() - start
    print(f"   Time: {time_new*1000:.1f}ms")
    print(f"   Results: {len(results_new)} document-entity pairs")
    for r in results_new[:5]:
        doc_title = (r['doc_title'] or 'Unknown')[:35]
        print(f"      {r['entity_name']} → {doc_title}... ({r['mention_count']} mentions, {r['section_count']} sections)")
    
    # Test with old 3-hop edges
    print(f"\n📄 Testing with 3-hop traversal (fallback):")
    start = time.time()
    results_old = await retriever.get_documents_for_entities(test_entities, use_new_edges=False)
    time_old = time.time() - start
    print(f"   Time: {time_old*1000:.1f}ms")
    print(f"   Results: {len(results_old)} document-entity pairs")
    
    # Compare
    speedup = time_old / time_new if time_new > 0 else 0
    print(f"\n   ⚡ Speedup: {speedup:.1f}x")
    
    driver.close()
    return len(results_new) > 0


async def test_get_hub_entities_for_sections():
    """Test get_hub_entities_for_sections."""
    print("\n" + "="*60)
    print("TEST: get_hub_entities_for_sections (LazyGraphRAG → HippoRAG bridge)")
    print("="*60)
    
    from app.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    retriever = EnhancedGraphRetriever(neo4j_driver=driver, group_id=GROUP_ID)
    
    # Get sections that HAVE HAS_HUB_ENTITY edges (not random sections)
    with driver.session() as session:
        result = session.run("""
            MATCH (s:Section)-[r:HAS_HUB_ENTITY]->(e:Entity)
            WHERE r.group_id = $group_id
            WITH DISTINCT s
            RETURN s.id AS section_id, s.title AS section_title
            LIMIT 5
        """, group_id=GROUP_ID)
        sections = list(result)
    
    section_ids = [s["section_id"] for s in sections]
    print(f"\n🔗 Testing with {len(section_ids)} sections:")
    for s in sections:
        print(f"      {s['section_title'][:50]}...")
    
    # Test hub entities retrieval
    start = time.time()
    results = await retriever.get_hub_entities_for_sections(section_ids)
    elapsed = time.time() - start
    
    print(f"\n   Time: {elapsed*1000:.1f}ms")
    print(f"   Results: {len(results)} hub entity links")
    
    # Group by section
    by_section = {}
    for r in results:
        sid = r['section_id']
        if sid not in by_section:
            by_section[sid] = []
        by_section[sid].append(r)
    
    for sid, entities in list(by_section.items())[:3]:
        section_title = entities[0]['section_title'][:40] if entities else 'Unknown'
        print(f"\n   Section: {section_title}...")
        for e in entities:
            print(f"      #{e['rank']}: {e['entity_name']} ({e['mention_count']} mentions)")
    
    driver.close()
    return len(results) > 0


async def test_get_entity_cross_doc_summary():
    """Test get_entity_cross_doc_summary."""
    print("\n" + "="*60)
    print("TEST: get_entity_cross_doc_summary (O(1) cross-doc stats)")
    print("="*60)
    
    from app.hybrid.pipeline.enhanced_graph_retriever import EnhancedGraphRetriever
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    retriever = EnhancedGraphRetriever(neo4j_driver=driver, group_id=GROUP_ID)
    
    test_entities = ["Builder", "Warranty", "Fabrikam Inc.", "Customer"]
    
    print(f"\n📊 Getting cross-doc summary for {len(test_entities)} entities:")
    
    start = time.time()
    summary = await retriever.get_entity_cross_doc_summary(test_entities)
    elapsed = time.time() - start
    
    print(f"   Time: {elapsed*1000:.1f}ms")
    
    for entity, stats in summary.items():
        print(f"\n   {entity}:")
        print(f"      Documents: {stats['doc_count']}")
        print(f"      Sections: {stats['section_count']}")
        print(f"      Total mentions: {stats['total_mentions']}")
        if stats['doc_titles']:
            print(f"      Sample docs: {', '.join(stats['doc_titles'][:2])}")
    
    driver.close()
    return len(summary) > 0


async def main():
    if not NEO4J_PASSWORD:
        print("❌ ERROR: NEO4J_PASSWORD environment variable not set")
        return 1
    
    print("🚀 Phase 1 Week 2: Testing New 1-Hop Retrieval Methods")
    print(f"   Group ID: {GROUP_ID}")
    print(f"   Neo4j URI: {NEO4J_URI}")
    
    results = []
    
    results.append(("get_sections_for_entities", await test_get_sections_for_entities()))
    results.append(("get_documents_for_entities", await test_get_documents_for_entities()))
    results.append(("get_hub_entities_for_sections", await test_get_hub_entities_for_sections()))
    results.append(("get_entity_cross_doc_summary", await test_get_entity_cross_doc_summary()))
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {status}: {name}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n✅ All tests passed! New 1-hop methods are working correctly.")
        print("   Next: Run benchmark to measure Route 2 improvement")
    else:
        print("\n❌ Some tests failed. Check the output above.")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
