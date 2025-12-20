#!/usr/bin/env python3
"""
GraphRAG v3 - PDF Test with Real-Time Progress Updates
Tests 5 PDFs with detailed status for each operation step
"""
import os
import requests
import json
import sys
import time
import base64
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Configuration
BASE_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
TEST_GROUP_ID = f"pdf-test-{int(time.time())}"

# Storage Account Configuration for managed identity
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


def load_pdfs() -> List[str]:
    """Generate raw blob URLs for managed identity access"""
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
    """Index documents with batch processing and detailed progress"""
    log(f"\n{'=' * 80}")
    log("🔄 INDEXING DOCUMENTS (GraphRAG v3 with Managed Identity)")
    log(f"{'=' * 80}\n")
    
    log(f"Group ID: {TEST_GROUP_ID}")
    log(f"Total PDFs: {len(blob_urls)}")
    log(f"Batch Size: 2 PDFs per request (avoid timeout)")
    log(f"Endpoint: {BASE_URL}/graphrag/v3/index\n")
    
    total_stats = {
        "documents_processed": 0,
        "entities_created": 0,
        "relationships_created": 0,
        "communities_created": 0,
        "raptor_nodes_created": 0
    }
    
    batch_size = 2
    num_batches = (len(blob_urls) + batch_size - 1) // batch_size
    
    for batch_num in range(num_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(blob_urls))
        batch = blob_urls[start_idx:end_idx]
        
        log(f"\n{'─' * 80}")
        log(f"📦 BATCH {batch_num + 1}/{num_batches}")
        log(f"{'─' * 80}")
        for url in batch:
            log(f"   • {url.split('/')[-1]}")
        
        batch_start = time.time()
        
        try:
            log(f"\n⏳ Step 1: Submitting {len(batch)} PDF URLs (managed identity)")
            
            response = requests.post(
                f"{BASE_URL}/graphrag/v3/index",
                headers={
                    'Content-Type': 'application/json',
                    'X-Group-ID': TEST_GROUP_ID
                },
                json={
                    "documents": batch,
                    "ingestion": "document-intelligence",
                    "run_raptor": True,
                    "run_community_detection": True
                },
                timeout=300  # 5 minutes
            )
            
            batch_time = time.time() - batch_start
            log(f"📥 Step 2: Received response (HTTP {response.status_code}) after {batch_time:.1f}s")
            
            try:
                result = response.json()
            except Exception as e:
                log(f"❌ Failed to parse JSON response")
                log(f"   Error: {e}")
                log(f"   Status: {response.status_code}")
                log(f"   Body: {response.text[:200]}")
                continue
            
            if response.status_code == 200:
                log(f"✅ Batch {batch_num + 1} completed successfully in {batch_time:.1f}s\n")
                log(f"   📄 Documents processed: {result.get('documents_processed', 0)}")
                log(f"   🏷️  Entities created: {result.get('entities_created', 0)}")
                log(f"   🔗 Relationships created: {result.get('relationships_created', 0)}")
                log(f"   🌐 Communities detected: {result.get('communities_created', 0)}")
                log(f"   🌳 RAPTOR nodes: {result.get('raptor_nodes_created', 0)}")
                
                for key in total_stats:
                    total_stats[key] += result.get(key, 0)
            else:
                log(f"❌ Batch {batch_num + 1} failed with HTTP {response.status_code}")
                log(f"   Error: {result.get('error', 'Unknown error')}")
        
        except requests.Timeout:
            log(f"⏱️  Batch {batch_num + 1} timed out after {time.time() - batch_start:.1f}s")
        except Exception as e:
            log(f"❌ Batch {batch_num + 1} error: {e}")
    
    log(f"\n{'=' * 80}")
    log("📊 INDEXING SUMMARY")
    log(f"{'=' * 80}")
    log(f"✅ Total documents: {total_stats['documents_processed']}")
    log(f"✅ Total entities: {total_stats['entities_created']}")
    log(f"✅ Total relationships: {total_stats['relationships_created']}")
    log(f"✅ Total communities: {total_stats['communities_created']}")
    log(f"✅ Total RAPTOR nodes: {total_stats['raptor_nodes_created']}\n")
    
    return total_stats


def test_queries(query_type: str) -> List[Dict]:
    """Test queries with progress updates"""
    log(f"\n{'=' * 80}")
    log(f"🔍 TESTING {query_type.upper()} QUERIES")
    log(f"{'=' * 80}\n")
    
    results = []
    for i, query in enumerate(TEST_QUERIES, 1):
        log(f"[{i}/{len(TEST_QUERIES)}] Query: {query}")
        log(f"⏳ Sending {query_type} query...")
        
        start = time.time()
        try:
            response = requests.post(
                f"{BASE_URL}/graphrag/v3/query/{query_type}",
                headers={'X-Group-ID': TEST_GROUP_ID},
                json={"query": query},
                timeout=90
            )
            elapsed = time.time() - start
            
            if response.status_code == 200:
                result = response.json()
                answer = result.get('answer', '')
                confidence = result.get('confidence', 0)
                log(f"✅ Response received in {elapsed:.2f}s")
                log(f"   Confidence: {confidence:.2f}")
                log(f"   Answer: {answer[:150]}...")
                results.append({"success": True, "time": elapsed, "confidence": confidence})
            else:
                log(f"❌ Failed with HTTP {response.status_code}")
                results.append({"success": False, "time": elapsed})
        except requests.Timeout:
            log(f"⏱️  Timeout after 90s")
            results.append({"success": False, "time": 90})
        except Exception as e:
            log(f"❌ Error: {e}")
            results.append({"success": False, "time": 0})
        
        log("")
    
    return results


def main():
    """Run test with detailed progress"""
    log("\n" + "=" * 80)
    log("  GraphRAG v3 - PDF Test with Progress Updates")
    log("  Testing: 5 PDFs with managed identity")
    log("=" * 80)
    
    start_time = time.time()
    
    # Step 1: Generate blob URLs
    blob_urls = load_pdfs()
    if not blob_urls:
        log("\n❌ No PDF URLs generated. Exiting.")
        sys.exit(1)
    
    # Step 2: Index documents
    stats = index_documents(blob_urls)
    if stats['documents_processed'] == 0:
        log("\n❌ Indexing failed. Skipping queries.")
        sys.exit(1)
    
    # Wait for propagation
    log("\n⏳ Waiting 5 seconds for Neo4j data propagation...")
    time.sleep(5)
    
    # Step 3: Test DRIFT queries
    drift_results = test_queries("drift")
    
    # Step 4: Test local queries
    local_results = test_queries("local")
    
    # Final summary
    total_time = time.time() - start_time
    log(f"\n{'=' * 80}")
    log("🎉 TEST COMPLETE")
    log(f"{'=' * 80}")
    log(f"Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
    log(f"Documents indexed: {stats['documents_processed']}")
    log(f"Entities created: {stats['entities_created']}")
    log(f"DRIFT queries: {sum(1 for r in drift_results if r['success'])}/{len(drift_results)} successful")
    log(f"Local queries: {sum(1 for r in local_results if r['success'])}/{len(local_results)} successful")
    log("")


if __name__ == "__main__":
    main()
