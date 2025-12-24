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
      version: '2025-04-14'
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
      version: '2025-04-16'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [gpt41Deployment]
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
      version: '2025-06-10'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [o4miniDeployment]
}

// GPT-5.2 - Primary synthesis model (Low latency, 128k context)
resource gpt52Deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'gpt-5-2'
  sku: {
    name: 'GlobalStandard'
    capacity: 100
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.2'
      version: '2025-12-10'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [o3proDeployment]
}

// text-embedding-3-small - Embeddings (Sweden Central backup)
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
  dependsOn: [gpt52Deployment]
}

output gpt41DeploymentName string = gpt41Deployment.name
output o4miniDeploymentName string = o4miniDeployment.name
output o3proDeploymentName string = o3proDeployment.name
output gpt52DeploymentName string = gpt52Deployment.name
output embeddingDeploymentName string = embeddingDeployment.name
