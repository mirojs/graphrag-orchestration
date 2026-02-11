#!/usr/bin/env python3
"""Deep analysis benchmark: Strategy A vs Strategy B vs Baseline.

Captures all dimensions the quick benchmark missed:
  1. Latency breakdown (API, embedding, retrieval, synthesis per strategy)
  2. Full response text (no truncation) + word/char counts
  3. Context noise analysis (what % of injected sentences are irrelevant to answer)
  4. LLM output noise analysis (what % of output tokens are filler vs ground truth)

Usage:
    python scripts/benchmark_strategy_ab_deep.py
    python scripts/benchmark_strategy_ab_deep.py --skip-negative
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
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


# ─── Neo4j ────────────────────────────────────────────────────────
from neo4j import GraphDatabase
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


# ─── Tokenizer helpers ────────────────────────────────────────────
def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer for metric computation."""
    return re.findall(r"[a-zA-Z0-9$%.,/'-]+", text.lower())


def _token_set(text: str) -> Set[str]:
    return set(_tokenize(text))


# ─── Voyage embedding ────────────────────────────────────────────
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


# ─── HTTP helpers ─────────────────────────────────────────────────
def _get_aad_token() -> Optional[str]:
    try:
        from azure.identity import DefaultAzureCredential
        cred = DefaultAzureCredential()
        return cred.get_token("https://management.azure.com/.default").token
    except Exception:
        return None


def call_route2_api(api_url: str, query: str, timeout: float = 120.0) -> Dict[str, Any]:
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
        line = f"[Strategy A: {source}, sim={r['score']:.3f}, doc={doc}] {display}"
        lines.append(line)
        sentences.append({
            "text": display,
            "score": r["score"],
            "source": source,
            "document": doc,
        })

    return {
        "context_text": "\n".join(lines),
        "sentences": sentences,
        "sentence_count": len(results),
        "context_words": sum(len(s["text"].split()) for s in sentences),
        "context_chars": sum(len(s["text"]) for s in sentences),
        "retrieval_ms": retrieval_ms,
        "scores": [r["score"] for r in results],
    }


# ─── Strategy B: Graph traversal ─────────────────────────────────
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
        srcs = r.get("sources", [])
        display = r.get("parent_text") or r.get("text", "")
        source = r.get("source", "paragraph")
        doc = r.get("document_title", "Unknown")
        src_label = "|".join(srcs)
        line = f"[Strategy B: {src_label}, sim={r['score']:.3f}, doc={doc}] {display}"
        lines.append(line)
        sentences.append({
            "text": display,
            "score": r["score"],
            "source": source,
            "document": doc,
            "via": srcs,
        })

    seed_count = sum(1 for r in results if "seed" in (r.get("sources") or []))
    related_count = sum(1 for r in results if "related_to" in (r.get("sources") or []))
    expanded_count = sum(1 for r in results if "next" in (r.get("sources") or []) or "prev" in (r.get("sources") or []))

    return {
        "context_text": "\n".join(lines),
        "sentences": sentences,
        "sentence_count": len(results),
        "context_words": sum(len(s["text"].split()) for s in sentences),
        "context_chars": sum(len(s["text"]) for s in sentences),
        "retrieval_ms": retrieval_ms,
        "scores": [r["score"] for r in results[:8]],
        "seeds": seed_count,
        "related": related_count,
        "expanded": expanded_count,
    }


# ─── LLM Re-synthesis ────────────────────────────────────────────
def resynthesize(query: str, route2_context: str, skeleton_context: str, label: str) -> Dict:
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
        elapsed = int((time.monotonic() - t0) * 1000)
        txt = resp.choices[0].message.content or ""
        usage = resp.usage
        return {
            "response": txt,
            "elapsed_ms": elapsed,
            "merged_context_words": len(merged.split()),
            "merged_context_chars": len(merged),
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
            "error": None,
        }
    except Exception as e:
        return {"response": "", "elapsed_ms": 0, "merged_context_words": 0,
                "merged_context_chars": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "error": str(e)}


# ─── Noise Analysis ──────────────────────────────────────────────
def analyze_context_noise(sentences: List[Dict], expected: str) -> Dict:
    """Analyze retrieval quality and context dilution.

    PRIMARY metrics (retrieval quality — did we get the right sentences?):
    - recall_at_k: 1 if ANY top-k sentence contains expected answer, else 0
    - signal_rank: rank of first sentence containing expected token (1-based, 0=not found)
    - signal_sentences: # sentences containing ≥1 expected token

    SECONDARY metrics (context dilution — how focused is the context?):
    - dilution_ratio: fraction of sentences NOT containing expected tokens (was: noise_ratio)
    - signal_density: expected_token_hits / total_context_tokens

    NOTE (2026-02-11): 'noise_ratio' was renamed to 'dilution_ratio' because high values
    do NOT indicate retrieval failure. With expected='2010-06-15' and top_k=8, only 1 of
    8 sentences will contain that token → 87.5% dilution, even when the answer is at rank #1.
    See scripts/verify_sentence_retrieval_ranking.py for proof all answers rank #1.
    """
    if not expected or not sentences:
        return {"recall_at_k": 0, "signal_rank": 0,
                "signal_sentences": 0, "noise_sentences": 0,
                "noise_ratio": 1.0, "dilution_ratio": 1.0,
                "signal_density": 0.0, "total_sentences": len(sentences),
                "expected_tokens_searched": 0}

    expected_tokens = _token_set(expected)
    # Remove very common words that would inflate signal
    stop_words = {"the", "a", "an", "is", "in", "of", "and", "to", "for", "with", "on", "at", "by"}
    expected_tokens -= stop_words

    signal_count = 0
    signal_rank = 0  # rank of first signal sentence (1-based)
    total_context_tokens = 0
    signal_token_hits = 0

    for i, s in enumerate(sentences):
        s_tokens = _tokenize(s["text"])
        s_token_set = set(s_tokens)
        total_context_tokens += len(s_tokens)
        overlap = expected_tokens & s_token_set
        if overlap:
            signal_count += 1
            signal_token_hits += sum(1 for t in s_tokens if t in expected_tokens)
            if signal_rank == 0:
                signal_rank = i + 1  # 1-based

    noise_count = len(sentences) - signal_count
    dilution = noise_count / len(sentences) if sentences else 1.0
    recall = 1 if signal_count > 0 else 0

    return {
        # Primary: retrieval quality
        "recall_at_k": recall,
        "signal_rank": signal_rank,
        "signal_sentences": signal_count,
        # Secondary: context dilution (renamed from noise_ratio)
        "noise_sentences": noise_count,
        "noise_ratio": dilution,       # kept for backward compat with saved JSON
        "dilution_ratio": dilution,
        "signal_density": signal_token_hits / total_context_tokens if total_context_tokens > 0 else 0.0,
        "total_sentences": len(sentences),
        "expected_tokens_searched": len(expected_tokens),
    }


def analyze_output_noise(response: str, expected: str, context_text: str) -> Dict:
    """How noisy is the LLM output?

    Metrics:
    - response_words: total words in response
    - response_chars: total chars in response
    - bloat_ratio: response_words / expected_words (1.0 = perfectly concise)
    - output_precision: fraction of response tokens present in expected
    - grounded_ratio: fraction of response tokens traceable to context
    - hallucination_tokens: response tokens not in context AND not in expected
    """
    resp_tokens = _tokenize(response)
    expected_tokens = _token_set(expected) if expected else set()
    context_tokens = _token_set(context_text) if context_text else set()

    # Remove citation markers like [1], [2] and common boilerplate
    resp_tokens_clean = [t for t in resp_tokens
                         if not re.match(r'^\[\d+\]$', t) and t not in
                         {"the", "a", "an", "is", "in", "of", "and", "to", "for", "with", "on", "at", "by",
                          "this", "that", "it", "as", "be", "was", "are", "were", "been", "has", "have",
                          "not", "but", "or", "from", "which", "their", "they", "its", "also", "can", "may",
                          "will", "would", "should", "could", "shall", "into", "than", "between", "these",
                          "those", "such", "so", "if", "then", "each", "all", "any", "both", "no", "nor",
                          "other"}]

    expected_words = _tokenize(expected) if expected else []

    # Tokens in response that match expected answer
    matched_expected = sum(1 for t in resp_tokens_clean if t in expected_tokens)
    # Tokens in response that come from context
    grounded = sum(1 for t in resp_tokens_clean if t in context_tokens)
    # Hallucination: not in context AND not in expected
    halluc = sum(1 for t in resp_tokens_clean if t not in context_tokens and t not in expected_tokens)

    return {
        "response_words": len(response.split()),
        "response_chars": len(response),
        "expected_words": len(expected_words),
        "bloat_ratio": len(response.split()) / max(len(expected_words), 1),
        "output_precision": matched_expected / max(len(resp_tokens_clean), 1),
        "grounded_ratio": grounded / max(len(resp_tokens_clean), 1),
        "hallucination_tokens": halluc,
        "hallucination_ratio": halluc / max(len(resp_tokens_clean), 1),
        "clean_content_tokens": len(resp_tokens_clean),
    }


# ─── Main ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Deep benchmark: A vs B vs Baseline")
    parser.add_argument("--url", default=DEFAULT_API_URL)
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_QUESTION_BANK)
    parser.add_argument("--skip-negative", action="store_true")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    ts = _now()
    print("=" * 90)
    print("  DEEP BENCHMARK: Strategy A vs Strategy B vs Route 2 Baseline")
    print("=" * 90)
    print(f"  API:      {args.url}")
    print(f"  Group:    {GROUP_ID}")
    print(f"  Model:    {SYNTHESIS_MODEL}")
    print(f"  Time:     {ts}")
    print()

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

        # ── 1. Baseline ──
        print(f"    Baseline...", end=" ", flush=True)
        baseline = call_route2_api(args.url, query, args.timeout)
        if baseline["error"]:
            print(f"ERROR: {baseline['error']}")
            continue
        print(f"{baseline['elapsed_ms']}ms, {len(baseline['response'].split())}w")

        if is_neg:
            bm = calculate_accuracy_metrics(expected, baseline["response"], True)
            results.append({"qid": qid, "is_negative": True, "baseline": {"metrics": bm}})
            continue

        # ── 2. Embed query ──
        print(f"    Embedding...", end=" ", flush=True)
        t0 = time.monotonic()
        q_emb = get_voyage_query_embedding(query)
        emb_ms = int((time.monotonic() - t0) * 1000)
        print(f"{emb_ms}ms")

        # ── 3. Strategy A retrieval ──
        print(f"    Strategy A retrieval...", end=" ", flush=True)
        ctx_a = get_strategy_a_context(q_emb, args.top_k, args.threshold)
        print(f"{ctx_a['sentence_count']}sent, {ctx_a['context_words']}w, {ctx_a['retrieval_ms']}ms")

        # ── 4. Strategy B retrieval ──
        print(f"    Strategy B retrieval...", end=" ", flush=True)
        ctx_b = get_strategy_b_context(q_emb, args.top_k, args.threshold)
        print(f"{ctx_b['sentence_count']}sent ({ctx_b.get('seeds',0)}s+"
              f"{ctx_b.get('related',0)}r+{ctx_b.get('expanded',0)}e), "
              f"{ctx_b['context_words']}w, {ctx_b['retrieval_ms']}ms")

        # ── 5. Synthesis A ──
        route2_ctx = baseline["llm_context"] or baseline["response"]
        print(f"    Synthesis A...", end=" ", flush=True)
        resp_a = resynthesize(query, route2_ctx, ctx_a["context_text"], "Strategy A")
        if resp_a["error"]:
            print(f"ERROR: {resp_a['error']}")
            continue
        print(f"{resp_a['elapsed_ms']}ms, {resp_a['completion_tokens']}tok, {len(resp_a['response'].split())}w")

        # ── 6. Synthesis B ──
        print(f"    Synthesis B...", end=" ", flush=True)
        resp_b = resynthesize(query, route2_ctx, ctx_b["context_text"], "Strategy B")
        if resp_b["error"]:
            print(f"ERROR: {resp_b['error']}")
            continue
        print(f"{resp_b['elapsed_ms']}ms, {resp_b['completion_tokens']}tok, {len(resp_b['response'].split())}w")

        # ── 7. Accuracy metrics ──
        bm = calculate_accuracy_metrics(expected, baseline["response"], False)
        am = calculate_accuracy_metrics(expected, resp_a["response"], False)
        bm2 = calculate_accuracy_metrics(expected, resp_b["response"], False)

        # ── 8. Context noise analysis ──
        noise_a = analyze_context_noise(ctx_a["sentences"], expected)
        noise_b = analyze_context_noise(ctx_b["sentences"], expected)

        # ── 9. Output noise analysis ──
        out_base = analyze_output_noise(baseline["response"], expected, route2_ctx)
        out_a = analyze_output_noise(resp_a["response"], expected, route2_ctx + "\n" + ctx_a["context_text"])
        out_b = analyze_output_noise(resp_b["response"], expected, route2_ctx + "\n" + ctx_b["context_text"])

        # Verdicts
        bf1 = bm.get("f1_score", 0) or 0
        af1 = am.get("f1_score", 0) or 0
        bbf1 = bm2.get("f1_score", 0) or 0

        print(f"    F1:  B={bf1:.3f}  A={af1:.3f}  B2={bbf1:.3f}")
        print(f"    Recall@k:      A={noise_a['recall_at_k']}  B={noise_b['recall_at_k']}  "
              f"(signal rank: A=#{noise_a['signal_rank']}, B=#{noise_b['signal_rank']})")
        print(f"    Ctx dilution:  A={noise_a['dilution_ratio']:.0%} ({noise_a['noise_sentences']}/{noise_a['total_sentences']})  "
              f"B={noise_b['dilution_ratio']:.0%} ({noise_b['noise_sentences']}/{noise_b['total_sentences']})")
        print(f"    Output bloat:  Base={out_base['bloat_ratio']:.1f}x  A={out_a['bloat_ratio']:.1f}x  B={out_b['bloat_ratio']:.1f}x")
        print(f"    Grounded:      Base={out_base['grounded_ratio']:.0%}  A={out_a['grounded_ratio']:.0%}  B={out_b['grounded_ratio']:.0%}")
        print(f"    Halluc ratio:  Base={out_base['hallucination_ratio']:.0%}  A={out_a['hallucination_ratio']:.0%}  B={out_b['hallucination_ratio']:.0%}")

        results.append({
            "qid": qid,
            "query": query,
            "expected": expected,
            "is_negative": False,
            # Timing
            "timing": {
                "baseline_api_ms": baseline["elapsed_ms"],
                "embedding_ms": emb_ms,
                "strategy_a_retrieval_ms": ctx_a["retrieval_ms"],
                "strategy_b_retrieval_ms": ctx_b["retrieval_ms"],
                "strategy_a_synthesis_ms": resp_a["elapsed_ms"],
                "strategy_b_synthesis_ms": resp_b["elapsed_ms"],
                "strategy_a_total_ms": baseline["elapsed_ms"] + emb_ms + ctx_a["retrieval_ms"] + resp_a["elapsed_ms"],
                "strategy_b_total_ms": baseline["elapsed_ms"] + emb_ms + ctx_b["retrieval_ms"] + resp_b["elapsed_ms"],
            },
            # Response lengths
            "response_length": {
                "baseline_words": len(baseline["response"].split()),
                "baseline_chars": len(baseline["response"]),
                "strategy_a_words": len(resp_a["response"].split()),
                "strategy_a_chars": len(resp_a["response"]),
                "strategy_b_words": len(resp_b["response"].split()),
                "strategy_b_chars": len(resp_b["response"]),
            },
            # Token usage
            "token_usage": {
                "strategy_a_prompt": resp_a["prompt_tokens"],
                "strategy_a_completion": resp_a["completion_tokens"],
                "strategy_b_prompt": resp_b["prompt_tokens"],
                "strategy_b_completion": resp_b["completion_tokens"],
            },
            # Context stats
            "context_stats": {
                "strategy_a_sentences": ctx_a["sentence_count"],
                "strategy_a_words": ctx_a["context_words"],
                "strategy_b_sentences": ctx_b["sentence_count"],
                "strategy_b_words": ctx_b["context_words"],
                "strategy_b_seeds": ctx_b.get("seeds", 0),
                "strategy_b_related": ctx_b.get("related", 0),
                "strategy_b_expanded": ctx_b.get("expanded", 0),
            },
            # Accuracy
            "accuracy": {
                "baseline": bm,
                "strategy_a": am,
                "strategy_b": bm2,
            },
            # Context noise
            "context_noise": {
                "strategy_a": noise_a,
                "strategy_b": noise_b,
            },
            # Output noise
            "output_noise": {
                "baseline": out_base,
                "strategy_a": out_a,
                "strategy_b": out_b,
            },
            # Full responses (not truncated)
            "responses": {
                "baseline": baseline["response"],
                "strategy_a": resp_a["response"],
                "strategy_b": resp_b["response"],
            },
        })

    # ═══════════════════════════════════════════════════════════════
    # SUMMARY TABLES
    # ═══════════════════════════════════════════════════════════════
    pos = [r for r in results if not r.get("is_negative")]
    if not pos:
        print("\n  No positive results to summarize.")
        driver.close()
        return

    print("\n" + "=" * 90)
    print("  RESULTS SUMMARY")
    print("=" * 90)

    # ── Table 1: Speed ──
    print("\n  ┌─── LATENCY (ms) ─────────────────────────────────────────────────┐")
    print(f"  │ {'QID':<8} {'Base API':>8} {'Embed':>6} {'A-Retr':>7} {'B-Retr':>7} "
          f"{'A-Synth':>8} {'B-Synth':>8} {'A-Total':>8} {'B-Total':>8} │")
    print(f"  │ {'─'*8} {'─'*8} {'─'*6} {'─'*7} {'─'*7} {'─'*8} {'─'*8} {'─'*8} {'─'*8} │")
    for r in pos:
        t = r["timing"]
        print(f"  │ {r['qid']:<8} {t['baseline_api_ms']:>8} {t['embedding_ms']:>6} "
              f"{t['strategy_a_retrieval_ms']:>7} {t['strategy_b_retrieval_ms']:>7} "
              f"{t['strategy_a_synthesis_ms']:>8} {t['strategy_b_synthesis_ms']:>8} "
              f"{t['strategy_a_total_ms']:>8} {t['strategy_b_total_ms']:>8} │")
    # Averages
    def avg_t(key):
        return int(sum(r["timing"][key] for r in pos) / len(pos))
    print(f"  │ {'AVG':<8} {avg_t('baseline_api_ms'):>8} {avg_t('embedding_ms'):>6} "
          f"{avg_t('strategy_a_retrieval_ms'):>7} {avg_t('strategy_b_retrieval_ms'):>7} "
          f"{avg_t('strategy_a_synthesis_ms'):>8} {avg_t('strategy_b_synthesis_ms'):>8} "
          f"{avg_t('strategy_a_total_ms'):>8} {avg_t('strategy_b_total_ms'):>8} │")
    print(f"  └──────────────────────────────────────────────────────────────────┘")

    # ── Table 2: Response Length ──
    print("\n  ┌─── RESPONSE LENGTH (words / chars) ────────────────────────────────────┐")
    print(f"  │ {'QID':<8} {'Base-W':>7} {'Base-C':>7} {'A-W':>6} {'A-C':>7} "
          f"{'B-W':>6} {'B-C':>7} {'Expect-W':>9} │")
    print(f"  │ {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*7} {'─'*6} {'─'*7} {'─'*9} │")
    for r in pos:
        rl = r["response_length"]
        exp_w = len(r["expected"].split()) if r["expected"] else 0
        print(f"  │ {r['qid']:<8} {rl['baseline_words']:>7} {rl['baseline_chars']:>7} "
              f"{rl['strategy_a_words']:>6} {rl['strategy_a_chars']:>7} "
              f"{rl['strategy_b_words']:>6} {rl['strategy_b_chars']:>7} "
              f"{exp_w:>9} │")
    def avg_rl(key):
        return int(sum(r["response_length"][key] for r in pos) / len(pos))
    print(f"  │ {'AVG':<8} {avg_rl('baseline_words'):>7} {avg_rl('baseline_chars'):>7} "
          f"{avg_rl('strategy_a_words'):>6} {avg_rl('strategy_a_chars'):>7} "
          f"{avg_rl('strategy_b_words'):>6} {avg_rl('strategy_b_chars'):>7} "
          f"{'':>9} │")
    print(f"  └───────────────────────────────────────────────────────────────────────┘")

    # ── Table 3: Token Usage ──
    print("\n  ┌─── LLM TOKEN USAGE ─────────────────────────────────────────┐")
    print(f"  │ {'QID':<8} {'A-Prompt':>9} {'A-Compl':>8} {'B-Prompt':>9} {'B-Compl':>8} │")
    print(f"  │ {'─'*8} {'─'*9} {'─'*8} {'─'*9} {'─'*8} │")
    for r in pos:
        tu = r["token_usage"]
        print(f"  │ {r['qid']:<8} {tu['strategy_a_prompt']:>9} {tu['strategy_a_completion']:>8} "
              f"{tu['strategy_b_prompt']:>9} {tu['strategy_b_completion']:>8} │")
    def avg_tu(key):
        return int(sum(r["token_usage"][key] for r in pos) / len(pos))
    print(f"  │ {'AVG':<8} {avg_tu('strategy_a_prompt'):>9} {avg_tu('strategy_a_completion'):>8} "
          f"{avg_tu('strategy_b_prompt'):>9} {avg_tu('strategy_b_completion'):>8} │")
    print(f"  └────────────────────────────────────────────────────────────┘")

    # ── Table 4: Retrieval Quality + Context Dilution ──
    print("\n  ┌─── RETRIEVAL QUALITY & CONTEXT DILUTION ────────────────────────────────────────────────────┐")
    print(f"  │ {'QID':<8} {'A-Rcl':>6} {'A-Rank':>7} {'A-Sig':>6} {'A-Dilut':>8} {'A-Dens':>7} "
          f"{'B-Rcl':>6} {'B-Rank':>7} {'B-Sig':>6} {'B-Dilut':>8} {'B-Dens':>7} │")
    print(f"  │ {'─'*8} {'─'*6} {'─'*7} {'─'*6} {'─'*8} {'─'*7} {'─'*6} {'─'*7} {'─'*6} {'─'*8} {'─'*7} │")
    for r in pos:
        na = r["context_noise"]["strategy_a"]
        nb = r["context_noise"]["strategy_b"]
        print(f"  │ {r['qid']:<8} {na['recall_at_k']:>6} {('#'+str(na['signal_rank']) if na['signal_rank'] else 'N/A'):>7} {na['signal_sentences']:>6} "
              f"{na['dilution_ratio']:>7.0%} {na['signal_density']:>7.1%} "
              f"{nb['recall_at_k']:>6} {('#'+str(nb['signal_rank']) if nb['signal_rank'] else 'N/A'):>7} {nb['signal_sentences']:>6} "
              f"{nb['dilution_ratio']:>7.0%} {nb['signal_density']:>7.1%} │")
    def avg_cn(strat, key):
        vals = [r["context_noise"][strat][key] for r in pos]
        return sum(vals) / len(vals)
    print(f"  │ {'AVG':<8} {avg_cn('strategy_a','recall_at_k'):>6.1f} {'':>7} {avg_cn('strategy_a','signal_sentences'):>6.1f} "
          f"{avg_cn('strategy_a','dilution_ratio'):>7.0%} {avg_cn('strategy_a','signal_density'):>7.1%} "
          f"{avg_cn('strategy_b','recall_at_k'):>6.1f} {'':>7} {avg_cn('strategy_b','signal_sentences'):>6.1f} "
          f"{avg_cn('strategy_b','dilution_ratio'):>7.0%} {avg_cn('strategy_b','signal_density'):>7.1%} │")
    print(f"  └──────────────────────────────────────────────────────────────────────────────────────────┘")

    # ── Table 5: Output Noise ──
    print("\n  ┌─── OUTPUT NOISE (LLM response quality) ──────────────────────────────────────────────────┐")
    print(f"  │ {'QID':<8} {'B-Bloat':>8} {'A-Bloat':>8} {'B2-Bloat':>9} "
          f"{'B-Ground':>9} {'A-Ground':>9} {'B2-Ground':>10} "
          f"{'B-Halluc':>9} {'A-Halluc':>9} {'B2-Halluc':>10} │")
    print(f"  │ {'─'*8} {'─'*8} {'─'*8} {'─'*9} {'─'*9} {'─'*9} {'─'*10} {'─'*9} {'─'*9} {'─'*10} │")
    for r in pos:
        ob = r["output_noise"]["baseline"]
        oa = r["output_noise"]["strategy_a"]
        obb = r["output_noise"]["strategy_b"]
        print(f"  │ {r['qid']:<8} {ob['bloat_ratio']:>7.1f}x {oa['bloat_ratio']:>7.1f}x {obb['bloat_ratio']:>8.1f}x "
              f"{ob['grounded_ratio']:>8.0%} {oa['grounded_ratio']:>8.0%} {obb['grounded_ratio']:>9.0%} "
              f"{ob['hallucination_ratio']:>8.0%} {oa['hallucination_ratio']:>8.0%} {obb['hallucination_ratio']:>9.0%} │")
    def avg_on(strat, key):
        vals = [r["output_noise"][strat][key] for r in pos]
        return sum(vals) / len(vals)
    print(f"  │ {'AVG':<8} {avg_on('baseline','bloat_ratio'):>7.1f}x {avg_on('strategy_a','bloat_ratio'):>7.1f}x "
          f"{avg_on('strategy_b','bloat_ratio'):>8.1f}x "
          f"{avg_on('baseline','grounded_ratio'):>8.0%} {avg_on('strategy_a','grounded_ratio'):>8.0%} "
          f"{avg_on('strategy_b','grounded_ratio'):>9.0%} "
          f"{avg_on('baseline','hallucination_ratio'):>8.0%} {avg_on('strategy_a','hallucination_ratio'):>8.0%} "
          f"{avg_on('strategy_b','hallucination_ratio'):>9.0%} │")
    print(f"  └─────────────────────────────────────────────────────────────────────────────────────────┘")

    # ── Table 6: Accuracy (recap) ──
    print("\n  ┌─── ACCURACY ───────────────────────────────────────────────┐")
    print(f"  │ {'QID':<8} {'B-F1':>6} {'A-F1':>6} {'B2-F1':>6} "
          f"{'B-C':>5} {'A-C':>5} {'B2-C':>5} │")
    print(f"  │ {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*5} {'─'*5} {'─'*5} │")
    for r in pos:
        ba = r["accuracy"]
        print(f"  │ {r['qid']:<8} "
              f"{ba['baseline'].get('f1_score',0) or 0:>6.3f} "
              f"{ba['strategy_a'].get('f1_score',0) or 0:>6.3f} "
              f"{ba['strategy_b'].get('f1_score',0) or 0:>6.3f} "
              f"{ba['baseline'].get('containment',0) or 0:>5.3f} "
              f"{ba['strategy_a'].get('containment',0) or 0:>5.3f} "
              f"{ba['strategy_b'].get('containment',0) or 0:>5.3f} │")
    def avg_acc(strat, key):
        vals = [r["accuracy"][strat].get(key, 0) or 0 for r in pos]
        return sum(vals) / len(vals)
    print(f"  │ {'AVG':<8} "
          f"{avg_acc('baseline','f1_score'):>6.3f} {avg_acc('strategy_a','f1_score'):>6.3f} {avg_acc('strategy_b','f1_score'):>6.3f} "
          f"{avg_acc('baseline','containment'):>5.3f} {avg_acc('strategy_a','containment'):>5.3f} {avg_acc('strategy_b','containment'):>5.3f} │")
    print(f"  └─────────────────────────────────────────────────────────┘")

    # ── Executive Summary ──
    print("\n  ═══ EXECUTIVE SUMMARY ═══")
    print(f"  Avg Baseline API latency:      {avg_t('baseline_api_ms'):>6}ms")
    print(f"  Avg embedding latency:         {avg_t('embedding_ms'):>6}ms")
    print(f"  Avg Strategy A total latency:  {avg_t('strategy_a_total_ms'):>6}ms  "
          f"(+{avg_t('strategy_a_total_ms') - avg_t('baseline_api_ms')}ms over baseline)")
    print(f"  Avg Strategy B total latency:  {avg_t('strategy_b_total_ms'):>6}ms  "
          f"(+{avg_t('strategy_b_total_ms') - avg_t('baseline_api_ms')}ms over baseline)")
    print()
    print(f"  Avg response length:  Base={avg_rl('baseline_words')}w  A={avg_rl('strategy_a_words')}w  B={avg_rl('strategy_b_words')}w")
    print(f"  Avg output bloat:     Base={avg_on('baseline','bloat_ratio'):.1f}x  A={avg_on('strategy_a','bloat_ratio'):.1f}x  B={avg_on('strategy_b','bloat_ratio'):.1f}x")
    print()
    print(f"  Avg context noise:    A={avg_cn('strategy_a','noise_ratio'):.0%}  B={avg_cn('strategy_b','noise_ratio'):.0%}")
    print(f"  Avg signal density:   A={avg_cn('strategy_a','signal_density'):.1%}  B={avg_cn('strategy_b','signal_density'):.1%}")
    print()
    print(f"  Avg grounded ratio:   Base={avg_on('baseline','grounded_ratio'):.0%}  A={avg_on('strategy_a','grounded_ratio'):.0%}  B={avg_on('strategy_b','grounded_ratio'):.0%}")
    print(f"  Avg halluc ratio:     Base={avg_on('baseline','hallucination_ratio'):.0%}  A={avg_on('strategy_a','hallucination_ratio'):.0%}  B={avg_on('strategy_b','hallucination_ratio'):.0%}")
    print()
    print(f"  Avg F1:               Base={avg_acc('baseline','f1_score'):.3f}  A={avg_acc('strategy_a','f1_score'):.3f}  B={avg_acc('strategy_b','f1_score'):.3f}")
    print(f"  Avg Containment:      Base={avg_acc('baseline','containment'):.3f}  A={avg_acc('strategy_a','containment'):.3f}  B={avg_acc('strategy_b','containment'):.3f}")

    # ── Save ──
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"strategy_ab_deep_{ts}.json"
    with out_path.open("w") as f:
        json.dump({"timestamp": ts, "config": vars(args), "results": results}, f,
                  indent=2, ensure_ascii=False, default=str)
    print(f"\n  Saved: {out_path}")
    print("=" * 90)

    driver.close()


if __name__ == "__main__":
    main()
