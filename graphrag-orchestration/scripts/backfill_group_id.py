#!/usr/bin/env python3
"""Backfill missing group_id safely for a single tenant.

This script exists to support *strict* multi-tenant isolation:
- runtime queries always require `group_id = $group_id`
- therefore legacy/buggy records with `group_id IS NULL` must be fixed
  (or they will be invisible to retrieval).

Safety model
------------
We only stamp `group_id` onto records that are provably associated to the tenant.
Today we do that via graph adjacency to chunks that already have the tenant's
`group_id`.

What it does
------------
For a given `--group-id`:
1) Set group_id on Entity/__Entity__ nodes where group_id IS NULL AND they are
   connected via MENTIONS (either direction) to a Chunk/TextChunk/__Node__ node
   with group_id = $group_id.
2) Set group_id on relationships where group_id IS NULL AND both endpoint nodes
   have group_id = $group_id.

Run in dry-run by default; use --commit to apply.

Usage
-----
  python scripts/backfill_group_id.py --group-id <gid>
  python scripts/backfill_group_id.py --group-id <gid> --commit

Connection is via environment variables:
  NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, optional NEO4J_DATABASE
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from neo4j import GraphDatabase


@dataclass(frozen=True)
class Neo4jConn:
    uri: str
    username: str
    password: str
    database: str | None


def _get_conn_from_env() -> Neo4jConn:
    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE") or None

    missing = [k for k, v in [("NEO4J_URI", uri), ("NEO4J_USERNAME", username), ("NEO4J_PASSWORD", password)] if not v]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)}")

    assert uri is not None
    assert username is not None
    assert password is not None

    return Neo4jConn(uri=uri, username=username, password=password, database=database)


def _run_single(session, cypher: str, params: dict) -> dict:
    rec = session.run(cypher, params).single()
    return dict(rec) if rec else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill group_id for one tenant")
    parser.add_argument("--group-id", required=True, help="Tenant group_id to backfill")
    parser.add_argument("--commit", action="store_true", help="Apply updates (default is dry-run)")
    args = parser.parse_args()

    conn = _get_conn_from_env()
    driver = GraphDatabase.driver(conn.uri, auth=(conn.username, conn.password))

    params = {"group_id": args.group_id}

    count_entities = """
    MATCH (c)
    WHERE (c:Chunk OR c:TextChunk OR c:__Node__) AND c.group_id = $group_id
    MATCH (c)-[:MENTIONS]-(e)
    WHERE (e:__Entity__ OR e:Entity) AND e.group_id IS NULL
    RETURN count(DISTINCT e) AS entities_to_update
    """

    update_entities = """
    MATCH (c)
    WHERE (c:Chunk OR c:TextChunk OR c:__Node__) AND c.group_id = $group_id
    MATCH (c)-[:MENTIONS]-(e)
    WHERE (e:__Entity__ OR e:Entity) AND e.group_id IS NULL
    SET e.group_id = $group_id
    RETURN count(DISTINCT e) AS entities_updated
    """

    count_rels = """
    MATCH (a)-[r]->(b)
    WHERE r.group_id IS NULL
      AND a.group_id = $group_id
      AND b.group_id = $group_id
    RETURN count(r) AS rels_to_update
    """

    update_rels = """
    MATCH (a)-[r]->(b)
    WHERE r.group_id IS NULL
      AND a.group_id = $group_id
      AND b.group_id = $group_id
    SET r.group_id = $group_id
    RETURN count(r) AS rels_updated
    """

    with driver:
        with driver.session(database=conn.database) as session:
            ent_counts = _run_single(session, count_entities, params)
            rel_counts = _run_single(session, count_rels, params)

            print(f"group_id={args.group_id}")
            print(f"entities_to_update={ent_counts.get('entities_to_update', 0)}")
            print(f"rels_to_update={rel_counts.get('rels_to_update', 0)}")

            if not args.commit:
                print("dry_run=true (use --commit to apply)")
                return 0

            ent_updated = _run_single(session, update_entities, params)
            rel_updated = _run_single(session, update_rels, params)

            print("dry_run=false")
            print(f"entities_updated={ent_updated.get('entities_updated', 0)}")
            print(f"rels_updated={rel_updated.get('rels_updated', 0)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
