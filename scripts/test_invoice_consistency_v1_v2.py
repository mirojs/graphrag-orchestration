#!/usr/bin/env python3
"""
Test Invoice Consistency Query: V1 vs V2 Side-by-Side Comparison

Runs the exact invoice-contract inconsistency query from the analysis document
on both V1 and V2 groups to validate the alias fix.
"""

import asyncio
import os
import sys
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

from app.core.config import settings
from app.hybrid.orchestrator import HybridPipeline as V1Pipeline
from app.hybrid_v2.orchestrator import HybridPipeline as V2Pipeline, DeploymentProfile
from app.hybrid.router.main import QueryRoute as V1Route
from app.hybrid_v2.router.main import QueryRoute as V2Route

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
V1_GROUP = "invoice-contract-verification"  # V1 unified index with aliases
V2_GROUP = "test-5pdfs-v2-knn-disabled"     # V2 KNN-disabled with manually-added aliases

# The exact query from the analysis
QUERY = "Find inconsistencies between invoice details (amounts, line items, quantities) and contract terms"


def analyze_response(response_text: str) -> dict:
    """Analyze response for key findings."""
    response_lower = response_text.lower()
    
    # Key inconsistencies to detect
    findings = {
        "payment_conflict": any(phrase in response_lower for phrase in [
            "payment", "due date", "installment", "$20,000", "$7,000", "$2,900"
        ]),
        "lift_model": "dumbwaiter" in response_lower or "platform lift" in response_lower,
        "door_hardware": any(phrase in response_lower for phrase in [
            "hall call", "flush", "door", "hardware"
        ]),
        "contoso_mentioned": "contoso" in response_lower,
        "fabrikam_mentioned": "fabrikam" in response_lower,
        "specific_amounts": any(amt in response_text for amt in [
            "$20,000", "$7,000", "$2,900", "$29,900"
        ])
    }
    
    # Count inconsistencies mentioned
    inconsistency_count = 0
    for line in response_text.split('\n'):
        if any(marker in line for marker in ['1.', '2.', '3.', '4.', '5.', '6.', '•', '-']):
            if any(word in line.lower() for word in [
                'inconsist', 'mismatch', 'conflict', 'discrepan', 'differ', 
                'payment', 'invoice', 'contract', 'lift', 'door'
            ]):
                inconsistency_count += 1
    
    return {
        "findings": findings,
        "inconsistency_count": inconsistency_count,
        "total_findings": sum(findings.values()),
        "response_length": len(response_text),
        "has_payment_conflict": findings["payment_conflict"]
    }


async def run_test(pipeline, pipeline_name: str, group_id: str, route) -> dict:
    """Run query on a pipeline."""
    print(f"\n{'='*80}")
    print(f"🔬 Testing: {pipeline_name}")
    print(f"{'='*80}")
    print(f"Group: {group_id}")
    print(f"Query: {QUERY}")
    print()
    
    start_time = datetime.now()
    
    try:
        result = await pipeline.force_route(
            query=QUERY,
            route=route,
            response_type="summary"
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        response = result.get("response", "")
        citations = result.get("citations", [])
        
        # Analysis
        analysis = analyze_response(response)
        
        print(f"✅ Query Complete ({elapsed:.1f}s)")
        print(f"📊 Inconsistencies Found: {analysis['inconsistency_count']}")
        print(f"📚 Citations: {len(citations)}")
        print(f"📝 Response Length: {analysis['response_length']:,} chars")
        print()
        print("Key Findings:")
        for key, found in analysis['findings'].items():
            status = "✅" if found else "❌"
            print(f"  {status} {key.replace('_', ' ').title()}")
        print()
        print("Response Preview (first 1000 chars):")
        print("-" * 80)
        print(response[:1000])
        if len(response) > 1000:
            print("...")
        print("-" * 80)
        
        return {
            "pipeline": pipeline_name,
            "group_id": group_id,
            "response": response,
            "citations": citations,
            "analysis": analysis,
            "elapsed_seconds": elapsed,
            "success": True
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "pipeline": pipeline_name,
            "group_id": group_id,
            "error": str(e),
            "success": False
        }


async def main():
    print("=" * 80)
    print("🧪 INVOICE CONSISTENCY TEST: V1 vs V2")
    print("=" * 80)
    print(f"Query: {QUERY}")
    print()
    
    # Initialize pipelines
    print("Initializing V1 pipeline...")
    v1_pipeline = V1Pipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_client,
        group_id=V1_GROUP
    )
    await v1_pipeline.initialize()
    
    print("Initializing V2 pipeline...")
    v2_pipeline = V2Pipeline(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm_client,
        group_id=V2_GROUP
    )
    await v2_pipeline.initialize()
    
    print("\n" + "=" * 80)
    
    # Run V1
    v1_result = await run_test(v1_pipeline, "V1 (OpenAI)", V1_GROUP, V1Route.DRIFT_MULTI_HOP)
    
    await asyncio.sleep(2)
    
    # Run V2
    v2_result = await run_test(v2_pipeline, "V2 (Voyage + Aliases)", V2_GROUP, V2Route.DRIFT_MULTI_HOP)
    
    # Comparison
    print("\n" + "=" * 80)
    print("📊 SIDE-BY-SIDE COMPARISON")
    print("=" * 80)
    
    if v1_result["success"] and v2_result["success"]:
        v1_a = v1_result["analysis"]
        v2_a = v2_result["analysis"]
        
        print(f"\n{'Metric':<30} | {'V1 (OpenAI)':>15} | {'V2 (Voyage)':>15} | {'Winner':>10}")
        print("-" * 80)
        print(f"{'Inconsistencies Found':<30} | {v1_a['inconsistency_count']:>15} | {v2_a['inconsistency_count']:>15} | {('V1' if v1_a['inconsistency_count'] > v2_a['inconsistency_count'] else 'V2' if v2_a['inconsistency_count'] > v1_a['inconsistency_count'] else 'TIE'):>10}")
        print(f"{'Total Key Findings':<30} | {v1_a['total_findings']:>15} | {v2_a['total_findings']:>15} | {('V1' if v1_a['total_findings'] > v2_a['total_findings'] else 'V2' if v2_a['total_findings'] > v1_a['total_findings'] else 'TIE'):>10}")
        print(f"{'Payment Conflict Detected':<30} | {('Yes' if v1_a['has_payment_conflict'] else 'No'):>15} | {('Yes' if v2_a['has_payment_conflict'] else 'No'):>15} | {('-'):>10}")
        print(f"{'Citations':<30} | {len(v1_result['citations']):>15} | {len(v2_result['citations']):>15} | {('-'):>10}")
        print(f"{'Response Length (chars)':<30} | {v1_a['response_length']:>15,} | {v2_a['response_length']:>15,} | {('-'):>10}")
        print(f"{'Latency (seconds)':<30} | {v1_result['elapsed_seconds']:>15.1f} | {v2_result['elapsed_seconds']:>15.1f} | {('V1' if v1_result['elapsed_seconds'] < v2_result['elapsed_seconds'] else 'V2'):>10}")
        
        print("\n" + "=" * 80)
        print("KEY FINDINGS COMPARISON")
        print("=" * 80)
        print(f"\n{'Finding':<30} | {'V1':>15} | {'V2':>15}")
        print("-" * 80)
        for key in v1_a['findings'].keys():
            v1_status = "✅" if v1_a['findings'][key] else "❌"
            v2_status = "✅" if v2_a['findings'][key] else "❌"
            print(f"{key.replace('_', ' ').title():<30} | {v1_status:>15} | {v2_status:>15}")
        
        # Winner determination
        print("\n" + "=" * 80)
        v2_better = v2_a['inconsistency_count'] > v1_a['inconsistency_count']
        v1_better = v1_a['inconsistency_count'] > v2_a['inconsistency_count']
        
        if v2_better:
            print("🏆 V2 WINS: Found more inconsistencies after alias fix")
        elif v1_better:
            print("🏆 V1 WINS: Found more inconsistencies")
        else:
            print("🏆 TIE: Both found same number of inconsistencies")
        
        if v2_a['has_payment_conflict'] and not v1_a['has_payment_conflict']:
            print("   ✨ V2 FIXED: Now detects payment conflict (key improvement)")
        elif not v2_a['has_payment_conflict'] and v1_a['has_payment_conflict']:
            print("   ⚠️  V2 REGRESSION: Missed payment conflict")
        elif v2_a['has_payment_conflict'] and v1_a['has_payment_conflict']:
            print("   ✅ BOTH: Correctly detect payment conflict")
        
    # Cleanup
    await v1_pipeline.close()
    await v2_pipeline.close()
    
    print("\n✅ Test Complete")


if __name__ == "__main__":
    asyncio.run(main())
