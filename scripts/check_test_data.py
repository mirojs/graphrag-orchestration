#!/usr/bin/env python3
"""Check if indexing is complete for test-3072-clean"""

from neo4j import GraphDatabase
import os
import sys

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
GROUP_ID = "test-3072-clean"

if not NEO4J_PASSWORD:
    print("Error: NEO4J_PASSWORD environment variable not set")
    sys.exit(1)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

print("=" * 70)
print(f"CHECKING NEO4J DATA FOR GROUP: {GROUP_ID}")
print("=" * 70)

with driver.session() as session:
    # Total nodes
    result = session.run("""
        MATCH (n {group_id: $group_id})
        RETURN count(n) as count
    """, group_id=GROUP_ID)
    total = result.single()['count']
    print(f"\nTotal nodes: {total}")
    
    # By label
    result = session.run("""
        MATCH (n {group_id: $group_id})
        RETURN labels(n)[0] as label, count(*) as count
        ORDER BY count DESC
    """, group_id=GROUP_ID)
    
    print("\nNodes by label:")
    has_communities = False
    for record in result:
        label = record['label']
        count = record['count']
        print(f"  {label}: {count}")
        if label == "__Community__":
            has_communities = True
    
    # Check communities specifically
    result = session.run("""
        MATCH (c:__Community__ {group_id: $group_id})
        RETURN c.level as level, count(*) as count
        ORDER BY level
    """, group_id=GROUP_ID)
    
    print("\nCommunities by level:")
    communities = list(result)
    if communities:
        for record in communities:
            print(f"  Level {record['level']}: {record['count']}")
    else:
        print("  ⚠ No communities found - DRIFT will not work")
    
    print("\n" + "=" * 70)
    if has_communities and total > 0:
        print("✓ Indexing appears complete - DRIFT should work")
    elif total > 0:
        print("⚠ Indexing in progress - communities not yet created")
    else:
        print("✗ No data found - indexing may have failed")
    print("=" * 70)

driver.close()
