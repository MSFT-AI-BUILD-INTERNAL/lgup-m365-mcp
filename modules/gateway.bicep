targetScope = 'resourceGroup'

param location string
param apimName string
param publisherEmail string
param publisherName string

@description('Base URL of the Container App backend, e.g. https://app.region.azurecontainerapps.io')
param containerAppUrl string
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
    displayName: 'Hanik MCP'
    path: ''
    protocols: [
      'https'
    ]
    serviceUrl: containerAppUrl
    subscriptionRequired: true
    subscriptionKeyParameterNames: {
      header: 'Ocp-Apim-Subscription-Key'
      query: 'subscription-key'
    }
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

resource opHealth 'Microsoft.ApiManagement/service/apis/operations@2022-08-01' = {
  parent: api
  name: 'get-health'
  properties: {
    displayName: 'Health'
    method: 'GET'
    urlTemplate: '/health'
  }
}

resource sub 'Microsoft.ApiManagement/service/subscriptions@2022-08-01' = {
  parent: apim
  name: 'mcp-subscription'
  properties: {
    displayName: 'MCP Subscription'
    scope: api.id
    state: 'active'
  }
}

output gatewayUrl string = apim.properties.gatewayUrl
output apimName string = apim.name
output subscriptionName string = sub.name
