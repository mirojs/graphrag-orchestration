#!/usr/bin/env python3
"""Compare NLP vs LLM section summaries for Tier 2 structural matching.

Standalone script — reads section data from Neo4j, generates TF-IDF and
TextRank summaries locally, embeds all three variants via Voyage, and
prints side-by-side cosine-similarity rankings per benchmark question.

Usage:
    python scripts/benchmark_section_summary_comparison.py
    python scripts/benchmark_section_summary_comparison.py --filter-qid Q-D3 --show-summaries
    python scripts/benchmark_section_summary_comparison.py --group-id test-5pdfs-v2-fix2 --top-k 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup (matches benchmark_skeleton_vs_route2.py pattern)
# ---------------------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
SERVICE_ROOT = PROJECT_ROOT / "graphrag-orchestration"
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(SERVICE_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from neo4j import GraphDatabase

from benchmark_accuracy_utils import BankQuestion, read_question_bank
from nlp_section_summarizer import (
    build_structural_text,
    cosine_sim,
    generate_textrank_summaries,
    generate_tfidf_summaries,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_QUESTION_BANK = (
    PROJECT_ROOT / "docs" / "archive" / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
)

# Sections expected in top-k results for known problem queries
EXPECTED_SECTIONS: Dict[str, List[str]] = {
    "Q-D3": ["PURCHASE CONTRACT"],
}

APPROACHES = ["LLM", "TF-IDF", "TextRank"]


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def connect_neo4j():
    """Connect to Neo4j using env vars."""
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME", os.environ.get("NEO4J_USER", "neo4j"))
    password = os.environ.get("NEO4J_PASSWORD")
    if not uri or not password:
        print("ERROR: NEO4J_URI and NEO4J_PASSWORD must be set")
        sys.exit(1)
    return GraphDatabase.driver(uri, auth=(user, password))


def fetch_sections(driver, group_id: str) -> List[Dict[str, Any]]:
    """Fetch all sections with their chunk texts and existing LLM summaries."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (s:Section {group_id: $group_id})
            OPTIONAL MATCH (t:TextChunk)-[:IN_SECTION]->(s)
            WITH s, collect(t.text) AS chunk_texts
            RETURN s.id AS section_id,
                   s.title AS title,
                   s.path_key AS path_key,
                   s.summary AS llm_summary,
                   chunk_texts
            ORDER BY s.title
            """,
            group_id=group_id,
        )
        return [dict(r) for r in result]


# ---------------------------------------------------------------------------
# Voyage embedding helpers
# ---------------------------------------------------------------------------

def init_voyage():
    """Initialize VoyageEmbedService."""
    from src.worker.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService
    return VoyageEmbedService()


def embed_texts(voyage, texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts as documents."""
    if not texts:
        return []
    return voyage.embed_documents(texts)


def embed_query(voyage, query: str) -> List[float]:
    """Embed a single query string."""
    return voyage.embed_query(query)


# ---------------------------------------------------------------------------
# Question loading
# ---------------------------------------------------------------------------

def load_questions(
    qbank_path: Path,
    prefixes: Optional[List[str]] = None,
) -> List[BankQuestion]:
    """Load benchmark questions from question bank."""
    questions: List[BankQuestion] = []
    for prefix in (prefixes or ["Q-D", "Q-G"]):
        try:
            qs = read_question_bank(
                qbank_path,
                positive_prefix=prefix,
                negative_prefix="Q-NONE",
            )
            questions.extend(qs)
        except (RuntimeError, FileNotFoundError):
            pass
    return questions


# ---------------------------------------------------------------------------
# Ranking computation
# ---------------------------------------------------------------------------

def compute_rankings(
    query_emb: List[float],
    section_embeddings: Dict[str, List[float]],
    section_meta: Dict[str, Dict[str, str]],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Rank sections by cosine similarity to the query embedding.

    Returns list of {"title": ..., "score": ..., "section_id": ...}
    sorted by descending score, limited to top_k.
    """
    results = []
    for sid, emb in section_embeddings.items():
        score = cosine_sim(query_emb, emb)
        results.append({
            "section_id": sid,
            "title": section_meta[sid]["title"],
            "score": round(score, 4),
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_section_summaries(
    sections: List[Dict],
    llm_texts: Dict[str, str],
    tfidf_texts: Dict[str, str],
    textrank_texts: Dict[str, str],
):
    """Print the structural text for each section under each approach."""
    print("\n" + "=" * 80)
    print("SECTION SUMMARIES — ALL APPROACHES")
    print("=" * 80)
    for sec in sections:
        sid = sec["section_id"]
        title = sec["title"] or "(untitled)"
        print(f"\n--- {title} ---")
        print(f"  LLM:      {llm_texts.get(sid, '(none)')}")
        print(f"  TF-IDF:   {tfidf_texts.get(sid, '(none)')}")
        print(f"  TextRank: {textrank_texts.get(sid, '(none)')}")


def print_ranking_table(
    qid: str,
    query: str,
    rankings: Dict[str, List[Dict]],
    top_k: int,
):
    """Print side-by-side ranking table for one question."""
    print(f"\n{'=' * 100}")
    print(f"{qid}: {query[:90]}")
    print("=" * 100)

    # Header
    col_w = 28
    score_w = 7
    print(
        f"  {'Rank':>4}  "
        f"{'LLM':<{col_w}} {'Score':<{score_w}}  "
        f"{'TF-IDF':<{col_w}} {'Score':<{score_w}}  "
        f"{'TextRank':<{col_w}} {'Score':<{score_w}}"
    )
    print(
        f"  {'----':>4}  "
        f"{'-' * col_w} {'-' * score_w}  "
        f"{'-' * col_w} {'-' * score_w}  "
        f"{'-' * col_w} {'-' * score_w}"
    )

    for rank in range(top_k):
        parts = [f"  {rank + 1:>4}  "]
        for approach in APPROACHES:
            r = rankings[approach]
            if rank < len(r):
                title = r[rank]["title"][:col_w]
                score = f"{r[rank]['score']:.4f}"
            else:
                title = ""
                score = ""
            parts.append(f"{title:<{col_w}} {score:<{score_w}}  ")
        print("".join(parts))


def print_expected_check(
    qid: str,
    rankings: Dict[str, List[Dict]],
    expected_titles: List[str],
):
    """Check if expected sections appear in rankings for this question."""
    for expected in expected_titles:
        print(f"\n  [{qid} CHECK] Expected \"{expected}\" in top-k:")
        for approach in APPROACHES:
            found = False
            for rank, r in enumerate(rankings[approach]):
                if expected.lower() in r["title"].lower():
                    print(f"    {approach:<10} YES (rank {rank + 1}, score {r['score']:.4f})")
                    found = True
                    break
            if not found:
                print(f"    {approach:<10} NO — not in top-{len(rankings[approach])}")


def print_aggregate_stats(
    all_rankings: Dict[str, Dict[str, List[Dict]]],
    questions: List[BankQuestion],
):
    """Print aggregate comparison statistics."""
    print(f"\n{'=' * 100}")
    print("AGGREGATE COMPARISON")
    print("=" * 100)

    for approach in APPROACHES:
        top1_scores = []
        for q in questions:
            r = all_rankings.get(q.qid, {}).get(approach, [])
            if r:
                top1_scores.append(r[0]["score"])
        avg = sum(top1_scores) / len(top1_scores) if top1_scores else 0
        print(f"  {approach:<10}  avg top-1 cosine similarity: {avg:.4f}  "
              f"(n={len(top1_scores)} questions)")

    # Expected section checks
    for qid, expected_titles in EXPECTED_SECTIONS.items():
        if not expected_titles:
            continue
        for expected in expected_titles:
            print(f"\n  {qid} — \"{expected}\":")
            for approach in APPROACHES:
                r = all_rankings.get(qid, {}).get(approach, [])
                rank = None
                for i, item in enumerate(r):
                    if expected.lower() in item["title"].lower():
                        rank = i + 1
                        break
                if rank is not None:
                    print(f"    {approach:<10} rank {rank}  (score {r[rank-1]['score']:.4f})")
                else:
                    print(f"    {approach:<10} NOT FOUND in top-{len(r)}")


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def write_results(
    output_dir: Path,
    timestamp: str,
    group_id: str,
    sections: List[Dict],
    summaries: Dict[str, Dict[str, str]],
    all_rankings: Dict[str, Dict[str, List[Dict]]],
    questions: List[BankQuestion],
):
    """Write JSON and markdown reports."""
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "meta": {
            "created_utc": timestamp,
            "group_id": group_id,
            "section_count": len(sections),
            "question_count": len(questions),
            "approaches": APPROACHES,
        },
        "summaries": {},
        "rankings": {},
    }

    # Summaries per section
    for sec in sections:
        sid = sec["section_id"]
        report["summaries"][sec["title"] or sid] = {
            approach: summaries[approach].get(sid, "")
            for approach in APPROACHES
        }

    # Rankings per question
    for q in questions:
        report["rankings"][q.qid] = {
            "query": q.query,
            "results": {
                approach: all_rankings.get(q.qid, {}).get(approach, [])
                for approach in APPROACHES
            },
        }

    json_path = output_dir / f"section_summary_comparison_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON report: {json_path}")

    # Markdown summary
    md_path = output_dir / f"section_summary_comparison_{timestamp}.md"
    with open(md_path, "w") as f:
        f.write(f"# Section Summary Comparison — {timestamp}\n\n")
        f.write(f"Group: `{group_id}` | Sections: {len(sections)} | "
                f"Questions: {len(questions)}\n\n")

        # Aggregate stats
        f.write("## Aggregate\n\n")
        f.write("| Approach | Avg Top-1 Similarity |\n")
        f.write("|----------|---------------------|\n")
        for approach in APPROACHES:
            scores = []
            for q in questions:
                r = all_rankings.get(q.qid, {}).get(approach, [])
                if r:
                    scores.append(r[0]["score"])
            avg = sum(scores) / len(scores) if scores else 0
            f.write(f"| {approach} | {avg:.4f} |\n")

        # Per-question top-3
        f.write("\n## Per-Question Top-3\n\n")
        for q in questions:
            f.write(f"### {q.qid}: {q.query[:80]}\n\n")
            f.write("| Rank | LLM | Score | TF-IDF | Score | TextRank | Score |\n")
            f.write("|------|-----|-------|--------|-------|----------|-------|\n")
            for rank in range(3):
                row = [f"| {rank+1} |"]
                for approach in APPROACHES:
                    r = all_rankings.get(q.qid, {}).get(approach, [])
                    if rank < len(r):
                        row.append(f" {r[rank]['title'][:20]} | {r[rank]['score']:.4f} |")
                    else:
                        row.append(" | |")
                f.write(" ".join(row) + "\n")
            f.write("\n")

    print(f"Markdown report: {md_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare NLP vs LLM section summaries for Tier 2 matching"
    )
    parser.add_argument(
        "--group-id", default="test-5pdfs-v2-fix2",
        help="Neo4j group_id (default: test-5pdfs-v2-fix2)",
    )
    parser.add_argument(
        "--qbank", type=Path, default=DEFAULT_QUESTION_BANK,
        help="Path to question bank MD file",
    )
    parser.add_argument(
        "--top-n-keywords", type=int, default=15,
        help="TF-IDF keywords per section (default: 15)",
    )
    parser.add_argument(
        "--textrank-sentences", type=int, default=2,
        help="TextRank sentences per section (default: 2)",
    )
    parser.add_argument(
        "--filter-qid", type=str, default=None,
        help="Run only one question (e.g., Q-D3)",
    )
    parser.add_argument(
        "--show-summaries", action="store_true",
        help="Print each section's summary text before embedding",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="Show top-K sections per question (default: 5)",
    )
    parser.add_argument(
        "--prefixes", type=str, default="Q-D,Q-G",
        help="Comma-separated question prefixes to load (default: Q-D,Q-G)",
    )
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefixes = [p.strip() for p in args.prefixes.split(",")]

    # ------------------------------------------------------------------
    # Step 1: Load questions
    # ------------------------------------------------------------------
    print(f"Loading questions from {args.qbank.name} (prefixes: {prefixes})")
    questions = load_questions(args.qbank, prefixes)
    if args.filter_qid:
        questions = [q for q in questions if q.qid == args.filter_qid]
    if not questions:
        print("ERROR: No questions loaded")
        sys.exit(1)
    print(f"  {len(questions)} question(s) loaded")

    # ------------------------------------------------------------------
    # Step 2: Fetch sections from Neo4j
    # ------------------------------------------------------------------
    print(f"\nConnecting to Neo4j (group_id={args.group_id})")
    driver = connect_neo4j()
    try:
        sections = fetch_sections(driver, args.group_id)
    finally:
        driver.close()

    if not sections:
        print("ERROR: No sections found in Neo4j")
        sys.exit(1)
    print(f"  {len(sections)} sections fetched")

    # ------------------------------------------------------------------
    # Step 3: Generate NLP summaries
    # ------------------------------------------------------------------
    print("\nGenerating NLP summaries...")
    section_data = [
        {
            "id": s["section_id"],
            "title": s["title"] or "",
            "path_key": s["path_key"] or "",
            "chunk_texts": s["chunk_texts"] or [],
        }
        for s in sections
    ]

    tfidf_summaries = generate_tfidf_summaries(
        section_data, top_n=args.top_n_keywords,
    )
    textrank_summaries = generate_textrank_summaries(
        section_data, num_sentences=args.textrank_sentences,
    )
    print(f"  TF-IDF: {len(tfidf_summaries)} summaries")
    print(f"  TextRank: {len(textrank_summaries)} summaries")

    # ------------------------------------------------------------------
    # Step 4: Build structural texts for each approach
    # ------------------------------------------------------------------
    llm_texts: Dict[str, str] = {}
    tfidf_texts: Dict[str, str] = {}
    textrank_texts: Dict[str, str] = {}

    for sec in sections:
        sid = sec["section_id"]
        title = sec["title"] or ""
        path_key = sec["path_key"] or ""

        llm_texts[sid] = build_structural_text(
            title, path_key, sec["llm_summary"] or "",
        )
        tfidf_texts[sid] = build_structural_text(
            title, path_key, tfidf_summaries.get(sid, ""),
        )
        textrank_texts[sid] = build_structural_text(
            title, path_key, textrank_summaries.get(sid, ""),
        )

    # Store for reporting
    summaries_by_approach = {
        "LLM": llm_texts,
        "TF-IDF": tfidf_texts,
        "TextRank": textrank_texts,
    }

    if args.show_summaries:
        print_section_summaries(sections, llm_texts, tfidf_texts, textrank_texts)

    # ------------------------------------------------------------------
    # Step 5: Embed everything via Voyage
    # ------------------------------------------------------------------
    print("\nInitializing Voyage embedding service...")
    voyage = init_voyage()

    section_ids = [s["section_id"] for s in sections]
    section_meta = {
        s["section_id"]: {"title": s["title"] or "(untitled)"}
        for s in sections
    }

    print("Embedding section texts (3 approaches)...")
    llm_embs_list = embed_texts(voyage, [llm_texts[sid] for sid in section_ids])
    tfidf_embs_list = embed_texts(voyage, [tfidf_texts[sid] for sid in section_ids])
    textrank_embs_list = embed_texts(
        voyage, [textrank_texts[sid] for sid in section_ids],
    )

    embeddings_by_approach = {
        "LLM": dict(zip(section_ids, llm_embs_list)),
        "TF-IDF": dict(zip(section_ids, tfidf_embs_list)),
        "TextRank": dict(zip(section_ids, textrank_embs_list)),
    }

    print("Embedding queries...")
    query_embeddings: Dict[str, List[float]] = {}
    for q in questions:
        query_embeddings[q.qid] = embed_query(voyage, q.query)
    print(f"  {len(query_embeddings)} query embeddings computed")

    # ------------------------------------------------------------------
    # Step 6: Compute rankings
    # ------------------------------------------------------------------
    print("\nComputing rankings...")
    all_rankings: Dict[str, Dict[str, List[Dict]]] = {}

    for q in questions:
        q_emb = query_embeddings[q.qid]
        rankings: Dict[str, List[Dict]] = {}
        for approach in APPROACHES:
            rankings[approach] = compute_rankings(
                q_emb, embeddings_by_approach[approach],
                section_meta, top_k=args.top_k,
            )
        all_rankings[q.qid] = rankings

        # Print per-question table
        print_ranking_table(q.qid, q.query, rankings, args.top_k)

        # Check expected sections
        if q.qid in EXPECTED_SECTIONS:
            print_expected_check(q.qid, rankings, EXPECTED_SECTIONS[q.qid])

    # ------------------------------------------------------------------
    # Step 7: Aggregate stats
    # ------------------------------------------------------------------
    print_aggregate_stats(all_rankings, questions)

    # ------------------------------------------------------------------
    # Step 8: Write reports
    # ------------------------------------------------------------------
    output_dir = PROJECT_ROOT / "benchmarks"
    write_results(
        output_dir, timestamp, args.group_id,
        sections, summaries_by_approach, all_rankings, questions,
    )

    print("\nDone.")


if __name__ == "__main__":
    main()
