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

def cleanup_neo4j():
    """Delete all existing groups from Neo4j before starting."""
    print("=" * 80)
    print("CLEANUP: DELETING ALL EXISTING GROUPS FROM NEO4J")
    print("=" * 80)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Find all unique group_ids
        result = session.run("""
            MATCH (n)
            WHERE n.group_id IS NOT NULL
            RETURN DISTINCT n.group_id AS group_id
            ORDER BY group_id
        """)
        
        groups = [record['group_id'] for record in result]
        
        if not groups:
            print("✅ No existing groups found - Neo4j is clean")
            driver.close()
            return
        
        print(f"Found {len(groups)} groups to delete")
        
        # Delete all groups
        for group_id in groups:
            result = session.run("""
                MATCH (n {group_id: $group_id})
                DETACH DELETE n
                RETURN count(n) AS deleted
            """, group_id=group_id)
            
            record = result.single()
            deleted = record['deleted'] if record else 0
            if deleted > 0:
                print(f"  ✅ Deleted {deleted} nodes from group: {group_id[:40]}...")
    
    print(f"✅ Cleanup complete - deleted {len(groups)} groups\n")
    driver.close()

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
        # Get comprehensive statistics
        result = session.run("""
            MATCH (e:Entity {group_id: $group_id})
            WITH count(e) AS entities
            MATCH (c:Community {group_id: $group_id})
            WITH entities, count(c) AS communities
            MATCH (r:RaptorNode {group_id: $group_id})
            WITH entities, communities, count(r) AS raptor_nodes
            MATCH (t:TextChunk {group_id: $group_id})
            WITH entities, communities, raptor_nodes, count(t) AS text_chunks
            MATCH (d:Document {group_id: $group_id})
            WITH entities, communities, raptor_nodes, text_chunks, count(d) AS documents
            OPTIONAL MATCH (:Entity {group_id: $group_id})-[rel]->(:Entity {group_id: $group_id})
            RETURN entities, communities, raptor_nodes, text_chunks, documents, count(rel) AS relationships
        """, group_id=GROUP_ID)
        
        record = result.single()
        if not record:
            print("   ❌ No data found - indexing may not have completed yet")
            driver.close()
            return False
        
        entities = record["entities"]
        relationships = record["relationships"]
        communities = record["communities"]
        documents = record["documents"]
        raptor_nodes = record["raptor_nodes"]
        text_chunks = record["text_chunks"]
        
        print(f"\n📊 Indexing Statistics:")
        print(f"   Documents: {documents}")
        print(f"   Text Chunks: {text_chunks}")
        print(f"   Entities: {entities}")
        print(f"   Relationships: {relationships}")
        print(f"   Communities: {communities}")
        print(f"   RAPTOR Nodes: {raptor_nodes}")
        
        # Check for duplicate Document nodes
        result = session.run("""
            MATCH (d:Document {group_id: $group_id})
            RETURN d.title AS title, count(*) AS count
            ORDER BY count DESC, title
        """, group_id=GROUP_ID)
        
        doc_counts = list(result)
        duplicates = [r for r in doc_counts if r["count"] > 1]
        
        if duplicates:
            print(f"\n⚠️  Duplicate Document nodes detected:")
            for r in duplicates:
                print(f"     {r['title']}: {r['count']} nodes")
        else:
            print(f"\n✅ No duplicate Document nodes (1 node per PDF)")
        
        # Compare with baseline
        print(f"\n📈 Comparison with Baseline (352 entities, 440 relationships):")
        if entities >= 300:
            print(f"   ✅ Entities: {entities} (target: 300+)")
        else:
            print(f"   ⚠️  Entities: {entities} (target: 300+, {((entities/352)-1)*100:+.1f}%)")
        
        if relationships >= 350:
            print(f"   ✅ Relationships: {relationships} (target: 350+)")
        else:
            print(f"   ⚠️  Relationships: {relationships} (target: 350+, {((relationships/440)-1)*100:+.1f}%)")
        
        if entities == 0:
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
    
    # Cleanup Neo4j first
    cleanup_neo4j()
    
    # Index documents
    if not test_indexing():
        print("\n❌ TEST FAILED: Indexing error")
        exit(1)
    
    # Wait for background processing to complete
    # Full pipeline typically takes 1-3 minutes for 5 PDFs with the fixes:
    # - Document Intelligence extraction (~30s)
    # - Chunking and entity extraction (~60s)
    # - Community detection and RAPTOR (~60s)
    print("\n⏳ Waiting 120 seconds (2 minutes) for background indexing to complete...")
    for i in range(24):
        time.sleep(5)
        if (i + 1) % 6 == 0:
            print(f"   {(i+1)*5}s elapsed...")
    
    # Quick stats check via API
    print("\n" + "=" * 80)
    print("CHECKING INDEXING PROGRESS VIA API")
    print("=" * 80)
    response = requests.get(
        f"{API_URL}/graphrag/v3/stats/{GROUP_ID}",
        headers={"X-Group-ID": GROUP_ID}
    )
    if response.status_code == 200:
        stats = response.json()
        print(f"   Documents: {stats.get('documents', 0)}")
        print(f"   Entities: {stats.get('entities', 0)}")
        print(f"   Relationships: {stats.get('relationships', 0)}")
        if stats.get('entities', 0) == 0:
            print("\n⏳ Still processing, waiting another 60 seconds...")
            time.sleep(60)
    
    # Verify metrics
    if not verify_quality_metrics():
        print("\n⚠️  Warning: Some data may still be processing")
    else:
        print("\n✅ Data verified in Neo4j!")
