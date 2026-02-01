#!/bin/bash
# Instant rollback to previous Container App revision
#
# Usage: 
#   ./scripts/rollback.sh                    # Rollback to previous revision
#   ./scripts/rollback.sh api-v2-stable      # Rollback to specific revision
#   ./scripts/rollback.sh --list             # List available revisions
#
# Target: <60 seconds rollback time

set -e

# Configuration
API_APP_NAME="${API_APP_NAME:-graphrag-api}"
WORKER_APP_NAME="${WORKER_APP_NAME:-graphrag-worker}"
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-graphrag-feature}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================"
echo "GraphRAG Rollback Tool"
echo "======================================"
echo ""

# Check Azure CLI
if ! command -v az &> /dev/null; then
    echo -e "${RED}Error: Azure CLI not found${NC}"
    exit 1
fi

# Check login
if ! az account show &> /dev/null; then
    echo -e "${YELLOW}Not logged in to Azure. Running 'az login'...${NC}"
    az login
fi

# List revisions mode
if [[ "$1" == "--list" ]]; then
    echo "API Container Revisions:"
    az containerapp revision list \
        --name "$API_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[].{Name:name, Active:properties.active, Traffic:properties.trafficWeight, Created:properties.createdTime}" \
        -o table
    
    echo ""
    echo "Worker Container Revisions:"
    az containerapp revision list \
        --name "$WORKER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[].{Name:name, Active:properties.active, Traffic:properties.trafficWeight, Created:properties.createdTime}" \
        -o table
    
    exit 0
fi

# Determine target revision
if [[ -n "$1" ]]; then
    TARGET_REVISION="$1"
    echo "Target revision: $TARGET_REVISION"
else
    # Find previous active revision (not current)
    echo "Finding previous revision..."
    
    CURRENT_REVISION=$(az containerapp revision list \
        --name "$API_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "[?properties.trafficWeight > \`0\`].name | [0]" -o tsv)
    
    # Get second most recent active revision
    TARGET_REVISION=$(az containerapp revision list \
        --name "$API_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "sort_by([?properties.active], &properties.createdTime) | reverse(@) | [1].name" -o tsv)
    
    if [[ -z "$TARGET_REVISION" ]]; then
        echo -e "${RED}Error: No previous revision found${NC}"
        echo "Use --list to see available revisions"
        exit 1
    fi
    
    echo "Current revision: $CURRENT_REVISION"
    echo "Rollback target:  $TARGET_REVISION"
fi

echo ""

# Confirm rollback
read -p "Proceed with rollback? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Rollback cancelled"
    exit 0
fi

# Start timer
START_TIME=$(date +%s)

echo ""
echo "🔄 Starting rollback..."
echo ""

# Step 1: Activate target revision if not active
echo "1. Activating revision $TARGET_REVISION..."
az containerapp revision activate \
    --name "$API_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --revision "$TARGET_REVISION" 2>/dev/null || true

# Step 2: Shift all traffic to target revision
echo "2. Shifting 100% traffic to $TARGET_REVISION..."
az containerapp ingress traffic set \
    --name "$API_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --revision-weight "$TARGET_REVISION=100"

# Step 3: Verify health
echo "3. Verifying health..."
API_URL=$(az containerapp show \
    --name "$API_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

for i in {1..5}; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$API_URL/health" 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo -e "   ${GREEN}✓ Health check passed${NC}"
        break
    fi
    echo "   Attempt $i: HTTP $HTTP_CODE, retrying..."
    sleep 2
done

if [[ "$HTTP_CODE" != "200" ]]; then
    echo -e "${YELLOW}⚠ Health check did not pass, but traffic has been shifted${NC}"
    echo "  Check https://$API_URL/health manually"
fi

# Calculate time
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "======================================"
echo -e "${GREEN}✅ Rollback complete in ${DURATION}s${NC}"
echo "======================================"
echo ""
echo "API now serving from: $TARGET_REVISION"
echo "URL: https://$API_URL"
echo ""

# Show current state
echo "Current traffic distribution:"
az containerapp ingress traffic show \
    --name "$API_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    -o table
