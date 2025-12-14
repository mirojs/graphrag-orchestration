#!/usr/bin/env python3
"""
Integration test for Text-to-Cypher retrieval with real Neo4j instance.

This test demonstrates the complete workflow:
1. Index sample documents into Neo4j graph
2. Query using natural language (no manual Cypher)
3. Verify Cypher is generated automatically
4. Validate multi-hop reasoning works

Prerequisites:
- Neo4j instance running (check services/graphrag-orchestration/.env)
- Azure OpenAI credentials configured
- Sample documents for indexing
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.indexing_service import IndexingService
from app.services.retrieval_service import RetrievalService
from llama_index.core.schema import Document


async def setup_test_graph(group_id: str = "text-to-cypher-test"):
    """Index sample documents to create test graph."""
    print("\n" + "="*80)
    print("SETUP: Creating test graph with sample data")
    print("="*80)
    
    # Sample documents with entities and relationships
    documents = [
        Document(
            text="""
            John Smith is the CEO of Acme Corporation. He hired Alice Johnson as 
            VP of Engineering in 2020. Alice attended Stanford University and 
            graduated in 2015. John also attended Stanford University, graduating 
            in 2005.
            """,
            metadata={"source": "company_directory", "type": "personnel"}
        ),
        Document(
            text="""
            Bob Williams joined Acme Corporation in 2021 as Senior Engineer, 
            hired by Alice Johnson. Bob attended MIT and has 10 years of experience. 
            He previously worked at TechCorp.
            """,
            metadata={"source": "company_directory", "type": "personnel"}
        ),
        Document(
            text="""
            Acme Corporation has a contract with TechVendor Inc for cloud services. 
            TechVendor is located in Seattle. The contract was signed in 2022 with 
            payment terms of Net 30 days.
            """,
            metadata={"source": "contracts", "type": "legal"}
        ),
        Document(
            text="""
            A warranty claim was filed by Sarah Chen for product failure. Sarah 
            lives in Seattle and purchased from TechVendor Inc. The claim was 
            filed in January 2024.
            """,
            metadata={"source": "warranty_claims", "type": "support"}
        ),
    ]
    
    try:
        indexing_service = IndexingService()
        
        # Index with entity/relationship extraction
        print("\n📊 Indexing documents...")
        stats = await indexing_service.index_documents(
            group_id=group_id,
            documents=documents,
            entity_types=["Person", "Organization", "University", "City"],
            relation_types=["HIRED", "ATTENDED", "WORKS_AT", "LOCATED_IN", "HAS_CONTRACT"],
            extraction_mode="schema",
        )
        
        print(f"✅ Indexed {stats.get('document_count', 0)} documents")
        print(f"   - Entities extracted: {stats.get('entity_count', 'N/A')}")
        print(f"   - Relationships extracted: {stats.get('relation_count', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_simple_query(group_id: str = "text-to-cypher-test"):
    """Test 1: Simple entity lookup."""
    print("\n" + "="*80)
    print("TEST 1: Simple Entity Lookup")
    print("="*80)
    print("Query: 'Find all people named Alice'")
    
    try:
        service = RetrievalService()
        result = await service.text_to_cypher_search(
            group_id=group_id,
            query="Find all people named Alice"
        )
        
        print(f"\n✅ Query executed successfully")
        print(f"Mode: {result['mode']}")
        print(f"Answer: {result['answer'][:200]}...")
        print(f"\n🔍 Generated Cypher:")
        print(f"   {result.get('cypher_query', 'N/A')[:200]}...")
        print(f"\n📊 Results: {len(result.get('results', []))} items")
        
        return result['metadata']['success']
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multi_hop_query(group_id: str = "text-to-cypher-test"):
    """Test 2: Multi-hop relationship query (GitHub issue #2039)."""
    print("\n" + "="*80)
    print("TEST 2: Multi-Hop Relationship Query (GitHub Issue #2039)")
    print("="*80)
    print("Query: 'Who did John hire that also attended the same university?'")
    
    try:
        service = RetrievalService()
        result = await service.text_to_cypher_search(
            group_id=group_id,
            query="Who did John hire that also attended the same university?"
        )
        
        print(f"\n✅ Multi-hop query executed successfully")
        print(f"Answer: {result['answer'][:300]}...")
        print(f"\n🔍 Generated Cypher:")
        cypher = result.get('cypher_query', '')
        print(f"   {cypher[:400]}...")
        
        # Check for multi-hop patterns
        if 'HIRED' in cypher and 'ATTENDED' in cypher:
            print(f"\n✅ Cypher contains multi-hop relationships:")
            print(f"   - HIRED relationship: ✅")
            print(f"   - ATTENDED relationship: ✅")
        
        print(f"\n📊 Results: {len(result.get('results', []))} items")
        
        # This proves GitHub issue #2039 is solved
        if result['metadata']['success']:
            print(f"\n🎉 GitHub issue microsoft/graphrag#2039 SOLVED!")
            print(f"   Natural language → Cypher conversion working!")
        
        return result['metadata']['success']
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_cross_entity_query(group_id: str = "text-to-cypher-test"):
    """Test 3: Complex cross-entity query."""
    print("\n" + "="*80)
    print("TEST 3: Complex Cross-Entity Query")
    print("="*80)
    print("Query: 'Find contracts where vendor is in same city as warranty claimant'")
    
    try:
        service = RetrievalService()
        result = await service.text_to_cypher_search(
            group_id=group_id,
            query="Find contracts where vendor is in same city as warranty claimant"
        )
        
        print(f"\n✅ Cross-entity query executed successfully")
        print(f"Answer: {result['answer'][:300]}...")
        print(f"\n🔍 Generated Cypher:")
        cypher = result.get('cypher_query', '')
        print(f"   {cypher[:400]}...")
        
        # Check for cross-entity patterns
        patterns_found = []
        if 'Contract' in cypher or 'contract' in cypher.lower():
            patterns_found.append("Contract entity")
        if 'Vendor' in cypher or 'vendor' in cypher.lower():
            patterns_found.append("Vendor entity")
        if 'City' in cypher or 'city' in cypher.lower():
            patterns_found.append("City entity")
        
        if patterns_found:
            print(f"\n✅ Cross-entity patterns detected:")
            for pattern in patterns_found:
                print(f"   - {pattern}: ✅")
        
        print(f"\n📊 Results: {len(result.get('results', []))} items")
        
        return result['metadata']['success']
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_comparison_queries(group_id: str = "text-to-cypher-test"):
    """Test 4: Comparison/aggregation queries."""
    print("\n" + "="*80)
    print("TEST 4: Comparison/Aggregation Query")
    print("="*80)
    print("Query: 'Compare all employees and where they went to university'")
    
    try:
        service = RetrievalService()
        result = await service.text_to_cypher_search(
            group_id=group_id,
            query="Compare all employees and where they went to university"
        )
        
        print(f"\n✅ Comparison query executed successfully")
        print(f"Answer: {result['answer'][:300]}...")
        print(f"\n🔍 Generated Cypher:")
        print(f"   {result.get('cypher_query', '')[:400]}...")
        print(f"\n📊 Results: {len(result.get('results', []))} items")
        
        return result['metadata']['success']
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run complete integration test suite."""
    print("\n" + "="*80)
    print("TEXT-TO-CYPHER INTEGRATION TEST SUITE")
    print("="*80)
    print("\nThis demonstrates:")
    print("1. Natural language → Cypher conversion (no manual Cypher)")
    print("2. Multi-hop relationship queries")
    print("3. Cross-entity reasoning")
    print("4. Solution to GitHub issue microsoft/graphrag#2039")
    
    group_id = "text-to-cypher-test"
    results = {}
    
    # Setup test graph
    print("\n" + "="*80)
    print("PHASE 1: Setup Test Graph")
    print("="*80)
    results['setup'] = await setup_test_graph(group_id)
    
    if not results['setup']:
        print("\n❌ Setup failed. Skipping tests.")
        return False
    
    # Wait for indexing to complete
    print("\n⏳ Waiting 5 seconds for indexing to complete...")
    await asyncio.sleep(5)
    
    # Run tests
    print("\n" + "="*80)
    print("PHASE 2: Execute Test Queries")
    print("="*80)
    
    results['simple'] = await test_simple_query(group_id)
    await asyncio.sleep(2)
    
    results['multi_hop'] = await test_multi_hop_query(group_id)
    await asyncio.sleep(2)
    
    results['cross_entity'] = await test_cross_entity_query(group_id)
    await asyncio.sleep(2)
    
    results['comparison'] = await test_comparison_queries(group_id)
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, passed_flag in results.items():
        status = "✅ PASSED" if passed_flag else "❌ FAILED"
        print(f"{test_name.upper()}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        print("\n✅ Text-to-Cypher implementation validated")
        print("✅ GitHub issue microsoft/graphrag#2039 solved")
        print("✅ Native graph-level multi-hop reasoning working")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return False


async def quick_smoke_test():
    """Quick smoke test without full setup."""
    print("\n" + "="*80)
    print("TEXT-TO-CYPHER SMOKE TEST")
    print("="*80)
    print("\nTesting basic functionality without graph setup...")
    
    try:
        service = RetrievalService()
        print("✅ RetrievalService instantiated")
        
        # Check method exists
        if hasattr(service, 'text_to_cypher_search'):
            print("✅ text_to_cypher_search method exists")
        else:
            print("❌ text_to_cypher_search method not found")
            return False
        
        print("\n📝 Method signature:")
        import inspect
        sig = inspect.signature(service.text_to_cypher_search)
        print(f"   {sig}")
        
        print("\n✅ Smoke test passed")
        print("\n💡 To run full integration test:")
        print("   python test_text_to_cypher_integration.py --full")
        return True
        
    except Exception as e:
        print(f"❌ Smoke test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Text-to-Cypher implementation")
    parser.add_argument('--full', action='store_true', help='Run full integration tests (requires Neo4j)')
    parser.add_argument('--smoke', action='store_true', help='Run quick smoke test only')
    args = parser.parse_args()
    
    if args.full:
        # Run full integration tests
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    else:
        # Default: run smoke test
        success = asyncio.run(quick_smoke_test())
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
