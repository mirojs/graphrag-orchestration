#!/usr/bin/env python3
"""
Phase 1 Week 1: Create Foundation Edges for Graph Schema Enhancement

This script creates the following edges:
1. APPEARS_IN_SECTION (Entity → Section) - Direct 1-hop link
2. APPEARS_IN_DOCUMENT (Entity → Document) - Direct 1-hop link  
3. HAS_HUB_ENTITY (Section → Entity) - Top-3 entities per section

Usage:
    python scripts/create_foundation_edges.py --group-id <group_id>
    
Example:
    python scripts/create_foundation_edges.py --group-id test-5pdfs-1768557493369886422
"""

import os
import argparse
from neo4j import GraphDatabase


# Neo4j connection settings
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://a86dcf63.databases.neo4j.io")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def create_appears_in_section_edges(session, group_id: str) -> int:
    """
    Create APPEARS_IN_SECTION edges from Entity to Section.
    
    This reduces Entity→Section traversal from 2 hops to 1 hop:
    Before: Entity ← MENTIONS ← TextChunk → IN_SECTION → Section
    After:  Entity → APPEARS_IN_SECTION → Section
    """
    print("\n📍 Creating APPEARS_IN_SECTION edges...")
    
    query = """
    MATCH (e:Entity)<-[:MENTIONS]-(c:TextChunk)-[:IN_SECTION]->(s:Section)
    WHERE e.group_id = $group_id
    WITH e, s, count(c) AS mention_count
    MERGE (e)-[r:APPEARS_IN_SECTION]->(s)
    SET r.mention_count = mention_count,
        r.group_id = $group_id,
        r.created_at = datetime()
    RETURN count(r) AS edges_created
    """
    
    result = session.run(query, group_id=group_id)
    record = result.single()
    edges_created = record["edges_created"] if record else 0
    
    print(f"   ✅ Created {edges_created} APPEARS_IN_SECTION edges")
    return edges_created


def create_appears_in_document_edges(session, group_id: str) -> int:
    """
    Create APPEARS_IN_DOCUMENT edges from Entity to Document.
    
    This reduces Entity→Document traversal from 3 hops to 1 hop:
    Before: Entity ← MENTIONS ← TextChunk → PART_OF → Document
    After:  Entity → APPEARS_IN_DOCUMENT → Document
    
    Includes aggregate properties for O(1) cross-doc queries.
    """
    print("\n📄 Creating APPEARS_IN_DOCUMENT edges...")
    
    query = """
    MATCH (e:Entity)<-[:MENTIONS]-(c:TextChunk)-[:PART_OF]->(d:Document)
    WHERE e.group_id = $group_id
    OPTIONAL MATCH (c)-[:IN_SECTION]->(s:Section)
    WITH e, d, count(DISTINCT c) AS chunk_count, count(DISTINCT s) AS section_count
    MERGE (e)-[r:APPEARS_IN_DOCUMENT]->(d)
    SET r.mention_count = chunk_count,
        r.section_count = section_count,
        r.chunk_count = chunk_count,
        r.group_id = $group_id,
        r.created_at = datetime()
    RETURN count(r) AS edges_created
    """
    
    result = session.run(query, group_id=group_id)
    record = result.single()
    edges_created = record["edges_created"] if record else 0
    
    print(f"   ✅ Created {edges_created} APPEARS_IN_DOCUMENT edges")
    return edges_created


def create_has_hub_entity_edges(session, group_id: str, top_n: int = 3) -> int:
    """
    Create HAS_HUB_ENTITY edges from Section to top-N entities.
    
    This bridges LazyGraphRAG (Section structure) to HippoRAG (Entity graph):
    - Identifies the most important entities per section
    - Enables section-aware PPR seeding for Route 4 (DRIFT)
    
    Args:
        top_n: Number of top entities per section (default: 3)
    """
    print(f"\n🔗 Creating HAS_HUB_ENTITY edges (top-{top_n} per section)...")
    
    query = """
    // Find top-N entities per section by mention count
    MATCH (s:Section)<-[:IN_SECTION]-(c:TextChunk)-[:MENTIONS]->(e:Entity)
    WHERE s.group_id = $group_id
      AND NOT e.name STARTS WITH 'doc_'  // Exclude synthetic document IDs
    WITH s, e, count(c) AS mentions
    ORDER BY s.id, mentions DESC
    WITH s, collect({entity: e, mentions: mentions}) AS all_entities
    WITH s, all_entities[0..$top_n] AS top_entities
    UNWIND range(0, size(top_entities)-1) AS idx
    WITH s, top_entities[idx].entity AS e, top_entities[idx].mentions AS mentions, idx+1 AS rank
    MERGE (s)-[r:HAS_HUB_ENTITY]->(e)
    SET r.rank = rank,
        r.mention_count = mentions,
        r.group_id = $group_id,
        r.created_at = datetime()
    RETURN count(r) AS edges_created
    """
    
    result = session.run(query, group_id=group_id, top_n=top_n)
    record = result.single()
    edges_created = record["edges_created"] if record else 0
    
    print(f"   ✅ Created {edges_created} HAS_HUB_ENTITY edges")
    return edges_created


def verify_edges(session, group_id: str) -> dict:
    """Verify edge counts after creation."""
    print("\n🔍 Verifying edge counts...")
    
    queries = {
        "APPEARS_IN_SECTION": """
            MATCH ()-[r:APPEARS_IN_SECTION {group_id: $group_id}]->()
            RETURN count(r) AS count
        """,
        "APPEARS_IN_DOCUMENT": """
            MATCH ()-[r:APPEARS_IN_DOCUMENT {group_id: $group_id}]->()
            RETURN count(r) AS count
        """,
        "HAS_HUB_ENTITY": """
            MATCH ()-[r:HAS_HUB_ENTITY {group_id: $group_id}]->()
            RETURN count(r) AS count
        """,
    }
    
    counts = {}
    for edge_type, query in queries.items():
        result = session.run(query, group_id=group_id)
        record = result.single()
        counts[edge_type] = record["count"] if record else 0
        print(f"   {edge_type}: {counts[edge_type]} edges")
    
    return counts


def show_sample_edges(session, group_id: str):
    """Show sample edges for verification."""
    print("\n📊 Sample edges:")
    
    # Sample APPEARS_IN_SECTION
    print("\n   APPEARS_IN_SECTION (Entity → Section):")
    result = session.run("""
        MATCH (e:Entity)-[r:APPEARS_IN_SECTION]->(s:Section)
        WHERE r.group_id = $group_id
        RETURN e.name AS entity, s.title AS section, r.mention_count AS mentions
        LIMIT 5
    """, group_id=group_id)
    for record in result:
        print(f"      {record['entity']} → {record['section'][:50]}... ({record['mentions']} mentions)")
    
    # Sample APPEARS_IN_DOCUMENT
    print("\n   APPEARS_IN_DOCUMENT (Entity → Document):")
    result = session.run("""
        MATCH (e:Entity)-[r:APPEARS_IN_DOCUMENT]->(d:Document)
        WHERE r.group_id = $group_id
        RETURN e.name AS entity, d.title AS doc, r.mention_count AS mentions, r.section_count AS sections
        LIMIT 5
    """, group_id=group_id)
    for record in result:
        doc_title = record['doc'][:40] if record['doc'] else 'Unknown'
        print(f"      {record['entity']} → {doc_title}... ({record['mentions']} mentions, {record['sections']} sections)")
    
    # Sample HAS_HUB_ENTITY
    print("\n   HAS_HUB_ENTITY (Section → Entity):")
    result = session.run("""
        MATCH (s:Section)-[r:HAS_HUB_ENTITY]->(e:Entity)
        WHERE r.group_id = $group_id
        RETURN s.title AS section, e.name AS entity, r.rank AS rank, r.mention_count AS mentions
        ORDER BY s.id, r.rank
        LIMIT 9
    """, group_id=group_id)
    current_section = None
    for record in result:
        section = record['section'][:40] if record['section'] else 'Unknown'
        if section != current_section:
            print(f"\n      Section: {section}...")
            current_section = section
        print(f"         #{record['rank']}: {record['entity']} ({record['mentions']} mentions)")


def main():
    parser = argparse.ArgumentParser(description="Create foundation edges for graph schema enhancement")
    parser.add_argument("--group-id", required=True, help="The group_id to process")
    parser.add_argument("--top-n", type=int, default=3, help="Number of hub entities per section (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without creating")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing edges")
    args = parser.parse_args()
    
    if not NEO4J_PASSWORD:
        print("❌ ERROR: NEO4J_PASSWORD environment variable not set")
        return 1
    
    print(f"🚀 Phase 1 Week 1: Foundation Edges Creation")
    print(f"   Group ID: {args.group_id}")
    print(f"   Hub entities per section: {args.top_n}")
    print(f"   Neo4j URI: {NEO4J_URI}")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    try:
        with driver.session() as session:
            if args.verify_only:
                verify_edges(session, args.group_id)
                show_sample_edges(session, args.group_id)
                return 0
            
            if args.dry_run:
                print("\n⚠️  DRY RUN - No edges will be created")
                # Show what would be created
                result = session.run("""
                    MATCH (e:Entity)<-[:MENTIONS]-(c:TextChunk)-[:IN_SECTION]->(s:Section)
                    WHERE e.group_id = $group_id
                    WITH e, s, count(c) AS mention_count
                    RETURN count(*) AS potential_appears_in_section
                """, group_id=args.group_id)
                print(f"   Would create ~{result.single()['potential_appears_in_section']} APPEARS_IN_SECTION edges")
                
                result = session.run("""
                    MATCH (e:Entity)<-[:MENTIONS]-(c:TextChunk)-[:PART_OF]->(d:Document)
                    WHERE e.group_id = $group_id
                    WITH DISTINCT e, d
                    RETURN count(*) AS potential_appears_in_document
                """, group_id=args.group_id)
                print(f"   Would create ~{result.single()['potential_appears_in_document']} APPEARS_IN_DOCUMENT edges")
                
                result = session.run("""
                    MATCH (s:Section)
                    WHERE s.group_id = $group_id
                    RETURN count(s) * $top_n AS potential_has_hub_entity
                """, group_id=args.group_id, top_n=args.top_n)
                print(f"   Would create up to ~{result.single()['potential_has_hub_entity']} HAS_HUB_ENTITY edges")
                return 0
            
            # Create edges
            print("\n" + "="*60)
            print("CREATING FOUNDATION EDGES")
            print("="*60)
            
            total_edges = 0
            total_edges += create_appears_in_section_edges(session, args.group_id)
            total_edges += create_appears_in_document_edges(session, args.group_id)
            total_edges += create_has_hub_entity_edges(session, args.group_id, args.top_n)
            
            print("\n" + "="*60)
            print(f"TOTAL: {total_edges} edges created")
            print("="*60)
            
            # Verify
            verify_edges(session, args.group_id)
            show_sample_edges(session, args.group_id)
            
            print("\n✅ Phase 1 Week 1 Complete!")
            print("   Next: Update Route 2 (Local) to use 1-hop queries")
            
    finally:
        driver.close()
    
    return 0


if __name__ == "__main__":
    exit(main())
