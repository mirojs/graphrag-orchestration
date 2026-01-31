
#!/usr/bin/env python3
"""
Restore a group from backup JSON into Neo4j.

Usage:
  python scripts/restore_group_from_backup.py --backup backups/group_backup_test-5pdfs-1767429340223041632_20260111T120127Z.json --dry-run
  python scripts/restore_group_from_backup.py --backup backups/group_backup_test-5pdfs-1767429340223041632_20260111T120127Z.json --commit
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

    # Backup format: {group_id, nodes: [], relationships: []}
    group_id = data.get('group_id', 'unknown')
    nodes = data.get('nodes', [])
    relationships = data.get('relationships', [])

    print(f"\nBackup metadata:")
    print(f"  Group ID: {group_id}")
    print(f"  Nodes: {len(nodes)}")
    print(f"  Relationships: {len(relationships)}")

    if args.dry_run:
        print("\n[DRY RUN] Would restore:")
        print(f"  {len(nodes)} nodes")
        print(f"  {len(relationships)} relationships")
        print(f"  to group_id: {group_id}")
        return 0

    # Connect to Neo4j
    gs = GraphService()
    if gs.driver is None:
        print('ERROR: Neo4j driver not configured')
        sys.exit(1)

    print(f"\n[COMMIT] Restoring {len(nodes)} nodes and {len(relationships)} relationships...")

    # Restore nodes
    print("Restoring nodes...")
    node_id_map = {}  # Map from backup node index to actual neo4j id
    
    with gs.driver.session() as session:
        for idx, node_data in enumerate(nodes):
            if idx % 100 == 0:
                print(f"  Progress: {idx}/{len(nodes)} nodes")
            
            labels = node_data.get('labels', [])
            props = node_data.get('properties', {})
            
            # Build CREATE query with labels and properties
            labels_str = ':'.join(labels) if labels else 'Node'
            
            # Create node
            query = f"CREATE (n:{labels_str}) SET n = $props RETURN elementId(n) AS id"
            result = session.run(query, props=props)
            record = result.single()
            if record:
                node_id_map[idx] = record['id']

    print(f"Restored {len(nodes)} nodes")

    # Restore relationships
    print("Restoring relationships...")
    with gs.driver.session() as session:
        for idx, rel_data in enumerate(relationships):
            if idx % 100 == 0:
                print(f"  Progress: {idx}/{len(relationships)} relationships")
            
            start_idx = rel_data.get('start')
            end_idx = rel_data.get('end')
            rel_type = rel_data.get('type', 'RELATED_TO')
            props = rel_data.get('properties', {})
            
            if start_idx not in node_id_map or end_idx not in node_id_map:
                continue
            
            start_id = node_id_map[start_idx]
            end_id = node_id_map[end_idx]
            
            # Create relationship
            query = f"""
            MATCH (a), (b)
            WHERE elementId(a) = $start_id AND elementId(b) = $end_id
            CREATE (a)-[r:{rel_type}]->(b)
            SET r = $props
            """
            session.run(query, start_id=start_id, end_id=end_id, props=props)

    print(f"Restored {len(relationships)} relationships")

    # Verify
    with gs.driver.session() as session:
        result = session.run("MATCH (n {group_id: $group_id}) RETURN count(n) AS cnt", group_id=group_id)
        record = result.single()
        verify_count = record['cnt'] if record else 0
        print(f"\nVerification: {verify_count} nodes with group_id={group_id}")

    print("\n✅ Restore complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
