#!/usr/bin/env python3
"""
Restore relationships for an already-restored group by pattern matching.

Since the backup format uses old internal Neo4j IDs that don't survive restoration,
this script rebuilds critical relationships using property-based heuristics:
- PART_OF: TextChunk/Section -> Document (match by document_id in chunk metadata)
- IN_SECTION: TextChunk -> Section (match by section_path in metadata)
- Other relationships reconstructed where possible

Usage:
  export NEO4J_URI="neo4j+s://..."
  export NEO4J_USERNAME="neo4j"
  export NEO4J_PASSWORD="..."
  export NEO4J_DATABASE="neo4j"
  
  python scripts/restore_group_relationships.py --group-id test-5pdfs-1767429340223041632 --dry-run
  python scripts/restore_group_relationships.py --group-id test-5pdfs-1767429340223041632 --commit
"""

import argparse
import json
import os
import sys
from datetime import datetime

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pkg_dir = os.path.join(root, 'graphrag-orchestration')
if os.path.isdir(pkg_dir):
    sys.path.insert(0, pkg_dir)

from src.worker.services.graph_service import GraphService


def restore_part_of_relationships(session, group_id, dry_run=False):
    """Restore PART_OF relationships: TextChunk -> Document"""
    
    # Find all TextChunks and extract document info from metadata
    query = """
    MATCH (c:TextChunk {group_id: $group_id})
    WHERE c.metadata IS NOT NULL
    WITH c, 
         apoc.convert.fromJsonMap(c.metadata) AS meta
    WHERE meta.url IS NOT NULL
    MATCH (d:Document {group_id: $group_id, source: meta.url})
    RETURN elementId(c) AS chunk_id, elementId(d) AS doc_id, c.id AS chunk_uuid, d.id AS doc_uuid
    """
    
    try:
        result = session.run(query, group_id=group_id)
        pairs = [(r['chunk_id'], r['doc_id']) for r in result]
        
        if dry_run:
            print(f"  [DRY RUN] Would create {len(pairs)} PART_OF relationships (TextChunk -> Document)")
            return 0
        
        # Create relationships in batch
        create_query = """
        UNWIND $pairs AS pair
        MATCH (c), (d)
        WHERE elementId(c) = pair[0] AND elementId(d) = pair[1]
        MERGE (c)-[:PART_OF]->(d)
        """
        
        session.run(create_query, pairs=pairs)
        print(f"  ✓ Created {len(pairs)} PART_OF relationships (TextChunk -> Document)")
        return len(pairs)
        
    except Exception as e:
        print(f"  ⚠ PART_OF restoration failed: {e}")
        # Try without apoc (manual JSON parsing)
        print(f"  → Trying fallback approach...")
        
        # Simpler approach: match by document source URL
        fallback_query = """
        MATCH (c:TextChunk {group_id: $group_id})
        MATCH (d:Document {group_id: $group_id})
        WHERE c.id STARTS WITH d.id
        RETURN elementId(c) AS chunk_id, elementId(d) AS doc_id
        """
        
        result = session.run(fallback_query, group_id=group_id)
        pairs = [(r['chunk_id'], r['doc_id']) for r in result]
        
        if dry_run:
            print(f"  [DRY RUN] Would create {len(pairs)} PART_OF relationships (fallback)")
            return 0
        
        if pairs:
            create_query = """
            UNWIND $pairs AS pair
            MATCH (c), (d)
            WHERE elementId(c) = pair[0] AND elementId(d) = pair[1]
            MERGE (c)-[:PART_OF]->(d)
            """
            session.run(create_query, pairs=pairs)
            print(f"  ✓ Created {len(pairs)} PART_OF relationships (fallback)")
            return len(pairs)
        
        return 0


def restore_in_section_relationships(session, group_id, dry_run=False):
    """Restore IN_SECTION relationships: TextChunk -> Section"""
    
    # Match chunks to sections by section_path in metadata
    query = """
    MATCH (c:TextChunk {group_id: $group_id})
    WHERE c.metadata IS NOT NULL
    MATCH (s:Section {group_id: $group_id})
    WHERE c.id CONTAINS s.id
    RETURN elementId(c) AS chunk_id, elementId(s) AS section_id
    LIMIT 10000
    """
    
    try:
        result = session.run(query, group_id=group_id)
        pairs = [(r['chunk_id'], r['section_id']) for r in result]
        
        if dry_run:
            print(f"  [DRY RUN] Would create {len(pairs)} IN_SECTION relationships (TextChunk -> Section)")
            return 0
        
        if pairs:
            create_query = """
            UNWIND $pairs AS pair
            MATCH (c), (s)
            WHERE elementId(c) = pair[0] AND elementId(s) = pair[1]
            MERGE (c)-[:IN_SECTION]->(s)
            """
            session.run(create_query, pairs=pairs)
            print(f"  ✓ Created {len(pairs)} IN_SECTION relationships (TextChunk -> Section)")
        
        return len(pairs)
        
    except Exception as e:
        print(f"  ⚠ IN_SECTION restoration skipped: {e}")
        return 0


def restore_section_hierarchy(session, group_id, dry_run=False):
    """Restore SUBSECTION_OF relationships: Section -> Section (parent)"""
    
    # This requires section_path analysis - skip for now
    print(f"  → SUBSECTION_OF relationships require section_path metadata (skipping)")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--group-id', required=True, help='Group ID to restore relationships for')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--commit', action='store_true', help='Execute the restoration')
    args = parser.parse_args()

    if not args.dry_run and not args.commit:
        print("ERROR: Must specify either --dry-run or --commit")
        sys.exit(1)

    group_id = args.group_id
    
    # Connect to Neo4j
    gs = GraphService()
    if gs.driver is None:
        print('ERROR: Neo4j driver not configured')
        print('Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD environment variables')
        sys.exit(1)

    print(f"\n{'[DRY RUN] ' if args.dry_run else '[COMMIT] '}Restoring relationships for group: {group_id}")
    
    total_created = 0
    
    with gs.driver.session() as session:
        # Verify group exists
        verify_query = "MATCH (n {group_id: $group_id}) RETURN count(n) AS cnt"
        result = session.run(verify_query, group_id=group_id)
        node_count = result.single()['cnt']
        
        if node_count == 0:
            print(f"ERROR: No nodes found for group_id={group_id}")
            sys.exit(1)
        
        print(f"Found {node_count} nodes for group {group_id}")
        
        # Restore relationship types
        print("\n1. Restoring PART_OF relationships (TextChunk/Section -> Document)...")
        total_created += restore_part_of_relationships(session, group_id, args.dry_run)
        
        print("\n2. Restoring IN_SECTION relationships (TextChunk -> Section)...")
        total_created += restore_in_section_relationships(session, group_id, args.dry_run)
        
        print("\n3. Checking section hierarchy...")
        total_created += restore_section_hierarchy(session, group_id, args.dry_run)
        
        # Report summary
        if not args.dry_run:
            rel_count_query = """
            MATCH (n {group_id: $group_id})-[r]-(m)
            WHERE m.group_id = $group_id
            RETURN count(DISTINCT r) AS rel_count
            """
            result = session.run(rel_count_query, group_id=group_id)
            final_rels = result.single()['rel_count']
            
            print(f"\n✓ Restoration complete!")
            print(f"  Total relationships created: {total_created}")
            print(f"  Total relationships in group: {final_rels}")
        else:
            print(f"\n[DRY RUN] Would create {total_created} relationships total")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
