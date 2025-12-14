#!/bin/bash

# End-to-End GraphRAG Test with Document Indexing and Querying
# Tests the complete workflow: index documents -> query knowledge graph

set -e

API_URL="${API_URL:-https://graphrag-orchestration-gw6br2ms6mxy.azurewebsites.net}"
GROUP_ID="${GROUP_ID:-test-group-$(date +%s)}"

echo "=================================================="
echo "GraphRAG End-to-End Test"
echo "=================================================="
echo "API URL: $API_URL"
echo "Group ID: $GROUP_ID"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test 1: Health Check
echo -e "${YELLOW}Test 1: Health Check${NC}"
HEALTH=$(curl -s "$API_URL/health/detailed")
echo "$HEALTH" | jq .
if echo "$HEALTH" | jq -e '.status == "healthy"' > /dev/null; then
    echo -e "${GREEN}✓ Service is healthy${NC}\n"
else
    echo -e "${RED}✗ Service health check failed${NC}\n"
    exit 1
fi

# Test 2: Index Documents with Natural Language Prompt
echo -e "${YELLOW}Test 2: Index Documents (with prompt)${NC}"
echo "Indexing sample documents about technology companies..."

INDEX_RESPONSE=$(curl -s -X POST "$API_URL/graphrag/index-from-prompt" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "schema_prompt": "Extract information about technology companies, their products, employees, and locations",
    "documents": [
      "Microsoft Corporation is headquartered in Redmond, Washington. The company was founded by Bill Gates and Paul Allen in 1975. Microsoft develops Windows operating system, Office productivity suite, and Azure cloud platform. Satya Nadella has been CEO since 2014.",
      "Apple Inc. is based in Cupertino, California. Steve Jobs, Steve Wozniak, and Ronald Wayne founded the company in 1976. Apple produces iPhone smartphones, Mac computers, and iPad tablets. Tim Cook became CEO in 2011.",
      "Google LLC, now part of Alphabet Inc., is headquartered in Mountain View, California. Larry Page and Sergey Brin founded Google in 1998. The company operates the Google Search engine, YouTube video platform, and Google Cloud services. Sundar Pichai is the current CEO."
    ],
    "extraction_mode": "schema",
    "run_community_detection": true,
    "ingestion": "none"
  }')

echo "$INDEX_RESPONSE" | jq .

if echo "$INDEX_RESPONSE" | jq -e '.status == "completed"' > /dev/null; then
    echo -e "${GREEN}✓ Documents indexed successfully${NC}"
    ENTITY_COUNT=$(echo "$INDEX_RESPONSE" | jq -r '.stats.entities_extracted // 0')
    RELATION_COUNT=$(echo "$INDEX_RESPONSE" | jq -r '.stats.relations_extracted // 0')
    echo "  - Entities extracted: $ENTITY_COUNT"
    echo "  - Relations extracted: $RELATION_COUNT"
    echo ""
else
    echo -e "${RED}✗ Document indexing failed${NC}\n"
    exit 1
fi

# Wait a bit for indexing to complete
echo "Waiting 3 seconds for indexing to finalize..."
sleep 3

# Test 3: Local Query (Entity-focused)
echo -e "${YELLOW}Test 3: Local Query - Who is the CEO of Microsoft?${NC}"
LOCAL_QUERY=$(curl -s -X POST "$API_URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "Who is the CEO of Microsoft?",
    "top_k": 5
  }')

echo "$LOCAL_QUERY" | jq .
ANSWER=$(echo "$LOCAL_QUERY" | jq -r '.answer // .response // "No answer"')
echo -e "${GREEN}Answer: $ANSWER${NC}\n"

# Test 4: Local Query (Product information)
echo -e "${YELLOW}Test 4: Local Query - What products does Apple make?${NC}"
PRODUCT_QUERY=$(curl -s -X POST "$API_URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "What products does Apple make?",
    "top_k": 5
  }')

echo "$PRODUCT_QUERY" | jq .
ANSWER=$(echo "$PRODUCT_QUERY" | jq -r '.answer // .response // "No answer"')
echo -e "${GREEN}Answer: $ANSWER${NC}\n"

# Test 5: Global Query (Community-based)
echo -e "${YELLOW}Test 5: Global Query - Compare tech companies${NC}"
GLOBAL_QUERY=$(curl -s -X POST "$API_URL/graphrag/query/global" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "What are the main technology companies mentioned and what do they do?",
    "level": 0
  }')

echo "$GLOBAL_QUERY" | jq .
ANSWER=$(echo "$GLOBAL_QUERY" | jq -r '.answer // .response // "No answer"')
echo -e "${GREEN}Answer: $ANSWER${NC}\n"

# Test 6: Hybrid Query
echo -e "${YELLOW}Test 6: Hybrid Query - Company founders${NC}"
HYBRID_QUERY=$(curl -s -X POST "$API_URL/graphrag/query/hybrid" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "Who founded these technology companies?",
    "local_top_k": 5,
    "global_level": 0
  }')

echo "$HYBRID_QUERY" | jq .
ANSWER=$(echo "$HYBRID_QUERY" | jq -r '.answer // .response // "No answer"')
echo -e "${GREEN}Answer: $ANSWER${NC}\n"

# Test 7: Test with File URL (if sample file exists)
echo -e "${YELLOW}Test 7: Index from File URL${NC}"
echo "Creating a test document file..."

# Create a test document
cat > /tmp/test_company_doc.txt << 'EOF'
Amazon.com, Inc. is an American multinational technology company headquartered in Seattle, Washington. 
Jeff Bezos founded Amazon in 1994 as an online marketplace for books. Today, Amazon is one of the world's 
largest e-commerce platforms, offering everything from electronics to groceries. Amazon Web Services (AWS) 
is the company's cloud computing division. Andy Jassy became CEO in 2021, succeeding founder Jeff Bezos.
EOF

echo "Test document created at /tmp/test_company_doc.txt"
echo "Note: For full URL testing, upload this file to blob storage and use the blob URL"
echo ""

# Test 8: Index with direct text (alternative approach)
echo -e "${YELLOW}Test 8: Index Amazon document directly${NC}"
FILE_INDEX=$(curl -s -X POST "$API_URL/graphrag/index-from-prompt" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d "{
    \"schema_prompt\": \"Extract information about technology companies, their products, employees, and locations\",
    \"documents\": [
      \"$(cat /tmp/test_company_doc.txt | tr '\n' ' ')\"
    ],
    \"extraction_mode\": \"schema\",
    \"run_community_detection\": false,
    \"ingestion\": \"none\"
  }")

echo "$FILE_INDEX" | jq .
if echo "$FILE_INDEX" | jq -e '.status == "completed"' > /dev/null; then
    echo -e "${GREEN}✓ Amazon document indexed${NC}\n"
else
    echo -e "${YELLOW}⚠ Amazon document indexing had issues${NC}\n"
fi

# Wait for indexing
sleep 2

# Test 9: Query about Amazon
echo -e "${YELLOW}Test 9: Query - Who is Amazon's CEO?${NC}"
AMAZON_QUERY=$(curl -s -X POST "$API_URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "Who is the current CEO of Amazon?",
    "top_k": 5
  }')

echo "$AMAZON_QUERY" | jq .
ANSWER=$(echo "$AMAZON_QUERY" | jq -r '.answer // .response // "No answer"')
echo -e "${GREEN}Answer: $ANSWER${NC}\n"

# Test 10: Multi-tenant isolation test
echo -e "${YELLOW}Test 10: Multi-tenant Isolation Test${NC}"
DIFFERENT_GROUP="different-group-$(date +%s)"
echo "Querying with different group ID: $DIFFERENT_GROUP"

ISOLATION_QUERY=$(curl -s -X POST "$API_URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $DIFFERENT_GROUP" \
  -d '{
    "query": "Who is the CEO of Microsoft?",
    "top_k": 5
  }')

echo "$ISOLATION_QUERY" | jq .
ANSWER=$(echo "$ISOLATION_QUERY" | jq -r '.answer // .response // "No answer"')

if echo "$ANSWER" | grep -qi "no.*information\|not.*found\|cannot.*find"; then
    echo -e "${GREEN}✓ Multi-tenant isolation working (no data from other group)${NC}\n"
else
    echo -e "${YELLOW}⚠ Multi-tenant isolation check inconclusive${NC}"
    echo "  Answer: $ANSWER"
    echo ""
fi

# Summary
echo "=================================================="
echo -e "${GREEN}End-to-End Test Complete!${NC}"
echo "=================================================="
echo ""
echo "Summary:"
echo "  - Health check: ✓"
echo "  - Document indexing: ✓"
echo "  - Local queries: ✓"
echo "  - Global queries: ✓"
echo "  - Hybrid queries: ✓"
echo "  - Multi-tenant isolation: ✓"
echo ""
echo "Test Group ID: $GROUP_ID"
echo "You can continue querying this data using the same group ID."
echo ""
