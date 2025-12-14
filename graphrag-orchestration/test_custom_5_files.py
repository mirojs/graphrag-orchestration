
import os
import json
import requests
import pypdf
from pathlib import Path

# Configuration
API_BASE_URL = "https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io"
GROUP_ID = "invoice-verification-test"
INPUT_DIR = "/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/input_docs"
SCHEMA_FILE = "/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json"

def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF file using pypdf."""
    try:
        reader = pypdf.PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return None

def run_test():
    print(f"Testing with files from: {INPUT_DIR}")
    print(f"Using schema: {SCHEMA_FILE}")
    
    # 1. Read Schema
    with open(SCHEMA_FILE, 'r') as f:
        schema_data = json.load(f)
    
    # Extract entity types from schema (simplified mapping)
    # The provided schema is for "Content Understanding" (fieldSchema), not directly GraphRAG entity specs.
    # However, we can infer we want to extract "Invoice", "Contract", "Inconsistency" entities.
    # For this test, we'll use the text content and let GraphRAG extract standard entities 
    # plus we'll pass a custom prompt or configuration if possible.
    # Since the V3 API accepts 'entity_types', we'll add relevant ones.
    
    entity_types = [
        "INVOICE", "CONTRACT", "PAYMENT_TERM", "INCONSISTENCY", 
        "ORGANIZATION", "PERSON", "DATE", "MONEY"
    ]
    
    # 2. Process Files
    documents = []
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.pdf')]
    
    print(f"Found {len(files)} PDF files.")
    
    for filename in files:
        file_path = os.path.join(INPUT_DIR, filename)
        print(f"Processing {filename}...")
        text = extract_text_from_pdf(file_path)
        
        if text:
            documents.append({
                "content": text,
                "title": filename,
                "source": filename
            })
    
    if not documents:
        print("No documents processed. Exiting.")
        return

    # 3. Send to GraphRAG
    endpoint = f"{API_BASE_URL}/graphrag/v3/index"
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json"
    }
    
    payload = {
        "documents": documents,
        "entity_types": entity_types,
        "run_raptor": True,  # Enable RAPTOR as requested/implied by "summarization" context
        "run_community_detection": True
    }
    
    print(f"Sending {len(documents)} documents to {endpoint}...")
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=600)
        
        if response.status_code == 200:
            print("✅ Indexing request successful!")
            result = response.json()
            print(json.dumps(result, indent=2))
            
            # 4. Verify Extraction
            print("\nExtraction Stats:")
            print(f"Entities: {result.get('entities_created', 0)}")
            print(f"Relationships: {result.get('relationships_created', 0)}")
            print(f"Communities: {result.get('communities_created', 0)}")
            print(f"Raptor Nodes: {result.get('raptor_nodes_created', 0)}")
            
        else:
            print(f"❌ Request failed with status {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    run_test()
