// Azure OpenAI Model Deployments for GraphRAG Lean Engine Architecture
param openAiResourceName string
param location string = resourceGroup().location

// Reference existing Azure OpenAI resource
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAiResourceName
}

// GPT-4.1 - Indexing & RAPTOR (Data Zone Standard for EU compliance + 1M context)
resource gpt41Deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'gpt-4.1'
  sku: {
    name: 'DataZoneStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1'
      version: '2025-01-15'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

// o4-mini - Query Routing (Data Zone Standard, 60% cheaper than o1-mini)
resource o4miniDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'o4-mini'
  sku: {
    name: 'DataZoneStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'o4-mini'
      version: '2025-10-01'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [gpt41Deployment] // Sequential deployment to avoid quota conflicts
}

// o3-pro - Answer Synthesis (Global Standard for high-end reasoning)
resource o3proDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'o3-pro'
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'o3-pro'
      version: '2025-12-01'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [o4miniDeployment]
}

// text-embedding-3-small - Embeddings (Standard, 1536 dims for cost optimization)
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
      version: '2024-09-15'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [o3proDeployment]
}

output gpt41DeploymentName string = gpt41Deployment.name
output o4miniDeploymentName string = o4miniDeployment.name
output o3proDeploymentName string = o3proDeployment.name
output embeddingDeploymentName string = embeddingDeployment.name
