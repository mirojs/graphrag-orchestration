"""
Monitor tenant resource usage in multi-tenant GraphRAG deployment.

Tracks per-tenant statistics:
- Node counts
- Document counts
- Query rates
- Storage usage

Usage:
    python monitor_tenants.py [--group-id GROUP_ID] [--top N]
"""

import sys
import os
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

# Load environment variables
load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def get_all_tenants(driver: Driver) -> List[str]:
    """Get list of all unique group_ids in the database."""
    query = """
    MATCH (n)
    WHERE n.group_id IS NOT NULL
    RETURN DISTINCT n.group_id AS group_id
    ORDER BY group_id
    """
    
    with driver.session() as session:
        result = session.run(query)
        return [record["group_id"] for record in result]


def get_tenant_stats(driver: Driver, group_id: str) -> Dict[str, Any]:
    """Get detailed statistics for a specific tenant."""
    
    # Query 1: Node and document counts
    node_query = """
    MATCH (n {group_id: $group_id})
    WITH n.url AS url, count(n) AS node_count
    RETURN 
        count(DISTINCT url) AS document_count,
        sum(node_count) AS total_nodes,
        collect({url: url, nodes: node_count}) AS documents
    """
    
    # Query 2: Relationship counts
    rel_query = """
    MATCH (n {group_id: $group_id})-[r]-()
    RETURN count(r) AS relationship_count
    """
    
    # Query 3: Entity type distribution
    entity_query = """
    MATCH (n:Entity {group_id: $group_id})
    RETURN labels(n) AS labels, count(*) AS count
    ORDER BY count DESC
    LIMIT 10
    """
    
    with driver.session() as session:
        # Get node stats
        node_result = session.run(node_query, group_id=group_id).single()
        
        # Get relationship stats
        rel_result = session.run(rel_query, group_id=group_id).single()
        
        # Get entity distribution
        entity_result = session.run(entity_query, group_id=group_id)
        entity_distribution = [dict(record) for record in entity_result]
        
        # Handle None results safely
        total_nodes = 0
        document_count = 0
        documents: List[Dict[str, Any]] = []
        if node_result:
            total_nodes = node_result["total_nodes"] or 0
            document_count = node_result["document_count"] or 0
            documents = node_result["documents"] or []
        
        relationship_count = 0
        if rel_result:
            relationship_count = rel_result["relationship_count"] or 0
        
        return {
            "group_id": group_id,
            "total_nodes": total_nodes,
            "document_count": document_count,
            "relationship_count": relationship_count,
            "documents": documents,
            "entity_distribution": entity_distribution,
        }


def print_tenant_stats(stats: Dict[str, Any], detailed: bool = False) -> None:
    """Print tenant statistics in a formatted way."""
    print(f"\n{'='*80}")
    print(f"Tenant: {stats['group_id']}")
    print(f"{'='*80}")
    print(f"  Total Nodes:        {stats['total_nodes']:,}")
    print(f"  Documents:          {stats['document_count']:,}")
    print(f"  Relationships:      {stats['relationship_count']:,}")
    
    if detailed and stats['documents']:
        print(f"\n  Documents:")
        for doc in stats['documents'][:10]:  # Show top 10
            print(f"    • {doc['url'][-60:]}: {doc['nodes']} nodes")
        if len(stats['documents']) > 10:
            print(f"    ... and {len(stats['documents']) - 10} more")
    
    if stats['entity_distribution']:
        print(f"\n  Top Entity Types:")
        for entity in stats['entity_distribution'][:5]:
            print(f"    • {entity['labels']}: {entity['count']:,} entities")


def monitor_all_tenants(driver: Driver, top_n: Optional[int] = None) -> None:
    """Monitor all tenants and show summary statistics."""
    tenants = get_all_tenants(driver)
    
    if not tenants:
        print("📭 No tenants found in database")
        return
    
    print(f"\n📊 Found {len(tenants)} tenant(s)")
    print(f"{'='*80}")
    
    # Collect stats for all tenants
    all_stats = []
    for group_id in tenants:
        stats = get_tenant_stats(driver, group_id)
        all_stats.append(stats)
    
    # Sort by node count (descending)
    all_stats.sort(key=lambda x: x['total_nodes'], reverse=True)
    
    # Show top N if specified
    if top_n:
        all_stats = all_stats[:top_n]
        print(f"Showing top {top_n} tenants by node count\n")
    
    # Print summary table
    print(f"{'Group ID':<30} {'Nodes':>10} {'Docs':>8} {'Relationships':>15}")
    print(f"{'-'*30} {'-'*10} {'-'*8} {'-'*15}")
    
    for stats in all_stats:
        print(
            f"{stats['group_id']:<30} "
            f"{stats['total_nodes']:>10,} "
            f"{stats['document_count']:>8,} "
            f"{stats['relationship_count']:>15,}"
        )
    
    # Print totals
    total_nodes = sum(s['total_nodes'] for s in all_stats)
    total_docs = sum(s['document_count'] for s in all_stats)
    total_rels = sum(s['relationship_count'] for s in all_stats)
    
    print(f"{'-'*30} {'-'*10} {'-'*8} {'-'*15}")
    print(
        f"{'TOTAL':<30} "
        f"{total_nodes:>10,} "
        f"{total_docs:>8,} "
        f"{total_rels:>15,}"
    )


def main() -> None:
    """Main entry point for tenant monitoring."""
    parser = argparse.ArgumentParser(
        description="Monitor tenant resource usage in GraphRAG"
    )
    parser.add_argument(
        "--group-id",
        type=str,
        help="Show detailed stats for a specific tenant",
    )
    parser.add_argument(
        "--top",
        type=int,
        help="Show only top N tenants by node count",
    )
    
    args = parser.parse_args()
    
    if not NEO4J_URI or not NEO4J_USERNAME or not NEO4J_PASSWORD:
        print("❌ Error: Neo4j credentials not configured in .env")
        sys.exit(1)
    
    # Type narrowing: after the check above, these are guaranteed to be str
    uri: str = NEO4J_URI
    username: str = NEO4J_USERNAME
    password: str = NEO4J_PASSWORD
    
    driver = GraphDatabase.driver(
        uri,
        auth=(username, password)
    )
    
    try:
        driver.verify_connectivity()
        print(f"✅ Connected to Neo4j at {uri}")
        print(f"⏰ Timestamp: {datetime.now().isoformat()}")
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        sys.exit(1)
    
    try:
        if args.group_id:
            # Show detailed stats for specific tenant
            stats = get_tenant_stats(driver, args.group_id)
            print_tenant_stats(stats, detailed=True)
        else:
            # Show summary for all tenants
            monitor_all_tenants(driver, top_n=args.top)
    
    finally:
        driver.close()


if __name__ == "__main__":
    main()
