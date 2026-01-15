// Azure OpenAI Model Deployments for GraphRAG Lean Engine Architecture
param openAiResourceName string
param location string = resourceGroup().location

// Reference existing Azure OpenAI resource
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAiResourceName
}

// GPT-4.1 - Indexing & Query Decomposition (Data Zone Standard for EU compliance + 1M context)
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

// GPT-5.1 - Hybrid NER, Intermediate Processing & Synthesis (Data Zone Standard in Sweden Central)
resource gpt51Deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'gpt-5.1'
  sku: {
    name: 'DataZoneStandard'
    capacity: 100
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.1'
      version: '2025-11-13'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [gpt41Deployment]
}

// GPT-4o-mini - Hybrid Router Classification (Standard SKU in Sweden Central)
resource gpt4oMiniDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'gpt-4o-mini'
  sku: {
    name: 'Standard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [gpt51Deployment]
}

// NOTE: text-embedding-3-small is deprecated and should NOT be deployed
// NOTE: text-embedding-3-large already deployed with Standard SKU - no need to redeploy
// Only deploying the 3 essential LLM models: gpt-4.1, gpt-4o, gpt-4o-mini

output gpt41DeploymentName string = gpt41Deployment.name
output gpt51DeploymentName string = gpt51Deployment.name
output gpt4oMiniDeploymentName string = gpt4oMiniDeployment.name
