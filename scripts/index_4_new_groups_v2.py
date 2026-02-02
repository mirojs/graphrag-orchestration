#!/usr/bin/env python3
"""
Index 4 New Test Groups with V2 Voyage Embeddings + Fixes

This script creates 4 new test groups to validate:
1. URL-decoded Document titles (fixes KVP section_path matching)
2. Preserved Azure DI language spans (enables sentence-level context)
3. Table→Document IN_DOCUMENT edges (already working, verification)

Based on: scripts/index_5pdfs_v2_enhanced_examples.py (from HANDOVER_2026-02-01.md)

Groups Created:
- test-5pdfs-v2-fix1: URL decode + language spans (baseline fix)
- test-5pdfs-v2-fix2: Same as fix1 + KNN enabled
- test-5pdfs-v2-fix3: Same as fix1 + different KNN config (K=3, cutoff=0.80)
- test-5pdfs-v2-fix4: Same as fix1 + sentence-level synthesis (future)

Usage:
    # Index all 4 groups
    python3 scripts/index_4_new_groups_v2.py

    # Index specific group
    python3 scripts/index_4_new_groups_v2.py --group 1

    # Dry run (verify config)
    python3 scripts/index_4_new_groups_v2.py --dry-run

    # Verify existing group
    python3 scripts/index_4_new_groups_v2.py --verify-only test-5pdfs-v2-fix1
"""

import asyncio
import os
import sys
import time
import argparse
from typing import Optional, Dict, Any, List

# Add project root to path (graphrag-orchestration/graphrag-orchestration where src/ lives)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # /graphrag-orchestration
app_root = os.path.join(project_root, "graphrag-orchestration")  # /graphrag-orchestration/graphrag-orchestration

# Add project_root to sys.path for src imports (src/ is at project root level)
sys.path.insert(0, project_root)

# Load .env from graphrag-orchestration subdirectory
from dotenv import load_dotenv
load_dotenv(os.path.join(app_root, '.env'))

from src.core.config import settings


def log(msg: str) -> None:
    """Print with flush for real-time output."""
    print(msg, flush=True)


# Group configurations
GROUP_CONFIGS = {
    1: {
        "group_id": "test-5pdfs-v2-fix1",
        "description": "Baseline fix: URL decode + language spans",
        "knn_enabled": False,
        "knn_config": None,
    },
    2: {
        "group_id": "test-5pdfs-v2-fix2",
        "description": "Fix + KNN default (K=5, cutoff=0.60)",
        "knn_enabled": True,
        "knn_config": "default",
    },
    3: {
        "group_id": "test-5pdfs-v2-fix3",
        "description": "Fix + KNN optimal (K=3, cutoff=0.80)",
        "knn_enabled": True,
        "knn_config": "knn-1",  # Best performing from Feb 1 benchmarks
    },
    4: {
        "group_id": "test-5pdfs-v2-fix4",
        "description": "Fix + reserved for sentence-level synthesis",
        "knn_enabled": False,
        "knn_config": None,
    },
}

# 5 Test PDFs (same as original test group)
PDF_URLS = [
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/BUILDERS%20LIMITED%20WARRANTY.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/contoso_lifts_invoice.pdf",
    "https://neo4jstorage21224.blob.core.windows.net/test-docs/purchase_contract.pdf",
]


def check_v2_config() -> bool:
    """Verify V2 configuration is correct."""
    log("=" * 70)
    log("V2 Configuration Check")
    log("=" * 70)
    
    issues = []
    
    if not settings.VOYAGE_V2_ENABLED:
        issues.append("VOYAGE_V2_ENABLED is not True (set in .env)")
    else:
        log(f"✅ VOYAGE_V2_ENABLED: {settings.VOYAGE_V2_ENABLED}")
    
    if not settings.VOYAGE_API_KEY:
        issues.append("VOYAGE_API_KEY is not set (add to .env)")
    else:
        log(f"✅ VOYAGE_API_KEY: {'*' * 10}...{settings.VOYAGE_API_KEY[-4:]}")
    
    if settings.VOYAGE_MODEL_NAME != "voyage-context-3":
        issues.append(f"VOYAGE_MODEL_NAME should be voyage-context-3 (got: {settings.VOYAGE_MODEL_NAME})")
    else:
        log(f"✅ VOYAGE_MODEL_NAME: {settings.VOYAGE_MODEL_NAME}")
    
    if settings.VOYAGE_EMBEDDING_DIM != 2048:
        issues.append(f"VOYAGE_EMBEDDING_DIM should be 2048 (got: {settings.VOYAGE_EMBEDDING_DIM})")
    else:
        log(f"✅ VOYAGE_EMBEDDING_DIM: {settings.VOYAGE_EMBEDDING_DIM}")
    
    if not settings.NEO4J_URI:
        issues.append("NEO4J_URI is not set")
    else:
        log(f"✅ NEO4J_URI: {settings.NEO4J_URI}")
    
    log("")
    
    if issues:
        log("❌ Configuration issues found:")
        for issue in issues:
            log(f"   - {issue}")
        return False
    
    log("✅ All V2 configuration verified!")
    return True


def persist_group_id(group_id: str) -> None:
    """Save group ID for future reference."""
    try:
        filepath = os.path.join(app_root, "last_test_group_id.txt")
        with open(filepath, "w") as f:
            f.write(group_id)
        log(f"💾 Saved group ID to: last_test_group_id.txt")
    except Exception as e:
        log(f"⚠️ Could not save group ID: {e}")


async def run_v2_indexing(
    group_id: str,
    reindex: bool = True,
    dry_run: bool = False,
    knn_enabled: bool = False,
    knn_config: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Run V2 indexing with Voyage embeddings and fixes."""
    from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import (
        LazyGraphRAGIndexingPipeline,
        LazyGraphRAGIndexingConfig,
    )
    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
    from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3
    from src.worker.services.llm_service import LLMService
    
    if not settings.VOYAGE_V2_ENABLED or not settings.VOYAGE_API_KEY:
        log("❌ V2 mode is not enabled. Check .env configuration.")
        return None
    
    log("\n" + "=" * 70)
    log(f"V2 INDEXING: {group_id}")
    log("=" * 70)
    log(f"Group ID: {group_id}")
    log(f"Reindex: {reindex}")
    log(f"Dry Run: {dry_run}")
    log(f"KNN Enabled: {knn_enabled}")
    log(f"KNN Config: {knn_config or 'N/A'}")
    log("")
    
    # Initialize V2 pipeline
    log("📦 Initializing V2 pipeline...")
    
    neo4j_store = Neo4jStoreV3(
        uri=settings.NEO4J_URI or "",
        username=settings.NEO4J_USERNAME or "",
        password=settings.NEO4J_PASSWORD or "",
    )
    
    llm_service = LLMService()
    
    voyage_embedder = VoyageEmbedService(
        model_name=settings.VOYAGE_MODEL_NAME,
        api_key=settings.VOYAGE_API_KEY,
    )
    
    config = LazyGraphRAGIndexingConfig(
        chunk_size=512,
        chunk_overlap=64,
        embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,
    )
    
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
        knn_enabled=knn_enabled,
        knn_config=knn_config,
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
    log(f"  DI Languages:  {stats.get('di_languages', 0)}")
    log(f"  Elapsed:       {elapsed:.1f}s")
    log("=" * 70)
    
    if stats.get("skipped"):
        log(f"⚠️  Skipped: {stats['skipped']}")
    
    persist_group_id(group_id)
    
    return stats


async def verify_v2_index(group_id: str) -> None:
    """Verify V2 index has correct properties."""
    from neo4j import GraphDatabase
    
    log("")
    log("=" * 70)
    log(f"🔍 V2 Index Verification: {group_id}")
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
                count(c.embedding_v2) AS with_v2_embedding
            """,
            group_id=group_id,
        )
        record = result.single()
        total = record["total_chunks"]
        v2_count = record["with_v2_embedding"]
        log(f"  Total chunks: {total}")
        if total > 0:
            log(f"  With embedding_v2: {v2_count} ({100*v2_count/total:.1f}%)")
        
        # Check Document titles (should be URL-decoded now)
        result = session.run(
            """
            MATCH (d:Document {group_id: $group_id})
            RETURN d.title AS title
            """,
            group_id=group_id,
        )
        log(f"  Document titles (should be URL-decoded):")
        for record in result:
            title = record["title"]
            has_percent = "%" in (title or "")
            status = "⚠️ STILL ENCODED" if has_percent else "✅"
            log(f"    {status} {title}")
        
        # Check Table→Document edges
        result = session.run(
            """
            MATCH (t:Table {group_id: $group_id})
            OPTIONAL MATCH (t)-[:IN_DOCUMENT]->(d:Document)
            RETURN count(t) AS total_tables, count(d) AS linked_to_doc
            """,
            group_id=group_id,
        )
        record = result.single()
        log(f"  Tables: {record['total_tables']}, Linked to Document: {record['linked_to_doc']}")
        
        # Check KVP→Document matching (via section_path with bidirectional CONTAINS)
        result = session.run(
            """
            MATCH (kvp:KeyValuePair {group_id: $group_id})
            WHERE kvp.section_path IS NOT NULL AND size(kvp.section_path) > 0
            WITH kvp, toUpper(kvp.section_path[0]) AS doc_section_upper
            OPTIONAL MATCH (d:Document {group_id: $group_id})
            WITH kvp, doc_section_upper, d, toUpper(d.title) AS doc_title_upper
            WHERE doc_title_upper CONTAINS substring(doc_section_upper, 0, 20)
               OR doc_section_upper CONTAINS doc_title_upper
            WITH count(kvp) AS matched
            MATCH (kvp2:KeyValuePair {group_id: $group_id})
            WHERE kvp2.section_path IS NOT NULL AND size(kvp2.section_path) > 0
            RETURN matched, count(kvp2) AS total
            """,
            group_id=group_id,
        )
        record = result.single()
        total_kvps = record["total"]
        matched = record["matched"]
        match_rate = (100*matched/total_kvps) if total_kvps > 0 else 0
        status = "✅" if match_rate > 80 else "⚠️"
        log(f"  {status} KVPs: {total_kvps}, Document match: {matched} ({match_rate:.1f}%)")
        
        # Check language data with spans
        result = session.run(
            """
            MATCH (d:Document {group_id: $group_id})
            WHERE d.language_spans IS NOT NULL
            RETURN d.title AS title, d.primary_language AS primary_lang, 
                   d.detected_languages AS all_langs, d.language_spans AS spans
            LIMIT 1
            """,
            group_id=group_id,
        )
        record = result.single()
        if record:
            import json
            try:
                spans_data = json.loads(record["spans"]) if record["spans"] else []
                has_spans = any(l.get("spans") for l in spans_data) if spans_data else False
                total_spans = sum(len(l.get("spans", [])) for l in spans_data)
                status = "✅" if has_spans else "⚠️"
                log(f"  {status} Language data: primary={record['primary_lang']}, locales={record['all_langs']}, total_spans={total_spans}")
            except Exception as e:
                log(f"  ⚠️ Could not parse language spans: {e}")
        else:
            log(f"  ⚠️ No language spans stored in Document nodes")
        
        # Check embedding dimension
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
            status = "✅" if dim == 2048 else "⚠️"
            log(f"  {status} V2 embedding dimension: {dim}")
    
    driver.close()
    log("=" * 70)


async def index_all_groups(dry_run: bool = False) -> None:
    """Index all 4 test groups."""
    log("=" * 70)
    log("INDEXING ALL 4 TEST GROUPS")
    log("=" * 70)
    log("")
    
    for group_num, config in GROUP_CONFIGS.items():
        log(f"\n{'='*70}")
        log(f"Group {group_num}/4: {config['group_id']}")
        log(f"Description: {config['description']}")
        log(f"{'='*70}")
        
        stats = await run_v2_indexing(
            group_id=config["group_id"],
            reindex=True,
            dry_run=dry_run,
            knn_enabled=config["knn_enabled"],
            knn_config=config["knn_config"],
        )
        
        if stats and not dry_run:
            await verify_v2_index(config["group_id"])
        
        log("")
    
    log("\n" + "=" * 70)
    log("✅ ALL GROUPS INDEXED")
    log("=" * 70)
    log("")
    log("Test commands:")
    for group_num, config in GROUP_CONFIGS.items():
        log(f"  # Group {group_num}: {config['description']}")
        log(f"  curl -X POST \"$API_URL/hybrid/query\" -H \"X-Group-Id: {config['group_id']}\" \\")
        log(f"       -d '{{\"query\": \"Find inconsistencies...\", \"response_type\": \"comprehensive\"}}'")
        log("")


def main():
    parser = argparse.ArgumentParser(description="V2 Fix Testing - 4 New Groups")
    parser.add_argument("--dry-run", action="store_true", help="Verify setup without indexing")
    parser.add_argument("--group", type=int, choices=[1, 2, 3, 4], help="Index specific group (1-4)")
    parser.add_argument("--verify-only", type=str, help="Only verify existing group")
    args = parser.parse_args()
    
    # Check V2 configuration
    if not check_v2_config():
        log("\n❌ Fix configuration issues before indexing.")
        sys.exit(1)
    
    # Verify only mode
    if args.verify_only:
        asyncio.run(verify_v2_index(args.verify_only))
        return
    
    # Single group mode
    if args.group:
        config = GROUP_CONFIGS[args.group]
        log(f"\n🧪 Indexing Group {args.group}: {config['description']}")
        
        stats = asyncio.run(run_v2_indexing(
            group_id=config["group_id"],
            reindex=True,
            dry_run=args.dry_run,
            knn_enabled=config["knn_enabled"],
            knn_config=config["knn_config"],
        ))
        
        if stats and not args.dry_run:
            asyncio.run(verify_v2_index(config["group_id"]))
        return
    
    # Index all groups
    asyncio.run(index_all_groups(args.dry_run))


if __name__ == "__main__":
    main()
