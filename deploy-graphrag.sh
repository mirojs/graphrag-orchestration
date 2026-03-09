#!/bin/bash
# GraphRAG Deployment Script
# Builds Docker images via ACR and deploys infrastructure + apps via azd/Bicep.
# All secrets, env vars, and RBAC are managed declaratively in infra/main.bicep.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR"

# ── Configuration ────────────────────────────────────────────────────────

get_env_value_or_default() {
    local key="$1"
    local default="$2"
    local required="${3:-false}"
    local value=""

    if [ -n "${!key:-}" ]; then
        value="${!key}"
    elif command -v azd &>/dev/null; then
        local azd_output
        azd_output=$(azd env get-value "$key" 2>/dev/null) || true
        if [ -n "$azd_output" ] && ! echo "$azd_output" | grep -q "^ERROR:"; then
            value="$azd_output"
        fi
    fi

    [ -z "$value" ] && value="$default"
    if [ -z "$value" ] && [ "$required" = "true" ]; then
        >&2 echo "❌ Required: $key. Set via: export $key=<value> or azd env set $key <value>"
        exit 1
    fi
    echo "$value"
}

AZURE_RESOURCE_GROUP=$(get_env_value_or_default "AZURE_RESOURCE_GROUP" "rg-graphrag-feature")
CONTAINER_REGISTRY_NAME=$(get_env_value_or_default "CONTAINER_REGISTRY_NAME" "graphragacr12153" true)
AZURE_ENV_IMAGETAG=$(get_env_value_or_default "AZURE_ENV_IMAGETAG" "")

if [ -z "$AZURE_ENV_IMAGETAG" ]; then
    GIT_SHA=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "manual")
    BUILD_SEQ=$(date -u +"%s" | tail -c 3)
    AZURE_ENV_IMAGETAG="${GIT_SHA}-${BUILD_SEQ}"
fi

echo "=================================================="
echo "GraphRAG Deployment"
echo "=================================================="
echo "Registry:   $CONTAINER_REGISTRY_NAME"
echo "Image Tag:  $AZURE_ENV_IMAGETAG"
echo "=================================================="
echo ""

# ── Azure Login ──────────────────────────────────────────────────────────

echo "🔐 Checking Azure login status..."
if ! az account show --only-show-errors &>/dev/null; then
    echo "Logging in..."
    az login --only-show-errors
fi
echo "✅ Logged in: $(az account show --query name -o tsv)"
echo ""

# ── Build Docker Images ─────────────────────────────────────────────────

API_IMAGE_NAME="graphrag-api"
WORKER_IMAGE_NAME="graphrag-worker"

# Minimal staging dir to avoid sending node_modules to ACR
STAGING_DIR=$(mktemp -d /tmp/graphrag-build-XXXXXX)
trap "rm -rf '$STAGING_DIR'" EXIT

echo "📦 Creating minimal build context..."
mkdir -p "$STAGING_DIR/frontend/app/frontend" \
         "$STAGING_DIR/frontend/app/backend" \
         "$STAGING_DIR/graphrag-orchestration"

cp Dockerfile.api Dockerfile.worker "$STAGING_DIR/"
cp -r src/ "$STAGING_DIR/src/"
cp frontend/app/frontend/package.json \
   frontend/app/frontend/package-lock.json \
   frontend/app/frontend/.npmrc \
   frontend/app/frontend/tsconfig.json \
   frontend/app/frontend/vite.config.ts \
   frontend/app/frontend/index.html \
   "$STAGING_DIR/frontend/app/frontend/"
cp -r frontend/app/frontend/src/ "$STAGING_DIR/frontend/app/frontend/src/"
cp -r frontend/app/frontend/public/ "$STAGING_DIR/frontend/app/frontend/public/"
cp -r frontend/app/backend/prepdocslib/ "$STAGING_DIR/frontend/app/backend/prepdocslib/"
cp graphrag-orchestration/requirements.txt "$STAGING_DIR/graphrag-orchestration/"
cp -r graphrag-orchestration/third_party/ "$STAGING_DIR/graphrag-orchestration/third_party/"

echo "✅ Build context: $(du -sh "$STAGING_DIR" | cut -f1)"
echo ""

echo "⏳ Building API image..."
az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --file Dockerfile.api \
    --image "$API_IMAGE_NAME:$AZURE_ENV_IMAGETAG" \
    --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --build-arg VERSION="$AZURE_ENV_IMAGETAG" \
    --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
    "$STAGING_DIR"

echo "⏳ Building Worker image..."
az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --file Dockerfile.worker \
    --image "$WORKER_IMAGE_NAME:$AZURE_ENV_IMAGETAG" \
    --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
    "$STAGING_DIR"

echo "✅ Images built and pushed"
echo ""

# ── Deploy Infrastructure + Apps via azd ─────────────────────────────────
# All secrets, env vars, RBAC, and container config are declared in
# infra/main.bicep. azd up provisions infrastructure and updates container
# apps in a single declarative deployment.

ACR_SERVER="${CONTAINER_REGISTRY_NAME}.azurecr.io"
azd env set SERVICE_GRAPHRAG_API_IMAGE_NAME "${ACR_SERVER}/${API_IMAGE_NAME}:${AZURE_ENV_IMAGETAG}"
azd env set SERVICE_GRAPHRAG_WORKER_IMAGE_NAME "${ACR_SERVER}/${WORKER_IMAGE_NAME}:${AZURE_ENV_IMAGETAG}"

echo "🚀 Deploying infrastructure via azd provision (Bicep)..."
azd provision --no-prompt

# ── Summary ──────────────────────────────────────────────────────────────

API_FQDN=$(azd env get-value GRAPHRAG_API_URI 2>/dev/null || echo "<unknown>")

echo ""
echo "=================================================="
echo "✅ Deployment Complete!"
echo "=================================================="
echo ""
echo "📋 Summary:"
echo "  • API Image:    ${ACR_SERVER}/${API_IMAGE_NAME}:${AZURE_ENV_IMAGETAG}"
echo "  • Worker Image: ${ACR_SERVER}/${WORKER_IMAGE_NAME}:${AZURE_ENV_IMAGETAG}"
echo "  • API URL:      ${API_FQDN}"
echo ""
echo "🔧 Next steps:"
echo "  1. Test health:    curl ${API_FQDN}/health"
echo "  2. Swagger docs:   open ${API_FQDN}/docs"
echo "=================================================="
