targetScope = 'resourceGroup'

param acrName string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

output loginServer string = acr.properties.loginServer
output acrName string = acr.name
