#!/usr/bin/env python3

"""Route 2 Prompt + Model Comparison (2-Phase Local Replay).

Two-phase approach isolating synthesis LLM from retrieval:

Phase 1 ("capture"):  Call the deployed API ONCE per question with
  include_context=true and force_route=local_search.  Captures the
  assembled evidence (llm_context) so retrieval cost is paid once.

Phase 2 ("replay"):  For each (prompt_variant, model) combo, call
  Azure OpenAI DIRECTLY with the captured context.  Pure synthesis
  latency — no retrieval overhead.

Test matrix (default):
  Prompts: v0 (production verbose), v1_concise (precision-optimised)
  Models:  gpt-5.1 (current default), gpt-4.1 (less verbose in Route 4 tests)

Usage
-----
  # Full 2-phase run:
  python3 scripts/benchmark_route2_prompt_model_comparison.py

  # Re-use saved context (skip Phase 1):
  python3 scripts/benchmark_route2_prompt_model_comparison.py \\
    --from-context benchmarks/route2_prompt_model_*.json

  # Custom combos:
  python3 scripts/benchmark_route2_prompt_model_comparison.py \\
    --models gpt-5.1 gpt-4.1 gpt-4o-mini \\
    --prompts v0 v1_concise
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Shared types ──

@dataclass
class GroundTruth:
    qid: str
    question: str
    expected: str
    is_negative: bool

@dataclass(frozen=True)
class BankQuestion:
    qid: str
    query: str


DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)

DEFAULT_QUESTION_BANK = (
    Path(__file__).resolve().parents[1]
    / "docs" / "archive" / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
)


def _default_group_id() -> str:
    env = os.getenv("TEST_GROUP_ID") or os.getenv("GROUP_ID")
    if env:
        return env
    p = Path(__file__).resolve().parents[1] / "last_test_group_id.txt"
    try:
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            if s:
                return s
    except Exception:
        pass
    return "test-5pdfs-v2-fix2"


def _now_utc_stamp() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^a-z0-9 $%]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ── Question bank parsing ──

def _read_question_bank(path: Path) -> List[BankQuestion]:
    content = path.read_text(encoding="utf-8")
    questions = []
    for m in re.finditer(r'^\d*\.?\s*\*\*(Q-[A-Z]\d+):\*\*\s+(.+)', content, re.MULTILINE):
        qid = m.group(1).strip()
        raw_q = m.group(2).strip()
        # Trim metadata from question text
        q = re.split(r'\s+-\s+\*\*Expected\s+Route:\*\*', raw_q)[0].strip()
        if qid.startswith("Q-L") or qid.startswith("Q-N"):
            questions.append(BankQuestion(qid=qid, query=q))
    return questions


def _extract_ground_truth(path: Path) -> Dict[str, GroundTruth]:
    content = path.read_text(encoding="utf-8")
    ground_truth: Dict[str, GroundTruth] = {}
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r'^\d*\.?\s*\*\*(Q-[A-Z]\d+):\*\*\s+(.+)', lines[i])
        if m:
            qid = m.group(1).strip()
            question = m.group(2).strip()
            is_negative = qid.startswith("Q-N")
            expected = "not specified" if is_negative else ""
            if not is_negative:
                # Look for Expected field
                j = i + 1
                while j < len(lines) and not re.match(r'^\d*\.?\s*\*\*Q-', lines[j]):
                    exp_m = re.match(r'-\s+\*\*Expected:\*\*\s*(.*)$', lines[j].strip())
                    if exp_m:
                        expected = exp_m.group(1).strip()
                        # Multi-line
                        k = j + 1
                        while k < len(lines):
                            nl = lines[k].strip()
                            if re.match(r'-\s+\*\*(?:Source|Expected):', nl):
                                break
                            if re.match(r'^\d*\.?\s*\*\*Q-', nl) or nl.startswith("##"):
                                break
                            if not nl:
                                break
                            if nl.startswith("-"):
                                expected += " " + nl[1:].strip()
                            else:
                                expected += " " + nl
                            k += 1
                        break
                    j += 1
            expected = re.sub(r'[`*]', '', expected)
            expected = re.sub(r'\s+', ' ', expected).strip()
            if expected or is_negative:
                ground_truth[qid] = GroundTruth(qid=qid, question=question,
                                                 expected=expected, is_negative=is_negative)
        i += 1
    return ground_truth


# ── Accuracy metrics ──

def _calculate_accuracy(expected: str, actual: str, is_negative: bool) -> Dict[str, Any]:
    if is_negative:
        actual_lower = actual.lower()
        not_found = [
            'not specified', 'not found', 'not mentioned', 'not provided',
            'no information', 'not available', 'not included', 'not stated',
            'does not contain', 'not referenced', 'not present',
        ]
        passes = any(p in actual_lower for p in not_found)
        return {
            "is_negative": True, "negative_pass": passes,
            "containment": None, "precision": None, "recall": None, "f1": None,
        }
    expected_norm = _normalize_text(expected)
    actual_norm = _normalize_text(actual)
    exp_tok = set(expected_norm.split())
    act_tok = set(actual_norm.split())
    if not exp_tok or not act_tok:
        return {"is_negative": False, "negative_pass": None,
                "containment": False, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    overlap = exp_tok & act_tok
    prec = len(overlap) / len(act_tok)
    rec = len(overlap) / len(exp_tok)
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    contained = (expected_norm in actual_norm) or (rec >= 0.8)
    return {
        "is_negative": False, "negative_pass": None,
        "containment": contained,
        "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
    }


# ── Azure auth ──

def _get_aad_token() -> Optional[str]:
    """Get AAD bearer token for the Container App."""
    try:
        r = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://management.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()
    except Exception:
        return None


def _get_aoai_endpoint() -> str:
    ep = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if ep:
        return ep.rstrip("/")
    for rg in ("rg-graphrag-feature", "rg-knowledgegraph"):
        try:
            r = subprocess.run(
                ["az", "cognitiveservices", "account", "list",
                 "--resource-group", rg,
                 "--query", "[?kind=='OpenAI' || kind=='AIServices'].properties.endpoint | [0]",
                 "-o", "tsv"],
                capture_output=True, text=True, check=True,
            )
            ep = r.stdout.strip()
            if ep:
                return ep.rstrip("/")
        except Exception:
            continue
    return "https://graphrag-openai-8476.openai.azure.com"


def _get_aoai_token() -> str:
    r = subprocess.run(
        ["az", "account", "get-access-token",
         "--resource", "https://cognitiveservices.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


# ── Azure OpenAI direct call ──

def _call_aoai(*, endpoint: str, token: str, deployment: str, prompt: str,
               api_version: str = "2024-10-21", temperature: float = 0.0,
               max_tokens: int = 8192) -> Tuple[str, int]:
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    use_new = any(deployment.startswith(p) for p in ("gpt-5", "o3", "o4"))
    tok_key = "max_completion_tokens" if use_new else "max_tokens"
    no_temp = any(deployment.startswith(p) for p in ("gpt-5-mini", "gpt-5-nano", "o1", "o3", "o4"))
    payload: Dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        tok_key: max_tokens,
    }
    if not no_temp:
        payload["temperature"] = temperature
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    for attempt in range(6):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                ms = int(round((time.monotonic() - t0) * 1000))
                return json.loads(raw)["choices"][0]["message"]["content"].strip(), ms
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if e.code == 429 and attempt < 5:
                ra = e.headers.get("Retry-After")
                wait = int(ra) if ra and ra.isdigit() else min(30, 5 * (2 ** attempt))
                print(f"    ⏳ 429, wait {wait}s (attempt {attempt+1}/5)...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"AOAI HTTP {e.code}: {body}") from e
    raise RuntimeError("Exhausted retries")


# ── HTTP helper for Phase 1 ──

def _http_post(url: str, headers: Dict, payload: Dict, timeout: float = 180) -> Tuple[int, Any, float]:
    """POST JSON, return (status, parsed_body, elapsed_seconds)."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=int(timeout)) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return resp.status, body, time.monotonic() - t0
    except urllib.error.HTTPError as e:
        body = None
        try:
            body = json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            pass
        return e.code, body, time.monotonic() - t0
    except Exception:
        return 0, None, time.monotonic() - t0


# ── Prompt builders ──

NEGATIVE_SUFFIX = "\n\nIf the requested information is not found in the uploaded documents, respond ONLY with: \"The requested information was not found in the available documents.\""


def _build_prompt_v0(query: str, context: str) -> str:
    """Production verbose prompt (v0) — mirrors _get_summary_prompt."""
    q_lower = query.lower()
    simple_patterns = [
        "each document", "every document", "all documents",
        "different documents", "how many documents", "most documents",
    ]
    regex_patterns = [
        r"summarize.*document", r"list.*document",
        r"appears?\s+in.*documents", r"which.*documents?",
    ]
    is_per_doc = (
        any(p in q_lower for p in simple_patterns) or
        any(re.search(p, q_lower) for p in regex_patterns)
    )
    doc_guidance = ""
    if is_per_doc:
        doc_guidance = """
IMPORTANT for Per-Document Queries:
- The Evidence Context contains chunks grouped by "=== DOCUMENT: <title> ===" headers.
- Count UNIQUE top-level documents only.
- Combine sections/exhibits into their parent document.
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
{doc_guidance}

Respond using this format:

## Summary

[Summary with citations [N] for every factual claim. Include explicit numeric values verbatim. Cover provisions from ALL source documents, not just the most prominent one.]

## Key Points

- [Distinct item/obligation 1 with citation [N]]
- [Distinct item/obligation 2 with citation [N]]
- [Additional items from each source document as needed]

Response:"""


def _build_prompt_v1_concise(query: str, context: str) -> str:
    """Precision-optimised concise prompt (v1)."""
    q_lower = query.lower()
    simple_patterns = [
        "each document", "every document", "all documents",
        "different documents", "how many documents", "most documents",
    ]
    regex_patterns = [
        r"summarize.*document", r"list.*document",
        r"appears?\s+in.*documents", r"which.*documents?",
    ]
    is_per_doc = (
        any(p in q_lower for p in simple_patterns) or
        any(re.search(p, q_lower) for p in regex_patterns)
    )
    doc_guidance = ""
    if is_per_doc:
        doc_guidance = """
- The evidence groups chunks by "=== DOCUMENT: <title> ===" headers. Count unique top-level documents only; combine sections/exhibits into parent.
"""
    return f"""Answer the question below using ONLY the evidence provided.

Question: {query}

Evidence (citation markers [N]):
{context}

Rules:
- If the evidence does NOT contain the specific information requested, respond ONLY with: "The requested information was not found in the available documents."
- Do NOT provide alternative or related information when the exact item is missing.
- Cite every factual claim with [N].
- Quote exact numeric values, dates, dollar amounts, and deadlines from the evidence.
- Answer directly and concisely — no section headers unless the question asks for a list or comparison.
- Include ONLY information that answers what was asked. Omit background context, qualifiers, and hedging.
{doc_guidance}
Your response:"""


PROMPT_BUILDERS = {
    "v0": _build_prompt_v0,
    "v1_concise": _build_prompt_v1_concise,
}

REFUSAL = "The requested information was not found in the available documents."


# ── Main ──

def main() -> int:
    ap = argparse.ArgumentParser(description="Route 2 Prompt + Model comparison (local replay)")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=_default_group_id())
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument("--models", nargs="+", default=["gpt-5.1", "gpt-4.1"])
    ap.add_argument("--prompts", nargs="+", default=["v0", "v1_concise"])
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--from-context", type=str, default=None,
                    help="Path to saved JSON with captured contexts (skips Phase 1)")
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()
    models = list(args.models)
    prompts = list(args.prompts)

    questions = _read_question_bank(qbank)
    ground_truth = _extract_ground_truth(qbank)

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"route2_prompt_model_{stamp}.json"
    out_md = out_dir / f"route2_prompt_model_{stamp}.md"

    combos = [(p, m) for p in prompts for m in models]

    print("=" * 70)
    print("ROUTE 2 PROMPT + MODEL COMPARISON (2-Phase Local Replay)")
    print("=" * 70)
    print(f"  models:    {models}")
    print(f"  prompts:   {prompts}")
    print(f"  combos:    {len(combos)} ({' / '.join(f'{p}+{m}' for p, m in combos)})")
    print(f"  questions: {len(questions)}")
    print(f"  group_id:  {group_id}")
    if args.from_context:
        print(f"  from_ctx:  {args.from_context} (skipping Phase 1)")
    print("=" * 70, flush=True)

    # ── Phase 1: Capture context ──
    captured: Dict[str, Dict[str, Any]] = {}

    if args.from_context:
        ctx_path = Path(args.from_context)
        print(f"\nPhase 1: Loading saved context from {ctx_path}...")
        saved = json.loads(ctx_path.read_text(encoding="utf-8"))
        captured = saved.get("captured_contexts", {})
        print(f"  Loaded context for {len(captured)} questions")
    else:
        print(f"\nPhase 1: Capturing context ({len(questions)} questions via API)...")
        api_token = _get_aad_token()
        api_headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Group-ID": group_id,
        }
        if api_token:
            api_headers["Authorization"] = f"Bearer {api_token}"
            print("  ✓ Using Azure AD auth")

        endpoint = base_url + "/hybrid/query"

        for qi, q in enumerate(questions, 1):
            gt = ground_truth.get(q.qid)
            is_neg = gt.is_negative if gt else q.qid.startswith("Q-N")
            effective_query = (q.query + NEGATIVE_SUFFIX) if is_neg else q.query

            payload = {
                "query": effective_query,
                "force_route": "local_search",
                "response_type": "summary",
                "include_context": True,
            }
            status, resp, elapsed = _http_post(endpoint, api_headers, payload, args.timeout)
            retrieval_ms = int(round(elapsed * 1000))

            llm_context = None
            answer = ""
            if isinstance(resp, dict):
                meta = resp.get("metadata") or {}
                llm_context = meta.get("llm_context")
                answer = resp.get("response", "")

            if llm_context:
                captured[q.qid] = {
                    "query": effective_query,
                    "llm_context": llm_context,
                    "retrieval_ms": retrieval_ms,
                    "baseline_answer": answer,
                }
                ctx_len = len(llm_context)
                print(f"  [{qi}/{len(questions)}] {q.qid}: {ctx_len:,} chars ({retrieval_ms}ms)", flush=True)
            elif answer:
                # Negative query with no context but valid refusal
                captured[q.qid] = {
                    "query": effective_query,
                    "llm_context": "",
                    "retrieval_ms": retrieval_ms,
                    "baseline_answer": answer,
                }
                print(f"  [{qi}/{len(questions)}] {q.qid}: no context, answer={len(answer)} chars ({retrieval_ms}ms)", flush=True)
            else:
                print(f"  [{qi}/{len(questions)}] {q.qid}: ⚠ FAILED (status={status})", flush=True)

    if not captured:
        print("\nERROR: No context captured. Cannot proceed.")
        return 1

    # ── Phase 2: Local replay ──
    print(f"\nPhase 2: Replaying through {len(combos)} combos...")
    aoai_endpoint = _get_aoai_endpoint()
    aoai_token = _get_aoai_token()
    print(f"  ✓ Azure OpenAI: {aoai_endpoint}")

    active_qs = [q for q in questions if q.qid in captured]
    total = len(combos) * len(active_qs) * args.repeats
    call_num = 0

    # results[combo_key][qid] = { ... }
    results: Dict[str, Dict[str, Any]] = {}
    for p, m in combos:
        results[f"{p}+{m}"] = {}

    for q in active_qs:
        ctx = captured[q.qid]
        gt = ground_truth.get(q.qid)
        is_neg = gt.is_negative if gt else q.qid.startswith("Q-N")

        # Skip LLM replay for questions with no context (pure negative refusals)
        if not ctx["llm_context"]:
            for p, m in combos:
                key = f"{p}+{m}"
                results[key][q.qid] = {
                    "qid": q.qid, "query": q.query, "prompt": p, "model": m,
                    "synthesis_ms": 0, "answer": ctx.get("baseline_answer", REFUSAL),
                    "answer_chars": len(ctx.get("baseline_answer", REFUSAL)),
                    "answer_words": len(ctx.get("baseline_answer", REFUSAL).split()),
                    "accuracy": _calculate_accuracy(
                        gt.expected if gt else "", ctx.get("baseline_answer", REFUSAL), is_neg,
                    ),
                    "skipped": True,
                }
            print(f"  {q.qid}: skipped (no context, using baseline refusal)", flush=True)
            continue

        for p, m in combos:
            key = f"{p}+{m}"
            builder = PROMPT_BUILDERS.get(p, _build_prompt_v0)
            prompt_text = builder(ctx["query"], ctx["llm_context"])

            runs = []
            for ri in range(args.repeats):
                call_num += 1
                try:
                    text, synth_ms = _call_aoai(
                        endpoint=aoai_endpoint, token=aoai_token,
                        deployment=m, prompt=prompt_text,
                    )
                    runs.append({"text": text, "ms": synth_ms, "error": None})
                except Exception as e:
                    runs.append({"text": "", "ms": 0, "error": str(e)})

            best = runs[0] if runs else {"text": "", "ms": 0}
            accuracy = _calculate_accuracy(
                gt.expected if gt else "", best["text"], is_neg,
            )
            synth_times = [r["ms"] for r in runs if not r.get("error")]
            avg_ms = int(sum(synth_times) / len(synth_times)) if synth_times else 0

            results[key][q.qid] = {
                "qid": q.qid, "query": q.query, "prompt": p, "model": m,
                "synthesis_ms": avg_ms, "answer": best["text"],
                "answer_chars": len(best["text"]),
                "answer_words": len(best["text"].split()),
                "accuracy": accuracy,
                "runs": runs,
            }

            # Progress
            acc_str = ""
            if is_neg:
                acc_str = "NEG_PASS" if accuracy.get("negative_pass") else "NEG_FAIL"
            else:
                f1_val = accuracy.get("f1", 0)
                cont = "✓" if accuracy.get("containment") else "✗"
                acc_str = f"F1={f1_val:.3f} cont={cont}"
            print(
                f"  [{call_num}/{total}] {q.qid} | {key:25s} | "
                f"{avg_ms:5d}ms | {len(best['text']):5d}ch | {acc_str}",
                flush=True,
            )

    # ── Aggregate ──
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)

    combo_summary: Dict[str, Dict[str, Any]] = {}
    for combo_key in results:
        qdata = results[combo_key]
        pos = [v for v in qdata.values() if not v["accuracy"].get("is_negative")]
        neg = [v for v in qdata.values() if v["accuracy"].get("is_negative")]

        f1s = [v["accuracy"]["f1"] for v in pos if v["accuracy"].get("f1") is not None]
        precs = [v["accuracy"]["precision"] for v in pos if v["accuracy"].get("precision") is not None]
        recs = [v["accuracy"]["recall"] for v in pos if v["accuracy"].get("recall") is not None]
        conts = [1 if v["accuracy"].get("containment") else 0 for v in pos]
        neg_passes = [1 if v["accuracy"].get("negative_pass") else 0 for v in neg]
        synth_ms_list = [v["synthesis_ms"] for v in qdata.values() if v["synthesis_ms"] > 0]
        char_list = [v["answer_chars"] for v in pos]
        word_list = [v["answer_words"] for v in pos]

        combo_summary[combo_key] = {
            "avg_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0,
            "avg_precision": round(sum(precs) / len(precs), 4) if precs else 0,
            "avg_recall": round(sum(recs) / len(recs), 4) if recs else 0,
            "containment": f"{sum(conts)}/{len(conts)}" if conts else "0/0",
            "containment_pct": round(sum(conts) / len(conts), 3) if conts else 0,
            "neg_pass": f"{sum(neg_passes)}/{len(neg_passes)}" if neg_passes else "0/0",
            "neg_pass_pct": round(sum(neg_passes) / len(neg_passes), 3) if neg_passes else 0,
            "avg_synthesis_ms": int(sum(synth_ms_list) / len(synth_ms_list)) if synth_ms_list else 0,
            "avg_answer_chars": int(sum(char_list) / len(char_list)) if char_list else 0,
            "avg_answer_words": int(sum(word_list) / len(word_list)) if word_list else 0,
        }

    # Console table
    print(f"{'Combo':25s} {'F1':>7s} {'Prec':>7s} {'Rec':>7s} {'Cont':>7s} {'Neg':>7s} {'SynthMs':>9s} {'Chars':>7s} {'Words':>7s}")
    print("-" * 95)
    for ck in results:
        s = combo_summary[ck]
        print(
            f"{ck:25s} {s['avg_f1']:>7.3f} {s['avg_precision']:>7.3f} {s['avg_recall']:>7.3f} "
            f"{s['containment']:>7s} {s['neg_pass']:>7s} {s['avg_synthesis_ms']:>7d}ms "
            f"{s['avg_answer_chars']:>7d} {s['avg_answer_words']:>7d}"
        )
    print("=" * 95)

    # ── Save JSON ──
    output = {
        "meta": {
            "created_utc": stamp,
            "method": "2-phase: capture Route 2 context once, replay each (prompt, model) combo directly via Azure OpenAI",
            "aoai_endpoint": aoai_endpoint,
            "models": models, "prompts": prompts,
            "combos": [f"{p}+{m}" for p, m in combos],
            "questions": len(active_qs), "repeats": args.repeats,
            "api_url": base_url, "group_id": group_id,
        },
        "captured_contexts": {
            qid: {"query": c["query"], "retrieval_ms": c["retrieval_ms"],
                  "llm_context": c["llm_context"],
                  "baseline_answer": c.get("baseline_answer", "")}
            for qid, c in captured.items()
        },
        "combo_summary": combo_summary,
        "results": results,
    }
    out_json.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Save Markdown ──
    md = []
    md.append(f"# Route 2 Prompt + Model Comparison ({stamp})\n\n")
    md.append(f"- **Combos:** {', '.join(f'{p}+{m}' for p, m in combos)}\n")
    md.append(f"- **Questions:** {len(active_qs)} (Q-L positive + Q-N negative)\n")
    md.append(f"- **Group ID:** {group_id}\n\n")

    md.append("## Summary\n\n")
    md.append(f"| Combo | F1 | Precision | Recall | Containment | Neg Pass | Synth ms | Chars | Words |\n")
    md.append(f"|-------|-----|-----------|--------|-------------|----------|----------|-------|-------|\n")
    for ck in results:
        s = combo_summary[ck]
        md.append(
            f"| {ck} | {s['avg_f1']:.3f} | {s['avg_precision']:.3f} | {s['avg_recall']:.3f} | "
            f"{s['containment']} | {s['neg_pass']} | {s['avg_synthesis_ms']}ms | "
            f"{s['avg_answer_chars']} | {s['avg_answer_words']} |\n"
        )

    # Per-question F1 comparison
    md.append("\n## Per-Question F1\n\n")
    headers = ["QID"] + list(results.keys())
    md.append("| " + " | ".join(headers) + " |\n")
    md.append("|" + "|".join(["---"] * len(headers)) + "|\n")
    for q in active_qs:
        cells = [q.qid]
        for ck in results:
            d = results[ck].get(q.qid, {})
            acc = d.get("accuracy", {})
            if acc.get("is_negative"):
                cells.append("NEG " + ("✓" if acc.get("negative_pass") else "✗"))
            else:
                f1_val = acc.get("f1", 0)
                cont = "✓" if acc.get("containment") else "✗"
                cells.append(f"{f1_val:.3f} {cont}")
        md.append("| " + " | ".join(cells) + " |\n")

    out_md.write_text("".join(md), encoding="utf-8")
    print(f"\nSaved: {out_json}")
    print(f"Saved: {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
