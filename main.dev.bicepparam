using './main.bicep'

param namePrefix = 'lgmcp'
param environmentName = 'dev'
param location = 'koreacentral'

param tags = {
  workload: 'm365-mcp'
  owner: 'platform-team'
  costCenter: 'tbd'
}

param m365 = {
  tenantId: '00000000-0000-0000-0000-000000000000'
  sharePointSiteUrl: 'https://example.sharepoint.com/sites/fieldops'
  oneDriveRootPath: '/Documents/Incoming'
  teamsTenantDomain: 'example.onmicrosoft.com'
  copilotStudioEnvironment: 'default-dev'
}

param integrations = {
  apimGatewayUrl: 'https://apim.example.com'
  ngisBaseUrl: 'https://ngis.example.com'
  pssBaseUrl: 'https://pss.example.com'
  tiroBaseUrl: 'https://tiro.example.com'
  confluenceBaseUrl: 'https://confluence.example.com'
  drmApiBaseUrl: 'https://drm.example.com'
}

param containerImage = 'lgmcpdevacreubidyfnm7le4.azurecr.io/hanik-mcp-server:1.1.0'
param containerPort = 8080
param minReplicas = 1
param maxReplicas = 2
param containerCpu = 1
param containerMemory = '2Gi'

param m365ClientSecret = 'replace-me'
param ngisApiKey = 'replace-me'
param drmApiKey = 'replace-me'

param apimPublisherEmail = 'admin@example.com'
param apimPublisherName = 'LGUP MCP'

param authClientId = '92ad2fc4-e344-423f-b312-849420011273'
