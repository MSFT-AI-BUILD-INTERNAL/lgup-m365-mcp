targetScope = 'resourceGroup'

param location string
param apimName string
param publisherEmail string
param publisherName string

@description('Base URL of the Container App backend, e.g. https://app.region.azurecontainerapps.io')
param containerAppUrl string

@description('Entra ID application (client) ID whose audience is accepted by APIM.')
param authClientId string

@description('Entra ID tenant ID used by APIM to resolve OpenID metadata.')
param authTenantId string = ''

param tags object

// API Management in Consumption tier: serverless gateway, pay-per-call, fast to provision.
resource apim 'Microsoft.ApiManagement/service@2022-08-01' = {
  name: apimName
  location: location
  tags: tags
  sku: {
    name: 'Consumption'
    capacity: 0
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2022-08-01' = {
  parent: apim
  name: 'mcp'
  properties: {
    displayName: 'Copilot Studio MCP Integration'
    path: ''
    protocols: [
      'https'
    ]
    serviceUrl: containerAppUrl
    subscriptionRequired: false
  }
}

// Disable response buffering so MCP Streamable HTTP (SSE) responses pass through.
resource apiPolicy 'Microsoft.ApiManagement/service/apis/policies@2022-08-01' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'xml'
    value: '<policies><inbound><base /></inbound><backend><forward-request buffer-response="false" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'
  }
}

resource opPostMcp 'Microsoft.ApiManagement/service/apis/operations@2022-08-01' = {
  parent: api
  name: 'post-mcp'
  properties: {
    displayName: 'MCP POST'
    method: 'POST'
    urlTemplate: '/mcp'
  }
}

resource opPostMcpPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2022-08-01' = {
  parent: opPostMcp
  name: 'policy'
  properties: {
    format: 'xml'
    value: '<policies><inbound><validate-jwt header-name="Authorization" require-scheme="Bearer" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized. Valid Entra bearer token required."><openid-config url="https://login.microsoftonline.com/${authTenantId}/v2.0/.well-known/openid-configuration" /><audiences><audience>api://${authClientId}</audience><audience>${authClientId}</audience></audiences></validate-jwt><base /></inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'
  }
}

resource opHealth 'Microsoft.ApiManagement/service/apis/operations@2022-08-01' = {
  parent: api
  name: 'get-health'
  properties: {
    displayName: 'Health'
    method: 'GET'
    urlTemplate: '/health'
  }
}

output gatewayUrl string = apim.properties.gatewayUrl
output apimName string = apim.name
