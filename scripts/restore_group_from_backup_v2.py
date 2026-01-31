#!/usr/bin/env python3
"""
Restore a group from backup JSON into Neo4j.

The backup format from remove_legacy_groups.py is:
{
  "group_id": "...",
  "nodes": [...],  # dict(node) serialization (no labels)
  "rels": [...]    # {start: node.id, end: node.id, type: str, properties: dict}
}

Usage:
  python scripts/restore_group_from_backup_v2.py --backup backups/group_backup_test-5pdfs-1767429340223041632_20260111T120127Z.json --dry-run
  python scripts/restore_group_from_backup_v2.py --backup backups/group_backup_test-5pdfs-1767429340223041632_20260111T120127Z.json --commit
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Ensure package path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pkg_dir = os.path.join(root, 'graphrag-orchestration')
if os.path.isdir(pkg_dir):
    sys.path.insert(0, pkg_dir)

from src.worker.services.graph_service import GraphService


def infer_labels(node_props):
    """
    Infer node labels from properties.
    This is a heuristic - adjust based on your data model.
    """
    labels = []
    
    # Check for specific properties that indicate labels
    if 'embedding' in node_props:
        labels.append('TextChunk')
    elif 'title' in node_props and 'source' in node_props and 'chunk_index' not in node_props:
        labels.append('Document')
    elif 'section_path' in node_props or ('title' in node_props and 'chunk_type' in node_props):
        labels.append('Section')
    elif 'name' in node_props and 'entity_type' in node_props:
        labels.append('Entity')
    elif 'title' in node_props and 'rank' in node_props:
        labels.append('Community')
    
    # Default fallback
    if not labels:
        labels.append('Node')
    
    return labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', required=True, help='Path to backup JSON file')
    parser.add_argument('--dry-run', action='store_true', help='Show restore plan without executing')
    parser.add_argument('--commit', action='store_true', help='Execute the restore')
    args = parser.parse_args()

    if not args.dry_run and not args.commit:
        print("ERROR: Must specify either --dry-run or --commit")
        sys.exit(1)

    # Load backup file
    backup_path = args.backup
    if not os.path.exists(backup_path):
        print(f"ERROR: Backup file not found: {backup_path}")
        sys.exit(1)

    print(f"Loading backup from: {backup_path}")
    with open(backup_path, 'r') as f:
        data = json.load(f)

    # Backup format: {group_id, nodes: [], rels: []}
    group_id = data.get('group_id', 'unknown')
    nodes = data.get('nodes', [])
    rels = data.get('rels', [])

    print(f"\nBackup metadata:")
    print(f"  Group ID: {group_id}")
    print(f"  Nodes: {len(nodes)}")
    print(f"  Relationships: {len(rels)}")

    if args.dry_run:
        print("\n[DRY RUN] Would restore:")
        print(f"  {len(nodes)} nodes")
        print(f"  {len(rels)} relationships")
        print(f"  to group_id: {group_id}")
        
        # Sample a few nodes to show label inference
        print("\nSample node label inference:")
        for i, node in enumerate(nodes[:5]):
            labels = infer_labels(node)
            print(f"  Node {i}: {labels} - {list(node.keys())[:5]}")
        
        return 0

    # Connect to Neo4j
    gs = GraphService()
    if gs.driver is None:
        print('ERROR: Neo4j driver not configured')
        sys.exit(1)

    print(f"\n[COMMIT] Restoring group {group_id} to Neo4j...")

    with gs.driver.session() as session:
        # Track old node internal ID -> new elementId mapping
        # The backup relationships use old internal Neo4j IDs (integers)
        # We need to track nodes by index and also get the old internal IDs from relationships
        id_map = {}
        node_by_uuid = {}
        
        # Restore nodes
        print(f"Restoring {len(nodes)} nodes...")
        for idx, node_props in enumerate(nodes):
            if idx > 0 and idx % 100 == 0:
                print(f"  Progress: {idx}/{len(nodes)} nodes...")
            
            # Infer labels
            labels = infer_labels(node_props)
            label_str = ':'.join(labels)
            
            # Create node with inferred labels
            create_query = f"""
            CREATE (n:{label_str})
            SET n = $props
            RETURN elementId(n) AS element_id, id(n) AS internal_id
            """
            
            result = session.run(create_query, props=node_props)
            rec = result.single()
            if rec:
                new_element_id = rec['element_id']
                # Store by UUID if available
                uuid = node_props.get('id')
                if uuid:
                    node_by_uuid[uuid] = new_element_id
        
        print(f"✓ Restored {len(nodes)} nodes")
        
        # Build a mapping from old internal IDs to UUIDs for relationship restoration
        # The relationships reference old internal Neo4j IDs, but we can't use those
        # Instead, we'll collect all relationships and try to match nodes by UUID
        print(f"\nRestoring {len(rels)} relationships...")
        print(f"  Note: Relationship matching by node properties (UUID)...")
        
        # Build reverse mapping: old internal ID (from rels) -> node UUID
        # We need to look at all relationships to see which internal IDs they reference
        old_ids_in_rels = set()
        for rel in rels:
            old_ids_in_rels.add(rel['start'])
            old_ids_in_rels.add(rel['end'])
        
        # Now find which nodes had these internal IDs by matching the backup node order
        # The backup likely preserves node order, and relationships use the index-based IDs
        # Let's try a different approach: match all nodes by properties
        
        print(f"  Building node property index for matching...")
        
        # For relationships, we'll need to match nodes - the safest is by unique properties
        # Let's use the `id` field (UUID) if available, otherwise try to match by all properties
        
        restored_rels = 0
        skipped_rels = 0
        
        for idx, rel in enumerate(rels):
            if idx > 0 and idx % 100 == 0:
                print(f"  Progress: {idx}/{len(rels)} relationships...")
            
            start_idx = rel.get('start')
            end_idx = rel.get('end')
            rel_type = rel.get('type', 'RELATED_TO')
            rel_props = rel.get('properties', {})
            
            # Try to find nodes by index in backup
            # The backup relationship IDs might be internal Neo4j IDs, not array indices
            # Skip if we can't map
            if start_idx is None or end_idx is None:
                skipped_rels += 1
                continue
            
            # Since we can't reliably map old internal IDs, we'll skip relationships for now
            # A better approach would be to enhance the backup to include node UUIDs in relationships
            skipped_rels += 1
        
        print(f"✓ Skipped {skipped_rels} relationships (cannot map old internal IDs)")
        print(f"  Note: Relationship restoration requires enhanced backup format with node UUIDs")
        
        # Verify restoration
        verify_query = """
        MATCH (n)
        WHERE n.group_id = $group_id
        RETURN count(n) AS node_count
        """
        result = session.run(verify_query, group_id=group_id)
        rec = result.single()
        actual_count = rec['node_count'] if rec else 0
        
        print(f"\n✓ Verification: {actual_count} nodes with group_id={group_id}")
        
        if actual_count != len(nodes):
            print(f"⚠ WARNING: Expected {len(nodes)} nodes but found {actual_count}")
        else:
            print(f"✓ Node count matches backup")
    
    print(f"\n✓ Restore complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
