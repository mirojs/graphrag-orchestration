#!/usr/bin/env python3
"""
Router Model Comparison — Production Prompt Evaluation

Extends evaluate_router_accuracy.py to compare multiple routing model candidates
using the ACTUAL production prompt (markdown output, disambiguation rules) and
the full 41-question bank.

Models tested:
  gpt-5.1, gpt-4.1, gpt-4.1-mini, gpt-4o-mini, gpt-5-mini, gpt-5-nano

Usage:
    python scripts/evaluate_router_model_comparison.py
"""

import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment — graphrag-orchestration/.env is authoritative
env_candidates = [
    project_root / ".env",
    project_root / ".azure" / "default" / ".env",
    project_root / "graphrag-orchestration" / ".env",   # wins (loaded last with override)
]
for env_path in env_candidates:
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"Loaded environment from: {env_path}")

print(f"Using endpoint: {os.getenv('AZURE_OPENAI_ENDPOINT', 'NOT SET')}")

from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from src.worker.hybrid.router.main import (
    DeploymentProfile,
    HybridRouter,
    QueryRoute,
)

# ── Models to test ───────────────────────────────────────────────────────────
MODELS_TO_TEST = [
    "gpt-5.1",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "gpt-5-mini",
    "gpt-5-nano",
]


# ── Question Bank Parser (reused from evaluate_router_accuracy.py) ───────────
class QuestionBankParser:
    """Parse question bank markdown and extract questions with expected routes."""

    def __init__(self, question_bank_path: str):
        self.path = Path(question_bank_path)
        self.questions: List[Dict[str, Any]] = []

    def parse(self) -> List[Dict[str, Any]]:
        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()

        pattern = (
            r'\d+\.\s+\*\*([QR]-[A-Z]\d+):\*\*\s+([^\n]+)\n'
            r'\s+-\s+\*\*Expected Route:\*\*\s+([^\n]+)'
        )

        for match in re.finditer(pattern, content, re.MULTILINE):
            qid = match.group(1)
            question = match.group(2).strip()
            expected_route = self._parse_route(match.group(3).strip())

            if expected_route:
                self.questions.append({
                    "id": qid,
                    "question": question,
                    "expected_route": expected_route,
                    "expected_route_text": match.group(3).strip(),
                })

        print(f"Parsed {len(self.questions)} questions from {self.path}")
        return self.questions

    @staticmethod
    def _parse_route(route_text: str) -> Optional[QueryRoute]:
        t = route_text.lower()
        if "route 1" in t or "vector rag" in t:
            return QueryRoute.LOCAL_SEARCH  # Vector RAG maps to local_search
        if "route 2" in t or "local search" in t:
            return QueryRoute.LOCAL_SEARCH
        if "route 3" in t or "global search" in t:
            return QueryRoute.GLOBAL_SEARCH
        if "route 4" in t or "drift" in t:
            return QueryRoute.DRIFT_MULTI_HOP
        print(f"  Warning: could not parse route: {route_text}")
        return None


# ── Per-model evaluation ─────────────────────────────────────────────────────
async def evaluate_model(
    deployment_name: str,
    questions: List[Dict[str, Any]],
    token_provider=None,
) -> Dict[str, Any]:
    """Evaluate a single model using the production HybridRouter."""
    from llama_index.llms.azure_openai import AzureOpenAI

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")

    llm_kwargs = {
        "engine": deployment_name,
        "azure_endpoint": endpoint,
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        "temperature": 1.0,  # gpt-5 series doesn't support custom temperature
    }

    if api_key:
        llm_kwargs["api_key"] = api_key
    else:
        # Use Azure AD / Managed Identity
        llm_kwargs["use_azure_ad"] = True
        llm_kwargs["azure_ad_token_provider"] = token_provider

    llm = AzureOpenAI(**llm_kwargs)

    router = HybridRouter(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm,
    )

    results = []
    total_latency_ms = 0.0

    print(f"\n{'=' * 80}")
    print(f"Model: {deployment_name}  ({len(questions)} questions)")
    print(f"{'=' * 80}")

    for q in questions:
        t0 = time.perf_counter()
        actual_route = await router.route(q["question"])
        latency_ms = (time.perf_counter() - t0) * 1000
        total_latency_ms += latency_ms

        expected = q["expected_route"]
        is_correct = actual_route == expected
        is_soft = {actual_route, expected} == {
            QueryRoute.LOCAL_SEARCH,
            QueryRoute.GLOBAL_SEARCH,
        }

        results.append({
            "qid": q["id"],
            "question": q["question"],
            "expected": expected.value,
            "actual": actual_route.value,
            "correct": is_correct,
            "soft_error": is_soft,
            "latency_ms": round(latency_ms, 1),
        })

        tag = "✓" if is_correct else ("~" if is_soft else "✗")
        print(
            f"  {tag} {q['id']:8} | {latency_ms:6.0f}ms | "
            f"exp={expected.value:20} act={actual_route.value:20}"
        )

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.05)

    metrics = _calc_metrics(results)
    metrics["model"] = deployment_name
    metrics["avg_latency_ms"] = round(total_latency_ms / len(questions), 1)
    metrics["total_latency_ms"] = round(total_latency_ms, 1)
    return metrics


def _calc_metrics(results: List[Dict]) -> Dict[str, Any]:
    total = len(results)
    hard_correct = sum(1 for r in results if r["correct"])
    soft_correct = sum(
        1.0 if r["correct"] else (0.5 if r["soft_error"] else 0.0)
        for r in results
    )

    # Confusion matrix
    confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        confusion[r["expected"]][r["actual"]] += 1

    # Per-route precision / recall / F1
    all_routes = ["local_search", "global_search", "drift_multi_hop"]
    per_route = {}
    for route in all_routes:
        tp = confusion[route][route]
        fp = sum(confusion[o][route] for o in confusion if o != route)
        fn = sum(confusion[route][o] for o in confusion[route] if o != route)
        prec = tp / (tp + fp) if (tp + fp) else 0
        rec = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        per_route[route] = {
            "precision": round(prec, 3),
            "recall": round(rec, 3),
            "f1": round(f1, 3),
            "support": sum(confusion[route].values()),
        }

    return {
        "total_questions": total,
        "hard_correct": hard_correct,
        "hard_accuracy": round(hard_correct / total, 4) if total else 0,
        "soft_correct": soft_correct,
        "soft_accuracy": round(soft_correct / total, 4) if total else 0,
        "per_route": per_route,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "results": results,
    }


# ── Report generation ────────────────────────────────────────────────────────
def generate_report(
    all_metrics: List[Dict[str, Any]],
    md_path: Path,
    json_path: Path,
):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = all_metrics[0]["total_questions"] if all_metrics else 0

    # Sort by hard accuracy desc, then avg latency asc
    ranked = sorted(
        all_metrics, key=lambda m: (-m["hard_accuracy"], m["avg_latency_ms"])
    )

    lines = [
        f"# Router Model Comparison — Production Prompt",
        f"**Date:** {ts}  ",
        f"**Questions:** {n} (full bank, production prompt, markdown output)\n",
        "## Summary\n",
        "| # | Model | Hard Acc | Soft Acc | Avg Latency | Errors |",
        "|---|-------|----------|----------|-------------|--------|",
    ]
    for i, m in enumerate(ranked, 1):
        errs = m["total_questions"] - m["hard_correct"]
        lines.append(
            f"| {i} | {m['model']} | "
            f"{m['hard_accuracy']:.1%} ({m['hard_correct']}/{m['total_questions']}) | "
            f"{m['soft_accuracy']:.1%} | "
            f"{m['avg_latency_ms']:.0f} ms | "
            f"{errs} |"
        )

    lines.append("\n## Per-Route Breakdown\n")

    for m in ranked:
        lines.append(f"### {m['model']}  —  {m['hard_accuracy']:.1%}\n")
        lines.append("| Route | Precision | Recall | F1 | Support |")
        lines.append("|-------|-----------|--------|----|---------|")
        for route, rm in m["per_route"].items():
            lines.append(
                f"| {route} | {rm['precision']:.1%} | {rm['recall']:.1%} | "
                f"{rm['f1']:.3f} | {rm['support']} |"
            )

        # Show misclassifications
        misses = [r for r in m["results"] if not r["correct"]]
        if misses:
            lines.append(f"\n**Misclassifications ({len(misses)}):**")
            for r in misses:
                soft_tag = " *(soft)*" if r["soft_error"] else ""
                lines.append(
                    f"- {r['qid']}: exp={r['expected']}, act={r['actual']}{soft_tag}  "
                    f"— \"{r['question'][:80]}\""
                )
        else:
            lines.append("\n**Perfect — no misclassifications.**")
        lines.append("")

    # Recommendation
    best = ranked[0]
    lines.append("## Recommendation\n")
    lines.append(
        f"**{best['model']}** — {best['hard_accuracy']:.1%} hard accuracy, "
        f"{best['avg_latency_ms']:.0f} ms avg latency.\n"
    )
    lines.append(f"---\n*Generated: {ts}*\n")

    report_text = "\n".join(lines)
    md_path.write_text(report_text, encoding="utf-8")
    print(f"\nReport saved: {md_path}")

    # Console summary
    print(f"\n{'=' * 80}")
    print("COMPARISON SUMMARY")
    print(f"{'=' * 80}")
    for i, m in enumerate(ranked, 1):
        print(
            f"  {i}. {m['model']:15s}  "
            f"hard={m['hard_accuracy']:.1%}  "
            f"soft={m['soft_accuracy']:.1%}  "
            f"latency={m['avg_latency_ms']:.0f}ms"
        )
    print(f"{'=' * 80}")

    # JSON
    json_data = {
        "timestamp": ts,
        "question_count": n,
        "prompt": "production (markdown, disambiguation rules)",
        "models": [m["model"] for m in ranked],
        "ranked_results": [
            {k: v for k, v in m.items() if k != "results"} for m in ranked
        ],
        "detailed_results": {m["model"]: m["results"] for m in ranked},
    }
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
    print(f"JSON saved:   {json_path}")


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    question_bank_path = project_root / "docs" / "archive" / "status_logs" / "QUESTION_BANK_5PDFS_2025-12-24.md"

    parser = QuestionBankParser(str(question_bank_path))
    questions = parser.parse()
    if not questions:
        print("ERROR: no questions found")
        return

    route_dist = defaultdict(int)
    for q in questions:
        route_dist[q["expected_route"].value] += 1
    print(f"Route distribution: {dict(route_dist)}")

    # Set up auth: API key or Managed Identity
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    token_provider = None
    if not api_key:
        print("No API key — using Azure AD (DefaultAzureCredential)")
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
    else:
        print("Using API key authentication")

    # Evaluate each model
    all_metrics: List[Dict[str, Any]] = []
    for model in MODELS_TO_TEST:
        try:
            metrics = await evaluate_model(model, questions, token_provider=token_provider)
            all_metrics.append(metrics)
        except Exception as e:
            print(f"\n❌ ERROR testing {model}: {e}")
            import traceback
            traceback.print_exc()
            continue

    if not all_metrics:
        print("ERROR: no models completed successfully")
        return

    # Generate report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = project_root / f"router_model_comparison_{ts}.md"
    json_path = project_root / f"router_model_comparison_{ts}.json"
    generate_report(all_metrics, md_path, json_path)


if __name__ == "__main__":
    asyncio.run(main())
