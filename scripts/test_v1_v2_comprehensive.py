#!/usr/bin/env python3
"""
Comprehensive V1 vs V2 Testing Suite
Combines single-query deep analysis with multi-question differentiation testing.
Outputs both detailed responses and JSON metrics for tracking over time.
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

# Initialize Voyage embedding client for V2 (Strategy 6 vector fallback)
from llama_index.embeddings.voyageai import VoyageEmbedding
voyage_embed_client = VoyageEmbedding(
    voyage_api_key=os.getenv("VOYAGE_API_KEY"),
    model_name="voyage-context-3"
)
print(f"Voyage embedding client initialized: {voyage_embed_client.model_name}")

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
V1_GROUP = "test-5pdfs-1769071711867955961"
V2_GROUP = "test-5pdfs-v2-enhanced-ex"  # VERIFIED: Re-indexed 2026-01-30 with embedding_v2 fix

print(f"\n{'='*80}")
print(f"🔍 CONFIGURATION VERIFICATION")
print(f"{'='*80}")
print(f"V1 Group: {V1_GROUP}")
print(f"V2 Group: {V2_GROUP}")
print(f"Neo4j URI: {settings.NEO4J_URI}")
print(f"{'='*80}\n")

# Test questions
QUESTIONS = [
    {
        "id": "CONSISTENCY_DEEP",
        "query": "Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms",
        "expected_keywords": ["payment", "conflict", "mismatch", "invoice", "contract", "$20,000", "$7,000", "$2,900"],
        "key_findings": {
            "payment_conflict": ["payment", "installment", "$20,000", "$7,000", "$2,900"],
            "lift_model": ["dumbwaiter", "platform lift", "savaria", "ascendpro"],
            "door_hardware": ["hall call", "flush", "door"],
            "contoso_mentioned": ["contoso"],
            "fabrikam_mentioned": ["fabrikam"],
            "specific_amounts": ["$20,000", "$7,000", "$2,900", "$29,900"]
        },
        "show_full_response": True
    },
    {
        "id": "Q-DR1",
        "query": "Identify the vendor responsible for the vertical platform lift maintenance. Does their invoice's payment schedule match the terms in the original Purchase Agreement?",
        "expected_keywords": ["Contoso", "payment", "$20,000", "$7,000", "$2,900", "installment"],
        "show_full_response": False
    },
    {
        "id": "Q-DR3", 
        "query": "A pipe burst in the kitchen (emergency) on a Sunday. If the homeowner notifies the Builder via certified mail the next day, is this considered valid notice under the Warranty terms?",
        "expected_keywords": ["emergency", "phone", "notify", "24 hours", "invalid", "mail"],
        "show_full_response": False
    },
    {
        "id": "Q-DR5",
        "query": "Compare the strictness of the 'financial penalties' for early termination in the Property Management Agreement versus the Holding Tank Servicing Contract.",
        "expected_keywords": ["termination", "penalty", "fee", "commission", "Property Management", "Holding Tank"],
        "show_full_response": False
    },
    {
        "id": "Q-DR7",
        "query": "The Purchase Contract lists specific payment milestones. Do these match the line items or total on the Invoice #1256003?",
        "expected_keywords": ["$20,000", "$7,000", "$2,900", "match", "milestone", "invoice"],
        "show_full_response": False
    },
]


def analyze_key_findings(response_text: str, key_findings: dict) -> dict:
    """Analyze response for specific key findings."""
    response_lower = response_text.lower()
    results = {}
    
    for finding_name, keywords in key_findings.items():
        found = any(kw.lower() in response_lower for kw in keywords)
        results[finding_name] = found
    
    return results


def score_keywords(response: str, expected_keywords: list) -> dict:
    """Score response based on keyword presence."""
    response_lower = response.lower()
    found = []
    missing = []
    
    for kw in expected_keywords:
        if kw.lower() in response_lower:
            found.append(kw)
        else:
            missing.append(kw)
    
    score = (len(found) / len(expected_keywords) * 100) if expected_keywords else 0
    return {
        "score": score,
        "found": found,
        "missing": missing,
        "found_count": len(found),
        "total_keywords": len(expected_keywords)
    }


def count_inconsistencies(response_text: str) -> int:
    """Count numbered/bulleted inconsistencies in response."""
    count = 0
    for line in response_text.split('\n'):
        if any(marker in line for marker in ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.', '11.', '12.', '13.', '14.', '15.', '16.', '17.', '18.', '19.', '20.', '•', '-']):
            if any(word in line.lower() for word in [
                'inconsist', 'mismatch', 'conflict', 'discrepan', 'differ'
            ]):
                count += 1
    return count


def extract_inconsistencies(response_text: str) -> list:
    """Extract list of inconsistencies from response for detailed comparison."""
    inconsistencies = []
    lines = response_text.split('\n')
    
    # Look for common patterns indicating inconsistencies
    patterns = [
        'inconsistenc', 'mismatch', 'conflict', 'discrepanc', 'differ',
        'does not match', 'vs', 'versus', 'contrary to', 'not in contract',
        'missing from', 'not specified'
    ]
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        # Check if line starts with numbering or bullet
        if any(marker in line for marker in ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.', '11.', '12.', '13.', '14.', '15.', '16.', '17.', '18.', '19.', '20.', '•', '-', '**']):
            # Check if it contains inconsistency keywords
            if any(pattern in line_lower for pattern in patterns):
                # Extract the inconsistency (clean up markdown)
                inconsistency = line.strip().lstrip('•-*#').strip()
                if inconsistency and len(inconsistency) > 10:  # Avoid empty or too short
                    inconsistencies.append(inconsistency)
    
    return inconsistencies


async def run_query(pipeline, pipeline_name: str, query: str, question_id: str, route) -> dict:
    """Run a single query on a pipeline."""
    print(f"\n{'='*80}")
    print(f"🔬 Testing: {pipeline_name}")
    print(f"{'='*80}")
    print(f"Query: {query}")
    print()
    
    start_time = datetime.now()
    
    try:
        result = await pipeline.force_route(
            query=query,
            route=route,
            response_type="comprehensive"  # 2-pass NLP extraction for 100% fact coverage
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        response = result.get("response", "")
        citations = result.get("citations", [])
        
        print(f"✅ Query Complete ({elapsed:.1f}s)")
        
        return {
            "success": True,
            "response": response,
            "citations": len(citations),
            "elapsed_seconds": elapsed,
            "response_length": len(response)
        }
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"❌ Query Failed ({elapsed:.1f}s)")
        print(f"Error: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "response": "",
            "citations": 0,
            "elapsed_seconds": elapsed,
            "response_length": 0
        }


async def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print(f"\n{'='*80}")
    print(f"🧪 COMPREHENSIVE V1 vs V2 TEST SUITE")
    print(f"{'='*80}")
    print(f"Timestamp: {timestamp}")
    print(f"Questions: {len(QUESTIONS)}")
    print()
    
    # Initialize Neo4j driver and text stores
    neo4j_driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
    )
    
    v1_text_store = Neo4jTextUnitStore(neo4j_driver, group_id=V1_GROUP)
    v2_text_store = Neo4jTextUnitStore(neo4j_driver, group_id=V2_GROUP)
    
    # Initialize pipelines
    print("Initializing V1 pipeline...")
    v1_pipeline = V1Pipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_client,
        group_id=V1_GROUP,
        neo4j_driver=neo4j_driver,
        text_unit_store=v1_text_store
    )
    await v1_pipeline.initialize()
    
    print("Initializing V2 pipeline (with Voyage embedding for Strategy 6)...")
    v2_pipeline = V2Pipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_client,
        embedding_client=voyage_embed_client,  # CRITICAL: Enable Strategy 6 vector fallback
        group_id=V2_GROUP,
        neo4j_driver=neo4j_driver,
        text_unit_store=v2_text_store
    )
    await v2_pipeline.initialize()
    
    # Verify groups from logs
    print(f"\n⚠️  VERIFY: Check logs above to confirm group_id in hybrid_pipeline_initialized")
    print(f"   Expected V1: {V1_GROUP}")
    print(f"   Expected V2: {V2_GROUP}")
    print()
    
    await asyncio.sleep(2)
    
    # Run tests
    results = []
    
    for q in QUESTIONS:
        print(f"\n{'='*80}")
        print(f"📝 QUESTION {q['id']}")
        print(f"{'='*80}")
        print(f"{q['query']}")
        print(f"{'='*80}\n")
        
        # Run V1
        v1_result = await run_query(v1_pipeline, "V1 (OpenAI)", q["query"], q["id"], V1Route.DRIFT_MULTI_HOP)
        
        await asyncio.sleep(1)
        
        # Run V2
        v2_result = await run_query(v2_pipeline, "V2 (Voyage)", q["query"], q["id"], V2Route.DRIFT_MULTI_HOP)
        
        # Analysis
        analysis = {
            "question_id": q["id"],
            "query": q["query"],
            "v1": v1_result,
            "v2": v2_result
        }
        
        # Display individual results in same format as original
        print(f"\n{'─'*80}")
        print(f"📊 V1 Results:")
        print(f"{'─'*80}")
        print(f"📚 Citations: {v1_result['citations']}")
        print(f"📝 Response Length: {v1_result['response_length']:,} chars")
        
        if "key_findings" in q and v1_result["success"]:
            v1_findings = analyze_key_findings(v1_result["response"], q["key_findings"])
            v1_inconsistencies = count_inconsistencies(v1_result["response"])
            analysis["v1_key_findings"] = v1_findings
            analysis["v1_inconsistencies"] = v1_inconsistencies
            
            print(f"📊 Inconsistencies Found: {v1_inconsistencies}")
            print(f"\nKey Findings:")
            for key in q["key_findings"].keys():
                status = "✅" if v1_findings[key] else "❌"
                print(f"  {status} {key.replace('_', ' ').title()}")
        
        print(f"\nResponse Preview (first 1000 chars):")
        print(f"{'-'*80}")
        if v1_result["success"]:
            print(v1_result["response"][:1000])
            if len(v1_result["response"]) > 1000:
                print("...")
        else:
            print(f"❌ Error: {v1_result.get('error', 'Unknown')}")
        print(f"{'-'*80}")
        
        print(f"\n{'─'*80}")
        print(f"📊 V2 Results:")
        print(f"{'─'*80}")
        print(f"📚 Citations: {v2_result['citations']}")
        print(f"📝 Response Length: {v2_result['response_length']:,} chars")
        
        if "key_findings" in q and v2_result["success"]:
            v2_findings = analyze_key_findings(v2_result["response"], q["key_findings"])
            v2_inconsistencies = count_inconsistencies(v2_result["response"])
            analysis["v2_key_findings"] = v2_findings
            analysis["v2_inconsistencies"] = v2_inconsistencies
            
            print(f"📊 Inconsistencies Found: {v2_inconsistencies}")
            print(f"\nKey Findings:")
            for key in q["key_findings"].keys():
                status = "✅" if v2_findings[key] else "❌"
                print(f"  {status} {key.replace('_', ' ').title()}")
        
        # Full response display for deep questions
        if q.get("show_full_response") and v2_result["success"]:
            print(f"\nFull Response:")
            print(f"{'-'*80}")
            print(v2_result["response"])
            print(f"{'-'*80}")
        else:
            print(f"\nResponse Preview (first 1000 chars):")
            print(f"{'-'*80}")
            if v2_result["success"]:
                print(v2_result["response"][:1000])
                if len(v2_result["response"]) > 1000:
                    print("...")
            else:
                print(f"❌ Error: {v2_result.get('error', 'Unknown')}")
            print(f"{'-'*80}")
        
        # Keyword scoring
        if v1_result["success"] and v2_result["success"]:
            v1_score = score_keywords(v1_result["response"], q["expected_keywords"])
            v2_score = score_keywords(v2_result["response"], q["expected_keywords"])
            
            analysis["v1_keyword_score"] = v1_score
            analysis["v2_keyword_score"] = v2_score
        
        # Side-by-side comparison for this question
        if v1_result["success"] and v2_result["success"]:
            print(f"\n{'='*80}")
            print(f"📊 SIDE-BY-SIDE COMPARISON - {q['id']}")
            print(f"{'='*80}\n")
            
            print(f"{'Metric':<30} | {'V1 (OpenAI)':>15} | {'V2 (Voyage)':>15} | {'Winner':>10}")
            print(f"{'-'*80}")
            
            # Show inconsistencies and key findings for questions that have them
            if "v1_inconsistencies" in analysis and "v2_inconsistencies" in analysis:
                winner = "V2" if analysis["v2_inconsistencies"] > analysis["v1_inconsistencies"] else "V1" if analysis["v1_inconsistencies"] > analysis["v2_inconsistencies"] else "TIE"
                print(f"{'Inconsistencies Found':<30} | {analysis['v1_inconsistencies']:>15} | {analysis['v2_inconsistencies']:>15} | {winner:>10}")
                
                v1_total = sum(analysis["v1_key_findings"].values())
                v2_total = sum(analysis["v2_key_findings"].values())
                winner = "V2" if v2_total > v1_total else "V1" if v1_total > v2_total else "TIE"
                print(f"{'Total Key Findings':<30} | {v1_total:>15} | {v2_total:>15} | {winner:>10}")
                
                # Show Payment Conflict as Yes/No if it's tracked
                if "payment_conflict" in analysis.get("v1_key_findings", {}):
                    v1_payment = "Yes" if analysis["v1_key_findings"]["payment_conflict"] else "No"
                    v2_payment = "Yes" if analysis["v2_key_findings"]["payment_conflict"] else "No"
                    print(f"{'Payment Conflict Detected':<30} | {v1_payment:>15} | {v2_payment:>15} | {'-':>10}")
            
            winner = "V2" if v2_result["citations"] > v1_result["citations"] else "V1" if v1_result["citations"] > v2_result["citations"] else "TIE"
            print(f"{'Citations':<30} | {v1_result['citations']:>15} | {v2_result['citations']:>15} | {winner:>10}")
            
            print(f"{'Response Length (chars)':<30} | {v1_result['response_length']:>15,} | {v2_result['response_length']:>15,} | {'-':>10}")
            
            winner = "V1" if v1_result["elapsed_seconds"] < v2_result["elapsed_seconds"] else "V2"
            print(f"{'Latency (seconds)':<30} | {v1_result['elapsed_seconds']:>15.1f} | {v2_result['elapsed_seconds']:>15.1f} | {winner:>10}")
            
            # Show keyword score at the end (for all questions)
            if "v1_keyword_score" in analysis:
                winner = "V2" if v2_score["score"] > v1_score["score"] else "V1" if v1_score["score"] > v2_score["score"] else "TIE"
                print(f"{'Keyword Score (%)':<30} | {v1_score['score']:>15.1f} | {v2_score['score']:>15.1f} | {winner:>10}")
            
            # Show detailed key findings comparison table
            if "v1_key_findings" in analysis:
                print(f"\n{'='*80}")
                print(f"KEY FINDINGS COMPARISON")
                print(f"{'='*80}\n")
                print(f"{'Finding':<30} | {'V1':>15} | {'V2':>15}")
                print(f"{'-'*80}")
                for key in q["key_findings"].keys():
                    v1_status = "✅" if analysis["v1_key_findings"][key] else "❌"
                    v2_status = "✅" if analysis["v2_key_findings"][key] else "❌"
                    print(f"{key.replace('_', ' ').title():<30} | {v1_status:>15} | {v2_status:>15}")
            
            # Show detailed inconsistencies list for CONSISTENCY question
            if q["id"] == "CONSISTENCY_DEEP" and v1_result["success"] and v2_result["success"]:
                v1_inconsistencies_list = extract_inconsistencies(v1_result["response"])
                v2_inconsistencies_list = extract_inconsistencies(v2_result["response"])
                
                if v1_inconsistencies_list or v2_inconsistencies_list:
                    print(f"\n{'='*80}")
                    print(f"DETAILED INCONSISTENCIES EXTRACTED")
                    print(f"{'='*80}\n")
                    
                    max_count = max(len(v1_inconsistencies_list), len(v2_inconsistencies_list))
                    
                    print(f"{'#':<3} | {'V1 (OpenAI)':<50} | {'V2 (Voyage)':<50}")
                    print(f"{'-'*110}")
                    
                    for i in range(max_count):
                        num = f"{i+1}."
                        v1_item = v1_inconsistencies_list[i][:47] + "..." if i < len(v1_inconsistencies_list) and len(v1_inconsistencies_list[i]) > 50 else (v1_inconsistencies_list[i] if i < len(v1_inconsistencies_list) else "-")
                        v2_item = v2_inconsistencies_list[i][:47] + "..." if i < len(v2_inconsistencies_list) and len(v2_inconsistencies_list[i]) > 50 else (v2_inconsistencies_list[i] if i < len(v2_inconsistencies_list) else "-")
                        print(f"{num:<3} | {v1_item:<50} | {v2_item:<50}")
                    
                    print(f"\n{'Total':<3} | {len(v1_inconsistencies_list):<50} | {len(v2_inconsistencies_list):<50}")
        
        results.append(analysis)
        await asyncio.sleep(2)
    
    # Overall Summary
    print(f"\n{'='*80}")
    print(f"📊 OVERALL SUMMARY")
    print(f"{'='*80}\n")
    
    v1_total_score = 0
    v2_total_score = 0
    v1_total_citations = 0
    v2_total_citations = 0
    v1_total_time = 0
    v2_total_time = 0
    count = 0
    
    print(f"{'Question ID':<20} | {'V1 Score':>10} | {'V2 Score':>10} | {'Diff':>8} | {'Verdict':>15}")
    print(f"{'-'*80}")
    
    for r in results:
        if "v1_keyword_score" in r and "v2_keyword_score" in r:
            v1_score = r["v1_keyword_score"]["score"]
            v2_score = r["v2_keyword_score"]["score"]
            v1_total_score += v1_score
            v2_total_score += v2_score
            
            if r["v1"]["success"]:
                v1_total_citations += r["v1"]["citations"]
                v1_total_time += r["v1"]["elapsed_seconds"]
            if r["v2"]["success"]:
                v2_total_citations += r["v2"]["citations"]
                v2_total_time += r["v2"]["elapsed_seconds"]
            
            count += 1
            diff = v2_score - v1_score
            
            if diff > 0:
                verdict = "🟢 V2 BETTER"
            elif diff < 0:
                verdict = "🔴 V1 BETTER"
            else:
                verdict = "⚪ TIE"
            
            print(f"{r['question_id']:<20} | {v1_score:>9.0f}% | {v2_score:>9.0f}% | {diff:>+7.0f}% | {verdict:>15}")
    
    if count > 0:
        v1_avg = v1_total_score / count
        v2_avg = v2_total_score / count
        print(f"\n{'─'*80}")
        print(f"{'Average Score':<20} | {v1_avg:>9.1f}% | {v2_avg:>9.1f}% | {v2_avg - v1_avg:>+7.1f}%")
        print(f"{'Total Citations':<20} | {v1_total_citations:>10} | {v2_total_citations:>10}")
        print(f"{'Total Time (s)':<20} | {v1_total_time:>10.1f} | {v2_total_time:>10.1f}")
        print(f"{'─'*80}")
        
        print(f"\n{'='*80}")
        if v2_avg > v1_avg:
            print(f"🏆 V2 WINS by {v2_avg - v1_avg:.1f} percentage points")
            if v2_total_citations > v1_total_citations:
                print(f"   ✨ V2 ADVANTAGE: {v2_total_citations - v1_total_citations} more citations")
        elif v1_avg > v2_avg:
            print(f"🏆 V1 WINS by {v1_avg - v2_avg:.1f} percentage points")
        else:
            print(f"⚪ TIE: Both systems performed equally")
        print(f"{'='*80}")
    
    # Save results
    output_json = f"comprehensive_test_{timestamp}.json"
    output_txt = f"comprehensive_test_{timestamp}.txt"
    
    json_data = {
        "timestamp": timestamp,
        "v1_group": V1_GROUP,
        "v2_group": V2_GROUP,
        "v1_avg_score": v1_avg if count > 0 else 0,
        "v2_avg_score": v2_avg if count > 0 else 0,
        "diff": (v2_avg - v1_avg) if count > 0 else 0,
        "results": results
    }
    
    with open(output_json, 'w') as f:
        json.dump(json_data, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to:")
    print(f"   - {output_json}")
    print(f"   - {output_txt} (tee output)")
    
    # Cleanup
    await v1_pipeline.close()
    await v2_pipeline.close()
    neo4j_driver.close()
    
    print("\n✅ Test Complete\n")


if __name__ == "__main__":
    asyncio.run(main())
