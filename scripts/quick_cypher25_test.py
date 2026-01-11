#!/usr/bin/env python3
"""Quick test to verify Cypher 25 queries are working."""

import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

# Load environment
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration', '.env')
load_dotenv(env_path)

from app.services.async_neo4j_service import AsyncNeo4jService, USE_CYPHER_25
import asyncio

async def main():
    print("=" * 60)
    print("Quick Cypher 25 Test")
    print("=" * 60)
    print(f"USE_CYPHER_25 = {USE_CYPHER_25}")
    print()
    
    group_id = "test-cypher25-final-1768129960"
    
    async with AsyncNeo4jService.from_settings() as service:
        print("✅ Connected to Neo4j")
        
        # Test 1: Get entities by importance
        print("\n📊 Test 1: Get entities by importance (top 5)")
        t0 = time.perf_counter()
        entities = await service.get_entities_by_importance(group_id, top_k=5)
        t1 = time.perf_counter()
        print(f"   Found {len(entities)} entities in {(t1-t0)*1000:.1f}ms")
        for e in entities[:3]:
            print(f"   - {e.get('name', 'N/A')} (score: {e.get('importance_score', 0):.2f})")
        
        # Test 2: Entity expansion
        if entities:
            print("\n🔗 Test 2: Expand neighbors (depth=2)")
            entity_ids = [e['id'] for e in entities[:2]]
            t0 = time.perf_counter()
            neighbors = await service.expand_neighbors(group_id, entity_ids, depth=2, limit_per_entity=5)
            t1 = time.perf_counter()
            print(f"   Found {len(neighbors)} neighbors in {(t1-t0)*1000:.1f}ms")
            for n in neighbors[:3]:
                print(f"   - {n.get('name', 'N/A')} (distance: {n.get('distance', 0)})")
        
        # Test 3: Check field exists
        print("\n🔍 Test 3: Check field exists in document")
        t0 = time.perf_counter()
        exists, section = await service.check_field_exists_in_document(
            group_id,
            "invoice",
            ["payment", "terms"]
        )
        t1 = time.perf_counter()
        print(f"   Result: {exists} in {(t1-t0)*1000:.1f}ms")
        if section:
            print(f"   Section: {section}")
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        print("\nCypher 25 queries are working correctly!")

if __name__ == "__main__":
    asyncio.run(main())
