#!/usr/bin/env python3
"""Test script for sentence-level comprehensive mode."""

import asyncio
import os
import sys

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(app_root, '.env'))

from neo4j import GraphDatabase
from src.worker.hybrid_v2.indexing.text_store import Neo4jTextUnitStore
from src.worker.hybrid_v2.pipeline.synthesis import EvidenceSynthesizer
from src.worker.services.llm_service import LLMService


def log(msg: str) -> None:
    print(msg, flush=True)


async def main():
    log("=" * 70)
    log("SENTENCE-LEVEL COMPREHENSIVE MODE TEST")
    log("=" * 70)
    
    # Setup
    driver = GraphDatabase.driver(
        os.getenv('NEO4J_URI'),
        auth=(os.getenv('NEO4J_USERNAME'), os.getenv('NEO4J_PASSWORD')),
    )
    
    group_id = 'test-5pdfs-v2-fix2'
    text_store = Neo4jTextUnitStore(driver, group_id=group_id)
    llm_service = LLMService()
    llm = llm_service.get_synthesis_llm()
    
    synthesizer = EvidenceSynthesizer(
        llm_client=llm,
        text_unit_store=text_store,
        relevance_budget=0.8
    )
    
    # Test query
    query = 'Analyze the invoice and contract documents to find all inconsistencies between invoice details (amounts, line items, quantities, payment terms) and the corresponding contract terms.'
    
    log(f"\nQuery: {query}")
    log(f"Group ID: {group_id}")
    log("")
    
    # Run sentence-level mode
    log("Running comprehensive_sentence mode...")
    result = await synthesizer._comprehensive_sentence_level_extract(
        query=query,
        text_chunks=[],
        evidence_nodes=[]
    )
    
    response = result.get('response', '')
    sentence_stats = result.get('sentence_stats', {})
    
    log(f"\nProcessing mode: {result.get('processing_mode')}")
    log(f"Sentence stats: {sentence_stats}")
    log(f"Response length: {len(response)} chars")
    
    # Check ground truth items
    check_patterns = [
        ('payment terms', 'installment'),
        ('model', 'savaria'),
        ('lock', 'wr-500'),
        ('motor', 'elite'),
        ('address', 'installation'),
        ('customer id', '4905201'),
        ('po', '30060204'),
        ('date', '2015'),
        ('warranty',),
        ('shipping', 'freight'),
        ('due', 'signing'),
        ('requisitioner', 'jim'),
        ('contact', 'phone'),
        ('tax',),
        ('delivery', '60'),
        ('return',),
    ]
    
    response_lower = response.lower()
    found_items = []
    
    for i, patterns in enumerate(check_patterns):
        if all(p in response_lower for p in patterns):
            found_items.append(i)
    
    log(f"\n{'='*70}")
    log(f"GROUND TRUTH COVERAGE: {len(found_items)}/16 ({100*len(found_items)/16:.1f}%)")
    log(f"{'='*70}")
    log(f"Found indices: {found_items}")
    log(f"Missing indices: {[i for i in range(16) if i not in found_items]}")
    
    # Show missing items
    ground_truth_names = [
        "Payment Terms / Installments",
        "Model Number (Savaria)",
        "Lock Type (WR-500)",
        "Motor Specs (Elite)",
        "Installation Address",
        "Customer ID (4905201)",
        "PO Number (30060204)",
        "Document Dates (2015)",
        "Warranty",
        "Shipping (Freight)",
        "Due on Signing",
        "Requisitioner (Jim)",
        "Contact/Phone",
        "Tax",
        "Delivery (60 days)",
        "Return Policy",
    ]
    
    log("\nMissing items:")
    for i in range(16):
        if i not in found_items:
            log(f"  - [{i}] {ground_truth_names[i]}")
    
    # Print full response
    log("\n" + "=" * 70)
    log("FULL RESPONSE:")
    log("=" * 70)
    print(response)
    
    driver.close()


if __name__ == "__main__":
    asyncio.run(main())
