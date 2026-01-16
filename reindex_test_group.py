#!/usr/bin/env python3
"""
Reindex the test-5pdfs group to rebuild SEMANTICALLY_SIMILAR edges with new threshold (0.43).
"""
import asyncio
import sys
from app.services.graph_service import GraphService
from app.hybrid.indexing.lazygraphrag_pipeline import LazyGraphRAGPipeline
from app.core.config import settings

GROUP_ID = "test-5pdfs-1768486622652179443"


async def clear_group_data():
    """Delete all data for the test group."""
    graph_service = GraphService()
    
    with graph_service.driver.session(database=graph_service.database) as session:
        # Get count before deletion
        result = session.run(
            """
            MATCH (n {group_id: $group_id})
            RETURN count(n) as node_count
            """,
            group_id=GROUP_ID
        )
        count = result.single()["node_count"]
        print(f"Found {count} nodes to delete for group {GROUP_ID}")
        
        # Delete all nodes and relationships
        session.run(
            """
            MATCH (n {group_id: $group_id})
            DETACH DELETE n
            """,
            group_id=GROUP_ID
        )
        print(f"✅ Deleted all data for group {GROUP_ID}")


async def get_documents_from_blob():
    """Get the 5 PDF documents from blob storage."""
    # These are the 5 PDFs mentioned in the handover
    # We'll need to get them from the blob storage or re-upload
    print("⚠️  Document retrieval from blob storage not implemented")
    print("   You'll need to re-upload the 5 PDFs through the API")
    return []


async def main():
    print(f"🔄 Re-indexing test group: {GROUP_ID}")
    print(f"   New similarity threshold: 0.43 (was 0.80)")
    print()
    
    # Step 1: Clear existing data
    print("Step 1: Clearing existing group data...")
    await clear_group_data()
    print()
    
    # Step 2: Re-index (would need document URLs/content)
    print("Step 2: Re-indexing...")
    print("   ⚠️  Manual step required:")
    print("   Use the /hybrid/index/documents endpoint with the 5 PDFs")
    print()
    print("   Example curl command:")
    print(f"""
   curl -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/index/documents" \\
     -H "X-Group-ID: {GROUP_ID}" \\
     -H "Content-Type: application/json" \\
     -d '{{
       "documents": [
         {{"source": "url_to_warranty.pdf"}},
         {{"source": "url_to_property_mgmt.pdf"}},
         {{"source": "url_to_holding_tank.pdf"}},
         {{"source": "url_to_purchase.pdf"}},
         {{"source": "url_to_invoice.pdf"}}
       ],
       "reindex": true
     }}'
    """)


if __name__ == "__main__":
    asyncio.run(main())
