#!/usr/bin/env python3
"""
Test invoice/contract verification with GraphRAG Orchestration
Following the standard indexing -> query workflow
"""

import requests
import json
import time
from pathlib import Path

# Configuration
API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "invoice-contract-verification"

# Load documents
DOCS_DIR = Path("/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/input_docs")

def extract_text_with_azure_di(pdf_path):
    """Extract text from PDF using Azure Document Intelligence"""
    import subprocess
    
    DI_ENDPOINT = "https://doc-intel-graphrag.cognitiveservices.azure.com"
    API_VERSION = "2024-11-30"
    
    # Get Azure token
    token_result = subprocess.run([
        "az", "account", "get-access-token",
        "--resource", "https://cognitiveservices.azure.com",
        "--query", "accessToken",
        "--output", "tsv"
    ], capture_output=True, text=True)
    
    if token_result.returncode != 0:
        return f"[Could not get Azure token for {pdf_path.name}]"
    
    token = token_result.stdout.strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/pdf"
    }
    
    # Analyze document - correct format per Microsoft docs
    analyze_url = f"{DI_ENDPOINT}/documentintelligence/documentModels/prebuilt-layout:analyze?api-version={API_VERSION}"
    
    with open(pdf_path, 'rb') as f:
        response = requests.post(analyze_url, headers=headers, data=f.read())
    
    if response.status_code != 202:
        return f"[DI analysis failed for {pdf_path.name}: {response.status_code}]"
    
    # Poll for result
    operation_location = response.headers.get("Operation-Location")
    headers_json = {"Authorization": f"Bearer {token}"}
    
    for _ in range(30):
        time.sleep(2)
        result_response = requests.get(operation_location, headers=headers_json)
        result_data = result_response.json()
        
        if result_data.get("status") == "succeeded":
            # Extract text from pages
            pages = result_data.get("analyzeResult", {}).get("pages", [])
            text = []
            for page in pages:
                for line in page.get("lines", []):
                    text.append(line.get("content", ""))
            return '\n'.join(text)
        elif result_data.get("status") == "failed":
            return f"[DI analysis failed for {pdf_path.name}]"
    
    return f"[DI timeout for {pdf_path.name}]"

def load_document_texts():
    """Load all 5 PDF documents with Azure DI extraction"""
    docs = []
    for pdf_file in sorted(DOCS_DIR.glob("*.pdf")):
        print(f"Extracting text from {pdf_file.name} with Azure DI...")
        content = extract_text_with_azure_di(pdf_file)
        print(f"  Extracted {len(content)} chars: {content[:100]}")
        docs.append({
            "id": pdf_file.stem,
            "title": pdf_file.name,
            "content": content
        })
    return docs

def test_health():
    """Check API health"""
    print("=" * 70)
    print("HEALTH CHECK")
    print("=" * 70)
    response = requests.get(f"{API_URL}/health", timeout=10)
    result = response.json()
    print(f"Status: {result.get('status')}")
    return response.status_code == 200

def index_documents(docs):
    """Index documents into GraphRAG using v3/index endpoint (matching working test format)"""
    print("\n" + "=" * 70)
    print(f"INDEXING {len(docs)} DOCUMENTS WITH V3")
    print("=" * 70)
    
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json"
    }
    
    # Format exactly like working v3 test: simple {"text": "..."} dicts
    documents = [{"text": doc["content"]} for doc in docs]
    
    print(f"Sending {len(documents)} documents to /graphrag/v3/index...")
    response = requests.post(
        f"{API_URL}/graphrag/v3/index",
        headers=headers,
        json={"documents": documents},
        timeout=180
    )
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Documents processed: {result.get('documents_processed', 0)}")
        print(f"✓ Entities created: {result.get('entities_created', 0)}")
        print(f"✓ Relationships created: {result.get('relationships_created', 0)}")
        print(f"✓ RAPTOR nodes: {result.get('raptor_nodes_created', 0)}")
        return True
    else:
        print(f"✗ Error: {response.text[:300]}")
        return False

def query_drift(query_text):
    """Query using DRIFT search (v3/query/drift endpoint)"""
    print("\n" + "=" * 70)
    print("DRIFT QUERY")
    print("=" * 70)
    print(f"Query: {query_text}")
    
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json"
    }
    
    # Using v3/query/drift endpoint
    response = requests.post(
        f"{API_URL}/graphrag/v3/query/drift",
        headers=headers,
        json={"query": query_text},
        timeout=120
    )
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        answer = result.get('answer', 'N/A')
        print(f"Answer: {answer[:300]}")
        print(f"Confidence: {result.get('confidence', 0):.2f}")
        print(f"Sources: {len(result.get('sources', []))}")
        return result
    else:
        print(f"✗ Error: {response.text[:300]}")
        return None

def main():
    print("\n" + "="*70)
    print("Invoice/Contract Verification - GraphRAG Pipeline Test")
    print("="*70)
    
    # Step 1: Health check
    if not test_health():
        print("API not healthy, exiting")
        return
    
    # Step 2: Load documents
    docs = load_document_texts()
    print(f"\nLoaded {len(docs)} documents")
    for doc in docs:
        print(f"  - {doc['title']}")
    
    # Step 3: Index documents
    if not index_documents(docs):
        print("Indexing failed, exiting")
        return
    
    # Wait for indexing to complete
    print("\nWaiting for indexing to stabilize...")
    time.sleep(5)
    
    # Step 4: Query with verification questions
    queries = [
        "What are the payment terms in the contracts?",
        "Compare invoice amounts against contract terms",
        "Identify any inconsistencies between invoices and contracts",
    ]
    
    results = []
    for query in queries:
        result = query_drift(query)
        if result:
            results.append({"query": query, "result": result})
    
    # Save results
    output_file = "/tmp/graphrag_invoice_verification_test.json"
    with open(output_file, 'w') as f:
        json.dump({
            "group_id": GROUP_ID,
            "documents": [d["title"] for d in docs],
            "queries": results
        }, f, indent=2)
    
    print(f"\n{'='*70}")
    print(f"Test complete. Results saved to: {output_file}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
