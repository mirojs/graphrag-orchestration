#!/usr/bin/env python3
"""
Re-index documents with KVP extraction enabled.

This script re-indexes a subset of documents to test the KeyValue node feature.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent / "graphrag-orchestration"))

from app.hybrid.indexing.lazygraphrag_pipeline import LazyGraphRAGPipeline
from app.hybrid.services.neo4j_store import Neo4jStore
from app.services.llm_service import LLMService


async def main():
    """Re-index documents with KVP extraction."""
    
    # Configuration
    GROUP_ID = "test_kvp"
    DOCUMENTS_DIR = "graphrag-orchestration/data/input_docs"
    
    # Select documents with likely KVP content (invoices, forms)
    TEST_DOCUMENTS = [
        "contoso_lifts_invoice.pdf",  # Invoice likely has key-value pairs
        "ClaimForm_1.pdf",            # Form likely has labeled fields
    ]
    
    print("=" * 80)
    print("KeyValue Node Feature - Re-indexing Test")
    print("=" * 80)
    print(f"Group ID: {GROUP_ID}")
    print(f"Documents to index: {len(TEST_DOCUMENTS)}")
    for doc in TEST_DOCUMENTS:
        print(f"  - {doc}")
    print()
    
    # Build document list for indexing
    docs_for_pipeline = []
    for doc_name in TEST_DOCUMENTS:
        doc_path = Path(DOCUMENTS_DIR) / doc_name
        if not doc_path.exists():
            print(f"⚠️  Warning: {doc_path} not found, skipping")
            continue
        
        # Convert to absolute path for the pipeline
        abs_path = doc_path.resolve()
        docs_for_pipeline.append({
            "content": "",  # Empty, will be extracted from file
            "title": doc_name,
            "source": str(abs_path),
            "metadata": {},
        })
    
    if not docs_for_pipeline:
        print("❌ No documents found to index!")
        return
    
    print(f"✅ Found {len(docs_for_pipeline)} documents to index\n")
    
    # Initialize services
    print("Initializing services...")
    try:
        neo4j_store = Neo4jStore()
        llm_service = LLMService()
        
        pipeline = LazyGraphRAGPipeline(
            neo4j_store=neo4j_store,
            llm=llm_service.llm,
            embedder=llm_service.embed_model,
        )
        print("✅ Services initialized\n")
    except Exception as e:
        print(f"❌ Failed to initialize services: {e}")
        return
    
    # Optional: Clear existing data for this group
    print(f"Clearing existing data for group '{GROUP_ID}'...")
    try:
        with neo4j_store.driver.session(database=neo4j_store.database) as session:
            session.run(
                "MATCH (n {group_id: $group_id}) DETACH DELETE n",
                group_id=GROUP_ID
            )
        print("✅ Cleared existing data\n")
    except Exception as e:
        print(f"⚠️  Warning: Failed to clear data: {e}\n")
    
    # Run indexing
    print("Starting indexing pipeline...")
    print("-" * 80)
    
    try:
        stats = await pipeline.index_documents(
            group_id=GROUP_ID,
            documents=docs_for_pipeline,
            ingestion="url",  # File paths treated as URLs
            reindex=True,
        )
        
        print("-" * 80)
        print("\n✅ Indexing complete!")
        print("\nIndexing Statistics:")
        print(f"  Documents:        {stats.get('documents', 0)}")
        print(f"  Chunks:           {stats.get('chunks', 0)}")
        print(f"  Entities:         {stats.get('entities', 0)}")
        print(f"  Relationships:    {stats.get('relationships', 0)}")
        print(f"  Sections:         {stats.get('sections', 0)}")
        print(f"  KeyValues:        {stats.get('key_values', 0)} 🆕")
        print(f"  KVs Embedded:     {stats.get('key_values_embedded', 0)} 🆕")
        print(f"  Elapsed:          {stats.get('elapsed_s', 0):.2f}s")
        
    except Exception as e:
        print(f"\n❌ Indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Verify KeyValue nodes
    print("\n" + "=" * 80)
    print("Verifying KeyValue Nodes in Neo4j")
    print("=" * 80)
    
    try:
        with neo4j_store.driver.session(database=neo4j_store.database) as session:
            # Count total KVPs
            result = session.run(
                "MATCH (kv:KeyValue {group_id: $group_id}) RETURN count(kv) AS count",
                group_id=GROUP_ID
            )
            kvp_count = result.single()["count"]
            print(f"\nTotal KeyValue nodes: {kvp_count}")
            
            if kvp_count > 0:
                # Sample KVPs
                result = session.run(
                    """
                    MATCH (kv:KeyValue {group_id: $group_id})
                    RETURN kv.key AS key, kv.value AS value, kv.confidence AS confidence
                    LIMIT 10
                    """,
                    group_id=GROUP_ID
                )
                print("\nSample KeyValue pairs:")
                for i, record in enumerate(result, 1):
                    key = record["key"]
                    value = record["value"]
                    conf = record["confidence"]
                    print(f"  {i}. {key}: {value} (confidence: {conf:.2f})")
                
                # Check embeddings
                result = session.run(
                    """
                    MATCH (kv:KeyValue {group_id: $group_id})
                    WHERE kv.key_embedding IS NOT NULL
                    RETURN count(kv) AS embedded_count
                    """,
                    group_id=GROUP_ID
                )
                embedded_count = result.single()["embedded_count"]
                print(f"\nKeyValue nodes with embeddings: {embedded_count}/{kvp_count}")
                
                # Check relationships
                result = session.run(
                    """
                    MATCH (kv:KeyValue {group_id: $group_id})-[:IN_SECTION]->(s:Section)
                    RETURN count(DISTINCT kv) AS kvps_with_sections
                    """,
                    group_id=GROUP_ID
                )
                kvps_with_sections = result.single()["kvps_with_sections"]
                print(f"KeyValue nodes linked to sections: {kvps_with_sections}/{kvp_count}")
                
            else:
                print("\n⚠️  No KeyValue nodes created.")
                print("Possible reasons:")
                print("  - Documents don't contain labeled key-value pairs")
                print("  - Azure DI didn't extract any KVPs")
                print("  - KVP extraction failed during indexing")
        
    except Exception as e:
        print(f"\n❌ Verification failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("Re-indexing test complete!")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Test Route 1 query: POST /hybrid/query")
    print("   Example: 'What is the invoice number?'")
    print("2. Check Neo4j Browser: MATCH (kv:KeyValue) RETURN kv LIMIT 25")
    print("3. Monitor logs for 'route_1_kvp_match_found' messages")
    print()


if __name__ == "__main__":
    asyncio.run(main())
