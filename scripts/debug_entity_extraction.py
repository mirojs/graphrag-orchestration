#!/usr/bin/env python3
"""
Debug entity extraction to understand why Route 4 gets no seeds.
"""

import asyncio
import json
import httpx
from datetime import datetime

GROUP_ID = "test-5pdfs-v2-enhanced-ex"
API_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Simple entity query
ENTITY_QUERY = "What are the payment terms in the Contoso invoice?"


async def main():
    print("="*80)
    print("🔍 Testing Entity-Based Query")
    print("="*80)
    
    async with httpx.AsyncClient(timeout=180) as client:
        # Test with Route 2 (entity-focused)
        print("\n--- Route 2 (Local Search - Entity-focused) ---")
        response = await client.post(
            f"{API_URL}/hybrid/query",
            headers={"X-Group-ID": GROUP_ID},
            json={
                "query": ENTITY_QUERY,
                "response_type": "summary",
                "force_route": "local_search"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Status: {response.status_code}")
            print(f"📝 Response: {result.get('response', '')[:200]}...")
            print(f"📚 Citations: {len(result.get('citations', []))}")
            meta = result.get('metadata', {})
            print(f"🌱 Seed Entities: {meta.get('seed_entities', 'N/A')}")
            print(f"📊 text_chunks_used: {meta.get('text_chunks_used', 'N/A')}")
        
        # Test with Route 4 (DRIFT)
        print("\n--- Route 4 (DRIFT Multi-hop) ---")
        response = await client.post(
            f"{API_URL}/hybrid/query",
            headers={"X-Group-ID": GROUP_ID},
            json={
                "query": ENTITY_QUERY,
                "response_type": "summary",
                "force_route": "drift_multi_hop"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Status: {response.status_code}")
            print(f"📝 Response: {result.get('response', '')[:200]}...")
            print(f"📚 Citations: {len(result.get('citations', []))}")
            meta = result.get('metadata', {})
            print(f"🌱 all_seeds_discovered: {meta.get('all_seeds_discovered', [])}")
            print(f"📊 text_chunks_used: {meta.get('text_chunks_used', 'N/A')}")
            print(f"📊 num_evidence_nodes: {meta.get('num_evidence_nodes', 'N/A')}")
            
            # Save result
            with open("debug_route4_entity.json", "w") as f:
                json.dump(result, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
