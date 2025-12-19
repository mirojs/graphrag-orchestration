#!/usr/bin/env python3
"""Test Phase 1 quality metrics with 5 real documents."""

import requests
import time
from neo4j import GraphDatabase

# Configuration
API_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = f"phase1-5docs-{int(time.time())}"  # Unique group ID
NEO4J_URI = "neo4j+s://a86dcf63.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"

# Document paths
DOC_DIR = "/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/input_docs"
DOCUMENTS = [
    f"{DOC_DIR}/BUILDERS LIMITED WARRANTY.pdf",
    f"{DOC_DIR}/HOLDING TANK SERVICING CONTRACT.pdf",
    f"{DOC_DIR}/PROPERTY MANAGEMENT AGREEMENT.pdf",
    f"{DOC_DIR}/contoso_lifts_invoice.pdf",
    f"{DOC_DIR}/purchase_contract.pdf"
]

def test_indexing():
    """Index 5 documents using GraphRAG v3 API."""
    print("=" * 80)
    print("PHASE 1: EXTRACTING TEXT FROM 5 DOCUMENTS")
    print("=" * 80)
    
    # Extract text from PDFs using Document Intelligence
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.identity import DefaultAzureCredential
    
    doc_intel_endpoint = "https://doc-intel-graphrag.cognitiveservices.azure.com/"
    credential = DefaultAzureCredential()
    client = DocumentIntelligenceClient(endpoint=doc_intel_endpoint, credential=credential)
    
    documents = []
    for doc_path in DOCUMENTS:
        filename = doc_path.split("/")[-1]
        print(f"Extracting text from {filename}...")
        
        with open(doc_path, 'rb') as f:
            poller = client.begin_analyze_document(
                model_id="prebuilt-layout",
                body=f,
                content_type="application/pdf"
            )
            result = poller.result()
        
        # Extract text content
        text_content = ""
        if result.content:
            text_content = result.content
        
        documents.append({
            "text": text_content,
            "metadata": {
                "source": filename,
                "type": "pdf"
            }
        })
        print(f"   Extracted {len(text_content)} characters")
    
    print("\n" + "=" * 80)
    print("PHASE 2: INDEXING WITH GRAPHRAG V3")
    print("=" * 80)
    
    # Index documents
    response = requests.post(
        f"{API_URL}/graphrag/v3/index",
        json={
            "documents": documents,
            "run_raptor": True,
            "run_community_detection": True,
            "ingestion": "none"  # Already extracted
        },
        headers={"X-Group-ID": GROUP_ID}
    )
    
    if response.status_code != 200:
        print(f"❌ Indexing failed: {response.status_code}")
        print(response.text)
        return False
    
    result = response.json()
    print("✅ Indexing successful")
    print(f"   Documents processed: {result.get('documents_processed', 0)}")
    print(f"   Entities created: {result.get('entities_created', 0)}")
    print(f"   Relationships created: {result.get('relationships_created', 0)}")
    print(f"   RAPTOR nodes created: {result.get('raptor_nodes_created', 0)}")
    
    return True

def verify_quality_metrics():
    """Query Neo4j to verify Phase 1 quality metrics."""
    print("\n" + "=" * 80)
    print("PHASE 2: VERIFY QUALITY METRICS IN NEO4J")
    print("=" * 80)
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
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
            print("❌ No RAPTOR nodes found with level > 0")
            driver.close()
            return False
        
        print(f"✅ Found {len(nodes)} RAPTOR nodes at level > 0")
        
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
    
    # Wait for processing
    print("\nWaiting 30 seconds for background processing...")
    time.sleep(30)
    
    # Verify metrics
    if not verify_quality_metrics():
        print("\n❌ TEST FAILED: Quality metrics missing or incorrect")
        exit(1)
    
    print("\n" + "=" * 80)
    print("✅ ALL TESTS PASSED - Phase 1 Quality Metrics Working!")
    print("=" * 80)
