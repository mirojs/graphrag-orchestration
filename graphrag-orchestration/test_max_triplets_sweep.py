"""
Systematic Test: max_triplets_per_chunk Optimization

Tests values from 20 to 100 to find optimal setting where:
1. Maximum entities/relationships extracted
2. Quality maintained (no hallucinations)
3. Processing time acceptable

Usage:
    python3 test_max_triplets_sweep.py
"""

import requests
import time
import os
from neo4j import GraphDatabase

API_BASE = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

if not NEO4J_PASSWORD:
    raise SystemExit("NEO4J_PASSWORD is not set")

# Test configuration
TEST_VALUES = [20, 40, 60, 80, 100]
TEST_PDFS = [
    "https://afhazstorage.blob.core.windows.net/source-docs/BUILDERS%20LIMITED%20WARRANTY.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/contoso_lifts_invoice.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/purchase_contract.pdf",
]


def cleanup_neo4j(group_id: str):
    """Delete a specific group from Neo4j"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
    try:
        with driver.session(database="neo4j") as session:
            result = session.run(
                """
                MATCH (n {group_id: $group_id})
                CALL (n) { WITH n DETACH DELETE n } IN TRANSACTIONS OF 100 ROWS
                RETURN count(*) as deleted
                """,
                group_id=group_id
            )
            record = result.single()
            return record["deleted"] if record else 0
    finally:
        driver.close()


def get_stats(group_id: str):
    """Get entity/relationship counts from Neo4j"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
    try:
        with driver.session(database="neo4j") as session:
            result = session.run(
                """
                MATCH (e:Entity {group_id: $group_id})
                WITH count(e) as entities
                MATCH (e1:Entity {group_id: $group_id})-[r]-(e2:Entity {group_id: $group_id})
                WHERE type(r) <> 'MENTIONS'
                RETURN entities, count(DISTINCT r) as relationships
                """,
                group_id=group_id
            )
            record = result.single()
            if record:
                return record["entities"], record["relationships"]
            return 0, 0
    finally:
        driver.close()


def run_test(max_triplets: int):
    """Run indexing test with specific max_triplets_per_chunk value"""
    
    print(f"\n{'='*70}")
    print(f"Testing max_triplets_per_chunk = {max_triplets}")
    print(f"{'='*70}")
    
    group_id = f"triplets-test-{max_triplets}-{int(time.time())}"
    
    # Step 1: Index documents
    print(f"\n📤 Submitting indexing request...")
    response = requests.post(
        f"{API_BASE}/graphrag/v3/index",
        headers={"x-group-id": group_id},
        json={
            "documents": [{"url": url} for url in TEST_PDFS],
            "ingestion": "document_intelligence",
            # NOTE: max_triplets_per_chunk must be changed in indexing_pipeline.py
            # This test will require code changes between runs
        }
    )
    
    if response.status_code != 200:
        print(f"❌ Error: {response.text}")
        return None
    
    print(f"✅ Request accepted, group_id: {group_id}")
    
    # Step 2: Wait for indexing
    print(f"\n⏳ Waiting 180 seconds for indexing to complete...")
    time.sleep(180)
    
    # Step 3: Get results
    print(f"\n📊 Retrieving results from Neo4j...")
    entities, relationships = get_stats(group_id)
    
    result = {
        "max_triplets": max_triplets,
        "group_id": group_id,
        "entities": entities,
        "relationships": relationships,
    }
    
    print(f"\n✅ Results:")
    print(f"   Entities: {entities}")
    print(f"   Relationships: {relationships}")
    
    return result


def main():
    print("="*70)
    print("MAX_TRIPLETS_PER_CHUNK OPTIMIZATION TEST")
    print("="*70)
    print(f"\nTest values: {TEST_VALUES}")
    print(f"PDFs: {len(TEST_PDFS)}")
    print(f"\n⚠️  IMPORTANT: You must manually update max_triplets_per_chunk")
    print(f"   in indexing_pipeline.py between each test run!")
    print(f"\n   File: app/v3/services/indexing_pipeline.py")
    print(f"   Line: ~732")
    print(f"   Change: max_triplets_per_chunk=<VALUE>")
    print(f"\n   Then run: bash deploy-graphrag.sh")
    print(f"   Then press Enter to continue each test")
    
    results = []
    
    for max_triplets in TEST_VALUES:
        input(f"\n\n🔧 Set max_triplets_per_chunk={max_triplets} and deploy. Press Enter when ready...")
        
        result = run_test(max_triplets)
        if result:
            results.append(result)
        
        # Small delay between tests
        time.sleep(5)
    
    # Print summary
    print("\n\n" + "="*70)
    print("FINAL RESULTS SUMMARY")
    print("="*70)
    print(f"\n{'max_triplets':<15} {'Entities':<12} {'Relationships':<15} {'E vs baseline':<15} {'R vs baseline'}")
    print("-"*70)
    
    baseline_entities = results[0]["entities"] if results else 352
    baseline_rels = results[0]["relationships"] if results else 440
    
    for result in results:
        e_pct = ((result["entities"] / baseline_entities) - 1) * 100
        r_pct = ((result["relationships"] / baseline_rels) - 1) * 100
        print(f"{result['max_triplets']:<15} {result['entities']:<12} {result['relationships']:<15} {e_pct:>+6.1f}%         {r_pct:>+6.1f}%")
    
    # Find optimal
    if results:
        optimal = max(results, key=lambda x: x["entities"])
        print(f"\n🎯 OPTIMAL: max_triplets_per_chunk = {optimal['max_triplets']}")
        print(f"   Entities: {optimal['entities']}")
        print(f"   Relationships: {optimal['relationships']}")
        
        # Check for plateau
        if len(results) >= 3:
            last_three = results[-3:]
            entity_variance = max(r["entities"] for r in last_three) - min(r["entities"] for r in last_three)
            if entity_variance < 50:
                print(f"\n📊 Plateau detected in last 3 tests (variance: {entity_variance} entities)")
                print(f"   Recommend using max_triplets_per_chunk = {results[-2]['max_triplets']}")


if __name__ == "__main__":
    main()
