#!/usr/bin/env python3
"""
Test V1 vs V2 on Route 4 differentiation questions.
Compares performance after HippoRAG alias + KVP resolution enhancements.
"""

import asyncio
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

# Setup paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, app_root)
os.chdir(app_root)

# Load env
load_dotenv(os.path.join(app_root, '.env'))

from src.core.config import settings
from src.worker.hybrid.orchestrator import HybridPipeline as V1Pipeline
from src.worker.hybrid_v2.orchestrator import HybridPipeline as V2Pipeline, DeploymentProfile
from src.worker.hybrid.router.main import QueryRoute as V1Route
from src.worker.hybrid_v2.router.main import QueryRoute as V2Route
from src.worker.hybrid_v2.indexing.text_store import Neo4jTextUnitStore
from neo4j import GraphDatabase

# Initialize LlamaIndex Azure OpenAI LLM
from llama_index.llms.azure_openai import AzureOpenAI as LlamaIndexAzureOpenAI
llm_client = LlamaIndexAzureOpenAI(
    engine=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version="2024-08-01-preview"
)

# Test groups
V1_GROUP = "invoice-contract-verification"  # V1 unified index
V2_GROUP = "test-5pdfs-v2-enhanced-ex"      # V2 with Voyage embeddings + alias fix

# Differentiation questions from QUESTION_BANK_ROUTE4_DEEP_REASONING_2026.md
QUESTIONS = [
    {
        "id": "Q-DR1",
        "query": "Identify the vendor responsible for the vertical platform lift maintenance. Does their invoice's payment schedule match the terms in the original Purchase Agreement?",
        "expected_keywords": ["Contoso", "payment", "$20,000", "$7,000", "$2,900", "installment"],
        "requires_cross_doc": True,
    },
    {
        "id": "Q-DR3", 
        "query": "A pipe burst in the kitchen (emergency) on a Sunday. If the homeowner notifies the Builder via certified mail the next day, is this considered valid notice under the Warranty terms?",
        "expected_keywords": ["emergency", "phone", "notify", "24 hours", "invalid", "mail"],
        "requires_inference": True,
    },
    {
        "id": "Q-DR5",
        "query": "Compare the strictness of the 'financial penalties' for early termination in the Property Management Agreement versus the Holding Tank Servicing Contract.",
        "expected_keywords": ["termination", "penalty", "fee", "commission", "Property Management", "Holding Tank"],
        "requires_comparison": True,
    },
    {
        "id": "Q-DR7",
        "query": "The Purchase Contract lists specific payment milestones. Do these match the line items or total on the Invoice #1256003?",
        "expected_keywords": ["$20,000", "$7,000", "$2,900", "match", "milestone", "invoice"],
        "requires_cross_doc": True,
    },
    {
        "id": "CONSISTENCY",
        "query": "Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms",
        "expected_keywords": ["payment", "due", "conflict", "mismatch", "invoice", "contract"],
        "requires_cross_doc": True,
    },
]


def score_response(response: str, expected_keywords: list) -> dict:
    """Score response based on keyword presence."""
    response_lower = response.lower()
    found = []
    missing = []
    for kw in expected_keywords:
        if kw.lower() in response_lower:
            found.append(kw)
        else:
            missing.append(kw)
    
    score = len(found) / len(expected_keywords) * 100 if expected_keywords else 0
    return {
        "score": score,
        "found": found,
        "missing": missing,
        "found_count": len(found),
        "total_keywords": len(expected_keywords)
    }


async def run_query_v1(pipeline, query: str, question_id: str) -> dict:
    """Run query on V1 pipeline."""
    try:
        result = await pipeline.force_route(
            query=query,
            route=V1Route.DRIFT_MULTI_HOP,
            response_type="summary"
        )
        return {
            "success": True,
            "response": result.get("response", ""),
            "citations": len(result.get("citations", [])),
            "route": result.get("route_used", "unknown")
        }
    except Exception as e:
        return {"success": False, "error": str(e), "response": "", "citations": 0}


async def run_query_v2(pipeline, query: str, question_id: str) -> dict:
    """Run query on V2 pipeline."""
    try:
        result = await pipeline.force_route(
            query=query,
            route=V2Route.DRIFT_MULTI_HOP,
            response_type="summary"
        )
        return {
            "success": True,
            "response": result.get("response", ""),
            "citations": len(result.get("citations", [])),
            "route": result.get("route_used", "unknown")
        }
    except Exception as e:
        return {"success": False, "error": str(e), "response": "", "citations": 0}


async def main():
    print("=" * 80)
    print("🧪 V1 vs V2 DIFFERENTIATION TEST - Route 4 Deep Reasoning")
    print("=" * 80)
    print(f"V1 Group: {V1_GROUP}")
    print(f"V2 Group: {V2_GROUP}")
    print(f"Questions: {len(QUESTIONS)}")
    print()
    
    # Initialize Neo4j driver and text stores
    neo4j_driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    
    # Create text stores for both groups
    v1_text_store = Neo4jTextUnitStore(neo4j_driver, V1_GROUP)
    v2_text_store = Neo4jTextUnitStore(neo4j_driver, V2_GROUP)
    
    # Initialize pipelines
    print("Initializing V1 pipeline...")
    v1_pipeline = V1Pipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_client,
        group_id=V1_GROUP,
        neo4j_driver=neo4j_driver,
        text_unit_store=v1_text_store
    )
    await v1_pipeline.initialize()  # CRITICAL: Connect async Neo4j for PPR
    
    print("Initializing V2 pipeline...")
    v2_pipeline = V2Pipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_client,
        group_id=V2_GROUP,
        neo4j_driver=neo4j_driver,
        text_unit_store=v2_text_store
    )
    await v2_pipeline.initialize()  # CRITICAL: Connect async Neo4j for PPR
    
    results = []
    v1_total_score = 0
    v2_total_score = 0
    
    for q in QUESTIONS:
        print(f"\n{'='*80}")
        print(f"📝 {q['id']}: {q['query'][:80]}...")
        print("=" * 80)
        
        # Run V1
        print("\n🔵 V1 Processing...")
        v1_result = await run_query_v1(v1_pipeline, q["query"], q["id"])
        v1_score_info = score_response(v1_result["response"], q["expected_keywords"])
        
        print(f"   Score: {v1_score_info['score']:.0f}% ({v1_score_info['found_count']}/{v1_score_info['total_keywords']} keywords)")
        print(f"   Citations: {v1_result['citations']}")
        if v1_score_info['missing']:
            print(f"   Missing: {v1_score_info['missing'][:3]}")
        
        # Run V2
        print("\n🟢 V2 Processing...")
        v2_result = await run_query_v2(v2_pipeline, q["query"], q["id"])
        v2_score_info = score_response(v2_result["response"], q["expected_keywords"])
        
        print(f"   Score: {v2_score_info['score']:.0f}% ({v2_score_info['found_count']}/{v2_score_info['total_keywords']} keywords)")
        print(f"   Citations: {v2_result['citations']}")
        if v2_score_info['missing']:
            print(f"   Missing: {v2_score_info['missing'][:3]}")
        
        # Comparison
        diff = v2_score_info['score'] - v1_score_info['score']
        if diff > 5:
            verdict = "🟢 V2 BETTER"
        elif diff < -5:
            verdict = "🔴 V1 BETTER"
        else:
            verdict = "⚪ TIE"
        
        print(f"\n   {verdict} (diff: {diff:+.0f}%)")
        
        v1_total_score += v1_score_info['score']
        v2_total_score += v2_score_info['score']
        
        results.append({
            "question_id": q["id"],
            "query": q["query"],
            "v1_score": v1_score_info['score'],
            "v2_score": v2_score_info['score'],
            "v1_citations": v1_result['citations'],
            "v2_citations": v2_result['citations'],
            "v1_keywords_found": v1_score_info['found'],
            "v2_keywords_found": v2_score_info['found'],
            "diff": diff,
            "verdict": verdict
        })
        
        await asyncio.sleep(2)  # Rate limit
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 FINAL SUMMARY")
    print("=" * 80)
    
    print(f"\n{'Question':<15} | {'V1 Score':>10} | {'V2 Score':>10} | {'Diff':>8} | {'Verdict':<12}")
    print("-" * 70)
    for r in results:
        print(f"{r['question_id']:<15} | {r['v1_score']:>9.0f}% | {r['v2_score']:>9.0f}% | {r['diff']:>+7.0f}% | {r['verdict']}")
    print("-" * 70)
    
    v1_avg = v1_total_score / len(QUESTIONS)
    v2_avg = v2_total_score / len(QUESTIONS)
    overall_diff = v2_avg - v1_avg
    
    print(f"{'AVERAGE':<15} | {v1_avg:>9.1f}% | {v2_avg:>9.1f}% | {overall_diff:>+7.1f}%")
    print()
    
    if overall_diff > 5:
        print("🏆 OVERALL WINNER: V2 (with alias + KVP resolution)")
    elif overall_diff < -5:
        print("🏆 OVERALL WINNER: V1")
    else:
        print("🏆 OVERALL: TIE (within 5% margin)")
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"/afh/projects/graphrag-orchestration/bench_v1_v2_differentiation_{timestamp}.json"
    with open(output_file, 'w') as f:
        json.dump({
            "timestamp": timestamp,
            "v1_group": V1_GROUP,
            "v2_group": V2_GROUP,
            "v1_avg_score": v1_avg,
            "v2_avg_score": v2_avg,
            "diff": overall_diff,
            "results": results
        }, f, indent=2)
    print(f"\n📁 Results saved to: {output_file}")
    
    # Cleanup
    await v1_pipeline.close()
    await v2_pipeline.close()
    neo4j_driver.close()


if __name__ == "__main__":
    asyncio.run(main())
