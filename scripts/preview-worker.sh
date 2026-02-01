#!/usr/bin/env bash
#
# Preview Worker Management Script
#
# Manages a separate worker container for testing algorithm versions before production.
# Enables side-by-side testing of v3 while production runs v2.
#
# Usage:
#   ./scripts/preview-worker.sh create v3        # Deploy preview worker with v3
#   ./scripts/preview-worker.sh status           # Check preview worker status
#   ./scripts/preview-worker.sh logs             # Stream preview worker logs
#   ./scripts/preview-worker.sh promote          # Promote preview to production
#   ./scripts/preview-worker.sh delete           # Remove preview worker
#
# Architecture:
#   - Production:  graphrag-worker (DEFAULT_ALGORITHM_VERSION=v2)
#   - Preview:     graphrag-worker-preview (DEFAULT_ALGORITHM_VERSION=v3)
#   - API routes X-Algorithm-Version: v3 requests to preview worker
#

set -euo pipefail

# Configuration
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-graphrag-feature}"
ACR_NAME="${ACR_NAME:-graphragacr12153}"
ENVIRONMENT="${CONTAINER_APP_ENVIRONMENT:-}"
WORKER_NAME="graphrag-worker"
PREVIEW_NAME="graphrag-worker-preview"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

# Get Container App Environment if not set
get_environment() {
    if [[ -z "$ENVIRONMENT" ]]; then
        ENVIRONMENT=$(az containerapp show \
            --name "$WORKER_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --query "properties.environmentId" -o tsv 2>/dev/null)
        
        if [[ -z "$ENVIRONMENT" ]]; then
            log_error "Could not determine Container App Environment"
            log_info "Set CONTAINER_APP_ENVIRONMENT or ensure $WORKER_NAME exists"
            exit 1
        fi
    fi
}

# Get current worker image
get_worker_image() {
    az containerapp show \
        --name "$WORKER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.template.containers[0].image" -o tsv 2>/dev/null
}

# Check if preview worker exists
preview_exists() {
    az containerapp show \
        --name "$PREVIEW_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        &>/dev/null
}

# ============================================================================
# Commands
# ============================================================================

cmd_create() {
    local algo_version="${1:-v3}"
    
    log_info "Creating preview worker with DEFAULT_ALGORITHM_VERSION=$algo_version"
    
    get_environment
    
    # Check if already exists
    if preview_exists; then
        log_warn "Preview worker already exists. Use 'delete' first or 'update'."
        exit 1
    fi
    
    # Get current production worker image
    local image
    image=$(get_worker_image)
    
    if [[ -z "$image" ]]; then
        log_error "Could not get current worker image. Is $WORKER_NAME deployed?"
        exit 1
    fi
    
    log_info "Using image: $image"
    log_info "Environment: $ENVIRONMENT"
    
    # Create preview worker with same config but different algorithm version
    az containerapp create \
        --name "$PREVIEW_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --environment "$ENVIRONMENT" \
        --image "$image" \
        --ingress internal \
        --target-port 8000 \
        --cpu 1 \
        --memory 2Gi \
        --min-replicas 1 \
        --max-replicas 1 \
        --env-vars \
            "DEFAULT_ALGORITHM_VERSION=$algo_version" \
            "ALGORITHM_V3_PREVIEW_ENABLED=true" \
        --query "properties.configuration.ingress.fqdn" -o tsv
    
    # Get the internal URL
    local preview_url
    preview_url=$(az containerapp show \
        --name "$PREVIEW_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.configuration.ingress.fqdn" -o tsv)
    
    log_success "Preview worker created!"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Preview Worker Configuration"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Name:      $PREVIEW_NAME"
    echo "  Algorithm: $algo_version"
    echo "  URL:       http://$PREVIEW_NAME (internal)"
    echo ""
    echo "  To enable preview routing, set in API environment:"
    echo "    WORKER_PREVIEW_URL=http://$PREVIEW_NAME"
    echo "    ALGORITHM_V3_PREVIEW_ENABLED=true"
    echo ""
    echo "  Then requests with X-Algorithm-Version: v3 will route to preview."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

cmd_update() {
    local algo_version="${1:-v3}"
    
    if ! preview_exists; then
        log_warn "Preview worker doesn't exist. Use 'create' first."
        exit 1
    fi
    
    log_info "Updating preview worker to $algo_version..."
    
    # Get latest production image
    local image
    image=$(get_worker_image)
    
    az containerapp update \
        --name "$PREVIEW_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$image" \
        --set-env-vars "DEFAULT_ALGORITHM_VERSION=$algo_version"
    
    log_success "Preview worker updated to $algo_version"
}

cmd_status() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Worker Status"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Production worker
    echo ""
    echo "  📦 Production Worker ($WORKER_NAME)"
    if az containerapp show --name "$WORKER_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
        local prod_algo prod_image prod_replicas
        prod_algo=$(az containerapp show --name "$WORKER_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].env[?name=='DEFAULT_ALGORITHM_VERSION'].value | [0]" -o tsv 2>/dev/null || echo "v2")
        prod_image=$(az containerapp show --name "$WORKER_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].image" -o tsv | rev | cut -d: -f1 | rev)
        prod_replicas=$(az containerapp show --name "$WORKER_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.scale.minReplicas" -o tsv 2>/dev/null || echo "?")
        
        echo "     Status:    ${GREEN}Running${NC}"
        echo "     Algorithm: ${prod_algo:-v2}"
        echo "     Image Tag: $prod_image"
        echo "     Replicas:  $prod_replicas"
    else
        echo "     Status:    ${RED}Not Found${NC}"
    fi
    
    # Preview worker
    echo ""
    echo "  🧪 Preview Worker ($PREVIEW_NAME)"
    if preview_exists; then
        local prev_algo prev_image prev_replicas
        prev_algo=$(az containerapp show --name "$PREVIEW_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].env[?name=='DEFAULT_ALGORITHM_VERSION'].value | [0]" -o tsv 2>/dev/null || echo "v3")
        prev_image=$(az containerapp show --name "$PREVIEW_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].image" -o tsv | rev | cut -d: -f1 | rev)
        prev_replicas=$(az containerapp show --name "$PREVIEW_NAME" --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.scale.minReplicas" -o tsv 2>/dev/null || echo "?")
        
        echo "     Status:    ${GREEN}Running${NC}"
        echo "     Algorithm: ${prev_algo:-v3}"
        echo "     Image Tag: $prev_image"
        echo "     Replicas:  $prev_replicas"
    else
        echo "     Status:    ${YELLOW}Not Deployed${NC}"
        echo "     Run: ./scripts/preview-worker.sh create v3"
    fi
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

cmd_logs() {
    if ! preview_exists; then
        log_error "Preview worker doesn't exist"
        exit 1
    fi
    
    log_info "Streaming logs from $PREVIEW_NAME..."
    az containerapp logs show \
        --name "$PREVIEW_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --follow
}

cmd_promote() {
    if ! preview_exists; then
        log_error "Preview worker doesn't exist. Nothing to promote."
        exit 1
    fi
    
    log_warn "This will update production worker to use the preview algorithm version."
    read -p "Continue? (y/N) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Aborted"
        exit 0
    fi
    
    # Get preview algorithm version
    local preview_algo
    preview_algo=$(az containerapp show \
        --name "$PREVIEW_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "properties.template.containers[0].env[?name=='DEFAULT_ALGORITHM_VERSION'].value | [0]" -o tsv)
    
    log_info "Promoting $preview_algo to production..."
    
    # Update production worker
    az containerapp update \
        --name "$WORKER_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --set-env-vars "DEFAULT_ALGORITHM_VERSION=$preview_algo"
    
    log_success "Production worker updated to $preview_algo"
    log_info "You can now delete the preview worker: ./scripts/preview-worker.sh delete"
}

cmd_delete() {
    if ! preview_exists; then
        log_warn "Preview worker doesn't exist"
        exit 0
    fi
    
    log_warn "This will delete the preview worker: $PREVIEW_NAME"
    read -p "Continue? (y/N) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Aborted"
        exit 0
    fi
    
    log_info "Deleting preview worker..."
    az containerapp delete \
        --name "$PREVIEW_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --yes
    
    log_success "Preview worker deleted"
    log_info "Remember to remove WORKER_PREVIEW_URL from API environment"
}

cmd_help() {
    cat << EOF
Preview Worker Management Script

Manages a separate worker container for testing algorithm versions before production.

USAGE:
    ./scripts/preview-worker.sh <command> [args]

COMMANDS:
    create <version>    Create preview worker with specified algorithm version (default: v3)
    update <version>    Update preview worker to new version
    status              Show status of production and preview workers
    logs                Stream logs from preview worker
    promote             Promote preview version to production
    delete              Remove preview worker

EXAMPLES:
    # Deploy v3 for testing
    ./scripts/preview-worker.sh create v3
    
    # Check status
    ./scripts/preview-worker.sh status
    
    # After successful testing, promote to production
    ./scripts/preview-worker.sh promote
    
    # Or delete if v3 isn't ready
    ./scripts/preview-worker.sh delete

ENVIRONMENT VARIABLES:
    AZURE_RESOURCE_GROUP           Resource group (default: rg-graphrag-feature)
    ACR_NAME                       Container registry (default: graphragacr12153)
    CONTAINER_APP_ENVIRONMENT      Container Apps environment ID (auto-detected)

EOF
}

# ============================================================================
# Main
# ============================================================================

main() {
    local command="${1:-help}"
    shift || true
    
    case "$command" in
        create)  cmd_create "$@" ;;
        update)  cmd_update "$@" ;;
        status)  cmd_status ;;
        logs)    cmd_logs ;;
        promote) cmd_promote ;;
        delete)  cmd_delete ;;
        help|--help|-h) cmd_help ;;
        *)
            log_error "Unknown command: $command"
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
