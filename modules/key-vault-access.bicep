targetScope = 'resourceGroup'

param keyVaultName string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
