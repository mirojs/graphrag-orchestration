#!/usr/bin/env python3
"""Check indexed documents via HippoRAG sync."""
import requests

BASE_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-1768558518157"

print(f"\nSyncing HippoRAG for group: {GROUP_ID}")
resp = requests.post(
    f"{BASE_URL}/hybrid/hippo/sync",
    json={},
    headers={"X-Group-ID": GROUP_ID},
    timeout=300,
)

if resp.status_code == 200:
    data = resp.json()
    print(f"✅ Sync completed")
    print(f"   Documents: {data.get('documents_processed', 0)}")
    print(f"   Chunks: {data.get('chunks_processed', 0)}")
    print(f"   Entities: {data.get('entities_processed', 0)}")
    
    # Show summary
    summary = data.get("summary", {})
    if "documents" in summary:
        print(f"\n📄 Document Titles:")
        for doc_title in summary.get("documents", []):
            print(f"   • {doc_title}")
else:
    print(f"❌ Error: {resp.status_code}")
    print(resp.text)
