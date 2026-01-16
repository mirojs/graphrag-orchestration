#!/usr/bin/env python3
"""Quick reindex script to test title extraction fix."""
import requests
import time

BASE_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS LIMITED WARRANTY.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING TANK SERVICING CONTRACT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY MANAGEMENT AGREEMENT.pdf",
]

print("Starting reindex...")
start = time.time()

# Index documents
payload = {
    "documents": [{"url": url} for url in PDF_URLS],
    "ingestion": "document-intelligence",
    "reindex": True,
}

resp = requests.post(
    f"{BASE_URL}/hybrid/index/documents",
    json=payload,
    headers={"X-Group-ID": f"test-5pdfs-{int(time.time() * 1000)}"},
    timeout=600,
)
resp.raise_for_status()
job_data = resp.json()
job_id = job_data["job_id"]
group_id = job_data["group_id"]
print(f"Job ID: {job_id}, Group ID: {group_id}")

# Poll status
while True:
    status_resp = requests.get(
        f"{BASE_URL}/hybrid/index/status/{job_id}",
        headers={"X-Group-ID": group_id},
    )
    status_resp.raise_for_status()
    status = status_resp.json()
    
    print(f"Status: {status['status']} - {status.get('progress', '')}")
    
    if status["status"] == "completed":
        elapsed = time.time() - start
        print(f"\n✅ Indexing completed in {elapsed:.1f}s")
        print(f"Group ID: {group_id}")
        break
    elif status["status"] == "failed":
        print(f"\n❌ Indexing failed: {status.get('error', 'Unknown')}")
        exit(1)
    
    time.sleep(5)
