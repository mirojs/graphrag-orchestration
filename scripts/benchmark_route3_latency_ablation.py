#!/usr/bin/env python3
"""Route 3 Latency Ablation: Community Reduction vs Reranking.

Isolates the dominant latency factor by testing 4 configurations:
  A: 37 communities, no rerank  (original baseline ~58s)
  B: 10 communities, no rerank  (isolate community reduction)
  C: 37 communities, rerank on  (isolate reranking effect)
  D: 10 communities, rerank on  (current production ~2-3s)

Runs a subset of benchmark questions through each config and measures
wall-clock latency at each stage (community match, MAP, rerank, REDUCE).

Usage:
    python scripts/benchmark_route3_latency_ablation.py
    python scripts/benchmark_route3_latency_ablation.py --questions 3
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Path setup ────────────────────────────────────────────────
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
APP_ROOT = PROJECT_ROOT / "graphrag-orchestration"
for p in [str(THIS_DIR), str(PROJECT_ROOT), str(APP_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(APP_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from openai import AzureOpenAI

# ─── Config ────────────────────────────────────────────────────
ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
API_KEY = os.environ["AZURE_OPENAI_API_KEY"]
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

# Use gpt-4.1 for all configs (proven 100% coverage in ablation, fast)
MODEL = os.getenv("ABLATION_MODEL", "gpt-4.1")

GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")
NEO4J_URI = os.environ.get("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "")
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")

MAP_PARALLEL_WORKERS = 5


# ─── 4 ablation configs ───────────────────────────────────────
CONFIGS = {
    "A_baseline":    {"community_top_k": 37, "rerank": False, "label": "37 communities, no rerank"},
    "B_comm_only":   {"community_top_k": 10, "rerank": False, "label": "10 communities, no rerank"},
    "C_rerank_only": {"community_top_k": 37, "rerank": True,  "label": "37 communities, rerank on"},
    "D_current":     {"community_top_k": 10, "rerank": True,  "label": "10 communities, rerank on"},
}


# ─── Prompts (concise — proven best variant) ───────────────────
MAP_PROMPT = """\
You are an analytical assistant performing the MAP phase of a global search.

**Task**: Extract specific, factual claims from the community summary below
that are relevant to the user's query. Each claim must be self-contained
(understandable without reading the summary) and cite the community as source.

**Query**: {query}

**Community**: {community_title}
**Key Entities**: {entity_names}
**Summary**:
{community_summary}

**Instructions**:
1. Read the summary carefully.
2. List up to {max_claims} claims that help answer the query.
3. Each claim must:
   - State a specific fact, relationship, or provision (not a vague theme).
   - Be a complete sentence.
   - Include entity names, amounts, dates, or conditions where present.
4. If NOTHING in the summary is relevant, respond with exactly:
   NO RELEVANT CLAIMS
5. Do NOT invent information not present in the summary.

**Output format** (numbered list):
1. [First factual claim]
2. [Second factual claim]
...
"""

REDUCE_PROMPT = """\
You are a document analysis assistant. Answer the query using the evidence below.

**Query**: {query}

**Community Claims**:
{community_claims}

**Document Sentences**:
{sentence_evidence}

**Rules**:
1. Use both sources. Include facts from sentences even if not in claims.
2. Organize by theme with clear headings.
3. Keep specific details: names, amounts, dates, conditions.
4. 3-5 focused paragraphs maximum — prioritize the most important findings.
5. Do not mention methodology or sources.
6. If no evidence, say: "The requested information was not found in the available documents."

**Answer**:
"""


# ─── Test questions (subset for speed) ─────────────────────────
QUESTIONS = [
    {
        "id": "T-1",
        "query": "What are the common themes across all the contracts and agreements in these documents?",
        "expected_themes": ["legal obligations", "payment terms", "termination clauses",
                            "liability provisions", "dispute resolution"],
    },
    {
        "id": "T-4",
        "query": "Summarize the risk management and liability provisions across all documents.",
        "expected_themes": ["indemnification", "limitation of liability",
                            "insurance requirements", "warranties"],
    },
    {
        "id": "T-6",
        "query": "How do the documents address confidentiality and data protection?",
        "expected_themes": ["NDA provisions", "data handling", "privacy",
                            "disclosure limitations"],
    },
]


# ─── Theme evaluation ─────────────────────────────────────────
THEME_SYNONYMS: Dict[str, List[str]] = {
    "indemnification": ["indemnif", "indemnit", "hold harmless", "defend and indemnify"],
    "privacy": ["privacy", "personal data", "data protection", "confidential information"],
}

def _theme_in_text(theme: str, text: str) -> bool:
    tl, xl = theme.lower(), text.lower()
    if tl in xl:
        return True
    for syn in THEME_SYNONYMS.get(tl, []):
        if syn in xl:
            return True
    words = [w for w in tl.split() if len(w) >= 4]
    if words:
        hits = sum(1 for w in words if w in xl)
        if hits >= max(1, len(words) * 0.5):
            return True
    return False


def check_theme_coverage(response: str, themes: List[str]) -> Tuple[float, Dict[str, bool]]:
    details = {t: _theme_in_text(t, response) for t in themes}
    found = sum(1 for v in details.values() if v)
    return (found / len(themes) if themes else 0.0, details)


# ─── Neo4j: fetch communities ─────────────────────────────────
def get_all_communities() -> List[Dict[str, Any]]:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    communities = []
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Community)
            WHERE c.group_id = $gid
            OPTIONAL MATCH (c)<-[:BELONGS_TO]-(e:Entity)
            WITH c, collect(e.name) AS entity_names
            RETURN c.title AS title, c.summary AS summary,
                   entity_names, c.community_id AS cid
            ORDER BY cid
        """, gid=GROUP_ID)
        for r in result:
            communities.append({
                "title": r["title"] or f"Community {r['cid']}",
                "summary": r["summary"] or "",
                "entity_names": r["entity_names"] or [],
            })
    driver.close()
    return communities


def get_community_embeddings() -> Dict[str, List[float]]:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    embeddings = {}
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Community)
            WHERE c.group_id = $gid AND c.embedding IS NOT NULL
            RETURN c.title AS title, c.embedding AS embedding
        """, gid=GROUP_ID)
        for r in result:
            if r["embedding"]:
                embeddings[r["title"]] = list(r["embedding"])
    driver.close()
    return embeddings


def cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def match_communities(
    query_embedding: List[float],
    communities: List[Dict[str, Any]],
    embeddings: Dict[str, List[float]],
    top_k: int,
) -> List[Dict[str, Any]]:
    scored = []
    for c in communities:
        title = c.get("title", "")
        emb = embeddings.get(title)
        if emb and len(query_embedding) == len(emb):
            scored.append((c, cosine_sim(query_embedding, emb)))
    scored.sort(key=lambda x: x[1], reverse=True)
    matched = [c for c, s in scored[:top_k] if s >= 0.05]
    if not matched:
        return communities  # fallback
    return matched


# ─── Sentence search ──────────────────────────────────────────
def get_sentence_evidence(query_embedding: List[float], top_k: int = 30, threshold: float = 0.2) -> List[Dict[str, Any]]:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    sentences = []
    with driver.session() as session:
        result = session.run("""
            CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
            YIELD node, score
            WHERE node.group_id = $gid AND score >= $threshold
            OPTIONAL MATCH (node)-[:IN_DOCUMENT]->(d:Document)
            RETURN node.text AS text, node.id AS sentence_id,
                   d.title AS document_title, score
            ORDER BY score DESC
        """, top_k=top_k, embedding=query_embedding, threshold=threshold, gid=GROUP_ID)
        for r in result:
            sentences.append({
                "text": r["text"] or "",
                "sentence_id": r["sentence_id"],
                "document_title": r["document_title"],
                "score": r["score"],
            })
    driver.close()
    return sentences


# ─── Denoise (mirrors production _denoise_sentences) ──────────
def denoise_sentences(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = []
    for ev in evidence:
        text = ev.get("text", "").strip()
        if len(re.findall(r"<[^>]+>", text)) >= 2:
            continue
        if len(text) < 25:
            continue
        if re.search(r"(?i)(signature|signed this|print\)|registration number|authorized representative)", text):
            continue
        if len(text) < 60 and text.endswith(":"):
            continue
        if len(text) < 50 and not re.search(r"[.?!]", text):
            continue
        cleaned.append(ev)
    return cleaned


# ─── Rerank ────────────────────────────────────────────────────
def rerank_sentences(query: str, evidence: List[Dict[str, Any]], top_k: int = 15) -> List[Dict[str, Any]]:
    import voyageai
    vc = voyageai.Client(api_key=VOYAGE_API_KEY)
    docs = [ev.get("text", "") for ev in evidence]
    rr = vc.rerank(query=query, documents=docs, model="rerank-2.5", top_k=min(top_k, len(docs)))
    reranked = []
    for r in rr.results:
        ev = {**evidence[r.index], "rerank_score": r.relevance_score}
        reranked.append(ev)
    return reranked


# ─── LLM call ─────────────────────────────────────────────────
def call_llm(prompt: str) -> Tuple[str, int]:
    client = AzureOpenAI(api_key=API_KEY, api_version=API_VERSION, azure_endpoint=ENDPOINT)
    t0 = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.0,
        )
        text = resp.choices[0].message.content or ""
        ms = int((time.monotonic() - t0) * 1000)
        return (text.strip(), ms)
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return (f"ERROR: {e}", ms)


def _parse_numbered_list(text: str) -> List[str]:
    lines = text.strip().split("\n")
    claims, current = [], ""
    for line in lines:
        s = line.strip()
        if re.match(r"^\d+[\.\)]\s+", s):
            if current:
                claims.append(current.strip())
            current = re.sub(r"^\d+[\.\)]\s+", "", s)
        elif current and s:
            current += " " + s
    if current:
        claims.append(current.strip())
    return claims


# ─── MAP one community ────────────────────────────────────────
def map_one(query: str, community: Dict, max_claims: int = 10) -> Tuple[str, List[str], int]:
    title = community.get("title", "Untitled")
    summary = community.get("summary", "")
    entities = ", ".join(community.get("entity_names", [])[:20])
    if not summary.strip():
        return (title, [], 0)
    prompt = MAP_PROMPT.format(
        query=query, community_title=title, community_summary=summary,
        entity_names=entities or "N/A", max_claims=max_claims,
    )
    text, ms = call_llm(prompt)
    if "NO RELEVANT CLAIMS" in text.upper():
        return (title, [], ms)
    return (title, _parse_numbered_list(text)[:max_claims], ms)


def run_map(query: str, communities: List[Dict]) -> Tuple[List[str], int]:
    all_claims = []
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=MAP_PARALLEL_WORKERS) as ex:
        futures = {ex.submit(map_one, query, c): c for c in communities}
        for f in as_completed(futures):
            title, claims, _ = f.result()
            for claim in claims:
                all_claims.append(f"[Community: {title}] {claim}")
    return (all_claims, int((time.monotonic() - t0) * 1000))


def run_reduce(query: str, claims: List[str], sentences: List[Dict]) -> Tuple[str, int]:
    claims_text = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1)) if claims else "(No claims)"
    if sentences:
        ev_lines = [f"{i}. [Source: {e.get('document_title','?')}, {e.get('score',0):.2f}] {e.get('text','')}"
                     for i, e in enumerate(sentences, 1)]
        ev_text = "\n".join(ev_lines)
    else:
        ev_text = "(No sentence evidence)"
    prompt = REDUCE_PROMPT.format(query=query, community_claims=claims_text, sentence_evidence=ev_text)
    return call_llm(prompt)


# ─── Main ablation ────────────────────────────────────────────
def run_latency_ablation(num_questions: int = 3):
    print("=" * 78)
    print("  ROUTE 3 LATENCY ABLATION: Community Reduction vs Reranking")
    print("=" * 78)
    print(f"  Model:     {MODEL}")
    print(f"  Questions: {num_questions}")
    print(f"  Group:     {GROUP_ID}")
    print(f"  Configs:   {', '.join(CONFIGS.keys())}")
    print("=" * 78)

    # Phase 0: Load data
    print("\n--- Loading communities and embeddings from Neo4j ---")
    all_communities = get_all_communities()
    embeddings = get_community_embeddings()
    print(f"  {len(all_communities)} communities, {len(embeddings)} with embeddings")

    # Pre-embed queries with Voyage (shared across configs)
    print("--- Embedding queries with Voyage ---")
    import voyageai
    vc = voyageai.Client(api_key=VOYAGE_API_KEY)

    questions = QUESTIONS[:num_questions]
    query_embeddings = {}
    for q in questions:
        resp = vc.contextualized_embed(
            inputs=[[q["query"]]], model="voyage-context-3",
            input_type="query", output_dimension=2048,
        )
        query_embeddings[q["id"]] = resp.results[0].embeddings[0]
    print(f"  Embedded {len(query_embeddings)} queries")

    # Run each config
    all_results: Dict[str, List[Dict]] = {}

    for config_name, config in CONFIGS.items():
        top_k = config["community_top_k"]
        do_rerank = config["rerank"]
        print(f"\n{'='*78}")
        print(f"  CONFIG: {config_name} — {config['label']}")
        print(f"{'='*78}")

        config_results = []

        for qi, q in enumerate(questions, 1):
            qid = q["id"]
            query = q["query"]
            print(f"\n  [{qi}/{len(questions)}] {qid}: {query[:60]}")

            timings: Dict[str, int] = {}
            t_total = time.monotonic()

            # Step 1: Community matching
            t0 = time.monotonic()
            matched = match_communities(query_embeddings[qid], all_communities, embeddings, top_k)
            timings["community_match_ms"] = int((time.monotonic() - t0) * 1000)
            print(f"    Communities: {len(matched)}/{len(all_communities)} ({timings['community_match_ms']}ms)")

            # Step 1B: Sentence search (shared data, but measured per-config for wall-clock)
            t0 = time.monotonic()
            raw_sentences = get_sentence_evidence(query_embeddings[qid])
            timings["sentence_search_ms"] = int((time.monotonic() - t0) * 1000)
            print(f"    Sentences: {len(raw_sentences)} ({timings['sentence_search_ms']}ms)")

            # Step 2: MAP (parallel)
            t0 = time.monotonic()
            claims, map_ms = run_map(query, matched)
            timings["map_ms"] = map_ms
            print(f"    MAP: {len(claims)} claims from {len(matched)} communities ({map_ms}ms)")

            # Step 2B: Denoise + optional rerank
            t0 = time.monotonic()
            sentences = denoise_sentences(raw_sentences)
            timings["denoise_ms"] = int((time.monotonic() - t0) * 1000)

            if do_rerank and sentences:
                t0 = time.monotonic()
                sentences = rerank_sentences(query, sentences)
                timings["rerank_ms"] = int((time.monotonic() - t0) * 1000)
                print(f"    Rerank: {len(raw_sentences)}→{len(sentences)} ({timings['rerank_ms']}ms)")
            else:
                timings["rerank_ms"] = 0
                # Without rerank, keep top 15 by vector score
                sentences = sentences[:15]

            # Step 3: REDUCE
            t0 = time.monotonic()
            response, reduce_ms = run_reduce(query, claims, sentences)
            timings["reduce_ms"] = reduce_ms
            timings["total_ms"] = int((time.monotonic() - t_total) * 1000)

            # Evaluate quality
            is_error = response.startswith("ERROR:")
            theme_cov, theme_details = (0.0, {}) if is_error else check_theme_coverage(response, q["expected_themes"])

            print(f"    REDUCE: {len(response)} chars ({reduce_ms}ms)")
            print(f"    TOTAL: {timings['total_ms']}ms | Coverage: {theme_cov:.0%}")
            for t_name, t_hit in theme_details.items():
                if not t_hit:
                    print(f"      MISS: {t_name}")

            config_results.append({
                "question_id": qid,
                "query": query,
                "config": config_name,
                "community_top_k": top_k,
                "rerank_enabled": do_rerank,
                "communities_matched": len(matched),
                "claims_count": len(claims),
                "sentences_raw": len(raw_sentences),
                "sentences_after_denoise": len(denoise_sentences(raw_sentences)),
                "sentences_final": len(sentences),
                "timings": timings,
                "theme_coverage": theme_cov,
                "theme_details": theme_details,
                "word_count": len(response.split()) if not is_error else 0,
                "is_error": is_error,
            })

        all_results[config_name] = config_results

    # ─── Analysis ────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("  LATENCY ABLATION RESULTS")
    print("=" * 78)

    print(f"\n  {'Config':<20} {'Communities':>12} {'MAP ms':>8} {'Rerank ms':>10} "
          f"{'REDUCE ms':>10} {'TOTAL ms':>9} {'Coverage':>9} {'Claims':>7}")
    print(f"  {'-'*18}  {'-'*10}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*5}")

    config_avgs: Dict[str, Dict[str, float]] = {}
    for config_name, results in all_results.items():
        valid = [r for r in results if not r["is_error"]]
        if not valid:
            print(f"  {config_name:<20} ALL ERRORS")
            continue
        avg_comm = sum(r["communities_matched"] for r in valid) / len(valid)
        avg_map = sum(r["timings"]["map_ms"] for r in valid) / len(valid)
        avg_rerank = sum(r["timings"]["rerank_ms"] for r in valid) / len(valid)
        avg_reduce = sum(r["timings"]["reduce_ms"] for r in valid) / len(valid)
        avg_total = sum(r["timings"]["total_ms"] for r in valid) / len(valid)
        avg_cov = sum(r["theme_coverage"] for r in valid) / len(valid)
        avg_claims = sum(r["claims_count"] for r in valid) / len(valid)

        config_avgs[config_name] = {
            "avg_communities": avg_comm,
            "avg_map_ms": avg_map,
            "avg_rerank_ms": avg_rerank,
            "avg_reduce_ms": avg_reduce,
            "avg_total_ms": avg_total,
            "avg_coverage": avg_cov,
            "avg_claims": avg_claims,
        }

        print(f"  {config_name:<20} {avg_comm:>10.0f}  {avg_map:>7.0f}  {avg_rerank:>9.0f}  "
              f"{avg_reduce:>9.0f}  {avg_total:>8.0f}  {avg_cov:>8.0%}  {avg_claims:>6.1f}")

    # ─── Factor decomposition ────────────────────────────────────
    if all(k in config_avgs for k in ["A_baseline", "B_comm_only", "C_rerank_only", "D_current"]):
        A = config_avgs["A_baseline"]["avg_total_ms"]
        B = config_avgs["B_comm_only"]["avg_total_ms"]
        C = config_avgs["C_rerank_only"]["avg_total_ms"]
        D = config_avgs["D_current"]["avg_total_ms"]

        comm_effect = A - B
        rerank_effect = A - C
        interaction = (A - D) - comm_effect - rerank_effect
        total_improvement = A - D

        print(f"\n  --- Factor Decomposition ---")
        print(f"  Total improvement (A→D):         {total_improvement:>8.0f} ms")
        print(f"  Community reduction effect (A-B): {comm_effect:>8.0f} ms  ({comm_effect/total_improvement*100:>5.1f}%)")
        print(f"  Reranking effect (A-C):           {rerank_effect:>8.0f} ms  ({rerank_effect/total_improvement*100:>5.1f}%)")
        print(f"  Interaction effect:               {interaction:>8.0f} ms  ({interaction/total_improvement*100:>5.1f}%)")
        print()

        if comm_effect > rerank_effect:
            dominant = "Community reduction"
            ratio = comm_effect / max(rerank_effect, 1)
        else:
            dominant = "Reranking"
            ratio = rerank_effect / max(comm_effect, 1)
        print(f"  DOMINANT FACTOR: {dominant} ({ratio:.1f}x larger effect)")

    # ─── Save ────────────────────────────────────────────────────
    ts = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = PROJECT_ROOT / f"benchmark_route3_latency_ablation_{ts}.json"
    with open(output_path, "w") as f:
        json.dump({
            "benchmark_type": "route3_latency_ablation",
            "timestamp": ts,
            "group_id": GROUP_ID,
            "model": MODEL,
            "num_questions": num_questions,
            "configs": {k: v for k, v in CONFIGS.items()},
            "config_averages": config_avgs,
            "results": all_results,
        }, f, indent=2)
    print(f"\n  Results saved to: {output_path}")
    print("=" * 78)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Route 3 latency ablation: community reduction vs reranking")
    parser.add_argument("--questions", type=int, default=3, help="Number of questions (1-3)")
    args = parser.parse_args()
    run_latency_ablation(args.questions)
