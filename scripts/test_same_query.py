#!/usr/bin/env python3
"""
Test API with the SAME query that worked yesterday.
"""

import asyncio
import httpx
import json

API_URL = 'https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io'
GROUP_ID = 'test-5pdfs-v2-enhanced-ex'

# SAME query as yesterday's test script
QUERY = 'Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms'

async def test():
    async with httpx.AsyncClient(timeout=300.0) as client:
        print(f"Testing API with query: {QUERY[:60]}...")
        response = await client.post(
            f'{API_URL}/hybrid/query',
            headers={'X-Group-ID': GROUP_ID},
            json={'query': QUERY, 'response_type': 'summary', 'force_route': 'drift_multi_hop'}
        )
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            print(response.text)
            return
            
        data = response.json()
        metadata = data.get('metadata', {})
        
        print(f"\n📊 Results:")
        print(f"  all_seeds: {metadata.get('all_seeds_discovered', [])}")
        print(f"  num_evidence_nodes: {metadata.get('num_evidence_nodes', 0)}")
        print(f"  text_chunks_used: {metadata.get('text_chunks_used', 0)}")
        print(f"  citations: {len(data.get('citations', []))}")
        print(f"  response_length: {len(data.get('response', ''))}")
        
        # Save full result
        with open("api_test_same_query.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n💾 Full result saved to api_test_same_query.json")

if __name__ == "__main__":
    asyncio.run(test())
