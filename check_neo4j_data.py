#!/usr/bin/env python3
"""Check Neo4j for actual data created by v3 indexing"""

from neo4j import GraphDatabase
import os

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
GROUP_ID = "invoice-contract-verification"

if not NEO4J_PASSWORD:
    raise SystemExit("NEO4J_PASSWORD is not set")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

print("=" * 80)
print(f"CHECKING NEO4J DATA FOR GROUP: {GROUP_ID}")
print("=" * 80)

with driver.session() as session:
    # Check entities
    result = session.run("""
        MATCH (n)
        WHERE n.group_id = $group_id
        RETURN labels(n) as labels, count(*) as count
    """, group_id=GROUP_ID)
    
    print("\nNodes by label:")
    for record in result:
        print(f"  {record['labels']}: {record['count']}")
    
    # Check RAPTOR nodes specifically
    result = session.run("""
        MATCH (n:RaptorNode)
        WHERE n.group_id = $group_id
        RETURN n.level as level, count(*) as count
        ORDER BY n.level
    """, group_id=GROUP_ID)
    
    print("\nRAPTOR nodes by level:")
    raptor_found = False
    for record in result:
        print(f"  Level {record['level']}: {record['count']}")
        raptor_found = True
    
    if not raptor_found:
        print("  No RAPTOR nodes found")
    
    # Check entities
    result = session.run("""
        MATCH (n:Entity)
        WHERE n.group_id = $group_id
        RETURN n.name as name, n.type as type
        LIMIT 10
    """, group_id=GROUP_ID)
    
    print("\nEntities (first 10):")
    entities_found = False
    for record in result:
        print(f"  {record['name']} ({record['type']})")
        entities_found = True
    
    if not entities_found:
        print("  No entities found")

driver.close()
