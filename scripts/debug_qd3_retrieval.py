#!/usr/bin/env python3
"""Debug Q-D3 retrieval: Compare what the 0.80 run got vs current runs."""

import requests
import json

API_BASE = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-5pdfs-1768557493369886422"
QUERY = 'Compare "time windows" across the set: list all explicit day-based timeframes.'

def query_api(query_text: str, force_route: str = "drift_multi_hop"):
    """Query the API and return full response with metadata."""
    url = f"{API_BASE}/hybrid/query"
    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": GROUP_ID,
    }
    payload = {
        "query": query_text,
        "response_type": "summary",
        "force_route": force_route,
    }
    
    print(f"\n{'='*70}")
    print(f"Query: {query_text[:60]}...")
    print(f"Route: {force_route}")
    print(f"{'='*70}")
    
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    response.raise_for_status()
    
    data = response.json()
    
    # Extract key metrics
    answer = data.get("answer", "")
    citations = data.get("citations", [])
    metadata = data.get("metadata", {})
    evidence_path = data.get("evidence_path", [])
    
    print(f"\n📊 RESULTS:")
    print(f"  Response length: {len(answer)} chars")
    if answer:
        print(f"  Answer preview: {answer[:200]}...")
    else:
        print(f"  No answer generated!")
    print(f"  Citation count: {len(citations)}")
    unique_docs = set(c.get("source_doc", "unknown") for c in citations)
    print(f"  Unique docs: {len(unique_docs)}")
    print(f"    → {list(unique_docs)[:8]}")
    
    # Show evidence path stages
    if evidence_path:
        print(f"\n🔍 EVIDENCE PATH:")
        for stage in evidence_path:
            stage_name = stage.get("stage", "unknown")
            count = stage.get("count", 0)
            items = stage.get("items", [])
            print(f"  {stage_name}: {count} items")
            if items and len(items) <= 10:
                for item in items[:10]:
                    print(f"    - {item}")
            elif items:
                print(f"    - {items[0]}")
                print(f"    - ... ({len(items)-2} more)")
                print(f"    - {items[-1]}")
    else:
        print(f"\n🔍 EVIDENCE PATH: Not available")
    
    # Show what entities/seeds were found
    if "seeds" in metadata:
        print(f"\n🌱 SEEDS:")
        print(f"  Count: {len(metadata['seeds'])}")
        print(f"    → {metadata['seeds'][:10]}")
    
    if "entities_retrieved" in metadata:
        print(f"\n🎯 ENTITIES RETRIEVED:")
        print(f"  Count: {len(metadata['entities_retrieved'])}")
        print(f"    → {metadata['entities_retrieved'][:10]}")
    
    # Show citation breakdown
    if citations:
        print(f"\n📚 CITATIONS BY DOCUMENT:")
        doc_groups = {}
        for cit in citations:
            doc = cit.get("source_doc", "unknown")
            doc_groups[doc] = doc_groups.get(doc, 0) + 1
        
        for doc, count in sorted(doc_groups.items(), key=lambda x: -x[1])[:10]:
            print(f"  - {doc}: {count} chunks")
    
    return data


if __name__ == "__main__":
    print("\n" + "="*70)
    print("Q-D3 RETRIEVAL DEBUG")
    print("="*70)
    
    # Run the query
    result = query_api(QUERY)
    
    print("\n" + "="*70)
    print("✓ Debug complete")
    print("="*70)
