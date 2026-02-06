#!/usr/bin/env python3
"""
Test synthesis prompt variants for Route 4 output conciseness.

This script:
1. Calls the live API to get evidence for a query (Route 4 pipeline runs normally)
2. Extracts the evidence context
3. Tests multiple prompt variants against the SAME evidence
4. Compares output length, latency, and quality

Usage:
  python3 scripts/test_synthesis_prompt_variants.py
  python3 scripts/test_synthesis_prompt_variants.py --query "Compare time windows..."
  python3 scripts/test_synthesis_prompt_variants.py --query-id Q-D5
"""

import argparse
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)
DEFAULT_GROUP_ID = (
    Path(__file__).resolve().parents[1] / "last_test_group_id.txt"
)

AZURE_OPENAI_ENDPOINT = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    "https://graphrag-openai-8476.openai.azure.com",
)
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
SYNTHESIS_MODEL = os.getenv("HYBRID_SYNTHESIS_MODEL", "gpt-5.1")

# ---------------------------------------------------------------------------
# Test queries (from question bank)
# ---------------------------------------------------------------------------
TEST_QUERIES = {
    "Q-D3": 'Compare "time windows" across the set: list all explicit day-based timeframes.',
    "Q-D5": "In the warranty, explain how the \"coverage start\" is defined and what must happen before coverage ends.",
    "Q-D9": 'Compare the "fees" concepts: which doc has a percentage-based fee, which has a flat fee, and which has a deposit?',
    "Q-D10": 'List the three different "risk allocation" statements and explain how each shifts liability.',
    "Q-DR1": "Identify the vendor responsible for the vertical platform lift maintenance. Does their invoice's payment schedule match the terms in the original Purchase Agreement?",
    "Q-DR5": 'Compare the strictness of the "financial penalties" for early termination in the Property Management Agreement versus the Holding Tank Servicing Contract.',
}


# ---------------------------------------------------------------------------
# Prompt variants to test
# ---------------------------------------------------------------------------
def get_prompt_variants(query: str, context: str, sub_questions: List[str]) -> Dict[str, str]:
    """Return dict of {variant_name: prompt_text}."""
    sub_q_list = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(sub_questions))

    variants = {}

    # --- V0: Current production prompt (old verbose version) ---
    variants["v0_current"] = f"""You are analyzing a complex query that was decomposed into multiple sub-questions.

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

    # --- V1: Query-focused, concise ---
    variants["v1_concise"] = f"""You are synthesizing evidence gathered from multiple sub-questions to answer a user query.

Original Query: {query}

Sub-questions explored:
{sub_q_list}

Evidence Context (with citation markers):
{context}

Instructions:
1. Answer the ORIGINAL QUERY — not each sub-question individually
2. Only include findings that are directly relevant to what was asked
3. Every factual claim must include a citation [n]
4. If a sub-question produced no useful evidence for the original query, skip it

Provide a concise response (2-3 paragraphs maximum) that:
- Directly answers the original query first
- Focuses ONLY on information explicitly requested — omit tangential findings
- Includes citations [n] for key claims
- Does NOT use section headers or bullet-point expansions unless the query asks for a list

Your response:"""

    # --- V2: Task-adaptive (let the LLM infer the right format) ---
    variants["v2_adaptive"] = f"""Answer the following query using the evidence provided. The evidence was gathered by decomposing the query into sub-questions and tracing relevant documents.

Query: {query}

Evidence (with citation markers [n]):
{context}

Rules:
- Cite every factual claim with [n]
- Be direct and concise — answer what was asked, nothing more
- If the query asks to compare: show the comparison clearly
- If the query asks to list: use a compact list
- If the query asks to explain: give a focused explanation
- Skip evidence that doesn't help answer the query

Your response:"""

    # --- V3: Minimal instruction ---
    variants["v3_minimal"] = f"""Query: {query}

Evidence (citations marked [n]):
{context}

Answer the query using only the evidence above. Cite sources with [n]. Be concise.

Your response:"""

    return variants


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def _get_group_id() -> str:
    try:
        return DEFAULT_GROUP_ID.read_text().strip()
    except Exception:
        return os.getenv("TEST_GROUP_ID", "test-5pdfs-v2-fix2")


def call_api(url: str, query: str, group_id: str, response_type: str = "summary") -> Dict[str, Any]:
    """Call the hybrid query API and return full response."""
    payload = json.dumps({
        "query": query,
        "group_id": group_id,
        "force_route": "drift_multi_hop",
        "response_type": response_type,
    }).encode()

    req = urllib.request.Request(
        f"{url}/hybrid/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode())
    elapsed = time.time() - t0
    data["_latency"] = elapsed
    return data


def call_llm_direct(prompt: str) -> tuple[str, float]:
    """Call Azure OpenAI directly with a prompt. Returns (response_text, latency)."""
    if not AZURE_OPENAI_KEY:
        raise RuntimeError(
            "AZURE_OPENAI_API_KEY not set. Export it or set in environment."
        )

    url = (
        f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{SYNTHESIS_MODEL}"
        f"/chat/completions?api-version=2024-10-21"
    )
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 4096,
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "api-key": AZURE_OPENAI_KEY,
        },
        method="POST",
    )

    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    elapsed = time.time() - t0

    text = data["choices"][0]["message"]["content"].strip()
    return text, elapsed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Test synthesis prompt variants")
    parser.add_argument("--url", default=DEFAULT_URL, help="API base URL")
    parser.add_argument("--group-id", default=None, help="Group ID override")
    parser.add_argument("--query", default=None, help="Custom query text")
    parser.add_argument("--query-id", default="Q-D5", help="Question bank ID (default: Q-D5)")
    parser.add_argument("--variants", default="all", help="Comma-separated variant names or 'all'")
    parser.add_argument("--skip-api", action="store_true", help="Skip API call, use cached evidence")
    parser.add_argument("--evidence-file", default=None, help="Path to cached evidence JSON")
    args = parser.parse_args()

    group_id = args.group_id or _get_group_id()
    query = args.query or TEST_QUERIES.get(args.query_id, TEST_QUERIES["Q-D5"])

    print("=" * 70)
    print("ROUTE 4 SYNTHESIS PROMPT VARIANT TEST")
    print("=" * 70)
    print(f"Query:    {query[:80]}...")
    print(f"Group:    {group_id}")
    print(f"Model:    {SYNTHESIS_MODEL}")
    print(f"Endpoint: {AZURE_OPENAI_ENDPOINT}")
    print()

    # ---------------------------------------------------------------
    # Step 1: Get evidence via API (the full Route 4 pipeline runs)
    # ---------------------------------------------------------------
    evidence_data = None
    if args.skip_api and args.evidence_file:
        print(f"Loading cached evidence from {args.evidence_file}...")
        with open(args.evidence_file) as f:
            evidence_data = json.load(f)
    else:
        print(f"Calling API for Route 4 evidence retrieval...")
        print(f"  URL: {args.url}")
        try:
            evidence_data = call_api(args.url, query, group_id, response_type="summary")
            print(f"  API latency: {evidence_data['_latency']:.1f}s")
            print(f"  Route used: {evidence_data.get('route_used', '?')}")
            print(f"  Current response length: {len(evidence_data.get('response', ''))} chars")
            print(f"  Citations: {len(evidence_data.get('citations', []))}")

            # Save evidence for reuse
            cache_path = f"bench_prompt_test_evidence_{args.query_id}.json"
            with open(cache_path, "w") as f:
                json.dump(evidence_data, f, indent=2)
            print(f"  Evidence cached to: {cache_path}")
        except Exception as e:
            print(f"  ERROR: {e}")
            return

    if not evidence_data:
        print("No evidence data available. Exiting.")
        return

    # ---------------------------------------------------------------
    # Step 2: Build evidence context from citations
    # ---------------------------------------------------------------
    # Reconstruct evidence context from what the API returned
    citations = evidence_data.get("citations", [])
    metadata = evidence_data.get("metadata", {})
    sub_questions = metadata.get("sub_questions", [])

    # Build context from citation text previews (approximation)
    context_parts = []
    for c in citations:
        idx = c.get("index", 0)
        doc = c.get("document_title", "Unknown")
        preview = c.get("text_preview", "")
        section = c.get("section_path", "")
        context_parts.append(f"=== DOCUMENT: {doc} ===")
        context_parts.append(f"[{idx}] {preview}")

    # Also include evidence_path info
    evidence_path = evidence_data.get("evidence_path", [])

    context = "\n".join(context_parts) if context_parts else "No citation text available."

    if not sub_questions:
        sub_questions = ["(sub-questions not available in API response)"]

    print(f"\n  Sub-questions: {len(sub_questions)}")
    for i, sq in enumerate(sub_questions):
        print(f"    {i+1}. {sq[:80]}...")
    print(f"  Context size: {len(context)} chars")
    print(f"  Evidence nodes: {len(evidence_path)}")

    # ---------------------------------------------------------------
    # Step 3: Test each prompt variant
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("TESTING PROMPT VARIANTS")
    print("=" * 70)

    # Current response as baseline
    current_response = evidence_data.get("response", "")
    print(f"\n--- BASELINE (current API response) ---")
    print(f"  Length: {len(current_response)} chars")
    print(f"  Preview: {current_response[:200]}...")
    print()

    variants = get_prompt_variants(query, context, sub_questions)

    # Filter variants if specified
    if args.variants != "all":
        selected = set(args.variants.split(","))
        variants = {k: v for k, v in variants.items() if k in selected}

    if not AZURE_OPENAI_KEY:
        print("⚠  AZURE_OPENAI_API_KEY not set — printing prompts only (no LLM calls)")
        print()
        for name, prompt in variants.items():
            print(f"--- {name} ---")
            print(f"  Prompt length: {len(prompt)} chars")
            print(f"  Prompt preview:\n{prompt[:300]}...")
            print()
        return

    results = {}
    for name, prompt in variants.items():
        print(f"\n--- {name} ---")
        print(f"  Prompt length: {len(prompt)} chars")
        try:
            response_text, latency = call_llm_direct(prompt)
            results[name] = {
                "response": response_text,
                "length": len(response_text),
                "latency": latency,
                "prompt_length": len(prompt),
            }
            print(f"  Response length: {len(response_text)} chars")
            print(f"  LLM latency: {latency:.1f}s")
            print(f"  Preview: {response_text[:200]}...")
        except Exception as e:
            print(f"  ERROR: {e}")
            results[name] = {"error": str(e)}

        # Avoid rate limiting
        time.sleep(1)

    # ---------------------------------------------------------------
    # Step 4: Summary comparison
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    print(f"\n{'Variant':<20} | {'Chars':>6} | {'LLM(s)':>6} | {'vs Baseline':>12} | Preview")
    print("-" * 90)
    print(f"{'baseline':20s} | {len(current_response):>6d} | {'N/A':>6s} | {'—':>12s} | {current_response[:40]}...")

    for name, r in results.items():
        if "error" in r:
            print(f"{name:20s} | {'ERR':>6s} | {'ERR':>6s} | {'ERR':>12s} | {r['error'][:40]}")
        else:
            pct = (r["length"] / len(current_response) * 100) if current_response else 0
            print(f"{name:20s} | {r['length']:>6d} | {r['latency']:>6.1f} | {pct:>10.0f}% | {r['response'][:40]}...")

    # Save full results
    out_path = f"bench_prompt_variants_{args.query_id}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump({
            "query": query,
            "query_id": args.query_id,
            "group_id": group_id,
            "baseline_length": len(current_response),
            "sub_questions": sub_questions,
            "context_length": len(context),
            "variants": {
                name: {
                    "length": r.get("length", 0),
                    "latency": r.get("latency", 0),
                    "response": r.get("response", ""),
                    "error": r.get("error"),
                }
                for name, r in results.items()
            },
        }, f, indent=2)
    print(f"\nFull results saved to: {out_path}")


if __name__ == "__main__":
    main()
