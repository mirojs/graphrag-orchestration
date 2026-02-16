#!/usr/bin/env python3
"""Diagnose vector index group isolation and test pre-filtered vector search.

This script:
1. Reports the Neo4j server version
2. Shows how many entities exist per group in the vector index
3. Tests the CURRENT post-filter approach (top_k → filter → may get 0 results)
4. Tests whether pre-filtered vector search is supported (Neo4j 2025.x)
5. Compares results and latency between approaches
6. (Optional) Tests creating a per-group filtered index

Usage:
    python scripts/diagnose_vector_isolation.py                         # uses env vars
    python scripts/diagnose_vector_isolation.py --group test-5pdfs-v2-fix2

Environment:
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE (optional)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from neo4j import AsyncGraphDatabase

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────

def get_config():
    """Load Neo4j connection config from environment."""
    return {
        "uri": os.environ.get("NEO4J_URI"),
        "username": os.environ.get("NEO4J_USERNAME"),
        "password": os.environ.get("NEO4J_PASSWORD"),
        "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
    }


# ── Helpers ───────────────────────────────────────────────────────

async def run_query(session, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    result = await session.run(query, parameters=params or {})
    return await result.data()


def fmt_results(records: List[Dict], max_rows: int = 10) -> str:
    if not records:
        return "  (no results)"
    lines = []
    for i, r in enumerate(records[:max_rows]):
        lines.append(f"  [{i+1}] {r}")
    if len(records) > max_rows:
        lines.append(f"  ... and {len(records) - max_rows} more")
    return "\n".join(lines)


# ── Test Functions ────────────────────────────────────────────────

async def test_server_version(session) -> str:
    """Report Neo4j server version."""
    records = await run_query(session, "CALL dbms.components() YIELD name, versions RETURN name, versions")
    if records:
        version_info = records[0]
        versions = version_info.get("versions", ["unknown"])
        version = versions[0] if versions else "unknown"
        print(f"\n{'='*60}")
        print(f"Neo4j Server: {version_info.get('name', 'unknown')} v{version}")
        print(f"{'='*60}")
        return version
    return "unknown"


async def test_entity_distribution(session, index_name: str = "entity_embedding_v2") -> Dict[str, int]:
    """Show how many entities exist per group in the vector index."""
    print(f"\n── Entity Distribution in Vector Index ──")
    
    # Count entities per group (only those with embeddings = those in the index)
    query = """
    MATCH (e:Entity)
    WHERE e.embedding_v2 IS NOT NULL
    RETURN e.group_id AS group_id, count(*) AS count
    ORDER BY count DESC
    """
    records = await run_query(session, query)
    
    total = 0
    distribution: Dict[str, int] = {}
    for r in records:
        gid = r["group_id"]
        cnt = r["count"]
        distribution[gid] = cnt
        total += cnt
        pct = cnt / max(total, 1) * 100
    
    # Print distribution
    for gid, cnt in sorted(distribution.items(), key=lambda x: -x[1]):
        pct = cnt / total * 100 if total > 0 else 0
        print(f"  {gid:40s}  {cnt:5d} entities  ({pct:5.1f}%)")
    print(f"  {'TOTAL':40s}  {total:5d} entities")
    
    # Also check EntityArchived
    archived_query = """
    MATCH (e:EntityArchived)
    RETURN count(*) AS count
    """
    archived = await run_query(session, archived_query)
    if archived and archived[0]["count"] > 0:
        print(f"  {'ARCHIVED (EntityArchived label)':40s}  {archived[0]['count']:5d} entities")
    
    return distribution


async def test_post_filter_approach(
    session, group_id: str, embedding: List[float], top_k: int = 3
) -> List[Dict]:
    """Test the CURRENT approach: global top-k → post-filter by group_id."""
    print(f"\n── Test 1: Post-Filter Approach (current production) ──")
    
    for oversample_factor in [3, 10, 50, 100]:
        top_k_oversample = top_k * oversample_factor
        query = f"""
        CALL db.index.vector.queryNodes('entity_embedding_v2', $top_k_oversample, $embedding)
        YIELD node, score
        WHERE node.group_id = $group_id
        RETURN node.name AS name, node.group_id AS gid, score
        ORDER BY score DESC
        LIMIT $top_k
        """
        t0 = time.perf_counter()
        records = await run_query(session, query, {
            "embedding": embedding,
            "top_k_oversample": top_k_oversample,
            "group_id": group_id,
            "top_k": top_k,
        })
        elapsed_ms = (time.perf_counter() - t0) * 1000
        
        print(f"\n  oversample={oversample_factor}x (fetch {top_k_oversample}, want {top_k})  [{elapsed_ms:.1f}ms]")
        if records:
            for r in records:
                print(f"    ✓ {r['name']} (score={r['score']:.4f})")
        else:
            print(f"    ✗ 0 results — group's entities didn't make it into top-{top_k_oversample}")
    
    return records


async def test_post_filter_ranking(
    session, group_id: str, embedding: List[float]
) -> Optional[int]:
    """Find what rank the FIRST entity from our group appears at."""
    print(f"\n── Test 2: Where does our group first appear in global ranking? ──")
    
    query = """
    CALL db.index.vector.queryNodes('entity_embedding_v2', 500, $embedding)
    YIELD node, score
    WITH node, score, 
         CASE WHEN node.group_id = $group_id THEN true ELSE false END AS is_ours
    RETURN node.name AS name, node.group_id AS gid, score, is_ours
    ORDER BY score DESC
    """
    records = await run_query(session, query, {
        "embedding": embedding,
        "group_id": group_id,
    })
    
    first_rank = None
    total_ours = 0
    for i, r in enumerate(records):
        if r["is_ours"]:
            total_ours += 1
            if first_rank is None:
                first_rank = i + 1
                print(f"  First result from group '{group_id}': rank {first_rank} / {len(records)}")
                print(f"    → {r['name']} (score={r['score']:.4f})")
    
    if first_rank is None:
        print(f"  ✗ Group '{group_id}' has NO entities in top-500 results!")
    else:
        print(f"  Total from our group in top-500: {total_ours}")
        print(f"  Implication: oversampling must be >= {first_rank} to get even 1 result")
    
    return first_rank


async def test_prefiltered_vector_search(
    session, group_id: str, embedding: List[float], top_k: int = 3
) -> Optional[List[Dict]]:
    """Test Neo4j 2025.x pre-filtered vector search.
    
    In Neo4j 2025.x, the Cypher planner can push WHERE predicates into the
    vector index scan when the property has a supporting range/text index.
    This requires:
    1. A range index on Entity.group_id (for the predicate push-down)
    2. Neo4j 2025.x runtime
    
    We test progressively:
    A) Standard db.index.vector.queryNodes with WHERE (planner may or may not push down)
    B) Cypher 25 vector search syntax (if available)
    """
    print(f"\n── Test 3: Pre-Filtered Vector Search (Neo4j 2025.x) ──")
    
    # Test A: Check if a range index on Entity.group_id exists
    print("\n  Checking for range index on Entity.group_id...")
    index_query = """
    SHOW INDEXES
    YIELD name, type, labelsOrTypes, properties
    WHERE 'Entity' IN labelsOrTypes AND 'group_id' IN properties
    RETURN name, type, labelsOrTypes, properties
    """
    try:
        indexes = await run_query(session, index_query)
        if indexes:
            for idx in indexes:
                print(f"    Found: {idx['name']} ({idx['type']}) on {idx['labelsOrTypes']}.{idx['properties']}")
        else:
            print("    ✗ No range/text index on Entity.group_id found")
            print("    → Creating one would enable the planner to push the filter into the vector scan")
            print("    → Run: CREATE INDEX entity_group_id IF NOT EXISTS FOR (e:Entity) ON (e.group_id)")
    except Exception as e:
        print(f"    Error checking indexes: {e}")
    
    # Test B: Try the vector search with Cypher 25 prefix
    # In Neo4j 2025.x, the planner should detect that group_id has a range index
    # and push the WHERE predicate into the vector index scan, making it a
    # pre-filtered search rather than a post-filter.
    print("\n  Testing vector search with WHERE group_id filter...")
    
    # Standard approach — but with Cypher 25 the planner may optimize this
    query_standard = """
    CALL db.index.vector.queryNodes('entity_embedding_v2', $top_k, $embedding)
    YIELD node, score
    WHERE node.group_id = $group_id
    RETURN node.name AS name, score
    ORDER BY score DESC
    LIMIT $top_k
    """
    
    # Cypher 25 variant with explicit runtime
    query_cypher25 = """
    CYPHER 25
    CALL db.index.vector.queryNodes('entity_embedding_v2', $top_k, $embedding)
    YIELD node, score
    WHERE node.group_id = $group_id
    RETURN node.name AS name, score
    ORDER BY score DESC
    LIMIT $top_k
    """
    
    results_standard = None
    results_cypher25 = None
    
    # Test standard
    try:
        t0 = time.perf_counter()
        results_standard = await run_query(session, query_standard, {
            "embedding": embedding,
            "top_k": top_k,
            "group_id": group_id,
        })
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  Standard (top_k={top_k}, no oversample): [{elapsed:.1f}ms]")
        if results_standard:
            for r in results_standard:
                print(f"    ✓ {r['name']} (score={r['score']:.4f})")
        else:
            print(f"    ✗ 0 results (WHERE filter applied AFTER top-k, not pushed down)")
    except Exception as e:
        print(f"    Error: {e}")
    
    # Test Cypher 25
    try:
        t0 = time.perf_counter()
        results_cypher25 = await run_query(session, query_cypher25, {
            "embedding": embedding,
            "top_k": top_k,
            "group_id": group_id,
        })
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  Cypher 25 (top_k={top_k}, no oversample): [{elapsed:.1f}ms]")
        if results_cypher25:
            for r in results_cypher25:
                print(f"    ✓ {r['name']} (score={r['score']:.4f})")
        else:
            print(f"    ✗ 0 results (WHERE filter still post-applied)")
    except Exception as e:
        print(f"    Cypher 25 not available: {e}")
    
    # Key diagnostic: if standard with top_k=3 returns 0 results but oversample=100x
    # returns results, then the filter is NOT being pushed down.
    return results_cypher25 or results_standard


async def test_explain_plan(
    session, group_id: str, embedding: List[float], top_k: int = 3
):
    """EXPLAIN the vector query to see if WHERE is pushed into the index scan."""
    print(f"\n── Test 4: Query Plan Analysis (EXPLAIN) ──")
    
    # We want to see if the planner shows "NodeIndexScan" with a filter predicate
    # vs a separate "Filter" operator after the scan.
    query = """
    EXPLAIN
    CALL db.index.vector.queryNodes('entity_embedding_v2', $top_k, $embedding)
    YIELD node, score
    WHERE node.group_id = $group_id
    RETURN node.name AS name, score
    ORDER BY score DESC
    LIMIT $top_k
    """
    
    try:
        result = await session.run(query, {
            "embedding": embedding,
            "top_k": top_k,
            "group_id": group_id,
        })
        summary = await result.consume()
        plan = summary.plan if hasattr(summary, 'plan') else None
        
        if plan:
            print(f"  Query plan root: {plan.get('operatorType', plan.get('operator_type', '?')) if isinstance(plan, dict) else getattr(plan, 'operator_type', '?')}")
            _print_plan(plan, indent=2)
        else:
            print("  Could not retrieve plan (plan is None)")
            # Try to inspect summary for available attributes
            plan_attrs = [a for a in dir(summary) if 'plan' in a.lower()]
            if plan_attrs:
                print(f"  Available plan attributes: {plan_attrs}")
    except Exception as e:
        print(f"  EXPLAIN failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Also try PROFILE to get actual row counts
    print(f"\n  PROFILE (actual row counts):")
    profile_query = """
    PROFILE
    CALL db.index.vector.queryNodes('entity_embedding_v2', 100, $embedding)
    YIELD node, score
    WHERE node.group_id = $group_id
    RETURN node.name AS name, score
    ORDER BY score DESC
    LIMIT $top_k
    """
    try:
        result = await session.run(profile_query, {
            "embedding": embedding,
            "top_k": top_k,
            "group_id": group_id,
        })
        # Consume all records so we get the profile
        await result.data()
        summary = await result.consume()
        profile = summary.profile if hasattr(summary, 'profile') else None
        
        if profile:
            _print_profile(profile, indent=2)
        else:
            print("  Could not retrieve profile (profile is None)")
            # Inspect summary
            profile_attrs = [a for a in dir(summary) if 'profil' in a.lower() or 'plan' in a.lower()]
            if profile_attrs:
                print(f"  Available attributes: {profile_attrs}")
    except Exception as e:
        print(f"  PROFILE failed: {e}")
        import traceback
        traceback.print_exc()


def _print_plan(plan, indent: int = 0):
    """Recursively print a query plan (handles both object and dict forms)."""
    prefix = " " * indent
    
    # Support both attribute-based and dict-based plan objects
    if isinstance(plan, dict):
        op_type = plan.get('operatorType', plan.get('operator_type', '?'))
        arguments = plan.get('arguments', {})
        children = plan.get('children', [])
    else:
        op_type = getattr(plan, 'operator_type', '?')
        arguments = getattr(plan, 'arguments', {}) or {}
        children = getattr(plan, 'children', [])
    
    args_str = ""
    if arguments:
        for key in ["Details", "Filter", "Index", "Identifiers", "details", "filter"]:
            if key in arguments:
                args_str += f" {key}={arguments[key]}"
    
    print(f"{prefix}├─ {op_type}{args_str}")
    
    for child in (children or []):
        _print_plan(child, indent + 3)


def _print_profile(profile, indent: int = 0):
    """Recursively print a profiled plan with row counts."""
    prefix = " " * indent
    
    if isinstance(profile, dict):
        op_type = profile.get('operatorType', profile.get('operator_type', '?'))
        rows = profile.get('rows', '?')
        db_hits = profile.get('dbHits', profile.get('db_hits', '?'))
        arguments = profile.get('arguments', {})
        children = profile.get('children', [])
    else:
        op_type = getattr(profile, 'operator_type', '?')
        rows = getattr(profile, 'rows', '?')
        db_hits = getattr(profile, 'db_hits', '?')
        arguments = getattr(profile, 'arguments', {}) or {}
        children = getattr(profile, 'children', [])
    
    args_str = ""
    if arguments:
        for key in ["Details", "Filter", "details", "filter"]:
            if key in arguments:
                args_str += f" {key}={arguments[key]}"
    
    print(f"{prefix}├─ {op_type}  rows={rows}  db_hits={db_hits}{args_str}")
    
    for child in (children or []):
        _print_profile(child, indent + 3)


async def suggest_fixes(session, group_id: str, distribution: Dict[str, int]):
    """Summarize findings and suggest fixes."""
    total_entities = sum(distribution.values())
    our_count = distribution.get(group_id, 0)
    num_groups = len(distribution)
    our_pct = our_count / total_entities * 100 if total_entities > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"DIAGNOSIS SUMMARY")
    print(f"{'='*60}")
    print(f"  Groups in index:     {num_groups}")
    print(f"  Total entities:      {total_entities}")
    print(f"  Your group:          {our_count} ({our_pct:.1f}%)")
    print(f"  Other groups:        {total_entities - our_count} ({100-our_pct:.1f}%)")
    
    if our_pct < 50:
        min_oversample = int(total_entities / max(our_count, 1)) + 1
        print(f"\n  ⚠ Your group is a MINORITY in the index ({our_pct:.1f}%)")
        print(f"    Minimum oversampling needed: {min_oversample}x")
        print(f"    Current production oversampling: 3x (async_neo4j_service) / 2x (hipporag)")
        print(f"    → These are INSUFFICIENT for reliable retrieval")
    
    print(f"\n  RECOMMENDED FIXES (in order of preference):")
    print(f"  ┌─────────────────────────────────────────────────────────────")
    print(f"  │ Fix 1 (best): Pre-filtered vector search")
    print(f"  │   Requires: range index on Entity.group_id + Neo4j 2025.x")
    print(f"  │   Run: CREATE INDEX entity_group_id IF NOT EXISTS FOR (e:Entity) ON (e.group_id)")
    print(f"  │   Then the Cypher planner pushes WHERE into the vector scan")
    print(f"  │   → Always returns top_k results for YOUR group, regardless of other groups")
    print(f"  │")
    print(f"  │ Fix 2 (fallback): Increase oversampling in production")
    print(f"  │   async_neo4j_service.py line ~456: top_k_oversample = max(top_k * 3, 200)")
    print(f"  │   hipporag_retriever.py line ~340:  top_k * 2 → max(top_k * 2, 200)")
    print(f"  │   route_4_drift.py vector_expansion: top_k → max(top_k, 200)")
    print(f"  │   → Works but wastes compute scanning entities you'll discard")
    print(f"  │")
    print(f"  │ Fix 3 (nuclear): Per-group vector indexes")
    print(f"  │   Create entity_embedding_v2_<group_id> per group")
    print(f"  │   Perfect isolation but O(n) indexes to manage")
    print(f"  │   → Only if Fix 1 is not supported by your Neo4j version")
    print(f"  └─────────────────────────────────────────────────────────────")
    
    # Also check sentence index which has the same problem
    sentence_query = """
    MATCH (s:Sentence)
    WHERE s.embedding_v2 IS NOT NULL
    RETURN s.group_id AS group_id, count(*) AS count
    ORDER BY count DESC
    """
    try:
        sentence_dist = await run_query(session, sentence_query)
        if sentence_dist and len(sentence_dist) > 1:
            total_sentences = sum(r["count"] for r in sentence_dist)
            our_sentences = next((r["count"] for r in sentence_dist if r["group_id"] == group_id), 0)
            print(f"\n  ⚠ Sentence index has the SAME issue:")
            print(f"    {len(sentence_dist)} groups, {total_sentences} total sentences")
            print(f"    Your group: {our_sentences} ({our_sentences/total_sentences*100:.1f}%)")
            print(f"    Affects: Route 2, Route 3, Route 4 sentence retrieval")
            print(f"    Fix: CREATE INDEX sentence_group_id IF NOT EXISTS FOR (s:Sentence) ON (s.group_id)")
    except Exception:
        pass


# ── Embedding Helper ──────────────────────────────────────────────

async def get_sample_embedding(session, group_id: str) -> Optional[List[float]]:
    """Get an embedding from an existing entity in the group (for testing)."""
    query = """
    MATCH (e:Entity {group_id: $group_id})
    WHERE e.embedding_v2 IS NOT NULL
    RETURN e.name AS name, e.embedding_v2 AS embedding
    LIMIT 1
    """
    records = await run_query(session, query, {"group_id": group_id})
    if records:
        print(f"  Using embedding from entity: '{records[0]['name']}'")
        return records[0]["embedding"]
    
    # Try EntityArchived if Entity label was stripped
    query_archived = """
    MATCH (e:EntityArchived {group_id: $group_id})
    WHERE e.embedding_v2 IS NOT NULL
    RETURN e.name AS name, e.embedding_v2 AS embedding
    LIMIT 1
    """
    records = await run_query(session, query_archived, {"group_id": group_id})
    if records:
        print(f"  Using embedding from archived entity: '{records[0]['name']}'")
        return records[0]["embedding"]
    
    return None


# ── Main ─────────────────────────────────────────────────────────

async def main(group_id: Optional[str] = None):
    config = get_config()
    
    if not config["uri"]:
        print("ERROR: Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD environment variables")
        sys.exit(1)
    
    driver = AsyncGraphDatabase.driver(
        config["uri"],
        auth=(config["username"], config["password"]),
    )
    
    try:
        async with driver.session(database=config["database"]) as session:
            # 0. Server version
            version = await test_server_version(session)
            
            # 1. Entity distribution
            distribution = await test_entity_distribution(session)
            
            if not distribution:
                print("\nNo entities with embedding_v2 found. Nothing to test.")
                return
            
            # Auto-detect group_id if not specified
            if not group_id:
                # Pick the group with the fewest entities (most affected by the bug)
                group_id = min(distribution, key=distribution.get)
                print(f"\n  Auto-selected group: '{group_id}' (smallest = most affected)")
            
            if group_id not in distribution:
                print(f"\n  WARNING: Group '{group_id}' has no entities with embedding_v2")
                print(f"  Available groups: {list(distribution.keys())}")
                return
            
            # 2. Get a sample embedding for testing
            print(f"\n── Getting sample embedding from group '{group_id}' ──")
            embedding = await get_sample_embedding(session, group_id)
            if not embedding:
                print("  Could not find any entity with embedding_v2 in this group")
                return
            
            # 3. Run tests
            await test_post_filter_approach(session, group_id, embedding)
            await test_post_filter_ranking(session, group_id, embedding)
            await test_prefiltered_vector_search(session, group_id, embedding)
            await test_explain_plan(session, group_id, embedding)
            
            # 4. Summary & recommendations
            await suggest_fixes(session, group_id, distribution)
    
    finally:
        await driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose vector index group isolation")
    parser.add_argument("--group", type=str, help="Group ID to test (auto-detects if not specified)")
    args = parser.parse_args()
    
    asyncio.run(main(group_id=args.group))
