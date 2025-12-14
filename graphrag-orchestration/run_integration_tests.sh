#!/bin/bash
# Stage 4: End-to-End Integration Tests
# Tests complete workflows across all services

set -e

echo "=================================================="
echo "Stage 4: End-to-End Integration Tests"
echo "=================================================="

# Configuration
GRAPHRAG_URL="${GRAPHRAG_URL:-http://localhost:8001}"
CONTENT_API_URL="${CONTENT_API_URL:-http://localhost:8000}"
TEST_GROUP="${TEST_GROUP:-test-group-integration}"

echo ""
echo "Configuration:"
echo "  GraphRAG URL: $GRAPHRAG_URL"
echo "  Content API URL: $CONTENT_API_URL"
echo "  Test Group: $TEST_GROUP"
echo ""

# Create test data directory
TEST_DIR="$(mktemp -d)"
echo "Test directory: $TEST_DIR"

# Helper function for API calls
call_api() {
    local method=$1
    local url=$2
    local data=$3
    
    if [ -n "$data" ]; then
        curl -s -w "\n%{http_code}" \
            -X "$method" \
            "$url" \
            -H "X-Group-ID: $TEST_GROUP" \
            -H "Content-Type: application/json" \
            -d "$data"
    else
        curl -s -w "\n%{http_code}" \
            -X "$method" \
            "$url" \
            -H "X-Group-ID: $TEST_GROUP"
    fi
}

extract_http_code() {
    echo "$1" | tail -n 1
}

extract_body() {
    echo "$1" | head -n -1
}

# Test 1: Schema-Based Workflow
echo ""
echo "=================================================="
echo "Test 1: Schema-Based Extraction Workflow"
echo "=================================================="

echo "Step 1: Create test schema..."
cat > "$TEST_DIR/test_schema.json" <<'EOF'
{
  "title": "ContractAnalysis",
  "type": "object",
  "properties": {
    "parties": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "role": {"type": "string"}
        }
      }
    },
    "effective_date": {"type": "string"},
    "key_terms": {
      "type": "array",
      "items": {"type": "string"}
    }
  }
}
EOF

echo "✅ Schema created"

echo ""
echo "Step 2: Index documents with schema conversion..."
RESPONSE=$(call_api POST "$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" '{
  "schema_prompt": "Extract contract parties, effective dates, and key terms from legal agreements",
  "documents": [
    "This Agreement is entered into on January 1, 2025, between Acme Corp (Buyer) and TechVendor Inc (Seller). Key terms include: payment within 30 days, warranty for 12 months, and exclusive territory rights."
  ],
  "extraction_mode": "schema",
  "ingestion": "none",
  "run_community_detection": false
}')

HTTP_CODE=$(extract_http_code "$RESPONSE")
BODY=$(extract_body "$RESPONSE")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Indexing successful"
    echo "$BODY" | python -m json.tool | head -20
else
    echo "❌ Indexing failed with code $HTTP_CODE"
    echo "$BODY"
fi

echo ""
echo "Step 3: Query the indexed data..."
sleep 2  # Allow indexing to complete

RESPONSE=$(call_api POST "$GRAPHRAG_URL/api/v1/graphrag/query/local" '{
  "query": "What are the key parties in the contract?",
  "top_k": 5
}')

HTTP_CODE=$(extract_http_code "$RESPONSE")
BODY=$(extract_body "$RESPONSE")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Query successful"
    echo "$BODY" | python -m json.tool | head -20
else
    echo "❌ Query failed with code $HTTP_CODE"
    echo "$BODY"
fi

# Test 2: Prompt-Based Quick Query
echo ""
echo "=================================================="
echo "Test 2: Prompt-Based Quick Query"
echo "=================================================="

echo "Indexing with natural language prompt..."
RESPONSE=$(call_api POST "$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" '{
  "schema_prompt": "Extract all people, their roles, organizations they work for, and any projects or products mentioned",
  "documents": [
    "Alice Johnson is the CEO of DataCorp. She leads the CloudAI project. Bob Smith, CTO of TechStart, collaborates with DataCorp on the CloudAI initiative. The project aims to deliver AI-powered analytics by Q2 2025."
  ],
  "extraction_mode": "schema",
  "ingestion": "none",
  "run_community_detection": false
}')

HTTP_CODE=$(extract_http_code "$RESPONSE")
BODY=$(extract_body "$RESPONSE")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Quick query indexing successful"
    STATS=$(echo "$BODY" | python -c "import sys, json; data=json.load(sys.stdin); print(f\"Nodes: {data['stats'].get('nodes_created', 0)}, Entities: {len(data['stats'].get('entity_types', []))}\")" 2>/dev/null || echo "Stats unavailable")
    echo "  $STATS"
else
    echo "❌ Quick query failed with code $HTTP_CODE"
    echo "$BODY"
fi

echo ""
echo "Querying quick query results..."
sleep 2

RESPONSE=$(call_api POST "$GRAPHRAG_URL/api/v1/graphrag/query/hybrid" '{
  "query": "Who are the key people and what do they work on?",
  "top_k": 10
}')

HTTP_CODE=$(extract_http_code "$RESPONSE")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Hybrid query successful"
else
    echo "⚠️  Hybrid query returned $HTTP_CODE"
fi

# Test 3: Multi-Tenant Isolation
echo ""
echo "=================================================="
echo "Test 3: Multi-Tenant Isolation"
echo "=================================================="

for GROUP in group-finance group-legal group-hr; do
    echo ""
    echo "Indexing for $GROUP..."
    
    RESPONSE=$(curl -s -w "\n%{http_code}" \
        -X POST "$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" \
        -H "X-Group-ID: $GROUP" \
        -H "Content-Type: application/json" \
        -d "{
            \"schema_prompt\": \"Extract entities\",
            \"documents\": [\"Confidential data for $GROUP department. Project Alpha managed by Team Leader.\"],
            \"ingestion\": \"none\",
            \"run_community_detection\": false
        }")
    
    HTTP_CODE=$(extract_http_code "$RESPONSE")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "  ✅ $GROUP indexed"
    else
        echo "  ❌ $GROUP failed with $HTTP_CODE"
    fi
done

echo ""
echo "Verifying isolation - querying each group..."
for GROUP in group-finance group-legal group-hr; do
    echo ""
    echo "Querying $GROUP..."
    
    RESPONSE=$(curl -s -w "\n%{http_code}" \
        -X POST "$GRAPHRAG_URL/api/v1/graphrag/query/local" \
        -H "X-Group-ID: $GROUP" \
        -H "Content-Type: application/json" \
        -d '{"query": "What data exists?", "top_k": 10}')
    
    HTTP_CODE=$(extract_http_code "$RESPONSE")
    BODY=$(extract_body "$RESPONSE")
    
    if [ "$HTTP_CODE" = "200" ]; then
        # Check that response contains group-specific data
        if echo "$BODY" | grep -q "$GROUP"; then
            echo "  ✅ $GROUP sees own data"
        else
            echo "  ⚠️  $GROUP response doesn't contain group identifier"
        fi
        
        # Check that it doesn't contain other groups' data
        OTHER_GROUPS=$(echo "group-finance group-legal group-hr" | sed "s/$GROUP//g")
        LEAK_FOUND=false
        for OTHER in $OTHER_GROUPS; do
            if echo "$BODY" | grep -q "$OTHER"; then
                echo "  ❌ $GROUP sees data from $OTHER - ISOLATION BREACH!"
                LEAK_FOUND=true
            fi
        done
        
        if [ "$LEAK_FOUND" = false ]; then
            echo "  ✅ No data leakage detected"
        fi
    else
        echo "  ❌ Query failed with $HTTP_CODE"
    fi
done

# Test 4: Community Detection
echo ""
echo "=================================================="
echo "Test 4: Community Detection & Global Search"
echo "=================================================="

echo "Indexing multiple documents with community detection..."
RESPONSE=$(call_api POST "$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" '{
  "schema_prompt": "Extract topics, themes, people, and organizations",
  "documents": [
    "The renewable energy sector is growing rapidly. Solar and wind power are leading technologies.",
    "Tech companies are investing heavily in AI research. Microsoft, Google, and OpenAI are major players.",
    "Climate change drives innovation in clean energy. Governments worldwide support green initiatives."
  ],
  "extraction_mode": "schema",
  "ingestion": "none",
  "run_community_detection": true
}')

HTTP_CODE=$(extract_http_code "$RESPONSE")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Documents indexed with community detection"
else
    echo "⚠️  Indexing returned $HTTP_CODE"
fi

echo ""
echo "Waiting for community detection to complete..."
sleep 10

echo ""
echo "Running global search query..."
RESPONSE=$(call_api POST "$GRAPHRAG_URL/api/v1/graphrag/query/global" '{
  "query": "What are the main themes across all documents?",
  "community_level": 0,
  "top_k": 5
}')

HTTP_CODE=$(extract_http_code "$RESPONSE")
BODY=$(extract_body "$RESPONSE")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Global search successful"
    echo "$BODY" | python -m json.tool | head -30
else
    echo "⚠️  Global search returned $HTTP_CODE"
    echo "$BODY"
fi

# Cleanup
echo ""
echo "=================================================="
echo "Cleanup"
echo "=================================================="
rm -rf "$TEST_DIR"
echo "✅ Test directory cleaned"

# Summary
echo ""
echo "=================================================="
echo "Stage 4 Complete - Integration Test Summary"
echo "=================================================="
echo ""
echo "Tests Run:"
echo "  ✓ Schema-based extraction workflow"
echo "  ✓ Prompt-based quick query"
echo "  ✓ Multi-tenant isolation"
echo "  ✓ Community detection & global search"
echo ""
echo "Manual verification recommended:"
echo "  - Check Neo4j for expected graph structure"
echo "  - Verify no cross-tenant data leaks"
echo "  - Test with real documents and schemas"
echo ""
echo "=================================================="
