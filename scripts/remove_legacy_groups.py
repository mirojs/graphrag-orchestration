#!/usr/bin/env python3
"""
Safely remove legacy group data from Neo4j, keeping a specified group.

Usage:
  # Dry run (shows groups and counts)
  python scripts/remove_legacy_groups.py --keep test-cypher25-final-1768129960 --dry-run

  # Commit (will backup then delete)
  python scripts/remove_legacy_groups.py --keep test-cypher25-final-1768129960 --commit

The script will:
  - Connect to Neo4j using settings (env vars in .env)
  - Enumerate distinct group_id values present
  - Backup nodes and relationships for groups to backups/groups_<group>_<timestamp>.json
  - Delete nodes/relationships for legacy groups (non-reversible unless restored from backup)

BE CAREFUL: This is destructive. Use --dry-run first.
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


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument('--keep', required=True, help='Group id to KEEP')
    p.add_argument('--dry-run', action='store_true', help='Show groups and counts, do not delete')
    p.add_argument('--commit', action='store_true', help='Perform backups and deletions')
    return p.parse_args()


def main():
    args = get_args()
    gs = GraphService()
    if gs.driver is None:
        print('Neo4j driver not configured in environment; aborting')
        sys.exit(1)

    keep = args.keep

    # Find distinct group_ids
    # Use IS NOT NULL (exists(...) syntax is deprecated in Cypher 25)
    query = """
    MATCH (n)
    WHERE n.group_id IS NOT NULL
    RETURN DISTINCT n.group_id AS gid, count(*) AS cnt
    ORDER BY cnt DESC
    """

    with gs.driver.session() as session:
        res = session.run(query)
        groups = [(r['gid'], r['cnt']) for r in res]

    print('Discovered groups:')
    for gid, cnt in groups:
        print(f' - {gid}: {cnt} nodes')

    legacy = [gid for gid, _ in groups if gid != keep]

    if not legacy:
        print('No legacy groups found. Nothing to do.')
        return

    print('\nLegacy groups to remove:')
    for gid in legacy:
        print(f' - {gid}')

    if args.dry_run:
        print('\nDry run requested; exiting before any destructive action.')
        return

    if not args.commit:
        print('\nNo --commit flag provided; use --commit to perform deletion (and backups).')
        return

    # Back up and delete each legacy group
    backups_dir = os.path.join(root, 'backups')
    os.makedirs(backups_dir, exist_ok=True)

    for gid in legacy:
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        backup_file = os.path.join(backups_dir, f'group_backup_{gid}_{ts}.json')
        print(f'Backing up group {gid} to {backup_file}...')

        # Export nodes and relationships for this group
        export_query = """
        MATCH (n)
        WHERE n.group_id = $group_id
        OPTIONAL MATCH (n)-[r]-(m)
        WHERE m.group_id = $group_id
        RETURN collect(distinct n) as nodes, collect(distinct r) as rels
        """
        with gs.driver.session() as session:
            r = session.run(export_query, group_id=gid)
            rec = r.single()
            nodes = []
            rels = []
            if rec:
                nodes = [dict(n) for n in rec['nodes']]
                # Relationships are not easy to serialize directly; get minimal: start/end/type/properties
                for rel in rec['rels']:
                    try:
                        rels.append({
                            'start': rel.start_node.id,
                            'end': rel.end_node.id,
                            'type': rel.type,
                            'properties': dict(rel)
                        })
                    except Exception:
                        pass

        with open(backup_file, 'w') as fh:
            json.dump({'group_id': gid, 'nodes': nodes, 'rels': rels}, fh, default=str)
        print('Backup complete.')

        # Delete nodes and relationships for the group
        delete_query = """
        MATCH (n)
        WHERE n.group_id = $group_id
        DETACH DELETE n
        """
        with gs.driver.session() as session:
            session.run(delete_query, group_id=gid)
        print(f'Deleted all nodes for group {gid}.')

    print('\nDone. Legacy groups removed. Verify system health and re-run small set of tests.')


if __name__ == '__main__':
    main()
