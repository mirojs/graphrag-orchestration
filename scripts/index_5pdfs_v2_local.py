#!/usr/bin/env python3
"""
Index 5 Test PDFs with V2 Voyage Embeddings (Local Execution)

This script indexes the 5 standard test PDFs directly using the V2 pipeline,
bypassing the API server. This is useful for:
- Testing V2 features before deployment
- Local development without needing the API running
- Faster iteration on indexing changes

V2 Features:
- Voyage voyage-context-3 embeddings (2048 dimensions)
- Contextual chunking (chunks aware of document context)
- Universal multilingual entity canonicalization
- Bin-packing for large documents (>32k tokens)
- Q-D8 document counting fix
- Section coverage fallback for large documents

Usage:
    # Fresh indexing (creates new group ID)
    python3 scripts/index_5pdfs_v2_local.py

    # Re-index existing group
    export GROUP_ID=test-5pdfs-v2-1234567890
    python3 scripts/index_5pdfs_v2_local.py

    # Dry run (verify setup without indexing)
    python3 scripts/index_5pdfs_v2_local.py --dry-run
"""

import asyncio
import os
import sys
import time
import argparse

# Add project root to path (graphrag-orchestration/graphrag-orchestration where app/ lives)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # /graphrag-orchestration
app_root = os.path.join(project_root, "graphrag-orchestration")  # /graphrag-orchestration/graphrag-orchestration
sys.path.insert(0, app_root)

from app.core.config import settings

# Verify V2 is configured
def check_v2_config():
    """Verify V2 configuration is correct."""
    print("=" * 70)
    print("V2 Configuration Check")
    print("=" * 70)
    
    issues = []
    
    if not settings.VOYAGE_V2_ENABLED:
        issues.append("VOYAGE_V2_ENABLED is not True (set in .env)")
    else:
        print(f"✅ VOYAGE_V2_ENABLED: {settings.VOYAGE_V2_ENABLED}")
    
    if not settings.VOYAGE_API_KEY:
        issues.append("VOYAGE_API_KEY is not set (add to .env)")
    else:
        print(f"✅ VOYAGE_API_KEY: {'*' * 10}...{settings.VOYAGE_API_KEY[-4:]}")
    
    if settings.VOYAGE_MODEL_NAME != "voyage-context-3":
        issues.append(f"VOYAGE_MODEL_NAME should be voyage-context-3 (got: {settings.VOYAGE_MODEL_NAME})")
    else:
        print(f"✅ VOYAGE_MODEL_NAME: {settings.VOYAGE_MODEL_NAME}")
    
    if settings.VOYAGE_EMBEDDING_DIM != 2048:
        issues.append(f"VOYAGE_EMBEDDING_DIM should be 2048 (got: {settings.VOYAGE_EMBEDDING_DIM})")
    else:
        print(f"✅ VOYAGE_EMBEDDING_DIM: {settings.VOYAGE_EMBEDDING_DIM}")
    
    if not settings.NEO4J_URI:
        issues.append("NEO4J_URI is not set")
    else:
        print(f"✅ NEO4J_URI: {settings.NEO4J_URI}")
    
    print()
    
    if issues:
        print("❌ Configuration issues found:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    
    print("✅ All V2 configuration verified!")
    return True


# 5 Test PDFs (URL-encoded for Azure DI compatibility)
PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS%20LIMITED%20WARRANTY.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf",
]


def log(msg):
    """Print with flush for real-time output"""
    print(msg, flush=True)


def persist_group_id(group_id: str) -> None:
    """Save group ID for future reference."""
    try:
        # Save to app_root (where .env and other config files are)
        filepath = os.path.join(app_root, "last_test_group_id.txt")
        with open(filepath, "w") as f:
            f.write(group_id)
        log(f"💾 Saved group ID to: last_test_group_id.txt")
    except Exception as e:
        log(f"⚠️ Could not save group ID: {e}")


async def run_v2_indexing(group_id: str, reindex: bool, dry_run: bool):
    """Run V2 indexing with Voyage embeddings."""
    from app.hybrid_v2.indexing.lazygraphrag_pipeline import (
        LazyGraphRAGIndexingPipeline,
        LazyGraphRAGIndexingConfig,
    )
    from app.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
    from app.hybrid_v2.services.neo4j_store import Neo4jStoreV3
    from app.services.llm_service import LLMService
    
    # Verify V2 mode
    if not settings.VOYAGE_V2_ENABLED or not settings.VOYAGE_API_KEY:
        log("❌ V2 mode is not enabled. Check .env configuration.")
        return None
    
    log("\n" + "=" * 70)
    log("V2 INDEXING: 5 TEST PDFs with Voyage Embeddings")
    log("=" * 70)
    log(f"Group ID: {group_id}")
    log(f"Reindex: {reindex}")
    log(f"Dry Run: {dry_run}")
    log("")
    
    # Initialize V2 pipeline directly
    log("📦 Initializing V2 pipeline...")
    
    # Neo4j store
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI or "",
        username=settings.NEO4J_USERNAME or "",
        password=settings.NEO4J_PASSWORD or "",
    )
    
    # LLM service for entity extraction
    llm_service = LLMService()
    
    # Voyage embedder
    voyage_embedder = VoyageEmbedService(
        model_name=settings.VOYAGE_MODEL_NAME,
        api_key=settings.VOYAGE_API_KEY,
    )
    
    # V2 config
    config = LazyGraphRAGIndexingConfig(
        chunk_size=512,
        chunk_overlap=64,
        embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,
    )
    
    # V2 pipeline
    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
        embedder=voyage_embedder,
        config=config,
        use_v2_embedding_property=True,
    )
    
    log(f"   Pipeline: {type(pipeline).__module__}")
    log(f"   Embedder: {type(pipeline.embedder).__name__}")
    log(f"   use_v2_embedding_property: {pipeline.use_v2_embedding_property}")
    log(f"   Dimensions: {pipeline.config.embedding_dimensions}")
    log("")
    
    # Prepare documents
    documents = [{"source": url} for url in PDF_URLS]
    
    log("📄 Documents to index:")
    for i, doc in enumerate(documents, 1):
        name = doc['source'].split('/')[-1].replace('%20', ' ')
        log(f"   [{i}/5] {name}")
    log("")
    
    if dry_run:
        log("🔍 DRY RUN - Configuration verified, not indexing")
        return {"dry_run": True, "documents": len(documents), "group_id": group_id}
    
    # Run indexing
    log("🚀 Starting V2 indexing...")
    start_time = time.time()
    
    stats = await pipeline.index_documents(
        group_id=group_id,
        documents=documents,
        reindex=reindex,
        ingestion="document-intelligence",
        run_community_detection=False,
        run_raptor=False,
    )
    
    elapsed = time.time() - start_time
    
    log("")
    log("=" * 70)
    log("📊 V2 Indexing Results")
    log("=" * 70)
    log(f"  Group ID:      {group_id}")
    log(f"  Documents:     {stats.get('documents', 0)}")
    log(f"  Chunks:        {stats.get('chunks', 0)}")
    log(f"  Entities:      {stats.get('entities', 0)}")
    log(f"  Relationships: {stats.get('relationships', 0)}")
    log(f"  Sections:      {stats.get('sections', 0)}")
    log(f"  Section Edges: {stats.get('section_edges', 0)}")
    log(f"  Semantic Sim:  {stats.get('semantic_similarity_edges', 0)}")
    log(f"  Elapsed:       {elapsed:.1f}s")
    log("=" * 70)
    
    if stats.get("skipped"):
        log(f"⚠️  Skipped: {stats['skipped']}")
    
    # Save group ID
    persist_group_id(group_id)
    
    return stats


async def verify_v2_index(group_id: str):
    """Verify V2 index has embedding_v2 properties."""
    from neo4j import GraphDatabase
    
    log("")
    log("=" * 70)
    log("🔍 V2 Index Verification")
    log("=" * 70)
    
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
        
        log(f"  Total chunks: {total}")
        if total > 0:
            log(f"  With embedding_v2: {v2_count} ({100*v2_count/total:.1f}%)")
            log(f"  With embedding (v1): {v1_count} ({100*v1_count/total:.1f}%)")
        else:
            log("  ⚠️ No chunks found!")
        
        # Check Document nodes
        result = session.run(
            """
            MATCH (d:Document {group_id: $group_id})
            RETURN count(d) AS doc_count, collect(d.title) AS titles
            """,
            group_id=group_id,
        )
        record = result.single()
        log(f"  Document nodes: {record['doc_count']}")
        for title in record["titles"]:
            log(f"    - {title}")
        
        # Check Section nodes
        result = session.run(
            """
            MATCH (s:Section {group_id: $group_id})
            RETURN count(s) AS section_count
            """,
            group_id=group_id,
        )
        log(f"  Section nodes: {result.single()['section_count']}")
        
        # Check APPEARS_IN_DOCUMENT edges
        result = session.run(
            """
            MATCH (:Entity {group_id: $group_id})-[r:APPEARS_IN_DOCUMENT]->(:Document {group_id: $group_id})
            RETURN count(r) AS edge_count
            """,
            group_id=group_id,
        )
        log(f"  APPEARS_IN_DOCUMENT edges: {result.single()['edge_count']}")
        
        # Check if V2 embeddings are correct dimension
        result = session.run(
            """
            MATCH (c:TextChunk {group_id: $group_id})
            WHERE c.embedding_v2 IS NOT NULL
            RETURN size(c.embedding_v2) AS dim
            LIMIT 1
            """,
            group_id=group_id,
        )
        record = result.single()
        if record:
            dim = record["dim"]
            if dim == 2048:
                log(f"  ✅ V2 embedding dimension: {dim} (correct)")
            else:
                log(f"  ⚠️ V2 embedding dimension: {dim} (expected 2048)")
        else:
            log("  ⚠️ No V2 embeddings found!")
    
    driver.close()
    log("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="V2 Local Indexing with Voyage Embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Verify setup without indexing")
    parser.add_argument("--group-id", type=str, help="Specific group ID (default: new ID)")
    parser.add_argument("--verify-only", type=str, help="Only verify existing group (no indexing)")
    args = parser.parse_args()
    
    # Check V2 configuration
    if not check_v2_config():
        log("\n❌ Fix configuration issues before indexing.")
        sys.exit(1)
    
    # Verify only mode
    if args.verify_only:
        asyncio.run(verify_v2_index(args.verify_only))
        return
    
    # Determine group ID
    group_id_from_env = os.getenv("GROUP_ID")
    group_id = args.group_id or group_id_from_env or f"test-5pdfs-v2-{int(time.time())}"
    reindex = bool(group_id_from_env or args.group_id)
    
    # Run indexing
    stats = asyncio.run(run_v2_indexing(group_id, reindex, args.dry_run))
    
    if stats and not args.dry_run:
        # Verify results
        asyncio.run(verify_v2_index(group_id))
        
        log("")
        log("=" * 70)
        log("✅ V2 INDEXING COMPLETE")
        log("=" * 70)
        log(f"Group ID: {group_id}")
        log("")
        log("Next steps:")
        log(f"  1. Run benchmark: python3 scripts/run_benchmark.py --group-id {group_id}")
        log(f"  2. Check edges: python3 check_edges.py {group_id}")
        log("=" * 70)


if __name__ == "__main__":
    main()
