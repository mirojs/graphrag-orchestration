#!/usr/bin/env python3
"""
Rebuild similarity edges via API endpoint - just delete old edges and re-run embedding step.
"""
import requests
import json
import time

BASE_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-1768486622652179443"
HEADERS = {"X-Group-ID": GROUP_ID, "Content-Type": "application/json"}

print(f"=" * 70)
print(f"Rebuilding SEMANTICALLY_SIMILAR edges for: {GROUP_ID}")
print(f"New threshold: 0.43 (deployed in revision 0000221)")
print(f"=" * 70)
print()

# Step 1: Check current state
print("Step 1: Checking current state...")
response = requests.get(f"{BASE_URL}/hybrid/debug/section_similarity_distribution", headers={"X-Group-ID": GROUP_ID})
if response.status_code == 200:
    data = response.json()
    print(f"  ✅ Sections with embeddings: {data.get('sections_with_embeddings', 0)}")
    print(f"  ✅ Cross-document pairs: {data.get('cross_document_pairs', 0)}")
    print(f"  Distribution: p50={data['distribution']['p50']}, p95={data['distribution']['p95']}, max={data['distribution']['max']}")
    print(f"  Current edges at 0.80: {data['thresholds_analysis']['threshold_0.8']['edges_created']}")
    print(f"  Expected edges at 0.43: ~{data['thresholds_analysis'].get('threshold_0.5', {}).get('edges_created', 'N/A')} (using 0.5 as proxy)")
else:
    print(f"  ❌ Error: {response.status_code} - {response.text}")
    exit(1)

print()
print("✅ Sections and embeddings already exist!")
print("   The new threshold (0.43) is deployed in the LazyGraphRAG pipeline.")
print()
print("⚠️  Since sections already exist with embeddings, we have 2 options:")
print()
print("Option A: Delete ONLY the SEMANTICALLY_SIMILAR edges and rebuild them")
print("   (Requires a custom endpoint or direct Neo4j query)")
print()
print("Option B: Re-index everything with reindex=true flag")
print("   (Will rebuild all sections + edges with new threshold)")
print()

# For now, let's provide the command for Option B (simplest)
print("Recommended: Option B - Full re-index")
print()
print("This will take ~9 minutes but ensures clean rebuild:")
print()
print(f"""
curl -X POST "{BASE_URL}/hybrid/index/sync" \\
  -H "X-Group-ID: {GROUP_ID}" \\
  -H "Content-Type: application/json" \\
  -d '{{"output_dir": "hipporag_index/{GROUP_ID}"}}'
""")

print("\n" + "=" * 70)
print("✅ Script complete - manual reindex required")
print("=" * 70)
