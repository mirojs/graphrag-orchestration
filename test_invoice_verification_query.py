#!/usr/bin/env python3
"""
Test invoice/contract verification schema with GraphRAG Orchestration
"""

import requests
import json
from pathlib import Path

# GraphRAG Orchestration endpoint
API_BASE = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-invoice-verification"

def test_health():
    """Check if API is responding"""
    response = requests.get(f"{API_BASE}/health")
    print(f"Health: {response.json()}")
    return response.status_code == 200

def load_schema():
    """Load the invoice verification schema"""
    schema_path = Path("/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json")
    with open(schema_path) as f:
        return json.load(f)

def query_with_schema(query_text, schema):
    """Query GraphRAG with structured schema"""
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json"
    }
    
    payload = {
        "query": query_text,
        "schema": schema  # Pass schema for structured extraction
    }
    
    # Try DRIFT endpoint
    print(f"\nQuerying DRIFT endpoint...")
    response = requests.post(
        f"{API_BASE}/graphrag/v3/query/drift",
        headers=headers,
        json=payload,
        timeout=120
    )
    
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.text[:500]}")
        return None

def main():
    print("="*70)
    print("Invoice/Contract Verification with GraphRAG")
    print("="*70)
    
    # Health check
    if not test_health():
        print("API not responding")
        return
    
    # Load schema
    schema = load_schema()
    print(f"\nSchema loaded: {schema['fieldSchema']['name']}")
    
    # Query with invoice/contract verification intent
    query = """
    Compare the following documents and identify any inconsistencies:
    - Invoice from Contoso Lifts
    - Purchase contracts
    - Service agreements
    
    Check for discrepancies in:
    - Payment terms
    - Item descriptions and quantities
    - Billing addresses
    """
    
    result = query_with_schema(query, schema)
    
    if result:
        print("\n" + "="*70)
        print("Query Result:")
        print("="*70)
        print(json.dumps(result, indent=2))
        
        # Save result
        output_file = "/tmp/graphrag_invoice_verification_result.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nResult saved to: {output_file}")

if __name__ == "__main__":
    main()
