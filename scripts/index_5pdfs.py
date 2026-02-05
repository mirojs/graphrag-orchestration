#!/usr/bin/env python3
"""
Index 5 Test PDFs with Azure Document Intelligence

Indexes 5 standard test PDFs to the hybrid GraphRAG service:
- BUILDERS LIMITED WARRANTY.pdf
- HOLDING TANK SERVICING CONTRACT.pdf
- PROPERTY MANAGEMENT AGREEMENT.pdf
- contoso_lifts_invoice.pdf
- purchase_contract.pdf

Features:
- Document date extraction (stored in Document.date)
- HippoRAG artifact sync
- Multi-tenant via X-Group-ID header

Usage:
    # Fresh indexing (creates new group ID)
    python3 scripts/index_5pdfs.py

    # Re-index existing group
    export GROUP_ID=test-5pdfs-1768557493369886422
    python3 scripts/index_5pdfs.py
"""

import os
import requests
import time

# Configuration
BASE_URL = os.getenv(
    "BASE_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

# Allow overriding via env var for re-indexing
GROUP_ID_FROM_ENV = os.getenv("GROUP_ID")
GROUP_ID = GROUP_ID_FROM_ENV or f"test-5pdfs-{time.time_ns()}"

# If reusing an existing group, enable reindex mode
REINDEX = bool(GROUP_ID_FROM_ENV)

PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS LIMITED WARRANTY.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING TANK SERVICING CONTRACT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY MANAGEMENT AGREEMENT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf",
]

HEADERS = {"Content-Type": "application/json", "X-Group-ID": GROUP_ID}


def log(msg):
    """Print with flush for real-time output"""
    print(msg, flush=True)


def persist_group_id(group_id: str) -> None:
    """Save group ID for future reference."""
    try:
        with open("last_test_group_id.txt", "w") as f:
            f.write(group_id)
        log(f"💾 Saved group ID to: last_test_group_id.txt")
    except Exception as e:
        log(f"⚠️ Could not save group ID: {e}")


def index_documents():
    """Index the 5 PDFs (async with polling)"""
    log("\n" + "="*80)
    log("INDEXING 5 TEST PDFs")
    log("="*80)
    log(f"Service: {BASE_URL}")
    log(f"Group ID: {GROUP_ID}")
    
    if REINDEX:
        log("🔄 Reindex mode: Will clean existing data first\n")
    else:
        log("✨ Fresh group: Creating new index\n")
    
    log("Documents:")
    for i, url in enumerate(PDF_URLS, 1):
        name = url.split('/')[-1].replace('%20', ' ')
        log(f"  [{i}/5] {name}")
    
    payload = {
        "documents": [{"url": url} for url in PDF_URLS],
        "ingestion": "document-intelligence",
        "run_raptor": False,
        "run_community_detection": False,
        "max_triplets_per_chunk": 20,
        "reindex": REINDEX,
    }
    
    try:
        log("\n⏳ Starting indexing job...")
        start = time.time()
        
        # Start indexing job
        response = requests.post(
            f"{BASE_URL}/hybrid/index/documents",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )
        
        if response.status_code != 200:
            log(f"❌ Failed to start indexing: HTTP {response.status_code}")
            log(f"   {response.text[:500]}")
            return False
        
        result = response.json()
        job_id = result.get("job_id")
        log(f"✅ Job started: {job_id}")
        
        # Poll for completion
        log("\n⏳ Polling for completion (max 15 minutes)...")
        poll_interval = 2
        max_wait = 900
        
        while time.time() - start < max_wait:
            time.sleep(poll_interval)
            elapsed = int(time.time() - start)
            
            try:
                status_resp = requests.get(
                    f"{BASE_URL}/hybrid/index/status/{job_id}",
                    headers=HEADERS,
                    timeout=10,
                )
                
                if status_resp.status_code != 200:
                    log(f"⚠️  [{elapsed}s] Status check failed: HTTP {status_resp.status_code}")
                    continue
                
                status = status_resp.json()
                job_status = status.get("status")
                progress = status.get("progress", "")
                
                if job_status == "completed":
                    elapsed_time = time.time() - start
                    log(f"\n✅ Indexing complete! (took {elapsed_time:.1f}s)")
                    
                    stats = status.get("stats", {})
                    if stats:
                        log("\nIndexing Statistics:")
                        log(f"  Documents:     {stats.get('documents', 0)}")
                        log(f"  Chunks:        {stats.get('chunks', 0)}")
                        log(f"  Entities:      {stats.get('entities', 0)}")
                        log(f"  Relationships: {stats.get('relationships', 0)}")
                        log(f"  Communities:   {stats.get('communities', 0)}")
                        
                        if stats.get('chunks', 0) == 0:
                            log("\n❌ WARNING: 0 chunks indexed!")
                            return False
                    return True
                    
                elif job_status == "failed":
                    log(f"\n❌ Indexing failed: {status.get('error', 'Unknown error')}")
                    return False
                    
                else:
                    log(f"⏳ [{elapsed}s] {job_status}: {progress}")
                    
            except Exception as e:
                log(f"⏳ [{elapsed}s] Polling... ({str(e)[:50]})")
        
        log(f"\n❌ Timeout after {max_wait}s")
        return False
        
    except Exception as e:
        log(f"\n❌ Error during indexing: {e}")
        return False


def sync_hipporag():
    """Sync and initialize HippoRAG artifacts"""
    log("\n" + "="*80)
    log("SYNCING HIPPORAG ARTIFACTS")
    log("="*80)
    
    try:
        # Sync HippoRAG artifacts from Neo4j
        log("⏳ Syncing HippoRAG artifacts from Neo4j...")
        sync_response = requests.post(
            f"{BASE_URL}/hybrid/index/sync",
            headers=HEADERS,  # Already includes X-Group-ID
            json={"output_dir": "./hipporag_index", "dry_run": False},
            timeout=300,
        )
        
        if sync_response.status_code != 200:
            log(f"❌ Sync failed: HTTP {sync_response.status_code}")
            log(f"   {sync_response.text[:500]}")
            return False
        
        sync_result = sync_response.json()
        log(f"✅ Sync complete: {sync_result.get('message', 'Success')}")
        
        if 'entities' in sync_result:
            log(f"   Entities:    {sync_result.get('entities', 0)}")
            log(f"   Text chunks: {sync_result.get('text_chunks', 0)}")
        
        # Initialize HippoRAG retriever
        log("\n⏳ Initializing HippoRAG retriever...")
        init_response = requests.post(
            f"{BASE_URL}/hybrid/index/initialize-hipporag",
            headers=HEADERS,  # Already includes X-Group-ID
            timeout=180,
        )
        
        if init_response.status_code != 200:
            log(f"❌ HippoRAG init failed: HTTP {init_response.status_code}")
            log(f"   {init_response.text[:500]}")
            return False
        
        log("✅ HippoRAG initialized successfully")
        return True
        
    except Exception as e:
        log(f"❌ Error during HippoRAG sync: {e}")
        return False


def main():
    """Main execution"""
    log("\n" + "="*80)
    log("5-PDF INDEXING SCRIPT")
    log("="*80)
    log(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Step 1: Index documents
    if not index_documents():
        log("\n❌ Indexing failed. Aborting.")
        return 1
    
    # Step 2: Sync HippoRAG artifacts
    if not sync_hipporag():
        log("\n❌ HippoRAG sync failed. Aborting.")
        return 1
    
    # Save group ID for future reference
    persist_group_id(GROUP_ID)
    
    # Success
    log("\n" + "="*80)
    log("✅ INDEXING COMPLETE")
    log("="*80)
    log(f"\nGroup ID: {GROUP_ID}")
    log("\nNext steps:")
    log("  - Run benchmarks: python3 scripts/benchmark_route4_drift_multi_hop.py")
    log(f"  - Test queries: Set X-Group-ID header to '{GROUP_ID}'")
    log("\n" + "="*80)
    
    return 0


if __name__ == "__main__":
    exit(main())
