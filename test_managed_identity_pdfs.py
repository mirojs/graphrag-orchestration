#!/usr/bin/env python3
"""
GraphRAG v3 - PDF Test with Managed Identity (No SAS Tokens)

Tests 5 PDFs using managed identity for both:
- Blob storage access (Container App -> Storage)
- Document Intelligence (Container App -> Azure DI)

This is the correct pattern when using managed identity.
"""
import os
import requests
import json
import time
from pathlib import Path
from typing import Dict, Any, List

# Configuration
BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
TEST_GROUP_ID = f"pdf-mi-test-{int(time.time())}"

# Storage Account Configuration
STORAGE_ACCOUNT = "neo4jstorage21224"
CONTAINER = "test-docs"

# PDF files to test
PDF_FILES = [
    "contoso_lifts_invoice.pdf",
    "purchase_contract.pdf",
    "PROPERTY MANAGEMENT AGREEMENT.pdf",
    "BUILDERS LIMITED WARRANTY.pdf",
    "HOLDING TANK SERVICING CONTRACT.pdf"
]

TEST_QUERIES = [
    "What are the total amounts and payment terms mentioned?",
    "What companies or parties are involved?",
]


def log(msg: str):
    """Print with flush for immediate output"""
    print(msg, flush=True)


def get_blob_urls() -> List[str]:
    """
    Generate raw blob URLs (NO SAS tokens).
    
    The Container App will use its managed identity to access these blobs.
    Requires: Container App has "Storage Blob Data Reader" role on storage account.
    """
    log(f"\n{'=' * 80}")
    log("🔗 GENERATING BLOB URLs (Managed Identity)")
    log(f"{'=' * 80}\n")
    
    log(f"  Storage Account: {STORAGE_ACCOUNT}")
    log(f"  Container: {CONTAINER}")
    log(f"  Authentication: Managed Identity (no SAS)\n")
    
    urls = []
    for i, filename in enumerate(PDF_FILES, 1):
        url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER}/{filename}"
        urls.append(url)
        log(f"  ✅ [{i}/{len(PDF_FILES)}] {filename}")
        log(f"     {url}\n")
    
    log(f"  📊 Total: {len(urls)} blob URLs (no SAS tokens)\n")
    return urls


def index_documents(blob_urls: List[str]) -> Dict[str, Any]:
    """Index documents using managed identity for both storage and DI"""
    log(f"\n{'=' * 80}")
    log("🔄 INDEXING DOCUMENTS (GraphRAG v3 with Managed Identity)")
    log(f"{'=' * 80}\n")
    
    log(f"Group ID: {TEST_GROUP_ID}")
    log(f"Total PDFs: {len(blob_urls)}")
    log(f"Ingestion Mode: document-intelligence")
    log(f"Authentication: Managed Identity")
    log(f"Endpoint: {BASE_URL}/graphrag/v3/index\n")
    
    log(f"Expected Flow:")
    log(f"  1. API receives blob URLs")
    log(f"  2. Container App downloads blobs (managed identity)")
    log(f"  3. Container App sends bytes to Document Intelligence")
    log(f"  4. Document Intelligence extracts text (managed identity)")
    log(f"  5. GraphRAG processes extracted text\n")
    
    start_time = time.time()
    
    try:
        log(f"⏳ Sending request...")
        
        response = requests.post(
            f"{BASE_URL}/graphrag/v3/index",
            headers={
                'Content-Type': 'application/json',
                'X-Group-ID': TEST_GROUP_ID
            },
            json={
                "documents": blob_urls,  # Raw URLs, no SAS
                "ingestion": "document-intelligence",
                "run_raptor": True,
                "run_community_detection": True
            },
            timeout=300  # 5 minutes
        )
        
        elapsed = time.time() - start_time
        log(f"📥 Response received (HTTP {response.status_code}) after {elapsed:.1f}s\n")
        
        try:
            result = response.json()
        except Exception as e:
            log(f"❌ Failed to parse JSON response")
            log(f"   Error: {e}")
            log(f"   Status: {response.status_code}")
            log(f"   Body: {response.text[:500]}")
            return {}
        
        if response.status_code == 200:
            log(f"✅ Indexing completed successfully in {elapsed:.1f}s\n")
            log(f"Results:")
            log(f"  📄 Documents processed: {result.get('documents_processed', 0)}")
            log(f"  🏷️  Entities created: {result.get('entities_created', 0)}")
            log(f"  🔗 Relationships created: {result.get('relationships_created', 0)}")
            log(f"  🌐 Communities detected: {result.get('communities_created', 0)}")
            log(f"  🌳 RAPTOR nodes: {result.get('raptor_nodes_created', 0)}")
            return result
        else:
            log(f"❌ Indexing failed with HTTP {response.status_code}")
            log(f"   Error: {result.get('error', 'Unknown error')}")
            log(f"   Detail: {result.get('detail', 'No details')}")
            return {}
            
    except requests.Timeout:
        elapsed = time.time() - start_time
        log(f"❌ Request timed out after {elapsed:.1f}s")
        log(f"   This suggests the backend is stuck processing the documents")
        log(f"   Check Container App logs for details")
        return {}
    except Exception as e:
        elapsed = time.time() - start_time
        log(f"❌ Request failed after {elapsed:.1f}s")
        log(f"   Error: {e}")
        return {}


def test_queries(group_id: str):
    """Test query against indexed documents"""
    log(f"\n{'=' * 80}")
    log("🔍 TESTING QUERIES")
    log(f"{'=' * 80}\n")
    
    for i, query in enumerate(TEST_QUERIES, 1):
        log(f"\n{'─' * 80}")
        log(f"Query {i}/{len(TEST_QUERIES)}: {query}")
        log(f"{'─' * 80}")
        
        try:
            response = requests.post(
                f"{BASE_URL}/graphrag/v3/query",
                headers={
                    'Content-Type': 'application/json',
                    'X-Group-ID': group_id
                },
                json={"query": query},
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                log(f"✅ Query successful\n")
                log(f"Answer:\n{result.get('answer', 'No answer')}\n")
                
                sources = result.get('sources', [])
                if sources:
                    log(f"Sources ({len(sources)}):")
                    for source in sources[:3]:
                        log(f"  • {source}")
            else:
                log(f"❌ Query failed: HTTP {response.status_code}")
                log(f"   {response.text[:200]}")
                
        except Exception as e:
            log(f"❌ Query error: {e}")


def main():
    """Run the full test"""
    log("=" * 80)
    log("GraphRAG v3 - PDF Test with Managed Identity")
    log("=" * 80)
    
    # Step 1: Get blob URLs
    blob_urls = get_blob_urls()
    
    if not blob_urls:
        log("❌ No blob URLs generated")
        return
    
    # Step 2: Index documents
    result = index_documents(blob_urls)
    
    if not result:
        log("\n❌ Indexing failed - skipping queries")
        return
    
    # Step 3: Test queries
    test_queries(TEST_GROUP_ID)
    
    log(f"\n{'=' * 80}")
    log("✅ TEST COMPLETE")
    log(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
