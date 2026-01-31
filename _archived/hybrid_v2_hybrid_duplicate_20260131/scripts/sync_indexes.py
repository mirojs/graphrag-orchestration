#!/usr/bin/env python3
"""
Dual Indexing CLI Script

Synchronizes GraphRAG data from Neo4j to HippoRAG format for the Hybrid Pipeline.

Usage:
    # Full sync for a specific group
    python -m app.hybrid.scripts.sync_indexes --group-id my-tenant
    
    # Sync all groups
    python -m app.hybrid.scripts.sync_indexes --all-groups
    
    # Dry run (show what would be indexed)
    python -m app.hybrid.scripts.sync_indexes --group-id my-tenant --dry-run
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.worker.hybrid_v2.indexing.dual_index import DualIndexService
from src.worker.services.graph_service import GraphService
from src.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


async def sync_group(group_id: str, output_dir: str, dry_run: bool = False) -> dict:
    """Sync a single group's data to HippoRAG format."""
    logger.info("sync_group_start", group_id=group_id, dry_run=dry_run)
    
    if dry_run:
        # Just check what would be indexed
        graph_service = GraphService()
        driver = graph_service.driver
        
        if not driver:
            return {"status": "error", "error": "Neo4j not configured"}
        
        with driver.session() as session:
            # Count entities
            entity_count = session.run(
                "MATCH (e) WHERE e.group_id = $gid AND NOT e:__Community__ AND NOT e:__Chunk__ RETURN count(e) as cnt",
                gid=group_id
            ).single()["cnt"]
            
            # Count relationships
            rel_count = session.run(
                "MATCH (s)-[r]->(o) WHERE s.group_id = $gid RETURN count(r) as cnt",
                gid=group_id
            ).single()["cnt"]
            
            # Count chunks
            chunk_count = session.run(
                "MATCH (c:__Chunk__) WHERE c.group_id = $gid RETURN count(c) as cnt",
                gid=group_id
            ).single()["cnt"]
        
        return {
            "status": "dry_run",
            "group_id": group_id,
            "would_index": {
                "entities": entity_count,
                "relationships": rel_count,
                "text_chunks": chunk_count
            }
        }
    
    # Actual sync
    graph_service = GraphService()
    
    dual_index = DualIndexService(
        neo4j_driver=graph_service.driver,
        hipporag_save_dir=output_dir,
        group_id=group_id
    )
    
    result = await dual_index.sync_from_neo4j()
    return result


async def get_all_groups() -> list:
    """Get all unique group_ids from Neo4j."""
    graph_service = GraphService()
    
    if not graph_service.driver:
        return []
    
    with graph_service.driver.session() as session:
        result = session.run(
            "MATCH (n) WHERE n.group_id IS NOT NULL RETURN DISTINCT n.group_id as gid"
        )
        return [record["gid"] for record in result]


async def main():
    parser = argparse.ArgumentParser(
        description="Sync GraphRAG data to HippoRAG format for the Hybrid Pipeline"
    )
    
    parser.add_argument(
        "--group-id", "-g",
        help="Group ID to sync (tenant identifier)"
    )
    
    parser.add_argument(
        "--all-groups", "-a",
        action="store_true",
        help="Sync all groups found in Neo4j"
    )
    
    parser.add_argument(
        "--output-dir", "-o",
        default="./hipporag_index",
        help="Output directory for HippoRAG indexes (default: ./hipporag_index)"
    )
    
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be indexed without actually syncing"
    )
    
    args = parser.parse_args()
    
    if not args.group_id and not args.all_groups:
        parser.error("Either --group-id or --all-groups is required")
    
    results = []
    
    if args.all_groups:
        groups = await get_all_groups()
        if not groups:
            print("No groups found in Neo4j")
            return
        
        print(f"Found {len(groups)} groups to sync")
        
        for gid in groups:
            result = await sync_group(gid, args.output_dir, args.dry_run)
            results.append(result)
            print(f"  [{result['status']}] {gid}")
    else:
        result = await sync_group(args.group_id, args.output_dir, args.dry_run)
        results.append(result)
    
    # Summary
    print("\n" + "="*60)
    print("SYNC SUMMARY")
    print("="*60)
    
    for r in results:
        if r["status"] == "success":
            print(f"\n✅ {r.get('group_id', 'unknown')}")
            print(f"   Entities: {r.get('entities_indexed', 0)}")
            print(f"   Triples: {r.get('triples_indexed', 0)}")
            print(f"   Text Units: {r.get('text_units_indexed', 0)}")
        elif r["status"] == "dry_run":
            print(f"\n📋 {r.get('group_id', 'unknown')} (dry run)")
            would = r.get("would_index", {})
            print(f"   Would index {would.get('entities', 0)} entities")
            print(f"   Would index {would.get('relationships', 0)} relationships")
            print(f"   Would index {would.get('text_chunks', 0)} text chunks")
        else:
            print(f"\n❌ {r.get('group_id', 'unknown')}: {r.get('error', 'unknown error')}")


if __name__ == "__main__":
    asyncio.run(main())
