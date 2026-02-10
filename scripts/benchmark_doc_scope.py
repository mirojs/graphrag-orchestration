#!/usr/bin/env python3
"""
Benchmark: Document-Scope Retrieval Impact on Route 2 F1
=========================================================

Two-mode benchmark:
  Phase 1  – Capture Route 2 context from the LIVE API (no doc-scope deployed).
  Phase 1b – For each question, query Neo4j directly to determine target docs
             via IDF-weighted voting, then filter captured context post-hoc.
  Phase 2a – Replay FULL (baseline) context → Azure OpenAI → measure F1.
  Phase 2b – Replay DOC-FILTERED context  → Azure OpenAI → measure F1.

This gives a conservative estimate – in production, doc-scoped Cypher would
fetch MORE relevant chunks from the target doc, which this simulation can't
capture.  But it accurately models the noise-removal benefit.

Usage:
    python scripts/benchmark_doc_scope.py
    python scripts/benchmark_doc_scope.py --from-context benchmarks/doc_scope_ctx_*.json
    python scripts/benchmark_doc_scope.py --models gpt-5-mini gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_QUESTION_BANK = PROJECT_ROOT / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md"
DEFAULT_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
DEFAULT_GROUP_ID = "test-5pdfs-v2-fix2"

# Neo4j connection
NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"

# IDF voting thresholds (must match synthesis.py)
DOC_SCOPE_MIN_SCORE = 1.5
DOC_SCOPE_DOMINANCE = 0.5   # top/total must exceed this

# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Question:
    qid: str
    query: str
    expected: str = ""
    source_doc: str = ""      # Which doc(s) the answer lives in
    is_negative: bool = False

@dataclass
class GroundTruth:
    expected: str
    is_negative: bool = False

@dataclass
class DocVote:
    doc_id: str
    doc_title: str
    score: float
    matching_seeds: List[str]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _read_question_bank(path: Path) -> List[Question]:
    """Parse Q-L* and Q-N* questions from the question bank markdown."""
    text = path.read_text(encoding="utf-8")
    questions: List[Question] = []
    # Match Q-L and Q-N questions
    for m in re.finditer(
        r'\*\*(Q-[LN]\d+):\*\*\s+(.+?)(?:\n|$)', text
    ):
        qid, query = m.group(1), m.group(2).strip()
        is_neg = qid.startswith("Q-N")
        questions.append(Question(qid=qid, query=query, is_negative=is_neg))
    return questions


def _extract_ground_truth(path: Path) -> Dict[str, GroundTruth]:
    """Extract expected answers from the question bank."""
    text = path.read_text(encoding="utf-8")
    gt: Dict[str, GroundTruth] = {}
    blocks = re.split(r'\n\d+\.\s+\*\*', text)
    for block in blocks:
        m = re.match(r'(Q-[A-Z]+\d+):\*\*', block)
        if not m:
            continue
        qid = m.group(1)
        is_neg = qid.startswith("Q-N")
        expected_parts = []
        for line in block.split('\n'):
            if '**Expected:**' in line or '**Expected:' in line:
                after = re.sub(r'.*\*\*Expected:\*\*\s*', '', line).strip()
                if after:
                    expected_parts.append(after)
            elif expected_parts and line.strip().startswith('-'):
                expected_parts.append(line.strip())
        expected = ' '.join(expected_parts) if expected_parts else ""
        # Also grab single-line expected with backticks
        m2 = re.search(r'\*\*Expected:\*\*\s*`([^`]+)`', block)
        if m2 and not expected:
            expected = m2.group(1)
        gt[qid] = GroundTruth(expected=expected, is_negative=is_neg)
    return gt


def _calculate_accuracy(expected: str, answer: str, is_negative: bool) -> Dict[str, Any]:
    """Token-level F1, containment, negative detection."""
    result: Dict[str, Any] = {"is_negative": is_negative}

    if is_negative:
        neg_patterns = [
            "not found", "not specified", "not mentioned", "no information",
            "not available", "not provided", "none", "n/a", "not included",
            "not present", "not stated", "does not", "no relevant",
            "not contain", "no mention", "not referenced",
        ]
        ans_lower = answer.lower()
        result["negative_pass"] = any(p in ans_lower for p in neg_patterns)
        result["f1"] = None
        result["precision"] = None
        result["recall"] = None
        result["containment"] = None
        return result

    def _tokenise(s: str) -> List[str]:
        return re.findall(r'\w+', s.lower())

    exp_toks = _tokenise(expected)
    ans_toks = _tokenise(answer)
    if not exp_toks:
        result.update(f1=0, precision=0, recall=0, containment=False)
        return result

    exp_set = set(exp_toks)
    ans_set = set(ans_toks)
    overlap = exp_set & ans_set
    precision = len(overlap) / len(ans_set) if ans_set else 0
    recall = len(overlap) / len(exp_set) if exp_set else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    # Containment: substring or high recall
    containment = (expected.lower().strip() in answer.lower()) or recall >= 0.8

    result.update(f1=round(f1, 4), precision=round(precision, 4),
                  recall=round(recall, 4), containment=containment)
    return result


# ── Neo4j direct queries (for IDF voting simulation) ────────────────────────

def _get_neo4j_driver():
    """Create a Neo4j driver."""
    try:
        from neo4j import GraphDatabase
        return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except ImportError:
        print("ERROR: neo4j package not installed. Run: pip install neo4j", file=sys.stderr)
        sys.exit(1)


def _resolve_target_doc_from_question(query: str) -> Optional[str]:
    """Determine the target document from the question text.

    For Q-L questions, the question text explicitly references which document
    the answer lives in.  This simulates what IDF voting would produce in
    the real pipeline (where PPR-expanded entities resolve to graph nodes
    that are linked to specific documents via APPEARS_IN_DOCUMENT edges).

    Returns the canonical document title or None if the question is multi-doc
    or the target is ambiguous.
    """
    q_lower = query.lower()

    # Map question keywords to canonical document titles (as they appear
    # in the context headers "=== DOCUMENT: <title> ===")
    doc_patterns: List[Tuple[str, str]] = [
        ("property management", "PROPERTY MANAGEMENT AGREEMENT"),
        ("purchase contract", "purchase_contract"),
        ("holding tank", "HOLDING TANK SERVICING CONTRACT"),
        ("warranty", "BUILDERS LIMITED WARRANTY"),
        ("invoice", "contoso_lifts_invoice"),
        ("contoso lifts", "contoso_lifts_invoice"),
    ]
    for pattern, doc_title in doc_patterns:
        if pattern in q_lower:
            return doc_title

    return None


def _query_entity_doc_coverage_neo4j(driver, seed_names: List[str],
                                      group_id: str) -> List[Dict[str, Any]]:
    """Query Neo4j for entity → document coverage via APPEARS_IN_DOCUMENT edges.

    Filters by group_id to ensure we only look at entities from the right corpus.
    Uses CONTAINS matching for partial name matches.
    """
    if not seed_names:
        return []

    cypher = """
    UNWIND $seed_names AS seed
    MATCH (e:__Entity__)-[:APPEARS_IN_DOCUMENT]->(d:Document)
    WHERE (toLower(e.id) CONTAINS toLower(seed)
           OR toLower(e.name) CONTAINS toLower(seed))
      AND e.group_id = $group_id
    WITH d, collect(DISTINCT e.name) AS matched_entities
    RETURN d.id AS doc_id,
           d.title AS doc_title,
           matched_entities AS matching_seeds,
           size(matched_entities) AS seed_count
    ORDER BY seed_count DESC
    """
    count_cypher = """
    UNWIND $seed_names AS seed
    MATCH (e:__Entity__)-[:APPEARS_IN_DOCUMENT]->(d:Document)
    WHERE (toLower(e.id) CONTAINS toLower(seed)
           OR toLower(e.name) CONTAINS toLower(seed))
      AND e.group_id = $group_id
    WITH e.name AS entity_name, count(DISTINCT d) AS doc_count
    RETURN entity_name, doc_count
    """

    with driver.session(database="neo4j") as session:
        docs_result = session.run(cypher, seed_names=seed_names,
                                  group_id=group_id).data()
        counts_result = session.run(count_cypher, seed_names=seed_names,
                                    group_id=group_id).data()

    entity_doc_counts = {r["entity_name"]: r["doc_count"] for r in counts_result}

    enriched = []
    for row in docs_result:
        enriched.append({
            "doc_id": row["doc_id"],
            "doc_title": row["doc_title"],
            "matching_seeds": row["matching_seeds"],
            "entity_doc_counts": {
                ent: entity_doc_counts.get(ent, 1)
                for ent in row["matching_seeds"]
            },
        })
    return enriched


def _filter_context_by_docs(context: str, target_doc_titles: List[str]) -> str:
    """Filter an LLM context string to only include chunks from target documents.

    The context is structured as:
      ## Retrieved from N unique source document(s): ...
      === DOCUMENT: <title> ===
      [1] Section > ...
      <chunk text>
      === DOCUMENT: <other title> ===
      ...

    Returns filtered context with only target document sections.
    """
    if not context or not target_doc_titles:
        return context

    # Normalise target titles for matching
    target_lower = [t.lower().strip() for t in target_doc_titles]

    # Split context by document headers
    # Pattern: === DOCUMENT: <title> ===
    doc_pattern = re.compile(r'^(=== DOCUMENT:\s*(.+?)\s*===)\s*$', re.MULTILINE)

    # Find all document section boundaries
    matches = list(doc_pattern.finditer(context))
    if not matches:
        return context  # No document headers found, return as-is

    # Extract header content (before first document section)
    header = context[:matches[0].start()].strip()

    # Extract each document section
    sections: List[Tuple[str, str, str]] = []  # (title, header_line, content)
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(context)
        content = context[start:end].strip()
        sections.append((title, m.group(1), content))

    # Filter to target documents
    kept = []
    for title, header_line, content in sections:
        title_lower = title.lower().strip()
        # Match by substring containment (handles slight title variations)
        if any(t in title_lower or title_lower in t for t in target_lower):
            kept.append(content)

    if not kept:
        return context  # Nothing matched, return original to be safe

    # Rebuild header with correct doc count
    kept_titles = []
    for title, _, _ in sections:
        title_lower = title.lower().strip()
        if any(t in title_lower or title_lower in t for t in target_lower):
            kept_titles.append(title)

    new_header = f"## Retrieved from {len(kept_titles)} unique source document(s): {', '.join(kept_titles)}\n"
    return new_header + "\n\n" + "\n\n".join(kept)


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _get_aad_token() -> Optional[str]:
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
    return "https://graphrag-openai-8476.openai.azure.com"


def _get_aoai_token() -> str:
    r = subprocess.run(
        ["az", "account", "get-access-token",
         "--resource", "https://cognitiveservices.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


# ── Azure OpenAI call ────────────────────────────────────────────────────────

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


# ── HTTP helper ──────────────────────────────────────────────────────────────

def _http_post(url: str, headers: Dict, payload: Dict,
               timeout: float = 180) -> Tuple[int, Any, float]:
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


# ── Prompt builder (v1_concise only — best performer) ────────────────────────

NEGATIVE_SUFFIX = "\n\nIf the requested information is not found in the uploaded documents, respond ONLY with: \"The requested information was not found in the available documents.\""
REFUSAL = "The requested information was not found in the available documents."


def _build_prompt(query: str, context: str) -> str:
    """v1_concise prompt — precision-optimised."""
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
        doc_guidance = "\n- The evidence groups chunks by \"=== DOCUMENT: <title> ===\" headers. Count unique top-level documents only; combine sections/exhibits into parent.\n"
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


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Document-Scope Retrieval Benchmark")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=DEFAULT_GROUP_ID)
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument("--models", nargs="+", default=["gpt-5-mini", "gpt-4.1-mini"])
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--from-context", type=str, default=None,
                    help="Path to saved JSON with captured contexts (skips Phase 1)")
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()
    models = list(args.models)

    questions = _read_question_bank(qbank)
    ground_truth = _extract_ground_truth(qbank)

    stamp = _now_utc_stamp()
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"doc_scope_{stamp}.json"
    out_md = out_dir / f"doc_scope_{stamp}.md"

    print("=" * 75)
    print("DOCUMENT-SCOPE RETRIEVAL BENCHMARK")
    print("=" * 75)
    print(f"  models:    {models}")
    print(f"  questions: {len(questions)} (Q-L* positive + Q-N* negative)")
    print(f"  group_id:  {group_id}")
    print(f"  IDF min:   {DOC_SCOPE_MIN_SCORE}")
    if args.from_context:
        print(f"  from_ctx:  {args.from_context} (skipping Phase 1)")
    print("=" * 75, flush=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 1: Capture context from live API
    # ═══════════════════════════════════════════════════════════════════════
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
            is_neg = q.is_negative
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
                captured[q.qid] = {
                    "query": effective_query,
                    "llm_context": "",
                    "retrieval_ms": retrieval_ms,
                    "baseline_answer": answer,
                }
                print(f"  [{qi}/{len(questions)}] {q.qid}: no context, answer={len(answer)} chars", flush=True)
            else:
                print(f"  [{qi}/{len(questions)}] {q.qid}: ⚠ FAILED (status={status})", flush=True)

    if not captured:
        print("\nERROR: No context captured. Cannot proceed.")
        return 1

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 1b: Determine target doc per question (question-text matching
    #           + optional Neo4j IDF confirmation)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPhase 1b: Resolving target document per question...")

    doc_scope_results: Dict[str, Dict[str, Any]] = {}

    for q in questions:
        if q.qid not in captured:
            continue

        target_title = _resolve_target_doc_from_question(q.query)
        if target_title:
            doc_scope_results[q.qid] = {
                "target_titles": [target_title],
                "reason": "question_text_match",
            }
            print(f"  {q.qid}: → {target_title} [question_text_match]", flush=True)
        else:
            doc_scope_results[q.qid] = {
                "target_titles": [],
                "reason": "ambiguous_or_multidoc",
            }
            print(f"  {q.qid}: → (blind) [ambiguous/multi-doc]", flush=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 1c: Build filtered contexts
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPhase 1c: Building doc-filtered contexts...")
    filtered_contexts: Dict[str, str] = {}

    for q in questions:
        if q.qid not in captured:
            continue
        ctx = captured[q.qid]["llm_context"]
        scope = doc_scope_results.get(q.qid, {})
        target_titles = scope.get("target_titles", [])

        if target_titles and ctx:
            filtered = _filter_context_by_docs(ctx, target_titles)
            filtered_contexts[q.qid] = filtered
            reduction = 1 - len(filtered) / len(ctx) if len(ctx) > 0 else 0
            print(f"  {q.qid}: {len(ctx):,} → {len(filtered):,} chars ({reduction:.0%} reduction)",
                  flush=True)
        else:
            filtered_contexts[q.qid] = ctx
            print(f"  {q.qid}: no filtering (fallback)", flush=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Phase 2: Replay through Azure OpenAI — baseline vs doc-scoped
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPhase 2: Replaying through Azure OpenAI...")
    aoai_endpoint = _get_aoai_endpoint()
    aoai_token = _get_aoai_token()
    print(f"  ✓ Azure OpenAI: {aoai_endpoint}")

    active_qs = [q for q in questions if q.qid in captured]
    modes = ["baseline", "doc_scope"]
    combos = [(mode, model) for mode in modes for model in models]
    total_calls = len([q for q in active_qs if captured[q.qid]["llm_context"]]) * len(combos)
    call_num = 0

    # results[combo_key][qid] = { ... }
    results: Dict[str, Dict[str, Any]] = {}
    for mode, model in combos:
        results[f"{mode}+{model}"] = {}

    for q in active_qs:
        ctx_data = captured[q.qid]
        gt = ground_truth.get(q.qid)
        is_neg = gt.is_negative if gt else q.is_negative

        # Skip LLM replay for questions with no context
        if not ctx_data["llm_context"]:
            for mode, model in combos:
                key = f"{mode}+{model}"
                results[key][q.qid] = {
                    "qid": q.qid, "query": q.query, "mode": mode, "model": model,
                    "synthesis_ms": 0, "answer": ctx_data.get("baseline_answer", REFUSAL),
                    "answer_chars": len(ctx_data.get("baseline_answer", REFUSAL)),
                    "accuracy": _calculate_accuracy(
                        gt.expected if gt else "", ctx_data.get("baseline_answer", REFUSAL), is_neg,
                    ),
                    "skipped": True,
                }
            print(f"  {q.qid}: skipped (no context, using baseline refusal)", flush=True)
            continue

        for mode, model in combos:
            key = f"{mode}+{model}"
            # Select context
            if mode == "doc_scope":
                context = filtered_contexts.get(q.qid, ctx_data["llm_context"])
            else:
                context = ctx_data["llm_context"]

            prompt_text = _build_prompt(ctx_data["query"], context)
            call_num += 1

            try:
                text, synth_ms = _call_aoai(
                    endpoint=aoai_endpoint, token=aoai_token,
                    deployment=model, prompt=prompt_text,
                )
            except Exception as e:
                text, synth_ms = f"ERROR: {e}", 0

            accuracy = _calculate_accuracy(
                gt.expected if gt else "", text, is_neg,
            )

            results[key][q.qid] = {
                "qid": q.qid, "query": q.query, "mode": mode, "model": model,
                "synthesis_ms": synth_ms, "answer": text,
                "answer_chars": len(text),
                "context_chars": len(context),
                "accuracy": accuracy,
            }

            # Progress
            if is_neg:
                acc_str = "NEG_PASS" if accuracy.get("negative_pass") else "NEG_FAIL"
            else:
                f1_val = accuracy.get("f1", 0)
                cont = "✓" if accuracy.get("containment") else "✗"
                acc_str = f"F1={f1_val:.3f} cont={cont}"
            print(
                f"  [{call_num}/{total_calls}] {q.qid} | {key:30s} | "
                f"{synth_ms:5d}ms | {len(context):5d}ch ctx | {acc_str}",
                flush=True,
            )

    # ═══════════════════════════════════════════════════════════════════════
    # Aggregate & Report
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("RESULTS SUMMARY")
    print("=" * 90)

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
        ctx_chars = [v.get("context_chars", 0) for v in pos if v.get("context_chars")]

        combo_summary[combo_key] = {
            "avg_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0,
            "avg_precision": round(sum(precs) / len(precs), 4) if precs else 0,
            "avg_recall": round(sum(recs) / len(recs), 4) if recs else 0,
            "containment": f"{sum(conts)}/{len(conts)}" if conts else "0/0",
            "containment_pct": round(sum(conts) / len(conts), 3) if conts else 0,
            "neg_pass": f"{sum(neg_passes)}/{len(neg_passes)}" if neg_passes else "0/0",
            "neg_pass_pct": round(sum(neg_passes) / len(neg_passes), 3) if neg_passes else 0,
            "avg_synthesis_ms": int(sum(synth_ms_list) / len(synth_ms_list)) if synth_ms_list else 0,
            "avg_context_chars": int(sum(ctx_chars) / len(ctx_chars)) if ctx_chars else 0,
        }

    # Console table
    print(f"\n{'Combo':30s} {'F1':>7s} {'Prec':>7s} {'Rec':>7s} {'Cont':>7s} {'Neg':>7s} {'CtxCh':>7s} {'Ms':>7s}")
    print("-" * 90)
    for ck in results:
        s = combo_summary[ck]
        print(
            f"{ck:30s} {s['avg_f1']:>7.3f} {s['avg_precision']:>7.3f} {s['avg_recall']:>7.3f} "
            f"{s['containment']:>7s} {s['neg_pass']:>7s} {s['avg_context_chars']:>7d} "
            f"{s['avg_synthesis_ms']:>5d}ms"
        )
    print("=" * 90)

    # Delta summary
    print("\n── Delta (doc_scope - baseline) ──")
    for model in models:
        bk = f"baseline+{model}"
        dk = f"doc_scope+{model}"
        if bk in combo_summary and dk in combo_summary:
            bf = combo_summary[bk]["avg_f1"]
            df = combo_summary[dk]["avg_f1"]
            bp = combo_summary[bk]["avg_precision"]
            dp = combo_summary[dk]["avg_precision"]
            br = combo_summary[bk]["avg_recall"]
            dr = combo_summary[dk]["avg_recall"]
            bc = combo_summary[bk]["avg_context_chars"]
            dc = combo_summary[dk]["avg_context_chars"]
            print(f"  {model:20s}  F1: {bf:.3f} → {df:.3f} (Δ{df-bf:+.3f})  "
                  f"Prec: {bp:.3f} → {dp:.3f} (Δ{dp-bp:+.3f})  "
                  f"Rec: {br:.3f} → {dr:.3f} (Δ{dr-br:+.3f})  "
                  f"Ctx: {bc} → {dc} ({(dc-bc)/bc*100:+.0f}%)" if bc else "")

    # ── Save JSON ──
    output = {
        "meta": {
            "created_utc": stamp,
            "method": "Post-hoc doc-scope simulation: capture context from API, "
                      "filter by IDF-voted target document, replay through AOAI",
            "aoai_endpoint": aoai_endpoint,
            "models": models,
            "idf_min_score": DOC_SCOPE_MIN_SCORE,
            "idf_dominance": DOC_SCOPE_DOMINANCE,
            "questions": len(active_qs),
            "api_url": base_url, "group_id": group_id,
        },
        "captured_contexts": {
            qid: {"query": c["query"], "retrieval_ms": c["retrieval_ms"],
                  "llm_context": c["llm_context"],
                  "baseline_answer": c.get("baseline_answer", "")}
            for qid, c in captured.items()
        },
        "doc_scope_results": doc_scope_results,
        "combo_summary": combo_summary,
        "results": results,
    }
    out_json.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Save Markdown ──
    md = []
    md.append(f"# Document-Scope Benchmark ({stamp})\n\n")
    md.append(f"- **Models:** {', '.join(models)}\n")
    md.append(f"- **Questions:** {len(active_qs)} (Q-L positive + Q-N negative)\n")
    md.append(f"- **IDF min score:** {DOC_SCOPE_MIN_SCORE}\n")
    md.append(f"- **Method:** Post-hoc doc-scope simulation\n\n")

    md.append("## Summary\n\n")
    md.append("| Combo | F1 | Precision | Recall | Containment | Neg Pass | Ctx Chars | Synth ms |\n")
    md.append("|-------|-----|-----------|--------|-------------|----------|-----------|----------|\n")
    for ck in results:
        s = combo_summary[ck]
        md.append(
            f"| {ck} | {s['avg_f1']:.3f} | {s['avg_precision']:.3f} | {s['avg_recall']:.3f} | "
            f"{s['containment']} | {s['neg_pass']} | {s['avg_context_chars']} | "
            f"{s['avg_synthesis_ms']}ms |\n"
        )

    md.append("\n## Delta (doc_scope - baseline)\n\n")
    md.append("| Model | F1 Δ | Precision Δ | Recall Δ | Context Δ |\n")
    md.append("|-------|------|-------------|----------|-----------|\n")
    for model in models:
        bk = f"baseline+{model}"
        dk = f"doc_scope+{model}"
        if bk in combo_summary and dk in combo_summary:
            bf = combo_summary[bk]["avg_f1"]
            df = combo_summary[dk]["avg_f1"]
            bp = combo_summary[bk]["avg_precision"]
            dp = combo_summary[dk]["avg_precision"]
            br = combo_summary[bk]["avg_recall"]
            dr = combo_summary[dk]["avg_recall"]
            bc = combo_summary[bk]["avg_context_chars"]
            dc = combo_summary[dk]["avg_context_chars"]
            ctx_delta = f"{(dc-bc)/bc*100:+.0f}%" if bc else "n/a"
            md.append(
                f"| {model} | {bf:.3f}→{df:.3f} ({df-bf:+.3f}) | "
                f"{bp:.3f}→{dp:.3f} ({dp-bp:+.3f}) | "
                f"{br:.3f}→{dr:.3f} ({dr-br:+.3f}) | {ctx_delta} |\n"
            )

    md.append("\n## Per-Question Detail\n\n")
    md.append("| QID | Target Doc | Reason | Ctx reduction |\n")
    md.append("|-----|------------|--------|---------------|\n")
    for q in active_qs:
        scope = doc_scope_results.get(q.qid, {})
        titles = scope.get("target_titles", [])
        reason = scope.get("reason", "-")
        orig_len = len(captured.get(q.qid, {}).get("llm_context", ""))
        filt_len = len(filtered_contexts.get(q.qid, ""))
        reduction = f"{(1 - filt_len/orig_len)*100:.0f}%" if orig_len > 0 else "-"
        md.append(
            f"| {q.qid} | "
            f"{', '.join(titles) if titles else '(blind)'} | "
            f"{reason} | {reduction} |\n"
        )

    md.append("\n## Per-Question F1 Comparison\n\n")
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
