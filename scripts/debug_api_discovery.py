#!/usr/bin/env python3
"""
Debug: Compare API entity discovery vs direct pipeline entity discovery.
"""

import asyncio
import json
import httpx
from datetime import datetime

API_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-v2-enhanced-ex"

# The same query that got 0 entities
QUERY = """List all areas of inconsistency identified in the invoice, organized by: (1) all inconsistencies with corresponding evidence, (2) inconsistencies in goods or services sold including detailed specifications for every line item, and (3) inconsistencies regarding billing logistics and administrative or legal issues."""


async def test_api_with_debug_headers():
    """Test API and examine metadata for debugging."""
    print("="*80)
    print("🔍 TESTING API WITH DEBUG")
    print("="*80)
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        # First, let's check if the route 4 endpoint has any debug info
        response = await client.post(
            f"{API_URL}/hybrid/query",
            headers={"X-Group-ID": GROUP_ID},
            json={
                "query": QUERY,
                "response_type": "summary",
                "force_route": "drift_multi_hop"
            }
        )
        
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            print(response.text)
            return
        
        data = response.json()
        metadata = data.get("metadata", {})
        
        print(f"\n📊 API Response Metadata:")
        print(f"  route_used: {data.get('route_used')}")
        print(f"  citations: {len(data.get('citations', []))}")
        print(f"  response_length: {len(data.get('response', ''))}")
        print(f"\n📋 Discovery Metadata:")
        print(f"  all_seeds_discovered: {metadata.get('all_seeds_discovered', [])}")
        print(f"  sub_questions: {metadata.get('sub_questions', [])}")
        print(f"  num_evidence_nodes: {metadata.get('num_evidence_nodes', 0)}")
        print(f"  text_chunks_used: {metadata.get('text_chunks_used', 0)}")
        print(f"  confidence_loop_triggered: {metadata.get('confidence_loop_triggered', False)}")
        
        # Check intermediate results
        intermediate = metadata.get('intermediate_results', [])
        if intermediate:
            print(f"\n📝 Intermediate Results:")
            for i, ir in enumerate(intermediate):
                print(f"  [{i+1}] Q: {ir.get('question', '')[:60]}...")
                print(f"      Entities: {ir.get('entities', [])}")
                print(f"      Evidence: {ir.get('evidence_count', 0)}")
        
        # Check coverage retrieval
        coverage = metadata.get('coverage_retrieval', {})
        if coverage:
            print(f"\n📂 Coverage Retrieval:")
            print(f"  applied: {coverage.get('applied')}")
            print(f"  strategy: {coverage.get('strategy')}")
            print(f"  chunks_added: {coverage.get('chunks_added')}")
        
        # Save full response for comparison
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"debug_api_discovery_{timestamp}.json"
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n💾 Full response saved to: {filename}")


async def main():
    await test_api_with_debug_headers()


if __name__ == "__main__":
    asyncio.run(main())
