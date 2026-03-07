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
CONTAINER_APP_API_B2C=$(get_env_value_or_default "CONTAINER_APP_API_B2C" "graphrag-api-b2c")
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
# Keys removed — DI and CU now use Managed Identity (DefaultAzureCredential).
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=$(get_env_value_or_default "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT" "")
AZURE_CONTENT_UNDERSTANDING_ENDPOINT=$(get_env_value_or_default "AZURE_CONTENT_UNDERSTANDING_ENDPOINT" "")

# Azure Translator (query translation for multilingual chat)
AZURE_TRANSLATOR_ENDPOINT=$(get_env_value_or_default "AZURE_TRANSLATOR_ENDPOINT" "")
AZURE_TRANSLATOR_REGION=$(get_env_value_or_default "AZURE_TRANSLATOR_REGION" "swedencentral")

# Azure Speech Translation (voice input with auto language detection)
ENABLE_SPEECH_TRANSLATION=$(get_env_value_or_default "ENABLE_SPEECH_TRANSLATION" "false")

# Neo4j Configuration
NEO4J_CONTAINER_NAME="neo4j-graphrag"
STORAGE_ACCOUNT=$(get_env_value_or_default "STORAGE_ACCOUNT_NAME" "neo4jstorage21224" false)

# User file upload storage
AZURE_USERSTORAGE_ACCOUNT=${AZURE_USERSTORAGE_ACCOUNT:-$STORAGE_ACCOUNT}
AZURE_USERSTORAGE_CONTAINER=${AZURE_USERSTORAGE_CONTAINER:-user-content}

# Group ID override — leave empty for per-user isolation; set for shared demo tenant
GROUP_ID_OVERRIDE=$(get_env_value_or_default "GROUP_ID_OVERRIDE" "" false)

# Docker cleanup control (default: enabled for deployment)
DOCKER_CLEANUP_ENABLED=${DOCKER_CLEANUP_ENABLED:-true}

echo "=================================================="
echo "GraphRAG Deployment Configuration"
echo "=================================================="
echo "Resource Group:       $AZURE_RESOURCE_GROUP"
echo "Location:             $AZURE_LOCATION"
echo "Container Registry:   $CONTAINER_REGISTRY_NAME"
echo "Container App (API):   $CONTAINER_APP_API"
echo "Container App (B2C):   $CONTAINER_APP_API_B2C"
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

# Build and push Docker images using ACR build (no login required)
# API and Worker use separate Dockerfiles with the same requirements.
echo "=================================================="
echo "🐳 Building and Pushing Docker Images"
echo "=================================================="

API_IMAGE_NAME="graphrag-api"
WORKER_IMAGE_NAME="graphrag-worker"
API_IMAGE_URI="$ACR_SERVER/$API_IMAGE_NAME:$AZURE_ENV_IMAGETAG"
WORKER_IMAGE_URI="$ACR_SERVER/$WORKER_IMAGE_NAME:$AZURE_ENV_IMAGETAG"

echo "API Image:    $API_IMAGE_URI"
echo "Worker Image: $WORKER_IMAGE_URI"
echo ""

# Create minimal staging directory with only what the Dockerfiles need.
# az acr build's tar packer recursively walks ALL dirs (even ignored ones)
# which is extremely slow when node_modules (558MB) exists in the tree.
STAGING_DIR=$(mktemp -d /tmp/graphrag-build-XXXXXX)
trap "rm -rf '$STAGING_DIR'" EXIT

echo "📦 Creating minimal build context..."
mkdir -p "$STAGING_DIR/frontend/app/frontend" \
         "$STAGING_DIR/frontend/app/backend" \
         "$STAGING_DIR/graphrag-orchestration"

cp Dockerfile.api Dockerfile.worker "$STAGING_DIR/"
cp -r src/ "$STAGING_DIR/src/"
# Frontend SPA source (exclude node_modules, dist)
cp frontend/app/frontend/package.json \
   frontend/app/frontend/package-lock.json \
   frontend/app/frontend/.npmrc \
   frontend/app/frontend/tsconfig.json \
   frontend/app/frontend/vite.config.ts \
   frontend/app/frontend/index.html \
   "$STAGING_DIR/frontend/app/frontend/"
cp -r frontend/app/frontend/src/ "$STAGING_DIR/frontend/app/frontend/src/"
cp -r frontend/app/frontend/public/ "$STAGING_DIR/frontend/app/frontend/public/"
# Backend prepdocslib (used by API Dockerfile)
cp -r frontend/app/backend/prepdocslib/ "$STAGING_DIR/frontend/app/backend/prepdocslib/"
# Python requirements and third-party stubs
cp graphrag-orchestration/requirements.txt "$STAGING_DIR/graphrag-orchestration/"
cp -r graphrag-orchestration/third_party/ "$STAGING_DIR/graphrag-orchestration/third_party/"

CONTEXT_SIZE=$(du -sh "$STAGING_DIR" | cut -f1)
echo "✅ Build context: $CONTEXT_SIZE (staging dir)"
echo ""

echo "⏳ Building and pushing API image in ACR..."
az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --file Dockerfile.api \
    --image "$API_IMAGE_NAME:$AZURE_ENV_IMAGETAG" \
    --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --build-arg VERSION="$AZURE_ENV_IMAGETAG" \
    --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
    "$STAGING_DIR"

echo "⏳ Building and pushing Worker image in ACR..."
az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --file Dockerfile.worker \
    --image "$WORKER_IMAGE_NAME:$AZURE_ENV_IMAGETAG" \
    --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
    "$STAGING_DIR"

echo "✅ Images built and pushed"
echo ""

# Update Container Apps (both API and Worker)
echo "=================================================="
echo "🚀 Updating Container Apps"
echo "=================================================="

for CA_NAME in "$CONTAINER_APP_API" "$CONTAINER_APP_API_B2C" "$CONTAINER_APP_WORKER"; do
    CA_EXISTS=$(az containerapp show \
        --name "$CA_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query name -o tsv 2>/dev/null || echo "")
    if [ -z "$CA_EXISTS" ]; then
        if [ "$CA_NAME" = "$CONTAINER_APP_API_B2C" ]; then
            echo "⚠️  B2C Container App '$CA_NAME' not found — skipping (optional)"
            SKIP_B2C=true
        else
            echo "❌ Container App '$CA_NAME' not found in resource group '$AZURE_RESOURCE_GROUP'"
            exit 1
        fi
    else
        echo "✅ Container App found: $CA_NAME"
    fi
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

# Ensure ACR registry auth is configured on all container apps
for CA_NAME in "$CONTAINER_APP_API" "$CONTAINER_APP_API_B2C" "$CONTAINER_APP_WORKER"; do
    if [ "$CA_NAME" = "$CONTAINER_APP_API_B2C" ] && [ "${SKIP_B2C:-}" = "true" ]; then continue; fi
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

# ── Tuning overrides ─────────────────────────────────────────────────────
# Most tuning knobs now have production-correct defaults in the code itself.
# Only set vars here that genuinely need per-environment override or that
# differ from code defaults intentionally.  All other knobs (DENOISE_*,
# SKELETON_*, ROUTE7_*, etc.) use their code defaults and can be overridden
# ad-hoc via `export VAR=val` before running this script.
#
# Previously-set vars that are now redundant (code defaults match production):
#   V3_GLOBAL_DYNAMIC_* (7 vars — dead code, never read by application)
#   DENOISE_SCORE_WEIGHTED, DENOISE_COMMUNITY_FILTER, COMMUNITY_PENALTY,
#   DENOISE_SCORE_GAP, SCORE_GAP_THRESHOLD, SCORE_GAP_MIN_KEEP,
#   DENOISE_SEMANTIC_DEDUP, SEMANTIC_DEDUP_THRESHOLD, DENOISE_VECTOR_FALLBACK,
#   VECTOR_FALLBACK_TOP_K, CHUNK_STRATEGY, ROUTE3_RETURN_TIMINGS,
#   ROUTE3_MAP_MAX_CLAIMS, ROUTE4_WORKFLOW, ROUTE5_SEED_MODE,
#   ROUTE7_RERANK_ALL, ROUTE7_SYNONYM_THRESHOLD, ROUTE7_SEMANTIC_SEED_TOP_K,
#   ROUTE7_PPR_PASSAGE_TOP_K, ROUTE7_RERANK,
#   SKELETON_ENRICHMENT_ENABLED, SKELETON_GRAPH_TRAVERSAL_ENABLED,
#   SKELETON_SYNTHESIS_MODEL, SKELETON_LLM_SENTENCE_REVIEW
#   ROUTE7_TRIPLE_TOP_K, ROUTE7_DPR_TOP_K, ROUTE7_ENTITY_SEED_TOP_K,
#   ROUTE7_TRIPLE_RERANK, ROUTE7_TRIPLE_CANDIDATES_K,
#   ROUTE7_SEMANTIC_PASSAGE_SEEDS, ROUTE7_SEMANTIC_SEED_WEIGHT,
#   ROUTE7_PROMPT_VARIANT, ROUTE6_COMMUNITY_EXTRACT, ROUTE3_COMMUNITY_TOP_K

# Route 3 v2 (LazyGraphRAG Map-Reduce) — override only if needed
# Examples:
#   export ROUTE3_MAP_MAX_CLAIMS=15
#   export ROUTE3_COMMUNITY_TOP_K=5
#   export ROUTE4_WORKFLOW=1  # Enable LlamaIndex Workflow for parallel DRIFT

# ── Secrets ──────────────────────────────────────────────────────────────
# Secrets are stored as Container App secrets and injected via secretref.
# If a value is provided in the environment / azd, the secret is updated.
# Otherwise, the existing Container App secret is kept unchanged.

VOYAGE_API_KEY=$(get_env_value_or_default "VOYAGE_API_KEY" "" false)
NEO4J_PASSWORD=$(get_env_value_or_default "NEO4J_PASSWORD" "" false)
MISTRAL_API_KEY=$(get_env_value_or_default "MISTRAL_API_KEY" "" false)
LLMWHISPERER_API_KEY=$(get_env_value_or_default "LLMWHISPERER_API_KEY" "" false)
AURA_DS_CLIENT_SECRET=$(get_env_value_or_default "AURA_DS_CLIENT_SECRET" "" false)

# Build a space-separated list of secrets to update (only those with values)
_SECRETS_TO_SET=""
[ -n "$VOYAGE_API_KEY" ]        && _SECRETS_TO_SET="$_SECRETS_TO_SET voyage-api-key=$VOYAGE_API_KEY"
[ -n "$NEO4J_PASSWORD" ]        && _SECRETS_TO_SET="$_SECRETS_TO_SET neo4j-password=$NEO4J_PASSWORD"
[ -n "$MISTRAL_API_KEY" ]       && _SECRETS_TO_SET="$_SECRETS_TO_SET mistral-api-key=$MISTRAL_API_KEY"
[ -n "$LLMWHISPERER_API_KEY" ]  && _SECRETS_TO_SET="$_SECRETS_TO_SET llmwhisperer-api-key=$LLMWHISPERER_API_KEY"
[ -n "$AURA_DS_CLIENT_SECRET" ] && _SECRETS_TO_SET="$_SECRETS_TO_SET aura-ds-client-secret=$AURA_DS_CLIENT_SECRET"

if [ -n "$_SECRETS_TO_SET" ]; then
    echo "🔑 Updating Container App secrets..."
    for CA_NAME in "$CONTAINER_APP_API" "$CONTAINER_APP_API_B2C" "$CONTAINER_APP_WORKER"; do
        if [ "$CA_NAME" = "$CONTAINER_APP_API_B2C" ] && [ "${SKIP_B2C:-}" = "true" ]; then continue; fi
        echo "   → $CA_NAME"
        az containerapp secret set \
            --name "$CA_NAME" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --secrets $_SECRETS_TO_SET \
            --only-show-errors || echo "⚠️  Warning: failed to set secrets on $CA_NAME"
    done
fi

# Route 3 v1 denoising vars — REMOVED in v2 (map-reduce has no chunk pipeline).
# Kept commented for rollback reference.
# ROUTE3_DENOISE_DEDUP=1
# ROUTE3_DENOISE_NOISE_FILTER=1
# ROUTE3_DENOISE_PPR_SCORING=1
# ROUTE3_DENOISE_TOKEN_BUDGET=1

ENV_VARS=(
    REFRESH_TIMESTAMP="$REFRESH_TIMESTAMP"
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT="$AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"
    AZURE_CONTENT_UNDERSTANDING_ENDPOINT="$AZURE_CONTENT_UNDERSTANDING_ENDPOINT"
    AZURE_TRANSLATOR_ENDPOINT="$AZURE_TRANSLATOR_ENDPOINT"
    AZURE_TRANSLATOR_REGION="$AZURE_TRANSLATOR_REGION"
    ENABLE_SPEECH_TRANSLATION="$ENABLE_SPEECH_TRANSLATION"
    USE_USER_UPLOAD="true"
    AZURE_STORAGE_ACCOUNT="$STORAGE_ACCOUNT"
    AZURE_STORAGE_CONTAINER="content"
    AZURE_USERSTORAGE_ACCOUNT="$AZURE_USERSTORAGE_ACCOUNT"
    AZURE_USERSTORAGE_CONTAINER="$AZURE_USERSTORAGE_CONTAINER"
    RUNNING_IN_PRODUCTION="true"
    GROUP_ID_OVERRIDE="$GROUP_ID_OVERRIDE"
)

# Only add secret-ref env vars when the corresponding secret exists
[ -n "$VOYAGE_API_KEY" ]        && ENV_VARS+=(VOYAGE_API_KEY="secretref:voyage-api-key")
[ -n "$NEO4J_PASSWORD" ]        && ENV_VARS+=(NEO4J_PASSWORD="secretref:neo4j-password")
[ -n "$AURA_DS_CLIENT_SECRET" ] && ENV_VARS+=(AURA_DS_CLIENT_ID="$AURA_DS_CLIENT_ID" AURA_DS_CLIENT_SECRET="secretref:aura-ds-client-secret")
[ -n "$MISTRAL_API_KEY" ]       && ENV_VARS+=(MISTRAL_API_KEY="secretref:mistral-api-key")
[ -n "$LLMWHISPERER_API_KEY" ]  && ENV_VARS+=(LLMWHISPERER_API_KEY="secretref:llmwhisperer-api-key")

# Update graphrag-api
echo "⏳ Updating $CONTAINER_APP_API with $API_IMAGE_URI..."
az containerapp update \
    --name "$CONTAINER_APP_API" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --image "$API_IMAGE_URI" \
    --set-env-vars "${ENV_VARS[@]}" \
    --only-show-errors
echo "✅ $CONTAINER_APP_API updated"

# Update graphrag-api-b2c (same env vars as B2B — auth-specific vars are set separately via Bicep/manual config)
# --set-env-vars merges; it won't overwrite B2C-specific auth vars that were set independently.
if [ "${SKIP_B2C:-}" != "true" ]; then
    echo "⏳ Updating $CONTAINER_APP_API_B2C with $API_IMAGE_URI..."
    az containerapp update \
        --name "$CONTAINER_APP_API_B2C" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --image "$API_IMAGE_URI" \
        --set-env-vars "${ENV_VARS[@]}" \
        --only-show-errors
    echo "✅ $CONTAINER_APP_API_B2C updated"
fi

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
