#!/usr/bin/env python3
"""
Check if indexing is complete for a test group.

Verifies:
- Node counts (Documents, TextChunks, Entities, Sections, Communities)
- Edge counts (Phase 1, 2, 3 foundation edges)
- Entity properties (embeddings, aliases)
- Indexing completeness

Usage:
    # Check specific group
    export GROUP_ID=test-5pdfs-1768557493369886422
    python3 scripts/check_index_complete.py
    
    # Check latest group (reads from last_test_group_id.txt)
    python3 scripts/check_index_complete.py
"""

import os
import sys
from neo4j import GraphDatabase

# Try to get Neo4j credentials from Key Vault via Azure SDK
try:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    
    credential = DefaultAzureCredential()
    vault_url = "https://graphrag-key-vault.vault.azure.net/"
    client = SecretClient(vault_url=vault_url, credential=credential)
    
    NEO4J_URI = client.get_secret("NEO4J-URI").value
    NEO4J_USERNAME = client.get_secret("NEO4J-USERNAME").value
    NEO4J_PASSWORD = client.get_secret("NEO4J-PASSWORD").value
    NEO4J_DATABASE = "neo4j"
    print("✓ Retrieved Neo4j credentials from Azure Key Vault\n")
except Exception as e:
    # Fallback to environment variables
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j-graphrag-23987.swedencentral.azurecontainer.io:7687")
    NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# Get group ID from env or file
GROUP_ID = os.getenv("GROUP_ID")
if not GROUP_ID:
    try:
        with open("last_test_group_id.txt") as f:
            GROUP_ID = f.read().strip()
        print(f"📋 Using group ID from last_test_group_id.txt: {GROUP_ID}\n")
    except FileNotFoundError:
        print("❌ Error: GROUP_ID not set and last_test_group_id.txt not found")
        print("   Set GROUP_ID environment variable or run indexing first")
        sys.exit(1)

if not NEO4J_PASSWORD:
    print("❌ Error: NEO4J_PASSWORD not available")
    print("   Either set NEO4J_PASSWORD environment variable or ensure Azure Key Vault access")
    sys.exit(1)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

print("=" * 80)
print(f"INDEX COMPLETENESS CHECK: {GROUP_ID}")
print("=" * 80)

with driver.session(database=NEO4J_DATABASE) as session:
    # =========================================================================
    # NODE COUNTS
    # =========================================================================
    print("\n📊 NODE COUNTS:")
    print("-" * 80)
    
    result = session.run("""
        MATCH (n {group_id: $group_id})
        WITH labels(n)[0] AS label, count(*) AS count
        RETURN label, count
        ORDER BY count DESC
    """, group_id=GROUP_ID)
    
    node_counts = {}
    for record in result:
        label = record['label']
        count = record['count']
        node_counts[label] = count
        print(f"  {label:20s} {count:6d}")
    
    if not node_counts:
        print("  ❌ No nodes found - indexing failed or wrong group ID")
        driver.close()
        sys.exit(1)
    
    # =========================================================================
    # EDGE COUNTS
    # =========================================================================
    print("\n🔗 EDGE COUNTS:")
    print("-" * 80)
    
    # Phase 1: Foundation edges
    print("  Phase 1 (Foundation):")
    for edge_type in ["APPEARS_IN_SECTION", "APPEARS_IN_DOCUMENT", "HAS_HUB_ENTITY"]:
        result = session.run(f"""
            MATCH ()-[r:{edge_type} {{group_id: $group_id}}]-()
            RETURN count(r) AS count
        """, group_id=GROUP_ID)
        count = result.single()['count']
        status = "✓" if count > 0 else "✗"
        print(f"    {status} {edge_type:25s} {count:6d}")
    
    # Phase 2: Connectivity edges
    print("\n  Phase 2 (Connectivity):")
    result = session.run("""
        MATCH ()-[r:SHARES_ENTITY {group_id: $group_id}]-()
        RETURN count(r) AS count
    """, group_id=GROUP_ID)
    count = result.single()['count']
    status = "✓" if count > 0 else "✗"
    print(f"    {status} SHARES_ENTITY              {count:6d}")
    
    # Phase 3: Semantic edges
    print("\n  Phase 3 (Semantic Enhancement):")
    result = session.run("""
        MATCH ()-[r:SIMILAR_TO {group_id: $group_id}]-()
        RETURN count(r) AS count
    """, group_id=GROUP_ID)
    count = result.single()['count']
    status = "✓" if count > 0 else "✗"
    print(f"    {status} SIMILAR_TO                 {count:6d}")
    
    # Core edges
    print("\n  Core Edges:")
    for edge_type in ["MENTIONS", "IN_SECTION", "RELATED_TO", "SEMANTICALLY_SIMILAR"]:
        result = session.run(f"""
            MATCH ()-[r:{edge_type}]-()
            WHERE (startNode(r).group_id = $group_id OR endNode(r).group_id = $group_id)
            RETURN count(r) AS count
        """, group_id=GROUP_ID)
        count = result.single()['count']
        status = "✓" if count > 0 else "⚠"
        print(f"    {status} {edge_type:25s} {count:6d}")
    
    # =========================================================================
    # ENTITY PROPERTIES (including aliases)
    # =========================================================================
    print("\n🏷️  ENTITY PROPERTIES:")
    print("-" * 80)
    
    result = session.run("""
        MATCH (e:Entity {group_id: $group_id})
        RETURN 
            count(e) AS total,
            sum(CASE WHEN e.embedding IS NOT NULL THEN 1 ELSE 0 END) AS with_embedding,
            sum(CASE WHEN e.aliases IS NOT NULL AND size(e.aliases) > 0 THEN 1 ELSE 0 END) AS with_aliases
    """, group_id=GROUP_ID)
    
    record = result.single()
    total = record['total']
    with_embedding = record['with_embedding']
    with_aliases = record['with_aliases']
    
    print(f"  Total entities:       {total:6d}")
    print(f"  With embeddings:      {with_embedding:6d} ({100*with_embedding//total if total > 0 else 0}%)")
    print(f"  With aliases:         {with_aliases:6d} ({100*with_aliases//total if total > 0 else 0}%)")
    
    # Sample entities with aliases
    if with_aliases > 0:
        print("\n  Sample entities with aliases:")
        result = session.run("""
            MATCH (e:Entity {group_id: $group_id})
            WHERE e.aliases IS NOT NULL AND size(e.aliases) > 0
            RETURN e.name AS name, e.aliases AS aliases
            LIMIT 5
        """, group_id=GROUP_ID)
        
        for record in result:
            aliases_str = ", ".join(record['aliases'][:3])  # Show first 3 aliases
            if len(record['aliases']) > 3:
                aliases_str += f" (+{len(record['aliases'])-3} more)"
            print(f"    • {record['name']:30s} → [{aliases_str}]")
    
    # =========================================================================
    # COMMUNITY DETECTION (DRIFT requirement)
    # =========================================================================
    print("\n🔍 COMMUNITY DETECTION:")
    print("-" * 80)
    
    result = session.run("""
        MATCH (c:__Community__ {group_id: $group_id})
        RETURN c.level AS level, count(*) AS count
        ORDER BY level
    """, group_id=GROUP_ID)
    
    communities = list(result)
    if communities:
        for record in communities:
            print(f"  Level {record['level']}: {record['count']} communities")
    else:
        print("  ⚠️  No communities found - DRIFT will not work")
        print("     Run community detection after indexing completes")
    
    # =========================================================================
    # OVERALL STATUS
    # =========================================================================
    print("\n" + "=" * 80)
    
    required_nodes = ["Document", "TextChunk", "Entity", "Section"]
    has_all_nodes = all(node_counts.get(label, 0) > 0 for label in required_nodes)
    has_communities = bool(communities)
    has_embeddings = with_embedding > 0
    has_aliases = with_aliases > 0
    
    if has_all_nodes and has_communities and has_embeddings:
        print("✅ INDEXING COMPLETE - All checks passed")
        if has_aliases:
            print("✅ ALIAS EXTRACTION WORKING - Entity lookup will be flexible")
        else:
            print("⚠️  NO ALIASES FOUND - Re-index with latest pipeline to enable aliases")
    elif has_all_nodes:
        print("⚠️  INDEXING IN PROGRESS - Communities not yet created")
    else:
        print("❌ INDEXING INCOMPLETE - Missing required nodes")
    
    print("=" * 80)

driver.close()
