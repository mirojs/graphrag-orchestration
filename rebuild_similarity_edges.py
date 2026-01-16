#!/usr/bin/env python3
"""
Rebuild SEMANTICALLY_SIMILAR edges for test group with new threshold (0.43).
This directly manipulates Neo4j to delete old edges and create new ones.
"""

import os
from neo4j import GraphDatabase
import numpy as np

# Neo4j connection from environment or hardcoded
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j-graphrag-23987.swedencentral.azurecontainer.io:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")  # Must be set
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

GROUP_ID = "test-5pdfs-1768486622652179443"
SIMILARITY_THRESHOLD = 0.43
MAX_EDGES_PER_SECTION = 5

if not NEO4J_PASSWORD:
    print("❌ Error: NEO4J_PASSWORD environment variable not set")
    exit(1)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

print(f"🗑️  Step 1: Deleting existing SEMANTICALLY_SIMILAR edges for group {GROUP_ID}...")
with driver.session(database=NEO4J_DATABASE) as session:
    result = session.run(
        """
        MATCH (s1:Section {group_id: $group_id})-[r:SEMANTICALLY_SIMILAR]->(s2:Section)
        DELETE r
        RETURN count(r) AS deleted_count
        """,
        group_id=GROUP_ID
    )
    deleted = result.single()["deleted_count"]
    print(f"   Deleted {deleted} existing edges")

print(f"\n📥 Step 2: Fetching sections with embeddings...")
with driver.session(database=NEO4J_DATABASE) as session:
    result = session.run(
        """
        MATCH (s:Section {group_id: $group_id})
        WHERE s.embedding IS NOT NULL
        RETURN s.id AS id, s.doc_id AS doc_id, s.embedding AS embedding
        """,
        group_id=GROUP_ID
    )
    sections = [
        {"id": record["id"], "doc_id": record["doc_id"], "embedding": record["embedding"]}
        for record in result
    ]

print(f"   Found {len(sections)} sections with embeddings")

if len(sections) < 2:
    print("❌ Not enough sections to create edges")
    driver.close()
    exit(1)

print(f"\n🔗 Step 3: Computing similarities and creating edges (threshold={SIMILARITY_THRESHOLD})...")
edges_to_create = []
edge_count_per_section = {}

for i, s1 in enumerate(sections):
    if s1["embedding"] is None:
        continue
    emb1 = np.array(s1["embedding"])
    norm1 = np.linalg.norm(emb1)
    if norm1 == 0:
        continue
    
    for j, s2 in enumerate(sections):
        if j <= i:  # Avoid duplicates and self-comparison
            continue
        if s1["doc_id"] == s2["doc_id"]:  # Only cross-document
            continue
        if s2["embedding"] is None:
            continue
        
        # Check edge count limits
        if edge_count_per_section.get(s1["id"], 0) >= MAX_EDGES_PER_SECTION:
            continue
        if edge_count_per_section.get(s2["id"], 0) >= MAX_EDGES_PER_SECTION:
            continue
        
        emb2 = np.array(s2["embedding"])
        norm2 = np.linalg.norm(emb2)
        if norm2 == 0:
            continue
        
        # Cosine similarity
        similarity = float(np.dot(emb1, emb2) / (norm1 * norm2))
        
        if similarity >= SIMILARITY_THRESHOLD:
            edges_to_create.append({
                "s1_id": s1["id"],
                "s2_id": s2["id"],
                "similarity": similarity
            })
            edge_count_per_section[s1["id"]] = edge_count_per_section.get(s1["id"], 0) + 1
            edge_count_per_section[s2["id"]] = edge_count_per_section.get(s2["id"], 0) + 1

print(f"   Found {len(edges_to_create)} edges above threshold")

if edges_to_create:
    print(f"\n💾 Step 4: Creating {len(edges_to_create)} SEMANTICALLY_SIMILAR edges...")
    with driver.session(database=NEO4J_DATABASE) as session:
        for edge in edges_to_create:
            session.run(
                """
                MATCH (s1:Section {id: $s1_id}), (s2:Section {id: $s2_id})
                MERGE (s1)-[r:SEMANTICALLY_SIMILAR]->(s2)
                SET r.similarity = $similarity, r.group_id = $group_id
                """,
                s1_id=edge["s1_id"],
                s2_id=edge["s2_id"],
                similarity=edge["similarity"],
                group_id=GROUP_ID
            )
    print(f"   ✅ Created {len(edges_to_create)} edges")
else:
    print("   ⚠️  No edges created - threshold may still be too high")

print(f"\n✅ Rebuild complete!")
print(f"   Threshold: {SIMILARITY_THRESHOLD}")
print(f"   Edges created: {len(edges_to_create)}")

driver.close()
