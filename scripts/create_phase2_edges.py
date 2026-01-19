#!/usr/bin/env python3
"""
Create Phase 2 Connectivity Edges (SHARES_ENTITY)

This script backfills SHARES_ENTITY edges for existing indexed corpora.
Run this after Phase 1 foundation edges are created.

Usage:
    python scripts/create_phase2_edges.py --group-id test-5pdfs-1768557493369886422
    
Or with environment variable:
    export GROUP_ID=test-5pdfs-1768557493369886422
    python scripts/create_phase2_edges.py
"""

import os
import sys
import argparse

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", "graphrag-orchestration"))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(SERVICE_ROOT, '.env'))

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def create_shares_entity_edges(group_id: str, min_shared_entities: int = 2) -> dict:
    """Create SHARES_ENTITY edges between sections that share entities.
    
    Args:
        group_id: The group ID to process
        min_shared_entities: Minimum number of shared entities to create an edge (default: 2)
        
    Returns:
        Dictionary with stats: {"edges_created": N, "cross_doc_pairs": M}
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    stats = {
        "edges_created": 0,
        "cross_doc_pairs": 0,
    }
    
    with driver.session() as session:
        # First, check how many potential cross-doc section pairs exist
        result = session.run(
            """
            MATCH (s1:Section {group_id: $group_id})<-[:IN_SECTION]-(c1:TextChunk)
                  -[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(c2:TextChunk)
                  -[:IN_SECTION]->(s2:Section {group_id: $group_id})
            WHERE s1 <> s2 AND s1.doc_id <> s2.doc_id
            WITH s1, s2, count(DISTINCT e) AS shared_count
            WHERE shared_count >= $min_shared
            RETURN count(*) AS pair_count
            """,
            group_id=group_id,
            min_shared=min_shared_entities,
        )
        stats["cross_doc_pairs"] = result.single()["pair_count"]
        
        # Create SHARES_ENTITY edges
        result = session.run(
            """
            MATCH (s1:Section {group_id: $group_id})<-[:IN_SECTION]-(c1:TextChunk)
                  -[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(c2:TextChunk)
                  -[:IN_SECTION]->(s2:Section {group_id: $group_id})
            WHERE s1 <> s2
              AND s1.doc_id <> s2.doc_id  // Cross-document only
            WITH s1, s2, collect(DISTINCT e.name) AS shared_entities, count(DISTINCT e) AS shared_count
            WHERE shared_count >= $min_shared  // Threshold
            MERGE (s1)-[r:SHARES_ENTITY]->(s2)
            SET r.shared_entities = shared_entities[0..10],
                r.shared_count = shared_count,
                r.similarity_boost = shared_count * 0.1,
                r.group_id = $group_id,
                r.created_at = datetime()
            RETURN count(r) AS count
            """,
            group_id=group_id,
            min_shared=min_shared_entities,
        )
        stats["edges_created"] = result.single()["count"]
    
    driver.close()
    return stats


def check_existing_edges(group_id: str) -> dict:
    """Check what edges already exist for a group."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Phase 1 edges
        result = session.run(
            """
            MATCH ()-[r:APPEARS_IN_SECTION]->()
            WHERE r.group_id = $group_id OR EXISTS { 
                MATCH (e:Entity {group_id: $group_id})-[r2:APPEARS_IN_SECTION]->() 
            }
            RETURN count(r) AS count
            """,
            group_id=group_id,
        )
        appears_in_section = result.single()["count"]
        
        result = session.run(
            """
            MATCH (e:Entity {group_id: $group_id})-[r:APPEARS_IN_DOCUMENT]->()
            RETURN count(r) AS count
            """,
            group_id=group_id,
        )
        appears_in_document = result.single()["count"]
        
        result = session.run(
            """
            MATCH (s:Section {group_id: $group_id})-[r:HAS_HUB_ENTITY]->()
            RETURN count(r) AS count
            """,
            group_id=group_id,
        )
        has_hub_entity = result.single()["count"]
        
        # Phase 2 edges
        result = session.run(
            """
            MATCH ()-[r:SHARES_ENTITY]->()
            WHERE r.group_id = $group_id
            RETURN count(r) AS count
            """,
            group_id=group_id,
        )
        shares_entity = result.single()["count"]
    
    driver.close()
    
    return {
        "phase1": {
            "APPEARS_IN_SECTION": appears_in_section,
            "APPEARS_IN_DOCUMENT": appears_in_document,
            "HAS_HUB_ENTITY": has_hub_entity,
        },
        "phase2": {
            "SHARES_ENTITY": shares_entity,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Create Phase 2 SHARES_ENTITY edges for cross-document section linking"
    )
    parser.add_argument(
        "--group-id",
        default=os.getenv("GROUP_ID", "test-5pdfs-1768557493369886422"),
        help="Group ID to process"
    )
    parser.add_argument(
        "--min-shared",
        type=int,
        default=2,
        help="Minimum shared entities to create edge (default: 2)"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check existing edges, don't create new ones"
    )
    args = parser.parse_args()
    
    print("=" * 70)
    print("Phase 2 Connectivity Edges - SHARES_ENTITY")
    print("=" * 70)
    print(f"Group ID: {args.group_id}")
    print(f"Min shared entities: {args.min_shared}")
    print()
    
    # Check existing edges
    print("Checking existing edges...")
    existing = check_existing_edges(args.group_id)
    
    print("\nPhase 1 (Foundation) edges:")
    for edge_type, count in existing["phase1"].items():
        status = "✅" if count > 0 else "❌"
        print(f"  {status} {edge_type}: {count}")
    
    print("\nPhase 2 (Connectivity) edges:")
    for edge_type, count in existing["phase2"].items():
        status = "✅" if count > 0 else "⏳"
        print(f"  {status} {edge_type}: {count}")
    
    if args.check_only:
        print("\n[check-only mode - not creating edges]")
        return
    
    # Create Phase 2 edges
    print("\nCreating SHARES_ENTITY edges...")
    stats = create_shares_entity_edges(args.group_id, args.min_shared)
    
    print(f"\n✅ Phase 2 edges created:")
    print(f"   Cross-doc section pairs found: {stats['cross_doc_pairs']}")
    print(f"   SHARES_ENTITY edges created: {stats['edges_created']}")
    
    # Verify
    print("\nVerifying final state...")
    final = check_existing_edges(args.group_id)
    print(f"   SHARES_ENTITY total: {final['phase2']['SHARES_ENTITY']}")
    
    print("\n" + "=" * 70)
    print("Done! Phase 2 connectivity edges are ready.")
    print("=" * 70)


if __name__ == "__main__":
    main()
