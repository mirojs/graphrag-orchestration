#!/bin/bash
# Stage 3: Deployed Container Tests
# Tests the service deployed to Azure Container Apps

set -e

echo "=================================================="
echo "Stage 3: Deployed Container Tests"
echo "=================================================="

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-graphrag-orchestration}"

if [ -z "$RESOURCE_GROUP" ]; then
    echo "❌ RESOURCE_GROUP environment variable not set"
    echo "Usage: RESOURCE_GROUP=<rg-name> ./run_deployed_tests.sh"
    exit 1
fi

# Check prerequisites
echo ""
echo "Checking prerequisites..."
if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI not found"
    exit 1
fi

# Check if logged in
if ! az account show &> /dev/null; then
    echo "❌ Not logged in to Azure"
    echo "Run: az login"
    exit 1
fi

echo "✅ Prerequisites OK"

# Get container app URL
echo ""
echo "=================================================="
echo "1. Getting Container App URL"
echo "=================================================="
GRAPHRAG_URL=$(az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn \
    -o tsv 2>/dev/null) || {
    echo "❌ Failed to get container app URL"
    echo "Check that the container app exists:"
    echo "  az containerapp list --resource-group $RESOURCE_GROUP -o table"
    exit 1
}

if [ -z "$GRAPHRAG_URL" ]; then
    echo "❌ Container app URL is empty"
    exit 1
fi

GRAPHRAG_URL="https://$GRAPHRAG_URL"
echo "✅ Service URL: $GRAPHRAG_URL"

# Check container app status
echo ""
echo "=================================================="
echo "2. Container App Status"
echo "=================================================="
az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "{name:name,status:properties.runningStatus,replicas:properties.template.scale.maxReplicas,revision:properties.latestRevisionName}" \
    -o table

# Health checks
echo ""
echo "=================================================="
echo "3. Health Checks"
echo "=================================================="

echo "Basic health check..."
HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" "$GRAPHRAG_URL/health") || {
    echo "❌ Health check failed"
    exit 1
}

HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n 1)
HEALTH_BODY=$(echo "$HEALTH_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Health check returned $HTTP_CODE"
    echo "$HEALTH_BODY"
    exit 1
fi

echo "✅ Basic health check passed"
echo "$HEALTH_BODY"

echo ""
echo "Detailed health check..."
curl -s "$GRAPHRAG_URL/api/v1/graphrag/health" | python -m json.tool || {
    echo "⚠️  Detailed health check failed"
}

# Test with managed identity
echo ""
echo "=================================================="
echo "4. Managed Identity Test"
echo "=================================================="

echo "Getting Azure AD token..."
TOKEN=$(az account get-access-token \
    --resource https://cognitiveservices.azure.com \
    --query accessToken \
    -o tsv) || {
    echo "❌ Failed to get token"
    exit 1
}

echo "✅ Token obtained"

# Test basic indexing with managed identity
echo ""
echo "Testing index-from-prompt endpoint..."
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Group-ID: test-group-deployed" \
    -H "Content-Type: application/json" \
    -d '{
        "schema_prompt": "Extract people and organizations",
        "documents": ["Microsoft was founded by Bill Gates and Paul Allen."],
        "ingestion": "cu-standard",
        "run_community_detection": false
    }')

HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
RESPONSE_BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Indexing endpoint works"
    echo "$RESPONSE_BODY" | python -m json.tool
else
    echo "⚠️  Indexing returned $HTTP_CODE"
    echo "$RESPONSE_BODY"
fi

# Check container logs
echo ""
echo "=================================================="
echo "5. Container Logs (last 50 lines)"
echo "=================================================="
az containerapp logs show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --tail 50 || {
    echo "⚠️  Could not fetch logs"
}

# Check environment variables
echo ""
echo "=================================================="
echo "6. Environment Configuration"
echo "=================================================="
echo "Checking configured environment variables..."
az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.template.containers[0].env[?!contains(name, 'SECRET') && !contains(name, 'KEY')].{Name:name,Value:value}" \
    -o table

# Check revisions
echo ""
echo "=================================================="
echo "7. Revision History"
echo "=================================================="
az containerapp revision list \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "[].{Revision:name,Active:properties.active,Created:properties.createdTime,Replicas:properties.replicas}" \
    -o table

echo ""
echo "=================================================="
echo "Stage 3 Complete!"
echo "=================================================="
echo ""
echo "Service URL: $GRAPHRAG_URL"
echo ""
echo "Next steps:"
echo "  - Run Stage 4 (Integration Tests): ./run_integration_tests.sh"
echo "  - Monitor logs: az containerapp logs tail -n $CONTAINER_APP_NAME -g $RESOURCE_GROUP --follow"
echo "  - View metrics: az monitor metrics list --resource <resource-id>"
echo ""
echo "Debugging commands:"
echo "  az containerapp exec -n $CONTAINER_APP_NAME -g $RESOURCE_GROUP --command /bin/bash"
echo "  az containerapp logs show -n $CONTAINER_APP_NAME -g $RESOURCE_GROUP --follow"
echo "=================================================="
