#!/usr/bin/env python3
"""Quick script to check if chunks use section-aware chunking."""
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load environment
env_path = os.path.join(os.path.dirname(__file__), 'graphrag-orchestration', '.env')
load_dotenv(env_path)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
GROUP_ID = "test-5pdfs-1768557493369886422"

def check_chunk_strategy():
    """Check what chunking strategy was used for the test group."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    query = """
    MATCH (c:TextChunk {group_id: $group_id})
    RETURN 
        c.metadata AS metadata,
        c.id AS chunk_id
    LIMIT 10
    """
    
    with driver.session() as session:
        results = session.run(query, group_id=GROUP_ID)
    
        print(f"\n{'='*80}")
        print(f"Checking chunk strategy for group: {GROUP_ID}")
        print(f"{'='*80}\n")
        
        section_aware_count = 0
        fixed_count = 0
        
        for i, r in enumerate(results, 1):
            metadata = r.get('metadata')
            chunk_id = r.get('chunk_id')
            
            # Parse metadata if it's a JSON string
            import json
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            elif metadata is None:
                metadata = {}
            
            strategy = metadata.get('chunk_strategy')
            section_path = metadata.get('section_path')
            section_title = metadata.get('section_title')
            
            print(f"Chunk {i}: {chunk_id}")
            print(f"  Strategy: {strategy or 'NOT SET (likely fixed chunking)'}")
            print(f"  Section Path: {section_path or 'N/A'}")
            print(f"  Section Title: {section_title or 'N/A'}")
            print()
            
            if strategy and 'section' in str(strategy).lower():
                section_aware_count += 1
            else:
                fixed_count += 1
        
        print(f"{'='*80}")
        print(f"Summary (sample of 10 chunks):")
        print(f"  Section-aware chunks: {section_aware_count}")
        print(f"  Fixed chunks: {fixed_count}")
        print(f"{'='*80}\n")
        
        if section_aware_count == 0:
            print("❌ FINDING: Chunks are using FIXED chunking (not section-aware)")
            print("   → You need to re-index with USE_SECTION_CHUNKING=1")
            return False
        else:
            print("✅ FINDING: Chunks are using SECTION-AWARE chunking")
            print("   → No re-indexing needed for Phase 2")
            return True
    
    driver.close()

if __name__ == "__main__":
    check_chunk_strategy()
