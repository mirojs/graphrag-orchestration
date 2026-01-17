#!/usr/bin/env python3
"""
Validate that section-based coverage captures all effective content.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j import GraphDatabase


def validate_coverage(group_id: str):
    """Validate section coverage for a corpus."""
    
    # Get Neo4j credentials from environment
    uri = os.environ.get("NEO4J_URI", "neo4j+s://9f5e6fa5.databases.neo4j.io")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    
    if not password:
        print("ERROR: NEO4J_PASSWORD environment variable not set")
        print("Set it using: export NEO4J_PASSWORD=your_password")
        sys.exit(1)
    
    driver = GraphDatabase.driver(uri, auth=(user, password))
    
    with driver.session() as session:
        # 1. Count chunks WITHOUT section relationships
        print("🔍 Checking for unmapped chunks...")
        result = session.run(
            """
            MATCH (t:TextChunk {group_id: $group_id})
            WHERE NOT EXISTS {
                MATCH (t)-[:IN_SECTION]->(:Section {group_id: $group_id})
            }
            RETURN count(t) as unmapped_chunks
            """,
            group_id=group_id
        )
        unmapped = result.single()["unmapped_chunks"]
        
        # 2. Get total chunk count
        result = session.run(
            """
            MATCH (t:TextChunk {group_id: $group_id})
            RETURN count(t) as total_chunks
            """,
            group_id=group_id
        )
        total_chunks = result.single()["total_chunks"]
        
        # 3. Get distribution of chunks across documents
        result = session.run(
            """
            MATCH (t:TextChunk)-[:IN_SECTION]->(s:Section)
            WHERE t.group_id = $group_id AND s.group_id = $group_id
            WITH t.doc_id as doc_id, count(DISTINCT t) as chunks_with_sections, count(DISTINCT s) as sections_used
            RETURN doc_id, chunks_with_sections, sections_used
            ORDER BY doc_id
            """,
            group_id=group_id
        )
        doc_coverage = list(result)
        
        # 4. Get total sections and chunks per document
        result = session.run(
            """
            MATCH (t:TextChunk {group_id: $group_id})
            RETURN t.doc_id as doc_id, count(t) as total_chunks
            ORDER BY doc_id
            """,
            group_id=group_id
        )
        doc_totals = {r["doc_id"]: r["total_chunks"] for r in result}
        
        # 5. Check for orphan chunks
        if unmapped > 0:
            result = session.run(
                """
                MATCH (t:TextChunk {group_id: $group_id})
                WHERE NOT EXISTS {
                    MATCH (t)-[:IN_SECTION]->(:Section)
                }
                RETURN t.doc_id as doc_id, t.id as chunk_id, 
                       substring(t.text, 0, 150) as preview
                LIMIT 5
                """,
                group_id=group_id
            )
            orphans = list(result)
        else:
            orphans = []
        
        # 6. Check section depth distribution
        result = session.run(
            """
            MATCH (s:Section {group_id: $group_id})
            WITH s, size(split(s.path, ' > ')) as depth
            RETURN depth, count(s) as section_count
            ORDER BY depth
            """,
            group_id=group_id
        )
        section_depths = list(result)
        
        # 7. Check which sections have chunks
        result = session.run(
            """
            MATCH (s:Section {group_id: $group_id})
            OPTIONAL MATCH (t:TextChunk)-[:IN_SECTION]->(s)
            WHERE t.group_id = $group_id
            WITH size(split(s.path, ' > ')) as depth, 
                 count(DISTINCT s) as total_sections,
                 count(DISTINCT CASE WHEN t IS NOT NULL THEN s END) as sections_with_chunks
            RETURN depth, total_sections, sections_with_chunks
            ORDER BY depth
            """,
            group_id=group_id
        )
        sections_with_chunks = list(result)
        
    driver.close()
    
    # Print results
    print("\n" + "=" * 80)
    print("SECTION COVERAGE VALIDATION")
    print("=" * 80)
    
    print(f"\n📊 Overall Statistics:")
    print(f"  Total chunks in corpus: {total_chunks}")
    mapped = total_chunks - unmapped
    print(f"  Chunks mapped to sections: {mapped} ({mapped/total_chunks*100:.1f}%)")
    print(f"  Chunks WITHOUT sections: {unmapped} ({unmapped/total_chunks*100:.1f}%)")
    
    print(f"\n📄 Coverage by Document:")
    total_mapped = 0
    total_sections_used = 0
    for r in doc_coverage:
        doc_id = r["doc_id"]
        chunks_mapped = r["chunks_with_sections"]
        sections_used = r["sections_used"]
        total = doc_totals.get(doc_id, 0)
        pct = (chunks_mapped / total * 100) if total > 0 else 0
        print(f"  {doc_id}:")
        print(f"    Chunks: {chunks_mapped}/{total} mapped ({pct:.1f}%)")
        print(f"    Sections used: {sections_used}")
        total_mapped += chunks_mapped
        total_sections_used += sections_used
    
    print(f"\n  TOTAL: {total_mapped} chunks across {total_sections_used} sections")
    
    print(f"\n📐 Section Hierarchy:")
    total_sections = sum(r["section_count"] for r in section_depths)
    print(f"  Total sections created: {total_sections}")
    for r in section_depths:
        print(f"    Depth {r['depth']}: {r['section_count']} sections")
    
    print(f"\n📊 Section Utilization (which sections have chunks):")
    for r in sections_with_chunks:
        pct = (r['sections_with_chunks'] / r['total_sections'] * 100) if r['total_sections'] > 0 else 0
        print(f"  Depth {r['depth']}: {r['sections_with_chunks']}/{r['total_sections']} sections have chunks ({pct:.1f}%)")
    
    if unmapped > 0:
        print(f"\n⚠️  WARNING: {unmapped} chunks are NOT mapped to sections!")
        print(f"\n❓ Sample unmapped chunks:")
        for o in orphans:
            print(f"  • Doc: {o['doc_id']}")
            print(f"    Chunk ID: {o['chunk_id']}")
            print(f"    Preview: {o['preview']}...")
            print()
        print("💡 This may indicate:")
        print("   - Chunks created before section graph feature was added")
        print("   - Indexing logic unable to determine section hierarchy for some chunks")
        print("   - Consider re-indexing to ensure all chunks get mapped")
    else:
        print(f"\n✅ SUCCESS: ALL {total_chunks} chunks are properly mapped to sections!")
        print(f"\n💡 The 50 sections used represent the effective content sections.")
        print(f"   {total_sections - total_sections_used} sections exist but contain no chunks")
        print(f"   (e.g., header sections, metadata, structural elements)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate section coverage")
    parser.add_argument(
        "--group-id",
        default=os.environ.get("GROUP_ID", "test-5pdfs-1768557493369886422"),
        help="Group ID to validate (default: from GROUP_ID env var)"
    )
    
    args = parser.parse_args()
    validate_coverage(args.group_id)
