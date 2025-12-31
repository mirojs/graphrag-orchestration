#!/usr/bin/env python3
"""
Test Phase 1 Quality Metrics in Deployed v3 API

Validates that silhouette scores, cluster coherence, and confidence levels
are properly calculated and stored in Neo4j.
"""

import requests
import time
import os
from neo4j import GraphDatabase

# Configuration
API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "phase1-v3-validation"
NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

if not NEO4J_PASSWORD:
    raise SystemExit("NEO4J_PASSWORD is not set")

# Test documents
TEST_DOCS = [
    {"text": "ABC Corporation announced a $10M partnership with XYZ Industries focused on AI development."},
    {"text": "CEO John Smith of ABC Corp stated the XYZ partnership will accelerate machine learning research."},
    {"text": "The ABC Corporation and XYZ Industries collaboration includes joint R&D in artificial intelligence."},
    {"text": "Sarah Johnson, CTO at XYZ Industries, confirmed the strategic alliance with ABC Corporation."},
]

def test_indexing():
    """Test v3 indexing endpoint"""
    print("=" * 80)
    print("PHASE 1: INDEXING TEST")
    print("=" * 80)
    
    response = requests.post(
        f"{API_URL}/graphrag/v3/index",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={"documents": TEST_DOCS},
        timeout=120
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Indexing successful")
        print(f"   Documents processed: {result.get('documents_processed', 0)}")
        print(f"   RAPTOR nodes created: {result.get('raptor_nodes_created', 0)}")
        return True
    else:
        print(f"❌ Indexing failed: {response.status_code}")
        print(f"   Response: {response.text}")
        return False

def verify_neo4j_metrics():
    """Verify Phase 1 quality metrics in Neo4j"""
    print("\n" + "=" * 80)
    print("PHASE 2: NEO4J QUALITY METRICS VERIFICATION")
    print("=" * 80)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    try:
        with driver.session() as session:
            # Query RAPTOR nodes with quality metrics
            result = session.run("""
                MATCH (n:RaptorNode)
                WHERE n.group_id = $group_id AND n.level > 0
                RETURN n.level as level,
                       n.cluster_coherence as coherence,
                       n.confidence_level as confidence_level,
                       n.confidence_score as confidence_score,
                       n.silhouette_score as silhouette_score,
                       n.child_count as child_count,
                       n.creation_model as model
                ORDER BY n.level
            """, group_id=GROUP_ID)
            
            records = list(result)
            
            if not records:
                print("❌ No RAPTOR nodes found with level > 0")
                return False
            
            print(f"✅ Found {len(records)} RAPTOR summary nodes")
            print()
            
            has_metrics = False
            for i, record in enumerate(records, 1):
                print(f"Node {i} (Level {record['level']}):")
                print(f"  Cluster Coherence: {record['coherence']}")
                print(f"  Confidence Level: {record['confidence_level']}")
                print(f"  Confidence Score: {record['confidence_score']}")
                print(f"  Silhouette Score: {record['silhouette_score']}")
                print(f"  Child Count: {record['child_count']}")
                print(f"  Creation Model: {record['model']}")
                print()
                
                # Check if metrics exist (not None)
                if (record['coherence'] is not None and 
                    record['confidence_level'] is not None and
                    record['silhouette_score'] is not None):
                    has_metrics = True
            
            if has_metrics:
                print("✅ Phase 1 quality metrics successfully stored in Neo4j")
                return True
            else:
                print("❌ Quality metrics are NULL in Neo4j")
                return False
                
    finally:
        driver.close()

def main():
    """Run Phase 1 validation tests"""
    print("\n" + "=" * 80)
    print("PHASE 1 V3 QUALITY METRICS VALIDATION")
    print("=" * 80)
    print(f"API: {API_URL}")
    print(f"Group ID: {GROUP_ID}")
    print()
    
    # Test 1: Indexing
    if not test_indexing():
        print("\n❌ Test failed: Indexing did not complete")
        return 1
    
    # Wait for processing
    print("\nWaiting 10 seconds for RAPTOR processing...")
    time.sleep(10)
    
    # Test 2: Verify metrics in Neo4j
    if not verify_neo4j_metrics():
        print("\n❌ Test failed: Quality metrics not found in Neo4j")
        return 1
    
    print("\n" + "=" * 80)
    print("✅ ALL TESTS PASSED - Phase 1 Quality Metrics Working!")
    print("=" * 80)
    return 0

if __name__ == "__main__":
    exit(main())
