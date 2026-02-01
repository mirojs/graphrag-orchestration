#!/usr/bin/env bash
set -euo pipefail

workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$workspace_dir"

api_image_name="$(azd env get-values --output json | jq -r '.SERVICE_GRAPHRAG_API_IMAGE_NAME // empty')"
worker_image_name="$(azd env get-values --output json | jq -r '.SERVICE_GRAPHRAG_WORKER_IMAGE_NAME // empty')"

if [[ -z "$api_image_name" ]]; then
  echo "SERVICE_GRAPHRAG_API_IMAGE_NAME is not set. Run 'azd package' first." >&2
  exit 1
fi

azd env set serviceGraphragApiImageName "$api_image_name"
echo "Set serviceGraphragApiImageName=$api_image_name"

if [[ -z "$worker_image_name" ]]; then
  derived_worker_image_name="${api_image_name/graphrag-api-default/graphrag-worker-default}"
  if [[ "$derived_worker_image_name" == "$api_image_name" ]]; then
    echo "Unable to derive worker image name from API image name: $api_image_name" >&2
    exit 1
  fi
  azd env set SERVICE_GRAPHRAG_WORKER_IMAGE_NAME "$derived_worker_image_name"
  azd env set serviceGraphragWorkerImageName "$derived_worker_image_name"
  echo "Set SERVICE_GRAPHRAG_WORKER_IMAGE_NAME=$derived_worker_image_name"
  echo "Set serviceGraphragWorkerImageName=$derived_worker_image_name"
else
  echo "SERVICE_GRAPHRAG_WORKER_IMAGE_NAME already set."
  azd env set serviceGraphragWorkerImageName "$worker_image_name"
  echo "Set serviceGraphragWorkerImageName=$worker_image_name"
fi
