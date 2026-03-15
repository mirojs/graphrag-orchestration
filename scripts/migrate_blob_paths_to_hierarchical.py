#!/usr/bin/env python3
"""Migrate flat blob storage paths to hierarchical paths.

Existing layout:  {group_id}/{leaf_folder_name}/{filename}
Target layout:    {group_id}/{root}/{parent}/{child}/{filename}

Walks the Neo4j SUBFOLDER_OF chain to build the full path for each folder,
then copies blobs from the old path to the new path in ADLS Gen2.

Usage:
    # Dry run (default) — shows what would be moved
    python scripts/migrate_blob_paths_to_hierarchical.py

    # Actually move blobs
    python scripts/migrate_blob_paths_to_hierarchical.py --execute

    # Specific group only
    python scripts/migrate_blob_paths_to_hierarchical.py --group-id <gid> --execute
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.worker.services import GraphService
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient


def resolve_folder_paths(driver) -> dict[str, dict]:
    """Query Neo4j and build a mapping of {group_id}/{leaf_name} -> {group_id}/{hierarchical_path}.

    Returns dict keyed by (group_id, leaf_name) -> full_path.
    """
    query = """
    MATCH (f:Folder)
    OPTIONAL MATCH path = (f)-[:SUBFOLDER_OF*0..]->(root:Folder)
    WHERE NOT (root)-[:SUBFOLDER_OF]->()
    WITH f, path
    ORDER BY length(path) DESC
    WITH f, head(collect(path)) AS longest_path
    WITH f, [n IN nodes(longest_path) | n.name] AS names
    RETURN f.group_id AS gid, f.name AS leaf_name,
           reduce(p = '', i IN reverse(names) |
               CASE WHEN p = '' THEN i ELSE p + '/' + i END
           ) AS full_path
    """
    results = {}
    with driver.session() as session:
        for rec in session.run(query):
            gid = rec["gid"]
            leaf = rec["leaf_name"]
            full = rec["full_path"]
            if leaf != full:  # Only include folders that actually need migration
                results[(gid, leaf)] = full
    return results


async def migrate(execute: bool, group_filter: str | None):
    # Connect to Neo4j
    gs = GraphService()
    if not gs.driver:
        print("ERROR: Cannot connect to Neo4j")
        return

    folder_map = resolve_folder_paths(gs.driver)
    if not folder_map:
        print("No folders need migration (all are already root-level).")
        return

    print(f"Found {len(folder_map)} folder(s) needing path migration:")
    for (gid, leaf), full in folder_map.items():
        print(f"  [{gid[:8]}...] {leaf} -> {full}")
    print()

    # Connect to ADLS Gen2
    account = os.environ.get("AZURE_USERSTORAGE_ACCOUNT", "neo4jstorage21224")
    container_name = os.environ.get("AZURE_USERSTORAGE_CONTAINER", "user-content")
    endpoint = f"https://{account}.blob.core.windows.net"

    credential = DefaultAzureCredential()
    blob_service = BlobServiceClient(endpoint, credential=credential)
    container = blob_service.get_container_client(container_name)

    moved = 0
    skipped = 0
    errors = 0

    try:
        for (gid, leaf_name), full_path in folder_map.items():
            if group_filter and gid != group_filter:
                continue

            old_prefix = f"{gid}/{leaf_name}/"
            new_prefix = f"{gid}/{full_path}/"

            print(f"\nScanning {old_prefix} ...")
            async for blob in container.list_blobs(name_starts_with=old_prefix):
                # Skip directory markers
                if blob.size == 0 and not blob.name.endswith(".json"):
                    continue

                relative = blob.name[len(old_prefix):]
                new_name = f"{new_prefix}{relative}"

                # Check if destination already exists
                dest_blob = container.get_blob_client(new_name)
                try:
                    await dest_blob.get_blob_properties()
                    print(f"  SKIP (exists): {blob.name} -> {new_name}")
                    skipped += 1
                    continue
                except Exception:
                    pass  # Doesn't exist — good, proceed

                if execute:
                    try:
                        source_blob = container.get_blob_client(blob.name)
                        source_url = source_blob.url
                        await dest_blob.start_copy_from_url(source_url)
                        # Verify copy succeeded
                        props = await dest_blob.get_blob_properties()
                        if props.copy.status == "success":
                            await source_blob.delete_blob()
                            print(f"  MOVED: {blob.name} -> {new_name}")
                            moved += 1
                        else:
                            print(f"  ERROR: Copy not successful for {blob.name}: {props.copy.status}")
                            errors += 1
                    except Exception as e:
                        print(f"  ERROR: {blob.name}: {e}")
                        errors += 1
                else:
                    print(f"  WOULD MOVE: {blob.name} -> {new_name}")
                    moved += 1

    finally:
        await credential.close()
        await blob_service.close()

    print(f"\n{'=' * 50}")
    print(f"{'DRY RUN' if not execute else 'MIGRATION'} COMPLETE")
    print(f"  Moved: {moved}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")
    if not execute and moved > 0:
        print(f"\nRe-run with --execute to apply changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate flat blob paths to hierarchical")
    parser.add_argument("--execute", action="store_true", help="Actually move blobs (default is dry run)")
    parser.add_argument("--group-id", help="Only migrate a specific group_id")
    args = parser.parse_args()

    asyncio.run(migrate(execute=args.execute, group_filter=args.group_id))
