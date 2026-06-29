targetScope = 'subscription'

@description('Short prefix used for generated resource names.')
param namePrefix string = 'lgmcp'

@description('Deployment environment name, for example dev, test, or prod.')
param environmentName string = 'dev'

@description('Azure region for all deployed resources.')
param location string = 'eastasia'

@description('Resource group name.')
param resourceGroupName string = 'lgup-rg'

@description('Tags applied to all supported resources.')
param tags object = {
  workload: 'copilot-studio-mcp'
  environment: environmentName
}

type CopilotStudioConfig = {
  tenantId: string
  copilotStudioEnvironment: string
}

type IntegrationEndpoints = {
  apimGatewayUrl: string
  ngisBaseUrl: string
  pssBaseUrl: string
  tiroBaseUrl: string
  confluenceBaseUrl: string
  drmApiBaseUrl: string
}

@description('Copilot Studio Agent and client application values used by the MCP/API workload.')
param copilotStudio CopilotStudioConfig

@description('Enterprise endpoint base URLs that the Azure-hosted MCP/API integrates with.')
param integrations IntegrationEndpoints

@description('Container image for the Azure-hosted MCP/API implementation.')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Existing Azure Container Registry name in the target resource group. Leave empty for public images.')
param containerRegistryName string = ''

@description('When true, configure the Container App to pull from the existing ACR on this deployment. Keep false for the first deploy before manual AcrPull grant.')
param enableContainerRegistryOnDeploy bool = false

@description('Existing Key Vault name in the target resource group. Leave empty when the workload does not need Key Vault.')
param keyVaultName string = ''

@description('Port exposed by the container application.')
param containerPort int = 8080

@description('Minimum replica count for the container app.')
param minReplicas int = 1

@description('Maximum replica count for the container app.')
param maxReplicas int = 3

@description('Container CPU allocation in cores.')
param containerCpu int = 1

@description('Container memory allocation.')
param containerMemory string = '2Gi'

@secure()
@description('Client application secret used for downstream authenticated integrations.')
param clientApplicationSecret string

@secure()
@description('API key for NGIS integration.')
param ngisApiKey string = ''

@secure()
@description('API key for DRM integration.')
param drmApiKey string = ''

@description('Publisher email for the API Management gateway.')
param apimPublisherEmail string = 'admin@example.com'

@description('Publisher organization name for the API Management gateway.')
param apimPublisherName string = 'LGUP MCP'

@description('Entra ID application (client) ID used for APIM JWT validation and Container Apps built-in authentication.')
param authClientId string

// Create the resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

var resourcePrefix = '${namePrefix}-${environmentName}'
var logAnalyticsWorkspaceName = '${resourcePrefix}-law'
var applicationInsightsName = '${resourcePrefix}-appi'
var managedIdentityName = '${resourcePrefix}-uami'
var managedEnvironmentName = '${resourcePrefix}-cae'
var containerAppName = '${resourcePrefix}-mcp-api'
var apimName = take('${namePrefix}-${environmentName}-apim-${uniqueString(subscription().id, resourceGroupName)}', 50)
var containerRegistryLoginServer = empty(containerRegistryName) ? '' : '${containerRegistryName}.azurecr.io'
var keyVaultUri = empty(keyVaultName) ? '' : keyVault!.outputs.keyVaultUri

module observability './modules/observability.bicep' = {
  scope: rg
  params: {
    location: location
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    applicationInsightsName: applicationInsightsName
    tags: tags
  }
}

module foundation './modules/platform-foundation.bicep' = {
  scope: rg
  params: {
    location: location
    managedIdentityName: managedIdentityName
    tags: tags
  }
}

module keyVault './modules/key-vault-access.bicep' = if (!empty(keyVaultName)) {
  scope: rg
  params: {
    keyVaultName: keyVaultName
  }
}

module registry './modules/registry.bicep' = if (!empty(containerRegistryName)) {
  scope: rg
  params: {
    acrName: containerRegistryName
  }
}

module application './modules/application.bicep' = {
  scope: rg
  params: {
    location: location
    managedEnvironmentName: managedEnvironmentName
    containerAppName: containerAppName
    logAnalyticsWorkspaceName: observability.outputs.logAnalyticsWorkspaceName
    applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
    managedIdentityId: foundation.outputs.managedIdentityId
    managedIdentityClientId: foundation.outputs.managedIdentityClientId
    keyVaultUri: keyVaultUri
    containerRegistryServer: enableContainerRegistryOnDeploy ? containerRegistryLoginServer : ''
    copilotStudio: copilotStudio
    integrations: integrations
    clientApplicationSecret: clientApplicationSecret
    ngisApiKey: ngisApiKey
    drmApiKey: drmApiKey
    containerImage: containerImage
    containerPort: containerPort
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    containerCpu: containerCpu
    containerMemory: containerMemory
    authClientId: authClientId
    authTenantId: subscription().tenantId
    tags: tags
  }
}

module gateway './modules/gateway.bicep' = {
  scope: rg
  params: {
    location: location
    apimName: apimName
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    containerAppUrl: application.outputs.containerAppUrl
    authClientId: authClientId
    authTenantId: subscription().tenantId
    tags: tags
  }
}

output logAnalyticsWorkspaceName string = observability.outputs.logAnalyticsWorkspaceName
output applicationInsightsName string = observability.outputs.applicationInsightsName
output managedIdentityName string = foundation.outputs.managedIdentityName
output managedIdentityId string = foundation.outputs.managedIdentityId
output managedIdentityPrincipalId string = foundation.outputs.managedIdentityPrincipalId
output keyVaultName string = keyVaultName
output keyVaultUri string = keyVaultUri
output containerRegistryLoginServer string = containerRegistryLoginServer
output containerRegistryName string = containerRegistryName
output managedEnvironmentName string = managedEnvironmentName
output containerAppName string = application.outputs.containerAppName
output containerAppUrl string = application.outputs.containerAppUrl
output apimName string = apimName
output apimGatewayUrl string = gateway.outputs.gatewayUrl
output apimMcpEndpoint string = '${gateway.outputs.gatewayUrl}/mcp'
output implementationChecklist array = [
  '1. Replace placeholder values in main.dev.bicepparam.'
  '2. Set keyVaultName and containerRegistryName to your pre-created Azure resources.'
  '3. Provision infrastructure with deploy-bicep.sh, which always uses a public bootstrap image.'
  '4. After manual AcrPull is granted, run deploy-app.sh to switch the Container App to your private MCP/API image.'
  '5. Configure RBAC manually, then add APIM policies and private networking hardening.'
  '6. Connect ghcp-sdlc-sample style GitHub Actions to build and deploy this Bicep stack.'
]
