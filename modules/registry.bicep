targetScope = 'resourceGroup'

param location string
param acrName string
param managedIdentityPrincipalId string
param tags object

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

// AcrPull role so the workload identity can pull images from this registry.
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, managedIdentityPrincipalId, acrPullRoleId)
  properties: {
    principalId: managedIdentityPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

output loginServer string = acr.properties.loginServer
output acrName string = acr.name
