#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
Usage: ./deploy-bicep.sh [--what-if] [--register-providers] [--param-file FILE] [--deployment-name NAME] [--location LOCATION]

Environment variables:
  CLIENT_APPLICATION_SECRET   Required
  NGIS_API_KEY                Optional
  DRM_API_KEY                 Optional
  SUBSCRIPTION_ID             Optional; if set, az account set --subscription is executed
  PARAM_FILE                  Optional; same as --param-file
  DEPLOYMENT_NAME             Optional; same as --deployment-name
  DEPLOYMENT_LOCATION         Optional; same as --location
  BOOTSTRAP_CONTAINER_IMAGE   Optional; public bootstrap image to provision with

Behavior:
  - Uses main.local.bicepparam by default when present, otherwise main.dev.bicepparam.
  - Injects secret values via CLI parameters instead of reading them from the parameter file.
  - Always provisions the Container App with a public bootstrap image and disables ACR wiring.
USAGE
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: required command not found: $1" >&2
    exit 1
  }
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Error: environment variable $name is required." >&2
    exit 1
  fi
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
DEPLOYMENT_LOCATION="${DEPLOYMENT_LOCATION:-}"
MODE="create"
REGISTER_PROVIDERS="false"
BOOTSTRAP_CONTAINER_IMAGE="${BOOTSTRAP_CONTAINER_IMAGE:-mcr.microsoft.com/azuredocs/containerapps-helloworld:latest}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --what-if)
      MODE="what-if"
      shift
      ;;
    --register-providers)
      REGISTER_PROVIDERS="true"
      shift
      ;;
    --param-file)
      PARAM_FILE="$2"
      shift 2
      ;;
    --deployment-name)
      DEPLOYMENT_NAME="$2"
      shift 2
      ;;
    --location)
      DEPLOYMENT_LOCATION="$2"
      shift 2
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

if [[ -z "$DEPLOYMENT_LOCATION" ]]; then
  DEPLOYMENT_LOCATION="$(parse_string_param "$PARAM_FILE" location)"
fi

if [[ -z "$DEPLOYMENT_LOCATION" ]]; then
  echo "Error: deployment location could not be determined. Pass --location or set DEPLOYMENT_LOCATION." >&2
  exit 1
fi

require_env CLIENT_APPLICATION_SECRET
if [[ -n "${SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$SUBSCRIPTION_ID"
fi

if [[ "$REGISTER_PROVIDERS" == "true" ]]; then
  for ns in \
    Microsoft.OperationalInsights \
    Microsoft.Insights \
    Microsoft.ManagedIdentity \
    Microsoft.KeyVault \
    Microsoft.Storage \
    Microsoft.ContainerRegistry \
    Microsoft.App \
    Microsoft.ApiManagement \
    Microsoft.Authorization
  do
    az provider register --namespace "$ns" >/dev/null
  done
fi

echo "Using parameter file: $PARAM_FILE"
echo "Deployment location: $DEPLOYMENT_LOCATION"
echo "Deployment mode: $MODE"
echo "Bootstrap image: $BOOTSTRAP_CONTAINER_IMAGE"

deployment_args=(
  az deployment sub "$MODE"
  --name "$DEPLOYMENT_NAME"
  --location "$DEPLOYMENT_LOCATION"
  --template-file main.bicep
  --parameters "$PARAM_FILE"
  --parameters
  containerRegistryName=''
  enableContainerRegistryOnDeploy=false
  containerImage="$BOOTSTRAP_CONTAINER_IMAGE"
  clientApplicationSecret="$CLIENT_APPLICATION_SECRET"
)

if [[ -n "${NGIS_API_KEY:-}" ]]; then
  deployment_args+=(ngisApiKey="$NGIS_API_KEY")
fi

if [[ -n "${DRM_API_KEY:-}" ]]; then
  deployment_args+=(drmApiKey="$DRM_API_KEY")
fi

"${deployment_args[@]}"
