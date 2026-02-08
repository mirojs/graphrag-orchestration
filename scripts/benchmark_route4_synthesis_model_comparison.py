#!/usr/bin/env python3

"""Synthesis Model Comparison Benchmark for Route 4 (DRIFT Multi-Hop).

Two-phase approach that isolates synthesis LLM performance from retrieval:

Phase 1 ("capture"):  Run each question ONCE via the API with include_context=true.
  This captures the assembled evidence (LLM context) and a baseline answer.
  Retrieval cost is paid only once per question (~30-60s for DRIFT).

Phase 2 ("replay"):  For each model in --models, call Azure OpenAI DIRECTLY with
  the captured context + the production DRIFT synthesis prompt.
  This gives pure synthesis-only latency — no retrieval overhead.

Outputs
-------
- JSON + MD in ./benchmarks/ with per-model, per-question metrics:
  - synthesis_latency_ms (pure LLM time, no retrieval)
  - retrieval_latency_ms (from Phase 1, same for all models)
  - output length (chars, words)
  - accuracy (containment, f1, negative_test_pass)

Usage
-----
  # Full 2-phase run:
  python3 scripts/benchmark_route4_synthesis_model_comparison.py \\
    --models gpt-5.1 gpt-4.1 gpt-5.1-mini gpt-4.1-mini \\
    --repeats 1

  # Re-use saved context from a previous run (skip Phase 1):
  python3 scripts/benchmark_route4_synthesis_model_comparison.py \\
    --from-context benchmarks/route4_synthesis_model_comparison_*.json \\
    --models gpt-5.1 gpt-4.1

  # Use context captured by the main Route 4 benchmark:
  python3 scripts/benchmark_route4_synthesis_model_comparison.py \\
    --from-context benchmarks/route4_drift_multi_hop_*.json \\
    --models gpt-5.1 gpt-4.1

Dependencies: azure-identity (in project venv).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Re-use helpers from the Route 4 benchmark
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_accuracy_utils import (
    GroundTruth, extract_ground_truth, calculate_accuracy_metrics,
    BankQuestion, read_question_bank,
)

# ── Constants ──

DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

DEFAULT_QUESTION_BANK = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "archive"
    / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
)


def _default_group_id() -> str:
    env = os.getenv("TEST_GROUP_ID") or os.getenv("GROUP_ID")
    if env:
        return env
    try:
        p = Path(__file__).resolve().parents[1] / "last_test_group_id.txt"
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            if s:
                return s
    except Exception:
        pass
    return "test-5pdfs-latest"


# ── Auth helpers ──

def _get_aad_token() -> Optional[str]:
    """Get Azure AD access token for API authentication.

    The Container App has Easy Auth enabled with resource_id=b68b6881-...
    We must request a token scoped to that specific app registration.
    """
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--scope", "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip() or None
    except Exception as e:
        print(f"Warning: Failed to get AAD token: {e}")
        return None


def _get_aoai_endpoint() -> str:
    """Resolve Azure OpenAI endpoint."""
    ep = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if ep:
        return ep.rstrip("/")
    try:
        result = subprocess.run(
            ["az", "cognitiveservices", "account", "list",
             "--resource-group", "rg-knowledgegraph",
             "--query", "[?kind=='OpenAI' || kind=='AIServices'].properties.endpoint | [0]",
             "-o", "tsv"],
            capture_output=True, text=True, check=True,
        )
        ep = result.stdout.strip()
        if ep:
            return ep.rstrip("/")
    except Exception:
        pass
    return "https://graphrag-cu-swedencentral.cognitiveservices.azure.com"


def _get_aoai_token() -> str:
    """Get Azure AD token scoped to Azure OpenAI (Cognitive Services)."""
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://cognitiveservices.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except Exception as e:
        raise RuntimeError(f"Failed to get Azure OpenAI token: {e}")


# ── Utility helpers ──

def _now_utc_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^a-z0-9 $%./:-]", "", t)
    return t


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _http_post_json(
    *, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_s: float,
) -> Tuple[int, Any, float, Optional[str]]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.monotonic() - t0
            try:
                return int(resp.status), json.loads(raw), elapsed, None
            except Exception:
                return int(resp.status), {"raw": raw}, elapsed, None
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        body = None
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return int(getattr(e, "code", 0) or 0), {"error": str(e), "body": body}, elapsed, str(e)
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, {"error": str(e)}, elapsed, str(e)


def _read_question_bank_route4(
    path: Path,
    *,
    positive_prefix: str = "Q-D",
    negative_prefix: str = "Q-N",
) -> List[BankQuestion]:
    return read_question_bank(path, positive_prefix=positive_prefix, negative_prefix=negative_prefix)


# ── Azure OpenAI direct call ──

def _call_aoai_direct(
    *,
    endpoint: str,
    token: str,
    deployment: str,
    prompt: str,
    api_version: str = "2024-10-21",
    temperature: float = 0.0,
    max_tokens: int = 8192,
) -> Tuple[str, int]:
    """Call Azure OpenAI chat completion directly. Returns (text, elapsed_ms)."""
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = int(round((time.monotonic() - t0) * 1000))
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
            return text.strip(), elapsed_ms
    except urllib.error.HTTPError as e:
        elapsed_ms = int(round((time.monotonic() - t0) * 1000))
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise RuntimeError(f"AOAI HTTP {e.code}: {body}") from e


# ── DRIFT synthesis prompt (production v0) ──

def _extract_sub_questions(llm_context: str) -> List[str]:
    """Extract sub-questions from enriched DRIFT context.

    The enriched context has headers like:
        ### Q1: What are the specific payment terms?
        ### Q2: Are there penalties for late payment?
    """
    matches = re.findall(r"###\s+Q\d+:\s*(.+)", llm_context)
    if matches:
        return [m.strip() for m in matches]
    # Fallback: try numbered list pattern
    matches = re.findall(r"^\s*\d+\.\s+(.+)", llm_context, re.MULTILINE)
    return [m.strip() for m in matches[:10]]  # cap at 10


def _build_drift_synthesis_prompt(
    query: str,
    context: str,
    sub_questions: Optional[List[str]] = None,
) -> str:
    """Replicate the production DRIFT synthesis prompt (v0) from synthesis.py."""
    if not sub_questions:
        sub_questions = _extract_sub_questions(context)
    if not sub_questions:
        sub_questions = [query]  # fallback: just the original query

    sub_q_list = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(sub_questions))

    return f"""You are analyzing a complex query that was decomposed into multiple sub-questions.

Original Query: {query}

Sub-questions explored:
{sub_q_list}

Evidence Context (with citation markers):
{context}

Instructions:
1. Synthesize findings from ALL sub-questions into a coherent analysis
2. Show how the answers connect to address the original query
3. EVERY factual claim must include a citation [n] to the evidence
4. Structure your response to follow the logical flow of the sub-questions
5. Include a final synthesis section that ties everything together

Format:
## Analysis

[Your comprehensive analysis addressing each sub-question]

## Key Connections

[How the findings relate to each other]

## Conclusion

[Final answer to the original query]

Your response:"""


# ── Main ──

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare synthesis LLM models on Route 4 (DRIFT) using identical retrieved context."
    )
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=_default_group_id())
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument(
        "--models",
        nargs="+",
        default=["gpt-5.1", "gpt-4.1", "gpt-5.1-mini", "gpt-4.1-mini"],
        help="List of synthesis model deployment names to compare",
    )
    ap.add_argument("--repeats", type=int, default=1, help="Repeats per model per question")
    ap.add_argument("--timeout", type=float, default=300.0, help="HTTP timeout for Phase 1 (Route 4 DRIFT is slow)")
    ap.add_argument("--max-questions", type=int, default=0, help="Limit questions (0=all)")
    ap.add_argument(
        "--questions-only",
        default="all",
        choices=["positive", "negative", "all"],
        help="Which questions to test (default: all)",
    )
    ap.add_argument(
        "--filter-qid", type=str, default=None,
        help="Run only a specific question ID (e.g. Q-D1)",
    )
    ap.add_argument(
        "--from-context",
        type=str,
        default=None,
        help="Path to a previous benchmark JSON with saved llm_context (skips Phase 1)",
    )
    ap.add_argument(
        "--response-type", type=str, default="summary",
        choices=["summary", "detailed_report"],
        help="Response type for Phase 1 capture (default: summary)",
    )
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()
    models = list(args.models)

    if not qbank.exists():
        raise FileNotFoundError(f"Question bank not found: {qbank}")

    # Load questions
    all_questions = _read_question_bank_route4(qbank, positive_prefix="Q-D", negative_prefix="Q-N")

    if args.filter_qid:
        all_questions = [q for q in all_questions if q.qid == args.filter_qid]
        if not all_questions:
            print(f"No question found with ID: {args.filter_qid}")
            return 1

    if args.questions_only == "positive":
        questions = [q for q in all_questions if q.qid.startswith("Q-D")]
    elif args.questions_only == "negative":
        questions = [q for q in all_questions if q.qid.startswith("Q-N")]
    else:
        questions = all_questions

    if args.max_questions and args.max_questions > 0:
        questions = questions[: args.max_questions]

    # Load ground truth
    ground_truth = extract_ground_truth(qbank)

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"route4_synthesis_model_comparison_{stamp}.json"
    out_md = out_dir / f"route4_synthesis_model_comparison_{stamp}.md"

    positive_count = sum(1 for q in questions if q.qid.startswith("Q-D"))
    negative_count = sum(1 for q in questions if q.qid.startswith("Q-N"))

    print("=" * 70)
    print("ROUTE 4 SYNTHESIS MODEL COMPARISON — 2-Phase")
    print("=" * 70)
    print(f"  url:        {base_url}")
    print(f"  group_id:   {group_id}")
    print(f"  models:     {models}")
    print(f"  questions:  {len(questions)} (positive={positive_count}, negative={negative_count})")
    print(f"  repeats:    {args.repeats}")
    print(f"  timeout:    {args.timeout}s (Phase 1)")
    print(f"  output:     {out_json}")
    if args.from_context:
        print(f"  from_ctx:   {args.from_context} (skipping Phase 1)")
    print("=" * 70, flush=True)

    # ──────────────────────────────────────────────────────────
    # Phase 1: Capture LLM context (one API call per question)
    # ──────────────────────────────────────────────────────────
    # Map: qid -> { query, llm_context, retrieval_ms }
    captured: Dict[str, Dict[str, Any]] = {}

    if args.from_context:
        ctx_path = Path(args.from_context)
        print(f"\nPhase 1: Loading saved context from {ctx_path}...")
        saved = json.loads(ctx_path.read_text(encoding="utf-8"))

        # Support multiple JSON formats:
        # 1. This script's format: captured_contexts with full llm_context
        # 2. This script's saved format: captured_contexts_full
        # 3. Main benchmark format: scenarios[].runs[].llm_context
        # 4. Old comparison format: results.model.qid.runs[].llm_context

        if "captured_contexts_full" in saved:
            for qid, ctx_data in saved["captured_contexts_full"].items():
                captured[qid] = ctx_data
        elif "captured_contexts" in saved:
            # Check if it has llm_context (full) or just context_chars (summary)
            sample = next(iter(saved["captured_contexts"].values()), {})
            if "llm_context" in sample:
                for qid, ctx_data in saved["captured_contexts"].items():
                    captured[qid] = ctx_data
            else:
                print("  ⚠ captured_contexts only has summaries (no llm_context). Need full context.")
        
        if not captured:
            # Try main benchmark format: scenarios[] -> runs[] -> llm_context
            for scenario in saved.get("scenarios", []):
                qid = scenario.get("qid")
                query = scenario.get("query", "")
                for run in scenario.get("runs", []):
                    if run.get("llm_context"):
                        captured[qid] = {
                            "query": query,
                            "llm_context": run["llm_context"],
                            "retrieval_ms": run.get("elapsed_ms", 0),
                        }
                        break

        if not captured:
            # Try old comparison format: results -> model -> qid -> runs[]
            for model_data in saved.get("results", {}).values():
                if isinstance(model_data, dict):
                    for qid, qdata in model_data.items():
                        if qid in captured:
                            continue
                        runs = qdata.get("runs", [])
                        for run in runs:
                            if run.get("llm_context"):
                                captured[qid] = {
                                    "query": qdata.get("query", ""),
                                    "llm_context": run["llm_context"],
                                    "retrieval_ms": run.get("elapsed_ms", 0),
                                }
                                break

        print(f"  Loaded context for {len(captured)} questions")

    else:
        # Fetch from API
        print(f"\nPhase 1: Capturing context via API ({len(questions)} questions)...")
        print("  Note: DRIFT Route 4 is slow (~30-60s per question). Be patient.")
        api_token = _get_aad_token()
        api_headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Group-ID": group_id,
        }
        if api_token:
            api_headers["Authorization"] = f"Bearer {api_token}"
            print("  ✓ Using Azure AD authentication (API)")
        else:
            print("  ⚠ No API authentication token")

        endpoint = base_url + "/hybrid/query"

        for qi, q in enumerate(questions, 1):
            payload: Dict[str, Any] = {
                "group_id": group_id,
                "query": q.query,
                "force_route": "drift_multi_hop",
                "response_type": args.response_type,
                "include_context": True,
            }
            status, resp, elapsed_s, err = _http_post_json(
                url=endpoint,
                headers=api_headers,
                payload=payload,
                timeout_s=args.timeout,
            )
            retrieval_ms = int(round(elapsed_s * 1000))
            llm_context = None
            if isinstance(resp, dict):
                meta = resp.get("metadata") or {}
                llm_context = meta.get("llm_context")

            if llm_context:
                captured[q.qid] = {
                    "query": q.query,
                    "llm_context": llm_context,
                    "retrieval_ms": retrieval_ms,
                }
                print(
                    f"  [{qi}/{len(questions)}] {q.qid}: captured {len(llm_context):,} chars ({retrieval_ms}ms)",
                    flush=True,
                )
            else:
                print(
                    f"  [{qi}/{len(questions)}] {q.qid}: ⚠ NO CONTEXT (status={status}, err={err})",
                    flush=True,
                )

    if not captured:
        print("\nERROR: No context captured. Cannot proceed to Phase 2.")
        return 1

    # ──────────────────────────────────────────────────────────
    # Phase 2: Replay context through each model (direct AOAI)
    # ──────────────────────────────────────────────────────────
    print(f"\nPhase 2: Replaying through {len(models)} models via direct Azure OpenAI...")
    aoai_endpoint = _get_aoai_endpoint()
    aoai_token = _get_aoai_token()
    print(f"  ✓ Azure OpenAI endpoint: {aoai_endpoint}")
    print(f"  ✓ Azure OpenAI token acquired")

    # Filter questions to those with captured context
    active_questions = [q for q in questions if q.qid in captured]
    total_calls = len(models) * len(active_questions) * args.repeats
    call_num = 0

    # Results: model -> qid -> metrics
    results: Dict[str, Dict[str, Any]] = {m: {} for m in models}

    for q in active_questions:
        ctx = captured[q.qid]
        gt = ground_truth.get(q.qid)
        is_negative = gt.is_negative if gt else q.qid.startswith("Q-N")

        # Build DRIFT synthesis prompt with sub-questions extracted from context
        prompt = _build_drift_synthesis_prompt(ctx["query"], ctx["llm_context"])

        for model in models:
            runs = []
            for ri in range(args.repeats):
                call_num += 1
                try:
                    text, synth_ms = _call_aoai_direct(
                        endpoint=aoai_endpoint,
                        token=aoai_token,
                        deployment=model,
                        prompt=prompt,
                    )
                    runs.append({
                        "run": ri,
                        "status": 200,
                        "synthesis_ms": synth_ms,
                        "text": text,
                        "text_length_chars": len(text),
                        "text_length_words": _word_count(text),
                        "error": None,
                    })
                except Exception as e:
                    runs.append({
                        "run": ri,
                        "status": 0,
                        "synthesis_ms": 0,
                        "text": "",
                        "text_length_chars": 0,
                        "text_length_words": 0,
                        "error": str(e),
                    })

            first_text = runs[0]["text"] if runs else ""

            # Accuracy
            accuracy: Dict[str, Any] = {}
            if q.qid in ground_truth and runs:
                accuracy = calculate_accuracy_metrics(
                    expected=ground_truth[q.qid].expected,
                    actual=first_text,
                    is_negative=ground_truth[q.qid].is_negative,
                )

            synth_times = [r["synthesis_ms"] for r in runs if r["status"] == 200]
            avg_synth = int(sum(synth_times) / len(synth_times)) if synth_times else 0
            char_lengths = [r["text_length_chars"] for r in runs]
            word_lengths = [r["text_length_words"] for r in runs]

            summary = {
                "qid": q.qid,
                "query": q.query,
                "model": model,
                "is_negative": is_negative,
                "retrieval_ms": ctx["retrieval_ms"],
                "avg_synthesis_ms": avg_synth,
                "min_synthesis_ms": min(synth_times) if synth_times else 0,
                "max_synthesis_ms": max(synth_times) if synth_times else 0,
                "avg_chars": int(sum(char_lengths) / len(char_lengths)) if char_lengths else 0,
                "avg_words": int(sum(word_lengths) / len(word_lengths)) if word_lengths else 0,
                "accuracy": accuracy,
                "runs": runs,
            }
            results[model][q.qid] = summary

            # Print progress
            cont = accuracy.get("containment", -1)
            cont_str = f"contain={cont:.2f}" if cont >= 0 else ""
            f1 = accuracy.get("f1_score", -1)
            f1_str = f"f1={f1:.2f}" if f1 >= 0 else ""
            neg_pass = accuracy.get("negative_test_pass", None)
            neg_str = "NEG_PASS" if neg_pass is True else ("NEG_FAIL" if neg_pass is False else "")
            metrics_parts = [s for s in [cont_str, f1_str, neg_str] if s]
            metrics_str = " | ".join(metrics_parts) if metrics_parts else ""

            print(
                f"  [{call_num}/{total_calls}] {q.qid} | {model:15s} | "
                f"synth={avg_synth:5d}ms | {summary['avg_words']:5d}w | {metrics_str}",
                flush=True,
            )

    # ── Build comparison summary ──
    comparison: Dict[str, Dict[str, Any]] = {}
    for model in models:
        model_data = results[model]
        synth_latencies = [v["avg_synthesis_ms"] for v in model_data.values() if v["avg_synthesis_ms"] > 0]
        all_words = [v["avg_words"] for v in model_data.values()]
        all_chars = [v["avg_chars"] for v in model_data.values()]
        containments = [
            v["accuracy"]["containment"]
            for v in model_data.values()
            if "containment" in v.get("accuracy", {})
        ]
        f1_scores = [
            v["accuracy"]["f1_score"]
            for v in model_data.values()
            if "f1_score" in v.get("accuracy", {})
        ]
        neg_results = [
            v["accuracy"].get("negative_test_pass", False)
            for v in model_data.values()
            if v.get("is_negative")
        ]
        pos_passes = [
            1 for v in model_data.values()
            if not v.get("is_negative") and v.get("accuracy", {}).get("containment", 0) >= 0.5
        ]
        pos_total = sum(
            1 for v in model_data.values()
            if not v.get("is_negative") and "containment" in v.get("accuracy", {})
        )

        comparison[model] = {
            "avg_synthesis_ms": int(sum(synth_latencies) / len(synth_latencies)) if synth_latencies else 0,
            "p50_synthesis_ms": sorted(synth_latencies)[len(synth_latencies) // 2] if synth_latencies else 0,
            "avg_words": int(sum(all_words) / len(all_words)) if all_words else 0,
            "avg_chars": int(sum(all_chars) / len(all_chars)) if all_chars else 0,
            "avg_containment": round(sum(containments) / len(containments), 3) if containments else 0,
            "avg_f1": round(sum(f1_scores) / len(f1_scores), 3) if f1_scores else 0,
            "positive_pass_rate": f"{sum(pos_passes)}/{pos_total}" if pos_total else "N/A",
            "negative_pass_rate": f"{sum(neg_results)}/{len(neg_results)}" if neg_results else "N/A",
            "negative_pass_pct": round(sum(neg_results) / len(neg_results), 3) if neg_results else None,
            "questions_tested": len(model_data),
        }

    # ── Save JSON (with full context for replay) ──
    output = {
        "meta": {
            "created_utc": stamp,
            "method": "2-phase: capture DRIFT context once, replay through each model directly via Azure OpenAI",
            "route": "drift_multi_hop",
            "aoai_endpoint": aoai_endpoint,
            "models": models,
            "questions": len(active_questions),
            "repeats": args.repeats,
            "api_url": base_url,
            "group_id": group_id,
        },
        "captured_contexts": {
            qid: {
                "query": ctx["query"],
                "retrieval_ms": ctx["retrieval_ms"],
                "context_chars": len(ctx["llm_context"]),
            }
            for qid, ctx in captured.items()
        },
        # Save full context for future replay (--from-context)
        "captured_contexts_full": {
            qid: ctx
            for qid, ctx in captured.items()
        },
        "comparison_summary": comparison,
        "results": results,
    }
    out_json.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Save Markdown ──
    lines: List[str] = []
    lines.append(f"# Route 4 Synthesis Model Comparison — 2-Phase ({stamp})\n\n")
    lines.append(f"- **Method:** Capture DRIFT context once via API, replay through each model directly via Azure OpenAI\n")
    lines.append(f"- **Route:** drift_multi_hop (Route 4)\n")
    lines.append(f"- **Models tested:** {', '.join(models)}\n")
    lines.append(f"- **Questions:** {len(active_questions)} (positive={positive_count}, negative={negative_count})\n")
    lines.append(f"- **Repeats:** {args.repeats}\n")
    lines.append(f"- **Group ID:** {group_id}\n\n")

    # Summary table
    lines.append("## Summary\n\n")
    lines.append("| Model | Avg Synthesis | P50 Synthesis | Avg Words | Avg Containment | Avg F1 | Pos Pass | Neg Pass |\n")
    lines.append("|-------|--------------|--------------|-----------|----------------|--------|----------|----------|\n")
    for model in models:
        c = comparison[model]
        lines.append(
            f"| {model} | {c['avg_synthesis_ms']}ms | {c['p50_synthesis_ms']}ms | "
            f"{c['avg_words']} | "
            f"{c['avg_containment']:.3f} | {c['avg_f1']:.3f} | "
            f"{c['positive_pass_rate']} | {c['negative_pass_rate']} |\n"
        )

    # Per-question comparison table
    lines.append("\n## Per-Question Comparison\n\n")
    lines.append("| QID | Retrieval | " + " | ".join(f"{m} (synth ms / words / score)" for m in models) + " |\n")
    lines.append("|-----|-----------|" + "|".join(["---" for _ in models]) + "|\n")
    for q in active_questions:
        ret_ms = captured.get(q.qid, {}).get("retrieval_ms", 0)
        cells = []
        for model in models:
            d = results[model].get(q.qid, {})
            s_ms = d.get("avg_synthesis_ms", 0)
            words = d.get("avg_words", 0)
            acc = d.get("accuracy", {})
            cont = acc.get("containment", -1)
            neg_pass = acc.get("negative_test_pass", None)
            if neg_pass is not None:
                score_str = "NEG_PASS" if neg_pass else "NEG_FAIL"
            elif cont >= 0:
                score_str = f"{cont:.2f}"
            else:
                score_str = "—"
            cells.append(f"{s_ms}ms / {words}w / {score_str}")
        lines.append(f"| {q.qid} | {ret_ms}ms | " + " | ".join(cells) + " |\n")

    # Accuracy details per question
    lines.append("\n## Accuracy Details\n\n")
    for q in active_questions:
        lines.append(f"### {q.qid}\n\n")
        lines.append(f"**Query:** {q.query}\n\n")
        lines.append("| Model | Synthesis ms | Chars | Words | Containment | F1 | Neg Pass |\n")
        lines.append("|-------|-------------|-------|-------|-------------|-----|----------|\n")
        for model in models:
            d = results[model].get(q.qid, {})
            acc = d.get("accuracy", {})
            s_ms = d.get("avg_synthesis_ms", 0)
            chars = d.get("avg_chars", 0)
            words = d.get("avg_words", 0)
            cont = acc.get("containment", "—")
            f1 = acc.get("f1_score", "—")
            neg = acc.get("negative_test_pass", "—")
            if isinstance(cont, float):
                cont = f"{cont:.3f}"
            if isinstance(f1, float):
                f1 = f"{f1:.3f}"
            lines.append(f"| {model} | {s_ms}ms | {chars} | {words} | {cont} | {f1} | {neg} |\n")
        lines.append("\n")

    out_md.write_text("".join(lines), encoding="utf-8")

    # ── Print console summary ──
    print(f"\n{'=' * 70}")
    print("COMPARISON SUMMARY (synthesis-only latency)")
    print("=" * 70)
    print(
        f"{'Model':20s} {'Synth ms':>10s} {'Words':>8s} {'Contain':>10s} "
        f"{'F1':>8s} {'Pos':>8s} {'Neg':>10s}"
    )
    print("-" * 80)
    for model in models:
        c = comparison[model]
        print(
            f"{model:20s} {c['avg_synthesis_ms']:>8d}ms {c['avg_words']:>7d} "
            f"{c['avg_containment']:>9.3f} {c['avg_f1']:>7.3f} "
            f"{c['positive_pass_rate']:>8s} {c['negative_pass_rate']:>10s}"
        )
    print("=" * 70)
    print(f"\n✅ Results saved:")
    print(f"   JSON: {out_json}")
    print(f"   MD:   {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
