# Azure M365 MCP scaffold

This folder is the starter scaffold for implementing the M365 + Azure MCP/API architecture.

## What is included

- `main.bicep`: top-level deployment orchestration
- `modules/observability.bicep`: Log Analytics + Application Insights
- `modules/platform-foundation.bicep`: User-assigned identity, Key Vault, Storage Account, baseline containers
- `modules/application.bicep`: Azure Container Apps environment + MCP/API app shell
- `main.dev.bicepparam`: sample development parameters

## Intended runtime shape

- M365 side: Copilot Studio, SharePoint, OneDrive, Outlook/Teams
- Azure side: MCP/API app, storage for incoming/result artifacts, Key Vault for secrets, managed identity, observability
- Enterprise integrations: APIM, NGIS, PSS, Tiro, Confluence, DRM API

## What this scaffold does not implement yet

- Actual MCP server application code
- APIM instance and policies
- Private networking / VNets / private endpoints
- Real RBAC assignments for operators and workload identity
- Secrets bootstrap automation
- CI/CD workflow for build and deployment

## First implementation steps

1. Replace placeholder values in `main.dev.bicepparam`.
2. Replace `containerImage` with your actual application image.
3. Add APIM resources or reference an existing APIM instance.
4. Add Key Vault secret seeding and RBAC.
5. Add GitHub Actions deployment workflow using this Bicep stack.

## Example deployment

```bash
az deployment sub create \
  --location <location> \
  --template-file main.bicep \
  --parameters main.dev.bicepparam
```
