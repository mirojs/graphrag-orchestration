#!/usr/bin/env python3
"""Query Neo4j to list all Section nodes and their chunk counts."""

import os
from neo4j import GraphDatabase

# Get Neo4j credentials from environment
neo4j_uri = os.getenv("NEO4J_URI")
neo4j_user = os.getenv("NEO4J_USER")
neo4j_password = os.getenv("NEO4J_PASSWORD")

if not all([neo4j_uri, neo4j_user, neo4j_password]):
    print("❌ Missing Neo4j credentials (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)")
    exit(1)

driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
group_id = "test-5pdfs-1767429340223041632"

# Query for all Section nodes
query = """
MATCH (s:Section)
WHERE s.group_id = $group_id
WITH s, count{(s)<-[:IN_SECTION]-(t:TextChunk)} as chunk_count
RETURN s.path_key as path, chunk_count
ORDER BY path
"""

with driver.session() as session:
    result = session.run(query, group_id=group_id)
    sections = list(result)

print(f"\n{'='*80}")
print(f"Section Nodes in Group: {group_id}")
print(f"{'='*80}\n")
print(f"Found {len(sections)} Section nodes:\n")

for i, sec in enumerate(sections, 1):
    path = sec['path'] or "[no path]"
    count = sec['chunk_count']
    print(f"{i:3}. {path:65} ({count:3} chunks)")

if sections:
    # Check for reporting-related sections
    reporting_sections = [s for s in sections if any(kw in s['path'].lower() for kw in ['report', 'account', 'statement', 'income', 'expense', 'record'])]
    
    print(f"\n{'='*80}")
    print(f"Reporting-related sections ({len(reporting_sections)} found):")
    print(f"{'='*80}\n")
    
    for sec in reporting_sections:
        print(f"  • {sec['path']} ({sec['chunk_count']} chunks)")

driver.close()
