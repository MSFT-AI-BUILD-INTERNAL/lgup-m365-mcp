targetScope = 'resourceGroup'

param location string
param managedEnvironmentName string
param containerAppName string
param logAnalyticsWorkspaceName string
param applicationInsightsConnectionString string
param managedIdentityId string
param managedIdentityClientId string
param keyVaultUri string
param copilotStudio object
param integrations object
@secure()
param clientApplicationSecret string
@secure()
param ngisApiKey string = ''
@secure()
param drmApiKey string = ''
param containerImage string
param containerPort int
param minReplicas int
param maxReplicas int
param containerCpu int
param containerMemory string
param tags object

@description('Entra ID application (client) ID used for Container Apps built-in authentication.')
param authClientId string

@description('Entra ID tenant ID used as the token issuer for built-in authentication.')
param authTenantId string = ''

@description('Login server of the container registry the workload identity pulls from. Empty for public images.')
param containerRegistryServer string = ''

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

var containerAppSecrets = concat([
  {
    name: 'client-application-secret'
    value: clientApplicationSecret
  }
], empty(ngisApiKey) ? [] : [
  {
    name: 'ngis-api-key'
    value: ngisApiKey
  }
], empty(drmApiKey) ? [] : [
  {
    name: 'drm-api-key'
    value: drmApiKey
  }
])

var containerAppEnv = concat([
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: applicationInsightsConnectionString
  }
  {
    name: 'AZURE_CLIENT_ID'
    value: managedIdentityClientId
  }
  {
    name: 'COPILOT_TENANT_ID'
    value: copilotStudio.tenantId
  }
  {
    name: 'COPILOT_STUDIO_ENVIRONMENT'
    value: copilotStudio.copilotStudioEnvironment
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
    name: 'CLIENT_APPLICATION_SECRET'
    secretRef: 'client-application-secret'
  }
], empty(ngisApiKey) ? [] : [
  {
    name: 'NGIS_API_KEY'
    secretRef: 'ngis-api-key'
  }
], empty(drmApiKey) ? [] : [
  {
    name: 'DRM_API_KEY'
    secretRef: 'drm-api-key'
  }
])

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
      secrets: containerAppSecrets
    }
    template: {
      containers: [
        {
          name: 'mcp-api'
          image: containerImage
          env: containerAppEnv
          resources: {
            cpu: containerCpu
            memory: containerMemory
          }
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/health'
                port: containerPort
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: containerPort
              }
              initialDelaySeconds: 30
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: containerPort
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 6
            }
          ]
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

// Built-in authentication (Easy Auth) with Entra ID.
// AllowAnonymous keeps the endpoint reachable while forwarding the caller's
// identity (x-ms-client-principal* headers) to the backend whenever a valid
// bearer token is presented.
resource authConfig 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: containerApp
  name: 'current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'AllowAnonymous'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://login.microsoftonline.com/${authTenantId}/v2.0'
          clientId: authClientId
        }
        validation: {
          allowedAudiences: [
            'api://${authClientId}'
            authClientId
          ]
        }
      }
    }
  }
}
