# Azure Copilot Studio MCP scaffold

This repository provides a starter scaffold for deploying an Azure-hosted MCP/API service that will be consumed by an M365 Copilot Studio Agent and a Client Application.

## What is included

- `main.bicep`: top-level deployment orchestration
- `modules/observability.bicep`: Log Analytics + Application Insights
- `modules/platform-foundation.bicep`: User-assigned identity baseline
- `modules/key-vault-access.bicep`: Existing Key Vault reference
- `modules/application.bicep`: Azure Container Apps environment + MCP/API app shell
- `modules/gateway.bicep`: API Management gateway in front of the MCP endpoint
- `main.dev.bicepparam`: checked-in sample development parameters for existing Key Vault/ACR resources in the target resource group (no real secrets)
- `deploy-bicep.sh`: helper script for provisioning infrastructure with a public bootstrap image
- `deploy-app.sh`: helper script for building/pushing the image to ACR and switching the existing Container App to it
- `destroy-bicep.sh`: helper script for deleting only the resources created by this stack

## Intended runtime shape

- Client side: M365 Copilot Studio Agent and Client Application
- Azure side: MCP/API app, pre-created Key Vault for secrets, managed identity, observability
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
2. Set `keyVaultName` and `containerRegistryName` to your pre-created Azure resource names.
3. Run `deploy-bicep.sh` to provision infra with the public bootstrap image.
4. After granting `AcrPull` manually, run `deploy-app.sh` to build/push and switch the Container App to your private `containerImage`.
5. Wire the MCP endpoint into your Copilot Studio Agent and Client Application flows.
6. Add Key Vault secret seeding and manual RBAC hardening.
7. Add GitHub Actions deployment workflow using this Bicep stack.

## Example deployment

```bash
export CLIENT_APPLICATION_SECRET='...'
./deploy-bicep.sh --param-file main.local.bicepparam
```
