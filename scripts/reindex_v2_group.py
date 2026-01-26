#!/usr/bin/env python3
"""
Re-index V2 group with correct embedding_v2 property after hybrid router fix.

This script will re-index the 5 test PDFs using the deployed V2 pipeline,
which now correctly stores Voyage 2048D embeddings in embedding_v2 property.

Usage:
    # After deployment completes:
    python3 scripts/reindex_v2_group.py
"""

import requests
import time
import sys

API_URL = "https://graphrag-orchestration-sweden.proudplant-e9a97bea.swedencentral.azurecontainerapps.io"

# Use same group ID to overwrite existing data
V2_GROUP_ID = "test-5pdfs-v2-1769440005"

# 5 Test PDFs
PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS LIMITED WARRANTY.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING TANK SERVICING CONTRACT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY MANAGEMENT AGREEMENT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf",
]

def check_health():
    """Check if API is ready."""
    try:
        response = requests.get(f"{API_URL}/health", timeout=10)
        return response.status_code == 200
    except Exception:
        return False

def reindex_v2_group():
    """Re-index V2 group with correct V2 pipeline (embedding_v2)."""
    
    print("=" * 70)
    print("RE-INDEX V2 GROUP WITH CORRECT EMBEDDING_V2")
    print("=" * 70)
    print(f"API: {API_URL}")
    print(f"Group ID: {V2_GROUP_ID}")
    print(f"PDFs: {len(PDF_URLS)}")
    print()
    
    # Check health
    print("🔍 Checking API health...")
    if not check_health():
        print("❌ API not available. Is deployment complete?")
        return 1
    print("✅ API is healthy")
    print()
    
    # Submit indexing job
    print("📤 Submitting indexing job...")
    try:
        payload = {
            "documents": [{"source": url} for url in PDF_URLS],
            "reindex": True,  # Overwrite existing data
            "ingestion": "document-intelligence",
            "run_community_detection": False,
            "run_raptor": False,
        }
        
        response = requests.post(
            f"{API_URL}/hybrid/index/documents",
            json=payload,
            headers={"X-Group-ID": V2_GROUP_ID},
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"❌ Failed: {response.status_code}")
            print(response.text)
            return 1
        
        data = response.json()
        job_id = data.get("job_id")
        
        print(f"✅ Job submitted: {job_id}")
        print()
        
        # Poll for completion
        print("⏳ Waiting for indexing to complete...")
        max_wait = 600  # 10 minutes
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                status_response = requests.get(
                    f"{API_URL}/hybrid/index/status/{job_id}",
                    headers={"X-Group-ID": V2_GROUP_ID},
                    timeout=10
                )
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status = status_data.get("status")
                    progress = status_data.get("progress", "")
                    
                    print(f"   Status: {status} - {progress}")
                    
                    if status == "completed":
                        stats = status_data.get("stats", {})
                        print()
                        print("=" * 70)
                        print("✅ INDEXING COMPLETE")
                        print("=" * 70)
                        print(f"Documents: {stats.get('documents', 0)}")
                        print(f"Chunks: {stats.get('chunks', 0)}")
                        print(f"Entities: {stats.get('entities', 0)}")
                        print(f"Relationships: {stats.get('relationships', 0)}")
                        print("=" * 70)
                        print()
                        print("Next steps:")
                        print(f"  1. Run benchmark: python3 scripts/run_benchmark_route3.py {V2_GROUP_ID}")
                        print(f"  2. Compare with V1: diff bench_route3_v1_baseline.txt bench_route3_v2_fixed.txt")
                        return 0
                    
                    elif status == "failed":
                        error = status_data.get("error", "Unknown error")
                        print(f"❌ Indexing failed: {error}")
                        return 1
                
            except Exception as e:
                print(f"⚠️  Status check error: {e}")
            
            time.sleep(10)
        
        print("❌ Timeout waiting for indexing to complete")
        return 1
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(reindex_v2_group())
