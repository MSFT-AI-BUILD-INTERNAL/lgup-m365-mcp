#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
Usage: ./deploy-app.sh [--param-file FILE] [--deployment-name NAME] [--resource-group NAME] [--container-app NAME] [--registry-name NAME] [--image IMAGE] [--build-context DIR] [--skip-build]

Environment variables:
  SUBSCRIPTION_ID       Optional; if set, az account set --subscription is executed
  PARAM_FILE            Optional; same as --param-file
  DEPLOYMENT_NAME       Optional; same as --deployment-name
  RESOURCE_GROUP_NAME   Optional; same as --resource-group
  CONTAINER_APP_NAME    Optional; same as --container-app
  CONTAINER_REGISTRY_NAME Optional; same as --registry-name
  CONTAINER_IMAGE       Optional; same as --image
  BUILD_CONTEXT         Optional; same as --build-context (default: ./app)
  SKIP_BUILD            Optional; set to true to skip ACR build/push

Behavior:
  - Uses main.local.bicepparam by default when present, otherwise main.dev.bicepparam.
  - Reads ACR name / target image from CLI, environment variables, or the parameter file.
  - Builds and pushes the image to the pre-created ACR unless --skip-build is used.
  - Configures the existing Container App to use the pre-created ACR via its user-assigned identity.
  - Safe to rerun: it rebuilds/pushes the same image tag and reapplies the same registry/image settings.
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

parse_string_param() {
  local file="$1"
  local name="$2"
  python - "$file" "$name" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text()
name = re.escape(sys.argv[2])
match = re.search(rf"^\s*param\s+{name}\s*=\s*'([^']*)'", text, re.MULTILINE)
print(match.group(1) if match else "")
PY
}

PARAM_FILE="${PARAM_FILE:-}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-lgup-mcp-deploy}"
RESOURCE_GROUP_NAME="${RESOURCE_GROUP_NAME:-}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-}"
CONTAINER_REGISTRY_NAME="${CONTAINER_REGISTRY_NAME:-}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-}"
BUILD_CONTEXT="${BUILD_CONTEXT:-./app}"
SKIP_BUILD="$(parse_bool "${SKIP_BUILD:-false}")"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --param-file)
      PARAM_FILE="$2"
      shift 2
      ;;
    --deployment-name)
      DEPLOYMENT_NAME="$2"
      shift 2
      ;;
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
    --image)
      CONTAINER_IMAGE="$2"
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

if [[ -z "$PARAM_FILE" ]]; then
  if [[ -f main.local.bicepparam ]]; then
    PARAM_FILE="main.local.bicepparam"
  else
    PARAM_FILE="main.dev.bicepparam"
  fi
fi

if [[ ! -f "$PARAM_FILE" ]]; then
  echo "Error: parameter file not found: $PARAM_FILE" >&2
  exit 1
fi

if [[ -n "${SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$SUBSCRIPTION_ID"
fi

if [[ -z "$RESOURCE_GROUP_NAME" ]]; then
  RESOURCE_GROUP_NAME="$(parse_string_param "$PARAM_FILE" resourceGroupName)"
fi

if [[ -z "$CONTAINER_REGISTRY_NAME" ]]; then
  CONTAINER_REGISTRY_NAME="$(parse_string_param "$PARAM_FILE" containerRegistryName)"
fi

if [[ -z "$CONTAINER_IMAGE" ]]; then
  CONTAINER_IMAGE="$(parse_string_param "$PARAM_FILE" containerImage)"
fi

if [[ -z "$CONTAINER_APP_NAME" ]]; then
  CONTAINER_APP_NAME="$(
    az deployment sub show \
      --name "$DEPLOYMENT_NAME" \
      --query "properties.outputs.containerAppName.value" \
      -o tsv
  )"
fi

MANAGED_IDENTITY_ID="$(
  az deployment sub show \
    --name "$DEPLOYMENT_NAME" \
    --query "properties.outputs.managedIdentityId.value" \
    -o tsv
)"

require_value "resource group name" "$RESOURCE_GROUP_NAME"
require_value "container app name" "$CONTAINER_APP_NAME"
require_value "container registry name" "$CONTAINER_REGISTRY_NAME"
require_value "container image" "$CONTAINER_IMAGE"
require_value "managed identity id" "$MANAGED_IDENTITY_ID"
require_value "build context" "$BUILD_CONTEXT"

PRE_UPDATE_READY_REVISION="$(
  az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --query "properties.latestReadyRevisionName" \
    -o tsv
)"

CONTAINER_REGISTRY_SERVER="$(
  az acr show \
    --name "$CONTAINER_REGISTRY_NAME" \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --query loginServer \
    -o tsv
)"

require_value "container registry login server" "$CONTAINER_REGISTRY_SERVER"

if [[ "$CONTAINER_IMAGE" == "${CONTAINER_REGISTRY_SERVER}/"* ]]; then
  ACR_IMAGE="${CONTAINER_IMAGE#${CONTAINER_REGISTRY_SERVER}/}"
  FULL_CONTAINER_IMAGE="$CONTAINER_IMAGE"
elif [[ "$CONTAINER_IMAGE" == */* ]]; then
  echo "Error: image '$CONTAINER_IMAGE' does not belong to registry '$CONTAINER_REGISTRY_SERVER'." >&2
  exit 1
else
  ACR_IMAGE="$CONTAINER_IMAGE"
  FULL_CONTAINER_IMAGE="${CONTAINER_REGISTRY_SERVER}/${CONTAINER_IMAGE}"
fi

if [[ ! -d "$BUILD_CONTEXT" ]]; then
  echo "Error: build context directory not found: $BUILD_CONTEXT" >&2
  exit 1
fi

echo "Using parameter file: $PARAM_FILE"
echo "Deployment name: $DEPLOYMENT_NAME"
echo "Resource group: $RESOURCE_GROUP_NAME"
echo "Container app: $CONTAINER_APP_NAME"
echo "Registry: $CONTAINER_REGISTRY_SERVER"
echo "Image: $FULL_CONTAINER_IMAGE"
echo "Build context: $BUILD_CONTEXT"

if [[ "$SKIP_BUILD" != "true" ]]; then
  echo "Building and pushing image to ACR..."
  az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --image "$ACR_IMAGE" \
    "$BUILD_CONTEXT" \
    --only-show-errors >/dev/null
else
  echo "Skipping ACR build/push as requested."
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
