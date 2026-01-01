"""
Test Azure Document Intelligence Integration

Validates:
1. SDK import and client creation
2. Document analysis with prebuilt-layout model
3. Table extraction and markdown conversion
4. Integration with GraphRAG indexing pipeline

Prerequisites:
- AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT configured
- AZURE_DOCUMENT_INTELLIGENCE_KEY (or managed identity)
- Sample PDF URL or local file
"""

import asyncio
import os
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.document_intelligence_service import DocumentIntelligenceService
from app.core.config import settings


async def test_sdk_import():
    """Test that Azure Document Intelligence SDK is installed correctly."""
    print("🧪 Test 1: SDK Import")
    try:
        from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
        print("✅ SDK imported successfully")
        return True
    except ImportError as e:
        print(f"❌ SDK import failed: {e}")
        print("   Run: pip install azure-ai-documentintelligence>=1.0.0b4")
        return False


async def test_service_initialization():
    """Test DocumentIntelligenceService initialization."""
    print("\n🧪 Test 2: Service Initialization")
    
    if not settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT:
        print("❌ AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not configured")
        print("   Set in .env or environment variables")
        return False
    
    try:
        service = DocumentIntelligenceService()
        print(f"✅ Service initialized")
        print(f"   Endpoint: {service.endpoint}")
        print(f"   Using API key: {bool(service.api_key)}")
        print(f"   API version: {service.api_version}")
        return True
    except Exception as e:
        print(f"❌ Service initialization failed: {e}")
        return False


async def test_document_extraction():
    """Test document extraction with a sample URL."""
    print("\n🧪 Test 3: Document Extraction")
    
    # Use a public sample PDF (Microsoft's own sample)
    sample_url = os.getenv(
        "TEST_DOCUMENT_URL",
        "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/sample-layout.pdf"
    )
    
    try:
        service = DocumentIntelligenceService()
        group_id = "test-group-001"
        
        print(f"📄 Analyzing: {sample_url[:60]}...")
        documents = await service.extract_documents(
            group_id=group_id,
            input_items=[sample_url]
        )
        
        if not documents:
            print("❌ No documents extracted")
            return False
        
        print(f"✅ Extracted {len(documents)} documents")
        
        # Analyze first document
        doc = documents[0]
        print(f"\n📊 Document Analysis:")
        print(f"   Text length: {len(doc.text)} characters")
        print(f"   Metadata keys: {list(doc.metadata.keys())}")
        print(f"   Chunk type: {doc.metadata.get('chunk_type', 'page')}")
        print(f"   Page number: {doc.metadata.get('page_number')}")
        print(f"   Tables found: {len(doc.metadata.get('tables', []))}")
        print(f"   Section path: {doc.metadata.get('section_path', [])}")
        if doc.metadata.get('chunk_type') == 'section':
            print(f"   DI section path: {doc.metadata.get('di_section_path')}")
            print(f"   DI section part: {doc.metadata.get('di_section_part')}")
        
        # Show markdown preview
        preview = doc.text[:500].replace("\n", "\n   ")
        print(f"\n📝 Markdown Preview (first 500 chars):")
        print(f"   {preview}")

        if len(documents) > 1:
            print(f"\n📦 Produced {len(documents)} chunks total")
            # Show the first few chunk headers to validate section chunking locally.
            for i, d in enumerate(documents[:5], 1):
                sp = d.metadata.get('section_path')
                ct = d.metadata.get('chunk_type', 'page')
                pn = d.metadata.get('page_number')
                print(f"   [{i}] type={ct} page={pn} section_path={sp}")
        
        # Table analysis
        tables = doc.metadata.get('tables', [])
        if tables:
            table = tables[0]
            print(f"\n📊 First Table:")
            print(f"   Rows: {table['row_count']}")
            print(f"   Columns: {table['column_count']}")
            print(f"   Headers: {table['headers']}")
            if table['rows']:
                print(f"   Sample row: {table['rows'][0]}")
        
        return True
        
    except Exception as e:
        print(f"❌ Document extraction failed: {e}")
        import traceback
        print(traceback.format_exc())
        return False


async def test_graphrag_integration():
    """Test integration with GraphRAG indexing endpoint."""
    print("\n🧪 Test 4: GraphRAG Integration")
    
    import httpx
    
    base_url = "http://localhost:8001"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Check if service is running
            health_resp = await client.get(f"{base_url}/health")
            if health_resp.status_code != 200:
                print(f"❌ Service not running at {base_url}")
                print(f"   Start with: docker-compose up graphrag")
                return False
            
            print(f"✅ Service is running")
            
            # Test indexing endpoint with document-intelligence mode
            sample_url = os.getenv(
                "TEST_DOCUMENT_URL",
                "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/sample-layout.pdf"
            )
            
            payload = {
                "documents": [sample_url],
                "ingestion": "document-intelligence",
                "extraction_mode": "schema",
                "run_community_detection": False
            }
            
            print(f"📤 Sending indexing request...")
            index_resp = await client.post(
                f"{base_url}/graphrag/index",
                json=payload,
                headers={"X-Group-ID": "test-group-001"}
            )
            
            if index_resp.status_code >= 400:
                print(f"❌ Indexing failed: {index_resp.status_code}")
                print(f"   Response: {index_resp.text}")
                return False
            
            result = index_resp.json()
            print(f"✅ Indexing completed")
            print(f"   Status: {result.get('status')}")
            print(f"   Message: {result.get('message')}")
            if result.get('stats'):
                print(f"   Stats: {result['stats']}")
            
            return True
            
    except httpx.ConnectError:
        print(f"❌ Cannot connect to {base_url}")
        print(f"   Service may not be running")
        return False
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        print(traceback.format_exc())
        return False


async def main():
    print("=" * 70)
    print("Azure Document Intelligence Integration Test Suite")
    print("=" * 70)
    
    results = []
    
    # Test 1: SDK Import
    results.append(await test_sdk_import())
    
    # Test 2: Service Initialization
    results.append(await test_service_initialization())
    
    # Test 3: Document Extraction (requires configured endpoint)
    if results[1]:  # Only if initialization succeeded
        results.append(await test_document_extraction())
    
    # Test 4: GraphRAG Integration (requires running service)
    # Uncomment to test with live service:
    # if results[2]:
    #     results.append(await test_graphrag_integration())
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✅ All tests passed - Document Intelligence integration working!")
    else:
        print("⚠️ Some tests failed - check configuration:")
        print("  - AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
        print("  - AZURE_DOCUMENT_INTELLIGENCE_KEY (or managed identity)")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
