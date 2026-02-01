#!/usr/bin/env python3
"""
Local KNN Benchmark - Direct Neo4j testing without API deployment.

Tests the KNN edge filtering by directly calling the semantic_multihop_beam
function with different knn_config values.
"""

import asyncio
import os
import sys
from typing import List, Tuple

# Add src to path for local imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from neo4j import AsyncGraphDatabase
import numpy as np


# Configuration
BASELINE_GROUP = "test-5pdfs-v2-enhanced-ex"

KNN_CONFIGS = [
    {"knn_config": None, "name": "Baseline (No KNN)"},
    {"knn_config": "knn-1", "name": "KNN-1 (K=3, cutoff=0.80)"},
    {"knn_config": "knn-2", "name": "KNN-2 (K=5, cutoff=0.75)"},
    {"knn_config": "knn-3", "name": "KNN-3 (K=5, cutoff=0.85)"},
]

# Test seed entities (common entities from invoice/contract analysis)
TEST_SEEDS = ["PURCHASE CONTRACT", "Fabrikam Inc.", "Payment Terms"]


async def get_driver():
    """Create Neo4j driver from environment."""
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    return AsyncGraphDatabase.driver(uri, auth=(user, password))


async def get_seed_ids(session, group_id: str, seed_names: List[str]) -> List[dict]:
    """Resolve seed names to entity IDs."""
    result = await session.run("""
        UNWIND $names AS name
        MATCH (e:Entity {group_id: $gid})
        WHERE toLower(e.name) CONTAINS toLower(name)
        RETURN e.id AS id, e.name AS name, e.embedding_v2 AS embedding
        LIMIT 10
    """, names=seed_names, gid=group_id)
    return await result.data()


async def trace_with_knn_config(
    session, 
    group_id: str, 
    seed_ids: List[str],
    query_embedding: List[float],
    knn_config: str = None,
    max_hops: int = 2,
    beam_width: int = 10,
) -> List[Tuple[str, int]]:
    """
    Manually trace multi-hop with KNN config filtering.
    
    Returns list of (entity_name, hop_found) tuples.
    """
    if knn_config:
        # Include SEMANTICALLY_SIMILAR edges with matching knn_config
        hop_query = """
        UNWIND $current_ids AS eid
        MATCH (src:Entity {id: eid})-[r]-(neighbor:Entity)
        WHERE neighbor.group_id = $gid
          AND type(r) <> 'MENTIONS'
          AND (
              type(r) <> 'SEMANTICALLY_SIMILAR' 
              OR r.knn_config = $knn_config
          )
          AND neighbor.embedding_v2 IS NOT NULL
        WITH DISTINCT neighbor
        RETURN neighbor.id AS id, neighbor.name AS name
        LIMIT $beam_width
        """
    else:
        # Baseline: exclude all SEMANTICALLY_SIMILAR edges
        hop_query = """
        UNWIND $current_ids AS eid
        MATCH (src:Entity {id: eid})-[r]-(neighbor:Entity)
        WHERE neighbor.group_id = $gid
          AND type(r) <> 'MENTIONS'
          AND type(r) <> 'SEMANTICALLY_SIMILAR'
          AND neighbor.embedding_v2 IS NOT NULL
        WITH DISTINCT neighbor
        RETURN neighbor.id AS id, neighbor.name AS name
        LIMIT $beam_width
        """
    
    visited = set(seed_ids)
    current_ids = list(seed_ids)
    all_found = [(eid, 0) for eid in seed_ids]  # Seeds at hop 0
    
    for hop in range(1, max_hops + 1):
        if not current_ids:
            break
        
        params = {
            "current_ids": current_ids,
            "gid": group_id,
            "beam_width": beam_width,
        }
        if knn_config:
            params["knn_config"] = knn_config
        
        result = await session.run(hop_query, **params)
        records = await result.data()
        
        next_ids = []
        for r in records:
            if r["id"] not in visited:
                visited.add(r["id"])
                next_ids.append(r["id"])
                all_found.append((r["name"], hop))
        
        current_ids = next_ids
    
    return all_found


async def main():
    print("=" * 70)
    print("Local KNN Benchmark - Direct Neo4j Testing")
    print("=" * 70)
    
    driver = await get_driver()
    
    async with driver.session() as session:
        # Step 1: Verify KNN edges
        print("\n📊 KNN Edge Counts:")
        result = await session.run("""
            MATCH (e1:Entity {group_id: $gid})-[r:SEMANTICALLY_SIMILAR]->(e2:Entity)
            RETURN r.knn_config AS config, count(r) AS cnt
            ORDER BY config
        """, gid=BASELINE_GROUP)
        for r in await result.data():
            print(f"  {r['config']}: {r['cnt']} edges")
        
        # Step 2: Resolve seed entities
        print(f"\n🌱 Resolving seeds: {TEST_SEEDS}")
        seeds = await get_seed_ids(session, BASELINE_GROUP, TEST_SEEDS)
        if not seeds:
            print("  ERROR: No seeds found!")
            return
        
        seed_ids = [s["id"] for s in seeds]
        print(f"  Found {len(seeds)} seed entities:")
        for s in seeds[:5]:
            print(f"    - {s['name']}")
        
        # Get a query embedding from first seed
        query_embedding = seeds[0]["embedding"] if seeds[0].get("embedding") else None
        
        # Step 3: Test each KNN configuration
        print("\n" + "=" * 70)
        print("🧪 Testing KNN Configurations")
        print("=" * 70)
        
        for cfg in KNN_CONFIGS:
            knn_config = cfg["knn_config"]
            name = cfg["name"]
            
            print(f"\n  [{name}]")
            
            found = await trace_with_knn_config(
                session,
                BASELINE_GROUP,
                seed_ids,
                query_embedding,
                knn_config=knn_config,
                max_hops=2,
                beam_width=20,
            )
            
            hop_counts = {}
            for entity, hop in found:
                hop_counts[hop] = hop_counts.get(hop, 0) + 1
            
            total = len(found)
            print(f"    Total entities reached: {total}")
            for hop in sorted(hop_counts.keys()):
                print(f"      Hop {hop}: {hop_counts[hop]} entities")
            
            # Show some example entities found at hop 1+
            new_entities = [e for e, h in found if h > 0][:5]
            if new_entities:
                print(f"    Sample new entities: {new_entities}")
        
        # Step 4: Compare unique entities found
        print("\n" + "=" * 70)
        print("📈 Comparison Summary")
        print("=" * 70)
        
        results = []
        for cfg in KNN_CONFIGS:
            found = await trace_with_knn_config(
                session,
                BASELINE_GROUP,
                seed_ids,
                query_embedding,
                knn_config=cfg["knn_config"],
                max_hops=2,
                beam_width=20,
            )
            results.append({
                "name": cfg["name"],
                "total": len(found),
                "entities": set(e for e, _ in found)
            })
        
        print("\n| Config | Entities | vs Baseline |")
        print("|--------|----------|-------------|")
        baseline_count = results[0]["total"]
        baseline_entities = results[0]["entities"]
        for r in results:
            diff = r["total"] - baseline_count
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            print(f"| {r['name'][:25]:<25} | {r['total']:>8} | {diff_str:>11} |")
        
        # Show entities unique to KNN configs
        print("\n🔍 Entities unique to each KNN config (not in baseline):")
        for i, r in enumerate(results[1:], 1):  # Skip baseline
            unique = r["entities"] - baseline_entities
            if unique:
                print(f"  {r['name']}: {len(unique)} unique entities")
                for e in list(unique)[:3]:
                    print(f"    - {e}")
    
    await driver.close()
    print("\n✅ Local benchmark complete!")


if __name__ == "__main__":
    asyncio.run(main())
