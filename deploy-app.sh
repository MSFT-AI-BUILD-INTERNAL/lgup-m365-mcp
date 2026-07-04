#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
Usage: ./deploy-app.sh [OPTIONS]

Deploys the latest container image to an existing Azure Container App.
No Bicep dependency — assumes ACR and Container App are already provisioned.

Options:
  --resource-group NAME     Target resource group name (required)
  --container-app NAME      Container App name (required)
  --registry-name NAME      ACR name (required)
  --image-name NAME         Container image name without tag (required; tag is always 'latest')
  --managed-identity-id ID  User-assigned managed identity resource ID (required)
  --build-context DIR       Docker build context directory (default: ./app)
  --skip-build              Skip ACR build/push (use existing 'latest' image in ACR)
  -h, --help                Show this help message

Environment variables (same precedence as CLI options):
  SUBSCRIPTION_ID           Optional; if set, az account set --subscription is executed
  RESOURCE_GROUP_NAME       Optional; same as --resource-group
  CONTAINER_APP_NAME        Optional; same as --container-app
  CONTAINER_REGISTRY_NAME   Optional; same as --registry-name
  CONTAINER_IMAGE_NAME      Optional; same as --image-name
  MANAGED_IDENTITY_ID       Optional; same as --managed-identity-id
  BUILD_CONTEXT             Optional; same as --build-context (default: ./app)
  SKIP_BUILD                Optional; set to true to skip ACR build/push

Examples:
  # Build and deploy latest image
  ./deploy-app.sh \
    --resource-group rg-ms-azure-ax-prd \
    --container-app lgmcp-prd-mcp-api \
    --registry-name lgmcpprdacr \
    --image-name hanik-mcp-server \
    --managed-identity-id /subscriptions/.../resourceGroups/.../providers/Microsoft.ManagedIdentity/userAssignedIdentities/lgmcp-prd-uami

  # Deploy existing latest image (skip build)
  ./deploy-app.sh \
    --resource-group rg-ms-azure-ax-prd \
    --container-app lgmcp-prd-mcp-api \
    --registry-name lgmcpprdacr \
    --image-name hanik-mcp-server \
    --managed-identity-id /subscriptions/.../resourceGroups/.../providers/Microsoft.ManagedIdentity/userAssignedIdentities/lgmcp-prd-uami \
    --skip-build
USAGE
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: required command not found: $1" >&2
    exit 1
  }
}

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "Error: $name is required." >&2
    exit 1
  fi
}

print_health_diagnostics() {
  local resource_group="$1"
  local container_app="$2"

  cat >&2 <<EOF
Health validation failed for Container App '${container_app}'.
Troubleshooting commands:
  az containerapp show --name "${container_app}" --resource-group "${resource_group}" -o yaml
  az containerapp revision list --name "${container_app}" --resource-group "${resource_group}" -o table
  az containerapp logs show --name "${container_app}" --resource-group "${resource_group}" --type system --tail 200
  az containerapp logs show --name "${container_app}" --resource-group "${resource_group}" --type console --tail 200
  az monitor activity-log list --resource-group "${resource_group}" --offset 1h --max-events 50 -o table
EOF
}

parse_bool() {
  local value="${1:-false}"
  case "${value,,}" in
    1|true|yes|y) echo "true" ;;
    0|false|no|n|"") echo "false" ;;
    *)
      echo "Error: invalid boolean value: $value" >&2
      exit 1
      ;;
  esac
}

RESOURCE_GROUP_NAME="${RESOURCE_GROUP_NAME:-}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-}"
CONTAINER_REGISTRY_NAME="${CONTAINER_REGISTRY_NAME:-}"
CONTAINER_IMAGE_NAME="${CONTAINER_IMAGE_NAME:-}"
MANAGED_IDENTITY_ID="${MANAGED_IDENTITY_ID:-}"
BUILD_CONTEXT="${BUILD_CONTEXT:-./app}"
SKIP_BUILD="$(parse_bool "${SKIP_BUILD:-false}")"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group)
      RESOURCE_GROUP_NAME="$2"
      shift 2
      ;;
    --container-app)
      CONTAINER_APP_NAME="$2"
      shift 2
      ;;
    --registry-name)
      CONTAINER_REGISTRY_NAME="$2"
      shift 2
      ;;
    --image-name)
      CONTAINER_IMAGE_NAME="$2"
      shift 2
      ;;
    --managed-identity-id)
      MANAGED_IDENTITY_ID="$2"
      shift 2
      ;;
    --build-context)
      BUILD_CONTEXT="$2"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_command az

if [[ -n "${SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$SUBSCRIPTION_ID"
fi

require_value "resource group name" "$RESOURCE_GROUP_NAME"
require_value "container app name" "$CONTAINER_APP_NAME"
require_value "container registry name" "$CONTAINER_REGISTRY_NAME"
require_value "container image name" "$CONTAINER_IMAGE_NAME"
require_value "managed identity id" "$MANAGED_IDENTITY_ID"
require_value "build context" "$BUILD_CONTEXT"

PRE_UPDATE_READY_REVISION="$(
  az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --query "properties.latestReadyRevisionName" \
    -o tsv
)"

CONTAINER_REGISTRY_SERVER="${CONTAINER_REGISTRY_NAME}.azurecr.io"
ACR_IMAGE="${CONTAINER_IMAGE_NAME}:latest"
FULL_CONTAINER_IMAGE="${CONTAINER_REGISTRY_SERVER}/${ACR_IMAGE}"

if [[ "$SKIP_BUILD" != "true" && ! -d "$BUILD_CONTEXT" ]]; then
  echo "Error: build context directory not found: $BUILD_CONTEXT" >&2
  exit 1
fi

echo "Resource group: $RESOURCE_GROUP_NAME"
echo "Container app: $CONTAINER_APP_NAME"
echo "Registry: $CONTAINER_REGISTRY_SERVER"
echo "Image: $FULL_CONTAINER_IMAGE"
echo "Managed identity: $MANAGED_IDENTITY_ID"
echo "Build context: $BUILD_CONTEXT"
echo "Skip build: $SKIP_BUILD"

if [[ "$SKIP_BUILD" != "true" ]]; then
  echo "Building and pushing image to ACR (tag: latest)..."
  az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --image "$ACR_IMAGE" \
    "$BUILD_CONTEXT" \
    --only-show-errors >/dev/null
else
  echo "Skipping ACR build/push — using existing 'latest' image in ACR."
fi

az containerapp registry set \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP_NAME" \
  --server "$CONTAINER_REGISTRY_SERVER" \
  --identity "$MANAGED_IDENTITY_ID" \
  --only-show-errors >/dev/null

az containerapp update \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP_NAME" \
  --image "$FULL_CONTAINER_IMAGE" \
  --only-show-errors >/dev/null

APP_URL="$(
  az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --query "properties.configuration.ingress.fqdn" \
    -o tsv
)"

HEALTH_MAX_ATTEMPTS=20
HEALTH_RETRY_DELAY_SECONDS=5
HEALTH_CHECK_PATH="/health"
HEALTH_CHECK_PASSED="false"

if command -v curl >/dev/null 2>&1 && [[ -n "$APP_URL" ]]; then
  HEALTH_CHECK_URL="https://${APP_URL}${HEALTH_CHECK_PATH}"
  echo "Validating app health at ${HEALTH_CHECK_PATH}..."
  for attempt in $(seq 1 "$HEALTH_MAX_ATTEMPTS"); do
    if curl --fail --silent --show-error --max-time 10 "$HEALTH_CHECK_URL" >/dev/null; then
      HEALTH_CHECK_PASSED="true"
      break
    fi

    if [[ "$attempt" -lt "$HEALTH_MAX_ATTEMPTS" ]]; then
      sleep "$HEALTH_RETRY_DELAY_SECONDS"
    fi
  done
else
  echo "curl unavailable or ingress URL missing; validating Container App readiness via Azure status..."
  for attempt in $(seq 1 "$HEALTH_MAX_ATTEMPTS"); do
    RUNNING_STATUS="$(
      az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --query "properties.runningStatus" \
        -o tsv
    )"
    PROVISIONING_STATE="$(
      az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --query "properties.provisioningState" \
        -o tsv
    )"
    READY_REVISION="$(
      az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --query "properties.latestReadyRevisionName" \
        -o tsv
    )"

    if [[ "$RUNNING_STATUS" == "Running" && "$PROVISIONING_STATE" == "Succeeded" && -n "$READY_REVISION" ]]; then
      HEALTH_CHECK_PASSED="true"
      break
    fi

    if [[ "$attempt" -lt "$HEALTH_MAX_ATTEMPTS" ]]; then
      sleep "$HEALTH_RETRY_DELAY_SECONDS"
    fi
  done
fi

if [[ "$HEALTH_CHECK_PASSED" != "true" ]]; then
  echo "Previous ready revision: ${PRE_UPDATE_READY_REVISION:-<none>}" >&2
  if [[ -n "${READY_REVISION:-}" ]]; then
    echo "Current ready revision: ${READY_REVISION}" >&2
  fi
  print_health_diagnostics "$RESOURCE_GROUP_NAME" "$CONTAINER_APP_NAME"
  exit 1
fi

echo "Updated Container App image successfully."
echo "App URL: https://${APP_URL}"
