#!/usr/bin/env python3
"""
Phase 2 Week 3: Create SHARES_ENTITY edges for cross-document section discovery.

This script creates SHARES_ENTITY edges between sections that share entities:
- Section1 ↔ Section2 when they share ≥threshold entities
- Enables Route 3 (Global) cross-doc thematic retrieval
- Expected: 100-200 edges total, 50-100 cross-doc

Usage:
    python scripts/create_shares_entity_edges.py --group-id <group_id>
    python scripts/create_shares_entity_edges.py --group-id <group_id> --threshold 3
    python scripts/create_shares_entity_edges.py --group-id <group_id> --dry-run
    
Example:
    python scripts/create_shares_entity_edges.py --group-id test-5pdfs-1768557493369886422
"""

import os
import argparse
from neo4j import GraphDatabase


# Neo4j connection settings
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def create_shares_entity_edges(session, group_id: str, threshold: int = 3) -> dict:
    """
    Create SHARES_ENTITY edges between sections that share entities.
    
    This enables cross-document section discovery for Route 3 (Global Search):
    - Sections discussing similar topics will be connected
    - Enables "find related sections across documents" queries
    
    Args:
        session: Neo4j session
        group_id: Group identifier for multi-tenancy
        threshold: Minimum number of shared entities to create edge (default: 3)
        
    Returns:
        dict with edge counts: {"total": N, "cross_doc": M, "same_doc": K}
    """
    print(f"\n🔗 Creating SHARES_ENTITY edges (threshold ≥{threshold} shared entities)...")
    
    # Create edges between sections that share entities
    # Use APPEARS_IN_SECTION edges we created in Phase 1 for efficiency
    query = """
    // Find section pairs that share entities via APPEARS_IN_SECTION
    MATCH (e:Entity)-[:APPEARS_IN_SECTION]->(s1:Section)
    WHERE e.group_id = $group_id AND s1.group_id = $group_id
    MATCH (e)-[:APPEARS_IN_SECTION]->(s2:Section)
    WHERE s2.group_id = $group_id AND id(s1) < id(s2)  // Avoid duplicates and self-loops
    
    // Count shared entities between each section pair
    WITH s1, s2, count(DISTINCT e) AS shared_count, collect(DISTINCT e.name) AS shared_entities
    WHERE shared_count >= $threshold
    
    // Create bidirectional SHARES_ENTITY edges
    MERGE (s1)-[r1:SHARES_ENTITY]->(s2)
    SET r1.shared_count = shared_count,
        r1.shared_entities = shared_entities[..10],  // Store up to 10 entity names for debugging
        r1.group_id = $group_id,
        r1.created_at = datetime()
    
    MERGE (s2)-[r2:SHARES_ENTITY]->(s1)
    SET r2.shared_count = shared_count,
        r2.shared_entities = shared_entities[..10],
        r2.group_id = $group_id,
        r2.created_at = datetime()
    
    // Determine if cross-doc
    WITH s1, s2, shared_count, shared_entities,
         CASE WHEN s1.doc_id <> s2.doc_id THEN 1 ELSE 0 END AS is_cross_doc
    
    RETURN count(*) AS pairs_created, sum(is_cross_doc) AS cross_doc_pairs
    """
    
    result = session.run(query, group_id=group_id, threshold=threshold)
    record = result.single()
    
    pairs_created = record["pairs_created"] if record else 0
    cross_doc_pairs = record["cross_doc_pairs"] if record else 0
    
    # Each pair creates 2 edges (bidirectional)
    total_edges = pairs_created * 2
    cross_doc_edges = cross_doc_pairs * 2
    same_doc_edges = total_edges - cross_doc_edges
    
    print(f"   ✅ Created {total_edges} SHARES_ENTITY edges")
    print(f"      - Cross-doc: {cross_doc_edges} edges ({cross_doc_pairs} section pairs)")
    print(f"      - Same-doc: {same_doc_edges} edges")
    
    return {
        "total": total_edges,
        "cross_doc": cross_doc_edges,
        "same_doc": same_doc_edges,
        "threshold": threshold,
    }


def create_shares_entity_index(session, group_id: str) -> None:
    """Create index on SHARES_ENTITY relationship for fast traversal."""
    print("\n📇 Creating index on SHARES_ENTITY edges...")
    
    # Create relationship property index for group_id filtering
    try:
        session.run("""
            CREATE INDEX shares_entity_group_id_index IF NOT EXISTS
            FOR ()-[r:SHARES_ENTITY]->() ON (r.group_id)
        """)
        print("   ✅ Index created: shares_entity_group_id_index")
    except Exception as e:
        if "already exists" in str(e).lower():
            print("   ⚠️  Index already exists (skipping)")
        else:
            print(f"   ❌ Index creation failed: {e}")


def verify_edges(session, group_id: str) -> dict:
    """Verify SHARES_ENTITY edge counts and distribution."""
    print("\n🔍 Verifying SHARES_ENTITY edges...")
    
    # Total edges
    result = session.run("""
        MATCH ()-[r:SHARES_ENTITY]->()
        WHERE r.group_id = $group_id
        RETURN count(r) AS total
    """, group_id=group_id)
    total = result.single()["total"]
    
    # Cross-doc edges
    result = session.run("""
        MATCH (s1:Section)-[r:SHARES_ENTITY]->(s2:Section)
        WHERE r.group_id = $group_id AND s1.doc_id <> s2.doc_id
        RETURN count(r) AS cross_doc
    """, group_id=group_id)
    cross_doc = result.single()["cross_doc"]
    
    # Distribution by shared_count
    result = session.run("""
        MATCH ()-[r:SHARES_ENTITY]->()
        WHERE r.group_id = $group_id
        RETURN r.shared_count AS shared_count, count(*) AS edge_count
        ORDER BY shared_count DESC
    """, group_id=group_id)
    
    distribution = [(r["shared_count"], r["edge_count"]) for r in result]
    
    print(f"   Total edges: {total}")
    print(f"   Cross-doc edges: {cross_doc}")
    print(f"   Same-doc edges: {total - cross_doc}")
    print(f"\n   Distribution by shared entity count:")
    for shared_count, edge_count in distribution[:10]:
        print(f"      {shared_count} shared entities: {edge_count} edges")
    
    return {
        "total": total,
        "cross_doc": cross_doc,
        "same_doc": total - cross_doc,
        "distribution": distribution,
    }


def show_sample_edges(session, group_id: str) -> None:
    """Show sample SHARES_ENTITY edges for manual validation."""
    print("\n📊 Sample SHARES_ENTITY edges:")
    
    # Cross-doc samples
    print("\n   Cross-document connections:")
    result = session.run("""
        MATCH (s1:Section)-[r:SHARES_ENTITY]->(s2:Section)
        WHERE r.group_id = $group_id AND s1.doc_id <> s2.doc_id
        RETURN s1.title AS section1, s1.doc_id AS doc1,
               s2.title AS section2, s2.doc_id AS doc2,
               r.shared_count AS shared, r.shared_entities AS entities
        LIMIT 5
    """, group_id=group_id)
    
    for record in result:
        s1 = (record['section1'] or 'Unknown')[:30]
        s2 = (record['section2'] or 'Unknown')[:30]
        d1 = (record['doc1'] or 'Unknown')[:20]
        d2 = (record['doc2'] or 'Unknown')[:20]
        entities = record['entities'][:3] if record['entities'] else []
        print(f"      [{d1}] {s1}...")
        print(f"        ↔ [{d2}] {s2}...")
        print(f"        Shared ({record['shared']}): {', '.join(entities)}...")
        print()
    
    # Same-doc samples
    print("   Same-document connections:")
    result = session.run("""
        MATCH (s1:Section)-[r:SHARES_ENTITY]->(s2:Section)
        WHERE r.group_id = $group_id AND s1.doc_id = s2.doc_id
        RETURN s1.title AS section1, s2.title AS section2,
               s1.doc_id AS doc_id,
               r.shared_count AS shared, r.shared_entities AS entities
        LIMIT 3
    """, group_id=group_id)
    
    for record in result:
        s1 = (record['section1'] or 'Unknown')[:30]
        s2 = (record['section2'] or 'Unknown')[:30]
        doc = (record['doc_id'] or 'Unknown')[:25]
        entities = record['entities'][:3] if record['entities'] else []
        print(f"      [{doc}]")
        print(f"        {s1}... ↔ {s2}...")
        print(f"        Shared ({record['shared']}): {', '.join(entities)}...")
        print()


def dry_run_analysis(session, group_id: str, threshold: int) -> None:
    """Analyze what would be created without making changes."""
    print(f"\n⚠️  DRY RUN - Analyzing potential SHARES_ENTITY edges (threshold ≥{threshold})...\n")
    
    # Check APPEARS_IN_SECTION edges exist (prerequisite)
    result = session.run("""
        MATCH ()-[r:APPEARS_IN_SECTION]->()
        WHERE r.group_id = $group_id
        RETURN count(r) AS count
    """, group_id=group_id)
    ais_count = result.single()["count"]
    
    if ais_count == 0:
        print("   ❌ No APPEARS_IN_SECTION edges found!")
        print("      Run Phase 1 (create_foundation_edges.py) first.")
        return
    
    print(f"   ✓ Found {ais_count} APPEARS_IN_SECTION edges (prerequisite)")
    
    # Analyze potential edges
    result = session.run("""
        MATCH (e:Entity)-[:APPEARS_IN_SECTION]->(s1:Section)
        WHERE e.group_id = $group_id AND s1.group_id = $group_id
        MATCH (e)-[:APPEARS_IN_SECTION]->(s2:Section)
        WHERE s2.group_id = $group_id AND id(s1) < id(s2)
        WITH s1, s2, count(DISTINCT e) AS shared_count
        WHERE shared_count >= $threshold
        WITH s1, s2, shared_count,
             CASE WHEN s1.doc_id <> s2.doc_id THEN 1 ELSE 0 END AS is_cross_doc
        RETURN count(*) AS total_pairs, 
               sum(is_cross_doc) AS cross_doc_pairs,
               avg(shared_count) AS avg_shared,
               max(shared_count) AS max_shared
    """, group_id=group_id, threshold=threshold)
    
    record = result.single()
    total_pairs = record["total_pairs"] or 0
    cross_doc_pairs = record["cross_doc_pairs"] or 0
    avg_shared = record["avg_shared"] or 0
    max_shared = record["max_shared"] or 0
    
    print(f"\n   Potential edges (threshold ≥{threshold}):")
    print(f"      Total section pairs: {total_pairs}")
    print(f"      Cross-doc pairs: {cross_doc_pairs}")
    print(f"      Same-doc pairs: {total_pairs - cross_doc_pairs}")
    print(f"      Average shared entities: {avg_shared:.1f}")
    print(f"      Max shared entities: {max_shared}")
    print(f"\n   Would create: {total_pairs * 2} edges (bidirectional)")
    
    # Show threshold sensitivity
    print("\n   Threshold sensitivity analysis:")
    for t in [2, 3, 4, 5]:
        result = session.run("""
            MATCH (e:Entity)-[:APPEARS_IN_SECTION]->(s1:Section)
            WHERE e.group_id = $group_id AND s1.group_id = $group_id
            MATCH (e)-[:APPEARS_IN_SECTION]->(s2:Section)
            WHERE s2.group_id = $group_id AND id(s1) < id(s2)
            WITH s1, s2, count(DISTINCT e) AS shared_count
            WHERE shared_count >= $threshold
            WITH s1, s2, CASE WHEN s1.doc_id <> s2.doc_id THEN 1 ELSE 0 END AS is_cross_doc
            RETURN count(*) AS pairs, sum(is_cross_doc) AS cross_doc
        """, group_id=group_id, threshold=t)
        r = result.single()
        marker = " ← current" if t == threshold else ""
        print(f"      threshold ≥{t}: {r['pairs']} pairs ({r['cross_doc']} cross-doc){marker}")


def main():
    parser = argparse.ArgumentParser(description="Create SHARES_ENTITY edges for cross-doc section discovery")
    parser.add_argument("--group-id", required=True, help="The group_id to process")
    parser.add_argument("--threshold", type=int, default=3, help="Minimum shared entities to create edge (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Analyze without creating edges")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing edges")
    parser.add_argument("--skip-index", action="store_true", help="Skip index creation")
    args = parser.parse_args()
    
    if not NEO4J_PASSWORD:
        print("❌ ERROR: NEO4J_PASSWORD environment variable not set")
        return 1
    
    print(f"🚀 Phase 2 Week 3: SHARES_ENTITY Edges Creation")
    print(f"   Group ID: {args.group_id}")
    print(f"   Threshold: ≥{args.threshold} shared entities")
    print(f"   Neo4j URI: {NEO4J_URI}")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    try:
        with driver.session() as session:
            if args.verify_only:
                verify_edges(session, args.group_id)
                show_sample_edges(session, args.group_id)
                return 0
            
            if args.dry_run:
                dry_run_analysis(session, args.group_id, args.threshold)
                return 0
            
            # Create edges
            print("\n" + "="*60)
            print("CREATING SHARES_ENTITY EDGES")
            print("="*60)
            
            stats = create_shares_entity_edges(session, args.group_id, args.threshold)
            
            # Create index (unless skipped)
            if not args.skip_index:
                create_shares_entity_index(session, args.group_id)
            
            # Verify
            print("\n" + "="*60)
            print("VERIFICATION")
            print("="*60)
            verify_edges(session, args.group_id)
            show_sample_edges(session, args.group_id)
            
            print("\n" + "="*60)
            print(f"✅ Phase 2 Week 3 Complete!")
            print(f"   Total edges created: {stats['total']}")
            print(f"   Cross-doc edges: {stats['cross_doc']}")
            print("="*60)
            print("\n   Next: Update Route 3 (Global) to use SHARES_ENTITY for cross-doc discovery")
            
    finally:
        driver.close()
    
    return 0


if __name__ == "__main__":
    exit(main())
