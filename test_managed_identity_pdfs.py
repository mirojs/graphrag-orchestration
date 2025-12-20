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
BASE_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
TEST_GROUP_ID = "test-3072-fresh"  # Fresh group for clean 3072-dim testing

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
        log(f"⏳ [Step 1/5] Sending request to backend...")
        log(f"   This will process {len(blob_urls)} PDFs in parallel")
        log(f"   Expected time: ~2-3 minutes for 5 PDFs\n")
        
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
        log(f"\n📥 [Step 2/5] Response received (HTTP {response.status_code}) after {elapsed:.1f}s")
        log(f"   Processing time: {elapsed/60:.1f} minutes\n")
        
        log(f"⏳ [Step 3/5] Parsing response...")
        try:
            result = response.json()
            log(f"✅ Response parsed successfully\n")
        except Exception as e:
            log(f"❌ Failed to parse JSON response")
            log(f"   Error: {e}")
            log(f"   Status: {response.status_code}")
            log(f"   Body: {response.text[:500]}")
            return {}
        
        if response.status_code == 200:
            log(f"✅ [Step 4/5] Indexing completed successfully!\n")
            log(f"⏱️  Performance Metrics:")
            log(f"  • Total time: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
            log(f"  • Average per PDF: {elapsed/len(blob_urls):.1f}s")
            log(f"  • Throughput: {len(blob_urls)/(elapsed/60):.1f} PDFs/minute\n")
            log(f"📊 Extraction Results:")
            log(f"  • Documents processed: {result.get('documents_processed', 0)}")
            log(f"  • Entities created: {result.get('entities_created', 0)}")
            log(f"  • Relationships created: {result.get('relationships_created', 0)}")
            log(f"  • Communities detected: {result.get('communities_created', 0)}")
            log(f"  • RAPTOR nodes: {result.get('raptor_nodes_created', 0)}\n")
            return result
        else:
            log(f"❌ Indexing failed with HTTP {response.status_code}")
            log(f"   Error: {result.get('error', 'Unknown error')}")
            log(f"   Detail: {result.get('detail', 'No details')}")
            return {}
            
    except requests.Timeout:
        elapsed = time.time() - start_time
        log(f"\n❌ Request timed out after {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
        log(f"   This suggests the backend is stuck processing the documents")
        log(f"   Check Container App logs: az containerapp logs show -n graphrag-orchestration -g rg-graphrag-feature --follow")
        return {}
    except Exception as e:
        elapsed = time.time() - start_time
        log(f"\n❌ Request failed after {elapsed:.1f}s")
        log(f"   Error: {e}")
        log(f"   Error type: {type(e).__name__}")
        return {}


def test_queries(group_id: str):
    """Test query against indexed documents"""
    log(f"\n{'=' * 80}")
    log("🔍 [Step 5/5] TESTING QUERIES")
    log(f"{'=' * 80}\n")
    log(f"Running {len(TEST_QUERIES)} test queries against indexed data...\n")
    
    for i, query in enumerate(TEST_QUERIES, 1):
        log(f"{'─' * 80}")
        log(f"Query {i}/{len(TEST_QUERIES)}: {query}")
        log(f"{'─' * 80}")
        log(f"⏳ Sending query to: /graphrag/v3/query/local\n")
        
        query_start = time.time()
        try:
            response = requests.post(
                f"{BASE_URL}/graphrag/v3/query/local",
                headers={
                    'Content-Type': 'application/json',
                    'X-Group-ID': group_id
                },
                json={"query": query},
                timeout=60
            )
            
            query_time = time.time() - query_start
            
            if response.status_code == 200:
                result = response.json()
                log(f"✅ Query successful (took {query_time:.1f}s)\n")
                log(f"Answer:\n{result.get('answer', 'No answer')}\n")
                
                sources = result.get('sources', [])
                if sources:
                    log(f"Sources ({len(sources)}):")
                    for source in sources[:3]:
                        log(f"  • {source}")
                log(f"")
            else:
                log(f"❌ Query failed: HTTP {response.status_code} (took {query_time:.1f}s)")
                log(f"   Response: {response.text[:200]}")
                log(f"")
                
        except Exception as e:
            query_time = time.time() - query_start
            log(f"❌ Query error after {query_time:.1f}s: {e}")
            log(f"   Error type: {type(e).__name__}\n")


def main():
    """Run the full test"""
    log("=" * 80)
    log("GraphRAG v3 - PDF Test with Managed Identity")
    log("=" * 80)
    log(f"\nTest started at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    overall_start = time.time()
    
    # Step 1: Get blob URLs
    log(f"📋 Test Plan:")
    log(f"  1. Generate blob URLs (no SAS tokens)")
    log(f"  2. Index 5 PDFs with Document Intelligence")
    log(f"  3. Run 2 test queries")
    log(f"  4. Report results\n")
    
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
    
    overall_time = time.time() - overall_start
    
    log(f"\n{'=' * 80}")
    log("✅ TEST COMPLETE")
    log(f"{'=' * 80}")
    log(f"\nTest Summary:")
    log(f"  • Total execution time: {overall_time:.1f}s ({overall_time/60:.1f} minutes)")
    log(f"  • Test finished at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  • Group ID: {TEST_GROUP_ID}")
    log(f"\nNext steps:")
    log(f"  • View data in Neo4j Browser: http://neo4j-graphrag.swedencentral.azurecontainer.io:7474")
    log(f"  • Query via API: {BASE_URL}/docs")
    log(f"  • Check logs: az containerapp logs show -n graphrag-orchestration -g rg-graphrag-feature\n")


if __name__ == "__main__":
    main()
