#!/usr/bin/env python3
"""
Test GraphRAG v2 endpoint with 5 production PDFs using Azure blob URLs
Based on successful test_e2e_simple_extraction.py pattern
"""
import requests
import time
import json
import os
from datetime import datetime

# Configuration
API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = f"pdf-test-v2-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

# Get SAS URLs from environment or use defaults
SAS_TOKEN = "se=2025-12-25T06%3A03Z&sp=r&sv=2022-11-02&sr=b&skoid=ddd5567a-7d84-4703-bbdb-aa00b3b95bd8&sktid=ecaa729a-f04c-4558-a31a-ab714740ee8b&skt=2025-12-18T06%3A03%3A37Z&ske=2025-12-25T06%3A03%3A00Z&sks=b&skv=2022-11-02&sig=oSc7TvC%2Bzh2WieNq2l%2BaDlGg1fOb3hx7EWWACgyGjWQ%3D"
STORAGE_ACCOUNT = "neo4jstorage21224"
CONTAINER = "test-docs"

# 5 Production PDFs
PDF_NAMES = [
    "contoso_lifts_invoice.pdf",
    "purchase_contract.pdf",
    "PROPERTY MANAGEMENT AGREEMENT.pdf",
    "BUILDERS LIMITED WARRANTY.pdf",
    "HOLDING TANK SERVICING CONTRACT.pdf"
]

# Build URLs with SAS token
PDF_URLS = [
    f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER}/{name}?{SAS_TOKEN}"
    for name in PDF_NAMES
]

print("=" * 80)
print("🔬 GRAPHRAG V2 ENDPOINT TEST: 5 PDFs with Document Intelligence")
print("=" * 80)
print(f"\nAPI URL: {API_URL}")
print(f"Group ID: {GROUP_ID}")
print(f"Document Count: {len(PDF_URLS)}")
print(f"\nPDFs:")
for i, name in enumerate(PDF_NAMES, 1):
    print(f"  {i}. {name}")

# Test 1: Index with Document Intelligence (all 5 PDFs at once)
print("\n" + "=" * 80)
print("📤 Step 1: Indexing 5 PDFs with Document Intelligence...")
print("=" * 80)

payload = {
    "documents": PDF_URLS,  # List of URL strings
    "ingestion": "document-intelligence",  # Use Document Intelligence
    "extraction_mode": "simple",  # Avoid schema validation
    "run_community_detection": False  # Disable for faster testing
}

print("\nPayload:")
print(f"  • documents: {len(payload['documents'])} URLs")
print(f"  • ingestion: {payload['ingestion']}")
print(f"  • extraction_mode: {payload['extraction_mode']}")

print("\n⏳ Sending POST request to /graphrag/index...")
print(f"   Timeout: 300 seconds (5 minutes)")

start_time = time.time()
try:
    resp = requests.post(
        f"{API_URL}/graphrag/index",
        headers={
            "X-Group-ID": GROUP_ID,
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=300  # 5 minutes
    )
    elapsed = time.time() - start_time
    
    print(f"\n✅ Response received: {resp.status_code}")
    print(f"⏱️  Total time: {elapsed:.1f} seconds")
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"\n📊 Indexing Results:")
        print(json.dumps(result, indent=2))
        
        if "stats" in result:
            stats = result["stats"]
            print(f"\n🎯 Statistics:")
            print(f"   • Documents processed: {stats.get('documents_processed', 'N/A')}")
            print(f"   • Entities extracted: {stats.get('entities_extracted', 'N/A')}")
            print(f"   • Relationships created: {stats.get('relationships_created', 'N/A')}")
        
        print("\n" + "=" * 80)
        print("✅ TEST PASSED")
        print("=" * 80)
        print(f"\n✓ Document Intelligence processed {len(PDF_URLS)} PDFs successfully")
        print(f"✓ Processing time: {elapsed:.1f} seconds")
        print(f"✓ Group ID: {GROUP_ID}")
        
    else:
        print(f"\n❌ Error: {resp.status_code}")
        print(f"Response: {resp.text}")
        exit(1)
        
except requests.exceptions.Timeout:
    elapsed = time.time() - start_time
    print(f"\n⏰ Request timed out after {elapsed:.1f} seconds")
    print("This suggests the backend is processing but not responding")
    exit(1)
    
except Exception as e:
    elapsed = time.time() - start_time
    print(f"\n❌ Exception after {elapsed:.1f} seconds: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Test 2: Verify data in Neo4j
print("\n" + "=" * 80)
print("📊 Step 2: Querying Neo4j to verify entities...")
print("=" * 80)

time.sleep(2)  # Give Neo4j time to commit

try:
    # Count nodes
    query_payload = {"query": f"MATCH (n) WHERE n.group_id = '{GROUP_ID}' RETURN count(n) as node_count"}
    resp = requests.post(
        f"{API_URL}/graphrag/query",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json=query_payload,
        timeout=30
    )
    
    if resp.status_code == 200:
        nodes = resp.json()["result"][0]["node_count"]
        print(f"   ✅ Nodes created: {nodes}")
    else:
        print(f"   ⚠️  Could not query nodes: {resp.text}")
    
    # Count relationships
    query_payload = {"query": f"MATCH ()-[r]->() WHERE r.group_id = '{GROUP_ID}' RETURN count(r) as rel_count"}
    resp = requests.post(
        f"{API_URL}/graphrag/query",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json=query_payload,
        timeout=30
    )
    
    if resp.status_code == 200:
        rels = resp.json()["result"][0]["rel_count"]
        print(f"   ✅ Relationships created: {rels}")
    else:
        print(f"   ⚠️  Could not query relationships: {resp.text}")
    
    # Get sample entities
    query_payload = {"query": f"MATCH (n) WHERE n.group_id = '{GROUP_ID}' RETURN labels(n) as type, n.name as name LIMIT 10"}
    resp = requests.post(
        f"{API_URL}/graphrag/query",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json=query_payload,
        timeout=30
    )
    
    if resp.status_code == 200:
        entities = resp.json()["result"]
        print(f"\n   📋 Sample entities:")
        for e in entities:
            entity_type = e['type'][0] if e['type'] else 'Unknown'
            entity_name = e.get('name', 'N/A')
            print(f"      • {entity_type}: {entity_name}")
    
except Exception as e:
    print(f"\n   ⚠️  Neo4j query error: {e}")

print("\n" + "=" * 80)
print("🎉 TEST COMPLETE")
print("=" * 80)
