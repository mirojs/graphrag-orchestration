#!/usr/bin/env python3
"""Query GraphRAG with invoice/contract verification schema."""

import requests
import json

# Configuration
API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "phase1-5docs-1765797213"
SCHEMA_PATH = "/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json"

# Load schema to understand what to query
with open(SCHEMA_PATH) as f:
    schema = json.load(f)

print("=" * 80)
print("GRAPHRAG QUERY WITH INVOICE/CONTRACT VERIFICATION SCHEMA")
print("=" * 80)
print(f"Group ID: {GROUP_ID}")
print(f"API: {API_URL}\n")

# Extract query topics from schema
queries = [
    {
        "title": "Payment Terms Analysis",
        "query": "What are the payment terms, amounts, due dates, and payment methods mentioned in the invoices and contracts? List all payment-related information found.",
        "method": "local"  # Entity-focused search
    },
    {
        "title": "Items and Services",
        "query": "What goods, services, items, or line items are listed in the invoices and contracts? Include descriptions, quantities, prices, and product codes.",
        "method": "local"
    },
    {
        "title": "Contract vs Invoice Comparison",
        "query": "Compare the contracts and invoices. What are the key differences or potential inconsistencies in payment terms, amounts, dates, items, or services?",
        "method": "drift"  # Multi-step reasoning with max_iterations=1 for speed
    },
    {
        "title": "Document Overview",
        "query": "Summarize the main purpose and key information from all contracts, invoices, agreements, and warranties in the collection.",
        "method": "global"  # Community summaries
    }
]

for i, q in enumerate(queries, 1):
    print(f"\n{'='*80}")
    print(f"QUERY {i}: {q['title']}")
    print(f"{'='*80}")
    print(f"Method: {q['method']}")
    print(f"Question: {q['query']}\n")
    
    # Choose endpoint based on method
    if q['method'] == 'drift':
        endpoint = f"{API_URL}/graphrag/v3/query/drift"
        payload = {
            "query": q['query'],
            "max_iterations": 1,  # Reduced from 3 to 1 for faster results (~20s vs 80s)
            "include_reasoning_path": True
        }
    else:
        endpoint = f"{API_URL}/graphrag/v3/query/{q['method']}"
        payload = {
            "query": q['query'],
            "top_k": 10,
            "include_sources": True
        }
    
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers={"X-Group-ID": GROUP_ID}
        )
        
        if response.status_code != 200:
            print(f"❌ Query failed: {response.status_code}")
            print(response.text)
            continue
        
        result = response.json()
        
        print("✅ RESULTS:")
        print("-" * 80)
        
        # Display response based on type
        if 'answer' in result:
            print(f"ANSWER: {result['answer']}")
            if 'confidence' in result:
                print(f"\nConfidence: {result['confidence']:.2%}")
        elif 'response' in result:
            print(result['response'])
        
        if 'reasoning_steps' in result and result.get('reasoning_steps'):
            print("\n📊 REASONING PATH:")
            for step in result['reasoning_steps']:
                print(f"  - {step}")
        
        if 'entities_used' in result and result.get('entities_used'):
            print(f"\n🏷️  ENTITIES USED ({len(result['entities_used'])}):")
            for entity in result['entities_used'][:10]:
                print(f"  - {entity}")
        
        if 'sources' in result and result.get('sources'):
            print(f"\n📄 SOURCES ({len(result['sources'])} items):")
            for source in result['sources'][:5]:  # Show top 5
                if isinstance(source, dict):
                    name = source.get('name', source.get('title', 'Unknown'))
                    entity_type = source.get('type', '')
                    score = source.get('score', 0)
                    print(f"  - {name} ({entity_type}) [score: {score:.3f}]")
                else:
                    print(f"  - {source}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")

print(f"\n{'='*80}")
print("QUERY COMPLETE")
print(f"{'='*80}")
