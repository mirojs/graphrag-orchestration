#!/usr/bin/env python3
"""
Route 4 V1 vs V2 Invoice-Contract Consistency Test Script

This script tests both V1 and V2 pipelines on the invoice-contract consistency
query to compare their performance and accuracy.

Usage:
    python scripts/test_route4_v1_v2_invoice_consistency.py

Both pipelines require:
    - A sync neo4j_driver (from neo4j.GraphDatabase.driver)
    - The correct group_id for each version

Results are saved to /tmp/v1_response.txt and /tmp/v2_response.txt

Created: 2026-01-29
"""

import asyncio
import os
import re
from datetime import datetime
from dotenv import load_dotenv

# Load environment
load_dotenv('.env')

from app.core.config import settings

# Create sync neo4j driver - REQUIRED for both V1 and V2
from neo4j import GraphDatabase

neo4j_driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
)

# Import pipelines
from app.hybrid.orchestrator import HybridPipeline as V1Pipeline
from app.hybrid_v2.orchestrator import HybridPipeline as V2Pipeline

# Import text_unit_store for V1
from app.services.neo4j_text_unit_store import Neo4jTextUnitStore

from llama_index.llms.azure_openai import AzureOpenAI as LlamaIndexAzureOpenAI

# LLM client
llm_client = LlamaIndexAzureOpenAI(
    engine=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version="2024-08-01-preview"
)

# Group IDs
V1_GROUP = "test-5pdfs-1769071711867955961"  # OpenAI embeddings
V2_GROUP = "test-5pdfs-v2-knn-disabled"      # Voyage embeddings + aliases

# The original 3-part invoice consistency query
QUERY = """List all areas of inconsistency identified in the invoice, organized by: (1) all inconsistencies with corresponding evidence, (2) inconsistencies in goods or services sold including detailed specifications for every line item, and (3) inconsistencies regarding billing logistics and administrative or legal issues."""


async def test_v1():
    """Run V1 pipeline on the invoice consistency query."""
    print("\n" + "="*80)
    print("V1 TEST (app/hybrid/orchestrator.py)")
    print(f"Group: {V1_GROUP}")
    print("="*80)
    
    start = datetime.now()
    
    # V1 requires text_unit_store for synthesis
    text_store = Neo4jTextUnitStore(neo4j_driver, group_id=V1_GROUP)
    
    pipeline = V1Pipeline(
        group_id=V1_GROUP,
        llm_client=llm_client,
        neo4j_driver=neo4j_driver,
        text_unit_store=text_store
    )
    await pipeline.initialize()
    
    result = await pipeline._execute_route_4_drift(QUERY, response_type="summary")
    response_text = result.get("response", str(result))
    
    elapsed = (datetime.now() - start).total_seconds()
    
    # Count citations
    citations = re.findall(r'\[\d+\]', response_text)
    unique_citations = set(citations)
    
    print(f"\nV1 Latency: {elapsed:.1f}s")
    print(f"V1 Response Length: {len(response_text)} chars")
    print(f"V1 Citations: {len(unique_citations)}")
    
    with open("/tmp/v1_response.txt", "w") as f:
        f.write(response_text)
    print("V1 response saved to /tmp/v1_response.txt")
    
    await pipeline.close()
    
    return {
        "latency": elapsed,
        "response_length": len(response_text),
        "citations": len(unique_citations),
        "response": response_text
    }


async def test_v2():
    """Run V2 pipeline on the invoice consistency query."""
    print("\n" + "="*80)
    print("V2 TEST (app/hybrid_v2/orchestrator.py)")
    print(f"Group: {V2_GROUP}")
    print("="*80)
    
    start = datetime.now()
    
    pipeline = V2Pipeline(
        group_id=V2_GROUP,
        llm_client=llm_client,
        neo4j_driver=neo4j_driver  # REQUIRED - same as V1
    )
    await pipeline.initialize()
    
    result = await pipeline._execute_route_4_drift(QUERY, response_type="summary")
    response_text = result.get("response", str(result))
    
    elapsed = (datetime.now() - start).total_seconds()
    
    # Count citations
    citations = re.findall(r'\[\d+\]', response_text)
    unique_citations = set(citations)
    
    print(f"\nV2 Latency: {elapsed:.1f}s")
    print(f"V2 Response Length: {len(response_text)} chars")
    print(f"V2 Citations: {len(unique_citations)}")
    
    with open("/tmp/v2_response.txt", "w") as f:
        f.write(response_text)
    print("V2 response saved to /tmp/v2_response.txt")
    
    await pipeline.close()
    
    return {
        "latency": elapsed,
        "response_length": len(response_text),
        "citations": len(unique_citations),
        "response": response_text
    }


def check_key_findings(response: str, version: str) -> dict:
    """Check if response contains key expected findings."""
    findings = {
        "savaria_v1504": "savaria" in response.lower() and "v1504" in response.lower(),
        "ascendpro_vpx200": "ascendpro" in response.lower() and "vpx200" in response.lower(),
        "amount_29900": "29,900" in response or "29900" in response,
        "fabrikam_mismatch": "fabrikam inc" in response.lower() and "fabrikam construction" in response.lower(),
        "flush_mount": "flush" in response.lower() and "mount" in response.lower(),
        "outdoor_config": "outdoor" in response.lower() and ("configuration" in response.lower() or "fitting" in response.lower()),
        "wr_500_lock": "wr-500" in response.lower() or "wr500" in response.lower(),
        "payment_installment": "20,000" in response or "20000" in response,
    }
    
    found = sum(1 for v in findings.values() if v)
    total = len(findings)
    
    print(f"\n{version} Key Findings Check ({found}/{total}):")
    for key, found_flag in findings.items():
        status = "✓" if found_flag else "✗"
        print(f"  {status} {key}")
    
    return findings


async def main():
    """Run both V1 and V2 tests and compare results."""
    print("="*80)
    print("ROUTE 4 V1 VS V2 INVOICE-CONTRACT CONSISTENCY TEST")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print(f"\nQuery: {QUERY[:100]}...")
    
    # Run V1
    v1_results = await test_v1()
    v1_findings = check_key_findings(v1_results["response"], "V1")
    
    # Run V2
    v2_results = await test_v2()
    v2_findings = check_key_findings(v2_results["response"], "V2")
    
    # Summary comparison
    print("\n" + "="*80)
    print("COMPARISON SUMMARY")
    print("="*80)
    print(f"{'Metric':<25} {'V1':<15} {'V2':<15} {'Diff':<15}")
    print("-"*70)
    print(f"{'Latency (s)':<25} {v1_results['latency']:<15.1f} {v2_results['latency']:<15.1f} {v2_results['latency'] - v1_results['latency']:+.1f}")
    print(f"{'Response Length':<25} {v1_results['response_length']:<15} {v2_results['response_length']:<15} {v2_results['response_length'] - v1_results['response_length']:+}")
    print(f"{'Citations':<25} {v1_results['citations']:<15} {v2_results['citations']:<15} {v2_results['citations'] - v1_results['citations']:+}")
    
    v1_findings_count = sum(1 for v in v1_findings.values() if v)
    v2_findings_count = sum(1 for v in v2_findings.values() if v)
    print(f"{'Key Findings':<25} {v1_findings_count}/8{'':<10} {v2_findings_count}/8{'':<10}")
    
    # Cleanup
    neo4j_driver.close()
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
