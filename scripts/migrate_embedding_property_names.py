#!/usr/bin/env python3
"""Migrate Neo4j embedding property names from generic to type-specific.

Renames:
  Entity.embedding_v2       → Entity.entity_embedding
  Sentence.embedding_v2     → Sentence.sentence_embedding
  RELATED_TO.embedding_v2   → RELATED_TO.triple_embedding
  Community.embedding        → Community.community_embedding
  Section.embedding          → Section.section_embedding

Also recreates vector indexes with new names/properties and drops old ones.

Safe to run multiple times (idempotent).
"""

import os
import sys
import time
from typing import Optional

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

BATCH_SIZE = 500


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def migrate_node_property(
    driver, label: str, old_prop: str, new_prop: str, dry_run: bool = False
):
    """Rename a property on all nodes of a given label, in batches."""
    with driver.session(database=NEO4J_DATABASE) as session:
        # Count
        result = session.run(
            f"MATCH (n:{label}) WHERE n.{old_prop} IS NOT NULL RETURN count(n) AS cnt"
        )
        total = result.single()["cnt"]
        if total == 0:
            print(f"  {label}.{old_prop} → .{new_prop}: 0 nodes (skip)")
            return

        if dry_run:
            print(f"  {label}.{old_prop} → .{new_prop}: {total} nodes (dry run)")
            return

        migrated = 0
        while migrated < total:
            result = session.run(
                f"""
                MATCH (n:{label})
                WHERE n.{old_prop} IS NOT NULL AND n.{new_prop} IS NULL
                WITH n LIMIT $batch
                SET n.{new_prop} = n.{old_prop}
                REMOVE n.{old_prop}
                RETURN count(n) AS cnt
                """,
                batch=BATCH_SIZE,
            )
            batch_count = result.single()["cnt"]
            if batch_count == 0:
                break
            migrated += batch_count
            print(f"  {label}.{old_prop} → .{new_prop}: {migrated}/{total}")

        print(f"  ✅ {label}: {migrated} nodes migrated")


def migrate_edge_property(
    driver, rel_type: str, old_prop: str, new_prop: str, dry_run: bool = False
):
    """Rename a property on all edges of a given type, in batches."""
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            f"MATCH ()-[r:{rel_type}]->() WHERE r.{old_prop} IS NOT NULL RETURN count(r) AS cnt"
        )
        total = result.single()["cnt"]
        if total == 0:
            print(f"  [:{rel_type}].{old_prop} → .{new_prop}: 0 edges (skip)")
            return

        if dry_run:
            print(f"  [:{rel_type}].{old_prop} → .{new_prop}: {total} edges (dry run)")
            return

        migrated = 0
        while migrated < total:
            result = session.run(
                f"""
                MATCH ()-[r:{rel_type}]->()
                WHERE r.{old_prop} IS NOT NULL AND r.{new_prop} IS NULL
                WITH r LIMIT $batch
                SET r.{new_prop} = r.{old_prop}
                REMOVE r.{old_prop}
                RETURN count(r) AS cnt
                """,
                batch=BATCH_SIZE,
            )
            batch_count = result.single()["cnt"]
            if batch_count == 0:
                break
            migrated += batch_count
            print(f"  [:{rel_type}].{old_prop} → .{new_prop}: {migrated}/{total}")

        print(f"  ✅ [:{rel_type}]: {migrated} edges migrated")


def manage_indexes(driver, dry_run: bool = False):
    """Create new vector indexes and drop old ones."""
    new_indexes = [
        {
            "name": "entity_embedding",
            "label": "Entity",
            "property": "entity_embedding",
            "dimensions": 2048,
        },
        {
            "name": "sentence_embedding",
            "label": "Sentence",
            "property": "sentence_embedding",
            "dimensions": 2048,
        },
    ]

    old_indexes = [
        "entity_embedding_v2",
        "sentence_embeddings_v2",
        "entity_embedding_v2_internal",
    ]

    with driver.session(database=NEO4J_DATABASE) as session:
        # Create new indexes
        for idx in new_indexes:
            cypher = f"""
            CREATE VECTOR INDEX {idx['name']} IF NOT EXISTS
            FOR (n:{idx['label']}) ON (n.{idx['property']})
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {idx['dimensions']},
                `vector.similarity_function`: 'cosine'
            }}}}
            """
            if dry_run:
                print(f"  Would create index: {idx['name']}")
            else:
                try:
                    session.run(cypher)
                    print(f"  ✅ Created index: {idx['name']}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  ⏭️  Index {idx['name']} already exists")
                    else:
                        print(f"  ❌ Error creating {idx['name']}: {e}")

        # Drop old indexes
        for name in old_indexes:
            if dry_run:
                print(f"  Would drop index: {name}")
            else:
                try:
                    session.run(f"DROP INDEX {name} IF EXISTS")
                    print(f"  🗑️  Dropped index: {name}")
                except Exception as e:
                    print(f"  ⚠️  Could not drop {name}: {e}")


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("🔍 DRY RUN — no changes will be made\n")
    else:
        print("🚀 LIVE RUN — migrating Neo4j embedding properties\n")

    driver = get_driver()

    try:
        # Step 1: Migrate properties
        print("Step 1: Migrate node properties")
        migrate_node_property(driver, "Entity", "embedding_v2", "entity_embedding", dry_run)
        migrate_node_property(driver, "Sentence", "embedding_v2", "sentence_embedding", dry_run)
        migrate_node_property(driver, "Community", "embedding", "community_embedding", dry_run)
        migrate_node_property(driver, "Section", "embedding", "section_embedding", dry_run)

        print("\nStep 2: Migrate edge properties")
        migrate_edge_property(driver, "RELATED_TO", "embedding_v2", "triple_embedding", dry_run)

        print("\nStep 3: Manage vector indexes")
        manage_indexes(driver, dry_run)

        print("\n✅ Migration complete!")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
