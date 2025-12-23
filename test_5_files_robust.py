#!/usr/bin/env python3
"""
Robust 5-Files Test for GraphRAG V3
1. Indexes 5 PDFs
2. Polls for completion
3. Tests Local, Global, and DRIFT search
"""
import requests
import json
import time
import sys

# Configuration
BASE_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = f"robust-test-{int(time.time())}"
STORAGE_ACCOUNT = "neo4jstorage21224"
CONTAINER = "test-docs"

PDF_FILES = [
    "contoso_lifts_invoice.pdf",
    "purchase_contract.pdf",
    "PROPERTY MANAGEMENT AGREEMENT.pdf",
    "BUILDERS LIMITED WARRANTY.pdf",
    "HOLDING TANK SERVICING CONTRACT.pdf"
]

# Generate URLs (assuming managed identity works, otherwise we need SAS)
# Using the format from test_pdfs_with_progress.py
PDF_URLS = [
    f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER}/{pdf}"
    for pdf in PDF_FILES
]

HEADERS = {
    "Content-Type": "application/json",
    "X-Group-ID": GROUP_ID
}

def log(msg):
    print(msg, flush=True)

def index_documents():
    log(f"\n{'='*50}")
    log(f"Indexing 5 Documents to Group: {GROUP_ID}")
    log(f"{'='*50}")
    
    url = f"{BASE_URL}/graphrag/v3/index"
    payload = {
        "documents": PDF_URLS,
        "ingestion": "document-intelligence",
        "run_raptor": True,
        "run_community_detection": True
    }
    
    try:
        response = requests.post(url, headers=HEADERS, json=payload, timeout=60)
        log(f"Status: {response.status_code}")
        if response.status_code == 200:
            log("Indexing started successfully.")
            return True
        else:
            log(f"Indexing failed: {response.text}")
            return False
    except Exception as e:
        log(f"Error: {e}")
        return False

def wait_for_completion(timeout_seconds=600):
    log(f"\n{'='*50}")
    log("Waiting for Indexing Completion...")
    log(f"{'='*50}")
    
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        url = f"{BASE_URL}/graphrag/v3/stats/{GROUP_ID}"
        try:
            response = requests.get(url, headers=HEADERS)
            if response.status_code == 200:
                stats = response.json()
                entities = stats.get("entities", 0)
                chunks = stats.get("text_chunks", 0)
                
                log(f"Stats: {entities} entities, {chunks} chunks... ({int(time.time() - start_time)}s)")
                
                if entities > 0:
                    log("✅ Indexing seems to have produced data!")
                    # Wait a bit more for relationships and communities
                    if stats.get("communities", 0) > 0:
                        log("✅ Communities detected!")
                        return True
                    
                    # If we have entities but no communities yet, wait a bit longer but eventually proceed
                    if time.time() - start_time > 300: # After 5 mins, if we have entities, proceed
                         log("⚠️ Timeout waiting for communities, but entities exist. Proceeding.")
                         return True
                
            else:
                log(f"Stats check failed: {response.status_code}")
        except Exception as e:
            log(f"Error checking stats: {e}")
        
        time.sleep(10)
    
    log("❌ Timeout waiting for indexing completion.")
    return False

def test_queries():
    queries = [
        ("Local", "What companies or parties are involved?", "/graphrag/v3/query/local"),
        ("Global", "What are the main themes and risks?", "/graphrag/v3/query/global"),
        ("DRIFT", "Compare invoice amount with contract amount. Is there a discrepancy?", "/graphrag/v3/query/drift")
    ]
    
    for name, query, endpoint in queries:
        log(f"\n{'='*50}")
        log(f"Testing {name} Search")
        log(f"{'='*50}")
        log(f"Query: {query}")
        
        url = f"{BASE_URL}{endpoint}"
        payload = {
            "query": query,
            "top_k": 10,
            "include_sources": True,
            "max_iterations": 5 # For DRIFT
        }
        
        try:
            start = time.time()
            response = requests.post(url, headers=HEADERS, json=payload, timeout=120)
            elapsed = time.time() - start
            log(f"Status: {response.status_code} (Time: {elapsed:.2f}s)")
            
            if response.status_code == 200:
                data = response.json()
                print(json.dumps(data, indent=2))
            else:
                log(f"Error: {response.text}")
        except Exception as e:
            log(f"Error: {e}")

if __name__ == "__main__":
    if index_documents():
        if wait_for_completion():
            test_queries()
        else:
            log("Skipping queries due to indexing timeout/failure.")
    else:
        log("Skipping queries due to indexing submission failure.")
