#!/usr/bin/env python3

"""Synthesis Model Comparison Benchmark for Route 3 (Global Search).

Two-phase approach that isolates synthesis LLM performance from retrieval:

Phase 1 ("capture"):  Run each question ONCE via the API with include_context=true.
  This captures the assembled evidence (LLM context) and a baseline answer.
  Retrieval cost is paid only once per question.

Phase 2 ("replay"):  For each model in --models, call Azure OpenAI DIRECTLY with
  the captured context + the same prompt template used in production.
  This gives pure synthesis-only latency — no retrieval overhead.

Outputs
-------
- JSON + MD in ./benchmarks/ with per-model, per-question metrics:
  - synthesis_latency_ms (pure LLM time, no retrieval)
  - retrieval_latency_ms (from Phase 1, same for all models)
  - output length (chars, words)
  - theme coverage (matched expected terms)
  - accuracy (containment, f1)

Usage
-----
  python3 scripts/benchmark_synthesis_model_comparison.py \\
    --models gpt-5.1 gpt-4.1 gpt-4o-mini \\
    --repeats 1 \\
    --max-questions 10

  # Re-use saved context from a previous run:
  python3 scripts/benchmark_synthesis_model_comparison.py \\
    --from-context benchmarks/synthesis_model_comparison_20260208T*.json \\
    --models gpt-5.1 gpt-4.1

Dependencies: openai, azure-identity (both in project venv).
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

# Re-use helpers from the main benchmark
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_accuracy_utils import GroundTruth, extract_ground_truth, calculate_accuracy_metrics
from benchmark_route3_global_search import (
    EXPECTED_TERMS,
    NEGATIVE_QUERY_SUFFIX,
    calculate_theme_coverage,
    _get_aad_token,
    _http_post_json,
    _read_question_bank,
    _normalize_text,
    _now_utc_stamp,
    _default_group_id,
    DEFAULT_URL,
    DEFAULT_QUESTION_BANK,
    BankQuestion,
)


# ── Azure OpenAI direct call ──

def _get_aoai_endpoint() -> str:
    """Resolve Azure OpenAI endpoint from env or deploy config."""
    ep = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if ep:
        return ep.rstrip("/")
    # Fallback: query Azure CLI
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
    # Last resort: hardcoded from deploy script
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


def _build_summary_prompt(query: str, context: str) -> str:
    """Replicate the production summary prompt from synthesis.py."""
    q_lower = query.lower()
    simple_patterns = [
        "each document", "every document", "all documents",
        "different documents", "how many documents", "most documents",
    ]
    regex_patterns = [
        r"summarize.*document", r"list.*document",
        r"appears?\s+in.*documents",
        r"which.*documents?",
    ]
    is_per_document_query = (
        any(pattern in q_lower for pattern in simple_patterns) or
        any(re.search(pattern, q_lower) for pattern in regex_patterns)
    )
    document_guidance = ""
    if is_per_document_query:
        document_guidance = """
IMPORTANT for Per-Document Queries:
- The Evidence Context contains chunks grouped by "=== DOCUMENT: <title> ===" headers.
- Count UNIQUE top-level documents only - do NOT create separate summaries for:
  * Document sections (e.g., "Section 2: Arbitration" belongs to parent document)
  * Exhibits, Appendices, Schedules (e.g., "Exhibit A" belongs to parent contract)
  * Repeated excerpts from the same document
- If you see "Builder's Warranty" and "Builder's Warranty - Section 3", combine into ONE summary.
- If you see "Purchase Contract" and "Exhibit A - Scope of Work", combine into ONE summary.
"""
    return f"""You are an expert analyst generating a concise summary.

Question: {query}

Evidence Context:
{context}

Instructions:
1. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence:
    - Question asks for "bank routing number" but evidence only has payment portal URL → Output: "The requested information was not found in the available documents."
    - Question asks for "SWIFT code" but evidence has no SWIFT/IBAN → Output: "The requested information was not found in the available documents."
    - Question asks for "California law" but evidence shows Texas law → Output: "The requested information was not found in the available documents."
   - Do NOT say "The invoice does not provide X, but here is Y" — Just refuse entirely.
2. ONLY if the EXACT requested information IS present: provide a brief summary (2-3 paragraphs).
3. **RESPECT ALL QUALIFIERS** in the question. If the question asks for a specific type, category, or unit:
   - Include ONLY items matching that qualifier
   - EXCLUDE items that don't match, even if they seem related
4. Include citations [N] for factual claims (aim for every sentence that states a fact).
5. If the evidence contains explicit numeric values (e.g., dollar amounts, time periods/deadlines, percentages, counts), include them verbatim.
6. Prefer concrete obligations/thresholds over general paraphrases.
7. If the question is asking for obligations, reporting/record-keeping, remedies, default/breach, or dispute-resolution: enumerate each distinct obligation/mechanism that is explicitly present in the Evidence Context; do not omit items just because another item is more prominent.
{document_guidance}

Respond using this format:

## Summary

[Summary with citations [N] for every factual claim. Include explicit numeric values verbatim. Cover provisions from ALL source documents, not just the most prominent one.]

## Key Points

- [Distinct item/obligation 1 with citation [N]]
- [Distinct item/obligation 2 with citation [N]]
- [Additional items from each source document as needed]

Response:"""


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare synthesis LLM models on Route 3 using identical retrieved context."
    )
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=_default_group_id())
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument(
        "--models",
        nargs="+",
        default=["gpt-5.1", "gpt-4.1", "gpt-4o-mini"],
        help="List of synthesis model deployment names to compare",
    )
    ap.add_argument("--repeats", type=int, default=1, help="Repeats per model per question")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--max-questions", type=int, default=0, help="Limit questions (0=all)")
    ap.add_argument(
        "--questions-only",
        default="positive",
        choices=["positive", "negative", "all"],
        help="Which questions to test",
    )
    ap.add_argument(
        "--from-context",
        type=str,
        default=None,
        help="Path to a previous benchmark JSON with saved llm_context (skips Phase 1)",
    )
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()
    models = list(args.models)

    # Load questions
    positive_questions = _read_question_bank(qbank, prefix="Q-G")
    negative_questions = []
    try:
        negative_questions = _read_question_bank(qbank, prefix="Q-N")
    except RuntimeError:
        pass

    if args.questions_only == "positive":
        questions = positive_questions
    elif args.questions_only == "negative":
        questions = negative_questions
    else:
        questions = positive_questions + negative_questions

    if args.max_questions and args.max_questions > 0:
        questions = questions[: args.max_questions]

    # Load ground truth
    ground_truth = extract_ground_truth(qbank)

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"synthesis_model_comparison_{stamp}.json"
    out_md = out_dir / f"synthesis_model_comparison_{stamp}.md"

    print("=" * 60)
    print("SYNTHESIS MODEL COMPARISON (2-Phase)")
    print("=" * 60)
    print(f"  models:     {models}")
    print(f"  questions:  {len(questions)} ({args.questions_only})")
    print(f"  repeats:    {args.repeats}")
    print(f"  output:     {out_json}")
    if args.from_context:
        print(f"  from_ctx:   {args.from_context} (skipping Phase 1)")
    print("=" * 60, flush=True)

    # ──────────────────────────────────────────────────────────
    # Phase 1: Capture LLM context (one API call per question)
    # ──────────────────────────────────────────────────────────
    # Map: qid -> { query, llm_context, retrieval_ms }
    captured: Dict[str, Dict[str, Any]] = {}

    if args.from_context:
        # Load from saved file
        ctx_path = Path(args.from_context)
        print(f"\nPhase 1: Loading saved context from {ctx_path}...")
        saved = json.loads(ctx_path.read_text(encoding="utf-8"))
        # Try new format first (captured_contexts), then old format (results)
        if "captured_contexts" in saved:
            for qid, ctx_data in saved["captured_contexts"].items():
                captured[qid] = ctx_data
        else:
            # Old format: extract from results
            for scenario_data in saved.get("results", {}).values():
                for qid, qdata in scenario_data.items():
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
        print(f"\nPhase 1: Capturing context ({len(questions)} questions)...")
        api_token = _get_aad_token()
        api_headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Group-ID": group_id,
        }
        if api_token:
            api_headers["Authorization"] = f"Bearer {api_token}"
            print("  ✓ Using Azure AD authentication (API)")

        endpoint = base_url + "/hybrid/query"

        for qi, q in enumerate(questions, 1):
            gt = ground_truth.get(q.qid)
            effective_query = (
                (q.query + NEGATIVE_QUERY_SUFFIX) if (gt and gt.is_negative) else q.query
            )
            payload = {
                "query": effective_query,
                "force_route": "global_search",
                "response_type": "summary",
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
                    "query": effective_query,
                    "llm_context": llm_context,
                    "retrieval_ms": retrieval_ms,
                }
                print(f"  [{qi}/{len(questions)}] {q.qid}: captured {len(llm_context):,} chars ({retrieval_ms}ms)", flush=True)
            else:
                print(f"  [{qi}/{len(questions)}] {q.qid}: ⚠ NO CONTEXT (status={status}, err={err})", flush=True)

    if not captured:
        print("\nERROR: No context captured. Cannot proceed to Phase 2.")
        return 1

    # ──────────────────────────────────────────────────────────
    # Phase 2: Replay context through each model (direct AOAI)
    # ──────────────────────────────────────────────────────────
    print(f"\nPhase 2: Replaying through {len(models)} models...")
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
        prompt = _build_summary_prompt(ctx["query"], ctx["llm_context"])

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

            # Theme coverage
            theme = {}
            if q.qid.startswith("Q-G") and q.qid in EXPECTED_TERMS:
                theme = calculate_theme_coverage(first_text, EXPECTED_TERMS[q.qid])

            # Accuracy
            accuracy = {}
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
                "retrieval_ms": ctx["retrieval_ms"],
                "avg_synthesis_ms": avg_synth,
                "min_synthesis_ms": min(synth_times) if synth_times else 0,
                "max_synthesis_ms": max(synth_times) if synth_times else 0,
                "avg_chars": int(sum(char_lengths) / len(char_lengths)) if char_lengths else 0,
                "avg_words": int(sum(word_lengths) / len(word_lengths)) if word_lengths else 0,
                "theme_coverage": theme,
                "accuracy": accuracy,
                "runs": runs,
            }
            results[model][q.qid] = summary

            # Print progress
            tc = theme.get("coverage", -1)
            tc_str = f"theme={tc:.0%}" if tc >= 0 else ""
            cont = accuracy.get("containment", -1)
            cont_str = f"contain={cont:.2f}" if cont >= 0 else ""
            neg_pass = accuracy.get("negative_test_pass", None)
            neg_str = "NEG_PASS" if neg_pass else ""
            metrics_parts = [s for s in [tc_str, cont_str, neg_str] if s]
            metrics_str = " | ".join(metrics_parts)

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
        theme_coverages = [
            v["theme_coverage"]["coverage"]
            for v in model_data.values()
            if v["theme_coverage"].get("coverage") is not None
        ]
        containments = [
            v["accuracy"]["containment"]
            for v in model_data.values()
            if "containment" in v.get("accuracy", {})
        ]
        neg_passes = [
            v["accuracy"].get("negative_test_pass", False)
            for v in model_data.values()
            if v["accuracy"].get("is_negative")
        ]

        comparison[model] = {
            "avg_synthesis_ms": int(sum(synth_latencies) / len(synth_latencies)) if synth_latencies else 0,
            "p50_synthesis_ms": sorted(synth_latencies)[len(synth_latencies) // 2] if synth_latencies else 0,
            "avg_words": int(sum(all_words) / len(all_words)) if all_words else 0,
            "avg_chars": int(sum(all_chars) / len(all_chars)) if all_chars else 0,
            "avg_theme_coverage": round(sum(theme_coverages) / len(theme_coverages), 3) if theme_coverages else 0,
            "avg_containment": round(sum(containments) / len(containments), 3) if containments else 0,
            "negative_pass_rate": round(sum(neg_passes) / len(neg_passes), 3) if neg_passes else None,
            "questions_tested": len(model_data),
        }

    # ── Save JSON ──
    output = {
        "meta": {
            "created_utc": stamp,
            "method": "2-phase: capture context once, replay through each model directly via Azure OpenAI",
            "aoai_endpoint": aoai_endpoint,
            "models": models,
            "questions": len(active_questions),
            "repeats": args.repeats,
            "api_url": base_url,
            "group_id": group_id,
        },
        "captured_contexts": {
            qid: {"query": ctx["query"], "retrieval_ms": ctx["retrieval_ms"], "context_chars": len(ctx["llm_context"])}
            for qid, ctx in captured.items()
        },
        "comparison_summary": comparison,
        "results": results,
    }
    out_json.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{out_json}")

    # ── Save Markdown ──
    lines: List[str] = []
    lines.append(f"# Synthesis Model Comparison — 2-Phase ({stamp})\n\n")
    lines.append(f"- **Method:** Capture context once via API, replay through each model directly via Azure OpenAI\n")
    lines.append(f"- **Models tested:** {', '.join(models)}\n")
    lines.append(f"- **Questions:** {len(active_questions)} ({args.questions_only})\n")
    lines.append(f"- **Repeats:** {args.repeats}\n")
    lines.append(f"- **Group ID:** {group_id}\n\n")

    # Summary table
    lines.append("## Summary\n\n")
    lines.append("| Model | Avg Synthesis | P50 Synthesis | Avg Words | Theme Coverage | Containment |\n")
    lines.append("|-------|--------------|--------------|-----------|---------------|-------------|\n")
    for model in models:
        c = comparison[model]
        lines.append(
            f"| {model} | {c['avg_synthesis_ms']}ms | {c['p50_synthesis_ms']}ms | "
            f"{c['avg_words']} | "
            f"{c['avg_theme_coverage']:.1%} | {c['avg_containment']:.2f} |\n"
        )

    # Per-question comparison
    lines.append("\n## Per-Question Comparison\n\n")
    lines.append("| QID | Retrieval | " + " | ".join(f"{m} (synth ms / words / theme)" for m in models) + " |\n")
    lines.append("|-----|-----------|" + "|".join(["---" for _ in models]) + "|\n")
    for q in active_questions:
        ret_ms = captured.get(q.qid, {}).get("retrieval_ms", 0)
        cells = []
        for model in models:
            d = results[model].get(q.qid, {})
            s_ms = d.get("avg_synthesis_ms", 0)
            words = d.get("avg_words", 0)
            tc = d.get("theme_coverage", {}).get("coverage", -1)
            tc_str = f"{tc:.0%}" if tc >= 0 else "—"
            cells.append(f"{s_ms}ms / {words}w / {tc_str}")
        lines.append(f"| {q.qid} | {ret_ms}ms | " + " | ".join(cells) + " |\n")

    # Missing terms detail
    lines.append("\n## Theme Coverage Details (Missing Terms)\n\n")
    for model in models:
        lines.append(f"### {model}\n\n")
        any_missing = False
        for q in active_questions:
            d = results[model].get(q.qid, {})
            missing = d.get("theme_coverage", {}).get("missing", [])
            if missing:
                any_missing = True
                lines.append(f"- **{q.qid}**: missing {missing}\n")
        if not any_missing:
            lines.append("- All terms matched ✓\n")
        lines.append("\n")

    out_md.write_text("".join(lines), encoding="utf-8")
    print(out_md)

    # ── Console summary ──
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY (synthesis-only latency)")
    print("=" * 70)
    print(f"{'Model':20s} {'Synth ms':>10s} {'Words':>8s} {'Theme':>8s} {'Contain':>10s}")
    print("-" * 70)
    for model in models:
        c = comparison[model]
        print(
            f"{model:20s} {c['avg_synthesis_ms']:>8d}ms {c['avg_words']:>7d} "
            f"{c['avg_theme_coverage']:>7.1%} {c['avg_containment']:>9.2f}"
        )
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
