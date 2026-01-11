#!/usr/bin/env python3
"""Check what properties exist on TextChunk nodes in the database."""

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load environment
env_path = os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration', '.env')
load_dotenv(env_path)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

GROUP_ID = "test-cypher25-final-1768129960"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

print("=" * 70)
print("Checking TextChunk Properties")
print("=" * 70)

with driver.session() as session:
    # Get a sample chunk
    query = """
    MATCH (c:TextChunk {group_id: $group_id})
    RETURN c
    LIMIT 1
    """
    result = session.run(query, group_id=GROUP_ID)
    record = result.single()
    
    if record:
        chunk = record["c"]
        print(f"\nSample TextChunk properties:")
        for key in sorted(chunk.keys()):
            value = chunk[key]
            if isinstance(value, str) and len(value) > 100:
                value = value[:100] + "..."
            print(f"  {key}: {value}")
    else:
        print("No TextChunk nodes found!")
    
    # Check if document_title or document_source exist on ANY chunk
    query2 = """
    MATCH (c)
    WHERE c.group_id = $group_id
      AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
      AND (c.document_title IS NOT NULL OR c.document_source IS NOT NULL)
    RETURN count(c) AS count_with_props,
           count(c.document_title) AS count_with_title,
           count(c.document_source) AS count_with_source
    """
    result = session.run(query2, group_id=GROUP_ID)
    record = result.single()
    
    print(f"\n" + "=" * 70)
    print("Property Statistics:")
    print("=" * 70)
    if record:
        print(f"Chunks with document_title or document_source: {record['count_with_props']}")
        print(f"Chunks with document_title: {record['count_with_title']}")
        print(f"Chunks with document_source: {record['count_with_source']}")
    
    # Get all property keys across all chunks
    query3 = """
    MATCH (c)
    WHERE c.group_id = $group_id
      AND (c:Chunk OR c:TextChunk OR c:`__Node__`)
    UNWIND keys(c) AS propKey
    RETURN DISTINCT propKey
    ORDER BY propKey
    """
    result = session.run(query3, group_id=GROUP_ID)
    records = list(result)
    
    print(f"\n" + "=" * 70)
    print("All unique property keys on chunk nodes:")
    print("=" * 70)
    for r in records:
        print(f"  • {r['propKey']}")
    
    # Check if these properties are used in the app's data model
    print(f"\n" + "=" * 70)
    print("Analysis:")
    print("=" * 70)
    
    prop_keys = [r['propKey'] for r in records]
    
    if 'document_title' in prop_keys:
        print("✅ document_title property EXISTS in database")
    else:
        print("⚠️  document_title property MISSING from database")
        print("   → Query uses coalesce(c.document_title, '') so it won't fail")
        print("   → Warning is expected for this test dataset")
    
    if 'document_source' in prop_keys:
        print("✅ document_source property EXISTS in database")
    else:
        print("⚠️  document_source property MISSING from database")
        print("   → Query uses coalesce(c.document_source, '') so it won't fail")
        print("   → Warning is expected for this test dataset")
    
    print()

driver.close()
