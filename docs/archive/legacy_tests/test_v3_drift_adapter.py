"""
Test V3 DRIFT Adapter with MS GraphRAG

This test verifies that the DRIFT adapter can:
1. Load data from Neo4j
2. Convert to MS GraphRAG data models
3. Execute DRIFT search
"""

import asyncio
import os
import sys

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.v3.services.drift_adapter import DRIFTAdapter, Neo4jDRIFTVectorStore
from app.core.config import settings


async def test_drift_imports():
    """Test that all MS GraphRAG DRIFT components can be imported."""
    print("=" * 60)
    print("TEST 1: MS GraphRAG DRIFT Imports")
    print("=" * 60)
    
    try:
        from graphrag.query.structured_search.drift_search.search import DRIFTSearch
        from graphrag.query.structured_search.drift_search.drift_context import DRIFTSearchContextBuilder
        from graphrag.data_model.entity import Entity
        from graphrag.data_model.relationship import Relationship
        from graphrag.data_model.text_unit import TextUnit
        from graphrag.data_model.community_report import CommunityReport
        from graphrag.vector_stores.base import BaseVectorStore
        
        print("✅ All MS GraphRAG DRIFT imports successful")
        print(f"   - DRIFTSearch: {DRIFTSearch}")
        print(f"   - DRIFTSearchContextBuilder: {DRIFTSearchContextBuilder}")
        print(f"   - Entity: {Entity}")
        print(f"   - Relationship: {Relationship}")
        print(f"   - TextUnit: {TextUnit}")
        print(f"   - CommunityReport: {CommunityReport}")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False


async def test_neo4j_connection():
    """Test Neo4j connectivity."""
    print("\n" + "=" * 60)
    print("TEST 2: Neo4j Connection")
    print("=" * 60)
    
    try:
        import neo4j
        
        uri = settings.NEO4J_URI or ""
        username = settings.NEO4J_USERNAME or ""
        password = settings.NEO4J_PASSWORD or ""
        
        print(f"   Connecting to: {uri}")
        
        driver = neo4j.GraphDatabase.driver(uri, auth=(username, password))
        driver.verify_connectivity()
        
        # Test query
        records, _, _ = driver.execute_query("RETURN 1 AS test")
        assert records[0]["test"] == 1
        
        print("✅ Neo4j connection successful")
        driver.close()
        return True
    except Exception as e:
        print(f"❌ Neo4j connection failed: {e}")
        return False


async def test_data_model_conversion():
    """Test converting Neo4j data to MS GraphRAG data models."""
    print("\n" + "=" * 60)
    print("TEST 3: Data Model Conversion")
    print("=" * 60)
    
    try:
        from graphrag.data_model.entity import Entity
        from graphrag.data_model.relationship import Relationship
        from graphrag.data_model.text_unit import TextUnit
        from graphrag.data_model.community_report import CommunityReport
        
        # Test Entity creation
        entity = Entity(
            id="entity-1",
            short_id="e1",
            title="Test Company",
            type="ORGANIZATION",
            description="A test company for validation",
            text_unit_ids=["chunk-1", "chunk-2"],
        )
        print(f"✅ Entity created: {entity.title} ({entity.type})")
        
        # Test Relationship creation
        relationship = Relationship(
            id="rel-1",
            short_id="r1",
            source="entity-1",
            target="entity-2",
            weight=0.9,
            description="Test relationship",
        )
        print(f"✅ Relationship created: {relationship.source} -> {relationship.target}")
        
        # Test TextUnit creation
        text_unit = TextUnit(
            id="chunk-1",
            short_id="c1",
            text="This is a test text chunk.",
            entity_ids=["entity-1"],
            n_tokens=10,
        )
        print(f"✅ TextUnit created: {text_unit.id} ({text_unit.n_tokens} tokens)")
        
        # Test CommunityReport creation
        community = CommunityReport(
            id="community-1",
            short_id="cm1",
            title="Test Community",
            community_id="community-1",
            summary="A test community summary",
            full_content="Full community content here",
            rank=0.8,
        )
        print(f"✅ CommunityReport created: {community.title}")
        
        return True
    except Exception as e:
        print(f"❌ Data model conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_drift_adapter_initialization():
    """Test DRIFT adapter initialization."""
    print("\n" + "=" * 60)
    print("TEST 4: DRIFT Adapter Initialization")
    print("=" * 60)
    
    try:
        import neo4j
        
        # Create Neo4j driver
        driver = neo4j.GraphDatabase.driver(
            settings.NEO4J_URI or "",
            auth=(settings.NEO4J_USERNAME or "", settings.NEO4J_PASSWORD or ""),
        )
        
        # Create adapter (without LLM/embedder for now)
        adapter = DRIFTAdapter(
            neo4j_driver=driver,
            llm=None,  # Will be set later
            embedder=None,  # Will be set later
        )
        
        print("✅ DRIFT adapter initialized")
        print(f"   - Driver: {adapter.driver}")
        print(f"   - Cache cleared: {len(adapter._entity_cache) == 0}")
        
        driver.close()
        return True
    except Exception as e:
        print(f"❌ DRIFT adapter initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_neo4j_data_loading():
    """Test loading data from Neo4j."""
    print("\n" + "=" * 60)
    print("TEST 5: Neo4j Data Loading")
    print("=" * 60)
    
    try:
        import neo4j
        
        driver = neo4j.GraphDatabase.driver(
            settings.NEO4J_URI or "",
            auth=(settings.NEO4J_USERNAME or "", settings.NEO4J_PASSWORD or ""),
        )
        
        adapter = DRIFTAdapter(
            neo4j_driver=driver,
            llm=None,
            embedder=None,
        )
        
        # Try to load data for a test group
        test_group = "test-group-v3"
        
        entities_df = adapter.load_entities(test_group, use_cache=False)
        communities_df = adapter.load_communities(test_group, use_cache=False)
        relationships_df = adapter.load_relationships(test_group, use_cache=False)
        text_chunks_df = adapter.load_text_chunks(test_group)
        
        print(f"✅ Data loaded from Neo4j:")
        print(f"   - Entities: {len(entities_df)} rows")
        print(f"   - Communities: {len(communities_df)} rows")
        print(f"   - Relationships: {len(relationships_df)} rows")
        print(f"   - Text chunks: {len(text_chunks_df)} rows")
        
        if len(entities_df) > 0:
            print(f"   - Entity columns: {list(entities_df.columns)}")
        
        driver.close()
        return True
    except Exception as e:
        print(f"❌ Neo4j data loading failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_graphrag_model_creation():
    """Test creating MS GraphRAG models from Neo4j data."""
    print("\n" + "=" * 60)
    print("TEST 6: MS GraphRAG Model Creation from Neo4j Data")
    print("=" * 60)
    
    try:
        import neo4j
        
        driver = neo4j.GraphDatabase.driver(
            settings.NEO4J_URI or "",
            auth=(settings.NEO4J_USERNAME or "", settings.NEO4J_PASSWORD or ""),
        )
        
        adapter = DRIFTAdapter(
            neo4j_driver=driver,
            llm=None,
            embedder=None,
        )
        
        test_group = "test-group-v3"
        
        # Load and convert entities
        entities = adapter.load_entities_as_graphrag_models(test_group)
        print(f"✅ Loaded {len(entities)} entities as GraphRAG Entity models")
        
        # Load and convert relationships
        relationships = adapter.load_relationships_as_graphrag_models(test_group)
        print(f"✅ Loaded {len(relationships)} relationships as GraphRAG Relationship models")
        
        # Load and convert text units
        text_units = adapter.load_text_units_as_graphrag_models(test_group)
        print(f"✅ Loaded {len(text_units)} text units as GraphRAG TextUnit models")
        
        # Load and convert communities
        communities = adapter.load_communities_as_graphrag_models(test_group)
        print(f"✅ Loaded {len(communities)} communities as GraphRAG CommunityReport models")
        
        driver.close()
        return True
    except Exception as e:
        print(f"❌ GraphRAG model creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_vector_store_adapter():
    """Test Neo4j vector store adapter for DRIFT."""
    print("\n" + "=" * 60)
    print("TEST 7: Neo4j Vector Store Adapter")
    print("=" * 60)
    
    try:
        import neo4j
        
        driver = neo4j.GraphDatabase.driver(
            settings.NEO4J_URI or "",
            auth=(settings.NEO4J_USERNAME or "", settings.NEO4J_PASSWORD or ""),
        )
        
        test_group = "test-group-v3"
        
        # Create vector store adapter
        vector_store = Neo4jDRIFTVectorStore(
            driver=driver,
            group_id=test_group,
            index_name="entity_embedding",
        )
        
        print(f"✅ Neo4j vector store adapter created")
        print(f"   - Group ID: {vector_store.group_id}")
        print(f"   - Index name: {vector_store.index_name}")
        
        driver.close()
        return True
    except Exception as e:
        print(f"❌ Vector store adapter failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("V3 DRIFT ADAPTER TEST SUITE")
    print("=" * 60)
    
    results = []
    
    results.append(("MS GraphRAG Imports", await test_drift_imports()))
    results.append(("Neo4j Connection", await test_neo4j_connection()))
    results.append(("Data Model Conversion", await test_data_model_conversion()))
    results.append(("DRIFT Adapter Init", await test_drift_adapter_initialization()))
    results.append(("Neo4j Data Loading", await test_neo4j_data_loading()))
    results.append(("GraphRAG Model Creation", await test_graphrag_model_creation()))
    results.append(("Vector Store Adapter", await test_vector_store_adapter()))
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
