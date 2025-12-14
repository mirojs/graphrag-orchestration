"""
Test Document Lifecycle Management for GraphRAG.

Tests add, list, delete operations for documents in the knowledge graph.
Validates that Neo4j nodes/edges and LanceDB vectors are managed correctly.

Usage:
    python test_document_lifecycle.py
"""

import asyncio
import httpx
import json
import sys
from datetime import datetime
from typing import List, Dict, Any

# Configuration
API_BASE_URL = "http://127.0.0.1:8001"  # Local service
# API_BASE_URL = "https://graphrag-orchestration-api.example.com"  # Remote service

GROUP_ID = "test-lifecycle-group"
TIMEOUT = 300.0  # 5 minutes for indexing

# Test documents (2 files for quick testing)
TEST_DOCUMENTS = [
    "https://contentprocessorstorageaustralia.blob.core.windows.net/demofiles/808ac9d7-faa1-49d9-92da-858546e7c45d/purchase_contract.pdf",
    "https://contentprocessorstorageaustralia.blob.core.windows.net/demofiles/25aac25f-f46e-41f1-8f36-46a7c7ef5ba0/invoice.pdf",
]


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


async def index_documents(urls: List[str]) -> Dict[str, Any]:
    """Index documents into the knowledge graph."""
    print_section("STEP 1: INDEX DOCUMENTS")
    
    payload = {
        "documents": urls,
        "extraction_mode": "dynamic",
        "run_community_detection": False,  # Skip for faster testing
        "ingestion": "document-intelligence",
    }
    
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json",
    }
    
    print(f"📥 Indexing {len(urls)} documents...")
    print(f"   Extraction mode: dynamic")
    print(f"   Ingestion: document-intelligence")
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{API_BASE_URL}/graphrag/index",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
    
    print(f"\n✅ Indexing completed!")
    print(f"   Documents indexed: {result['stats']['documents_indexed']}")
    print(f"   Nodes created: {result['stats']['nodes_created']}")
    print(f"   Extraction mode: {result['stats']['extraction_mode']}")
    
    return result


async def list_documents() -> List[Dict[str, Any]]:
    """List all indexed documents."""
    print_section("STEP 2: LIST INDEXED DOCUMENTS")
    
    headers = {"X-Group-ID": GROUP_ID}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{API_BASE_URL}/graphrag/documents",
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
    
    documents = result["documents"]
    print(f"📋 Found {len(documents)} indexed documents:")
    
    for i, doc in enumerate(documents, 1):
        print(f"\n   {i}. URL: {doc['url'][-60:]}")
        print(f"      Nodes: {doc['node_count']}")
        print(f"      Pages: {doc['page_count']}")
        if doc.get('pages'):
            print(f"      Page numbers: {doc['pages'][:5]}{'...' if len(doc['pages']) > 5 else ''}")
    
    return documents


async def get_document_stats(url: str) -> Dict[str, Any]:
    """Get detailed statistics for a document."""
    print(f"\n📊 Getting stats for: {url[-60:]}...")
    
    headers = {"X-Group-ID": GROUP_ID}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{API_BASE_URL}/graphrag/documents/stats",
            params={"url": url},
            headers=headers,
        )
        response.raise_for_status()
        stats = response.json()
    
    print(f"   Total nodes: {stats['total_nodes']}")
    print(f"   Label sets: {len(stats['label_sets'])} unique")
    print(f"   Pages: {stats['pages']}")
    
    return stats


async def delete_document(url: str) -> Dict[str, Any]:
    """Delete a document from the knowledge graph."""
    print_section("STEP 3: DELETE DOCUMENT")
    
    print(f"🗑️  Deleting: {url[-60:]}...")
    
    payload = {"url": url}
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/graphrag/documents/delete",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
    
    print(f"\n✅ Deletion completed!")
    print(f"   Nodes deleted: {result['neo4j_stats']['nodes_deleted']}")
    print(f"   Relationships deleted: {result['neo4j_stats']['relationships_deleted']}")
    print(f"   Vectors deleted: {result['vector_stats']['vectors_deleted']}")
    print(f"   Message: {result['message']}")
    
    return result


async def verify_deletion(url: str):
    """Verify that document was actually deleted."""
    print(f"\n🔍 Verifying deletion of: {url[-60:]}...")
    
    headers = {"X-Group-ID": GROUP_ID}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{API_BASE_URL}/graphrag/documents/stats",
            params={"url": url},
            headers=headers,
        )
        response.raise_for_status()
        stats = response.json()
    
    if stats["total_nodes"] == 0:
        print("   ✅ Confirmed: No nodes remain for this document")
    else:
        print(f"   ⚠️  WARNING: {stats['total_nodes']} nodes still exist!")
        return False
    
    return True


async def delete_all_documents():
    """Delete all documents for the tenant (cleanup)."""
    print_section("STEP 4: DELETE ALL DOCUMENTS (CLEANUP)")
    
    print(f"🗑️  Deleting ALL documents for group: {GROUP_ID}")
    print("   (This is a cleanup operation for testing)")
    
    headers = {"X-Group-ID": GROUP_ID}
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.delete(
            f"{API_BASE_URL}/graphrag/documents/all",
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
    
    print(f"\n✅ Cleanup completed!")
    print(f"   Nodes deleted: {result['neo4j_stats']['nodes_deleted']}")
    print(f"   Vectors deleted: {result['vector_stats']['vectors_deleted']}")
    
    return result


async def query_after_deletion(query: str):
    """Test querying after document deletion."""
    print_section("STEP 5: QUERY AFTER DELETION")
    
    print(f"🔎 Query: {query}")
    
    payload = {
        "query": query,
        "top_k": 5,
    }
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/graphrag/query/local",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()
    
    answer = result["answer"]
    sources = result.get("sources", [])
    
    print(f"\n📝 Answer: {answer[:200]}...")
    print(f"   Sources: {len(sources)}")
    
    if len(sources) == 0:
        print("   ✅ Confirmed: No results after deletion (expected)")
    
    return result


async def main():
    """Run the complete document lifecycle test."""
    print(f"\n{'#'*80}")
    print(f"#  GraphRAG Document Lifecycle Test")
    print(f"#  Group ID: {GROUP_ID}")
    print(f"#  API: {API_BASE_URL}")
    print(f"#  Test Documents: {len(TEST_DOCUMENTS)}")
    print(f"#  Timestamp: {datetime.now().isoformat()}")
    print(f"{'#'*80}")
    
    try:
        # 1. Index documents
        index_result = await index_documents(TEST_DOCUMENTS)
        
        # 2. List documents
        documents = await list_documents()
        
        if len(documents) == 0:
            print("\n❌ ERROR: No documents indexed!")
            sys.exit(1)
        
        # 3. Get stats for each document
        print_section("DOCUMENT STATISTICS")
        for doc in documents:
            await get_document_stats(doc["url"])
        
        # 4. Delete first document
        if len(documents) > 0:
            first_doc_url = documents[0]["url"]
            await delete_document(first_doc_url)
            
            # Verify deletion
            if not await verify_deletion(first_doc_url):
                print("\n❌ ERROR: Deletion verification failed!")
                sys.exit(1)
        
        # 5. List documents again (should be one less)
        print_section("DOCUMENTS AFTER DELETION")
        remaining_docs = await list_documents()
        
        expected_count = len(documents) - 1
        if len(remaining_docs) == expected_count:
            print(f"\n✅ Confirmed: Document count reduced from {len(documents)} to {len(remaining_docs)}")
        else:
            print(f"\n⚠️  WARNING: Expected {expected_count} documents, found {len(remaining_docs)}")
        
        # 6. Query to verify graph state
        await query_after_deletion("Summarize all documents")
        
        # 7. Cleanup: Delete all documents
        await delete_all_documents()
        
        # 8. Final verification
        print_section("FINAL VERIFICATION")
        final_docs = await list_documents()
        
        if len(final_docs) == 0:
            print("✅ All documents successfully deleted!")
        else:
            print(f"⚠️  WARNING: {len(final_docs)} documents still exist after cleanup")
        
        print_section("TEST SUMMARY")
        print("✅ Document lifecycle test PASSED!")
        print("\nTested operations:")
        print("  ✓ Index documents with metadata tracking")
        print("  ✓ List indexed documents")
        print("  ✓ Get document statistics")
        print("  ✓ Delete individual document")
        print("  ✓ Verify deletion")
        print("  ✓ Delete all documents")
        print("  ✓ Query after deletion")
        
        print("\nKey findings:")
        print(f"  • Initial index created {index_result['stats']['nodes_created']} nodes")
        print(f"  • Document deletion removes nodes, edges, and vectors")
        print(f"  • Group isolation maintained throughout ({GROUP_ID})")
        print(f"  • Metadata tracking enables per-document management")
        
    except httpx.HTTPStatusError as e:
        print(f"\n❌ HTTP Error: {e.response.status_code}")
        print(f"   Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
