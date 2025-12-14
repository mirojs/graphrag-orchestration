#!/bin/bash
# Test DRIFT Multi-Step Reasoning Endpoint

set -e

echo "🧠 Testing GraphRAG DRIFT Multi-Step Reasoning"
echo "=============================================="

SERVICE_URL="${GRAPHRAG_SERVICE_URL:-http://localhost:8001}"
GROUP_ID="${TEST_GROUP_ID:-test-group-001}"

echo "Service URL: $SERVICE_URL"
echo "Group ID: $GROUP_ID"
echo ""

# Test 1: Health check
echo "1️⃣  Health Check..."
curl -s "$SERVICE_URL/health" | jq '.'
echo ""

# Test 2: Simple DRIFT query
echo "2️⃣  Simple DRIFT Query..."
curl -s -X POST "$SERVICE_URL/graphrag/query/drift" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "What are the main themes in the documents?",
    "top_k": 5,
    "reduce": true
  }' | jq '.'
echo ""

# Test 3: Complex multi-step query
echo "3️⃣  Complex Multi-Step Query..."
curl -s -X POST "$SERVICE_URL/graphrag/query/drift" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "Compare the warranty terms across different documents and identify any inconsistencies",
    "top_k": 10,
    "reduce": true
  }' | jq '.'
echo ""

# Test 4: DRIFT with conversation history
echo "4️⃣  DRIFT with Conversation History..."
curl -s -X POST "$SERVICE_URL/graphrag/query/drift" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d '{
    "query": "What are the key differences?",
    "conversation_history": [
      {"role": "user", "content": "Tell me about the payment terms"},
      {"role": "assistant", "content": "The payment terms vary..."}
    ],
    "top_k": 5,
    "reduce": true
  }' | jq '.'
echo ""

# Test 5: Compare all three query modes
echo "5️⃣  Comparing Query Modes for Same Question..."
TEST_QUERY="What entities are mentioned in the documents?"

echo "  📍 LOCAL Search..."
curl -s -X POST "$SERVICE_URL/graphrag/query/local" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d "{\"query\": \"$TEST_QUERY\", \"top_k\": 5}" | jq '.mode, .answer' || echo "Failed"

echo ""
echo "  🌍 GLOBAL Search..."
curl -s -X POST "$SERVICE_URL/graphrag/query/global" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d "{\"query\": \"$TEST_QUERY\", \"top_k\": 5}" | jq '.mode, .answer' || echo "Failed"

echo ""
echo "  🔄 HYBRID Search..."
curl -s -X POST "$SERVICE_URL/graphrag/query/hybrid" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d "{\"query\": \"$TEST_QUERY\", \"top_k\": 5}" | jq '.mode, .answer' || echo "Failed"

echo ""
echo "  🧠 DRIFT Search (Multi-Step)..."
curl -s -X POST "$SERVICE_URL/graphrag/query/drift" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: $GROUP_ID" \
  -d "{\"query\": \"$TEST_QUERY\", \"top_k\": 5, \"reduce\": true}" | jq '.mode, .answer, .metadata' || echo "Failed"

echo ""
echo "✅ DRIFT Testing Complete!"
echo ""
echo "💡 Use Case Recommendations:"
echo "   • LOCAL: 'Tell me about Company X' (entity-focused)"
echo "   • GLOBAL: 'What are the main themes?' (thematic)"
echo "   • HYBRID: 'Find documents about payment terms' (semantic + structural)"
echo "   • DRIFT: 'Compare warranty terms and identify outliers' (complex, multi-step)"
