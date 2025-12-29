#!/bin/bash
# DRIFT Debug Logging Test Script
# Purpose: Enable debug logging and test DRIFT queries
# Date: 2025-12-28

set -e

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}DRIFT Debug Logging Test Script${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Check if running on host
if ! command -v curl &> /dev/null; then
    echo -e "${YELLOW}⚠ curl not found. Please run this from a system with curl installed.${NC}"
    exit 1
fi

# Configuration
CONTAINER_URL="${CONTAINER_URL:-https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io}"
GROUP_MISSING="drift-missing-1766862853"
GROUP_OK="drift-ok-1766862426"

echo -e "${YELLOW}1. Test Setup${NC}"
echo "   Container URL: $CONTAINER_URL"
echo "   Test Group (missing communities): $GROUP_MISSING"
echo "   Test Group (with communities): $GROUP_OK"
echo ""

# Test 1: Missing communities (should return 422)
echo -e "${YELLOW}2. Test A: Group without communities (expect 422)${NC}"
echo "   Query: 'What is the notice period?'"
echo "   Command:"
echo "   curl -sS -X POST \"$CONTAINER_URL/graphrag/v3/query/drift\" \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -H \"X-Group-ID: $GROUP_MISSING\" \\"
echo "     -d '{\"query\":\"What is the notice period?\"}'"
echo ""

echo -e "${GREEN}Testing...${NC}"
RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST "$CONTAINER_URL/graphrag/v3/query/drift" \
  -H 'Content-Type: application/json' \
  -H "X-Group-ID: $GROUP_MISSING" \
  -d '{"query":"What is the notice period?"}')

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

echo "   HTTP Status: $HTTP_CODE"
if [ "$HTTP_CODE" = "422" ]; then
    echo -e "   ${GREEN}✓ Expected 422 received${NC}"
else
    echo -e "   ${YELLOW}⚠ Expected 422, got $HTTP_CODE${NC}"
fi
echo "   Response: $BODY" | head -c 200
echo "..."
echo ""

# Test 2: Group with communities (should return 200)
echo -e "${YELLOW}3. Test B: Group with communities (expect 200)${NC}"
echo "   Query: 'What is the notice period?'"
echo "   Expected: Answer with sources (or debug logs showing why empty)"
echo ""
echo -e "${GREEN}Testing...${NC}"

RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST "$CONTAINER_URL/graphrag/v3/query/drift" \
  -H 'Content-Type: application/json' \
  -H "X-Group-ID: $GROUP_OK" \
  -d '{"query":"What is the notice period?"}')

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

echo "   HTTP Status: $HTTP_CODE"
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "   ${GREEN}✓ Expected 200 received${NC}"
else
    echo -e "   ${YELLOW}⚠ Expected 200, got $HTTP_CODE${NC}"
fi

echo "   Response:"
echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
echo ""

# Test 3: Stats check
echo -e "${YELLOW}4. Test C: Verify group data exists${NC}"
echo "   Endpoint: /graphrag/v3/stats/$GROUP_OK"
echo ""
echo -e "${GREEN}Testing...${NC}"

STATS=$(curl -sS "$CONTAINER_URL/graphrag/v3/stats/$GROUP_OK" \
  -H "X-Group-ID: $GROUP_OK" | jq '.')

echo "   Stats:"
echo "$STATS"
echo ""

# Enable debug logging instructions
echo -e "${YELLOW}5. Enable Debug Logging for Next Test${NC}"
echo ""
echo "To enable debug logging, set these environment variables in your deployment:"
echo ""
echo -e "   ${BLUE}export V3_DRIFT_DEBUG_LOGGING=true${NC}"
echo -e "   ${BLUE}export V3_DRIFT_DEBUG_GROUP_ID=$GROUP_OK${NC}"
echo ""
echo "Then rerun Test B to see detailed debug output in container logs"
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Complete${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Review test results above"
echo "2. If Test B shows 'Not specified' with empty sources:"
echo "   a. Enable debug logging (see instructions above)"
echo "   b. Rerun Test B"
echo "   c. Check container logs for [DEBUG] messages"
echo "   d. Look for why sources are empty or content not found"
echo ""
