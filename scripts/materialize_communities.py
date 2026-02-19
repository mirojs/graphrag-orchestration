#!/usr/bin/env python3
"""Materialize Community nodes from existing entity community_id assignments.

Standalone script — connects directly to Neo4j, groups entities by community_id,
creates Community nodes with BELONGS_TO edges, and optionally generates
LLM summaries via Azure OpenAI.

When LLM summaries are not generated (default), the community_matcher's
_ensure_embeddings() method will auto-embed communities on first query-time
load using the fallback text: "{title}. Entities: {name1, name2, ...}"

Usage:
    python scripts/materialize_communities.py --group test-5pdfs-v2-fix2
    python scripts/materialize_communities.py --group test-5pdfs-v2-fix2 --min-size 3
    python scripts/materialize_communities.py --group test-5pdfs-v2-fix2 --generate-summaries
    python scripts/materialize_communities.py --group test-5pdfs-v2-fix2 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
SERVICE_ROOT = PROJECT_ROOT / "graphrag-orchestration"
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(SERVICE_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AZURE_OPENAI_API_VERSION = "2024-10-21"


def get_neo4j_driver():
    """Create Neo4j driver from environment variables."""
    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USERNAME", "")
    pw = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not user or not pw:
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD must be set")
        sys.exit(1)
    return GraphDatabase.driver(uri, auth=(user, pw))


def get_azure_openai_token() -> Optional[str]:
    """Get Azure AD token for OpenAI via az CLI."""
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://cognitiveservices.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Failed to get Azure AD token: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 1: Read community assignments from Neo4j
# ---------------------------------------------------------------------------
def read_community_assignments(driver, group_id: str, min_size: int = 2) -> List[Dict]:
    """Group entities by community_id, return communities with >= min_size members."""
    query = """
    MATCH (e:Entity {group_id: $group_id})
    WHERE e.community_id IS NOT NULL
    WITH e.community_id AS cid,
         collect({
             name: e.name,
             id: e.id,
             description: coalesce(e.description, ''),
             degree: coalesce(e.degree, 0),
             pagerank: coalesce(e.pagerank, 0.0)
         }) AS members
    WHERE size(members) >= $min_size
    RETURN cid, members
    ORDER BY size(members) DESC
    """
    with driver.session() as session:
        result = session.run(query, group_id=group_id, min_size=min_size)
        communities = []
        for record in result:
            communities.append({
                "cid": record["cid"],
                "members": record["members"],
            })
    return communities


# ---------------------------------------------------------------------------
# Step 2: Check existing Community nodes
# ---------------------------------------------------------------------------
def count_existing_communities(driver, group_id: str) -> int:
    """Count existing Community nodes for a group."""
    query = "MATCH (c:Community {group_id: $group_id}) RETURN count(c) AS cnt"
    with driver.session() as session:
        result = session.run(query, group_id=group_id)
        return result.single()["cnt"]


def delete_existing_communities(driver, group_id: str) -> int:
    """Delete existing Community nodes and BELONGS_TO edges for a group."""
    query = """
    MATCH (c:Community {group_id: $group_id})
    DETACH DELETE c
    RETURN count(c) AS deleted
    """
    with driver.session() as session:
        # Need to use a different approach since count after delete doesn't work
        count = session.run(
            "MATCH (c:Community {group_id: $group_id}) RETURN count(c) AS cnt",
            group_id=group_id,
        ).single()["cnt"]
        if count > 0:
            session.run(
                "MATCH (c:Community {group_id: $group_id}) DETACH DELETE c",
                group_id=group_id,
            )
        return count


# ---------------------------------------------------------------------------
# Step 3: Create Community nodes + BELONGS_TO edges
# ---------------------------------------------------------------------------
def create_community_nodes(
    driver,
    group_id: str,
    communities: List[Dict],
    dry_run: bool = False,
) -> int:
    """Create Community nodes and link entities via BELONGS_TO edges."""
    created = 0

    for comm in communities:
        cid = comm["cid"]
        members = comm["members"]

        # Sort members by pagerank descending for title generation
        sorted_members = sorted(members, key=lambda m: m["pagerank"], reverse=True)
        top_names = [m["name"] for m in sorted_members[:5]]

        community_id = f"louvain_{group_id}_{cid}"
        title = f"Community {cid}: {', '.join(top_names)}"
        # Truncate title if too long
        if len(title) > 300:
            title = title[:297] + "..."

        avg_pagerank = sum(m["pagerank"] for m in members) / len(members)
        entity_ids = [m["id"] for m in members]

        if dry_run:
            print(f"  [DRY RUN] Would create {community_id}")
            print(f"    title: {title}")
            print(f"    members: {len(members)}")
            print(f"    rank: {avg_pagerank:.4f}")
            print()
            created += 1
            continue

        # Create Community node
        upsert_query = """
        MERGE (c:Community {id: $id, group_id: $group_id})
        SET c.level = 0,
            c.title = $title,
            c.summary = '',
            c.full_content = '',
            c.rank = $rank,
            c.group_id = $group_id,
            c.updated_at = datetime()
        RETURN c.id AS id
        """
        with driver.session() as session:
            session.run(
                upsert_query,
                id=community_id,
                group_id=group_id,
                title=title,
                rank=avg_pagerank,
            )

        # Create BELONGS_TO edges
        link_query = """
        MATCH (c:Community {id: $community_id, group_id: $group_id})
        UNWIND $entity_ids AS entity_id
        MATCH (e:Entity {id: entity_id, group_id: $group_id})
        MERGE (e)-[r:BELONGS_TO]->(c)
        SET r.group_id = $group_id
        """
        with driver.session() as session:
            session.run(
                link_query,
                community_id=community_id,
                group_id=group_id,
                entity_ids=entity_ids,
            )

        created += 1

    return created


# ---------------------------------------------------------------------------
# Step 4 (optional): Generate LLM summaries
# ---------------------------------------------------------------------------
def generate_llm_summaries(
    driver,
    group_id: str,
    communities: List[Dict],
    endpoint: str,
    deployment: str = "gpt-4.1",
) -> int:
    """Generate LLM summaries for each community and update Neo4j."""
    import openai

    token = get_azure_openai_token()
    if not token:
        print("ERROR: Cannot get Azure AD token for LLM summaries")
        return 0

    client = openai.AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token=token,
        api_version=AZURE_OPENAI_API_VERSION,
    )

    updated = 0

    for comm in communities:
        cid = comm["cid"]
        members = comm["members"]
        community_id = f"louvain_{group_id}_{cid}"

        # Fetch relationships between community entities
        rel_query = """
        MATCH (e1:Entity {group_id: $group_id})-[r:RELATED_TO]->(e2:Entity {group_id: $group_id})
        WHERE e1.community_id = $cid AND e2.community_id = $cid
        RETURN e1.name AS source, type(r) AS rel_type,
               coalesce(r.description, '') AS description, e2.name AS target
        LIMIT 30
        """
        with driver.session() as session:
            result = session.run(rel_query, group_id=group_id, cid=cid)
            relationships = [dict(r) for r in result]

        # Build prompt
        sorted_members = sorted(members, key=lambda m: m["pagerank"], reverse=True)
        entity_section = "\n".join(
            f"- {m['name']}: {m['description'][:200]}" if m['description']
            else f"- {m['name']}"
            for m in sorted_members[:30]
        )
        rel_section = "\n".join(
            f"- {r['source']} -> {r['target']}: {r['description'][:200]}" if r['description']
            else f"- {r['source']} -> {r['target']}"
            for r in relationships[:30]
        )

        prompt = (
            "You are summarising a community of related entities found in a set of legal/business documents.\n\n"
            f"Community has {len(members)} entities.\n\n"
            f"Key entities:\n{entity_section}\n\n"
        )
        if rel_section:
            prompt += f"Key relationships:\n{rel_section}\n\n"
        prompt += (
            "Write a response with exactly this format:\n"
            "TITLE: <short descriptive title, 5-10 words>\n"
            "SUMMARY: <1-2 sentence summary of what this community represents>\n"
        )

        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            text = response.choices[0].message.content.strip()

            # Parse TITLE: and SUMMARY:
            title = ""
            summary = ""
            for line in text.split("\n"):
                line = line.strip()
                if line.upper().startswith("TITLE:"):
                    title = line[6:].strip()
                elif line.upper().startswith("SUMMARY:"):
                    summary = line[8:].strip()

            if not title:
                title = f"Community {cid}"
            if not summary:
                summary = text[:300]

            # Update Neo4j
            update_query = """
            MATCH (c:Community {id: $community_id, group_id: $group_id})
            SET c.title = $title, c.summary = $summary, c.updated_at = datetime()
            """
            with driver.session() as session:
                session.run(
                    update_query,
                    community_id=community_id,
                    group_id=group_id,
                    title=title,
                    summary=summary,
                )

            print(f"  [{cid}] {title}")
            print(f"         {summary[:100]}...")
            updated += 1

        except Exception as e:
            print(f"  [{cid}] LLM error: {e}")

    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Materialize Community nodes from entity community_id assignments"
    )
    parser.add_argument("--group", required=True, help="Group ID (e.g. test-5pdfs-v2-fix2)")
    parser.add_argument("--min-size", type=int, default=2,
                        help="Min entities per community (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created without writing to Neo4j")
    parser.add_argument("--generate-summaries", action="store_true",
                        help="Generate LLM summaries via Azure OpenAI (requires auth)")
    parser.add_argument("--openai-endpoint", default=None,
                        help="Azure OpenAI endpoint URL (for --generate-summaries)")
    parser.add_argument("--openai-deployment", default="gpt-4.1",
                        help="Azure OpenAI deployment name (default: gpt-4.1)")
    parser.add_argument("--clean", action="store_true",
                        help="Delete existing Community nodes before creating new ones")
    args = parser.parse_args()

    print("=" * 70)
    print("COMMUNITY NODE MATERIALIZATION")
    print("=" * 70)
    print(f"  Group ID:     {args.group}")
    print(f"  Min size:     {args.min_size}")
    print(f"  Dry run:      {args.dry_run}")
    print(f"  LLM summaries: {args.generate_summaries}")
    print()

    driver = get_neo4j_driver()

    # Check existing
    existing = count_existing_communities(driver, args.group)
    print(f"Existing Community nodes: {existing}")

    if existing > 0 and args.clean:
        deleted = delete_existing_communities(driver, args.group)
        print(f"Deleted {deleted} existing Community nodes")
        existing = 0

    if existing > 0 and not args.clean:
        print(f"WARNING: {existing} Community nodes already exist. Use --clean to replace them.")
        print("Proceeding will merge/update existing nodes.\n")

    # Step 1: Read assignments
    print("\nStep 1: Reading community assignments from Entity nodes...")
    communities = read_community_assignments(driver, args.group, args.min_size)
    total_entities = sum(len(c["members"]) for c in communities)
    print(f"  Found {len(communities)} communities with {total_entities} entities "
          f"(min_size={args.min_size})")
    print()

    if not communities:
        print("No communities found. Check that entities have community_id set.")
        driver.close()
        return

    # Print community summary
    print("Community breakdown:")
    print(f"  {'CID':<6} {'Size':>5}  {'Avg PR':>8}  Top entities")
    print("  " + "-" * 68)
    for comm in communities:
        cid = comm["cid"]
        members = comm["members"]
        avg_pr = sum(m["pagerank"] for m in members) / len(members)
        sorted_m = sorted(members, key=lambda m: m["pagerank"], reverse=True)
        top = ", ".join(m["name"] for m in sorted_m[:3])
        if len(members) > 3:
            top += f" (+{len(members)-3} more)"
        print(f"  {cid:<6} {len(members):>5}  {avg_pr:>8.4f}  {top[:60]}")
    print()

    # Step 2: Create nodes
    print("Step 2: Creating Community nodes + BELONGS_TO edges...")
    t0 = time.time()
    created = create_community_nodes(driver, args.group, communities, dry_run=args.dry_run)
    elapsed = time.time() - t0
    print(f"  Created {created} Community nodes in {elapsed:.1f}s")
    print()

    # Step 3 (optional): LLM summaries
    summaries_generated = 0
    if args.generate_summaries and not args.dry_run:
        endpoint = args.openai_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        if not endpoint:
            print("WARNING: No --openai-endpoint or AZURE_OPENAI_ENDPOINT set. Skipping LLM summaries.")
        else:
            print("Step 3: Generating LLM summaries...")
            t0 = time.time()
            summaries_generated = generate_llm_summaries(
                driver, args.group, communities, endpoint, args.openai_deployment,
            )
            elapsed = time.time() - t0
            print(f"  Generated {summaries_generated} summaries in {elapsed:.1f}s")
            print()

    # Verify
    if not args.dry_run:
        final_count = count_existing_communities(driver, args.group)
        print("=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"  Community nodes in Neo4j:  {final_count}")
        print(f"  BELONGS_TO edges created:  {total_entities}")
        print(f"  LLM summaries generated:   {summaries_generated}")
        print()
        print("Note: Embeddings will be auto-generated by community_matcher")
        print("      on first query-time load via _ensure_embeddings().")
        print("=" * 70)

    driver.close()


if __name__ == "__main__":
    main()
