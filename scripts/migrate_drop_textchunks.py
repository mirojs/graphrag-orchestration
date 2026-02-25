#!/usr/bin/env python3
"""Post-reindex migration: drop TextChunk nodes, PART_OF edges, and legacy indexes.

Run this AFTER all documents have been re-indexed with sentence-based chunking.
It removes the now-obsolete TextChunk layer from Neo4j.

Usage:
    python scripts/migrate_drop_textchunks.py [--dry-run] [--neo4j-uri URI] [--neo4j-password PWD]

Environment variables (fallback):
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE
"""
import argparse
import os
import sys

from neo4j import GraphDatabase


def get_driver(uri: str, username: str, password: str):
    return GraphDatabase.driver(uri, auth=(username, password))


def run_migration(driver, database: str, dry_run: bool = False):
    results = {}

    with driver.session(database=database) as session:
        # 1. Count TextChunk nodes
        record = session.run("MATCH (c:TextChunk) RETURN count(c) AS cnt").single()
        chunk_count = record["cnt"] if record else 0
        results["textchunk_count"] = chunk_count
        print(f"TextChunk nodes found: {chunk_count}")

        # 2. Count PART_OF edges (Sentence→TextChunk)
        record = session.run(
            "MATCH ()-[r:PART_OF]->(:TextChunk) RETURN count(r) AS cnt"
        ).single()
        partof_count = record["cnt"] if record else 0
        results["partof_edges"] = partof_count
        print(f"PART_OF edges to TextChunk: {partof_count}")

        # 3. Count IN_CHUNK edges (Table/KVP→TextChunk)
        record = session.run(
            "MATCH ()-[r:IN_CHUNK]->(:TextChunk) RETURN count(r) AS cnt"
        ).single()
        inchunk_count = record["cnt"] if record else 0
        results["in_chunk_edges"] = inchunk_count
        print(f"IN_CHUNK edges to TextChunk: {inchunk_count}")

        if dry_run:
            print("\n[DRY RUN] No changes made.")
            return results

        if chunk_count == 0:
            print("No TextChunk nodes to remove. Skipping.")
        else:
            # 4. Delete TextChunk nodes in batches
            print(f"\nDeleting {chunk_count} TextChunk nodes in batches...")
            total_deleted = 0
            while True:
                record = session.run(
                    """
                    MATCH (c:TextChunk)
                    WITH c LIMIT 1000
                    DETACH DELETE c
                    RETURN count(*) AS deleted
                    """
                ).single()
                batch = record["deleted"] if record else 0
                if batch == 0:
                    break
                total_deleted += batch
                print(f"  Deleted {total_deleted}/{chunk_count}...")
            results["deleted"] = total_deleted
            print(f"Total TextChunk nodes deleted: {total_deleted}")

        # 4b. Delete RaptorNode nodes
        record = session.run("MATCH (r:RaptorNode) RETURN count(r) AS cnt").single()
        raptor_count = record["cnt"] if record else 0
        results["raptor_count"] = raptor_count
        print(f"RaptorNode nodes found: {raptor_count}")
        if not dry_run and raptor_count > 0:
            session.run("MATCH (r:RaptorNode) DETACH DELETE r")
            print(f"Deleted {raptor_count} RaptorNode nodes")

        # 5. Drop legacy indexes
        legacy_indexes = [
            "chunk_embedding",        # v1 OpenAI 3072-dim vector index
            "chunk_embeddings_v2",    # v2 Voyage 2048-dim vector index
            "textchunk_fulltext",     # fulltext index on TextChunk.text
            "raptor_embedding",       # RAPTOR tree embedding index
        ]
        for idx_name in legacy_indexes:
            try:
                session.run(f"DROP INDEX {idx_name} IF EXISTS")
                print(f"Dropped index: {idx_name}")
                results[f"dropped_{idx_name}"] = True
            except Exception as e:
                print(f"Warning: could not drop {idx_name}: {e}")
                results[f"dropped_{idx_name}"] = False

        # 6. Drop legacy constraint
        try:
            session.run(
                "DROP CONSTRAINT chunk_id IF EXISTS"
            )
            print("Dropped constraint: chunk_id")
            results["dropped_chunk_id_constraint"] = True
        except Exception as e:
            print(f"Warning: could not drop chunk_id constraint: {e}")
            results["dropped_chunk_id_constraint"] = False

    print("\nMigration complete.")
    return results


def main():
    parser = argparse.ArgumentParser(description="Drop TextChunk nodes and legacy indexes from Neo4j")
    parser.add_argument("--dry-run", action="store_true", help="Count but don't delete")
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-username", default=os.getenv("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--neo4j-database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    args = parser.parse_args()

    if not args.neo4j_password:
        print("Error: NEO4J_PASSWORD not set", file=sys.stderr)
        sys.exit(1)

    driver = get_driver(args.neo4j_uri, args.neo4j_username, args.neo4j_password)
    try:
        run_migration(driver, args.neo4j_database, dry_run=args.dry_run)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
