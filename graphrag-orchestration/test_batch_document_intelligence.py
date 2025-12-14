#!/usr/bin/env python3
"""
Test Azure Document Intelligence batch processing with 5 documents.
Measures response times and validates multi-document summarization.
"""

import asyncio
import time
from typing import List
from app.services.document_intelligence_service import DocumentIntelligenceService
from llama_index.core import Document

# Test URLs - 5 different documents for batch processing
TEST_DOCUMENTS = [
    "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/sample-layout.pdf",
    # Add more when we find accessible URLs
]


async def test_single_document():
    """Test single document extraction with timing."""
    print("=" * 80)
    print("TEST 1: Single Document Extraction")
    print("=" * 80)
    
    service = DocumentIntelligenceService()
    
    start_time = time.time()
    docs = await service.extract_documents('test-batch', [TEST_DOCUMENTS[0]])
    elapsed = time.time() - start_time
    
    print(f"\n✅ Extracted {len(docs)} page(s)")
    print(f"⏱️  Response time: {elapsed:.2f} seconds")
    
    for i, doc in enumerate(docs):
        print(f"\n📄 Page {i+1}:")
        print(f"   Text length: {len(doc.text)} chars")
        print(f"   Metadata keys: {list(doc.metadata.keys())}")
        if doc.metadata.get('tables'):
            print(f"   Tables found: {len(doc.metadata['tables'])}")
    
    return elapsed


async def test_batch_processing():
    """Test batch processing with multiple documents."""
    print("\n" + "=" * 80)
    print("TEST 2: Batch Document Processing (Multiple URLs)")
    print("=" * 80)
    
    # For now, test with same document 5 times to simulate batch load
    # In production, you'd use 5 different URLs
    test_urls = [TEST_DOCUMENTS[0]] * 5
    
    service = DocumentIntelligenceService(max_concurrency=5)
    
    print(f"\n📦 Processing {len(test_urls)} documents in parallel...")
    print(f"   Max concurrency: {service.max_concurrency}")
    
    start_time = time.time()
    docs = await service.extract_documents('test-batch', test_urls)
    elapsed = time.time() - start_time
    
    print(f"\n✅ Extracted {len(docs)} total page(s) from {len(test_urls)} documents")
    print(f"⏱️  Total response time: {elapsed:.2f} seconds")
    print(f"⏱️  Average per document: {elapsed/len(test_urls):.2f} seconds")
    
    # Calculate throughput
    throughput = len(test_urls) / elapsed
    print(f"📊 Throughput: {throughput:.2f} documents/second")
    
    return elapsed, docs


async def test_summarization(docs: List[Document]):
    """Test multi-document summarization with GraphRAG."""
    print("\n" + "=" * 80)
    print("TEST 3: Multi-Document Summarization")
    print("=" * 80)
    
    # Combine all document texts
    combined_text = "\n\n---\n\n".join([doc.text for doc in docs[:5]])  # First 5 pages
    
    print(f"\n📝 Combined content:")
    print(f"   Total characters: {len(combined_text)}")
    print(f"   Documents/pages: {min(len(docs), 5)}")
    
    # Show preview
    print(f"\n📖 Preview (first 500 chars):")
    print(combined_text[:500])
    print("...")
    
    # This would normally call Azure OpenAI for summarization
    # For now, just show the structure
    summarization_prompt = """
Analyze the following documents and provide:
1. Key themes and topics
2. Main entities (people, organizations, places)
3. Important relationships
4. Critical dates and events
5. Overall summary

Documents:
---
{combined_text}
---
"""
    
    print(f"\n💡 Summarization prompt ready ({len(summarization_prompt)} chars)")
    print("   (Would be sent to Azure OpenAI gpt-4o)")
    
    return combined_text


async def main():
    """Run all tests."""
    print("\n" + "🧪" * 40)
    print("Azure Document Intelligence Batch Processing Test Suite")
    print("🧪" * 40)
    
    # Test 1: Single document
    single_time = await test_single_document()
    
    # Test 2: Batch processing
    batch_time, batch_docs = await test_batch_processing()
    
    # Test 3: Summarization preparation
    await test_summarization(batch_docs)
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 PERFORMANCE SUMMARY")
    print("=" * 80)
    print(f"Single document:  {single_time:.2f}s")
    print(f"Batch (5 docs):   {batch_time:.2f}s")
    print(f"Speedup factor:   {(single_time * 5) / batch_time:.2f}x")
    print(f"Parallel efficiency: {((single_time * 5) / batch_time) / 5 * 100:.1f}%")
    
    print("\n✅ All tests complete!")


if __name__ == "__main__":
    asyncio.run(main())
