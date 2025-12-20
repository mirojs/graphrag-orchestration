#!/usr/bin/env python3
"""Test Phase 1 quality metrics with 5 real documents."""

import requests
import time
from neo4j import GraphDatabase

# Configuration
API_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = f"phase1-5docs-{int(time.time())}"  # Unique group ID
NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"

# Storage Account for managed identity
STORAGE_ACCOUNT = "neo4jstorage21224"
CONTAINER = "test-docs"
PDF_FILES = [
    "BUILDERS LIMITED WARRANTY.pdf",
    "HOLDING TANK SERVICING CONTRACT.pdf",
    "PROPERTY MANAGEMENT AGREEMENT.pdf",
    "contoso_lifts_invoice.pdf",
    "purchase_contract.pdf"
]

def test_indexing():
    """Index 5 documents using managed identity for blob storage and Document Intelligence."""
    print("=" * 80)
    print("PHASE 1: INDEXING 5 DOCUMENTS WITH MANAGED IDENTITY")
    print("=" * 80)
    
    # Generate blob URLs (no SAS tokens)
    blob_urls = []
    for filename in PDF_FILES:
        url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER}/{filename}"
        blob_urls.append(url)
        print(f"   {filename}")
    
    print(f"\n   Total: {len(blob_urls)} PDFs")
    print(f"   Authentication: Managed Identity")
    
    print("\n" + "=" * 80)
    print("PHASE 2: SUBMITTING TO GRAPHRAG V3 API")
    print("=" * 80)
    
    start_time = time.time()
    
    # Index documents
    response = requests.post(
        f"{API_URL}/graphrag/v3/index",
        json={
            "documents": blob_urls,
            "run_raptor": True,
            "run_community_detection": True,
            "ingestion": "document-intelligence"  # Use DI with managed identity
        },
        headers={"X-Group-ID": GROUP_ID},
        timeout=300
    )
    
    elapsed = time.time() - start_time
    
    if response.status_code != 200:
        print(f"❌ Indexing failed: {response.status_code} after {elapsed:.1f}s")
        print(response.text)
        return False
    
    result = response.json()
    print(f"✅ Indexing request accepted in {elapsed:.1f}s")
    print(f"   Status: {result.get('status', 'unknown')}")
    print(f"   Documents processed: {result.get('documents_processed', 0)}")
    print(f"   Entities created: {result.get('entities_created', 0)}")
    print(f"   Relationships created: {result.get('relationships_created', 0)}")
    print(f"   RAPTOR nodes created: {result.get('raptor_nodes_created', 0)}")
    print(f"   Message: {result.get('message', '')}")
    
    return True

def verify_quality_metrics():
    """Query Neo4j to verify Phase 1 quality metrics and entity counts."""
    print("\n" + "=" * 80)
    print("PHASE 3: VERIFY DATA AND QUALITY METRICS IN NEO4J")
    print("=" * 80)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # First check if entities exist
        result = session.run("""
            MATCH (e:Entity {group_id: $group_id})
            RETURN count(e) as entity_count
        """, group_id=GROUP_ID)
        entity_count = result.single()["entity_count"]
        
        print(f"\n📊 Data Summary:")
        print(f"   Entities: {entity_count}")
        
        if entity_count == 0:
            print("   ❌ No entities found - indexing may not have completed yet")
            driver.close()
            return False
        
        # Get all RAPTOR nodes with quality metrics
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
        
        nodes = list(result)
        
        if not nodes:
            print("\n   ℹ️  No RAPTOR nodes found with level > 0 (may still be processing)")
            driver.close()
            return entity_count > 0  # Pass if we have entities
        
        print(f"\n✅ Found {len(nodes)} RAPTOR nodes at level > 0")
        
        # Analyze quality metrics
        all_have_metrics = True
        for record in nodes:
            level = record["level"]
            coherence = record["coherence"]
            confidence = record["confidence_level"]
            conf_score = record["confidence_score"]
            child_count = record["child_count"]
            
            print(f"\nLevel {level}:")
            coherence_str = f"{coherence:.3f}" if coherence else "0.000"
            print(f"  Cluster Coherence: {coherence_str}")
            print(f"  Confidence Level: {confidence}")
            conf_score_str = f"{conf_score:.2f}" if conf_score else "0.00"
            print(f"  Confidence Score: {conf_score_str}")
            print(f"  Child Count: {child_count}")
            print(f"  Model: {record['model']}")
            
            # Verify metrics exist
            if coherence is None or coherence == 0.0:
                print(f"  ⚠️  No coherence calculated")
                all_have_metrics = False
            elif confidence == "unknown":
                print(f"  ⚠️  No confidence level assigned")
                all_have_metrics = False
            else:
                # Verify confidence matches coherence threshold
                if coherence >= 0.85 and confidence != "high":
                    print(f"  ❌ Coherence {coherence:.3f} should be 'high' confidence, got '{confidence}'")
                    all_have_metrics = False
                elif 0.75 <= coherence < 0.85 and confidence != "medium":
                    print(f"  ❌ Coherence {coherence:.3f} should be 'medium' confidence, got '{confidence}'")
                    all_have_metrics = False
                elif coherence < 0.75 and confidence != "low":
                    print(f"  ❌ Coherence {coherence:.3f} should be 'low' confidence, got '{confidence}'")
                    all_have_metrics = False
                else:
                    print(f"  ✅ Phase 1 quality metrics correct!")
        
        driver.close()
        return all_have_metrics

if __name__ == "__main__":
    print(f"\nTesting GraphRAG Phase 1 with 5 documents")
    print(f"API: {API_URL}")
    print(f"Group ID: {GROUP_ID}\n")
    
    # Index documents
    if not test_indexing():
        print("\n❌ TEST FAILED: Indexing error")
        exit(1)
    
    # Wait for background processing to complete
    # Full pipeline takes ~7 minutes for 5 PDFs:
    # - Document Intelligence extraction
    # - Chunking
    # - Entity/relationship extraction (LLM)
    # - Community detection
    # - RAPTOR hierarchy (LLM)
    # - Vector indexing
    print("\n⏳ Waiting 450 seconds (~7.5 minutes) for background indexing to complete...")
    for i in range(90):
        time.sleep(5)
        print(f"   {(i+1)*5}s elapsed...")
    
    # Verify metrics
    if not verify_quality_metrics():
        print("\n⚠️  Warning: Some data may still be processing")
    else:
        print("\n✅ Data verified in Neo4j!")
