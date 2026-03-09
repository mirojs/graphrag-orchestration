@description('Name of the Key Vault')
param name string

@description('Location for the Key Vault')
param location string = resourceGroup().location

@description('Tags for the resource')
param tags object = {}

@description('Principal IDs that need Key Vault Secrets User access (e.g., container app managed identities)')
param secretReaderPrincipalIds array = []

// ── Secrets to store ────────────────────────────────────────────────────
// Each is optional — only stored if a non-empty value is provided.

@secure()
@description('Neo4j database password')
param neo4jPassword string = ''

@secure()
@description('Voyage AI API key for embeddings')
param voyageApiKey string = ''

@secure()
@description('Mistral AI API key for OCR')
param mistralApiKey string = ''

@secure()
@description('LLMWhisperer API key for OCR')
param llmwhispererApiKey string = ''

@secure()
@description('Neo4j Aura DS client secret for GDS')
param auraDsClientSecret string = ''

@secure()
@description('Azure AD client secret for EasyAuth token refresh')
param authClientSecret string = ''

@secure()
@description('External ID (B2C) client secret')
param b2cClientSecret string = ''

@secure()
@description('Admin API key for version management')
param adminApiKey string = ''

// ── Key Vault resource ──────────────────────────────────────────────────

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
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
    enabledForTemplateDeployment: true
  }
}

// ── Store secrets ───────────────────────────────────────────────────────

resource neo4jPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(neo4jPassword)) {
  parent: keyVault
  name: 'neo4j-password'
  properties: { value: neo4jPassword }
}

resource voyageApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(voyageApiKey)) {
  parent: keyVault
  name: 'voyage-api-key'
  properties: { value: voyageApiKey }
}

resource mistralApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(mistralApiKey)) {
  parent: keyVault
  name: 'mistral-api-key'
  properties: { value: mistralApiKey }
}

resource llmwhispererApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(llmwhispererApiKey)) {
  parent: keyVault
  name: 'llmwhisperer-api-key'
  properties: { value: llmwhispererApiKey }
}

resource auraDsClientSecretSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(auraDsClientSecret)) {
  parent: keyVault
  name: 'aura-ds-client-secret'
  properties: { value: auraDsClientSecret }
}

resource authClientSecretSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(authClientSecret)) {
  parent: keyVault
  name: 'aad-client-secret'
  properties: { value: authClientSecret }
}

resource b2cClientSecretSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(b2cClientSecret)) {
  parent: keyVault
  name: 'b2c-client-secret'
  properties: { value: b2cClientSecret }
}

resource adminApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(adminApiKey)) {
  parent: keyVault
  name: 'admin-api-key'
  properties: { value: adminApiKey }
}

// ── RBAC: Key Vault Secrets User (4633458b-17de-408a-b874-0445c86b69e6) ─

resource kvSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in secretReaderPrincipalIds: {
  name: guid(keyVault.id, principalId, 'kvSecretsUser-${i}')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// ── Outputs ─────────────────────────────────────────────────────────────

output vaultUri string = keyVault.properties.vaultUri
output vaultName string = keyVault.name
output vaultId string = keyVault.id
