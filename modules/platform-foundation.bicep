targetScope = 'resourceGroup'

param location string
param managedIdentityName string
param keyVaultName string
param storageAccountName string
param tags object

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
  tags: tags
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Enabled'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource incomingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'incoming-nonhwp'
  properties: {
    publicAccess: 'None'
  }
}

resource resultContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'result-hwp'
  properties: {
    publicAccess: 'None'
  }
}

resource artifactContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'processing-artifacts'
  properties: {
    publicAccess: 'None'
  }
}

// Key Vault Secrets User so the workload identity can read secrets at runtime.
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource keyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, managedIdentity.id, keyVaultSecretsUserRoleId)
  properties: {
    principalId: managedIdentity.properties.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

output managedIdentityName string = managedIdentity.name
output managedIdentityId string = managedIdentity.id
output managedIdentityClientId string = managedIdentity.properties.clientId
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
