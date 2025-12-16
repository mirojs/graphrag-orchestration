param documentIntelligenceName string
param storageAccountName string
param containerRegistryName string
param containerAppPrincipalId string
param azureOpenAiName string

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

// Cognitive Services User role on Document Intelligence
resource cognitiveServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(documentIntelligence.id, containerAppPrincipalId, 'cognitiveServicesUser-v2')
  scope: documentIntelligence
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Storage Blob Data Reader role on Storage Account
resource storageBlobDataReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, containerAppPrincipalId, 'storageBlobReader-v2')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// AcrPull role on Container Registry
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, containerAppPrincipalId, 'acrPull-v2')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Cognitive Services OpenAI User role on Azure OpenAI
resource azureOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(azureOpenAi.id, containerAppPrincipalId, 'openaiUser-v2')
  scope: azureOpenAi
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}
