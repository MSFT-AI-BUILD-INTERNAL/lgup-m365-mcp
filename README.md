# Azure Copilot Studio MCP scaffold

This repository provides a starter scaffold for deploying an Azure-hosted MCP/API service that will be consumed by an M365 Copilot Studio Agent and a Client Application.

## What is included

- `main.bicep`: top-level deployment orchestration
- `modules/observability.bicep`: Log Analytics + Application Insights
- `modules/platform-foundation.bicep`: User-assigned identity, Key Vault, Storage Account, baseline containers
- `modules/application.bicep`: Azure Container Apps environment + MCP/API app shell
- `modules/gateway.bicep`: API Management gateway in front of the MCP endpoint
- `main.dev.bicepparam`: checked-in sample development parameters (no real secrets)

## Intended runtime shape

- Client side: M365 Copilot Studio Agent and Client Application
- Azure side: MCP/API app, storage for incoming/result artifacts, Key Vault for secrets, managed identity, observability
- Enterprise integrations: APIM, NGIS, PSS, Tiro, Confluence, DRM API
- Gateway auth: Entra bearer token validation at APIM for `/mcp` (no APIM subscription key)

## What this scaffold does not implement yet

- Full MCP business logic beyond the starter server
- APIM production policies and advanced gateway hardening
- Private networking / VNets / private endpoints
- Real RBAC assignments for operators and workload identity
- Secrets bootstrap automation
- CI/CD workflow for build and deployment

## First implementation steps

1. Keep `main.dev.bicepparam` as a sample, use placeholders only, and inject real secrets at deployment time or from an untracked local `.bicepparam` file.
2. Replace `containerImage` with your actual application image.
3. Wire the MCP endpoint into your Copilot Studio Agent and Client Application flows.
4. Add Key Vault secret seeding and RBAC hardening.
5. Add GitHub Actions deployment workflow using this Bicep stack.

## Example deployment

```bash
az deployment sub create \
  --location <location> \
  --template-file main.bicep \
  --parameters main.local.bicepparam
```
