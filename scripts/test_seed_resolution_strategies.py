#!/usr/bin/env python3
"""
Test script to verify all 6 seed resolution strategies in HippoRAG retriever.

Strategies:
1. Exact match on node ID (case-insensitive)
2. Alias match - check entity aliases for exact match
3. KVP key match - check KeyValue node keys for exact match
4. Substring match on node ID
5. Token overlap (Jaccard similarity) on node ID
6. Vector similarity - semantic search on entity embeddings (last resort)

Usage:
    python scripts/test_seed_resolution_strategies.py [--group-id GROUP_ID]
"""

import asyncio
import os
import sys
from typing import Dict, List, Any

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'graphrag-orchestration'))

from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


def get_neo4j_driver():
    """Get Neo4j driver from environment."""
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    
    if not uri or not password:
        raise ValueError("NEO4J_URI and NEO4J_PASSWORD must be set")
    
    return GraphDatabase.driver(uri, auth=(user, password))


def analyze_group(driver, group_id: str) -> Dict[str, Any]:
    """Analyze a group's entities, aliases, and KVP keys."""
    
    results = {
        "group_id": group_id,
        "entities": [],
        "aliases": {},
        "kvp_keys": {},
        "sample_entities": [],
    }
    
    with driver.session() as session:
        # Count entities
        count_result = session.run("""
            MATCH (e:Entity {group_id: $group_id})
            RETURN count(e) AS entity_count
        """, group_id=group_id)
        record = count_result.single()
        results["entity_count"] = record["entity_count"] if record else 0
        
        # Get entities with aliases
        alias_result = session.run("""
            MATCH (e:Entity {group_id: $group_id})
            WHERE e.aliases IS NOT NULL AND size(e.aliases) > 0
            RETURN e.id AS entity_id, e.name AS name, e.aliases AS aliases
            LIMIT 20
        """, group_id=group_id)
        
        for record in alias_result:
            entity_id = record["entity_id"]
            aliases = record["aliases"]
            results["entities"].append({
                "id": entity_id,
                "name": record["name"],
                "aliases": aliases,
            })
            for alias in aliases:
                alias_lc = alias.lower().strip()
                if alias_lc not in results["aliases"]:
                    results["aliases"][alias_lc] = []
                results["aliases"][alias_lc].append(entity_id)
        
        # Get KVP keys
        kvp_result = session.run("""
            MATCH (k:KeyValuePair {group_id: $group_id})
            WHERE k.key IS NOT NULL
            RETURN k.id AS kvp_id, k.key AS key, k.value AS value
            LIMIT 20
        """, group_id=group_id)
        
        for record in kvp_result:
            key_lc = record["key"].lower().strip()
            if key_lc not in results["kvp_keys"]:
                results["kvp_keys"][key_lc] = []
            results["kvp_keys"][key_lc].append(record["kvp_id"])
        
        # Get sample entities for testing
        sample_result = session.run("""
            MATCH (e:Entity {group_id: $group_id})
            RETURN e.id AS entity_id, e.name AS name
            LIMIT 10
        """, group_id=group_id)
        
        for record in sample_result:
            results["sample_entities"].append({
                "id": record["entity_id"],
                "name": record["name"],
            })
    
    return results


def test_strategy_matching(group_data: Dict[str, Any]) -> Dict[str, List[Dict]]:
    """Test various seed phrases against each strategy."""
    
    test_cases = []
    
    # Test cases for different strategies
    sample_entities = group_data.get("sample_entities", [])
    aliases = group_data.get("aliases", {})
    kvp_keys = group_data.get("kvp_keys", {})
    
    # Strategy 1: Exact match - use entity name directly
    if sample_entities:
        entity = sample_entities[0]
        test_cases.append({
            "seed": entity["name"] or entity["id"],
            "expected_strategy": "1. Exact match",
            "should_match": entity["id"],
        })
    
    # Strategy 2: Alias match
    if aliases:
        alias_key = list(aliases.keys())[0]
        test_cases.append({
            "seed": alias_key,
            "expected_strategy": "2. Alias match",
            "should_match": aliases[alias_key][0],
        })
    
    # Strategy 3: KVP key match
    if kvp_keys:
        kvp_key = list(kvp_keys.keys())[0]
        test_cases.append({
            "seed": kvp_key,
            "expected_strategy": "3. KVP key match",
            "should_match": kvp_keys[kvp_key][0],
        })
    
    # Strategy 4: Substring match - use partial entity name
    if sample_entities and len(sample_entities) > 1:
        entity = sample_entities[1]
        name = entity["name"] or entity["id"]
        if len(name) > 5:
            partial = name[:len(name)//2]
            test_cases.append({
                "seed": partial,
                "expected_strategy": "4. Substring match",
                "should_match": entity["id"],
            })
    
    # Strategy 5: Jaccard match - use word tokens
    if sample_entities and len(sample_entities) > 2:
        entity = sample_entities[2]
        name = entity["name"] or entity["id"]
        words = name.split()
        if len(words) >= 2:
            test_cases.append({
                "seed": words[0],
                "expected_strategy": "5. Jaccard/Token overlap",
                "should_match": entity["id"],
            })
    
    # Strategy 6: Vector similarity - use semantic paraphrase
    test_cases.append({
        "seed": "elevator equipment",  # Should match "Vertical Platform Lift" via embedding
        "expected_strategy": "6. Vector similarity",
        "should_match": None,  # Unknown, depends on corpus
    })
    
    test_cases.append({
        "seed": "payment portal",  # Should match payment-related entities
        "expected_strategy": "6. Vector similarity", 
        "should_match": None,
    })
    
    return test_cases


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test seed resolution strategies")
    parser.add_argument("--group-id", default="test-5pdfs-v2-enhanced-ex",
                       help="Group ID to test (default: test-5pdfs-v2-enhanced-ex)")
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"Testing Seed Resolution Strategies")
    print(f"Group ID: {args.group_id}")
    print(f"{'='*60}\n")
    
    driver = get_neo4j_driver()
    
    try:
        # Analyze group
        print("Analyzing group structure...")
        group_data = analyze_group(driver, args.group_id)
        
        print(f"\n📊 Group Statistics:")
        print(f"   - Total entities: {group_data['entity_count']}")
        print(f"   - Entities with aliases: {len(group_data['entities'])}")
        print(f"   - Unique alias keys: {len(group_data['aliases'])}")
        print(f"   - KVP keys: {len(group_data['kvp_keys'])}")
        
        # Show sample aliases
        print(f"\n📝 Sample Aliases:")
        for i, (alias, entities) in enumerate(list(group_data['aliases'].items())[:5]):
            print(f"   - '{alias}' → {entities[0][:50]}...")
        
        # Show sample KVP keys
        if group_data['kvp_keys']:
            print(f"\n🔑 Sample KVP Keys:")
            for i, (key, kvps) in enumerate(list(group_data['kvp_keys'].items())[:5]):
                print(f"   - '{key}' → {kvps[0][:50]}...")
        
        # Generate test cases
        print(f"\n🧪 Test Cases for Each Strategy:")
        print("-" * 60)
        
        test_cases = test_strategy_matching(group_data)
        
        for tc in test_cases:
            print(f"\nSeed: \"{tc['seed']}\"")
            print(f"   Expected Strategy: {tc['expected_strategy']}")
            if tc['should_match']:
                print(f"   Should Match: {tc['should_match'][:60]}...")
            else:
                print(f"   Should Match: (semantic match - verify manually)")
        
        # Instructions for manual testing
        print(f"\n{'='*60}")
        print("📋 Manual Verification Steps:")
        print("="*60)
        print("""
1. Start the API server:
   cd graphrag-orchestration && python -m uvicorn app.main:app --reload

2. Test Route 4 with a seed:
   curl -X POST "http://localhost:8000/hybrid/query" \\
     -H "X-Group-ID: """ + args.group_id + """" \\
     -H "Content-Type: application/json" \\
     -d '{"query": "What is the Savaria V1504?", "force_route": "drift_multi_hop"}'

3. Check logs for seed resolution:
   Look for: hipporag_seed_expanded, hipporag_seed_matched_via_vector, hipporag_seed_no_match

4. Verify evidence count is > 0 in response
""")
        
    finally:
        driver.close()


if __name__ == "__main__":
    main()
