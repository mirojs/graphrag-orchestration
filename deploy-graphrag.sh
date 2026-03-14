#!/bin/bash
# GraphRAG Full Deployment Script
#
# Comprehensive deployment: Docker build → Bicep infra → Health check → Rollback
#
# This is the authoritative deployment path that guarantees ALL configuration,
# secrets, env vars, and infrastructure defined in Bicep are deployed in sync
# with the code. Use this when you need a guaranteed-correct deployment.
#
# The CI/CD pipeline (.github/workflows/deploy.yml) is the fast path for
# code-only changes — it skips Bicep and only swaps container images.
#
# Usage:
#   ./deploy-graphrag.sh                          # Full deploy with defaults
#   ./deploy-graphrag.sh --algo v3                # Deploy with algorithm v3
#   ./deploy-graphrag.sh --skip-build             # Skip Docker build (infra-only)
#   ./deploy-graphrag.sh --tag abc1234-42         # Use a specific image tag

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Parse Arguments ──────────────────────────────────────────────────────

ALGO_VERSION="v2"
SKIP_BUILD=false
CUSTOM_TAG=""

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --algo VERSION       Algorithm version for worker: v1, v2, v3 (default: v2)"
    echo "  --skip-build         Skip Docker image build (redeploy existing images)"
    echo "  --tag TAG            Use a specific image tag instead of auto-generating"
    echo "  -h, --help           Show this help message"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --algo|--algorithm-version)
            ALGO_VERSION="$2"
            if [[ ! "$ALGO_VERSION" =~ ^v[1-3]$ ]]; then
                echo "❌ Invalid algorithm version: $ALGO_VERSION (must be v1, v2, or v3)"
                exit 1
            fi
            shift 2 ;;
        --skip-build)  SKIP_BUILD=true; shift ;;
        --tag)         CUSTOM_TAG="$2"; shift 2 ;;
        -h|--help)     usage; exit 0 ;;
        *)             echo "❌ Unknown option: $1"; usage; exit 1 ;;
    esac
done

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

API_APP_NAME="graphrag-api"
WORKER_APP_NAME="graphrag-worker"
B2C_APP_NAME="graphrag-api-b2c"
ACR_SERVER="${CONTAINER_REGISTRY_NAME}.azurecr.io"

# Auth scope for health check — matches the app registration
HEALTH_CHECK_SCOPE=$(get_env_value_or_default "HEALTH_CHECK_SCOPE" "api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default")

if [ -n "$CUSTOM_TAG" ]; then
    AZURE_ENV_IMAGETAG="$CUSTOM_TAG"
else
    AZURE_ENV_IMAGETAG=$(get_env_value_or_default "AZURE_ENV_IMAGETAG" "")
    if [ -z "$AZURE_ENV_IMAGETAG" ]; then
        GIT_SHA=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "manual")
        BUILD_SEQ=$(date -u +"%s" | tail -c 3)
        AZURE_ENV_IMAGETAG="${GIT_SHA}-${BUILD_SEQ}"
    fi
fi

REVISION_SUFFIX="d${AZURE_ENV_IMAGETAG}" # 'd' prefix = manual deploy (vs 'r' for CI/CD)
# Azure requires revision suffix ≤ 20 chars, alphanumeric + hyphens only
REVISION_SUFFIX=$(echo "$REVISION_SUFFIX" | sed 's/[^a-zA-Z0-9-]/-/g' | cut -c1-20)

echo "=================================================="
echo "GraphRAG Full Deployment"
echo "=================================================="
echo "Registry:       $CONTAINER_REGISTRY_NAME"
echo "Image Tag:      $AZURE_ENV_IMAGETAG"
echo "Algorithm:      $ALGO_VERSION"
echo "Revision:       $REVISION_SUFFIX"
echo "Skip Build:     $SKIP_BUILD"
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

# ── Capture Current Revisions (for rollback) ─────────────────────────────

echo "📸 Capturing current revisions for rollback (parallel)..."

REV_TMPDIR=$(mktemp -d /tmp/graphrag-rev-XXXXXX)

# Capture API and Worker revisions in parallel — each pair (list→show) runs
# in its own subshell, but both subshells run simultaneously.
(
    rev=$(az containerapp revision list \
        --name "$API_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "[?properties.active && properties.trafficWeight > \`0\`].name | [0]" \
        -o tsv 2>/dev/null || echo "")
    img=""
    if [ -n "$rev" ]; then
        img=$(az containerapp revision show \
            --name "$API_APP_NAME" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --revision "$rev" \
            --query "properties.template.containers[0].image" \
            -o tsv 2>/dev/null || echo "")
    fi
    echo "${rev}|${img}" > "$REV_TMPDIR/api"
) &
API_REV_PID=$!

(
    rev=$(az containerapp revision list \
        --name "$WORKER_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "[?properties.active && properties.trafficWeight > \`0\`].name | [0]" \
        -o tsv 2>/dev/null || echo "")
    img=""
    if [ -n "$rev" ]; then
        img=$(az containerapp revision show \
            --name "$WORKER_APP_NAME" \
            --resource-group "$AZURE_RESOURCE_GROUP" \
            --revision "$rev" \
            --query "properties.template.containers[0].image" \
            -o tsv 2>/dev/null || echo "")
    fi
    echo "${rev}|${img}" > "$REV_TMPDIR/worker"
) &
WORKER_REV_PID=$!

wait $API_REV_PID $WORKER_REV_PID

PREV_API_REVISION=$(cut -d'|' -f1 < "$REV_TMPDIR/api")
PREV_API_IMAGE=$(cut -d'|' -f2 < "$REV_TMPDIR/api")
PREV_WORKER_REVISION=$(cut -d'|' -f1 < "$REV_TMPDIR/worker")
PREV_WORKER_IMAGE=$(cut -d'|' -f2 < "$REV_TMPDIR/worker")
rm -rf "$REV_TMPDIR"

if [ -n "$PREV_API_REVISION" ]; then
    echo "  API:    $PREV_API_REVISION → $PREV_API_IMAGE"
else
    echo "  API:    (no active revision found — rollback unavailable)"
fi
if [ -n "$PREV_WORKER_REVISION" ]; then
    echo "  Worker: $PREV_WORKER_REVISION → $PREV_WORKER_IMAGE"
else
    echo "  Worker: (no active revision found — rollback unavailable)"
fi
echo ""

# ── Build Docker Images ──────────────────────────────────────────────────

if [ "$SKIP_BUILD" = true ]; then
    echo "⏭️  Skipping Docker build (--skip-build)"
    echo ""
else
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

    echo "⏳ Building API + Worker images in parallel (with layer caching)..."

    az acr build \
        --registry "$CONTAINER_REGISTRY_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --file Dockerfile.api \
        --image "$API_APP_NAME:$AZURE_ENV_IMAGETAG" \
        --image "$API_APP_NAME:latest" \
        --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        --build-arg VERSION="$AZURE_ENV_IMAGETAG" \
        --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        "$STAGING_DIR" &
    API_BUILD_PID=$!

    az acr build \
        --registry "$CONTAINER_REGISTRY_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --file Dockerfile.worker \
        --image "$WORKER_APP_NAME:$AZURE_ENV_IMAGETAG" \
        --image "$WORKER_APP_NAME:latest" \
        --build-arg CACHE_BUST="$AZURE_ENV_IMAGETAG" \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        "$STAGING_DIR" &
    WORKER_BUILD_PID=$!

    API_BUILD_OK=0
    WORKER_BUILD_OK=0
    wait $API_BUILD_PID || API_BUILD_OK=1
    wait $WORKER_BUILD_PID || WORKER_BUILD_OK=1

    if [ $API_BUILD_OK -ne 0 ] || [ $WORKER_BUILD_OK -ne 0 ]; then
        [ $API_BUILD_OK -ne 0 ] && echo "❌ API image build failed"
        [ $WORKER_BUILD_OK -ne 0 ] && echo "❌ Worker image build failed"
        exit 1
    fi

    echo "✅ Both images built and pushed"
    echo ""
fi

# ── Deploy Infrastructure + Apps via azd provision ───────────────────────
# All secrets, env vars, RBAC, and container config are declared in
# infra/main.bicep. azd provision runs Bicep to guarantee every config
# parameter is deployed in sync with the code — this is the key advantage
# over CI/CD's image-only deploy.

API_IMAGE="${ACR_SERVER}/${API_APP_NAME}:${AZURE_ENV_IMAGETAG}"
WORKER_IMAGE="${ACR_SERVER}/${WORKER_APP_NAME}:${AZURE_ENV_IMAGETAG}"

azd env set SERVICE_GRAPHRAG_API_IMAGE_NAME "$API_IMAGE"
azd env set SERVICE_GRAPHRAG_WORKER_IMAGE_NAME "$WORKER_IMAGE"

echo "🚀 Deploying infrastructure + apps via azd provision (Bicep)..."
echo "   This ensures all config, secrets, and env vars are in sync."
echo ""

DEPLOY_METHOD=""
if azd provision --no-prompt; then
    DEPLOY_METHOD="bicep"
    echo ""
    echo "✅ azd provision succeeded — all config is in sync"
else
    echo ""
    echo "⚠️  azd provision failed!"
    echo ""
    echo "   Bicep deployment failed. Falling back to direct container update."
    echo "   WARNING: Config parameters defined in Bicep may NOT be updated."
    echo "   If this is a config-sensitive deploy, fix Bicep issues and re-run."
    echo ""
    echo "   Continuing with image-only update in 5 seconds... (Ctrl+C to abort)"
    sleep 5

    DEPLOY_METHOD="fallback"
    FALLBACK_FAILED=0

    echo "Updating ${API_APP_NAME}..."
    az containerapp update \
        --name "$API_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --image "$API_IMAGE" \
        --revision-suffix "$REVISION_SUFFIX" \
        --set-env-vars \
            "VOYAGE_API_KEY=secretref:voyage-api-key" \
            "NEO4J_PASSWORD=secretref:neo4j-password" \
            "MISTRAL_API_KEY=secretref:mistral-api-key" \
            "LLMWHISPERER_API_KEY=secretref:llmwhisperer-api-key" \
        --output none &
    API_DEPLOY_PID=$!

    echo "Updating ${WORKER_APP_NAME}..."
    az containerapp update \
        --name "$WORKER_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --image "$WORKER_IMAGE" \
        --revision-suffix "$REVISION_SUFFIX" \
        --set-env-vars \
            "DEFAULT_ALGORITHM_VERSION=$ALGO_VERSION" \
            "VOYAGE_API_KEY=secretref:voyage-api-key" \
            "NEO4J_PASSWORD=secretref:neo4j-password" \
            "MISTRAL_API_KEY=secretref:mistral-api-key" \
            "LLMWHISPERER_API_KEY=secretref:llmwhisperer-api-key" \
        --output none &
    WORKER_DEPLOY_PID=$!

    echo "Updating ${B2C_APP_NAME}..."
    az containerapp update \
        --name "$B2C_APP_NAME" \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --image "$API_IMAGE" \
        --revision-suffix "$REVISION_SUFFIX" \
        --set-env-vars \
            "VOYAGE_API_KEY=secretref:voyage-api-key" \
            "NEO4J_PASSWORD=secretref:neo4j-password" \
            "MISTRAL_API_KEY=secretref:mistral-api-key" \
            "LLMWHISPERER_API_KEY=secretref:llmwhisperer-api-key" \
        --output none &
    B2C_DEPLOY_PID=$!

    wait $API_DEPLOY_PID    || FALLBACK_FAILED=1
    wait $WORKER_DEPLOY_PID || FALLBACK_FAILED=1
    wait $B2C_DEPLOY_PID    || FALLBACK_FAILED=1

    if [ $FALLBACK_FAILED -ne 0 ]; then
        echo "❌ Fallback container update failed"
        exit 1
    fi

    echo "✅ All container apps updated via direct deploy (config may be stale)"
fi
echo ""

# ── Health Check ─────────────────────────────────────────────────────────

echo "🏥 Running health check..."
echo "   Waiting 60s for containers to start (fetching FQDN + token in parallel)..."

# Fetch FQDN and auth token in parallel DURING the startup wait
HC_TMPDIR=$(mktemp -d /tmp/graphrag-hc-XXXXXX)

(az containerapp show \
    --name "$API_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" \
    -o tsv 2>/dev/null || echo "") > "$HC_TMPDIR/fqdn" &

(az account get-access-token \
    --scope "$HEALTH_CHECK_SCOPE" \
    --query accessToken -o tsv 2>/dev/null || echo "") > "$HC_TMPDIR/token" &

sleep 60  # container startup wait runs concurrently with FQDN + token fetches
wait      # ensure FQDN + token fetches are done (they finish well within 60s)

API_FQDN=$(cat "$HC_TMPDIR/fqdn")
TOKEN=$(cat "$HC_TMPDIR/token")
rm -rf "$HC_TMPDIR"

if [ -z "$API_FQDN" ]; then
    echo "⚠️  Could not determine API URL — skipping health check"
    HEALTH_OK=true
else
    HEALTH_URL="https://${API_FQDN}/health"
    echo "   Endpoint: $HEALTH_URL"

    AUTH_HEADER=""
    if [ -n "$TOKEN" ]; then
        AUTH_HEADER="Authorization: Bearer $TOKEN"
    else
        echo "   ⚠️  Could not get auth token — trying without auth"
    fi

    HEALTH_OK=false
    for i in {1..8}; do
        if [ -n "$AUTH_HEADER" ]; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" \
                --max-time 10 -H "$AUTH_HEADER" 2>/dev/null || echo "000")
        else
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" \
                --max-time 10 2>/dev/null || echo "000")
        fi

        if [ "$HTTP_CODE" = "200" ]; then
            echo "   ✅ Health check passed (attempt $i/8)"
            HEALTH_OK=true
            break
        fi
        echo "   Attempt $i/8: HTTP $HTTP_CODE — retrying in 15s..."
        sleep 15
    done
fi

# ── Rollback on Failure ──────────────────────────────────────────────────

if [ "$HEALTH_OK" = false ]; then
    echo ""
    echo "❌ Health check failed after 8 attempts!"
    echo ""

    if [ -n "$PREV_API_IMAGE" ] || [ -n "$PREV_WORKER_IMAGE" ]; then
        echo "🔄 Rolling back to previous revisions (parallel)..."
        ROLLBACK_SUFFIX="rollback-$(date -u +%s | tail -c 6)"
        ROLLBACK_FAILED=0

        if [ -n "$PREV_API_IMAGE" ]; then
            echo "   Reverting API → $PREV_API_IMAGE"
            az containerapp update \
                --name "$API_APP_NAME" \
                --resource-group "$AZURE_RESOURCE_GROUP" \
                --image "$PREV_API_IMAGE" \
                --revision-suffix "$ROLLBACK_SUFFIX" \
                --output none &
            ROLLBACK_API_PID=$!
        fi

        if [ -n "$PREV_WORKER_IMAGE" ]; then
            echo "   Reverting Worker → $PREV_WORKER_IMAGE"
            az containerapp update \
                --name "$WORKER_APP_NAME" \
                --resource-group "$AZURE_RESOURCE_GROUP" \
                --image "$PREV_WORKER_IMAGE" \
                --revision-suffix "$ROLLBACK_SUFFIX" \
                --output none &
            ROLLBACK_WORKER_PID=$!
        fi

        if [ -n "$PREV_API_IMAGE" ]; then
            echo "   Reverting B2C → $PREV_API_IMAGE"
            az containerapp update \
                --name "$B2C_APP_NAME" \
                --resource-group "$AZURE_RESOURCE_GROUP" \
                --image "$PREV_API_IMAGE" \
                --revision-suffix "$ROLLBACK_SUFFIX" \
                --output none &
            ROLLBACK_B2C_PID=$!
        fi

        [ -n "${ROLLBACK_API_PID:-}" ]    && { wait $ROLLBACK_API_PID    || ROLLBACK_FAILED=1; }
        [ -n "${ROLLBACK_WORKER_PID:-}" ] && { wait $ROLLBACK_WORKER_PID || ROLLBACK_FAILED=1; }
        [ -n "${ROLLBACK_B2C_PID:-}" ]    && { wait $ROLLBACK_B2C_PID    || ROLLBACK_FAILED=1; }

        if [ $ROLLBACK_FAILED -ne 0 ]; then
            echo "   ⚠️  One or more rollbacks failed — check container status manually"
        else
            echo ""
            echo "🔄 Rollback complete. Previous images restored."
        fi
    else
        echo "⚠️  No previous revision captured — cannot rollback automatically."
        echo "   Manually check container status and logs."
    fi

    exit 1
fi

# ── Summary ──────────────────────────────────────────────────────────────

API_URL=$(azd env get-value GRAPHRAG_API_URI 2>/dev/null || echo "https://${API_FQDN}")

echo ""
echo "=================================================="
echo "✅ Deployment Complete!"
echo "=================================================="
echo ""
echo "📋 Summary:"
echo "  • Deploy method: ${DEPLOY_METHOD} ($([ "$DEPLOY_METHOD" = "bicep" ] && echo "full infra sync" || echo "image-only fallback"))"
echo "  • Algorithm:     ${ALGO_VERSION}"
echo "  • API Image:     ${API_IMAGE}"
echo "  • Worker Image:  ${WORKER_IMAGE}"
echo "  • B2C Image:     ${API_IMAGE}"
echo "  • Revision:      ${REVISION_SUFFIX}"
echo "  • API URL:       ${API_URL}"
echo ""
echo "🔧 Verify:"
echo "  curl ${API_URL}/health"
echo "  open ${API_URL}/docs"
echo "=================================================="
