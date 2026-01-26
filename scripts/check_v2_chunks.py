#!/usr/bin/env python3
"""
Check if V2 group chunks have embedding_v2 property populated.
"""

import requests
import sys

API_URL = "https://graphrag-orchestration-sweden.proudplant-e9a97bea.swedencentral.azurecontainerapps.io"
V2_GROUP_ID = "test-5pdfs-v2-1769440005"

def check_v2_chunks():
    """Query chunks to inspect embedding_v2 property."""
    
    # Try a simple query that will return chunk details
    query_payload = {
        "question": "EXHIBIT A",
        "response_type": "detailed",
        "force_route": "route_3"  # Use Route 3 which does vector search
    }
    
    try:
        response = requests.post(
            f"{API_URL}/query",
            json=query_payload,
            headers={"X-Group-ID": V2_GROUP_ID},
            timeout=60
        )
        
        if response.status_code != 200:
            print(f"❌ Query failed: {response.status_code}")
            print(response.text)
            return
        
        data = response.json()
        
        # Check if we got chunks
        if "retrieved_chunks" in data:
            chunks = data["retrieved_chunks"]
            print(f"✅ Retrieved {len(chunks)} chunks")
            
            # Sample a chunk
            if chunks:
                first_chunk = chunks[0]
                print(f"\n📄 First chunk:")
                print(f"   ID: {first_chunk.get('id', 'N/A')}")
                print(f"   Text preview: {first_chunk.get('text', 'N/A')[:100]}...")
                print(f"   Score: {first_chunk.get('score', 'N/A')}")
                
        else:
            print("⚠️  No retrieved_chunks in response")
            print(f"Response keys: {list(data.keys())}")
    
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_v2_chunks()
