#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
Usage: ./destroy-bicep.sh [--param-file FILE] [--resource-group NAME] [--deployment-name NAME] [--yes] [--wait]

Environment variables:
  SUBSCRIPTION_ID      Optional; if set, az account set --subscription is executed
  PARAM_FILE           Optional; same as --param-file
  RESOURCE_GROUP_NAME  Optional; same as --resource-group
  DEPLOYMENT_NAME      Optional; same as --deployment-name

Behavior:
  - Uses main.local.bicepparam by default when present, otherwise main.dev.bicepparam.
  - Reads resourceGroupName from the parameter file when --resource-group is not provided.
  - Deletes only resources created by this stack instead of deleting the whole resource group.
USAGE
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: required command not found: $1" >&2
    exit 1
  }
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

deployment_output() {
  local deployment_name="$1"
  local output_name="$2"
  az deployment sub show \
    --name "$deployment_name" \
    --query "properties.outputs.${output_name}.value" \
    -o tsv 2>/dev/null || true
}

resolve_apim_name() {
  local resource_group="$1"
  local name_prefix="$2"
  local environment_name="$3"
  az resource list \
    --resource-group "$resource_group" \
    --query "[?type=='Microsoft.ApiManagement/service' && starts_with(name, '${name_prefix}-${environment_name}-apim-')].name | [0]" \
    -o tsv 2>/dev/null || true
}

resource_exists() {
  local resource_group="$1"
  local resource_type="$2"
  local resource_name="$3"
  az resource show \
    --resource-group "$resource_group" \
    --resource-type "$resource_type" \
    --name "$resource_name" \
    --only-show-errors \
    -o none >/dev/null 2>&1
}

delete_resource() {
  local resource_group="$1"
  local resource_type="$2"
  local resource_name="$3"

  if [[ -z "$resource_name" ]]; then
    return 0
  fi

  if ! resource_exists "$resource_group" "$resource_type" "$resource_name"; then
    echo "Skipping missing resource: $resource_type/$resource_name"
    return 0
  fi

  echo "Deleting resource: $resource_type/$resource_name"
  az resource delete \
    --resource-group "$resource_group" \
    --resource-type "$resource_type" \
    --name "$resource_name" \
    --only-show-errors >/dev/null
}

wait_for_resource_deletion() {
  local resource_group="$1"
  local resource_type="$2"
  local resource_name="$3"

  if [[ -z "$resource_name" ]]; then
    return 0
  fi

  for _ in {1..60}; do
    if ! resource_exists "$resource_group" "$resource_type" "$resource_name"; then
      return 0
    fi
    sleep 5
  done

  echo "Error: timed out waiting for deletion of $resource_type/$resource_name" >&2
  exit 1
}

PARAM_FILE="${PARAM_FILE:-}"
RESOURCE_GROUP_NAME="${RESOURCE_GROUP_NAME:-}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-lgup-mcp-deploy}"
ASSUME_YES="false"
WAIT_FOR_COMPLETION="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --param-file)
      PARAM_FILE="$2"
      shift 2
      ;;
    --resource-group)
      RESOURCE_GROUP_NAME="$2"
      shift 2
      ;;
    --deployment-name)
      DEPLOYMENT_NAME="$2"
      shift 2
      ;;
    --yes)
      ASSUME_YES="true"
      shift
      ;;
    --wait)
      WAIT_FOR_COMPLETION="true"
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

if [[ -z "$RESOURCE_GROUP_NAME" ]]; then
  if [[ ! -f "$PARAM_FILE" ]]; then
    echo "Error: parameter file not found: $PARAM_FILE" >&2
    exit 1
  fi
  RESOURCE_GROUP_NAME="$(parse_string_param "$PARAM_FILE" resourceGroupName)"
fi

NAME_PREFIX="$(parse_string_param "$PARAM_FILE" namePrefix)"
ENVIRONMENT_NAME="$(parse_string_param "$PARAM_FILE" environmentName)"

if [[ -z "$NAME_PREFIX" ]]; then
  NAME_PREFIX="lgmcp"
fi

if [[ -z "$ENVIRONMENT_NAME" ]]; then
  ENVIRONMENT_NAME="dev"
fi

if [[ -z "$RESOURCE_GROUP_NAME" ]]; then
  echo "Error: resource group name could not be determined. Pass --resource-group or set RESOURCE_GROUP_NAME." >&2
  exit 1
fi

if [[ -n "${SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$SUBSCRIPTION_ID"
fi

CONTAINER_APP_NAME="$(deployment_output "$DEPLOYMENT_NAME" containerAppName)"
MANAGED_ENVIRONMENT_NAME="$(deployment_output "$DEPLOYMENT_NAME" managedEnvironmentName)"
MANAGED_IDENTITY_NAME="$(deployment_output "$DEPLOYMENT_NAME" managedIdentityName)"
APPLICATION_INSIGHTS_NAME="$(deployment_output "$DEPLOYMENT_NAME" applicationInsightsName)"
LOG_ANALYTICS_WORKSPACE_NAME="$(deployment_output "$DEPLOYMENT_NAME" logAnalyticsWorkspaceName)"
APIM_NAME="$(deployment_output "$DEPLOYMENT_NAME" apimName)"

RESOURCE_PREFIX="${NAME_PREFIX}-${ENVIRONMENT_NAME}"

if [[ -z "$CONTAINER_APP_NAME" ]]; then
  CONTAINER_APP_NAME="${RESOURCE_PREFIX}-mcp-api"
fi

if [[ -z "$MANAGED_ENVIRONMENT_NAME" ]]; then
  MANAGED_ENVIRONMENT_NAME="${RESOURCE_PREFIX}-cae"
fi

if [[ -z "$MANAGED_IDENTITY_NAME" ]]; then
  MANAGED_IDENTITY_NAME="${RESOURCE_PREFIX}-uami"
fi

if [[ -z "$APPLICATION_INSIGHTS_NAME" ]]; then
  APPLICATION_INSIGHTS_NAME="${RESOURCE_PREFIX}-appi"
fi

if [[ -z "$LOG_ANALYTICS_WORKSPACE_NAME" ]]; then
  LOG_ANALYTICS_WORKSPACE_NAME="${RESOURCE_PREFIX}-law"
fi

if [[ -z "$APIM_NAME" ]]; then
  APIM_NAME="$(resolve_apim_name "$RESOURCE_GROUP_NAME" "$NAME_PREFIX" "$ENVIRONMENT_NAME")"
fi

echo "Target resource group: $RESOURCE_GROUP_NAME"
echo "Stack resources scheduled for deletion:"
for item in \
  "Microsoft.App/containerApps:$CONTAINER_APP_NAME" \
  "Microsoft.ApiManagement/service:$APIM_NAME" \
  "Microsoft.App/managedEnvironments:$MANAGED_ENVIRONMENT_NAME" \
  "Microsoft.Insights/components:$APPLICATION_INSIGHTS_NAME" \
  "Microsoft.OperationalInsights/workspaces:$LOG_ANALYTICS_WORKSPACE_NAME" \
  "Microsoft.ManagedIdentity/userAssignedIdentities:$MANAGED_IDENTITY_NAME"
do
  printf '  - %s\n' "$item"
done

if [[ "$ASSUME_YES" != "true" ]]; then
  read -r -p "Delete only the stack resources above from '$RESOURCE_GROUP_NAME'? [y/N] " reply
  case "$reply" in
    y|Y|yes|YES)
      ;;
    *)
      echo "Cancelled."
      exit 0
      ;;
  esac
fi

delete_resource "$RESOURCE_GROUP_NAME" "Microsoft.App/containerApps" "$CONTAINER_APP_NAME"
wait_for_resource_deletion "$RESOURCE_GROUP_NAME" "Microsoft.App/containerApps" "$CONTAINER_APP_NAME"

delete_resource "$RESOURCE_GROUP_NAME" "Microsoft.ApiManagement/service" "$APIM_NAME"

delete_resource "$RESOURCE_GROUP_NAME" "Microsoft.App/managedEnvironments" "$MANAGED_ENVIRONMENT_NAME"
wait_for_resource_deletion "$RESOURCE_GROUP_NAME" "Microsoft.App/managedEnvironments" "$MANAGED_ENVIRONMENT_NAME"

delete_resource "$RESOURCE_GROUP_NAME" "Microsoft.Insights/components" "$APPLICATION_INSIGHTS_NAME"
wait_for_resource_deletion "$RESOURCE_GROUP_NAME" "Microsoft.Insights/components" "$APPLICATION_INSIGHTS_NAME"

delete_resource "$RESOURCE_GROUP_NAME" "Microsoft.OperationalInsights/workspaces" "$LOG_ANALYTICS_WORKSPACE_NAME"

delete_resource "$RESOURCE_GROUP_NAME" "Microsoft.ManagedIdentity/userAssignedIdentities" "$MANAGED_IDENTITY_NAME"

if [[ "$WAIT_FOR_COMPLETION" == "true" ]]; then
  wait_for_resource_deletion "$RESOURCE_GROUP_NAME" "Microsoft.ApiManagement/service" "$APIM_NAME"
  wait_for_resource_deletion "$RESOURCE_GROUP_NAME" "Microsoft.OperationalInsights/workspaces" "$LOG_ANALYTICS_WORKSPACE_NAME"
  wait_for_resource_deletion "$RESOURCE_GROUP_NAME" "Microsoft.ManagedIdentity/userAssignedIdentities" "$MANAGED_IDENTITY_NAME"
fi

echo "Delete requests submitted for stack resources in: $RESOURCE_GROUP_NAME"
