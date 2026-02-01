#!/usr/bin/env python3
"""
Thorough check of Neo4j database - all labels, all nodes.
"""
from neo4j import GraphDatabase
import os

NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

if not NEO4J_PASSWORD:
    print("ERROR: Please set NEO4J_PASSWORD environment variable")
    exit(1)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

def thorough_check():
    """Check all aspects of the database."""
    
    with driver.session() as session:
        print("="*60)
        print("NEO4J DATABASE THOROUGH CHECK")
        print("="*60)
        
        # 1. Total node count
        print("\n1. TOTAL NODE COUNT:")
        result = session.run("MATCH (n) RETURN count(n) as total")
        total = result.single()["total"]
        print(f"   Total nodes: {total}")
        
        if total == 0:
            print("   ⚠️  DATABASE IS COMPLETELY EMPTY!")
            return
        
        # 2. All labels
        print("\n2. ALL LABELS IN DATABASE:")
        labels_result = session.run("CALL db.labels()")
        labels = [record["label"] for record in labels_result]
        print(f"   Found {len(labels)} labels:")
        for label in labels:
            print(f"   - {label}")
        
        # 3. Count by label
        print("\n3. NODE COUNT BY LABEL:")
        for label in labels:
            result = session.run(f"MATCH (n:`{label}`) RETURN count(n) as count")
            count = result.single()["count"]
            print(f"   {label}: {count} nodes")
        
        # 4. Sample nodes from each label
        print("\n4. SAMPLE NODES (showing group_id if present):")
        for label in labels:
            result = session.run(f"MATCH (n:`{label}`) RETURN n LIMIT 3")
            print(f"\n   {label}:")
            for i, record in enumerate(result, 1):
                node = record["n"]
                group_id = node.get("group_id", "N/A")
                name = node.get("name", node.get("title", "N/A"))
                print(f"     {i}. group_id={group_id}, name={name}")
        
        # 5. All distinct group_ids
        print("\n5. ALL DISTINCT GROUP_IDs:")
        result = session.run("""
            MATCH (n)
            WHERE n.group_id IS NOT NULL
            RETURN DISTINCT n.group_id as group_id
            ORDER BY group_id
        """)
        
        group_ids = [record["group_id"] for record in result]
        if group_ids:
            print(f"   Found {len(group_ids)} distinct group_ids:")
            for gid in group_ids:
                # Count nodes with this group_id
                count_result = session.run("""
                    MATCH (n {group_id: $gid})
                    RETURN count(n) as count
                """, gid=gid)
                count = count_result.single()["count"]
                print(f"   - {gid}: {count} nodes")
        else:
            print("   No group_id property found on any nodes")
        
        # 6. Relationship types
        print("\n6. RELATIONSHIP TYPES:")
        rel_result = session.run("CALL db.relationshipTypes()")
        rel_types = [record["relationshipType"] for record in rel_result]
        print(f"   Found {len(rel_types)} relationship types:")
        for rel_type in rel_types:
            result = session.run(f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) as count")
            count = result.single()["count"]
            print(f"   - {rel_type}: {count} relationships")

if __name__ == "__main__":
    try:
        thorough_check()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.close()
