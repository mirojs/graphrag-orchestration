#!/usr/bin/env python3
"""Benchmark: Strategy A (flat search) vs Strategy B (graph traversal) vs Baseline.

Runs all 10 positive questions against:
  1. Route 2 baseline (entity→chunk retrieval, no skeleton)
  2. Strategy A (baseline + flat sentence vector search as supplementary evidence)
  3. Strategy B (baseline + graph traversal with NEXT/RELATED_TO expansion)

All three variants share the same LLM synthesis (gpt-5.1) and scoring.
Strategy A and B both inject evidence via the same coverage_chunks merge path.

Usage:
    python scripts/benchmark_strategy_ab.py
    python scripts/benchmark_strategy_ab.py --skip-negative
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ─── Path setup ──────────────────────────────────────────────────
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
SERVICE_ROOT = PROJECT_ROOT / "graphrag-orchestration"
for p in [str(THIS_DIR), str(PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
load_dotenv(SERVICE_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from benchmark_accuracy_utils import (
    BankQuestion,
    GroundTruth,
    calculate_accuracy_metrics,
    extract_ground_truth,
    read_question_bank,
)

# ─── Config ──────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
SYNTHESIS_MODEL = os.getenv("HYBRID_SYNTHESIS_MODEL", "gpt-5.1")
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]
GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")

DEFAULT_API_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)
DEFAULT_QUESTION_BANK = (
    PROJECT_ROOT / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md"
)


def _now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ─── Neo4j + Voyage setup ────────────────────────────────────────
from neo4j import GraphDatabase
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


def get_voyage_query_embedding(query: str) -> List[float]:
    """Embed query with Voyage contextualized_embed."""
    import voyageai
    client = voyageai.Client(api_key=VOYAGE_API_KEY)
    result = client.contextualized_embed(
        inputs=[[query]],
        model="voyage-context-3",
        input_type="query",
        output_dimension=2048,
    )
    return result.results[0].embeddings[0]


# ─── HTTP helpers ─────────────────────────────────────────────────
def _get_aad_token() -> Optional[str]:
    try:
        from azure.identity import DefaultAzureCredential
        cred = DefaultAzureCredential()
        return cred.get_token("https://management.azure.com/.default").token
    except Exception:
        return None


def call_route2_api(api_url: str, query: str, timeout: float = 120.0) -> Dict[str, Any]:
    """Call Route 2 API and return response + llm_context."""
    url = f"{api_url.rstrip('/')}/hybrid/query"
    headers = {"Content-Type": "application/json", "X-Group-ID": GROUP_ID}
    token = _get_aad_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "query": query,
        "force_route": "local_search",
        "response_type": "summary",
        "include_context": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return {
                "response": body.get("response", ""),
                "llm_context": body.get("metadata", {}).get("llm_context", ""),
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "error": None,
            }
    except Exception as e:
        return {"response": "", "llm_context": "", "elapsed_ms": 0, "error": str(e)}


# ─── Strategy A: Flat vector search ──────────────────────────────
def get_strategy_a_context(query_embedding: List[float], top_k: int = 8, threshold: float = 0.45) -> Dict:
    """Strategy A: flat sentence vector search, same as production _retrieve_skeleton_sentences."""
    cypher = """
    CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
    YIELD node AS sent, score
    WHERE sent.group_id = $group_id AND score >= $threshold
    OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
    RETURN sent.id AS sentence_id,
           sent.text AS text,
           sent.parent_text AS parent_text,
           sent.source AS source,
           sent.section_path AS section_path,
           sent.page AS page,
           doc.title AS document_title,
           score
    ORDER BY score DESC
    """
    with driver.session(database=NEO4J_DATABASE) as session:
        results = session.run(cypher, embedding=query_embedding, group_id=GROUP_ID,
                              top_k=top_k, threshold=threshold).data()

    lines = []
    for r in results:
        display = r.get("parent_text") or r.get("text", "")
        source = r.get("source", "paragraph")
        doc = r.get("document_title", "Unknown")
        section = r.get("section_path", "")
        lines.append(f"[Strategy A: {source}, sim={r['score']:.3f}, doc={doc}] {display}")

    return {
        "context_text": "\n".join(lines),
        "sentence_count": len(results),
        "total_tokens": sum(len(l.split()) for l in lines),
        "scores": [r["score"] for r in results],
    }


# ─── Strategy B: Graph traversal ─────────────────────────────────
def get_strategy_b_context(query_embedding: List[float], top_k: int = 8, threshold: float = 0.45) -> Dict:
    """Strategy B: graph traversal from seed sentences via RELATED_TO + NEXT edges."""
    cypher = """
    // ANCHOR: Vector search for seed sentences
    CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
    YIELD node AS seed, score
    WHERE seed.group_id = $group_id AND score >= $threshold

    // EXPAND: RELATED_TO (cross-chunk semantic links)
    OPTIONAL MATCH (seed)-[rel:RELATED_TO {source: 'knn_sentence'}]-(related:Sentence)
    WHERE related.group_id = $group_id

    WITH collect(DISTINCT {node: seed, score: score, via: 'seed'}) AS seeds,
         collect(DISTINCT {node: related, score: score * rel.similarity * 0.8, via: 'related_to'}) AS related_nodes
    WITH seeds + [r IN related_nodes WHERE r.node IS NOT NULL] AS all_anchors
    UNWIND all_anchors AS anchor
    WITH DISTINCT anchor.node AS sent, max(anchor.score) AS sent_score,
         collect(DISTINCT anchor.via)[0] AS via

    // EXPAND: NEXT/PREV neighbours
    CALL {
        WITH sent
        OPTIONAL MATCH (sent)-[:NEXT*1..2]->(fwd:Sentence)
        RETURN collect(DISTINCT fwd) AS fwd_list
    }
    CALL {
        WITH sent
        OPTIONAL MATCH (sent)<-[:NEXT*1..2]-(prev:Sentence)
        RETURN collect(DISTINCT prev) AS prev_list
    }

    // Merge anchor + expansions
    WITH collect({node: sent, score: sent_score, via: via, fwd: fwd_list, prev: prev_list}) AS expansions
    UNWIND expansions AS exp
    WITH collect({node: exp.node, score: exp.score, via: exp.via}) AS anchor_entries,
         [e IN expansions | [f IN e.fwd | {node: f, score: e.score * 0.9, via: 'next'}]] AS fwd_entries,
         [e IN expansions | [p IN e.prev | {node: p, score: e.score * 0.9, via: 'prev'}]] AS prev_entries
    WITH anchor_entries +
         reduce(acc=[], x IN fwd_entries | acc + x) +
         reduce(acc=[], x IN prev_entries | acc + x) AS all_entries
    UNWIND all_entries AS entry
    WITH DISTINCT entry.node AS sent, max(entry.score) AS final_score,
         collect(DISTINCT entry.via) AS sources

    // Context
    OPTIONAL MATCH (sent)-[:IN_DOCUMENT]->(doc:Document)
    RETURN sent.id AS sentence_id,
           sent.text AS text,
           sent.parent_text AS parent_text,
           sent.source AS source,
           sent.section_path AS section_path,
           sent.chunk_id AS chunk_id,
           sent.page AS page,
           doc.title AS document_title,
           final_score AS score,
           sources
    ORDER BY final_score DESC
    """
    with driver.session(database=NEO4J_DATABASE) as session:
        results = session.run(cypher, embedding=query_embedding, group_id=GROUP_ID,
                              top_k=top_k, threshold=threshold).data()

    # Format — for context expansion via NEXT, group by chunk and render contiguously
    lines = []
    seen_chunks = set()  # Track chunks we've already rendered fully
    for r in results:
        sources = r.get("sources", [])
        is_expansion = any(s in ("next", "prev") for s in sources) and "seed" not in sources
        display = r.get("parent_text") or r.get("text", "")
        source = r.get("source", "paragraph")
        doc = r.get("document_title", "Unknown")
        src_label = "|".join(sources)
        lines.append(f"[Strategy B: {src_label}, sim={r['score']:.3f}, doc={doc}] {display}")

    seed_count = sum(1 for r in results if "seed" in (r.get("sources") or []))
    related_count = sum(1 for r in results if "related_to" in (r.get("sources") or []))
    expanded_count = sum(1 for r in results if "next" in (r.get("sources") or []) or "prev" in (r.get("sources") or []))

    return {
        "context_text": "\n".join(lines),
        "sentence_count": len(results),
        "total_tokens": sum(len(l.split()) for l in lines),
        "scores": [r["score"] for r in results[:8]],
        "seeds": seed_count,
        "related": related_count,
        "expanded": expanded_count,
    }


# ─── LLM Re-synthesis ────────────────────────────────────────────
def resynthesize(query: str, route2_context: str, skeleton_context: str, label: str) -> Dict:
    """Re-synthesize with enriched context, same LLM and prompt as baseline."""
    merged = route2_context
    if skeleton_context.strip():
        merged += (
            "\n\n"
            f"=== SUPPLEMENTARY EVIDENCE ({label}) ===\n"
            "Sentence-level evidence retrieved via skeleton enrichment.\n"
            "Use this to find specific facts missed in the chunks above.\n"
            f"{skeleton_context}\n"
            "=== END SUPPLEMENTARY ===\n"
        )

    system = (
        "You are a precise document analysis assistant. Answer the question using ONLY "
        "the evidence provided below. Cite every factual claim with [N] markers. "
        "If the exact information is not present, say so explicitly.\n"
        "FORMAT: Lead with a direct answer. Support with citations [N]. "
        "Quote exact values verbatim.\n"
    )

    try:
        import openai
        client = openai.AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version="2025-01-01-preview",
        )
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=SYNTHESIS_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"EVIDENCE:\n{merged}\n\nQUESTION: {query}"},
            ],
            temperature=0.0,
            max_completion_tokens=2048,
        )
        return {
            "response": resp.choices[0].message.content or "",
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "context_tokens": len(merged.split()),
            "error": None,
        }
    except Exception as e:
        return {"response": "", "elapsed_ms": 0, "context_tokens": 0, "error": str(e)}


# ─── Evaluation ───────────────────────────────────────────────────
def evaluate(expected: str, response: str, is_negative: bool) -> Dict:
    return calculate_accuracy_metrics(expected, response, is_negative)


def verdict(bm: Dict, em: Dict, is_neg: bool) -> str:
    if is_neg:
        bp = bm.get("negative_test_pass", False)
        ep = em.get("negative_test_pass", False)
        return "TIE" if bp == ep else ("ENRICHED_WINS" if ep else "BASELINE_WINS")
    bf1 = bm.get("f1_score", 0) or 0
    ef1 = em.get("f1_score", 0) or 0
    bc = bm.get("containment", 0) or 0
    ec = em.get("containment", 0) or 0
    if ef1 > bf1 + 0.01 or (ec > bc + 0.01 and ef1 >= bf1 - 0.01):
        return "ENRICHED_WINS"
    elif bf1 > ef1 + 0.01 or (bc > ec + 0.01 and bf1 >= ef1 - 0.01):
        return "BASELINE_WINS"
    return "TIE"


# ─── Main ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Benchmark: Strategy A vs B vs Baseline")
    parser.add_argument("--url", default=DEFAULT_API_URL)
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_QUESTION_BANK)
    parser.add_argument("--skip-negative", action="store_true")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    ts = _now()
    print("=" * 80)
    print("  BENCHMARK: Strategy A vs Strategy B vs Route 2 Baseline")
    print("=" * 80)
    print(f"  API:      {args.url}")
    print(f"  Group:    {GROUP_ID}")
    print(f"  Top-k:    {args.top_k}, Threshold: {args.threshold}")
    print(f"  Model:    {SYNTHESIS_MODEL}")
    print(f"  Time:     {ts}")
    print()

    # Load questions
    questions = read_question_bank(args.question_bank, positive_prefix="Q-L", negative_prefix="Q-N")
    ground_truth = extract_ground_truth(args.question_bank)
    if args.skip_negative:
        questions = [q for q in questions if not q.qid.startswith("Q-N")]
    print(f"  Questions: {len(questions)}")
    print()

    results = []

    for i, q in enumerate(questions):
        qid, query = q.qid, q.query
        gt = ground_truth.get(qid)
        is_neg = gt.is_negative if gt else qid.startswith("Q-N")
        expected = gt.expected if gt else ""

        print(f"\n  [{i+1}/{len(questions)}] {qid}: {query[:60]}...")

        # ── 1. Route 2 Baseline ──
        print(f"    Baseline...", end=" ", flush=True)
        baseline = call_route2_api(args.url, query, args.timeout)
        if baseline["error"]:
            print(f"ERROR: {baseline['error']}")
            continue
        print(f"{baseline['elapsed_ms']}ms")

        if is_neg:
            bm = evaluate(expected, baseline["response"], True)
            print(f"    Negative: {'PASS' if bm.get('negative_test_pass') else 'FAIL'}")
            results.append({
                "qid": qid, "is_negative": True,
                "baseline": {"metrics": bm},
                "strategy_a": {"metrics": bm},
                "strategy_b": {"metrics": bm},
                "verdict_a": "TIE", "verdict_b": "TIE",
            })
            continue

        # ── 2. Get query embedding (shared by A and B) ──
        print(f"    Embedding...", end=" ", flush=True)
        t0 = time.monotonic()
        q_emb = get_voyage_query_embedding(query)
        print(f"{int((time.monotonic()-t0)*1000)}ms")

        # ── 3. Strategy A context ──
        print(f"    Strategy A...", end=" ", flush=True)
        ctx_a = get_strategy_a_context(q_emb, args.top_k, args.threshold)
        print(f"{ctx_a['sentence_count']} sentences, {ctx_a['total_tokens']} tokens")

        # ── 4. Strategy B context ──
        print(f"    Strategy B...", end=" ", flush=True)
        ctx_b = get_strategy_b_context(q_emb, args.top_k, args.threshold)
        print(f"{ctx_b['sentence_count']} sentences ({ctx_b.get('seeds',0)} seeds, "
              f"{ctx_b.get('related',0)} related, {ctx_b.get('expanded',0)} next/prev), "
              f"{ctx_b['total_tokens']} tokens")

        # ── 5. Re-synthesize with A ──
        route2_ctx = baseline["llm_context"] or baseline["response"]
        print(f"    Synth A...", end=" ", flush=True)
        resp_a = resynthesize(query, route2_ctx, ctx_a["context_text"], "Strategy A")
        if resp_a["error"]:
            print(f"ERROR: {resp_a['error']}")
            continue
        print(f"{resp_a['elapsed_ms']}ms")

        # ── 6. Re-synthesize with B ──
        print(f"    Synth B...", end=" ", flush=True)
        resp_b = resynthesize(query, route2_ctx, ctx_b["context_text"], "Strategy B")
        if resp_b["error"]:
            print(f"ERROR: {resp_b['error']}")
            continue
        print(f"{resp_b['elapsed_ms']}ms")

        # ── 7. Evaluate ──
        bm = evaluate(expected, baseline["response"], False)
        am = evaluate(expected, resp_a["response"], False)
        bm2 = evaluate(expected, resp_b["response"], False)

        va = verdict(bm, am, False)
        vb = verdict(bm, bm2, False)

        # Also compare A vs B directly
        if (bm2.get("f1_score", 0) or 0) > (am.get("f1_score", 0) or 0) + 0.01:
            vab = "B_WINS"
        elif (am.get("f1_score", 0) or 0) > (bm2.get("f1_score", 0) or 0) + 0.01:
            vab = "A_WINS"
        else:
            vab = "TIE"

        bf1 = bm.get("f1_score", 0) or 0
        af1 = am.get("f1_score", 0) or 0
        bbf1 = bm2.get("f1_score", 0) or 0
        bc = bm.get("containment", 0) or 0
        ac = am.get("containment", 0) or 0
        bbc = bm2.get("containment", 0) or 0

        print(f"    Base: F1={bf1:.3f} C={bc:.3f} | A: F1={af1:.3f} C={ac:.3f} [{va}] | "
              f"B: F1={bbf1:.3f} C={bbc:.3f} [{vb}] | A-vs-B: {vab}")

        results.append({
            "qid": qid, "query": query, "expected": expected, "is_negative": False,
            "baseline": {"metrics": bm, "response": baseline["response"][:300]},
            "strategy_a": {
                "metrics": am, "response": resp_a["response"][:300],
                "context_tokens": resp_a["context_tokens"],
                "sentence_count": ctx_a["sentence_count"],
            },
            "strategy_b": {
                "metrics": bm2, "response": resp_b["response"][:300],
                "context_tokens": resp_b["context_tokens"],
                "sentence_count": ctx_b["sentence_count"],
                "seeds": ctx_b.get("seeds", 0),
                "related": ctx_b.get("related", 0),
                "expanded": ctx_b.get("expanded", 0),
            },
            "verdict_a": va, "verdict_b": vb, "verdict_ab": vab,
        })

    # ─── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  RESULTS SUMMARY")
    print("=" * 80)

    pos = [r for r in results if not r.get("is_negative")]

    print(f"\n  {'QID':<8} {'B-F1':>6} {'A-F1':>6} {'B2-F1':>6} "
          f"{'B-C':>5} {'A-C':>5} {'B2-C':>5} {'vs-Base-A':<12} {'vs-Base-B':<12} {'A-vs-B':<8}")
    print(f"  {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*5} {'─'*5} {'─'*5} {'─'*12} {'─'*12} {'─'*8}")

    for r in pos:
        bm = r["baseline"]["metrics"]
        am = r["strategy_a"]["metrics"]
        bm2 = r["strategy_b"]["metrics"]
        print(f"  {r['qid']:<8} "
              f"{bm.get('f1_score',0) or 0:>6.3f} "
              f"{am.get('f1_score',0) or 0:>6.3f} "
              f"{bm2.get('f1_score',0) or 0:>6.3f} "
              f"{bm.get('containment',0) or 0:>5.3f} "
              f"{am.get('containment',0) or 0:>5.3f} "
              f"{bm2.get('containment',0) or 0:>5.3f} "
              f"{r['verdict_a']:<12} {r['verdict_b']:<12} {r.get('verdict_ab',''):<8}")

    # Averages
    if pos:
        def avg(items, path):
            vals = [r[path[0]]["metrics"].get(path[1], 0) or 0 for r in items]
            return sum(vals) / len(vals)

        print(f"\n  Averages ({len(pos)} positive questions):")
        print(f"  {'':>8} {'Baseline':>8} {'Strat A':>8} {'Strat B':>8}")
        print(f"  {'F1':>8} {avg(pos, ('baseline','f1_score')):>8.3f} "
              f"{avg(pos, ('strategy_a','f1_score')):>8.3f} "
              f"{avg(pos, ('strategy_b','f1_score')):>8.3f}")
        print(f"  {'Contain':>8} {avg(pos, ('baseline','containment')):>8.3f} "
              f"{avg(pos, ('strategy_a','containment')):>8.3f} "
              f"{avg(pos, ('strategy_b','containment')):>8.3f}")

        wins_a = sum(1 for r in pos if r["verdict_a"] == "ENRICHED_WINS")
        wins_b = sum(1 for r in pos if r["verdict_b"] == "ENRICHED_WINS")
        loss_a = sum(1 for r in pos if r["verdict_a"] == "BASELINE_WINS")
        loss_b = sum(1 for r in pos if r["verdict_b"] == "BASELINE_WINS")
        tie_a = sum(1 for r in pos if r["verdict_a"] == "TIE")
        tie_b = sum(1 for r in pos if r["verdict_b"] == "TIE")

        b_wins_ab = sum(1 for r in pos if r.get("verdict_ab") == "B_WINS")
        a_wins_ab = sum(1 for r in pos if r.get("verdict_ab") == "A_WINS")
        tie_ab = sum(1 for r in pos if r.get("verdict_ab") == "TIE")

        print(f"\n  Strategy A vs Baseline: {wins_a}W / {loss_a}L / {tie_a}T")
        print(f"  Strategy B vs Baseline: {wins_b}W / {loss_b}L / {tie_b}T")
        print(f"  Strategy B vs A:        {b_wins_ab}W / {a_wins_ab}L / {tie_ab}T")

    # ─── Save ─────────────────────────────────────────────────────
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"strategy_ab_{ts}.json"
    with out_path.open("w") as f:
        json.dump({"timestamp": ts, "config": vars(args), "results": results}, f,
                  indent=2, ensure_ascii=False, default=str)
    print(f"\n  Saved: {out_path}")
    print("=" * 80)

    driver.close()


if __name__ == "__main__":
    main()
