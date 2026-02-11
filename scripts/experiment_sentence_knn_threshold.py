#!/usr/bin/env python3
"""Experiment: Sentence k-NN threshold analysis.

For every :Sentence node that has an embedding, query the vector index
for its nearest neighbours (cross-chunk only) and analyze the similarity
distribution at different thresholds (≥0.60 vs ≥0.90).

This does NOT create any edges — it's pure analysis to validate the right
threshold before we commit Phase 2 RELATED_TO edges to the pipeline.

Usage:
    python scripts/experiment_sentence_knn_threshold.py
"""

import os
import sys
import time
import statistics
from pathlib import Path
from collections import defaultdict

# ─── Project root ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv
load_dotenv(ROOT / "graphrag-orchestration" / ".env")

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
GROUP_ID = "test-5pdfs-v2-fix2"

# k-NN budget per sentence — generous for experiment, will tighten in prod
TOP_K = 10

# Thresholds to evaluate
THRESHOLDS = [0.60, 0.70, 0.80, 0.85, 0.90, 0.95]

print("=" * 72)
print("  SENTENCE k-NN THRESHOLD EXPERIMENT")
print("=" * 72)
print(f"  Neo4j:    {NEO4J_URI}")
print(f"  Group:    {GROUP_ID}")
print(f"  Top-K:    {TOP_K}")
print(f"  Thresholds: {THRESHOLDS}")
print()

# ─── Step 1: Load all sentences with embeddings ─────────────────

from neo4j import GraphDatabase

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

print("─── Step 1: Load sentences with embeddings ─────────────────")
t0 = time.time()

with driver.session(database=NEO4J_DATABASE) as session:
    records = session.run(
        """
        MATCH (s:Sentence {group_id: $group_id})
        WHERE s.embedding_v2 IS NOT NULL
        OPTIONAL MATCH (s)-[:PART_OF]->(c:TextChunk)
        OPTIONAL MATCH (s)-[:IN_DOCUMENT]->(d:Document)
        RETURN s.id AS id,
               s.text AS text,
               s.chunk_id AS chunk_id,
               s.document_id AS document_id,
               s.source AS source,
               s.section_path AS section_path,
               s.page AS page,
               d.title AS doc_title,
               s.embedding_v2 AS embedding
        ORDER BY s.document_id, s.chunk_id, s.index_in_chunk
        """,
        group_id=GROUP_ID,
    ).data()

sentences = []
for r in records:
    sentences.append({
        "id": r["id"],
        "text": r["text"],
        "chunk_id": r["chunk_id"],
        "document_id": r["document_id"],
        "source": r["source"],
        "section_path": r["section_path"] or "",
        "page": r["page"],
        "doc_title": r["doc_title"] or "",
        "embedding": r["embedding"],
    })

print(f"  Loaded {len(sentences)} sentences with embeddings in {time.time()-t0:.1f}s")
print()

if not sentences:
    print("ERROR: No sentences found. Run E2E test first.")
    sys.exit(1)


# ─── Step 2: For each sentence, query vector index for neighbors ──

print("─── Step 2: Query vector index for each sentence ───────────")
t0 = time.time()

# For every sentence, find its top-K nearest neighbours
# Store: list of (source_id, target_id, similarity, source_chunk, target_chunk)
all_pairs = []     # Cross-chunk pairs only
same_chunk = 0     # Count of same-chunk pairs (excluded)
self_matches = 0   # Count of self-matches (excluded)

with driver.session(database=NEO4J_DATABASE) as session:
    for i, sent in enumerate(sentences):
        results = session.run(
            """
            CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
            YIELD node AS n, score
            WHERE n.group_id = $group_id AND n.id <> $self_id
            RETURN n.id AS id,
                   n.text AS text,
                   n.chunk_id AS chunk_id,
                   n.document_id AS document_id,
                   n.source AS source,
                   n.section_path AS section_path,
                   n.page AS page,
                   score
            ORDER BY score DESC
            """,
            embedding=sent["embedding"],
            group_id=GROUP_ID,
            self_id=sent["id"],
            top_k=TOP_K + 1,  # +1 in case self is included by index
        ).data()

        for r in results:
            if r["id"] == sent["id"]:
                self_matches += 1
                continue

            if r["chunk_id"] == sent["chunk_id"]:
                same_chunk += 1
                continue

            # Cross-chunk pair — deduplicate by always storing (min_id, max_id)
            pair_key = tuple(sorted([sent["id"], r["id"]]))
            all_pairs.append({
                "source_id": sent["id"],
                "target_id": r["id"],
                "source_text": sent["text"],
                "target_text": r["text"],
                "source_chunk": sent["chunk_id"],
                "target_chunk": r["chunk_id"],
                "source_doc": sent["doc_title"],
                "target_doc": r.get("document_id", ""),
                "source_section": sent["section_path"],
                "target_section": r.get("section_path", ""),
                "similarity": r["score"],
                "pair_key": pair_key,
            })

        if (i + 1) % 50 == 0 or i == len(sentences) - 1:
            print(f"  Queried {i+1}/{len(sentences)} sentences...")

elapsed = time.time() - t0
print(f"  Done in {elapsed:.1f}s")
print(f"  Raw cross-chunk pairs: {len(all_pairs)}")
print(f"  Same-chunk excluded:   {same_chunk}")
print(f"  Self-matches excluded: {self_matches}")
print()


# ─── Step 3: Deduplicate pairs (A→B and B→A are the same edge) ───

print("─── Step 3: Deduplicate pairs ──────────────────────────────")

# Keep highest similarity for each unique pair
deduped = {}
for p in all_pairs:
    key = p["pair_key"]
    if key not in deduped or p["similarity"] > deduped[key]["similarity"]:
        deduped[key] = p

unique_pairs = sorted(deduped.values(), key=lambda x: x["similarity"], reverse=True)
print(f"  Unique cross-chunk pairs: {len(unique_pairs)}")
if unique_pairs:
    sims = [p["similarity"] for p in unique_pairs]
    print(f"  Similarity range: {min(sims):.4f} — {max(sims):.4f}")
    print(f"  Mean: {statistics.mean(sims):.4f}, Median: {statistics.median(sims):.4f}")
    if len(sims) > 1:
        print(f"  Stdev: {statistics.stdev(sims):.4f}")
print()


# ─── Step 4: Threshold analysis ──────────────────────────────────

print("─── Step 4: Threshold Analysis ─────────────────────────────")
print()

for threshold in THRESHOLDS:
    edges = [p for p in unique_pairs if p["similarity"] >= threshold]
    
    # Count unique sentences involved
    involved_sents = set()
    for e in edges:
        involved_sents.add(e["source_id"])
        involved_sents.add(e["target_id"])
    
    # Count cross-document edges
    cross_doc = sum(1 for e in edges if e["source_doc"] != e["target_doc"])
    
    # Max edges per sentence
    edge_counts = defaultdict(int)
    for e in edges:
        edge_counts[e["source_id"]] += 1
        edge_counts[e["target_id"]] += 1
    max_per_node = max(edge_counts.values()) if edge_counts else 0
    avg_per_node = statistics.mean(edge_counts.values()) if edge_counts else 0
    
    print(f"  ≥ {threshold:.2f}: {len(edges):4d} edges | "
          f"{len(involved_sents):3d}/{len(sentences)} sentences connected | "
          f"cross-doc: {cross_doc} | "
          f"max/node: {max_per_node} | avg/node: {avg_per_node:.1f}")

print()


# ─── Step 5: Detailed inspection at each key threshold ───────────

def show_pairs(pairs, label, max_show=10):
    """Print sample pairs for quality inspection."""
    print(f"\n  {'─'*60}")
    print(f"  {label}: {len(pairs)} edges")
    print(f"  {'─'*60}")
    
    for i, p in enumerate(pairs[:max_show]):
        print(f"\n  [{i+1}] sim={p['similarity']:.4f}")
        src_doc = p.get('source_doc', '')[:30]
        tgt_chunk = p.get('target_chunk', '')[:30]
        print(f"      SRC [{src_doc}] chunk={p['source_chunk'][-12:]}")
        print(f"          \"{p['source_text'][:120]}\"")
        print(f"      TGT chunk={p['target_chunk'][-12:]}")
        print(f"          \"{p['target_text'][:120]}\"")
    
    if len(pairs) > max_show:
        print(f"\n  ... and {len(pairs) - max_show} more")


print("─── Step 5: Sample Pairs by Threshold Band ─────────────────")

# Band analysis: show sample pairs in each similarity range
bands = [
    ("HIGH  ≥ 0.90", 0.90, 1.01),
    ("MED   0.80–0.89", 0.80, 0.90),
    ("LOW   0.70–0.79", 0.70, 0.80),
    ("NOISE 0.60–0.69", 0.60, 0.70),
]

for label, lo, hi in bands:
    band_pairs = [p for p in unique_pairs if lo <= p["similarity"] < hi]
    show_pairs(band_pairs, label, max_show=5)

print()


# ─── Step 6: Histogram ───────────────────────────────────────────

print("─── Step 6: Similarity Distribution ─────────────────────────")

if unique_pairs:
    # ASCII histogram in 0.05-wide bins
    bins = defaultdict(int)
    for p in unique_pairs:
        bucket = round(p["similarity"] * 20) / 20  # round to nearest 0.05
        bins[bucket] += 1
    
    max_count = max(bins.values())
    bar_width = 50
    
    for bucket in sorted(bins.keys()):
        count = bins[bucket]
        bar = "█" * int(count / max_count * bar_width)
        print(f"  {bucket:.2f} | {bar} {count}")
    
    print()

    # Also show cumulative from top
    print("  Cumulative from top:")
    sorted_sims = sorted([p["similarity"] for p in unique_pairs], reverse=True)
    for t in THRESHOLDS:
        count = sum(1 for s in sorted_sims if s >= t)
        print(f"    ≥ {t:.2f}: {count:4d} edges")

print()


# ─── Step 7: Architecture Recommendation ─────────────────────────

print("─── Step 7: Recommendation ─────────────────────────────────")
print()

edges_090 = [p for p in unique_pairs if p["similarity"] >= 0.90]
edges_060 = [p for p in unique_pairs if p["similarity"] >= 0.60]

ratio = len(edges_090) / len(edges_060) * 100 if edges_060 else 0

print(f"  At ≥0.60: {len(edges_060)} edges (100%)")
print(f"  At ≥0.90: {len(edges_090)} edges ({ratio:.0f}%)")
print(f"  Noise reduction: {100-ratio:.0f}% of edges eliminated by 0.90 threshold")
print()

# Check edge budget compliance: max k=2 per sentence
over_budget_090 = 0
edge_counts_090 = defaultdict(int)
for e in edges_090:
    edge_counts_090[e["source_id"]] += 1
    edge_counts_090[e["target_id"]] += 1
for sid, count in edge_counts_090.items():
    if count > 2:
        over_budget_090 += 1

if over_budget_090:
    print(f"  ⚠ At ≥0.90, {over_budget_090} sentences exceed max k=2 budget")
    print(f"    → In production, enforce k=2 cap to keep edge count bounded")
else:
    print(f"  ✓ At ≥0.90, all sentences within k=2 budget — naturally sparse")

print()
print("=" * 72)
print("  EXPERIMENT COMPLETE")
print("=" * 72)

driver.close()
