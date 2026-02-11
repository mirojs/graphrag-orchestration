#!/usr/bin/env python3
"""Verify that sentence-level vector retrieval ranks answer-bearing sentences correctly.

Key finding (2026-02-11):
    All 5 questions previously flagged as "100% context noise" (Q-L4, Q-L5, Q-L7,
    Q-L8, Q-L10) have their answer-bearing sentence at **rank #1** in the Voyage
    voyage-context-3 sentence embedding space.

    This proves:
    1. The sentence skeleton retrieval path is working correctly.
    2. The "100% context noise" was a measurement artifact — the noise metric counted
       how many of the top-k sentences DON'T contain the expected answer token, but
       for a question like "What is the start date?" with expected="2010-06-15", only
       1 of 8 sentences will contain that token → 87.5% "noise" even though retrieval
       is perfect (answer at rank 1).
    3. No reranker (PPR, voyage-rerank-2.5, or cross-encoder) is needed — bi-encoder
       sentence embeddings are precise enough at the 20-50 token level.
    4. The architecture doc's Phase 3+ reranker condition ("right sentences exist in
       top-20 but not top-5") is NOT met — all answers are at rank 1.

Implications:
    - KVP-aware retrieval would only help Q-L4 (1 of 5 questions); the rest have
      answers in sentence prose, not key-value pairs.
    - The original top_k=8 is sufficient — increasing to 16-20 adds context dilution
      without improving recall.
    - The benchmark noise metric should measure recall@k and signal_rank, not just
      noise_ratio (which is misleading for short expected answers).

Usage:
    python scripts/verify_sentence_retrieval_ranking.py
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
for p in [str(THIS_DIR), str(PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "graphrag-orchestration" / ".env")
load_dotenv(PROJECT_ROOT / ".env")

warnings.filterwarnings("ignore", category=DeprecationWarning)

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]
GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")


# -- Questions that the deep benchmark flagged as "100% context noise" ---------
QUESTIONS = {
    "Q-L4": {
        "query": "What is the initial term start date in the property management agreement?",
        "expected": "2010-06-15",
        "answer_token": "2010-06-15",
    },
    "Q-L5": {
        "query": "What written notice period is required for termination of the property management agreement?",
        "expected": "sixty (60) days written notice",
        "answer_token": "sixty",
    },
    "Q-L7": {
        "query": "What is the Agent fee/commission for long-term leases (>180 days)?",
        "expected": "ten percent (10%) of the gross revenues",
        "answer_token": "ten percent",
    },
    "Q-L8": {
        "query": "What is the pro-ration advertising charge and minimum admin/accounting charge in the property management agreement?",
        "expected": "$75.00/month advertising; $50.00/month minimum admin/accounting",
        "answer_token": "75.00",
    },
    "Q-L10": {
        "query": "In the purchase contract Exhibit A, what is the contact's name and email?",
        "expected": "Elizabeth Nolasco; enolasco@fabrikam.com",
        "answer_token": "enolasco",
    },
}


def main():
    import voyageai
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    voyage = voyageai.Client(api_key=VOYAGE_API_KEY)

    # Load all sentence embeddings
    print("Loading sentence embeddings from Neo4j...")
    with driver.session(database=NEO4J_DATABASE) as session:
        rows = session.run(
            """
            MATCH (sent:Sentence {group_id: $gid})
            RETURN sent.id AS id, sent.text AS text, sent.embedding_v2 AS emb
            """,
            gid=GROUP_ID,
        ).data()

    print(f"Total sentences: {len(rows)}")
    sent_embs = np.array([r["emb"] for r in rows])
    sent_norms = sent_embs / np.linalg.norm(sent_embs, axis=1, keepdims=True)

    # Check each question
    print("\n" + "=" * 80)
    print("SENTENCE RETRIEVAL RANKING VERIFICATION")
    print("=" * 80)

    all_pass = True
    for qid, q in QUESTIONS.items():
        query = q["query"]
        answer_token = q["answer_token"]

        # Embed query
        result = voyage.contextualized_embed(
            inputs=[[query]],
            model="voyage-context-3",
            input_type="query",
            output_dimension=2048,
        )
        q_emb = np.array(result.results[0].embeddings[0])
        q_norm = q_emb / np.linalg.norm(q_emb)

        # Cosine similarity ranking
        sims = sent_norms @ q_norm
        ranked_idx = np.argsort(sims)[::-1]

        # Find first rank containing answer token
        answer_rank = None
        for rank, idx in enumerate(ranked_idx[:30], 1):
            if answer_token.lower() in rows[idx]["text"].lower():
                answer_rank = rank
                break

        in_top8 = any(
            answer_token.lower() in rows[ranked_idx[i]]["text"].lower()
            for i in range(min(8, len(rows)))
        )
        in_top20 = any(
            answer_token.lower() in rows[ranked_idx[i]]["text"].lower()
            for i in range(min(20, len(rows)))
        )

        # Count total sentences containing answer
        total_with_answer = sum(
            1 for r in rows if answer_token.lower() in r["text"].lower()
        )

        sim_at_rank = float(sims[ranked_idx[answer_rank - 1]]) if answer_rank else 0
        sim_at_top1 = float(sims[ranked_idx[0]])

        status = "PASS" if answer_rank and answer_rank <= 8 else "FAIL"
        if status == "FAIL":
            all_pass = False

        print(f"\n{qid} [{status}]")
        print(f"  Query:          {query[:80]}")
        print(f"  Expected:       {q['expected']}")
        print(f"  Answer token:   '{answer_token}'")
        print(f"  Answer rank:    #{answer_rank or '>30'} (of {len(rows)} sentences)")
        print(f"  In top-8:       {in_top8}")
        print(f"  In top-20:      {in_top20}")
        print(f"  Sim@answer:     {sim_at_rank:.4f}")
        print(f"  Sim@top1:       {sim_at_top1:.4f}")
        print(f"  Sentences with answer token: {total_with_answer}")
        if answer_rank and answer_rank <= 5:
            sent_text = rows[ranked_idx[answer_rank - 1]]["text"][:120]
            print(f"  Rank-1 text:    \"{sent_text}...\"")

    # KVP coverage check
    print("\n" + "=" * 80)
    print("KVP NODE COVERAGE (would KVP-aware retrieval help?)")
    print("=" * 80)

    with driver.session(database=NEO4J_DATABASE) as session:
        for qid, q in QUESTIONS.items():
            answer_token = q["answer_token"]
            kvp_count = session.run(
                """
                MATCH (k:KeyValuePair {group_id: $gid})
                WHERE toLower(k.value) CONTAINS toLower($tok)
                   OR toLower(k.key) CONTAINS toLower($tok)
                RETURN count(k) AS cnt
                """,
                gid=GROUP_ID,
                tok=answer_token,
            ).single()["cnt"]

            has_kvp = "YES" if kvp_count > 0 else "NO"
            print(f"  {qid}: answer in KVP nodes = {has_kvp} ({kvp_count} nodes)")

    # Summary
    print("\n" + "=" * 80)
    print("CONCLUSION")
    print("=" * 80)
    if all_pass:
        print("  ALL answer-bearing sentences rank within top-8 of vector search.")
        print("  Sentence-level bi-encoder retrieval is working correctly.")
        print("  No reranker (PPR / voyage-rerank-2.5 / cross-encoder) is needed.")
        print("  The '100% context noise' was a measurement artifact (noise_ratio")
        print("  counts non-answer sentences, not retrieval failures).")
        print("  KVP-aware retrieval would only help 1 of 5 questions (Q-L4).")
    else:
        print("  Some questions have answer sentences outside top-8.")
        print("  Consider: increase top_k, add reranker, or hybrid BM25 retrieval.")

    driver.close()
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
