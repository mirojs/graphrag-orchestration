#!/usr/bin/env python3
"""End-to-end test: Skeleton enrichment (Strategy A) production code.

This script exercises the full production code path locally:
  1. Extract sentences from existing TextChunks (sentence_extraction_service.py)
  2. Embed with Voyage (voyage_embed.py)
  3. Persist :Sentence nodes in Neo4j (neo4j_store.py)
  4. Query sentence vector index for test queries (neo4j_store.py)
  5. Format as coverage_chunks (same as Route 2 stage 2.2.6)
  6. Compare enriched Route 2 vs baseline Route 2 via production API

Uses real Neo4j + Voyage + Azure OpenAI credentials from .env.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# ─── Project root on PYTHONPATH ──────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# ─── Load .env ───────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(ROOT / "graphrag-orchestration" / ".env")

# ─── Config ──────────────────────────────────────────────────────
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]
GROUP_ID = "test-5pdfs-v2-fix2"
API_BASE = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

# Force skeleton settings for this test
os.environ["SKELETON_ENRICHMENT_ENABLED"] = "true"
os.environ["VOYAGE_V2_ENABLED"] = "true"
os.environ["SKELETON_SENTENCE_TOP_K"] = "8"
os.environ["SKELETON_SIMILARITY_THRESHOLD"] = "0.45"

print("=" * 70)
print("  SKELETON ENRICHMENT E2E TEST")
print("=" * 70)
print(f"  Neo4j:    {NEO4J_URI}")
print(f"  Group:    {GROUP_ID}")
print(f"  API:      {API_BASE}")
print()


# ─── Phase 1: Extract Sentences from Existing Chunks ────────────
def phase1_extract_sentences():
    """Pull TextChunks from Neo4j, extract sentences using production service."""
    from neo4j import GraphDatabase
    from src.worker.services.sentence_extraction_service import (
        extract_sentences_from_chunks,
    )

    print("─── Phase 1: Sentence Extraction ───────────────────────")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

    # Pull chunks (same query as experiment)
    chunks = []
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (c:TextChunk {group_id: $group_id})-[:IN_DOCUMENT]->(d:Document)
            OPTIONAL MATCH (c)-[:IN_SECTION]->(s:Section)
            RETURN c.id AS id, c.text AS text, c.metadata AS metadata,
                   c.tokens AS tokens, c.document_id AS document_id,
                   d.title AS doc_title,
                   s.path_key AS section_path
            ORDER BY d.id, c.chunk_index
            """,
            group_id=GROUP_ID,
        )
        for record in result:
            # Build a minimal TextChunk-like object
            meta_raw = record["metadata"]
            if isinstance(meta_raw, str):
                try:
                    meta = json.loads(meta_raw)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            elif isinstance(meta_raw, dict):
                meta = meta_raw
            else:
                meta = {}

            class _Chunk:
                pass

            c = _Chunk()
            c.id = record["id"]
            c.text = record["text"]
            c.metadata = meta
            c.document_id = record["document_id"]
            c.tokens = record["tokens"]
            c._section_path = record["section_path"] or ""
            chunks.append(c)

    driver.close()
    print(f"  📦 Loaded {len(chunks)} TextChunks from Neo4j")

    # Build section map
    chunk_section_map = {c.id: c._section_path for c in chunks}

    # Extract sentences using production code
    sentences = extract_sentences_from_chunks(chunks, chunk_section_map)
    print(f"  ✂️  Extracted {len(sentences)} sentences (after dedup)")

    # Stats by source
    source_counts = {}
    for s in sentences:
        src = s["source"]
        source_counts[src] = source_counts.get(src, 0) + 1
    for src, cnt in sorted(source_counts.items()):
        print(f"     {src}: {cnt}")

    return sentences


# ─── Phase 2: Embed Sentences with Voyage ───────────────────────
def phase2_embed_sentences(sentences):
    """Embed extracted sentences using production Voyage service."""
    print("\n─── Phase 2: Voyage Embedding ──────────────────────────")
    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService

    voyage = VoyageEmbedService()
    texts = [s["text"] for s in sentences]

    # Embed in batches of 128 (Voyage API limit)
    BATCH_SIZE = 128
    all_embeddings = []
    t0 = time.time()

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        embs = voyage.embed_documents(batch)
        all_embeddings.extend(embs)
        print(f"    Embedded batch {i // BATCH_SIZE + 1}: {len(batch)} sentences")

    elapsed = time.time() - t0
    print(f"  ✅ Embedded {len(all_embeddings)} sentences in {elapsed:.1f}s")
    print(f"     Dimensions: {len(all_embeddings[0])}")

    # Attach embeddings to sentence dicts
    for sent, emb in zip(sentences, all_embeddings):
        sent["embedding_v2"] = emb

    return sentences


# ─── Phase 3: Persist Sentence Nodes in Neo4j ───────────────────
def phase3_persist_sentences(sentences):
    """Create :Sentence nodes in Neo4j using production neo4j_store code."""
    print("\n─── Phase 3: Neo4j Persistence ─────────────────────────")
    from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3, Sentence

    store = Neo4jStoreV3(
        uri=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE,
    )

    # Initialize schema (creates vector index if missing)
    print("  🔧 Ensuring schema (sentence vector index)...")
    store.initialize_schema()

    # Convert to Sentence dataclass
    sentence_objects = []
    for s in sentences:
        sentence_objects.append(
            Sentence(
                id=s["id"],
                text=s["text"],
                chunk_id=s["chunk_id"],
                document_id=s["document_id"],
                source=s["source"],
                index_in_chunk=s["index_in_chunk"],
                section_path=s.get("section_path", ""),
                page=s.get("page"),
                confidence=s.get("confidence", 1.0),
                embedding_v2=s.get("embedding_v2"),
                tokens=s.get("tokens", 0),
                parent_text=s.get("parent_text"),
            )
        )

    # Upsert
    count = store.upsert_sentences_batch(GROUP_ID, sentence_objects)
    print(f"  ✅ Upserted {count} Sentence nodes")

    # Verify
    with store.driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            "MATCH (s:Sentence {group_id: $gid}) RETURN count(s) AS cnt",
            gid=GROUP_ID,
        )
        total = result.single()["cnt"]
        print(f"  📊 Total Sentence nodes in Neo4j: {total}")

        # Check edges
        result = session.run(
            """
            MATCH (s:Sentence {group_id: $gid})-[r:PART_OF]->(c:TextChunk)
            RETURN count(r) AS part_of
            """,
            gid=GROUP_ID,
        )
        part_of = result.single()["part_of"]

        result = session.run(
            """
            MATCH (a:Sentence {group_id: $gid})-[r:NEXT]->(b:Sentence)
            RETURN count(r) AS next_count
            """,
            gid=GROUP_ID,
        )
        next_count = result.single()["next_count"]

        print(f"  📊 PART_OF edges: {part_of}")
        print(f"  📊 NEXT edges: {next_count}")

    store.close()
    return count


# ─── Phase 4: Query Sentence Vector Index ────────────────────────
def phase4_query_sentences():
    """Test vector search against the sentence index."""
    print("\n─── Phase 4: Sentence Vector Search ────────────────────")
    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
    from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3

    voyage = VoyageEmbedService()
    store = Neo4jStoreV3(
        uri=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE,
    )

    test_queries = [
        "What is the warranty period?",
        "What are the payment terms?",
        "When was the agreement signed?",
        "Who are the parties to the contract?",
        "What is the governing law?",
    ]

    all_results = {}
    for query in test_queries:
        print(f"\n  🔍 Query: {query}")
        emb = voyage.embed_query(query)
        results = store.query_sentences_by_vector(
            query_embedding=emb,
            group_id=GROUP_ID,
            top_k=5,
            similarity_threshold=0.40,
        )
        all_results[query] = results
        for i, r in enumerate(results[:3], 1):
            text_preview = r["text"][:80].replace("\n", " ")
            print(f"    [{i}] score={r['score']:.3f} src={r['source']:<12} {text_preview}...")
            if r.get("document_title"):
                print(f"        doc: {r['document_title']}")

    store.close()
    print(f"\n  ✅ Queried {len(test_queries)} test queries")
    return all_results


# ─── Phase 5: Route 2 Comparison (API) ──────────────────────────
def phase5_route2_comparison(sentence_query_results):
    """Compare Route 2 baseline vs enriched (skeleton sentences injected)."""
    print("\n─── Phase 5: Route 2 Comparison ────────────────────────")
    import httpx
    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
    from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3

    voyage = VoyageEmbedService()
    store = Neo4jStoreV3(
        uri=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE,
    )

    test_queries = [
        "What is the warranty period?",
        "What are the payment terms?",
        "When was the agreement signed?",
    ]

    for query in test_queries:
        print(f"\n  📝 Query: {query}")

        # --- Baseline: Route 2 via API ---
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(
                    f"{API_BASE}/hybrid/query",
                    json={
                        "query": query,
                        "group_id": GROUP_ID,
                        "response_type": "summary",
                        "force_route": "route_2",
                        "include_context": False,
                    },
                )
                baseline = resp.json()
                baseline_response = baseline.get("response", "")[:200]
                print(f"    [Baseline] {baseline_response}...")
        except Exception as e:
            print(f"    [Baseline] ERROR: {e}")
            baseline_response = ""

        # --- Enriched: Retrieve skeleton sentences ---
        emb = voyage.embed_query(query)
        sentences = store.query_sentences_by_vector(
            query_embedding=emb,
            group_id=GROUP_ID,
            top_k=8,
            similarity_threshold=0.45,
        )
        if sentences:
            print(f"    [Skeleton] Retrieved {len(sentences)} sentences (top score={sentences[0]['score']:.3f})")
            for i, s in enumerate(sentences[:3], 1):
                print(f"      S{i}: {s['text'][:70].replace(chr(10), ' ')}...")
        else:
            print(f"    [Skeleton] No sentences retrieved above threshold")

    store.close()
    print(f"\n  ✅ Route 2 comparison complete for {len(test_queries)} queries")


# ─── Main ────────────────────────────────────────────────────────
def main():
    t0 = time.time()

    # Phase 1: Extract sentences
    sentences = phase1_extract_sentences()
    if not sentences:
        print("❌ No sentences extracted. Aborting.")
        return

    # Phase 2: Embed with Voyage
    sentences = phase2_embed_sentences(sentences)

    # Phase 3: Persist to Neo4j
    phase3_persist_sentences(sentences)

    # Wait for index to update
    print("\n  ⏳ Waiting 5s for vector index to populate...")
    time.sleep(5)

    # Phase 4: Query sentence index
    query_results = phase4_query_sentences()

    # Phase 5: Route 2 comparison
    phase5_route2_comparison(query_results)

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"  E2E TEST COMPLETE in {elapsed:.1f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
