#!/usr/bin/env python3
"""
Check when KNN test groups were created in Neo4j.
"""
import os
import sys
from neo4j import GraphDatabase

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from src.core.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI, 
    auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
)

def check_groups():
    """Check existence and metadata of KNN test groups."""
    
    groups_to_check = [
        "test-5pdfs-v2-enhanced-ex",  # Yesterday's V2 group (15/16)
        "test-5pdfs-v2-knn-disabled",  # Today's KNN baseline
        "test-5pdfs-v2-knn-1",
        "test-5pdfs-v2-knn-2",
        "test-5pdfs-v2-knn-3",
    ]
    
    with driver.session() as session:
        for group_id in groups_to_check:
            print(f"\n{'='*60}")
            print(f"Group: {group_id}")
            print('='*60)
            
            # Check if group exists by counting entities
            result = session.run("""
                MATCH (e:__Entity__ {group_id: $group_id})
                RETURN count(e) as entity_count
            """, group_id=group_id)
            
            record = result.single()
            entity_count = record["entity_count"] if record else 0
            
            if entity_count == 0:
                print(f"❌ NOT FOUND - 0 entities")
                continue
            
            print(f"✓ Found {entity_count} entities")
            
            # Count KNN edges
            knn_result = session.run("""
                MATCH (e1:__Entity__ {group_id: $group_id})-[r:KNN_SIMILAR]->(e2:__Entity__ {group_id: $group_id})
                RETURN count(r) as knn_edge_count
            """, group_id=group_id)
            
            knn_record = knn_result.single()
            knn_edges = knn_record["knn_edge_count"] if knn_record else 0
            print(f"  KNN edges: {knn_edges}")
            
            # Count regular relationships
            rel_result = session.run("""
                MATCH (e1:__Entity__ {group_id: $group_id})-[r]-(e2:__Entity__ {group_id: $group_id})
                WHERE type(r) <> 'KNN_SIMILAR'
                RETURN count(DISTINCT r) as rel_count
            """, group_id=group_id)
            
            rel_record = rel_result.single()
            rel_count = rel_record["rel_count"] if rel_record else 0
            print(f"  Regular relationships: {rel_count}")
            
            # Sample entity to check properties
            sample_result = session.run("""
                MATCH (e:__Entity__ {group_id: $group_id})
                RETURN e LIMIT 1
            """, group_id=group_id)
            
            sample = sample_result.single()
            if sample:
                entity = sample["e"]
                print(f"\n  Sample entity properties:")
                for key, value in entity.items():
                    if key not in ['group_id', 'description', 'embedding']:
                        print(f"    {key}: {value}")

if __name__ == "__main__":
    check_groups()
    driver.close()
