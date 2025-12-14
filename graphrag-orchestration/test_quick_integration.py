#!/usr/bin/env python3
"""
Quick Integration Test: Document Intelligence extraction only
Tests just the document processing layer without full GraphRAG indexing.
"""

import requests
import json
import time

BASE_URL = "http://localhost:8001"
GROUP_ID = "quick-test-di"
TEST_DOC = "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/sample-layout.pdf"

print("=" * 80)
print("QUICK INTEGRATION TEST: Document Intelligence Extraction")
print("=" * 80)

# Test the _to_documents helper directly via a simpler endpoint
print("\n1. Testing Document Intelligence extraction...")

start = time.time()

# We'll use the health/detailed endpoint which tests document extraction
payload = {
    "documents": [TEST_DOC],
    "ingestion_mode": "document-intelligence"  
}

try:
    # Use requests library to call the internal conversion
    # Actually, let's test via Python directly
    import sys
    sys.path.insert(0, '/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/services/graphrag-orchestration')
    
    import asyncio
    from app.routers.graphrag import _to_documents
    
    async def test():
        docs = await _to_documents([TEST_DOC], ingestion_mode="document-intelligence", group_id=GROUP_ID)
        return docs
    
    docs = asyncio.run(test())
    elapsed = time.time() - start
    
    print(f"✅ Document Intelligence extracted {len(docs)} page(s) in {elapsed:.2f}s")
    
    for i, doc in enumerate(docs[:3]):  # Show first 3 pages
        print(f"\n📄 Page {i+1}:")
        print(f"   Text length: {len(doc.text)} chars")
        print(f"   Metadata: {list(doc.metadata.keys())}")
        if doc.metadata.get('tables'):
            print(f"   Tables: {len(doc.metadata['tables'])}")
        if doc.metadata.get('section_path'):
            print(f"   Sections: {doc.metadata['section_path']}")
        print(f"   Preview: {doc.text[:150]}...")
    
    print("\n" + "=" * 80)
    print("✅ INTEGRATION TEST PASSED")
    print(f"   Document Intelligence successfully extracted {len(docs)} pages")
    print(f"   Processing time: {elapsed:.2f}s")
    print(f"   Ready for GraphRAG indexing")
    print("=" * 80)
    
except Exception as e:
    print(f"\n❌ TEST FAILED: {e}")
    import traceback
    traceback.print_exc()
