#!/usr/bin/env python3
"""
Debug script to trace why PPR is returning fewer entities/chunks for Q-D3.
Compares current behavior against the 0.80 baseline expectations.
"""

import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

from src.worker.services.async_neo4j_service import AsyncNeo4jService

GROUP_ID = "test-5pdfs-1768557493369886422"
Q_D3_QUERY = 'Compare "time windows" across the set: list all explicit day-based timeframes.'


async def step1_get_seed_entities():
    """Step 1: Query embedding + get seed entities from BM25."""
    print("\n" + "="*80)
    print("STEP 1: Get seed entities for Q-D3")
    print("="*80)
    
    async with AsyncNeo4jService.from_settings() as neo4j:
        # Get BM25 seed entities (mimics Stage 1 in Route 4)
        query = """
        CALL db.index.fulltext.queryNodes(
            'entity_name_description_index',
            $query_text
        ) YIELD node, score
        WHERE node.group_id = $group_id
        RETURN node.id AS id,
               node.name AS name,
               node.description AS description,
               score
        ORDER BY score DESC
        LIMIT 10
        """
        
        async with neo4j._get_session() as session:
            result = await session.run(
                query,
                group_id=GROUP_ID,
                query_text=Q_D3_QUERY
            )
            records = await result.data()
        
        print(f"Found {len(records)} seed entities:")
        for i, r in enumerate(records, 1):
            print(f"  {i}. {r['name']} (score={r['score']:.4f})")
            if r['description']:
                print(f"     Description: {r['description'][:100]}...")
        
        seed_ids = [r['id'] for r in records]
        return seed_ids


async def step2_run_ppr_entity_only(seed_ids):
    """Step 2: Run entity-only PPR."""
    print("\n" + "="*80)
    print("STEP 2: Run Entity-Only PPR (include_section_graph=False)")
    print("="*80)
    
    async with AsyncNeo4jService.from_settings() as neo4j:
        results = await neo4j.personalized_pagerank_native(
            group_id=GROUP_ID,
            seed_entity_ids=seed_ids,
            top_k=20,
            per_seed_limit=25,
            per_neighbor_limit=10,
            include_section_graph=False,
        )
        
        print(f"PPR returned {len(results)} entities:")
        for i, (name, score) in enumerate(results[:15], 1):
            print(f"  {i}. {name} (score={score:.4f})")
        
        return [name for name, _ in results]


async def step3_run_ppr_with_section_graph(seed_ids):
    """Step 3: Run PPR with section graph."""
    print("\n" + "="*80)
    print("STEP 3: Run PPR with Section Graph (include_section_graph=True)")
    print("="*80)
    
    async with AsyncNeo4jService.from_settings() as neo4j:
        results = await neo4j.personalized_pagerank_native(
            group_id=GROUP_ID,
            seed_entity_ids=seed_ids,
            top_k=20,
            per_seed_limit=25,
            per_neighbor_limit=10,
            include_section_graph=True,
        )
        
        print(f"PPR returned {len(results)} entities:")
        for i, (name, score) in enumerate(results[:15], 1):
            print(f"  {i}. {name} (score={score:.4f})")
        
        return [name for name, _ in results]


async def step4_get_chunks_for_entities(entity_names):
    """Step 4: Get chunks for the PPR entities."""
    print("\n" + "="*80)
    print("STEP 4: Get chunks for PPR entities")
    print("="*80)
    
    async with AsyncNeo4jService.from_settings() as neo4j:
        # Convert names to IDs
        query = """
        UNWIND $names AS name
        MATCH (e {name: name})
        WHERE e.group_id = $group_id
          AND (e:Entity OR e:`__Entity__`)
        RETURN DISTINCT e.id AS id
        """
        
        async with neo4j._get_session() as session:
            result = await session.run(query, group_id=GROUP_ID, names=entity_names)
            records = await result.data()
        
        entity_ids = [r['id'] for r in records]
        print(f"Converted {len(entity_names)} entity names → {len(entity_ids)} entity IDs")
        
        # Get chunks
        chunks = await neo4j.get_chunks_for_entities(
            group_id=GROUP_ID,
            entity_ids=entity_ids,
            limit=50,
        )
        
        print(f"Retrieved {len(chunks)} chunks")
        
        # Count unique documents
        doc_ids = set()
        for chunk in chunks:
            if 'document_id' in chunk:
                doc_ids.add(chunk['document_id'])
        
        print(f"From {len(doc_ids)} unique documents:")
        for doc_id in sorted(doc_ids):
            chunk_count = sum(1 for c in chunks if c.get('document_id') == doc_id)
            print(f"  - {doc_id}: {chunk_count} chunks")
        
        return chunks


async def step5_check_baseline_expectations():
    """Step 5: Check what we SHOULD have found (from 0.80 baseline)."""
    print("\n" + "="*80)
    print("STEP 5: Expected Results from 0.80 Baseline")
    print("="*80)
    
    # Load the 0.80 baseline
    baseline_path = "benchmarks/route4_drift_multi_hop_20260117T081731Z.json"
    if not os.path.exists(baseline_path):
        print(f"⚠ Baseline file not found: {baseline_path}")
        return
    
    with open(baseline_path) as f:
        data = json.load(f)
    
    q_d3 = data['scenario']['questions'][0]  # Q-D3 is first question
    run1 = q_d3['runs'][0]
    
    print(f"Baseline had {len(set(run1['citations_sig']))} unique citations")
    
    # Extract document names
    docs = set()
    for cit in run1['citations_sig']:
        doc_name = cit.split(' — ')[0]
        docs.add(doc_name)
    
    print(f"From {len(docs)} documents:")
    for doc in sorted(docs):
        count = sum(1 for c in run1['citations_sig'] if c.startswith(doc))
        print(f"  - {doc}: {count} citations")


async def main():
    """Run full diagnostic trace."""
    print("="*80)
    print("Q-D3 RETRIEVAL COVERAGE DEBUG")
    print("="*80)
    print(f"Corpus: {GROUP_ID}")
    print(f"Query: {Q_D3_QUERY}")
    
    # Step 5 first (expectations)
    await step5_check_baseline_expectations()
    
    # Steps 1-4 (current behavior)
    seed_ids = await step1_get_seed_entities()
    
    entity_names_only = await step2_run_ppr_entity_only(seed_ids)
    chunks_only = await step4_get_chunks_for_entities(entity_names_only)
    
    entity_names_section = await step3_run_ppr_with_section_graph(seed_ids)
    chunks_section = await step4_get_chunks_for_entities(entity_names_section)
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Baseline (0.80):  20 citations from 8 documents")
    print(f"Entity-only PPR:  {len(chunks_only)} chunks from PPR")
    print(f"Section PPR:      {len(chunks_section)} chunks from PPR")
    print()
    print("⚠ If current runs show dramatically fewer chunks, there's a bug in either:")
    print("   1. Seed entity discovery (BM25)")
    print("   2. PPR expansion logic")
    print("   3. Chunk retrieval")


if __name__ == "__main__":
    asyncio.run(main())
