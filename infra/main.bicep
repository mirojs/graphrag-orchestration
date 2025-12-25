targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (e.g., dev, prod)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

// CRITICAL: Ensure we never accidentally deploy hello-world images
// This must point to the actual GraphRAG application image
@description('MUST use drift-mini-optimized or later - NEVER use placeholder/hello-world images')
var requiredImageTag = 'latest'

@secure()
@description('Neo4j Password')
param neo4jPassword string

@description('Azure Document Intelligence Endpoint')
param azureDocumentIntelligenceEndpoint string = 'https://doc-intel-graphrag.cognitiveservices.azure.com/'

@description('Azure AI Search Endpoint')
param azureSearchEndpoint string = 'https://graphrag-search.search.windows.net'

// Tags for all resources
var tags = {
  azd_env_name: environmentName
  app: 'graphrag-orchestration'
}

// Reference existing Resource Group in Sweden Central
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: 'rg-graphrag-feature'
}

// Container Apps Environment - Create with consistent name
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: 'graphrag-env'  // Use fixed name instead of random token
    location: location
    tags: tags
  }
}

// Reference existing Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' existing = {
  name: 'graphragacr12153'
  scope: rg
}

// GraphRAG Orchestration Container App
module graphragApp './core/host/container-app.bicep' = {
  name: 'graphrag-app'
  scope: rg
  params: {
    name: 'graphrag-orchestration'
    location: location
    tags: union(tags, {
      'azd-service-name': 'graphrag'
    })
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    containerRegistryName: containerRegistry.name
    containerName: 'graphrag-orchestration'
    // CRITICAL REQUIREMENT: Must use drift-mini-optimized or later
    // NEVER allow placeholder hello-world images to sneak back in
    containerImage: '${containerRegistry.name}.azurecr.io/graphrag-orchestration:${requiredImageTag}'
    targetPort: 8000
    env: concat([
      {
        name: 'AZURE_OPENAI_ENDPOINT'
        value: 'https://graphrag-openai-8476.openai.azure.com/'
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_ENDPOINT'
        value: 'https://graphrag-openai-switzerland.openai.azure.com/'
      }
      {
        name: 'AZURE_TENANT_ID'
        value: subscription().tenantId
      }
    ], [
      {
        name: 'PORT'
        value: '8000'
      }
      {
        name: 'AZURE_OPENAI_DEPLOYMENT_NAME'
        value: 'gpt-5-2'
      }
      {
        name: 'AZURE_OPENAI_ROUTING_DEPLOYMENT'
        value: 'o4-mini'
      }
      {
        name: 'AZURE_OPENAI_INDEXING_DEPLOYMENT'
        value: 'gpt-4.1'
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT'
        value: 'text-embedding-3-small'
      }
      {
        name: 'AZURE_OPENAI_EMBEDDING_DIMENSIONS'
        value: '1536'
      }
      {
        name: 'AZURE_OPENAI_REASONING_EFFORT'
        value: 'high'
      }
      {
        name: 'AZURE_OPENAI_ROUTING_REASONING_EFFORT'
        value: 'medium'
      }
      {
        name: 'AZURE_OPENAI_API_VERSION'
        value: '2024-10-21'
      }
      {
        name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT'
        value: azureDocumentIntelligenceEndpoint
      }
      {
        name: 'AZURE_SEARCH_ENDPOINT'
        value: azureSearchEndpoint
      }
      {
        name: 'AZURE_SEARCH_INDEX_NAME'
        value: 'graphrag-raptor'
      }
      {
        name: 'VECTOR_STORE_TYPE'
        value: 'azure_search'
      }
      {
        name: 'NEO4J_URI'
        value: 'neo4j+s://a86dcf63.databases.neo4j.io'
      }
      {
        name: 'NEO4J_USERNAME'
        value: 'neo4j'
      }
      {
        name: 'NEO4J_PASSWORD'
        secretRef: 'neo4j-password'
      }
      {
        name: 'NEO4J_DATABASE'
        value: 'neo4j'
      }
      {
        name: 'ENABLE_GROUP_ISOLATION'
        value: 'true'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_SELECTION'
        value: 'true'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_MAX_DEPTH'
        value: '2'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_CANDIDATE_BUDGET'
        value: '30'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_KEEP_PER_LEVEL'
        value: '12'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_SCORE_THRESHOLD'
        value: '25'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_RATING_BATCH_SIZE'
        value: '8'
      }
      {
        name: 'V3_GLOBAL_DYNAMIC_BUILD_HIERARCHY_ON_QUERY'
        value: 'true'
      }
    ])
    secrets: [
      {
        name: 'neo4j-password'
        value: neo4jPassword
      }
    ]
  }
}

// Deploy Azure OpenAI Models (Lean Engine Architecture)
module openAiModels './core/ai/openai-models.bicep' = {
  name: 'openai-models'
  scope: rg
  params: {
    openAiResourceName: 'graphrag-openai-8476'
    location: location
  }
}

// Role Assignments for Container App Managed Identity
module roleAssignments './core/security/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: rg
  params: {
    documentIntelligenceName: 'doc-intel-graphrag'
    storageAccountName: 'neo4jstorage21224'
    containerRegistryName: containerRegistry.name
    containerAppPrincipalId: graphragApp.outputs.identityPrincipalId
    azureOpenAiName: 'graphrag-openai-8476'
    azureSearchName: 'graphrag-search'
  }
  dependsOn: [openAiModels] // Ensure models exist before assigning permissions
}

// Outputs
output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = '${containerRegistry.name}.azurecr.io'
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.name
output GRAPHRAG_APP_URI string = graphragApp.outputs.uri
output GRAPHRAG_APP_NAME string = graphragApp.outputs.name
