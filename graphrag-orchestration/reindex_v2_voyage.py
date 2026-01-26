#!/usr/bin/env python3
"""
V2 Reindex Script - Voyage Contextual Embeddings + Multilingual Support

This script reindexes the 5 benchmark PDFs using V2 features:
- Voyage voyage-context-3 embeddings (2048 dimensions)
- Universal multilingual entity canonicalization
- Section-aware chunking with language propagation
- Q-D8 document counting fix (synthesis patterns)
- Bin-packing for large documents (>32k tokens)

Usage:
    python reindex_v2_voyage.py [--dry-run]
"""

import asyncio
import os
import sys
import time
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.config import settings

# Verify Voyage is configured
if not settings.VOYAGE_API_KEY:
    print("❌ VOYAGE_API_KEY not configured in .env")
    print("   Add: VOYAGE_API_KEY=your_api_key")
    sys.exit(1)

if not settings.VOYAGE_V2_ENABLED:
    print("❌ VOYAGE_V2_ENABLED not set to True")
    print("   Add: VOYAGE_V2_ENABLED=true")
    sys.exit(1)

print(f"✅ Voyage configured: model={settings.VOYAGE_MODEL_NAME}, dim={settings.VOYAGE_EMBEDDING_DIM}")

# 5 Benchmark PDFs
TEST_PDFS = [
    "https://afhazstorage.blob.core.windows.net/source-docs/BUILDERS%20LIMITED%20WARRANTY.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/contoso_lifts_invoice.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/purchase_contract.pdf",
]


async def run_reindex(group_id: str, dry_run: bool = False):
    """Run V2 reindexing with Voyage embeddings."""
    from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3
    from app.hybrid_v2.indexing.lazygraphrag_pipeline import (
        LazyGraphRAGIndexingPipeline,
        LazyGraphRAGIndexingConfig,
    )
    from app.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
    from llama_index.llms.azure_openai import AzureOpenAI
    
    print(f"\n🔄 V2 Reindex: group_id={group_id}")
    print(f"   Features: Voyage {settings.VOYAGE_MODEL_NAME} ({settings.VOYAGE_EMBEDDING_DIM}D)")
    print(f"             Multilingual entity canonicalization")
    print(f"             Section-aware chunking with language")
    print(f"             Q-D8 document counting fix")
    print(f"   Dry run: {dry_run}")
    print()
    
    # Initialize services
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE or "neo4j",
    )
    
    # LLM for entity extraction
    llm = AzureOpenAI(
        deployment_name=settings.AZURE_OPENAI_INDEXING_DEPLOYMENT or settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )
    
    # V2 Voyage embedder
    voyage_embed_service = VoyageEmbedService(
        model_name=settings.VOYAGE_MODEL_NAME,
        api_key=settings.VOYAGE_API_KEY,
    )
    
    # Pipeline config for V2
    config = LazyGraphRAGIndexingConfig(
        chunk_size=512,
        chunk_overlap=64,
        embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,  # 2048 for Voyage
        use_native_extractor=True,  # Use neo4j-graphrag extractor
    )
    
    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=llm,
        embedder=voyage_embed_service,  # V2 Voyage embeddings
        config=config,
        use_v2_embedding_property=True,  # Store in embedding_v2 property
    )
    
    # Prepare documents
    documents = [{"source": url} for url in TEST_PDFS]
    
    print(f"📄 Documents to index: {len(documents)}")
    for i, doc in enumerate(documents, 1):
        print(f"   {i}. {doc['source'].split('/')[-1]}")
    print()
    
    if dry_run:
        print("🔍 DRY RUN - Not indexing")
        return {"dry_run": True, "documents": len(documents)}
    
    # Run indexing
    print("🚀 Starting V2 indexing...")
    start_time = time.time()
    
    stats = await pipeline.index_documents(
        group_id=group_id,
        documents=documents,
        reindex=True,  # Clear existing data first
        ingestion="document-intelligence",  # Use Azure DI
    )
    
    elapsed = time.time() - start_time
    
    print()
    print("=" * 60)
    print("📊 V2 Indexing Results:")
    print("=" * 60)
    print(f"   Group ID: {group_id}")
    print(f"   Documents: {stats.get('documents', 0)}")
    print(f"   Chunks: {stats.get('chunks', 0)}")
    print(f"   Entities: {stats.get('entities', 0)}")
    print(f"   Relationships: {stats.get('relationships', 0)}")
    print(f"   Sections: {stats.get('sections', 0)}")
    print(f"   Section edges: {stats.get('section_edges', 0)}")
    print(f"   Semantic similarity edges: {stats.get('semantic_similarity_edges', 0)}")
    print(f"   Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    
    if stats.get("skipped"):
        print(f"   ⚠️  Skipped: {stats['skipped']}")
    
    return stats


async def verify_v2_index(group_id: str):
    """Verify V2 index has embedding_v2 properties."""
    from neo4j import GraphDatabase
    
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
    )
    
    with driver.session(database=settings.NEO4J_DATABASE or "neo4j") as session:
        # Check embedding_v2 coverage
        result = session.run(
            """
            MATCH (c:TextChunk {group_id: $group_id})
            RETURN 
                count(c) AS total_chunks,
                count(c.embedding_v2) AS with_v2_embedding,
                count(c.embedding) AS with_v1_embedding
            """,
            group_id=group_id,
        )
        record = result.single()
        
        total = record["total_chunks"]
        v2_count = record["with_v2_embedding"]
        v1_count = record["with_v1_embedding"]
        
        print()
        print("🔍 V2 Index Verification:")
        print(f"   Total chunks: {total}")
        print(f"   With embedding_v2: {v2_count} ({100*v2_count/total:.1f}%)" if total else "   No chunks")
        print(f"   With embedding (v1): {v1_count}")
        
        # Check Document nodes
        result = session.run(
            """
            MATCH (d:Document {group_id: $group_id})
            RETURN count(d) AS doc_count, collect(d.title) AS titles
            """,
            group_id=group_id,
        )
        record = result.single()
        print(f"   Document nodes: {record['doc_count']}")
        for title in record["titles"]:
            print(f"      - {title}")
        
        # Check Section nodes
        result = session.run(
            """
            MATCH (s:Section {group_id: $group_id})
            RETURN count(s) AS section_count
            """,
            group_id=group_id,
        )
        print(f"   Section nodes: {result.single()['section_count']}")
        
        # Check APPEARS_IN_DOCUMENT edges
        result = session.run(
            """
            MATCH (:Entity {group_id: $group_id})-[r:APPEARS_IN_DOCUMENT]->(:Document {group_id: $group_id})
            RETURN count(r) AS edge_count
            """,
            group_id=group_id,
        )
        print(f"   APPEARS_IN_DOCUMENT edges: {result.single()['edge_count']}")
    
    driver.close()


def main():
    parser = argparse.ArgumentParser(description="V2 Reindex with Voyage embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually index")
    parser.add_argument("--group-id", type=str, help="Specific group ID (default: new ID)")
    parser.add_argument("--verify-only", type=str, help="Only verify existing group")
    args = parser.parse_args()
    
    if args.verify_only:
        asyncio.run(verify_v2_index(args.verify_only))
        return
    
    # Generate new group ID with v2 suffix
    group_id = args.group_id or f"test-5pdfs-v2-{int(time.time())}"
    
    # Run reindex
    asyncio.run(run_reindex(group_id, dry_run=args.dry_run))
    
    # Verify results
    if not args.dry_run:
        asyncio.run(verify_v2_index(group_id))
        
        print()
        print("=" * 60)
        print("✅ V2 Reindex Complete!")
        print(f"   Group ID: {group_id}")
        print()
        print("   Next steps:")
        print("   1. Run benchmark: python run_v2_benchmark.py --group-id", group_id)
        print("   2. Compare results with V1 baseline")
        print("=" * 60)


if __name__ == "__main__":
    main()
