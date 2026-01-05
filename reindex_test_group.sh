#!/bin/bash
# Clean reindex test using hybrid pipeline with test-5pdfs data
# Verifies all 3 embedding types are 3072 dimensions
set -e

GROUP_ID="test-5pdfs-clean-$(date +%s)"
ENDPOINT="https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"

echo "=========================================="
echo "CLEAN REINDEX - HYBRID PIPELINE TEST"
echo "=========================================="
echo "Group ID: $GROUP_ID"
echo "Endpoint: $ENDPOINT"
echo ""

# Step 1: Clean any existing data (safety check)
echo "🗑️  Step 1: Verifying clean slate..."
python3 << PYEOF
from neo4j import GraphDatabase

uri = "neo4j+s://a86dcf63.databases.neo4j.io"
driver = GraphDatabase.driver(uri, auth=("neo4j", "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"))

with driver.session(database="neo4j") as session:
    result = session.run("""
        MATCH (n)
        WHERE n.group_id = \$group_id
        DETACH DELETE n
        RETURN count(*) as deleted
    """, group_id="$GROUP_ID")
    
    record = result.single()
    print(f"  Deleted {record['deleted']} nodes (should be 0 for new group)")

driver.close()
PYEOF

echo ""
echo "📤 Step 2: Indexing via /hybrid/index/documents..."

# Use HYBRID indexing endpoint (not v3) - this creates Entity + TextChunk embeddings
curl -X POST "$ENDPOINT/hybrid/index/documents" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "documents": [
      {
        "id": "real-estate-agreement",
        "content": "REAL ESTATE PURCHASE AGREEMENT\n\nThis Agreement is made on November 15, 2024, between:\n\nSELLER: John Smith, residing at 456 Oak Avenue, Seattle, WA 98101\nBUYER: ABC Corporation, a Delaware corporation with principal offices at 500 Tech Plaza, Austin, TX 78701\n\nPROPERTY: 123 Main Street, Seattle, WA 98101\nLegal Description: Lot 7, Block 3, Downtown Seattle Subdivision\n\nPURCHASE PRICE: $500,000.00 (Five Hundred Thousand Dollars)\n\nTERMS:\n1. Earnest Money: Buyer shall deposit $50,000 with First National Bank within 5 business days.\n2. Financing: Buyer to obtain conventional mortgage within 45 days.\n3. Inspection: 14-day inspection period from acceptance.\n4. Closing Date: On or before December 31, 2024.\n\nThe property is sold AS-IS with all fixtures and improvements including:\n- Central HVAC system (installed 2020)\n- Kitchen appliances (refrigerator, stove, dishwasher)\n- Window treatments throughout\n\nCONTINGENCIES:\n- Subject to buyer obtaining financing\n- Subject to satisfactory property inspection\n- Subject to clear title report\n\nSIGNATURES:\nJohn Smith, Seller / ABC Corporation, Buyer (By: Sarah Williams, CFO)"
      },
      {
        "id": "elevator-invoice",
        "content": "CONTOSO LIFTS INC. INVOICE\n\nInvoice Number: INV-2024-1847\nInvoice Date: November 22, 2024\n\nBILL TO:\nABC Corporation\n500 Tech Plaza, Austin, TX 78701\nAttn: Facilities Department\n\nDATE: November 20, 2024\nDUE DATE: December 20, 2024\nTERMS: Net 30\n\nSERVICES PROVIDED:\n1. Quarterly Elevator Maintenance - Building A (2 elevators)\n   - Safety system inspection and testing\n   - Lubrication of all moving components\n   - Door alignment and adjustment\n   - Emergency phone system test\n   Unit Price: $500.00 each x 2 = $1,000.00\n\n2. Parts Replacement\n   - Control panel circuit board (Elevator #1): $450.00\n   - Door sensor replacement (Elevator #2): $200.00\n   Parts Subtotal: $650.00\n\n3. Emergency Call-Out (November 5, 2024)\n   - After-hours response to stuck elevator\n   - Labor: 3 hours @ $150/hour = $450.00\n\nSUBTOTAL: $2,100.00\nTAX (8.25%): $173.25\nTOTAL DUE: $2,273.25\n\nPlease remit payment to: Contoso Lifts Inc., Account #44521\nAnnual service contract renewal available - 10% discount on labor rates."
      }
    ],
    "extraction_prompt": "Extract entities and relationships about companies, people, locations, financial transactions, and business agreements."
  }' | jq '.'

echo ""
echo "⏳ Step 3: Waiting 60 seconds for hybrid indexing (entities + chunks + embeddings)..."
sleep 60

echo ""
echo "📊 Step 4: Checking index stats..."
curl -s -X GET "$ENDPOINT/graphrag/v3/stats/$GROUP_ID" \
  -H "X-Group-ID: $GROUP_ID" | jq '.'

echo ""
echo "🔍 Step 5: Verifying embedding dimensions in Neo4j..."
python3 << PYEOF
from neo4j import GraphDatabase

uri = "neo4j+s://a86dcf63.databases.neo4j.io"
driver = GraphDatabase.driver(uri, auth=("neo4j", "uvRJoWeYwAu7ouvN25427WjGnU37oMWaKN_XMN4ySKI"))

with driver.session(database="neo4j") as session:
    # Check TextChunk embeddings (for vector/DRIFT)
    result = session.run("""
        MATCH (c:TextChunk)
        WHERE c.group_id = \$group_id AND c.embedding IS NOT NULL
        WITH size(c.embedding) as dim, COUNT(*) as count
        RETURN dim, count
        ORDER BY dim
    """, group_id="$GROUP_ID")
    
    print("TextChunk embeddings (vector/DRIFT):")
    chunk_dims = []
    for record in result:
        chunk_dims.append(record['dim'])
        print(f"  {record['dim']}d: {record['count']} chunks")
    
    # Check Entity embeddings (for LazyGraphRAG)
    result = session.run("""
        MATCH (e:Entity)
        WHERE e.group_id = \$group_id AND e.embedding IS NOT NULL
        WITH size(e.embedding) as dim, COUNT(*) as count
        RETURN dim, count
        ORDER BY dim
    """, group_id="$GROUP_ID")
    
    print("\nEntity embeddings (LazyGraphRAG/HippoRAG):")
    entity_dims = []
    for record in result:
        entity_dims.append(record['dim'])
        print(f"  {record['dim']}d: {record['count']} entities")
    
    # Verify all are 3072
    print("\n" + "="*60)
    if chunk_dims == [3072] and entity_dims == [3072]:
        print("✅ SUCCESS: All embeddings are 3072 dimensions!")
        print("   - TextChunk (vector/DRIFT): 3072d ✓")
        print("   - Entity (LazyGraphRAG/HippoRAG): 3072d ✓")
    elif 1536 in chunk_dims or 1536 in entity_dims:
        print("❌ FAILURE: Found 1536-dim embeddings!")
        print(f"   Chunk dims: {chunk_dims}, Entity dims: {entity_dims}")
    elif len(chunk_dims) > 1 or len(entity_dims) > 1:
        print("⚠️  WARNING: Mixed dimensions detected!")
        print(f"   Chunk dims: {chunk_dims}, Entity dims: {entity_dims}")
    else:
        print(f"⚠️  UNEXPECTED STATE:")
        print(f"   Chunk dims: {chunk_dims}, Entity dims: {entity_dims}")

driver.close()
PYEOF

echo ""
echo "🧪 Step 6: Testing DRIFT route (tests chunk embeddings)..."
curl -s -X POST "$ENDPOINT/hybrid/query" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "What is the relationship between ABC Corporation and Contoso Lifts?",
    "response_type": "detailed_report",
    "force_route": "drift_multi_hop"
  }' | jq -r '.route_used, .response[:150], "Citations:", .citations | length'

echo ""
echo "🧪 Step 7: Testing LazyGraphRAG route (tests entity embeddings)..."
curl -s -X POST "$ENDPOINT/hybrid/query" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "What is the relationship between ABC Corporation and Contoso Lifts?",
    "response_type": "detailed_report",
    "force_route": "global_search"
  }' | jq -r '.route_used, .response[:150], "Citations:", .citations | length'

echo ""
echo "✅ Clean reindex complete!"
echo "Group ID: $GROUP_ID"
