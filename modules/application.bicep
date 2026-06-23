targetScope = 'resourceGroup'

param location string
param managedEnvironmentName string
param containerAppName string
param logAnalyticsWorkspaceName string
param applicationInsightsConnectionString string
param managedIdentityId string
param managedIdentityClientId string
param keyVaultUri string
param storageAccountName string
param m365 object
param integrations object
@secure()
param m365ClientSecret string
@secure()
param ngisApiKey string
@secure()
param drmApiKey string
param containerImage string
param containerPort int
param minReplicas int
param maxReplicas int
param containerCpu int
param containerMemory string
param tags object

@description('Login server of the container registry the workload identity pulls from. Empty for public images.')
param containerRegistryServer string = ''

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: managedEnvironmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: containerPort
        transport: 'auto'
      }
      registries: empty(containerRegistryServer) ? [] : [
        {
          server: containerRegistryServer
          identity: managedIdentityId
        }
      ]
      secrets: [
        {
          name: 'm365-client-secret'
          value: m365ClientSecret
        }
        {
          name: 'ngis-api-key'
          value: ngisApiKey
        }
        {
          name: 'drm-api-key'
          value: drmApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp-api'
          image: containerImage
          env: [
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: applicationInsightsConnectionString
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
            {
              name: 'M365_TENANT_ID'
              value: m365.tenantId
            }
            {
              name: 'M365_SHAREPOINT_SITE_URL'
              value: m365.sharePointSiteUrl
            }
            {
              name: 'M365_ONEDRIVE_ROOT_PATH'
              value: m365.oneDriveRootPath
            }
            {
              name: 'M365_TEAMS_TENANT_DOMAIN'
              value: m365.teamsTenantDomain
            }
            {
              name: 'M365_COPILOT_STUDIO_ENVIRONMENT'
              value: m365.copilotStudioEnvironment
            }
            {
              name: 'APIM_GATEWAY_URL'
              value: integrations.apimGatewayUrl
            }
            {
              name: 'NGIS_BASE_URL'
              value: integrations.ngisBaseUrl
            }
            {
              name: 'PSS_BASE_URL'
              value: integrations.pssBaseUrl
            }
            {
              name: 'TIRO_BASE_URL'
              value: integrations.tiroBaseUrl
            }
            {
              name: 'CONFLUENCE_BASE_URL'
              value: integrations.confluenceBaseUrl
            }
            {
              name: 'DRM_API_BASE_URL'
              value: integrations.drmApiBaseUrl
            }
            {
              name: 'KEY_VAULT_URI'
              value: keyVaultUri
            }
            {
              name: 'STORAGE_ACCOUNT_NAME'
              value: storageAccountName
            }
            {
              name: 'M365_CLIENT_SECRET'
              secretRef: 'm365-client-secret'
            }
            {
              name: 'NGIS_API_KEY'
              secretRef: 'ngis-api-key'
            }
            {
              name: 'DRM_API_KEY'
              secretRef: 'drm-api-key'
            }
          ]
          resources: {
            cpu: containerCpu
            memory: containerMemory
          }
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output containerAppName string = containerApp.name
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output managedEnvironmentId string = managedEnvironment.id
