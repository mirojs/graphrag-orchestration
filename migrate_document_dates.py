#!/usr/bin/env python3
"""
Migrate existing documents to extract and store dates from their chunks.
This is a one-time migration script to populate d.date on Document nodes.
"""
import sys
import os
from typing import Optional
import re
from datetime import datetime
from neo4j import GraphDatabase

# Neo4j connection details from environment
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j-graphrag-23987.swedencentral.azurecontainer.io:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# Add date extraction function from lazygraphrag_pipeline
def extract_document_date(text: str) -> Optional[str]:
    """
    Extract the latest date from document text and return as ISO format (YYYY-MM-DD).
    Supports: MM/DD/YYYY, YYYY-MM-DD, 'Month DD, YYYY', 'DD Month YYYY'
    """
    if not text:
        return None
    
    # Date patterns (most specific first)
    patterns = [
        # ISO format: YYYY-MM-DD or YYYY/MM/DD
        (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"),
        # US format: MM/DD/YYYY or MM-DD-YYYY
        (r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', lambda m: f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"),
        # Month DD, YYYY
        (r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})', 
         lambda m: datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")),
        # DD Month YYYY
        (r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
         lambda m: datetime.strptime(f"{m.group(2)} {m.group(1)} {m.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")),
    ]
    
    dates = []
    for pattern, formatter in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                iso_date = formatter(match)
                # Validate it's a reasonable date (1900-2100)
                year = int(iso_date.split('-')[0])
                if 1900 <= year <= 2100:
                    dates.append(iso_date)
            except (ValueError, AttributeError):
                continue
    
    # Return the latest date found
    return max(dates) if dates else None


def migrate_document_dates(group_id: str):
    """Extract dates from chunks and update Document nodes."""
    if not NEO4J_PASSWORD:
        print("❌ NEO4J_PASSWORD environment variable not set")
        sys.exit(1)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    print(f"🔄 Migrating document dates for group: {group_id}")
    
    # Step 1: Get all documents in the group
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(
            """
            MATCH (d:Document {group_id: $group_id})
            RETURN d.id AS id, d.title AS title, d.date AS existing_date
            """,
            group_id=group_id
        )
        documents = [{"id": r["id"], "title": r["title"], "existing_date": r["existing_date"]} for r in result]
    
    print(f"   Found {len(documents)} documents")
    
    # Step 2: For each document, get its chunks and extract dates
    for doc in documents:
        doc_id = doc["id"]
        doc_title = doc["title"]
        
        with driver.session(database=NEO4J_DATABASE) as session:
            # Get all chunks for this document
            result = session.run(
                """
                MATCH (c:TextChunk {group_id: $group_id})-[:PART_OF]->(d:Document {id: $doc_id})
                RETURN c.text AS text
                """,
                group_id=group_id,
                doc_id=doc_id
            )
            chunks = [r["text"] for r in result if r["text"]]
        
        if not chunks:
            print(f"   ⚠️  {doc_title}: No chunks found")
            continue
        
        # Concatenate all chunk text for date extraction
        all_text = " ".join(chunks)
        extracted_date = extract_document_date(all_text)
        
        if extracted_date:
            # Update the Document node with the extracted date
            with driver.session(database=NEO4J_DATABASE) as session:
                session.run(
                    """
                    MATCH (d:Document {id: $doc_id, group_id: $group_id})
                    SET d.date = $date
                    """,
                    doc_id=doc_id,
                    group_id=group_id,
                    date=extracted_date
                )
            print(f"   ✅ {doc_title}: date={extracted_date}")
        else:
            print(f"   ⚠️  {doc_title}: No date found in {len(chunks)} chunks")
    
    driver.close()
    print(f"\n✅ Migration complete for group {group_id}")


if __name__ == "__main__":
    # First, let's see what groups exist
    if not NEO4J_PASSWORD:
        print("❌ NEO4J_PASSWORD environment variable not set")
        sys.exit(1)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    
    print("🔍 Checking available groups...")
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (d:Document)
            RETURN DISTINCT d.group_id AS group_id, count(d) AS doc_count
            ORDER BY group_id
        """)
        groups = [(r["group_id"], r["doc_count"]) for r in result]
    
    driver.close()
    
    if not groups:
        print("❌ No documents found in Neo4j")
        sys.exit(1)
    
    print(f"   Found {len(groups)} group(s):")
    for gid, count in groups:
        print(f"      - {gid}: {count} documents")
    
    # Migrate all groups starting with "test-5pdfs"
    test_groups = [gid for gid, _ in groups if gid.startswith("test-5pdfs")]
    
    print(f"\n✨ Migrating {len(test_groups)} test-5pdfs groups...")
    for group_id in test_groups:
        migrate_document_dates(group_id)
        print()
