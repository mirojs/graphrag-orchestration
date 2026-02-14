#!/usr/bin/env python3
"""
NER Model Comparison Benchmark
================================
Tests different LLM models for Route 2 Stage 2.1 (Entity Extraction / NER).

Compares: latency, extracted entities, and downstream answer quality.

Usage:
    python scripts/benchmark_ner_model_comparison.py
    python scripts/benchmark_ner_model_comparison.py --models gpt-4.1-mini gpt-5-nano
    python scripts/benchmark_ner_model_comparison.py --full-pipeline   # also test downstream synthesis
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env.local into environment before importing settings
_env_local = PROJECT_ROOT / ".env.local"
if _env_local.exists():
    for _line in _env_local.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip()
            if not os.environ.get(_k):  # don't override existing env vars
                os.environ[_k] = _v

from src.core.config import settings


# ── Test queries with expected entities ──────────────────────────────────────
# These are the Route 2 benchmark queries. "expected_entities" are the key
# entity names that a good NER model should extract (case-insensitive match).

TEST_QUERIES = [
    {
        "qid": "Q-L1",
        "query": "Who is the **Agent** in the property management agreement?",
        "expected_entities": ["Agent", "Property Management Agreement"],
    },
    {
        "qid": "Q-L3",
        "query": "What is the managed property address in the property management agreement?",
        "expected_entities": ["Managed Property", "Property Management Agreement"],
    },
    {
        "qid": "Q-L4",
        "query": "What is the initial term start date in the property management agreement?",
        "expected_entities": ["Property Management Agreement"],
    },
    {
        "qid": "Q-L6",
        "query": "What is the Agent fee/commission for **short-term** rentals (<180 days)?",
        "expected_entities": ["Agent"],
    },
    {
        "qid": "Q-L9",
        "query": "In the purchase contract Exhibit A, what is the job location?",
        "expected_entities": ["Purchase Contract", "Exhibit A"],
    },
    {
        "qid": "Q-L10",
        "query": "In the purchase contract Exhibit A, what is the contact's name and email?",
        "expected_entities": ["Purchase Contract", "Exhibit A"],
    },
    {
        "qid": "Q-N1",
        "query": "What is the invoice's **bank routing number** for payment?",
        "expected_entities": [],  # negative test — should ideally extract nothing meaningful
    },
    {
        "qid": "Q-N6",
        "query": "Which documents are governed by the laws of **California**?",
        "expected_entities": ["California"],
    },
]

# ── Models to test ──────────────────────────────────────────────────────────
DEFAULT_MODELS = [
    "gpt-5.1",       # current (baseline)
    "gpt-4.1",       # strong reasoning, cheaper
    "gpt-4.1-mini",  # fast + cheap
    "gpt-5-nano",    # ultra-fast + cheapest
]


def _create_llm(model_name: str) -> Any:
    """Create a LlamaIndex AzureOpenAI LLM for the given deployment name."""
    from llama_index.llms.azure_openai import AzureOpenAI

    if not settings.AZURE_OPENAI_API_KEY:
        env_token = os.getenv("AZURE_OPENAI_BEARER_TOKEN")
        if env_token:
            def token_provider() -> str:
                return env_token
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )

        llm_kwargs: Dict[str, Any] = {
            "engine": model_name,
            "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
            "api_version": settings.AZURE_OPENAI_API_VERSION,
            "use_azure_ad": True,
            "azure_ad_token_provider": token_provider,
        }
    else:
        llm_kwargs = {
            "engine": model_name,
            "api_key": settings.AZURE_OPENAI_API_KEY,
            "azure_endpoint": settings.AZURE_OPENAI_ENDPOINT,
            "api_version": settings.AZURE_OPENAI_API_VERSION,
        }

    no_temperature_models = ("gpt-5-mini", "gpt-5-nano", "o1", "o3", "o4")
    if model_name.startswith(no_temperature_models):
        # These models only accept temperature=1 (default). Override LlamaIndex's 0.1 default.
        llm_kwargs["temperature"] = 1.0
    else:
        llm_kwargs["temperature"] = 0.0

    return AzureOpenAI(**llm_kwargs)


async def _run_ner(llm: Any, query: str, top_k: int = 5) -> Tuple[List[str], float]:
    """Run NER extraction and return (entities, latency_ms).

    Uses the same prompt as IntentDisambiguator.disambiguate().
    """
    import re

    prompt = f"""You are an expert at identifying specific entities in a knowledge graph.

Given the following user query and the available entity communities in our graph,
identify the top {top_k} specific entity names that this query is referring to.

User Query: "{query}"

Available Communities/Entities:
No community information available. Extract entities directly from the query.

Important:
- Return specific entity-like strings (proper nouns, organizations, document titles, named clauses) likely to exist in the graph.
- Do NOT return generic keywords (e.g., "licensed", "state", "jurisdiction", "payment", "instructions").
- If you are unsure, return nothing.

Return ONLY a markdown list of entity names, one per line. Example:
- Contoso Ltd.
- Purchase Contract
- Warranty Agreement

Do not include any explanation, just the list.
"""

    t0 = time.perf_counter()
    response = await llm.acomplete(prompt)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    raw = response.text.strip()
    entities: List[str] = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            entities.append(line[2:].strip())
        elif line.startswith("* "):
            entities.append(line[2:].strip())

    # Clean entities (same logic as IntentDisambiguator)
    cleaned: List[str] = []
    for e in entities:
        e = e.strip()
        while len(e) >= 2 and e[0] == e[-1] and e[0] in ('"', "'", "`"):
            e = e[1:-1].strip()
        if e:
            cleaned.append(e)

    return cleaned[:top_k], elapsed_ms


def _entity_match_score(extracted: List[str], expected: List[str]) -> Dict[str, Any]:
    """Compute how well extracted entities cover expected entities.

    Returns recall (fraction of expected matched), plus extracted list.
    Match is case-insensitive substring containment in either direction.
    """
    if not expected:
        # Negative test — ideally extracts nothing or irrelevant stuff
        return {
            "recall": 1.0 if len(extracted) == 0 else 0.5,
            "expected": expected,
            "extracted": extracted,
            "matched": [],
            "missed": [],
        }

    matched = []
    missed = []
    for exp in expected:
        exp_lower = exp.lower()
        found = False
        for ext in extracted:
            ext_lower = ext.lower()
            if exp_lower in ext_lower or ext_lower in exp_lower:
                found = True
                break
        if found:
            matched.append(exp)
        else:
            missed.append(exp)

    recall = len(matched) / len(expected) if expected else 1.0
    return {
        "recall": recall,
        "expected": expected,
        "extracted": extracted,
        "matched": matched,
        "missed": missed,
    }


async def benchmark_model(model_name: str, queries: List[Dict], repeats: int = 2) -> Dict[str, Any]:
    """Run all queries against a single model, return aggregate results."""
    print(f"\n{'='*60}")
    print(f"  Model: {model_name}")
    print(f"{'='*60}")

    try:
        llm = _create_llm(model_name)
    except Exception as e:
        print(f"  ERROR: Failed to create LLM for {model_name}: {e}")
        return {"model": model_name, "error": str(e)}

    results: List[Dict[str, Any]] = []

    for q in queries:
        qid = q["qid"]
        query = q["query"]
        expected = q["expected_entities"]

        latencies: List[float] = []
        last_entities: List[str] = []

        for r in range(repeats):
            try:
                entities, lat_ms = await _run_ner(llm, query)
                latencies.append(lat_ms)
                last_entities = entities
                marker = "✓" if r > 0 else " "
                print(f"  {qid} [{r+1}/{repeats}] {lat_ms:>7.0f}ms  entities={entities}")
            except Exception as e:
                print(f"  {qid} [{r+1}/{repeats}] ERROR: {e}")
                latencies.append(-1)

        valid_lats = [l for l in latencies if l > 0]
        avg_ms = sum(valid_lats) / len(valid_lats) if valid_lats else -1
        match = _entity_match_score(last_entities, expected)

        results.append({
            "qid": qid,
            "query": query,
            "avg_ms": round(avg_ms, 1),
            "min_ms": round(min(valid_lats), 1) if valid_lats else -1,
            "max_ms": round(max(valid_lats), 1) if valid_lats else -1,
            "entities": last_entities,
            "entity_recall": match["recall"],
            "matched": match["matched"],
            "missed": match["missed"],
        })

    # Aggregate
    valid_results = [r for r in results if r["avg_ms"] > 0]
    avg_latency = sum(r["avg_ms"] for r in valid_results) / len(valid_results) if valid_results else -1
    avg_recall = sum(r["entity_recall"] for r in valid_results) / len(valid_results) if valid_results else 0
    min_latency = min(r["min_ms"] for r in valid_results) if valid_results else -1

    print(f"\n  Summary: avg={avg_latency:.0f}ms  min={min_latency:.0f}ms  entity_recall={avg_recall:.2f}")

    return {
        "model": model_name,
        "avg_latency_ms": round(avg_latency, 1),
        "min_latency_ms": round(min_latency, 1),
        "avg_entity_recall": round(avg_recall, 3),
        "results": results,
    }


async def run_full_pipeline_comparison(
    models: List[str],
    api_base: str,
    group_id: str,
) -> Dict[str, Any]:
    """Run full end-to-end Route 2 queries with different NER models.

    This requires the API to support a ner_model override parameter.
    Falls back to NER-only if the API doesn't support it.
    """
    import urllib.request
    import subprocess

    # Get AAD token
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--scope", "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True,
        )
        token = result.stdout.strip()
    except Exception as e:
        print(f"WARNING: Could not get AAD token: {e}")
        token = None

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{api_base.rstrip('/')}/hybrid/query"

    pipeline_results = {}
    test_queries = [q for q in TEST_QUERIES if not q["qid"].startswith("Q-N")][:4]

    for model in models:
        print(f"\n--- Full pipeline with NER={model} ---")
        model_runs = []
        for q in test_queries:
            payload = {
                "query": q["query"],
                "group_id": group_id,
                "force_route": "local_search",
                "response_type": "summary",
                "ner_model": model,  # override NER model
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode(),
                    headers=headers,
                    method="POST",
                )
                t0 = time.monotonic()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = json.loads(resp.read())
                elapsed = (time.monotonic() - t0) * 1000
                answer = body.get("response", "")[:60]
                seeds = body.get("metadata", {}).get("seed_entities", [])
                print(f"  {q['qid']}: {elapsed:.0f}ms  seeds={seeds}  ans={answer}")
                model_runs.append({
                    "qid": q["qid"],
                    "elapsed_ms": round(elapsed),
                    "seed_entities": seeds,
                    "response": answer,
                })
            except Exception as e:
                print(f"  {q['qid']}: ERROR {e}")
                model_runs.append({"qid": q["qid"], "error": str(e)})

        pipeline_results[model] = model_runs

    return pipeline_results


async def main():
    parser = argparse.ArgumentParser(description="NER Model Comparison Benchmark")
    parser.add_argument(
        "--models", nargs="+", default=DEFAULT_MODELS,
        help="Models to test (default: gpt-5.1 gpt-4.1 gpt-4.1-mini gpt-5-nano)",
    )
    parser.add_argument("--repeats", type=int, default=2, help="Repeats per query per model")
    parser.add_argument(
        "--full-pipeline", action="store_true",
        help="Also run full Route 2 pipeline with each NER model",
    )
    parser.add_argument(
        "--api-base",
        default=os.getenv(
            "GRAPHRAG_API_BASE",
            "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
        ),
    )
    parser.add_argument("--group-id", default="test-5pdfs-v2-fix2")
    args = parser.parse_args()

    print("=" * 60)
    print("  NER Model Comparison Benchmark")
    print(f"  Models: {args.models}")
    print(f"  Repeats: {args.repeats}")
    print(f"  Queries: {len(TEST_QUERIES)}")
    print("=" * 60)

    all_results: List[Dict[str, Any]] = []
    for model in args.models:
        result = await benchmark_model(model, TEST_QUERIES, repeats=args.repeats)
        all_results.append(result)

    # ── Comparison Table ──
    print("\n" + "=" * 80)
    print("  COMPARISON SUMMARY")
    print("=" * 80)
    print(f"{'Model':<18} {'Avg Latency':>12} {'Min Latency':>12} {'Entity Recall':>14} {'Speedup':>9}")
    print("-" * 80)

    baseline_lat = next(
        (r["avg_latency_ms"] for r in all_results if r["model"] == "gpt-5.1" and "error" not in r),
        None,
    )

    for r in all_results:
        if "error" in r:
            print(f"{r['model']:<18} {'ERROR':>12}")
            continue
        speedup = ""
        if baseline_lat and baseline_lat > 0 and r["avg_latency_ms"] > 0:
            ratio = baseline_lat / r["avg_latency_ms"]
            speedup = f"{ratio:.1f}x"
        print(
            f"{r['model']:<18} {r['avg_latency_ms']:>10.0f}ms {r['min_latency_ms']:>10.0f}ms "
            f"{r['avg_entity_recall']:>13.1%} {speedup:>9}"
        )

    # ── Per-query detail ──
    print("\n" + "-" * 80)
    print("  PER-QUERY ENTITY EXTRACTION DETAIL")
    print("-" * 80)
    for q in TEST_QUERIES:
        qid = q["qid"]
        print(f"\n  {qid}: {q['query'][:70]}")
        print(f"    Expected: {q['expected_entities']}")
        for r in all_results:
            if "error" in r:
                continue
            qr = next((x for x in r["results"] if x["qid"] == qid), None)
            if qr:
                status = "✓" if qr["entity_recall"] >= 0.8 else "✗"
                missed = f"  MISSED: {qr['missed']}" if qr["missed"] else ""
                print(f"    {status} {r['model']:<16} {qr['avg_ms']:>6.0f}ms  → {qr['entities']}{missed}")

    # ── Full pipeline (optional) ──
    pipeline_results = {}
    if args.full_pipeline:
        pipeline_results = await run_full_pipeline_comparison(
            args.models, args.api_base, args.group_id,
        )

    # ── Save JSON ──
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = Path(__file__).parent.parent / "benchmarks" / f"ner_model_comparison_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_data = {
        "timestamp": ts,
        "models": args.models,
        "repeats": args.repeats,
        "results": all_results,
    }
    if pipeline_results:
        out_data["pipeline_results"] = pipeline_results
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)
    print(f"\n✅ Results saved: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
