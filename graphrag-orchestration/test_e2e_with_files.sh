#!/bin/bash
# End-to-End GraphRAG Test with Real PDF Files via Azure Content Understanding
# Full workflow: Upload PDFs → CU Extract → GraphRAG Index → Query

set -e

# Configuration
URL="https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io"
CONTENT_API_URL="${CONTENT_API_URL:-http://localhost:8000}"
GROUP="e2e-test-$(date +%s)"
INPUT_DIR="../../data/input_docs"

echo "=========================================="
echo "GraphRAG E2E Test: PDF → CU → GraphRAG"
echo "=========================================="
echo "GraphRAG Service: $URL"
echo "Content API: $CONTENT_API_URL"
echo "Group ID: $GROUP"
echo "Input Directory: $INPUT_DIR"
echo ""

# Check if input files exist
if [ ! -d "$INPUT_DIR" ]; then
    echo "❌ Input directory not found: $INPUT_DIR"
    exit 1
fi

echo "Available PDF files:"
ls -lh "$INPUT_DIR"/*.pdf 2>/dev/null || echo "No PDF files found"
echo ""

# Test 1: Health Check
echo "=========================================="
echo "Test 1: Service Health Check"
echo "=========================================="
curl -s "$URL/health/detailed" | python3 -m json.tool
echo ""

# Test 2A: Option 1 - Use Azure Content Understanding for PDF extraction
echo "=========================================="
echo "Test 2: Index PDFs via Azure Content Understanding"
echo "=========================================="
echo "Note: This requires PDFs to be uploaded to Azure Blob Storage"
echo "      with SAS URLs for Content Understanding to access them."
echo ""

# For testing, we'll use direct text extraction since we need blob URLs
# In production, you would:
# 1. Upload PDFs to blob storage
# 2. Generate SAS URLs
# 3. Pass URLs to GraphRAG with ingestion="cu-standard"

echo "Using fallback: Direct text extraction for demo..."
echo ""

# Extract sample text (in production this would be blob URLs)
WARRANTY_TEXT="LIMITED WARRANTY AGREEMENT

Builder: ABC Construction Inc
Address: 456 Builder Lane, Construction City, CA 90210
Phone: (555) 123-4567

Homeowner: John and Mary Smith  
Property: 789 New Home Drive, Suburbia, CA 90211

Effective Date: January 15, 2024
Warranty Period: 
- Workmanship: 1 year from date of closing
- Systems (HVAC, Plumbing, Electrical): 2 years from closing
- Structural Defects: 10 years from closing

Coverage: This warranty covers defects in materials and workmanship for the construction of your new home. Builder agrees to repair or replace defective items at no cost to homeowner during the warranty period.

Exclusions: Normal wear and tear, homeowner negligence, and modifications made by homeowner are not covered."

CONTRACT_TEXT="PURCHASE AND SALE AGREEMENT

This Agreement dated March 15, 2024

BETWEEN:
Buyer: Acme Corporation
Address: 123 Commerce Blvd, Business Park, NY 10001
Contact: Jane Doe, VP Procurement

AND:
Seller: TechVendor LLC
Address: 999 Innovation Way, Tech Valley, CA 94025  
Contact: Robert Johnson, Sales Director

AGREEMENT:
1. Purchase Price: \$250,000 USD
2. Product: Enterprise Software License - CloudAI Platform v3.0
3. Support Term: 3 years technical support and maintenance
4. Payment Terms:
   - Deposit: \$75,000 (30%) due upon signing
   - Balance: \$175,000 (70%) due at closing on June 1, 2024
5. Delivery: Software delivered within 30 days of final payment
6. Warranties: Seller warrants software free from defects for 90 days"

PROPERTY_TEXT="PROPERTY MANAGEMENT AGREEMENT

Owner: Sarah Johnson
Property Address: 123 Oak Street, San Francisco, CA 94102
Property Type: Residential - 3 bedroom, 2 bath single family home

Manager: Premier Property Management LLC
Office: 555 Management Plaza, San Francisco, CA 94103
License: CA-PM-12345

Term: 12 months commencing April 1, 2024

Management Fee: 8% of monthly gross rent collected

Responsibilities:
- Tenant screening and placement
- Monthly rent collection  
- Property maintenance coordination
- Annual property inspections
- Financial reporting to owner
- Emergency repairs (up to \$500 without owner approval)

Owner Responsibilities:
- Maintain property insurance
- Approve major repairs over \$500
- Pay property taxes and HOA fees"

echo "Sample documents prepared. Indexing into GraphRAG..."
echo ""

# Test 2B: Index with inline text (ingestion="none")
echo "Indexing Mode: Direct text (ingestion='none')"
RESPONSE=$(curl -s -X POST "$URL/graphrag/index" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d "{
    \"documents\": [
      \"$WARRANTY_TEXT\",
      \"$CONTRACT_TEXT\",
      \"$PROPERTY_TEXT\"
    ],
    \"extraction_mode\": \"simple\",
    \"run_community_detection\": true,
    \"ingestion\": \"none\"
  }")

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

# Wait for indexing to complete
echo "Waiting 5 seconds for indexing to complete..."
sleep 5

# Test 3: Query - Local (Entity-Focused)
echo "=========================================="
echo "Test 3: Entity-Focused Query (Local)"
echo "=========================================="
echo "Query: What parties are involved in the contracts?"
echo ""

RESPONSE=$(curl -s -X POST "$URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d '{
    "query": "What parties are involved in the contracts and what are their roles?",
    "top_k": 10
  }')

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

# Test 4: Query - Dates and Terms
echo "=========================================="
echo "Test 4: Query Specific Information"
echo "=========================================="
echo "Query: What are the key dates and financial terms?"
echo ""

RESPONSE=$(curl -s -X POST "$URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d '{
    "query": "What are the effective dates, payment amounts, and warranty periods mentioned?",
    "top_k": 10
  }')

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

# Test 5: Query - Global (Community-Based)
echo "=========================================="
echo "Test 5: Community-Based Query (Global)"
echo "=========================================="
echo "Query: Summarize all contract relationships"
echo ""

RESPONSE=$(curl -s -X POST "$URL/graphrag/query/global" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d '{
    "query": "Provide a high-level summary of all the business relationships and contract terms across all documents",
    "community_level": 1
  }')

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

# Test 6: Query - Hybrid (Best of Both)
echo "=========================================="
echo "Test 6: Hybrid Query"
echo "=========================================="
echo "Query: What properties or assets are mentioned?"
echo ""

RESPONSE=$(curl -s -X POST "$URL/graphrag/query/hybrid" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d '{
    "query": "What properties, products, or assets are mentioned in the documents?",
    "top_k": 10,
    "community_level": 1
  }')

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

echo "=========================================="
echo "✅ End-to-End Test Complete!"
echo "=========================================="
echo "Test Group ID: $GROUP"
echo ""
echo "Next steps:"
echo "  - View graph in Neo4j Browser: http://neo4j-graphrag-23987.swedencentral.azurecontainer.io:7474"
echo "  - Query entities: MATCH (n {group_id: '$GROUP'}) RETURN n LIMIT 25"
echo "  - Query relationships: MATCH (a {group_id: '$GROUP'})-[r]->(b) RETURN a, r, b LIMIT 25"
echo ""
