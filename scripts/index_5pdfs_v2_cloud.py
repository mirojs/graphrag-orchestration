#!/usr/bin/env python3
"""
Index 5 Test PDFs with V2 Voyage Embeddings (Cloud Indexing via API)

This script indexes the 5 standard test PDFs via the deployed Azure API,
which will store data in Azure LanceDB and Neo4j.

V2 Features:
- Voyage voyage-context-3 embeddings (2048 dimensions)
- Threshold: 0.87 (optimized for 932 edges)
- Contextual chunking
- Universal multilingual entity canonicalization

Usage:
    python3 scripts/index_5pdfs_v2_cloud.py
"""

import requests
import json
import time
import os
from pathlib import Path

# Configuration
API_BASE_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Use existing PDFs from input_docs
TEST_PDFS_DIR = Path("/afh/projects/graphrag-orchestration/graphrag-orchestration/data/input_docs")

# Available test PDFs
TEST_PDFS = [
    "purchase_contract.pdf",
    "PROPERTY MANAGEMENT AGREEMENT.pdf",
    "BUILDERS LIMITED WARRANTY.pdf",
]

def check_api_health():
    """Check if API is responding."""
    print("🔍 Checking API health...")
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=10)
        if response.status_code == 200:
            print(f"✅ API is healthy: {response.json()}")
            return True
        else:
            print(f"❌ API health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to API: {e}")
        return False

def upload_and_index_pdf(pdf_path: Path, group_id: str):
    """Upload and index a single PDF."""
    print(f"\n📄 Processing: {pdf_path.name}")
    
    # Step 1: Upload PDF
    print(f"  ⬆️  Uploading...")
    with open(pdf_path, 'rb') as f:
        files = {'file': (pdf_path.name, f, 'application/pdf')}
        headers = {'X-Group-ID': group_id}
        
        try:
            upload_response = requests.post(
                f"{API_BASE_URL}/upload",
                files=files,
                headers=headers,
                timeout=30
            )
            
            if upload_response.status_code != 200:
                print(f"  ❌ Upload failed: {upload_response.status_code}")
                print(f"     {upload_response.text}")
                return False
            
            upload_data = upload_response.json()
            document_id = upload_data.get('document_id')
            print(f"  ✅ Uploaded: document_id={document_id}")
            
        except Exception as e:
            print(f"  ❌ Upload error: {e}")
            return False
    
    # Step 2: Index the document
    print(f"  🔄 Indexing with V2 pipeline...")
    try:
        index_payload = {
            'document_id': document_id,
            'force_reindex': False
        }
        
        index_response = requests.post(
            f"{API_BASE_URL}/index",
            json=index_payload,
            headers={'X-Group-ID': group_id},
            timeout=600  # 10 minutes for indexing
        )
        
        if index_response.status_code != 200:
            print(f"  ❌ Indexing failed: {index_response.status_code}")
            print(f"     {index_response.text}")
            return False
        
        index_data = index_response.json()
        print(f"  ✅ Indexed successfully")
        print(f"     Chunks: {index_data.get('chunks_created', 'N/A')}")
        print(f"     Graph nodes: {index_data.get('graph_nodes', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Indexing error: {e}")
        return False

def main():
    print("=" * 70)
    print("V2 Cloud Indexing - Test PDFs")
    print("=" * 70)
    print(f"API: {API_BASE_URL}")
    print(f"PDFs: {TEST_PDFS_DIR}")
    print()
    
    # Check API health
    if not check_api_health():
        print("\n❌ API is not available. Exiting.")
        return 1
    
    # Generate group ID with timestamp
    timestamp = int(time.time())
    group_id = f"test-v2-{timestamp}"
    print(f"\n📦 Group ID: {group_id}")
    print("=" * 70)
    
    # Verify PDFs exist
    missing_pdfs = []
    for pdf_name in TEST_PDFS:
        pdf_path = TEST_PDFS_DIR / pdf_name
        if not pdf_path.exists():
            missing_pdfs.append(pdf_name)
    
    if missing_pdfs:
        print(f"\n❌ Missing PDFs: {missing_pdfs}")
        return 1
    
    # Index each PDF
    successful = 0
    failed = 0
    
    for pdf_name in TEST_PDFS:
        pdf_path = TEST_PDFS_DIR / pdf_name
        if upload_and_index_pdf(pdf_path, group_id):
            successful += 1
        else:
            failed += 1
        time.sleep(2)  # Rate limiting
    
    # Summary
    print("\n" + "=" * 70)
    print("Indexing Summary")
    print("=" * 70)
    print(f"✅ Successful: {successful}")
    print(f"❌ Failed: {failed}")
    print(f"📦 Group ID: {group_id}")
    print()
    
    if successful == len(TEST_PDFS):
        print("🎉 All PDFs indexed successfully!")
        print(f"\nTest query:")
        print(f'curl -X POST "{API_BASE_URL}/query" \\')
        print(f'  -H "Content-Type: application/json" \\')
        print(f'  -H "X-Group-ID: {group_id}" \\')
        print(f'  -d \'{{"question": "What are the key findings about climate change?"}}\'')
        return 0
    else:
        print("⚠️  Some PDFs failed to index")
        return 1

if __name__ == "__main__":
    exit(main())
