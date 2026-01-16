#!/usr/bin/env python3
"""
Rebuild the test-5pdfs group with new HippoRAG 2 similarity threshold.
"""

import requests
import time
import json

BASE_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-1768486622652179443"
HEADERS = {"X-Group-ID": GROUP_ID}

print(f"🗑️  Step 1: Deleting existing graph for group {GROUP_ID}...")
delete_resp = requests.post(f"{BASE_URL}/hybrid/clear", headers=HEADERS)
print(f"   Status: {delete_resp.status_code}")
if delete_resp.status_code == 200:
    print(f"   Response: {delete_resp.json()}")
else:
    print(f"   Response: {delete_resp.text}")

print("\n⏳ Waiting 5 seconds for cleanup to complete...")
time.sleep(5)

print(f"\n📊 Step 2: Triggering sync to rebuild from Neo4j...")
sync_resp = requests.post(
    f"{BASE_URL}/hybrid/index/sync",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={"output_dir": f"hipporag_index/{GROUP_ID}"}
)
print(f"   Status: {sync_resp.status_code}")
print(f"   Response: {json.dumps(sync_resp.json(), indent=2)}")

print("\n✅ Rebuild complete! The new threshold (0.43) will be applied on next indexing.")
print("   Note: Section similarity edges are built during document indexing, not sync.")
print("   You may need to re-index documents to rebuild the SEMANTICALLY_SIMILAR edges.")
