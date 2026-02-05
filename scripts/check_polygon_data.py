#!/usr/bin/env python3
"""Check if polygon data was stored in Neo4j chunk metadata."""
import os
import sys

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
app_root = os.path.join(project_root, "graphrag-orchestration")
sys.path.insert(0, project_root)

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(app_root, '.env'))

from neo4j import GraphDatabase
import json
from src.core.config import settings

uri = settings.NEO4J_URI
user = settings.NEO4J_USERNAME  
password = settings.NEO4J_PASSWORD
database = settings.NEO4J_DATABASE or "neo4j"

if not uri:
    print("Error: NEO4J_URI not set")
    sys.exit(1)
    
print(f"Connecting to Neo4j: {uri[:30]}...")

driver = GraphDatabase.driver(uri, auth=(user, password))

with driver.session(database=database) as session:
    result = session.run('''
        MATCH (c:TextChunk {group_id: "test-5pdfs-v2-fix2"})
        RETURN c.chunk_id as chunk_id, c.metadata as metadata
        LIMIT 5
    ''')
    
    print("\nChecking polygon data in chunks:")
    print("-" * 50)
    
    for record in result:
        chunk_id = record['chunk_id']
        m = json.loads(record['metadata'] or '{}')
        has_sent = 'sentences' in m and len(m.get('sentences', [])) > 0
        has_dims = 'page_dimensions' in m and len(m.get('page_dimensions', [])) > 0
        
        print(f"\nChunk: {chunk_id}")
        print(f"  has sentences: {has_sent}")
        print(f"  has page_dimensions: {has_dims}")
        
        if has_sent:
            sents = m['sentences']
            print(f"  sentence count: {len(sents)}")
            if sents:
                s = sents[0]
                print(f"  first sentence:")
                print(f"    text: {s.get('text', '')[:60]}...")
                print(f"    page: {s.get('page')}")
                print(f"    polygons: {len(s.get('polygons', []))}")
        
        if has_dims:
            dims = m['page_dimensions'] 
            print(f"  page dimensions: {len(dims)} pages")
            if dims:
                d = dims[0]
                print(f"    page 1: {d.get('width')}x{d.get('height')}, angle={d.get('angle')}")
            
driver.close()
print("\n✅ Done")
