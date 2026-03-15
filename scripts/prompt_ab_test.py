#!/usr/bin/env python3
"""Prompt variant A/B test for v3_keypoints synthesis.

Reconstructs the exact context from experiment #4 benchmark data and tests
multiple prompt variants against GPT-4.1 to find the optimal balance of
precision and completeness for community-dominant questions.

Usage:
    python scripts/prompt_ab_test.py [--variants v3_keypoints,v4_precise] [--questions Q-G2,Q-G4,Q-G5]
"""

import asyncio
import json
import os
import sys
import time
import argparse
from collections import OrderedDict
from typing import Dict, Any, List

# ---------------------------------------------------------------------------
# Prompt Variants
# ---------------------------------------------------------------------------

def build_prompt(variant: str, query: str, context: str) -> str:
    """Build the full prompt for a given variant."""

    # ── CURRENT PRODUCTION (baseline) ─────────────────────────────────
    if variant == "v3_keypoints":
        return f"""You are an expert analyst. Answer with bullet points only.

Question: {query}

Evidence Context:
{context}

Instructions:
1. Answer the question using ONLY information from the Evidence Context.
2. REFUSE only for specific lookups where the exact data point is absent:
   - Question asks for "bank routing number" but evidence has no routing number → Refuse
   - Question asks for "SWIFT code" but evidence has no SWIFT/IBAN → Refuse
   - Question asks for "California law" but evidence shows a different state → Refuse
   - Question asks about a specific term, clause, or concept by name (e.g. "mold damage", "force majeure") but that exact term does NOT appear anywhere in the evidence → Refuse. Do NOT infer that an unnamed concept falls under a broader or related category.
   When refusing, respond ONLY with: "The requested information was not found in the available documents."
3. For general questions (warranty terms, agreement details, fees, obligations, etc.),
   synthesize all relevant information from the evidence even if the text is
   fragmentary or OCR-imperfect. Do NOT refuse when partial evidence is available.
4. **RESPECT ALL QUALIFIERS** in the question. If the question asks for a specific type, category, or unit:
   - Include ONLY items matching that qualifier
   - EXCLUDE items that don't match, even if they seem related
   - If the question specifies a unit (e.g. "day-based"), do NOT include items in other units (weeks, months) even if convertible
5. Include citations [N] for factual claims.
6. If the evidence contains explicit numeric values (e.g., dollar amounts, time periods/deadlines, percentages, counts), include them verbatim.
7. Prefer concrete obligations/thresholds over general paraphrases.
8. Answer ONLY what was asked — no extra items, no tangential information.
   If the question asks for N items (e.g. "list the three"), return exactly N bullets.
9. When the specific information requested is absent from the evidence, **lead with** an explicit statement that it was not found before mentioning any related information.
10. Entities with different legal names are DIFFERENT entities (e.g. "Contoso Lifts LLC" ≠ "Contoso Ltd."). Do NOT conflate them.
11. **Prefer exact lexical matches over semantic paraphrases.** If the question asks about "non-transferability" and the evidence contains a clause saying something "is not transferable", cite THAT clause rather than a loosely related clause (e.g. "may not assign"). Match the question's specific terminology to the evidence's wording.

Respond using ONLY bullet points — no summary paragraph, no headers, no preamble:

- [Fact with citation [N]]
- [Fact with citation [N]]

Response:"""

    # ── V4: Hierarchy + Consolidation ─────────────────────────────────
    if variant == "v4_hierarchy":
        return f"""You are an expert analyst. Answer with bullet points only.

Question: {query}

Evidence Context:
{context}

Instructions:
1. Answer the question using ONLY information from the Evidence Context.
2. REFUSE only when the specific concept, term, or data point named in the question does NOT appear anywhere in the evidence. When refusing, respond ONLY with: "The requested information was not found in the available documents."
3. When partial or fragmentary evidence is available, synthesize it — do NOT refuse.
4. **RESPECT ALL QUALIFIERS** in the question. Include ONLY items matching the qualifier; EXCLUDE items that don't match even if related.
5. Include citations [N] for factual claims.
6. **ONE bullet per distinct top-level item.** If the question asks about mechanisms, list each MECHANISM once — do not break implementation details (e.g. venue, timeline, administrator) into separate bullets. Consolidate related sub-points into a single bullet with key details inline.
7. **Distinguish the category from its instances.** E.g., "binding arbitration" is ONE dispute-resolution mechanism — its procedural details (AAA, 180 days, Pocatello) belong inside that single bullet, not as separate bullets.
8. Answer ONLY what was asked — no tangential information. If the question asks for N items, return exactly N bullets.
9. Prefer exact wording from the evidence over paraphrases. Include explicit numeric values verbatim.
10. Entities with different legal names are DIFFERENT entities.

Respond using ONLY bullet points — no summary paragraph, no headers, no preamble:

- [Fact with citation [N]]
- [Fact with citation [N]]

Response:"""

    # ── V5: Strict top-level + max bullet guidance ────────────────────
    if variant == "v5_strict":
        return f"""You are an expert analyst. Answer with bullet points only.

Question: {query}

Evidence Context:
{context}

Instructions:
1. Answer the question using ONLY information from the Evidence Context.
2. REFUSE only when the specific concept or data point named in the question does NOT appear anywhere in the evidence. When refusing, respond ONLY with: "The requested information was not found in the available documents."
3. When partial or fragmentary evidence is available, synthesize it — do NOT refuse.
4. **RESPECT ALL QUALIFIERS** in the question. Include ONLY items matching the qualifier.
5. Include citations [N] for factual claims.
6. **Each bullet = one DISTINCT top-level answer to the question.** Do NOT create separate bullets for sub-details, procedural specifics, or elaborations of a previously stated item. Pack supporting details (amounts, deadlines, venues) into the same bullet as the main item they belong to.
7. If multiple evidence passages describe the SAME item from different angles, merge them into ONE bullet.
8. Answer ONLY what was asked. Omit tangential information even if it appears in the evidence.
9. Prefer exact wording and numeric values from the evidence.
10. Entities with different legal names are DIFFERENT entities.

Respond using ONLY bullet points — no summary paragraph, no headers, no preamble:

- [Fact with citation [N]]
- [Fact with citation [N]]

Response:"""

    # ── V6: Question-type aware (count-constrained) ───────────────────
    if variant == "v6_count_aware":
        return f"""You are an expert analyst. Answer with bullet points only.

Question: {query}

Evidence Context:
{context}

Instructions:
1. Answer the question using ONLY information from the Evidence Context.
2. REFUSE only when the specific concept or data point named in the question does NOT appear anywhere in the evidence. When refusing, respond ONLY with: "The requested information was not found in the available documents."
3. When partial or fragmentary evidence is available, synthesize it — do NOT refuse.
4. **RESPECT ALL QUALIFIERS** in the question. Include ONLY items matching the qualifier.
5. Include citations [N] for factual claims.
6. **Produce the MINIMUM number of bullets that fully answers the question.** Each bullet must represent a genuinely distinct item — not a sub-detail or elaboration of another bullet. When in doubt whether something is a new item or a detail of an existing one, fold it into the existing bullet.
7. If multiple passages discuss the same topic (e.g., different clauses of the same mechanism), consolidate into ONE bullet that captures the key facts with citations.
8. Answer ONLY what was asked. Omit tangential information.
9. Prefer exact wording and numeric values from the evidence.
10. Entities with different legal names are DIFFERENT entities.

Respond using ONLY bullet points — no summary paragraph, no headers, no preamble:

- [Fact with citation [N]]
- [Fact with citation [N]]

Response:"""

    raise ValueError(f"Unknown variant: {variant}")


# ---------------------------------------------------------------------------
# Ground Truth (from QUESTION_BANK_5PDFS_2025-12-24.md + eval files)
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "Q-G1": {
        "expected_items": 4,
        "items": [
            "Property management: either party may terminate with 60 days written notice",
            "Purchase contract: customer may cancel within 3 business days for full refund; afterward deposit is forfeited",
            "Holding tank contract: remains until owner or pumper terminates",
            "Warranty: not transferable; terminates if first purchaser sells/moves out",
        ],
    },
    "Q-G2": {
        "expected_items": 3,
        "items": [
            "Warranty/arbitration: disputes governed by State of Idaho substantive law",
            "Purchase contract: governed by laws of State of Florida",
            "Property management agreement: governed by laws of State of Hawaii",
        ],
    },
    "Q-G3": {
        "expected_items": 8,
        "items": [
            "Invoice: TOTAL/AMOUNT DUE 29900.00",
            "Purchase contract: $29,900 in 3 installments",
            "Property management: 25%/10% commissions",
            "$75/month advertising",
            "$50/month admin",
            "10% repair fee",
            "$35/hour scheduling",
            "Hawaii excise tax on fees",
        ],
    },
    "Q-G4": {
        "expected_items": 2,
        "items": [
            "Holding tank: pumper submits reports to County including service dates, volumes pumped, and condition",
            "Property management: agent provides owner a monthly statement of income and expenses",
        ],
    },
    "Q-G5": {
        "expected_items": 2,
        "items": [
            "Warranty disputes subject to binding arbitration (small-claims carveout, confidentiality)",
            "Purchase contract: contractor may recover legal fees upon customer default",
        ],
    },
}


# ---------------------------------------------------------------------------
# LLM Call
# ---------------------------------------------------------------------------
async def call_llm(prompt: str, model: str = "gpt-4.1") -> str:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AsyncAzureOpenAI

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    endpoint = os.getenv(
        "AZURE_OPENAI_ENDPOINT", "https://graphrag-openai-8476.openai.azure.com/"
    )
    client = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2025-01-01-preview",
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=2000,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def count_bullets(text: str) -> int:
    return len([l for l in text.split("\n") if l.strip().startswith("-")])


def evaluate_answer(qid: str, answer: str) -> Dict[str, Any]:
    gt = GROUND_TRUTH.get(qid, {})
    expected = gt.get("expected_items", "?")
    bullets = count_bullets(answer)
    ratio = f"{bullets / expected:.1f}x" if isinstance(expected, int) and expected > 0 else "?"
    return {
        "bullets": bullets,
        "expected": expected,
        "ratio": ratio,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    parser = argparse.ArgumentParser(description="Prompt variant A/B test")
    parser.add_argument(
        "--variants",
        default="v3_keypoints,v4_hierarchy,v5_strict,v6_count_aware",
        help="Comma-separated variant names",
    )
    parser.add_argument(
        "--questions",
        default="Q-G2,Q-G4,Q-G5",
        help="Comma-separated question IDs to test",
    )
    parser.add_argument(
        "--model", default="gpt-4.1", help="Azure OpenAI deployment name"
    )
    args = parser.parse_args()

    variants = [v.strip() for v in args.variants.split(",")]
    question_ids = [q.strip() for q in args.questions.split(",")]

    # Load test cases
    with open("/tmp/prompt_test_cases.json") as f:
        test_cases = json.load(f)

    print(f"Testing {len(variants)} variants × {len(question_ids)} questions")
    print(f"Model: {args.model}")
    print("=" * 80)

    results: Dict[str, Dict[str, Any]] = {}

    for variant in variants:
        results[variant] = {}
        print(f"\n{'='*80}")
        print(f"VARIANT: {variant}")
        print(f"{'='*80}")

        for qid in question_ids:
            tc = test_cases.get(qid)
            if not tc:
                print(f"  {qid}: SKIPPED (no test case)")
                continue

            prompt = build_prompt(variant, tc["query"], tc["context"])
            print(f"\n  {qid}: {tc['query'][:70]}...")
            print(f"  Passages: {tc['num_passages']}, Context: {len(tc['context'])} chars")

            t0 = time.time()
            try:
                answer = await call_llm(prompt, model=args.model)
            except Exception as e:
                print(f"  ERROR: {e}")
                answer = f"ERROR: {e}"
            elapsed = time.time() - t0

            ev = evaluate_answer(qid, answer)
            results[variant][qid] = {
                "answer": answer,
                "bullets": ev["bullets"],
                "expected": ev["expected"],
                "ratio": ev["ratio"],
                "elapsed_ms": int(elapsed * 1000),
            }

            print(f"  Bullets: {ev['bullets']} (expected: {ev['expected']}, ratio: {ev['ratio']})")
            print(f"  Latency: {int(elapsed*1000)}ms")
            print(f"  Answer:")
            for line in answer.split("\n"):
                if line.strip():
                    print(f"    {line.strip()[:120]}")

    # Summary table
    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)
    header = f"{'Variant':<20}"
    for qid in question_ids:
        gt = GROUND_TRUTH.get(qid, {})
        header += f" {qid} (exp={gt.get('expected_items','?')})"
        header += " " * max(0, 12 - len(f"{qid} (exp={gt.get('expected_items','?')})"))
    print(header)
    print("-" * len(header))

    for variant in variants:
        row = f"{variant:<20}"
        for qid in question_ids:
            r = results.get(variant, {}).get(qid, {})
            cell = f"{r.get('bullets','?')} ({r.get('ratio','?')})"
            row += f" {cell:<18}"
        print(row)

    # Save detailed results
    out_path = f"benchmarks/prompt_ab_test_{int(time.time())}.json"
    with open(out_path, "w") as f:
        json.dump(
            {"variants": variants, "questions": question_ids, "model": args.model, "results": results},
            f, indent=2,
        )
    print(f"\nDetailed results saved to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
