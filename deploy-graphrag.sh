#!/bin/bash
# Reliable GraphRAG Deployment Script
# Based on proven docker-build.sh pattern from dev/pro environment
# Supports both manual config and azd environment integration

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/graphrag-orchestration"

# Helper function to get environment value from azd or fallback to default
get_env_value_or_default() {
    local key="$1"
    local default="$2"
    local required="${3:-false}"

    local value
    # Try azd first if available
    if command -v azd &>/dev/null; then
        value=$(azd env get-value "$key" 2>/dev/null || echo "")
    fi
    
    # Fallback to environment variable
    if [ -z "$value" ]; then
        value="${!key}"
    fi
    
    # Fallback to default
    if [ -z "$value" ]; then
        value="$default"
    fi

    if [ -z "$value" ] && [ "$required" = "true" ]; then
        echo "❌ Required environment key '$key' not found." >&2
        echo "   Set it via: export $key=<value> or azd env set $key <value>" >&2
        exit 1
    fi

    echo "$value"
}

# Configuration
AZURE_SUBSCRIPTION_ID=$(get_env_value_or_default "AZURE_SUBSCRIPTION_ID" "" false)
AZURE_RESOURCE_GROUP=$(get_env_value_or_default "AZURE_RESOURCE_GROUP" "rg-graphrag-feature" false)
AZURE_LOCATION=$(get_env_value_or_default "AZURE_LOCATION" "swedencentral" false)
CONTAINER_REGISTRY_NAME=$(get_env_value_or_default "CONTAINER_REGISTRY_NAME" "graphragacr12153" true)
CONTAINER_APP_NAME=$(get_env_value_or_default "CONTAINER_APP_NAME" "graphrag-orchestration" false)
CONTAINER_APP_ENVIRONMENT=$(get_env_value_or_default "CONTAINER_APP_ENVIRONMENT" "graphrag-env" false)
AZURE_ENV_IMAGETAG=$(get_env_value_or_default "AZURE_ENV_IMAGETAG" "latest" false)
CONTAINER_APP_USER_IDENTITY_ID=$(get_env_value_or_default "CONTAINER_APP_USER_IDENTITY_ID" "" false)

# Neo4j Configuration
NEO4J_CONTAINER_NAME="neo4j-graphrag"
STORAGE_ACCOUNT=$(get_env_value_or_default "STORAGE_ACCOUNT_NAME" "neo4jstorage21224" false)
NEO4J_PASSWORD=$(get_env_value_or_default "NEO4J_PASSWORD" "" false)

# Docker cleanup control (default: enabled for deployment)
DOCKER_CLEANUP_ENABLED=${DOCKER_CLEANUP_ENABLED:-true}

echo "=================================================="
echo "GraphRAG Deployment Configuration"
echo "=================================================="
echo "Resource Group:       $AZURE_RESOURCE_GROUP"
echo "Location:             $AZURE_LOCATION"
echo "Container Registry:   $CONTAINER_REGISTRY_NAME"
echo "Container App:        $CONTAINER_APP_NAME"
echo "Image Tag:            $AZURE_ENV_IMAGETAG"
echo "Docker Cleanup:       $DOCKER_CLEANUP_ENABLED"
echo "=================================================="
echo ""

# Ensure Azure login
echo "🔐 Checking Azure login status..."
if ! az account show --only-show-errors &>/dev/null; then
    echo "No active Azure session found. Logging in..."
    az login --only-show-errors
    if [ -n "$AZURE_SUBSCRIPTION_ID" ]; then
        az account set --subscription "$AZURE_SUBSCRIPTION_ID"
    fi
fi

CURRENT_SUBSCRIPTION=$(az account show --query name -o tsv)
echo "✅ Logged in to Azure subscription: $CURRENT_SUBSCRIPTION"
echo ""

# Get ACR credentials
echo "📦 Retrieving ACR credentials..."
ACR_SERVER=$(az acr show \
    --name "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query loginServer -o tsv)

if [ -z "$ACR_SERVER" ]; then
    echo "❌ Failed to retrieve ACR server. Check if ACR exists: $CONTAINER_REGISTRY_NAME"
    exit 1
fi

echo "✅ ACR Endpoint: $ACR_SERVER"

# Login to ACR
echo "🔐 Logging into Azure Container Registry..."
az acr login \
    --name "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP"
echo ""

# Build and push Docker image
echo "=================================================="
echo "🐳 Building and Pushing Docker Image"
echo "=================================================="

IMAGE_NAME="graphrag-orchestration"
IMAGE_URI="$ACR_SERVER/$IMAGE_NAME:$AZURE_ENV_IMAGETAG"

echo "Image URI: $IMAGE_URI"
echo "Build Context: $APP_DIR"
echo ""

echo "⏳ Building image (this may take 2-3 minutes)..."
docker build "$APP_DIR" \
    --no-cache \
    -t "$IMAGE_URI" \
    --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --build-arg VERSION="$AZURE_ENV_IMAGETAG"

echo ""
echo "⏳ Pushing image to ACR..."
docker push "$IMAGE_URI"

echo "✅ Image built and pushed: $IMAGE_URI"
echo ""

# Update Container App
echo "=================================================="
echo "🚀 Updating Container App"
echo "=================================================="

# Check if Container App exists
CONTAINER_APP_EXISTS=$(az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query name -o tsv 2>/dev/null || echo "")

if [ -z "$CONTAINER_APP_EXISTS" ]; then
    echo "❌ Container App '$CONTAINER_APP_NAME' not found in resource group '$AZURE_RESOURCE_GROUP'"
    echo "   Please create it first using the infrastructure deployment (azd up or bicep)."
    exit 1
fi

echo "✅ Container App found: $CONTAINER_APP_NAME"
echo ""

# Set registry authentication (using managed identity if available)
if [ -n "$CONTAINER_APP_USER_IDENTITY_ID" ]; then
    echo "⏳ Configuring ACR authentication with managed identity..."
    az containerapp registry set \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --server "$ACR_SERVER" \
        --identity "$CONTAINER_APP_USER_IDENTITY_ID" \
        --only-show-errors
    echo "✅ Registry authentication configured (managed identity)"
else
    echo "⚠️  No managed identity ID provided. Ensure ACR admin credentials are enabled."
fi

# Update container app with new image
echo "⏳ Updating Container App with new image..."
REFRESH_TIMESTAMP=$(date +%Y%m%d%H%M%S)

az containerapp update \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --image "$IMAGE_URI" \
    --set-env-vars REFRESH_TIMESTAMP="$REFRESH_TIMESTAMP" \
    --only-show-errors

echo "✅ Container App updated successfully"
echo ""

# Get Container App endpoint
CONTAINER_APP_FQDN=$(az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

if [ -n "$CONTAINER_APP_FQDN" ]; then
    echo "🌐 Application URL: https://$CONTAINER_APP_FQDN"
    echo "   Swagger UI:      https://$CONTAINER_APP_FQDN/docs"
    echo "   Health Check:    https://$CONTAINER_APP_FQDN/health"
fi
echo ""

# Docker cleanup
if [ "$DOCKER_CLEANUP_ENABLED" = "true" ]; then
    echo "=================================================="
    echo "🧹 Cleaning up Docker resources"
    echo "=================================================="
    echo "Removing dangling images and build cache..."
    
    # Comprehensive cleanup to free disk space
    docker system prune -a -f --volumes 2>/dev/null || {
        echo "⚠️  Docker cleanup partially failed (this is usually safe to ignore)"
    }
    
    echo "✅ Docker cleanup complete"
    echo ""
fi

# Neo4j health check
echo "=================================================="
echo "🔍 Neo4j Health Check"
echo "=================================================="

NEO4J_STATE=$(az container show \
    --name "$NEO4J_CONTAINER_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query instanceView.state -o tsv 2>/dev/null || echo "NotFound")

if [ "$NEO4J_STATE" = "Running" ]; then
    NEO4J_FQDN=$(az container show \
        --name "$NEO4J_CONTAINER_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query ipAddress.fqdn -o tsv)
    echo "✅ Neo4j is running"
    echo "   FQDN: $NEO4J_FQDN"
    echo "   Bolt: bolt://$NEO4J_FQDN:7687"
    echo "   HTTP: http://$NEO4J_FQDN:7474"
elif [ "$NEO4J_STATE" = "NotFound" ]; then
    echo "⚠️  Neo4j container not found. You may need to deploy it separately."
    echo "   Use: ./graphrag-orchestration/deploy-simple.sh"
else
    echo "⚠️  Neo4j state: $NEO4J_STATE (not Running)"
    echo "   Check container logs for issues"
fi
echo ""

# Final summary
echo "=================================================="
echo "✅ Deployment Complete!"
echo "=================================================="
echo ""
echo "📋 Summary:"
echo "  • Image:     $IMAGE_URI"
echo "  • App URL:   https://$CONTAINER_APP_FQDN"
echo "  • Timestamp: $REFRESH_TIMESTAMP"
echo ""
echo "🔧 Next steps:"
echo "  1. Test health endpoint:    curl https://$CONTAINER_APP_FQDN/health"
echo "  2. View Swagger docs:       open https://$CONTAINER_APP_FQDN/docs"
echo "  3. Check application logs:  az containerapp logs show -n $CONTAINER_APP_NAME -g $AZURE_RESOURCE_GROUP --follow"
echo "  4. Run test suite:          python test_managed_identity_pdfs.py"
echo ""
echo "=================================================="
