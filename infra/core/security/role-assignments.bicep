param documentIntelligenceName string
param storageAccountName string
param containerRegistryName string
param containerAppPrincipalIds array  // Array of principal IDs for multiple container apps
param azureOpenAiName string
param cosmosAccountName string

@description('Name of the ADLS Gen2 user storage account (empty = skip user storage roles)')
param userStorageAccountName string = ''

// Reference existing Document Intelligence resource
resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: documentIntelligenceName
}

// Reference existing Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

// Reference Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' existing = {
  name: containerRegistryName
}

// Reference Azure OpenAI resource
resource azureOpenAi 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: azureOpenAiName
}

// Reference Cosmos DB account
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosAccountName
}

// Cognitive Services User role on Document Intelligence (for each principal)
resource cognitiveServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in containerAppPrincipalIds: {
  name: guid(documentIntelligence.id, principalId, 'cognitiveServicesUser-v3-${i}')
  scope: documentIntelligence
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// Storage Blob Data Contributor role on Storage Account (for each principal)
// Apps need write access for user uploads and content management
resource storageBlobDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in containerAppPrincipalIds: {
  name: guid(storageAccount.id, principalId, 'storageBlobContributor-v4-${i}')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// AcrPull role on Container Registry (for each principal)
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in containerAppPrincipalIds: {
  name: guid(containerRegistry.id, principalId, 'acrPull-v3-${i}')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// Cognitive Services OpenAI User role on Azure OpenAI (for each principal)
resource azureOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in containerAppPrincipalIds: {
  name: guid(azureOpenAi.id, principalId, 'openaiUser-v3-${i}')
  scope: azureOpenAi
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// Cosmos DB Data Contributor role on Cosmos DB (for each principal)
resource cosmosDataContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in containerAppPrincipalIds: {
  name: guid(cosmosAccount.id, principalId, 'cosmosDataContributor-v2-${i}')
  scope: cosmosAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// Reference existing ADLS Gen2 user storage account (optional)
resource userStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = if (!empty(userStorageAccountName)) {
  name: userStorageAccountName
}

// Storage Blob Data Owner role on user storage (for each principal)
// Required for ADLS Gen2 file operations: upload, delete, rename, move, ACL management
resource userStorageBlobDataOwnerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in containerAppPrincipalIds: if (!empty(userStorageAccountName)) {
  name: guid(userStorageAccount.id, principalId, 'storageBlobDataOwner-${i}')
  scope: userStorageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]
