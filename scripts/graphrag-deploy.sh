#!/bin/bash
set -euo pipefail

# Lightweight deployment helper for Graphrag.
# Wraps canonical build/push/update flow in `docs/docker-build.sh` and
# provides a quick "restart" shortcut for in-place container app restarts.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_BUILD_SCRIPT="$REPO_ROOT/docs/docker-build.sh"

usage() {
  cat <<EOF
Usage: $(basename "$0") [build|restart|help] [args...]

Commands:
  build [args...]   Run the canonical build+push+update script (for full deploy).
  restart           Restart the API container app revision (fast, no build).
  help              Show this message.

Examples:
  # Full deploy (build, push, update):
  ./scripts/graphrag-deploy.sh build

  # Restart latest running revision (fast):
  ./scripts/graphrag-deploy.sh restart

Note: `docs/docker-build.sh` expects azd env values to be configured (see README).
EOF
}

cmd="${1:-help}"
case "$cmd" in
  build)
    shift || true
    if [ ! -x "$DOCKER_BUILD_SCRIPT" ]; then
      echo "ERROR: $DOCKER_BUILD_SCRIPT not found or not executable" >&2
      exit 2
    fi
    echo "Running canonical build+push+update script: $DOCKER_BUILD_SCRIPT"
    exec "$DOCKER_BUILD_SCRIPT" "$@"
    ;;
  restart)
    # Needs: CONTAINER_API_APP_NAME, AZURE_RESOURCE_GROUP
    APP_NAME="${CONTAINER_API_APP_NAME:-graphrag-orchestration}"
    RG="${AZURE_RESOURCE_GROUP:-rg-graphrag-feature}"
    echo "Restarting Container App: $APP_NAME (resource group: $RG)"
    az containerapp revision restart --name "$APP_NAME" --resource-group "$RG" --only-show-errors
    ;;
  help|--help|-h)
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage
    exit 1
    ;;
esac
