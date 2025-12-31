#!/usr/bin/env python3
"""
Index test documents to the deployed GraphRAG service.

This indexes a few sample documents so we can test the query endpoints.
"""

import os
import requests
import time

# Configuration
CLOUD_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
)
GROUP_ID = os.getenv("TEST_GROUP_ID", "test-3072-clean")

# Sample documents to index
TEST_DOCUMENTS = [
    {
        "title": "GraphRAG Overview",
        "content": """
GraphRAG is a structured, hierarchical approach to Retrieval Augmented Generation (RAG) 
that uses graph-based text indexing and querying. It enables better understanding of 
complex information through entity extraction, relationship mapping, and community detection.

Key features:
- Entity and relationship extraction from documents
- Knowledge graph construction
- Community detection for hierarchical summaries
- Multi-hop reasoning capabilities
- DRIFT (Dynamic Reasoning and Inference with Flexible Traversal)

GraphRAG supports multiple search methods including vector search, local search 
(entity-focused), global search (thematic), and DRIFT multi-hop reasoning.
        """.strip()
    },
    {
        "title": "Invoice #12345",
        "content": """
INVOICE

Invoice Number: #12345
Date: December 30, 2025
Due Date: January 29, 2026

Bill To:
Contoso Ltd
123 Business St
Seattle, WA 98101

From:
Vendor ABC Corp
456 Supply Ave
Portland, OR 97201

Items:
1. Office Supplies - $500.00
2. Software License - $1,200.00
3. Consulting Services - $3,000.00

Subtotal: $4,700.00
Tax (10%): $470.00
Total: $5,170.00

Payment Terms: Net 30
Payment Method: Wire Transfer

Notes: Please reference invoice #12345 when making payment.
        """.strip()
    },
    {
        "title": "Property Management Agreement",
        "content": """
PROPERTY MANAGEMENT AGREEMENT

This agreement is entered into between Contoso Ltd ("Owner") and Property Managers Inc ("Manager").

Obligations of Contoso Ltd:
1. Monthly management fee of $5,000 due on the 1st of each month
2. Maintain property insurance coverage of at least $2 million
3. Provide access to property for inspections with 24-hour notice
4. Approve all expenditures over $10,000 in writing

Obligations of Property Managers Inc:
1. Collect rent from tenants
2. Handle maintenance requests within 48 hours
3. Provide monthly financial reports
4. Maintain 24/7 emergency contact

Term: 12 months starting January 1, 2025
Termination: Either party may terminate with 30-day written notice

Governing Law: State of Washington
        """.strip()
    }
]


def index_documents():
    """Index test documents to the cloud service."""
    print("=" * 70)
    print("INDEXING TEST DOCUMENTS")
    print("=" * 70)
    print(f"Service: {CLOUD_URL}")
    print(f"Group ID: {GROUP_ID}")
    print("=" * 70)
    print()
    
    # Check health first
    try:
        response = requests.get(f"{CLOUD_URL}/health", timeout=10)
        response.raise_for_status()
        print("✓ Service health check passed")
    except Exception as e:
        print(f"✗ Service health check failed: {e}")
        return False
    
    print()
    
    # Index all documents in one batch
    try:
        # Prepare documents in the correct format
        documents = [
            {
                "text": doc["content"],
                "metadata": {
                    "title": doc["title"],
                    "source": "test_indexing",
                    "test_doc": True
                }
            }
            for doc in TEST_DOCUMENTS
        ]
        
        # Prepare request
        payload = {
            "documents": documents,
            "run_raptor": True,  # Enable RAPTOR hierarchical indexing
            "run_community_detection": True
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-Group-ID": GROUP_ID
        }
        
        print(f"Indexing {len(documents)} documents in batch...")
        
        # Send indexing request
        response = requests.post(
            f"{CLOUD_URL}/graphrag/v3/index",
            json=payload,
            headers=headers,
            timeout=180  # Indexing can take time
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ Success: {result.get('message', 'Indexed')}")
            indexed_count = len(documents)
        else:
            print(f"✗ Failed: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            indexed_count = 0
            
    except Exception as e:
        print(f"✗ Error: {e}")
        indexed_count = 0
    
    print()
    print("=" * 70)
    print(f"INDEXING COMPLETE: {indexed_count}/{len(TEST_DOCUMENTS)} documents indexed")
    print("=" * 70)
    
    if indexed_count > 0:
        print()
        print("Next steps:")
        print("  1. Run query tests:")
        print(f"     pytest tests/cloud/ -v --cloud")
        print()
        print("  2. Test queries manually:")
        print(f"     curl -X POST {CLOUD_URL}/graphrag/v3/query/local \\")
        print(f"       -H 'Content-Type: application/json' \\")
        print(f"       -H 'X-Group-ID: {GROUP_ID}' \\")
        print(f"       -d '{{\"query\": \"What is GraphRAG?\", \"top_k\": 5}}'")
    
    return indexed_count == len(TEST_DOCUMENTS)


if __name__ == "__main__":
    success = index_documents()
    exit(0 if success else 1)
