#!/usr/bin/env python3
"""Debug script to check Neo4j RAPTOR nodes."""

from neo4j import GraphDatabase

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

with driver.session() as session:
    # Get all properties of RAPTOR nodes
    result = session.run("""
        MATCH (n:RaptorNode)
        WHERE n.group_id = 'phase1-v3-validation'
        RETURN n LIMIT 5
    """)
    
    print("RAPTOR Nodes in phase1-v3-validation:")
    for record in result:
        node = record["n"]
        print(f"\nNode ID: {node['id']}")
        print(f"Level: {node.get('level', 'N/A')}")
        print(f"Properties: {dict(node)}")
        print(f"All keys: {list(node.keys())}")

driver.close()
