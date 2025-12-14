#!/usr/bin/env python3
"""
Test Azure Content Understanding Response Format

This script calls Azure CU with a sample PDF to inspect the actual
response structure and verify our parsing assumptions.
"""

import asyncio
import json
import os
import sys
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
import httpx


async def test_cu_response_format():
    """Call Azure CU and print the actual response structure."""
    
    # Configuration
    endpoint = os.getenv("AZURE_CONTENT_UNDERSTANDING_ENDPOINT")
    if not endpoint:
        print("❌ AZURE_CONTENT_UNDERSTANDING_ENDPOINT not set")
        sys.exit(1)
    
    # Sample blob URL (replace with actual test file)
    blob_url = os.getenv("TEST_BLOB_URL")
    if not blob_url:
        print("❌ TEST_BLOB_URL not set")
        print("Usage: TEST_BLOB_URL='https://storage.blob.core.windows.net/...' python test_cu_response_format.py")
        sys.exit(1)
    
    print("=" * 80)
    print("Azure Content Understanding Response Format Test")
    print("=" * 80)
    print(f"Endpoint: {endpoint}")
    print(f"Test File: {blob_url}")
    print()
    
    # Setup authentication
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential,
        "https://cognitiveservices.azure.com/.default"
    )
    
    # Prepare request
    api_version = "2025-11-01"
    analyze_url = f"{endpoint}/contentunderstanding/analyzers/prebuilt-documentAnalyzer:analyze?api-version={api_version}"
    
    payload = {
        "inputs": [{"content": {"sourceUrl": blob_url}}],
        "config": {
            "enableLayout": True,
            "enableOcr": True,
            "tableFormat": "markdown",
        },
        "output": {
            "format": "json"
        }
    }
    
    headers = {
        "Authorization": f"Bearer {token_provider()}",
        "Content-Type": "application/json",
    }
    
    print("Request Payload:")
    print(json.dumps(payload, indent=2))
    print()
    
    # Call Azure CU
    print("Calling Azure Content Understanding...")
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(analyze_url, json=payload, headers=headers)
        
        print(f"Response Status: {resp.status_code}")
        print()
        
        if resp.status_code >= 400:
            print("❌ Error Response:")
            print(resp.text)
            sys.exit(1)
        
        data = resp.json()
        
        # Print full response structure
        print("=" * 80)
        print("FULL RESPONSE STRUCTURE:")
        print("=" * 80)
        print(json.dumps(data, indent=2))
        print()
        
        # Analyze structure
        print("=" * 80)
        print("STRUCTURE ANALYSIS:")
        print("=" * 80)
        
        # Check top-level keys
        print(f"Top-level keys: {list(data.keys())}")
        
        # Check if our assumptions are correct
        assumptions = {
            "Has 'result' key": "result" in data,
            "Has 'result.contents'": "contents" in data.get("result", {}),
        }
        
        if "result" in data and "contents" in data.get("result", {}):
            contents = data["result"]["contents"]
            print(f"Number of content items: {len(contents)}")
            
            if contents:
                first_item = contents[0]
                print(f"First item keys: {list(first_item.keys())}")
                
                assumptions.update({
                    "Has 'pages'": "pages" in first_item,
                    "Has 'text'": "text" in first_item,
                    "Has 'content'": "content" in first_item,
                    "Has 'fields'": "fields" in first_item,
                })
                
                if "pages" in first_item:
                    pages = first_item["pages"]
                    print(f"Number of pages: {len(pages)}")
                    
                    if pages:
                        first_page = pages[0]
                        print(f"First page keys: {list(first_page.keys())}")
                        
                        assumptions.update({
                            "Has 'pageNumber'": "pageNumber" in first_page,
                            "Has 'paragraphs'": "paragraphs" in first_page,
                            "Has 'tables'": "tables" in first_page,
                        })
                        
                        if "paragraphs" in first_page and first_page["paragraphs"]:
                            para = first_page["paragraphs"][0]
                            print(f"First paragraph keys: {list(para.keys())}")
                            assumptions["Paragraph has 'content'"] = "content" in para
                        
                        if "tables" in first_page and first_page["tables"]:
                            table = first_page["tables"][0]
                            print(f"First table keys: {list(table.keys())}")
                            assumptions["Table has 'content'"] = "content" in table
        
        print()
        print("=" * 80)
        print("ASSUMPTION VALIDATION:")
        print("=" * 80)
        for assumption, valid in assumptions.items():
            status = "✅" if valid else "❌"
            print(f"{status} {assumption}: {valid}")
        
        print()
        
        # Test text extraction with current code
        print("=" * 80)
        print("TEXT EXTRACTION TEST (Current Code Logic):")
        print("=" * 80)
        
        items = data.get("result", {}).get("contents", [])
        for i, item in enumerate(items):
            print(f"\n--- Document {i+1} ---")
            text_parts = []
            
            if "pages" in item:
                for page in item["pages"]:
                    page_num = page.get("pageNumber", "?")
                    text_parts.append(f"\n--- Page {page_num} ---\n")
                    
                    if "paragraphs" in page:
                        for para in page["paragraphs"]:
                            text_parts.append(para.get("content", ""))
                    
                    if "tables" in page:
                        for table in page["tables"]:
                            table_content = table.get("content", "")
                            if table_content:
                                text_parts.append(f"\n{table_content}\n")
            
            if not text_parts:
                text = item.get("text") or item.get("content") or ""
                text_parts.append(text)
            
            extracted_text = "\n".join(text_parts)
            print(f"Extracted {len(extracted_text)} characters")
            print(f"Preview (first 500 chars):")
            print(extracted_text[:500])
            print("...")


if __name__ == "__main__":
    asyncio.run(test_cu_response_format())
