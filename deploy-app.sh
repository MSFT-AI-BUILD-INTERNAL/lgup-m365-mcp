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
  --managed-identity-id ID  Managed identity for ACR pull. Use a UAMI resource ID
                            or "system" for system-assigned identity (default: system)
  --build-context DIR       Docker build context directory (default: ./app)
  --skip-build              Skip ACR build/push (use existing 'latest' image in ACR)
  --storage-account-url URL Azure Blob Storage account URL (sets AZURE_STORAGE_ACCOUNT_URL env var)
  --storage-container NAME  Blob container name (default: uploads)
  -h, --help                Show this help message

Environment variables (same precedence as CLI options):
  SUBSCRIPTION_ID           Optional; if set, az account set --subscription is executed
  RESOURCE_GROUP_NAME       Optional; same as --resource-group
  CONTAINER_APP_NAME        Optional; same as --container-app
  CONTAINER_REGISTRY_NAME   Optional; same as --registry-name
  CONTAINER_IMAGE_NAME      Optional; same as --image-name
  MANAGED_IDENTITY_ID       Optional; same as --managed-identity-id (default: system)
  BUILD_CONTEXT             Optional; same as --build-context (default: ./app)
  SKIP_BUILD                Optional; set to true to skip ACR build/push
  AZURE_STORAGE_ACCOUNT_URL Optional; same as --storage-account-url
  AZURE_STORAGE_CONTAINER   Optional; same as --storage-container (default: uploads)

Examples:
  # Build and deploy with system-assigned managed identity (default)
  ./deploy-app.sh \
    --resource-group rg-ms-azure-ax-prd \
    --container-app lgmcp-prd-mcp-api \
    --registry-name lgmcpprdacr \
    --image-name lgup-mcp-server

  # Build and deploy with user-assigned managed identity
  ./deploy-app.sh \
    --resource-group rg-ms-azure-ax-prd \
    --container-app lgmcp-prd-mcp-api \
    --registry-name lgmcpprdacr \
    --image-name lgup-mcp-server \
    --managed-identity-id /subscriptions/.../resourceGroups/.../providers/Microsoft.ManagedIdentity/userAssignedIdentities/lgmcp-prd-uami

  # Deploy existing latest image (skip build)
  ./deploy-app.sh \
    --resource-group rg-ms-azure-ax-prd \
    --container-app lgmcp-prd-mcp-api \
    --registry-name lgmcpprdacr \
    --image-name lgup-mcp-server \
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
MANAGED_IDENTITY_ID="${MANAGED_IDENTITY_ID:-system}"
BUILD_CONTEXT="${BUILD_CONTEXT:-./app}"
SKIP_BUILD="$(parse_bool "${SKIP_BUILD:-false}")"
AZURE_STORAGE_ACCOUNT_URL="${AZURE_STORAGE_ACCOUNT_URL:-}"
AZURE_STORAGE_CONTAINER="${AZURE_STORAGE_CONTAINER:-uploads}"

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
    --storage-account-url)
      AZURE_STORAGE_ACCOUNT_URL="$2"
      shift 2
      ;;
    --storage-container)
      AZURE_STORAGE_CONTAINER="$2"
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

# Normalize managed identity: accept "system", a full resource ID (/subscriptions/...),
# or a bare GUID (object/principal ID) which is mapped to "system".
if [[ "$MANAGED_IDENTITY_ID" == "system" ]]; then
  :
elif [[ "$MANAGED_IDENTITY_ID" == /* ]]; then
  :
else
  echo "Note: '${MANAGED_IDENTITY_ID}' is not a resource ID; using system-assigned managed identity for ACR pull." >&2
  MANAGED_IDENTITY_ID="system"
fi

if [[ -n "${SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$SUBSCRIPTION_ID"
fi

if ! AZ_SUBSCRIPTION_ID="$(az account show --query id -o tsv 2>/dev/null)"; then
  echo "Error: Azure CLI login context is unavailable. Run 'az login' in this shell user context." >&2
  exit 1
fi
AZ_SUBSCRIPTION_NAME="$(az account show --query name -o tsv)"
AZ_SCOPE_ARGS=(--subscription "$AZ_SUBSCRIPTION_ID")

require_value "resource group name" "$RESOURCE_GROUP_NAME"
require_value "container app name" "$CONTAINER_APP_NAME"
require_value "container registry name" "$CONTAINER_REGISTRY_NAME"
require_value "container image name" "$CONTAINER_IMAGE_NAME"
require_value "build context" "$BUILD_CONTEXT"

if [[ "$CONTAINER_REGISTRY_NAME" =~ [[:space:]] ]]; then
  echo "Error: container registry name contains whitespace: '$CONTAINER_REGISTRY_NAME'" >&2
  exit 1
fi

if ! az acr show --name "$CONTAINER_REGISTRY_NAME" "${AZ_SCOPE_ARGS[@]}" --query id -o tsv >/dev/null 2>&1; then
  echo "Error: ACR '$CONTAINER_REGISTRY_NAME' was not found in resolved subscription '$AZ_SUBSCRIPTION_ID'." >&2
  echo "Hint: root/sudo sessions often use a different Azure CLI context. Verify with:" >&2
  echo "  az account show -o table" >&2
  echo "  az acr show -n \"$CONTAINER_REGISTRY_NAME\" --subscription \"$AZ_SUBSCRIPTION_ID\" -o table" >&2
  exit 1
fi

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
if [[ "$MANAGED_IDENTITY_ID" == "system" ]]; then
  echo "Managed identity: system-assigned"
else
  echo "Managed identity: $MANAGED_IDENTITY_ID (user-assigned)"
fi
echo "Azure subscription: $AZ_SUBSCRIPTION_NAME ($AZ_SUBSCRIPTION_ID)"
echo "Build context: $BUILD_CONTEXT"
echo "Skip build: $SKIP_BUILD"
if [[ -n "$AZURE_STORAGE_ACCOUNT_URL" ]]; then
  echo "Storage account URL: $AZURE_STORAGE_ACCOUNT_URL"
  echo "Storage container: $AZURE_STORAGE_CONTAINER"
fi

if [[ "$SKIP_BUILD" != "true" ]]; then
  echo "Building and pushing image to ACR (tag: latest)..."
  az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    "${AZ_SCOPE_ARGS[@]}" \
    --image "$ACR_IMAGE" \
    "$BUILD_CONTEXT" \
    --only-show-errors >/dev/null
else
  echo "Skipping ACR build/push — using existing 'latest' image in ACR."
fi

az containerapp registry set \
  --name "$CONTAINER_APP_NAME" \
  --resource-group "$RESOURCE_GROUP_NAME" \
  "${AZ_SCOPE_ARGS[@]}" \
  --server "$CONTAINER_REGISTRY_SERVER" \
  --identity "$MANAGED_IDENTITY_ID" \
  --only-show-errors >/dev/null

UPDATE_ARGS=(
  --name "$CONTAINER_APP_NAME"
  --resource-group "$RESOURCE_GROUP_NAME"
  "${AZ_SCOPE_ARGS[@]}"
  --image "$FULL_CONTAINER_IMAGE"
)

if [[ -n "$AZURE_STORAGE_ACCOUNT_URL" ]]; then
  UPDATE_ARGS+=(
    --set-env-vars
    "AZURE_STORAGE_ACCOUNT_URL=$AZURE_STORAGE_ACCOUNT_URL"
    "AZURE_STORAGE_CONTAINER=$AZURE_STORAGE_CONTAINER"
  )
fi

az containerapp update \
  "${UPDATE_ARGS[@]}" \
  --only-show-errors >/dev/null

APP_URL="$(
  az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP_NAME" \
    "${AZ_SCOPE_ARGS[@]}" \
    --query "properties.configuration.ingress.fqdn" \
    -o tsv
)"

echo "Updated Container App image successfully."
echo "App URL: https://${APP_URL}"
