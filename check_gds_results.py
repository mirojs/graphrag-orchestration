#!/usr/bin/env python3
"""Quick check of GDS results."""
from dotenv import load_dotenv
load_dotenv('graphrag-orchestration/.env')
import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=('neo4j', os.getenv('NEO4J_PASSWORD')))

print("=" * 70)
print("GDS Results Check - test-5pdfs-v2-1769496129")
print("=" * 70)

with driver.session() as session:
    # Check node properties
    result = session.run('''
        MATCH (n)
        WHERE n.group_id = "test-5pdfs-v2-1769496129"
        RETURN 
            count(DISTINCT CASE WHEN n:Entity THEN n END) AS entities,
            count(DISTINCT CASE WHEN n:Figure THEN n END) AS figures,
            count(DISTINCT CASE WHEN n:KeyValuePair THEN n END) AS kvps,
            count(DISTINCT CASE WHEN n.embedding_v2 IS NOT NULL THEN n END) AS with_v2_embedding,
            count(DISTINCT CASE WHEN n.pagerank IS NOT NULL THEN n END) AS with_pagerank,
            count(DISTINCT CASE WHEN n.community_id IS NOT NULL THEN n END) AS with_community
    ''')
    r = result.single()
    print("\nNode Counts:")
    print(f"  Entities: {r['entities']}")
    print(f"  Figures: {r['figures']}")
    print(f"  KeyValuePairs: {r['kvps']}")
    print(f"  With embedding_v2: {r['with_v2_embedding']}")
    print(f"  With PageRank: {r['with_pagerank']}")
    print(f"  With Community ID: {r['with_community']}")
    
    # Check GDS edges
    edge_result = session.run('''
        MATCH ()-[r]->()
        WHERE r.group_id = "test-5pdfs-v2-1769496129" AND r.method = "gds_knn"
        RETURN type(r) AS edge_type, count(r) AS count
    ''')
    
    print("\nGDS KNN Edges:")
    total_knn = 0
    for r in edge_result:
        print(f"  {r['edge_type']}: {r['count']}")
        total_knn += r['count']
    
    if total_knn == 0:
        print("  ⚠️  No GDS KNN edges found")
    
    # Check PageRank distribution
    pr_result = session.run('''
        MATCH (n)
        WHERE n.group_id = "test-5pdfs-v2-1769496129" AND n.pagerank IS NOT NULL
        RETURN min(n.pagerank) AS min_pr, max(n.pagerank) AS max_pr, avg(n.pagerank) AS avg_pr
    ''')
    pr = pr_result.single()
    if pr and pr['max_pr']:
        print(f"\nPageRank Distribution:")
        print(f"  Min: {pr['min_pr']:.6f}")
        print(f"  Max: {pr['max_pr']:.6f}")
        print(f"  Avg: {pr['avg_pr']:.6f}")
    
    # Check community distribution
    comm_result = session.run('''
        MATCH (n)
        WHERE n.group_id = "test-5pdfs-v2-1769496129" AND n.community_id IS NOT NULL
        RETURN count(DISTINCT n.community_id) AS num_communities
    ''')
    comm = comm_result.single()
    if comm and comm['num_communities']:
        print(f"\nCommunities: {comm['num_communities']}")

driver.close()
print("\n" + "=" * 70)
