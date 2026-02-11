#!/usr/bin/env python3
"""
Benchmark: Skeleton Sentence Context vs Route 2 Baseline

Strategy A evaluation — "Context Enrichment":
  - Phase 1: Call Route 2 API normally → capture context + response (baseline)
  - Phase 2: Build skeleton in-memory, get sentence-level context for same query
  - Phase 3: Merge skeleton context into Route 2's context, re-synthesize via LLM
  - Phase 4: Compare baseline vs enriched on ground-truth metrics

This is a FAIR A/B test:
  - Same PPR entity retrieval (no changes to Route 2 pipeline)
  - Same de-noising, same prompt template, same LLM
  - Only difference: skeleton sentences APPENDED as supplementary evidence
  - If enriched > baseline → skeleton adds value to Route 2 retrieval

Architecture:
  ┌─────────────────────────────────────────────────┐
  │ Route 2 (unchanged)                              │
  │  NER → PPR → chunks → de-noise → context        │──→ Baseline Response
  │                                    ↓             │
  │                              [llm_context]       │
  │                                    +             │
  │  Skeleton (in-memory)              ↓             │
  │  Neo4j chunks → spaCy → Voyage → Stage 1-3      │
  │                                    ↓             │
  │                          [sentence evidence]     │──→ Enriched Response
  │                                    ↓             │
  │                        Merged context → LLM      │
  └─────────────────────────────────────────────────┘

Metrics (same as existing Route 2 benchmark):
  - Containment (recall ≥ 0.8 OR substring match)
  - F1 / Precision / Recall (token-level)
  - Negative test pass rate
  - Context tokens (efficiency)
  - Latency

Usage:
    python scripts/benchmark_skeleton_vs_route2.py
    python scripts/benchmark_skeleton_vs_route2.py --group-id test-5pdfs-v2-fix2
    python scripts/benchmark_skeleton_vs_route2.py --url http://localhost:8000 --repeats 1
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Path setup
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

# Import shared accuracy utils
from benchmark_accuracy_utils import (
    BankQuestion,
    GroundTruth,
    calculate_accuracy_metrics,
    extract_ground_truth,
    normalize_text,
    read_question_bank,
)

# Import skeleton components (reuse, don't duplicate)
from experiment_hybrid_skeleton import (
    HybridSkeleton,
    build_skeleton,
    build_sparse_semantic_links,
    embed_query,
    embed_sentences,
    extract_chunks_from_neo4j,
    stage1_semantic_anchor,
    stage2_context_expansion,
    stage3_rerank_and_select,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
SYNTHESIS_MODEL = os.getenv("HYBRID_SYNTHESIS_MODEL", "gpt-5.1")

DEFAULT_API_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

DEFAULT_QUESTION_BANK = (
    PROJECT_ROOT / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md"
)


def _default_group_id() -> str:
    env = os.getenv("TEST_GROUP_ID") or os.getenv("GROUP_ID")
    if env:
        return env
    p = PROJECT_ROOT / "last_test_group_id.txt"
    try:
        if p.exists():
            return p.read_text().strip() or "test-5pdfs-v2-fix2"
    except Exception:
        pass
    return "test-5pdfs-v2-fix2"


def _now_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _get_aad_token() -> Optional[str]:
    """Try Azure AD token for API auth."""
    try:
        from azure.identity import DefaultAzureCredential
        cred = DefaultAzureCredential()
        token = cred.get_token("https://management.azure.com/.default")
        return token.token
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTTP client (stdlib, no requests dependency)
# ---------------------------------------------------------------------------
def _http_post(url: str, headers: Dict, payload: Dict, timeout: float = 120.0) -> Tuple[int, Dict, float, Optional[str]]:
    """POST JSON → (status, json_body, elapsed_secs, error_msg)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body, time.monotonic() - t0, None
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {"error": str(e)}
        return e.code, err_body, time.monotonic() - t0, str(e)
    except Exception as e:
        return 0, {}, time.monotonic() - t0, str(e)


# ---------------------------------------------------------------------------
# Phase 1: Route 2 Baseline Call
# ---------------------------------------------------------------------------
def call_route2_baseline(
    api_url: str,
    group_id: str,
    query: str,
    response_type: str = "summary",
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """Call Route 2 API with include_context=true to capture LLM context.

    Returns:
        {
            "response": str,       # LLM answer
            "llm_context": str,    # Raw evidence context sent to LLM
            "citations": [...],
            "metadata": {...},
            "elapsed_ms": int,
            "status": int,
            "error": str | None,
        }
    """
    url = f"{api_url.rstrip('/')}/hybrid/query"
    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": group_id,
    }
    token = _get_aad_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "query": query,
        "force_route": "local_search",
        "response_type": response_type,
        "include_context": True,
    }

    status, body, elapsed, err = _http_post(url, headers, payload, timeout)

    return {
        "response": body.get("response", ""),
        "llm_context": body.get("metadata", {}).get("llm_context", ""),
        "citations": body.get("citations", []),
        "metadata": body.get("metadata", {}),
        "evidence_path": body.get("evidence_path", []),
        "elapsed_ms": int(elapsed * 1000),
        "status": status,
        "error": err,
    }


# ---------------------------------------------------------------------------
# Phase 2: Skeleton Sentence Context Builder
# ---------------------------------------------------------------------------
def get_skeleton_context(
    skeleton: HybridSkeleton,
    query: str,
    top_k: int = 5,
    expand_window: int = 2,
) -> Dict[str, Any]:
    """Run skeleton three-stage retrieval for a query.

    Returns structured sentence-level context that can be merged
    into Route 2's LLM prompt.
    """
    q_emb = embed_query(query)
    anchors = stage1_semantic_anchor(skeleton, q_emb, top_k)
    anchor_ids = [a[0] for a in anchors]
    expanded = stage2_context_expansion(skeleton, anchor_ids, expand_window)
    selected = stage3_rerank_and_select(expanded, query, max_chunks=top_k)

    # Format as structured evidence text
    evidence_lines = []
    total_tokens = 0
    sentence_count = 0

    for sel in selected:
        chunk_id = sel.get("chunk_id", "")
        chunk = skeleton.chunks.get(chunk_id, {})
        doc_title = chunk.get("doc_title", "Unknown")
        section = sel.get("section_path", "[Unknown]")

        evidence_lines.append(f"\n--- Sentence evidence from: {doc_title} / {section} ---")
        for cs in sel.get("context_sentences", []):
            marker = "→" if cs.get("is_anchor") else " "
            text = cs["text"]
            evidence_lines.append(f"  {marker} {text}")
            total_tokens += len(text.split())
            sentence_count += 1

        # Include full paragraph context if available
        if sel.get("paragraph_text"):
            para = sel["paragraph_text"]
            if para not in "\n".join(evidence_lines):
                evidence_lines.append(f"  [Full paragraph]: {para}")
                total_tokens += len(para.split())

    context_text = "\n".join(evidence_lines)

    return {
        "context_text": context_text,
        "sentence_count": sentence_count,
        "total_tokens": total_tokens,
        "anchor_count": len(anchors),
        "anchor_similarities": [round(a[1], 4) for a in anchors[:5]],
        "expanded_chunks": len(selected),
    }


# ---------------------------------------------------------------------------
# Phase 3: Enriched Re-synthesis via Direct LLM Call
# ---------------------------------------------------------------------------
def synthesize_with_enriched_context(
    query: str,
    route2_context: str,
    skeleton_context: str,
    response_type: str = "summary",
) -> Dict[str, Any]:
    """Call the LLM directly with merged context (Route 2 + skeleton).

    Uses the same synthesis prompt style as Route 2 to ensure fairness.
    The only difference is: skeleton sentences are appended as
    SUPPLEMENTARY EVIDENCE after the original Route 2 context.
    """
    # Merge contexts: Route 2 original + skeleton supplement
    merged_context = route2_context

    if skeleton_context.strip():
        merged_context += (
            "\n\n"
            "============================================================\n"
            "SUPPLEMENTARY SENTENCE-LEVEL EVIDENCE (high-precision retrieval)\n"
            "============================================================\n"
            "The following evidence was retrieved at sentence granularity using\n"
            "semantic search over individual sentences (not full chunks).\n"
            "Sentences marked with → are the most semantically relevant.\n"
            "Use this to find specific facts that may be buried in longer chunks above.\n"
            f"{skeleton_context}\n"
            "============================================================\n"
        )

    # Build synthesis prompt (matches Route 2's v0 style)
    if response_type == "summary":
        system_prompt = (
            "You are a precise document analysis assistant. Answer the question using ONLY "
            "the evidence provided below. Cite every factual claim with [N] markers matching "
            "the evidence block numbers. If the exact information is not present in the "
            "evidence, say so explicitly — do NOT guess or infer beyond what is stated.\n\n"
            "FORMAT:\n"
            "- Lead with a direct answer\n"
            "- Support with specific citations [N]\n"
            "- Quote exact values (numbers, dates, names) verbatim from the evidence\n"
        )
    else:
        system_prompt = (
            "You are a precise document analysis assistant. Generate a detailed report "
            "answering the question using ONLY the evidence provided below. "
            "Cite every claim with [N] markers. Refuse if information is not present.\n"
        )

    user_prompt = f"EVIDENCE:\n{merged_context}\n\nQUESTION: {query}"

    # Call Azure OpenAI
    try:
        import openai
        client = openai.AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version="2025-01-01-preview",
        )
        t0 = time.monotonic()
        response = client.chat.completions.create(
            model=SYNTHESIS_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_completion_tokens=2048,
        )
        elapsed = time.monotonic() - t0
        answer = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0
        return {
            "response": answer,
            "elapsed_ms": int(elapsed * 1000),
            "context_tokens": len(merged_context.split()),
            "total_api_tokens": tokens_used,
            "error": None,
        }
    except Exception as e:
        return {
            "response": "",
            "elapsed_ms": 0,
            "context_tokens": len(merged_context.split()),
            "total_api_tokens": 0,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Phase 4: Comparative Evaluation
# ---------------------------------------------------------------------------
def evaluate_query(
    qid: str,
    query: str,
    ground_truth: Optional[GroundTruth],
    baseline_result: Dict[str, Any],
    enriched_result: Dict[str, Any],
    skeleton_stats: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare baseline vs enriched for one query."""
    is_negative = ground_truth.is_negative if ground_truth else False
    expected = ground_truth.expected if ground_truth else ""

    baseline_metrics = calculate_accuracy_metrics(expected, baseline_result["response"], is_negative) if ground_truth else {}
    enriched_metrics = calculate_accuracy_metrics(expected, enriched_result["response"], is_negative) if ground_truth else {}

    # Delta analysis
    delta = {}
    if baseline_metrics and enriched_metrics and not is_negative:
        for key in ["containment", "f1_score", "precision", "recall"]:
            bv = baseline_metrics.get(key, 0.0)
            ev = enriched_metrics.get(key, 0.0)
            delta[key] = round(ev - bv, 4) if isinstance(bv, (int, float)) and isinstance(ev, (int, float)) else None

    # Verdict
    if is_negative:
        bp = baseline_metrics.get("negative_test_pass", False)
        ep = enriched_metrics.get("negative_test_pass", False)
        if bp == ep:
            verdict = "TIE"
        elif ep and not bp:
            verdict = "ENRICHED_WINS"
        else:
            verdict = "BASELINE_WINS"
    else:
        bf1 = baseline_metrics.get("f1_score", 0.0) or 0.0
        ef1 = enriched_metrics.get("f1_score", 0.0) or 0.0
        bc = baseline_metrics.get("containment", 0.0) or 0.0
        ec = enriched_metrics.get("containment", 0.0) or 0.0
        # Win if F1 improved OR containment improved (and neither regressed)
        if ef1 > bf1 + 0.01 or (ec > bc + 0.01 and ef1 >= bf1 - 0.01):
            verdict = "ENRICHED_WINS"
        elif bf1 > ef1 + 0.01 or (bc > ec + 0.01 and bf1 >= ef1 - 0.01):
            verdict = "BASELINE_WINS"
        else:
            verdict = "TIE"

    return {
        "qid": qid,
        "query": query,
        "is_negative": is_negative,
        "expected": expected,
        "baseline": {
            "response": baseline_result["response"][:500],
            "elapsed_ms": baseline_result["elapsed_ms"],
            "context_tokens": baseline_result.get("metadata", {}).get("context_stats", {}).get("total_context_tokens", 0),
            "chunks_used": baseline_result.get("metadata", {}).get("text_chunks_used", 0),
            "metrics": baseline_metrics,
        },
        "enriched": {
            "response": enriched_result["response"][:500],
            "elapsed_ms": enriched_result["elapsed_ms"],
            "context_tokens": enriched_result.get("context_tokens", 0),
            "metrics": enriched_metrics,
        },
        "skeleton_context": {
            "sentence_count": skeleton_stats.get("sentence_count", 0),
            "tokens_added": skeleton_stats.get("total_tokens", 0),
            "anchor_count": skeleton_stats.get("anchor_count", 0),
            "anchor_similarities": skeleton_stats.get("anchor_similarities", []),
        },
        "delta": delta,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Summary & Reporting
# ---------------------------------------------------------------------------
def print_results(results: List[Dict], skeleton: HybridSkeleton):
    """Print comparison summary."""
    print("\n" + "=" * 80)
    print("BENCHMARK: Skeleton-Enriched Context vs Route 2 Baseline")
    print("=" * 80)

    # Skeleton stats
    stats = skeleton.stats
    print(f"\n📊 Skeleton Stats:")
    print(f"   Sentences: {stats['sentences']}")
    print(f"   Paragraphs: {stats['paragraphs']}")
    print(f"   Sections: {stats['sections']}")
    print(f"   RELATED_TO edges: {stats['edges_semantic (RELATED_TO)']}")

    # Per-query results
    print(f"\n📈 Per-Query Results:")
    print(f"   {'QID':<8} {'Type':<10} {'B-F1':>6} {'E-F1':>6} {'ΔF1':>6} {'B-Cont':>7} {'E-Cont':>7} {'Verdict':<16}")
    print(f"   {'─'*8} {'─'*10} {'─'*6} {'─'*6} {'─'*6} {'─'*7} {'─'*7} {'─'*16}")

    wins = {"ENRICHED_WINS": 0, "BASELINE_WINS": 0, "TIE": 0}
    for r in results:
        qid = r["qid"]
        is_neg = r["is_negative"]
        verdict = r["verdict"]
        wins[verdict] += 1

        if is_neg:
            bp = "PASS" if r["baseline"]["metrics"].get("negative_test_pass") else "FAIL"
            ep = "PASS" if r["enriched"]["metrics"].get("negative_test_pass") else "FAIL"
            print(f"   {qid:<8} {'negative':<10} {bp:>6} {ep:>6} {'':>6} {'':>7} {'':>7} {verdict:<16}")
        else:
            bf1 = r["baseline"]["metrics"].get("f1_score", 0)
            ef1 = r["enriched"]["metrics"].get("f1_score", 0)
            df1 = r["delta"].get("f1_score", 0)
            bc = r["baseline"]["metrics"].get("containment", 0)
            ec = r["enriched"]["metrics"].get("containment", 0)
            print(f"   {qid:<8} {'positive':<10} {bf1:>6.3f} {ef1:>6.3f} {df1:>+6.3f} {bc:>7.3f} {ec:>7.3f} {verdict:<16}")

    print(f"\n🏆 Overall Verdict:")
    print(f"   Enriched wins: {wins['ENRICHED_WINS']}")
    print(f"   Baseline wins: {wins['BASELINE_WINS']}")
    print(f"   Ties:          {wins['TIE']}")

    # Aggregate metrics
    pos_results = [r for r in results if not r["is_negative"]]
    neg_results = [r for r in results if r["is_negative"]]

    if pos_results:
        avg_bf1 = sum(r["baseline"]["metrics"].get("f1_score", 0) for r in pos_results) / len(pos_results)
        avg_ef1 = sum(r["enriched"]["metrics"].get("f1_score", 0) for r in pos_results) / len(pos_results)
        avg_bc = sum(r["baseline"]["metrics"].get("containment", 0) for r in pos_results) / len(pos_results)
        avg_ec = sum(r["enriched"]["metrics"].get("containment", 0) for r in pos_results) / len(pos_results)
        avg_b_tokens = sum(r["baseline"].get("context_tokens", 0) for r in pos_results) / len(pos_results)
        avg_e_tokens = sum(r["enriched"].get("context_tokens", 0) for r in pos_results) / len(pos_results)

        print(f"\n📈 Positive Test Averages ({len(pos_results)} questions):")
        print(f"   {'Metric':<20} {'Baseline':>10} {'Enriched':>10} {'Delta':>10}")
        print(f"   {'─'*20} {'─'*10} {'─'*10} {'─'*10}")
        print(f"   {'F1 Score':<20} {avg_bf1:>10.3f} {avg_ef1:>10.3f} {avg_ef1 - avg_bf1:>+10.3f}")
        print(f"   {'Containment':<20} {avg_bc:>10.3f} {avg_ec:>10.3f} {avg_ec - avg_bc:>+10.3f}")
        print(f"   {'Context Tokens':<20} {avg_b_tokens:>10.0f} {avg_e_tokens:>10.0f} {avg_e_tokens - avg_b_tokens:>+10.0f}")

    if neg_results:
        bp_rate = sum(1 for r in neg_results if r["baseline"]["metrics"].get("negative_test_pass")) / len(neg_results)
        ep_rate = sum(1 for r in neg_results if r["enriched"]["metrics"].get("negative_test_pass")) / len(neg_results)
        print(f"\n🛡️  Negative Test Pass Rate ({len(neg_results)} questions):")
        print(f"   Baseline: {bp_rate:.0%}  |  Enriched: {ep_rate:.0%}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Benchmark: Skeleton vs Route 2")
    parser.add_argument("--url", default=DEFAULT_API_URL, help="API base URL")
    parser.add_argument("--group-id", default=_default_group_id(), help="Neo4j group ID")
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_QUESTION_BANK,
                        help="Question bank markdown file")
    parser.add_argument("--positive-prefix", default="Q-L", help="Positive question prefix")
    parser.add_argument("--negative-prefix", default="Q-N", help="Negative question prefix")
    parser.add_argument("--response-type", default="summary", help="Route 2 response type")
    parser.add_argument("--top-k", type=int, default=5, help="Skeleton anchor top-k")
    parser.add_argument("--expand-window", type=int, default=2, help="Context expansion window")
    parser.add_argument("--similarity-threshold", type=float, default=0.90, help="RELATED_TO threshold")
    parser.add_argument("--timeout", type=float, default=120.0, help="API timeout (seconds)")
    parser.add_argument("--skip-negative", action="store_true", help="Skip negative test questions")
    args = parser.parse_args()

    timestamp = _now_stamp()
    print("=" * 80)
    print("Benchmark: Skeleton-Enriched Context vs Route 2 Baseline")
    print("=" * 80)
    print(f"  API URL:      {args.url}")
    print(f"  Group ID:     {args.group_id}")
    print(f"  Question Bank: {args.question_bank}")
    print(f"  Timestamp:    {timestamp}")
    print()

    # ── Load questions and ground truth ──────────────────────────────
    print("Step 0: Loading question bank...")
    questions = read_question_bank(
        args.question_bank,
        positive_prefix=args.positive_prefix,
        negative_prefix=args.negative_prefix,
    )
    ground_truth = extract_ground_truth(args.question_bank)
    print(f"  Loaded {len(questions)} questions, {len(ground_truth)} ground truth entries")

    if args.skip_negative:
        questions = [q for q in questions if not q.qid.startswith("Q-N")]
        print(f"  Filtered to {len(questions)} positive-only questions")

    # ── Build skeleton (one-time) ────────────────────────────────────
    print("\nStep 1: Building skeleton from Neo4j...")
    chunks = extract_chunks_from_neo4j(args.group_id)

    print("\nStep 2: Building deterministic skeleton...")
    skeleton = build_skeleton(chunks)
    stats = skeleton.stats
    print(f"  Skeleton: {stats['sentences']} sentences, {stats['paragraphs']} paragraphs")

    print("\nStep 3: Embedding sentences with Voyage...")
    n_embedded = embed_sentences(skeleton)
    print(f"  Embedded {n_embedded} sentences")

    print("\nStep 4: Building sparse semantic links...")
    n_links = build_sparse_semantic_links(skeleton, similarity_threshold=args.similarity_threshold)
    print(f"  Created {n_links} RELATED_TO edges")

    # ── Run A/B comparison ───────────────────────────────────────────
    print(f"\nStep 5: Running A/B comparison ({len(questions)} questions)...")
    results = []

    for i, q in enumerate(questions):
        qid = q.qid
        query = q.query
        gt = ground_truth.get(qid)
        is_neg = gt.is_negative if gt else qid.startswith("Q-N")

        print(f"\n  [{i+1}/{len(questions)}] {qid}: {query[:60]}...")

        # ── Phase 1: Route 2 baseline ────────────────────────────────
        print(f"    Phase 1: Calling Route 2 baseline...", end=" ", flush=True)
        baseline = call_route2_baseline(
            api_url=args.url,
            group_id=args.group_id,
            query=query,
            response_type=args.response_type,
            timeout=args.timeout,
        )
        if baseline["error"]:
            print(f"ERROR: {baseline['error']}")
            continue
        print(f"{baseline['elapsed_ms']}ms")

        # For negative tests, skip skeleton enrichment (no value in adding context)
        if is_neg:
            print(f"    Negative test — using baseline response for both variants")
            enriched = {
                "response": baseline["response"],
                "elapsed_ms": baseline["elapsed_ms"],
                "context_tokens": 0,
                "error": None,
            }
            skel_stats = {"sentence_count": 0, "total_tokens": 0, "anchor_count": 0, "anchor_similarities": []}
        else:
            # ── Phase 2: Skeleton context ────────────────────────────
            print(f"    Phase 2: Getting skeleton context...", end=" ", flush=True)
            skel_stats = get_skeleton_context(
                skeleton, query,
                top_k=args.top_k,
                expand_window=args.expand_window,
            )
            print(f"{skel_stats['sentence_count']} sentences, {skel_stats['total_tokens']} tokens")

            # ── Phase 3: Enriched re-synthesis ───────────────────────
            print(f"    Phase 3: Re-synthesizing with enriched context...", end=" ", flush=True)
            route2_context = baseline.get("llm_context", "")
            if not route2_context:
                print("WARN: No llm_context from Route 2 — using response as context")
                route2_context = baseline["response"]

            enriched = synthesize_with_enriched_context(
                query=query,
                route2_context=route2_context,
                skeleton_context=skel_stats["context_text"],
                response_type=args.response_type,
            )
            if enriched["error"]:
                print(f"ERROR: {enriched['error']}")
                continue
            print(f"{enriched['elapsed_ms']}ms")

        # ── Phase 4: Evaluate ────────────────────────────────────────
        result = evaluate_query(
            qid=qid,
            query=query,
            ground_truth=gt,
            baseline_result=baseline,
            enriched_result=enriched,
            skeleton_stats=skel_stats,
        )
        results.append(result)

        # Quick verdict printout
        if is_neg:
            bp = result["baseline"]["metrics"].get("negative_test_pass", False)
            print(f"    Negative: {'PASS' if bp else 'FAIL'}")
        else:
            bf1 = result["baseline"]["metrics"].get("f1_score", 0)
            ef1 = result["enriched"]["metrics"].get("f1_score", 0)
            bc = result["baseline"]["metrics"].get("containment", 0)
            ec = result["enriched"]["metrics"].get("containment", 0)
            print(f"    Baseline: F1={bf1:.3f} Cont={bc:.3f}  |  Enriched: F1={ef1:.3f} Cont={ec:.3f}  →  {result['verdict']}")

    # ── Results ──────────────────────────────────────────────────────
    print_results(results, skeleton)

    # ── Save outputs ─────────────────────────────────────────────────
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_json = out_dir / f"skeleton_vs_route2_{timestamp}.json"
    out_data = {
        "timestamp": timestamp,
        "config": {
            "api_url": args.url,
            "group_id": args.group_id,
            "response_type": args.response_type,
            "skeleton_top_k": args.top_k,
            "expand_window": args.expand_window,
            "similarity_threshold": args.similarity_threshold,
            "synthesis_model": SYNTHESIS_MODEL,
        },
        "skeleton_stats": skeleton.stats,
        "results": results,
        "summary": {
            "total_questions": len(results),
            "enriched_wins": sum(1 for r in results if r["verdict"] == "ENRICHED_WINS"),
            "baseline_wins": sum(1 for r in results if r["verdict"] == "BASELINE_WINS"),
            "ties": sum(1 for r in results if r["verdict"] == "TIE"),
        },
    }

    with out_json.open("w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n📁 Results saved to {out_json}")
    print("=" * 80)


if __name__ == "__main__":
    main()
