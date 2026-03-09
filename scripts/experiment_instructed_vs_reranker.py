#!/usr/bin/env python3
"""
Experiment: Instructed Embedding vs Reranker for Q-D3 Triple Retrieval

Compares four approaches for retrieving the "180-day" triple that Q-D3 misses:

  A) BASELINE — Standard cosine (current: embed_query → dot product)
  B) INSTRUCTED EMBEDDING — Query-side instruction via voyage-context-3
  C) RERANKER ON TOP-50 — Current Stage 2 (voyage-rerank-2.5 on cosine top-50)
  D) RERANKER ON ALL — Reranker on every triple (no cosine pre-filter)

For each approach, reports:
  - Full top-20 ranking with scores
  - Whether the "180-day" triple appears (and at what rank)
  - Whether "3 business days" and "10 business days" triples appear

Usage:
  cd /workspaces/graphrag-orchestration
  set -a && source .env && set +a   # or .env.local
  python scripts/experiment_instructed_vs_reranker.py
"""

import asyncio
import json
import os
import sys
import time
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

VOYAGE_MODEL = "voyage-context-3"
VOYAGE_DIM = 2048

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")

QUERY = 'Compare "time windows" across the set: list all explicit day-based timeframes.'

# Instruction variants to test
INSTRUCTIONS = {
    "minimal": (
        "Find facts about time periods and durations. "
        f"Query: {QUERY}"
    ),
    "moderate": (
        "Find all mentions of time periods, durations, deadlines, and day-based "
        "timeframes including specific day-counts, month-counts, and year-counts. "
        f"Query: {QUERY}"
    ),
    "aggressive": (
        "Identify every fact mentioning a numeric time period — days, business days, "
        "months, or years — regardless of surrounding topic (fees, warranties, "
        "contracts, schedules). Any number followed by a time unit is relevant. "
        f"Query: {QUERY}"
    ),
}

# Triples containing these substrings are the "target" triples we want to find
TARGET_PATTERNS = ["180 day", "180-day", "3 business day", "10 business day"]

# Reranker instruction (same as production Route 7)
RERANK_INSTRUCTION = (
    "Identify facts relevant to answering this query. "
    "Consider abstract category membership — e.g., specific durations "
    "like '3 business days' or '90 days' are relevant to 'timeframes'. "
    f"Query: {QUERY}"
)

TOP_K_DISPLAY = 20
COSINE_TOP_K = 50


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Triple:
    subject_name: str
    predicate: str
    object_name: str
    triple_text: str
    embedding: Optional[List[float]] = None


def is_target(triple_text: str) -> bool:
    """Check if this triple contains one of the target timeframe patterns."""
    t = triple_text.lower()
    return any(p in t for p in TARGET_PATTERNS)


# ---------------------------------------------------------------------------
# Neo4j: Load all triples
# ---------------------------------------------------------------------------
def load_triples_from_neo4j() -> List[Triple]:
    from neo4j import GraphDatabase

    print(f"\n{'='*70}")
    print(f"Loading triples from Neo4j (group_id={GROUP_ID})")
    print(f"{'='*70}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    cypher = """
    MATCH (e1:Entity)-[r:RELATED_TO]->(e2:Entity)
    WHERE e1.group_id IN $group_ids AND e2.group_id IN $group_ids
          AND r.description IS NOT NULL AND r.description <> ''
    RETURN e1.name AS subj_name, r.description AS predicate,
           e2.name AS obj_name, r.triple_embedding AS embedding
    """
    triples = []
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(cypher, group_ids=[GROUP_ID])
        for record in result:
            subj = record["subj_name"] or ""
            pred = record["predicate"] or ""
            obj = record["obj_name"] or ""
            text = f"{subj} {pred} {obj}"
            emb = record["embedding"]
            triples.append(Triple(
                subject_name=subj, predicate=pred, object_name=obj,
                triple_text=text,
                embedding=list(emb) if emb else None,
            ))
    driver.close()

    precomputed = sum(1 for t in triples if t.embedding is not None)
    print(f"  Loaded {len(triples)} triples ({precomputed} with precomputed embeddings)")

    # Flag target triples
    targets = [t for t in triples if is_target(t.triple_text)]
    print(f"  Target triples found: {len(targets)}")
    for t in targets:
        print(f"    ★ {t.triple_text[:100]}")

    return triples


# ---------------------------------------------------------------------------
# Build embedding matrix
# ---------------------------------------------------------------------------
def build_embedding_matrix(triples: List[Triple]) -> np.ndarray:
    mat = np.array([t.embedding for t in triples], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    mat /= norms
    return mat


# ---------------------------------------------------------------------------
# Approach A: Standard cosine search (current baseline)
# ---------------------------------------------------------------------------
def cosine_search(
    query_embedding: List[float],
    emb_matrix: np.ndarray,
    triples: List[Triple],
    top_k: int,
) -> List[Tuple[Triple, float]]:
    q = np.array(query_embedding, dtype=np.float32)
    q /= np.linalg.norm(q)
    scores = emb_matrix @ q
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(triples[i], float(scores[i])) for i in top_indices]


# ---------------------------------------------------------------------------
# Approach B: Instructed query embedding
# ---------------------------------------------------------------------------
def embed_instructed_query(client, instructed_text: str) -> List[float]:
    """Embed a query with instruction prefix using voyage-context-3."""
    result = client.contextualized_embed(
        inputs=[[instructed_text]],
        model=VOYAGE_MODEL,
        input_type="query",
        output_dimension=VOYAGE_DIM,
    )
    return result.results[0].embeddings[0]


# ---------------------------------------------------------------------------
# Approach C/D: Reranker
# ---------------------------------------------------------------------------
def rerank_triples(
    client,
    instructed_query: str,
    candidates: List[Tuple[Triple, float]],
    top_k: int,
) -> List[Tuple[Triple, float]]:
    """Rerank candidate triples using voyage-rerank-2.5.
    
    For large candidate sets, batches to avoid rate limits.
    """
    documents = [triple.triple_text for triple, _ in candidates]
    
    # Batch if too many documents (rate limit: 100K TPM)
    BATCH_SIZE = 200
    if len(documents) <= BATCH_SIZE:
        rr_result = client.rerank(
            query=instructed_query,
            documents=documents,
            model="rerank-2.5",
            top_k=min(top_k, len(documents)),
        )
        return [
            (candidates[rr.index][0], rr.relevance_score)
            for rr in rr_result.results
        ]
    
    # Batch reranking: score each batch, merge, take top_k
    all_scored = []
    for i in range(0, len(documents), BATCH_SIZE):
        batch_docs = documents[i:i + BATCH_SIZE]
        batch_offset = i
        rr_result = client.rerank(
            query=instructed_query,
            documents=batch_docs,
            model="rerank-2.5",
            top_k=min(top_k, len(batch_docs)),
        )
        for rr in rr_result.results:
            global_idx = batch_offset + rr.index
            all_scored.append((candidates[global_idx][0], rr.relevance_score))
        # Brief pause between batches to respect rate limits
        if i + BATCH_SIZE < len(documents):
            time.sleep(2)
    
    all_scored.sort(key=lambda x: x[1], reverse=True)
    return all_scored[:top_k]


# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------
def print_results(label: str, results: List[Tuple[Triple, float]], top_k: int = TOP_K_DISPLAY):
    print(f"\n{'─'*70}")
    print(f"  {label}")
    print(f"{'─'*70}")

    target_found = {}
    for rank, (triple, score) in enumerate(results[:top_k], 1):
        marker = "  "
        if is_target(triple.triple_text):
            marker = "★ "
            # Track which target patterns were found
            for p in TARGET_PATTERNS:
                if p in triple.triple_text.lower():
                    target_found[p] = rank

        text = triple.triple_text[:80]
        print(f"  {marker}{rank:3d}. [{score:.4f}] {text}")

    # Also check beyond top_k for targets
    for rank, (triple, score) in enumerate(results[top_k:], top_k + 1):
        if is_target(triple.triple_text):
            for p in TARGET_PATTERNS:
                if p in triple.triple_text.lower() and p not in target_found:
                    target_found[p] = rank

    print(f"\n  Summary:")
    for p in TARGET_PATTERNS:
        if p in target_found:
            print(f"    ✅ '{p}' found at rank {target_found[p]}")
        else:
            print(f"    ❌ '{p}' NOT in results")

    return target_found


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------
async def main():
    import voyageai

    if not VOYAGE_API_KEY:
        print("ERROR: VOYAGE_API_KEY not set. Run: set -a && source .env && set +a")
        sys.exit(1)
    if not NEO4J_URI:
        print("ERROR: NEO4J_URI not set.")
        sys.exit(1)

    vc = voyageai.Client(api_key=VOYAGE_API_KEY)

    # Load triples
    triples = load_triples_from_neo4j()
    if not all(t.embedding for t in triples):
        print("ERROR: Some triples missing embeddings. Run reindex first.")
        sys.exit(1)

    emb_matrix = build_embedding_matrix(triples)

    # -----------------------------------------------------------------------
    # A) BASELINE: Standard cosine search
    # -----------------------------------------------------------------------
    print(f"\n{'='*70}")
    print("EMBEDDING QUERIES")
    print(f"{'='*70}")

    t0 = time.perf_counter()
    baseline_emb = embed_instructed_query(vc, QUERY)
    baseline_ms = (time.perf_counter() - t0) * 1000
    print(f"  Baseline query embedding: {baseline_ms:.0f}ms")

    baseline_results = cosine_search(baseline_emb, emb_matrix, triples, len(triples))
    summary_a = print_results(
        f"A) BASELINE COSINE (current behavior) — top {TOP_K_DISPLAY} of {len(triples)}",
        baseline_results,
    )

    # -----------------------------------------------------------------------
    # B) INSTRUCTED EMBEDDING: Each instruction variant
    # -----------------------------------------------------------------------
    summaries_b = {}
    for name, instruction in INSTRUCTIONS.items():
        t0 = time.perf_counter()
        instr_emb = embed_instructed_query(vc, instruction)
        instr_ms = (time.perf_counter() - t0) * 1000
        print(f"\n  Instructed '{name}' embedding: {instr_ms:.0f}ms")

        instr_results = cosine_search(instr_emb, emb_matrix, triples, len(triples))
        summaries_b[name] = print_results(
            f"B-{name}) INSTRUCTED COSINE — top {TOP_K_DISPLAY}",
            instr_results,
        )

    # -----------------------------------------------------------------------
    # C) RERANKER on cosine top-50 (current Stage 2)
    # -----------------------------------------------------------------------
    print(f"\n{'='*70}")
    print("RERANKER EXPERIMENTS")
    print(f"{'='*70}")

    cosine_top50 = cosine_search(baseline_emb, emb_matrix, triples, COSINE_TOP_K)
    print(f"\n  Cosine top-{COSINE_TOP_K} candidates for reranker:")
    target_in_top50 = any(is_target(t.triple_text) for t, _ in cosine_top50)
    print(f"    Target triples in top-{COSINE_TOP_K}: {'YES ✅' if target_in_top50 else 'NO ❌'}")

    t0 = time.perf_counter()
    reranked_top50 = rerank_triples(vc, RERANK_INSTRUCTION, cosine_top50, TOP_K_DISPLAY)
    rerank_top50_ms = (time.perf_counter() - t0) * 1000
    print(f"  Reranker on top-{COSINE_TOP_K}: {rerank_top50_ms:.0f}ms")

    summary_c = print_results(
        f"C) RERANKER on cosine top-{COSINE_TOP_K} (current Stage 2)",
        reranked_top50,
    )

    # -----------------------------------------------------------------------
    # D) RERANKER on ALL triples — SKIPPED (rate-limited at 1853 triples)
    # We know from C that the reranker is garbage-in-garbage-out: if targets
    # aren't in the candidate set, reranking can't find them.
    # -----------------------------------------------------------------------
    print(f"\n  D) RERANKER on ALL {len(triples)} triples — SKIPPED (rate limit)")
    print(f"     (1853 triples × ~50 tokens = ~93K, exceeds 100K TPM)")
    summary_d = {}

    # -----------------------------------------------------------------------
    # E) INSTRUCTED EMBEDDING + RERANKER (best of both worlds?)
    # -----------------------------------------------------------------------
    # Use the best instruction variant's top-50, then rerank
    best_instr = "aggressive"
    best_instr_emb = embed_instructed_query(vc, INSTRUCTIONS[best_instr])
    instr_top50 = cosine_search(best_instr_emb, emb_matrix, triples, COSINE_TOP_K)
    target_in_instr_top50 = any(is_target(t.triple_text) for t, _ in instr_top50)
    print(f"\n  Instructed '{best_instr}' top-{COSINE_TOP_K} candidates:")
    print(f"    Target triples in top-{COSINE_TOP_K}: {'YES ✅' if target_in_instr_top50 else 'NO ❌'}")

    t0 = time.perf_counter()
    reranked_instr = rerank_triples(vc, RERANK_INSTRUCTION, instr_top50, TOP_K_DISPLAY)
    rerank_instr_ms = (time.perf_counter() - t0) * 1000

    summary_e = print_results(
        f"E) INSTRUCTED COSINE top-{COSINE_TOP_K} → RERANKER (combo)",
        reranked_instr,
    )

    # -----------------------------------------------------------------------
    # Summary comparison
    # -----------------------------------------------------------------------
    print(f"\n{'='*70}")
    print("COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"\n  {'Approach':<50} {'180-day':<12} {'3 biz day':<12} {'10 biz day':<12}")
    print(f"  {'─'*86}")

    all_summaries = [
        ("A) Baseline cosine", summary_a),
    ]
    for name, s in summaries_b.items():
        all_summaries.append((f"B-{name}) Instructed cosine", s))
    all_summaries.extend([
        (f"C) Reranker on top-{COSINE_TOP_K}", summary_c),
        (f"D) Reranker on ALL", summary_d),
        (f"E) Instructed + reranker", summary_e),
    ])

    for label, summary in all_summaries:
        def rank_str(patterns, summary):
            for p in patterns:
                if p in summary:
                    return f"rank {summary[p]}"
            return "MISS"

        r180 = rank_str(["180 day", "180-day"], summary)
        r3 = rank_str(["3 business day"], summary)
        r10 = rank_str(["10 business day"], summary)
        print(f"  {label:<50} {r180:<12} {r3:<12} {r10:<12}")

    print(f"\n  Latencies:")
    print(f"    Baseline embedding:           {baseline_ms:.0f}ms")
    print(f"    Reranker on {COSINE_TOP_K} candidates:     {rerank_top50_ms:.0f}ms")
    print(f"    Reranker on ALL triples:      {rerank_all_ms:.0f}ms")
    print()


if __name__ == "__main__":
    asyncio.run(main())
