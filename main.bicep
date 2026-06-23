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
  workload: 'm365-mcp'
  environment: environmentName
}

type M365Config = {
  tenantId: string
  sharePointSiteUrl: string
  oneDriveRootPath: string
  teamsTenantDomain: string
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

@description('M365-side integration values used by the MCP/API workload.')
param m365 M365Config

@description('Enterprise endpoint base URLs that the Azure-hosted MCP/API integrates with.')
param integrations IntegrationEndpoints

@description('Container image for the Azure-hosted MCP/API implementation.')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

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
@description('Client secret used to access M365-side integrations.')
param m365ClientSecret string

@secure()
@description('API key for NGIS integration.')
param ngisApiKey string

@secure()
@description('API key for DRM integration.')
param drmApiKey string

@description('Publisher email for the API Management gateway.')
param apimPublisherEmail string = 'admin@example.com'

@description('Publisher organization name for the API Management gateway.')
param apimPublisherName string = 'LGUP MCP'

// Create the resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

var normalizedPrefix = replace(toLower(namePrefix), '-', '')
var resourcePrefix = '${namePrefix}-${environmentName}'
var logAnalyticsWorkspaceName = '${resourcePrefix}-law'
var applicationInsightsName = '${resourcePrefix}-appi'
var managedIdentityName = '${resourcePrefix}-uami'
var managedEnvironmentName = '${resourcePrefix}-cae'
var containerAppName = '${resourcePrefix}-mcp-api'
var keyVaultName = take(
  '${normalizedPrefix}${environmentName}kv${uniqueString(subscription().id, resourceGroupName)}',
  24
)
var storageAccountName = take(
  '${normalizedPrefix}${environmentName}st${uniqueString(subscription().id, resourceGroupName)}',
  24
)
var containerRegistryName = take(
  '${normalizedPrefix}${environmentName}acr${uniqueString(subscription().id, resourceGroupName)}',
  50
)
var apimName = take('${namePrefix}-${environmentName}-apim-${uniqueString(subscription().id, resourceGroupName)}', 50)

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
    keyVaultName: keyVaultName
    storageAccountName: storageAccountName
    tags: tags
  }
}

module registry './modules/registry.bicep' = {
  scope: rg
  params: {
    location: location
    acrName: containerRegistryName
    managedIdentityPrincipalId: foundation.outputs.managedIdentityPrincipalId
    tags: tags
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
    keyVaultUri: foundation.outputs.keyVaultUri
    storageAccountName: foundation.outputs.storageAccountName
    containerRegistryServer: registry.outputs.loginServer
    m365: m365
    integrations: integrations
    m365ClientSecret: m365ClientSecret
    ngisApiKey: ngisApiKey
    drmApiKey: drmApiKey
    containerImage: containerImage
    containerPort: containerPort
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    containerCpu: containerCpu
    containerMemory: containerMemory
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
    tags: tags
  }
}

output logAnalyticsWorkspaceName string = observability.outputs.logAnalyticsWorkspaceName
output applicationInsightsName string = observability.outputs.applicationInsightsName
output managedIdentityName string = foundation.outputs.managedIdentityName
output keyVaultName string = foundation.outputs.keyVaultName
output storageAccountName string = foundation.outputs.storageAccountName
output containerRegistryLoginServer string = registry.outputs.loginServer
output containerRegistryName string = registry.outputs.acrName
output containerAppName string = application.outputs.containerAppName
output containerAppUrl string = application.outputs.containerAppUrl
output apimGatewayUrl string = gateway.outputs.gatewayUrl
output apimMcpEndpoint string = '${gateway.outputs.gatewayUrl}/mcp'
output implementationChecklist array = [
  '1. Replace placeholder values in main.dev.bicepparam.'
  '2. Wire containerImage to your real MCP/API build artifact or ACR image.'
  '3. Add APIM policies, private networking, and RBAC hardening after first deployment.'
  '4. Connect ghcp-sdlc-sample style GitHub Actions to build and deploy this Bicep stack.'
]
