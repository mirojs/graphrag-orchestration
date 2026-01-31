param documentIntelligenceName string
param storageAccountName string
param containerRegistryName string
param containerAppPrincipalIds array  // Array of principal IDs for multiple container apps
param azureOpenAiName string
param cosmosAccountName string

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

// Storage Blob Data Reader role on Storage Account (for each principal)
resource storageBlobDataReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (principalId, i) in containerAppPrincipalIds: {
  name: guid(storageAccount.id, principalId, 'storageBlobReader-v3-${i}')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
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
