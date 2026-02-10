#!/usr/bin/env python3

"""Route 3 Community-Structured Prompt A/B Test (Local).

Two-phase approach that isolates the *prompt format* difference from retrieval:

Phase 1 ("capture"):
  Call the cloud API once per question with include_context=True.
  Captures the assembled LLM context (doc-grouped, with Steps D1-D4 denoising).
  Also fetches community data from Neo4j (titles, summaries, entity_names).

Phase 2 ("replay"):
  For each captured question:
    A) Doc-grouped context (captured as-is) + standard prompt → AOAI direct
    B) Same chunks re-grouped by community + community summaries → AOAI direct
  Pure synthesis comparison — same chunks, different organisation.

Outputs
-------
- JSON + MD in ./benchmarks/ with per-variant, per-question metrics:
  - synthesis_latency_ms (pure LLM time)
  - theme coverage, accuracy (containment, f1)
  - context_tokens (doc-grouped vs community-grouped)

Usage
-----
  # Full run: capture + replay
  python3 scripts/benchmark_route3_community_prompt.py

  # Re-use saved context from a previous run (skip Phase 1):
  python3 scripts/benchmark_route3_community_prompt.py \\
    --from-context benchmarks/route3_community_prompt_*.json

  # Specify model:
  python3 scripts/benchmark_route3_community_prompt.py --model gpt-4.1

Dependencies: openai, azure-identity, neo4j (all in project venv).
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
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Re-use helpers from existing benchmarks
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root for src.*
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


# ── Azure OpenAI direct call (borrowed from synthesis model comparison) ──

def _get_aoai_endpoint() -> str:
    ep = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if ep:
        return ep.rstrip("/")
    for rg in ("rg-graphrag-feature", "rg-knowledgegraph"):
        try:
            result = subprocess.run(
                ["az", "cognitiveservices", "account", "list",
                 "--resource-group", rg,
                 "--query", "[?kind=='OpenAI' || kind=='AIServices'].properties.endpoint | [0]",
                 "-o", "tsv"],
                capture_output=True, text=True, check=True,
            )
            ep = result.stdout.strip()
            if ep:
                return ep.rstrip("/")
        except Exception:
            continue
    return "https://graphrag-openai-8476.openai.azure.com"


def _get_aoai_token() -> str:
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
    use_new_param = any(deployment.startswith(p) for p in ("gpt-5", "o3", "o4"))
    token_key = "max_completion_tokens" if use_new_param else "max_tokens"
    no_temperature = any(deployment.startswith(p) for p in ("gpt-5-mini", "gpt-5-nano", "o1", "o3", "o4"))
    payload: Dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        token_key: max_tokens,
    }
    if not no_temperature:
        payload["temperature"] = temperature
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    max_retries = 5
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
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
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if e.code == 429 and attempt < max_retries:
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else min(30, 5 * (2 ** attempt))
                print(f"    ⏳ 429 rate-limited, waiting {wait}s (attempt {attempt+1}/{max_retries})...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"AOAI HTTP {e.code}: {body}") from e
    raise RuntimeError("Exhausted retries")


# ── Neo4j community fetcher ──

def _fetch_communities_from_neo4j(group_id: str) -> List[Dict[str, Any]]:
    """Fetch all communities with entity_names from Neo4j."""
    neo4j_uri = os.environ.get("NEO4J_URI")
    neo4j_password = os.environ.get("NEO4J_PASSWORD")
    if not neo4j_uri or not neo4j_password:
        raise RuntimeError(
            "NEO4J_URI and NEO4J_PASSWORD env vars required. "
            "Set them or use --communities-json to load from file."
        )

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(neo4j_uri, auth=("neo4j", neo4j_password))
    query = """
    MATCH (c:Community {group_id: $group_id})
    WHERE c.title IS NOT NULL AND c.title <> ''
    OPTIONAL MATCH (c)<-[:BELONGS_TO]-(e:Entity)
    WITH c, collect(e.name) AS entity_names
    RETURN c.id AS id,
           c.title AS title,
           coalesce(c.summary, '') AS summary,
           coalesce(c.rank, 0.0) AS rank,
           entity_names
    ORDER BY c.rank DESC
    """
    with driver.session() as session:
        records = list(session.run(query, group_id=group_id))
    driver.close()

    communities = []
    for rec in records:
        communities.append({
            "id": rec["id"],
            "title": rec["title"],
            "summary": rec["summary"],
            "rank": rec["rank"],
            "entity_names": rec["entity_names"],
        })
    return communities


# ── Context parsing ──

def _parse_chunks_from_context(llm_context: str) -> Tuple[str, str, str, List[Dict[str, Any]]]:
    """Parse the formatted llm_context into structural sections + chunk list.

    Returns:
        (entity_section, relationship_section, header_line, chunks)
        where each chunk = {idx, section, entity, document, text}
    """
    # Split into sections.  The context is built as:
    #   entity_context + "\n\n" + relationship_context + "\n\n" + chunk_parts
    # Identify the chunk section by the "## Retrieved from" header or "=== DOCUMENT:" marker.
    lines = llm_context.split("\n")

    # Find the start of the chunk section
    chunk_start_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## Retrieved from ") or line.startswith("=== DOCUMENT:"):
            chunk_start_idx = i
            break

    if chunk_start_idx is None:
        # Can't parse — return the whole thing as is
        return "", "", "", []

    # Everything before chunk_start is entity + relationship context
    preamble = "\n".join(lines[:chunk_start_idx]).strip()

    # Try to split preamble into entity and relationship sections
    entity_section = ""
    relationship_section = ""

    # Look for "## Entity Descriptions:" marker
    entity_marker = "## Entity Descriptions:"
    rel_markers = ["## Key Relationships", "## Relationships"]

    if entity_marker in preamble:
        entity_start = preamble.index(entity_marker)
        # Find where relationships start
        rel_start = len(preamble)
        for rm in rel_markers:
            if rm in preamble:
                rel_start = min(rel_start, preamble.index(rm))
                break
        entity_section = preamble[entity_start:rel_start].strip()
        relationship_section = preamble[rel_start:].strip()
    else:
        # Treat entire preamble as relationship section
        relationship_section = preamble

    # Parse the header line (## Retrieved from N ...)
    header_line = ""
    if lines[chunk_start_idx].startswith("## Retrieved from"):
        header_line = lines[chunk_start_idx]
        chunk_start_idx += 1
        # Skip blank lines after header
        while chunk_start_idx < len(lines) and not lines[chunk_start_idx].strip():
            chunk_start_idx += 1

    # Parse chunks from the remaining lines
    # Pattern: [N] [Section: ...] [Entity: ...]
    chunk_pattern = re.compile(
        r'^\[(\d+)\]\s+\[Section:\s*(.*?)\]\s+\[Entity:\s*(.*?)\]'
    )
    doc_pattern = re.compile(r'^=== DOCUMENT:\s*(.*?)\s*===')

    chunks: List[Dict[str, Any]] = []
    current_doc = "Unknown"
    current_chunk: Optional[Dict[str, Any]] = None

    for i in range(chunk_start_idx, len(lines)):
        line = lines[i]

        # Check for document header
        doc_match = doc_pattern.match(line)
        if doc_match:
            current_doc = doc_match.group(1)
            continue

        # Check for chunk header
        chunk_match = chunk_pattern.match(line)
        if chunk_match:
            # Save previous chunk
            if current_chunk is not None:
                current_chunk["text"] = current_chunk["text"].strip()
                chunks.append(current_chunk)

            idx = int(chunk_match.group(1))
            section = chunk_match.group(2)
            entity = chunk_match.group(3)

            # Check if text follows on the same line (after the header)
            rest_of_line = line[chunk_match.end():].strip()

            current_chunk = {
                "idx": idx,
                "section": section,
                "entity": entity,
                "document": current_doc,
                "text": rest_of_line + "\n" if rest_of_line else "",
            }
            continue

        # Accumulate text for current chunk (skip blank lines between docs)
        if current_chunk is not None and line.strip():
            # Check if this is a sentence citation line like [1a] text...
            if re.match(r'^\[\d+[a-z]\]', line):
                current_chunk["text"] += line + "\n"
            elif not line.startswith("==="):
                current_chunk["text"] += line + "\n"

    # Save last chunk
    if current_chunk is not None:
        current_chunk["text"] = current_chunk["text"].strip()
        chunks.append(current_chunk)

    return entity_section, relationship_section, header_line, chunks


# ── Context builders ──

# Import shared sentence-marker stripping (authoritative regex lives in synthesis.py)
from src.worker.hybrid_v2.pipeline.synthesis import strip_sentence_markers as _strip_sentence_markers


def _estimate_tokens(text: str) -> int:
    """Quick token estimate (~4 chars per token)."""
    return max(1, len(text) // 4)


def _build_doc_grouped_context(
    entity_section: str,
    relationship_section: str,
    header_line: str,
    chunks: List[Dict[str, Any]],
) -> str:
    """Rebuild the original doc-grouped context (should match captured context)."""
    parts = []
    if entity_section:
        parts.append(entity_section)
    if relationship_section:
        parts.append(relationship_section)
    if header_line:
        parts.append(header_line + "\n")

    # Group by document
    doc_groups: Dict[str, List[Dict]] = defaultdict(list)
    for chunk in chunks:
        doc_groups[chunk["document"]].append(chunk)

    for doc_title, doc_chunks in doc_groups.items():
        parts.append(f"=== DOCUMENT: {doc_title} ===")
        for chunk in doc_chunks:
            entry = f"[{chunk['idx']}] [Section: {chunk['section']}] [Entity: {chunk['entity']}]\n{chunk['text']}"
            parts.append(entry)
        parts.append("")

    return "\n\n".join(parts) if parts else ""


def _build_community_grouped_context(
    entity_section: str,
    relationship_section: str,
    chunks: List[Dict[str, Any]],
    communities: List[Dict[str, Any]],
) -> str:
    """Build community-grouped context with theme summaries."""
    parts = []
    if entity_section:
        parts.append(entity_section)
    if relationship_section:
        parts.append(relationship_section)

    # Build entity → community reverse map
    entity_to_community: Dict[str, Dict[str, Any]] = {}
    for comm in communities:
        for ename in comm.get("entity_names", []):
            entity_to_community[ename.lower()] = comm

    # Group chunks by community
    community_groups: Dict[str, List[Tuple[Dict, Dict]]] = defaultdict(list)
    ungrouped: List[Dict] = []
    for chunk in chunks:
        ename = (chunk.get("entity") or "").lower()
        if ename in entity_to_community:
            comm = entity_to_community[ename]
            community_groups[comm["title"]].append((chunk, comm))
        else:
            ungrouped.append(chunk)

    # Unique documents for the header
    all_docs = sorted(set(c["document"] for c in chunks))

    parts.append(
        f"## Evidence organized by {len(community_groups)} thematic communities "
        f"(from {len(all_docs)} source documents: {', '.join(all_docs)})\n"
    )

    for comm_title, comm_chunks in community_groups.items():
        comm = comm_chunks[0][1]
        parts.append(f"=== COMMUNITY: {comm_title} ===")
        summary = comm.get("summary", "")
        if summary:
            parts.append(f"Theme: {summary[:500]}")
            parts.append("")

        for chunk, _ in comm_chunks:
            clean_text = _strip_sentence_markers(chunk['text'])
            entry = (
                f"[{chunk['idx']}] [Section: {chunk['section']}] "
                f"[Entity: {chunk['entity']}] [Document: {chunk['document']}]\n"
                f"{clean_text}"
            )
            parts.append(entry)
        parts.append("")

    if ungrouped:
        parts.append("=== OTHER EVIDENCE ===")
        for chunk in ungrouped:
            clean_text = _strip_sentence_markers(chunk['text'])
            entry = (
                f"[{chunk['idx']}] [Section: {chunk['section']}] "
                f"[Entity: {chunk['entity']}] [Document: {chunk['document']}]\n"
                f"{clean_text}"
            )
            parts.append(entry)
        parts.append("")

    return "\n\n".join(parts) if parts else ""


# ── Prompt builders ──

def _build_prompt_variant_a(query: str, context: str) -> str:
    """Variant A: Doc-grouped prompt (production baseline)."""
    return f"""You are an expert analyst generating a concise summary.

Question: {query}

Evidence Context (organized by entity relationships and document sections):
{context}

Instructions:
1. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence.
2. ONLY if the EXACT requested information IS present: provide a brief summary (2-3 paragraphs).
3. **RESPECT ALL QUALIFIERS** in the question.
4. Include citations [N] for factual claims (aim for every sentence that states a fact).
5. If the evidence contains explicit numeric values, include them verbatim.
6. Prefer concrete obligations/thresholds over general paraphrases.
7. Organize information by document sections where relevant.

## Summary

[Summary with citations [N] for every factual claim.]

## Key Points

- [Distinct item 1 with citation [N]]
- [Distinct item 2 with citation [N]]

Response:"""


def _build_prompt_variant_b(query: str, context: str) -> str:
    """Variant B: Community-grouped prompt (Step 5 candidate)."""
    return f"""You are an expert analyst generating a concise summary.

Question: {query}

Evidence Context (organized by thematic communities from a knowledge graph):
{context}

Instructions:
1. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence.
2. ONLY if the EXACT requested information IS present: provide a brief summary (2-3 paragraphs).
3. **RESPECT ALL QUALIFIERS** in the question.
4. Include citations [N] for factual claims (aim for every sentence that states a fact).
5. If the evidence contains explicit numeric values, include them verbatim.
6. Prefer concrete obligations/thresholds over general paraphrases.
7. Leverage the thematic community structure to explain connections across documents.

## Summary

[Summary with citations [N] for every factual claim.]

## Key Points

- [Distinct item 1 with citation [N]]
- [Distinct item 2 with citation [N]]

Response:"""


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


# ── Main ──

def main() -> int:
    ap = argparse.ArgumentParser(
        description="A/B test: doc-grouped vs community-grouped context for Route 3."
    )
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--group-id", default=_default_group_id())
    ap.add_argument("--question-bank", default=str(DEFAULT_QUESTION_BANK))
    ap.add_argument("--model", default="gpt-4.1", help="Synthesis model deployment")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--max-questions", type=int, default=0)
    ap.add_argument(
        "--questions-only", default="positive",
        choices=["positive", "negative", "all"],
    )
    ap.add_argument(
        "--from-context", type=str, default=None,
        help="Path to a previous benchmark JSON with saved contexts (skips Phase 1)",
    )
    ap.add_argument(
        "--communities-json", type=str, default=None,
        help="Path to a JSON file with communities (skips Neo4j query)",
    )
    args = ap.parse_args()

    base_url = str(args.url).rstrip("/")
    group_id = str(args.group_id)
    qbank = Path(str(args.question_bank)).expanduser().resolve()
    model = str(args.model)

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
        questions = questions[:args.max_questions]

    ground_truth = extract_ground_truth(qbank)

    stamp = _now_utc_stamp()
    out_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"route3_community_prompt_{stamp}.json"
    out_md = out_dir / f"route3_community_prompt_{stamp}.md"

    print("=" * 60)
    print("ROUTE 3 COMMUNITY PROMPT A/B TEST")
    print("=" * 60)
    print(f"  model:      {model}")
    print(f"  questions:  {len(questions)} ({args.questions_only})")
    print(f"  group_id:   {group_id}")
    if args.from_context:
        print(f"  from_ctx:   {args.from_context}")
    print("=" * 60, flush=True)

    # ──────────────────────────────────────────────────────────
    # Phase 1: Capture LLM context from API + communities from Neo4j
    # ──────────────────────────────────────────────────────────
    captured: Dict[str, Dict[str, Any]] = {}
    communities: List[Dict[str, Any]] = []

    if args.from_context:
        ctx_path = Path(args.from_context)
        print(f"\nPhase 1: Loading saved data from {ctx_path}...")
        saved = json.loads(ctx_path.read_text(encoding="utf-8"))
        captured = saved.get("captured_contexts", {})
        communities = saved.get("communities", [])
        print(f"  Loaded {len(captured)} contexts, {len(communities)} communities")
    else:
        # 1a: Fetch from API
        print(f"\nPhase 1a: Capturing context ({len(questions)} questions from API)...")
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
                url=endpoint, headers=api_headers,
                payload=payload, timeout_s=args.timeout,
            )
            retrieval_ms = int(round(elapsed_s * 1000))
            llm_context = None
            hub_entities = []
            context_stats = {}
            if isinstance(resp, dict):
                meta = resp.get("metadata") or {}
                llm_context = meta.get("llm_context")
                hub_entities = meta.get("hub_entities", [])
                context_stats = meta.get("context_stats", {})

            if llm_context:
                captured[q.qid] = {
                    "query": effective_query,
                    "llm_context": llm_context,
                    "retrieval_ms": retrieval_ms,
                    "hub_entities": hub_entities,
                    "context_stats": context_stats,
                }
                print(f"  [{qi}/{len(questions)}] {q.qid}: {len(llm_context):,} chars ({retrieval_ms}ms)", flush=True)
            else:
                print(f"  [{qi}/{len(questions)}] {q.qid}: ⚠ NO CONTEXT (status={status})", flush=True)

        # 1b: Fetch communities from Neo4j
        if args.communities_json:
            print(f"\nPhase 1b: Loading communities from {args.communities_json}")
            communities = json.loads(Path(args.communities_json).read_text(encoding="utf-8"))
        else:
            print(f"\nPhase 1b: Fetching communities from Neo4j for group '{group_id}'...")
            try:
                communities = _fetch_communities_from_neo4j(group_id)
                print(f"  ✓ {len(communities)} communities loaded")
                for c in communities:
                    print(f"    - {c['title']}: {len(c['entity_names'])} entities")
            except Exception as e:
                print(f"  ⚠ Neo4j fetch failed: {e}")
                print("  Falling back to community-free mode (only variant A will run)")

    if not captured:
        print("\nERROR: No context captured. Cannot proceed.")
        return 1

    # ──────────────────────────────────────────────────────────
    # Phase 2: Replay with both prompt variants
    # ──────────────────────────────────────────────────────────
    print(f"\nPhase 2: Replaying with model '{model}'...")
    aoai_endpoint = _get_aoai_endpoint()
    aoai_token = _get_aoai_token()
    print(f"  ✓ Azure OpenAI endpoint: {aoai_endpoint}")

    active_questions = [q for q in questions if q.qid in captured]
    variants = ["doc_grouped", "community_grouped"] if communities else ["doc_grouped"]
    total_calls = len(variants) * len(active_questions)
    call_num = 0

    results: Dict[str, Dict[str, Any]] = {v: {} for v in variants}

    for q in active_questions:
        ctx = captured[q.qid]
        llm_context = ctx["llm_context"]

        # Parse the context into sections + chunks
        entity_sec, rel_sec, header_line, chunks = _parse_chunks_from_context(llm_context)

        if not chunks:
            print(f"  ⚠ {q.qid}: Failed to parse chunks from context, skipping")
            continue

        # Build context variants
        context_a = llm_context  # Use captured context as-is (most faithful)
        context_b = _build_community_grouped_context(
            entity_sec, rel_sec, chunks, communities
        ) if communities else None

        variant_contexts = {"doc_grouped": context_a}
        if context_b:
            variant_contexts["community_grouped"] = context_b

        for variant_name, context in variant_contexts.items():
            call_num += 1

            # Build prompt
            if variant_name == "doc_grouped":
                prompt = _build_prompt_variant_a(ctx["query"], context)
            else:
                prompt = _build_prompt_variant_b(ctx["query"], context)

            # Call AOAI
            try:
                text, synth_ms = _call_aoai_direct(
                    endpoint=aoai_endpoint, token=aoai_token,
                    deployment=model, prompt=prompt,
                )
                status_code = 200
                error = None
            except Exception as e:
                text = ""
                synth_ms = 0
                status_code = 0
                error = str(e)

            # Theme coverage
            theme = {}
            if q.qid.startswith("Q-G") and q.qid in EXPECTED_TERMS:
                theme = calculate_theme_coverage(text, EXPECTED_TERMS[q.qid])

            # Accuracy
            accuracy = {}
            gt = ground_truth.get(q.qid)
            if gt and text:
                accuracy = calculate_accuracy_metrics(
                    expected=gt.expected, actual=text, is_negative=gt.is_negative,
                )

            # Token estimates
            context_tokens = _estimate_tokens(context)
            prompt_tokens = _estimate_tokens(prompt)

            # Chunk mapping stats (community variant only)
            mapping_stats = {}
            if variant_name == "community_grouped" and communities:
                entity_to_comm = {}
                for comm in communities:
                    for en in comm.get("entity_names", []):
                        entity_to_comm[en.lower()] = comm["title"]
                mapped = sum(1 for c in chunks if (c.get("entity") or "").lower() in entity_to_comm)
                mapping_stats = {
                    "chunks_total": len(chunks),
                    "chunks_mapped": mapped,
                    "chunks_ungrouped": len(chunks) - mapped,
                    "communities_used": len(set(
                        entity_to_comm[(c.get("entity") or "").lower()]
                        for c in chunks
                        if (c.get("entity") or "").lower() in entity_to_comm
                    )),
                }

            summary = {
                "qid": q.qid,
                "query": ctx["query"],
                "variant": variant_name,
                "model": model,
                "status": status_code,
                "synthesis_ms": synth_ms,
                "retrieval_ms": ctx["retrieval_ms"],
                "text": text,
                "text_length_chars": len(text),
                "text_length_words": _word_count(text),
                "context_tokens": context_tokens,
                "prompt_tokens": prompt_tokens,
                "theme_coverage": theme,
                "accuracy": accuracy,
                "mapping_stats": mapping_stats,
                "error": error,
            }
            results[variant_name][q.qid] = summary

            # Print progress
            tc = theme.get("coverage", -1)
            tc_str = f"theme={tc:.0%}" if tc >= 0 else ""
            cont = accuracy.get("containment", -1)
            cont_str = f"contain={cont:.2f}" if cont >= 0 else ""
            f1 = accuracy.get("f1", -1)
            f1_str = f"f1={f1:.3f}" if f1 >= 0 else ""
            neg_pass = accuracy.get("negative_test_pass", None)
            neg_str = "NEG_PASS" if neg_pass else ("NEG_FAIL" if neg_pass is False else "")
            metrics = " | ".join(s for s in [tc_str, cont_str, f1_str, neg_str] if s)

            label = "A_doc" if variant_name == "doc_grouped" else "B_comm"
            print(
                f"  [{call_num}/{total_calls}] {q.qid} {label:6s} | "
                f"synth={synth_ms:5d}ms | ctx_tok={context_tokens:6d} | {metrics}",
                flush=True,
            )

    # ──────────────────────────────────────────────────────────
    # Build comparison summary
    # ──────────────────────────────────────────────────────────
    comparison: Dict[str, Dict[str, Any]] = {}
    for variant in variants:
        vdata = results[variant]
        synth_times = [v["synthesis_ms"] for v in vdata.values() if v["synthesis_ms"] > 0]
        ctx_tokens = [v["context_tokens"] for v in vdata.values()]
        containments = [v["accuracy"].get("containment", 0) for v in vdata.values() if v["accuracy"]]
        f1s = [v["accuracy"].get("f1", 0) for v in vdata.values() if v["accuracy"]]
        coverages = [v["theme_coverage"].get("coverage", 0) for v in vdata.values() if v["theme_coverage"]]
        neg_results = [v["accuracy"].get("negative_test_pass") for v in vdata.values() if v["accuracy"].get("negative_test_pass") is not None]

        comparison[variant] = {
            "avg_synthesis_ms": int(sum(synth_times) / len(synth_times)) if synth_times else 0,
            "avg_context_tokens": int(sum(ctx_tokens) / len(ctx_tokens)) if ctx_tokens else 0,
            "avg_containment": round(sum(containments) / len(containments), 3) if containments else 0,
            "avg_f1": round(sum(f1s) / len(f1s), 3) if f1s else 0,
            "avg_theme_coverage": round(sum(coverages) / len(coverages), 3) if coverages else 0,
            "negative_pass": f"{sum(1 for x in neg_results if x)}/{len(neg_results)}" if neg_results else "n/a",
            "num_questions": len(vdata),
        }

    # ── Save JSON ──
    output = {
        "timestamp": stamp,
        "model": model,
        "group_id": group_id,
        "variants": variants,
        "comparison": comparison,
        "results": results,
        "captured_contexts": captured,
        "communities": communities,
    }
    out_json.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")

    # ── Print summary ──
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Variant':<22s} {'Synth(ms)':>10s} {'Ctx Tok':>10s} {'Contain':>10s} {'F1':>8s} {'Theme':>8s} {'Neg':>8s}")
    print("-" * 70)
    for variant in variants:
        c = comparison[variant]
        label = "A: Doc-grouped" if variant == "doc_grouped" else "B: Community-grouped"
        print(
            f"{label:<22s} {c['avg_synthesis_ms']:>10d} {c['avg_context_tokens']:>10d} "
            f"{c['avg_containment']:>10.3f} {c['avg_f1']:>8.3f} {c['avg_theme_coverage']:>7.0%} {c['negative_pass']:>8s}"
        )
    print("=" * 70)

    # ── Per-question delta ──
    if len(variants) == 2:
        print(f"\n{'QID':<8s} {'Contain_A':>10s} {'Contain_B':>10s} {'Delta':>8s} {'F1_A':>8s} {'F1_B':>8s} {'Tok_A':>8s} {'Tok_B':>8s}")
        print("-" * 70)
        deltas = []
        for q in active_questions:
            if q.qid not in results["doc_grouped"] or q.qid not in results["community_grouped"]:
                continue
            ra = results["doc_grouped"][q.qid]
            rb = results["community_grouped"][q.qid]
            ca = ra["accuracy"].get("containment", 0)
            cb = rb["accuracy"].get("containment", 0)
            fa = ra["accuracy"].get("f1", 0)
            fb = rb["accuracy"].get("f1", 0)
            delta = cb - ca
            deltas.append(delta)
            marker = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "→")
            print(
                f"{q.qid:<8s} {ca:>10.3f} {cb:>10.3f} {delta:>+7.3f}{marker} "
                f"{fa:>8.3f} {fb:>8.3f} {ra['context_tokens']:>8d} {rb['context_tokens']:>8d}"
            )
        if deltas:
            avg_delta = sum(deltas) / len(deltas)
            wins = sum(1 for d in deltas if d > 0.01)
            losses = sum(1 for d in deltas if d < -0.01)
            ties = len(deltas) - wins - losses
            print(f"\n  Avg delta: {avg_delta:+.3f} | Wins: {wins} | Losses: {losses} | Ties: {ties}")

    # ── Write MD report ──
    md_lines = [
        f"# Route 3 Community Prompt A/B Test",
        f"",
        f"**Date**: {stamp}",
        f"**Model**: {model}",
        f"**Group**: {group_id}",
        f"**Questions**: {len(active_questions)}",
        f"**Communities**: {len(communities)}",
        f"",
        f"## Summary",
        f"",
        f"| Variant | Synth (ms) | Ctx Tokens | Containment | F1 | Theme | Neg |",
        f"|---------|-----------|-----------|-------------|------|-------|-----|",
    ]
    for variant in variants:
        c = comparison[variant]
        label = "A: Doc-grouped" if variant == "doc_grouped" else "B: Community-grouped"
        md_lines.append(
            f"| {label} | {c['avg_synthesis_ms']} | {c['avg_context_tokens']} | "
            f"{c['avg_containment']:.3f} | {c['avg_f1']:.3f} | {c['avg_theme_coverage']:.0%} | {c['negative_pass']} |"
        )

    if len(variants) == 2:
        md_lines += [
            f"",
            f"## Per-Question Comparison",
            f"",
            f"| QID | Contain A | Contain B | Delta | F1 A | F1 B | Tok A | Tok B |",
            f"|-----|-----------|-----------|-------|------|------|-------|-------|",
        ]
        for q in active_questions:
            if q.qid not in results["doc_grouped"] or q.qid not in results["community_grouped"]:
                continue
            ra = results["doc_grouped"][q.qid]
            rb = results["community_grouped"][q.qid]
            ca = ra["accuracy"].get("containment", 0)
            cb = rb["accuracy"].get("containment", 0)
            fa = ra["accuracy"].get("f1", 0)
            fb = rb["accuracy"].get("f1", 0)
            md_lines.append(
                f"| {q.qid} | {ca:.3f} | {cb:.3f} | {cb-ca:+.3f} | "
                f"{fa:.3f} | {fb:.3f} | {ra['context_tokens']} | {rb['context_tokens']} |"
            )

    out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"\n  JSON: {out_json}")
    print(f"  MD:   {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
