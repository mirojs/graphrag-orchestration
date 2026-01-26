#!/usr/bin/env python3
"""
Test: Azure Document Intelligence Language Detection Granularity

Purpose: Determine if language detection is sentence-based, line-based, or paragraph-based.

Uses a sample PDF URL that works with Azure DI.
"""

import asyncio
import json
from app.services.document_intelligence_service import DocumentIntelligenceService
from app.core.config import settings


async def test_language_detection_with_real_doc():
    """Test language detection using our DocumentIntelligenceService."""
    
    print("=" * 80)
    print("Azure DI Language Detection Granularity Test")
    print("=" * 80)
    print()
    
    # Use a sample PDF URL
    test_url = "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/sample-layout.pdf"
    
    print(f"Test URL: {test_url[:60]}...")
    print()
    
    service = DocumentIntelligenceService()
    
    print("📤 Sending to Azure DI with LANGUAGES feature...")
    
    try:
        docs = await service.extract_documents(
            group_id="test-language-granularity",
            input_items=[test_url],
        )
        
        print(f"✅ Extracted {len(docs)} documents")
        print()
        
        # Check first document for language metadata
        if docs:
            doc = docs[0]
            languages = doc.metadata.get("languages", [])
            
            print("=" * 80)
            print("DETECTED LANGUAGES")
            print("=" * 80)
            
            if languages:
                print(f"Languages detected: {len(languages)}")
                for lang in languages:
                    print(f"  - {lang.get('locale', 'unknown')}: confidence={lang.get('confidence', 0):.2f}, spans={lang.get('span_count', 0)}")
            else:
                print("No languages in first chunk metadata (may be in document-level)")
                
            # Show all metadata keys
            print()
            print("All metadata keys:", list(doc.metadata.keys()))
            
    except Exception as e:
        print(f"❌ Error: {e}")


async def test_language_spans_detail():
    """Test with raw Azure DI client to see full span details."""
    
    print()
    print("=" * 80)
    print("DETAILED SPAN ANALYSIS (Raw Azure DI)")
    print("=" * 80)
    print()
    
    from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import (
        AnalyzeDocumentRequest,
        DocumentAnalysisFeature,
    )
    from azure.core.credentials import AzureKeyCredential
    from azure.identity.aio import DefaultAzureCredential
    
    endpoint = settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
    api_key = settings.AZURE_DOCUMENT_INTELLIGENCE_KEY
    
    # Create client
    if api_key:
        credential = AzureKeyCredential(api_key)
    else:
        credential = DefaultAzureCredential()
    
    test_url = "https://raw.githubusercontent.com/Azure-Samples/cognitive-services-REST-api-samples/master/curl/form-recognizer/sample-layout.pdf"
    
    async with DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=credential,
        api_version=settings.AZURE_DOC_INTELLIGENCE_API_VERSION,
    ) as client:
        
        print("📤 Analyzing document...")
        
        poller = await client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(url_source=test_url),
            features=[DocumentAnalysisFeature.LANGUAGES],
        )
        
        result = await poller.result()
        
        print("✅ Analysis complete!")
        print()
        
        content = result.content or ""
        languages = result.languages or []
        
        print(f"Content length: {len(content)} chars")
        print(f"Language spans detected: {len(languages)}")
        print()
        
        # Show each language span with context
        for i, lang in enumerate(languages[:10]):  # Limit to first 10
            locale = lang.locale or ""
            confidence = lang.confidence or 0.0
            spans = lang.spans or []
            
            print(f"Language {i + 1}: {locale} (confidence: {confidence:.2f})")
            
            for j, span in enumerate(spans[:3]):  # Limit spans
                offset = span.offset or 0
                length = span.length or 0
                text_slice = content[offset:offset + length]
                
                # Count newlines in span
                newline_count = text_slice.count('\n')
                
                # Show first 80 chars
                preview = text_slice[:80].replace('\n', '↵')
                if len(text_slice) > 80:
                    preview += "..."
                
                print(f"  Span: offset={offset}, length={length}, newlines={newline_count}")
                print(f"    Text: \"{preview}\"")
            print()
        
        # Summary
        print("=" * 80)
        print("GRANULARITY SUMMARY")
        print("=" * 80)
        
        total_spans = sum(len(lang.spans or []) for lang in languages)
        spans_with_newlines = 0
        
        for lang in languages:
            for span in (lang.spans or []):
                offset = span.offset or 0
                length = span.length or 0
                if '\n' in content[offset:offset + length]:
                    spans_with_newlines += 1
        
        print(f"Total language spans: {total_spans}")
        print(f"Spans containing newlines: {spans_with_newlines}")
        print()
        
        if spans_with_newlines > total_spans * 0.5:
            print("📊 CONCLUSION: PARAGRAPH/BLOCK based (spans cross line boundaries)")
        elif spans_with_newlines > 0:
            print("📊 CONCLUSION: MIXED (some block, some line based)")
        else:
            print("📊 CONCLUSION: LINE based (no spans cross line boundaries)")


if __name__ == "__main__":
    asyncio.run(test_language_detection_with_real_doc())
    asyncio.run(test_language_spans_detail())
