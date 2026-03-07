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

Prerequisites:
    # Required environment variables (set in .env or export):
    #   NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
    #   AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME
    #   AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
    #   VOYAGE_API_KEY, VOYAGE_V2_ENABLED=true
    #
    # Authenticate to Azure (if not using API keys):
    #   az login

Usage:
    # Fresh indexing (creates new group ID)
    PYTHONPATH=. python3 scripts/index_5pdfs_v2_local.py

    # Re-index existing group (deletes old data first)
    GROUP_ID=test-5pdfs-v2-fix2 PYTHONPATH=. python3 scripts/index_5pdfs_v2_local.py

    # Dry run (verify setup without indexing)
    PYTHONPATH=. python3 scripts/index_5pdfs_v2_local.py --dry-run

Post-indexing workflow:
    # 1. Start API server (takes ~60-90s for Neo4j schema init)
    PYTHONPATH=. uvicorn src.api_gateway.main:app --host 0.0.0.0 --port 8000

    # 2. Run Route 7 benchmark
    PYTHONPATH=. python3 scripts/benchmark_route7_hipporag2.py \\
        --url http://localhost:8000 --no-auth \\
        --group-id test-5pdfs-v2-fix2 --repeats 1

    # 3. Evaluate with LLM judge
    PYTHONPATH=. python3 scripts/evaluate_route4_reasoning.py \\
        benchmarks/<benchmark_json_file>
"""

import asyncio
import os
import sys
import time
import argparse

# Add project root to path so src/ is importable
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # /graphrag-orchestration
app_root = os.path.join(project_root, "graphrag-orchestration")  # /graphrag-orchestration/graphrag-orchestration
sys.path.insert(0, project_root)  # src/ is at project_root level


from src.core.config import settings

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

    if not settings.SKELETON_ENRICHMENT_ENABLED:
        issues.append(
            "SKELETON_ENRICHMENT_ENABLED is False — sentence nodes will NOT be created, "
            "breaking Routes 3/4 sentence search and Route 5 semantic addon. "
            "Set SKELETON_ENRICHMENT_ENABLED=True in .env"
        )
    else:
        print(f"✅ SKELETON_ENRICHMENT_ENABLED: {settings.SKELETON_ENRICHMENT_ENABLED}")
        print(f"   SKELETON_MIN_SENTENCE_WORDS: {settings.SKELETON_MIN_SENTENCE_WORDS} "
              f"(must be 3; was changed from 5 in commit 019e584)")

    # Azure services — required for actual indexing, not for --dry-run.
    # NOTE: Voyage (above) handles embeddings. Azure OpenAI is a SEPARATE concern:
    # it provides the LLM for entity extraction (NER/KGE step that creates Entity nodes).
    # Azure DI provides PDF parsing (OCR + layout). Both are required for a full index.
    #
    # Authentication: this project uses Managed Identity — NO API keys needed.
    # For local runs, authenticate with: az login
    # DefaultAzureCredential will automatically pick up your Azure CLI token.
    print()
    print("Azure services (required for real indexing, not for --dry-run):")
    azure_di = getattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", None) or \
               getattr(settings, "AZURE_CONTENT_UNDERSTANDING_ENDPOINT", None)
    if not azure_di:
        print("  ⚠️  AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT — not set (Azure DI PDF parsing will fail)")
        print("      Add to .env: AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<name>.cognitiveservices.azure.com/")
    else:
        azure_di_key = getattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_KEY", None) or \
                       getattr(settings, "AZURE_CONTENT_UNDERSTANDING_API_KEY", None)
        auth_mode = "API key" if azure_di_key else "Managed Identity / az login token"
        print(f"  ✅ AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: {azure_di}  [{auth_mode}]")

    azure_oai = getattr(settings, "AZURE_OPENAI_ENDPOINT", None)
    if not azure_oai:
        print("  ⚠️  AZURE_OPENAI_ENDPOINT — not set "
              "(entity extraction/NER will be disabled; Entity nodes will NOT be created)")
        print("      Add to .env: AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com/")
    else:
        azure_oai_key = getattr(settings, "AZURE_OPENAI_API_KEY", None)
        auth_mode = "API key" if azure_oai_key else "Managed Identity / az login token"
        print(f"  ✅ AZURE_OPENAI_ENDPOINT: {azure_oai}  [{auth_mode}]")

    # GDS (Graph Data Science) — Aura Serverless for KNN, Louvain, PageRank
    print("Aura GDS (required for graph algorithms):")
    gds_id = getattr(settings, "AURA_DS_CLIENT_ID", None)
    gds_secret = getattr(settings, "AURA_DS_CLIENT_SECRET", None)
    if not gds_id or not gds_secret:
        missing = []
        if not gds_id:
            missing.append("AURA_DS_CLIENT_ID")
        if not gds_secret:
            missing.append("AURA_DS_CLIENT_SECRET")
        print(f"  ⚠️  GDS credentials missing: {', '.join(missing)}")
        print("      KNN + Louvain + PageRank will be skipped")
        print("      Fix: ensure azd env has the values, or set in .env")
    else:
        print(f"  ✅ AURA_DS_CLIENT_ID: {gds_id[:8]}...")
        print(f"  ✅ AURA_DS_CLIENT_SECRET: {'*' * 8}...{gds_secret[-4:]}")

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

    # Prepare documents (needed even for dry run to show what would be indexed)
    documents = [{"source": url} for url in PDF_URLS]

    log("📄 Documents to index:")
    for i, doc in enumerate(documents, 1):
        name = doc['source'].split('/')[-1].replace('%20', ' ')
        log(f"   [{i}/5] {name}")
    log("")

    if dry_run:
        log("🔍 DRY RUN - Configuration verified, not indexing")
        return {"dry_run": True, "documents": len(documents), "group_id": group_id}

    # Heavy imports deferred until we know we're actually running (not dry-run).
    # The pipeline pulls in Azure SDK and other large dependencies that may not
    # be installed in all local environments — importing them only here keeps
    # the config-check/dry-run path lightweight.
    from src.worker.hybrid_v2.indexing.lazygraphrag_pipeline import (
        LazyGraphRAGIndexingPipeline,
        LazyGraphRAGIndexingConfig,
    )
    from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3
    from src.worker.services.llm_service import LLMService
    from src.worker.hybrid_v2.embeddings import get_voyage_embed_service

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

    # Voyage embedder (use LlamaIndex embed model, same as pipeline_factory.py)
    voyage_service = get_voyage_embed_service()
    embedder = voyage_service.get_llama_index_embed_model()

    # V2 config (matches pipeline_factory.py get_lazygraphrag_indexing_pipeline_v2)
    config = LazyGraphRAGIndexingConfig(
        chunk_size=1500,     # Section-aware: larger chunks (section boundaries)
        chunk_overlap=50,    # Overlap for split sections
        embedding_dimensions=settings.VOYAGE_EMBEDDING_DIM,  # 2048
    )

    # V2 pipeline
    pipeline = LazyGraphRAGIndexingPipeline(
        neo4j_store=neo4j_store,
        llm=llm_service.get_indexing_llm() if llm_service.llm is not None else None,
        section_embed_model=embedder,
        voyage_service=voyage_service,
        config=config,
    )

    log(f"   Pipeline: {type(pipeline).__module__}")
    log(f"   Embedder: {type(embedder).__name__}")
    log(f"   Dimensions: {pipeline.config.embedding_dimensions}")
    log("")

    # Run indexing — all documents in one batch call.
    # Voyage voyage-context-3 contextualizes each chunk within its document by
    # grouping chunks per document: inputs = [[doc1_chunks...], [doc2_chunks...]].
    # Splitting into per-document index_documents calls would fragment that batching
    # without any benefit (the contextualization is scoped per inner list regardless).
    #
    # The "all files as one" chunking bug lives in _prepare_documents (pipeline-level),
    # where all URLs were passed to extract_documents in a single batch. That is fixed
    # there (one URL per extract_documents call). Do NOT re-introduce a loop here.
    #
    # run_community_detection=True: Route 5 needs communities at query time — they must
    # exist in Neo4j when indexing completes, not built lazily on first query.
    log("🚀 Starting V2 indexing...")
    start_time = time.time()

    stats = await pipeline.index_documents(
        group_id=group_id,
        documents=documents,
        reindex=reindex,
        ingestion="document-intelligence",
        run_community_detection=True,    # eager — Route 5 requires communities at index time
        run_raptor=False,
        knn_enabled=False,               # GDS entity KNN disabled (synonymy computed locally in step 7.6)
        knn_top_k=0,
        knn_similarity_cutoff=0.60,
        entity_synonymy_threshold=0.65,  # Cross-doc entity bridges (§47) — lowered from 0.70 for LLM non-determinism robustness
    )

    elapsed = time.time() - start_time
    
    log("")
    log("=" * 70)
    log("📊 V2 Indexing Results")
    log("=" * 70)
    log(f"  Group ID:      {group_id}")
    log(f"  Documents:     {stats.get('documents', 0)}")
    log(f"  Sentences:     {stats.get('sentences', 0)} "
        f"(embedded: {stats.get('sentences_embedded', 0)})")
    if stats.get('sentences', 0) == 0:
        log("  WARNING: No sentence nodes created")
    log(f"  Entities:      {stats.get('entities', 0)}")
    log(f"  Relationships: {stats.get('relationships', 0)}")
    log(f"  Sections:      {stats.get('sections', 0)}")
    log(f"  Section Edges: {stats.get('section_edges', 0)}")
    log(f"  Semantic Sim:  {stats.get('semantic_similarity_edges', 0)}")
    log(f"  Communities:   {stats.get('communities_created', 0)} "
        f"(summaries: {stats.get('summaries_generated', 0)})")
    log(f"  KNN Edges:     {stats.get('gds_knn_edges', 0)}")
    log(f"  Elapsed:       {elapsed:.1f}s")
    log("=" * 70)
    
    if stats.get("skipped"):
        log(f"⚠️  Skipped: {stats['skipped']}")
    
    # Save group ID
    persist_group_id(group_id)
    
    return stats


async def verify_v2_index(group_id: str):
    """Verify index has correct Sentence-based structure."""
    from neo4j import GraphDatabase
    
    log("")
    log("=" * 70)
    log("V2 Index Verification")
    log("=" * 70)
    
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
    )
    
    with driver.session(database=settings.NEO4J_DATABASE or "neo4j") as session:
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
        
        # Check Sentence nodes and embeddings
        result = session.run(
            """
            MATCH (s:Sentence {group_id: $group_id})
            RETURN count(s) AS total_sentences,
                   count(s.embedding_v2) AS with_embedding
            """,
            group_id=group_id,
        )
        record = result.single()
        sent_total = record["total_sentences"]
        sent_embedded = record["with_embedding"]
        if sent_total > 0:
            log(f"  Sentence nodes: {sent_total} (embedded: {sent_embedded})")
        else:
            log("  WARNING: Sentence nodes: 0")

        # Check Sentence embedding dimension
        result = session.run(
            """
            MATCH (s:Sentence {group_id: $group_id})
            WHERE s.embedding_v2 IS NOT NULL
            RETURN size(s.embedding_v2) AS dim
            LIMIT 1
            """,
            group_id=group_id,
        )
        record = result.single()
        if record:
            dim = record["dim"]
            log(f"  Sentence embedding dim: {dim} {'(correct)' if dim == 2048 else '(expected 2048)'}")

        # Check Entity nodes
        result = session.run(
            """
            MATCH (e:Entity {group_id: $group_id})
            RETURN count(e) AS entity_count,
                   count(e.embedding_v2) AS with_embedding
            """,
            group_id=group_id,
        )
        record = result.single()
        log(f"  Entity nodes: {record['entity_count']} (embedded: {record['with_embedding']})")
        
        # Check APPEARS_IN_DOCUMENT edges
        result = session.run(
            """
            MATCH (:Entity {group_id: $group_id})-[r:APPEARS_IN_DOCUMENT]->(:Document {group_id: $group_id})
            RETURN count(r) AS edge_count
            """,
            group_id=group_id,
        )
        log(f"  APPEARS_IN_DOCUMENT edges: {result.single()['edge_count']}")

        # Check Sentence->Entity MENTIONS
        result = session.run(
            """
            MATCH (s:Sentence {group_id: $group_id})-[r:MENTIONS]->(e:Entity {group_id: $group_id})
            RETURN count(r) AS mentions_count
            """,
            group_id=group_id,
        )
        log(f"  Sentence->Entity MENTIONS: {result.single()['mentions_count']}")

        # Check Community nodes
        result = session.run(
            """
            MATCH (c:Community {group_id: $group_id})
            RETURN count(c) AS community_count,
                   count(c.summary) AS with_summary,
                   count(c.embedding) AS with_embedding
            """,
            group_id=group_id,
        )
        record = result.single()
        log(f"  Community nodes: {record['community_count']} "
            f"(summaries: {record['with_summary']}, embedded: {record['with_embedding']})")

        # Check KNN edges
        result = session.run(
            """
            MATCH (:Entity {group_id: $group_id})-[r:SEMANTICALLY_SIMILAR]->(:Entity {group_id: $group_id})
            RETURN count(r) AS knn_count
            """,
            group_id=group_id,
        )
        log(f"  SEMANTICALLY_SIMILAR (KNN) edges: {result.single()['knn_count']}")

        # Check for stale legacy nodes (TextChunk / Chunk) that should not exist after reindex
        result = session.run(
            """
            OPTIONAL MATCH (tc:TextChunk {group_id: $group_id})
            WITH count(tc) AS tc_count
            OPTIONAL MATCH (c:Chunk {group_id: $group_id})
            RETURN tc_count, count(c) AS chunk_count
            """,
            group_id=group_id,
        )
        record = result.single()
        tc_count = record["tc_count"]
        chunk_count = record["chunk_count"]
        if tc_count > 0 or chunk_count > 0:
            log(f"  ⚠️  STALE LEGACY NODES: TextChunk={tc_count}, Chunk={chunk_count}")
            log(f"     These are leftover from pre-Sentence migration and should be removed.")
        else:
            log(f"  ✅ No stale TextChunk/Chunk nodes (clean Sentence-based graph)")
    
    driver.close()
    log("=" * 70)


def _flush_api_cache(group_id: str):
    """Tell a running local API to flush its pipeline cache for this group.

    Best-effort: if the API isn't running, we just log a reminder.
    """
    import urllib.request
    import urllib.error

    api_port = os.getenv("API_PORT", "8000")
    url = f"http://localhost:{api_port}/hybrid/cache/flush"
    headers = {"Content-Type": "application/json", "X-Group-ID": group_id}
    body = b"{}"

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = resp.read().decode()
            log(f"🔄 API cache flushed for {group_id}: {result}")
    except urllib.error.URLError:
        log(f"⚠️  API not reachable on port {api_port} — remember to restart API before benchmarking")
    except Exception as e:
        log(f"⚠️  Cache flush failed ({e}) — remember to restart API before benchmarking")


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

        # Flush API pipeline cache so next query loads fresh graph data
        _flush_api_cache(group_id)

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
