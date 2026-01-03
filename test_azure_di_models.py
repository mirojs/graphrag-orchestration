"""
Test Azure Document Intelligence with different prebuilt models
to see which extracts P.O. NUMBER and address correctly.
"""
import asyncio
import os
from pathlib import Path
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import DefaultAzureCredential

# Get credentials from environment
ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
API_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
API_VERSION = "2024-11-30"

# Test files
TEST_FILES = {
    "contoso_lifts_invoice.pdf": {
        "search_for": ["30060204", "P.O. NUMBER", "Jim Contoso"],
        "models": ["prebuilt-layout", "prebuilt-invoice", "prebuilt-read"]
    },
    "BUILDERS LIMITED WARRANTY.pdf": {
        "search_for": ["Pocatello", "83201"],
        "models": ["prebuilt-layout", "prebuilt-read"]
    }
}


async def test_model(client, file_path: Path, model_id: str, search_terms: list):
    """Test a specific model on a file and check if it extracts target values."""
    print(f"\n{'='*60}")
    print(f"Testing: {file_path.name}")
    print(f"Model: {model_id}")
    print(f"{'='*60}")
    
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        # Match the signature from document_intelligence_service.py
        poller = await client.begin_analyze_document(
            model_id,  # Positional argument
            AnalyzeDocumentRequest(bytes_source=file_bytes),  # body argument
            output_content_format=DocumentContentFormat.MARKDOWN
        )
        result = await poller.result()
        
        # Get the full markdown content
        content = result.content if result.content else ""
        
        print(f"✅ Extraction successful")
        print(f"   Content length: {len(content)} characters")
        print(f"   Pages: {len(result.pages) if result.pages else 0}")
        
        # Check for target values
        print(f"\n📋 Search Results:")
        found_any = False
        for term in search_terms:
            if term in content:
                found_any = True
                print(f"   ✅ FOUND: '{term}'")
                # Show context
                idx = content.find(term)
                start = max(0, idx - 80)
                end = min(len(content), idx + 80)
                print(f"      Context: ...{content[start:end]}...")
            else:
                print(f"   ❌ NOT FOUND: '{term}'")
        
        # Show a sample of the content
        if not found_any:
            print(f"\n📄 First 500 chars of extracted content:")
            print(content[:500])
            print("...")
        
        return {
            "model": model_id,
            "success": True,
            "content_length": len(content),
            "found_terms": [t for t in search_terms if t in content],
            "missing_terms": [t for t in search_terms if t not in content]
        }
        
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        return {
            "model": model_id,
            "success": False,
            "error": str(e)
        }


async def main():
    if not ENDPOINT:
        print("❌ AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not set")
        return
    
    print(f"Azure DI Endpoint: {ENDPOINT}")
    print(f"Using API key: {bool(API_KEY)}")
    
    # Create client
    if API_KEY:
        credential = AzureKeyCredential(API_KEY)
    else:
        credential = DefaultAzureCredential()
    
    async with DocumentIntelligenceClient(
        endpoint=ENDPOINT,
        credential=credential,
        api_version=API_VERSION
    ) as client:
        
        base_path = Path("graphrag-orchestration/data/input_docs")
        
        results = {}
        
        for filename, config in TEST_FILES.items():
            file_path = base_path / filename
            if not file_path.exists():
                print(f"⚠️  File not found: {file_path}")
                continue
            
            results[filename] = []
            
            for model_id in config["models"]:
                result = await test_model(
                    client, 
                    file_path, 
                    model_id, 
                    config["search_for"]
                )
                results[filename].append(result)
                
                # Small delay between requests
                await asyncio.sleep(1)
        
        # Summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        
        for filename, file_results in results.items():
            print(f"\n📄 {filename}:")
            for r in file_results:
                if r["success"]:
                    found = len(r["found_terms"])
                    total = found + len(r["missing_terms"])
                    print(f"   {r['model']}: {found}/{total} terms found")
                    if r["found_terms"]:
                        print(f"      ✅ Found: {', '.join(r['found_terms'])}")
                    if r["missing_terms"]:
                        print(f"      ❌ Missing: {', '.join(r['missing_terms'])}")
                else:
                    print(f"   {r['model']}: FAILED - {r.get('error', 'Unknown error')}")
        
        print("\n" + "="*60)
        print("RECOMMENDATION")
        print("="*60)
        
        # Determine best model for each file type
        print("Based on extraction results:")
        print("- If prebuilt-invoice extracts P.O. NUMBER: Use it for invoices")
        print("- If prebuilt-read extracts address: Consider using it as fallback")
        print("- If all fail: May need to investigate table extraction separately")


if __name__ == "__main__":
    asyncio.run(main())
