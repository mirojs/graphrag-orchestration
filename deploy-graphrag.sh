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

    local value=""
    
    # Try environment variable first
    if [ -n "${!key:-}" ]; then
        value="${!key}"
    # Try azd if env var is empty and azd is available
    elif command -v azd &>/dev/null; then
        # azd outputs errors to stdout, so check for ERROR prefix
        local azd_output=$(azd env get-value "$key" 2>&1)
        if ! echo "$azd_output" | grep -q "^ERROR:"; then
            value="$azd_output"
        fi
    fi
    
    # Fallback to default
    if [ -z "$value" ]; then
        value="$default"
    fi

    # Check if required and still empty
    if [ -z "$value" ] && [ "$required" = "true" ]; then
        >&2 echo "❌ Required environment key '$key' not found."
        >&2 echo "   Set it via: export $key=<value> or azd env set $key <value>"
        exit 1
    fi

    echo "$value"
}

# Configuration
AZURE_SUBSCRIPTION_ID=$(get_env_value_or_default "AZURE_SUBSCRIPTION_ID" "")
AZURE_RESOURCE_GROUP=$(get_env_value_or_default "AZURE_RESOURCE_GROUP" "rg-graphrag-feature")
AZURE_LOCATION=$(get_env_value_or_default "AZURE_LOCATION" "swedencentral")
CONTAINER_REGISTRY_NAME=$(get_env_value_or_default "CONTAINER_REGISTRY_NAME" "" true)
CONTAINER_APP_NAME=$(get_env_value_or_default "CONTAINER_APP_NAME" "graphrag-orchestration")
CONTAINER_APP_ENVIRONMENT=$(get_env_value_or_default "CONTAINER_APP_ENVIRONMENT" "graphrag-env")
AZURE_ENV_IMAGETAG=$(get_env_value_or_default "AZURE_ENV_IMAGETAG" "")

# Prefer immutable image tags by default (avoids confusion with mutable :latest).
# Can be overridden via env var or `azd env set AZURE_ENV_IMAGETAG <tag>`.
if [ -z "$AZURE_ENV_IMAGETAG" ]; then
    GIT_SHA=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "manual")
    AZURE_ENV_IMAGETAG="main-${GIT_SHA}-$(date -u +"%Y%m%d%H%M%S")"
fi
CONTAINER_APP_USER_IDENTITY_ID=$(get_env_value_or_default "CONTAINER_APP_USER_IDENTITY_ID" "")

# Azure Document Intelligence configuration (required for DI-based ingestion)
# Prefer DI-specific vars; allow CU vars as a backwards-compatible alias.
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=$(get_env_value_or_default "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT" "")
AZURE_DOCUMENT_INTELLIGENCE_KEY=$(get_env_value_or_default "AZURE_DOCUMENT_INTELLIGENCE_KEY" "")
AZURE_CONTENT_UNDERSTANDING_ENDPOINT=$(get_env_value_or_default "AZURE_CONTENT_UNDERSTANDING_ENDPOINT" "")
AZURE_CONTENT_UNDERSTANDING_API_KEY=$(get_env_value_or_default "AZURE_CONTENT_UNDERSTANDING_API_KEY" "")

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
echo "DI Endpoint:          ${AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT:-${AZURE_CONTENT_UNDERSTANDING_ENDPOINT:-<unset>}}"
echo "Docker Cleanup:       $DOCKER_CLEANUP_ENABLED"
echo "=================================================="
echo ""

if [ -z "$AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT" ] && [ -z "$AZURE_CONTENT_UNDERSTANDING_ENDPOINT" ]; then
    >&2 echo "❌ Missing Document Intelligence endpoint configuration."
    >&2 echo "   Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT (preferred) or AZURE_CONTENT_UNDERSTANDING_ENDPOINT (alias)."
    >&2 echo "   Example: azd env set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT https://<resource>.cognitiveservices.azure.com/"
    exit 1
fi

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
echo ""

# Build and push Docker image using ACR build (no login required)
echo "=================================================="
echo "🐳 Building and Pushing Docker Image"
echo "=================================================="

IMAGE_NAME="graphrag-orchestration"
IMAGE_URI="$ACR_SERVER/$IMAGE_NAME:$AZURE_ENV_IMAGETAG"

echo "Image URI: $IMAGE_URI"
echo "Build Context: $APP_DIR"
echo ""

echo "⏳ Building and pushing image in ACR (this may take 2-3 minutes)..."
az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --image "$IMAGE_NAME:$AZURE_ENV_IMAGETAG" \
    --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --build-arg VERSION="$AZURE_ENV_IMAGETAG" \
    --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
    "$APP_DIR"

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

# Auto-detect managed identity if not provided
if [ -z "$CONTAINER_APP_USER_IDENTITY_ID" ]; then
    echo "🔍 Auto-detecting managed identity..."
    
    # Check for system-assigned identity first
    SYSTEM_IDENTITY=$(az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "identity.type" -o tsv 2>/dev/null || echo "")
    
    if [ "$SYSTEM_IDENTITY" == "SystemAssigned" ] || [ "$SYSTEM_IDENTITY" == "SystemAssigned, UserAssigned" ]; then
        echo "✅ Found system-assigned managed identity"
        CONTAINER_APP_USER_IDENTITY_ID="system"
    else
        # Check for user-assigned identity
        CONTAINER_APP_USER_IDENTITY_ID=$(az containerapp show \
            --name "$CONTAINER_APP_NAME" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --query "identity.userAssignedIdentities | keys(@) | [0]" -o tsv 2>/dev/null || echo "")
        
        if [ -n "$CONTAINER_APP_USER_IDENTITY_ID" ]; then
            echo "✅ Found user-assigned managed identity: ${CONTAINER_APP_USER_IDENTITY_ID##*/}"
        fi
    fi
fi

# Check if registry is already configured (skip if it is - saves 30-60 seconds)
EXISTING_REGISTRY=$(az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.configuration.registries[?server=='$ACR_SERVER'].server" -o tsv 2>/dev/null || echo "")

if [ -n "$EXISTING_REGISTRY" ]; then
    echo "✅ ACR authentication already configured, skipping..."
else
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
        echo "⚠️  No managed identity found. Using ACR admin credentials (less secure)."
        echo "   Consider enabling managed identity for better security."
    fi
fi

# Update container app with new image
echo "⏳ Updating Container App with new image..."
REFRESH_TIMESTAMP=$(date +%Y%m%d%H%M%S)

# Enable Microsoft-style dynamic community selection for V3 global search
V3_GLOBAL_DYNAMIC_SELECTION=${V3_GLOBAL_DYNAMIC_SELECTION:-true}
V3_GLOBAL_DYNAMIC_MAX_DEPTH=${V3_GLOBAL_DYNAMIC_MAX_DEPTH:-2}
V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET=${V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET:-30}
V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL=${V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL:-12}
V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD=${V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD:-25}
V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE=${V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE:-8}
V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY=${V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY:-true}

# Route 3 (Hybrid Global Search) debugging / performance tuning
# These are safe to leave at defaults; override by exporting before running the script.
# Examples:
#   export ROUTE3_RETURN_TIMINGS=1
#   export ROUTE3_DISABLE_PPR=1
#   export ROUTE3_PPR_PER_SEED_LIMIT=10
#   export ROUTE3_PPR_PER_NEIGHBOR_LIMIT=5
ROUTE3_RETURN_TIMINGS=${ROUTE3_RETURN_TIMINGS:-0}
ROUTE3_DISABLE_PPR=${ROUTE3_DISABLE_PPR:-0}
ROUTE3_PPR_PER_SEED_LIMIT=${ROUTE3_PPR_PER_SEED_LIMIT:-25}
ROUTE3_PPR_PER_NEIGHBOR_LIMIT=${ROUTE3_PPR_PER_NEIGHBOR_LIMIT:-10}
ROUTE3_GRAPH_NATIVE_BM25=${ROUTE3_GRAPH_NATIVE_BM25:-1}

az containerapp update \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --image "$IMAGE_URI" \
        --set-env-vars \
            REFRESH_TIMESTAMP="$REFRESH_TIMESTAMP" \
            AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT="$AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT" \
            AZURE_DOCUMENT_INTELLIGENCE_KEY="$AZURE_DOCUMENT_INTELLIGENCE_KEY" \
            AZURE_CONTENT_UNDERSTANDING_ENDPOINT="$AZURE_CONTENT_UNDERSTANDING_ENDPOINT" \
            AZURE_CONTENT_UNDERSTANDING_API_KEY="$AZURE_CONTENT_UNDERSTANDING_API_KEY" \
            V3_GLOBAL_DYNAMIC_SELECTION="$V3_GLOBAL_DYNAMIC_SELECTION" \
            V3_GLOBAL_DYNAMIC_MAX_DEPTH="$V3_GLOBAL_DYNAMIC_MAX_DEPTH" \
            V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET="$V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET" \
            V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL="$V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL" \
            V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD="$V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD" \
            V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE="$V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE" \
            V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY="$V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY" \
            ROUTE3_RETURN_TIMINGS="$ROUTE3_RETURN_TIMINGS" \
            ROUTE3_DISABLE_PPR="$ROUTE3_DISABLE_PPR" \
            ROUTE3_PPR_PER_SEED_LIMIT="$ROUTE3_PPR_PER_SEED_LIMIT" \
            ROUTE3_PPR_PER_NEIGHBOR_LIMIT="$ROUTE3_PPR_PER_NEIGHBOR_LIMIT" \
            ROUTE3_GRAPH_NATIVE_BM25="$ROUTE3_GRAPH_NATIVE_BM25" \
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
