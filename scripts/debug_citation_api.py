#!/usr/bin/env python3
"""
Debug script to compare API vs Direct Pipeline citation counts.
"""

import asyncio
import json
import httpx
from datetime import datetime

# Test configuration
GROUP_ID = "test-5pdfs-v2-enhanced-ex"
QUERY = """List all areas of inconsistency identified in the invoice, organized by:
(1) all inconsistencies with corresponding evidence,
(2) inconsistencies in goods or services sold including detailed specifications for every line item, and
(3) inconsistencies regarding billing logistics and administrative or legal issues."""

API_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"


async def test_api():
    """Test via deployed API."""
    print("\n" + "="*80)
    print("🌐 Testing via DEPLOYED API")
    print("="*80)
    
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{API_URL}/hybrid/query",
            headers={"X-Group-ID": GROUP_ID},
            json={
                "query": QUERY,
                "response_type": "detailed_report",
                "force_route": "drift_multi_hop"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Status: {response.status_code}")
            print(f"📝 Response Length: {len(result.get('response', '')):,} chars")
            print(f"📚 Citations Count: {len(result.get('citations', []))}")
            print(f"🔗 Evidence Path: {len(result.get('evidence_path', []))}")
            print(f"🛤️  Route: {result.get('route_used', 'unknown')}")
            
            # Check metadata for text_chunks_used
            meta = result.get('metadata', {})
            print(f"📊 text_chunks_used: {meta.get('text_chunks_used', 'N/A')}")
            
            # Show all citations
            print("\n--- All Citations ---")
            for i, cit in enumerate(result.get('citations', [])):
                doc = cit.get('document_title', cit.get('document', 'Unknown'))
                preview = cit.get('text_preview', '')[:60].replace('\n', ' ')
                print(f"  [{i+1}] {doc} - {preview}...")
            
            # Count citation markers in response
            response_text = result.get('response', '')
            import re
            markers = set(re.findall(r'\[(\d+)\]', response_text))
            print(f"\n📌 Citation markers in response: {len(markers)} unique markers")
            print(f"   Markers found: {sorted(int(m) for m in markers)}")
            
            # Save full result
            fname = f"debug_api_result_{datetime.now().strftime('%H%M%S')}.json"
            with open(fname, "w") as f:
                json.dump(result, f, indent=2)
            print(f"\n💾 Full result saved to {fname}")
            
            return result
        else:
            print(f"❌ Status: {response.status_code}")
            print(f"Error: {response.text}")
            return None


async def main():
    print("="*80)
    print("🔍 CITATION DEBUG: API Response Analysis")
    print("="*80)
    print(f"Group: {GROUP_ID}")
    print(f"Query: {QUERY[:100]}...")
    
    # Test API
    api_result = await test_api()
    
    if api_result:
        citations = len(api_result.get('citations', []))
        if citations < 10:
            print("\n⚠️  LOW CITATION COUNT DETECTED!")
            print("This confirms the production bug - expected 30-50 citations.")


if __name__ == "__main__":
    asyncio.run(main())
