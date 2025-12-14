#!/bin/bash
# Simple GraphRAG Integration Test

set -e

URL="https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io"
GROUP="test-$(date +%s)"

echo "=========================================="
echo "GraphRAG Integration Test"
echo "=========================================="
echo "Service: $URL"
echo "Group ID: $GROUP"
echo ""

# Test 1: Health Check
echo "Test 1: Health Check"
echo "--------------------"
curl -s "$URL/health/detailed" | python3 -m json.tool
echo ""

# Test 2: Index Sample Data
echo "Test 2: Index Sample Contract Data"
echo "-----------------------------------"
curl -X POST "$URL/graphrag/index" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d '{
    "documents": [
      "Microsoft Corporation, headquartered in Redmond, Washington, entered into a partnership agreement with OpenAI on July 22, 2019. The agreement involves a $1 billion investment and exclusive cloud computing partnership.",
      "Apple Inc., based in Cupertino, California, announced its collaboration with TSMC for advanced chip manufacturing. Tim Cook serves as CEO of Apple."
    ],
    "extraction_mode": "simple",
    "run_community_detection": false,
    "ingestion": "none"
  }' | python3 -m json.tool
echo ""

# Test 3: Query Local (Entity-Focused)
echo "Test 3: Query - Entity Focused (Local)"
echo "---------------------------------------"
curl -X POST "$URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d '{
    "query": "What companies are mentioned and where are they located?",
    "top_k": 5
  }' | python3 -m json.tool
echo ""

# Test 4: Query Global (Community-Based)
echo "Test 4: Query - Community Based (Global)"
echo "-----------------------------------------"
curl -X POST "$URL/graphrag/query/global" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP" \
  -d '{
    "query": "Summarize the business relationships and partnerships",
    "community_level": 1
  }' | python3 -m json.tool
echo ""

echo "=========================================="
echo "All tests completed!"
echo "=========================================="
