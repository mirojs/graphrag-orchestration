#!/usr/bin/env python3
"""
Rebuild KNN test groups properly.

Problem: Current KNN groups (knn-1, knn-2, knn-3) were indexed separately,
resulting in different entity extractions. This invalidates KNN comparison.

Solution: Use the baseline group's entities and create KNN edges with
different configurations. We have two approaches:

APPROACH A (Recommended): Edge-level configuration tagging
- Keep all KNN edges in the same group
- Tag edges with knn_config property (e.g., 'knn-1', 'knn-2', 'knn-3')
- Modify query to filter by knn_config during traversal

APPROACH B: Clone baseline to new groups
- Clone baseline entities/chunks/sections to new group_ids
- Add KNN edges with respective configurations
- More isolated but requires data duplication

This script implements APPROACH A for efficiency.
"""

import asyncio
import os
from typing import List, Tuple
from neo4j import AsyncGraphDatabase
import numpy as np

# Configuration
BASELINE_GROUP = "test-5pdfs-v2-enhanced-ex"

# KNN configurations to test
KNN_CONFIGS = [
    {"name": "knn-1", "k": 3, "cutoff": 0.80, "description": "Conservative: K=3, cutoff=0.80"},
    {"name": "knn-2", "k": 5, "cutoff": 0.75, "description": "Relaxed: K=5, cutoff=0.75"},
    {"name": "knn-3", "k": 5, "cutoff": 0.85, "description": "Strict: K=5, cutoff=0.85"},
]


async def get_driver():
    """Create Neo4j driver from environment."""
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    return AsyncGraphDatabase.driver(uri, auth=(user, password))


async def delete_existing_knn_edges(session, group_id: str):
    """Delete all SEMANTICALLY_SIMILAR edges for a group."""
    result = await session.run("""
        MATCH (e1:Entity {group_id: $group_id})-[r:SEMANTICALLY_SIMILAR]->(e2:Entity)
        DELETE r
        RETURN count(r) AS deleted
    """, group_id=group_id)
    record = await result.single()
    return record["deleted"] if record else 0


async def get_entity_embeddings(session, group_id: str) -> List[dict]:
    """Get all entities with embeddings from the baseline group."""
    result = await session.run("""
        MATCH (e:Entity {group_id: $group_id})
        WHERE e.embedding_v2 IS NOT NULL
        RETURN e.id AS id, e.name AS name, e.embedding_v2 AS embedding
    """, group_id=group_id)
    records = await result.data()
    return records


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec1)
    b = np.array(vec2)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def compute_knn_edges(
    entities: List[dict], k: int, cutoff: float
) -> List[Tuple[str, str, float]]:
    """
    Compute KNN edges for entities.
    
    Returns list of (source_id, target_id, similarity) tuples.
    """
    edges = []
    n = len(entities)
    
    # Precompute all embeddings as numpy arrays
    embeddings = {e["id"]: np.array(e["embedding"]) for e in entities}
    entity_ids = list(embeddings.keys())
    
    print(f"  Computing KNN for {n} entities (K={k}, cutoff={cutoff})...")
    
    for i, src_id in enumerate(entity_ids):
        if i % 50 == 0:
            print(f"    Processing entity {i+1}/{n}...")
        
        src_emb = embeddings[src_id]
        
        # Compute similarities to all other entities
        similarities = []
        for tgt_id in entity_ids:
            if tgt_id == src_id:
                continue
            tgt_emb = embeddings[tgt_id]
            sim = float(np.dot(src_emb, tgt_emb) / (np.linalg.norm(src_emb) * np.linalg.norm(tgt_emb)))
            if sim >= cutoff:
                similarities.append((tgt_id, sim))
        
        # Keep top-k neighbors above cutoff
        similarities.sort(key=lambda x: x[1], reverse=True)
        for tgt_id, sim in similarities[:k]:
            edges.append((src_id, tgt_id, sim))
    
    return edges


async def create_knn_edges(
    session, 
    group_id: str, 
    edges: List[Tuple[str, str, float]], 
    knn_config: str
):
    """Create KNN edges with configuration tag."""
    # Batch insert for efficiency
    batch_size = 100
    total_created = 0
    
    for i in range(0, len(edges), batch_size):
        batch = edges[i:i+batch_size]
        edge_data = [
            {"src": e[0], "tgt": e[1], "score": e[2]} 
            for e in batch
        ]
        
        result = await session.run("""
            UNWIND $edges AS edge
            MATCH (e1:Entity {id: edge.src, group_id: $group_id})
            MATCH (e2:Entity {id: edge.tgt, group_id: $group_id})
            MERGE (e1)-[r:SEMANTICALLY_SIMILAR {knn_config: $knn_config}]->(e2)
            SET r.score = edge.score,
                r.method = 'knn',
                r.created_at = datetime()
            RETURN count(r) AS created
        """, edges=edge_data, group_id=group_id, knn_config=knn_config)
        
        record = await result.single()
        total_created += record["created"] if record else 0
    
    return total_created


async def main():
    print("=" * 70)
    print("KNN Test Groups Rebuild - Proper Implementation")
    print("=" * 70)
    print(f"\nBaseline group: {BASELINE_GROUP}")
    print("\nKNN configurations to create:")
    for cfg in KNN_CONFIGS:
        print(f"  - {cfg['name']}: {cfg['description']}")
    
    driver = await get_driver()
    
    async with driver.session() as session:
        # Step 1: Delete existing KNN edges
        print(f"\n{'='*70}")
        print("Step 1: Cleaning up existing SEMANTICALLY_SIMILAR edges")
        print("=" * 70)
        
        deleted = await delete_existing_knn_edges(session, BASELINE_GROUP)
        print(f"  Deleted {deleted} existing edges from {BASELINE_GROUP}")
        
        # Step 2: Get all entity embeddings
        print(f"\n{'='*70}")
        print("Step 2: Loading entity embeddings")
        print("=" * 70)
        
        entities = await get_entity_embeddings(session, BASELINE_GROUP)
        print(f"  Loaded {len(entities)} entities with embeddings")
        
        # Step 3: Compute and create KNN edges for each configuration
        print(f"\n{'='*70}")
        print("Step 3: Creating KNN edges for each configuration")
        print("=" * 70)
        
        results = {}
        for cfg in KNN_CONFIGS:
            print(f"\n  [{cfg['name']}] {cfg['description']}")
            
            # Compute edges
            edges = compute_knn_edges(entities, cfg['k'], cfg['cutoff'])
            print(f"    Computed {len(edges)} edges")
            
            # Create edges with config tag
            created = await create_knn_edges(
                session, BASELINE_GROUP, edges, cfg['name']
            )
            print(f"    Created {created} edges in Neo4j")
            
            results[cfg['name']] = {
                'computed': len(edges),
                'created': created,
                'k': cfg['k'],
                'cutoff': cfg['cutoff']
            }
        
        # Step 4: Verify edge counts
        print(f"\n{'='*70}")
        print("Step 4: Verification")
        print("=" * 70)
        
        result = await session.run("""
            MATCH (e1:Entity {group_id: $group_id})-[r:SEMANTICALLY_SIMILAR]->(e2:Entity)
            RETURN r.knn_config AS config, count(r) AS cnt
            ORDER BY config
        """, group_id=BASELINE_GROUP)
        records = await result.data()
        
        print(f"\n  SEMANTICALLY_SIMILAR edges by knn_config:")
        for r in records:
            print(f"    {r['config']}: {r['cnt']} edges")
    
    await driver.close()
    
    # Summary
    print(f"\n{'='*70}")
    print("Summary")
    print("=" * 70)
    print(f"\nAll KNN configurations created in group: {BASELINE_GROUP}")
    print("\nTo query with specific KNN config, filter by r.knn_config:")
    print("  - 'knn-1' for conservative (K=3, cutoff=0.80)")
    print("  - 'knn-2' for relaxed (K=5, cutoff=0.75)")  
    print("  - 'knn-3' for strict (K=5, cutoff=0.85)")
    print("  - No filter = baseline (no KNN edges traversed)")
    print("\nExample Cypher:")
    print("""
    // With KNN-2 config:
    MATCH (e1)-[r:SEMANTICALLY_SIMILAR {knn_config: 'knn-2'}]-(e2)
    WHERE e1.group_id = 'test-5pdfs-v2-enhanced-ex'
    RETURN e1.name, e2.name, r.score
    
    // Without KNN (baseline):
    MATCH (e1)-[r:RELATED_TO]-(e2)  // Use only RELATED_TO edges
    WHERE e1.group_id = 'test-5pdfs-v2-enhanced-ex'
    RETURN e1.name, e2.name
    """)


if __name__ == "__main__":
    asyncio.run(main())
