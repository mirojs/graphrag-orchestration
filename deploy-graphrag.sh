#!/bin/bash
# GraphRAG Deployment Script
# Builds one Docker image and deploys to both graphrag-api and graphrag-worker
# container apps in Azure Container Apps (rg-graphrag-feature).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR"

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
        # Call azd but suppress noisy stderr (sometimes shows HTTP errors like 'Bad Request')
        # Use '|| true' to prevent 'set -e' from exiting on azd failures.
        local azd_output
        azd_output=$(azd env get-value "$key" 2>/dev/null) || true
        # If azd returned an explicit ERROR: prefix, treat as not found and emit a concise warning
        if [ -n "$azd_output" ] && ! echo "$azd_output" | grep -q "^ERROR:"; then
            value="$azd_output"
        else
            >&2 echo "⚠️  azd env get-value $key failed or not set; continuing with default"
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
CONTAINER_REGISTRY_NAME=$(get_env_value_or_default "CONTAINER_REGISTRY_NAME" "graphragacr12153" true)
CONTAINER_APP_API=$(get_env_value_or_default "CONTAINER_APP_API" "graphrag-api")
CONTAINER_APP_WORKER=$(get_env_value_or_default "CONTAINER_APP_WORKER" "graphrag-worker")
CONTAINER_APP_ENVIRONMENT=$(get_env_value_or_default "CONTAINER_APP_ENVIRONMENT" "graphrag-env")
AZURE_ENV_IMAGETAG=$(get_env_value_or_default "AZURE_ENV_IMAGETAG" "")

# Prefer immutable image tags by default (avoids confusion with mutable :latest).
# Can be overridden via env var or `azd env set AZURE_ENV_IMAGETAG <tag>`.
if [ -z "$AZURE_ENV_IMAGETAG" ]; then
    GIT_SHA=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "manual")
    # Match existing tag format: {sha}-{seq}. Use epoch seconds as sequence.
    BUILD_SEQ=$(date -u +"%s" | tail -c 3)
    AZURE_ENV_IMAGETAG="${GIT_SHA}-${BUILD_SEQ}"
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
echo "Container App (API):   $CONTAINER_APP_API"
echo "Container App (Worker):$CONTAINER_APP_WORKER"
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
# Both graphrag-api and graphrag-worker use the same image.
echo "=================================================="
echo "🐳 Building and Pushing Docker Images"
echo "=================================================="

API_IMAGE_NAME="graphrag-api"
WORKER_IMAGE_NAME="graphrag-worker"
API_IMAGE_URI="$ACR_SERVER/$API_IMAGE_NAME:$AZURE_ENV_IMAGETAG"
WORKER_IMAGE_URI="$ACR_SERVER/$WORKER_IMAGE_NAME:$AZURE_ENV_IMAGETAG"

echo "API Image:    $API_IMAGE_URI"
echo "Worker Image: $WORKER_IMAGE_URI"
echo "Build Context: $APP_DIR"
echo ""

echo "⏳ Building and pushing image in ACR (this may take 2-3 minutes)..."
az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --file Dockerfile.api \
    --image "$API_IMAGE_NAME:$AZURE_ENV_IMAGETAG" \
    --image "$WORKER_IMAGE_NAME:$AZURE_ENV_IMAGETAG" \
    --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --build-arg VERSION="$AZURE_ENV_IMAGETAG" \
    --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
    "$APP_DIR"

echo "✅ Images built and pushed"
echo ""

# Update Container Apps (both API and Worker)
echo "=================================================="
echo "🚀 Updating Container Apps"
echo "=================================================="

for CA_NAME in "$CONTAINER_APP_API" "$CONTAINER_APP_WORKER"; do
    CA_EXISTS=$(az containerapp show \
        --name "$CA_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query name -o tsv 2>/dev/null || echo "")
    if [ -z "$CA_EXISTS" ]; then
        echo "❌ Container App '$CA_NAME' not found in resource group '$AZURE_RESOURCE_GROUP'"
        exit 1
    fi
    echo "✅ Container App found: $CA_NAME"
done
echo ""

# Auto-detect managed identity from the API container app
if [ -z "$CONTAINER_APP_USER_IDENTITY_ID" ]; then
    echo "🔍 Auto-detecting managed identity..."
    SYSTEM_IDENTITY=$(az containerapp show \
        --name "$CONTAINER_APP_API" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "identity.type" -o tsv 2>/dev/null || echo "")
    if [[ "$SYSTEM_IDENTITY" == *"SystemAssigned"* ]]; then
        echo "✅ Found system-assigned managed identity"
        CONTAINER_APP_USER_IDENTITY_ID="system"
    else
        CONTAINER_APP_USER_IDENTITY_ID=$(az containerapp show \
            --name "$CONTAINER_APP_API" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --query "identity.userAssignedIdentities | keys(@) | [0]" -o tsv 2>/dev/null || echo "")
        if [ -n "$CONTAINER_APP_USER_IDENTITY_ID" ]; then
            echo "✅ Found user-assigned managed identity: ${CONTAINER_APP_USER_IDENTITY_ID##*/}"
        fi
    fi
fi

# Ensure ACR registry auth is configured on both container apps
for CA_NAME in "$CONTAINER_APP_API" "$CONTAINER_APP_WORKER"; do
    EXISTING_REGISTRY=$(az containerapp show \
        --name "$CA_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "properties.configuration.registries[?server=='$ACR_SERVER'].server" -o tsv 2>/dev/null || echo "")
    if [ -n "$EXISTING_REGISTRY" ]; then
        echo "✅ ACR auth on $CA_NAME: already configured"
    elif [ -n "$CONTAINER_APP_USER_IDENTITY_ID" ]; then
        echo "⏳ Configuring ACR auth on $CA_NAME..."
        az containerapp registry set \
            --name "$CA_NAME" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --server "$ACR_SERVER" \
            --identity "$CONTAINER_APP_USER_IDENTITY_ID" \
            --only-show-errors
        echo "✅ ACR auth on $CA_NAME: configured (managed identity)"
    else
        echo "⚠️  No managed identity found for $CA_NAME. ACR admin credentials needed."
    fi
done

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

# Route 3 v2 (LazyGraphRAG Map-Reduce) tuning
# v2 replaces the 7-stage pipeline with 3-step map-reduce.
# Override by exporting before running the script.
# Examples:
#   export ROUTE3_RETURN_TIMINGS=1
#   export ROUTE3_MAP_MAX_CLAIMS=15
#   export ROUTE3_COMMUNITY_TOP_K=5
#   export ROUTE4_WORKFLOW=1  # Enable LlamaIndex Workflow for parallel DRIFT
ROUTE3_RETURN_TIMINGS=${ROUTE3_RETURN_TIMINGS:-0}
ROUTE3_MAP_MAX_CLAIMS=${ROUTE3_MAP_MAX_CLAIMS:-10}
ROUTE3_COMMUNITY_TOP_K=${ROUTE3_COMMUNITY_TOP_K:-3}
ROUTE4_WORKFLOW=${ROUTE4_WORKFLOW:-0}
# Route 2 denoising defaults — production-tested values from Feb 2026 ablation study.
# See ANALYSIS_ROUTE2_ARCHITECTURE_DEEP_DIVE_2026-02-10.md Section 8 for rationale.
DENOISE_SCORE_WEIGHTED=${DENOISE_SCORE_WEIGHTED:-1}
DENOISE_COMMUNITY_FILTER=${DENOISE_COMMUNITY_FILTER:-1}
COMMUNITY_PENALTY=${COMMUNITY_PENALTY:-0.3}
DENOISE_SCORE_GAP=${DENOISE_SCORE_GAP:-1}
SCORE_GAP_THRESHOLD=${SCORE_GAP_THRESHOLD:-0.5}
SCORE_GAP_MIN_KEEP=${SCORE_GAP_MIN_KEEP:-6}
DENOISE_SEMANTIC_DEDUP=${DENOISE_SEMANTIC_DEDUP:-1}
SEMANTIC_DEDUP_THRESHOLD=${SEMANTIC_DEDUP_THRESHOLD:-0.92}
DENOISE_VECTOR_FALLBACK=${DENOISE_VECTOR_FALLBACK:-0}
VECTOR_FALLBACK_TOP_K=${VECTOR_FALLBACK_TOP_K:-3}

# Voyage V2 Embedding API key (required for V2 vector search)
VOYAGE_API_KEY=$(get_env_value_or_default "VOYAGE_API_KEY" "" false)

# Route 3 v1 denoising vars — REMOVED in v2 (map-reduce has no chunk pipeline).
# Kept commented for rollback reference.
# ROUTE3_DENOISE_DEDUP=1
# ROUTE3_DENOISE_NOISE_FILTER=1
# ROUTE3_DENOISE_PPR_SCORING=1
# ROUTE3_DENOISE_TOKEN_BUDGET=1

# Skeleton enrichment (sentence-level retrieval + graph traversal).
# Strategy B + gpt-4.1-mini synthesis — validated Feb 2026 benchmark.
SKELETON_ENRICHMENT_ENABLED=${SKELETON_ENRICHMENT_ENABLED:-true}
SKELETON_GRAPH_TRAVERSAL_ENABLED=${SKELETON_GRAPH_TRAVERSAL_ENABLED:-true}
SKELETON_SYNTHESIS_MODEL=${SKELETON_SYNTHESIS_MODEL:-gpt-4.1-mini}

# Route 5 flat-pool seed mode (flat = equal-weight seed union, weighted = legacy 3-tier)
ROUTE5_SEED_MODE=${ROUTE5_SEED_MODE:-weighted}

ENV_VARS=(
    REFRESH_TIMESTAMP="$REFRESH_TIMESTAMP"
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT="$AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"
    AZURE_DOCUMENT_INTELLIGENCE_KEY="$AZURE_DOCUMENT_INTELLIGENCE_KEY"
    AZURE_CONTENT_UNDERSTANDING_ENDPOINT="$AZURE_CONTENT_UNDERSTANDING_ENDPOINT"
    AZURE_CONTENT_UNDERSTANDING_API_KEY="$AZURE_CONTENT_UNDERSTANDING_API_KEY"
    V3_GLOBAL_DYNAMIC_SELECTION="$V3_GLOBAL_DYNAMIC_SELECTION"
    V3_GLOBAL_DYNAMIC_MAX_DEPTH="$V3_GLOBAL_DYNAMIC_MAX_DEPTH"
    V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET="$V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET"
    V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL="$V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL"
    V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD="$V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD"
    V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE="$V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE"
    V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY="$V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY"
    ROUTE3_RETURN_TIMINGS="$ROUTE3_RETURN_TIMINGS"
    ROUTE3_MAP_MAX_CLAIMS="$ROUTE3_MAP_MAX_CLAIMS"
    ROUTE3_COMMUNITY_TOP_K="$ROUTE3_COMMUNITY_TOP_K"
    ROUTE4_WORKFLOW="$ROUTE4_WORKFLOW"
    DENOISE_SCORE_WEIGHTED="$DENOISE_SCORE_WEIGHTED"
    DENOISE_COMMUNITY_FILTER="$DENOISE_COMMUNITY_FILTER"
    COMMUNITY_PENALTY="$COMMUNITY_PENALTY"
    DENOISE_SCORE_GAP="$DENOISE_SCORE_GAP"
    SCORE_GAP_THRESHOLD="$SCORE_GAP_THRESHOLD"
    SCORE_GAP_MIN_KEEP="$SCORE_GAP_MIN_KEEP"
    DENOISE_SEMANTIC_DEDUP="$DENOISE_SEMANTIC_DEDUP"
    SEMANTIC_DEDUP_THRESHOLD="$SEMANTIC_DEDUP_THRESHOLD"
    DENOISE_VECTOR_FALLBACK="$DENOISE_VECTOR_FALLBACK"
    VECTOR_FALLBACK_TOP_K="$VECTOR_FALLBACK_TOP_K"
    VOYAGE_API_KEY="$VOYAGE_API_KEY"
    AURA_DS_CLIENT_ID="$AURA_DS_CLIENT_ID"
    AURA_DS_CLIENT_SECRET="$AURA_DS_CLIENT_SECRET"
    SKELETON_ENRICHMENT_ENABLED="$SKELETON_ENRICHMENT_ENABLED"
    SKELETON_GRAPH_TRAVERSAL_ENABLED="$SKELETON_GRAPH_TRAVERSAL_ENABLED"
    SKELETON_SYNTHESIS_MODEL="$SKELETON_SYNTHESIS_MODEL"
    ROUTE5_SEED_MODE="$ROUTE5_SEED_MODE"
)

# Update graphrag-api
echo "⏳ Updating $CONTAINER_APP_API with $API_IMAGE_URI..."
az containerapp update \
    --name "$CONTAINER_APP_API" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --image "$API_IMAGE_URI" \
    --set-env-vars "${ENV_VARS[@]}" \
    --only-show-errors
echo "✅ $CONTAINER_APP_API updated"

# Update graphrag-worker
echo "⏳ Updating $CONTAINER_APP_WORKER with $WORKER_IMAGE_URI..."
az containerapp update \
    --name "$CONTAINER_APP_WORKER" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --image "$WORKER_IMAGE_URI" \
    --set-env-vars "${ENV_VARS[@]}" \
    --only-show-errors
echo "✅ $CONTAINER_APP_WORKER updated"
echo ""

# Get API endpoint
CONTAINER_APP_FQDN=$(az containerapp show \
    --name "$CONTAINER_APP_API" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)

if [ -n "$CONTAINER_APP_FQDN" ]; then
    echo "🌐 API URL:       https://$CONTAINER_APP_FQDN"
    echo "   Swagger UI:    https://$CONTAINER_APP_FQDN/docs"
    echo "   Health Check:  https://$CONTAINER_APP_FQDN/health"
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
echo "  • API Image:    $API_IMAGE_URI"
echo "  • Worker Image: $WORKER_IMAGE_URI"
echo "  • API URL:      https://$CONTAINER_APP_FQDN"
echo "  • Timestamp:    $REFRESH_TIMESTAMP"
echo ""
echo "🔧 Next steps:"
echo "  1. Test health:    curl https://$CONTAINER_APP_FQDN/health"
echo "  2. Swagger docs:   open https://$CONTAINER_APP_FQDN/docs"
echo "  3. API logs:       az containerapp logs show -n $CONTAINER_APP_API -g $AZURE_RESOURCE_GROUP --follow"
echo "  4. Worker logs:    az containerapp logs show -n $CONTAINER_APP_WORKER -g $AZURE_RESOURCE_GROUP --follow"
echo ""
echo "=================================================="
