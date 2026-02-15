#!/usr/bin/env python3
"""Diagnose why sentence vector search misses certain terms.

For each failing Q-G query, this script:
1. Embeds the query with Voyage (same as production)
2. Runs the SAME Neo4j vector search with top_k=30, threshold=0.2
3. Also runs with top_k=177 (ALL sentences) to see scores for missing-term sentences
4. Shows which sentences contain missing terms and their scores
5. Notes if denoise rules would filter them out
"""

import os, sys, json, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))

import voyageai
from neo4j import GraphDatabase
from src.core.config import settings

# ── Config ──
GROUP_ID = "test-5pdfs-v2-fix2"
THRESHOLD = 0.2
PROD_TOP_K = 30

# ── Failing queries + missing terms ──
FAILING_QUERIES = {
    "Q-G5": {
        "query": "What remedies or dispute-resolution mechanisms are described across all documents?",
        "missing": ["legal fees", "default"],
    },
    "Q-G9": {
        "query": "What deposit, escrow, or trust-account requirements appear across all documents?",
        "missing": ["deposit", "3 business days"],
    },
    "Q-G10": {
        "query": "For each document, list every service or scope-of-work item the performing party must deliver.",
        "missing": ["warranty", "arbitration", "servicing", "invoice", "scope of work", "payment"],
    },
}


def denoise_would_keep(text: str) -> bool:
    """Check if the denoise function would keep this sentence."""
    text = text.strip()
    # Rule 1: HTML / markup-heavy
    tag_count = len(re.findall(r"<[^>]+>", text))
    if tag_count >= 2:
        return False
    # Rule 2: Too short / fragment
    if len(text) < 25:
        return False
    # Rule 3: Signature / form boilerplate
    if re.search(
        r"(?i)(signature|signed this|print\)|registration number"
        r"|authorized representative)",
        text,
    ):
        return False
    # Rule 4: Bare label ending with colon
    if len(text) < 60 and text.endswith(":"):
        return False
    # Rule 5: No sentence structure (heading-only)
    if len(text) < 50 and not re.search(r"[.?!]", text):
        return False
    return True


def main():
    api_key = settings.VOYAGE_API_KEY or os.environ.get("VOYAGE_API_KEY")
    vc = voyageai.Client(api_key=api_key)
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
    )

    # First, get all 177 sentences with their text (for term checking)
    with driver.session() as session:
        all_sents = session.run(
            "MATCH (s:Sentence {group_id: $gid}) RETURN s.id AS id, s.text AS text",
            gid=GROUP_ID,
        )
        all_sentences = {r["id"]: r["text"] for r in all_sents}
    print(f"Total sentences in Neo4j: {len(all_sentences)}\n")

    for qid, info in FAILING_QUERIES.items():
        query = info["query"]
        missing = info["missing"]
        print(f"\n{'='*80}")
        print(f"{qid}: {query}")
        print(f"Missing terms: {missing}")
        print(f"{'='*80}")

        # 1. Embed query with voyage-context-3 (same as production)
        result = vc.contextualized_embed(
            inputs=[[query]],
            model=settings.VOYAGE_MODEL_NAME,
            input_type="query",
            output_dimension=settings.VOYAGE_EMBEDDING_DIM,
        )
        embedding = result.results[0].embeddings[0]

        # 2. Vector search - ALL sentences (no threshold, large top_k)
        cypher_all = """
        CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
        YIELD node AS sent, score
        WHERE sent.group_id = $group_id
        RETURN sent.id AS sid, sent.text AS text, score
        ORDER BY score DESC
        """

        with driver.session() as session:
            results = list(session.run(
                cypher_all,
                embedding=embedding,
                group_id=GROUP_ID,
                top_k=177,  # ALL sentences
            ))

        all_results = [(r["sid"], r["text"], r["score"]) for r in results]

        # 3. Show top 30 (what production sees)
        print(f"\n--- Production top {PROD_TOP_K} (threshold={THRESHOLD}) ---")
        prod_results = [r for r in all_results[:PROD_TOP_K] if r[2] >= THRESHOLD]
        for i, (sid, text, score) in enumerate(prod_results[:10]):
            kept = denoise_would_keep(text)
            print(f"  #{i+1} score={score:.4f} denoise={'KEEP' if kept else 'DROP'} | {text[:80]}...")

        print(f"  ... ({len(prod_results)} total above threshold)")

        # 4. Check where missing-term sentences rank
        print(f"\n--- Missing-term sentence scores ---")
        for term in missing:
            found_any = False
            for rank, (sid, text, score) in enumerate(all_results, 1):
                if term.lower() in text.lower():
                    found_any = True
                    in_top_k = rank <= PROD_TOP_K and score >= THRESHOLD
                    kept = denoise_would_keep(text)
                    print(f"  '{term}' → rank #{rank}/{len(all_results)} "
                          f"score={score:.4f} "
                          f"in_top_{PROD_TOP_K}={'YES' if in_top_k else 'NO'} "
                          f"above_threshold={'YES' if score >= THRESHOLD else 'NO'} "
                          f"denoise={'KEEP' if kept else 'DROP'}")
                    print(f"    text: {text[:120]}")
            if not found_any:
                print(f"  '{term}' → NOT FOUND in any sentence")

        # 5. Score spread
        if all_results:
            scores = [r[2] for r in all_results]
            print(f"\n--- Score spread ---")
            print(f"  Max: {max(scores):.4f}  Min: {min(scores):.4f}  "
                  f"Spread: {max(scores)-min(scores):.4f}")
            print(f"  Threshold cutoff ({THRESHOLD}): {sum(1 for s in scores if s >= THRESHOLD)} sentences pass")
            # Show score at rank 30
            if len(scores) >= PROD_TOP_K:
                print(f"  Score at rank {PROD_TOP_K}: {scores[PROD_TOP_K-1]:.4f}")

    driver.close()
    print("\n\nDone.")


if __name__ == "__main__":
    main()
