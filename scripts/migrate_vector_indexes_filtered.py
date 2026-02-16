#!/usr/bin/env python3
"""
Migration: Recreate vector indexes with WITH [group_id] for SEARCH clause pre-filtering.

Background:
    Neo4j 5.x SEARCH clause enables true in-index filtering via:
        MATCH (e:Entity)
        SEARCH e IN (VECTOR INDEX idx FOR $emb WHERE e.group_id = $gid LIMIT k)
        SCORE AS score
    
    This requires indexes created with filter properties:
        CREATE VECTOR INDEX ... WITH [e.group_id] OPTIONS {…}
    
    Without WITH, the SEARCH WHERE clause is evaluated AFTER the ANN scan,
    causing the same cross-group contamination as db.index.vector.queryNodes().

Steps:
    1. Drop the temporary test index (entity_embedding_v2_filtered)
    2. Restore :EntityArchived → :Entity labels (reverse yesterday's workaround)
    3. Drop existing V2 indexes (no IF NOT EXISTS won't add WITH to existing indexes)
    4. Recreate V2 indexes with WITH [*.group_id]
    5. Optionally recreate V1 indexes with WITH [*.group_id]
    6. Wait for all indexes to reach ONLINE status

Requires:
    - Neo4j 5.18+ with vector-3.0 provider (AuraDB 5.27 qualifies)
    - CYPHER 25 runtime for SEARCH clause queries
    - pip install neo4j python-dotenv

Usage:
    python scripts/migrate_vector_indexes_filtered.py [--include-v1] [--dry-run] [--restore-labels]
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv
from neo4j import GraphDatabase

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

# V2 indexes (active production – Voyage 2048-dim)
V2_INDEXES = [
    {
        "name": "entity_embedding_v2",
        "label": "Entity",
        "property": "embedding_v2",
        "dimensions": 2048,
        "similarity": "cosine",
        "filter_properties": ["group_id"],
    },
    {
        "name": "entity_embedding_v2_internal",
        "label": "`__Entity__`",
        "property": "embedding_v2",
        "dimensions": 2048,
        "similarity": "cosine",
        "filter_properties": ["group_id"],
    },
    {
        "name": "chunk_embeddings_v2",
        "label": "TextChunk",
        "property": "embedding_v2",
        "dimensions": 2048,
        "similarity": "cosine",
        "filter_properties": ["group_id"],
    },
    {
        "name": "sentence_embeddings_v2",
        "label": "Sentence",
        "property": "embedding_v2",
        "dimensions": 2048,
        "similarity": "cosine",
        "filter_properties": ["group_id"],
    },
]

# V1 indexes (legacy – OpenAI 3072-dim / 1536-dim)
V1_INDEXES = [
    {
        "name": "entity_embedding",
        "label": "Entity",
        "property": "embedding",
        "dimensions": 1536,
        "similarity": "cosine",
        "filter_properties": ["group_id"],
    },
    {
        "name": "raptor_embedding",
        "label": "RaptorNode",
        "property": "embedding",
        "dimensions": 3072,
        "similarity": "cosine",
        "filter_properties": ["group_id"],
    },
    {
        "name": "chunk_embedding",
        "label": "TextChunk",
        "property": "embedding",
        "dimensions": 3072,
        "similarity": "cosine",
        "filter_properties": ["group_id"],
    },
]

# Test indexes to clean up
TEST_INDEXES_TO_DROP = [
    "entity_embedding_v2_filtered",
]


def get_driver():
    """Create Neo4j driver from .env.local."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env.local")
    load_dotenv(env_path)

    uri = os.environ["NEO4J_URI"]
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    return driver, database


def show_current_indexes(session):
    """Show all vector indexes and their filter properties."""
    result = session.run("SHOW INDEXES WHERE type = 'VECTOR'")
    indexes = list(result)
    print(f"\n{'='*80}")
    print(f"  Current vector indexes ({len(indexes)} total)")
    print(f"{'='*80}")
    for idx in indexes:
        name = idx["name"]
        state = idx["state"]
        entity_type = idx.get("entityType", "?")
        labels = idx.get("labelsOrTypes", [])
        props = idx.get("properties", [])
        config = idx.get("indexConfig", {})
        dims = config.get("vector.dimensions", "?")
        sim = config.get("vector.similarity_function", "?")
        # Check for filter properties (WITH clause)
        # In Neo4j 5.18+, indexes with filter properties show them in config
        print(f"  {name:40s} {state:10s} {labels} ON {props} ({dims}d, {sim})")
    print()
    return indexes


def drop_index(session, name, dry_run=False):
    """Drop an index by name."""
    query = f"DROP INDEX {name} IF EXISTS"
    if dry_run:
        print(f"  [DRY-RUN] {query}")
    else:
        print(f"  Dropping: {name} ... ", end="", flush=True)
        session.run(query)
        print("done")


def create_filtered_index(session, spec, dry_run=False):
    """Create a vector index with filter properties (WITH clause)."""
    label = spec["label"]
    prop = spec["property"]
    dims = spec["dimensions"]
    sim = spec["similarity"]
    name = spec["name"]
    filters = spec["filter_properties"]

    # Use variable name from label (lowercase first char, strip backticks)
    var = label.strip("`")[0].lower()

    # Build WITH clause: WITH [e.group_id, e.oid] etc.
    with_clause = ", ".join(f"{var}.{f}" for f in filters)

    query = f"""
    CREATE VECTOR INDEX {name} IF NOT EXISTS
    FOR ({var}:{label}) ON ({var}.{prop})
    WITH [{with_clause}]
    OPTIONS {{indexConfig: {{
        `vector.dimensions`: {dims},
        `vector.similarity_function`: '{sim}'
    }}}}
    """

    if dry_run:
        print(f"  [DRY-RUN] CREATE VECTOR INDEX {name} WITH [{with_clause}]")
    else:
        print(f"  Creating: {name} WITH [{with_clause}] ... ", end="", flush=True)
        session.run(query.strip())
        print("done")


def wait_for_indexes_online(session, index_names, timeout=300):
    """Wait for all specified indexes to reach ONLINE status."""
    print(f"\n  Waiting for {len(index_names)} indexes to reach ONLINE status...")
    start = time.time()
    pending = set(index_names)

    while pending and (time.time() - start) < timeout:
        result = session.run("SHOW INDEXES WHERE type = 'VECTOR'")
        for idx in result:
            if idx["name"] in pending and idx["state"] == "ONLINE":
                elapsed = time.time() - start
                print(f"    ✓ {idx['name']} is ONLINE ({elapsed:.1f}s)")
                pending.discard(idx["name"])
        if pending:
            time.sleep(5)

    if pending:
        print(f"\n  ⚠ TIMEOUT after {timeout}s. Still pending: {pending}")
        return False
    else:
        elapsed = time.time() - start
        print(f"  All indexes ONLINE in {elapsed:.1f}s")
        return True


def restore_archived_labels(session, dry_run=False):
    """Restore :EntityArchived → :Entity labels.
    
    Reverses yesterday's workaround that moved non-target-group entities
    to :EntityArchived to avoid cross-group contamination.
    With filtered indexes, all entities can safely be :Entity.
    """
    # Count archived
    result = session.run("MATCH (e:EntityArchived) RETURN count(e) AS cnt")
    archived_count = result.single()["cnt"]

    if archived_count == 0:
        print("  No :EntityArchived nodes to restore.")
        return 0

    print(f"  Found {archived_count} :EntityArchived nodes to restore to :Entity")

    if dry_run:
        print(f"  [DRY-RUN] Would restore {archived_count} nodes")
        return archived_count

    # Restore in batches to avoid transaction timeouts
    batch_size = 1000
    total_restored = 0

    while total_restored < archived_count:
        result = session.run("""
        MATCH (e:EntityArchived)
        WITH e LIMIT $batch
        SET e:Entity
        REMOVE e:EntityArchived
        RETURN count(e) AS restored
        """, batch=batch_size)
        restored = result.single()["restored"]
        total_restored += restored
        print(f"    Restored {total_restored}/{archived_count} ...")
        if restored == 0:
            break

    print(f"  ✓ Restored {total_restored} nodes from :EntityArchived → :Entity")
    return total_restored


def verify_search_clause(session):
    """Quick smoke test: run a SEARCH query to confirm it uses NodeVectorIndexSearch."""
    print("\n  Verifying SEARCH clause works with filtered index...")
    try:
        # Get a sample group_id
        result = session.run("MATCH (e:Entity) WHERE e.group_id IS NOT NULL RETURN e.group_id AS gid LIMIT 1")
        rec = result.single()
        if not rec:
            print("  ⚠ No Entity nodes found to test")
            return

        gid = rec["gid"]

        # Get a sample embedding
        result = session.run(
            "MATCH (e:Entity {group_id: $gid}) WHERE e.embedding_v2 IS NOT NULL RETURN e.embedding_v2 AS emb LIMIT 1",
            gid=gid,
        )
        rec = result.single()
        if not rec:
            print("  ⚠ No Entity with embedding_v2 found to test")
            return

        emb = list(rec["emb"])

        # Run SEARCH query
        result = session.run(
            """CYPHER 25
            MATCH (e:Entity)
            SEARCH e IN (VECTOR INDEX entity_embedding_v2 FOR $emb WHERE e.group_id = $gid LIMIT 3)
            SCORE AS score
            RETURN e.name AS name, e.group_id AS group_id, score
            """,
            emb=emb,
            gid=gid,
        )
        records = list(result)
        print(f"  ✓ SEARCH returned {len(records)} results, all group_id={gid}:")
        for r in records:
            assert r["group_id"] == gid, f"Group isolation violated! Expected {gid}, got {r['group_id']}"
            print(f"    {r['name']}: {r['score']:.4f}")

        # PROFILE to confirm NodeVectorIndexSearch operator
        result = session.run(
            """CYPHER 25
            PROFILE
            MATCH (e:Entity)
            SEARCH e IN (VECTOR INDEX entity_embedding_v2 FOR $emb WHERE e.group_id = $gid LIMIT 3)
            SCORE AS score
            RETURN e.name, score
            """,
            emb=emb,
            gid=gid,
        )
        _ = list(result)
        summary = result.consume()
        plan = summary.profile

        def find_operators(p, ops=None):
            if ops is None:
                ops = []
            if isinstance(p, dict):
                ops.append(p.get("operatorType", "?"))
                for child in p.get("children", []):
                    find_operators(child, ops)
            else:
                ops.append(getattr(p, "operator_type", "?"))
                for child in getattr(p, "children", []):
                    find_operators(child, ops)
            return ops

        operators = find_operators(plan)
        if any("NodeVectorIndexSearch" in op for op in operators):
            print("  ✓ PROFILE confirms NodeVectorIndexSearch (in-index filtering)")
        elif any("Filter" in op for op in operators):
            print("  ⚠ PROFILE shows separate Filter operator (post-filtering!) — WITH clause may not be active")
        else:
            print(f"  ? Operators: {operators}")

    except Exception as e:
        print(f"  ⚠ Verification failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Migrate vector indexes to filtered (WITH) variant")
    parser.add_argument("--include-v1", action="store_true", help="Also recreate V1 (legacy) indexes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    parser.add_argument("--restore-labels", action="store_true", help="Restore :EntityArchived → :Entity")
    parser.add_argument("--skip-drop", action="store_true", help="Skip dropping existing indexes (for resume)")
    parser.add_argument("--verify-only", action="store_true", help="Only run verification, skip migration")
    args = parser.parse_args()

    driver, database = get_driver()

    indexes_to_migrate = list(V2_INDEXES)
    if args.include_v1:
        indexes_to_migrate.extend(V1_INDEXES)

    index_names = [idx["name"] for idx in indexes_to_migrate]

    print(f"Neo4j Filtered Vector Index Migration")
    print(f"Database: {database}")
    print(f"Indexes to migrate: {index_names}")
    if args.dry_run:
        print("MODE: DRY-RUN (no changes will be made)")
    print()

    with driver.session(database=database) as session:
        # Show current state
        show_current_indexes(session)

        if args.verify_only:
            verify_search_clause(session)
            driver.close()
            return

        # Step 1: Drop test indexes
        print("Step 1: Drop test indexes")
        for name in TEST_INDEXES_TO_DROP:
            drop_index(session, name, dry_run=args.dry_run)

        # Step 2: Restore archived labels
        if args.restore_labels:
            print("\nStep 2: Restore :EntityArchived → :Entity")
            restore_archived_labels(session, dry_run=args.dry_run)
        else:
            print("\nStep 2: Skipping label restore (use --restore-labels to enable)")

        # Step 3: Drop existing indexes
        if not args.skip_drop:
            print("\nStep 3: Drop existing indexes")
            for idx in indexes_to_migrate:
                drop_index(session, idx["name"], dry_run=args.dry_run)
            if not args.dry_run:
                print("  Waiting 5s for drops to propagate...")
                time.sleep(5)
        else:
            print("\nStep 3: Skipping drops (--skip-drop)")

        # Step 4: Create filtered indexes
        print("\nStep 4: Create filtered indexes (WITH [group_id])")
        for idx in indexes_to_migrate:
            create_filtered_index(session, idx, dry_run=args.dry_run)

        # Step 5: Wait for ONLINE
        if not args.dry_run:
            print("\nStep 5: Wait for indexes to reach ONLINE")
            success = wait_for_indexes_online(session, index_names, timeout=600)
            if not success:
                print("\n⚠ Some indexes did not reach ONLINE status in time.")
                print("  Monitor with: SHOW INDEXES WHERE type='VECTOR'")
                driver.close()
                sys.exit(1)
        else:
            print("\nStep 5: [DRY-RUN] Would wait for indexes to reach ONLINE")

        # Step 6: Verify
        if not args.dry_run:
            print("\nStep 6: Verify SEARCH clause")
            verify_search_clause(session)

        # Show final state
        show_current_indexes(session)

    driver.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
