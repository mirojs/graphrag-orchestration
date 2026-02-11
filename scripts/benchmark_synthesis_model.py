#!/usr/bin/env python3
"""Benchmark: gpt-5.1 vs gpt-4.1-mini for skeleton sentence synthesis.

Since sentence retrieval is precise (answer at rank #1 for all questions),
the synthesis task is simple extraction — a smaller model may match quality
at lower latency and cost.

Compares side-by-side on identical retrieved context (Strategy B).

Usage:
    python scripts/benchmark_synthesis_model.py
    python scripts/benchmark_synthesis_model.py --models gpt-5.1 gpt-4.1-mini gpt-4o-mini
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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
    calculate_accuracy_metrics,
    extract_ground_truth,
    read_question_bank,
)

# ─── Config ──────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
VOYAGE_API_KEY = os.environ["VOYAGE_API_KEY"]
GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")
DEFAULT_QUESTION_BANK = (
    PROJECT_ROOT / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md"
)

DEFAULT_MODELS = ["gpt-5.1", "gpt-4.1-mini"]

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from neo4j import GraphDatabase
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


# ─── Tokenizer ───────────────────────────────────────────────────
def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9$%.,/'-]+", text.lower())


def _token_set(text: str) -> Set[str]:
    return set(_tokenize(text))


# ─── Voyage embedding ───────────────────────────────────────────
def get_voyage_query_embedding(query: str) -> List[float]:
    import voyageai
    client = voyageai.Client(api_key=VOYAGE_API_KEY)
    result = client.contextualized_embed(
        inputs=[[query]],
        model="voyage-context-3",
        input_type="query",
        output_dimension=2048,
    )
    return result.results[0].embeddings[0]


# ─── Strategy B retrieval (reused from deep benchmark) ───────────
def get_strategy_b_context(query_embedding: List[float], top_k: int = 8, threshold: float = 0.45) -> Dict:
    cypher = """
    CALL db.index.vector.queryNodes('sentence_embeddings_v2', $top_k, $embedding)
    YIELD node AS seed, score
    WHERE seed.group_id = $group_id AND score >= $threshold

    OPTIONAL MATCH (seed)-[rel:RELATED_TO {source: 'knn_sentence'}]-(related:Sentence)
    WHERE related.group_id = $group_id

    WITH collect(DISTINCT {node: seed, score: score, via: 'seed'}) AS seeds,
         collect(DISTINCT {node: related, score: score * rel.similarity * 0.8, via: 'related_to'}) AS related_nodes
    WITH seeds + [r IN related_nodes WHERE r.node IS NOT NULL] AS all_anchors
    UNWIND all_anchors AS anchor
    WITH DISTINCT anchor.node AS sent, max(anchor.score) AS sent_score,
         collect(DISTINCT anchor.via)[0] AS via

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
    t0 = time.monotonic()
    with driver.session(database=NEO4J_DATABASE) as session:
        results = session.run(cypher, embedding=query_embedding, group_id=GROUP_ID,
                              top_k=top_k, threshold=threshold).data()
    retrieval_ms = int((time.monotonic() - t0) * 1000)

    sentences = []
    lines = []
    for r in results:
        display = r.get("parent_text") or r.get("text", "")
        source = r.get("source", "paragraph")
        doc = r.get("document_title", "Unknown")
        srcs = r.get("sources", ["seed"])
        line = f"[{source}, sim={r['score']:.3f}, doc={doc}, via={'+'.join(srcs)}] {display}"
        lines.append(line)
        sentences.append({"text": display, "score": r["score"], "source": source, "document": doc})

    return {
        "context_text": "\n".join(lines),
        "sentences": sentences,
        "sentence_count": len(results),
        "context_words": sum(len(s["text"].split()) for s in sentences),
        "retrieval_ms": retrieval_ms,
    }


# ─── Synthesis ───────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are a precise document analysis assistant. Answer the question using ONLY "
    "the evidence provided below. Cite every factual claim with [N] markers. "
    "If the exact information is not present, say so explicitly.\n"
    "FORMAT: Lead with a direct answer. Support with citations [N]. "
    "Quote exact values verbatim.\n"
)


def synthesize(query: str, context: str, model: str) -> Dict:
    """Call Azure OpenAI chat completion with the given model."""
    import openai
    client = openai.AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version="2025-01-01-preview",
    )
    try:
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"EVIDENCE:\n{context}\n\nQUESTION: {query}"},
            ],
            temperature=0.0,
            max_completion_tokens=2048,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        txt = resp.choices[0].message.content or ""
        usage = resp.usage
        return {
            "response": txt,
            "elapsed_ms": elapsed_ms,
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "error": None,
        }
    except Exception as e:
        return {"response": "", "elapsed_ms": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "error": str(e)}


# ─── Main ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Benchmark synthesis models on skeleton context")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                        help="Models to compare (default: gpt-5.1 gpt-4.1-mini)")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_QUESTION_BANK)
    args = parser.parse_args()

    questions_v = read_question_bank(args.question_bank, positive_prefix="Q-V")
    questions_l = read_question_bank(args.question_bank, positive_prefix="Q-L")
    questions = questions_v + questions_l
    ground_truth = extract_ground_truth(args.question_bank)
    models = args.models

    # Filter to positive questions only
    pos_questions = []
    for q in questions:
        gt = ground_truth.get(q.qid)
        is_neg = (gt.is_negative if gt else q.qid.startswith("Q-N"))
        if not is_neg and gt:
            pos_questions.append((q, gt))

    print(f"\n{'='*90}")
    print(f"  SYNTHESIS MODEL BENCHMARK: {' vs '.join(models)}")
    print(f"  Questions: {len(pos_questions)} positive, Strategy B retrieval")
    print(f"{'='*90}")

    results = []

    for i, (q, gt) in enumerate(pos_questions):
        expected = gt.expected
        print(f"\n  [{i+1}/{len(pos_questions)}] {q.qid}: {q.query[:60]}...")

        # Embed query (once per question)
        print(f"    Embedding...", end=" ", flush=True)
        t0 = time.monotonic()
        q_emb = get_voyage_query_embedding(q.query)
        emb_ms = int((time.monotonic() - t0) * 1000)
        print(f"{emb_ms}ms")

        # Retrieve context (once per question — same for all models)
        print(f"    Retrieval...", end=" ", flush=True)
        ctx = get_strategy_b_context(q_emb, args.top_k, args.threshold)
        print(f"{ctx['sentence_count']}sent, {ctx['context_words']}w, {ctx['retrieval_ms']}ms")

        row: Dict[str, Any] = {
            "qid": q.qid,
            "query": q.query,
            "expected": expected,
            "retrieval_ms": ctx["retrieval_ms"],
            "embedding_ms": emb_ms,
            "sentence_count": ctx["sentence_count"],
            "context_words": ctx["context_words"],
            "models": {},
        }

        # Synthesize with each model
        for model in models:
            print(f"    {model}...", end=" ", flush=True)
            result = synthesize(q.query, ctx["context_text"], model)
            if result["error"]:
                print(f"ERROR: {result['error']}")
                row["models"][model] = {"error": result["error"]}
                continue

            # Accuracy metrics
            metrics = calculate_accuracy_metrics(expected, result["response"], False)
            f1 = metrics.get("f1_score", 0) or 0
            containment = metrics.get("containment_score", 0) or 0
            resp_words = len(result["response"].split())

            print(f"{result['elapsed_ms']}ms, {resp_words}w, F1={f1:.3f}, contain={containment:.3f}")

            row["models"][model] = {
                "response": result["response"],
                "elapsed_ms": result["elapsed_ms"],
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
                "response_words": resp_words,
                "f1": f1,
                "containment": containment,
                "metrics": metrics,
            }

        results.append(row)

    # ═════════════════════════════════════════════════════════════
    # SUMMARY
    # ═════════════════════════════════════════════════════════════
    print(f"\n{'='*90}")
    print(f"  SUMMARY: {' vs '.join(models)}")
    print(f"{'='*90}")

    # Per-question comparison
    header = f"  {'QID':<8}"
    for m in models:
        short = m.replace("gpt-", "")
        header += f"  {short+'-ms':>9} {short+'-F1':>8} {short+'-cnt':>9} {short+'-w':>6} {short+'-pt':>8}"
    print(header)
    print(f"  {'─'*8}" + f"  {'─'*9} {'─'*8} {'─'*9} {'─'*6} {'─'*8}" * len(models))

    for r in results:
        line = f"  {r['qid']:<8}"
        for m in models:
            mr = r["models"].get(m, {})
            if "error" in mr:
                line += f"  {'ERR':>9} {'':>8} {'':>9} {'':>6} {'':>8}"
            else:
                line += (f"  {mr.get('elapsed_ms',0):>9} {mr.get('f1',0):>8.3f} "
                        f"{mr.get('containment',0):>9.3f} {mr.get('response_words',0):>6} "
                        f"{mr.get('prompt_tokens',0):>8}")
        print(line)

    # Aggregates
    print(f"  {'─'*8}" + f"  {'─'*9} {'─'*8} {'─'*9} {'─'*6} {'─'*8}" * len(models))
    agg_line = f"  {'AVG':<8}"
    for m in models:
        valid = [r["models"][m] for r in results if m in r["models"] and "error" not in r["models"][m]]
        if valid:
            avg_ms = sum(v["elapsed_ms"] for v in valid) / len(valid)
            avg_f1 = sum(v["f1"] for v in valid) / len(valid)
            avg_cnt = sum(v["containment"] for v in valid) / len(valid)
            avg_w = sum(v["response_words"] for v in valid) / len(valid)
            avg_pt = sum(v["prompt_tokens"] for v in valid) / len(valid)
            agg_line += f"  {avg_ms:>9.0f} {avg_f1:>8.3f} {avg_cnt:>9.3f} {avg_w:>6.0f} {avg_pt:>8.0f}"
        else:
            agg_line += f"  {'N/A':>9} {'':>8} {'':>9} {'':>6} {'':>8}"
    print(agg_line)

    # Win/Loss/Tie (first model is reference)
    if len(models) >= 2:
        ref = models[0]
        for challenger in models[1:]:
            wins = losses = ties = 0
            for r in results:
                ref_r = r["models"].get(ref, {})
                chal_r = r["models"].get(challenger, {})
                if "error" in ref_r or "error" in chal_r:
                    continue
                ref_f1 = ref_r.get("f1", 0)
                chal_f1 = chal_r.get("f1", 0)
                if abs(ref_f1 - chal_f1) < 0.01:
                    ties += 1
                elif chal_f1 > ref_f1:
                    wins += 1
                else:
                    losses += 1
            ref_valid = [r["models"][ref] for r in results if ref in r["models"] and "error" not in r["models"][ref]]
            chal_valid = [r["models"][challenger] for r in results if challenger in r["models"] and "error" not in r["models"][challenger]]
            ref_avg_ms = sum(v["elapsed_ms"] for v in ref_valid) / len(ref_valid) if ref_valid else 0
            chal_avg_ms = sum(v["elapsed_ms"] for v in chal_valid) / len(chal_valid) if chal_valid else 0
            speedup = ref_avg_ms / chal_avg_ms if chal_avg_ms else 0
            ref_avg_pt = sum(v["prompt_tokens"] for v in ref_valid) / len(ref_valid) if ref_valid else 0
            chal_avg_pt = sum(v["prompt_tokens"] for v in chal_valid) / len(chal_valid) if chal_valid else 0

            print(f"\n  {challenger} vs {ref}:  {wins}W / {losses}L / {ties}T")
            print(f"    Speed:  {ref_avg_ms:.0f}ms → {chal_avg_ms:.0f}ms ({speedup:.1f}x faster)")
            print(f"    Tokens: {ref_avg_pt:.0f} → {chal_avg_pt:.0f} prompt tokens/query")

    # Save results
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)
    ts = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"synthesis_model_{ts}.json"
    with open(out_file, "w") as f:
        json.dump({
            "timestamp": ts,
            "models": models,
            "top_k": args.top_k,
            "threshold": args.threshold,
            "group_id": GROUP_ID,
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n  Results saved: {out_file}")

    driver.close()


if __name__ == "__main__":
    main()
