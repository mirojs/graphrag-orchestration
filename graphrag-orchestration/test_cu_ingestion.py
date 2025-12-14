#!/usr/bin/env python3
"""
Quick smoke test for CU Standard ingestion integration with GraphRAG.

Tests the /graphrag/index-from-prompt endpoint with CU Standard ingestion.
Requires:
- GraphRAG service running (http://localhost:8001)
- AZURE_CONTENT_UNDERSTANDING_ENDPOINT configured
- AZURE_OPENAI credentials configured
- X-Group-ID header for multi-tenancy
"""

import requests
import json
import sys

BASE_URL = "http://localhost:8001/api/v1"
GROUP_ID = "test-group-123"
HEADERS = {
    "X-Group-ID": GROUP_ID,
    "Content-Type": "application/json"
}


def test_cu_standard_ingestion():
    """Test CU Standard ingestion with prompt-based schema indexing."""
    print("🧪 Testing CU Standard Ingestion + Prompt-based GraphRAG Indexing")
    print("=" * 70)
    
    # Test payload with raw text (passes through CU)
    payload = {
        "schema_prompt": (
            "Extract key entities and relationships about people, organizations, "
            "products, and events. Capture names, roles, affiliations, dates, "
            "locations, and relationships such as WORKS_FOR, PART_OF, RELATED_TO, "
            "and OCCURRED_AT."
        ),
        "documents": [
            # Raw text - should pass through CU ingestion unchanged
            "OpenAI released GPT-4 in March 2023. Sam Altman is the CEO of OpenAI. "
            "The company is based in San Francisco, California."
        ],
        "extraction_mode": "schema",
        "ingestion": "cu-standard",
        "run_community_detection": False
    }
    
    print(f"\n📤 Request:")
    print(f"  Endpoint: POST {BASE_URL}/graphrag/index-from-prompt")
    print(f"  Group ID: {GROUP_ID}")
    print(f"  Schema Prompt: {payload['schema_prompt'][:80]}...")
    print(f"  Documents: {len(payload['documents'])} document(s)")
    print(f"  Ingestion Mode: {payload['ingestion']}")
    
    try:
        resp = requests.post(
            f"{BASE_URL}/graphrag/index-from-prompt",
            headers=HEADERS,
            json=payload,
            timeout=120
        )
        
        print(f"\n📥 Response:")
        print(f"  Status: {resp.status_code}")
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"  ✅ Success!")
            print(f"\n📊 Indexing Stats:")
            stats = result.get("stats", {})
            print(f"  - Documents indexed: {stats.get('documents_indexed', 0)}")
            print(f"  - Nodes created: {stats.get('nodes_created', 0)}")
            print(f"  - Entity types: {len(stats.get('entity_types', []))}")
            print(f"  - Relation types: {len(stats.get('relation_types', []))}")
            print(f"  - Schema source: {stats.get('schema_source', 'N/A')}")
            print(f"  - Schema name: {stats.get('schema_name', 'N/A')}")
            
            if stats.get('entity_types'):
                print(f"\n  Entity types (sample): {stats['entity_types'][:5]}")
            if stats.get('relation_types'):
                print(f"  Relation types (sample): {stats['relation_types'][:5]}")
            
            print("\n✅ CU Standard ingestion test PASSED")
            return True
        else:
            print(f"  ❌ Error: {resp.status_code}")
            print(f"  Response: {resp.text}")
            print("\n❌ CU Standard ingestion test FAILED")
            return False
            
    except requests.exceptions.Timeout:
        print("\n⏱️  Request timed out (this is normal for large documents)")
        print("   Check service logs for actual processing status")
        return False
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        return False


def test_cu_with_url():
    """Test CU Standard ingestion with a URL input."""
    print("\n" + "=" * 70)
    print("🧪 Testing CU Standard with URL Input (requires valid blob SAS)")
    print("=" * 70)
    
    # You would replace this with an actual blob SAS URL
    # For now, we'll skip this test
    print("⏭️  Skipped - requires valid blob SAS URL")
    print("   To test: Update payload with actual URL and uncomment the request")
    
    # Example payload structure:
    example = {
        "schema_prompt": "Extract invoice details",
        "documents": [
            # {"url": "https://<storage>.blob.core.windows.net/<container>/<file>.pdf?<SAS>"}
        ],
        "ingestion": "cu-standard",
        "run_community_detection": False
    }
    print(f"\n  Example payload structure:")
    print(f"  {json.dumps(example, indent=2)}")


if __name__ == "__main__":
    print("=" * 70)
    print("GraphRAG CU Standard Ingestion Test Suite")
    print("=" * 70)
    
    # Test 1: Raw text ingestion
    success = test_cu_standard_ingestion()
    
    # Test 2: URL ingestion (informational)
    test_cu_with_url()
    
    print("\n" + "=" * 70)
    if success:
        print("✅ Tests completed - CU Standard ingestion is working")
    else:
        print("⚠️  Tests failed - check configuration and service logs")
        print("\nRequired environment variables:")
        print("  - AZURE_CONTENT_UNDERSTANDING_ENDPOINT")
        print("  - AZURE_OPENAI_ENDPOINT")
        print("  - AZURE_OPENAI_DEPLOYMENT_NAME")
        print("  - AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        print("  - NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD")
    print("=" * 70)
    
    sys.exit(0 if success else 1)
