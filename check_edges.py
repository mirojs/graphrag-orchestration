#!/usr/bin/env python3
"""Check Phase 1, 2, 3 edges and entity aliases in the graph."""

from neo4j import GraphDatabase
import os
import sys

# Get credentials from environment
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

if not NEO4J_PASSWORD:
    print("ERROR: NEO4J_PASSWORD environment variable not set")
    exit(1)

# Get group ID from file or argument
group_id = None
if len(sys.argv) > 1:
    group_id = sys.argv[1]
else:
    try:
        with open("last_test_group_id.txt") as f:
            group_id = f.read().strip()
        print(f"Using group ID from last_test_group_id.txt: {group_id}\n")
    except FileNotFoundError:
        group_id = 'test-5pdfs-1768557493369886422'
        print(f"Using default group ID: {group_id}\n")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

with driver.session(database='neo4j') as session:
    print("\n" + "="*70)
    print("Phase 1: Foundation Edges")
    print("="*70)
    
    result = session.run('''
        MATCH (e:Entity)-[r:APPEARS_IN_SECTION]->(s:Section {group_id: $group_id})
        RETURN count(r) as count
    ''', group_id=group_id)
    print(f'APPEARS_IN_SECTION: {result.single()["count"]}')
    
    result = session.run('''
        MATCH (e:Entity)-[r:APPEARS_IN_DOCUMENT]->(d:Document {group_id: $group_id})
        RETURN count(r) as count
    ''', group_id=group_id)
    print(f'APPEARS_IN_DOCUMENT: {result.single()["count"]}')
    
    result = session.run('''
        MATCH (s:Section {group_id: $group_id})-[r:HAS_HUB_ENTITY]->(e:Entity)
        RETURN count(r) as count
    ''', group_id=group_id)
    print(f'HAS_HUB_ENTITY: {result.single()["count"]}')
    
    print("\n" + "="*70)
    print("Phase 2: Connectivity Edges")
    print("="*70)
    
    result = session.run('''
        MATCH (s1:Section {group_id: $group_id})-[r:SHARES_ENTITY]->(s2:Section)
        RETURN count(r) as count
    ''', group_id=group_id)
    shares_entity = result.single()["count"]
    print(f'SHARES_ENTITY: {shares_entity}')
    
    print("\n" + "="*70)
    print("Phase 3: Semantic Enhancement Edges")
    print("="*70)
    
    result = session.run('''
        MATCH ()-[r:SIMILAR_TO {group_id: $group_id}]-()
        RETURN count(r) as count
    ''', group_id=group_id)
    similar_to = result.single()["count"]
    print(f'SIMILAR_TO: {similar_to}')
    
    print("\n" + "="*70)
    print("Graph Statistics")
    print("="*70)
    
    result = session.run('''
        MATCH (n:TextChunk {group_id: $group_id})
        RETURN count(n) as count
    ''', group_id=group_id)
    print(f'TextChunks: {result.single()["count"]}')
    
    result = session.run('''
        MATCH (n:Section {group_id: $group_id})
        RETURN count(n) as count
    ''', group_id=group_id)
    print(f'Sections: {result.single()["count"]}')
    
    result = session.run('''
        MATCH (n:Entity {group_id: $group_id})
        RETURN count(n) as count
    ''', group_id=group_id)
    entities = result.single()["count"]
    print(f'Entities: {entities}')
    
    print("\n" + "="*70)
    print("Entity Aliases (New Feature)")
    print("="*70)
    
    result = session.run('''
        MATCH (e:Entity {group_id: $group_id})
        WHERE e.aliases IS NOT NULL AND size(e.aliases) > 0
        RETURN count(e) as count
    ''', group_id=group_id)
    with_aliases = result.single()["count"]
    print(f'Entities with aliases: {with_aliases}/{entities} ({100*with_aliases//entities if entities > 0 else 0}%)')
    
    if with_aliases > 0:
        print("\nSample entities with aliases:")
        result = session.run('''
            MATCH (e:Entity {group_id: $group_id})
            WHERE e.aliases IS NOT NULL AND size(e.aliases) > 0
            RETURN e.name as name, e.aliases as aliases
            LIMIT 5
        ''', group_id=group_id)
        
        for record in result:
            aliases_str = ", ".join(record['aliases'][:3])
            if len(record['aliases']) > 3:
                aliases_str += f" (+{len(record['aliases'])-3} more)"
            print(f"  • {record['name']:30s} → [{aliases_str}]")

driver.close()
