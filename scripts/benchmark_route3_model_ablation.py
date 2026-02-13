#!/usr/bin/env python3
"""Route 3 Model & Prompt Ablation Test.

Tests 4 LLM models on Route 3's MAP and REDUCE steps using identical
evidence context.  The goal is to measure whether the current gpt-5.1
can be improved or replaced by a faster/cheaper model.

Methodology:
  Phase 1 — Capture evidence.
    One API call per question captures community claims + sentence evidence
    from the deployed gpt-5.1 pipeline.  This ensures all models see the
    EXACT same retrieval context.

  Phase 2 — Replay MAP with each model.
    Each model runs the MAP prompt on the same community summaries.

  Phase 3 — Replay REDUCE with each model.
    Each model runs the REDUCE prompt using the gpt-5.1 baseline claims
    (to isolate the REDUCE variable) AND using its own MAP claims.

Models tested:
  - gpt-5.1      (current production — high quality, highest cost)
  - gpt-4.1      (strong reasoning, moderate cost)
  - gpt-4.1-mini (fast, cheap, good for structured extraction)
  - gpt-5-nano   (fastest, cheapest, lightweight)

Usage:
    python scripts/benchmark_route3_model_ablation.py
    python scripts/benchmark_route3_model_ablation.py --questions 3
    python scripts/benchmark_route3_model_ablation.py --models gpt-4.1,gpt-5-nano
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import re
import sys
import time
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

ALL_MODELS = ["gpt-5.1", "gpt-4.1", "gpt-4.1-mini", "gpt-5-nano"]

GROUP_ID = os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")
NEO4J_URI = os.environ.get("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "")

# Community matching: matches production ROUTE3_COMMUNITY_TOP_K default
COMMUNITY_TOP_K = int(os.getenv("ABLATION_COMMUNITY_TOP_K", "10"))

# Max parallel MAP calls (matches production asyncio.gather behaviour)
MAP_PARALLEL_WORKERS = int(os.getenv("ABLATION_MAP_WORKERS", "5"))
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")


# ─── Prompts (identical to route_3_prompts.py) ─────────────────
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
You are an analytical assistant performing the REDUCE phase of a global search.

**Task**: Synthesize TWO sources of evidence into a coherent {response_type}
that comprehensively answers the user's query.

**Query**: {query}

---

**SOURCE 1 — Community Claims** (extracted from knowledge graph community summaries):
{community_claims}

---

**SOURCE 2 — Direct Sentence Evidence** (retrieved from source documents via semantic search):
{sentence_evidence}

---

**Instructions**:
1. Use BOTH sources to build the most complete answer possible.
2. Community claims provide thematic structure — use them to organize topics.
3. Sentence evidence provides direct factual content from source documents.
   If a fact appears in sentence evidence but NOT in community claims,
   you MUST still include it in your response.
4. Organize thematically — group related facts together under clear headings
   or logical sections.
5. Preserve specific details: entity names, amounts, dates, percentages,
   conditions, section references.
6. If sources provide different levels of detail on the same topic, use
   the more specific/detailed version.
7. Note cross-document patterns and differences when applicable.
8. If BOTH sources are empty, respond with:
   "The requested information was not found in the available documents."
9. Do NOT add information beyond what the evidence states.
10. Do NOT mention or reference the two-source methodology in your response.
    Write as if all information comes from a single comprehensive analysis.

**Response Type**: {response_type}
- "summary": Concise overview (3-5 paragraphs)
- "detailed_report": Comprehensive structured report with headings
- "bullet_points": Organized bullet-point list
- Otherwise: Adapt to the requested format

**Response**:
"""

# Alternative REDUCE prompt — more concise
REDUCE_PROMPT_CONCISE = """\
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


# ─── Questions (same as benchmark) ──────────────────────────────
QUESTIONS = [
    {
        "id": "T-1",
        "query": "What are the common themes across all the contracts and agreements in these documents?",
        "expected_themes": ["legal obligations", "payment terms", "termination clauses", "liability provisions", "dispute resolution"],
    },
    {
        "id": "T-2",
        "query": "How do the different parties relate to each other across the documents?",
        "expected_themes": ["contractual relationships", "service providers", "clients", "third parties"],
    },
    {
        "id": "T-3",
        "query": "What patterns emerge in the financial terms and payment structures?",
        "expected_themes": ["payment schedules", "amounts", "invoicing"],
    },
    {
        "id": "T-4",
        "query": "Summarize the risk management and liability provisions across all documents.",
        "expected_themes": ["indemnification", "limitation of liability", "insurance requirements", "warranties"],
    },
    {
        "id": "T-5",
        "query": "What dispute resolution mechanisms are mentioned across the agreements?",
        "expected_themes": ["arbitration", "jurisdiction", "governing law"],
    },
    {
        "id": "T-6",
        "query": "How do the documents address confidentiality and data protection?",
        "expected_themes": ["NDA provisions", "data handling", "privacy", "disclosure limitations"],
    },
    {
        "id": "T-7",
        "query": "What are the key obligations and responsibilities outlined for each party?",
        "expected_themes": ["warranty obligations", "dispute resolution", "service responsibilities", "cost obligations"],
    },
    {
        "id": "T-8",
        "query": "Compare the termination and cancellation provisions across the documents.",
        "expected_themes": ["notice periods", "grounds for termination", "effects of termination", "survival clauses"],
    },
    {
        "id": "T-9",
        "query": "What insurance and indemnification requirements appear in the documents?",
        "expected_themes": ["coverage types", "minimum amounts", "certificate requirements", "named insureds"],
    },
    {
        "id": "T-10",
        "query": "Identify the key dates, deadlines, and time-sensitive provisions across all documents.",
        "expected_themes": ["effective dates", "expiration", "renewal", "notice periods", "response times"],
    },
]


# ─── Theme evaluation (same as benchmark) ──────────────────────
THEME_SYNONYMS: Dict[str, List[str]] = {
    "clients": ["client", "customer", "tenant", "lessee", "occupant", "buyer", "owner"],
    "indemnification": ["indemnif", "indemnit", "hold harmless", "defend and indemnify"],
    "privacy": ["privacy", "personal data", "data protection", "confidential information"],
    "expiration": ["expir", "expire", "end date", "expiry", "lapse",
                    "terminat", "one year", "twelve month", "warranty period"],
    "response times": ["response time", "business day", "calendar day", "within.*day",
                        "timeframe", "time frame", "turnaround"],
    "invoicing": ["invoic", "billing", "bill", "payment request"],
    "amounts": ["$", "fee", "rate", "cost", "price", "compensation", "amount"],
    "governing law": ["substantive law", "state of idaho", "governed by", "applicable law",
                       "governing law"],
    "renewal": ["renew", "auto-renew", "automatic renewal", "extend", "extension"],
}


def _simple_stem(word: str) -> str:
    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    if word.endswith('es') and len(word) > 4:
        return word[:-2]
    if word.endswith('s') and not word.endswith('ss') and len(word) > 4:
        return word[:-1]
    if word.endswith('ing') and len(word) > 5:
        return word[:-3]
    if word.endswith('ed') and len(word) > 4:
        return word[:-2]
    if word.endswith('tion') and len(word) > 6:
        return word[:-4]
    return word


def _theme_in_text(theme: str, text: str) -> bool:
    theme_lower = theme.lower()
    text_lower = text.lower()
    if theme_lower in text_lower:
        return True
    for syn in THEME_SYNONYMS.get(theme_lower, []):
        if syn in text_lower:
            return True
    significant_words = [w for w in theme_lower.split() if len(w) >= 4]
    if significant_words:
        hits = sum(1 for w in significant_words
                   if w in text_lower or (_simple_stem(w) in text_lower and len(_simple_stem(w)) >= 4))
        if hits >= max(1, len(significant_words) * 0.5):
            return True
    return False


def check_theme_coverage(response: str, expected_themes: List[str]) -> Tuple[float, Dict[str, bool]]:
    per_theme: Dict[str, bool] = {}
    for theme in expected_themes:
        per_theme[theme] = _theme_in_text(theme, response)
    found = sum(1 for v in per_theme.values() if v)
    return (found / len(expected_themes) if expected_themes else 0.0, per_theme)


def _parse_numbered_list(text: str) -> List[str]:
    """Parse a numbered list from LLM output."""
    lines = text.strip().split("\n")
    claims = []
    current = ""
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\d+[\.\)]\s+", stripped):
            if current:
                claims.append(current.strip())
            current = re.sub(r"^\d+[\.\)]\s+", "", stripped)
        elif current and stripped:
            current += " " + stripped
    if current:
        claims.append(current.strip())
    return claims


# ─── Neo4j: fetch community data ──────────────────────────────
def get_communities() -> List[Dict[str, Any]]:
    """Fetch community summaries from Neo4j."""
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
    print(f"  Loaded {len(communities)} communities from Neo4j")
    return communities


# ─── Neo4j: sentence vector search via Voyage ──────────────────
def get_sentence_evidence(query: str, top_k: int = 30, threshold: float = 0.2) -> List[Dict[str, Any]]:
    """Embed query with Voyage and search sentence_embeddings_v2 index."""
    import voyageai
    from neo4j import GraphDatabase

    vc = voyageai.Client(api_key=VOYAGE_API_KEY)
    # voyage-context-3 requires contextualized_embed, not embed
    # Returns ContextualizedEmbeddingsObject with .results[0].embeddings[0]
    resp = vc.contextualized_embed(
        inputs=[[query]],  # Single document with single chunk
        model="voyage-context-3",
        input_type="query",
        output_dimension=2048,
    )
    query_embedding = resp.results[0].embeddings[0]

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
                "text": r["text"],
                "sentence_id": r["sentence_id"],
                "document_title": r["document_title"],
                "score": r["score"],
            })
    driver.close()
    return sentences


# ─── Community matching (mirrors production CommunityMatcher) ──
def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def match_communities(
    query: str,
    communities: List[Dict[str, Any]],
    top_k: int = COMMUNITY_TOP_K,
) -> List[Dict[str, Any]]:
    """Match query to top-k communities using embedding similarity.

    Mirrors production behaviour in CommunityMatcher._semantic_match():
    embeds query, computes cosine similarity against community embeddings
    stored in Neo4j, returns top-k communities.

    Falls back to ALL communities if embeddings are unavailable (backwards
    compatible with pre-embedding test groups).
    """
    from neo4j import GraphDatabase

    # Fetch community embeddings from Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    embeddings: Dict[str, List[float]] = {}
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

    if not embeddings:
        print(f"  ⚠ No community embeddings found — using all {len(communities)} communities")
        return communities

    # Embed query with Voyage voyage-context-3 (same model+dims as community embeddings)
    import voyageai
    vc = voyageai.Client(api_key=VOYAGE_API_KEY)
    resp = vc.contextualized_embed(
        inputs=[[query]],  # Single document with single chunk
        model="voyage-context-3",
        input_type="query",
        output_dimension=2048,
    )
    query_embedding = resp.results[0].embeddings[0]

    # Score and rank
    scored: List[Tuple[Dict[str, Any], float]] = []
    for community in communities:
        title = community.get("title", "")
        emb = embeddings.get(title)
        if emb:
            if len(query_embedding) != len(emb):
                continue  # Skip dimension mismatches
            sim = _cosine_similarity(query_embedding, emb)
            scored.append((community, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    matched = [c for c, s in scored[:top_k] if s >= 0.05]

    if not matched:
        print(f"  ⚠ All community scores < 0.05 — using all {len(communities)} communities")
        return communities

    print(f"  Matched top-{len(matched)} communities (scores: "
          f"{', '.join(f'{s:.3f}' for _, s in scored[:min(5, len(scored))])})")
    return matched


# ─── LLM call ──────────────────────────────────────────────────
def call_llm(model: str, prompt: str) -> Tuple[str, int]:
    """Call Azure OpenAI and return (response_text, latency_ms)."""
    client = AzureOpenAI(
        api_key=API_KEY,
        api_version=API_VERSION,
        azure_endpoint=ENDPOINT,
    )
    t0 = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        text = resp.choices[0].message.content or ""
        elapsed = int((time.monotonic() - t0) * 1000)
        return (text.strip(), elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return (f"ERROR: {type(e).__name__}: {str(e)[:200]}", elapsed)


# ─── MAP phase (parallel — matches production asyncio.gather) ──
def _map_one_community(model: str, query: str, community: Dict, max_claims: int) -> Tuple[str, List[str], int]:
    """MAP a single community. Returns (title, claims, latency_ms)."""
    title = community.get("title", "Untitled")
    summary = community.get("summary", "")
    entity_names = ", ".join(community.get("entity_names", [])[:20])
    if not summary.strip():
        return (title, [], 0)
    prompt = MAP_PROMPT.format(
        query=query,
        community_title=title,
        community_summary=summary,
        entity_names=entity_names or "N/A",
        max_claims=max_claims,
    )
    text, ms = call_llm(model, prompt)
    if "NO RELEVANT CLAIMS" in text.upper():
        return (title, [], ms)
    claims = _parse_numbered_list(text)[:max_claims]
    return (title, claims, ms)


def run_map(model: str, query: str, communities: List[Dict], max_claims: int = 10) -> Tuple[List[str], int]:
    """Run MAP on communities in parallel using ThreadPoolExecutor.

    Mirrors production: asyncio.gather over all matched communities.
    Returns (all_claims, wall_clock_ms).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_claims: List[str] = []
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=MAP_PARALLEL_WORKERS) as executor:
        futures = {
            executor.submit(_map_one_community, model, query, c, max_claims): c
            for c in communities
        }
        for future in as_completed(futures):
            title, claims, _ = future.result()
            for claim in claims:
                all_claims.append(f"[Community: {title}] {claim}")

    wall_ms = int((time.monotonic() - t0) * 1000)
    return (all_claims, wall_ms)


# ─── REDUCE phase ──────────────────────────────────────────────
def run_reduce(
    model: str,
    query: str,
    claims: List[str],
    sentences: List[Dict],
    prompt_template: str = "default",
) -> Tuple[str, int]:
    """Run REDUCE with the given model. Returns (response, latency_ms)."""
    if claims:
        claims_text = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1))
    else:
        claims_text = "(No community claims extracted)"

    if sentences:
        evidence_lines = []
        for i, ev in enumerate(sentences, 1):
            doc = ev.get("document_title", "Unknown")
            score = ev.get("score", 0)
            text = ev.get("text", "")
            evidence_lines.append(f"{i}. [Source: {doc}, relevance: {score:.2f}] {text}")
        evidence_text = "\n".join(evidence_lines)
    else:
        evidence_text = "(No direct sentence evidence retrieved)"

    template = REDUCE_PROMPT_CONCISE if prompt_template == "concise" else REDUCE_PROMPT
    prompt = template.format(
        query=query,
        response_type="summary",
        community_claims=claims_text,
        sentence_evidence=evidence_text,
    )

    return call_llm(model, prompt)


# ─── Main experiment ──────────────────────────────────────────
def run_ablation(
    models: List[str],
    num_questions: int = 10,
    prompt_variants: List[str] = ["default", "concise"],
):
    """Run full model x prompt ablation."""
    print("=" * 78)
    print("  ROUTE 3 MODEL & PROMPT ABLATION TEST")
    print("=" * 78)
    print(f"  Models:    {', '.join(models)}")
    print(f"  Prompts:   {', '.join(prompt_variants)}")
    print(f"  Questions: {num_questions}/{len(QUESTIONS)}")
    print(f"  Group:     {GROUP_ID}")
    print(f"  Comm TopK: {COMMUNITY_TOP_K}")
    print(f"  MAP Workers: {MAP_PARALLEL_WORKERS}")
    print("=" * 78)

    # Phase 0: Load ALL communities (then match per-query like production)
    print("\n--- Phase 0: Load communities from Neo4j ---")
    all_communities = get_communities()

    questions = QUESTIONS[:num_questions]
    results: Dict[str, List[Dict]] = {}  # key = "model|prompt"

    for qi, q in enumerate(questions, 1):
        qid = q["id"]
        query = q["query"]
        print(f"\n{'='*78}")
        print(f"  [{qi}/{len(questions)}] {qid}: {query[:65]}")
        print(f"{'='*78}")

        # Phase 0.5: Community matching (mirrors production top-k)
        print(f"  Matching communities (top-{COMMUNITY_TOP_K})...")
        matched = match_communities(query, all_communities, top_k=COMMUNITY_TOP_K)

        # Phase 1: Sentence evidence (shared across all models)
        print("  Fetching sentence evidence...")
        t0 = time.monotonic()
        sentences = get_sentence_evidence(query)
        sent_ms = int((time.monotonic() - t0) * 1000)
        print(f"  Got {len(sentences)} sentences ({sent_ms}ms)")

        for model in models:
            # Phase 2: MAP with this model (parallel, top-k communities)
            print(f"\n  [{model}] MAP ({len(matched)} communities, parallel)...")
            claims, map_ms = run_map(model, query, matched)
            print(f"  [{model}] MAP: {len(claims)} claims in {map_ms}ms")

            for prompt_variant in prompt_variants:
                key = f"{model}|{prompt_variant}"
                if key not in results:
                    results[key] = []

                # Phase 3: REDUCE with this model + prompt
                print(f"  [{model}|{prompt_variant}] REDUCE...")
                response, reduce_ms = run_reduce(
                    model, query, claims, sentences, prompt_variant,
                )

                # Evaluate
                is_error = response.startswith("ERROR:")
                if is_error:
                    theme_cov = 0.0
                    theme_details = {}
                    word_count = 0
                    char_count = len(response)
                else:
                    theme_cov, theme_details = check_theme_coverage(response, q["expected_themes"])
                    word_count = len(response.split())
                    char_count = len(response)

                total_ms = map_ms + reduce_ms + sent_ms  # approximate
                print(f"  [{model}|{prompt_variant}] REDUCE: {char_count} chars, {word_count} words, "
                      f"{reduce_ms}ms, themes={theme_cov:.0%}")

                # Show missed themes
                for t_name, t_hit in theme_details.items():
                    if not t_hit:
                        print(f"    MISS: {t_name}")

                results[key].append({
                    "question_id": qid,
                    "query": query,
                    "model": model,
                    "prompt_variant": prompt_variant,
                    "response": response,
                    "is_error": is_error,
                    "map_claims": len(claims),
                    "map_ms": map_ms,
                    "reduce_ms": reduce_ms,
                    "sentence_ms": sent_ms,
                    "total_ms": total_ms,
                    "theme_coverage": theme_cov,
                    "theme_details": theme_details,
                    "word_count": word_count,
                    "char_count": char_count,
                    "sentence_count": len(sentences),
                    "matched_communities": len(matched),
                })

    # ─── Summary ─────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("  ABLATION RESULTS SUMMARY")
    print("=" * 78)
    print(f"\n  {'Variant':<28} {'Coverage':>8} {'Words':>7} {'Chars':>7} "
          f"{'MAP ms':>7} {'RED ms':>7} {'Claims':>7}")
    print(f"  {'-'*26}  {'-'*6}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}")

    summary_rows = []
    for key in sorted(results.keys()):
        rows = results[key]
        valid = [r for r in rows if not r["is_error"]]
        if not valid:
            print(f"  {key:<28} {'ERROR':>8}")
            continue
        avg_cov = sum(r["theme_coverage"] for r in valid) / len(valid)
        avg_words = sum(r["word_count"] for r in valid) / len(valid)
        avg_chars = sum(r["char_count"] for r in valid) / len(valid)
        avg_map_ms = sum(r["map_ms"] for r in valid) / len(valid)
        avg_red_ms = sum(r["reduce_ms"] for r in valid) / len(valid)
        avg_claims = sum(r["map_claims"] for r in valid) / len(valid)
        perfect = sum(1 for r in valid if r["theme_coverage"] >= 1.0)

        print(f"  {key:<28} {avg_cov:>7.1%} {avg_words:>7.0f} {avg_chars:>7.0f} "
              f"{avg_map_ms:>7.0f} {avg_red_ms:>7.0f} {avg_claims:>7.1f}")

        summary_rows.append({
            "variant": key,
            "avg_theme_coverage": round(avg_cov, 4),
            "perfect_questions": perfect,
            "total_questions": len(valid),
            "avg_word_count": round(avg_words),
            "avg_char_count": round(avg_chars),
            "avg_map_ms": round(avg_map_ms),
            "avg_reduce_ms": round(avg_red_ms),
            "avg_claims": round(avg_claims, 1),
        })

    # ─── Save ────────────────────────────────────────────────────
    ts = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = PROJECT_ROOT / f"benchmark_route3_ablation_{ts}.json"
    with open(output_path, "w") as f:
        json.dump({
            "benchmark_type": "route3_model_prompt_ablation",
            "timestamp": ts,
            "group_id": GROUP_ID,
            "models": models,
            "prompt_variants": prompt_variants,
            "num_questions": num_questions,
            "community_top_k": COMMUNITY_TOP_K,
            "map_parallel_workers": MAP_PARALLEL_WORKERS,
            "summary": summary_rows,
            "results": {k: v for k, v in results.items()},
        }, f, indent=2)
    print(f"\n  Results saved to: {output_path}")
    print("=" * 78)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Route 3 model & prompt ablation")
    parser.add_argument("--models", default=",".join(ALL_MODELS),
                        help="Comma-separated model names")
    parser.add_argument("--questions", type=int, default=10,
                        help="Number of questions to test (1-10)")
    parser.add_argument("--prompts", default="default,concise",
                        help="Comma-separated prompt variants")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",")]
    prompts = [p.strip() for p in args.prompts.split(",")]
    run_ablation(models, args.questions, prompts)
