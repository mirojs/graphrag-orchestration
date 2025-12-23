// Azure OpenAI Resource and Embedding Model Deployment for Switzerland North
param openAiResourceName string = 'graphrag-openai-switzerland'
param location string = 'switzerlandnorth'

// Create new Azure OpenAI resource in Switzerland North
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: openAiResourceName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: openAiResourceName
    publicNetworkAccess: 'Enabled'
  }
}

// text-embedding-3-small - Embeddings (Standard SKU)
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'text-embedding-3-small'
  sku: {
    name: 'Standard'
    capacity: 100
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

output openAiResourceName string = openAiAccount.name
output openAiEndpoint string = openAiAccount.properties.endpoint
output embeddingDeploymentName string = embeddingDeployment.name
